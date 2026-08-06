from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
import re
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from archive_workbench.contracts.layout import LayoutColumn, LayoutStructure
from archive_workbench.db.models import EditableObject, EditablePage, EditablePageRevision, utc_now
from archive_workbench.editing import (
    _append_page_revision,
    _record_reorder,
    merge_editable_object,
    set_editable_object_lifecycle,
)
from archive_workbench.identity import new_id, sha256_json

_LAYOUT_ALGORITHM = "layout_columns_v1"
_TEXT_TYPES = {"paragraph", "list_item", "unknown"}
_TERMINAL_RE = re.compile(r"[.!?;:]\s*$")


@dataclass(frozen=True, slots=True)
class LayoutBox:
    left: float
    top: float
    right: float
    bottom: float

    @property
    def width(self) -> float:
        return self.right - self.left

    @property
    def height(self) -> float:
        return self.bottom - self.top

    @property
    def center_x(self) -> float:
        return (self.left + self.right) / 2

    @property
    def center_y(self) -> float:
        return (self.top + self.bottom) / 2

    @property
    def area(self) -> float:
        return self.width * self.height


@dataclass(frozen=True, slots=True)
class LayoutObjectView:
    object_id: str
    order_index: int
    object_type: str
    text: str
    geometry: list[dict[str, Any]]
    lifecycle_status: str


@dataclass(frozen=True, slots=True)
class LayoutCandidateColumn:
    label: str
    order_index: int
    object_ids: tuple[str, ...]
    left: float
    right: float


@dataclass(frozen=True, slots=True)
class LayoutFragmentCandidate:
    fingerprint: str
    object_ids: tuple[str, ...]
    column_index: int
    text_preview: str


@dataclass(frozen=True, slots=True)
class LayoutDuplicateCandidate:
    fingerprint: str
    keep_object_id: str
    duplicate_object_id: str
    text_preview: str
    overlap: float


@dataclass(frozen=True, slots=True)
class LayoutProposal:
    fingerprint: str
    algorithm: str
    confidence: float
    columns: tuple[LayoutCandidateColumn, ...]
    proposed_order: tuple[str, ...]
    current_order: tuple[str, ...]
    unassigned_object_ids: tuple[str, ...]
    changed_positions: int
    fragment_candidates: tuple[LayoutFragmentCandidate, ...]
    duplicate_candidates: tuple[LayoutDuplicateCandidate, ...]


@dataclass(slots=True)
class LayoutStructureHistoryRow:
    revision_number: int
    operation: str
    note: str | None
    created_by: str
    created_at: datetime
    active_column_count: int
    assigned_object_count: int
    details: dict[str, Any]


def _view(item: Any) -> LayoutObjectView:
    return LayoutObjectView(
        object_id=str(getattr(item, "id", getattr(item, "object_id", ""))),
        order_index=int(
            getattr(item, "current_order_index", getattr(item, "order_index", 0))
        ),
        object_type=str(
            getattr(
                item,
                "current_object_type",
                getattr(item, "object_type", "unknown"),
            )
            or "unknown"
        ),
        text=str(
            getattr(
                item,
                "current_text",
                getattr(item, "text", getattr(item, "original_text", "")),
            )
            or ""
        ),
        geometry=list(
            getattr(
                item,
                "current_geometry_json",
                getattr(item, "geometry", getattr(item, "geometry_json", [])),
            )
            or []
        ),
        lifecycle_status=str(getattr(item, "lifecycle_status", "active")),
    )


def normalized_layout_box(item: Any, *, page_number: int) -> LayoutBox | None:
    view = item if isinstance(item, LayoutObjectView) else _view(item)
    boxes: list[LayoutBox] = []
    for geometry in view.geometry:
        if int(geometry.get("page") or 0) != page_number:
            continue
        if geometry.get("coordinate_space") != "normalized":
            continue
        polygon = geometry.get("polygon") or []
        if len(polygon) < 4:
            continue
        try:
            xs = [float(point[0]) for point in polygon]
            ys = [float(point[1]) for point in polygon]
        except (TypeError, ValueError, IndexError):
            continue
        left, right = max(0.0, min(xs)), min(1.0, max(xs))
        top, bottom = max(0.0, min(ys)), min(1.0, max(ys))
        if right > left and bottom > top:
            boxes.append(LayoutBox(left, top, right, bottom))
    if not boxes:
        return None
    return LayoutBox(
        min(box.left for box in boxes),
        min(box.top for box in boxes),
        max(box.right for box in boxes),
        max(box.bottom for box in boxes),
    )


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


