from __future__ import annotations

import json
import os
import shutil
import sqlite3
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from sqlalchemy import func, select

from archive_workbench.db import (
    create_sqlite_engine,
    database_path,
    require_current_database,
    session_scope,
)
from archive_workbench.db.models import (
    ArchivalUnit,
    AuthorityRecord,
    DigitalObject,
    FileInstance,
    Project,
)
from archive_workbench.exchange import (
    create_exchange_checkpoint,
    current_editable_state_sha256,
    exchange_status,
    fork_exchange_workspace,
)
from archive_workbench.identity import new_id, sha256_file, short_id, slugify
from archive_workbench.project_init import initialize_project
from archive_workbench.version import __version__


TEAM_COPY_FORMAT = "archive-workbench-team-copy-v1"
TEAM_COPY_MARKER = Path("exchange") / "team_copy.json"
TEAM_COPY_MANIFEST = "TEAM_COPY_MANIFEST.json"
TEAM_COPY_README = "LEER_PRIMERO_COPIA_DE_TRABAJO.txt"

TEAM_COPY_GROUP_LABELS: dict[str, str] = {
    "originals": "Documentos originales",
    "derivatives": "Imágenes y derivados de consulta",
    "extraction": "Resultados y archivos de extracción",
    "transcripts": "Transcripciones y materiales audiovisuales derivados",
    "indexes": "Índices de búsqueda",
    "exports": "Exportaciones previas",
    "evaluation": "Materiales de evaluación y verdad terreno",
    "other": "Otros archivos auxiliares del proyecto",
}
TEAM_COPY_PRESETS: dict[str, tuple[str, ...]] = {
    "complete": tuple(TEAM_COPY_GROUP_LABELS),
    "review": ("derivatives", "extraction", "transcripts"),
}

_EXCLUDED_TOP_LEVEL = {"backups", "logs", "exchange"}
_EXCLUDED_DB_NAMES = {
    "archive_workbench.sqlite3",
    "archive_workbench.sqlite3-wal",
    "archive_workbench.sqlite3-shm",
}


@dataclass(frozen=True, slots=True)
class TeamCopyContentGroupSummary:
    key: str
    label: str
    file_count: int
    byte_size: int
    included: bool


@dataclass(frozen=True, slots=True)
class TeamCopyPlan:
    profile_name: str
    included_groups: tuple[str, ...]
    omitted_groups: tuple[str, ...]
    group_summaries: tuple[TeamCopyContentGroupSummary, ...]
    core_file_count: int
    core_byte_size: int
    selected_file_count: int
    selected_byte_size: int
    database_estimated_byte_size: int
    estimated_total_byte_size: int


@dataclass(slots=True)
class TeamCopyPackageSummary:
    package_id: str
    output_path: Path
    package_sha256: str
    byte_size: int
    file_count: int
    project_id: str
    project_name: str
    source_workspace_id: str
    source_workspace_name: str
    base_checkpoint_id: str
    base_checkpoint_label: str
    base_state_sha256: str
    content_profile: str
    included_content_groups: tuple[str, ...]
    omitted_content_groups: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TeamCopyPackageInspection:
    path: Path
    package_id: str
    project_id: str
    project_name: str
    base_checkpoint_label: str
    base_state_sha256: str
    content_profile: str
    included_content_groups: tuple[str, ...]
    omitted_content_groups: tuple[str, ...]
    project_folder: str


@dataclass(slots=True)
class TeamCopyActivationSummary:
    package_id: str
    previous_workspace_id: str
    previous_workspace_name: str
    workspace_id: str
    workspace_name: str
    checkpoint_label: str
    state_sha256: str
    omitted_content_groups: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class TeamCopyTargetAssessment:
    project_id: str
    project_name: str
    archival_unit_count: int
    digital_object_count: int
    authority_count: int

    @property
    def is_empty(self) -> bool:
        return not (
            self.archival_unit_count
            or self.digital_object_count
            or self.authority_count
        )


