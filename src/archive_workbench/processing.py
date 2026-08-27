from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from archive_workbench.db.models import (
    ArchivalUnit,
    DigitalObject,
    DerivativeAsset,
    EditablePage,
    ExtractionPage,
    ExtractionPageSelection,
    ExtractionRun,
    FileInstance,
    PreprocessingRun,
    ProcessingJob,
    ProcessingJobItem,
    SourceRegistration,
    utc_now,
)
from archive_workbench.identity import new_id
from archive_workbench.sources import DOCUMENT_MEDIA_TYPES, PROCESSABLE_SOURCE_TYPES

PROCESSING_OPERATIONS = ("prepare", "extract", "retry_failed", "bootstrap")
PROCESSING_ITEM_STATUSES = ("queued", "running", "completed", "warning", "failed")
PROCESSING_STATUSES = (
    "missing_local_file",
    "file_available",
    "pending_preparation",
    "prepared",
    "pending_extraction",
    "incomplete_extraction",
    "pending_selection",
    "ready_for_review",
    "in_review",
    "completed",
    "error",
)

_SUCCESS_RUN_STATUSES = {"completed", "completed_with_warnings"}
_SUCCESS_PAGE_STATUSES = {"completed", "completed_with_warnings"}
_REVIEWED_STATUSES = {"reviewed", "approved"}


@dataclass(slots=True)
class ProcessingInventoryRow:
    source_type: str
    source_key: str
    title: str
    archival_path: str
    digital_object_id: str
    original_filename: str
    media_type: str
    page_count: int | None
    local_path: str | None
    file_presence: str
    status: str
    preprocessing_status: str | None
    preprocessing_ready: bool
    preprocessing_profile: str | None
    preprocessing_ocr_treatment: str | None
    preprocessing_geometry_mode: str | None
    extraction_status: str | None
    extraction_profile: str | None
    extracted_pages: int
    selected_pages: int
    editable_pages: int
    reviewed_pages: int
    approved_pages: int
    failed_pages: list[int]
    last_error: str | None


@dataclass(slots=True)
class PreprocessingGeometryRow:
    source_key: str
    title: str
    page: int
    orientation_detected: int | None
    orientation_confidence: float | None
    rotation_applied: int
    deskew_detected_angle: float | None
    deskew_angle: float | None
    deskew_confidence: float | None
    lines_detected: int
    lines_removed: int
    removed_pixels: int
    dewarp_detected: bool
    dewarp_applied: bool
    dewarp_confidence: float
    dewarp_max_displacement_px: float
    dewarp_support_strips: int
    preview_relative_path: str | None
    ocr_relative_path: str
    mask_relative_path: str | None
    dewarp_diagnostic_relative_path: str | None
    transformations: dict[str, Any]


@dataclass(slots=True)
class ExtractionCandidateRun:
    run_id: str
    profile_key: str | None
    engine: str
    status: str
    quality_status: str
    is_current: bool
    pages: list[int]
    failed_pages: list[int]
    objects: int
    characters: int
    created_at: datetime


@dataclass(slots=True)
class ProcessingJobRow:
    job_id: str
    operation: str
    status: str
    total_items: int
    completed_items: int
    warning_items: int
    failed_items: int
    created_by: str
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    parameters: dict[str, Any]


@dataclass(slots=True)
class ProcessingJobItemRow:
    item_id: str
    source_key: str
    status: str
    pages: list[int]
    message: str | None
    detail: dict[str, Any]
    started_at: datetime | None
    completed_at: datetime | None


def _archival_paths(session: Session, project_id: str) -> dict[str, str]:
    units = session.scalars(
        select(ArchivalUnit).where(ArchivalUnit.project_id == project_id)
    ).all()
    by_id = {unit.id: unit for unit in units}
    cache: dict[str, str] = {}

    def resolve(unit_id: str) -> str:
        if unit_id in cache:
            return cache[unit_id]
        labels: list[str] = []
        seen: set[str] = set()
        current = by_id.get(unit_id)
        while current is not None and current.id not in seen:
            seen.add(current.id)
            labels.append(current.title)
            current = by_id.get(current.parent_id) if current.parent_id else None
        value = " / ".join(reversed(labels))
        cache[unit_id] = value
        return value

    return {unit_id: resolve(unit_id) for unit_id in by_id}


