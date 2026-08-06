from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from archive_workbench.contracts.forms import FormControl, FormGroup, FormStructure
from archive_workbench.db.models import EditableObject, EditablePage, EditablePageRevision, utc_now
from archive_workbench.editing import _append_page_revision
from archive_workbench.identity import new_id, sha256_json
from archive_workbench.structure_quality import checkbox_candidates


@dataclass(slots=True)
class FormCandidateRow:
    fingerprint: str
    marker_object_id: str | None
    label_object_id: str | None
    state: str
    label: str | None
    method: str
    marker: str | None
    already_registered: bool


@dataclass(slots=True)
class FormStructureHistoryRow:
    revision_number: int
    operation: str
    note: str | None
    created_by: str
    created_at: datetime
    group_count: int
    control_count: int
    details: dict[str, Any]


def _structure(page: EditablePage) -> FormStructure:
    return FormStructure.model_validate(page.form_structure_json or {})


def _persist_structure(
    session: Session,
    *,
    page: EditablePage,
    structure: FormStructure,
    changed_by: str,
    note: str | None,
    details: dict[str, Any],
) -> None:
    actor = changed_by.strip()
    if not actor:
        raise ValueError("Indicá quién realiza el cambio")
    base = page.revision_number
    page.form_structure_json = structure.model_dump(mode="json")
    page.revision_number += 1
    page.updated_at = utc_now()
    _append_page_revision(
        session,
        page,
        operation="form_structure",
        created_by=actor,
        note=note,
        details=details,
        base_revision_number=base,
    )
    # Cada operación de dominio debe producir su propio UPDATE y evento de intercambio.
    # Sin este flush, dos cambios consecutivos dentro de una misma acción podrían
    # colapsar en un salto de revisiones y perder el estado intermedio.
    session.flush()


def _active_objects(session: Session, editable_page_id: str) -> list[EditableObject]:
    return list(
        session.scalars(
            select(EditableObject)
            .where(
                EditableObject.editable_page_id == editable_page_id,
                EditableObject.lifecycle_status == "active",
            )
            .order_by(EditableObject.current_order_index, EditableObject.id)
        ).all()
    )


def _fingerprint(candidate: dict[str, Any]) -> str:
    payload = {
        "marker_object_id": candidate.get("marker_object_id"),
        "label_object_id": candidate.get("label_object_id"),
        "control_index": candidate.get("control_index"),
        "state": candidate.get("state"),
        "label": candidate.get("label"),
        "method": candidate.get("method"),
        "marker": candidate.get("marker"),
    }
    return sha256_json(payload)


def form_candidates(session: Session, *, editable_page_id: str) -> list[FormCandidateRow]:
    page = session.get(EditablePage, editable_page_id)
    if page is None:
        raise ValueError(f"Página editable inexistente: {editable_page_id}")
    structure = _structure(page)
    registered = {
        item.candidate_fingerprint
        for item in structure.controls
        if item.candidate_fingerprint and item.lifecycle_status == "active"
    }
    registered_anchors = {
        (item.marker_object_id, item.label_object_id)
        for item in structure.controls
        if item.source == "candidate" and item.lifecycle_status == "active"
    }
    candidates = checkbox_candidates(
        _active_objects(session, editable_page_id), page_number=page.page_number
    )
    return [
        FormCandidateRow(
            fingerprint=_fingerprint(item),
            marker_object_id=item.get("marker_object_id"),
            label_object_id=item.get("label_object_id"),
            state=str(item.get("state") or "indeterminate"),
            label=(str(item.get("label")).strip() if item.get("label") else None),
            method=str(item.get("method") or "unknown"),
            marker=(str(item.get("marker")) if item.get("marker") is not None else None),
            already_registered=(
                _fingerprint(item) in registered
                or (item.get("marker_object_id"), item.get("label_object_id"))
                in registered_anchors
            ),
        )
        for item in candidates
    ]


def form_structure(session: Session, *, editable_page_id: str) -> FormStructure:
    page = session.get(EditablePage, editable_page_id)
    if page is None:
        raise ValueError(f"Página editable inexistente: {editable_page_id}")
    return _structure(page)


