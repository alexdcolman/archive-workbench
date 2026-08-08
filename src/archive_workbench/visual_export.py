from __future__ import annotations

import hashlib
import json
import mimetypes
import re
import shutil
import tempfile
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from archive_workbench.db.models import (
    DerivativeAsset,
    DigitalObject,
    DocumentPart,
    EditableObject,
    EditablePage,
    ExtractedObject,
    ExtractionPage,
    ExtractionRegion,
    SourceRegistration,
)
from archive_workbench.version import __version__

VISUAL_PACKAGE_FORMAT = "visual_zip"
VISUAL_PACKAGE_SCHEMA_VERSION = "1.0"


@dataclass(slots=True, frozen=True)
class VisualExportOptions:
    include_pages: bool = True
    include_regions: bool = True
    include_figures: bool = True
    include_context: bool = True


@dataclass(slots=True)
class VisualPackageResult:
    page_count: int
    region_count: int
    figure_count: int
    context_object_count: int
    manifest: dict[str, Any]


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_project_file(project_root: Path, relative_path: str) -> Path:
    candidate = (project_root / relative_path).resolve()
    try:
        candidate.relative_to(project_root.resolve())
    except ValueError as exc:
        raise ValueError(f"La ruta registrada sale del proyecto: {relative_path}") from exc
    if not candidate.is_file():
        raise ValueError(f"Falta un archivo requerido para la exportación: {relative_path}")
    return candidate


def _verified_source_asset(project_root: Path, asset: DerivativeAsset) -> Path:
    path = _safe_project_file(project_root, asset.relative_path)
    digest = _sha256_path(path)
    if digest != asset.sha256:
        raise ValueError(
            "El derivado de página fue modificado después de registrarse: "
            f"{asset.relative_path}"
        )
    if path.stat().st_size != asset.byte_size:
        raise ValueError(
            "El tamaño del derivado de página ya no coincide con el registrado: "
            f"{asset.relative_path}"
        )
    return path