def _local_file_state(
    *, project_root: Path, digital: DigitalObject, files: list[FileInstance]
) -> tuple[str, str | None]:
    existing: list[FileInstance] = []
    for item in files:
        candidate = project_root / item.relative_path
        if candidate.is_file():
            existing.append(item)
    if not existing:
        return "missing", None
    chosen = sorted(
        existing,
        key=lambda item: (
            item.presence != "present",
            item.presence == "modified",
            item.relative_path,
        ),
    )[0]
    if chosen.presence == "modified":
        presence = "modified"
    elif chosen.presence == "present" or chosen.verified_sha256 == digital.sha256:
        presence = "present"
    else:
        presence = "unverified"
    return presence, chosen.relative_path


def _latest_run(session: Session, model, *, digital_object_id: str):
    current = session.scalar(
        select(model)
        .where(model.digital_object_id == digital_object_id, model.is_current.is_(True))
        .order_by(model.created_at.desc())
    )
    if current is not None:
        return current
    return session.scalar(
        select(model)
        .where(model.digital_object_id == digital_object_id)
        .order_by(model.created_at.desc())
    )


def _active_processing_operation(session: Session, source_key: str) -> str | None:
    return session.scalar(
        select(ProcessingJob.operation)
        .join(ProcessingJobItem, ProcessingJobItem.processing_job_id == ProcessingJob.id)
        .where(
            ProcessingJobItem.source_key == source_key,
            ProcessingJob.status.in_(("queued", "running")),
            ProcessingJobItem.status.in_(("queued", "running")),
        )
        .order_by(ProcessingJob.created_at.desc())
        .limit(1)
    )


def _requested_pages(run: ExtractionRun, page_count: int | None) -> set[int]:
    options = run.options_json or {}
    raw = options.get("selected_pages")
    if isinstance(raw, list):
        pages = {int(value) for value in raw if isinstance(value, int) and value >= 1}
        if pages:
            return pages
    if page_count:
        return set(range(1, page_count + 1))
    return set()


def _run_failed_pages(
    session: Session, run: ExtractionRun, *, page_count: int | None
) -> set[int]:
    page_rows = session.scalars(
        select(ExtractionPage).where(ExtractionPage.extraction_run_id == run.id)
    ).all()
    completed = {
        item.page_number for item in page_rows if item.status in _SUCCESS_PAGE_STATUSES
    }
    failed = {
        item.page_number for item in page_rows if item.status not in _SUCCESS_PAGE_STATUSES
    }
    if run.status == "failed":
        failed |= _requested_pages(run, page_count) - completed
    return failed


def failed_extraction_pages(session: Session, *, source_key: str) -> list[int]:
    row = session.execute(
        select(SourceRegistration, DigitalObject)
        .join(DigitalObject, SourceRegistration.digital_object_id == DigitalObject.id)
        .where(
            SourceRegistration.source_type.in_(PROCESSABLE_SOURCE_TYPES),
            SourceRegistration.source_key == source_key,
            DigitalObject.media_type.in_(DOCUMENT_MEDIA_TYPES),
        )
    ).one_or_none()
    if row is None:
        raise ValueError(f"source_key no registrado: {source_key}")
    digital = row[1]
    latest = session.scalar(
        select(ExtractionRun)
        .where(ExtractionRun.digital_object_id == digital.id)
        .order_by(ExtractionRun.created_at.desc())
    )
    if latest is None:
        return []
    return sorted(_run_failed_pages(session, latest, page_count=digital.page_count))