def _ensure_object_on_page(
    session: Session, *, editable_page_id: str, object_id: str | None
) -> None:
    if object_id is None:
        return
    obj = session.get(EditableObject, object_id)
    if obj is None or obj.editable_page_id != editable_page_id:
        raise ValueError("El objeto indicado no pertenece a la página editable")


def ensure_group(
    session: Session,
    *,
    editable_page_id: str,
    label: str,
    changed_by: str,
    note: str | None = None,
) -> str:
    page = session.get(EditablePage, editable_page_id)
    if page is None:
        raise ValueError(f"Página editable inexistente: {editable_page_id}")
    clean_label = " ".join(label.split())
    if not clean_label:
        raise ValueError("Indicá el nombre del grupo")
    structure = _structure(page)
    for group in structure.groups:
        if group.lifecycle_status == "active" and group.label.casefold() == clean_label.casefold():
            return group.group_id
    now = utc_now()
    group = FormGroup(
        group_id=new_id(),
        label=clean_label,
        note=note,
        created_by=changed_by,
        created_at=now,
        updated_by=changed_by,
        updated_at=now,
    )
    structure.groups.append(group)
    _persist_structure(
        session,
        page=page,
        structure=structure,
        changed_by=changed_by,
        note=note,
        details={"action": "create_group", "group_id": group.group_id},
    )
    return group.group_id


def register_control(
    session: Session,
    *,
    editable_page_id: str,
    state: str,
    label: str,
    changed_by: str,
    marker_object_id: str | None = None,
    label_object_id: str | None = None,
    group_id: str | None = None,
    source: str = "manual",
    candidate_fingerprint: str | None = None,
    candidate_method: str | None = None,
    marker_text: str | None = None,
    evidence_note: str | None = None,
) -> FormControl:
    page = session.get(EditablePage, editable_page_id)
    if page is None:
        raise ValueError(f"Página editable inexistente: {editable_page_id}")
    _ensure_object_on_page(session, editable_page_id=editable_page_id, object_id=marker_object_id)
    _ensure_object_on_page(session, editable_page_id=editable_page_id, object_id=label_object_id)
    structure = _structure(page)
    if candidate_fingerprint and any(
        item.candidate_fingerprint == candidate_fingerprint
        and item.lifecycle_status == "active"
        for item in structure.controls
    ):
        raise ValueError("Este candidato ya fue registrado")
    if group_id is not None and not any(
        item.group_id == group_id and item.lifecycle_status == "active"
        for item in structure.groups
    ):
        raise ValueError("El grupo seleccionado no existe o está archivado")
    now = utc_now()
    control = FormControl(
        control_id=new_id(),
        group_id=group_id,
        marker_object_id=marker_object_id,
        label_object_id=label_object_id,
        label=" ".join(label.split()),
        state=state,
        source=source,
        candidate_fingerprint=candidate_fingerprint,
        candidate_method=candidate_method,
        marker_text=marker_text,
        evidence_note=evidence_note,
        confirmed_by=changed_by,
        confirmed_at=now,
        updated_by=changed_by,
        updated_at=now,
    )
    structure.controls.append(control)
    _persist_structure(
        session,
        page=page,
        structure=structure,
        changed_by=changed_by,
        note=evidence_note,
        details={"action": "register_control", "control_id": control.control_id},
    )
    return control


def update_control(
    session: Session,
    *,
    editable_page_id: str,
    control_id: str,
    changed_by: str,
    state: str,
    label: str,
    group_id: str | None,
    evidence_note: str | None,
) -> FormControl:
    page = session.get(EditablePage, editable_page_id)
    if page is None:
        raise ValueError(f"Página editable inexistente: {editable_page_id}")
    structure = _structure(page)
    if group_id is not None and not any(
        item.group_id == group_id and item.lifecycle_status == "active"
        for item in structure.groups
    ):
        raise ValueError("El grupo seleccionado no existe o está archivado")
    target = next((item for item in structure.controls if item.control_id == control_id), None)
    if target is None:
        raise ValueError("Casillero inexistente")
    if target.lifecycle_status != "active":
        raise ValueError("El casillero está archivado")
    target.state = state
    target.label = " ".join(label.split())
    target.group_id = group_id
    target.evidence_note = evidence_note
    target.updated_by = changed_by
    target.updated_at = utc_now()
    _persist_structure(
        session,
        page=page,
        structure=structure,
        changed_by=changed_by,
        note=evidence_note,
        details={"action": "update_control", "control_id": control_id},
    )
    return target