def _normalized_text(text: str) -> str:
    return re.sub(r"\W+", " ", text.casefold()).strip()


def _intersection_over_union(first: LayoutBox, second: LayoutBox) -> float:
    left = max(first.left, second.left)
    top = max(first.top, second.top)
    right = min(first.right, second.right)
    bottom = min(first.bottom, second.bottom)
    if right <= left or bottom <= top:
        return 0.0
    intersection = (right - left) * (bottom - top)
    union = first.area + second.area - intersection
    return intersection / union if union > 0 else 0.0


def _column_segments(
    positioned: list[tuple[LayoutObjectView, LayoutBox]],
) -> tuple[list[list[tuple[LayoutObjectView, LayoutBox]]], float]:
    if len(positioned) < 4:
        return [positioned], 0.55 if positioned else 0.0
    by_center = sorted(positioned, key=lambda pair: (pair[1].center_x, pair[1].top))
    gaps = [
        (by_center[index + 1][1].center_x - by_center[index][1].center_x, index)
        for index in range(len(by_center) - 1)
    ]
    eligible = sorted(
        ((gap, index) for gap, index in gaps if gap >= 0.18),
        reverse=True,
    )
    split_indexes: list[int] = []
    for gap, index in eligible:
        tentative = sorted([*split_indexes, index])
        boundaries = [-1, *tentative, len(by_center) - 1]
        sizes = [boundaries[i + 1] - boundaries[i] for i in range(len(boundaries) - 1)]
        if min(sizes) >= 2 and len(tentative) <= 2:
            split_indexes = tentative
    if not split_indexes:
        return [positioned], 0.60
    segments: list[list[tuple[LayoutObjectView, LayoutBox]]] = []
    start = 0
    for split in split_indexes:
        segments.append(by_center[start : split + 1])
        start = split + 1
    segments.append(by_center[start:])
    segments.sort(key=lambda group: min(box.left for _, box in group))
    separation = min(
        min(box.center_x for _, box in segments[index + 1])
        - max(box.center_x for _, box in segments[index])
        for index in range(len(segments) - 1)
    )
    confidence = max(0.0, min(1.0, 0.55 + separation))
    return segments, confidence


def _fragment_candidates(
    columns: list[list[tuple[LayoutObjectView, LayoutBox]]],
) -> list[LayoutFragmentCandidate]:
    results: list[LayoutFragmentCandidate] = []
    for column_index, column in enumerate(columns):
        ordered = sorted(column, key=lambda pair: (pair[1].top, pair[1].left, pair[0].order_index))
        current: list[tuple[LayoutObjectView, LayoutBox]] = []
        for pair in ordered:
            item, box = pair
            eligible = item.object_type in _TEXT_TYPES and bool(item.text.strip())
            if not eligible:
                if len(current) >= 2:
                    results.append(_fragment_row(column_index, current))
                current = []
                continue
            if not current:
                current = [pair]
                continue
            previous, previous_box = current[-1]
            gap = box.top - previous_box.bottom
            aligned = abs(box.left - previous_box.left) <= 0.055
            similar_width = abs(box.width - previous_box.width) <= 0.18
            close = -0.01 <= gap <= max(0.035, previous_box.height * 1.2)
            continuation = not _TERMINAL_RE.search(previous.text.strip())
            if aligned and similar_width and close and continuation:
                current.append(pair)
            else:
                if len(current) >= 2:
                    results.append(_fragment_row(column_index, current))
                current = [pair]
        if len(current) >= 2:
            results.append(_fragment_row(column_index, current))
    return results


