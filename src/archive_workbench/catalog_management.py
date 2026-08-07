from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from archive_workbench.contracts.decisions import ProjectDecisions
from archive_workbench.db.models import (
    ArchivalFieldValue,
    ArchivalUnit,
    ArchivalUnitRevision,
    DigitalObject,
    DigitalObjectUnitLink,
    EditablePage,
    ExtractionPageSelection,
    ExtractionRun,
    FileInstance,
    PreprocessingRun,
    Project,
    SourceRegistration,
)
from archive_workbench.domain.enums import FilePresence, MediaType
from archive_workbench.identity import new_id, slugify, stable_id
from archive_workbench.inspection import inspect_input
from archive_workbench.sources import PROCESSABLE_SOURCE_TYPES

REGISTRATION_STATUSES = ("incomplete", "provisional", "complete")
RELATION_TYPES = ("represents", "contains", "is_part_of", "alternate_representation")


@dataclass(slots=True)
class CatalogSummary:
    units: int
    incomplete_units: int
    digital_objects: int
    file_instances: int
    present_files: int
    missing_files: int


@dataclass(slots=True)
class CatalogUnitRow:
    id: str
    parent_id: str | None
    level_key: str
    title: str
    reference_code: str | None
    registration_status: str
    completion_confirmed: bool
    revision: int
    depth: int
    path: str
    child_count: int
    digital_object_count: int


@dataclass(slots=True)
class CatalogFieldRow:
    id: str
    field_key: str
    value_state: str
    value: Any | None
    sort_order: int
    source_note: str | None


@dataclass(slots=True)
class CatalogFileRow:
    id: str
    storage_root: str
    relative_path: str
    presence: str
    byte_size_seen: int | None
    last_seen_at: datetime | None
    verified_sha256: str | None


@dataclass(slots=True)
class CatalogDigitalObjectRow:
    id: str
    link_id: str
    source_key: str | None
    relation_type: str
    page_start: int | None
    page_end: int | None
    media_type: str
    original_filename: str
    sha256: str
    byte_size: int
    page_count: int | None
    preprocessing_status: str
    extraction_status: str
    selected_pages: int
    editable_pages: int
    reviewed_pages: int
    linked_unit_count: int
    files: list[CatalogFileRow] = field(default_factory=list)


@dataclass(slots=True)
class CatalogRevisionRow:
    revision_number: int
    operation: str
    changed_by: str
    changed_at: datetime
    note: str | None
    snapshot: dict[str, Any]


@dataclass(slots=True)
class RegisterFileResult:
    digital_object_id: str
    file_instance_id: str
    link_id: str
    digital_object_created: bool
    file_instance_created: bool
    link_created: bool
    duplicate_content: bool
    source_key: str


@dataclass(slots=True)
class RegisterUploadedFileResult:
    relative_path: str
    reused_existing_path: bool
    registration: RegisterFileResult


@dataclass(slots=True)
class UnlinkDigitalObjectResult:
    link_id: str
    archival_unit_id: str
    digital_object_id: str
    original_filename: str
    remaining_links: int


@dataclass(slots=True)
class RemoveFileInstanceResult:
    file_instance_id: str
    digital_object_id: str
    relative_path: str
    physical_deleted: bool
    remaining_instances: int


_CATALOG_NAMESPACE = UUID("fb5f12a5-cde2-47fc-9e5f-28c6a60d47e1")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _level_map(decisions: ProjectDecisions):
    return {item.key: item for item in decisions.archival_levels if item.enabled}


def _field_map(decisions: ProjectDecisions):
    return {item.key: item for item in decisions.descriptive_fields if item.enabled}


def _unit_snapshot(session: Session, unit: ArchivalUnit) -> dict[str, Any]:
    fields = session.scalars(
        select(ArchivalFieldValue)
        .where(ArchivalFieldValue.archival_unit_id == unit.id)
        .order_by(ArchivalFieldValue.field_key, ArchivalFieldValue.sort_order)
    ).all()
    return {
        "id": unit.id,
        "project_id": unit.project_id,
        "parent_id": unit.parent_id,
        "level_key": unit.level_key,
        "reference_code": unit.reference_code,
        "title": unit.title,
        "registration_status": unit.registration_status,
        "completion_confirmed": bool(unit.completion_confirmed),
        "completion_confirmed_at": (
            unit.completion_confirmed_at.isoformat() if unit.completion_confirmed_at else None
        ),
        "completion_confirmed_by": unit.completion_confirmed_by,
        "revision": unit.revision,
        "fields": [
            {
                "field_key": row.field_key,
                "value_state": row.value_state,
                "value": row.value_json,
                "sort_order": row.sort_order,
                "source_note": row.source_note,
            }
            for row in fields
        ],
    }


def _append_revision(
    session: Session,
    unit: ArchivalUnit,
    *,
    operation: str,
    changed_by: str,
    note: str | None = None,
) -> ArchivalUnitRevision:
    row = ArchivalUnitRevision(
        id=new_id(),
        archival_unit_id=unit.id,
        revision_number=unit.revision,
        operation=operation,
        snapshot_json=_unit_snapshot(session, unit),
        note=(note.strip() if note and note.strip() else None),
        changed_by=changed_by,
    )
    session.add(row)
    session.flush()
    return row


