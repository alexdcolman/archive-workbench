from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Iterable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from archive_workbench.catalog_management import create_archival_unit, link_existing_digital_object
from archive_workbench.contracts.decisions import ProjectDecisions
from archive_workbench.db.models import (
    ArchivalDocumentComponent,
    ArchivalUnit,
    DigitalObject,
    DigitalObjectUnitLink,
    DerivativeAsset,
    EditableObject,
    FileInstance,
    PreprocessingRun,
)
from archive_workbench.identity import new_id

_TITLE_TYPES = {
    "title",
    "titulo",
    "título",
    "heading",
    "header",
    "section_header",
    "section-heading",
    "encabezado",
    "encabezado interno",
}


@dataclass(slots=True, frozen=True)
class DocumentOrganizationSourceRow:
    digital_object_id: str
    original_filename: str
    media_type: str
    page_count: int | None
    relative_path: str | None
    preview_relative_path: str | None
    suggested_title: str
    text_preview: str
    organized_count: int


@dataclass(slots=True, frozen=True)
class DocumentComponentDraft:
    digital_object_id: str
    page_start: int | None = None
    page_end: int | None = None


@dataclass(slots=True, frozen=True)
class DocumentGroupDraft:
    title: str
    components: tuple[DocumentComponentDraft, ...]


@dataclass(slots=True, frozen=True)
class CreatedDocumentRow:
    archival_unit_id: str
    title: str
    component_count: int


@dataclass(slots=True, frozen=True)
class CreateDocumentsResult:
    created: tuple[CreatedDocumentRow, ...]


def natural_filename_key(value: str) -> tuple[tuple[int, object], ...]:
    """Ordena nombres con tramos numéricos como 1, 2, 3, 10, 100."""
    parts = re.split(r"(\d+)", str(value or ""))
    return tuple(
        (0, int(part)) if part.isdigit() else (1, part.casefold())
        for part in parts
        if part
    )


def record_level_options(decisions: ProjectDecisions, parent_level_key: str) -> list[str]:
    return [
        level.key
        for level in sorted(decisions.archival_levels, key=lambda row: row.display_order)
        if level.enabled
        and level.resolved_semantic_kind == "record"
        and parent_level_key in level.parent_keys
    ]


def _normalize_preview(text: str, *, limit: int = 360) -> str:
    cleaned = " ".join(str(text or "").split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1].rstrip() + "…"


def _filename_title(filename: str) -> str:
    stem = Path(filename).stem.replace("_", " ").replace("-", " ")
    cleaned = " ".join(stem.split()).strip()
    return cleaned or filename


def organization_source_rows(
    session: Session,
    *,
    project_id: str,
    parent_unit_id: str,
) -> list[DocumentOrganizationSourceRow]:
    parent = session.get(ArchivalUnit, parent_unit_id)
    if parent is None or parent.project_id != project_id:
        raise ValueError("La unidad seleccionada no existe en este proyecto")

    digital_rows = session.execute(
        select(DigitalObjectUnitLink, DigitalObject)
        .join(DigitalObject, DigitalObject.id == DigitalObjectUnitLink.digital_object_id)
        .where(
            DigitalObjectUnitLink.archival_unit_id == parent_unit_id,
            DigitalObject.project_id == project_id,
        )
        .order_by(DigitalObject.original_filename, DigitalObject.id)
    ).all()
    if not digital_rows:
        return []

    digital_ids = [digital.id for _link, digital in digital_rows]
    file_rows = session.scalars(
        select(FileInstance)
        .where(
            FileInstance.digital_object_id.in_(digital_ids),
            FileInstance.storage_root == "project",
        )
        .order_by(FileInstance.digital_object_id, FileInstance.relative_path)
    ).all()
    first_file: dict[str, str] = {}
    for row in file_rows:
        first_file.setdefault(row.digital_object_id, row.relative_path)

    preview_rows = session.execute(
        select(
            DerivativeAsset.digital_object_id,
            DerivativeAsset.relative_path,
            PreprocessingRun.created_at,
        )
        .join(
            PreprocessingRun,
            PreprocessingRun.id == DerivativeAsset.preprocessing_run_id,
        )
        .where(
            DerivativeAsset.digital_object_id.in_(digital_ids),
            DerivativeAsset.page_number == 1,
            DerivativeAsset.kind == "preview",
            PreprocessingRun.is_current.is_(True),
            PreprocessingRun.status.in_(["completed", "completed_with_warnings"]),
        )
        .order_by(
            DerivativeAsset.digital_object_id,
            PreprocessingRun.created_at.desc(),
            DerivativeAsset.id,
        )
    ).all()
    first_preview: dict[str, str] = {}
    for digital_id, relative_path, _created_at in preview_rows:
        first_preview.setdefault(str(digital_id), str(relative_path))

    editable_rows = session.scalars(
        select(EditableObject)
        .where(
            EditableObject.digital_object_id.in_(digital_ids),
            EditableObject.lifecycle_status == "active",
        )
        .order_by(
            EditableObject.digital_object_id,
            EditableObject.page_number,
            EditableObject.current_order_index,
            EditableObject.id,
        )
    ).all()
    texts: dict[str, list[EditableObject]] = {digital_id: [] for digital_id in digital_ids}
    for row in editable_rows:
        texts.setdefault(row.digital_object_id, []).append(row)

    component_counts = dict(
        session.execute(
            select(ArchivalDocumentComponent.digital_object_id, func.count())
            .join(ArchivalUnit, ArchivalUnit.id == ArchivalDocumentComponent.archival_unit_id)
            .where(
                ArchivalUnit.project_id == project_id,
                ArchivalUnit.parent_id == parent_unit_id,
                ArchivalDocumentComponent.digital_object_id.in_(digital_ids),
            )
            .group_by(ArchivalDocumentComponent.digital_object_id)
        ).all()
    )

    result: list[DocumentOrganizationSourceRow] = []
    seen: set[str] = set()
    for _link, digital in digital_rows:
        if digital.id in seen:
            continue
        seen.add(digital.id)
        objects = texts.get(digital.id, [])
        title_text = ""
        for obj in objects:
            object_type = str(obj.current_object_type or "").strip().casefold()
            if object_type in _TITLE_TYPES and obj.current_text.strip():
                title_text = obj.current_text.strip().splitlines()[0]
                break
        if not title_text:
            for obj in objects:
                if obj.current_text.strip():
                    title_text = obj.current_text.strip().splitlines()[0]
                    break
        preview = " ".join(obj.current_text.strip() for obj in objects if obj.current_text.strip())
        result.append(
            DocumentOrganizationSourceRow(
                digital_object_id=digital.id,
                original_filename=digital.original_filename,
                media_type=digital.media_type,
                page_count=digital.page_count,
                relative_path=first_file.get(digital.id),
                preview_relative_path=first_preview.get(digital.id),
                suggested_title=_normalize_preview(title_text, limit=140)
                or _filename_title(digital.original_filename),
                text_preview=_normalize_preview(preview),
                organized_count=int(component_counts.get(digital.id, 0)),
            )
        )
    result.sort(key=lambda row: (natural_filename_key(row.original_filename), row.digital_object_id))
    return result