def _fragment_row(
    column_index: int,
    pairs: list[tuple[LayoutObjectView, LayoutBox]],
) -> LayoutFragmentCandidate:
    ids = tuple(item.object_id for item, _ in pairs)
    preview = " / ".join(item.text.strip().replace("\n", " ")[:70] for item, _ in pairs)
    return LayoutFragmentCandidate(
        fingerprint=sha256_json({"kind": "fragment", "object_ids": ids}),
        object_ids=ids,
        column_index=column_index,
        text_preview=preview,
    )


def _duplicate_candidates(
    positioned: list[tuple[LayoutObjectView, LayoutBox]],
) -> list[LayoutDuplicateCandidate]:
    results: list[LayoutDuplicateCandidate] = []
    for index, (first, first_box) in enumerate(positioned):
        normalized = _normalized_text(first.text)
        if len(normalized) < 3:
            continue
        for second, second_box in positioned[index + 1 :]:
            if _normalized_text(second.text) != normalized:
                continue
            overlap = _intersection_over_union(first_box, second_box)
            if overlap < 0.65:
                continue
            keep, duplicate = sorted(
                [first, second], key=lambda item: (item.order_index, item.object_id)
            )
            results.append(
                LayoutDuplicateCandidate(
                    fingerprint=sha256_json(
                        {
                            "kind": "duplicate",
                            "keep": keep.object_id,
                            "duplicate": duplicate.object_id,
                        }
                    ),
                    keep_object_id=keep.object_id,
                    duplicate_object_id=duplicate.object_id,
                    text_preview=keep.text.strip().replace("\n", " ")[:120],
                    overlap=round(overlap, 6),
                )
            )
    return results


def propose_layout(objects: Iterable[Any], *, page_number: int) -> LayoutProposal:
    views = sorted(
        (_view(item) for item in objects if _view(item).lifecycle_status == "active"),
        key=lambda item: (item.order_index, item.object_id),
    )
    current_order = tuple(item.object_id for item in views)
    positioned: list[tuple[LayoutObjectView, LayoutBox]] = []
    unassigned: list[LayoutObjectView] = []
    for item in views:
        box = normalized_layout_box(item, page_number=page_number)
        if box is None:
            unassigned.append(item)
        else:
            positioned.append((item, box))
    segments, confidence = _column_segments(positioned)
    columns: list[LayoutCandidateColumn] = []
    proposed: list[str] = []
    ordered_segments: list[list[tuple[LayoutObjectView, LayoutBox]]] = []
    for index, segment in enumerate(segments):
        ordered = sorted(
            segment,
            key=lambda pair: (pair[1].top, pair[1].left, pair[0].order_index, pair[0].object_id),
        )
        ordered_segments.append(ordered)
        ids = tuple(item.object_id for item, _ in ordered)
        proposed.extend(ids)
        columns.append(
            LayoutCandidateColumn(
                label=f"Columna {index + 1}",
                order_index=index,
                object_ids=ids,
                left=round(min((box.left for _, box in segment), default=0.0), 6),
                right=round(max((box.right for _, box in segment), default=1.0), 6),
            )
        )
    unassigned_ids = tuple(item.object_id for item in unassigned)
    proposed.extend(unassigned_ids)
    proposed_order = tuple(proposed)
    changed_positions = sum(
        first != second for first, second in zip(current_order, proposed_order)
    ) + abs(len(current_order) - len(proposed_order))
    payload = {
        "algorithm": _LAYOUT_ALGORITHM,
        "page": page_number,
        "columns": [
            {"order": item.order_index, "objects": item.object_ids} for item in columns
        ],
        "unassigned": unassigned_ids,
    }
    return LayoutProposal(
        fingerprint=sha256_json(payload),
        algorithm=_LAYOUT_ALGORITHM,
        confidence=round(confidence, 6),
        columns=tuple(columns),
        proposed_order=proposed_order,
        current_order=current_order,
        unassigned_object_ids=unassigned_ids,
        changed_positions=changed_positions,
        fragment_candidates=tuple(_fragment_candidates(ordered_segments)),
        duplicate_candidates=tuple(_duplicate_candidates(positioned)),
    )


