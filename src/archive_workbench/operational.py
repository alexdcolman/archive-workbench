from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
from uuid import uuid4
import zipfile

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from archive_workbench.db import create_sqlite_engine, database_path, session_scope, upgrade_database
from archive_workbench.db.migrations import current_revision
from archive_workbench.db.models import (
    AuthorityRecord,
    CorpusExportProfile,
    CorpusExportRun,
    DigitalObject,
    EditablePage,
    EntityMention,
    EntityRelation,
    ExchangeCheckpoint,
    FileInstance,
    ProcessingJob,
    Project,
    ProjectRecoveryCheck,
    SemanticSearchProfile,
    SourceRegistration,
    WorkAssignment,
)
from archive_workbench.project_admin import inspect_project_backup, list_project_backups
from archive_workbench.search import search_index_status
from archive_workbench.semantic_search import semantic_index_status


READINESS_STATUSES = ("ready", "attention", "pending", "optional")


@dataclass(slots=True)
class ReadinessItem:
    key: str
    label: str
    status: str
    summary: str
    detail: str | None
    app_mode: str | None


@dataclass(slots=True)
class OperationalReadinessReport:
    checked_at: str
    database_revision: str | None
    project_id: str | None
    items: list[ReadinessItem]

    @property
    def attention_count(self) -> int:
        return sum(item.status == "attention" for item in self.items)

    @property
    def ready_count(self) -> int:
        return sum(item.status == "ready" for item in self.items)

    @property
    def pending_count(self) -> int:
        return sum(item.status == "pending" for item in self.items)

    @property
    def overall_status(self) -> str:
        if self.attention_count:
            return "attention"
        if self.pending_count:
            return "in_progress"
        return "ready"


@dataclass(slots=True)
class RecoveryCheckRow:
    id: str
    backup_relative_path: str
    backup_sha256: str
    source_database_revision: str | None
    upgraded_database_revision: str | None
    status: str
    details: dict
    note: str | None
    tested_by: str
    tested_at: datetime


def _count(session: Session, model, *conditions) -> int:
    statement = select(func.count()).select_from(model)
    if conditions:
        statement = statement.where(*conditions)
    return int(session.scalar(statement) or 0)