def processing_inventory_rows(
    session: Session, *, project_root: str | Path, project_id: str
) -> list[ProcessingInventoryRow]:
    root = Path(project_root).resolve()
    paths = _archival_paths(session, project_id)
    registrations = session.execute(
        select(SourceRegistration, DigitalObject, ArchivalUnit)
        .join(DigitalObject, SourceRegistration.digital_object_id == DigitalObject.id)
        .join(ArchivalUnit, SourceRegistration.archival_unit_id == ArchivalUnit.id)
        .where(
            SourceRegistration.project_id == project_id,
            SourceRegistration.source_type.in_(PROCESSABLE_SOURCE_TYPES),
            DigitalObject.media_type.in_(DOCUMENT_MEDIA_TYPES),
        )
        .order_by(ArchivalUnit.title, SourceRegistration.source_key)
    ).all()
    output: list[ProcessingInventoryRow] = []
    for registration, digital, unit in registrations:
        file_rows = session.scalars(
            select(FileInstance).where(FileInstance.digital_object_id == digital.id)
        ).all()
        file_presence, local_path = _local_file_state(
            project_root=root, digital=digital, files=file_rows
        )
        preprocessing = _latest_run(
            session, PreprocessingRun, digital_object_id=digital.id
        )
        preprocessing_ready = session.scalar(
            select(PreprocessingRun.id)
            .where(
                PreprocessingRun.digital_object_id == digital.id,
                PreprocessingRun.is_current.is_(True),
                PreprocessingRun.status.in_(_SUCCESS_RUN_STATUSES),
            )
            .limit(1)
        ) is not None
        extraction = _latest_run(session, ExtractionRun, digital_object_id=digital.id)
        successful_runs = session.scalars(
            select(ExtractionRun.id).where(
                ExtractionRun.digital_object_id == digital.id,
                ExtractionRun.status.in_(_SUCCESS_RUN_STATUSES),
            )
        ).all()
        extracted_pages: set[int] = set()
        if successful_runs:
            extracted_pages = set(
                session.scalars(
                    select(ExtractionPage.page_number).where(
                        ExtractionPage.extraction_run_id.in_(successful_runs),
                        ExtractionPage.status.in_(_SUCCESS_PAGE_STATUSES),
                    )
                ).all()
            )
        selected_page_numbers = set(
            session.scalars(
                select(ExtractionPageSelection.page_number).where(
                    ExtractionPageSelection.digital_object_id == digital.id
                )
            ).all()
        )
        editable = session.scalars(
            select(EditablePage).where(EditablePage.digital_object_id == digital.id)
        ).all()
        editable_active = [item for item in editable if item.status in {"active", "stale"}]
        reviewed = [item for item in editable_active if item.review_status in _REVIEWED_STATUSES]
        approved = [item for item in editable_active if item.review_status == "approved"]
        failed_pages: set[int] = set()
        if extraction is not None:
            failed_pages = _run_failed_pages(
                session, extraction, page_count=digital.page_count
            )
        active_operation = _active_processing_operation(session, registration.source_key)
        expected = set(range(1, (digital.page_count or 0) + 1))
        last_error: str | None = None

        if file_presence == "missing":
            status = "missing_local_file"
        elif file_presence == "modified":
            status = "error"
            last_error = "El archivo local fue modificado desde su registro."
        elif preprocessing is not None and preprocessing.status == "failed":
            status = "error"
            last_error = "; ".join(preprocessing.warnings_json or []) or "Falló la preparación."
        elif extraction is not None and extraction.status == "failed":
            status = "error"
            last_error = extraction.error_text or "Falló la extracción."
        elif expected and len(approved) >= len(expected):
            status = "completed"
        elif editable_active:
            status = "in_review"
        elif expected and expected.issubset(selected_page_numbers):
            status = "ready_for_review"
        elif active_operation in {"extract", "retry_failed"} or (
            extraction is not None and extraction.status in {"registered", "running"}
        ):
            status = "pending_extraction"
        elif extraction is not None or extracted_pages:
            if expected and not expected.issubset(extracted_pages):
                status = "incomplete_extraction"
            elif not expected and failed_pages:
                status = "incomplete_extraction"
            else:
                status = "pending_selection"
        elif preprocessing is not None and preprocessing.status in _SUCCESS_RUN_STATUSES:
            status = "prepared"
        elif active_operation == "prepare" or (
            preprocessing is not None and preprocessing.status in {"registered", "running"}
        ):
            status = "pending_preparation"
        elif file_presence == "unverified":
            status = "file_available"
        else:
            status = "pending_preparation"

        output.append(
            ProcessingInventoryRow(
                source_type=registration.source_type,
                source_key=registration.source_key,
                title=unit.title,
                archival_path=paths.get(unit.id, unit.title),
                digital_object_id=digital.id,
                original_filename=digital.original_filename,
                media_type=digital.media_type,
                page_count=digital.page_count,
                local_path=local_path,
                file_presence=file_presence,
                status=status,
                preprocessing_status=preprocessing.status if preprocessing else None,
                preprocessing_ready=preprocessing_ready,
                preprocessing_profile=preprocessing.profile_key if preprocessing else None,
                preprocessing_ocr_treatment=(
                    str((preprocessing.options_json or {}).get("ocr_treatment", "original"))
                    if preprocessing
                    else None
                ),
                preprocessing_geometry_mode=(
                    str((preprocessing.options_json or {}).get("geometry_mode", "none"))
                    if preprocessing
                    else None
                ),
                extraction_status=extraction.status if extraction else None,
                extraction_profile=extraction.profile_key if extraction else None,
                extracted_pages=len(extracted_pages),
                selected_pages=len(selected_page_numbers),
                editable_pages=len(editable_active),
                reviewed_pages=len(reviewed),
                approved_pages=len(approved),
                failed_pages=sorted(failed_pages),
                last_error=last_error,
            )
        )
    return output