def _ensure_baseline(session: Session, unit: ArchivalUnit) -> None:
    existing = session.scalar(
        select(ArchivalUnitRevision.id).where(
            ArchivalUnitRevision.archival_unit_id == unit.id,
            ArchivalUnitRevision.revision_number == unit.revision,
        )
    )
    if existing is None:
        _append_revision(
            session,
            unit,
            operation="baseline",
            changed_by=unit.updated_by or unit.created_by,
            note="Estado anterior a la primera edición desde la interfaz de catálogo.",
        )


def _validate_parent(
    session: Session,
    decisions: ProjectDecisions,
    *,
    project_id: str,
    level_key: str,
    parent_id: str | None,
    moving_unit_id: str | None = None,
) -> ArchivalUnit | None:
    levels = _level_map(decisions)
    if level_key not in levels:
        raise ValueError(f"Nivel archivístico desconocido: {level_key}")
    level = levels[level_key]
    if parent_id is None:
        if level.parent_keys:
            raise ValueError(
                f"{level.label} necesita una unidad padre de tipo: "
                + ", ".join(level.parent_keys)
            )
        return None
    parent = session.get(ArchivalUnit, parent_id)
    if parent is None or parent.project_id != project_id:
        raise ValueError("La unidad padre no existe en este proyecto")
    if moving_unit_id:
        cursor: ArchivalUnit | None = parent
        while cursor is not None:
            if cursor.id == moving_unit_id:
                raise ValueError("No se puede mover una unidad dentro de sí misma o de un descendiente")
            cursor = session.get(ArchivalUnit, cursor.parent_id) if cursor.parent_id else None
    if parent.level_key not in level.parent_keys:
        raise ValueError(
            f"{levels.get(parent.level_key, parent).label if parent.level_key in levels else parent.level_key} "
            f"no puede contener una unidad de nivel {level.label}"
        )
    return parent


def create_archival_unit(
    session: Session,
    *,
    decisions: ProjectDecisions,
    project_id: str,
    parent_id: str | None,
    level_key: str,
    title: str,
    created_by: str,
    reference_code: str | None = None,
    note: str | None = None,
) -> ArchivalUnit:
    clean_title = title.strip()
    if not clean_title:
        raise ValueError("El título no puede estar vacío")
    actor = created_by.strip() or "local_user"
    _validate_parent(
        session,
        decisions,
        project_id=project_id,
        level_key=level_key,
        parent_id=parent_id,
    )
    unit = ArchivalUnit(
        id=new_id(),
        project_id=project_id,
        parent_id=parent_id,
        level_key=level_key,
        reference_code=reference_code.strip() if reference_code and reference_code.strip() else None,
        title=clean_title,
        registration_status="incomplete",
        completion_confirmed=False,
        created_by=actor,
        updated_by=actor,
        revision=1,
    )
    session.add(unit)
    session.flush()
    _append_revision(session, unit, operation="create", changed_by=actor, note=note)
    return unit


def _normalize_field_values(definition, payload: dict[str, Any]) -> list[tuple[str, Any | None, str | None]]:
    state = str(payload.get("state", "pending"))
    if state not in {"provided", "no_information", "not_applicable", "pending"}:
        raise ValueError(f"Estado de campo inválido para {definition.label}: {state}")
    note = payload.get("source_note")
    note = str(note).strip() if note is not None and str(note).strip() else None
    if state != "provided":
        return [(state, None, note)]
    raw_values = payload.get("values", [])
    if isinstance(raw_values, str):
        raw_values = [line.strip() for line in raw_values.splitlines() if line.strip()]
    elif not isinstance(raw_values, list):
        raw_values = [raw_values]
    values = [value for value in raw_values if value is not None and str(value).strip()]
    if not values:
        return [("pending", None, note)]
    if not definition.repeatable:
        values = values[:1]
    return [("provided", value, note) for value in values]


