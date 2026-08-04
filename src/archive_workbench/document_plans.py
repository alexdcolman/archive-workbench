from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import yaml
from PIL import Image, ImageDraw, ImageFont, ImageOps
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from archive_workbench.sources import PROCESSABLE_SOURCE_TYPES
from archive_workbench.contracts.decisions import ProjectDecisions
from archive_workbench.contracts.plans import DocumentProcessingPlan
from archive_workbench.db.models import (
    ArchivalUnit,
    DigitalObject,
    DocumentPart,
    DocumentProcessingPlanRecord,
    PageProcessingAssignmentRecord,
    SourceRegistration,
)
from archive_workbench.extraction import (
    ExtractionSummary,
    _current_assets,
    extract_documents_preferred,
    extraction_doctor,
    load_extraction_profile,
    resolve_extraction_profile,
)
from archive_workbench.identity import new_id, sha256_file, sha256_json
from archive_workbench.region_extraction import extract_regions, load_region_template

# Alias local para conservar un punto de extensión estable en pruebas e integraciones.
extract_documents = extract_documents_preferred

@dataclass(slots=True)
class ContactSheetResult:
    sheet_number: int
    pages: list[int]
    path: str


@dataclass(slots=True)
class PlanImportResult:
    plan_id: str
    reused: bool
    assignments: int
    parts: int


@dataclass(slots=True)
class PlanExecutionSummary:
    plan_id: str
    ocr_groups: int = 0
    region_groups: int = 0
    manual_pages: int = 0
    skipped_pages: int = 0
    runs_created: int = 0
    runs_reused: int = 0
    failed: int = 0
    pages_processed: int = 0
    objects_created: int = 0
    characters_created: int = 0
    warnings: list[str] = field(default_factory=list)
    manifest_path: str | None = None


@dataclass(slots=True)
class PlanStatusRow:
    source_key: str
    title: str
    plan_key: str | None
    status: str | None
    page_count: int
    assigned_pages: int
    pending_pages: int
    parts: int
    modes: dict[str, int]


@dataclass(slots=True)
class DocumentPartStatusRow:
    source_key: str
    part_key: str
    title: str
    part_type: str
    status: str
    physical_pages: list[int]
    logical_pages: list[int]
    notes: str | None


def load_document_plan(path: str | Path) -> DocumentProcessingPlan:
    source = Path(path)
    try:
        payload = yaml.safe_load(source.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"No existe el plan documental: {source}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"El plan documental debe ser un objeto YAML: {source}")
    return DocumentProcessingPlan.model_validate(payload)


def write_document_plan(path: str | Path, plan: DocumentProcessingPlan) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        yaml.safe_dump(
            plan.model_dump(mode="json", exclude_none=True),
            allow_unicode=True,
            sort_keys=False,
            width=110,
        ),
        encoding="utf-8",
    )
    return destination


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