def extraction_candidate_runs(
    session: Session, *, source_key: str, digital_object_id: str | None = None
) -> list[ExtractionCandidateRun]:
    statement = (
        select(SourceRegistration, DigitalObject)
        .join(DigitalObject, SourceRegistration.digital_object_id == DigitalObject.id)
        .where(
            SourceRegistration.source_type.in_(PROCESSABLE_SOURCE_TYPES),
            SourceRegistration.source_key == source_key,
        )
    )
    if digital_object_id is not None:
        statement = statement.where(DigitalObject.id == digital_object_id)
    rows = session.execute(statement).all()
    if not rows:
        raise ValueError(f"source_key no registrado: {source_key}")
    if len(rows) > 1 and digital_object_id is None:
        raise ValueError(
            "Ese identificador de origen corresponde a más de un documento. "
            "Elegí el documento concreto antes de consultar sus extracciones."
        )
    digital = rows[0][1]
    runs = session.scalars(
        select(ExtractionRun)
        .where(ExtractionRun.digital_object_id == digital.id)
        .order_by(ExtractionRun.created_at.desc())
    ).all()
    output: list[ExtractionCandidateRun] = []
    for run in runs:
        pages = session.scalars(
            select(ExtractionPage)
            .where(ExtractionPage.extraction_run_id == run.id)
            .order_by(ExtractionPage.page_number)
        ).all()
        output.append(
            ExtractionCandidateRun(
                run_id=run.id,
                profile_key=run.profile_key,
                engine=run.engine,
                status=run.status,
                quality_status=run.quality_status,
                is_current=bool(run.is_current),
                pages=[item.page_number for item in pages if item.status in _SUCCESS_PAGE_STATUSES],
                failed_pages=[
                    item.page_number for item in pages if item.status not in _SUCCESS_PAGE_STATUSES
                ],
                objects=run.total_objects or 0,
                characters=run.total_characters or 0,
                created_at=run.created_at,
            )
        )
    return output


def create_processing_job(
    session: Session,
    *,
    project_id: str,
    operation: str,
    source_keys: list[str] | tuple[str, ...] | set[str],
    created_by: str,
    parameters: dict[str, Any] | None = None,
) -> ProcessingJob:
    if operation not in PROCESSING_OPERATIONS:
        raise ValueError(f"Operación de procesamiento inválida: {operation}")
    ordered = sorted({str(value).strip() for value in source_keys if str(value).strip()})
    if not ordered:
        raise ValueError("Debe seleccionar al menos un documento")
    registrations = session.execute(
        select(SourceRegistration.source_key, SourceRegistration.digital_object_id)
        .join(DigitalObject, SourceRegistration.digital_object_id == DigitalObject.id)
        .where(
            SourceRegistration.project_id == project_id,
            SourceRegistration.source_type.in_(PROCESSABLE_SOURCE_TYPES),
            SourceRegistration.source_key.in_(ordered),
            DigitalObject.media_type.in_(DOCUMENT_MEDIA_TYPES),
        )
    ).all()
    by_key = {row.source_key: row.digital_object_id for row in registrations}
    missing = set(ordered) - set(by_key)
    if missing:
        raise ValueError("source_key no registrado: " + ", ".join(sorted(missing)))
    now = utc_now()
    job = ProcessingJob(
        id=new_id(),
        project_id=project_id,
        operation=operation,
        status="queued",
        source_keys_json=ordered,
        parameters_json=parameters or {},
        total_items=len(ordered),
        created_by=created_by or "local_user",
        created_at=now,
    )
    session.add(job)
    session.flush()
    for source_key in ordered:
        session.add(
            ProcessingJobItem(
                id=new_id(),
                processing_job_id=job.id,
                digital_object_id=by_key[source_key],
                source_key=source_key,
                status="queued",
                pages_json=[],
                detail_json={},
                created_at=now,
            )
        )
    session.flush()
    return job