def update_archival_unit(
    session: Session,
    *,
    decisions: ProjectDecisions,
    unit_id: str,
    changed_by: str,
    title: str,
    reference_code: str | None,
    registration_status: str,
    completion_confirmed: bool,
    field_values: dict[str, dict[str, Any]] | None = None,
    note: str | None = None,
) -> ArchivalUnit:
    unit = session.get(ArchivalUnit, unit_id)
    if unit is None:
        raise ValueError("La unidad archivística no existe")
    clean_title = title.strip()
    if not clean_title:
        raise ValueError("El título no puede estar vacío")
    if registration_status not in REGISTRATION_STATUSES:
        raise ValueError(f"Estado de registro inválido: {registration_status}")
    actor = changed_by.strip() or "local_user"
    _ensure_baseline(session, unit)
    unit.title = clean_title
    unit.reference_code = reference_code.strip() if reference_code and reference_code.strip() else None
    if registration_status == "complete" and not completion_confirmed:
        raise ValueError("Un registro completo requiere confirmación manual")
    unit.completion_confirmed = bool(completion_confirmed)
    if unit.completion_confirmed:
        unit.registration_status = "complete"
        unit.completion_confirmed_at = _utc_now()
        unit.completion_confirmed_by = actor
    else:
        unit.registration_status = registration_status
        unit.completion_confirmed_at = None
        unit.completion_confirmed_by = None
    if field_values is not None:
        definitions = _field_map(decisions)
        applicable = {
            key: definition
            for key, definition in definitions.items()
            if "all" in definition.applies_to_levels or unit.level_key in definition.applies_to_levels
        }
        unknown = sorted(set(field_values) - set(applicable))
        if unknown:
            raise ValueError("Campos no aplicables o desconocidos: " + ", ".join(unknown))
        session.execute(
            delete(ArchivalFieldValue).where(ArchivalFieldValue.archival_unit_id == unit.id)
        )
        for field_key, payload in field_values.items():
            definition = applicable[field_key]
            for index, (state, value, source_note) in enumerate(
                _normalize_field_values(definition, payload)
            ):
                session.add(
                    ArchivalFieldValue(
                        id=new_id(),
                        archival_unit_id=unit.id,
                        field_key=field_key,
                        value_state=state,
                        value_json=value,
                        sort_order=index,
                        source_note=source_note,
                    )
                )
    unit.revision += 1
    unit.updated_by = actor
    unit.updated_at = _utc_now()
    session.flush()
    _append_revision(session, unit, operation="update", changed_by=actor, note=note)
    return unit


def move_archival_unit(
    session: Session,
    *,
    decisions: ProjectDecisions,
    unit_id: str,
    new_parent_id: str | None,
    changed_by: str,
    note: str | None = None,
) -> ArchivalUnit:
    unit = session.get(ArchivalUnit, unit_id)
    if unit is None:
        raise ValueError("La unidad archivística no existe")
    if unit.parent_id == new_parent_id:
        return unit
    _validate_parent(
        session,
        decisions,
        project_id=unit.project_id,
        level_key=unit.level_key,
        parent_id=new_parent_id,
        moving_unit_id=unit.id,
    )
    actor = changed_by.strip() or "local_user"
    _ensure_baseline(session, unit)
    unit.parent_id = new_parent_id
    unit.revision += 1
    unit.updated_by = actor
    unit.updated_at = _utc_now()
    session.flush()
    _append_revision(session, unit, operation="move", changed_by=actor, note=note)
    return unit


def undo_last_archival_move(
    session: Session,
    *,
    decisions: ProjectDecisions,
    unit_id: str,
    changed_by: str,
    note: str | None = None,
) -> ArchivalUnit:
    """Revierte el movimiento más reciente mediante una nueva revisión append-only."""
    unit = session.get(ArchivalUnit, unit_id)
    if unit is None:
        raise ValueError("La unidad archivística no existe")
    revisions = session.scalars(
        select(ArchivalUnitRevision)
        .where(ArchivalUnitRevision.archival_unit_id == unit_id)
        .order_by(ArchivalUnitRevision.revision_number.desc())
    ).all()
    latest_move = next(
        (row for row in revisions if row.operation in {"move", "undo_move"}),
        None,
    )
    if latest_move is None or latest_move.revision_number != unit.revision:
        raise ValueError(
            "El último cambio de esta unidad no fue un movimiento; no hay un movimiento inmediato para deshacer"
        )
    previous = next(
        (row for row in revisions if row.revision_number < latest_move.revision_number),
        None,
    )
    if previous is None:
        raise ValueError("No existe un estado anterior al movimiento")
    previous_parent_id = previous.snapshot_json.get("parent_id")
    _validate_parent(
        session,
        decisions,
        project_id=unit.project_id,
        level_key=unit.level_key,
        parent_id=previous_parent_id,
        moving_unit_id=unit.id,
    )
    actor = changed_by.strip() or "local_user"
    unit.parent_id = previous_parent_id
    unit.revision += 1
    unit.updated_by = actor
    unit.updated_at = _utc_now()
    session.flush()
    _append_revision(
        session,
        unit,
        operation="undo_move",
        changed_by=actor,
        note=note or f"Se deshizo el movimiento de la revisión {latest_move.revision_number}.",
    )
    return unit


def archival_field_rows(session: Session, unit_id: str) -> list[CatalogFieldRow]:
    rows = session.scalars(
        select(ArchivalFieldValue)
        .where(ArchivalFieldValue.archival_unit_id == unit_id)
        .order_by(ArchivalFieldValue.field_key, ArchivalFieldValue.sort_order)
    ).all()
    return [
        CatalogFieldRow(
            id=row.id,
            field_key=row.field_key,
            value_state=row.value_state,
            value=row.value_json,
            sort_order=row.sort_order,
            source_note=row.source_note,
        )
        for row in rows
    ]


