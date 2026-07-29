from __future__ import annotations

from dataclasses import dataclass
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
    FileInstance,
    Project,
    SemanticSearchProfile,
)
from archive_workbench.graph import graph_consistency_issues
from archive_workbench.project_init import PROJECT_DIRS
from archive_workbench.search import search_index_status
from archive_workbench.semantic_search import semantic_index_status
from archive_workbench.version import __version__


BACKUP_FORMAT = "archive-workbench-project-backup-v1"


@dataclass(slots=True)
class ProjectHealthIssue:
    severity: str
    code: str
    message: str
    detail: str | None = None


@dataclass(slots=True)
class ProjectHealthReport:
    checked_at: str
    database_revision: str | None
    issues: list[ProjectHealthIssue]

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
                ProjectHealthIssue("warning", "missing_directory", f"Falta el directorio del proyecto: {relative}")
            )

    file_rows = session.execute(
        select(FileInstance, DigitalObject).join(
            DigitalObject, DigitalObject.id == FileInstance.digital_object_id
        )
    ).all()
    for instance, digital in file_rows:
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
                )
            )
        if instance.verified_sha256 and instance.verified_sha256 != digital.sha256:
            issues.append(
                ProjectHealthIssue(
                    "error",
                    "registered_hash_mismatch",
                    f"La verificación registrada no coincide con el objeto digital: {instance.relative_path}.",
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
            issues.append(
                ProjectHealthIssue(
                    graph_issue.severity,
                    f"graph_{graph_issue.code}",
                    graph_issue.message,
                    graph_issue.relation_id or graph_issue.mention_id or graph_issue.entity_id,
                )
            )

    try:
        index_state = search_index_status(session)
        if not index_state.is_current:
            issues.append(
                ProjectHealthIssue(
                    "info",
                    "search_index_pending",
                    "El índice de búsqueda está pendiente de reconstrucción; se actualizará al buscar.",
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
                        f"El índice semántico '{semantic_profile.name}' requiere reconstrucción.",
                        semantic_state.reason,
                    )
                )

    exports = session.scalars(select(CorpusExportRun).order_by(CorpusExportRun.created_at)).all()
    for run in exports:
        output = root / run.output_relative_path
        if not output.exists():
            issues.append(
                ProjectHealthIssue(
                    "warning",
                    "missing_export_file",
                    f"Ya no existe la exportación registrada {run.output_relative_path}.",
                    run.id,
                )
            )
        elif _sha256_path(output) != run.output_sha256:
            issues.append(
                ProjectHealthIssue(
                    "warning",
                    "modified_export_file",
                    f"La exportación {run.output_relative_path} fue modificada después de generarse.",
                    run.id,
                )
            )

    if not issues:
        issues.append(ProjectHealthIssue("info", "healthy", "No se detectaron problemas."))
    return ProjectHealthReport(datetime.now(timezone.utc).isoformat(), revision, issues)


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