@dataclass(frozen=True, slots=True)
class TeamCopyAdoptionSummary:
    package_id: str
    project_id: str
    project_name: str
    workspace_id: str
    workspace_name: str
    checkpoint_label: str
    backup_path: Path
    backup_sha256: str
    omitted_content_groups: tuple[str, ...]


def _canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _marker_path(project_root: Path) -> Path:
    return project_root.resolve() / TEAM_COPY_MARKER


def _snapshot_sqlite(source: Path, destination: Path) -> None:
    source_connection = sqlite3.connect(source)
    target_connection = sqlite3.connect(destination)
    try:
        source_connection.backup(target_connection)
    finally:
        target_connection.close()
        source_connection.close()
    connection = sqlite3.connect(destination)
    try:
        result = connection.execute("PRAGMA quick_check").fetchone()
    finally:
        connection.close()
    if not result or str(result[0]).lower() != "ok":
        raise ValueError("La copia SQLite no superó quick_check")


def _normalize_groups(groups: Iterable[str] | None) -> tuple[str, ...]:
    if groups is None:
        return TEAM_COPY_PRESETS["complete"]
    requested = {str(item).strip() for item in groups if str(item).strip()}
    unknown = requested.difference(TEAM_COPY_GROUP_LABELS)
    if unknown:
        raise ValueError(
            "La configuración de la copia contiene grupos desconocidos: "
            + ", ".join(sorted(unknown))
        )
    return tuple(key for key in TEAM_COPY_GROUP_LABELS if key in requested)


def _registered_original_paths(project_root: Path) -> set[str]:
    engine = create_sqlite_engine(database_path(project_root))
    try:
        with session_scope(engine) as session:
            rows = session.scalars(
                select(FileInstance).where(FileInstance.storage_root == "project")
            ).all()
            return {
                Path(row.relative_path).as_posix().lstrip("./")
                for row in rows
                if str(row.relative_path).strip()
            }
    finally:
        engine.dispose()


def _classify_project_file(relative: Path, original_paths: set[str]) -> str:
    rel = relative.as_posix()
    if rel in original_paths:
        return "originals"
    top = relative.parts[0] if relative.parts else ""
    if top == "config":
        return "core"
    if top in {"data", "corpus"}:
        return "originals"
    if top in {"derivatives", "region_previews"}:
        return "derivatives"
    if top == "extraction":
        return "extraction"
    if top == "transcripts":
        return "transcripts"
    if top == "indexes":
        return "indexes"
    if top == "exports":
        return "exports"
    if top in {"ocr_benchmarks", "ground_truth"}:
        return "evaluation"
    return "other"


def _all_copy_candidates(project_root: Path) -> tuple[list[tuple[Path, str]], set[str]]:
    root = project_root.resolve()
    original_paths = _registered_original_paths(root)
    rows: list[tuple[Path, str]] = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError(
                "La carpeta del proyecto contiene enlaces simbólicos. "
                "Archive Workbench no los incluye automáticamente en una copia para compartir."
            )
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if relative.parts and relative.parts[0] in _EXCLUDED_TOP_LEVEL:
            continue
        if relative.as_posix() in {TEAM_COPY_MANIFEST, TEAM_COPY_README}:
            continue
        if relative.parts[:1] == ("data",) and path.name in _EXCLUDED_DB_NAMES:
            continue
        rows.append((path, _classify_project_file(relative, original_paths)))
    return rows, original_paths


def _database_estimated_size(source_db: Path) -> int:
    total = source_db.stat().st_size if source_db.is_file() else 0
    wal = Path(str(source_db) + "-wal")
    if wal.is_file():
        total += wal.stat().st_size
    return total