def archival_revision_rows(session: Session, unit_id: str) -> list[CatalogRevisionRow]:
    rows = session.scalars(
        select(ArchivalUnitRevision)
        .where(ArchivalUnitRevision.archival_unit_id == unit_id)
        .order_by(ArchivalUnitRevision.revision_number.desc())
    ).all()
    return [
        CatalogRevisionRow(
            revision_number=row.revision_number,
            operation=row.operation,
            changed_by=row.changed_by,
            changed_at=row.changed_at,
            note=row.note,
            snapshot=row.snapshot_json,
        )
        for row in rows
    ]


def catalog_summary(session: Session, project_id: str) -> CatalogSummary:
    units = int(
        session.scalar(
            select(func.count()).select_from(ArchivalUnit).where(ArchivalUnit.project_id == project_id)
        )
        or 0
    )
    incomplete = int(
        session.scalar(
            select(func.count()).select_from(ArchivalUnit).where(
                ArchivalUnit.project_id == project_id,
                ArchivalUnit.registration_status != "complete",
            )
        )
        or 0
    )
    digital = int(
        session.scalar(
            select(func.count()).select_from(DigitalObject).where(DigitalObject.project_id == project_id)
        )
        or 0
    )
    file_base = (
        select(func.count())
        .select_from(FileInstance)
        .join(DigitalObject, DigitalObject.id == FileInstance.digital_object_id)
        .where(DigitalObject.project_id == project_id)
    )
    files = int(session.scalar(file_base) or 0)
    present = int(
        session.scalar(file_base.where(FileInstance.presence == FilePresence.PRESENT.value)) or 0
    )
    missing = int(
        session.scalar(file_base.where(FileInstance.presence == FilePresence.MISSING.value)) or 0
    )
    return CatalogSummary(units, incomplete, digital, files, present, missing)


def catalog_unit_rows(session: Session, project_id: str) -> list[CatalogUnitRow]:
    units = session.scalars(
        select(ArchivalUnit).where(ArchivalUnit.project_id == project_id)
    ).all()
    project = session.get(Project, project_id)
    level_order: dict[str, int] = {}
    if project is not None:
        for item in project.decisions_json.get("archival_levels", []):
            if isinstance(item, dict) and item.get("key") is not None:
                level_order[str(item["key"])] = int(item.get("display_order", 10_000))
    children: dict[str | None, list[ArchivalUnit]] = {}
    for row in units:
        children.setdefault(row.parent_id, []).append(row)
    for group in children.values():
        group.sort(
            key=lambda item: (
                level_order.get(item.level_key, 10_000),
                item.title.casefold(),
                item.id,
            )
        )
    child_counts = {key: len(value) for key, value in children.items() if key is not None}
    object_counts = dict(
        session.execute(
            select(
                DigitalObjectUnitLink.archival_unit_id,
                func.count(func.distinct(DigitalObjectUnitLink.digital_object_id)),
            )
            .group_by(DigitalObjectUnitLink.archival_unit_id)
        ).all()
    )
    result: list[CatalogUnitRow] = []
    visited: set[str] = set()

    def visit(unit: ArchivalUnit, depth: int, ancestors: list[str]) -> None:
        if unit.id in visited:
            return
        visited.add(unit.id)
        path_titles = ancestors + [unit.title]
        result.append(
            CatalogUnitRow(
                id=unit.id,
                parent_id=unit.parent_id,
                level_key=unit.level_key,
                title=unit.title,
                reference_code=unit.reference_code,
                registration_status=unit.registration_status,
                completion_confirmed=bool(unit.completion_confirmed),
                revision=unit.revision,
                depth=depth,
                path=" / ".join(path_titles),
                child_count=int(child_counts.get(unit.id, 0)),
                digital_object_count=int(object_counts.get(unit.id, 0)),
            )
        )
        for child in children.get(unit.id, []):
            visit(child, depth + 1, path_titles)

    roots = children.get(None, [])
    for root in roots:
        visit(root, 0, [])
    # Defensive fallback for legacy rows with a missing parent.
    for unit in sorted(units, key=lambda item: (item.title.casefold(), item.id)):
        if unit.id not in visited:
            visit(unit, 0, [])
    return result


def search_catalog_units(
    session: Session,
    *,
    project_id: str,
    query: str = "",
    level_key: str | None = None,
    registration_status: str | None = None,
) -> list[CatalogUnitRow]:
    rows = catalog_unit_rows(session, project_id)
    fields_by_unit: dict[str, list[str]] = {}
    for unit_id, value in session.execute(
        select(ArchivalFieldValue.archival_unit_id, ArchivalFieldValue.value_json)
    ):
        if value is not None:
            fields_by_unit.setdefault(unit_id, []).append(str(value))
    files_by_unit: dict[str, list[str]] = {}
    for unit_id, filename, path in session.execute(
        select(
            DigitalObjectUnitLink.archival_unit_id,
            DigitalObject.original_filename,
            FileInstance.relative_path,
        )
        .join(DigitalObject, DigitalObject.id == DigitalObjectUnitLink.digital_object_id)
        .outerjoin(FileInstance, FileInstance.digital_object_id == DigitalObject.id)
    ):
        files_by_unit.setdefault(unit_id, []).extend(
            item for item in (filename, path) if item
        )
    needle = query.strip().casefold()
    result: list[CatalogUnitRow] = []
    for row in rows:
        if level_key and row.level_key != level_key:
            continue
        if registration_status and row.registration_status != registration_status:
            continue
        if needle:
            haystack = " ".join(
                [row.path, row.reference_code or ""]
                + fields_by_unit.get(row.id, [])
                + files_by_unit.get(row.id, [])
            ).casefold()
            if needle not in haystack:
                continue
        result.append(row)
    return result


