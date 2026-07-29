from __future__ import annotations

import hashlib
import json
import sqlite3
import zipfile
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from archive_workbench.contracts.changes import (
    BundleInspection,
    ChangeBundleManifest,
    ChangeEvent,
)
from archive_workbench.db.models import (
    EditableObject,
    EditableObjectRevision,
    EditableObjectComment,
    EditableObjectTag,
    EditablePage,
    EntityMention,
    EntityMentionRevision,
    EntityRelation,
    EntityRelationRevision,
    DocumentPart,
    ArchivalFieldValue,
    ArchivalUnit,
    ArchivalUnitRevision,
    AuthorityAlias,
    AuthorityRecord,
    AuthorityRevision,
    DigitalObject,
    DigitalObjectUnitLink,
    ExtractionPage,
    ExtractionPageSelection,
    SourceRegistration,
    WorkAssignment,
    WorkAssignmentRevision,
    ExchangeBundleApplication,
    ExchangeBundleRecord,
    ExchangeChangeEvent,
    ExchangeCheckpoint,
    ExchangeConflictResolution,
    ExchangeWorkspace,
    Project,
    utc_now,
)
from archive_workbench.identity import new_id, sha256_file, sha256_json, short_id, slugify
from archive_workbench.version import __version__


@dataclass(slots=True)
class ExchangeStatus:
    workspace_id: str
    workspace_name: str
    project_id: str
    current_sequence: int
    checkpoint_count: int
    last_checkpoint_label: str | None
    last_checkpoint_sequence: int | None
    pending_event_count: int
    exported_bundle_count: int


@dataclass(slots=True)
class CheckpointRow:
    checkpoint_id: str
    label: str
    sequence_number: int
    state_sha256: str
    created_by: str
    created_at: datetime
    note: str | None


@dataclass(slots=True)
class BundleExportSummary:
    bundle_id: str
    output_path: Path
    bundle_sha256: str
    event_count: int
    base_sequence: int
    last_sequence: int
    next_checkpoint_id: str
    next_checkpoint_label: str