def layout_proposal(session: Session, *, editable_page_id: str) -> LayoutProposal:
    page = session.get(EditablePage, editable_page_id)
    if page is None:
        raise ValueError(f"Página editable inexistente: {editable_page_id}")
    return propose_layout(
        _active_objects(session, editable_page_id), page_number=page.page_number
    )


def _structure(page: EditablePage) -> LayoutStructure:
    return LayoutStructure.model_validate(page.layout_structure_json or {})


def layout_structure(session: Session, *, editable_page_id: str) -> LayoutStructure:
    page = session.get(EditablePage, editable_page_id)
    if page is None:
        raise ValueError(f"Página editable inexistente: {editable_page_id}")
    return _structure(page)


def _persist_structure(
    session: Session,
    *,
    page: EditablePage,
    structure: LayoutStructure,
    changed_by: str,
    note: str | None,
    details: dict[str, Any],
) -> None:
    actor = changed_by.strip()
    if not actor:
        raise ValueError("Indicá quién realiza el cambio")
    base = page.revision_number
    page.layout_structure_json = structure.model_dump(mode="json")
    page.revision_number += 1
    page.updated_at = utc_now()
    _append_page_revision(
        session,
        page,
        operation="layout_structure",
        created_by=actor,
        note=note,
        details=details,
        base_revision_number=base,
    )
    session.flush()


def apply_layout_proposal(
    session: Session,
    *,
    editable_page_id: str,
    changed_by: str,
    note: str | None = None,
) -> LayoutStructure:
    page = session.get(EditablePage, editable_page_id)
    if page is None:
        raise ValueError(f"Página editable inexistente: {editable_page_id}")
    proposal = layout_proposal(session, editable_page_id=editable_page_id)
    objects = {item.id: item for item in _active_objects(session, editable_page_id)}
    if set(proposal.proposed_order) != set(objects):
        raise ValueError("La propuesta no coincide con los objetos activos de la página")
    for new_order, object_id in enumerate(proposal.proposed_order):
        _record_reorder(
            session,
            objects[object_id],
            new_order=new_order,
            changed_by=changed_by,
            note="Orden aplicado desde la propuesta revisada de layout",
        )
    now = utc_now()
    columns = [
        LayoutColumn(
            column_id=new_id(),
            label=item.label,
            order_index=item.order_index,
            object_ids=list(item.object_ids),
            source="candidate",
            evidence_note=note,
            created_by=changed_by,
            created_at=now,
            updated_by=changed_by,
            updated_at=now,
        )
        for item in proposal.columns
    ]
    structure = LayoutStructure(
        columns=columns,
        candidate_fingerprint=proposal.fingerprint,
        candidate_algorithm=proposal.algorithm,
        candidate_confidence=proposal.confidence,
        applied_by=changed_by,
        applied_at=now,
        evidence_note=note,
    )
    _persist_structure(
        session,
        page=page,
        structure=structure,
        changed_by=changed_by,
        note=note,
        details={
            "action": "apply_layout_proposal",
            "candidate_fingerprint": proposal.fingerprint,
            "column_count": len(columns),
            "changed_positions": proposal.changed_positions,
        },
    )
    return structure