def _safe_component(value: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._")
    return clean or "item"


def _extension(path: Path, mime_type: str | None = None) -> str:
    suffix = path.suffix.lower()
    if suffix:
        return suffix
    guessed = mimetypes.guess_extension(mime_type or "")
    return guessed or ".bin"


def _jsonl_bytes(rows: Iterable[dict[str, Any]]) -> bytes:
    lines = [json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows]
    return (("\n".join(lines) + "\n") if lines else "").encode("utf-8")


def _record_map(records: list[dict[str, Any]]) -> tuple[dict[str, list[str]], dict[tuple[str, int], list[str]]]:
    by_object: dict[str, list[str]] = {}
    for record in records:
        record_id = str(record["record_id"])
        for object_id in record.get("object_ids") or []:
            by_object.setdefault(str(object_id), []).append(record_id)
    return by_object, {}


def _source_registrations(session: Session, *, project_id: str, digital_ids: set[str]) -> dict[str, SourceRegistration]:
    if not digital_ids:
        return {}
    rows = session.scalars(
        select(SourceRegistration)
        .where(
            SourceRegistration.project_id == project_id,
            SourceRegistration.digital_object_id.in_(digital_ids),
        )
        .order_by(SourceRegistration.registered_at.desc(), SourceRegistration.id.desc())
    ).all()
    result: dict[str, SourceRegistration] = {}
    for row in rows:
        if row.digital_object_id and row.digital_object_id not in result:
            result[row.digital_object_id] = row
    return result


def _geometry_bbox(geometry: list[dict[str, Any]], *, page: int, width: int, height: int) -> tuple[int, int, int, int]:
    points: list[tuple[float, float]] = []
    for item in geometry or []:
        if item.get("page") not in (None, page):
            continue
        if item.get("coordinate_space", "normalized") != "normalized":
            continue
        for raw in item.get("polygon") or []:
            if not isinstance(raw, (list, tuple)) or len(raw) < 2:
                continue
            try:
                x = float(raw[0])
                y = float(raw[1])
            except (TypeError, ValueError):
                continue
            points.append((x, y))
    if not points:
        raise ValueError("La figura no tiene una geometría normalizada utilizable")
    min_x = max(0.0, min(point[0] for point in points))
    min_y = max(0.0, min(point[1] for point in points))
    max_x = min(1.0, max(point[0] for point in points))
    max_y = min(1.0, max(point[1] for point in points))
    left = max(0, min(width - 1, int(min_x * width)))
    top = max(0, min(height - 1, int(min_y * height)))
    right = max(left + 1, min(width, int(max_x * width + 0.999999)))
    bottom = max(top + 1, min(height, int(max_y * height + 0.999999)))
    return left, top, right, bottom


def _select_context_text(current: str, original: str | None, policy: str) -> str:
    if policy == "original_only":
        return (original or "").strip()
    if policy == "corrected_only":
        return current.strip()
    return current.strip() or (original or "").strip()


def build_text_image_package(
    session: Session,
    *,
    project_root: Path,
    project_id: str,
    records: list[dict[str, Any]],
    profile_snapshot: dict[str, Any],
    corpus_state_sha256: str,
    destination: Path,
    options: VisualExportOptions,
) -> VisualPackageResult:
    """Materializa un ZIP trazable de texto, imágenes y contexto.

    Las páginas visuales se anclan a ``EditablePage.source_extraction_page_id`` y por
    lo tanto a la imagen exacta utilizada por la extracción que originó la capa
    editable. No consulta originales alternativos ni una corrida de preprocesamiento
    más reciente.
    """

    if not (options.include_pages or options.include_regions or options.include_figures):
        raise ValueError("Elegí al menos un tipo de imagen para incluir en el ZIP")

    record_by_object, _unused = _record_map(records)
    primary_object_ids = set(record_by_object)
    if not primary_object_ids:
        raise ValueError("El perfil no selecciona objetos textuales para exportar")

    primary_objects = session.scalars(
        select(EditableObject).where(EditableObject.id.in_(primary_object_ids))
    ).all()
    if len(primary_objects) != len(primary_object_ids):
        raise ValueError("Algún objeto textual exportado ya no existe")

    selected_page_keys = {(row.digital_object_id, row.page_number) for row in primary_objects}
    digital_ids = {row.digital_object_id for row in primary_objects}
    registrations = _source_registrations(session, project_id=project_id, digital_ids=digital_ids)
    digitals = {
        row.id: row
        for row in session.scalars(select(DigitalObject).where(DigitalObject.id.in_(digital_ids))).all()
    }

    editable_pages = session.scalars(
        select(EditablePage)
        .where(EditablePage.digital_object_id.in_(digital_ids))
        .order_by(EditablePage.digital_object_id, EditablePage.page_number)
    ).all()
    page_by_key = {(row.digital_object_id, row.page_number): row for row in editable_pages}
    for key in selected_page_keys:
        if key not in page_by_key:
            raise ValueError(f"No existe la página editable requerida: {key[0]} página {key[1]}")

    extraction_page_ids = {page_by_key[key].source_extraction_page_id for key in selected_page_keys}
    extraction_pages = {
        row.id: row
        for row in session.scalars(
            select(ExtractionPage).where(ExtractionPage.id.in_(extraction_page_ids))
        ).all()
    }
    if len(extraction_pages) != len(extraction_page_ids):
        raise ValueError("Falta una página de extracción requerida por la exportación visual")

    source_asset_ids = {
        page.source_asset_id for page in extraction_pages.values() if page.source_asset_id
    }
    assets = {
        row.id: row
        for row in session.scalars(
            select(DerivativeAsset).where(DerivativeAsset.id.in_(source_asset_ids))
        ).all()
    }
    if len(assets) != len(source_asset_ids):
        raise ValueError("Falta un derivado visual requerido por la extracción seleccionada")

    primary_records_by_page: dict[tuple[str, int], set[str]] = {}
    for obj in primary_objects:
        primary_records_by_page.setdefault((obj.digital_object_id, obj.page_number), set()).update(
            record_by_object.get(obj.id, [])
        )

    allowed_page_statuses = set(profile_snapshot.get("include_page_review_statuses") or [])
    allowed_object_statuses = set(profile_snapshot.get("include_review_statuses") or [])
    context_objects: list[dict[str, Any]] = []
    document_contexts: list[dict[str, Any]] = []
    page_contexts: list[dict[str, Any]] = []
    context_ids_by_page: dict[tuple[str, int], str] = {}
    document_context_ids: dict[str, str] = {}

    if options.include_context:
        all_context_rows = session.execute(
            select(EditableObject, EditablePage, ExtractedObject, DocumentPart)
            .join(EditablePage, EditablePage.id == EditableObject.editable_page_id)
            .outerjoin(ExtractedObject, ExtractedObject.id == EditableObject.source_extracted_object_id)
            .outerjoin(DocumentPart, DocumentPart.id == EditableObject.document_part_id)
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
        by_page: dict[tuple[str, int], list[dict[str, Any]]] = {}
        for editable, page, original, part in all_context_rows:
            if allowed_page_statuses and page.review_status not in allowed_page_statuses:
                continue
            text = _select_context_text(
                editable.current_text,
                original.original_text if original is not None else None,
                str(profile_snapshot.get("text_policy") or "corrected_fallback_original"),
            )
            if not text:
                continue
            item = {
                "object_id": editable.id,
                "digital_object_id": editable.digital_object_id,
                "source_key": (
                    registrations[editable.digital_object_id].source_key
                    if editable.digital_object_id in registrations
                    else None
                ),
                "page_number": editable.page_number,
                "order_index": editable.current_order_index,
                "object_type": editable.current_object_type,
                "object_review_status": editable.review_status,
                "page_review_status": page.review_status,
                "document_part_id": part.id if part else None,
                "document_part_key": part.part_key if part else None,
                "document_part_title": part.title if part else None,
                "text": text,
                "included_in_primary_export": editable.id in primary_object_ids,
                "primary_record_ids": sorted(record_by_object.get(editable.id, [])),
            }
            context_objects.append(item)
            by_page.setdefault((editable.digital_object_id, editable.page_number), []).append(item)

        for key, members in sorted(by_page.items()):
            digital_id, page_number = key
            context_id = f"page:{digital_id}:{page_number}"
            context_ids_by_page[key] = context_id
            page_contexts.append(
                {
                    "page_context_id": context_id,
                    "digital_object_id": digital_id,
                    "source_key": registrations[digital_id].source_key if digital_id in registrations else None,
                    "page_number": page_number,
                    "page_review_status": page_by_key[key].review_status if key in page_by_key else None,
                    "object_ids": [item["object_id"] for item in members],
                    "primary_object_ids": [
                        item["object_id"] for item in members if item["included_in_primary_export"]
                    ],
                    "text": "\n\n".join(item["text"] for item in members),
                }
            )

        for digital_id in sorted(digital_ids):
            context_id = f"document:{digital_id}"
            document_context_ids[digital_id] = context_id
            pages = [row for row in page_contexts if row["digital_object_id"] == digital_id]
            digital = digitals.get(digital_id)
            registration = registrations.get(digital_id)
            document_contexts.append(
                {
                    "document_context_id": context_id,
                    "digital_object_id": digital_id,
                    "source_key": registration.source_key if registration else None,
                    "original_filename": digital.original_filename if digital else None,
                    "original_sha256": digital.sha256 if digital else None,
                    "page_context_ids": [row["page_context_id"] for row in pages],
                    "text": "\n\n".join(
                        f"[Página {row['page_number']}]\n{row['text']}" for row in pages
                    ),
                }
            )

    visual_assets: list[dict[str, Any]] = []
    page_count = 0
    region_count = 0
    figure_count = 0

    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="archive_workbench_visual_export_") as temp_name:
        temp_root = Path(temp_name)
        (temp_root / "text").mkdir(parents=True, exist_ok=True)
        (temp_root / "context").mkdir(parents=True, exist_ok=True)
        (temp_root / "images" / "pages").mkdir(parents=True, exist_ok=True)
        (temp_root / "images" / "regions").mkdir(parents=True, exist_ok=True)
        (temp_root / "images" / "figures").mkdir(parents=True, exist_ok=True)

        records_bytes = _jsonl_bytes(records)
        (temp_root / "text" / "records.jsonl").write_bytes(records_bytes)
        context_objects_bytes = _jsonl_bytes(context_objects)
        page_contexts_bytes = _jsonl_bytes(page_contexts)
        document_contexts_bytes = _jsonl_bytes(document_contexts)
        (temp_root / "context" / "objects.jsonl").write_bytes(context_objects_bytes)
        (temp_root / "context" / "pages.jsonl").write_bytes(page_contexts_bytes)
        (temp_root / "context" / "documents.jsonl").write_bytes(document_contexts_bytes)

        for digital_id, page_number in sorted(selected_page_keys):
            editable_page = page_by_key[(digital_id, page_number)]
            extraction_page = extraction_pages[editable_page.source_extraction_page_id]
            if not extraction_page.source_asset_id:
                raise ValueError(
                    f"La página {page_number} no conserva el derivado visual usado por su extracción"
                )
            source_asset = assets[extraction_page.source_asset_id]
            source_path = _verified_source_asset(project_root, source_asset)
            registration = registrations.get(digital_id)
            digital = digitals.get(digital_id)
            common = {
                "digital_object_id": digital_id,
                "source_key": registration.source_key if registration else None,
                "source_registration_id": registration.id if registration else None,
                "source_type": registration.source_type if registration else None,
                "archival_unit_id": registration.archival_unit_id if registration else None,
                "original_filename": digital.original_filename if digital else None,
                "original_sha256": digital.sha256 if digital else None,
                "page_number": page_number,
                "editable_page_id": editable_page.id,
                "page_review_status": editable_page.review_status,
                "extraction_run_id": extraction_page.extraction_run_id,
                "extraction_page_id": extraction_page.id,
                "source_asset_id": source_asset.id,
                "source_asset_sha256": source_asset.sha256,
                "source_asset_relative_path": source_asset.relative_path,
                "primary_record_ids": sorted(primary_records_by_page.get((digital_id, page_number), set())),
                "page_context_id": context_ids_by_page.get((digital_id, page_number)),
                "document_context_id": document_context_ids.get(digital_id),
            }

            if options.include_pages:
                relative = Path("images") / "pages" / f"{digital_id}_p{page_number:04d}{_extension(source_path, source_asset.mime_type)}"
                target = temp_root / relative
                shutil.copy2(source_path, target)
                visual_assets.append(
                    {
                        "asset_id": f"page:{digital_id}:{page_number}",
                        "kind": "page",
                        "path": relative.as_posix(),
                        "sha256": _sha256_path(target),
                        "byte_size": target.stat().st_size,
                        "mime_type": source_asset.mime_type,
                        "width": source_asset.width,
                        "height": source_asset.height,
                        **common,
                    }
                )
                page_count += 1

            if options.include_regions:
                regions = session.scalars(
                    select(ExtractionRegion)
                    .where(
                        ExtractionRegion.extraction_run_id == editable_page.source_extraction_run_id,
                        ExtractionRegion.page_number == page_number,
                    )
                    .order_by(ExtractionRegion.reading_order, ExtractionRegion.region_key)
                ).all()
                for region in regions:
                    crop_source = _safe_project_file(project_root, region.crop_path)
                    relative = Path("images") / "regions" / (
                    f"{_safe_component(digital_id)}_p{page_number:04d}_"
                    f"{_safe_component(region.region_key)}{_extension(crop_source)}"
                )
                    target = temp_root / relative
                    shutil.copy2(crop_source, target)
                    with Image.open(target) as image:
                        width, height = image.size
                        mime_type = Image.MIME.get(image.format) or mimetypes.guess_type(target.name)[0]
                    visual_assets.append(
                        {
                            "asset_id": f"region:{region.id}",
                            "kind": "region",
                            "path": relative.as_posix(),
                            "sha256": _sha256_path(target),
                            "byte_size": target.stat().st_size,
                            "mime_type": mime_type,
                            "width": width,
                            "height": height,
                            "region_id": region.id,
                            "region_key": region.region_key,
                            "label": region.label,
                            "mode": region.mode,
                            "object_type": region.object_type,
                            "reading_order": region.reading_order,
                            "bbox": region.bbox_json,
                            "registered_crop_path": region.crop_path,
                            **common,
                        }
                    )
                    region_count += 1

            if options.include_figures:
                figure_query = select(EditableObject).where(
                    EditableObject.digital_object_id == digital_id,
                    EditableObject.page_number == page_number,
                    EditableObject.lifecycle_status == "active",
                    EditableObject.current_object_type == "figure",
                )
                if allowed_object_statuses:
                    figure_query = figure_query.where(
                        EditableObject.review_status.in_(allowed_object_statuses)
                    )
                figures = session.scalars(
                    figure_query.order_by(EditableObject.current_order_index, EditableObject.id)
                ).all()
                if figures:
                    with Image.open(source_path) as source_image:
                        source_image.load()
                        width, height = source_image.size
                        for figure in figures:
                            bbox = _geometry_bbox(
                                figure.current_geometry_json or [],
                                page=page_number,
                                width=width,
                                height=height,
                            )
                            crop = source_image.crop(bbox)
                            relative = Path("images") / "figures" / f"{digital_id}_p{page_number:04d}_{figure.id}.png"
                            target = temp_root / relative
                            crop.save(target, format="PNG")
                            visual_assets.append(
                                {
                                    "asset_id": f"figure:{figure.id}",
                                    "kind": "figure",
                                    "path": relative.as_posix(),
                                    "sha256": _sha256_path(target),
                                    "byte_size": target.stat().st_size,
                                    "mime_type": "image/png",
                                    "width": crop.width,
                                    "height": crop.height,
                                    "editable_object_id": figure.id,
                                    "object_review_status": figure.review_status,
                                    "order_index": figure.current_order_index,
                                    "geometry": figure.current_geometry_json or [],
                                    "pixel_bbox": list(bbox),
                                    **common,
                                }
                            )
                            figure_count += 1

        manifest = {
            "schema_version": VISUAL_PACKAGE_SCHEMA_VERSION,
            "package_type": "archive_workbench_text_and_images",
            "archive_workbench_version": __version__,
            "project_id": project_id,
            "profile": profile_snapshot,
            "corpus_state_sha256": corpus_state_sha256,
            "options": asdict(options),
            "text": {
                "path": "text/records.jsonl",
                "record_count": len(records),
                "character_count": sum(len(str(row.get("texto") or "")) for row in records),
                "sha256": hashlib.sha256(records_bytes).hexdigest(),
            },
            "context": {
                "objects_path": "context/objects.jsonl",
                "objects_sha256": hashlib.sha256(context_objects_bytes).hexdigest(),
                "object_count": len(context_objects),
                "pages_path": "context/pages.jsonl",
                "pages_sha256": hashlib.sha256(page_contexts_bytes).hexdigest(),
                "page_count": len(page_contexts),
                "documents_path": "context/documents.jsonl",
                "documents_sha256": hashlib.sha256(document_contexts_bytes).hexdigest(),
                "document_count": len(document_contexts),
            },
            "assets": visual_assets,
            "asset_counts": {
                "pages": page_count,
                "regions": region_count,
                "figures": figure_count,
            },
        }
        manifest_path = temp_root / "manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        temporary_zip = destination.with_name(destination.name + ".tmp")
        try:
            with zipfile.ZipFile(temporary_zip, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for path in sorted(temp_root.rglob("*")):
                    if path.is_file():
                        archive.write(path, path.relative_to(temp_root).as_posix())
            temporary_zip.replace(destination)
        finally:
            temporary_zip.unlink(missing_ok=True)

    return VisualPackageResult(
        page_count=page_count,
        region_count=region_count,
        figure_count=figure_count,
        context_object_count=len(context_objects),
        manifest=manifest,
    )
