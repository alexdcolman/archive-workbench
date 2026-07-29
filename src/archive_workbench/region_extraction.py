from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Callable
from uuid import NAMESPACE_URL

import yaml
from PIL import Image, ImageDraw, ImageFont
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from archive_workbench.sources import PROCESSABLE_SOURCE_TYPES
from archive_workbench.contracts.decisions import ProjectDecisions
from archive_workbench.contracts.extraction import (
    ExtractedObjectRecord,
    PageGeometry,
)
from archive_workbench.contracts.regions import (
    NormalizedRegionBox,
    RegionDefinition,
    RegionExportRecord,
    RegionExtractionManifest,
    RegionTemplate,
)
from archive_workbench.db.models import (
    ArchivalUnit,
    DerivativeAsset,
    DigitalObject,
    ExtractionPage,
    ExtractionRegion,
    ExtractionRun,
    SourceRegistration,
)
from archive_workbench.domain.enums import ExtractionStatus
from archive_workbench.extraction import (
    ExtractionSummary,
    _apply_page_selections,
    _current_assets,
    _image_records,
    _paragraph_records,
    _persist_objects,
    _relative,
    _tesseract_version,
)
from archive_workbench.identity import new_id, sha256_file, sha256_json, stable_id
from archive_workbench.io.jsonl import write_models_atomic
from archive_workbench.tesseract_engine import (
    TesseractLine,
    TesseractPageResult,
    prepare_image_variant,
    run_tesseract_page,
    text_quality_metrics,
    write_tesseract_raw,
)


TesseractRunner = Callable[..., TesseractPageResult]


@dataclass(slots=True)
class RegionRenderResult:
    page: int
    path: str


@dataclass(slots=True)
class RegionStatusRow:
    source_key: str
    run_id: str
    profile_key: str
    page: int
    region_key: str
    label: str
    mode: str
    object_type: str
    status: str
    objects: int
    characters: int
    warning: str | None