def ensure_layout_column(
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
        raise ValueError("Indicá el nombre de la columna")
    structure = _structure(page)
    for column in structure.columns:
        if column.lifecycle_status == "active" and column.label.casefold() == clean_label.casefold():
            return column.column_id
    now = utc_now()
    active_orders = [item.order_index for item in structure.columns if item.lifecycle_status == "active"]
    column = LayoutColumn(
        column_id=new_id(),
        label=clean_label,
        order_index=max(active_orders, default=-1) + 1,
        object_ids=[],
        source="manual",
        evidence_note=note,
        created_by=changed_by,
        created_at=now,
        updated_by=changed_by,
        updated_at=now,
    )
    structure.columns.append(column)
    _persist_structure(
        session,
        page=page,
        structure=structure,
        changed_by=changed_by,
        note=note,
        details={"action": "create_layout_column", "column_id": column.column_id},
    )
    return column.column_id


def create_layout_column_for_object(
    session: Session,
    *,
    editable_page_id: str,
    object_id: str,
    label: str,
    changed_by: str,
    note: str | None = None,
) -> str:
    """Crea una columna manual y asigna el objeto en una sola revisión."""

    page = session.get(EditablePage, editable_page_id)
    obj = session.get(EditableObject, object_id)
    if page is None:
        raise ValueError(f"Página editable inexistente: {editable_page_id}")
    if obj is None or obj.editable_page_id != editable_page_id or obj.lifecycle_status != "active":
        raise ValueError("El objeto indicado no pertenece a la página editable activa")
    clean_label = " ".join(label.split())
    if not clean_label:
        raise ValueError("Indicá el nombre de la columna")

    structure = _structure(page)
    if any(
        column.lifecycle_status == "active"
        and column.label.casefold() == clean_label.casefold()
        for column in structure.columns
    ):
        raise ValueError("Ya existe una columna activa con ese nombre")

    now = utc_now()
    active_orders = [
        item.order_index
        for item in structure.columns
        if item.lifecycle_status == "active"
    ]
    for column in structure.columns:
        if object_id in column.object_ids:
            column.object_ids = [
                value for value in column.object_ids if value != object_id
            ]
            column.updated_by = changed_by
            column.updated_at = now

    column = LayoutColumn(
        column_id=new_id(),
        label=clean_label,
        order_index=max(active_orders, default=-1) + 1,
        object_ids=[object_id],
        source="manual",
        evidence_note=note,
        created_by=changed_by,
        created_at=now,
        updated_by=changed_by,
        updated_at=now,
    )
    structure.columns.append(column)
    _persist_structure(
        session,
        page=page,
        structure=structure,
        changed_by=changed_by,
        note=note,
        details={
            "action": "create_and_assign_layout_column",
            "column_id": column.column_id,
            "object_id": object_id,
        },
    )
    return column.column_id


def assign_object_to_column(
    session: Session,
    *,
    editable_page_id: str,
    object_id: str,
    column_id: str | None,
    changed_by: str,
    note: str | None = None,
) -> LayoutStructure:
    page = session.get(EditablePage, editable_page_id)
    obj = session.get(EditableObject, object_id)
    if page is None:
        raise ValueError(f"Página editable inexistente: {editable_page_id}")
    if obj is None or obj.editable_page_id != editable_page_id or obj.lifecycle_status != "active":
        raise ValueError("El objeto indicado no pertenece a la página editable activa")
    structure = _structure(page)
    target = None
    if column_id is not None:
        target = next(
            (
                item
                for item in structure.columns
                if item.column_id == column_id and item.lifecycle_status == "active"
            ),
            None,
        )
        if target is None:
            raise ValueError("La columna seleccionada no existe o está archivada")
    changed = False
    for column in structure.columns:
        if object_id in column.object_ids:
            column.object_ids = [value for value in column.object_ids if value != object_id]
            column.updated_by = changed_by
            column.updated_at = utc_now()
            changed = True
    if target is not None and object_id not in target.object_ids:
        target.object_ids.append(object_id)
        target.updated_by = changed_by
        target.updated_at = utc_now()
        changed = True
    if not changed:
        return structure
    _persist_structure(
        session,
        page=page,
        structure=structure,
        changed_by=changed_by,
        note=note,
        details={
            "action": "assign_layout_column",
            "object_id": object_id,
            "column_id": column_id,
        },
    )
    return structure


def rename_layout_column(
    session: Session,
    *,
    editable_page_id: str,
    column_id: str,
    label: str,
    changed_by: str,
    note: str | None = None,
) -> LayoutColumn:
    page = session.get(EditablePage, editable_page_id)
    if page is None:
        raise ValueError(f"Página editable inexistente: {editable_page_id}")
    structure = _structure(page)
    clean_label = " ".join(label.split())
    if not clean_label:
        raise ValueError("Indicá el nombre de la columna")
    target = next((item for item in structure.columns if item.column_id == column_id), None)
    if target is None or target.lifecycle_status != "active":
        raise ValueError("La columna no existe o está archivada")
    target.label = clean_label
    target.evidence_note = note
    target.updated_by = changed_by
    target.updated_at = utc_now()
    _persist_structure(
        session,
        page=page,
        structure=structure,
        changed_by=changed_by,
        note=note,
        details={"action": "rename_layout_column", "column_id": column_id},
    )
    return target


def archive_layout_column(
    session: Session,
    *,
    editable_page_id: str,
    column_id: str,
    changed_by: str,
    note: str | None = None,
) -> LayoutColumn:
    page = session.get(EditablePage, editable_page_id)
    if page is None:
        raise ValueError(f"Página editable inexistente: {editable_page_id}")
    structure = _structure(page)
    target = next((item for item in structure.columns if item.column_id == column_id), None)
    if target is None or target.lifecycle_status != "active":
        raise ValueError("La columna no existe o ya está archivada")
    target.lifecycle_status = "archived"
    target.updated_by = changed_by
    target.updated_at = utc_now()
    _persist_structure(
        session,
        page=page,
        structure=structure,
        changed_by=changed_by,
        note=note,
        details={"action": "archive_layout_column", "column_id": column_id},
    )
    return target



def _replace_layout_object_ids(
    structure: LayoutStructure, *, removed_ids: set[str], replacement_id: str | None
) -> bool:
    changed = False
    for column in structure.columns:
        updated: list[str] = []
        for object_id in column.object_ids:
            if object_id in removed_ids:
                changed = True
                if replacement_id is not None and replacement_id not in updated:
                    updated.append(replacement_id)
                continue
            if object_id not in updated:
                updated.append(object_id)
        column.object_ids = updated
    return changed


def merge_fragment_candidate(
    session: Session,
    *,
    editable_page_id: str,
    fingerprint: str,
    changed_by: str,
    note: str | None = None,
) -> EditableObject:
    proposal = layout_proposal(session, editable_page_id=editable_page_id)
    candidate = next(
        (item for item in proposal.fragment_candidates if item.fingerprint == fingerprint),
        None,
    )
    if candidate is None:
        raise ValueError("La candidata de fragmentación ya no coincide con la página")
    active = _active_objects(session, editable_page_id)
    positions = {item.id: index for index, item in enumerate(active)}
    indexes = [positions.get(object_id) for object_id in candidate.object_ids]
    if any(index is None for index in indexes) or indexes != list(
        range(min(indexes), min(indexes) + len(indexes))
    ):
        raise ValueError(
            "Aplicá primero la propuesta de orden para combinar esta secuencia"
        )
    survivor = next(item for item in active if item.id == candidate.object_ids[0])
    removed_ids: set[str] = set()
    for adjacent_id in candidate.object_ids[1:]:
        refreshed = session.get(EditableObject, survivor.id)
        adjacent = session.get(EditableObject, adjacent_id)
        if refreshed is None or adjacent is None or adjacent.lifecycle_status != "active":
            raise ValueError("La secuencia cambió durante la combinación")
        survivor = merge_editable_object(
            session,
            object_id=refreshed.id,
            expected_revision=refreshed.revision_number,
            direction="next",
            separator="\n",
            changed_by=changed_by,
            note=note or "Fragmentos combinados después de revisión visual",
        )
        removed_ids.add(adjacent_id)
    page = session.get(EditablePage, editable_page_id)
    if page is not None and (page.layout_structure_json or {}).get("columns"):
        structure = _structure(page)
        if _replace_layout_object_ids(
            structure, removed_ids=removed_ids, replacement_id=survivor.id
        ):
            _persist_structure(
                session,
                page=page,
                structure=structure,
                changed_by=changed_by,
                note=note,
                details={
                    "action": "merge_layout_fragment",
                    "candidate_fingerprint": fingerprint,
                    "survivor_object_id": survivor.id,
                },
            )
    return survivor


def archive_duplicate_candidate(
    session: Session,
    *,
    editable_page_id: str,
    fingerprint: str,
    changed_by: str,
    note: str | None = None,
) -> EditableObject:
    proposal = layout_proposal(session, editable_page_id=editable_page_id)
    candidate = next(
        (item for item in proposal.duplicate_candidates if item.fingerprint == fingerprint),
        None,
    )
    if candidate is None:
        raise ValueError("La candidata de duplicación ya no coincide con la página")
    duplicate = session.get(EditableObject, candidate.duplicate_object_id)
    if duplicate is None or duplicate.lifecycle_status != "active":
        raise ValueError("El posible duplicado ya no está activo")
    result = set_editable_object_lifecycle(
        session,
        object_id=duplicate.id,
        expected_revision=duplicate.revision_number,
        lifecycle_status="deleted",
        changed_by=changed_by,
        note=note or f"Duplicado confirmado del objeto {candidate.keep_object_id}",
    )
    page = session.get(EditablePage, editable_page_id)
    if page is not None and (page.layout_structure_json or {}).get("columns"):
        structure = _structure(page)
        if _replace_layout_object_ids(
            structure, removed_ids={duplicate.id}, replacement_id=None
        ):
            _persist_structure(
                session,
                page=page,
                structure=structure,
                changed_by=changed_by,
                note=note,
                details={
                    "action": "archive_layout_duplicate",
                    "candidate_fingerprint": fingerprint,
                    "duplicate_object_id": duplicate.id,
                    "kept_object_id": candidate.keep_object_id,
                },
            )
    return result

def layout_structure_history(
    session: Session, *, editable_page_id: str
) -> list[LayoutStructureHistoryRow]:
    if session.get(EditablePage, editable_page_id) is None:
        raise ValueError(f"Página editable inexistente: {editable_page_id}")
    revisions = session.scalars(
        select(EditablePageRevision)
        .where(
            EditablePageRevision.editable_page_id == editable_page_id,
            EditablePageRevision.operation.in_(["layout_structure", "undo", "redo"]),
        )
        .order_by(EditablePageRevision.revision_number)
    ).all()
    rows: list[LayoutStructureHistoryRow] = []
    for revision in revisions:
        structure = LayoutStructure.model_validate(revision.layout_structure_json or {})
        active = [item for item in structure.columns if item.lifecycle_status == "active"]
        rows.append(
            LayoutStructureHistoryRow(
                revision_number=revision.revision_number,
                operation=revision.operation,
                note=revision.note,
                created_by=revision.created_by,
                created_at=revision.created_at,
                active_column_count=len(active),
                assigned_object_count=len(
                    {object_id for column in active for object_id in column.object_ids}
                ),
                details=deepcopy(revision.details_json or {}),
            )
        )
    return rows


def render_layout_overlay(
    image_path: str | Any,
    objects: Iterable[Any],
    *,
    proposal: LayoutProposal,
    page_number: int,
):
    """Dibuja la propuesta sin modificar la imagen de origen."""
    from pathlib import Path
    from PIL import Image, ImageDraw, ImageFont

    image = Image.open(Path(image_path)).convert("RGB")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default()
    views = {_view(item).object_id: _view(item) for item in objects}
    order_positions = {
        object_id: index + 1 for index, object_id in enumerate(proposal.proposed_order)
    }
    palette = [
        (28, 111, 164),
        (214, 39, 40),
        (44, 160, 44),
    ]
    for column_index, column in enumerate(proposal.columns):
        color = palette[column_index % len(palette)]
        for object_id in column.object_ids:
            item = views.get(object_id)
            if item is None:
                continue
            box = normalized_layout_box(item, page_number=page_number)
            if box is None:
                continue
            left = int(round(box.left * image.width))
            top = int(round(box.top * image.height))
            right = int(round(box.right * image.width))
            bottom = int(round(box.bottom * image.height))
            draw.rectangle((left, top, right, bottom), outline=color, width=3)
            label = f"{column_index + 1}.{order_positions[object_id]}"
            bbox = draw.textbbox((0, 0), label, font=font)
            label_width = bbox[2] - bbox[0] + 8
            label_height = bbox[3] - bbox[1] + 6
            label_top = max(0, top - label_height)
            draw.rectangle(
                (left, label_top, left + label_width, label_top + label_height),
                fill=color,
            )
            draw.text((left + 4, label_top + 2), label, fill="white", font=font)
    return image
