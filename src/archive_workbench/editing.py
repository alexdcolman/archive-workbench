from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from archive_workbench.sources import PROCESSABLE_SOURCE_TYPES
from archive_workbench.contracts.decisions import ProjectDecisions
from archive_workbench.contracts.editing import (
    EditableCommentExport,
    EditableExportManifest,
    EditableFormStructureExport,
    EditableObjectExport,
    EditableRevisionExport,
    EditableTagExport,
)
from archive_workbench.db.models import (
    ArchivalUnit,
    DigitalObject,
    DocumentPart,
    EditableObject,
    EditableObjectComment,
    EditableObjectRevision,
    EditableObjectTag,
    EditablePage,
    EditablePageRevision,
    ExtractedObject,
    ExtractionPage,
    ExtractionPageSelection,
    SourceRegistration,
    utc_now,
)
from archive_workbench.identity import new_id
from archive_workbench.io.jsonl import write_models_atomic


@dataclass(slots=True)
class EditingBootstrapSummary:
    documents_seen: int = 0
    pages_created: int = 0
    pages_reused: int = 0
    pages_stale: int = 0
    objects_created: int = 0
    revisions_created: int = 0
    warnings: list[str] = field(default_factory=list)


@dataclass(slots=True)
class EditingStatusRow:
    source_key: str
    title: str
    page_count: int | None
    selected_pages: int
    editable_pages: int
    stale_pages: list[int]
    active_objects: int
    deleted_objects: int
    revisions: int


@dataclass(slots=True)
class EditableObjectRow:
    object_id: str
    source_key: str
    page: int
    order_index: int
    object_type: str
    lifecycle_status: str
    review_status: str
    revision_number: int
    document_part_id: str | None
    document_part_key: str | None
    text: str


@dataclass(slots=True)
class RevisionRow:
    revision_id: str
    revision_number: int
    base_revision_number: int | None
    operation: str
    lifecycle_status: str
    object_type: str
    order_index: int
    text: str
    document_part_id: str | None
    note: str | None
    created_by: str
    created_at: datetime


@dataclass(slots=True)
class EditableExportSummary:
    output_root: Path
    manifest_path: Path
    objects_path: Path
    revisions_path: Path
    comments_path: Path
    tags_path: Path
    form_structures_path: Path
    object_count: int
    revision_count: int
    comment_count: int
    tag_count: int
    form_structure_count: int


def _registration_for_source(
    session: Session, source_key: str
) -> tuple[SourceRegistration, DigitalObject, ArchivalUnit]:
    row = session.execute(
        select(SourceRegistration, DigitalObject, ArchivalUnit)
        .join(DigitalObject, SourceRegistration.digital_object_id == DigitalObject.id)
        .join(ArchivalUnit, SourceRegistration.archival_unit_id == ArchivalUnit.id)
        .where(
            SourceRegistration.source_type.in_(PROCESSABLE_SOURCE_TYPES),
            SourceRegistration.source_key == source_key,
        )
    ).one_or_none()
    if row is None:
        raise ValueError(f"source_key no registrado: {source_key}")
    return row[0], row[1], row[2]


def _allowed_object_type(decisions: ProjectDecisions, object_type: str) -> None:
    definitions = {item.key: item for item in decisions.object_types}
    definition = definitions.get(object_type)
    if definition is None:
        raise ValueError(f"Tipo de objeto desconocido: {object_type}")
    if not definition.editable:
        raise ValueError(f"El tipo de objeto no es editable: {object_type}")


def _append_revision(
    session: Session,
    obj: EditableObject,
    *,
    operation: str,
    created_by: str,
    note: str | None,
    base_revision_number: int | None,
    created_at: datetime | None = None,
) -> EditableObjectRevision:
    revision = EditableObjectRevision(
        id=new_id(),
        editable_object_id=obj.id,
        revision_number=obj.revision_number,
        base_revision_number=base_revision_number,
        operation=operation,
        text=obj.current_text,
        object_type=obj.current_object_type,
        order_index=obj.current_order_index,
        geometry_json=obj.current_geometry_json,
        attributes_json=obj.current_attributes_json,
        lifecycle_status=obj.lifecycle_status,
        document_part_id=obj.document_part_id,
        note=note,
        created_by=created_by,
        created_at=created_at or utc_now(),
    )
    session.add(revision)
    return revision


