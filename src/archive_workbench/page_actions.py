from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, TypeVar

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from archive_workbench.db.models import (
    EditableObject,
    EditablePage,
    EditablePageAction,
    utc_now,
)
from archive_workbench.editing import _append_page_revision, _append_revision
from archive_workbench.identity import new_id

T = TypeVar("T")


@dataclass(slots=True)
class PageActionAvailability:
    can_undo: bool
    can_redo: bool
    undo_label: str | None = None
    redo_label: str | None = None


def _object_snapshot(obj: EditableObject) -> dict[str, Any]:
    return {
        "id": obj.id,
        "text": obj.current_text,
        "object_type": obj.current_object_type,
        "order_index": obj.current_order_index,
        "geometry": obj.current_geometry_json or [],
        "attributes": obj.current_attributes_json or {},
        "lifecycle_status": obj.lifecycle_status,
        "document_part_id": obj.document_part_id,
    }


def capture_page_snapshot(session: Session, editable_page_id: str) -> dict[str, Any]:
    page = session.get(EditablePage, editable_page_id)
    if page is None:
        raise ValueError(f"Página editable inexistente: {editable_page_id}")
    objects = session.scalars(
        select(EditableObject)
        .where(EditableObject.editable_page_id == editable_page_id)
        .order_by(EditableObject.current_order_index, EditableObject.id)
    ).all()
    return {
        "form_structure": page.form_structure_json or {},
        "layout_structure": page.layout_structure_json or {},
        "objects": [_object_snapshot(item) for item in objects],
    }


def _restore_page_snapshot(
    session: Session,
    *,
    editable_page_id: str,
    snapshot: dict[str, Any],
    operation: str,
    changed_by: str,
    note: str,
) -> None:
    current = {
        item.id: item
        for item in session.scalars(
            select(EditableObject).where(EditableObject.editable_page_id == editable_page_id)
        ).all()
    }
    target_rows = {str(item["id"]): item for item in snapshot.get("objects", [])}
    page = session.get(EditablePage, editable_page_id)
    if page is None:
        raise ValueError(f"Página editable inexistente: {editable_page_id}")
    target_structure = dict(snapshot.get("form_structure") or {})
    target_layout = dict(snapshot.get("layout_structure") or {})
    page_changed = False
    restored: list[str] = []
    base_page_revision = page.revision_number
    if (page.form_structure_json or {}) != target_structure:
        page.form_structure_json = target_structure
        page_changed = True
        restored.append("form_structure")
    if (page.layout_structure_json or {}) != target_layout:
        page.layout_structure_json = target_layout
        page_changed = True
        restored.append("layout_structure")
    if page_changed:
        page.revision_number += 1
        page.updated_at = utc_now()
        _append_page_revision(
            session,
            page,
            operation=operation,
            created_by=changed_by,
            note=note,
            details={"restored": restored},
            base_revision_number=base_page_revision,
        )

    # Los objetos creados por una acción posterior no se borran físicamente: quedan eliminados.
    for object_id, obj in current.items():
        target = target_rows.get(object_id)
        if target is None:
            if obj.lifecycle_status != "deleted":
                base = obj.revision_number
                obj.lifecycle_status = "deleted"
                obj.revision_number += 1
                obj.updated_by = changed_by
                obj.updated_at = utc_now()
                _append_revision(
                    session,
                    obj,
                    operation=operation,
                    created_by=changed_by,
                    note=note,
                    base_revision_number=base,
                )
            continue

        changed = any(
            [
                obj.current_text != target["text"],
                obj.current_object_type != target["object_type"],
                obj.current_order_index != int(target["order_index"]),
                (obj.current_geometry_json or []) != (target.get("geometry") or []),
                (obj.current_attributes_json or {}) != (target.get("attributes") or {}),
                obj.lifecycle_status != target["lifecycle_status"],
                obj.document_part_id != target.get("document_part_id"),
            ]
        )
        if not changed:
            continue
        base = obj.revision_number
        obj.current_text = str(target["text"])
        obj.current_object_type = str(target["object_type"])
        obj.current_order_index = int(target["order_index"])
        obj.current_geometry_json = list(target.get("geometry") or [])
        obj.current_attributes_json = dict(target.get("attributes") or {})
        obj.lifecycle_status = str(target["lifecycle_status"])
        obj.document_part_id = target.get("document_part_id")
        obj.revision_number += 1
        obj.updated_by = changed_by
        obj.updated_at = utc_now()
        _append_revision(
            session,
            obj,
            operation=operation,
            created_by=changed_by,
            note=note,
            base_revision_number=base,
        )