def operational_readiness(
    session: Session,
    *,
    project_root: Path,
) -> OperationalReadinessReport:
    root = project_root.resolve()
    project = session.scalars(select(Project).order_by(Project.created_at)).first()
    project_id = project.id if project else None
    items: list[ReadinessItem] = []

    source_count = _count(session, SourceRegistration)
    digital_count = _count(session, DigitalObject)
    file_count = _count(session, FileInstance)
    present_files = _count(session, FileInstance, FileInstance.presence == "present")
    modified_files = _count(session, FileInstance, FileInstance.presence == "modified")
    missing_files = _count(session, FileInstance, FileInstance.presence == "missing")
    if source_count == 0:
        items.append(ReadinessItem(
            "catalog", "Catálogo", "pending", "Todavía no hay archivos vinculados con unidades del catálogo.",
            "Creá o importá unidades del catálogo y vinculá al menos un archivo digital para continuar.", "catalog",
        ))
    elif file_count == 0:
        items.append(ReadinessItem(
            "catalog", "Catálogo", "attention",
            f"Hay {source_count} documentos, pero ninguno tiene una instancia local registrada.",
            "Asociá o recuperá los archivos antes de iniciar nuevos procesamientos.", "catalog",
        ))
    elif modified_files:
        items.append(ReadinessItem(
            "catalog", "Catálogo", "attention",
            f"Hay {source_count} documentos y {modified_files} archivos modificados.",
            "Verificá los archivos cuyo tamaño o huella cambió antes de procesarlos.", "catalog",
        ))
    elif missing_files:
        items.append(ReadinessItem(
            "catalog", "Catálogo", "attention",
            f"Hay {source_count} documentos y {missing_files} archivos locales ausentes.",
            f"Objetos digitales registrados: {digital_count}; archivos presentes: {present_files}.", "catalog",
        ))
    else:
        items.append(ReadinessItem(
            "catalog", "Catálogo", "ready",
            f"{source_count} documentos procesables; {present_files} archivos locales verificados.",
            None, "catalog",
        ))

    processing_count = _count(session, ProcessingJob)
    editable_pages = _count(session, EditablePage)
    approved_pages = _count(session, EditablePage, EditablePage.review_status == "approved")
    stale_pages = _count(session, EditablePage, EditablePage.status == "stale")
    if source_count == 0:
        processing_status = "pending"
        processing_summary = "Procesar documentos todavía no puede comenzar porque no hay documentos registrados en el catálogo."
    elif editable_pages == 0:
        processing_status = "pending"
        processing_summary = f"Hay {source_count} documentos registrados, pero todavía no hay páginas preparadas para revisión."
    elif stale_pages:
        processing_status = "attention"
        processing_summary = f"Hay {stale_pages} páginas cuya base de revisión quedó desactualizada respecto del resultado de extracción elegido."
    else:
        processing_status = "ready"
        processing_summary = f"{editable_pages} páginas preparadas para revisión; {approved_pages} páginas aprobadas."
    items.append(ReadinessItem(
        "processing", "Procesar documentos", processing_status, processing_summary,
        "En Procesar documentos podés preparar imágenes de página, extraer texto y elegir qué resultado de extracción usar como base para revisar cada página.",
        "processing" if editable_pages == 0 or stale_pages else "review",
    ))

    active_work = _count(
        session, WorkAssignment,
        WorkAssignment.status.in_(("planned", "in_progress", "submitted", "blocked")),
    )
    blocked_work = _count(session, WorkAssignment, WorkAssignment.status == "blocked")
    submitted_work = _count(session, WorkAssignment, WorkAssignment.status == "submitted")
    if blocked_work:
        work_status = "attention"
        work_summary = f"Hay {blocked_work} asignaciones bloqueadas."
    elif active_work:
        work_status = "ready"
        work_summary = f"Hay {active_work} asignaciones activas y {submitted_work} enviadas."
    else:
        work_status = "optional" if editable_pages == 0 else "pending"
        work_summary = "No hay asignaciones activas."
    items.append(ReadinessItem(
        "work", "Organizar trabajo", work_status, work_summary,
        "En Organizar trabajo podés asignar documentos o páginas a integrantes del equipo y registrar el avance de cada tarea.", "work",
    ))

    try:
        lexical = search_index_status(session)
        lexical_status = "ready" if lexical.is_current else "attention"
        if lexical.is_current:
            lexical_summary = "La búsqueda textual está actualizada."
            lexical_detail = "Podés buscar sobre la versión más reciente del contenido revisado."
        elif lexical.indexed_generation == 0:
            lexical_summary = "La búsqueda textual todavía no está preparada para este proyecto."
            lexical_detail = (
                "Abrí Búsqueda textual y construí el índice antes de realizar la primera búsqueda."
            )
        else:
            lexical_summary = (
                "La búsqueda textual necesita actualizarse porque el contenido cambió desde la última indexación."
            )
            lexical_detail = (
                "Abrí Búsqueda textual y reconstruí el índice para incluir los cambios más recientes."
            )
    except RuntimeError as exc:
        lexical_status = "attention"
        lexical_summary = "El índice literal no está disponible."
        lexical_detail = str(exc)
    items.append(ReadinessItem(
        "search", "Búsqueda textual", lexical_status, lexical_summary, lexical_detail, "search",
    ))

    semantic_profiles = session.scalars(
        select(SemanticSearchProfile).order_by(SemanticSearchProfile.name)
    ).all()
    if not semantic_profiles or project is None:
        items.append(ReadinessItem(
            "semantic", "Búsqueda semántica", "optional",
            "Todavía no se configuró una búsqueda por significado para este proyecto.",
            "Podés configurarla cuando necesites encontrar fragmentos relacionados aunque no compartan las mismas palabras.",
            "semantic",
        ))
    else:
        stale = []
        for profile in semantic_profiles:
            state = semantic_index_status(
                session, project_root=root, project_id=project.id, profile=profile
            )
            if not state.is_current:
                stale.append(profile.name)
        items.append(ReadinessItem(
            "semantic", "Búsqueda semántica", "attention" if stale else "ready",
            (
                f"{len(stale)} configuraciones de búsqueda semántica necesitan reconstruir su índice."
                if stale else f"{len(semantic_profiles)} configuraciones de búsqueda semántica tienen un índice vigente."
            ),
            ", ".join(stale) if stale else "Los índices de búsqueda semántica configurados están disponibles para buscar fragmentos por significado.",
            "semantic",
        ))

    entity_count = _count(session, AuthorityRecord, AuthorityRecord.lifecycle_status == "active")
    mention_count = _count(session, EntityMention, EntityMention.status != "rejected")
    relation_count = _count(session, EntityRelation, EntityRelation.lifecycle_status == "active")
    items.append(ReadinessItem(
        "entities", "Entidades y menciones", "ready" if entity_count else "optional",
        f"{entity_count} entidades, {mention_count} menciones y {relation_count} relaciones activas.",
        "Podés registrar personas, organizaciones, lugares u otras entidades cuando aparezcan durante la revisión.", "authorities",
    ))

    export_profiles = _count(session, CorpusExportProfile)
    export_runs = _count(session, CorpusExportRun)
    items.append(ReadinessItem(
        "export", "Exportar corpus", "ready" if export_runs else ("pending" if editable_pages else "optional"),
        f"{export_profiles} configuraciones de exportación guardadas y {export_runs} archivos de exportación creados.",
        "En Exportar corpus podés elegir qué textos revisados y datos descriptivos incluir y crear un archivo reproducible para análisis u otros usos.", "export",
    ))

    checkpoints = _count(session, ExchangeCheckpoint)
    items.append(ReadinessItem(
        "exchange", "Intercambiar cambios", "ready" if checkpoints else "pending",
        f"{checkpoints} referencias de sincronización registradas entre copias del proyecto.",
        "En Intercambiar cambios podés enviar y recibir modificaciones entre copias del mismo proyecto mediante paquetes verificables, sin compartir la base de datos activa.", "exchange",
    ))

    backups = list_project_backups(root)
    latest_check = session.scalars(
        select(ProjectRecoveryCheck).order_by(ProjectRecoveryCheck.tested_at.desc())
    ).first()
    if not backups:
        recovery_status = "attention"
        recovery_summary = "No hay copias de seguridad verificables del proyecto."
        recovery_detail = "Creá una copia de seguridad antes de continuar con cambios sustantivos en el proyecto."
    elif latest_check is None:
        recovery_status = "attention"
        recovery_summary = f"Hay {len(backups)} copias de seguridad, pero ninguna tiene una prueba de recuperación registrada."
        recovery_detail = "La verificación de checksums no demuestra por sí sola que la base pueda migrarse y abrirse."
    elif latest_check.status != "completed":
        recovery_status = "attention"
        recovery_summary = "La última prueba de recuperación falló."
        recovery_detail = str((latest_check.details_json or {}).get("error") or "Sin detalle")
    elif latest_check.backup_sha256 != backups[0].backup_sha256:
        recovery_status = "attention"
        recovery_summary = "La copia de seguridad más reciente todavía no fue probada mediante una recuperación temporal."
        recovery_detail = f"Última prueba exitosa: {latest_check.tested_at.isoformat(timespec='minutes')}"
    else:
        recovery_status = "ready"
        recovery_summary = "La copia de seguridad más reciente fue verificada y pudo abrirse en una recuperación temporal."
        recovery_detail = f"Prueba: {latest_check.tested_at.isoformat(timespec='minutes')}"
    items.append(ReadinessItem(
        "recovery", "Administrar y recuperar", recovery_status, recovery_summary, recovery_detail, "admin",
    ))

    return OperationalReadinessReport(
        checked_at=datetime.now(timezone.utc).isoformat(),
        database_revision=current_revision(root),
        project_id=project_id,
        items=items,
    )


