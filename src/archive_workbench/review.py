from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import fitz
from PIL import Image, ImageDraw, ImageFont, ImageOps
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from archive_workbench.sources import PROCESSABLE_SOURCE_TYPES
from archive_workbench.db.models import (
    ArchivalUnit,
    DerivativeAsset,
    DigitalObject,
    DocumentPart,
    EditableObject,
    EditableObjectComment,
    EditableObjectTag,
    EditablePage,
    ExtractedObject,
    FileInstance,
    ExtractionPageSelection,
    PreprocessingRun,
    SourceRegistration,
)


@dataclass(slots=True)
class ReviewDocumentRow:
    source_key: str
    title: str
    page_count: int
    editable_pages: list[int]
    stale_pages: list[int]
    active_objects: int
    deleted_objects: int


@dataclass(slots=True)
class ReviewTagRow:
    tag_id: str
    tag: str
    tag_kind: str


@dataclass(slots=True)
class ReviewPartRow:
    part_id: str
    part_key: str
    title: str
    part_type: str
    page_sequence: list[int]
    status: str

@dataclass(slots=True)
class ReviewObjectRow:
    object_id: str
    page: int
    order_index: int
    object_type: str
    lifecycle_status: str
    revision_number: int
    text: str
    original_text: str | None
    geometry: list[dict[str, Any]]
    attributes: dict[str, Any]
    updated_by: str
    updated_at: datetime
    manually_added: bool
    review_status: str = "unreviewed"
    document_part_id: str | None = None
    document_part_key: str | None = None
    document_part_title: str | None = None
    tags: list[ReviewTagRow] = field(default_factory=list)
    comment_count: int = 0


@dataclass(slots=True)
class ReviewPageView:
    source_key: str
    title: str
    page: int
    page_count: int
    editable_status: str
    page_review_status: str
    page_review_note: str | None
    editable_page_id: str
    is_stale: bool
    preview_path: Path | None
    preview_width: int | None
    preview_height: int | None
    parts: list[ReviewPartRow]
    objects: list[ReviewObjectRow]