def unit_digital_objects(session: Session, unit_id: str) -> list[CatalogDigitalObjectRow]:
    links = session.execute(
        select(DigitalObjectUnitLink, DigitalObject)
        .join(DigitalObject, DigitalObject.id == DigitalObjectUnitLink.digital_object_id)
        .where(DigitalObjectUnitLink.archival_unit_id == unit_id)
        .order_by(DigitalObject.original_filename, DigitalObject.id)
    ).all()
    result: list[CatalogDigitalObjectRow] = []
    for link, digital in links:
        files = session.scalars(
            select(FileInstance)
            .where(FileInstance.digital_object_id == digital.id)
            .order_by(FileInstance.relative_path)
        ).all()
        preprocessing = session.scalar(
            select(PreprocessingRun)
            .where(PreprocessingRun.digital_object_id == digital.id)
            .order_by(PreprocessingRun.is_current.desc(), PreprocessingRun.created_at.desc())
        )
        extraction = session.scalar(
            select(ExtractionRun)
            .where(ExtractionRun.digital_object_id == digital.id)
            .order_by(ExtractionRun.is_current.desc(), ExtractionRun.created_at.desc())
        )
        selected_pages = int(
            session.scalar(
                select(func.count()).select_from(ExtractionPageSelection).where(
                    ExtractionPageSelection.digital_object_id == digital.id
                )
            )
            or 0
        )
        editable_pages = int(
            session.scalar(
                select(func.count()).select_from(EditablePage).where(
                    EditablePage.digital_object_id == digital.id
                )
            )
            or 0
        )
        reviewed_pages = int(
            session.scalar(
                select(func.count()).select_from(EditablePage).where(
                    EditablePage.digital_object_id == digital.id,
                    EditablePage.review_status.in_(["reviewed", "approved"]),
                )
            )
            or 0
        )
        registration = session.scalar(
            select(SourceRegistration)
            .where(
                SourceRegistration.project_id == digital.project_id,
                SourceRegistration.digital_object_id == digital.id,
                SourceRegistration.source_type.in_(PROCESSABLE_SOURCE_TYPES),
            )
            .order_by(SourceRegistration.registered_at, SourceRegistration.id)
        )
        linked_unit_count = int(
            session.scalar(
                select(func.count()).select_from(DigitalObjectUnitLink).where(
                    DigitalObjectUnitLink.digital_object_id == digital.id
                )
            )
            or 0
        )
        result.append(
            CatalogDigitalObjectRow(
                id=digital.id,
                link_id=link.id,
                source_key=registration.source_key if registration else None,
                relation_type=link.relation_type,
                page_start=link.page_start,
                page_end=link.page_end,
                media_type=digital.media_type,
                original_filename=digital.original_filename,
                sha256=digital.sha256,
                byte_size=digital.byte_size,
                page_count=digital.page_count,
                preprocessing_status=preprocessing.status if preprocessing else "not_started",
                extraction_status=extraction.status if extraction else "not_started",
                selected_pages=selected_pages,
                editable_pages=editable_pages,
                reviewed_pages=reviewed_pages,
                linked_unit_count=linked_unit_count,
                files=[
                    CatalogFileRow(
                        id=item.id,
                        storage_root=item.storage_root,
                        relative_path=item.relative_path,
                        presence=item.presence,
                        byte_size_seen=item.byte_size_seen,
                        last_seen_at=item.last_seen_at,
                        verified_sha256=item.verified_sha256,
                    )
                    for item in files
                ],
            )
        )
    return result


def _safe_relative_path(value: str) -> str:
    raw = value.strip().replace("\\", "/")
    path = PurePosixPath(raw)
    if not raw or raw == "." or path.is_absolute() or ".." in path.parts:
        raise ValueError("La ruta debe ser relativa al proyecto y no puede contener '..'")
    return str(path)


def _ensure_catalog_source_registration(
    session: Session,
    *,
    project_id: str,
    unit: ArchivalUnit,
    digital: DigitalObject,
    registered_by: str,
    relative_path: str | None = None,
) -> SourceRegistration:
    existing = session.scalar(
        select(SourceRegistration)
        .where(
            SourceRegistration.project_id == project_id,
            SourceRegistration.digital_object_id == digital.id,
            SourceRegistration.source_type.in_(PROCESSABLE_SOURCE_TYPES),
        )
        .order_by(SourceRegistration.registered_at, SourceRegistration.id)
    )
    if existing is not None:
        if existing.source_type == "catalog" and relative_path:
            payload = dict(existing.source_payload_json or {})
            payload["local_path"] = relative_path
            existing.source_payload_json = payload
            existing.registered_at = _utc_now()
            existing.registered_by = registered_by
        return existing
    source_key = (
        f"catalog_{slugify(Path(digital.original_filename).stem, max_length=40)}_"
        f"{digital.id}"
    )
    registration = SourceRegistration(
        id=stable_id(_CATALOG_NAMESPACE, "source_registration", project_id, digital.id),
        project_id=project_id,
        source_type="catalog",
        source_key=source_key,
        digital_object_id=digital.id,
        archival_unit_id=unit.id,
        source_payload_json={
            "short_description": unit.title,
            "local_path": relative_path,
            "catalog_unit_id": unit.id,
            "catalog_level_key": unit.level_key,
            "origin": "catalog",
        },
        registered_by=registered_by,
    )
    session.add(registration)
    session.flush()
    return registration



