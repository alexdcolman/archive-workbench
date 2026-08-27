from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
import zipfile

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from archive_workbench.db.migrations import current_revision
from archive_workbench.db.models import (
    CorpusExportRun,
    DigitalObject,
    EditableObject,
    EntityMention,
    EntityRelation,
    FileInstance,
    Project,
    SemanticSearchProfile,
)
from archive_workbench.graph import graph_consistency_issues
from archive_workbench.project_init import PROJECT_DIRS
from archive_workbench.search import search_index_status
from archive_workbench.semantic_search import semantic_index_status
from archive_workbench.team_copy import TEAM_COPY_MARKER
from archive_workbench.version import __version__


BACKUP_FORMAT = "archive-workbench-project-backup-v1"
HEALTH_DISMISSALS_FORMAT = "archive-workbench-project-health-dismissals-v1"
HEALTH_DISMISSALS_RELATIVE_PATH = Path("config") / "project_health_dismissals.json"


@dataclass(slots=True)
class ProjectHealthIssue:
    severity: str
    code: str
    message: str
    detail: str | None = None
    subject_key: str | None = None
    dismissible: bool = False
    entity_id: str | None = None
    relation_id: str | None = None
    mention_id: str | None = None
    archival_unit_id: str | None = None
    semantic_profile_id: str | None = None
    export_run_id: str | None = None
    export_material_type: str | None = None
    resource_path: str | None = None


@dataclass(slots=True)
class ProjectHealthReport:
    checked_at: str
    database_revision: str | None
    issues: list[ProjectHealthIssue]
    dismissed_issues: list[ProjectHealthIssue] = field(default_factory=list)

    @property
    def error_count(self) -> int:
        return sum(item.severity == "error" for item in self.issues)

    @property
    def warning_count(self) -> int:
        return sum(item.severity == "warning" for item in self.issues)

    @property
    def info_count(self) -> int:
        return sum(item.severity == "info" for item in self.issues)


@dataclass(slots=True)
class ProjectBackupInfo:
    path: Path
    backup_sha256: str
    database_sha256: str
    database_revision: str | None
    project_id: str | None
    project_name: str | None
    created_by: str
    created_at: str
    note: str | None
    config_file_count: int


@dataclass(slots=True)
class ProjectRestoreSummary:
    restored_backup: Path
    restored_database_sha256: str
    safety_backup: Path
    safety_backup_sha256: str
    database_revision: str | None




def _health_dismissals_path(project_root: Path) -> Path:
    return project_root.resolve() / HEALTH_DISMISSALS_RELATIVE_PATH