def _relative(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def representative_pages(page_count: int, sample_count: int = 5) -> list[int]:
    if page_count < 1:
        return []
    count = min(max(1, sample_count), page_count)
    if count == 1:
        return [1]
    pages = {
        1 + int(index * (page_count - 1) / (count - 1) + 0.5)
        for index in range(count)
    }
    return sorted(pages)


def create_document_plan_template(
    session: Session,
    *,
    source_key: str,
    created_by: str = "local_user",
    sample_count: int = 5,
) -> DocumentProcessingPlan:
    _registration, digital, unit = _registration_for_source(session, source_key)
    if not digital.page_count:
        raise ValueError(f"El objeto {source_key} no tiene cantidad de páginas registrada")
    return DocumentProcessingPlan(
        plan_key=f"{source_key}_plan_v1",
        source_key=source_key,
        expected_page_count=digital.page_count,
        status="draft",
        benchmark_pages=representative_pages(digital.page_count, sample_count),
        parts=[],
        assignments=[
            {
                "assignment_key": "pending_all_pages",
                "page_start": 1,
                "page_end": digital.page_count,
                "mode": "pending",
                "notes": "Dividir esta asignación después de revisar las hojas de contacto y benchmarks.",
            }
        ],
        created_by=created_by,
        notes=(
            f"Plan inicial para {unit.title}. Definir documentos internos y perfiles por páginas o rangos."
        ),
    )


def validate_plan_against_catalog(
    session: Session,
    *,
    project_root: str | Path,
    plan: DocumentProcessingPlan,
    require_ready: bool = False,
) -> None:
    root = Path(project_root)
    _registration, digital, _unit = _registration_for_source(session, plan.source_key)
    if digital.page_count != plan.expected_page_count:
        raise ValueError(
            f"El plan espera {plan.expected_page_count} páginas, pero el catálogo registra "
            f"{digital.page_count}"
        )
    if require_ready and plan.status != "ready":
        raise ValueError("El plan debe tener status: ready para ejecutarse")
    for assignment in plan.assignments:
        if assignment.mode == "ocr":
            assert assignment.profile
            profile_path = plan.resolve_path(root, assignment.profile)
            load_extraction_profile(profile_path)
        elif assignment.mode == "regions":
            assert assignment.region_template
            template_path = plan.resolve_path(root, assignment.region_template)
            template = load_region_template(template_path)
            if template.source_key != plan.source_key:
                raise ValueError(
                    f"La plantilla {template_path} corresponde a {template.source_key}, no a "
                    f"{plan.source_key}"
                )
            template_pages = {region.page for region in template.regions}
            assignment_pages = assignment.expanded_pages
            if template_pages != assignment_pages:
                raise ValueError(
                    f"La asignación {assignment.assignment_key} debe coincidir exactamente con "
                    f"las páginas de su plantilla regional: {sorted(template_pages)}"
                )


def _sheet_canvas_size(
    thumbnails: list[tuple[int, Image.Image]], columns: int, thumb_width: int
) -> tuple[int, int, int, int]:
    margin = 24
    caption_height = 30
    cell_width = thumb_width + margin * 2
    max_height = max((image.height for _, image in thumbnails), default=thumb_width)
    cell_height = max_height + caption_height + margin * 2
    rows = (len(thumbnails) + columns - 1) // columns
    return columns * cell_width, rows * cell_height, cell_width, cell_height


def render_contact_sheets(
    session: Session,
    *,
    project_root: str | Path,
    source_key: str,
    pages_per_sheet: int = 12,
    columns: int = 3,
    thumb_width: int = 420,
) -> list[ContactSheetResult]:
    if pages_per_sheet < 1 or columns < 1 or thumb_width < 100:
        raise ValueError("Parámetros inválidos para la hoja de contacto")
    root = Path(project_root)
    _registration, digital, _unit = _registration_for_source(session, source_key)
    _preprocessing, _ocr_assets, preview_assets = _current_assets(session, digital.id)
    if not preview_assets:
        raise RuntimeError("No existen derivados de vista para generar hojas de contacto")
    asset_by_page = {asset.page_number: asset for asset in preview_assets}
    expected_pages = list(range(1, (digital.page_count or len(asset_by_page)) + 1))
    missing = [page for page in expected_pages if page not in asset_by_page]
    if missing:
        raise RuntimeError(f"Faltan derivados de vista para páginas: {missing}")

    destination_root = root / "document_plans" / source_key / "contact_sheets"
    destination_root.mkdir(parents=True, exist_ok=True)
    font = ImageFont.load_default()
    results: list[ContactSheetResult] = []
    for offset in range(0, len(expected_pages), pages_per_sheet):
        page_batch = expected_pages[offset : offset + pages_per_sheet]
        thumbnails: list[tuple[int, Image.Image]] = []
        try:
            for page in page_batch:
                asset = asset_by_page[page]
                source = root / asset.relative_path
                if sha256_file(source) != asset.sha256:
                    raise RuntimeError(f"el derivado de vista fue modificado: {asset.relative_path}")
                with Image.open(source) as raw:
                    image = ImageOps.contain(raw.convert("RGB"), (thumb_width, thumb_width * 2))
                    thumbnails.append((page, image.copy()))

            width, height, cell_width, cell_height = _sheet_canvas_size(
                thumbnails, columns, thumb_width
            )
            canvas = Image.new("RGB", (width, height), "white")
            draw = ImageDraw.Draw(canvas)
            for index, (page, image) in enumerate(thumbnails):
                row, column = divmod(index, columns)
                x = column * cell_width + (cell_width - image.width) // 2
                y = row * cell_height + 24
                canvas.paste(image, (x, y))
                caption = f"Página {page}"
                box = draw.textbbox((0, 0), caption, font=font)
                text_width = box[2] - box[0]
                draw.text(
                    (column * cell_width + (cell_width - text_width) // 2, y + image.height + 8),
                    caption,
                    fill="black",
                    font=font,
                )
                draw.rectangle(
                    (x - 1, y - 1, x + image.width, y + image.height),
                    outline=(100, 100, 100),
                    width=1,
                )
            sheet_number = offset // pages_per_sheet + 1
            destination = destination_root / f"sheet_{sheet_number:02d}.jpg"
            canvas.save(destination, format="JPEG", quality=88, optimize=True)
            results.append(
                ContactSheetResult(
                    sheet_number=sheet_number,
                    pages=page_batch,
                    path=_relative(destination, root),
                )
            )
        finally:
            for _, image in thumbnails:
                image.close()
    return results


def import_document_plan(
    session: Session,
    *,
    project_root: str | Path,
    plan: DocumentProcessingPlan,
    source_path: str | Path | None = None,
) -> PlanImportResult:
    root = Path(project_root)
    validate_plan_against_catalog(session, project_root=root, plan=plan)
    _registration, digital, _unit = _registration_for_source(session, plan.source_key)
    payload = plan.model_dump(mode="json", exclude_none=True)
    plan_hash = sha256_json(payload)
    existing = session.scalar(
        select(DocumentProcessingPlanRecord).where(
            DocumentProcessingPlanRecord.digital_object_id == digital.id,
            DocumentProcessingPlanRecord.plan_key == plan.plan_key,
            DocumentProcessingPlanRecord.plan_hash == plan_hash,
        )
    )
    if existing is not None:
        session.execute(
            update(DocumentProcessingPlanRecord)
            .where(DocumentProcessingPlanRecord.digital_object_id == digital.id)
            .values(is_current=False)
        )
        existing.is_current = True
        session.flush()
        return PlanImportResult(existing.id, True, len(plan.assigned_pages), len(plan.parts))

    session.execute(
        update(DocumentProcessingPlanRecord)
        .where(DocumentProcessingPlanRecord.digital_object_id == digital.id)
        .values(is_current=False)
    )
    plan_id = new_id()
    relative_source: str | None = None
    if source_path:
        source = Path(source_path)
        if source.is_absolute():
            try:
                relative_source = _relative(source, root)
            except ValueError:
                relative_source = str(source)
        else:
            relative_source = source.as_posix()
    record = DocumentProcessingPlanRecord(
        id=plan_id,
        digital_object_id=digital.id,
        plan_key=plan.plan_key,
        plan_hash=plan_hash,
        schema_version=plan.schema_version,
        status=plan.status,
        is_current=True,
        source_path=relative_source,
        plan_json=payload,
        created_by=plan.created_by,
    )
    session.add(record)

    for assignment in plan.assignments:
        for page in sorted(assignment.expanded_pages):
            session.add(
                PageProcessingAssignmentRecord(
                    id=new_id(),
                    processing_plan_id=plan_id,
                    page_number=page,
                    assignment_key=assignment.assignment_key,
                    mode=assignment.mode,
                    profile_path=assignment.profile,
                    region_template_path=assignment.region_template,
                    part_key=assignment.part_key,
                    notes=assignment.notes,
                )
            )

    existing_parts = {
        item.part_key: item
        for item in session.scalars(
            select(DocumentPart).where(DocumentPart.digital_object_id == digital.id)
        )
    }
    planned_keys = {part.part_key for part in plan.parts}
    for key, item in existing_parts.items():
        if key not in planned_keys and item.status == "provisional":
            session.delete(item)
    for part in plan.parts:
        item = existing_parts.get(part.part_key)
        if item is None:
            item = DocumentPart(
                id=new_id(),
                digital_object_id=digital.id,
                part_key=part.part_key,
                title=part.title,
                part_type=part.part_type,
                page_start=part.physical_page_start,
                page_end=part.physical_page_end,
                page_sequence_json=part.logical_pages,
                status=part.status,
                notes=part.notes,
                created_by=plan.created_by,
            )
            session.add(item)
        else:
            item.title = part.title
            item.part_type = part.part_type
            item.page_start = part.physical_page_start
            item.page_end = part.physical_page_end
            item.page_sequence_json = part.logical_pages
            item.status = part.status
            item.notes = part.notes
    session.flush()
    return PlanImportResult(plan_id, False, len(plan.assigned_pages), len(plan.parts))


def _merge_summary(target: PlanExecutionSummary, source: ExtractionSummary) -> None:
    target.runs_created += source.runs_created
    target.runs_reused += source.runs_reused
    target.failed += source.failed
    target.pages_processed += source.pages_processed
    target.objects_created += source.objects_created
    target.characters_created += source.characters_created
    target.warnings.extend(source.warnings)


def execute_document_plan(
    session: Session,
    *,
    project_root: str | Path,
    decisions: ProjectDecisions,
    plan: DocumentProcessingPlan,
    plan_path: str | Path | None = None,
    created_by: str = "local_user",
    force: bool = False,
) -> PlanExecutionSummary:
    root = Path(project_root)
    validate_plan_against_catalog(
        session, project_root=root, plan=plan, require_ready=True
    )
    imported = import_document_plan(
        session, project_root=root, plan=plan, source_path=plan_path
    )
    summary = PlanExecutionSummary(plan_id=imported.plan_id)

    for assignment in plan.assignments:
        pages = assignment.expanded_pages
        if assignment.mode == "pending":  # pragma: no cover - bloqueado por validación
            raise ValueError("No puede ejecutarse una asignación pending")
        if assignment.mode == "manual":
            summary.manual_pages += len(pages)
            continue
        if assignment.mode == "skip":
            summary.skipped_pages += len(pages)
            continue
        if assignment.mode == "ocr":
            assert assignment.profile
            profile = load_extraction_profile(plan.resolve_path(root, assignment.profile))
            resolution = resolve_extraction_profile(root, profile)
            failures = [
                check
                for check in resolution.effective_report.checks
                if check.required and not check.ok
            ]
            if failures:
                details = "; ".join(f"{check.name}: {check.detail}" for check in failures)
                raise RuntimeError(f"El entorno no está listo para {assignment.assignment_key}: {details}")
            result = extract_documents(
                session,
                project_root=root,
                decisions=decisions,
                profile=profile,
                source_keys={plan.source_key},
                selected_pages=set(pages),
                force=force,
                created_by=created_by,
                selection_policy="replace",
            )
            summary.ocr_groups += 1
            _merge_summary(summary, result)
            continue
        if assignment.mode == "regions":
            assert assignment.region_template
            template = load_region_template(plan.resolve_path(root, assignment.region_template))
            result = extract_regions(
                session,
                project_root=root,
                decisions=decisions,
                template=template,
                created_by=created_by,
                selection_policy="replace",
                force=force,
            )
            summary.region_groups += 1
            _merge_summary(summary, result)

    record = session.get(DocumentProcessingPlanRecord, imported.plan_id)
    assert record is not None
    record.status = "executed_with_errors" if summary.failed else "executed"
    record.executed_at = datetime.now(timezone.utc)

    output_root = root / "document_plans" / plan.source_key / plan.plan_key
    output_root.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema_version": "1.0",
        "plan_id": imported.plan_id,
        "plan_key": plan.plan_key,
        "source_key": plan.source_key,
        "executed_at": record.executed_at.isoformat(),
        "created_by": created_by,
        "summary": {
            "ocr_groups": summary.ocr_groups,
            "region_groups": summary.region_groups,
            "manual_pages": summary.manual_pages,
            "skipped_pages": summary.skipped_pages,
            "runs_created": summary.runs_created,
            "runs_reused": summary.runs_reused,
            "failed": summary.failed,
            "pages_processed": summary.pages_processed,
            "objects_created": summary.objects_created,
            "characters_created": summary.characters_created,
            "warnings": summary.warnings,
        },
        "plan": plan.model_dump(mode="json", exclude_none=True),
    }
    destination = output_root / "execution_manifest.json"
    destination.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    summary.manifest_path = _relative(destination, root)
    session.flush()
    return summary


def plan_status_rows(session: Session) -> list[PlanStatusRow]:
    rows = session.execute(
        select(SourceRegistration, DigitalObject, ArchivalUnit, DocumentProcessingPlanRecord)
        .join(DigitalObject, SourceRegistration.digital_object_id == DigitalObject.id)
        .join(ArchivalUnit, SourceRegistration.archival_unit_id == ArchivalUnit.id)
        .outerjoin(
            DocumentProcessingPlanRecord,
            (DocumentProcessingPlanRecord.digital_object_id == DigitalObject.id)
            & (DocumentProcessingPlanRecord.is_current.is_(True)),
        )
        .where(SourceRegistration.source_type.in_(PROCESSABLE_SOURCE_TYPES))
        .order_by(SourceRegistration.source_key)
    ).all()
    result: list[PlanStatusRow] = []
    for registration, digital, unit, plan_record in rows:
        assignments: list[PageProcessingAssignmentRecord] = []
        part_count = 0
        if plan_record is not None:
            assignments = list(
                session.scalars(
                    select(PageProcessingAssignmentRecord).where(
                        PageProcessingAssignmentRecord.processing_plan_id == plan_record.id
                    )
                )
            )
            part_count = len(
                session.scalars(
                    select(DocumentPart).where(DocumentPart.digital_object_id == digital.id)
                ).all()
            )
        modes = Counter(item.mode for item in assignments)
        result.append(
            PlanStatusRow(
                source_key=registration.source_key,
                title=unit.title,
                plan_key=plan_record.plan_key if plan_record else None,
                status=plan_record.status if plan_record else None,
                page_count=digital.page_count or 0,
                assigned_pages=len(assignments),
                pending_pages=modes.get("pending", 0),
                parts=part_count,
                modes=dict(sorted(modes.items())),
            )
        )
    return result


def document_part_status_rows(
    session: Session, *, source_key: str | None = None
) -> list[DocumentPartStatusRow]:
    query = (
        select(SourceRegistration, DocumentPart)
        .join(DigitalObject, SourceRegistration.digital_object_id == DigitalObject.id)
        .join(DocumentPart, DocumentPart.digital_object_id == DigitalObject.id)
        .where(SourceRegistration.source_type.in_(PROCESSABLE_SOURCE_TYPES))
    )
    if source_key:
        query = query.where(SourceRegistration.source_key == source_key)
    rows = session.execute(
        query.order_by(SourceRegistration.source_key, DocumentPart.page_start, DocumentPart.part_key)
    ).all()
    result: list[DocumentPartStatusRow] = []
    for registration, part in rows:
        physical_pages = list(range(part.page_start, part.page_end + 1))
        logical_pages = list(part.page_sequence_json or physical_pages)
        result.append(
            DocumentPartStatusRow(
                source_key=registration.source_key,
                part_key=part.part_key,
                title=part.title,
                part_type=part.part_type,
                status=part.status,
                physical_pages=physical_pages,
                logical_pages=logical_pages,
                notes=part.notes,
            )
        )
    return result
