from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from archive_workbench.db.models import (
    EditableObject,
    EditableObjectComment,
    EditableObjectTag,
    EditablePage,
    utc_now,
)
from archive_workbench.identity import new_id
from archive_workbench.editing import _append_page_revision

REVIEW_STATUSES = ("unreviewed", "needs_review", "reviewed", "approved")
TAG_KINDS = ("thematic", "conceptual", "workflow", "unclassified")


@dataclass(slots=True)
class CommentRow:
    comment_id: str
    body: str
    created_by: str
    created_at: datetime


@dataclass(slots=True)
class TagRow:
    tag_id: str
    tag: str
    tag_kind: str
    created_by: str
    created_at: datetime


def _validate_status(status: str) -> None:
    if status not in REVIEW_STATUSES:
        raise ValueError("Estado de revisión inválido: " + status)


def _validate_tag_kind(tag_kind: str) -> None:
    if tag_kind not in TAG_KINDS:
        raise ValueError("Categoría de etiqueta inválida: " + tag_kind)


def normalize_tag(tag: str) -> str:
    return re.sub(r"\s+", " ", tag.strip()).casefold()


def add_object_comment(
    session: Session, *, object_id: str, body: str, created_by: str
) -> EditableObjectComment:
    if session.get(EditableObject, object_id) is None:
        raise ValueError(f"Objeto editable inexistente: {object_id}")
    clean = body.strip()
    if not clean:
        raise ValueError("El comentario no puede estar vacío")
    comment = EditableObjectComment(
        id=new_id(),
        editable_object_id=object_id,
        body=clean,
        created_by=created_by,
        created_at=utc_now(),
    )
    session.add(comment)
    return comment


def object_comment_rows(session: Session, *, object_id: str) -> list[CommentRow]:
    rows = session.scalars(
        select(EditableObjectComment)
        .where(EditableObjectComment.editable_object_id == object_id)
        .order_by(EditableObjectComment.created_at, EditableObjectComment.id)
    ).all()
    return [
        CommentRow(
            comment_id=item.id,
            body=item.body,
            created_by=item.created_by,
            created_at=item.created_at,
        )
        for item in rows
    ]


def add_object_tag(
    session: Session,
    *,
    object_id: str,
    tag: str,
    tag_kind: str = "unclassified",
    created_by: str,
) -> EditableObjectTag:
    if session.get(EditableObject, object_id) is None:
        raise ValueError(f"Objeto editable inexistente: {object_id}")
    _validate_tag_kind(tag_kind)
    clean = re.sub(r"\s+", " ", tag.strip())
    normalized = normalize_tag(clean)
    if not normalized:
        raise ValueError("La etiqueta no puede estar vacía")
    existing = session.scalar(
        select(EditableObjectTag).where(
            EditableObjectTag.editable_object_id == object_id,
            EditableObjectTag.tag_kind == tag_kind,
            EditableObjectTag.normalized_tag == normalized,
        )
    )
    if existing is not None:
        return existing
    item = EditableObjectTag(
        id=new_id(),
        editable_object_id=object_id,
        tag=clean,
        normalized_tag=normalized,
        tag_kind=tag_kind,
        created_by=created_by,
        created_at=utc_now(),
    )
    session.add(item)
    return item


def remove_object_tag(
    session: Session,
    *,
    object_id: str,
    tag_id: str | None = None,
    tag: str | None = None,
    tag_kind: str | None = None,
) -> None:
    if tag_id:
        result = session.execute(
            delete(EditableObjectTag).where(
                EditableObjectTag.id == tag_id,
                EditableObjectTag.editable_object_id == object_id,
            )
        )
        label = tag_id
    else:
        if tag is None:
            raise ValueError("Debe indicar tag_id o tag")
        normalized = normalize_tag(tag)
        conditions = [
            EditableObjectTag.editable_object_id == object_id,
            EditableObjectTag.normalized_tag == normalized,
        ]
        if tag_kind is not None:
            _validate_tag_kind(tag_kind)
            conditions.append(EditableObjectTag.tag_kind == tag_kind)
        result = session.execute(delete(EditableObjectTag).where(*conditions))
        label = tag
    if not result.rowcount:
        raise ValueError(f"La etiqueta no está asignada al objeto: {label}")


def object_tag_rows(session: Session, *, object_id: str) -> list[TagRow]:
    rows = session.scalars(
        select(EditableObjectTag)
        .where(EditableObjectTag.editable_object_id == object_id)
        .order_by(EditableObjectTag.tag_kind, EditableObjectTag.normalized_tag)
    ).all()
    return [
        TagRow(
            tag_id=item.id,
            tag=item.tag,
            tag_kind=item.tag_kind,
            created_by=item.created_by,
            created_at=item.created_at,
        )
        for item in rows
    ]


def object_tags(session: Session, *, object_id: str) -> list[str]:
    """Compatibilidad: devuelve únicamente los textos de las etiquetas."""
    return [item.tag for item in object_tag_rows(session, object_id=object_id)]


def set_object_review_status(
    session: Session, *, object_id: str, status: str, changed_by: str
) -> EditableObject:
    _validate_status(status)
    obj = session.get(EditableObject, object_id)
    if obj is None:
        raise ValueError(f"Objeto editable inexistente: {object_id}")
    obj.review_status = status
    obj.updated_by = changed_by
    obj.updated_at = utc_now()
    return obj


def set_page_review_status(
    session: Session,
    *,
    editable_page_id: str,
    status: str,
    changed_by: str,
    note: str | None = None,
) -> EditablePage:
    _validate_status(status)
    page = session.get(EditablePage, editable_page_id)
    if page is None:
        raise ValueError(f"Página editable inexistente: {editable_page_id}")
    clean_note = note.strip() if note and note.strip() else None
    if page.review_status == status and page.review_note == clean_note:
        return page
    base = page.revision_number
    page.review_status = status
    page.review_note = clean_note
    page.reviewed_by = changed_by
    page.reviewed_at = utc_now()
    page.updated_at = utc_now()
    page.revision_number += 1
    _append_page_revision(
        session,
        page,
        operation="review_status",
        created_by=changed_by,
        note=clean_note,
        details={"review_status": status},
        base_revision_number=base,
    )
    return page