def plan_team_copy(
    *,
    project_root: Path,
    included_groups: Iterable[str] | None = None,
    profile_name: str = "complete",
) -> TeamCopyPlan:
    """Calcula qué viajará en una copia sin escribir checkpoints ni archivos."""

    root = project_root.resolve()
    source_db = database_path(root)
    if not source_db.is_file():
        raise ValueError("No existe la base SQLite del proyecto")
    selected_groups = _normalize_groups(included_groups)
    selected_set = set(selected_groups)
    candidates, _ = _all_copy_candidates(root)

    grouped: dict[str, list[Path]] = {key: [] for key in TEAM_COPY_GROUP_LABELS}
    core: list[Path] = []
    for path, group in candidates:
        if group == "core":
            core.append(path)
        else:
            grouped[group].append(path)

    summaries: list[TeamCopyContentGroupSummary] = []
    selected_files = list(core)
    for key, label in TEAM_COPY_GROUP_LABELS.items():
        paths = grouped[key]
        byte_size = sum(path.stat().st_size for path in paths)
        included = key in selected_set
        summaries.append(
            TeamCopyContentGroupSummary(
                key=key,
                label=label,
                file_count=len(paths),
                byte_size=byte_size,
                included=included,
            )
        )
        if included:
            selected_files.extend(paths)

    core_bytes = sum(path.stat().st_size for path in core)
    selected_bytes = sum(path.stat().st_size for path in selected_files)
    database_estimate = _database_estimated_size(source_db)
    return TeamCopyPlan(
        profile_name=profile_name,
        included_groups=selected_groups,
        omitted_groups=tuple(
            key for key in TEAM_COPY_GROUP_LABELS if key not in selected_set
        ),
        group_summaries=tuple(summaries),
        core_file_count=len(core),
        core_byte_size=core_bytes,
        selected_file_count=len(selected_files),
        selected_byte_size=selected_bytes,
        database_estimated_byte_size=database_estimate,
        estimated_total_byte_size=selected_bytes + database_estimate,
    )


def _project_files_for_copy(
    project_root: Path,
    *,
    included_groups: Iterable[str] | None = None,
) -> tuple[list[Path], TeamCopyPlan]:
    selected_groups = _normalize_groups(included_groups)
    plan = plan_team_copy(
        project_root=project_root,
        included_groups=selected_groups,
        profile_name="custom",
    )
    selected_set = set(selected_groups)
    candidates, _ = _all_copy_candidates(project_root)
    rows = [
        path
        for path, group in candidates
        if group == "core" or group in selected_set
    ]
    return rows, plan