def _validate_component(
    digital: DigitalObject,
    component: DocumentComponentDraft,
) -> tuple[int | None, int | None]:
    start = component.page_start
    end = component.page_end
    if (start is None) != (end is None):
        raise ValueError("Para usar un rango de páginas hay que indicar inicio y fin")
    if start is not None:
        if start < 1 or end is None or end < start:
            raise ValueError("El rango de páginas es inválido")
        if digital.page_count is not None and end > digital.page_count:
            raise ValueError(
                f"{digital.original_filename} tiene {digital.page_count} página(s); el rango termina en {end}"
            )
        if digital.page_count is not None and start == 1 and end == digital.page_count:
            return None, None
    return start, end


def create_document_groups(
    session: Session,
    *,
    decisions: ProjectDecisions,
    project_id: str,
    parent_unit_id: str,
    document_level_key: str,
    groups: Iterable[DocumentGroupDraft],
    created_by: str,
) -> CreateDocumentsResult:
    parent = session.get(ArchivalUnit, parent_unit_id)
    if parent is None or parent.project_id != project_id:
        raise ValueError("La unidad seleccionada no existe en este proyecto")
    if document_level_key not in record_level_options(decisions, parent.level_key):
        raise ValueError("El tipo de Documento no está permitido debajo de la unidad seleccionada")

    drafts = list(groups)
    if not drafts:
        raise ValueError("No hay documentos provisionales para crear")
    actor = created_by.strip() or "local_user"
    created: list[CreatedDocumentRow] = []

    direct_digital_ids = set(
        session.scalars(
            select(DigitalObjectUnitLink.digital_object_id).where(
                DigitalObjectUnitLink.archival_unit_id == parent_unit_id
            )
        ).all()
    )

    for group in drafts:
        title = group.title.strip()
        if not title:
            raise ValueError("Cada documento provisional necesita un título")
        if not group.components:
            raise ValueError(f"{title}: el documento no contiene archivos")
        unit = create_archival_unit(
            session,
            decisions=decisions,
            project_id=project_id,
            parent_id=parent_unit_id,
            level_key=document_level_key,
            title=title,
            created_by=actor,
            note="Creado desde Organizar archivos en documentos.",
        )
        seen_components: set[tuple[str, int | None, int | None]] = set()
        normalized: list[tuple[DigitalObject, int | None, int | None]] = []
        for draft in group.components:
            if draft.digital_object_id not in direct_digital_ids:
                raise ValueError(
                    f"{title}: uno de los archivos ya no está vinculado directamente con la unidad de origen"
                )
            digital = session.get(DigitalObject, draft.digital_object_id)
            if digital is None or digital.project_id != project_id:
                raise ValueError(f"{title}: objeto digital inexistente")
            start, end = _validate_component(digital, draft)
            identity = (digital.id, start, end)
            if identity in seen_components:
                raise ValueError(f"{title}: el mismo archivo o rango aparece dos veces")
            seen_components.add(identity)
            normalized.append((digital, start, end))

        for position, (digital, start, end) in enumerate(normalized, start=1):
            relation_type = (
                "contains"
                if start is not None or end is not None
                else ("represents" if len(normalized) == 1 else "is_part_of")
            )
            link_existing_digital_object(
                session,
                project_id=project_id,
                archival_unit_id=unit.id,
                digital_object_id=digital.id,
                relation_type=relation_type,
                page_start=start,
                page_end=end,
                registered_by=actor,
            )
            session.add(
                ArchivalDocumentComponent(
                    id=new_id(),
                    archival_unit_id=unit.id,
                    digital_object_id=digital.id,
                    sequence_position=position,
                    page_start=start,
                    page_end=end,
                    created_by=actor,
                    updated_by=actor,
                )
            )
        session.flush()
        created.append(
            CreatedDocumentRow(
                archival_unit_id=unit.id,
                title=unit.title,
                component_count=len(normalized),
            )
        )
    return CreateDocumentsResult(created=tuple(created))