def _foreign_key_check(path: Path) -> list[tuple]:
    connection = sqlite3.connect(path)
    try:
        return list(connection.execute("PRAGMA foreign_key_check").fetchall())
    finally:
        connection.close()


def _relative_or_absolute(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path.resolve())


def run_project_backup_recovery_test(
    session: Session,
    *,
    project_root: Path,
    backup_path: Path,
    tested_by: str,
    note: str | None = None,
) -> RecoveryCheckRow:
    root = project_root.resolve()
    project = session.scalars(select(Project).order_by(Project.created_at)).first()
    if project is None:
        raise ValueError("El proyecto no está registrado en SQLite")

    tested_at = datetime.now(timezone.utc)
    status = "failed"
    details: dict = {}
    backup_sha256 = ""
    source_revision: str | None = None
    upgraded_revision: str | None = None
    error: Exception | None = None

    try:
        info = inspect_project_backup(backup_path)
        backup_sha256 = info.backup_sha256
        source_revision = info.database_revision
        if info.project_id and info.project_id != project.id:
            raise ValueError(
                f"El backup pertenece al proyecto {info.project_id}, no a {project.id}"
            )
        with tempfile.TemporaryDirectory(prefix="archive_workbench_recovery_") as tmp_name:
            temp_root = Path(tmp_name) / "project"
            (temp_root / "data").mkdir(parents=True)
            with zipfile.ZipFile(info.path, "r") as archive:
                database_target = temp_root / "data" / "archive_workbench.sqlite3"
                database_target.write_bytes(archive.read("database.sqlite3"))
                for name in archive.namelist():
                    if name.startswith("config/") and not name.endswith("/"):
                        target = temp_root / name
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_bytes(archive.read(name))

            before_foreign = _foreign_key_check(database_target)
            if before_foreign:
                raise ValueError(
                    f"La base del backup contiene {len(before_foreign)} referencias inválidas"
                )
            upgrade_database(temp_root)
            upgraded_revision = current_revision(temp_root)
            after_foreign = _foreign_key_check(database_target)
            if after_foreign:
                raise ValueError(
                    f"La base migrada contiene {len(after_foreign)} referencias inválidas"
                )
            engine = create_sqlite_engine(database_path(temp_root))
            try:
                with session_scope(engine) as restored_session:
                    restored_project = restored_session.get(Project, project.id)
                    if restored_project is None:
                        raise ValueError("La copia migrada no contiene el proyecto esperado")
                    table_count = int(
                        restored_session.execute(
                            text("SELECT count(*) FROM sqlite_master WHERE type='table'")
                        ).scalar_one()
                    )
            finally:
                engine.dispose()
            details = {
                "source_revision": source_revision,
                "upgraded_revision": upgraded_revision,
                "table_count": table_count,
                "config_file_count": info.config_file_count,
                "database_sha256": info.database_sha256,
                "active_project_unchanged": True,
            }
            status = "completed"
    except Exception as exc:  # se persiste el resultado fallido para auditoría
        error = exc
        details = {"error": str(exc), "active_project_unchanged": True}
        if backup_path.exists() and not backup_sha256:
            import hashlib
            digest = hashlib.sha256()
            with backup_path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
            backup_sha256 = digest.hexdigest()

    record = ProjectRecoveryCheck(
        id=str(uuid4()),
        project_id=project.id,
        backup_relative_path=_relative_or_absolute(backup_path, root),
        backup_sha256=backup_sha256 or "unavailable",
        source_database_revision=source_revision,
        upgraded_database_revision=upgraded_revision,
        status=status,
        details_json=details,
        note=note or None,
        tested_by=tested_by or "local_user",
        tested_at=tested_at,
    )
    session.add(record)
    session.flush()
    row = RecoveryCheckRow(
        id=record.id,
        backup_relative_path=record.backup_relative_path,
        backup_sha256=record.backup_sha256,
        source_database_revision=record.source_database_revision,
        upgraded_database_revision=record.upgraded_database_revision,
        status=record.status,
        details=dict(record.details_json or {}),
        note=record.note,
        tested_by=record.tested_by,
        tested_at=record.tested_at,
    )
    return row


def recovery_check_rows(
    session: Session,
    *,
    project_id: str | None = None,
    limit: int = 50,
) -> list[RecoveryCheckRow]:
    statement = select(ProjectRecoveryCheck)
    if project_id:
        statement = statement.where(ProjectRecoveryCheck.project_id == project_id)
    records = session.scalars(
        statement.order_by(ProjectRecoveryCheck.tested_at.desc()).limit(limit)
    ).all()
    return [
        RecoveryCheckRow(
            id=item.id,
            backup_relative_path=item.backup_relative_path,
            backup_sha256=item.backup_sha256,
            source_database_revision=item.source_database_revision,
            upgraded_database_revision=item.upgraded_database_revision,
            status=item.status,
            details=dict(item.details_json or {}),
            note=item.note,
            tested_by=item.tested_by,
            tested_at=item.tested_at,
        )
        for item in records
    ]