def _safe_upload_filename(value: str) -> str:
    name = Path(value).name.strip()
    name = "".join(ch for ch in name if ord(ch) >= 32 and ch not in {"/", "\\"}).strip()
    if not name or name in {".", ".."}:
        raise ValueError("El archivo seleccionado no tiene un nombre válido")
    return name


def _uploaded_destination(
    project_root: Path,
    *,
    destination_dir: str,
    filename: str,
    content_sha256: str,
) -> tuple[Path, str, bool]:
    relative_dir = _safe_relative_path(destination_dir)
    root = project_root.resolve()
    directory = (root / relative_dir).resolve()
    try:
        directory.relative_to(root)
    except ValueError as exc:
        raise ValueError("La carpeta de destino sale del directorio del proyecto") from exc
    directory.mkdir(parents=True, exist_ok=True)
    clean_name = _safe_upload_filename(filename)
    stem = Path(clean_name).stem or "archivo"
    suffix = "".join(Path(clean_name).suffixes)
    candidate = directory / clean_name
    index = 2
    while candidate.exists():
        if candidate.is_file() and hashlib.sha256(candidate.read_bytes()).hexdigest() == content_sha256:
            relative = candidate.relative_to(root).as_posix()
            return candidate, relative, True
        candidate = directory / f"{stem}_{index}{suffix}"
        index += 1
    relative = candidate.relative_to(root).as_posix()
    return candidate, relative, False


def register_uploaded_file(
    session: Session,
    *,
    project_root: str | Path,
    project_id: str,
    archival_unit_id: str,
    original_filename: str,
    content: bytes,
    destination_dir: str = "corpus/importados",
    relation_type: str = "represents",
    page_start: int | None = None,
    page_end: int | None = None,
    registered_by: str = "local_user",
) -> RegisterUploadedFileResult:
    if not content:
        raise ValueError("El archivo seleccionado está vacío")
    root = Path(project_root).resolve()
    digest = hashlib.sha256(content).hexdigest()
    destination, relative_path, reused = _uploaded_destination(
        root,
        destination_dir=destination_dir,
        filename=original_filename,
        content_sha256=digest,
    )
    wrote_file = False
    if not reused:
        temporary = destination.with_name(destination.name + ".uploading")
        temporary.write_bytes(content)
        temporary.replace(destination)
        wrote_file = True
    try:
        registration = register_local_file(
            session,
            project_root=root,
            project_id=project_id,
            archival_unit_id=archival_unit_id,
            relative_path=relative_path,
            relation_type=relation_type,
            page_start=page_start,
            page_end=page_end,
            registered_by=registered_by,
        )
    except Exception:
        if wrote_file:
            destination.unlink(missing_ok=True)
        raise
    return RegisterUploadedFileResult(
        relative_path=relative_path,
        reused_existing_path=reused,
        registration=registration,
    )