def _append_page_revision(
    session: Session,
    page: EditablePage,
    *,
    operation: str,
    created_by: str,
    note: str | None = None,
    details: dict[str, Any] | None = None,
    base_revision_number: int | None = None,
) -> EditablePageRevision:
    revision = EditablePageRevision(
        id=new_id(),
        editable_page_id=page.id,
        revision_number=page.revision_number,
        base_revision_number=base_revision_number,
        operation=operation,
        source_extraction_run_id=page.source_extraction_run_id,
        source_extraction_page_id=page.source_extraction_page_id,
        source_selection_id=page.source_selection_id,
        status=page.status,
        review_status=page.review_status,
        review_note=page.review_note,
        form_structure_json=page.form_structure_json or {},
        details_json=details or {},
        note=note,
        created_by=created_by,
        created_at=utc_now(),
    )
    session.add(revision)
    return revision


def _set_page_status(
    session: Session,
    page: EditablePage,
    *,
    status: str,
    changed_by: str,
    operation: str,
    note: str | None = None,
    details: dict[str, Any] | None = None,
) -> bool:
    if page.status == status:
        return False
    base = page.revision_number
    page.status = status
    page.revision_number += 1
    page.updated_at = utc_now()
    _append_page_revision(
        session,
        page,
        operation=operation,
        created_by=changed_by,
        note=note,
        details=details,
        base_revision_number=base,
    )
    return True


def bootstrap_editable_layer(
    session: Session,
    *,
    decisions: ProjectDecisions,
    created_by: str,
    source_keys: set[str] | None = None,
    pages: set[int] | None = None,
) -> EditingBootstrapSummary:
    """Copia selecciones OCR a una capa editable sin modificar extracted_objects."""
    summary = EditingBootstrapSummary()
    query = (
        select(SourceRegistration, DigitalObject, ArchivalUnit)
        .join(DigitalObject, SourceRegistration.digital_object_id == DigitalObject.id)
        .join(ArchivalUnit, SourceRegistration.archival_unit_id == ArchivalUnit.id)
        .where(SourceRegistration.source_type.in_(PROCESSABLE_SOURCE_TYPES))
        .order_by(SourceRegistration.source_key)
    )
    if source_keys:
        query = query.where(SourceRegistration.source_key.in_(source_keys))
    rows = session.execute(query).all()
    found = {row[0].source_key for row in rows}
    missing = (source_keys or set()) - found
    if missing:
        raise ValueError(f"source_key no registrado: {', '.join(sorted(missing))}")

    for registration, digital, _unit in rows:
        summary.documents_seen += 1
        selection_query = (
            select(ExtractionPageSelection, ExtractionPage)
            .join(ExtractionPage, ExtractionPageSelection.extraction_page_id == ExtractionPage.id)
            .where(ExtractionPageSelection.digital_object_id == digital.id)
            .order_by(ExtractionPageSelection.page_number)
        )
        if pages:
            selection_query = selection_query.where(
                ExtractionPageSelection.page_number.in_(pages)
            )
        selections = session.execute(selection_query).all()
        if not selections:
            summary.warnings.append(
                f"{registration.source_key}: no hay páginas seleccionadas para inicializar"
            )
            continue

        for selection, extraction_page in selections:
            existing = session.scalar(
                select(EditablePage).where(
                    EditablePage.digital_object_id == digital.id,
                    EditablePage.page_number == selection.page_number,
                )
            )
            if existing is not None:
                if existing.source_extraction_page_id == extraction_page.id:
                    _set_page_status(
                        session,
                        existing,
                        status="active",
                        changed_by=created_by,
                        operation="reactivate",
                        note="La selección canónica vuelve a coincidir con el origen editable.",
                    )
                    summary.pages_reused += 1
                else:
                    _set_page_status(
                        session,
                        existing,
                        status="stale",
                        changed_by=created_by,
                        operation="mark_stale",
                        note="La selección OCR cambió; la capa editable se conservó sin reemplazos.",
                        details={
                            "selected_extraction_run_id": selection.extraction_run_id,
                            "selected_extraction_page_id": extraction_page.id,
                        },
                    )
                    summary.pages_stale += 1
                    summary.warnings.append(
                        f"{registration.source_key}, página {selection.page_number}: "
                        "la selección OCR cambió; la capa editable existente no fue reemplazada"
                    )
                continue

            editable_page = EditablePage(
                id=new_id(),
                digital_object_id=digital.id,
                page_number=selection.page_number,
                source_extraction_run_id=selection.extraction_run_id,
                source_extraction_page_id=extraction_page.id,
                source_selection_id=selection.id,
                status="active",
                bootstrapped_by=created_by,
                bootstrapped_at=utc_now(),
                updated_at=utc_now(),
            )
            session.add(editable_page)
            session.flush()
            _append_page_revision(
                session,
                editable_page,
                operation="bootstrap",
                created_by=created_by,
                note="Página inicializada desde la extracción seleccionada.",
                details={"source_key": registration.source_key},
                base_revision_number=None,
            )
            summary.pages_created += 1

            source_objects = session.scalars(
                select(ExtractedObject)
                .where(
                    ExtractedObject.extraction_run_id == selection.extraction_run_id,
                    ExtractedObject.page_number == selection.page_number,
                )
                .order_by(ExtractedObject.order_index, ExtractedObject.id)
            ).all()
            for source in source_objects:
                object_type = source.object_type
                if object_type not in {item.key for item in decisions.object_types}:
                    object_type = "paragraph"
                obj = EditableObject(
                    id=new_id(),
                    editable_page_id=editable_page.id,
                    digital_object_id=digital.id,
                    page_number=selection.page_number,
                    source_extracted_object_id=source.id,
                    source_origin_id=source.origin_id,
                    current_text=source.original_text,
                    current_object_type=object_type,
                    current_order_index=source.order_index,
                    current_geometry_json=source.geometry_json,
                    current_attributes_json={
                        **(source.attributes_json or {}),
                        "source_label": source.source_label,
                        "source_confidence": source.confidence,
                        "source_language": source.language,
                    },
                    lifecycle_status="active",
                    revision_number=1,
                    created_by=created_by,
                    created_at=utc_now(),
                    updated_by=created_by,
                    updated_at=utc_now(),
                )
                session.add(obj)
                session.flush()
                _append_revision(
                    session,
                    obj,
                    operation="import",
                    created_by=created_by,
                    note="Importado desde la extracción seleccionada; OCR original inmutable",
                    base_revision_number=None,
                )
                summary.objects_created += 1
                summary.revisions_created += 1
    return summary