def _registration(
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



def _source_preview_fallback(
    session: Session,
    *,
    project_root: str | Path,
    digital: DigitalObject,
    page: int,
) -> tuple[Path | None, int | None, int | None]:
    """Crea una vista cacheada desde el original cuando no existe preview derivado.

    El archivo original permanece inmutable. La imagen se escribe únicamente bajo
    ``.cache/review_previews``, una ruta local ignorada por Git.
    """

    instances = session.scalars(
        select(FileInstance)
        .where(
            FileInstance.digital_object_id == digital.id,
            FileInstance.storage_root == "project",
        )
        .order_by(FileInstance.presence.desc(), FileInstance.relative_path)
    ).all()
    source = next(
        (
            Path(project_root) / item.relative_path
            for item in instances
            if (Path(project_root) / item.relative_path).is_file()
        ),
        None,
    )
    if source is None:
        return None, None, None

    cache = (
        Path(project_root)
        / ".cache"
        / "review_previews"
        / digital.id
        / f"page_{page:04d}.png"
    )
    try:
        if cache.is_file() and cache.stat().st_mtime_ns >= source.stat().st_mtime_ns:
            with Image.open(cache) as image:
                width, height = image.size
            return cache, width, height

        cache.parent.mkdir(parents=True, exist_ok=True)
        if digital.media_type == "pdf" or source.suffix.lower() == ".pdf":
            with fitz.open(source) as document:
                if page < 1 or page > len(document):
                    return None, None, None
                pixmap = document[page - 1].get_pixmap(
                    dpi=150,
                    colorspace=fitz.csRGB,
                    alpha=False,
                )
                pixmap.save(cache)
                return cache, pixmap.width, pixmap.height

        with Image.open(source) as image:
            frame_count = int(getattr(image, "n_frames", 1))
            if page < 1 or page > frame_count:
                return None, None, None
            image.seek(page - 1)
            rendered = ImageOps.exif_transpose(image).convert("RGB")
            rendered.thumbnail((1800, 2400), Image.Resampling.LANCZOS)
            rendered.save(cache, format="PNG")
            width, height = rendered.size
            return cache, width, height
    except (OSError, ValueError, RuntimeError, fitz.FileDataError):
        return None, None, None

def review_document_rows(session: Session) -> list[ReviewDocumentRow]:
    rows = session.execute(
        select(SourceRegistration, DigitalObject, ArchivalUnit)
        .join(DigitalObject, SourceRegistration.digital_object_id == DigitalObject.id)
        .join(ArchivalUnit, SourceRegistration.archival_unit_id == ArchivalUnit.id)
        .where(SourceRegistration.source_type.in_(PROCESSABLE_SOURCE_TYPES))
        .order_by(SourceRegistration.source_key)
    ).all()
    result: list[ReviewDocumentRow] = []
    for registration, digital, unit in rows:
        editable_pages = session.scalars(
            select(EditablePage)
            .where(EditablePage.digital_object_id == digital.id)
            .order_by(EditablePage.page_number)
        ).all()
        if not editable_pages:
            continue
        selections = {
            item.page_number: item.extraction_page_id
            for item in session.scalars(
                select(ExtractionPageSelection).where(
                    ExtractionPageSelection.digital_object_id == digital.id
                )
            ).all()
        }
        stale_pages = [
            item.page_number
            for item in editable_pages
            if selections.get(item.page_number) != item.source_extraction_page_id
        ]
        objects = session.scalars(
            select(EditableObject).where(EditableObject.digital_object_id == digital.id)
        ).all()
        result.append(
            ReviewDocumentRow(
                source_key=registration.source_key,
                title=unit.title,
                page_count=digital.page_count or max(item.page_number for item in editable_pages),
                editable_pages=[item.page_number for item in editable_pages],
                stale_pages=stale_pages,
                active_objects=sum(item.lifecycle_status == "active" for item in objects),
                deleted_objects=sum(item.lifecycle_status == "deleted" for item in objects),
            )
        )
    return result


def review_page_view(
    session: Session,
    *,
    project_root: str | Path,
    source_key: str,
    page: int,
    include_deleted: bool = False,
) -> ReviewPageView:
    _source, digital, unit = _registration(session, source_key)
    editable_page = session.scalar(
        select(EditablePage).where(
            EditablePage.digital_object_id == digital.id,
            EditablePage.page_number == page,
        )
    )
    if editable_page is None:
        raise ValueError(f"La página {page} de {source_key} no está inicializada para edición")

    selection = session.scalar(
        select(ExtractionPageSelection).where(
            ExtractionPageSelection.digital_object_id == digital.id,
            ExtractionPageSelection.page_number == page,
        )
    )
    is_stale = selection is None or selection.extraction_page_id != editable_page.source_extraction_page_id

    preprocessing = session.scalar(
        select(PreprocessingRun)
        .where(
            PreprocessingRun.digital_object_id == digital.id,
            PreprocessingRun.is_current.is_(True),
            PreprocessingRun.status.in_(["completed", "completed_with_warnings"]),
        )
        .order_by(PreprocessingRun.created_at.desc())
    )
    asset = None
    if preprocessing is not None:
        asset = session.scalar(
            select(DerivativeAsset).where(
                DerivativeAsset.preprocessing_run_id == preprocessing.id,
                DerivativeAsset.page_number == page,
                DerivativeAsset.kind == "preview",
            )
        )

    query = select(EditableObject).where(
        EditableObject.digital_object_id == digital.id,
        EditableObject.page_number == page,
    )
    if not include_deleted:
        query = query.where(EditableObject.lifecycle_status == "active")
    editable_objects = session.scalars(
        query.order_by(EditableObject.current_order_index, EditableObject.id)
    ).all()
    source_ids = [item.source_extracted_object_id for item in editable_objects if item.source_extracted_object_id]
    originals = {
        item.id: item.original_text
        for item in (
            session.scalars(select(ExtractedObject).where(ExtractedObject.id.in_(source_ids))).all()
            if source_ids
            else []
        )
    }
    object_ids = [item.id for item in editable_objects]
    tag_map: dict[str, list[ReviewTagRow]] = {item.id: [] for item in editable_objects}
    comment_counts: dict[str, int] = {item.id: 0 for item in editable_objects}
    if object_ids:
        for object_id, tag_id, tag, tag_kind in session.execute(
            select(
                EditableObjectTag.editable_object_id,
                EditableObjectTag.id,
                EditableObjectTag.tag,
                EditableObjectTag.tag_kind,
            )
            .where(EditableObjectTag.editable_object_id.in_(object_ids))
            .order_by(EditableObjectTag.tag_kind, EditableObjectTag.normalized_tag)
        ).all():
            tag_map.setdefault(object_id, []).append(
                ReviewTagRow(tag_id=tag_id, tag=tag, tag_kind=tag_kind)
            )
        for object_id, count in session.execute(
            select(
                EditableObjectComment.editable_object_id,
                func.count(EditableObjectComment.id),
            )
            .where(EditableObjectComment.editable_object_id.in_(object_ids))
            .group_by(EditableObjectComment.editable_object_id)
        ).all():
            comment_counts[object_id] = int(count)
    part_models = session.scalars(
        select(DocumentPart)
        .where(DocumentPart.digital_object_id == digital.id)
        .order_by(DocumentPart.page_start, DocumentPart.page_end, DocumentPart.part_key)
    ).all()
    parts = [
        ReviewPartRow(
            part_id=item.id,
            part_key=item.part_key,
            title=item.title,
            part_type=item.part_type,
            page_sequence=list(item.page_sequence_json or []),
            status=item.status,
        )
        for item in part_models
        if page in (item.page_sequence_json or list(range(item.page_start, item.page_end + 1)))
    ]
    parts_by_id = {item.id: item for item in part_models}

    objects = [
        ReviewObjectRow(
            object_id=item.id,
            page=item.page_number,
            order_index=item.current_order_index,
            object_type=item.current_object_type,
            lifecycle_status=item.lifecycle_status,
            revision_number=item.revision_number,
            text=item.current_text,
            original_text=originals.get(item.source_extracted_object_id or ""),
            geometry=item.current_geometry_json or [],
            attributes=item.current_attributes_json or {},
            updated_by=item.updated_by,
            updated_at=item.updated_at,
            manually_added=item.source_extracted_object_id is None,
            review_status=item.review_status,
            document_part_id=item.document_part_id,
            document_part_key=(
                parts_by_id[item.document_part_id].part_key
                if item.document_part_id in parts_by_id
                else None
            ),
            document_part_title=(
                parts_by_id[item.document_part_id].title
                if item.document_part_id in parts_by_id
                else None
            ),
            tags=tag_map.get(item.id, []),
            comment_count=comment_counts.get(item.id, 0),
        )
        for item in editable_objects
    ]
    preview_path = Path(project_root) / asset.relative_path if asset is not None else None
    preview_width = asset.width if asset is not None else None
    preview_height = asset.height if asset is not None else None
    if preview_path is not None and not preview_path.is_file():
        preview_path = None
        preview_width = None
        preview_height = None
    if preview_path is None:
        preview_path, preview_width, preview_height = _source_preview_fallback(
            session,
            project_root=project_root,
            digital=digital,
            page=page,
        )
    return ReviewPageView(
        source_key=source_key,
        title=unit.title,
        page=page,
        page_count=digital.page_count or page,
        editable_status=editable_page.status,
        page_review_status=editable_page.review_status,
        page_review_note=editable_page.review_note,
        editable_page_id=editable_page.id,
        is_stale=is_stale,
        preview_path=preview_path,
        preview_width=preview_width,
        preview_height=preview_height,
        parts=parts,
        objects=objects,
    )


def _normalized_polygons(
    geometry: list[dict[str, Any]], *, page: int
) -> list[list[tuple[float, float]]]:
    polygons: list[list[tuple[float, float]]] = []
    for item in geometry:
        if item.get("page") not in {None, page}:
            continue
        polygon = item.get("polygon") or []
        if len(polygon) < 4:
            continue
        coordinate_space = item.get("coordinate_space", "normalized")
        if coordinate_space != "normalized":
            continue
        try:
            points = [(float(point[0]), float(point[1])) for point in polygon]
        except (TypeError, ValueError, IndexError):
            continue
        if all(0 <= x <= 1 and 0 <= y <= 1 for x, y in points):
            polygons.append(points)
    return polygons


def render_review_overlay(
    image_path: str | Path,
    objects: list[ReviewObjectRow],
    *,
    page: int,
    selected_object_id: str | None = None,
    show_deleted: bool = False,
) -> Image.Image:
    """Dibuja cajas numeradas sin alterar el derivado almacenado."""
    with Image.open(image_path) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default()
    width, height = image.size
    for item in objects:
        if item.lifecycle_status == "deleted" and not show_deleted:
            continue
        polygons = _normalized_polygons(item.geometry, page=page)
        if not polygons:
            continue
        selected = item.object_id == selected_object_id
        if item.lifecycle_status == "deleted":
            outline = (115, 115, 115)
        elif selected:
            outline = (210, 45, 45)
        else:
            outline = (20, 120, 180)
        stroke = 5 if selected else 3
        for polygon in polygons:
            pixels = [(round(x * width), round(y * height)) for x, y in polygon]
            draw.line(pixels + [pixels[0]], fill=outline, width=stroke, joint="curve")
            xs = [point[0] for point in pixels]
            ys = [point[1] for point in pixels]
            label = str(item.order_index + 1)
            left, top = min(xs), min(ys)
            box = draw.textbbox((left, top), label, font=font, stroke_width=1)
            padding = 3
            draw.rectangle(
                (
                    box[0] - padding,
                    box[1] - padding,
                    box[2] + padding,
                    box[3] + padding,
                ),
                fill=outline,
            )
            draw.text((left, top), label, fill=(255, 255, 255), font=font, stroke_width=1)
    return image