def register_local_file(
    session: Session,
    *,
    project_root: str | Path,
    project_id: str,
    archival_unit_id: str,
    relative_path: str,
    relation_type: str = "represents",
    page_start: int | None = None,
    page_end: int | None = None,
    registered_by: str = "local_user",
) -> RegisterFileResult:
    unit = session.get(ArchivalUnit, archival_unit_id)
    if unit is None or unit.project_id != project_id:
        raise ValueError("La unidad archivística no existe en este proyecto")
    if relation_type not in RELATION_TYPES:
        raise ValueError(f"Tipo de relación inválido: {relation_type}")
    if page_start is not None and page_start < 1:
        raise ValueError("page_start debe ser >= 1")
    if page_end is not None and page_end < 1:
        raise ValueError("page_end debe ser >= 1")
    if page_start and page_end and page_end < page_start:
        raise ValueError("page_end no puede ser menor que page_start")
    relative = _safe_relative_path(relative_path)
    root = Path(project_root).resolve()
    path = (root / relative).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError("La ruta sale del directorio del proyecto") from exc
    if not path.is_file():
        raise FileNotFoundError(f"No existe el archivo: {path}")
    inspection = inspect_input(path)
    digital = session.scalar(
        select(DigitalObject).where(
            DigitalObject.project_id == project_id,
            DigitalObject.sha256 == inspection.sha256,
        )
    )
    duplicate_content = digital is not None
    digital_created = False
    if digital is None:
        digital = DigitalObject(
            id=stable_id(_CATALOG_NAMESPACE, "digital", project_id, inspection.sha256),
            project_id=project_id,
            media_type=inspection.media_type.value,
            original_filename=path.name,
            sha256=inspection.sha256,
            byte_size=inspection.byte_size,
            page_count=inspection.page_count,
        )
        session.add(digital)
        session.flush()
        digital_created = True
    file_instance = session.scalar(
        select(FileInstance).where(
            FileInstance.storage_root == "project",
            FileInstance.relative_path == relative,
        )
    )
    file_created = False
    stat = path.stat()
    if file_instance is None:
        file_instance = FileInstance(
            id=stable_id(_CATALOG_NAMESPACE, "file", "project", relative),
            digital_object_id=digital.id,
            storage_root="project",
            relative_path=relative,
            presence=FilePresence.PRESENT.value,
            byte_size_seen=stat.st_size,
            mtime_ns=stat.st_mtime_ns,
            last_seen_at=_utc_now(),
            verified_sha256=inspection.sha256,
        )
        session.add(file_instance)
        file_created = True
    else:
        file_instance.digital_object_id = digital.id
        file_instance.presence = FilePresence.PRESENT.value
        file_instance.byte_size_seen = stat.st_size
        file_instance.mtime_ns = stat.st_mtime_ns
        file_instance.last_seen_at = _utc_now()
        file_instance.verified_sha256 = inspection.sha256
    registration = _ensure_catalog_source_registration(
        session,
        project_id=project_id,
        unit=unit,
        digital=digital,
        registered_by=registered_by.strip() or "local_user",
        relative_path=relative,
    )
    link = session.scalar(
        select(DigitalObjectUnitLink).where(
            DigitalObjectUnitLink.digital_object_id == digital.id,
            DigitalObjectUnitLink.archival_unit_id == unit.id,
            DigitalObjectUnitLink.relation_type == relation_type,
            DigitalObjectUnitLink.page_start.is_(page_start) if page_start is None else DigitalObjectUnitLink.page_start == page_start,
            DigitalObjectUnitLink.page_end.is_(page_end) if page_end is None else DigitalObjectUnitLink.page_end == page_end,
        )
    )
    link_created = False
    if link is None:
        link = DigitalObjectUnitLink(
            id=new_id(),
            digital_object_id=digital.id,
            archival_unit_id=unit.id,
            relation_type=relation_type,
            page_start=page_start,
            page_end=page_end,
        )
        session.add(link)
        link_created = True
    if inspection.media_type in {MediaType.AUDIO, MediaType.VIDEO}:
        from archive_workbench.audiovisual import ensure_audiovisual_media

        ensure_audiovisual_media(
            session,
            project_root=root,
            digital_object_id=digital.id,
            actor=registered_by.strip() or "local_user",
        )
    session.flush()
    return RegisterFileResult(
        digital_object_id=digital.id,
        file_instance_id=file_instance.id,
        link_id=link.id,
        digital_object_created=digital_created,
        file_instance_created=file_created,
        link_created=link_created,
        duplicate_content=duplicate_content,
        source_key=registration.source_key,
    )


def link_existing_digital_object(
    session: Session,
    *,
    project_id: str,
    archival_unit_id: str,
    digital_object_id: str,
    relation_type: str = "represents",
    page_start: int | None = None,
    page_end: int | None = None,
    registered_by: str = "local_user",
) -> DigitalObjectUnitLink:
    unit = session.get(ArchivalUnit, archival_unit_id)
    digital = session.get(DigitalObject, digital_object_id)
    if unit is None or unit.project_id != project_id:
        raise ValueError("La unidad archivística no existe en este proyecto")
    if digital is None or digital.project_id != project_id:
        raise ValueError("El objeto digital no existe en este proyecto")
    if relation_type not in RELATION_TYPES:
        raise ValueError(f"Tipo de relación inválido: {relation_type}")
    if page_start is not None and page_start < 1:
        raise ValueError("page_start debe ser >= 1")
    if page_end is not None and page_end < 1:
        raise ValueError("page_end debe ser >= 1")
    if page_start and page_end and page_end < page_start:
        raise ValueError("page_end no puede ser menor que page_start")
    existing = session.scalar(
        select(DigitalObjectUnitLink).where(
            DigitalObjectUnitLink.digital_object_id == digital.id,
            DigitalObjectUnitLink.archival_unit_id == unit.id,
            DigitalObjectUnitLink.relation_type == relation_type,
            DigitalObjectUnitLink.page_start.is_(None)
            if page_start is None
            else DigitalObjectUnitLink.page_start == page_start,
            DigitalObjectUnitLink.page_end.is_(None)
            if page_end is None
            else DigitalObjectUnitLink.page_end == page_end,
        )
    )
    _ensure_catalog_source_registration(
        session,
        project_id=project_id,
        unit=unit,
        digital=digital,
        registered_by=registered_by.strip() or "local_user",
        relative_path=None,
    )
    if existing is not None:
        return existing
    row = DigitalObjectUnitLink(
        id=new_id(),
        digital_object_id=digital.id,
        archival_unit_id=unit.id,
        relation_type=relation_type,
        page_start=page_start,
        page_end=page_end,
    )
    session.add(row)
    session.flush()
    return row