def execute_page_action(
    session: Session,
    *,
    editable_page_id: str,
    action_type: str,
    changed_by: str,
    action: Callable[[], T],
    selected_object_id: str | None = None,
    note: str | None = None,
) -> T:
    """Ejecuta una mutación y guarda snapshots para deshacer/rehacer la página completa."""
    if session.get(EditablePage, editable_page_id) is None:
        raise ValueError(f"Página editable inexistente: {editable_page_id}")
    before = capture_page_snapshot(session, editable_page_id)
    result = action()
    session.flush()
    after = capture_page_snapshot(session, editable_page_id)
    if before == after:
        return result

    # Una acción nueva después de deshacer invalida la rama de rehacer.
    session.execute(
        update(EditablePageAction)
        .where(
            EditablePageAction.editable_page_id == editable_page_id,
            EditablePageAction.status == "undone",
        )
        .values(status="superseded")
    )
    sequence = int(
        session.scalar(
            select(func.max(EditablePageAction.sequence_number)).where(
                EditablePageAction.editable_page_id == editable_page_id
            )
        )
        or 0
    ) + 1
    session.add(
        EditablePageAction(
            id=new_id(),
            editable_page_id=editable_page_id,
            sequence_number=sequence,
            action_type=action_type,
            status="active",
            before_snapshot_json=before,
            after_snapshot_json=after,
            selected_object_id=selected_object_id,
            note=note,
            created_by=changed_by,
            created_at=utc_now(),
        )
    )
    return result


def page_action_availability(session: Session, *, editable_page_id: str) -> PageActionAvailability:
    active = session.scalar(
        select(EditablePageAction)
        .where(
            EditablePageAction.editable_page_id == editable_page_id,
            EditablePageAction.status == "active",
        )
        .order_by(EditablePageAction.sequence_number.desc())
    )
    max_active = active.sequence_number if active is not None else 0
    redo = session.scalar(
        select(EditablePageAction)
        .where(
            EditablePageAction.editable_page_id == editable_page_id,
            EditablePageAction.status == "undone",
            EditablePageAction.sequence_number > max_active,
        )
        .order_by(EditablePageAction.sequence_number.asc())
    )
    return PageActionAvailability(
        can_undo=active is not None,
        can_redo=redo is not None,
        undo_label=active.action_type if active is not None else None,
        redo_label=redo.action_type if redo is not None else None,
    )


def undo_page_action(
    session: Session,
    *,
    editable_page_id: str,
    changed_by: str,
) -> str | None:
    action = session.scalar(
        select(EditablePageAction)
        .where(
            EditablePageAction.editable_page_id == editable_page_id,
            EditablePageAction.status == "active",
        )
        .order_by(EditablePageAction.sequence_number.desc())
    )
    if action is None:
        raise ValueError("No hay acciones para deshacer en esta página")
    _restore_page_snapshot(
        session,
        editable_page_id=editable_page_id,
        snapshot=action.before_snapshot_json,
        operation="undo",
        changed_by=changed_by,
        note=f"Deshacer: {action.action_type}",
    )
    action.status = "undone"
    action.undone_by = changed_by
    action.undone_at = utc_now()
    return action.selected_object_id


def redo_page_action(
    session: Session,
    *,
    editable_page_id: str,
    changed_by: str,
) -> str | None:
    max_active = int(
        session.scalar(
            select(func.max(EditablePageAction.sequence_number)).where(
                EditablePageAction.editable_page_id == editable_page_id,
                EditablePageAction.status == "active",
            )
        )
        or 0
    )
    action = session.scalar(
        select(EditablePageAction)
        .where(
            EditablePageAction.editable_page_id == editable_page_id,
            EditablePageAction.status == "undone",
            EditablePageAction.sequence_number > max_active,
        )
        .order_by(EditablePageAction.sequence_number.asc())
    )
    if action is None:
        raise ValueError("No hay acciones para rehacer en esta página")
    _restore_page_snapshot(
        session,
        editable_page_id=editable_page_id,
        snapshot=action.after_snapshot_json,
        operation="redo",
        changed_by=changed_by,
        note=f"Rehacer: {action.action_type}",
    )
    action.status = "active"
    action.redone_by = changed_by
    action.redone_at = utc_now()
    return action.selected_object_id