def _iso_utc(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _jsonl_bytes(rows: Iterable[dict[str, Any]]) -> bytes:
    payload = b""
    for row in rows:
        payload += _canonical_json_bytes(row) + b"\n"
    return payload


def _project(session: Session) -> Project:
    rows = session.scalars(select(Project).order_by(Project.created_at, Project.id)).all()
    if not rows:
        raise ValueError("El proyecto todavía no está registrado en SQLite")
    if len(rows) > 1:
        raise ValueError("La base contiene más de un proyecto; el intercambio requiere uno solo")
    return rows[0]


def ensure_exchange_workspace(
    session: Session,
    *,
    workspace_name: str | None = None,
    changed_by: str = "local_user",
) -> ExchangeWorkspace:
    project = _project(session)
    workspace = session.scalar(
        select(ExchangeWorkspace).order_by(ExchangeWorkspace.created_at, ExchangeWorkspace.id)
    )
    if workspace is None:
        workspace = ExchangeWorkspace(
            id=new_id(),
            project_id=project.id,
            workspace_name=(workspace_name or "local_workspace").strip() or "local_workspace",
            created_by=changed_by,
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        session.add(workspace)
        session.flush()
        return workspace
    workspace.project_id = project.id
    if workspace_name is not None:
        clean = workspace_name.strip()
        if not clean:
            raise ValueError("El nombre de la copia no puede estar vacío")
        workspace.workspace_name = clean
    if workspace.created_by == "system":
        workspace.created_by = changed_by
    workspace.updated_at = utc_now()
    session.flush()
    return workspace


def _current_sequence(session: Session, workspace_id: str) -> int:
    return int(
        session.scalar(
            select(func.max(ExchangeChangeEvent.sequence_number)).where(
                ExchangeChangeEvent.workspace_id == workspace_id
            )
        )
        or 0
    )


def _editable_state_payload(session: Session, project_id: str) -> dict[str, Any]:
    pages = session.scalars(
        select(EditablePage)
        .join(DigitalObject, DigitalObject.id == EditablePage.digital_object_id)
        .where(DigitalObject.project_id == project_id)
        .order_by(EditablePage.digital_object_id, EditablePage.page_number)
    ).all()
    objects = session.scalars(
        select(EditableObject)
        .join(DigitalObject, DigitalObject.id == EditableObject.digital_object_id)
        .where(DigitalObject.project_id == project_id)
        .order_by(
            EditableObject.digital_object_id,
            EditableObject.page_number,
            EditableObject.current_order_index,
            EditableObject.id,
        )
    ).all()
    comments = session.scalars(
        select(EditableObjectComment).order_by(
            EditableObjectComment.editable_object_id,
            EditableObjectComment.created_at,
            EditableObjectComment.id,
        )
    ).all()
    tags = session.scalars(
        select(EditableObjectTag).order_by(
            EditableObjectTag.editable_object_id,
            EditableObjectTag.tag_kind,
            EditableObjectTag.normalized_tag,
            EditableObjectTag.id,
        )
    ).all()
    units = session.scalars(
        select(ArchivalUnit)
        .where(ArchivalUnit.project_id == project_id)
        .order_by(ArchivalUnit.id)
    ).all()
    unit_ids = [row.id for row in units]
    field_rows = session.scalars(
        select(ArchivalFieldValue)
        .where(ArchivalFieldValue.archival_unit_id.in_(unit_ids))
        .order_by(
            ArchivalFieldValue.archival_unit_id,
            ArchivalFieldValue.field_key,
            ArchivalFieldValue.sort_order,
        )
    ).all() if unit_ids else []
    fields_by_unit: dict[str, list[dict[str, Any]]] = {unit_id: [] for unit_id in unit_ids}
    for row in field_rows:
        fields_by_unit.setdefault(row.archival_unit_id, []).append(
            {
                "field_key": row.field_key,
                "value_state": row.value_state,
                "value": row.value_json,
                "sort_order": row.sort_order,
                "source_note": row.source_note,
            }
        )
    authorities = session.scalars(
        select(AuthorityRecord)
        .where(AuthorityRecord.project_id == project_id)
        .order_by(AuthorityRecord.id)
    ).all()
    authority_ids = [row.id for row in authorities]
    authority_aliases = session.scalars(
        select(AuthorityAlias)
        .where(AuthorityAlias.authority_id.in_(authority_ids))
        .order_by(AuthorityAlias.authority_id, AuthorityAlias.normalized_alias, AuthorityAlias.id)
    ).all() if authority_ids else []
    aliases_by_authority: dict[str, list[AuthorityAlias]] = {
        authority_id: [] for authority_id in authority_ids
    }
    for alias in authority_aliases:
        aliases_by_authority.setdefault(alias.authority_id, []).append(alias)
    mentions = session.scalars(
        select(EntityMention)
        .join(EditableObject, EditableObject.id == EntityMention.editable_object_id)
        .join(DigitalObject, DigitalObject.id == EditableObject.digital_object_id)
        .where(DigitalObject.project_id == project_id)
        .order_by(EntityMention.editable_object_id, EntityMention.start_offset, EntityMention.id)
    ).all()
    relations = session.scalars(
        select(EntityRelation)
        .where(EntityRelation.project_id == project_id)
        .order_by(EntityRelation.id)
    ).all()
    assignments = session.scalars(
        select(WorkAssignment)
        .where(WorkAssignment.project_id == project_id)
        .order_by(WorkAssignment.id)
    ).all()

    links = session.execute(
        select(DigitalObjectUnitLink, DigitalObject)
        .join(DigitalObject, DigitalObject.id == DigitalObjectUnitLink.digital_object_id)
        .where(DigitalObject.project_id == project_id)
        .order_by(DigitalObjectUnitLink.id)
    ).all()
    return {
        "project_id": project_id,
        "pages": [
            {
                "id": row.id,
                "digital_object_id": row.digital_object_id,
                "page_number": row.page_number,
                "status": row.status,
                "review_status": row.review_status,
                "review_note": row.review_note,
            }
            for row in pages
        ],
        "objects": [
            {
                "id": row.id,
                "editable_page_id": row.editable_page_id,
                "digital_object_id": row.digital_object_id,
                "page_number": row.page_number,
                "document_part_id": row.document_part_id,
                "source_extracted_object_id": row.source_extracted_object_id,
                "text": row.current_text,
                "object_type": row.current_object_type,
                "order_index": row.current_order_index,
                "geometry": row.current_geometry_json or [],
                "attributes": row.current_attributes_json or {},
                "lifecycle_status": row.lifecycle_status,
                "review_status": row.review_status,
                "revision_number": row.revision_number,
            }
            for row in objects
        ],
        "comments": [
            {
                "id": row.id,
                "editable_object_id": row.editable_object_id,
                "body": row.body,
                "created_by": row.created_by,
                "created_at": row.created_at.isoformat(),
            }
            for row in comments
        ],
        "tags": [
            {
                "id": row.id,
                "editable_object_id": row.editable_object_id,
                "tag": row.tag,
                "normalized_tag": row.normalized_tag,
                "tag_kind": row.tag_kind,
                "created_by": row.created_by,
                "created_at": row.created_at.isoformat(),
            }
            for row in tags
        ],
        "authorities": [
            {
                "id": row.id,
                "entity_type": row.entity_type,
                "preferred_name": row.preferred_name,
                "normalized_name": row.normalized_name,
                "description": row.description,
                "temporal_expression": row.temporal_expression,
                "temporal_start": row.temporal_start.isoformat() if row.temporal_start else None,
                "temporal_end": row.temporal_end.isoformat() if row.temporal_end else None,
                "temporal_precision": row.temporal_precision,
                "temporal_approximate": bool(row.temporal_approximate),
                "temporal_note": row.temporal_note,
                "lifecycle_status": row.lifecycle_status,
                "review_status": row.review_status,
                "revision": row.revision,
                "aliases": [
                    {
                        "id": alias.id,
                        "alias": alias.alias,
                        "normalized_alias": alias.normalized_alias,
                        "alias_type": alias.alias_type,
                        "note": alias.note,
                        "created_by": alias.created_by,
                        "created_at": alias.created_at.isoformat(),
                    }
                    for alias in aliases_by_authority.get(row.id, [])
                ],
            }
            for row in authorities
        ],
        "entity_mentions": [
            {
                "id": row.id,
                "editable_object_id": row.editable_object_id,
                "authority_id": row.authority_id,
                "mention_text": row.mention_text,
                "normalized_text": row.normalized_text,
                "start_offset": row.start_offset,
                "end_offset": row.end_offset,
                "object_revision_number": row.object_revision_number,
                "status": row.status,
                "source": row.source,
                "confidence": row.confidence,
                "note": row.note,
                "revision": row.revision,
            }
            for row in mentions
        ],
        "entity_relations": [
            {
                "id": row.id,
                "source_authority_id": row.source_authority_id,
                "relation_label": row.relation_label,
                "target_authority_id": row.target_authority_id,
                "target_archival_unit_id": row.target_archival_unit_id,
                "target_document_part_id": row.target_document_part_id,
                "evidence_note": row.evidence_note,
                "temporal_expression": row.temporal_expression,
                "temporal_start": row.temporal_start.isoformat() if row.temporal_start else None,
                "temporal_end": row.temporal_end.isoformat() if row.temporal_end else None,
                "temporal_precision": row.temporal_precision,
                "temporal_approximate": bool(row.temporal_approximate),
                "temporal_note": row.temporal_note,
                "lifecycle_status": row.lifecycle_status,
                "review_status": row.review_status,
                "revision": row.revision,
            }
            for row in relations
        ],
        "work_assignments": [
            {
                "id": row.id,
                "source_type": row.source_type,
                "source_key": row.source_key,
                "page_start": row.page_start,
                "page_end": row.page_end,
                "assignment_kind": row.assignment_kind,
                "assignee": row.assignee,
                "status": row.status,
                "priority": row.priority,
                "due_at": _iso_utc(row.due_at),
                "parent_assignment_id": row.parent_assignment_id,
                "outcome": row.outcome,
                "note": row.note,
                "submitted_at": _iso_utc(row.submitted_at),
                "completed_at": _iso_utc(row.completed_at),
                "revision": row.revision,
            }
            for row in assignments
        ],
        "catalog_units": [
            {
                "id": row.id,
                "parent_id": row.parent_id,
                "level_key": row.level_key,
                "reference_code": row.reference_code,
                "title": row.title,
                "registration_status": row.registration_status,
                "completion_confirmed": bool(row.completion_confirmed),
                "completion_confirmed_at": (
                    row.completion_confirmed_at.isoformat()
                    if row.completion_confirmed_at else None
                ),
                "completion_confirmed_by": row.completion_confirmed_by,
                "revision": row.revision,
                "fields": fields_by_unit.get(row.id, []),
            }
            for row in units
        ],
        "digital_links": [
            {
                "id": link.id,
                "digital_object_id": link.digital_object_id,
                "archival_unit_id": link.archival_unit_id,
                "relation_type": link.relation_type,
                "page_start": link.page_start,
                "page_end": link.page_end,
                "digital": {
                    "project_id": digital.project_id,
                    "media_type": digital.media_type,
                    "original_filename": digital.original_filename,
                    "sha256": digital.sha256,
                    "byte_size": digital.byte_size,
                    "page_count": digital.page_count,
                },
            }
            for link, digital in links
        ],
    }


def current_editable_state_sha256(session: Session, project_id: str) -> str:
    return sha256_json(_editable_state_payload(session, project_id))


def create_exchange_checkpoint(
    session: Session,
    *,
    label: str,
    created_by: str,
    note: str | None = None,
    workspace_name: str | None = None,
) -> ExchangeCheckpoint:
    workspace = ensure_exchange_workspace(
        session, workspace_name=workspace_name, changed_by=created_by
    )
    clean = label.strip()
    if not clean:
        raise ValueError("La etiqueta del checkpoint no puede estar vacía")
    existing = session.scalar(
        select(ExchangeCheckpoint).where(
            ExchangeCheckpoint.workspace_id == workspace.id,
            ExchangeCheckpoint.label == clean,
        )
    )
    if existing is not None:
        raise ValueError(f"Ya existe un checkpoint con la etiqueta: {clean}")
    assert workspace.project_id is not None
    checkpoint = ExchangeCheckpoint(
        id=new_id(),
        workspace_id=workspace.id,
        project_id=workspace.project_id,
        sequence_number=_current_sequence(session, workspace.id),
        label=clean,
        note=note.strip() if note and note.strip() else None,
        state_sha256=current_editable_state_sha256(session, workspace.project_id),
        created_by=created_by,
        created_at=utc_now(),
    )
    session.add(checkpoint)
    session.flush()
    return checkpoint


def checkpoint_rows(session: Session) -> list[CheckpointRow]:
    workspace = ensure_exchange_workspace(session)
    rows = session.scalars(
        select(ExchangeCheckpoint)
        .where(ExchangeCheckpoint.workspace_id == workspace.id)
        .order_by(ExchangeCheckpoint.sequence_number, ExchangeCheckpoint.created_at)
    ).all()
    return [
        CheckpointRow(
            checkpoint_id=row.id,
            label=row.label,
            sequence_number=row.sequence_number,
            state_sha256=row.state_sha256,
            created_by=row.created_by,
            created_at=row.created_at,
            note=row.note,
        )
        for row in rows
    ]


def exchange_status(session: Session) -> ExchangeStatus:
    workspace = ensure_exchange_workspace(session)
    current = _current_sequence(session, workspace.id)
    checkpoints = session.scalars(
        select(ExchangeCheckpoint)
        .where(ExchangeCheckpoint.workspace_id == workspace.id)
        .order_by(ExchangeCheckpoint.sequence_number.desc(), ExchangeCheckpoint.created_at.desc())
    ).all()
    last = checkpoints[0] if checkpoints else None
    bundles = int(
        session.scalar(
            select(func.count()).select_from(ExchangeBundleRecord).where(
                ExchangeBundleRecord.workspace_id == workspace.id,
                ExchangeBundleRecord.direction == "outgoing",
            )
        )
        or 0
    )
    last_sequence = last.sequence_number if last else 0
    assert workspace.project_id is not None
    return ExchangeStatus(
        workspace_id=workspace.id,
        workspace_name=workspace.workspace_name,
        project_id=workspace.project_id,
        current_sequence=current,
        checkpoint_count=len(checkpoints),
        last_checkpoint_label=last.label if last else None,
        last_checkpoint_sequence=last.sequence_number if last else None,
        pending_event_count=max(0, current - last_sequence),
        exported_bundle_count=bundles,
    )


def _resolve_checkpoint(
    session: Session, workspace_id: str, checkpoint_ref: str | None
) -> ExchangeCheckpoint:
    query = select(ExchangeCheckpoint).where(ExchangeCheckpoint.workspace_id == workspace_id)
    if checkpoint_ref:
        row = session.scalar(
            query.where(
                (ExchangeCheckpoint.id == checkpoint_ref)
                | (ExchangeCheckpoint.label == checkpoint_ref)
            )
        )
        if row is None:
            raise ValueError(f"Checkpoint inexistente: {checkpoint_ref}")
        return row
    row = session.scalar(
        query.order_by(
            ExchangeCheckpoint.sequence_number.desc(), ExchangeCheckpoint.created_at.desc()
        )
    )
    if row is None:
        raise ValueError(
            "Todavía no hay checkpoints. Creá uno con exchange-checkpoint antes de exportar."
        )
    return row


def _event_contract(row: ExchangeChangeEvent) -> ChangeEvent:
    if row.project_id is None:
        raise ValueError(f"El evento {row.id} no tiene project_id")
    return ChangeEvent(
        event_id=row.id,
        project_id=row.project_id,
        workspace_id=row.workspace_id,
        sequence_number=row.sequence_number,
        transaction_id=row.transaction_id,
        entity_type=row.entity_type,
        entity_id=row.entity_id,
        operation=row.operation,
        base_revision=row.base_revision,
        new_revision=row.new_revision,
        changed_fields=row.changed_fields_json or {},
        actor=row.actor,
        timestamp=row.occurred_at,
    )


def _write_zip(path: Path, entries: dict[str, bytes]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    with zipfile.ZipFile(temp, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name in sorted(entries):
            info = zipfile.ZipInfo(name)
            info.date_time = (1980, 1, 1, 0, 0, 0)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o600 << 16
            archive.writestr(info, entries[name])
    temp.replace(path)


def export_change_bundle(
    session: Session,
    *,
    project_root: Path,
    checkpoint_ref: str | None,
    created_by: str,
    destination: Path | None = None,
) -> BundleExportSummary:
    workspace = ensure_exchange_workspace(session, changed_by=created_by)
    checkpoint = _resolve_checkpoint(session, workspace.id, checkpoint_ref)
    current_sequence = _current_sequence(session, workspace.id)
    rows = session.scalars(
        select(ExchangeChangeEvent)
        .where(
            ExchangeChangeEvent.workspace_id == workspace.id,
            ExchangeChangeEvent.sequence_number > checkpoint.sequence_number,
            ExchangeChangeEvent.sequence_number <= current_sequence,
        )
        .order_by(ExchangeChangeEvent.sequence_number)
    ).all()
    events = [_event_contract(row) for row in rows]
    imported_objects: list[ChangeEvent] = []
    imported_pages: set[tuple[str, int]] = set()
    imported_documents: set[str] = set()
    for event in events:
        if (
            event.entity_type == "editable_object"
            and event.operation.value == "create"
            and _new_value(event.changed_fields, "source_extracted_object_id") is not None
        ):
            imported_objects.append(event)
            digital_object_id = _new_value(event.changed_fields, "digital_object_id")
            page_number = _new_value(event.changed_fields, "page_number")
            if isinstance(digital_object_id, str):
                imported_documents.add(digital_object_id)
                if isinstance(page_number, int):
                    imported_pages.add((digital_object_id, page_number))
    if imported_objects:
        raise ValueError(
            "El rango solicitado contiene "
            f"{len(imported_objects)} objetos OCR inicializados después del checkpoint, "
            f"distribuidos en {len(imported_pages)} páginas de "
            f"{len(imported_documents)} documentos. Los bundles de cambios no transportan "
            "corridas, páginas ni selecciones de extracción. Creá una nueva copia física del "
            "proyecto después de inicializar la capa editable, ejecutá exchange-fork-copy en "
            "la receptora y establecé un nuevo checkpoint común antes de intercambiar ediciones."
        )
    changes_bytes = _jsonl_bytes(
        event.model_dump(mode="json", exclude_none=True) for event in events
    )
    changes_sha = hashlib.sha256(changes_bytes).hexdigest()
    bundle_id = new_id()
    assert workspace.project_id is not None
    from archive_workbench.db.migrations import current_revision

    manifest = ChangeBundleManifest(
        project_id=workspace.project_id,
        bundle_id=bundle_id,
        source_workspace_id=workspace.id,
        source_workspace_name=workspace.workspace_name,
        app_version=__version__,
        database_revision=current_revision(project_root) or "unknown",
        created_by=created_by,
        base_checkpoint_id=checkpoint.id,
        base_checkpoint_label=checkpoint.label,
        base_checkpoint_state_sha256=checkpoint.state_sha256,
        base_sequence=checkpoint.sequence_number,
        last_sequence=current_sequence,
        event_count=len(events),
        changes_sha256=changes_sha,
        attachment_checksums={},
    )
    manifest_bytes = _canonical_json_bytes(
        manifest.model_dump(mode="json", exclude_none=True)
    ) + b"\n"
    checksums = (
        f"{hashlib.sha256(manifest_bytes).hexdigest()}  manifest.json\n"
        f"{changes_sha}  changes.jsonl\n"
    ).encode("utf-8")
    readme = (
        "Archive Workbench — bundle de cambios offline\n"
        "Este paquete es verificable. Use dry-run antes de cualquier aplicación futura.\n"
        "Use exchange-inspect-bundle antes de transferirlo o archivarlo.\n"
    ).encode("utf-8")
    if destination is None:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        destination = (
            project_root
            / "exchange"
            / "outgoing"
            / f"{timestamp}_{slugify(workspace.workspace_name, 40)}_{short_id(bundle_id)}.zip"
        )
    destination = destination.expanduser().resolve()
    _write_zip(
        destination,
        {
            "README.txt": readme,
            "changes.jsonl": changes_bytes,
            "checksums.sha256": checksums,
            "manifest.json": manifest_bytes,
        },
    )
    bundle_sha = sha256_file(destination)
    relative_path: str | None
    try:
        relative_path = destination.relative_to(project_root.resolve()).as_posix()
    except ValueError:
        relative_path = str(destination)
    record = ExchangeBundleRecord(
        id=new_id(),
        workspace_id=workspace.id,
        bundle_id=bundle_id,
        direction="outgoing",
        bundle_sha256=bundle_sha,
        relative_path=relative_path,
        base_sequence=checkpoint.sequence_number,
        last_sequence=current_sequence,
        event_count=len(events),
        status="exported",
        counterpart_workspace_id=None,
        created_by=created_by,
        created_at=utc_now(),
    )
    session.add(record)
    session.flush()
    next_label = f"bundle_{short_id(bundle_id)}"
    next_checkpoint = create_exchange_checkpoint(
        session,
        label=next_label,
        created_by=created_by,
        note=f"Checkpoint creado después de exportar el bundle {bundle_id}",
    )
    return BundleExportSummary(
        bundle_id=bundle_id,
        output_path=destination,
        bundle_sha256=bundle_sha,
        event_count=len(events),
        base_sequence=checkpoint.sequence_number,
        last_sequence=current_sequence,
        next_checkpoint_id=next_checkpoint.id,
        next_checkpoint_label=next_checkpoint.label,
    )


def inspect_change_bundle(path: Path) -> BundleInspection:
    bundle_path = path.expanduser().resolve()
    if not bundle_path.is_file():
        raise ValueError(f"No existe el bundle: {bundle_path}")
    allowed = {"README.txt", "changes.jsonl", "checksums.sha256", "manifest.json"}
    with zipfile.ZipFile(bundle_path, "r") as archive:
        names = set(archive.namelist())
        unsafe = [name for name in names if Path(name).is_absolute() or ".." in Path(name).parts]
        if unsafe:
            raise ValueError("El ZIP contiene rutas inseguras")
        missing = {"manifest.json", "changes.jsonl", "checksums.sha256"} - names
        if missing:
            raise ValueError("Faltan archivos obligatorios: " + ", ".join(sorted(missing)))
        extra = names - allowed
        manifest_bytes = archive.read("manifest.json")
        changes_bytes = archive.read("changes.jsonl")
        checksums_bytes = archive.read("checksums.sha256")
    manifest = ChangeBundleManifest.model_validate_json(manifest_bytes)
    actual_changes_sha = hashlib.sha256(changes_bytes).hexdigest()
    if actual_changes_sha != manifest.changes_sha256:
        raise ValueError("El checksum de changes.jsonl no coincide con el manifest")
    expected: dict[str, str] = {}
    for raw in checksums_bytes.decode("utf-8").splitlines():
        if not raw.strip():
            continue
        digest, name = raw.split(maxsplit=1)
        expected[name.strip()] = digest
    for name, payload in (("manifest.json", manifest_bytes), ("changes.jsonl", changes_bytes)):
        if expected.get(name) != hashlib.sha256(payload).hexdigest():
            raise ValueError(f"Checksum inválido para {name}")
    events: list[ChangeEvent] = []
    for line_number, raw in enumerate(changes_bytes.splitlines(), start=1):
        if not raw.strip():
            continue
        try:
            event = ChangeEvent.model_validate_json(raw)
        except Exception as exc:  # Pydantic agrega el detalle exacto.
            raise ValueError(f"Evento inválido en changes.jsonl, línea {line_number}: {exc}") from exc
        events.append(event)
    if len(events) != manifest.event_count:
        raise ValueError(
            f"El manifest declara {manifest.event_count} eventos y el archivo contiene {len(events)}"
        )
    sequences = [event.sequence_number for event in events]
    if sequences != sorted(sequences) or len(sequences) != len(set(sequences)):
        raise ValueError("Los eventos no tienen una secuencia estrictamente creciente")
    if events:
        if sequences[0] <= manifest.base_sequence or sequences[-1] != manifest.last_sequence:
            raise ValueError("El rango de secuencias no coincide con el manifest")
        for event in events:
            if event.project_id != manifest.project_id:
                raise ValueError("Un evento pertenece a otro proyecto")
            if event.workspace_id != manifest.source_workspace_id:
                raise ValueError("Un evento pertenece a otra copia de trabajo")
    elif manifest.last_sequence != manifest.base_sequence:
        raise ValueError("Un bundle vacío debe tener el mismo inicio y final de secuencia")
    warnings: list[str] = []
    if extra:
        warnings.append("Archivos adicionales ignorados: " + ", ".join(sorted(extra)))
    return BundleInspection(
        manifest=manifest,
        bundle_sha256=sha256_file(bundle_path),
        event_count=len(events),
        first_sequence=sequences[0] if sequences else None,
        last_sequence=sequences[-1] if sequences else None,
        warnings=warnings,
    )


@dataclass(slots=True)
class BundleDryRunSummary:
    bundle_id: str
    bundle_sha256: str
    source_workspace_id: str
    source_workspace_name: str
    common_checkpoint_id: str | None
    common_checkpoint_label: str | None
    base_match_status: str
    overall_status: str
    counts: dict[str, int]
    report_json_path: Path
    report_markdown_path: Path
    repeated_assessment: bool


@dataclass(slots=True)
class IncomingBundleRow:
    bundle_id: str
    source_workspace_name: str
    source_workspace_id: str
    event_count: int
    status: str
    base_match_status: str
    counts: dict[str, int]
    assessed_by: str
    assessed_at: datetime
    report_markdown_path: str | None


def _load_bundle_events(
    path: Path,
) -> tuple[BundleInspection, list[ChangeEvent], list[str]]:
    inspection = inspect_change_bundle(path)
    with zipfile.ZipFile(path.expanduser().resolve(), "r") as archive:
        changes_bytes = archive.read("changes.jsonl")
    events: list[ChangeEvent] = []
    normalization_warnings: list[str] = []
    for raw in changes_bytes.splitlines():
        if not raw.strip():
            continue
        event, warning = _normalize_incoming_event(ChangeEvent.model_validate_json(raw))
        events.append(event)
        if warning:
            normalization_warnings.append(warning)
    return inspection, events, normalization_warnings


def _relative_or_absolute(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def _known_database_revisions() -> set[str]:
    versions = Path(__file__).with_name("migrations") / "versions"
    return {path.stem for path in versions.glob("*.py") if not path.name.startswith("__")}


def _matching_checkpoint(
    session: Session, *, workspace_id: str, state_sha256: str
) -> ExchangeCheckpoint | None:
    return session.scalar(
        select(ExchangeCheckpoint)
        .where(
            ExchangeCheckpoint.workspace_id == workspace_id,
            ExchangeCheckpoint.state_sha256 == state_sha256,
        )
        .order_by(
            ExchangeCheckpoint.sequence_number.desc(), ExchangeCheckpoint.created_at.desc()
        )
    )


def _lineage_checkpoint_from_applied_bundle(
    session: Session,
    *,
    workspace_id: str,
    source_workspace_id: str,
    base_checkpoint_label: str,
    base_sequence: int,
) -> ExchangeCheckpoint | None:
    """Reconoce una base remota por un bundle previamente aplicado.

    El hash del checkpoint local puede diferir del remoto cuando la aplicación
    anterior conservó una resolución local. Esa divergencia no invalida la
    ascendencia: el registro de aplicación conserva qué bundle del origen fue
    incorporado y hasta qué secuencia remota llegó.
    """
    prefix = "bundle_"
    if not base_checkpoint_label.startswith(prefix):
        return None
    short_bundle_id = base_checkpoint_label[len(prefix) :].strip()
    if not short_bundle_id:
        return None

    rows = session.execute(
        select(ExchangeBundleApplication.checkpoint_id, ExchangeBundleRecord.bundle_id)
        .join(
            ExchangeBundleRecord,
            ExchangeBundleRecord.id == ExchangeBundleApplication.bundle_record_id,
        )
        .where(
            ExchangeBundleApplication.workspace_id == workspace_id,
            ExchangeBundleApplication.source_workspace_id == source_workspace_id,
            ExchangeBundleApplication.status == "applied",
            ExchangeBundleApplication.checkpoint_id.is_not(None),
            ExchangeBundleRecord.direction == "incoming",
            ExchangeBundleRecord.status == "applied",
            ExchangeBundleRecord.last_sequence == base_sequence,
            ExchangeBundleRecord.bundle_id.like(f"{short_bundle_id}%"),
        )
        .order_by(ExchangeBundleApplication.applied_at.desc())
    ).all()
    if len(rows) != 1:
        return None
    checkpoint_id, _bundle_id = rows[0]
    checkpoint = session.get(ExchangeCheckpoint, checkpoint_id)
    if checkpoint is None or checkpoint.workspace_id != workspace_id:
        return None
    return checkpoint


def _entity_exists(session: Session, entity_type: str, entity_id: str) -> bool:
    model = {
        "editable_object": EditableObject,
        "editable_page": EditablePage,
        "editable_object_comment": EditableObjectComment,
        "editable_object_tag": EditableObjectTag,
        "archival_unit": ArchivalUnit,
        "digital_object_unit_link": DigitalObjectUnitLink,
        "authority_record": AuthorityRecord,
        "entity_mention": EntityMention,
        "entity_relation": EntityRelation,
        "work_assignment": WorkAssignment,
    }.get(entity_type)
    return bool(model is not None and session.get(model, entity_id) is not None)


def _new_value(changed_fields: dict[str, Any], field: str) -> Any:
    value = changed_fields.get(field)
    if isinstance(value, list) and len(value) == 2:
        return value[1]
    return None


def _exchange_values_equal(left: Any, right: Any) -> bool:
    """Compara valores de eventos tolerando serializaciones equivalentes."""
    if left == right:
        return True
    if isinstance(left, dict) and isinstance(right, dict):
        return set(left) == set(right) and all(
            _exchange_values_equal(left[key], right[key]) for key in left
        )
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(
            _exchange_values_equal(a, b) for a, b in zip(left, right)
        )
    if isinstance(left, str) and isinstance(right, str) and "T" in left and "T" in right:
        try:
            left_dt = datetime.fromisoformat(left.replace("Z", "+00:00"))
            right_dt = datetime.fromisoformat(right.replace("Z", "+00:00"))
        except ValueError:
            return False
        if left_dt.tzinfo is None:
            left_dt = left_dt.replace(tzinfo=timezone.utc)
        if right_dt.tzinfo is None:
            right_dt = right_dt.replace(tzinfo=timezone.utc)
        return left_dt.astimezone(timezone.utc) == right_dt.astimezone(timezone.utc)
    return False


def _editable_page_materialization_source(
    session: Session, *, digital_object_id: str, page_number: int
) -> tuple[ExtractionPageSelection, ExtractionPage] | None:
    """Devuelve la selección local necesaria para materializar una página editable."""
    if session.get(DigitalObject, digital_object_id) is None:
        return None
    selection = session.scalar(
        select(ExtractionPageSelection).where(
            ExtractionPageSelection.digital_object_id == digital_object_id,
            ExtractionPageSelection.page_number == page_number,
        )
    )
    if selection is None:
        return None
    extraction_page = session.get(ExtractionPage, selection.extraction_page_id)
    if (
        extraction_page is None
        or extraction_page.extraction_run_id != selection.extraction_run_id
        or extraction_page.page_number != page_number
    ):
        return None
    return selection, extraction_page


def _catalog_unit_values(session: Session, unit: ArchivalUnit) -> dict[str, Any]:
    fields = session.scalars(
        select(ArchivalFieldValue)
        .where(ArchivalFieldValue.archival_unit_id == unit.id)
        .order_by(ArchivalFieldValue.field_key, ArchivalFieldValue.sort_order)
    ).all()
    return {
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


def _digital_link_values(
    session: Session, link: DigitalObjectUnitLink
) -> dict[str, Any]:
    digital = session.get(DigitalObject, link.digital_object_id)
    return {
        "digital_object_id": link.digital_object_id,
        "archival_unit_id": link.archival_unit_id,
        "relation_type": link.relation_type,
        "page_start": link.page_start,
        "page_end": link.page_end,
        "digital_project_id": digital.project_id if digital else None,
        "media_type": digital.media_type if digital else None,
        "original_filename": digital.original_filename if digital else None,
        "sha256": digital.sha256 if digital else None,
        "byte_size": digital.byte_size if digital else None,
        "page_count": digital.page_count if digital else None,
    }



def _authority_values(session: Session, authority: AuthorityRecord) -> dict[str, Any]:
    aliases = session.scalars(
        select(AuthorityAlias)
        .where(AuthorityAlias.authority_id == authority.id)
        .order_by(AuthorityAlias.normalized_alias, AuthorityAlias.id)
    ).all()
    return {
        "entity_type": authority.entity_type,
        "preferred_name": authority.preferred_name,
        "normalized_name": authority.normalized_name,
        "description": authority.description,
        "temporal_expression": authority.temporal_expression,
        "temporal_start": authority.temporal_start.isoformat() if authority.temporal_start else None,
        "temporal_end": authority.temporal_end.isoformat() if authority.temporal_end else None,
        "temporal_precision": authority.temporal_precision,
        "temporal_approximate": bool(authority.temporal_approximate),
        "temporal_note": authority.temporal_note,
        "lifecycle_status": authority.lifecycle_status,
        "review_status": authority.review_status,
        "aliases": [
            {
                "id": row.id,
                "alias": row.alias,
                "normalized_alias": row.normalized_alias,
                "alias_type": row.alias_type,
                "note": row.note,
                "created_by": row.created_by,
                "created_at": row.created_at.isoformat(),
            }
            for row in aliases
        ],
    }


def _entity_mention_values(mention: EntityMention) -> dict[str, Any]:
    return {
        "editable_object_id": mention.editable_object_id,
        "authority_id": mention.authority_id,
        "mention_text": mention.mention_text,
        "normalized_text": mention.normalized_text,
        "start_offset": mention.start_offset,
        "end_offset": mention.end_offset,
        "object_revision_number": mention.object_revision_number,
        "status": mention.status,
        "source": mention.source,
        "confidence": mention.confidence,
        "note": mention.note,
    }

def _entity_relation_values(relation: EntityRelation) -> dict[str, Any]:
    return {
        "source_authority_id": relation.source_authority_id,
        "relation_label": relation.relation_label,
        "target_authority_id": relation.target_authority_id,
        "target_archival_unit_id": relation.target_archival_unit_id,
        "target_document_part_id": relation.target_document_part_id,
        "evidence_note": relation.evidence_note,
        "temporal_expression": relation.temporal_expression,
        "temporal_start": relation.temporal_start.isoformat() if relation.temporal_start else None,
        "temporal_end": relation.temporal_end.isoformat() if relation.temporal_end else None,
        "temporal_precision": relation.temporal_precision,
        "temporal_approximate": bool(relation.temporal_approximate),
        "temporal_note": relation.temporal_note,
        "lifecycle_status": relation.lifecycle_status,
        "review_status": relation.review_status,
    }


def _work_assignment_values(assignment: WorkAssignment) -> dict[str, Any]:
    return {
        "project_id": assignment.project_id,
        "source_type": assignment.source_type,
        "source_key": assignment.source_key,
        "page_start": assignment.page_start,
        "page_end": assignment.page_end,
        "assignment_kind": assignment.assignment_kind,
        "assignee": assignment.assignee,
        "status": assignment.status,
        "priority": assignment.priority,
        "due_at": _iso_utc(assignment.due_at),
        "parent_assignment_id": assignment.parent_assignment_id,
        "outcome": assignment.outcome,
        "note": assignment.note,
        "submitted_at": _iso_utc(assignment.submitted_at),
        "completed_at": _iso_utc(assignment.completed_at),
    }


def _normalize_incoming_event(event: ChangeEvent) -> tuple[ChangeEvent, str | None]:
    """Normaliza eventos históricos defectuosos sin alterar el bundle verificado.

    Las versiones 0.17.0–0.19.0 podían adjuntar pares espurios de texto a una
    eliminación/restauración cuando faltaba la revisión base consultada por el
    trigger. Esas operaciones solo cambian el estado lógico del objeto.
    """
    if event.entity_type != "editable_object" or event.operation.value not in {
        "delete",
        "restore",
    }:
        return event, None
    expected, target = ("active", "deleted") if event.operation.value == "delete" else ("deleted", "active")
    canonical = {"lifecycle_status": [expected, target]}
    if event.changed_fields == canonical:
        return event, None
    payload = event.model_dump(mode="python")
    payload["changed_fields"] = canonical
    return (
        ChangeEvent.model_validate(payload),
        f"El evento {event.event_id} de {event.operation.value} fue normalizado: "
        "solo se considera lifecycle_status.",
    )


def _assess_prior_incoming_state(
    event: ChangeEvent,
    incoming_state: dict[tuple[str, str], dict[str, Any]],
) -> tuple[str, str, list[str]] | None:
    """Evalúa un evento contra el estado producido antes en el mismo bundle.

    Esto permite cadenas legítimas como crear una autoridad y, en el evento
    siguiente, agregarle un alias. La comparación sigue siendo estricta: los
    valores ``old`` del segundo evento deben coincidir con el estado simulado
    por los eventos anteriores.
    """
    from archive_workbench.domain.enums import MergeDisposition

    key = (event.entity_type, event.entity_id)
    current_state = incoming_state.get(key)
    if current_state is None or event.operation.value == "create":
        return None

    pairs: list[tuple[str, Any, Any, Any]] = []
    for field in event.changed_fields:
        pair = _changed_pair(event, field)
        if pair is None:
            continue
        old, new = pair
        if field not in current_state:
            if old is not None:
                return (
                    MergeDisposition.REVIEW.value,
                    "El evento depende de una creación previa del mismo bundle, pero "
                    f"el campo {field} no está presente en el estado simulado.",
                    [field],
                )
            current_state[field] = None
        pairs.append((field, current_state[field], old, new))

    if not pairs:
        return (
            MergeDisposition.DUPLICATE.value,
            "El evento encadenado no contiene cambios efectivos.",
            [],
        )
    if all(_exchange_values_equal(current, new) for _field, current, _old, new in pairs):
        return (
            MergeDisposition.DUPLICATE.value,
            "El cambio ya está representado por eventos anteriores del mismo bundle.",
            [],
        )
    if all(_exchange_values_equal(current, old) for _field, current, old, _new in pairs):
        return (
            MergeDisposition.APPLY.value,
            "Las precondiciones coinciden con el estado creado antes en el mismo bundle.",
            [],
        )
    mismatches = [
        field for field, current, old, _new in pairs
        if not _exchange_values_equal(current, old)
    ]
    return (
        MergeDisposition.REVIEW.value,
        "La cadena de eventos del bundle contiene precondiciones internas incompatibles.",
        mismatches,
    )


def _advance_incoming_state(
    event: ChangeEvent,
    disposition: str,
    incoming_state: dict[tuple[str, str], dict[str, Any]],
) -> None:
    """Actualiza el estado simulado solo para eventos seguros del mismo bundle."""
    from archive_workbench.domain.enums import MergeDisposition

    if disposition not in {MergeDisposition.APPLY.value, MergeDisposition.DUPLICATE.value}:
        return
    key = (event.entity_type, event.entity_id)
    if event.operation.value == "delete":
        incoming_state.pop(key, None)
        return
    if event.operation.value == "create":
        incoming_state[key] = {
            field: _new_value(event.changed_fields, field) for field in event.changed_fields
        }
        return
    state = incoming_state.get(key)
    if state is None:
        return
    for field in event.changed_fields:
        pair = _changed_pair(event, field)
        if pair is not None:
            state[field] = pair[1]


def _assess_current_state(
    session: Session,
    event: ChangeEvent,
    incoming_creations: set[tuple[str, str]] | None = None,
) -> tuple[str, str, list[str]]:
    incoming_creations = incoming_creations or set()
    """Evalúa las precondiciones reales contra el estado canónico actual.

    No usa el número de revisión como bloqueo absoluto porque un cambio local
    compatible sobre otro campo puede haber incrementado la revisión. La
    comparación es campo por campo y el hash del dry-run protege el intervalo
    entre evaluación y aplicación.
    """
    from archive_workbench.domain.enums import MergeDisposition

    if event.entity_type == "editable_object":
        obj = session.get(EditableObject, event.entity_id)
        if event.operation.value == "create":
            if obj is None:
                return MergeDisposition.APPLY.value, "La entidad no existe localmente.", []
            checks = {
                "text": obj.current_text,
                "object_type": obj.current_object_type,
                "order_index": obj.current_order_index,
                "geometry": obj.current_geometry_json or [],
                "attributes": obj.current_attributes_json or {},
                "lifecycle_status": obj.lifecycle_status,
                "review_status": obj.review_status,
                "document_part_id": obj.document_part_id,
                "editable_page_id": obj.editable_page_id,
                "digital_object_id": obj.digital_object_id,
                "page_number": obj.page_number,
                "source_extracted_object_id": obj.source_extracted_object_id,
                "source_origin_id": obj.source_origin_id,
            }
            comparable = [
                (field, current, _new_value(event.changed_fields, field))
                for field, current in checks.items()
                if field in event.changed_fields
            ]
            if comparable and all(_exchange_values_equal(current, new) for _field, current, new in comparable):
                return MergeDisposition.DUPLICATE.value, "La creación ya está representada localmente.", []
            return MergeDisposition.REVIEW.value, "La entidad ya existe con un estado diferente.", [field for field, current, new in comparable if not _exchange_values_equal(current, new)]
        if obj is None:
            return MergeDisposition.REVIEW.value, "El objeto editable no existe localmente.", []
        attributes = {
            "text": "current_text",
            "object_type": "current_object_type",
            "order_index": "current_order_index",
            "geometry": "current_geometry_json",
            "attributes": "current_attributes_json",
            "lifecycle_status": "lifecycle_status",
            "review_status": "review_status",
            "document_part_id": "document_part_id",
        }
        pairs: list[tuple[str, Any, Any, Any]] = []
        for field, attribute in attributes.items():
            pair = _changed_pair(event, field)
            if pair is None:
                continue
            old, new = pair
            current = getattr(obj, attribute)
            if field in {"geometry", "attributes"}:
                current = current or ([] if field == "geometry" else {})
            pairs.append((field, current, old, new))
    elif event.entity_type == "editable_page":
        page = session.get(EditablePage, event.entity_id)
        if page is None:
            return MergeDisposition.REVIEW.value, "La página editable no existe localmente.", []
        pairs = []
        for field, attribute in (("review_status", "review_status"), ("review_note", "review_note")):
            pair = _changed_pair(event, field)
            if pair is not None:
                pairs.append((field, getattr(page, attribute), pair[0], pair[1]))
    elif event.entity_type == "editable_object_comment":
        comment = session.get(EditableObjectComment, event.entity_id)
        if event.operation.value != "create":
            return MergeDisposition.REVIEW.value, "Los comentarios solo admiten creación.", []
        if comment is None:
            return MergeDisposition.APPLY.value, "El comentario no existe localmente.", []
        expected = {
            "editable_object_id": _new_value(event.changed_fields, "editable_object_id"),
            "body": _new_value(event.changed_fields, "body"),
        }
        if comment.editable_object_id == expected["editable_object_id"] and comment.body == expected["body"]:
            return MergeDisposition.DUPLICATE.value, "El comentario ya existe localmente.", []
        return MergeDisposition.REVIEW.value, "El ID del comentario ya existe con otro contenido.", ["editable_object_id", "body"]
    elif event.entity_type == "editable_object_tag":
        tag = session.get(EditableObjectTag, event.entity_id)
        if event.operation.value == "create":
            if tag is None:
                return MergeDisposition.APPLY.value, "La etiqueta no existe localmente.", []
            expected = {field: _new_value(event.changed_fields, field) for field in ("editable_object_id", "tag", "normalized_tag", "tag_kind")}
            if all(getattr(tag, field) == value for field, value in expected.items()):
                return MergeDisposition.DUPLICATE.value, "La etiqueta ya existe localmente.", []
            return MergeDisposition.REVIEW.value, "El ID de etiqueta ya existe con otros valores.", list(expected)
        if event.operation.value == "delete":
            if tag is None:
                return MergeDisposition.DUPLICATE.value, "La etiqueta ya está ausente localmente.", []
            pairs = []
            for field in ("editable_object_id", "tag", "normalized_tag", "tag_kind"):
                pair = _changed_pair(event, field)
                if pair is not None:
                    pairs.append((field, getattr(tag, field), pair[0], pair[1]))
        else:
            return MergeDisposition.REVIEW.value, "Operación de etiqueta no admitida.", []
    elif event.entity_type == "archival_unit":
        unit = session.get(ArchivalUnit, event.entity_id)
        if event.operation.value == "create":
            if unit is None:
                return MergeDisposition.APPLY.value, "La unidad archivística no existe localmente.", []
            current_values = _catalog_unit_values(session, unit)
            comparable = [
                (field, current_values.get(field), _new_value(event.changed_fields, field))
                for field in event.changed_fields
                if field in current_values
            ]
            if comparable and all(_exchange_values_equal(current, new) for _field, current, new in comparable):
                return MergeDisposition.DUPLICATE.value, "La unidad ya está representada localmente.", []
            return (
                MergeDisposition.REVIEW.value,
                "El ID de la unidad ya existe con otros valores.",
                [field for field, current, new in comparable if not _exchange_values_equal(current, new)],
            )
        if unit is None:
            return MergeDisposition.REVIEW.value, "La unidad archivística no existe localmente.", []
        current_values = _catalog_unit_values(session, unit)
        pairs = []
        for field, current in current_values.items():
            pair = _changed_pair(event, field)
            if pair is not None:
                pairs.append((field, current, pair[0], pair[1]))
    elif event.entity_type == "digital_object_unit_link":
        link = session.get(DigitalObjectUnitLink, event.entity_id)
        if event.operation.value == "delete":
            if link is None:
                sha256 = _changed_pair(event, "sha256")
                unit_id = _changed_pair(event, "archival_unit_id")
                relation_type = _changed_pair(event, "relation_type")
                page_start = _changed_pair(event, "page_start")
                page_end = _changed_pair(event, "page_end")
                old_sha = sha256[0] if sha256 else None
                old_unit = unit_id[0] if unit_id else None
                digital = session.scalar(
                    select(DigitalObject).where(
                        DigitalObject.project_id == event.project_id,
                        DigitalObject.sha256 == old_sha,
                    )
                ) if isinstance(old_sha, str) else None
                if digital is not None and isinstance(old_unit, str):
                    link = session.scalar(
                        select(DigitalObjectUnitLink).where(
                            DigitalObjectUnitLink.digital_object_id == digital.id,
                            DigitalObjectUnitLink.archival_unit_id == old_unit,
                            DigitalObjectUnitLink.relation_type == (relation_type[0] if relation_type else "represents"),
                            DigitalObjectUnitLink.page_start.is_(None)
                            if not page_start or page_start[0] is None
                            else DigitalObjectUnitLink.page_start == page_start[0],
                            DigitalObjectUnitLink.page_end.is_(None)
                            if not page_end or page_end[0] is None
                            else DigitalObjectUnitLink.page_end == page_end[0],
                        )
                    )
            if link is None:
                return MergeDisposition.DUPLICATE.value, "El vínculo ya está ausente localmente.", []
            current_values = _digital_link_values(session, link)
            pairs = []
            for field, current in current_values.items():
                pair = _changed_pair(event, field)
                if pair is not None:
                    pairs.append((field, current, pair[0], pair[1]))
        elif event.operation.value == "create":
            if link is not None:
                current_values = _digital_link_values(session, link)
                comparable = [
                    (field, current_values.get(field), _new_value(event.changed_fields, field))
                    for field in event.changed_fields
                    if field in current_values
                ]
                if comparable and all(_exchange_values_equal(current, new) for _field, current, new in comparable):
                    return MergeDisposition.DUPLICATE.value, "El vínculo ya existe localmente.", []
                return (
                    MergeDisposition.REVIEW.value,
                    "El ID del vínculo ya existe con otros valores.",
                    [field for field, current, new in comparable if not _exchange_values_equal(current, new)],
                )
            unit_id = _new_value(event.changed_fields, "archival_unit_id")
            if not isinstance(unit_id, str):
                return MergeDisposition.REVIEW.value, "El vínculo no identifica una unidad archivística.", []
            if (
                session.get(ArchivalUnit, unit_id) is None
                and ("archival_unit", unit_id) not in incoming_creations
            ):
                return MergeDisposition.REVIEW.value, "El vínculo apunta a una unidad inexistente.", []
            sha256 = _new_value(event.changed_fields, "sha256")
            relation_type = _new_value(event.changed_fields, "relation_type")
            page_start = _new_value(event.changed_fields, "page_start")
            page_end = _new_value(event.changed_fields, "page_end")
            digital = session.scalar(
                select(DigitalObject).where(
                    DigitalObject.project_id == event.project_id,
                    DigitalObject.sha256 == sha256,
                )
            ) if isinstance(sha256, str) else None
            if digital is not None:
                existing = session.scalar(
                    select(DigitalObjectUnitLink).where(
                        DigitalObjectUnitLink.digital_object_id == digital.id,
                        DigitalObjectUnitLink.archival_unit_id == unit_id,
                        DigitalObjectUnitLink.relation_type == relation_type,
                        DigitalObjectUnitLink.page_start.is_(None)
                        if page_start is None
                        else DigitalObjectUnitLink.page_start == page_start,
                        DigitalObjectUnitLink.page_end.is_(None)
                        if page_end is None
                        else DigitalObjectUnitLink.page_end == page_end,
                    )
                )
                if existing is not None:
                    return MergeDisposition.DUPLICATE.value, "El mismo contenido ya está vinculado a la unidad.", []
            return MergeDisposition.APPLY.value, "El vínculo y sus metadatos pueden incorporarse.", []
        else:
            return MergeDisposition.REVIEW.value, "Operación de vínculo digital no admitida.", []
    elif event.entity_type == "authority_record":
        authority = session.get(AuthorityRecord, event.entity_id)
        if event.operation.value == "create":
            if authority is None:
                return MergeDisposition.APPLY.value, "La autoridad no existe localmente.", []
            current_values = _authority_values(session, authority)
            comparable = [
                (field, current_values.get(field), _new_value(event.changed_fields, field))
                for field in event.changed_fields
                if field in current_values
            ]
            if comparable and all(_exchange_values_equal(current, new) for _field, current, new in comparable):
                return MergeDisposition.DUPLICATE.value, "La autoridad ya existe localmente.", []
            return (
                MergeDisposition.REVIEW.value,
                "El ID de autoridad ya existe con otros valores.",
                [field for field, current, new in comparable if not _exchange_values_equal(current, new)],
            )
        if authority is None:
            return MergeDisposition.REVIEW.value, "La autoridad no existe localmente.", []
        current_values = _authority_values(session, authority)
        pairs = []
        for field, current in current_values.items():
            pair = _changed_pair(event, field)
            if pair is not None:
                pairs.append((field, current, pair[0], pair[1]))
    elif event.entity_type == "entity_mention":
        mention = session.get(EntityMention, event.entity_id)
        if event.operation.value == "create":
            if mention is None:
                return MergeDisposition.APPLY.value, "La mención no existe localmente.", []
            current_values = _entity_mention_values(mention)
            comparable = [
                (field, current_values.get(field), _new_value(event.changed_fields, field))
                for field in event.changed_fields
                if field in current_values
            ]
            if comparable and all(_exchange_values_equal(current, new) for _field, current, new in comparable):
                return MergeDisposition.DUPLICATE.value, "La mención ya existe localmente.", []
            return (
                MergeDisposition.REVIEW.value,
                "El ID de mención ya existe con otros valores.",
                [field for field, current, new in comparable if not _exchange_values_equal(current, new)],
            )
        if mention is None:
            return MergeDisposition.REVIEW.value, "La mención no existe localmente.", []
        current_values = _entity_mention_values(mention)
        pairs = []
        for field, current in current_values.items():
            pair = _changed_pair(event, field)
            if pair is not None:
                pairs.append((field, current, pair[0], pair[1]))
    elif event.entity_type == "entity_relation":
        relation = session.get(EntityRelation, event.entity_id)
        if event.operation.value == "create":
            if relation is None:
                return MergeDisposition.APPLY.value, "La relación no existe localmente.", []
            current_values = _entity_relation_values(relation)
            comparable = [
                (field, current_values.get(field), _new_value(event.changed_fields, field))
                for field in event.changed_fields
                if field in current_values
            ]
            if comparable and all(_exchange_values_equal(current, new) for _field, current, new in comparable):
                return MergeDisposition.DUPLICATE.value, "La relación ya existe localmente.", []
            return (
                MergeDisposition.REVIEW.value,
                "El ID de relación ya existe con otros valores.",
                [field for field, current, new in comparable if not _exchange_values_equal(current, new)],
            )
        if relation is None:
            return MergeDisposition.REVIEW.value, "La relación no existe localmente.", []
        current_values = _entity_relation_values(relation)
        pairs = []
        for field, current in current_values.items():
            pair = _changed_pair(event, field)
            if pair is not None:
                pairs.append((field, current, pair[0], pair[1]))
    elif event.entity_type == "work_assignment":
        assignment = session.get(WorkAssignment, event.entity_id)
        if event.operation.value == "create":
            if assignment is None:
                source_type = _new_value(event.changed_fields, "source_type")
                source_key = _new_value(event.changed_fields, "source_key")
                registration = session.scalar(
                    select(SourceRegistration).where(
                        SourceRegistration.project_id == event.project_id,
                        SourceRegistration.source_type == source_type,
                        SourceRegistration.source_key == source_key,
                    )
                )
                if registration is None:
                    return (
                        MergeDisposition.REVIEW.value,
                        "La asignación apunta a un documento no registrado localmente.",
                        ["source_type", "source_key"],
                    )
                return MergeDisposition.APPLY.value, "La asignación no existe localmente.", []
            current_values = _work_assignment_values(assignment)
            comparable = [
                (field, current_values.get(field), _new_value(event.changed_fields, field))
                for field in event.changed_fields
                if field in current_values
            ]
            if comparable and all(_exchange_values_equal(current, new) for _field, current, new in comparable):
                return MergeDisposition.DUPLICATE.value, "La asignación ya existe localmente.", []
            return (
                MergeDisposition.REVIEW.value,
                "El ID de asignación ya existe con otros valores.",
                [field for field, current, new in comparable if not _exchange_values_equal(current, new)],
            )
        if assignment is None:
            return MergeDisposition.REVIEW.value, "La asignación no existe localmente.", []
        current_values = _work_assignment_values(assignment)
        pairs = []
        for field, current in current_values.items():
            pair = _changed_pair(event, field)
            if pair is not None:
                pairs.append((field, current, pair[0], pair[1]))
    else:
        return MergeDisposition.REVIEW.value, f"Tipo de entidad no evaluable: {event.entity_type}", []

    if not pairs:
        return MergeDisposition.DUPLICATE.value, "El evento no contiene cambios efectivos.", []
    if all(_exchange_values_equal(current, new) for _field, current, _old, new in pairs):
        return MergeDisposition.DUPLICATE.value, "El cambio ya está representado en el estado local.", []
    if all(_exchange_values_equal(current, old) for _field, current, old, _new in pairs):
        return MergeDisposition.APPLY.value, "Las precondiciones coinciden con el estado local.", []
    mismatches = [field for field, current, old, _new in pairs if not _exchange_values_equal(current, old)]
    return MergeDisposition.CONFLICT.value, "Las precondiciones no coinciden con el estado local actual.", mismatches


def _parent_reference_problem(
    session: Session, event: ChangeEvent, incoming_creations: set[tuple[str, str]] | None = None
) -> str | None:
    incoming_creations = incoming_creations or set()
    if event.operation != "create":
        return None
    if event.entity_type == "editable_object":
        required = ("editable_page_id", "digital_object_id", "page_number")
        values = {field: _new_value(event.changed_fields, field) for field in required}
        if any(values[field] is None for field in required):
            return (
                "La creación del objeto no incluye contexto de página suficiente; "
                "requiere revisión humana."
            )
        page = session.get(EditablePage, values["editable_page_id"])
        if page is None:
            natural_page = session.scalar(
                select(EditablePage).where(
                    EditablePage.digital_object_id == values["digital_object_id"],
                    EditablePage.page_number == values["page_number"],
                )
            )
            if natural_page is not None:
                return (
                    "La página editable existe localmente con otro ID; "
                    "el objeto requiere remapeo explícito."
                )
            source = _editable_page_materialization_source(
                session,
                digital_object_id=values["digital_object_id"],
                page_number=int(values["page_number"]),
            )
            if source is None:
                return (
                    "La creación del objeto apunta a una página editable inexistente y "
                    "no hay una selección OCR local para materializarla."
                )
            return None
        if (
            page.digital_object_id != values["digital_object_id"]
            or page.page_number != values["page_number"]
        ):
            return "La creación del objeto contiene referencias de página inconsistentes."
        return None
    if event.entity_type == "archival_unit":
        parent_id = _new_value(event.changed_fields, "parent_id")
        if parent_id is None:
            return None
        if session.get(ArchivalUnit, parent_id) is not None:
            return None
        if ("archival_unit", str(parent_id)) in incoming_creations:
            return None
        return "La unidad nueva apunta a una unidad padre inexistente."
    if event.entity_type == "digital_object_unit_link":
        unit_id = _new_value(event.changed_fields, "archival_unit_id")
        if session.get(ArchivalUnit, unit_id) is not None:
            return None
        if ("archival_unit", str(unit_id)) in incoming_creations:
            return None
        return "El vínculo digital apunta a una unidad archivística inexistente."
    if event.entity_type == "entity_mention":
        object_id = _new_value(event.changed_fields, "editable_object_id")
        authority_id = _new_value(event.changed_fields, "authority_id")
        if (
            not isinstance(object_id, str)
            or (
                session.get(EditableObject, object_id) is None
                and ("editable_object", object_id) not in incoming_creations
            )
        ):
            return "La mención apunta a un objeto editable inexistente."
        if authority_id is not None and (
            not isinstance(authority_id, str)
            or (
                session.get(AuthorityRecord, authority_id) is None
                and ("authority_record", authority_id) not in incoming_creations
            )
        ):
            return "La mención apunta a una autoridad inexistente."
        return None
    if event.entity_type == "entity_relation":
        source_id = _new_value(event.changed_fields, "source_authority_id")
        if not isinstance(source_id, str) or (
            session.get(AuthorityRecord, source_id) is None
            and ("authority_record", source_id) not in incoming_creations
        ):
            return "La relación apunta a una entidad de origen inexistente."
        target_authority_id = _new_value(event.changed_fields, "target_authority_id")
        target_unit_id = _new_value(event.changed_fields, "target_archival_unit_id")
        target_part_id = _new_value(event.changed_fields, "target_document_part_id")
        targets = [target_authority_id, target_unit_id, target_part_id]
        if sum(value is not None for value in targets) != 1:
            return "La relación no contiene exactamente un destino."
        if target_authority_id is not None and (
            not isinstance(target_authority_id, str)
            or (
                session.get(AuthorityRecord, target_authority_id) is None
                and ("authority_record", target_authority_id) not in incoming_creations
            )
        ):
            return "La relación apunta a una entidad de destino inexistente."
        if target_unit_id is not None and (
            not isinstance(target_unit_id, str)
            or (
                session.get(ArchivalUnit, target_unit_id) is None
                and ("archival_unit", target_unit_id) not in incoming_creations
            )
        ):
            return "La relación apunta a una unidad archivística inexistente."
        if target_part_id is not None and session.get(DocumentPart, target_part_id) is None:
            return "La relación apunta a una parte interna inexistente."
        return None
    if event.entity_type == "work_assignment":
        parent_id = _new_value(event.changed_fields, "parent_assignment_id")
        if parent_id is None:
            return None
        if session.get(WorkAssignment, parent_id) is not None:
            return None
        if ("work_assignment", str(parent_id)) in incoming_creations:
            return None
        return "La revisión cruzada apunta a una asignación primaria inexistente."
    if event.entity_type not in {"editable_object_comment", "editable_object_tag"}:
        return None
    object_id = _new_value(event.changed_fields, "editable_object_id")
    if not isinstance(object_id, str) or session.get(EditableObject, object_id) is None:
        return "El evento crea una anotación para un objeto editable que no existe localmente."
    return None


def _combine_pair_assessments(
    incoming: ChangeEvent, pair_rows: list[Any]
) -> tuple[str, str, list[str], list[str]]:
    from archive_workbench.domain.enums import MergeDisposition

    if not pair_rows:
        return (MergeDisposition.APPLY.value, "No hay cambios locales concurrentes sobre la entidad.", [], [])
    by_priority = {
        MergeDisposition.CONFLICT: 4,
        MergeDisposition.REVIEW: 3,
        MergeDisposition.APPLY: 2,
        MergeDisposition.DUPLICATE: 1,
    }
    strongest = max(pair_rows, key=lambda row: by_priority[row.disposition])
    local_ids = sorted({row.local_event_id for row in pair_rows if row.local_event_id})
    overlaps = sorted({field for row in pair_rows for field in row.overlapping_fields})
    if strongest.disposition == MergeDisposition.CONFLICT:
        reason = "Existe al menos un cambio local concurrente incompatible."
    elif strongest.disposition == MergeDisposition.REVIEW:
        reason = "La combinación requiere revisión humana antes de aplicar."
    elif all(row.disposition == MergeDisposition.DUPLICATE for row in pair_rows):
        reason = "El mismo cambio ya está representado en la copia local."
        strongest = pair_rows[0]
    else:
        reason = "Los cambios locales concurrentes son compatibles según la política del proyecto."
    return strongest.disposition.value, reason, local_ids, overlaps


def _dry_run_markdown(report: Any) -> str:
    lines = [
        f"# Dry-run de bundle {report.bundle_id}",
        "",
        f"- Proyecto: `{report.project_id}`",
        f"- Copia local: `{report.local_workspace_name}` (`{report.local_workspace_id}`)",
        f"- Copia de origen: `{report.source_workspace_name}` (`{report.source_workspace_id}`)",
        f"- Base común: `{report.common_checkpoint_label or 'no encontrada'}`",
        f"- Estado: `{report.overall_status}`",
        f"- Estado local evaluado: `{report.assessed_local_state_sha256}`",
        f"- Secuencia local evaluada: `{report.assessed_local_sequence}`",
        "",
        "## Resumen",
        "",
        "| Clasificación | Cantidad |",
        "|---|---:|",
    ]
    for key in ("apply", "duplicate", "review", "conflict"):
        lines.append(f"| `{key}` | {report.counts.get(key, 0)} |")
    if report.warnings:
        lines.extend(["", "## Advertencias", ""])
        lines.extend(f"- {warning}" for warning in report.warnings)
    lines.extend(["", "## Eventos", ""])
    if not report.assessments:
        lines.append("El bundle no contiene eventos.")
    for row in report.assessments:
        event = row.incoming_event
        lines.extend(
            [
                f"### Secuencia {event.sequence_number}: `{row.disposition.value}`",
                "",
                f"- Entidad: `{event.entity_type}` / `{event.entity_id}`",
                f"- Operación: `{event.operation.value}`",
                f"- Autor de origen: `{event.actor}`",
                f"- Motivo: {row.reason}",
            ]
        )
        if row.overlapping_fields:
            lines.append("- Campos superpuestos: " + ", ".join(f"`{x}`" for x in row.overlapping_fields))
        if row.local_event_ids:
            lines.append("- Eventos locales relacionados: " + ", ".join(f"`{x}`" for x in row.local_event_ids))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def dry_run_change_bundle(
    session: Session,
    *,
    project_root: Path,
    bundle_path: Path,
    assessed_by: str,
    copy_to_incoming: bool = True,
) -> BundleDryRunSummary:
    from collections import Counter, defaultdict
    import shutil

    from archive_workbench.contracts.changes import (
        BundleDryRunReport,
        DryRunEventAssessment,
    )
    from archive_workbench.contracts.decisions import ProjectDecisions
    from archive_workbench.db.models import (
        ExchangeDryRun,
        ExchangeIncomingEventAssessment,
        ExchangeConflictResolution,
    )
    from archive_workbench.domain.enums import MergeDisposition
    from archive_workbench.merge import assess_pair

    inspection, incoming_events, normalization_warnings = _load_bundle_events(bundle_path)
    manifest = inspection.manifest
    workspace = ensure_exchange_workspace(session, changed_by=assessed_by)
    project = _project(session)
    if manifest.project_id != project.id:
        raise ValueError(
            f"El bundle pertenece al proyecto {manifest.project_id}, no a {project.id}"
        )
    if manifest.source_workspace_id == workspace.id:
        raise ValueError("El bundle fue producido por esta misma copia de trabajo")

    repeated = session.scalar(
        select(ExchangeDryRun).where(ExchangeDryRun.bundle_id == manifest.bundle_id)
    )
    existing_record = session.scalar(
        select(ExchangeBundleRecord).where(ExchangeBundleRecord.bundle_id == manifest.bundle_id)
    )
    if existing_record is not None and existing_record.bundle_sha256 != inspection.bundle_sha256:
        raise ValueError("Ya existe un bundle con el mismo ID pero distinto SHA-256")
    applied = session.scalar(
        select(ExchangeBundleApplication).where(
            ExchangeBundleApplication.bundle_id == manifest.bundle_id
        )
    )
    if applied is not None:
        raise ValueError(f"El bundle {manifest.bundle_id} ya fue aplicado")

    source = bundle_path.expanduser().resolve()
    if copy_to_incoming:
        destination = (
            project_root.resolve()
            / "exchange"
            / "incoming"
            / f"{slugify(manifest.source_workspace_name, 40)}_{short_id(manifest.bundle_id)}.zip"
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.resolve() != source:
            if destination.exists() and sha256_file(destination) != inspection.bundle_sha256:
                raise ValueError(f"Ya existe otro archivo en la ruta de recepción: {destination}")
            if not destination.exists():
                shutil.copy2(source, destination)
        stored_path = destination
    else:
        stored_path = source

    common = _matching_checkpoint(
        session,
        workspace_id=workspace.id,
        state_sha256=manifest.base_checkpoint_state_sha256,
    )
    lineage_match = False
    if common is None:
        common = _lineage_checkpoint_from_applied_bundle(
            session,
            workspace_id=workspace.id,
            source_workspace_id=manifest.source_workspace_id,
            base_checkpoint_label=manifest.base_checkpoint_label,
            base_sequence=manifest.base_sequence,
        )
        lineage_match = common is not None
    warnings = list(inspection.warnings) + normalization_warnings
    if lineage_match:
        warnings.append(
            "La base común se reconoció por un bundle previamente aplicado; "
            "el estado local puede diferir por resoluciones conservadas."
        )
    force_review_reason: str | None = None
    if manifest.database_revision not in _known_database_revisions():
        force_review_reason = (
            f"La revisión de base de origen {manifest.database_revision} no es conocida por esta versión."
        )
        warnings.append(force_review_reason)
    if common is None:
        warnings.append(
            "No se encontró un checkpoint local con el mismo hash de estado que la base del bundle."
        )

    local_events: list[ExchangeChangeEvent] = []
    if common is not None:
        local_events = session.scalars(
            select(ExchangeChangeEvent)
            .where(
                ExchangeChangeEvent.workspace_id == workspace.id,
                ExchangeChangeEvent.sequence_number > common.sequence_number,
            )
            .order_by(ExchangeChangeEvent.sequence_number)
        ).all()
    local_by_entity: dict[tuple[str, str], list[ChangeEvent]] = defaultdict(list)
    for row in local_events:
        local_by_entity[(row.entity_type, row.entity_id)].append(_event_contract(row))

    incoming_creations = {
        (event.entity_type, event.entity_id)
        for event in incoming_events
        if event.operation.value == "create"
    }
    assessment_contracts: list[DryRunEventAssessment] = []
    incoming_state: dict[tuple[str, str], dict[str, Any]] = {}
    for incoming in incoming_events:
        local_candidates = local_by_entity.get((incoming.entity_type, incoming.entity_id), [])
        local_ids: list[str] = []
        overlaps: list[str] = []
        if force_review_reason:
            disposition = MergeDisposition.REVIEW.value
            reason = force_review_reason
        elif common is None:
            disposition = MergeDisposition.REVIEW.value
            reason = "No existe una base común verificable para comparar el evento."
        else:
            parent_problem = _parent_reference_problem(session, incoming, incoming_creations)
            if parent_problem:
                disposition = MergeDisposition.REVIEW.value
                reason = parent_problem
            elif (chain_assessment := _assess_prior_incoming_state(incoming, incoming_state)) is not None:
                disposition, reason, overlaps = chain_assessment
            elif local_candidates:
                merge_rules = ProjectDecisions.model_validate(project.decisions_json).merge
                pairs = [assess_pair(local, incoming, merge_rules) for local in local_candidates]
                disposition, reason, local_ids, overlaps = _combine_pair_assessments(incoming, pairs)
                if disposition == MergeDisposition.APPLY.value:
                    state_disposition, state_reason, state_overlaps = _assess_current_state(
                        session, incoming, incoming_creations
                    )
                    if state_disposition != MergeDisposition.APPLY.value:
                        disposition = state_disposition
                        reason = state_reason
                        overlaps = sorted(set(overlaps) | set(state_overlaps))
                    else:
                        reason = f"{reason} {state_reason}"
            else:
                disposition, reason, overlaps = _assess_current_state(
                    session, incoming, incoming_creations
                )
        _advance_incoming_state(incoming, disposition, incoming_state)
        assessment_contracts.append(
            DryRunEventAssessment(
                incoming_event=incoming,
                disposition=MergeDisposition(disposition),
                reason=reason,
                local_event_ids=local_ids,
                overlapping_fields=overlaps,
            )
        )

    counter = Counter(row.disposition.value for row in assessment_contracts)
    counts = {key: int(counter.get(key, 0)) for key in ("apply", "duplicate", "review", "conflict")}
    if not assessment_contracts:
        overall = "empty"
    elif counts["conflict"]:
        overall = "conflicts"
    elif counts["review"]:
        overall = "needs_review"
    else:
        overall = "ready_to_apply"
    base_status = "matched" if common is not None else "unmatched"
    assessed_state_sha256 = current_editable_state_sha256(session, project.id)
    assessed_sequence_number = _current_sequence(session, workspace.id)

    report = BundleDryRunReport(
        project_id=project.id,
        local_workspace_id=workspace.id,
        local_workspace_name=workspace.workspace_name,
        bundle_id=manifest.bundle_id,
        bundle_sha256=inspection.bundle_sha256,
        source_workspace_id=manifest.source_workspace_id,
        source_workspace_name=manifest.source_workspace_name,
        base_checkpoint_state_sha256=manifest.base_checkpoint_state_sha256,
        common_checkpoint_id=common.id if common else None,
        common_checkpoint_label=common.label if common else None,
        common_checkpoint_sequence=common.sequence_number if common else None,
        base_match_status=base_status,
        overall_status=overall,
        counts=counts,
        warnings=warnings,
        assessments=assessment_contracts,
        assessed_local_state_sha256=assessed_state_sha256,
        assessed_local_sequence=assessed_sequence_number,
        assessed_by=assessed_by,
    )
    report_dir = project_root.resolve() / "exchange" / "incoming" / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_json = report_dir / f"{manifest.bundle_id}_dry_run.json"
    report_md = report_dir / f"{manifest.bundle_id}_dry_run.md"
    report_json.write_text(
        json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    report_md.write_text(_dry_run_markdown(report), encoding="utf-8")

    if existing_record is None:
        existing_record = ExchangeBundleRecord(
            id=new_id(),
            workspace_id=workspace.id,
            bundle_id=manifest.bundle_id,
            direction="incoming",
            bundle_sha256=inspection.bundle_sha256,
            relative_path=_relative_or_absolute(stored_path, project_root),
            base_sequence=manifest.base_sequence,
            last_sequence=manifest.last_sequence,
            event_count=manifest.event_count,
            status="assessed",
            counterpart_workspace_id=manifest.source_workspace_id,
            created_by=assessed_by,
            created_at=utc_now(),
        )
        session.add(existing_record)
        session.flush()
    else:
        existing_record.status = "assessed"
        existing_record.relative_path = _relative_or_absolute(stored_path, project_root)
        existing_record.counterpart_workspace_id = manifest.source_workspace_id

    if repeated is None:
        dry = ExchangeDryRun(
            id=new_id(),
            workspace_id=workspace.id,
            bundle_record_id=existing_record.id,
            bundle_id=manifest.bundle_id,
            source_workspace_id=manifest.source_workspace_id,
            source_workspace_name=manifest.source_workspace_name,
            common_checkpoint_id=common.id if common else None,
            common_checkpoint_label=common.label if common else None,
            common_checkpoint_sequence=common.sequence_number if common else None,
            base_match_status=base_status,
            overall_status=overall,
            counts_json=counts,
            warnings_json=warnings,
            report_json_path=_relative_or_absolute(report_json, project_root),
            report_markdown_path=_relative_or_absolute(report_md, project_root),
            assessed_state_sha256=assessed_state_sha256,
            assessed_sequence_number=assessed_sequence_number,
            assessed_by=assessed_by,
            assessed_at=utc_now(),
        )
        session.add(dry)
        session.flush()
    else:
        dry = repeated
        session.query(ExchangeConflictResolution).filter(
            ExchangeConflictResolution.dry_run_id == dry.id
        ).delete(synchronize_session=False)
        session.query(ExchangeIncomingEventAssessment).filter(
            ExchangeIncomingEventAssessment.dry_run_id == dry.id
        ).delete(synchronize_session=False)
        dry.bundle_record_id = existing_record.id
        dry.source_workspace_id = manifest.source_workspace_id
        dry.source_workspace_name = manifest.source_workspace_name
        dry.common_checkpoint_id = common.id if common else None
        dry.common_checkpoint_label = common.label if common else None
        dry.common_checkpoint_sequence = common.sequence_number if common else None
        dry.base_match_status = base_status
        dry.overall_status = overall
        dry.counts_json = counts
        dry.warnings_json = warnings
        dry.report_json_path = _relative_or_absolute(report_json, project_root)
        dry.report_markdown_path = _relative_or_absolute(report_md, project_root)
        dry.assessed_state_sha256 = assessed_state_sha256
        dry.assessed_sequence_number = assessed_sequence_number
        dry.assessed_by = assessed_by
        dry.assessed_at = utc_now()
        session.flush()

    for row in assessment_contracts:
        event = row.incoming_event
        session.add(
            ExchangeIncomingEventAssessment(
                id=new_id(),
                dry_run_id=dry.id,
                incoming_event_id=event.event_id,
                source_sequence_number=event.sequence_number,
                entity_type=event.entity_type,
                entity_id=event.entity_id,
                operation=event.operation.value,
                disposition=row.disposition.value,
                reason=row.reason,
                local_event_ids_json=row.local_event_ids,
                overlapping_fields_json=row.overlapping_fields,
                incoming_event_json=event.model_dump(mode="json", exclude_none=True),
                application_status="not_applied",
                assessed_at=utc_now(),
            )
        )
    session.flush()
    return BundleDryRunSummary(
        bundle_id=manifest.bundle_id,
        bundle_sha256=inspection.bundle_sha256,
        source_workspace_id=manifest.source_workspace_id,
        source_workspace_name=manifest.source_workspace_name,
        common_checkpoint_id=common.id if common else None,
        common_checkpoint_label=common.label if common else None,
        base_match_status=base_status,
        overall_status=overall,
        counts=counts,
        report_json_path=report_json,
        report_markdown_path=report_md,
        repeated_assessment=repeated is not None,
    )


def incoming_bundle_rows(session: Session) -> list[IncomingBundleRow]:
    from archive_workbench.db.models import ExchangeDryRun

    rows = session.scalars(
        select(ExchangeDryRun).order_by(ExchangeDryRun.assessed_at.desc(), ExchangeDryRun.id)
    ).all()
    workspace = ensure_exchange_workspace(session)
    project = _project(session)
    current_state = current_editable_state_sha256(session, project.id)
    current_sequence = _current_sequence(session, workspace.id)
    result: list[IncomingBundleRow] = []
    for row in rows:
        status = row.overall_status
        if status not in {"applied"} and (
            row.assessed_state_sha256 is None
            or row.assessed_sequence_number is None
            or row.assessed_state_sha256 != current_state
            or row.assessed_sequence_number != current_sequence
        ):
            status = "stale"
        result.append(
            IncomingBundleRow(
                bundle_id=row.bundle_id,
                source_workspace_name=row.source_workspace_name,
                source_workspace_id=row.source_workspace_id,
                event_count=sum(int(value) for value in (row.counts_json or {}).values()),
                status=status,
                base_match_status=row.base_match_status,
                counts=row.counts_json or {},
                assessed_by=row.assessed_by,
                assessed_at=row.assessed_at,
                report_markdown_path=row.report_markdown_path,
            )
        )
    return result


@dataclass(slots=True)
class ForkWorkspaceSummary:
    previous_workspace_id: str
    previous_workspace_name: str
    workspace_id: str
    workspace_name: str
    checkpoint_id: str
    checkpoint_label: str
    state_sha256: str


def fork_exchange_workspace(
    session: Session,
    *,
    workspace_name: str,
    created_by: str,
    checkpoint_label: str = "baseline",
) -> ForkWorkspaceSummary:
    """Reidentifica una copia física del proyecto sin alterar su estado editable."""
    from sqlalchemy import delete

    from archive_workbench.db.models import (
        ExchangeDryRun,
        ExchangeIncomingEventAssessment,
    )

    clean_name = workspace_name.strip()
    clean_label = checkpoint_label.strip()
    if not clean_name:
        raise ValueError("El nombre de la nueva copia no puede estar vacío")
    if not clean_label:
        raise ValueError("La etiqueta del checkpoint inicial no puede estar vacía")
    previous = ensure_exchange_workspace(session, changed_by=created_by)
    previous_id = previous.id
    previous_name = previous.workspace_name
    session.execute(delete(ExchangeConflictResolution))
    session.execute(delete(ExchangeIncomingEventAssessment))
    session.execute(delete(ExchangeBundleApplication))
    session.execute(delete(ExchangeDryRun))
    session.execute(delete(ExchangeBundleRecord))
    session.execute(delete(ExchangeCheckpoint))
    session.execute(delete(ExchangeChangeEvent))
    session.execute(delete(ExchangeWorkspace))
    session.flush()
    workspace = ensure_exchange_workspace(
        session, workspace_name=clean_name, changed_by=created_by
    )
    checkpoint = create_exchange_checkpoint(
        session,
        label=clean_label,
        created_by=created_by,
        note=(
            "Checkpoint inicial creado al reidentificar una copia física del proyecto; "
            f"identidad anterior {previous_name} ({previous_id})"
        ),
    )
    return ForkWorkspaceSummary(
        previous_workspace_id=previous_id,
        previous_workspace_name=previous_name,
        workspace_id=workspace.id,
        workspace_name=workspace.workspace_name,
        checkpoint_id=checkpoint.id,
        checkpoint_label=checkpoint.label,
        state_sha256=checkpoint.state_sha256,
    )


@dataclass(slots=True)
class ConflictFieldRow:
    bundle_id: str
    event_id: str
    source_sequence_number: int
    entity_type: str
    entity_id: str
    operation: str
    disposition: str
    field_name: str
    base_value: Any
    local_value: Any
    incoming_value: Any
    choice: str | None
    resolved_value: Any
    resolved_by: str | None
    note: str | None


@dataclass(slots=True)
class ResolutionStatusSummary:
    bundle_id: str
    event_count: int
    field_count: int
    resolved_field_count: int
    auto_matched_field_count: int
    skipped_event_count: int
    unresolved_field_count: int
    overall_status: str
    already_finalized: bool = False


@dataclass(slots=True)
class BulkResolutionSummary:
    bundle_id: str
    event_count: int
    resolved_field_count: int
    auto_matched_field_count: int
    choice: str


def _dry_run_for_bundle(session: Session, bundle_ref: str):
    from archive_workbench.db.models import ExchangeDryRun

    dry = session.scalar(select(ExchangeDryRun).where(ExchangeDryRun.bundle_id == bundle_ref))
    if dry is None:
        candidate = Path(bundle_ref).expanduser()
        if candidate.is_file():
            inspection = inspect_change_bundle(candidate)
            dry = session.scalar(
                select(ExchangeDryRun).where(
                    ExchangeDryRun.bundle_id == inspection.manifest.bundle_id
                )
            )
    if dry is None:
        raise ValueError(
            "El bundle todavía no tiene un dry-run persistido. "
            "Ejecutá exchange-dry-run primero."
        )
    return dry


def _event_resolvable_fields(event: ChangeEvent) -> list[str]:
    return sorted(
        field
        for field, value in event.changed_fields.items()
        if isinstance(value, list) and len(value) == 2
    )


def _current_field_value(session: Session, event: ChangeEvent, field: str) -> Any:
    if event.entity_type == "editable_object":
        obj = session.get(EditableObject, event.entity_id)
        if obj is None:
            return None
        mapping = {
            "text": "current_text",
            "object_type": "current_object_type",
            "order_index": "current_order_index",
            "geometry": "current_geometry_json",
            "attributes": "current_attributes_json",
            "lifecycle_status": "lifecycle_status",
            "review_status": "review_status",
            "document_part_id": "document_part_id",
            "editable_page_id": "editable_page_id",
            "digital_object_id": "digital_object_id",
            "page_number": "page_number",
            "source_extracted_object_id": "source_extracted_object_id",
            "source_origin_id": "source_origin_id",
        }
        attribute = mapping.get(field)
        return getattr(obj, attribute) if attribute else None
    if event.entity_type == "editable_page":
        page = session.get(EditablePage, event.entity_id)
        if page is None:
            return None
        mapping = {"review_status": "review_status", "review_note": "review_note"}
        attribute = mapping.get(field)
        return getattr(page, attribute) if attribute else None
    if event.entity_type == "editable_object_comment":
        row = session.get(EditableObjectComment, event.entity_id)
        if row is None:
            return None
        mapping = {"editable_object_id": "editable_object_id", "body": "body"}
        attribute = mapping.get(field)
        return getattr(row, attribute) if attribute else None
    if event.entity_type == "editable_object_tag":
        row = session.get(EditableObjectTag, event.entity_id)
        if row is None:
            return None
        mapping = {
            "editable_object_id": "editable_object_id",
            "tag": "tag",
            "normalized_tag": "normalized_tag",
            "tag_kind": "tag_kind",
        }
        attribute = mapping.get(field)
        return getattr(row, attribute) if attribute else None
    if event.entity_type == "archival_unit":
        row = session.get(ArchivalUnit, event.entity_id)
        if row is None:
            return None
        return _catalog_unit_values(session, row).get(field)
    if event.entity_type == "digital_object_unit_link":
        row = session.get(DigitalObjectUnitLink, event.entity_id)
        if row is None:
            return None
        return _digital_link_values(session, row).get(field)
    if event.entity_type == "authority_record":
        row = session.get(AuthorityRecord, event.entity_id)
        if row is None:
            return None
        return _authority_values(session, row).get(field)
    if event.entity_type == "entity_mention":
        row = session.get(EntityMention, event.entity_id)
        if row is None:
            return None
        return _entity_mention_values(row).get(field)
    if event.entity_type == "entity_relation":
        row = session.get(EntityRelation, event.entity_id)
        if row is None:
            return None
        return _entity_relation_values(row).get(field)
    if event.entity_type == "work_assignment":
        row = session.get(WorkAssignment, event.entity_id)
        if row is None:
            return None
        return _work_assignment_values(row).get(field)
    return None


def _event_fields_requiring_decision(session: Session, event: ChangeEvent) -> list[str]:
    """Devuelve solo campos donde el valor local difiere del recibido.

    Un campo puede tener una base ausente o antigua y, sin embargo, estar ya
    representado de forma idéntica en ambas copias. Pedir una decisión humana
    en ese caso es ruido y puede producir resoluciones engañosas.
    """
    result: list[str] = []
    for field in _event_resolvable_fields(event):
        pair = _changed_pair(event, field)
        if pair is None:
            continue
        local = _current_field_value(session, event, field)
        if local != pair[1]:
            result.append(field)
    return result


def _event_auto_matched_fields(session: Session, event: ChangeEvent) -> list[str]:
    required = set(_event_fields_requiring_decision(session, event))
    return [field for field in _event_resolvable_fields(event) if field not in required]


def conflict_field_rows(session: Session, bundle_ref: str) -> list[ConflictFieldRow]:
    from archive_workbench.db.models import ExchangeIncomingEventAssessment

    dry = _dry_run_for_bundle(session, bundle_ref)
    assessments = session.scalars(
        select(ExchangeIncomingEventAssessment)
        .where(
            ExchangeIncomingEventAssessment.dry_run_id == dry.id,
            ExchangeIncomingEventAssessment.disposition.in_(["review", "conflict"]),
        )
        .order_by(ExchangeIncomingEventAssessment.source_sequence_number)
    ).all()
    resolutions = session.scalars(
        select(ExchangeConflictResolution).where(
            ExchangeConflictResolution.dry_run_id == dry.id
        )
    ).all()
    by_key = {(row.incoming_event_id, row.field_name): row for row in resolutions}
    result: list[ConflictFieldRow] = []
    for assessment in assessments:
        event = ChangeEvent.model_validate(assessment.incoming_event_json)
        skip = by_key.get((event.event_id, "__event__"))
        fields = _event_fields_requiring_decision(session, event)
        if not fields:
            # El evento puede seguir clasificado como conflictivo por su base,
            # aunque todos sus valores recibidos ya coincidan con la copia.
            # En ese caso no se exige una confirmación campo por campo.
            continue
        for field in fields:
            pair = _changed_pair(event, field) if field != "__event__" else None
            resolution = by_key.get((event.event_id, field)) or skip
            result.append(
                ConflictFieldRow(
                    bundle_id=dry.bundle_id,
                    event_id=event.event_id,
                    source_sequence_number=assessment.source_sequence_number,
                    entity_type=event.entity_type,
                    entity_id=event.entity_id,
                    operation=event.operation.value,
                    disposition=assessment.disposition,
                    field_name=field,
                    base_value=pair[0] if pair else None,
                    local_value=(
                        _current_field_value(session, event, field)
                        if field != "__event__"
                        else None
                    ),
                    incoming_value=pair[1] if pair else None,
                    choice=resolution.choice if resolution else None,
                    resolved_value=resolution.resolved_value_json if resolution else None,
                    resolved_by=resolution.resolved_by if resolution else None,
                    note=resolution.note if resolution else None,
                )
            )
    return result


def save_conflict_resolution(
    session: Session,
    *,
    bundle_ref: str,
    event_id: str,
    field_name: str,
    choice: str,
    resolved_by: str,
    custom_value: Any = None,
    note: str | None = None,
) -> ExchangeConflictResolution:
    from archive_workbench.db.models import ExchangeIncomingEventAssessment

    dry = _dry_run_for_bundle(session, bundle_ref)
    if dry.overall_status in {"applied", "stale"}:
        raise ValueError(f"El bundle no admite resoluciones en estado {dry.overall_status}")
    assessment = session.scalar(
        select(ExchangeIncomingEventAssessment).where(
            ExchangeIncomingEventAssessment.dry_run_id == dry.id,
            ExchangeIncomingEventAssessment.incoming_event_id == event_id,
        )
    )
    if assessment is None:
        raise ValueError(f"No existe el evento recibido: {event_id}")
    if assessment.disposition not in {"review", "conflict"}:
        raise ValueError("El evento no está clasificado como revisable o conflictivo")
    event = ChangeEvent.model_validate(assessment.incoming_event_json)
    if field_name not in _event_fields_requiring_decision(session, event):
        if field_name in _event_resolvable_fields(event):
            raise ValueError(
                f"El campo {field_name} ya coincide entre la copia local y el bundle"
            )
        raise ValueError(f"El evento no modifica el campo: {field_name}")
    clean_choice = choice.strip().lower()
    if clean_choice not in {"local", "incoming", "custom"}:
        raise ValueError("La elección debe ser local, incoming o custom")
    pair = _changed_pair(event, field_name)
    assert pair is not None
    local_value = _current_field_value(session, event, field_name)
    resolved_value = (
        local_value
        if clean_choice == "local"
        else pair[1]
        if clean_choice == "incoming"
        else custom_value
    )
    session.query(ExchangeConflictResolution).filter(
        ExchangeConflictResolution.dry_run_id == dry.id,
        ExchangeConflictResolution.incoming_event_id == event_id,
        ExchangeConflictResolution.field_name == "__event__",
    ).delete(synchronize_session=False)
    existing = session.scalar(
        select(ExchangeConflictResolution).where(
            ExchangeConflictResolution.dry_run_id == dry.id,
            ExchangeConflictResolution.incoming_event_id == event_id,
            ExchangeConflictResolution.field_name == field_name,
        )
    )
    if existing is None:
        existing = ExchangeConflictResolution(
            id=new_id(),
            dry_run_id=dry.id,
            incoming_event_id=event_id,
            field_name=field_name,
            choice=clean_choice,
            base_value_json=pair[0],
            local_value_json=local_value,
            incoming_value_json=pair[1],
            resolved_value_json=resolved_value,
            note=note.strip() if note and note.strip() else None,
            resolved_by=resolved_by,
            resolved_at=utc_now(),
        )
        session.add(existing)
    else:
        existing.choice = clean_choice
        existing.base_value_json = pair[0]
        existing.local_value_json = local_value
        existing.incoming_value_json = pair[1]
        existing.resolved_value_json = resolved_value
        existing.note = note.strip() if note and note.strip() else None
        existing.resolved_by = resolved_by
        existing.resolved_at = utc_now()
    dry.overall_status = "resolving"
    session.flush()
    return existing


def skip_conflicted_event(
    session: Session,
    *,
    bundle_ref: str,
    event_id: str,
    resolved_by: str,
    note: str | None = None,
) -> ExchangeConflictResolution:
    from archive_workbench.db.models import ExchangeIncomingEventAssessment

    dry = _dry_run_for_bundle(session, bundle_ref)
    assessment = session.scalar(
        select(ExchangeIncomingEventAssessment).where(
            ExchangeIncomingEventAssessment.dry_run_id == dry.id,
            ExchangeIncomingEventAssessment.incoming_event_id == event_id,
        )
    )
    if assessment is None or assessment.disposition not in {"review", "conflict"}:
        raise ValueError("El evento no está disponible para resolución")
    existing = session.scalar(
        select(ExchangeConflictResolution).where(
            ExchangeConflictResolution.dry_run_id == dry.id,
            ExchangeConflictResolution.incoming_event_id == event_id,
            ExchangeConflictResolution.field_name == "__event__",
        )
    )
    if existing is None:
        existing = ExchangeConflictResolution(
            id=new_id(),
            dry_run_id=dry.id,
            incoming_event_id=event_id,
            field_name="__event__",
            choice="skip",
            base_value_json=None,
            local_value_json=None,
            incoming_value_json=None,
            resolved_value_json=None,
            note=note.strip() if note and note.strip() else None,
            resolved_by=resolved_by,
            resolved_at=utc_now(),
        )
        session.add(existing)
    else:
        existing.choice = "skip"
        existing.note = note.strip() if note and note.strip() else None
        existing.resolved_by = resolved_by
        existing.resolved_at = utc_now()
    session.query(ExchangeConflictResolution).filter(
        ExchangeConflictResolution.dry_run_id == dry.id,
        ExchangeConflictResolution.incoming_event_id == event_id,
        ExchangeConflictResolution.field_name != "__event__",
    ).delete(synchronize_session=False)
    dry.overall_status = "resolving"
    session.flush()
    return existing


def resolve_conflict_fields_bulk(
    session: Session,
    *,
    bundle_ref: str,
    choice: str,
    resolved_by: str,
    event_id: str | None = None,
    note: str | None = None,
) -> BulkResolutionSummary:
    """Resuelve en bloque los campos que realmente difieren.

    Los campos cuyo valor local ya coincide con el recibido se contabilizan
    como coincidencias automáticas y nunca requieren una decisión humana.
    """
    from archive_workbench.db.models import ExchangeIncomingEventAssessment

    clean_choice = choice.strip().lower()
    if clean_choice not in {"local", "incoming"}:
        raise ValueError("La resolución masiva admite únicamente local o incoming")
    dry = _dry_run_for_bundle(session, bundle_ref)
    query = select(ExchangeIncomingEventAssessment).where(
        ExchangeIncomingEventAssessment.dry_run_id == dry.id,
        ExchangeIncomingEventAssessment.disposition.in_(["review", "conflict"]),
    )
    if event_id is not None:
        query = query.where(ExchangeIncomingEventAssessment.incoming_event_id == event_id)
    assessments = session.scalars(
        query.order_by(ExchangeIncomingEventAssessment.source_sequence_number)
    ).all()
    if not assessments:
        raise ValueError("No hay eventos revisables o conflictivos para resolver")
    resolved_fields = 0
    auto_matched = 0
    touched_events = 0
    for assessment in assessments:
        event = ChangeEvent.model_validate(assessment.incoming_event_json)
        fields = _event_fields_requiring_decision(session, event)
        auto_matched += len(_event_auto_matched_fields(session, event))
        if not fields:
            continue
        if event.operation.value == "create" and clean_choice == "incoming":
            raise ValueError(
                f"La creación conflictiva {event.event_id} no puede aceptarse en bloque; "
                "requiere conservar localmente o descartar el evento"
            )
        touched_events += 1
        for field in fields:
            save_conflict_resolution(
                session,
                bundle_ref=dry.bundle_id,
                event_id=event.event_id,
                field_name=field,
                choice=clean_choice,
                resolved_by=resolved_by,
                note=note,
            )
            resolved_fields += 1
    session.flush()
    return BulkResolutionSummary(
        bundle_id=dry.bundle_id,
        event_count=touched_events,
        resolved_field_count=resolved_fields,
        auto_matched_field_count=auto_matched,
        choice=clean_choice,
    )


def resolution_status(session: Session, bundle_ref: str) -> ResolutionStatusSummary:
    from archive_workbench.db.models import ExchangeIncomingEventAssessment

    dry = _dry_run_for_bundle(session, bundle_ref)
    assessments = session.scalars(
        select(ExchangeIncomingEventAssessment).where(
            ExchangeIncomingEventAssessment.dry_run_id == dry.id,
            ExchangeIncomingEventAssessment.disposition.in_(["review", "conflict"]),
        )
    ).all()
    resolutions = session.scalars(
        select(ExchangeConflictResolution).where(
            ExchangeConflictResolution.dry_run_id == dry.id
        )
    ).all()
    by_event: dict[str, dict[str, ExchangeConflictResolution]] = {}
    for row in resolutions:
        by_event.setdefault(row.incoming_event_id, {})[row.field_name] = row
    field_count = 0
    auto_matched = 0
    resolved = 0
    skipped = 0
    completed_events = 0
    for assessment in assessments:
        event = ChangeEvent.model_validate(assessment.incoming_event_json)
        event_rows = by_event.get(event.event_id, {})
        if event_rows.get("__event__") and event_rows["__event__"].choice == "skip":
            skipped += 1
            completed_events += 1
            auto_matched += len(_event_auto_matched_fields(session, event))
            continue
        fields = _event_fields_requiring_decision(session, event)
        auto_matched += len(_event_auto_matched_fields(session, event))
        if not fields:
            completed_events += 1
            continue
        field_count += len(fields)
        event_resolved = sum(1 for field in fields if field in event_rows)
        resolved += event_resolved
        if event_resolved == len(fields):
            completed_events += 1
    unresolved = max(field_count - resolved, 0)
    already_finalized = dry.overall_status in {"ready_to_apply_resolved", "applied"}
    if dry.overall_status in {"ready_to_apply_resolved", "applied", "stale"}:
        status = dry.overall_status
    elif not assessments:
        status = dry.overall_status
    elif completed_events == len(assessments):
        status = "ready_to_finalize"
    else:
        status = "pending"
    return ResolutionStatusSummary(
        bundle_id=dry.bundle_id,
        event_count=len(assessments),
        field_count=field_count,
        resolved_field_count=resolved,
        auto_matched_field_count=auto_matched,
        skipped_event_count=skipped,
        unresolved_field_count=unresolved,
        overall_status=status,
        already_finalized=already_finalized,
    )


def finalize_bundle_resolutions(
    session: Session,
    *,
    bundle_ref: str,
    finalized_by: str,
) -> ResolutionStatusSummary:
    from archive_workbench.db.models import ExchangeIncomingEventAssessment

    dry = _dry_run_for_bundle(session, bundle_ref)
    if dry.overall_status in {"ready_to_apply_resolved", "applied"}:
        result = resolution_status(session, dry.bundle_id)
        result.already_finalized = True
        return result
    workspace = ensure_exchange_workspace(session, changed_by=finalized_by)
    project = _project(session)
    if dry.assessed_state_sha256 is None or dry.assessed_sequence_number is None:
        raise ValueError("Repetí el dry-run antes de resolver este bundle")
    if (
        current_editable_state_sha256(session, project.id) != dry.assessed_state_sha256
        or _current_sequence(session, workspace.id) != dry.assessed_sequence_number
    ):
        dry.overall_status = "stale"
        raise ValueError(
            "La copia local cambió después del dry-run. Repetí la evaluación y las resoluciones."
        )
    status = resolution_status(session, dry.bundle_id)
    if status.event_count == 0:
        raise ValueError("El bundle no contiene conflictos o eventos revisables")
    if status.overall_status != "ready_to_finalize":
        raise ValueError(
            f"Todavía quedan {status.unresolved_field_count} campos sin resolver"
        )
    assessments = session.scalars(
        select(ExchangeIncomingEventAssessment).where(
            ExchangeIncomingEventAssessment.dry_run_id == dry.id,
            ExchangeIncomingEventAssessment.disposition.in_(["review", "conflict"]),
        )
    ).all()
    resolutions = session.scalars(
        select(ExchangeConflictResolution).where(
            ExchangeConflictResolution.dry_run_id == dry.id
        )
    ).all()
    by_key = {(row.incoming_event_id, row.field_name): row for row in resolutions}
    for assessment in assessments:
        event = ChangeEvent.model_validate(assessment.incoming_event_json)
        if (event.event_id, "__event__") in by_key:
            continue
        for field in _event_fields_requiring_decision(session, event):
            row = by_key[(event.event_id, field)]
            current = _current_field_value(session, event, field)
            if current != row.local_value_json:
                dry.overall_status = "stale"
                raise ValueError(
                    f"El campo {field} del evento {event.event_id} "
                    "cambió después de la resolución"
                )
    dry.overall_status = "ready_to_apply_resolved"
    session.flush()
    final = resolution_status(session, dry.bundle_id)
    final.overall_status = "ready_to_apply_resolved"
    return final


def _resolved_event(
    session: Session,
    *,
    dry_run_id: str,
    assessment: Any,
    event: ChangeEvent,
) -> tuple[ChangeEvent | None, str]:
    resolutions = session.scalars(
        select(ExchangeConflictResolution).where(
            ExchangeConflictResolution.dry_run_id == dry_run_id,
            ExchangeConflictResolution.incoming_event_id == event.event_id,
        )
    ).all()
    by_field = {row.field_name: row for row in resolutions}
    skip = by_field.get("__event__")
    if skip is not None and skip.choice == "skip":
        return None, "kept_local_resolution"
    fields = _event_fields_requiring_decision(session, event)
    if not fields:
        return None, "already_matched"
    if any(field not in by_field for field in fields):
        raise ValueError(f"El evento {event.event_id} no tiene una resolución completa")
    if event.operation.value == "create":
        if all(by_field[field].choice == "local" for field in fields):
            return None, "kept_local_resolution"
        raise ValueError(
            f"La creación conflictiva {event.event_id} solo puede conservarse localmente "
            "o descartarse en esta versión"
        )
    changed: dict[str, Any] = {}
    for field in fields:
        row = by_field[field]
        current = _current_field_value(session, event, field)
        if current != row.local_value_json:
            raise ValueError(
                f"La resolución del campo {field} del evento {event.event_id} caducó"
            )
        if row.resolved_value_json != current:
            changed[field] = [current, row.resolved_value_json]
    if not changed:
        return None, "kept_local_resolution"
    payload = event.model_dump(mode="python")
    payload["changed_fields"] = changed
    payload["base_revision"] = None
    payload["new_revision"] = None
    return ChangeEvent.model_validate(payload), "resolved_apply"


@dataclass(slots=True)
class BundleApplicationSummary:
    application_id: str
    bundle_id: str
    source_workspace_name: str
    applied_event_count: int
    duplicate_event_count: int
    kept_local_event_count: int
    backup_path: Path
    backup_sha256: str
    local_sequence_start: int
    local_sequence_end: int
    checkpoint_id: str
    checkpoint_label: str
    report_json_path: Path
    report_markdown_path: Path


@dataclass(slots=True)
class BundleApplicationRow:
    application_id: str
    bundle_id: str
    source_workspace_id: str
    applied_event_count: int
    duplicate_event_count: int
    kept_local_event_count: int
    status: str
    checkpoint_label: str | None
    backup_relative_path: str
    applied_by: str
    applied_at: datetime


def _stored_bundle_path(project_root: Path, record: ExchangeBundleRecord) -> Path:
    if not record.relative_path:
        raise ValueError("El bundle recibido no tiene una ruta almacenada")
    candidate = Path(record.relative_path)
    if not candidate.is_absolute():
        candidate = project_root.resolve() / candidate
    candidate = candidate.resolve()
    if not candidate.is_file():
        raise ValueError(f"No se encuentra el bundle recibido: {candidate}")
    return candidate


def _backup_sqlite(project_root: Path, bundle_id: str) -> tuple[Path, str]:
    from archive_workbench.db.session import database_path

    source = database_path(project_root).resolve()
    if not source.is_file():
        raise ValueError(f"No existe la base SQLite: {source}")
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = (
        project_root.resolve()
        / "exchange"
        / "backups"
        / f"before_{timestamp}_{short_id(bundle_id)}.sqlite3"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        raise ValueError(f"Ya existe el backup previsto: {target}")
    with sqlite3.connect(source) as source_db, sqlite3.connect(target) as target_db:
        source_db.backup(target_db)
    return target, sha256_file(target)


def _changed_pair(event: ChangeEvent, field: str) -> tuple[Any, Any] | None:
    value = event.changed_fields.get(field)
    if isinstance(value, list) and len(value) == 2:
        return value[0], value[1]
    return None


def _assert_expected(current: Any, expected: Any, *, event: ChangeEvent, field: str) -> None:
    if current != expected:
        raise ValueError(
            f"El evento {event.event_id} ya no puede aplicarse: {field} esperaba "
            f"{expected!r} y la copia local contiene {current!r}"
        )


def _apply_object_event(
    session: Session,
    *,
    event: ChangeEvent,
    applied_by: str,
    source_workspace_name: str,
) -> None:
    from archive_workbench.editing import _append_revision

    actor = f"{applied_by} [bundle de {source_workspace_name}]"
    obj = session.get(EditableObject, event.entity_id)
    if event.operation.value == "create":
        if obj is not None:
            raise ValueError(f"El objeto {event.entity_id} ya existe localmente")
        required = ("editable_page_id", "digital_object_id", "page_number")
        context = {name: _new_value(event.changed_fields, name) for name in required}
        if any(context[name] is None for name in required):
            raise ValueError(
                f"El evento {event.event_id} no incluye el contexto necesario para crear el objeto"
            )
        page = session.get(EditablePage, context["editable_page_id"])
        if page is None:
            natural_page = session.scalar(
                select(EditablePage).where(
                    EditablePage.digital_object_id == context["digital_object_id"],
                    EditablePage.page_number == context["page_number"],
                )
            )
            if natural_page is not None:
                raise ValueError(
                    "La página editable existe localmente con otro ID y no puede remapearse implícitamente"
                )
            source = _editable_page_materialization_source(
                session,
                digital_object_id=context["digital_object_id"],
                page_number=int(context["page_number"]),
            )
            if source is None:
                raise ValueError(
                    "La página editable de destino no existe y no puede materializarse desde una selección OCR local"
                )
            selection, extraction_page = source
            actor = f"{applied_by} [bundle de {source_workspace_name}]"
            page = EditablePage(
                id=context["editable_page_id"],
                digital_object_id=context["digital_object_id"],
                page_number=int(context["page_number"]),
                source_extraction_run_id=selection.extraction_run_id,
                source_extraction_page_id=extraction_page.id,
                source_selection_id=selection.id,
                status="active",
                review_status="unreviewed",
                bootstrapped_by=actor,
                bootstrapped_at=utc_now(),
                updated_at=utc_now(),
            )
            session.add(page)
            session.flush()
        if page.digital_object_id != context["digital_object_id"] or page.page_number != context["page_number"]:
            raise ValueError("El contexto de página del objeto recibido es inconsistente")
        new_revision = event.new_revision or 1
        if new_revision != 1:
            raise ValueError("Una creación recibida debe comenzar en la revisión 1")
        obj = EditableObject(
            id=event.entity_id,
            editable_page_id=context["editable_page_id"],
            digital_object_id=context["digital_object_id"],
            page_number=int(context["page_number"]),
            document_part_id=_new_value(event.changed_fields, "document_part_id"),
            source_extracted_object_id=_new_value(event.changed_fields, "source_extracted_object_id"),
            source_origin_id=_new_value(event.changed_fields, "source_origin_id"),
            current_text=_new_value(event.changed_fields, "text") or "",
            current_object_type=_new_value(event.changed_fields, "object_type") or "paragraph",
            current_order_index=int(_new_value(event.changed_fields, "order_index") or 0),
            current_geometry_json=_new_value(event.changed_fields, "geometry") or [],
            current_attributes_json=_new_value(event.changed_fields, "attributes") or {},
            lifecycle_status=_new_value(event.changed_fields, "lifecycle_status") or "active",
            review_status=_new_value(event.changed_fields, "review_status") or "unreviewed",
            revision_number=1,
            created_by=actor,
            created_at=utc_now(),
            updated_by=actor,
            updated_at=utc_now(),
        )
        session.add(obj)
        session.flush()
        _append_revision(
            session,
            obj,
            operation="create",
            created_by=actor,
            note=f"Aplicado desde evento remoto {event.event_id}",
            base_revision_number=None,
        )
        return

    if obj is None:
        raise ValueError(f"Objeto editable inexistente: {event.entity_id}")
    revision_fields = {
        "text": "current_text",
        "object_type": "current_object_type",
        "order_index": "current_order_index",
        "geometry": "current_geometry_json",
        "attributes": "current_attributes_json",
        "lifecycle_status": "lifecycle_status",
        "document_part_id": "document_part_id",
    }
    changed_revision = False
    for field, attribute in revision_fields.items():
        pair = _changed_pair(event, field)
        if pair is None:
            continue
        old, new = pair
        current = getattr(obj, attribute)
        _assert_expected(current, old, event=event, field=field)
        setattr(obj, attribute, new)
        changed_revision = True
    review_pair = _changed_pair(event, "review_status")
    if review_pair is not None:
        old, new = review_pair
        _assert_expected(obj.review_status, old, event=event, field="review_status")
        obj.review_status = new
    if changed_revision:
        base = obj.revision_number
        obj.revision_number += 1
        obj.updated_by = actor
        obj.updated_at = utc_now()
        _append_revision(
            session,
            obj,
            operation=(
                "delete" if event.operation.value == "delete" else
                "restore" if event.operation.value == "restore" else
                "exchange_apply"
            ),
            created_by=actor,
            note=f"Aplicado desde evento remoto {event.event_id}",
            base_revision_number=base,
        )
    elif review_pair is not None:
        obj.updated_by = actor
        obj.updated_at = utc_now()
    else:
        raise ValueError(f"El evento {event.event_id} no contiene campos aplicables")


def _apply_page_event(
    session: Session,
    *,
    event: ChangeEvent,
    applied_by: str,
    source_workspace_name: str,
) -> None:
    page = session.get(EditablePage, event.entity_id)
    if page is None:
        raise ValueError(f"Página editable inexistente: {event.entity_id}")
    actor = f"{applied_by} [bundle de {source_workspace_name}]"
    status_pair = _changed_pair(event, "review_status")
    note_pair = _changed_pair(event, "review_note")
    if status_pair is None and note_pair is None:
        raise ValueError(f"El evento {event.event_id} no contiene campos de página aplicables")
    if status_pair is not None:
        old, new = status_pair
        _assert_expected(page.review_status, old, event=event, field="review_status")
        page.review_status = new
    if note_pair is not None:
        old, new = note_pair
        _assert_expected(page.review_note, old, event=event, field="review_note")
        page.review_note = new
    page.reviewed_by = actor
    page.reviewed_at = utc_now()
    page.updated_at = utc_now()


def _apply_comment_event(
    session: Session,
    *,
    event: ChangeEvent,
    applied_by: str,
    source_workspace_name: str,
) -> None:
    if event.operation.value != "create":
        raise ValueError("Los comentarios recibidos solo admiten creación append-only")
    if session.get(EditableObjectComment, event.entity_id) is not None:
        raise ValueError(f"El comentario {event.entity_id} ya existe localmente")
    object_id = _new_value(event.changed_fields, "editable_object_id")
    body = _new_value(event.changed_fields, "body")
    if not isinstance(object_id, str) or session.get(EditableObject, object_id) is None:
        raise ValueError("El comentario recibido apunta a un objeto inexistente")
    if not isinstance(body, str) or not body.strip():
        raise ValueError("El comentario recibido no contiene texto")
    session.add(
        EditableObjectComment(
            id=event.entity_id,
            editable_object_id=object_id,
            body=body,
            created_by=event.actor,
            created_at=event.timestamp,
        )
    )


def _apply_tag_event(
    session: Session,
    *,
    event: ChangeEvent,
    applied_by: str,
    source_workspace_name: str,
) -> None:
    tag = session.get(EditableObjectTag, event.entity_id)
    if event.operation.value == "create":
        if tag is not None:
            raise ValueError(f"La etiqueta {event.entity_id} ya existe localmente")
        object_id = _new_value(event.changed_fields, "editable_object_id")
        if not isinstance(object_id, str) or session.get(EditableObject, object_id) is None:
            raise ValueError("La etiqueta recibida apunta a un objeto inexistente")
        values = {
            field: _new_value(event.changed_fields, field)
            for field in ("tag", "normalized_tag", "tag_kind")
        }
        if not all(isinstance(values[field], str) and values[field] for field in values):
            raise ValueError("La etiqueta recibida está incompleta")
        session.add(
            EditableObjectTag(
                id=event.entity_id,
                editable_object_id=object_id,
                tag=values["tag"],
                normalized_tag=values["normalized_tag"],
                tag_kind=values["tag_kind"],
                created_by=event.actor,
                created_at=event.timestamp,
            )
        )
        return
    if event.operation.value == "delete":
        if tag is None:
            raise ValueError(f"La etiqueta {event.entity_id} ya no existe localmente")
        for field, attribute in (
            ("editable_object_id", "editable_object_id"),
            ("tag", "tag"),
            ("normalized_tag", "normalized_tag"),
            ("tag_kind", "tag_kind"),
        ):
            pair = _changed_pair(event, field)
            if pair is not None:
                _assert_expected(getattr(tag, attribute), pair[0], event=event, field=field)
        session.delete(tag)
        return
    raise ValueError("Las etiquetas recibidas solo admiten creación o eliminación")


def _coerce_datetime(value: Any) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"Fecha inválida en evento de catálogo: {value}") from exc
    raise ValueError(f"Fecha inválida en evento de catálogo: {value!r}")


def _coerce_date(value: Any) -> date | None:
    if value is None or isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(f"Fecha temporal inválida en evento: {value}") from exc
    raise ValueError(f"Fecha temporal inválida en evento: {value!r}")


def _replace_catalog_fields(
    session: Session, *, unit_id: str, fields: Any
) -> None:
    if not isinstance(fields, list):
        raise ValueError("Los campos descriptivos recibidos deben formar una lista")
    session.execute(
        delete(ArchivalFieldValue).where(ArchivalFieldValue.archival_unit_id == unit_id)
    )
    positions: set[tuple[str, int]] = set()
    for item in fields:
        if not isinstance(item, dict):
            raise ValueError("Un campo descriptivo recibido no es un objeto JSON")
        field_key = item.get("field_key")
        state = item.get("value_state")
        order = item.get("sort_order", 0)
        if not isinstance(field_key, str) or not field_key:
            raise ValueError("Un campo descriptivo recibido no tiene field_key")
        if state not in {"provided", "no_information", "not_applicable", "pending"}:
            raise ValueError(f"Estado descriptivo inválido: {state}")
        if not isinstance(order, int) or order < 0:
            raise ValueError("sort_order descriptivo inválido")
        key = (field_key, order)
        if key in positions:
            raise ValueError("El bundle repite la posición de un campo descriptivo")
        positions.add(key)
        session.add(
            ArchivalFieldValue(
                id=new_id(),
                archival_unit_id=unit_id,
                field_key=field_key,
                value_state=state,
                value_json=item.get("value"),
                sort_order=order,
                source_note=item.get("source_note"),
            )
        )


def _apply_archival_unit_event(
    session: Session,
    *,
    event: ChangeEvent,
    applied_by: str,
    source_workspace_name: str,
) -> None:
    from archive_workbench.catalog_management import _append_revision, _validate_parent
    from archive_workbench.contracts.decisions import ProjectDecisions

    project = session.get(Project, event.project_id)
    if project is None:
        raise ValueError("El proyecto del evento de catálogo no existe")
    decisions = ProjectDecisions.model_validate(project.decisions_json)
    actor = f"{applied_by} [bundle de {source_workspace_name}]"
    unit = session.get(ArchivalUnit, event.entity_id)
    if event.operation.value == "create":
        if unit is not None:
            raise ValueError(f"La unidad archivística {event.entity_id} ya existe")
        values = {field: _new_value(event.changed_fields, field) for field in (
            "parent_id", "level_key", "reference_code", "title",
            "registration_status", "completion_confirmed",
            "completion_confirmed_at", "completion_confirmed_by", "fields",
        )}
        if not isinstance(values["level_key"], str) or not values["level_key"]:
            raise ValueError("La unidad recibida no tiene nivel archivístico")
        if not isinstance(values["title"], str) or not values["title"].strip():
            raise ValueError("La unidad recibida no tiene título")
        _validate_parent(
            session, decisions, project_id=event.project_id,
            level_key=values["level_key"], parent_id=values["parent_id"],
        )
        revision = event.new_revision or 1
        if revision != 1:
            raise ValueError("Una unidad archivística nueva debe comenzar en revisión 1")
        unit = ArchivalUnit(
            id=event.entity_id,
            project_id=event.project_id,
            parent_id=values["parent_id"],
            level_key=values["level_key"],
            reference_code=values["reference_code"],
            title=values["title"].strip(),
            registration_status=values["registration_status"] or "incomplete",
            completion_confirmed=bool(values["completion_confirmed"]),
            completion_confirmed_at=_coerce_datetime(values["completion_confirmed_at"]),
            completion_confirmed_by=values["completion_confirmed_by"],
            created_by=event.actor,
            created_at=event.timestamp,
            updated_by=actor,
            updated_at=utc_now(),
            revision=1,
        )
        session.add(unit)
        session.flush()
        _replace_catalog_fields(session, unit_id=unit.id, fields=values["fields"] or [])
        session.flush()
        _append_revision(
            session, unit, operation="create", changed_by=actor,
            note=f"Aplicado desde evento remoto {event.event_id}",
        )
        return

    if unit is None:
        raise ValueError(f"Unidad archivística inexistente: {event.entity_id}")
    current = _catalog_unit_values(session, unit)
    scalar_fields = {
        "parent_id": "parent_id",
        "level_key": "level_key",
        "reference_code": "reference_code",
        "title": "title",
        "registration_status": "registration_status",
        "completion_confirmed": "completion_confirmed",
        "completion_confirmed_by": "completion_confirmed_by",
    }
    prospective_parent = unit.parent_id
    prospective_level = unit.level_key
    parent_pair = _changed_pair(event, "parent_id")
    level_pair = _changed_pair(event, "level_key")
    if parent_pair is not None:
        prospective_parent = parent_pair[1]
    if level_pair is not None:
        prospective_level = level_pair[1]
    if parent_pair is not None or level_pair is not None:
        _validate_parent(
            session, decisions, project_id=unit.project_id,
            level_key=prospective_level, parent_id=prospective_parent, moving_unit_id=unit.id,
        )
    changed = False
    for field, attribute in scalar_fields.items():
        pair = _changed_pair(event, field)
        if pair is None:
            continue
        _assert_expected(current[field], pair[0], event=event, field=field)
        setattr(unit, attribute, pair[1])
        changed = True
    date_pair = _changed_pair(event, "completion_confirmed_at")
    if date_pair is not None:
        _assert_expected(current["completion_confirmed_at"], date_pair[0], event=event, field="completion_confirmed_at")
        unit.completion_confirmed_at = _coerce_datetime(date_pair[1])
        changed = True
    fields_pair = _changed_pair(event, "fields")
    if fields_pair is not None:
        _assert_expected(current["fields"], fields_pair[0], event=event, field="fields")
        _replace_catalog_fields(session, unit_id=unit.id, fields=fields_pair[1] or [])
        changed = True
    if not changed:
        raise ValueError(f"El evento {event.event_id} no contiene campos de catálogo aplicables")
    unit.revision += 1
    unit.updated_by = actor
    unit.updated_at = utc_now()
    session.flush()
    _append_revision(
        session, unit, operation="exchange_apply", changed_by=actor,
        note=f"Aplicado desde evento remoto {event.event_id}",
    )


def _apply_digital_link_event(
    session: Session,
    *,
    event: ChangeEvent,
    applied_by: str,
    source_workspace_name: str,
) -> None:
    from archive_workbench.catalog_management import (
        _ensure_catalog_source_registration,
        unlink_digital_object_from_unit,
    )

    if event.operation.value == "delete":
        link = session.get(DigitalObjectUnitLink, event.entity_id)
        if link is None:
            old_sha = (_changed_pair(event, "sha256") or (None, None))[0]
            old_unit = (_changed_pair(event, "archival_unit_id") or (None, None))[0]
            relation_type = (_changed_pair(event, "relation_type") or ("represents", None))[0]
            page_start = (_changed_pair(event, "page_start") or (None, None))[0]
            page_end = (_changed_pair(event, "page_end") or (None, None))[0]
            digital = session.scalar(
                select(DigitalObject).where(
                    DigitalObject.project_id == event.project_id,
                    DigitalObject.sha256 == old_sha,
                )
            ) if isinstance(old_sha, str) else None
            if digital is not None and isinstance(old_unit, str):
                link = session.scalar(
                    select(DigitalObjectUnitLink).where(
                        DigitalObjectUnitLink.digital_object_id == digital.id,
                        DigitalObjectUnitLink.archival_unit_id == old_unit,
                        DigitalObjectUnitLink.relation_type == relation_type,
                        DigitalObjectUnitLink.page_start.is_(None)
                        if page_start is None else DigitalObjectUnitLink.page_start == page_start,
                        DigitalObjectUnitLink.page_end.is_(None)
                        if page_end is None else DigitalObjectUnitLink.page_end == page_end,
                    )
                )
        if link is None:
            raise ValueError("El vínculo digital recibido ya no existe")
        current = _digital_link_values(session, link)
        for field in event.changed_fields:
            pair = _changed_pair(event, field)
            if pair is not None:
                _assert_expected(current.get(field), pair[0], event=event, field=field)
        unlink_digital_object_from_unit(
            session,
            link_id=link.id,
            removed_by=f"{applied_by} [bundle de {source_workspace_name}]",
        )
        return
    if event.operation.value != "create":
        raise ValueError("Operación de vínculo digital no admitida")
    if session.get(DigitalObjectUnitLink, event.entity_id) is not None:
        raise ValueError(f"El vínculo digital {event.entity_id} ya existe")
    unit_id = _new_value(event.changed_fields, "archival_unit_id")
    unit = session.get(ArchivalUnit, unit_id)
    if unit is None or unit.project_id != event.project_id:
        raise ValueError("La unidad del vínculo digital no existe")
    values = {field: _new_value(event.changed_fields, field) for field in (
        "digital_object_id", "relation_type", "page_start", "page_end",
        "digital_project_id", "media_type", "original_filename", "sha256",
        "byte_size", "page_count",
    )}
    if values["digital_project_id"] != event.project_id:
        raise ValueError("Los metadatos digitales pertenecen a otro proyecto")
    if not isinstance(values["sha256"], str) or len(values["sha256"]) != 64:
        raise ValueError("El vínculo no contiene un SHA-256 válido")
    digital = session.get(DigitalObject, values["digital_object_id"])
    if digital is None:
        digital = session.scalar(
            select(DigitalObject).where(
                DigitalObject.project_id == event.project_id,
                DigitalObject.sha256 == values["sha256"],
            )
        )
    if digital is None:
        digital = DigitalObject(
            id=values["digital_object_id"],
            project_id=event.project_id,
            media_type=values["media_type"],
            original_filename=values["original_filename"],
            sha256=values["sha256"],
            byte_size=int(values["byte_size"]),
            page_count=values["page_count"],
            created_at=event.timestamp,
        )
        session.add(digital)
        session.flush()
    else:
        expected = {
            "project_id": event.project_id,
            "media_type": values["media_type"],
            "original_filename": values["original_filename"],
            "sha256": values["sha256"],
            "byte_size": values["byte_size"],
            "page_count": values["page_count"],
        }
        for field, expected_value in expected.items():
            if getattr(digital, field) != expected_value:
                raise ValueError(f"El objeto digital existente difiere en {field}")
    actor = f"{applied_by} [bundle de {source_workspace_name}]"
    _ensure_catalog_source_registration(
        session, project_id=event.project_id, unit=unit, digital=digital,
        registered_by=actor, relative_path=None,
    )
    link = DigitalObjectUnitLink(
        id=event.entity_id,
        digital_object_id=digital.id,
        archival_unit_id=unit.id,
        relation_type=values["relation_type"] or "represents",
        page_start=values["page_start"],
        page_end=values["page_end"],
    )
    session.add(link)
    session.flush()



def _replace_authority_aliases(
    session: Session,
    *,
    authority_id: str,
    aliases: Any,
    fallback_actor: str,
    fallback_time: datetime,
) -> None:
    session.execute(delete(AuthorityAlias).where(AuthorityAlias.authority_id == authority_id))
    if aliases is None:
        return
    if not isinstance(aliases, list):
        raise ValueError("Los alias recibidos deben ser una lista")
    seen: set[str] = set()
    for item in aliases:
        if not isinstance(item, dict):
            raise ValueError("Cada alias recibido debe ser un objeto")
        alias = str(item.get("alias") or "").strip()
        normalized = str(item.get("normalized_alias") or "").strip()
        if not alias or not normalized:
            raise ValueError("Un alias recibido no tiene texto o forma normalizada")
        if normalized in seen:
            raise ValueError(f"Alias normalizado duplicado en el bundle: {normalized}")
        seen.add(normalized)
        session.add(
            AuthorityAlias(
                id=str(item.get("id") or new_id()),
                authority_id=authority_id,
                alias=alias,
                normalized_alias=normalized,
                alias_type=str(item.get("alias_type") or "variant"),
                note=(str(item["note"]).strip() or None) if item.get("note") else None,
                created_by=str(item.get("created_by") or fallback_actor),
                created_at=_coerce_datetime(item.get("created_at")) or fallback_time,
            )
        )


def _apply_authority_event(
    session: Session,
    *,
    event: ChangeEvent,
    applied_by: str,
    source_workspace_name: str,
) -> None:
    from archive_workbench.authorities import (
        AUTHORITY_LIFECYCLE_STATUSES,
        AUTHORITY_REVIEW_STATUSES,
        AUTHORITY_TYPES,
        _append_authority_revision,
        normalize_authority_text,
    )

    actor = f"{applied_by} [bundle de {source_workspace_name}]"
    authority = session.get(AuthorityRecord, event.entity_id)
    fields = (
        "entity_type", "preferred_name", "normalized_name", "description",
        "temporal_expression", "temporal_start", "temporal_end",
        "temporal_precision", "temporal_approximate", "temporal_note",
        "lifecycle_status", "review_status", "aliases",
    )
    if event.operation.value == "create":
        if authority is not None:
            raise ValueError(f"La autoridad {event.entity_id} ya existe")
        values = {field: _new_value(event.changed_fields, field) for field in fields}
        if values["entity_type"] not in AUTHORITY_TYPES:
            raise ValueError("La autoridad recibida tiene un tipo inválido")
        preferred_name = str(values["preferred_name"] or "").strip()
        if not preferred_name:
            raise ValueError("La autoridad recibida no tiene nombre preferido")
        normalized = normalize_authority_text(preferred_name)
        if values["normalized_name"] not in {None, normalized}:
            raise ValueError("La forma normalizada de la autoridad no coincide con su nombre")
        if values["lifecycle_status"] not in AUTHORITY_LIFECYCLE_STATUSES:
            raise ValueError("La autoridad recibida tiene un estado de ciclo de vida inválido")
        if values["review_status"] not in AUTHORITY_REVIEW_STATUSES:
            raise ValueError("La autoridad recibida tiene un estado de revisión inválido")
        if session.get(Project, event.project_id) is None:
            raise ValueError("El proyecto de la autoridad recibida no existe")
        authority = AuthorityRecord(
            id=event.entity_id,
            project_id=event.project_id,
            entity_type=values["entity_type"],
            preferred_name=preferred_name,
            normalized_name=normalized,
            description=values["description"],
            temporal_expression=values["temporal_expression"],
            temporal_start=_coerce_date(values["temporal_start"]),
            temporal_end=_coerce_date(values["temporal_end"]),
            temporal_precision=values["temporal_precision"],
            temporal_approximate=bool(values["temporal_approximate"]),
            temporal_note=values["temporal_note"],
            lifecycle_status=values["lifecycle_status"],
            review_status=values["review_status"],
            created_by=event.actor,
            created_at=event.timestamp,
            updated_by=actor,
            updated_at=utc_now(),
            revision=1,
        )
        session.add(authority)
        session.flush()
        _replace_authority_aliases(
            session,
            authority_id=authority.id,
            aliases=values["aliases"] or [],
            fallback_actor=event.actor,
            fallback_time=event.timestamp,
        )
        session.flush()
        _append_authority_revision(
            session,
            authority,
            operation="create",
            changed_by=actor,
            note=f"Aplicado desde evento remoto {event.event_id}",
        )
        return

    if authority is None:
        raise ValueError(f"Autoridad inexistente: {event.entity_id}")
    current = _authority_values(session, authority)
    changed = False
    scalar_mapping = {
        "entity_type": "entity_type",
        "preferred_name": "preferred_name",
        "normalized_name": "normalized_name",
        "description": "description",
        "temporal_expression": "temporal_expression",
        "temporal_start": "temporal_start",
        "temporal_end": "temporal_end",
        "temporal_precision": "temporal_precision",
        "temporal_approximate": "temporal_approximate",
        "temporal_note": "temporal_note",
        "lifecycle_status": "lifecycle_status",
        "review_status": "review_status",
    }
    prospective = dict(current)
    for field, attribute in scalar_mapping.items():
        pair = _changed_pair(event, field)
        if pair is None:
            continue
        _assert_expected(current[field], pair[0], event=event, field=field)
        incoming_value = _coerce_date(pair[1]) if field in {"temporal_start", "temporal_end"} else pair[1]
        prospective[field] = incoming_value
        setattr(authority, attribute, incoming_value)
        changed = True
    if prospective["entity_type"] not in AUTHORITY_TYPES:
        raise ValueError("El tipo de autoridad recibido es inválido")
    if prospective["lifecycle_status"] not in AUTHORITY_LIFECYCLE_STATUSES:
        raise ValueError("El estado de autoridad recibido es inválido")
    if prospective["review_status"] not in AUTHORITY_REVIEW_STATUSES:
        raise ValueError("El estado de revisión recibido es inválido")
    clean_name = str(prospective["preferred_name"] or "").strip()
    if not clean_name:
        raise ValueError("El nombre preferido recibido está vacío")
    normalized = normalize_authority_text(clean_name)
    if prospective["normalized_name"] != normalized:
        raise ValueError("El nombre normalizado recibido no coincide con el nombre preferido")
    authority.preferred_name = clean_name
    aliases_pair = _changed_pair(event, "aliases")
    if aliases_pair is not None:
        _assert_expected(current["aliases"], aliases_pair[0], event=event, field="aliases")
        _replace_authority_aliases(
            session,
            authority_id=authority.id,
            aliases=aliases_pair[1] or [],
            fallback_actor=event.actor,
            fallback_time=event.timestamp,
        )
        changed = True
    if not changed:
        raise ValueError(f"El evento {event.event_id} no contiene cambios de autoridad")
    authority.revision += 1
    authority.updated_by = actor
    authority.updated_at = utc_now()
    session.flush()
    _append_authority_revision(
        session,
        authority,
        operation="exchange_apply",
        changed_by=actor,
        note=f"Aplicado desde evento remoto {event.event_id}",
    )


def _validate_mention_references(
    session: Session,
    *,
    project_id: str,
    object_id: Any,
    authority_id: Any,
) -> EditableObject:
    if not isinstance(object_id, str):
        raise ValueError("La mención recibida no identifica un objeto editable")
    obj = session.get(EditableObject, object_id)
    if obj is None:
        raise ValueError("El objeto editable de la mención no existe")
    digital = session.get(DigitalObject, obj.digital_object_id)
    if digital is None or digital.project_id != project_id:
        raise ValueError("La mención recibida pertenece a otro proyecto")
    if authority_id is not None:
        authority = session.get(AuthorityRecord, authority_id)
        if authority is None or authority.project_id != project_id:
            raise ValueError("La autoridad vinculada a la mención no existe en el proyecto")
    return obj


def _apply_entity_mention_event(
    session: Session,
    *,
    event: ChangeEvent,
    applied_by: str,
    source_workspace_name: str,
) -> None:
    from archive_workbench.authorities import (
        MENTION_SOURCES,
        MENTION_STATUSES,
        _active_mention_at_offsets,
        _append_mention_revision,
        _validate_mention_link,
        normalize_authority_text,
    )

    actor = f"{applied_by} [bundle de {source_workspace_name}]"
    mention = session.get(EntityMention, event.entity_id)
    fields = (
        "editable_object_id", "authority_id", "mention_text", "normalized_text",
        "start_offset", "end_offset", "object_revision_number", "status", "source",
        "confidence", "note",
    )
    if event.operation.value == "create":
        if mention is not None:
            raise ValueError(f"La mención {event.entity_id} ya existe")
        values = {field: _new_value(event.changed_fields, field) for field in fields}
        obj = _validate_mention_references(
            session,
            project_id=event.project_id,
            object_id=values["editable_object_id"],
            authority_id=values["authority_id"],
        )
        text_value = str(values["mention_text"] or "")
        start = values["start_offset"]
        end = values["end_offset"]
        if not text_value:
            raise ValueError("La mención recibida no tiene texto")
        if start is not None or end is not None:
            if not isinstance(start, int) or not isinstance(end, int):
                raise ValueError("Los offsets de la mención recibida son inválidos")
            if start < 0 or end <= start or end > len(obj.current_text):
                raise ValueError("Los offsets de la mención están fuera del texto")
        if values["status"] not in MENTION_STATUSES:
            raise ValueError("El estado de mención recibido es inválido")
        _validate_mention_link(
            status=values["status"], authority_id=values["authority_id"]
        )
        if values["source"] not in MENTION_SOURCES:
            raise ValueError("El origen de mención recibido es inválido")
        if values["status"] != "rejected" and start is not None and end is not None:
            duplicate = _active_mention_at_offsets(
                session,
                object_id=obj.id,
                object_revision_number=int(values["object_revision_number"]),
                start_offset=start,
                end_offset=end,
            )
            if duplicate is not None:
                raise ValueError(
                    "El bundle intenta crear una mención activa duplicada sobre el mismo fragmento"
                )
        normalized = normalize_authority_text(text_value)
        if values["normalized_text"] not in {None, normalized}:
            raise ValueError("La forma normalizada de la mención no coincide")
        mention = EntityMention(
            id=event.entity_id,
            editable_object_id=obj.id,
            authority_id=values["authority_id"],
            mention_text=text_value,
            normalized_text=normalized,
            start_offset=start,
            end_offset=end,
            object_revision_number=int(values["object_revision_number"]),
            status=values["status"],
            source=values["source"],
            confidence=values["confidence"],
            note=values["note"],
            created_by=event.actor,
            created_at=event.timestamp,
            updated_by=actor,
            updated_at=utc_now(),
            revision=1,
        )
        session.add(mention)
        session.flush()
        _append_mention_revision(
            session,
            mention,
            operation="create",
            changed_by=actor,
            note=f"Aplicado desde evento remoto {event.event_id}",
        )
        return

    if mention is None:
        raise ValueError(f"Mención inexistente: {event.entity_id}")
    current = _entity_mention_values(mention)
    prospective = dict(current)
    changed = False
    mapping = {
        "editable_object_id": "editable_object_id",
        "authority_id": "authority_id",
        "mention_text": "mention_text",
        "normalized_text": "normalized_text",
        "start_offset": "start_offset",
        "end_offset": "end_offset",
        "object_revision_number": "object_revision_number",
        "status": "status",
        "source": "source",
        "confidence": "confidence",
        "note": "note",
    }
    for field, attribute in mapping.items():
        pair = _changed_pair(event, field)
        if pair is None:
            continue
        _assert_expected(current[field], pair[0], event=event, field=field)
        prospective[field] = pair[1]
        setattr(mention, attribute, pair[1])
        changed = True
    if not changed:
        raise ValueError(f"El evento {event.event_id} no contiene cambios de mención")
    obj = _validate_mention_references(
        session,
        project_id=event.project_id,
        object_id=prospective["editable_object_id"],
        authority_id=prospective["authority_id"],
    )
    if prospective["status"] not in MENTION_STATUSES:
        raise ValueError("El estado de mención recibido es inválido")
    _validate_mention_link(
        status=prospective["status"], authority_id=prospective["authority_id"]
    )
    if prospective["source"] not in MENTION_SOURCES:
        raise ValueError("El origen de mención recibido es inválido")
    clean_text = str(prospective["mention_text"] or "")
    if not clean_text:
        raise ValueError("El texto recibido de la mención está vacío")
    normalized = normalize_authority_text(clean_text)
    if prospective["normalized_text"] != normalized:
        raise ValueError("La forma normalizada recibida no coincide con la mención")
    start = prospective["start_offset"]
    end = prospective["end_offset"]
    if start is not None or end is not None:
        if not isinstance(start, int) or not isinstance(end, int):
            raise ValueError("Los offsets recibidos son inválidos")
        if start < 0 or end <= start or end > len(obj.current_text):
            raise ValueError("Los offsets recibidos están fuera del texto")
    if prospective["status"] != "rejected" and start is not None and end is not None:
        duplicate = _active_mention_at_offsets(
            session,
            object_id=obj.id,
            object_revision_number=int(prospective["object_revision_number"]),
            start_offset=start,
            end_offset=end,
            exclude_mention_id=mention.id,
        )
        if duplicate is not None:
            raise ValueError(
                "El bundle produciría dos menciones activas sobre el mismo fragmento"
            )
    mention.revision += 1
    mention.updated_by = actor
    mention.updated_at = utc_now()
    session.flush()
    _append_mention_revision(
        session,
        mention,
        operation="exchange_apply",
        changed_by=actor,
        note=f"Aplicado desde evento remoto {event.event_id}",
    )

def _apply_entity_relation_event(
    session: Session,
    *,
    event: ChangeEvent,
    applied_by: str,
    source_workspace_name: str,
) -> None:
    from archive_workbench.relations import (
        RELATION_LIFECYCLE_STATUSES,
        RELATION_REVIEW_STATUSES,
        _append_relation_revision,
        _validate_target,
    )

    actor = f"{applied_by} [bundle de {source_workspace_name}]"
    relation = session.get(EntityRelation, event.entity_id)
    fields = (
        "source_authority_id", "relation_label", "target_authority_id",
        "target_archival_unit_id", "target_document_part_id", "evidence_note",
        "temporal_expression", "temporal_start", "temporal_end",
        "temporal_precision", "temporal_approximate", "temporal_note",
        "lifecycle_status", "review_status",
    )
    if event.operation.value == "create":
        if relation is not None:
            raise ValueError(f"La relación {event.entity_id} ya existe")
        values = {field: _new_value(event.changed_fields, field) for field in fields}
        source = session.get(AuthorityRecord, values["source_authority_id"])
        if source is None or source.project_id != event.project_id:
            raise ValueError("La entidad de origen de la relación no existe")
        targets = [
            ("entity", values["target_authority_id"]),
            ("archival_unit", values["target_archival_unit_id"]),
            ("document_part", values["target_document_part_id"]),
        ]
        selected = [(kind, value) for kind, value in targets if value is not None]
        if len(selected) != 1:
            raise ValueError("La relación recibida no tiene exactamente un destino")
        _validate_target(
            session,
            project_id=event.project_id,
            source_authority_id=source.id,
            target_kind=selected[0][0],
            target_id=str(selected[0][1]),
        )
        label = str(values["relation_label"] or "").strip()
        if not label:
            raise ValueError("La relación recibida no tiene etiqueta")
        if values["review_status"] not in RELATION_REVIEW_STATUSES:
            raise ValueError("Estado de revisión de relación inválido")
        if values["lifecycle_status"] not in RELATION_LIFECYCLE_STATUSES:
            raise ValueError("Estado de relación inválido")
        relation = EntityRelation(
            id=event.entity_id,
            project_id=event.project_id,
            source_authority_id=source.id,
            relation_label=label,
            target_authority_id=values["target_authority_id"],
            target_archival_unit_id=values["target_archival_unit_id"],
            target_document_part_id=values["target_document_part_id"],
            evidence_note=values["evidence_note"],
            temporal_expression=values["temporal_expression"],
            temporal_start=_coerce_date(values["temporal_start"]),
            temporal_end=_coerce_date(values["temporal_end"]),
            temporal_precision=values["temporal_precision"],
            temporal_approximate=bool(values["temporal_approximate"]),
            temporal_note=values["temporal_note"],
            lifecycle_status=values["lifecycle_status"],
            review_status=values["review_status"],
            created_by=event.actor,
            created_at=event.timestamp,
            updated_by=actor,
            updated_at=utc_now(),
            revision=1,
        )
        session.add(relation)
        session.flush()
        _append_relation_revision(
            session, relation, operation="create", changed_by=actor,
            note=f"Aplicado desde evento remoto {event.event_id}",
        )
        return

    if relation is None:
        raise ValueError(f"Relación inexistente: {event.entity_id}")
    current = _entity_relation_values(relation)
    prospective = dict(current)
    changed = False
    for field in fields:
        pair = _changed_pair(event, field)
        if pair is None:
            continue
        _assert_expected(current[field], pair[0], event=event, field=field)
        incoming_value = _coerce_date(pair[1]) if field in {"temporal_start", "temporal_end"} else pair[1]
        prospective[field] = incoming_value
        setattr(relation, field, incoming_value)
        changed = True
    if not changed:
        raise ValueError(f"El evento {event.event_id} no contiene cambios de relación")
    source = session.get(AuthorityRecord, prospective["source_authority_id"])
    if source is None or source.project_id != event.project_id:
        raise ValueError("La entidad de origen de la relación no existe")
    targets = [
        ("entity", prospective["target_authority_id"]),
        ("archival_unit", prospective["target_archival_unit_id"]),
        ("document_part", prospective["target_document_part_id"]),
    ]
    selected = [(kind, value) for kind, value in targets if value is not None]
    if len(selected) != 1:
        raise ValueError("La relación resultante no tiene exactamente un destino")
    _validate_target(
        session,
        project_id=event.project_id,
        source_authority_id=source.id,
        target_kind=selected[0][0],
        target_id=str(selected[0][1]),
    )
    label = str(prospective["relation_label"] or "").strip()
    if not label:
        raise ValueError("La relación resultante no tiene etiqueta")
    relation.relation_label = label
    if prospective["review_status"] not in RELATION_REVIEW_STATUSES:
        raise ValueError("Estado de revisión de relación inválido")
    if prospective["lifecycle_status"] not in RELATION_LIFECYCLE_STATUSES:
        raise ValueError("Estado de relación inválido")
    relation.revision += 1
    relation.updated_by = actor
    relation.updated_at = utc_now()
    session.flush()
    _append_relation_revision(
        session, relation, operation="exchange_apply", changed_by=actor,
        note=f"Aplicado desde evento remoto {event.event_id}",
    )


def _apply_work_assignment_event(
    session: Session,
    *,
    event: ChangeEvent,
    applied_by: str,
    source_workspace_name: str,
) -> None:
    from archive_workbench.work import (
        ASSIGNMENT_KINDS,
        ASSIGNMENT_PRIORITIES,
        ASSIGNMENT_STATUSES,
        CROSS_REVIEW_OUTCOMES,
        _append_assignment_revision,
        _registration,
        _validate_parent,
        _validate_scope,
    )

    actor = f"{applied_by} [bundle de {source_workspace_name}]"
    assignment = session.get(WorkAssignment, event.entity_id)
    fields = (
        "project_id", "source_type", "source_key", "page_start", "page_end",
        "assignment_kind", "assignee", "status", "priority", "due_at",
        "parent_assignment_id", "outcome", "note", "submitted_at", "completed_at",
    )
    if event.operation.value == "create":
        if assignment is not None:
            raise ValueError(f"La asignación {event.entity_id} ya existe")
        values = {field: _new_value(event.changed_fields, field) for field in fields}
        if values["project_id"] != event.project_id:
            raise ValueError("La asignación recibida pertenece a otro proyecto")
        if values["assignment_kind"] not in ASSIGNMENT_KINDS:
            raise ValueError("Tipo de asignación recibido inválido")
        if values["status"] not in ASSIGNMENT_STATUSES:
            raise ValueError("Estado de asignación recibido inválido")
        if values["priority"] not in ASSIGNMENT_PRIORITIES:
            raise ValueError("Prioridad de asignación recibida inválida")
        if values["outcome"] is not None and values["outcome"] not in CROSS_REVIEW_OUTCOMES:
            raise ValueError("Resultado de revisión cruzada recibido inválido")
        assignee = str(values["assignee"] or "").strip()
        if not assignee:
            raise ValueError("La asignación recibida no tiene responsable")
        source_type = str(values["source_type"] or "")
        source_key = str(values["source_key"] or "")
        registration = _registration(
            session, project_id=event.project_id, source_type=source_type, source_key=source_key
        )
        page_start = values["page_start"]
        page_end = values["page_end"]
        _validate_scope(
            session, registration=registration, page_start=page_start, page_end=page_end
        )
        _validate_parent(
            session,
            project_id=event.project_id,
            assignment_kind=str(values["assignment_kind"]),
            assignee=assignee,
            source_type=source_type,
            source_key=source_key,
            page_start=page_start,
            page_end=page_end,
            parent_assignment_id=values["parent_assignment_id"],
        )
        if values["assignment_kind"] != "cross_review" and values["outcome"] is not None:
            raise ValueError("Solo una revisión cruzada puede registrar resultado")
        if values["assignment_kind"] == "cross_review" and values["status"] == "completed" and values["outcome"] is None:
            raise ValueError("La revisión cruzada completada no tiene resultado")
        assignment = WorkAssignment(
            id=event.entity_id,
            project_id=event.project_id,
            source_type=source_type,
            source_key=source_key,
            page_start=page_start,
            page_end=page_end,
            assignment_kind=str(values["assignment_kind"]),
            assignee=assignee,
            status=str(values["status"]),
            priority=str(values["priority"]),
            due_at=_coerce_datetime(values["due_at"]),
            parent_assignment_id=values["parent_assignment_id"],
            outcome=values["outcome"],
            note=values["note"],
            submitted_at=_coerce_datetime(values["submitted_at"]),
            completed_at=_coerce_datetime(values["completed_at"]),
            created_by=event.actor,
            created_at=event.timestamp,
            updated_by=actor,
            updated_at=utc_now(),
            revision=1,
        )
        session.add(assignment)
        session.flush()
        _append_assignment_revision(
            session, assignment, operation="create", changed_by=actor,
            note=f"Aplicado desde evento remoto {event.event_id}",
        )
        return

    if assignment is None:
        raise ValueError(f"Asignación inexistente: {event.entity_id}")
    current = _work_assignment_values(assignment)
    prospective = dict(current)
    changed = False
    for field in fields:
        pair = _changed_pair(event, field)
        if pair is None:
            continue
        _assert_expected(current[field], pair[0], event=event, field=field)
        prospective[field] = pair[1]
        changed = True
    if not changed:
        raise ValueError(f"El evento {event.event_id} no contiene cambios de asignación")
    if prospective["project_id"] != event.project_id:
        raise ValueError("La asignación resultante pertenece a otro proyecto")
    if prospective["assignment_kind"] not in ASSIGNMENT_KINDS:
        raise ValueError("Tipo de asignación resultante inválido")
    if prospective["status"] not in ASSIGNMENT_STATUSES:
        raise ValueError("Estado de asignación resultante inválido")
    if prospective["priority"] not in ASSIGNMENT_PRIORITIES:
        raise ValueError("Prioridad de asignación resultante inválida")
    if prospective["outcome"] is not None and prospective["outcome"] not in CROSS_REVIEW_OUTCOMES:
        raise ValueError("Resultado de revisión cruzada resultante inválido")
    assignee = str(prospective["assignee"] or "").strip()
    if not assignee:
        raise ValueError("La asignación resultante no tiene responsable")
    registration = _registration(
        session,
        project_id=event.project_id,
        source_type=str(prospective["source_type"]),
        source_key=str(prospective["source_key"]),
    )
    _validate_scope(
        session,
        registration=registration,
        page_start=prospective["page_start"],
        page_end=prospective["page_end"],
    )
    _validate_parent(
        session,
        project_id=event.project_id,
        assignment_kind=str(prospective["assignment_kind"]),
        assignee=assignee,
        source_type=str(prospective["source_type"]),
        source_key=str(prospective["source_key"]),
        page_start=prospective["page_start"],
        page_end=prospective["page_end"],
        parent_assignment_id=prospective["parent_assignment_id"],
    )
    if prospective["assignment_kind"] != "cross_review" and prospective["outcome"] is not None:
        raise ValueError("Solo una revisión cruzada puede registrar resultado")
    if prospective["assignment_kind"] == "cross_review" and prospective["status"] == "completed" and prospective["outcome"] is None:
        raise ValueError("La revisión cruzada completada no tiene resultado")
    assignment.source_type = str(prospective["source_type"])
    assignment.source_key = str(prospective["source_key"])
    assignment.page_start = prospective["page_start"]
    assignment.page_end = prospective["page_end"]
    assignment.assignment_kind = str(prospective["assignment_kind"])
    assignment.assignee = assignee
    assignment.status = str(prospective["status"])
    assignment.priority = str(prospective["priority"])
    assignment.due_at = _coerce_datetime(prospective["due_at"])
    assignment.parent_assignment_id = prospective["parent_assignment_id"]
    assignment.outcome = prospective["outcome"]
    assignment.note = prospective["note"]
    assignment.submitted_at = _coerce_datetime(prospective["submitted_at"])
    assignment.completed_at = _coerce_datetime(prospective["completed_at"])
    assignment.revision += 1
    assignment.updated_by = actor
    assignment.updated_at = utc_now()
    session.flush()
    _append_assignment_revision(
        session, assignment, operation="exchange_apply", changed_by=actor,
        note=f"Aplicado desde evento remoto {event.event_id}",
    )



def _apply_incoming_event(
    session: Session,
    *,
    event: ChangeEvent,
    applied_by: str,
    source_workspace_name: str,
) -> None:
    if event.entity_type == "editable_object":
        _apply_object_event(
            session,
            event=event,
            applied_by=applied_by,
            source_workspace_name=source_workspace_name,
        )
    elif event.entity_type == "editable_page":
        _apply_page_event(
            session,
            event=event,
            applied_by=applied_by,
            source_workspace_name=source_workspace_name,
        )
    elif event.entity_type == "editable_object_comment":
        _apply_comment_event(
            session,
            event=event,
            applied_by=applied_by,
            source_workspace_name=source_workspace_name,
        )
    elif event.entity_type == "editable_object_tag":
        _apply_tag_event(
            session,
            event=event,
            applied_by=applied_by,
            source_workspace_name=source_workspace_name,
        )
    elif event.entity_type == "archival_unit":
        _apply_archival_unit_event(
            session,
            event=event,
            applied_by=applied_by,
            source_workspace_name=source_workspace_name,
        )
    elif event.entity_type == "digital_object_unit_link":
        _apply_digital_link_event(
            session,
            event=event,
            applied_by=applied_by,
            source_workspace_name=source_workspace_name,
        )
    elif event.entity_type == "authority_record":
        _apply_authority_event(
            session,
            event=event,
            applied_by=applied_by,
            source_workspace_name=source_workspace_name,
        )
    elif event.entity_type == "entity_mention":
        _apply_entity_mention_event(
            session,
            event=event,
            applied_by=applied_by,
            source_workspace_name=source_workspace_name,
        )
    elif event.entity_type == "entity_relation":
        _apply_entity_relation_event(
            session,
            event=event,
            applied_by=applied_by,
            source_workspace_name=source_workspace_name,
        )
    elif event.entity_type == "work_assignment":
        _apply_work_assignment_event(
            session,
            event=event,
            applied_by=applied_by,
            source_workspace_name=source_workspace_name,
        )
    else:
        raise ValueError(f"Tipo de entidad no aplicable: {event.entity_type}")


def apply_change_bundle(
    session: Session,
    *,
    project_root: Path,
    bundle_ref: str,
    applied_by: str,
) -> BundleApplicationSummary:
    from archive_workbench.db.models import (
        ExchangeBundleApplication,
        ExchangeDryRun,
        ExchangeIncomingEventAssessment,
    )

    dry = session.scalar(
        select(ExchangeDryRun).where(ExchangeDryRun.bundle_id == bundle_ref)
    )
    if dry is None:
        candidate = Path(bundle_ref).expanduser()
        if candidate.is_file():
            inspection = inspect_change_bundle(candidate)
            dry = session.scalar(
                select(ExchangeDryRun).where(
                    ExchangeDryRun.bundle_id == inspection.manifest.bundle_id
                )
            )
        if dry is None:
            raise ValueError(
                "El bundle todavía no tiene un dry-run persistido. Ejecutá exchange-dry-run primero."
            )
    existing = session.scalar(
        select(ExchangeBundleApplication).where(
            ExchangeBundleApplication.bundle_id == dry.bundle_id
        )
    )
    if existing is not None:
        raise ValueError(f"El bundle {dry.bundle_id} ya fue aplicado")
    if dry.overall_status not in {"ready_to_apply", "ready_to_apply_resolved"}:
        raise ValueError(
            f"El bundle no puede aplicarse: estado dry-run {dry.overall_status}"
        )
    workspace = ensure_exchange_workspace(session, changed_by=applied_by)
    project = _project(session)
    if dry.assessed_state_sha256 is None or dry.assessed_sequence_number is None:
        raise ValueError(
            "El dry-run fue creado antes del control de caducidad. "
            "Repetí exchange-dry-run antes de aplicar."
        )
    current_state_sha256 = current_editable_state_sha256(session, project.id)
    current_sequence_number = _current_sequence(session, workspace.id)
    if (
        current_state_sha256 != dry.assessed_state_sha256
        or current_sequence_number != dry.assessed_sequence_number
    ):
        raise ValueError(
            "El dry-run caducó porque la copia local cambió después de la evaluación. "
            "Repetí exchange-dry-run antes de aplicar."
        )

    assessments = session.scalars(
        select(ExchangeIncomingEventAssessment)
        .where(ExchangeIncomingEventAssessment.dry_run_id == dry.id)
        .order_by(ExchangeIncomingEventAssessment.source_sequence_number)
    ).all()
    blocked = [row for row in assessments if row.disposition in {"review", "conflict"}]
    if blocked and dry.overall_status != "ready_to_apply_resolved":
        raise ValueError("El bundle contiene eventos revisables o conflictivos")
    record = session.get(ExchangeBundleRecord, dry.bundle_record_id)
    if record is None:
        raise ValueError("No existe el registro local del bundle recibido")
    bundle_path = _stored_bundle_path(project_root, record)
    inspection, events, _normalization_warnings = _load_bundle_events(bundle_path)
    if inspection.manifest.bundle_id != dry.bundle_id:
        raise ValueError("El archivo almacenado no coincide con el dry-run")
    if inspection.bundle_sha256 != record.bundle_sha256:
        raise ValueError("El SHA-256 del bundle almacenado cambió después del dry-run")
    by_id = {event.event_id: event for event in events}
    if set(by_id) != {row.incoming_event_id for row in assessments}:
        raise ValueError("Los eventos del bundle ya no coinciden con la evaluación persistida")
    for row in assessments:
        persisted = ChangeEvent.model_validate(row.incoming_event_json)
        if persisted.model_dump(mode="json", exclude_none=True) != by_id[row.incoming_event_id].model_dump(mode="json", exclude_none=True):
            raise ValueError(
                f"El evento {row.incoming_event_id} cambió semánticamente desde el dry-run"
            )

    backup_path, backup_sha = _backup_sqlite(project_root, dry.bundle_id)
    sequence_start = _current_sequence(session, workspace.id)
    application = ExchangeBundleApplication(
        id=new_id(),
        workspace_id=workspace.id,
        dry_run_id=dry.id,
        bundle_record_id=record.id,
        bundle_id=dry.bundle_id,
        source_workspace_id=dry.source_workspace_id,
        backup_relative_path=_relative_or_absolute(backup_path, project_root),
        backup_sha256=backup_sha,
        applied_event_count=0,
        duplicate_event_count=0,
        kept_local_event_count=0,
        local_sequence_start=sequence_start,
        local_sequence_end=sequence_start,
        checkpoint_id=None,
        checkpoint_label=None,
        status="applying",
        applied_by=applied_by,
        applied_at=utc_now(),
    )
    session.add(application)
    session.flush()

    applied_count = 0
    duplicate_count = 0
    kept_local_count = 0
    for assessment in assessments:
        event = by_id[assessment.incoming_event_id]
        if assessment.disposition == "duplicate":
            assessment.application_status = "skipped_duplicate"
            duplicate_count += 1
        elif assessment.disposition == "apply":
            _apply_incoming_event(
                session,
                event=event,
                applied_by=applied_by,
                source_workspace_name=dry.source_workspace_name,
            )
            assessment.application_status = "applied"
            applied_count += 1
        elif assessment.disposition in {"review", "conflict"}:
            effective, resolution_status_value = _resolved_event(
                session,
                dry_run_id=dry.id,
                assessment=assessment,
                event=event,
            )
            if effective is None:
                assessment.application_status = resolution_status_value
                if resolution_status_value == "already_matched":
                    duplicate_count += 1
                else:
                    kept_local_count += 1
            else:
                _apply_incoming_event(
                    session,
                    event=effective,
                    applied_by=applied_by,
                    source_workspace_name=dry.source_workspace_name,
                )
                assessment.application_status = resolution_status_value
                applied_count += 1
        else:
            raise ValueError(
                f"Disposición inesperada durante la aplicación: {assessment.disposition}"
            )
        assessment.application_id = application.id
        assessment.applied_at = utc_now()
        session.flush()

    session.flush()
    sequence_end = _current_sequence(session, workspace.id)
    checkpoint_label = f"incoming_{short_id(dry.bundle_id)}"
    checkpoint = create_exchange_checkpoint(
        session,
        label=checkpoint_label,
        created_by=applied_by,
        note=(
            f"Estado posterior a aplicar bundle {dry.bundle_id} de "
            f"{dry.source_workspace_name} ({dry.source_workspace_id})"
        ),
    )
    application.applied_event_count = applied_count
    application.duplicate_event_count = duplicate_count
    application.kept_local_event_count = kept_local_count
    application.local_sequence_end = sequence_end
    application.checkpoint_id = checkpoint.id
    application.checkpoint_label = checkpoint.label
    application.status = "applied"
    record.status = "applied"
    dry.overall_status = "applied"
    session.flush()

    report_dir = project_root.resolve() / "exchange" / "incoming" / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_json = report_dir / f"{dry.bundle_id}_application.json"
    report_md = report_dir / f"{dry.bundle_id}_application.md"
    payload = {
        "schema_version": "1.0",
        "application_id": application.id,
        "bundle_id": dry.bundle_id,
        "source_workspace_id": dry.source_workspace_id,
        "source_workspace_name": dry.source_workspace_name,
        "applied_event_count": applied_count,
        "duplicate_event_count": duplicate_count,
        "kept_local_event_count": kept_local_count,
        "backup_path": application.backup_relative_path,
        "backup_sha256": backup_sha,
        "local_sequence_start": sequence_start,
        "local_sequence_end": sequence_end,
        "checkpoint_id": checkpoint.id,
        "checkpoint_label": checkpoint.label,
        "applied_by": applied_by,
        "applied_at": application.applied_at.isoformat(),
    }
    report_json.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    report_md.write_text(
        "\n".join(
            [
                f"# Aplicación de bundle {dry.bundle_id}",
                "",
                f"- Origen: `{dry.source_workspace_name}` (`{dry.source_workspace_id}`)",
                f"- Eventos aplicados: {applied_count}",
                f"- Duplicados omitidos: {duplicate_count}",
                f"- Resoluciones que conservaron la versión local: {kept_local_count}",
                f"- Backup: `{application.backup_relative_path}`",
                f"- SHA-256 del backup: `{backup_sha}`",
                f"- Secuencia local: {sequence_start} → {sequence_end}",
                f"- Checkpoint: `{checkpoint.label}` (`{checkpoint.id}`)",
                f"- Aplicado por: {applied_by}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return BundleApplicationSummary(
        application_id=application.id,
        bundle_id=dry.bundle_id,
        source_workspace_name=dry.source_workspace_name,
        applied_event_count=applied_count,
        duplicate_event_count=duplicate_count,
        kept_local_event_count=kept_local_count,
        backup_path=backup_path,
        backup_sha256=backup_sha,
        local_sequence_start=sequence_start,
        local_sequence_end=sequence_end,
        checkpoint_id=checkpoint.id,
        checkpoint_label=checkpoint.label,
        report_json_path=report_json,
        report_markdown_path=report_md,
    )


def bundle_application_rows(session: Session) -> list[BundleApplicationRow]:
    rows = session.scalars(
        select(ExchangeBundleApplication).order_by(
            ExchangeBundleApplication.applied_at.desc(),
            ExchangeBundleApplication.id,
        )
    ).all()
    return [
        BundleApplicationRow(
            application_id=row.id,
            bundle_id=row.bundle_id,
            source_workspace_id=row.source_workspace_id,
            applied_event_count=row.applied_event_count,
            duplicate_event_count=row.duplicate_event_count,
            kept_local_event_count=row.kept_local_event_count,
            status=row.status,
            checkpoint_label=row.checkpoint_label,
            backup_relative_path=row.backup_relative_path,
            applied_by=row.applied_by,
            applied_at=row.applied_at,
        )
        for row in rows
    ]
