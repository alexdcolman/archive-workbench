from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from archive_workbench.sources import PROCESSABLE_SOURCE_TYPES
from archive_workbench.db.models import (
    DigitalObject,
    DocumentPart,
    EditableObject,
    SourceRegistration,
    utc_now,
)
from archive_workbench.editing import _append_revision


@dataclass(slots=True)
class PartAssignmentRow:
    part_id: str
    part_key: str
    title: str
    part_type: str
    page_sequence: list[int]
    status: str


def _digital_for_source(session: Session, source_key: str) -> DigitalObject:
    digital = session.scalar(
        select(DigitalObject)
        .join(SourceRegistration, SourceRegistration.digital_object_id == DigitalObject.id)
        .where(
            SourceRegistration.source_type.in_(PROCESSABLE_SOURCE_TYPES),
            SourceRegistration.source_key == source_key,
        )
    )
    if digital is None:
        raise ValueError(f"source_key no registrado: {source_key}")
    return digital


def document_part_rows(
    session: Session, *, source_key: str, page: int | None = None
) -> list[PartAssignmentRow]:
    digital = _digital_for_source(session, source_key)
    parts = session.scalars(
        select(DocumentPart)
        .where(DocumentPart.digital_object_id == digital.id)
        .order_by(DocumentPart.page_start, DocumentPart.page_end, DocumentPart.part_key)
    ).all()
    result: list[PartAssignmentRow] = []
    for item in parts:
        sequence = list(item.page_sequence_json or range(item.page_start, item.page_end + 1))
        if page is not None and page not in sequence:
            continue
        result.append(
            PartAssignmentRow(
                part_id=item.id,
                part_key=item.part_key,
                title=item.title,
                part_type=item.part_type,
                page_sequence=sequence,
                status=item.status,
            )
        )
    return result


def _validate_part_for_object(
    session: Session, *, obj: EditableObject, part_id: str | None
) -> DocumentPart | None:
    if part_id is None:
        return None
    part = session.get(DocumentPart, part_id)
    if part is None:
        raise ValueError(f"Parte interna inexistente: {part_id}")
    if part.digital_object_id != obj.digital_object_id:
        raise ValueError("La parte interna pertenece a otro documento")
    sequence = list(part.page_sequence_json or range(part.page_start, part.page_end + 1))
    if obj.page_number not in sequence:
        raise ValueError(
            f"La parte {part.part_key} no incluye la página física {obj.page_number}"
        )
    return part


def assign_editable_object_part(
    session: Session,
    *,
    object_id: str,
    part_id: str | None,
    expected_revision: int,
    changed_by: str,
    note: str | None = None,
) -> EditableObject:
    obj = session.get(EditableObject, object_id)
    if obj is None:
        raise ValueError(f"Objeto editable inexistente: {object_id}")
    if obj.revision_number != expected_revision:
        raise ValueError(
            f"Conflicto de revisión: se esperaba {expected_revision}, "
            f"pero el objeto está en {obj.revision_number}"
        )
    part = _validate_part_for_object(session, obj=obj, part_id=part_id)
    if obj.document_part_id == part_id:
        return obj
    base = obj.revision_number
    obj.document_part_id = part_id
    obj.revision_number += 1
    obj.updated_by = changed_by
    obj.updated_at = utc_now()
    _append_revision(
        session,
        obj,
        operation="assign_part",
        created_by=changed_by,
        note=note
        or (
            f"Asignado a la parte {part.part_key}"
            if part is not None
            else "Desvinculado de la parte interna"
        ),
        base_revision_number=base,
    )
    return obj


def assign_page_objects_to_part(
    session: Session,
    *,
    editable_page_id: str,
    part_id: str | None,
    changed_by: str,
    note: str | None = None,
) -> list[EditableObject]:
    objects = session.scalars(
        select(EditableObject)
        .where(
            EditableObject.editable_page_id == editable_page_id,
            EditableObject.lifecycle_status == "active",
        )
        .order_by(EditableObject.current_order_index, EditableObject.id)
    ).all()
    if not objects:
        raise ValueError("La página no tiene objetos activos")
    changed: list[EditableObject] = []
    for obj in objects:
        _validate_part_for_object(session, obj=obj, part_id=part_id)
        if obj.document_part_id == part_id:
            continue
        base = obj.revision_number
        obj.document_part_id = part_id
        obj.revision_number += 1
        obj.updated_by = changed_by
        obj.updated_at = utc_now()
        _append_revision(
            session,
            obj,
            operation="assign_part",
            created_by=changed_by,
            note=note or "Asignación conjunta de parte interna para la página",
            base_revision_number=base,
        )
        changed.append(obj)
    return changed