def load_region_template(path: str | Path) -> RegionTemplate:
    source = Path(path)
    try:
        payload = yaml.safe_load(source.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"No existe la plantilla regional: {source}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"La plantilla regional debe ser un objeto YAML: {source}")
    return RegionTemplate.model_validate(payload)


def validate_region_template(
    template: RegionTemplate, decisions: ProjectDecisions
) -> RegionTemplate:
    allowed_types = {item.key for item in decisions.object_types}
    invalid = sorted({item.object_type for item in template.regions} - allowed_types)
    if invalid:
        raise ValueError(
            "Tipos de objeto regionales no definidos en decisions.yaml: "
            + ", ".join(invalid)
        )
    return template


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
    return row


def _asset_for_page(assets: list[DerivativeAsset], page: int) -> DerivativeAsset:
    for asset in assets:
        if asset.page_number == page:
            return asset
    raise ValueError(f"No existe derivado para la página {page}")


def _crop_pixels(box: NormalizedRegionBox, width: int, height: int) -> tuple[int, int, int, int]:
    left = max(0, min(width - 1, round(box.x0 * width)))
    top = max(0, min(height - 1, round(box.y0 * height)))
    right = max(left + 1, min(width, round(box.x1 * width)))
    bottom = max(top + 1, min(height, round(box.y1 * height)))
    return left, top, right, bottom


def render_region_template(
    session: Session,
    *,
    project_root: str | Path,
    template: RegionTemplate,
) -> list[RegionRenderResult]:
    root = Path(project_root)
    _registration, digital, _unit = _registration_for_source(session, template.source_key)
    _preprocessing, _ocr_assets, preview_assets = _current_assets(session, digital.id)
    pages = sorted({item.page for item in template.regions})
    output: list[RegionRenderResult] = []
    palette = {
        "ocr": (220, 40, 40),
        "manual": (35, 90, 210),
    }
    for page in pages:
        asset = _asset_for_page(preview_assets, page)
        source = root / asset.relative_path
        if sha256_file(source) != asset.sha256:
            raise RuntimeError(f"el derivado de vista fue modificado: {asset.relative_path}")
        with Image.open(source).convert("RGB") as image:
            draw = ImageDraw.Draw(image)
            font = ImageFont.load_default()
            for region in sorted(
                (item for item in template.regions if item.page == page),
                key=lambda item: item.reading_order,
            ):
                left, top, right, bottom = _crop_pixels(region.bbox, image.width, image.height)
                color = palette[region.mode]
                draw.rectangle((left, top, right, bottom), outline=color, width=4)
                label = f"{region.reading_order}. {region.region_key} [{region.mode}]"
                text_box = draw.textbbox((left, top), label, font=font)
                box_width = text_box[2] - text_box[0] + 8
                box_height = text_box[3] - text_box[1] + 6
                label_top = max(0, top - box_height)
                draw.rectangle(
                    (left, label_top, min(image.width, left + box_width), top),
                    fill=color,
                )
                draw.text((left + 4, label_top + 3), label, fill="white", font=font)
            destination = (
                root
                / "region_previews"
                / template.source_key
                / f"{template.template_key}_page_{page:04d}.png"
            )
            destination.parent.mkdir(parents=True, exist_ok=True)
            image.save(destination, format="PNG")
        output.append(RegionRenderResult(page=page, path=_relative(destination, root)))
    return output


def _region_geometry(
    box: NormalizedRegionBox,
    *,
    page: int,
    line: TesseractLine | None = None,
    crop_width: int | None = None,
    crop_height: int | None = None,
) -> PageGeometry:
    if line is None:
        polygon = box.polygon()
    else:
        assert crop_width and crop_height
        width = box.x1 - box.x0
        height = box.y1 - box.y0
        x0 = box.x0 + (line.left / crop_width) * width
        y0 = box.y0 + (line.top / crop_height) * height
        x1 = box.x0 + (line.right / crop_width) * width
        y1 = box.y0 + (line.bottom / crop_height) * height
        polygon = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    return PageGeometry(page=page, polygon=polygon)


def _normalize_region_result(
    result: TesseractPageResult,
    *,
    region: RegionDefinition,
    digital_object_id: str,
    extraction_run_id: str,
    template_key: str,
    order_start: int,
    crop_path: str,
) -> list[ExtractedObjectRecord]:
    assert region.ocr is not None
    if region.ocr.object_granularity == "line":
        groups: list[list[TesseractLine]] = [[line] for line in result.lines]
    else:
        grouped: dict[tuple[int, int], list[TesseractLine]] = {}
        for line in result.lines:
            grouped.setdefault((line.block_num, line.paragraph_num), []).append(line)
        groups = list(grouped.values())

    if not groups:
        return [
            ExtractedObjectRecord(
                object_id=stable_id(
                    NAMESPACE_URL,
                    "archive-workbench-region",
                    digital_object_id,
                    result.page_number,
                    template_key,
                    region.region_key,
                    "empty",
                ),
                digital_object_id=digital_object_id,
                extraction_run_id=extraction_run_id,
                order_index=order_start,
                object_type=region.object_type,
                original_text="",
                geometry=[_region_geometry(region.bbox, page=result.page_number)],
                source_label="region_ocr_empty",
                hidden_by_default=region.hidden_by_default,
                attributes={
                    "template_key": template_key,
                    "region_key": region.region_key,
                    "region_label": region.label,
                    "region_mode": region.mode,
                    "crop_path": crop_path,
                    "manual_correction_required": True,
                    "ocr_empty": True,
                },
            )
        ]

    records: list[ExtractedObjectRecord] = []
    for index, lines in enumerate(groups):
        confidences = [line.confidence for line in lines if line.confidence is not None]
        confidence = mean(confidences) / 100.0 if confidences else None
        left = min(line.left for line in lines)
        top = min(line.top for line in lines)
        right = max(line.right for line in lines)
        bottom = max(line.bottom for line in lines)
        aggregate = TesseractLine(
            block_num=lines[0].block_num,
            paragraph_num=lines[0].paragraph_num,
            line_num=lines[0].line_num,
            text="\n".join(line.text for line in lines),
            left=left,
            top=top,
            right=right,
            bottom=bottom,
            confidence=mean(confidences) if confidences else None,
            word_count=sum(line.word_count for line in lines),
        )
        object_id = stable_id(
            NAMESPACE_URL,
            "archive-workbench-region",
            digital_object_id,
            result.page_number,
            template_key,
            region.region_key,
            index,
            aggregate.text,
        )
        records.append(
            ExtractedObjectRecord(
                object_id=object_id,
                digital_object_id=digital_object_id,
                extraction_run_id=extraction_run_id,
                order_index=order_start + index,
                object_type=region.object_type,
                original_text=aggregate.text,
                geometry=[
                    _region_geometry(
                        region.bbox,
                        page=result.page_number,
                        line=aggregate,
                        crop_width=result.width,
                        crop_height=result.height,
                    )
                ],
                source_label="region_tesseract",
                confidence=confidence,
                hidden_by_default=region.hidden_by_default,
                attributes={
                    "template_key": template_key,
                    "region_key": region.region_key,
                    "region_label": region.label,
                    "region_mode": region.mode,
                    "crop_path": crop_path,
                    "psm": region.ocr.psm,
                    "image_variant": region.ocr.image_variant,
                    "granularity": region.ocr.object_granularity,
                    "line_count": len(lines),
                    "line_texts": [line.text for line in lines],
                    "manual_correction_required": False,
                },
            )
        )
    return records


def _manual_region_object(
    *,
    region: RegionDefinition,
    digital_object_id: str,
    extraction_run_id: str,
    template_key: str,
    crop_path: str,
    order_index: int,
) -> ExtractedObjectRecord:
    return ExtractedObjectRecord(
        object_id=stable_id(
            NAMESPACE_URL,
            "archive-workbench-region",
            digital_object_id,
            region.page,
            template_key,
            region.region_key,
        ),
        digital_object_id=digital_object_id,
        extraction_run_id=extraction_run_id,
        order_index=order_index,
        object_type=region.object_type,
        original_text=region.initial_text,
        geometry=[_region_geometry(region.bbox, page=region.page)],
        source_label="manual_region",
        hidden_by_default=region.hidden_by_default,
        attributes={
            "template_key": template_key,
            "region_key": region.region_key,
            "region_label": region.label,
            "region_mode": region.mode,
            "crop_path": crop_path,
            "manual_transcription_required": not bool(region.initial_text.strip()),
            "note": region.note,
        },
    )


def extract_regions(
    session: Session,
    *,
    project_root: str | Path,
    decisions: ProjectDecisions,
    template: RegionTemplate,
    created_by: str = "local_user",
    selection_policy: str = "replace",
    force: bool = False,
    runner: TesseractRunner = run_tesseract_page,
) -> ExtractionSummary:
    root = Path(project_root)
    validate_region_template(template, decisions)
    if selection_policy not in {"never", "if_unselected", "replace"}:
        raise ValueError(f"Política de selección inválida: {selection_policy}")
    registration, digital, _unit = _registration_for_source(session, template.source_key)
    preprocessing, ocr_assets, preview_assets = _current_assets(session, digital.id)
    if preprocessing.source_sha256 != digital.sha256:
        raise RuntimeError("el preprocesamiento vigente no corresponde al SHA-256 actual")

    requested_pages = sorted({item.page for item in template.regions})
    available_pages = {asset.page_number for asset in ocr_assets}
    missing_pages = set(requested_pages) - available_pages
    if missing_pages:
        raise ValueError(
            "La plantilla solicita páginas inexistentes: "
            + ", ".join(map(str, sorted(missing_pages)))
        )

    options = {
        "template": template.model_dump(mode="json"),
        "preprocessing_run_id": preprocessing.id,
        "pages": requested_pages,
    }
    options_hash = sha256_json(options)
    equivalent = session.scalar(
        select(ExtractionRun)
        .where(
            ExtractionRun.digital_object_id == digital.id,
            ExtractionRun.source_sha256 == digital.sha256,
            ExtractionRun.options_hash == options_hash,
            ExtractionRun.status.in_(["completed", "completed_with_warnings"]),
        )
        .order_by(ExtractionRun.created_at.desc())
    )
    summary = ExtractionSummary(objects_seen=1)
    if equivalent is not None and not force:
        if selection_policy != "never":
            _apply_page_selections(
                session,
                run=equivalent,
                selected_by=created_by,
                policy=selection_policy,
                note=f"Plantilla regional {template.template_key} reutilizada",
            )
        summary.runs_reused = 1
        return summary

    run_id = new_id()
    output_dir = root / "extraction" / digital.id / run_id
    raw_dir = output_dir / "raw"
    crop_dir = output_dir / "regions"
    output_dir.mkdir(parents=True, exist_ok=False)
    run = ExtractionRun(
        id=run_id,
        digital_object_id=digital.id,
        preprocessing_run_id=preprocessing.id,
        profile_key=template.profile_key,
        engine="tesseract_regions",
        source_sha256=digital.sha256,
        options_json=options,
        options_hash=options_hash,
        status=ExtractionStatus.RUNNING.value,
        is_current=False,
        output_root=_relative(output_dir, root),
        raw_pages_path=_relative(raw_dir, root),
        created_by=created_by,
    )
    session.add(run)
    session.flush()

    try:
        all_objects: list[ExtractedObjectRecord] = []
        region_exports: list[RegionExportRecord] = []
        warnings: list[str] = []
        page_objects: dict[int, list[ExtractedObjectRecord]] = {page: [] for page in requested_pages}
        page_source_assets: dict[int, DerivativeAsset] = {}
        quality_scores: list[float] = []
        order_index = 0

        for page in requested_pages:
            asset = _asset_for_page(ocr_assets, page)
            page_source_assets[page] = asset
            source = root / asset.relative_path
            if not source.is_file():
                raise RuntimeError(f"falta el derivado OCR {asset.relative_path}")
            if sha256_file(source) != asset.sha256:
                raise RuntimeError(f"el derivado OCR fue modificado: {asset.relative_path}")

            with Image.open(source) as full_image:
                full_image.load()
                for region in sorted(
                    (item for item in template.regions if item.page == page),
                    key=lambda item: item.reading_order,
                ):
                    left, top, right, bottom = _crop_pixels(
                        region.bbox, full_image.width, full_image.height
                    )
                    region_root = crop_dir / f"page_{page:04d}" / region.region_key
                    raw_crop = region_root / "crop_original.png"
                    raw_crop.parent.mkdir(parents=True, exist_ok=True)
                    full_image.crop((left, top, right, bottom)).save(raw_crop, format="PNG")
                    crop_relative = _relative(raw_crop, root)
                    warning: str | None = None
                    raw_json_path: str | None = None
                    raw_tsv_path: str | None = None
                    raw_text_path: str | None = None

                    if region.mode == "manual":
                        objects = [
                            _manual_region_object(
                                region=region,
                                digital_object_id=digital.id,
                                extraction_run_id=run_id,
                                template_key=template.template_key,
                                crop_path=crop_relative,
                                order_index=order_index,
                            )
                        ]
                        warning = f"Región '{region.label}': requiere transcripción manual"
                        warnings.append(warning)
                        status = ExtractionStatus.COMPLETED_WITH_WARNINGS.value
                    else:
                        assert region.ocr is not None
                        variant_path = region_root / f"input_{region.ocr.image_variant}.png"
                        prepare_image_variant(raw_crop, variant_path, region.ocr.image_variant)
                        result = runner(
                            variant_path,
                            page_number=page,
                            tesseract_command=template.tesseract_command,
                            languages=region.ocr.languages,
                            psm=region.ocr.psm,
                            image_variant=region.ocr.image_variant,
                            timeout_seconds=template.timeout_seconds,
                        )
                        region_raw_dir = raw_dir / f"page_{page:04d}" / region.region_key
                        json_path, tsv_path, text_path = write_tesseract_raw(
                            result, region_raw_dir
                        )
                        raw_json_path = _relative(json_path, root)
                        raw_tsv_path = _relative(tsv_path, root)
                        raw_text_path = _relative(text_path, root)
                        objects = _normalize_region_result(
                            result,
                            region=region,
                            digital_object_id=digital.id,
                            extraction_run_id=run_id,
                            template_key=template.template_key,
                            order_start=order_index,
                            crop_path=crop_relative,
                        )
                        metrics = text_quality_metrics(result.full_text, result.lines)
                        quality_scores.append(float(metrics["heuristic_score"]))
                        if int(metrics["character_count"]) < region.ocr.minimum_characters_warning:
                            warning = (
                                f"Región '{region.label}': solo "
                                f"{int(metrics['character_count'])} caracteres reconocidos"
                            )
                            warnings.append(warning)
                        status = (
                            ExtractionStatus.COMPLETED_WITH_WARNINGS.value
                            if warning
                            else ExtractionStatus.COMPLETED.value
                        )

                    order_index += len(objects)
                    all_objects.extend(objects)
                    page_objects[page].extend(objects)
                    characters = sum(len(item.original_text) for item in objects)
                    region_row = ExtractionRegion(
                        id=new_id(),
                        extraction_run_id=run_id,
                        page_number=page,
                        region_key=region.region_key,
                        label=region.label,
                        mode=region.mode,
                        object_type=region.object_type,
                        reading_order=region.reading_order,
                        bbox_json=region.bbox.model_dump(mode="json"),
                        profile_json=(
                            region.ocr.model_dump(mode="json") if region.ocr else None
                        ),
                        crop_path=crop_relative,
                        raw_json_path=raw_json_path,
                        raw_tsv_path=raw_tsv_path,
                        raw_text_path=raw_text_path,
                        object_count=len(objects),
                        character_count=characters,
                        status=status,
                        warning_text=warning,
                    )
                    session.add(region_row)
                    region_exports.append(
                        RegionExportRecord(
                            extraction_run_id=run_id,
                            digital_object_id=digital.id,
                            source_key=template.source_key,
                            template_key=template.template_key,
                            region_key=region.region_key,
                            label=region.label,
                            page=page,
                            reading_order=region.reading_order,
                            mode=region.mode,
                            object_type=region.object_type,
                            bbox=region.bbox,
                            crop_path=crop_relative,
                            raw_json_path=raw_json_path,
                            raw_tsv_path=raw_tsv_path,
                            raw_text_path=raw_text_path,
                            object_count=len(objects),
                            character_count=characters,
                            status=status,
                            warning=warning,
                            note=region.note,
                        )
                    )

        for page in requested_pages:
            objects = page_objects[page]
            page_warnings = [
                item.warning
                for item in region_exports
                if item.page == page and item.warning
            ]
            session.add(
                ExtractionPage(
                    id=new_id(),
                    extraction_run_id=run_id,
                    page_number=page,
                    source_asset_id=page_source_assets[page].id,
                    raw_json_path=None,
                    object_count=len(objects),
                    character_count=sum(len(item.original_text) for item in objects),
                    status=(
                        ExtractionStatus.COMPLETED_WITH_WARNINGS.value
                        if page_warnings
                        else ExtractionStatus.COMPLETED.value
                    ),
                    warning_text="; ".join(page_warnings) if page_warnings else None,
                )
            )

        paragraphs = _paragraph_records(all_objects)
        selected_previews = [
            asset for asset in preview_assets if asset.page_number in requested_pages
        ]
        images = _image_records(selected_previews, extraction_run_id=run_id)
        objects_path = output_dir / decisions.jsonl.objects_filename
        paragraphs_path = output_dir / decisions.jsonl.paragraphs_filename
        images_path = output_dir / decisions.jsonl.images_filename
        regions_path = output_dir / "regions.jsonl"
        manifest_path = output_dir / decisions.jsonl.manifest_filename
        write_models_atomic(objects_path, all_objects)
        write_models_atomic(paragraphs_path, paragraphs)
        write_models_atomic(images_path, images)
        write_models_atomic(regions_path, region_exports)
        _persist_objects(session, all_objects)

        now = datetime.now(timezone.utc)
        status = (
            ExtractionStatus.COMPLETED_WITH_WARNINGS
            if warnings
            else ExtractionStatus.COMPLETED
        )
        engine_version = _tesseract_version(template.tesseract_command)
        character_count = sum(len(item.original_text) for item in all_objects)
        manifest = RegionExtractionManifest(
            run_id=run_id,
            digital_object_id=digital.id,
            preprocessing_run_id=preprocessing.id,
            source_key=registration.source_key,
            source_sha256=digital.sha256,
            template=template,
            engine_version=engine_version,
            options_hash=options_hash,
            created_by=created_by,
            created_at=run.created_at.isoformat(),
            completed_at=now.isoformat(),
            status=status.value,
            warnings=warnings,
            pages_processed=requested_pages,
            object_count=len(all_objects),
            paragraph_count=len(paragraphs),
            character_count=character_count,
            output_root=_relative(output_dir, root),
            objects_path=_relative(objects_path, root),
            paragraphs_path=_relative(paragraphs_path, root),
            images_path=_relative(images_path, root),
            regions_path=_relative(regions_path, root),
        )
        manifest_path.write_text(
            manifest.model_dump_json(indent=2, exclude_none=True), encoding="utf-8"
        )
        shutil.rmtree(output_dir / ".work", ignore_errors=True)

        session.execute(
            update(ExtractionRun)
            .where(
                ExtractionRun.digital_object_id == digital.id,
                ExtractionRun.id != run_id,
            )
            .values(is_current=False)
        )
        run.engine_version = engine_version
        run.status = status.value
        run.is_current = True
        run.manifest_path = _relative(manifest_path, root)
        run.objects_path = _relative(objects_path, root)
        run.paragraphs_path = _relative(paragraphs_path, root)
        run.images_path = _relative(images_path, root)
        run.regions_path = _relative(regions_path, root)
        run.total_pages = len(requested_pages)
        run.total_objects = len(all_objects)
        run.total_paragraphs = len(paragraphs)
        run.total_characters = character_count
        run.warnings_json = warnings
        run.quality_score = mean(quality_scores) if quality_scores else None
        run.completed_at = now
        session.flush()
        if selection_policy != "never":
            _apply_page_selections(
                session,
                run=run,
                selected_by=created_by,
                policy=selection_policy,
                note=f"Extracción regional {template.template_key}",
            )

        summary.runs_created = 1
        summary.pages_processed = len(requested_pages)
        summary.objects_created = len(all_objects)
        summary.paragraphs_created = len(paragraphs)
        summary.characters_created = character_count
        summary.warnings = [f"{template.source_key}: {warning}" for warning in warnings]
        return summary
    except Exception as exc:
        run.status = ExtractionStatus.FAILED.value
        run.error_text = str(exc)
        run.completed_at = datetime.now(timezone.utc)
        session.flush()
        summary.failed = 1
        summary.warnings.append(f"{template.source_key}: {exc}")
        return summary


def region_status_rows(
    session: Session, *, source_key: str | None = None
) -> list[RegionStatusRow]:
    statement = (
        select(
            SourceRegistration.source_key,
            ExtractionRun.id.label("run_id"),
            ExtractionRun.profile_key,
            ExtractionRegion.page_number,
            ExtractionRegion.region_key,
            ExtractionRegion.label,
            ExtractionRegion.mode,
            ExtractionRegion.object_type,
            ExtractionRegion.status,
            ExtractionRegion.object_count,
            ExtractionRegion.character_count,
            ExtractionRegion.warning_text,
        )
        .join(
            DigitalObject,
            SourceRegistration.digital_object_id == DigitalObject.id,
        )
        .join(ExtractionRun, ExtractionRun.digital_object_id == DigitalObject.id)
        .join(ExtractionRegion, ExtractionRegion.extraction_run_id == ExtractionRun.id)
        .where(
            SourceRegistration.source_type.in_(PROCESSABLE_SOURCE_TYPES),
            ExtractionRun.is_current.is_(True),
        )
        .order_by(
            SourceRegistration.source_key,
            ExtractionRegion.page_number,
            ExtractionRegion.reading_order,
        )
    )
    if source_key:
        statement = statement.where(SourceRegistration.source_key == source_key)
    return [
        RegionStatusRow(
            source_key=row.source_key,
            run_id=row.run_id,
            profile_key=row.profile_key or "-",
            page=row.page_number,
            region_key=row.region_key,
            label=row.label,
            mode=row.mode,
            object_type=row.object_type,
            status=row.status,
            objects=row.object_count,
            characters=row.character_count,
            warning=row.warning_text,
        )
        for row in session.execute(statement)
    ]