def _read_health_dismissals(project_root: Path) -> dict[str, dict[str, str]]:
    path = _health_dismissals_path(project_root)
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("No se pudo leer la lista de avisos de integridad descartados") from exc
    if payload.get("format") != HEALTH_DISMISSALS_FORMAT:
        raise ValueError("La lista de avisos de integridad descartados tiene un formato incompatible")
    rows = payload.get("dismissals")
    if not isinstance(rows, list):
        raise ValueError("La lista de avisos de integridad descartados es inválida")
    result: dict[str, dict[str, str]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        code = str(row.get("code") or "").strip()
        subject_key = str(row.get("subject_key") or "").strip()
        if not code or not subject_key:
            continue
        result[f"{code}:{subject_key}"] = {
            "code": code,
            "subject_key": subject_key,
            "dismissed_by": str(row.get("dismissed_by") or "local_user"),
            "dismissed_at": str(row.get("dismissed_at") or ""),
        }
    return result


def _write_health_dismissals(project_root: Path, rows: dict[str, dict[str, str]]) -> None:
    path = _health_dismissals_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "format": HEALTH_DISMISSALS_FORMAT,
        "dismissals": sorted(rows.values(), key=lambda row: (row["code"], row["subject_key"])),
    }
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def dismiss_project_health_issue(
    *,
    project_root: Path,
    issue: ProjectHealthIssue,
    dismissed_by: str,
) -> None:
    if not issue.dismissible or not issue.subject_key:
        raise ValueError("Este aviso de integridad no puede descartarse")
    rows = _read_health_dismissals(project_root)
    key = f"{issue.code}:{issue.subject_key}"
    rows[key] = {
        "code": issue.code,
        "subject_key": issue.subject_key,
        "dismissed_by": dismissed_by.strip() or "local_user",
        "dismissed_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }
    _write_health_dismissals(project_root, rows)


def restore_project_health_issue(
    *,
    project_root: Path,
    issue: ProjectHealthIssue,
) -> None:
    if not issue.subject_key:
        return
    rows = _read_health_dismissals(project_root)
    rows.pop(f"{issue.code}:{issue.subject_key}", None)
    _write_health_dismissals(project_root, rows)


def _team_copy_omitted_groups(project_root: Path) -> set[str]:
    marker = project_root.resolve() / TEAM_COPY_MARKER
    if not marker.is_file():
        return set()
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    values = payload.get("omitted_content_groups")
    if not isinstance(values, list):
        return set()
    return {str(value) for value in values if str(value).strip()}


def _filter_dismissed_health_issues(
    project_root: Path, issues: list[ProjectHealthIssue]
) -> tuple[list[ProjectHealthIssue], list[ProjectHealthIssue]]:
    dismissals = _read_health_dismissals(project_root)
    active: list[ProjectHealthIssue] = []
    dismissed: list[ProjectHealthIssue] = []
    for issue in issues:
        key = (
            f"{issue.code}:{issue.subject_key}"
            if issue.dismissible and issue.subject_key
            else None
        )
        if key and key in dismissals:
            dismissed.append(issue)
        else:
            active.append(issue)
    return active, dismissed

def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_zip_members(archive: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    members = archive.infolist()
    for member in members:
        path = Path(member.filename)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError(f"Ruta insegura dentro del backup: {member.filename}")
    return members


def _sqlite_quick_check(path: Path) -> tuple[bool, str]:
    connection = sqlite3.connect(path)
    try:
        row = connection.execute("PRAGMA quick_check").fetchone()
        value = str(row[0]) if row else "sin resultado"
        return value == "ok", value
    finally:
        connection.close()


def check_project_health(
    session: Session,
    *,
    project_root: Path,
) -> ProjectHealthReport:
    root = project_root.resolve()
    issues: list[ProjectHealthIssue] = []
    db_path = root / "data" / "archive_workbench.sqlite3"
    revision = current_revision(root)
    omitted_groups = _team_copy_omitted_groups(root)

    if not db_path.exists():
        issues.append(ProjectHealthIssue("error", "missing_database", "No existe la base SQLite."))
        return ProjectHealthReport(datetime.now(timezone.utc).isoformat(), revision, issues)

    quick = session.execute(text("PRAGMA quick_check")).scalar_one_or_none()
    if quick != "ok":
        issues.append(
            ProjectHealthIssue("error", "sqlite_quick_check", "SQLite informó un problema de integridad.", str(quick))
        )
    foreign_rows = session.execute(text("PRAGMA foreign_key_check")).all()
    if foreign_rows:
        issues.append(
            ProjectHealthIssue(
                "error",
                "foreign_key_check",
                f"Hay {len(foreign_rows)} referencias internas inválidas.",
                repr(foreign_rows[:10]),
            )
        )

    for relative in PROJECT_DIRS:
        if not (root / relative).is_dir():
            issues.append(
                ProjectHealthIssue(
                    "warning",
                    "missing_directory",
                    f"Falta el directorio del proyecto: {relative}",
                    resource_path=relative,
                )
            )

    file_rows = session.execute(
        select(FileInstance, DigitalObject).join(
            DigitalObject, DigitalObject.id == FileInstance.digital_object_id
        )
    ).all()
    for instance, digital in file_rows:
        if "originals" in omitted_groups:
            continue
        if instance.storage_root != "project":
            continue
        path = root / instance.relative_path
        if not path.exists():
            issues.append(
                ProjectHealthIssue(
                    "warning",
                    "missing_local_file",
                    f"No está disponible el archivo local {instance.relative_path}.",
                    f"Objeto digital {digital.id}",
                    resource_path=instance.relative_path,
                )
            )
            continue
        if path.is_file() and path.stat().st_size != digital.byte_size:
            issues.append(
                ProjectHealthIssue(
                    "error",
                    "file_size_mismatch",
                    f"Cambió el tamaño del archivo {instance.relative_path}.",
                    f"Esperado {digital.byte_size}; actual {path.stat().st_size}",
                    resource_path=instance.relative_path,
                )
            )
        if instance.verified_sha256 and instance.verified_sha256 != digital.sha256:
            issues.append(
                ProjectHealthIssue(
                    "error",
                    "registered_hash_mismatch",
                    f"La verificación registrada no coincide con el objeto digital: {instance.relative_path}.",
                    resource_path=instance.relative_path,
                )
            )

    stale_mentions = session.scalar(
        select(func.count())
        .select_from(EntityMention)
        .join(EditableObject, EditableObject.id == EntityMention.editable_object_id)
        .where(EntityMention.object_revision_number != EditableObject.revision_number)
    )
    if stale_mentions:
        issues.append(
            ProjectHealthIssue(
                "warning",
                "stale_mentions",
                f"Hay {int(stale_mentions)} menciones creadas sobre revisiones textuales anteriores.",
            )
        )

    project = session.scalars(select(Project).order_by(Project.created_at)).first()
    if project is not None:
        for graph_issue in graph_consistency_issues(session, project_id=project.id):
            relation = (
                session.get(EntityRelation, graph_issue.relation_id)
                if graph_issue.relation_id
                else None
            )
            issues.append(
                ProjectHealthIssue(
                    graph_issue.severity,
                    f"graph_{graph_issue.code}",
                    graph_issue.message,
                    graph_issue.relation_id or graph_issue.mention_id or graph_issue.entity_id,
                    entity_id=(
                        graph_issue.entity_id
                        or (relation.source_authority_id if relation is not None else None)
                    ),
                    relation_id=graph_issue.relation_id,
                    mention_id=graph_issue.mention_id,
                    archival_unit_id=(
                        relation.target_archival_unit_id if relation is not None else None
                    ),
                )
            )

    try:
        index_state = search_index_status(session)
        if not index_state.is_current:
            issues.append(
                ProjectHealthIssue(
                    "info",
                    "search_index_pending",
                    "Los textos usados por la búsqueda textual están pendientes de actualización.",
                    f"Generación {index_state.indexed_generation} → {index_state.dirty_generation}",
                    subject_key=f"{index_state.indexed_generation}:{index_state.dirty_generation}",
                    dismissible=True,
                )
            )
    except RuntimeError as exc:
        issues.append(ProjectHealthIssue("error", "missing_search_index", str(exc)))

    if project is not None:
        semantic_profiles = session.scalars(
            select(SemanticSearchProfile)
            .where(SemanticSearchProfile.project_id == project.id)
            .order_by(SemanticSearchProfile.name)
        ).all()
        for semantic_profile in semantic_profiles:
            semantic_state = semantic_index_status(
                session,
                project_root=root,
                project_id=project.id,
                profile=semantic_profile,
            )
            if not semantic_state.is_current:
                issues.append(
                    ProjectHealthIssue(
                        "info",
                        "semantic_index_pending",
                        f"La búsqueda semántica con “{semantic_profile.name}” necesita actualizar su índice.",
                        semantic_state.reason,
                        subject_key=(
                            f"{semantic_profile.id}:{semantic_profile.revision}:"
                            f"{semantic_state.current_corpus_state_sha256}:{semantic_state.reason}"
                        ),
                        dismissible=True,
                        semantic_profile_id=semantic_profile.id,
                    )
                )

    exports = session.scalars(select(CorpusExportRun).order_by(CorpusExportRun.created_at)).all()
    if "exports" not in omitted_groups:
        for run in exports:
            output = root / run.output_relative_path
            material_type = str(run.profile_snapshot_json.get("material_type") or "documents")
            if not output.exists():
                issues.append(
                    ProjectHealthIssue(
                        "warning",
                        "missing_export_file",
                        f"Ya no existe el archivo exportado {run.output_relative_path}.",
                        run.id,
                        subject_key=run.id,
                        dismissible=True,
                        export_run_id=run.id,
                        export_material_type=material_type,
                        resource_path=run.output_relative_path,
                    )
                )
            elif _sha256_path(output) != run.output_sha256:
                issues.append(
                    ProjectHealthIssue(
                        "warning",
                        "modified_export_file",
                        f"El archivo exportado {run.output_relative_path} cambió después de generarse.",
                        run.id,
                        export_run_id=run.id,
                        export_material_type=material_type,
                        resource_path=run.output_relative_path,
                    )
                )

    if not issues:
        issues.append(ProjectHealthIssue("info", "healthy", "No se detectaron problemas."))
    active, dismissed = _filter_dismissed_health_issues(root, issues)
    return ProjectHealthReport(
        datetime.now(timezone.utc).isoformat(),
        revision,
        active,
        dismissed,
    )


def create_project_backup(
    *,
    project_root: Path,
    created_by: str,
    note: str | None = None,
    output_path: Path | None = None,
) -> ProjectBackupInfo:
    root = project_root.resolve()
    source_db = root / "data" / "archive_workbench.sqlite3"
    if not source_db.exists():
        raise ValueError("No existe la base SQLite del proyecto")
    created_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = output_path or (root / "backups" / "project" / f"project_{stamp}.zip")
    target = target.resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and output_path is None:
        base = target.with_suffix("")
        counter = 2
        while target.exists():
            target = base.with_name(f"{base.name}_{counter}").with_suffix(".zip")
            counter += 1
    elif target.exists():
        raise ValueError(f"Ya existe el backup: {target}")

    with tempfile.TemporaryDirectory(prefix="archive_workbench_backup_") as tmp_name:
        tmp = Path(tmp_name)
        snapshot_db = tmp / "database.sqlite3"
        source_connection = sqlite3.connect(source_db)
        target_connection = sqlite3.connect(snapshot_db)
        try:
            source_connection.backup(target_connection)
        finally:
            target_connection.close()
            source_connection.close()
        valid, quick_result = _sqlite_quick_check(snapshot_db)
        if not valid:
            raise ValueError(f"La copia SQLite no superó quick_check: {quick_result}")

        connection = sqlite3.connect(snapshot_db)
        try:
            project_row = connection.execute(
                "SELECT id, name FROM projects ORDER BY created_at LIMIT 1"
            ).fetchone()
            revision_row = connection.execute(
                "SELECT version_num FROM alembic_version LIMIT 1"
            ).fetchone()
        finally:
            connection.close()
        project_id = str(project_row[0]) if project_row else None
        project_name = str(project_row[1]) if project_row else None
        db_revision = str(revision_row[0]) if revision_row else None

        files: dict[str, str] = {"database.sqlite3": _sha256_path(snapshot_db)}
        config_root = root / "config"
        config_paths: list[Path] = []
        if config_root.exists():
            config_paths = sorted(path for path in config_root.rglob("*") if path.is_file())
            for config_path in config_paths:
                relative = "config/" + config_path.relative_to(config_root).as_posix()
                files[relative] = _sha256_path(config_path)
        manifest = {
            "format": BACKUP_FORMAT,
            "app_version": __version__,
            "database_revision": db_revision,
            "project_id": project_id,
            "project_name": project_name,
            "created_by": created_by,
            "created_at": created_at,
            "note": note.strip() if note and note.strip() else None,
            "includes_local_source_files": False,
            "files": files,
        }
        manifest_path = tmp / "manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.write(snapshot_db, "database.sqlite3")
            archive.write(manifest_path, "manifest.json")
            for config_path in config_paths:
                archive.write(
                    config_path,
                    "config/" + config_path.relative_to(config_root).as_posix(),
                )

    return ProjectBackupInfo(
        path=target,
        backup_sha256=_sha256_path(target),
        database_sha256=files["database.sqlite3"],
        database_revision=db_revision,
        project_id=project_id,
        project_name=project_name,
        created_by=created_by,
        created_at=created_at,
        note=manifest["note"],
        config_file_count=len(config_paths),
    )


def inspect_project_backup(path: Path) -> ProjectBackupInfo:
    backup = path.resolve()
    if not backup.exists():
        raise ValueError(f"Backup inexistente: {backup}")
    with zipfile.ZipFile(backup, "r") as archive:
        members = _safe_zip_members(archive)
        names = {member.filename for member in members}
        if {"manifest.json", "database.sqlite3"} - names:
            raise ValueError("El ZIP no contiene manifest.json y database.sqlite3")
        manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
        if manifest.get("format") != BACKUP_FORMAT:
            raise ValueError("Formato de backup incompatible")
        declared = manifest.get("files")
        if not isinstance(declared, dict):
            raise ValueError("Manifest inválido: files")
        for name, expected in declared.items():
            if name not in names:
                raise ValueError(f"Falta el archivo declarado {name}")
            actual = hashlib.sha256(archive.read(name)).hexdigest()
            if actual != expected:
                raise ValueError(f"Checksum inválido para {name}")
        with tempfile.TemporaryDirectory(prefix="archive_workbench_inspect_") as tmp_name:
            db_path = Path(tmp_name) / "database.sqlite3"
            db_path.write_bytes(archive.read("database.sqlite3"))
            valid, quick_result = _sqlite_quick_check(db_path)
            if not valid:
                raise ValueError(f"La base incluida no superó quick_check: {quick_result}")
    return ProjectBackupInfo(
        path=backup,
        backup_sha256=_sha256_path(backup),
        database_sha256=str(manifest["files"]["database.sqlite3"]),
        database_revision=manifest.get("database_revision"),
        project_id=manifest.get("project_id"),
        project_name=manifest.get("project_name"),
        created_by=str(manifest.get("created_by") or ""),
        created_at=str(manifest.get("created_at") or ""),
        note=manifest.get("note"),
        config_file_count=sum(name.startswith("config/") for name in manifest["files"]),
    )


def _project_backup_sort_key(info: ProjectBackupInfo) -> tuple[datetime, str]:
    try:
        created_at = datetime.fromisoformat(info.created_at.replace("Z", "+00:00"))
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        created_at = created_at.astimezone(timezone.utc)
    except (TypeError, ValueError):
        created_at = datetime.fromtimestamp(info.path.stat().st_mtime, tz=timezone.utc)
    return created_at, info.path.name


def list_project_backups(project_root: Path) -> list[ProjectBackupInfo]:
    root = project_root.resolve() / "backups" / "project"
    if not root.exists():
        return []
    rows: list[ProjectBackupInfo] = []
    for path in root.glob("*.zip"):
        try:
            rows.append(inspect_project_backup(path))
        except (ValueError, OSError, zipfile.BadZipFile):
            continue
    rows.sort(key=_project_backup_sort_key, reverse=True)
    return rows


def restore_project_backup(
    *,
    project_root: Path,
    backup_path: Path,
    restored_by: str,
    restore_config: bool = True,
) -> ProjectRestoreSummary:
    root = project_root.resolve()
    info = inspect_project_backup(backup_path)
    source_db = root / "data" / "archive_workbench.sqlite3"
    if not source_db.exists():
        raise ValueError("No existe una base activa que pueda resguardarse antes de restaurar")
    safety = create_project_backup(
        project_root=root,
        created_by=restored_by,
        note=f"Backup automático previo a restaurar {info.path.name}",
    )
    with tempfile.TemporaryDirectory(prefix="archive_workbench_restore_") as tmp_name:
        tmp = Path(tmp_name)
        with zipfile.ZipFile(info.path, "r") as archive:
            _safe_zip_members(archive)
            restored_db = tmp / "database.sqlite3"
            restored_db.write_bytes(archive.read("database.sqlite3"))
            valid, quick_result = _sqlite_quick_check(restored_db)
            if not valid:
                raise ValueError(f"La base a restaurar no superó quick_check: {quick_result}")
            target_tmp = source_db.with_suffix(".sqlite3.restore_tmp")
            shutil.copy2(restored_db, target_tmp)
            for suffix in ("-wal", "-shm"):
                companion = Path(str(source_db) + suffix)
                if companion.exists():
                    companion.unlink()
            os.replace(target_tmp, source_db)
            if restore_config:
                for name in archive.namelist():
                    if not name.startswith("config/") or name.endswith("/"):
                        continue
                    target = root / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(archive.read(name))
    return ProjectRestoreSummary(
        restored_backup=info.path,
        restored_database_sha256=info.database_sha256,
        safety_backup=safety.path,
        safety_backup_sha256=safety.backup_sha256,
        database_revision=info.database_revision,
    )