def unlink_digital_object_from_unit(
    session: Session,
    *,
    link_id: str,
    removed_by: str = "local_user",
) -> UnlinkDigitalObjectResult:
    """Quita solamente el vínculo archivístico; conserva objeto digital e instancias locales."""
    link = session.get(DigitalObjectUnitLink, link_id)
    if link is None:
        raise ValueError("La asociación entre la unidad y el objeto digital no existe")
    unit = session.get(ArchivalUnit, link.archival_unit_id)
    digital = session.get(DigitalObject, link.digital_object_id)
    if unit is None or digital is None:
        raise ValueError("La asociación está incompleta y no puede quitarse de forma segura")
    actor = removed_by.strip() or "local_user"
    # El trigger de intercambio consulta esta procedencia para identificar al actor.
    registrations = session.scalars(
        select(SourceRegistration).where(
            SourceRegistration.digital_object_id == digital.id,
            SourceRegistration.source_type == "catalog",
        )
    ).all()
    for registration in registrations:
        registration.registered_by = actor
        registration.registered_at = _utc_now()
    session.flush()
    session.delete(link)
    session.flush()
    remaining = session.scalars(
        select(DigitalObjectUnitLink)
        .where(DigitalObjectUnitLink.digital_object_id == digital.id)
        .order_by(DigitalObjectUnitLink.id)
    ).all()
    replacement = remaining[0] if remaining else None
    for registration in registrations:
        if registration.archival_unit_id == unit.id:
            registration.archival_unit_id = replacement.archival_unit_id if replacement else None
            payload = dict(registration.source_payload_json or {})
            payload["catalog_unit_id"] = replacement.archival_unit_id if replacement else None
            if replacement:
                replacement_unit = session.get(ArchivalUnit, replacement.archival_unit_id)
                payload["catalog_level_key"] = replacement_unit.level_key if replacement_unit else None
                if replacement_unit:
                    payload["short_description"] = replacement_unit.title
            else:
                payload["catalog_level_key"] = None
            registration.source_payload_json = payload
    session.flush()
    return UnlinkDigitalObjectResult(
        link_id=link_id,
        archival_unit_id=unit.id,
        digital_object_id=digital.id,
        original_filename=digital.original_filename,
        remaining_links=len(remaining),
    )


def remove_file_instance(
    session: Session,
    *,
    project_root: str | Path,
    file_instance_id: str,
    delete_physical: bool = False,
    removed_by: str = "local_user",
) -> RemoveFileInstanceResult:
    """Quita una instancia local y, opcionalmente, el archivo físico bajo project_root."""
    instance = session.get(FileInstance, file_instance_id)
    if instance is None:
        raise ValueError("La instancia local del archivo no existe")
    digital = session.get(DigitalObject, instance.digital_object_id)
    if digital is None:
        raise ValueError("El objeto digital asociado no existe")
    root = Path(project_root).resolve()
    relative = _safe_relative_path(instance.relative_path)
    physical = (root / relative).resolve()
    try:
        physical.relative_to(root)
    except ValueError as exc:
        raise ValueError("La ruta del archivo sale del proyecto") from exc
    physical_deleted = False
    if delete_physical:
        if physical.exists() and not physical.is_file():
            raise ValueError("La ruta registrada no corresponde a un archivo regular")
        if physical.is_file():
            physical.unlink()
            physical_deleted = True
    digital_id = digital.id
    session.delete(instance)
    session.flush()
    remaining = session.scalars(
        select(FileInstance)
        .where(FileInstance.digital_object_id == digital_id)
        .order_by(FileInstance.relative_path)
    ).all()
    replacement_path = remaining[0].relative_path if remaining else None
    for registration in session.scalars(
        select(SourceRegistration).where(
            SourceRegistration.digital_object_id == digital_id,
            SourceRegistration.source_type == "catalog",
        )
    ).all():
        payload = dict(registration.source_payload_json or {})
        if payload.get("local_path") == relative:
            payload["local_path"] = replacement_path
            registration.source_payload_json = payload
            registration.registered_by = removed_by.strip() or "local_user"
            registration.registered_at = _utc_now()
    session.flush()
    return RemoveFileInstanceResult(
        file_instance_id=file_instance_id,
        digital_object_id=digital_id,
        relative_path=relative,
        physical_deleted=physical_deleted,
        remaining_instances=len(remaining),
    )


@dataclass(slots=True)
class DigitalObjectChoice:
    id: str
    original_filename: str
    media_type: str
    page_count: int | None
    sha256: str


def digital_object_choices(session: Session, project_id: str) -> list[DigitalObjectChoice]:
    rows = session.scalars(
        select(DigitalObject)
        .where(DigitalObject.project_id == project_id)
        .order_by(DigitalObject.original_filename, DigitalObject.id)
    ).all()
    return [
        DigitalObjectChoice(
            id=row.id,
            original_filename=row.original_filename,
            media_type=row.media_type,
            page_count=row.page_count,
            sha256=row.sha256,
        )
        for row in rows
    ]