def archive_control(
    session: Session,
    *,
    editable_page_id: str,
    control_id: str,
    changed_by: str,
    note: str | None = None,
) -> FormControl:
    page = session.get(EditablePage, editable_page_id)
    if page is None:
        raise ValueError(f"Página editable inexistente: {editable_page_id}")
    structure = _structure(page)
    target = next((item for item in structure.controls if item.control_id == control_id), None)
    if target is None:
        raise ValueError("Casillero inexistente")
    if target.lifecycle_status != "active":
        raise ValueError("El casillero ya está archivado")
    target.lifecycle_status = "archived"
    target.updated_by = changed_by
    target.updated_at = utc_now()
    _persist_structure(
        session,
        page=page,
        structure=structure,
        changed_by=changed_by,
        note=note,
        details={"action": "archive_control", "control_id": control_id},
    )
    return target


def rename_group(
    session: Session,
    *,
    editable_page_id: str,
    group_id: str,
    label: str,
    changed_by: str,
    note: str | None = None,
) -> FormGroup:
    page = session.get(EditablePage, editable_page_id)
    if page is None:
        raise ValueError(f"Página editable inexistente: {editable_page_id}")
    structure = _structure(page)
    clean_label = " ".join(label.split())
    if not clean_label:
        raise ValueError("Indicá el nombre del grupo")
    if any(
        item.group_id != group_id
        and item.lifecycle_status == "active"
        and item.label.casefold() == clean_label.casefold()
        for item in structure.groups
    ):
        raise ValueError("Ya existe otro grupo activo con ese nombre")
    target = next((item for item in structure.groups if item.group_id == group_id), None)
    if target is None:
        raise ValueError("Grupo inexistente")
    if target.lifecycle_status != "active":
        raise ValueError("El grupo está archivado")
    target.label = clean_label
    target.note = note
    target.updated_by = changed_by
    target.updated_at = utc_now()
    _persist_structure(
        session,
        page=page,
        structure=structure,
        changed_by=changed_by,
        note=note,
        details={"action": "rename_group", "group_id": group_id},
    )
    return target


def archive_group(
    session: Session,
    *,
    editable_page_id: str,
    group_id: str,
    changed_by: str,
    note: str | None = None,
) -> FormGroup:
    page = session.get(EditablePage, editable_page_id)
    if page is None:
        raise ValueError(f"Página editable inexistente: {editable_page_id}")
    structure = _structure(page)
    target = next((item for item in structure.groups if item.group_id == group_id), None)
    if target is None:
        raise ValueError("Grupo inexistente")
    if target.lifecycle_status != "active":
        raise ValueError("El grupo ya está archivado")
    target.lifecycle_status = "archived"
    target.updated_by = changed_by
    target.updated_at = utc_now()
    for control in structure.controls:
        if control.group_id == group_id and control.lifecycle_status == "active":
            control.group_id = None
            control.updated_by = changed_by
            control.updated_at = utc_now()
    _persist_structure(
        session,
        page=page,
        structure=structure,
        changed_by=changed_by,
        note=note,
        details={"action": "archive_group", "group_id": group_id},
    )
    return target


def form_structure_history(
    session: Session, *, editable_page_id: str
) -> list[FormStructureHistoryRow]:
    if session.get(EditablePage, editable_page_id) is None:
        raise ValueError(f"Página editable inexistente: {editable_page_id}")
    revisions = session.scalars(
        select(EditablePageRevision)
        .where(
            EditablePageRevision.editable_page_id == editable_page_id,
            EditablePageRevision.operation.in_(["form_structure", "undo", "redo"]),
        )
        .order_by(EditablePageRevision.revision_number)
    ).all()
    rows: list[FormStructureHistoryRow] = []
    for revision in revisions:
        structure = FormStructure.model_validate(revision.form_structure_json or {})
        rows.append(
            FormStructureHistoryRow(
                revision_number=revision.revision_number,
                operation=revision.operation,
                note=revision.note,
                created_by=revision.created_by,
                created_at=revision.created_at,
                group_count=len(structure.groups),
                control_count=len(structure.controls),
                details=deepcopy(revision.details_json or {}),
            )
        )
    return rows