def inspect_team_copy_package(path: Path) -> TeamCopyPackageInspection:
    source = path.expanduser().resolve()
    if not source.is_file():
        raise ValueError(f"No existe la copia de trabajo: {source}")
    try:
        with zipfile.ZipFile(source, "r") as archive:
            names = archive.namelist()
            unsafe = [
                name
                for name in names
                if Path(name).is_absolute() or ".." in Path(name).parts
            ]
            if unsafe:
                raise ValueError("La copia de trabajo contiene rutas inseguras")
            manifests = [
                name for name in names if Path(name).name == TEAM_COPY_MANIFEST
            ]
            if len(manifests) != 1:
                raise ValueError(
                    "El ZIP no contiene un manifiesto único de copia de trabajo"
                )
            manifest_name = manifests[0]
            project_folder = str(Path(manifest_name).parent.as_posix())
            marker_name = f"{project_folder}/{TEAM_COPY_MARKER.as_posix()}"
            db_name = f"{project_folder}/data/archive_workbench.sqlite3"
            if marker_name not in names or db_name not in names:
                raise ValueError(
                    "La copia de trabajo no contiene su marca o su base SQLite"
                )
            broken = archive.testzip()
            if broken is not None:
                raise ValueError(
                    f"La copia de trabajo contiene un archivo ZIP dañado: {broken}"
                )
            try:
                manifest = json.loads(archive.read(manifest_name).decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError(
                    "No se pudo leer el manifiesto de la copia de trabajo"
                ) from exc
    except zipfile.BadZipFile as exc:
        raise ValueError("El archivo elegido no es un ZIP válido") from exc

    if manifest.get("format") != TEAM_COPY_FORMAT:
        raise ValueError("El ZIP no corresponde a una copia de trabajo compatible")
    package_id = str(manifest.get("package_id") or "").strip()
    project_id = str(manifest.get("project_id") or "").strip()
    project_name = str(manifest.get("project_name") or "").strip()
    if not package_id or not project_id:
        raise ValueError("El manifiesto de la copia de trabajo está incompleto")
    included = tuple(
        str(item)
        for item in manifest.get("included_content_groups", TEAM_COPY_PRESETS["complete"])
        if str(item) in TEAM_COPY_GROUP_LABELS
    )
    omitted = tuple(
        str(item)
        for item in manifest.get("omitted_content_groups", ())
        if str(item) in TEAM_COPY_GROUP_LABELS
    )
    return TeamCopyPackageInspection(
        path=source,
        package_id=package_id,
        project_id=project_id,
        project_name=project_name,
        base_checkpoint_label=str(manifest.get("base_checkpoint_label") or ""),
        base_state_sha256=str(manifest.get("base_state_sha256") or ""),
        content_profile=str(manifest.get("content_profile") or "complete"),
        included_content_groups=included,
        omitted_content_groups=omitted,
        project_folder=project_folder,
    )


def create_team_copy_package(
    *,
    project_root: Path,
    created_by: str,
    output_path: Path | None = None,
    included_groups: Iterable[str] | None = None,
    content_profile: str = "complete",
) -> TeamCopyPackageSummary:
    """Crea una copia reutilizable como origen de varias copias de trabajo.

    SQLite y la configuración son siempre obligatorias. Los demás grupos pueden omitirse
    deliberadamente para reducir tamaño; el manifiesto conserva esa decisión para que una
    copia receptora distinga una ausencia intencional de un archivo perdido.
    """

    root = project_root.resolve()
    source_db = database_path(root)
    if not source_db.is_file():
        raise ValueError("No existe la base SQLite del proyecto")
    actor = created_by.strip()
    if not actor:
        raise ValueError("Indicá quién prepara la copia de trabajo")
    selected_groups = _normalize_groups(included_groups)

    package_id = new_id()
    base_label = f"team_base_{short_id(package_id)}"
    engine = create_sqlite_engine(source_db)
    try:
        with session_scope(engine) as session:
            project = session.scalar(select(Project).order_by(Project.created_at))
            if project is None:
                raise ValueError("El proyecto no está registrado en la base")
            checkpoint = create_exchange_checkpoint(
                session,
                label=base_label,
                created_by=actor,
                note=(
                    "Punto de partida creado al preparar una copia de trabajo compartible. "
                    "El mismo ZIP puede entregarse a varias personas."
                ),
            )
            workspace = exchange_status(session)
            project_id = project.id
            project_name = project.name
            base_checkpoint_id = checkpoint.id
            base_state_sha256 = checkpoint.state_sha256
            source_workspace_id = workspace.workspace_id
            source_workspace_name = workspace.workspace_name
    finally:
        engine.dispose()

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    if output_path is None:
        output_path = (
            root
            / "exchange"
            / "outgoing"
            / f"{stamp}_copia_trabajo_{short_id(package_id)}.zip"
        )
    destination = output_path.expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise ValueError(f"Ya existe el archivo de salida: {destination}")

    project_folder = f"{slugify(project_name, 50) or slugify(root.name, 50) or 'proyecto'}_copia"
    created_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    files, planned = _project_files_for_copy(
        root,
        included_groups=selected_groups,
    )
    omitted_groups = tuple(
        key for key in TEAM_COPY_GROUP_LABELS if key not in set(selected_groups)
    )
    marker = {
        "format": TEAM_COPY_FORMAT,
        "package_id": package_id,
        "status": "pending_first_open",
        "project_id": project_id,
        "project_name": project_name,
        "source_workspace_id": source_workspace_id,
        "source_workspace_name": source_workspace_name,
        "base_checkpoint_label": base_label,
        "base_state_sha256": base_state_sha256,
        "created_by": actor,
        "created_at": created_at,
        "multi_recipient": True,
        "content_profile": content_profile,
        "included_content_groups": list(selected_groups),
        "omitted_content_groups": list(omitted_groups),
    }

    with tempfile.TemporaryDirectory(prefix="archive_workbench_team_copy_") as tmp_name:
        snapshot_db = Path(tmp_name) / "archive_workbench.sqlite3"
        _snapshot_sqlite(source_db, snapshot_db)
        manifest = {
            **marker,
            "app_version": __version__,
            "database_sha256": sha256_file(snapshot_db),
            "project_file_count": len(files),
            "excluded_top_level": sorted(_EXCLUDED_TOP_LEVEL),
            "content_group_stats": {
                row.key: {
                    "label": row.label,
                    "file_count": row.file_count,
                    "byte_size": row.byte_size,
                    "included": row.included,
                }
                for row in planned.group_summaries
            },
        }
        omitted_labels = [TEAM_COPY_GROUP_LABELS[key] for key in omitted_groups]
        readme_lines = [
            "Archive Workbench - copia de trabajo compartible",
            "",
            "Extraiga esta carpeta en el equipo receptor y ábrala normalmente con Archive Workbench. La primera apertura asignará automáticamente una identidad propia a esa copia sin modificar el trabajo editable.",
            "",
            "El mismo ZIP puede entregarse a varias personas. Cada extracción recibirá una identidad diferente al abrirse por primera vez y todas conservarán el mismo punto de partida para intercambiar cambios.",
        ]
        if omitted_labels:
            readme_lines.extend(
                [
                    "",
                    "Esta copia fue preparada deliberadamente sin algunos grupos de archivos:",
                    *[f"- {label}" for label in omitted_labels],
                    "La ausencia de esos grupos está registrada en el manifiesto y no significa que se hayan perdido del proyecto de origen.",
                ]
            )
        readme = ("\n".join(readme_lines) + "\n").encode("utf-8")
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        temporary.unlink(missing_ok=True)
        try:
            with zipfile.ZipFile(
                temporary, "w", compression=zipfile.ZIP_DEFLATED
            ) as archive:
                for source in files:
                    relative = source.relative_to(root).as_posix()
                    archive.write(source, f"{project_folder}/{relative}")
                archive.write(
                    snapshot_db, f"{project_folder}/data/archive_workbench.sqlite3"
                )
                archive.writestr(
                    f"{project_folder}/{TEAM_COPY_MARKER.as_posix()}",
                    _canonical_json_bytes(marker),
                )
                archive.writestr(
                    f"{project_folder}/{TEAM_COPY_MANIFEST}",
                    _canonical_json_bytes(manifest),
                )
                archive.writestr(f"{project_folder}/{TEAM_COPY_README}", readme)
            os.replace(temporary, destination)
        except Exception:
            temporary.unlink(missing_ok=True)
            destination.unlink(missing_ok=True)
            raise

    inspection = inspect_team_copy_package(destination)
    if inspection.package_id != package_id:
        destination.unlink(missing_ok=True)
        raise ValueError("La copia creada no conserva la identidad esperada")

    return TeamCopyPackageSummary(
        package_id=package_id,
        output_path=destination,
        package_sha256=sha256_file(destination),
        byte_size=destination.stat().st_size,
        file_count=len(files) + 4,
        project_id=project_id,
        project_name=project_name,
        source_workspace_id=source_workspace_id,
        source_workspace_name=source_workspace_name,
        base_checkpoint_id=base_checkpoint_id,
        base_checkpoint_label=base_label,
        base_state_sha256=base_state_sha256,
        content_profile=content_profile,
        included_content_groups=selected_groups,
        omitted_content_groups=omitted_groups,
    )


def activate_received_team_copy(
    *,
    project_root: Path,
    created_by: str,
) -> TeamCopyActivationSummary | None:
    """Reidentifica una copia recibida una sola vez, sin pedir una contraparte manual."""

    root = project_root.resolve()
    marker_path = _marker_path(root)
    if not marker_path.is_file():
        return None
    try:
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("No se pudo leer la marca de la copia de trabajo recibida") from exc
    if marker.get("format") != TEAM_COPY_FORMAT:
        raise ValueError("La marca de la copia de trabajo tiene un formato incompatible")
    if marker.get("status") == "activated":
        return None
    if marker.get("status") != "pending_first_open":
        raise ValueError("La copia de trabajo recibida tiene un estado de activación desconocido")

    initialize_project(root, allow_existing=True)
    actor = created_by.strip() or "local_user"
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            project = session.scalar(select(Project).order_by(Project.created_at))
            if project is None:
                raise ValueError("La copia recibida no contiene un proyecto registrado")
            if project.id != marker.get("project_id"):
                raise ValueError("La copia recibida no corresponde al proyecto indicado en su manifiesto")
            observed_state = current_editable_state_sha256(session, project.id)
            expected_state = str(marker.get("base_state_sha256") or "")
            if not expected_state or observed_state != expected_state:
                raise ValueError(
                    "El trabajo editable de la copia recibida ya no coincide con el punto de partida "
                    "con el que fue preparada. No se cambió su identidad."
                )
            local_name = f"copia-{short_id(new_id())}"
            summary = fork_exchange_workspace(
                session,
                workspace_name=local_name,
                created_by=actor,
                checkpoint_label=str(marker.get("base_checkpoint_label") or "team_base"),
            )
    finally:
        engine.dispose()

    marker.update(
        {
            "status": "activated",
            "activated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "activated_by": actor,
            "local_workspace_id": summary.workspace_id,
            "local_workspace_name": summary.workspace_name,
        }
    )
    temporary = marker_path.with_suffix(".json.tmp")
    temporary.write_bytes(_canonical_json_bytes(marker))
    os.replace(temporary, marker_path)

    omitted_groups = tuple(
        str(item)
        for item in marker.get("omitted_content_groups", ())
        if str(item) in TEAM_COPY_GROUP_LABELS
    )
    return TeamCopyActivationSummary(
        package_id=str(marker["package_id"]),
        previous_workspace_id=summary.previous_workspace_id,
        previous_workspace_name=summary.previous_workspace_name,
        workspace_id=summary.workspace_id,
        workspace_name=summary.workspace_name,
        checkpoint_label=summary.checkpoint_label,
        state_sha256=summary.state_sha256,
        omitted_content_groups=omitted_groups,
    )


def assess_team_copy_target(project_root: Path) -> TeamCopyTargetAssessment:
    """Indica si el proyecto abierto aún no contiene trabajo de dominio."""

    root = project_root.expanduser().resolve()
    require_current_database(root)
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            project = session.scalar(select(Project).order_by(Project.created_at))
            if project is None:
                raise ValueError("El proyecto actual no está registrado en SQLite")
            archival_unit_count = int(
                session.scalar(
                    select(func.count(ArchivalUnit.id)).where(
                        ArchivalUnit.project_id == project.id
                    )
                )
                or 0
            )
            digital_object_count = int(
                session.scalar(
                    select(func.count(DigitalObject.id)).where(
                        DigitalObject.project_id == project.id
                    )
                )
                or 0
            )
            authority_count = int(
                session.scalar(
                    select(func.count(AuthorityRecord.id)).where(
                        AuthorityRecord.project_id == project.id
                    )
                )
                or 0
            )
            return TeamCopyTargetAssessment(
                project_id=project.id,
                project_name=project.name,
                archival_unit_count=archival_unit_count,
                digital_object_count=digital_object_count,
                authority_count=authority_count,
            )
    finally:
        engine.dispose()


def _atomic_copy(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".team_copy_tmp")
    temporary.unlink(missing_ok=True)
    try:
        shutil.copy2(source, temporary)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def adopt_team_copy_into_empty_project(
    *,
    project_root: Path,
    package_path: Path,
    adopted_by: str,
    adoption_confirmed: bool,
) -> TeamCopyAdoptionSummary:
    """Carga una copia completa en la carpeta actual cuando el proyecto está vacío.

    La copia se valida y activa primero en una carpeta temporal. El proyecto vacío
    se resguarda antes de sustituir configuración y SQLite. Los directorios locales
    de backups, logs y transporte se conservan.
    """

    if not adoption_confirmed:
        raise ValueError("Confirmá que querés usar la copia recibida en este proyecto")
    actor = adopted_by.strip() or "local_user"
    root = project_root.expanduser().resolve()
    package = package_path.expanduser().resolve()
    inspection = inspect_team_copy_package(package)
    assessment = assess_team_copy_target(root)
    if not assessment.is_empty:
        raise ValueError(
            "El proyecto actual ya contiene trabajo. Para combinar trabajo entre copias, "
            "recibí un paquete de cambios; esta operación sólo reemplaza un proyecto vacío."
        )

    with tempfile.TemporaryDirectory(prefix="archive_workbench_team_copy_adopt_") as tmp_name:
        staging_parent = Path(tmp_name)
        with zipfile.ZipFile(package, "r") as archive:
            # inspect_team_copy_package ya rechazó rutas inseguras y comprobó el ZIP.
            archive.extractall(staging_parent)
        staged_root = staging_parent / inspection.project_folder
        staged_config = staged_root / "config" / "decisions.yaml"
        staged_db = database_path(staged_root)
        if not staged_config.is_file() or not staged_db.is_file():
            raise ValueError(
                "La copia recibida no contiene la configuración y la base necesarias para abrir el proyecto"
            )
        require_current_database(staged_root)
        activation = activate_received_team_copy(
            project_root=staged_root,
            created_by=actor,
        )
        if activation is None:
            raise ValueError(
                "La copia recibida ya figura como activada y no puede usarse como copia inicial reutilizable"
            )

        from archive_workbench.project_admin import create_project_backup

        backup = create_project_backup(
            project_root=root,
            created_by=actor,
            note=f"Antes de cargar la copia de trabajo {inspection.package_id}",
        )

        staged_files = [path for path in staged_root.rglob("*") if path.is_file()]
        critical_config: list[tuple[Path, Path]] = []
        staged_database: tuple[Path, Path] | None = None
        regular_files: list[tuple[Path, Path]] = []
        for source in staged_files:
            relative = source.relative_to(staged_root)
            if relative.parts and relative.parts[0] in {"backups", "logs"}:
                continue
            if relative.parts and relative.parts[0] == "exchange" and relative != TEAM_COPY_MARKER:
                continue
            target = root / relative
            if relative == Path("data/archive_workbench.sqlite3"):
                staged_database = (source, target)
            elif relative.parts and relative.parts[0] == "config":
                critical_config.append((source, target))
            else:
                regular_files.append((source, target))
        if staged_database is None:
            raise ValueError("La copia recibida no contiene su base SQLite")

        conflicting_regular = [target for _source, target in regular_files if target.exists()]
        if conflicting_regular:
            relative_conflicts = ", ".join(
                str(path.relative_to(root)) for path in conflicting_regular[:3]
            )
            raise ValueError(
                "El proyecto vacío contiene archivos locales que coinciden con la copia recibida "
                f"({relative_conflicts}). No se sobrescribieron esos archivos."
            )

        created_regular: list[Path] = []
        original_config: dict[Path, bytes | None] = {}
        try:
            for source, target in regular_files:
                existed = target.exists()
                _atomic_copy(source, target)
                if not existed:
                    created_regular.append(target)

            for source, target in critical_config:
                original_config[target] = target.read_bytes() if target.is_file() else None
                _atomic_copy(source, target)

            source_db, target_db = staged_database
            for suffix in ("-wal", "-shm"):
                companion = Path(str(target_db) + suffix)
                companion.unlink(missing_ok=True)
            _atomic_copy(source_db, target_db)
        except Exception:
            for target, original in original_config.items():
                if original is None:
                    target.unlink(missing_ok=True)
                else:
                    temporary = target.with_name(target.name + ".team_copy_rollback")
                    temporary.write_bytes(original)
                    os.replace(temporary, target)
            for target in reversed(created_regular):
                target.unlink(missing_ok=True)
            raise

    return TeamCopyAdoptionSummary(
        package_id=inspection.package_id,
        project_id=inspection.project_id,
        project_name=inspection.project_name,
        workspace_id=activation.workspace_id,
        workspace_name=activation.workspace_name,
        checkpoint_label=activation.checkpoint_label,
        backup_path=backup.path,
        backup_sha256=backup.backup_sha256,
        omitted_content_groups=activation.omitted_content_groups,
    )