def update_editable_object(
    session: Session,
    *,
    decisions: ProjectDecisions,
    object_id: str,
    expected_revision: int,
    edited_by: str,
    text: str | None = None,
    object_type: str | None = None,
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
    if text is None and object_type is None:
        raise ValueError("Debe indicarse --text/--text-file o --object-type")
    if object_type is not None:
        _allowed_object_type(decisions, object_type)
    base = obj.revision_number
    if text is not None:
        obj.current_text = text
    if object_type is not None:
        obj.current_object_type = object_type
    obj.revision_number += 1
    obj.updated_by = edited_by
    obj.updated_at = utc_now()
    _append_revision(
        session,
        obj,
        operation="edit",
        created_by=edited_by,
        note=note,
        base_revision_number=base,
    )
    return obj


def add_editable_object(
    session: Session,
    *,
    decisions: ProjectDecisions,
    source_key: str,
    page: int,
    object_type: str,
    text: str,
    created_by: str,
    after_object_id: str | None = None,
    before_object_id: str | None = None,
    note: str | None = None,
    document_part_id: str | None = None,
) -> EditableObject:
    if after_object_id and before_object_id:
        raise ValueError("Use --after-object-id o --before-object-id, no ambos")
    _allowed_object_type(decisions, object_type)
    _registration, digital, _unit = _registration_for_source(session, source_key)
    editable_page = session.scalar(
        select(EditablePage).where(
            EditablePage.digital_object_id == digital.id,
            EditablePage.page_number == page,
        )
    )
    if editable_page is None:
        raise ValueError(
            f"La página {page} de {source_key} no fue inicializada para edición"
        )
    if document_part_id is not None:
        part = session.get(DocumentPart, document_part_id)
        if part is None:
            raise ValueError(f"Parte interna inexistente: {document_part_id}")
        if part.digital_object_id != digital.id:
            raise ValueError("La parte interna pertenece a otro documento")
        sequence = list(part.page_sequence_json or range(part.page_start, part.page_end + 1))
        if page not in sequence:
            raise ValueError(
                f"La parte {part.part_key} no incluye la página física {page}"
            )

    active = session.scalars(
        select(EditableObject)
        .where(
            EditableObject.editable_page_id == editable_page.id,
            EditableObject.lifecycle_status == "active",
        )
        .order_by(EditableObject.current_order_index, EditableObject.id)
    ).all()
    position = (max((item.current_order_index for item in active), default=-1) + 1)
    anchor_id = after_object_id or before_object_id
    if anchor_id:
        anchor = next((item for item in active if item.id == anchor_id), None)
        if anchor is None:
            raise ValueError("El objeto de anclaje no pertenece a la página indicada")
        position = anchor.current_order_index + (1 if after_object_id else 0)
        # Reordenamiento versionado de los objetos desplazados.
        for item in sorted(
            (candidate for candidate in active if candidate.current_order_index >= position),
            key=lambda candidate: candidate.current_order_index,
            reverse=True,
        ):
            base = item.revision_number
            item.current_order_index += 1
            item.revision_number += 1
            item.updated_by = created_by
            item.updated_at = utc_now()
            _append_revision(
                session,
                item,
                operation="edit",
                created_by=created_by,
                note=f"Reordenado al insertar un objeto en la posición {position}",
                base_revision_number=base,
            )

    obj = EditableObject(
        id=new_id(),
        editable_page_id=editable_page.id,
        digital_object_id=digital.id,
        page_number=page,
        document_part_id=document_part_id,
        source_extracted_object_id=None,
        source_origin_id=None,
        current_text=text,
        current_object_type=object_type,
        current_order_index=position,
        current_geometry_json=[],
        current_attributes_json={"manually_added": True},
        lifecycle_status="active",
        revision_number=1,
        created_by=created_by,
        created_at=utc_now(),
        updated_by=created_by,
        updated_at=utc_now(),
    )
    session.add(obj)
    session.flush()
    _append_revision(
        session,
        obj,
        operation="add",
        created_by=created_by,
        note=note,
        base_revision_number=None,
    )
    return obj



def _active_page_objects(session: Session, editable_page_id: str) -> list[EditableObject]:
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


def _require_editable_object(
    session: Session, *, object_id: str, expected_revision: int
) -> EditableObject:
    obj = session.get(EditableObject, object_id)
    if obj is None:
        raise ValueError(f"Objeto editable inexistente: {object_id}")
    if obj.lifecycle_status != "active":
        raise ValueError("La operación estructural requiere un objeto activo")
    if obj.revision_number != expected_revision:
        raise ValueError(
            f"Conflicto de revisión: se esperaba {expected_revision}, "
            f"pero el objeto está en {obj.revision_number}"
        )
    return obj


def _append_lineage_event(
    attributes: dict[str, Any] | None, event: dict[str, Any]
) -> dict[str, Any]:
    result = dict(attributes or {})
    events = list(result.get("lineage_events") or [])
    events.append(event)
    result["lineage_events"] = events
    return result


def _record_reorder(
    session: Session,
    obj: EditableObject,
    *,
    new_order: int,
    changed_by: str,
    note: str,
) -> None:
    if obj.current_order_index == new_order:
        return
    base = obj.revision_number
    obj.current_order_index = new_order
    obj.revision_number += 1
    obj.updated_by = changed_by
    obj.updated_at = utc_now()
    _append_revision(
        session,
        obj,
        operation="reorder",
        created_by=changed_by,
        note=note,
        base_revision_number=base,
    )


def move_editable_object(
    session: Session,
    *,
    object_id: str,
    expected_revision: int,
    direction: str,
    changed_by: str,
    note: str | None = None,
) -> EditableObject:
    """Intercambia el objeto con su vecino activo y registra ambas revisiones."""
    if direction not in {"up", "down"}:
        raise ValueError("direction debe ser up o down")
    obj = _require_editable_object(
        session, object_id=object_id, expected_revision=expected_revision
    )
    active = _active_page_objects(session, obj.editable_page_id)
    index = next((i for i, item in enumerate(active) if item.id == obj.id), None)
    if index is None:
        raise ValueError("El objeto no pertenece a una página editable activa")
    target_index = index - 1 if direction == "up" else index + 1
    if target_index < 0 or target_index >= len(active):
        raise ValueError("El objeto ya está en el extremo de la página")
    neighbor = active[target_index]
    old_order = obj.current_order_index
    neighbor_order = neighbor.current_order_index
    movement_note = note or (
        "Movido una posición hacia arriba" if direction == "up" else "Movido una posición hacia abajo"
    )
    _record_reorder(
        session, obj, new_order=neighbor_order, changed_by=changed_by, note=movement_note
    )
    _record_reorder(
        session,
        neighbor,
        new_order=old_order,
        changed_by=changed_by,
        note=f"Desplazado por el movimiento del objeto {obj.id}",
    )
    return obj


def split_editable_object(
    session: Session,
    *,
    object_id: str,
    expected_revision: int,
    left_text: str,
    right_text: str,
    changed_by: str,
    note: str | None = None,
) -> tuple[EditableObject, EditableObject]:
    """Divide el texto sin inventar una geometría nueva para la segunda parte."""
    if not left_text.strip() or not right_text.strip():
        raise ValueError("Ambas partes de la división deben contener texto")
    obj = _require_editable_object(
        session, object_id=object_id, expected_revision=expected_revision
    )
    active = _active_page_objects(session, obj.editable_page_id)
    insertion_order = obj.current_order_index + 1
    for candidate in sorted(
        (item for item in active if item.current_order_index >= insertion_order),
        key=lambda item: item.current_order_index,
        reverse=True,
    ):
        _record_reorder(
            session,
            candidate,
            new_order=candidate.current_order_index + 1,
            changed_by=changed_by,
            note=f"Desplazado al dividir el objeto {obj.id}",
        )

    base = obj.revision_number
    obj.current_text = left_text
    obj.current_attributes_json = _append_lineage_event(
        obj.current_attributes_json,
        {
            "operation": "split",
            "role": "left",
            "created_by": changed_by,
            "created_at": utc_now().isoformat(),
        },
    )
    obj.revision_number += 1
    obj.updated_by = changed_by
    obj.updated_at = utc_now()
    _append_revision(
        session,
        obj,
        operation="split",
        created_by=changed_by,
        note=note or "Primera parte de una división manual",
        base_revision_number=base,
    )

    new_object = EditableObject(
        id=new_id(),
        editable_page_id=obj.editable_page_id,
        digital_object_id=obj.digital_object_id,
        page_number=obj.page_number,
        document_part_id=obj.document_part_id,
        source_extracted_object_id=None,
        source_origin_id=None,
        current_text=right_text,
        current_object_type=obj.current_object_type,
        current_order_index=insertion_order,
        current_geometry_json=[],
        current_attributes_json={
            "manually_added": True,
            "split_from_object_id": obj.id,
            "geometry_pending": bool(obj.current_geometry_json),
            "lineage_events": [
                {
                    "operation": "split",
                    "role": "right",
                    "source_object_id": obj.id,
                    "created_by": changed_by,
                    "created_at": utc_now().isoformat(),
                }
            ],
        },
        lifecycle_status="active",
        revision_number=1,
        created_by=changed_by,
        created_at=utc_now(),
        updated_by=changed_by,
        updated_at=utc_now(),
    )
    session.add(new_object)
    session.flush()
    _append_revision(
        session,
        new_object,
        operation="split",
        created_by=changed_by,
        note=note or f"Segunda parte derivada del objeto {obj.id}",
        base_revision_number=None,
    )
    return obj, new_object


def merge_editable_object(
    session: Session,
    *,
    object_id: str,
    expected_revision: int,
    direction: str,
    separator: str,
    changed_by: str,
    note: str | None = None,
) -> EditableObject:
    """Combina con el vecino, conserva el objeto seleccionado y elimina lógicamente el otro."""
    if direction not in {"previous", "next"}:
        raise ValueError("direction debe ser previous o next")
    obj = _require_editable_object(
        session, object_id=object_id, expected_revision=expected_revision
    )
    active = _active_page_objects(session, obj.editable_page_id)
    index = next((i for i, item in enumerate(active) if item.id == obj.id), None)
    if index is None:
        raise ValueError("El objeto no pertenece a una página editable activa")
    adjacent_index = index - 1 if direction == "previous" else index + 1
    if adjacent_index < 0 or adjacent_index >= len(active):
        raise ValueError("No existe un objeto adyacente en esa dirección")
    adjacent = active[adjacent_index]
    if (
        obj.document_part_id is not None
        and adjacent.document_part_id is not None
        and obj.document_part_id != adjacent.document_part_id
    ):
        raise ValueError(
            "No se pueden combinar objetos asignados a partes internas diferentes"
        )
    if obj.document_part_id is None and adjacent.document_part_id is not None:
        obj.document_part_id = adjacent.document_part_id
    first, second = (adjacent, obj) if direction == "previous" else (obj, adjacent)
    combined_text = first.current_text + separator + second.current_text
    combined_geometry: list[dict[str, Any]] = []
    for geometry in list(first.current_geometry_json or []) + list(second.current_geometry_json or []):
        if geometry not in combined_geometry:
            combined_geometry.append(geometry)

    original_selected_order = obj.current_order_index
    removed_order = adjacent.current_order_index
    base = obj.revision_number
    obj.current_text = combined_text
    obj.current_order_index = min(original_selected_order, removed_order)
    obj.current_geometry_json = combined_geometry
    obj.current_attributes_json = _append_lineage_event(
        obj.current_attributes_json,
        {
            "operation": "merge",
            "merged_object_id": adjacent.id,
            "direction": direction,
            "created_by": changed_by,
            "created_at": utc_now().isoformat(),
        },
    )
    obj.revision_number += 1
    obj.updated_by = changed_by
    obj.updated_at = utc_now()
    _append_revision(
        session,
        obj,
        operation="merge",
        created_by=changed_by,
        note=note or f"Combinado con el objeto {adjacent.id}",
        base_revision_number=base,
    )

    adjacent_base = adjacent.revision_number
    adjacent.lifecycle_status = "deleted"
    adjacent.current_attributes_json = _append_lineage_event(
        adjacent.current_attributes_json,
        {
            "operation": "merge",
            "merged_into_object_id": obj.id,
            "created_by": changed_by,
            "created_at": utc_now().isoformat(),
        },
    )
    adjacent.revision_number += 1
    adjacent.updated_by = changed_by
    adjacent.updated_at = utc_now()
    _append_revision(
        session,
        adjacent,
        operation="merge",
        created_by=changed_by,
        note=note or f"Eliminado lógicamente al combinarse con {obj.id}",
        base_revision_number=adjacent_base,
    )

    threshold = max(original_selected_order, removed_order)
    for candidate in active:
        if candidate.id in {obj.id, adjacent.id}:
            continue
        if candidate.current_order_index > threshold:
            _record_reorder(
                session,
                candidate,
                new_order=candidate.current_order_index - 1,
                changed_by=changed_by,
                note=f"Reindexado después de combinar {obj.id} y {adjacent.id}",
            )
    return obj

def set_editable_object_lifecycle(
    session: Session,
    *,
    object_id: str,
    expected_revision: int,
    lifecycle_status: str,
    changed_by: str,
    note: str | None = None,
) -> EditableObject:
    if lifecycle_status not in {"active", "deleted"}:
        raise ValueError("lifecycle_status debe ser active o deleted")
    obj = session.get(EditableObject, object_id)
    if obj is None:
        raise ValueError(f"Objeto editable inexistente: {object_id}")
    if obj.revision_number != expected_revision:
        raise ValueError(
            f"Conflicto de revisión: se esperaba {expected_revision}, "
            f"pero el objeto está en {obj.revision_number}"
        )
    if obj.lifecycle_status == lifecycle_status:
        return obj
    base = obj.revision_number
    obj.lifecycle_status = lifecycle_status
    obj.revision_number += 1
    obj.updated_by = changed_by
    obj.updated_at = utc_now()
    _append_revision(
        session,
        obj,
        operation="delete" if lifecycle_status == "deleted" else "restore",
        created_by=changed_by,
        note=note,
        base_revision_number=base,
    )
    return obj


def revert_editable_object(
    session: Session,
    *,
    object_id: str,
    target_revision: int,
    expected_revision: int,
    reverted_by: str,
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
    target = session.scalar(
        select(EditableObjectRevision).where(
            EditableObjectRevision.editable_object_id == object_id,
            EditableObjectRevision.revision_number == target_revision,
        )
    )
    if target is None:
        raise ValueError(f"No existe la revisión {target_revision} para {object_id}")
    base = obj.revision_number
    obj.current_text = target.text
    obj.current_object_type = target.object_type
    obj.current_order_index = target.order_index
    obj.current_geometry_json = target.geometry_json
    obj.current_attributes_json = target.attributes_json
    obj.lifecycle_status = target.lifecycle_status
    obj.document_part_id = target.document_part_id
    obj.revision_number += 1
    obj.updated_by = reverted_by
    obj.updated_at = utc_now()
    _append_revision(
        session,
        obj,
        operation="revert",
        created_by=reverted_by,
        note=note or f"Restaurado desde la revisión {target_revision}",
        base_revision_number=base,
    )
    return obj


def editing_status_rows(session: Session) -> list[EditingStatusRow]:
    registrations = session.execute(
        select(SourceRegistration, DigitalObject, ArchivalUnit)
        .join(DigitalObject, SourceRegistration.digital_object_id == DigitalObject.id)
        .join(ArchivalUnit, SourceRegistration.archival_unit_id == ArchivalUnit.id)
        .where(SourceRegistration.source_type.in_(PROCESSABLE_SOURCE_TYPES))
        .order_by(SourceRegistration.source_key)
    ).all()
    result: list[EditingStatusRow] = []
    for registration, digital, unit in registrations:
        selected = int(
            session.scalar(
                select(func.count())
                .select_from(ExtractionPageSelection)
                .where(ExtractionPageSelection.digital_object_id == digital.id)
            )
            or 0
        )
        editable_pages = session.scalars(
            select(EditablePage)
            .where(EditablePage.digital_object_id == digital.id)
            .order_by(EditablePage.page_number)
        ).all()
        stale: list[int] = []
        for page in editable_pages:
            selected_page = session.scalar(
                select(ExtractionPageSelection).where(
                    ExtractionPageSelection.digital_object_id == digital.id,
                    ExtractionPageSelection.page_number == page.page_number,
                )
            )
            if selected_page is None or selected_page.extraction_page_id != page.source_extraction_page_id:
                stale.append(page.page_number)
        active = int(
            session.scalar(
                select(func.count())
                .select_from(EditableObject)
                .where(
                    EditableObject.digital_object_id == digital.id,
                    EditableObject.lifecycle_status == "active",
                )
            )
            or 0
        )
        deleted = int(
            session.scalar(
                select(func.count())
                .select_from(EditableObject)
                .where(
                    EditableObject.digital_object_id == digital.id,
                    EditableObject.lifecycle_status == "deleted",
                )
            )
            or 0
        )
        revisions = int(
            session.scalar(
                select(func.count())
                .select_from(EditableObjectRevision)
                .join(EditableObject, EditableObjectRevision.editable_object_id == EditableObject.id)
                .where(EditableObject.digital_object_id == digital.id)
            )
            or 0
        )
        result.append(
            EditingStatusRow(
                source_key=registration.source_key,
                title=unit.title,
                page_count=digital.page_count,
                selected_pages=selected,
                editable_pages=len(editable_pages),
                stale_pages=stale,
                active_objects=active,
                deleted_objects=deleted,
                revisions=revisions,
            )
        )
    return result


def editable_object_rows(
    session: Session,
    *,
    source_key: str,
    page: int | None = None,
    include_deleted: bool = False,
) -> list[EditableObjectRow]:
    _registration, digital, _unit = _registration_for_source(session, source_key)
    query = select(EditableObject).where(EditableObject.digital_object_id == digital.id)
    if page is not None:
        query = query.where(EditableObject.page_number == page)
    if not include_deleted:
        query = query.where(EditableObject.lifecycle_status == "active")
    objects = session.scalars(
        query.order_by(
            EditableObject.page_number,
            EditableObject.current_order_index,
            EditableObject.id,
        )
    ).all()
    part_ids = {item.document_part_id for item in objects if item.document_part_id}
    part_keys = {
        item.id: item.part_key
        for item in (
            session.scalars(select(DocumentPart).where(DocumentPart.id.in_(part_ids))).all()
            if part_ids
            else []
        )
    }
    return [
        EditableObjectRow(
            object_id=item.id,
            source_key=source_key,
            page=item.page_number,
            order_index=item.current_order_index,
            document_part_id=item.document_part_id,
            document_part_key=part_keys.get(item.document_part_id),
            object_type=item.current_object_type,
            lifecycle_status=item.lifecycle_status,
            review_status=item.review_status,
            revision_number=item.revision_number,
            text=item.current_text,
        )
        for item in objects
    ]


def object_revision_rows(session: Session, *, object_id: str) -> list[RevisionRow]:
    if session.get(EditableObject, object_id) is None:
        raise ValueError(f"Objeto editable inexistente: {object_id}")
    revisions = session.scalars(
        select(EditableObjectRevision)
        .where(EditableObjectRevision.editable_object_id == object_id)
        .order_by(EditableObjectRevision.revision_number)
    ).all()
    return [
        RevisionRow(
            revision_id=item.id,
            revision_number=item.revision_number,
            base_revision_number=item.base_revision_number,
            operation=item.operation,
            lifecycle_status=item.lifecycle_status,
            object_type=item.object_type,
            order_index=item.order_index,
            text=item.text,
            document_part_id=item.document_part_id,
            note=item.note,
            created_by=item.created_by,
            created_at=item.created_at,
        )
        for item in revisions
    ]


def export_editable_layer(
    session: Session,
    *,
    project_root: str | Path,
    source_key: str,
    destination: str | Path | None = None,
) -> EditableExportSummary:
    _registration, digital, _unit = _registration_for_source(session, source_key)
    root = Path(project_root)
    output_root = (
        Path(destination)
        if destination is not None
        else root / "exports" / "editable" / source_key
    )
    if not output_root.is_absolute():
        output_root = root / output_root
    output_root.mkdir(parents=True, exist_ok=True)

    objects = session.scalars(
        select(EditableObject)
        .where(EditableObject.digital_object_id == digital.id)
        .order_by(
            EditableObject.page_number,
            EditableObject.current_order_index,
            EditableObject.id,
        )
    ).all()
    object_ids = [item.id for item in objects]
    revisions = (
        session.scalars(
            select(EditableObjectRevision)
            .where(EditableObjectRevision.editable_object_id.in_(object_ids))
            .order_by(
                EditableObjectRevision.editable_object_id,
                EditableObjectRevision.revision_number,
            )
        ).all()
        if object_ids
        else []
    )

    part_ids = {
        item.document_part_id for item in objects if item.document_part_id
    } | {
        item.document_part_id for item in revisions if item.document_part_id
    }
    part_keys = {
        item.id: item.part_key
        for item in (
            session.scalars(select(DocumentPart).where(DocumentPart.id.in_(part_ids))).all()
            if part_ids
            else []
        )
    }

    object_exports = [
        EditableObjectExport(
            editable_object_id=item.id,
            source_key=source_key,
            digital_object_id=item.digital_object_id,
            page=item.page_number,
            order_index=item.current_order_index,
            document_part_id=item.document_part_id,
            document_part_key=part_keys.get(item.document_part_id),
            object_type=item.current_object_type,
            text=item.current_text,
            geometry=item.current_geometry_json,
            attributes=item.current_attributes_json,
            lifecycle_status=item.lifecycle_status,
            review_status=item.review_status,
            revision_number=item.revision_number,
            source_extracted_object_id=item.source_extracted_object_id,
            source_origin_id=item.source_origin_id,
            updated_by=item.updated_by,
            updated_at=item.updated_at,
        )
        for item in objects
    ]
    revision_exports = [
        EditableRevisionExport(
            revision_id=item.id,
            editable_object_id=item.editable_object_id,
            revision_number=item.revision_number,
            base_revision_number=item.base_revision_number,
            operation=item.operation,  # type: ignore[arg-type]
            text=item.text,
            object_type=item.object_type,
            order_index=item.order_index,
            geometry=item.geometry_json,
            attributes=item.attributes_json,
            lifecycle_status=item.lifecycle_status,  # type: ignore[arg-type]
            document_part_id=item.document_part_id,
            document_part_key=part_keys.get(item.document_part_id),
            note=item.note,
            created_by=item.created_by,
            created_at=item.created_at,
        )
        for item in revisions
    ]
    comments = (
        session.scalars(
            select(EditableObjectComment)
            .where(EditableObjectComment.editable_object_id.in_(object_ids))
            .order_by(EditableObjectComment.created_at, EditableObjectComment.id)
        ).all()
        if object_ids
        else []
    )
    tags = (
        session.scalars(
            select(EditableObjectTag)
            .where(EditableObjectTag.editable_object_id.in_(object_ids))
            .order_by(EditableObjectTag.editable_object_id, EditableObjectTag.normalized_tag)
        ).all()
        if object_ids
        else []
    )
    comment_exports = [
        EditableCommentExport(
            comment_id=item.id,
            editable_object_id=item.editable_object_id,
            body=item.body,
            created_by=item.created_by,
            created_at=item.created_at,
        )
        for item in comments
    ]
    tag_exports = [
        EditableTagExport(
            tag_id=item.id,
            editable_object_id=item.editable_object_id,
            tag=item.tag,
            tag_kind=item.tag_kind,
            created_by=item.created_by,
            created_at=item.created_at,
        )
        for item in tags
    ]
    pages = session.scalars(
        select(EditablePage)
        .where(EditablePage.digital_object_id == digital.id)
        .order_by(EditablePage.page_number, EditablePage.id)
    ).all()
    form_structure_exports = [
        EditableFormStructureExport(
            editable_page_id=item.id,
            source_key=source_key,
            digital_object_id=item.digital_object_id,
            page=item.page_number,
            revision_number=item.revision_number,
            structure=item.form_structure_json or {},
        )
        for item in pages
        if (item.form_structure_json or {}).get("groups")
        or (item.form_structure_json or {}).get("controls")
    ]
    objects_path = output_root / "editable_objects.jsonl"
    revisions_path = output_root / "editable_revisions.jsonl"
    comments_path = output_root / "editable_comments.jsonl"
    tags_path = output_root / "editable_tags.jsonl"
    form_structures_path = output_root / "form_structures.jsonl"
    manifest_path = output_root / "manifest.json"
    write_models_atomic(objects_path, object_exports)
    write_models_atomic(revisions_path, revision_exports)
    write_models_atomic(comments_path, comment_exports)
    write_models_atomic(tags_path, tag_exports)
    write_models_atomic(form_structures_path, form_structure_exports)
    active_count = sum(item.lifecycle_status == "active" for item in objects)
    manifest = EditableExportManifest(
        source_key=source_key,
        digital_object_id=digital.id,
        exported_at=datetime.now(timezone.utc),
        object_count=len(objects),
        active_count=active_count,
        deleted_count=len(objects) - active_count,
        revision_count=len(revisions),
        comment_count=len(comments),
        tag_count=len(tags),
        form_structure_count=len(form_structure_exports),
        objects_path=objects_path.name,
        revisions_path=revisions_path.name,
        comments_path=comments_path.name,
        tags_path=tags_path.name,
        form_structures_path=form_structures_path.name,
    )
    manifest_path.write_text(
        json.dumps(manifest.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return EditableExportSummary(
        output_root=output_root,
        manifest_path=manifest_path,
        objects_path=objects_path,
        revisions_path=revisions_path,
        comments_path=comments_path,
        tags_path=tags_path,
        form_structures_path=form_structures_path,
        object_count=len(objects),
        revision_count=len(revisions),
        comment_count=len(comments),
        tag_count=len(tags),
        form_structure_count=len(form_structure_exports),
    )