def start_processing_job(session: Session, *, job_id: str) -> ProcessingJob:
    job = session.get(ProcessingJob, job_id)
    if job is None:
        raise ValueError(f"Trabajo de procesamiento inexistente: {job_id}")
    if job.status not in {"queued", "running"}:
        raise ValueError(f"El trabajo ya está cerrado con estado {job.status}")
    job.status = "running"
    job.started_at = job.started_at or utc_now()
    session.flush()
    return job


def update_processing_job_item(
    session: Session,
    *,
    job_id: str,
    source_key: str,
    status: str,
    pages: list[int] | tuple[int, ...] | set[int] | None = None,
    message: str | None = None,
    detail: dict[str, Any] | None = None,
) -> ProcessingJobItem:
    if status not in PROCESSING_ITEM_STATUSES:
        raise ValueError(f"Estado de ítem inválido: {status}")
    item = session.scalar(
        select(ProcessingJobItem).where(
            ProcessingJobItem.processing_job_id == job_id,
            ProcessingJobItem.source_key == source_key,
        )
    )
    if item is None:
        raise ValueError(f"Ítem inexistente para {source_key}")
    now = utc_now()
    item.status = status
    if status == "running":
        item.started_at = item.started_at or now
    if status in {"completed", "warning", "failed"}:
        item.started_at = item.started_at or now
        item.completed_at = now
    if pages is not None:
        item.pages_json = sorted({int(page) for page in pages if int(page) >= 1})
    item.message = message.strip() if message and message.strip() else None
    item.detail_json = detail or {}
    session.flush()
    return item


def finish_processing_job(session: Session, *, job_id: str) -> ProcessingJob:
    job = session.get(ProcessingJob, job_id)
    if job is None:
        raise ValueError(f"Trabajo de procesamiento inexistente: {job_id}")
    items = session.scalars(
        select(ProcessingJobItem).where(ProcessingJobItem.processing_job_id == job_id)
    ).all()
    job.completed_items = sum(item.status == "completed" for item in items)
    job.warning_items = sum(item.status == "warning" for item in items)
    job.failed_items = sum(item.status == "failed" for item in items)
    unfinished = [item for item in items if item.status in {"queued", "running"}]
    if unfinished:
        job.status = "running"
        job.completed_at = None
    elif job.failed_items == len(items):
        job.status = "failed"
        job.completed_at = utc_now()
    elif job.failed_items or job.warning_items:
        job.status = "completed_with_warnings"
        job.completed_at = utc_now()
    else:
        job.status = "completed"
        job.completed_at = utc_now()
    session.flush()
    return job


def processing_job_rows(
    session: Session, *, project_id: str, limit: int = 50
) -> list[ProcessingJobRow]:
    jobs = session.scalars(
        select(ProcessingJob)
        .where(ProcessingJob.project_id == project_id)
        .order_by(ProcessingJob.created_at.desc())
        .limit(max(1, limit))
    ).all()
    return [
        ProcessingJobRow(
            job_id=job.id,
            operation=job.operation,
            status=job.status,
            total_items=job.total_items,
            completed_items=job.completed_items,
            warning_items=job.warning_items,
            failed_items=job.failed_items,
            created_by=job.created_by,
            created_at=job.created_at,
            started_at=job.started_at,
            completed_at=job.completed_at,
            parameters=dict(job.parameters_json or {}),
        )
        for job in jobs
    ]


def processing_job_item_rows(
    session: Session, *, job_id: str
) -> list[ProcessingJobItemRow]:
    items = session.scalars(
        select(ProcessingJobItem)
        .where(ProcessingJobItem.processing_job_id == job_id)
        .order_by(ProcessingJobItem.created_at, ProcessingJobItem.source_key)
    ).all()
    return [
        ProcessingJobItemRow(
            item_id=item.id,
            source_key=item.source_key,
            status=item.status,
            pages=list(item.pages_json or []),
            message=item.message,
            detail=dict(item.detail_json or {}),
            started_at=item.started_at,
            completed_at=item.completed_at,
        )
        for item in items
    ]


def processing_geometry_rows(
    session: Session,
    *,
    source_keys: set[str] | None = None,
) -> list[PreprocessingGeometryRow]:
    statement = (
        select(SourceRegistration, DigitalObject)
        .join(DigitalObject, DigitalObject.id == SourceRegistration.digital_object_id)
        .order_by(SourceRegistration.source_key)
    )
    if source_keys:
        statement = statement.where(SourceRegistration.source_key.in_(source_keys))
    rows: list[PreprocessingGeometryRow] = []
    for registration, digital in session.execute(statement):
        run = session.scalar(
            select(PreprocessingRun)
            .where(
                PreprocessingRun.digital_object_id == digital.id,
                PreprocessingRun.is_current.is_(True),
            )
            .order_by(PreprocessingRun.created_at.desc())
        )
        if run is None:
            continue
        assets = list(
            session.scalars(
                select(DerivativeAsset)
                .where(DerivativeAsset.preprocessing_run_id == run.id)
                .order_by(DerivativeAsset.page_number, DerivativeAsset.kind)
            )
        )
        by_page: dict[int, dict[str, DerivativeAsset]] = {}
        for asset in assets:
            by_page.setdefault(asset.page_number, {})[asset.kind] = asset
        title = str(
            (registration.source_payload_json or {}).get("short_description")
            or registration.source_key
        )
        for page, page_assets in sorted(by_page.items()):
            preview = page_assets.get("preview")
            ocr = page_assets.get("ocr")
            if ocr is None or not (ocr.analysis_json or ocr.transformations_json):
                continue
            analysis = dict(ocr.analysis_json or {})
            mask = page_assets.get("diagnostic_mask")
            dewarp_diagnostic = page_assets.get("dewarp_diagnostic")
            rows.append(
                PreprocessingGeometryRow(
                    source_key=str(registration.source_key),
                    title=title,
                    page=page,
                    orientation_detected=(
                        int(analysis["orientation_detected"])
                        if analysis.get("orientation_detected") is not None
                        else None
                    ),
                    orientation_confidence=(
                        float(analysis["orientation_confidence"])
                        if analysis.get("orientation_confidence") is not None
                        else None
                    ),
                    rotation_applied=int(ocr.rotation_applied or 0),
                    deskew_detected_angle=(
                        float(analysis["deskew_detected_angle"])
                        if analysis.get("deskew_detected_angle") is not None
                        else None
                    ),
                    deskew_angle=(
                        float(analysis["deskew_angle"])
                        if analysis.get("deskew_angle") is not None
                        else None
                    ),
                    deskew_confidence=(
                        float(analysis["deskew_confidence"])
                        if analysis.get("deskew_confidence") is not None
                        else None
                    ),
                    lines_detected=int(analysis.get("lines_detected") or 0),
                    lines_removed=int(analysis.get("lines_removed") or 0),
                    removed_pixels=int(analysis.get("removed_pixels") or 0),
                    dewarp_detected=bool(analysis.get("dewarp_detected", False)),
                    dewarp_applied=bool(analysis.get("dewarp_applied", False)),
                    dewarp_confidence=float(analysis.get("dewarp_confidence") or 0.0),
                    dewarp_max_displacement_px=float(
                        analysis.get("dewarp_max_displacement_px") or 0.0
                    ),
                    dewarp_support_strips=int(
                        analysis.get("dewarp_support_strips") or 0
                    ),
                    preview_relative_path=preview.relative_path if preview else None,
                    ocr_relative_path=ocr.relative_path,
                    mask_relative_path=mask.relative_path if mask else None,
                    dewarp_diagnostic_relative_path=(
                        dewarp_diagnostic.relative_path if dewarp_diagnostic else None
                    ),
                    transformations=dict(ocr.transformations_json or {}),
                )
            )
    return rows
