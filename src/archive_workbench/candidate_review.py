from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from difflib import SequenceMatcher, unified_diff
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont, ImageOps
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from archive_workbench.contracts.decisions import ProjectDecisions
from archive_workbench.db.models import (
    ArchivalUnit,
    DerivativeAsset,
    DigitalObject,
    EditableObject,
    EditableObjectComment,
    EditableObjectRevision,
    EditableObjectTag,
    EditablePage,
    EditablePageAction,
    EditablePageRevision,
    EntityMention,
    EntityMentionRevision,
    ExchangeChangeEvent,
    ExtractedObject,
    ExtractionPage,
    ExtractionPageSelection,
    ExtractionPageSelectionRevision,
    ExtractionRun,
    PreprocessingRun,
    SourceRegistration,
    utc_now,
)
from archive_workbench.editing import (
    _allowed_object_type,
    _append_page_revision,
    _append_revision,
    add_editable_object,
    bootstrap_editable_layer,
)
from archive_workbench.extraction import select_extraction_pages
from archive_workbench.identity import new_id
from archive_workbench.page_quality import PageQualityResult, latest_page_quality_assessment
from archive_workbench.sources import PROCESSABLE_SOURCE_TYPES

ADOPTION_NOT_INITIALIZED = "not_initialized"
ADOPTION_SAFE = "safe_to_adopt"
ADOPTION_ALREADY = "already_adopted"
ADOPTION_MANUAL = "manual_resolution_required"

_SAFE_OBJECT_OPERATIONS = {"import", "source_replaced", "candidate_adopted"}


@dataclass(slots=True)
class CandidateObjectRow:
    object_id: str
    order_index: int
    object_type: str
    text: str
    geometry: list[dict[str, Any]]
    confidence: float | None
    source_label: str | None


@dataclass(slots=True)
class CandidatePageVersion:
    run_id: str
    page_id: str
    profile_key: str | None
    engine: str
    status: str
    quality_status: str
    quality_score: float | None
    created_at: datetime
    object_count: int
    character_count: int
    text: str
    objects: list[CandidateObjectRow]
    preview_path: Path | None
    is_selected: bool
    is_editable_source: bool
    automatic_quality: PageQualityResult | None


@dataclass(slots=True)
class CandidatePageComparison:
    source_key: str
    title: str
    page: int
    current: CandidatePageVersion | None
    candidate: CandidatePageVersion
    editable_text: str | None
    editable_object_count: int
    editable_status: str | None
    text_similarity: float | None
    object_delta: int | None
    character_delta: int | None
    changed_object_types: bool | None
    unified_text_diff: str


@dataclass(slots=True)
class AdoptionAssessment:
    code: str
    title: str
    explanation: str
    can_adopt: bool
    editable_page_id: str | None
    blocking_reasons: list[str] = field(default_factory=list)


@dataclass(slots=True)
class CandidateAdoptionResult:
    assessment_code: str
    selection_changed: bool
    editable_page_id: str
    objects_activated: int
    objects_retired: int


@dataclass(slots=True)
class ManualCandidateResolutionResult:
    selection_changed: bool
    editable_page_id: str
    retained_objects: int
    candidate_objects_not_imported: int


@dataclass(slots=True)
class RegionalTextReplacementResult:
    editable_page_id: str
    editable_object_id: str
    regional_object_id: str
    regional_run_id: str
    previous_text: str
    replacement_text: str


@dataclass(slots=True)
class RegionalObjectAdditionResult:
    editable_page_id: str
    editable_object_id: str
    regional_object_id: str
    regional_run_id: str
    added_text: str


@dataclass(slots=True)
class BulkReviewPreparationResult:
    source_key: str
    run_id: str
    pages_available: int
    pages_already_initialized: int
    pages_initialized: int
    selections_changed: int
    objects_created: int


@dataclass(slots=True)
class PageHistoryRow:
    occurred_at: datetime
    category: str
    operation: str
    title: str
    actor: str
    note: str | None
    object_id: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


def _registration(
    session: Session, source_key: str, *, digital_object_id: str | None = None
) -> tuple[SourceRegistration, DigitalObject, ArchivalUnit]:
    statement = (
        select(SourceRegistration, DigitalObject, ArchivalUnit)
        .join(DigitalObject, SourceRegistration.digital_object_id == DigitalObject.id)
        .join(ArchivalUnit, SourceRegistration.archival_unit_id == ArchivalUnit.id)
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
            "La operación necesita la identidad concreta del documento."
        )
    row = rows[0]
    return row[0], row[1], row[2]


def _candidate_page(
    session: Session,
    *,
    digital_object_id: str,
    page: int,
    run_id: str,
) -> tuple[ExtractionRun, ExtractionPage]:
    run = session.get(ExtractionRun, run_id)
    if run is None or run.digital_object_id != digital_object_id:
        raise ValueError("La extracción elegida no pertenece al documento seleccionado")
    if run.status not in {"completed", "completed_with_warnings"}:
        raise ValueError("La extracción elegida todavía no está completada")
    extraction_page = session.scalar(
        select(ExtractionPage).where(
            ExtractionPage.extraction_run_id == run.id,
            ExtractionPage.page_number == page,
        )
    )
    if extraction_page is None:
        raise ValueError(f"La extracción elegida no contiene la página {page}")
    if extraction_page.status not in {"completed", "completed_with_warnings"}:
        raise ValueError(f"La página {page} no terminó correctamente en esa corrida")
    return run, extraction_page


def _preview_path(
    session: Session,
    *,
    project_root: Path,
    digital_object_id: str,
    extraction_page: ExtractionPage,
) -> Path | None:
    asset = (
        session.get(DerivativeAsset, extraction_page.source_asset_id)
        if extraction_page.source_asset_id
        else None
    )
    if asset is None:
        preprocessing = session.scalar(
            select(PreprocessingRun)
            .where(
                PreprocessingRun.digital_object_id == digital_object_id,
                PreprocessingRun.status.in_(("completed", "completed_with_warnings")),
            )
            .order_by(PreprocessingRun.is_current.desc(), PreprocessingRun.created_at.desc())
        )
        if preprocessing is not None:
            asset = session.scalar(
                select(DerivativeAsset).where(
                    DerivativeAsset.preprocessing_run_id == preprocessing.id,
                    DerivativeAsset.page_number == extraction_page.page_number,
                    DerivativeAsset.kind == "preview",
                )
            )
    if asset is None:
        return None
    path = project_root / asset.relative_path
    return path if path.is_file() else None


def _version_row(
    session: Session,
    *,
    project_root: Path,
    digital: DigitalObject,
    run: ExtractionRun,
    extraction_page: ExtractionPage,
    selection: ExtractionPageSelection | None,
    editable_page: EditablePage | None,
) -> CandidatePageVersion:
    objects = session.scalars(
        select(ExtractedObject)
        .where(
            ExtractedObject.extraction_run_id == run.id,
            ExtractedObject.page_number == extraction_page.page_number,
        )
        .order_by(ExtractedObject.order_index, ExtractedObject.id)
    ).all()
    rows = [
        CandidateObjectRow(
            object_id=item.id,
            order_index=item.order_index,
            object_type=item.object_type,
            text=item.original_text,
            geometry=list(item.geometry_json or []),
            confidence=item.confidence,
            source_label=item.source_label,
        )
        for item in objects
    ]
    return CandidatePageVersion(
        run_id=run.id,
        page_id=extraction_page.id,
        profile_key=run.profile_key,
        engine=run.engine,
        status=extraction_page.status,
        quality_status=run.quality_status,
        quality_score=run.quality_score,
        created_at=run.created_at,
        object_count=len(rows),
        character_count=sum(len(item.text) for item in rows),
        text="\n\n".join(item.text for item in rows if item.text),
        objects=rows,
        preview_path=_preview_path(
            session,
            project_root=project_root,
            digital_object_id=digital.id,
            extraction_page=extraction_page,
        ),
        is_selected=bool(selection and selection.extraction_page_id == extraction_page.id),
        is_editable_source=bool(
            editable_page and editable_page.source_extraction_page_id == extraction_page.id
        ),
        automatic_quality=latest_page_quality_assessment(session, extraction_page.id),
    )


def compare_candidate_page(
    session: Session,
    *,
    project_root: str | Path,
    source_key: str,
    page: int,
    candidate_run_id: str,
    digital_object_id: str | None = None,
) -> CandidatePageComparison:
    _source, digital, unit = _registration(
        session, source_key, digital_object_id=digital_object_id
    )
    candidate_run, candidate_page = _candidate_page(
        session,
        digital_object_id=digital.id,
        page=page,
        run_id=candidate_run_id,
    )
    selection = session.scalar(
        select(ExtractionPageSelection).where(
            ExtractionPageSelection.digital_object_id == digital.id,
            ExtractionPageSelection.page_number == page,
        )
    )
    editable_page = session.scalar(
        select(EditablePage).where(
            EditablePage.digital_object_id == digital.id,
            EditablePage.page_number == page,
        )
    )
    root = Path(project_root).resolve()
    candidate = _version_row(
        session,
        project_root=root,
        digital=digital,
        run=candidate_run,
        extraction_page=candidate_page,
        selection=selection,
        editable_page=editable_page,
    )
    current: CandidatePageVersion | None = None
    if selection is not None:
        current_run = session.get(ExtractionRun, selection.extraction_run_id)
        current_page = session.get(ExtractionPage, selection.extraction_page_id)
        if current_run is not None and current_page is not None:
            current = _version_row(
                session,
                project_root=root,
                digital=digital,
                run=current_run,
                extraction_page=current_page,
                selection=selection,
                editable_page=editable_page,
            )

    editable_objects = _page_objects(session, editable_page.id) if editable_page else []
    editable_active = [item for item in editable_objects if item.lifecycle_status == "active"]
    editable_text = (
        "\n\n".join(item.current_text for item in editable_active if item.current_text)
        if editable_page is not None
        else None
    )

    if current is None:
        similarity = None
        object_delta = None
        character_delta = None
        changed_types = None
        diff = ""
    else:
        similarity = SequenceMatcher(None, current.text, candidate.text).ratio()
        object_delta = candidate.object_count - current.object_count
        character_delta = candidate.character_count - current.character_count
        changed_types = [item.object_type for item in current.objects] != [
            item.object_type for item in candidate.objects
        ]
        diff = "\n".join(
            unified_diff(
                current.text.splitlines(),
                candidate.text.splitlines(),
                fromfile="selección vigente",
                tofile="candidata",
                lineterm="",
            )
        )
    return CandidatePageComparison(
        source_key=source_key,
        title=unit.title,
        page=page,
        current=current,
        candidate=candidate,
        editable_text=editable_text,
        editable_object_count=len(editable_active),
        editable_status=editable_page.status if editable_page is not None else None,
        text_similarity=similarity,
        object_delta=object_delta,
        character_delta=character_delta,
        changed_object_types=changed_types,
        unified_text_diff=diff,
    )


def _page_objects(session: Session, editable_page_id: str) -> list[EditableObject]:
    return session.scalars(
        select(EditableObject)
        .where(EditableObject.editable_page_id == editable_page_id)
        .order_by(EditableObject.current_order_index, EditableObject.id)
    ).all()


def assess_candidate_adoption(
    session: Session,
    *,
    source_key: str,
    page: int,
    candidate_run_id: str,
    digital_object_id: str | None = None,
) -> AdoptionAssessment:
    _source, digital, _unit = _registration(
        session, source_key, digital_object_id=digital_object_id
    )
    _run, candidate_page = _candidate_page(
        session,
        digital_object_id=digital.id,
        page=page,
        run_id=candidate_run_id,
    )
    editable_page = session.scalar(
        select(EditablePage).where(
            EditablePage.digital_object_id == digital.id,
            EditablePage.page_number == page,
        )
    )
    if editable_page is None:
        return AdoptionAssessment(
            code=ADOPTION_NOT_INITIALIZED,
            title="La página todavía no fue editada",
            explanation=(
                "Podés elegir esta extracción y enviar la página a Revisar documentos sin reemplazar trabajo previo."
            ),
            can_adopt=True,
            editable_page_id=None,
        )
    if editable_page.source_extraction_page_id == candidate_page.id:
        return AdoptionAssessment(
            code=ADOPTION_ALREADY,
            title="Esta extracción ya es la que usa Revisar documentos",
            explanation="No hace falta volver a aplicarla.",
            can_adopt=False,
            editable_page_id=editable_page.id,
        )

    objects = _page_objects(session, editable_page.id)
    object_ids = [item.id for item in objects]
    reasons: list[str] = []
    if editable_page.review_status != "unreviewed" or editable_page.review_note:
        reasons.append("la página ya tiene un estado o una nota de revisión")
    if editable_page.reviewed_by or editable_page.reviewed_at:
        reasons.append("la página ya fue revisada por una persona")
    if any(item.review_status != "unreviewed" for item in objects):
        reasons.append("hay objetos con estado de revisión")
    if any(item.source_extracted_object_id is None for item in objects):
        reasons.append("hay objetos agregados manualmente")
    if any(item.document_part_id is not None for item in objects):
        reasons.append("hay objetos asignados a partes documentales")

    if object_ids:
        revisions = session.scalars(
            select(EditableObjectRevision).where(
                EditableObjectRevision.editable_object_id.in_(object_ids)
            )
        ).all()
        if any(item.operation not in _SAFE_OBJECT_OPERATIONS for item in revisions):
            reasons.append("hay correcciones o cambios estructurales")
        if session.scalar(
            select(func.count())
            .select_from(EditableObjectComment)
            .where(EditableObjectComment.editable_object_id.in_(object_ids))
        ):
            reasons.append("hay comentarios")
        if session.scalar(
            select(func.count())
            .select_from(EditableObjectTag)
            .where(EditableObjectTag.editable_object_id.in_(object_ids))
        ):
            reasons.append("hay etiquetas")
        if session.scalar(
            select(func.count())
            .select_from(EntityMention)
            .where(EntityMention.editable_object_id.in_(object_ids))
        ):
            reasons.append("hay menciones de entidades")
    if session.scalar(
        select(func.count())
        .select_from(EditablePageAction)
        .where(EditablePageAction.editable_page_id == editable_page.id)
    ):
        reasons.append("hay acciones de división, unión, ordenamiento o deshacer/rehacer")

    reasons = list(dict.fromkeys(reasons))
    if reasons:
        return AdoptionAssessment(
            code=ADOPTION_MANUAL,
            title="La edición existente debe conservarse",
            explanation=(
                "Podés elegir otra extracción para la página, pero Archive Workbench no reemplazará automáticamente el texto que ya fue revisado. Compará ambas versiones y decidí cómo conservar los cambios."
            ),
            can_adopt=False,
            editable_page_id=editable_page.id,
            blocking_reasons=reasons,
        )
    return AdoptionAssessment(
        code=ADOPTION_SAFE,
        title="La página puede actualizarse con esta extracción",
        explanation=(
            "No se detectó trabajo revisado. La extracción anterior quedará en el historial y esta pasará a ser la usada en Revisar documentos."
        ),
        can_adopt=True,
        editable_page_id=editable_page.id,
    )


def _editable_attributes(source: ExtractedObject) -> dict[str, Any]:
    return {
        **(source.attributes_json or {}),
        "source_label": source.source_label,
        "source_confidence": source.confidence,
        "source_language": source.language,
    }


def adopt_candidate_page(
    session: Session,
    *,
    decisions: ProjectDecisions,
    source_key: str,
    page: int,
    candidate_run_id: str,
    adopted_by: str,
    note: str | None = None,
    digital_object_id: str | None = None,
) -> CandidateAdoptionResult:
    assessment = assess_candidate_adoption(
        session,
        source_key=source_key,
        page=page,
        candidate_run_id=candidate_run_id,
        digital_object_id=digital_object_id,
    )
    if not assessment.can_adopt:
        raise ValueError(assessment.explanation)
    _source, digital, _unit = _registration(
        session, source_key, digital_object_id=digital_object_id
    )
    run, candidate_page = _candidate_page(
        session,
        digital_object_id=digital.id,
        page=page,
        run_id=candidate_run_id,
    )
    _selected_run, changed = select_extraction_pages(
        session,
        source_key=source_key,
        selected_by=adopted_by,
        run_id=run.id,
        pages={page},
        note=note or "Extracción aplicada desde la comparación por página",
        digital_object_id=digital.id,
    )
    selection = session.scalar(
        select(ExtractionPageSelection).where(
            ExtractionPageSelection.digital_object_id == digital.id,
            ExtractionPageSelection.page_number == page,
        )
    )
    if selection is None:
        raise RuntimeError("No pudo guardarse la extracción elegida para la página")

    if assessment.code == ADOPTION_NOT_INITIALIZED:
        summary = bootstrap_editable_layer(
            session,
            decisions=decisions,
            created_by=adopted_by,
            source_keys={source_key},
            digital_object_ids={digital.id},
            pages={page},
        )
        editable_page = session.scalar(
            select(EditablePage).where(
                EditablePage.digital_object_id == digital.id,
                EditablePage.page_number == page,
            )
        )
        if editable_page is None:
            raise RuntimeError("No pudo inicializarse la página editable")
        return CandidateAdoptionResult(
            assessment_code=assessment.code,
            selection_changed=bool(changed),
            editable_page_id=editable_page.id,
            objects_activated=summary.objects_created,
            objects_retired=0,
        )

    editable_page = session.get(EditablePage, assessment.editable_page_id)
    if editable_page is None:
        raise RuntimeError("La página editable dejó de existir durante la adopción")
    candidate_objects = session.scalars(
        select(ExtractedObject)
        .where(
            ExtractedObject.extraction_run_id == run.id,
            ExtractedObject.page_number == page,
        )
        .order_by(ExtractedObject.order_index, ExtractedObject.id)
    ).all()
    current_objects = _page_objects(session, editable_page.id)
    by_source = {
        item.source_extracted_object_id: item
        for item in current_objects
        if item.source_extracted_object_id is not None
    }
    candidate_ids = {item.id for item in candidate_objects}
    retired = 0
    for obj in current_objects:
        if obj.lifecycle_status == "active" and obj.source_extracted_object_id not in candidate_ids:
            base = obj.revision_number
            obj.lifecycle_status = "deleted"
            obj.revision_number += 1
            obj.updated_by = adopted_by
            obj.updated_at = utc_now()
            _append_revision(
                session,
                obj,
                operation="source_replaced",
                created_by=adopted_by,
                note="Retirado al aplicar otra extracción de texto.",
                base_revision_number=base,
            )
            retired += 1

    activated = 0
    allowed_types = {item.key for item in decisions.object_types}
    for source in candidate_objects:
        object_type = source.object_type if source.object_type in allowed_types else "paragraph"
        _allowed_object_type(decisions, object_type)
        existing = by_source.get(source.id)
        if existing is None:
            existing = EditableObject(
                id=new_id(),
                editable_page_id=editable_page.id,
                digital_object_id=digital.id,
                page_number=page,
                source_extracted_object_id=source.id,
                source_origin_id=source.origin_id,
                current_text=source.original_text,
                current_object_type=object_type,
                current_order_index=source.order_index,
                current_geometry_json=source.geometry_json or [],
                current_attributes_json=_editable_attributes(source),
                lifecycle_status="active",
                review_status="unreviewed",
                revision_number=1,
                created_by=adopted_by,
                created_at=utc_now(),
                updated_by=adopted_by,
                updated_at=utc_now(),
            )
            session.add(existing)
            session.flush()
            _append_revision(
                session,
                existing,
                operation="import",
                created_by=adopted_by,
                note="Importado al aplicar otra extracción de texto.",
                base_revision_number=None,
            )
        else:
            base = existing.revision_number
            existing.current_text = source.original_text
            existing.current_object_type = object_type
            existing.current_order_index = source.order_index
            existing.current_geometry_json = source.geometry_json or []
            existing.current_attributes_json = _editable_attributes(source)
            existing.lifecycle_status = "active"
            existing.review_status = "unreviewed"
            existing.document_part_id = None
            existing.revision_number += 1
            existing.updated_by = adopted_by
            existing.updated_at = utc_now()
            _append_revision(
                session,
                existing,
                operation="candidate_adopted",
                created_by=adopted_by,
                note="Reactivado desde una extracción de texto previamente conservada.",
                base_revision_number=base,
            )
        activated += 1

    base_page_revision = editable_page.revision_number
    previous_page_id = editable_page.source_extraction_page_id
    previous_run_id = editable_page.source_extraction_run_id
    editable_page.source_extraction_run_id = run.id
    editable_page.source_extraction_page_id = candidate_page.id
    editable_page.source_selection_id = selection.id
    editable_page.status = "active"
    editable_page.review_status = "unreviewed"
    editable_page.review_note = None
    editable_page.reviewed_by = None
    editable_page.reviewed_at = None
    editable_page.revision_number += 1
    editable_page.updated_at = utc_now()
    _append_page_revision(
        session,
        editable_page,
        operation="candidate_adopted",
        created_by=adopted_by,
        note=note or "Extracción de texto aplicada a la página editable.",
        details={
            "previous_extraction_run_id": previous_run_id,
            "previous_extraction_page_id": previous_page_id,
            "objects_activated": activated,
            "objects_retired": retired,
        },
        base_revision_number=base_page_revision,
    )
    session.flush()
    return CandidateAdoptionResult(
        assessment_code=assessment.code,
        selection_changed=bool(changed),
        editable_page_id=editable_page.id,
        objects_activated=activated,
        objects_retired=retired,
    )


def resolve_candidate_keep_edits(
    session: Session,
    *,
    source_key: str,
    page: int,
    candidate_run_id: str,
    resolved_by: str,
    note: str | None = None,
    digital_object_id: str | None = None,
) -> ManualCandidateResolutionResult:
    """Vincula una candidata nueva sin alterar ningún objeto editable existente."""
    assessment = assess_candidate_adoption(
        session,
        source_key=source_key,
        page=page,
        candidate_run_id=candidate_run_id,
        digital_object_id=digital_object_id,
    )
    if assessment.code != ADOPTION_MANUAL or assessment.editable_page_id is None:
        raise ValueError(
            "Esta resolución solo corresponde cuando existe trabajo revisado que debe conservarse."
        )
    _source, digital, _unit = _registration(
        session, source_key, digital_object_id=digital_object_id
    )
    run, candidate_page = _candidate_page(
        session,
        digital_object_id=digital.id,
        page=page,
        run_id=candidate_run_id,
    )
    editable_page = session.get(EditablePage, assessment.editable_page_id)
    if editable_page is None:
        raise RuntimeError("La página editable dejó de existir durante la resolución")

    previous_run_id = editable_page.source_extraction_run_id
    previous_page_id = editable_page.source_extraction_page_id
    previous_status = editable_page.status
    editable_objects = _page_objects(session, editable_page.id)
    retained_ids = [item.id for item in editable_objects]
    candidate_ids = session.scalars(
        select(ExtractedObject.id)
        .where(
            ExtractedObject.extraction_run_id == run.id,
            ExtractedObject.page_number == page,
        )
        .order_by(ExtractedObject.order_index, ExtractedObject.id)
    ).all()

    _selected_run, changed = select_extraction_pages(
        session,
        source_key=source_key,
        selected_by=resolved_by,
        run_id=run.id,
        pages={page},
        note=note or "Extracción vinculada conservando la edición revisada existente.",
    )
    selection = session.scalar(
        select(ExtractionPageSelection).where(
            ExtractionPageSelection.digital_object_id == digital.id,
            ExtractionPageSelection.page_number == page,
        )
    )
    if selection is None:
        raise RuntimeError("No pudo guardarse la extracción elegida para la página")

    base_page_revision = editable_page.revision_number
    editable_page.source_extraction_run_id = run.id
    editable_page.source_extraction_page_id = candidate_page.id
    editable_page.source_selection_id = selection.id
    editable_page.status = "active"
    editable_page.revision_number += 1
    editable_page.updated_at = utc_now()
    _append_page_revision(
        session,
        editable_page,
        operation="manual_keep_edits",
        created_by=resolved_by,
        note=note or "Se conservó íntegramente la edición revisada al vincular la nueva extracción.",
        details={
            "strategy": "keep_existing_editable_objects",
            "previous_extraction_run_id": previous_run_id,
            "previous_extraction_page_id": previous_page_id,
            "previous_status": previous_status,
            "retained_editable_object_ids": retained_ids,
            "candidate_object_ids_not_imported": list(candidate_ids),
        },
        base_revision_number=base_page_revision,
    )
    session.flush()
    return ManualCandidateResolutionResult(
        selection_changed=bool(changed),
        editable_page_id=editable_page.id,
        retained_objects=len(retained_ids),
        candidate_objects_not_imported=len(candidate_ids),
    )


def prepare_candidate_run_for_review(
    session: Session,
    *,
    decisions: ProjectDecisions,
    source_key: str,
    run_id: str,
    created_by: str,
    digital_object_id: str | None = None,
    note: str | None = None,
) -> BulkReviewPreparationResult:
    """Usa un resultado general como texto inicial en páginas aún no enviadas a revisión.

    Las páginas que ya tienen una capa editable se omiten.
    """
    _source, digital, _unit = _registration(
        session, source_key, digital_object_id=digital_object_id
    )
    run = session.get(ExtractionRun, run_id)
    if run is None or run.digital_object_id != digital.id:
        raise ValueError("El resultado de extracción no pertenece al documento elegido.")
    if run.status not in {"completed", "completed_with_warnings"}:
        raise ValueError("El resultado de extracción todavía no está completado.")
    if run.engine == "tesseract_regions":
        raise ValueError(
            "Una lectura parcial de la página no puede usarse para enviar la página completa a Revisar documentos."
        )

    run_pages = set(
        session.scalars(
            select(ExtractionPage.page_number).where(
                ExtractionPage.extraction_run_id == run.id,
                ExtractionPage.status.in_(["completed", "completed_with_warnings"]),
            )
        ).all()
    )
    if not run_pages:
        raise ValueError("El resultado elegido no contiene páginas completadas.")
    initialized_pages = set(
        session.scalars(
            select(EditablePage.page_number).where(
                EditablePage.digital_object_id == digital.id
            )
        ).all()
    )
    target_pages = run_pages - initialized_pages
    if not target_pages:
        return BulkReviewPreparationResult(
            source_key=source_key,
            run_id=run.id,
            pages_available=len(run_pages),
            pages_already_initialized=len(run_pages & initialized_pages),
            pages_initialized=0,
            selections_changed=0,
            objects_created=0,
        )

    _selected_run, changed = select_extraction_pages(
        session,
        source_key=source_key,
        selected_by=created_by,
        run_id=run.id,
        pages=target_pages,
        note=note
        or "Extracción elegida explícitamente para enviar páginas pendientes a Revisar documentos.",
        digital_object_id=digital.id,
    )
    summary = bootstrap_editable_layer(
        session,
        decisions=decisions,
        created_by=created_by,
        source_keys={source_key},
        digital_object_ids={digital.id},
        pages=target_pages,
    )
    return BulkReviewPreparationResult(
        source_key=source_key,
        run_id=run.id,
        pages_available=len(run_pages),
        pages_already_initialized=len(run_pages & initialized_pages),
        pages_initialized=summary.pages_created,
        selections_changed=int(changed),
        objects_created=summary.objects_created,
    )


def replace_editable_object_text_from_regional_candidate(
    session: Session,
    *,
    source_key: str,
    page: int,
    candidate_run_id: str,
    editable_object_id: str,
    regional_object_id: str,
    changed_by: str,
    digital_object_id: str | None = None,
    note: str | None = None,
) -> RegionalTextReplacementResult:
    """Reemplaza sólo el texto de un objeto editable usando un resultado OCR regional.

    La selección de extracción de la página y el origen de su capa editable no cambian.
    La procedencia regional se conserva dentro de los atributos versionados del objeto.
    """
    _source, digital, _unit = _registration(
        session, source_key, digital_object_id=digital_object_id
    )
    run, _candidate_page_row = _candidate_page(
        session,
        digital_object_id=digital.id,
        page=page,
        run_id=candidate_run_id,
    )
    if run.engine != "tesseract_regions":
        raise ValueError(
            "Esta acción sólo puede usar texto recuperado al volver a leer una parte concreta de la página."
        )

    editable_page = session.scalar(
        select(EditablePage).where(
            EditablePage.digital_object_id == digital.id,
            EditablePage.page_number == page,
        )
    )
    if editable_page is None:
        raise ValueError(
            "La página todavía no está en Revisar documentos. Elegí primero una extracción completa para esa página."
        )

    editable = session.get(EditableObject, editable_object_id)
    if (
        editable is None
        or editable.editable_page_id != editable_page.id
        or editable.lifecycle_status != "active"
    ):
        raise ValueError("El fragmento de texto elegido ya no está activo en esta página.")

    regional = session.get(ExtractedObject, regional_object_id)
    if (
        regional is None
        or regional.extraction_run_id != run.id
        or regional.page_number != page
    ):
        raise ValueError("El texto recuperado que elegiste no pertenece a esta página.")
    replacement = regional.original_text
    if not replacement.strip():
        raise ValueError("La lectura parcial elegida no recuperó texto para hacer la corrección.")

    previous_text = editable.current_text
    base = editable.revision_number
    attributes = dict(editable.current_attributes_json or {})
    history = list(attributes.get("regional_ocr_text_replacements") or [])
    regional_attributes = dict(regional.attributes_json or {})
    history.append(
        {
            "regional_run_id": run.id,
            "regional_object_id": regional.id,
            "regional_profile_key": run.profile_key,
            "region_key": regional_attributes.get("region_key"),
            "region_label": regional_attributes.get("region_label"),
            "previous_text": previous_text,
        }
    )
    attributes["regional_ocr_text_replacements"] = history
    editable.current_text = replacement
    editable.current_attributes_json = attributes
    editable.revision_number += 1
    editable.updated_by = changed_by
    editable.updated_at = utc_now()
    _append_revision(
        session,
        editable,
        operation="regional_ocr_replace",
        created_by=changed_by,
        note=note
        or (
            "Texto corregido con una lectura parcial de la página; "
            f"origen regional {run.id}."
        ),
        base_revision_number=base,
    )
    session.flush()
    return RegionalTextReplacementResult(
        editable_page_id=editable_page.id,
        editable_object_id=editable.id,
        regional_object_id=regional.id,
        regional_run_id=run.id,
        previous_text=previous_text,
        replacement_text=replacement,
    )


def add_editable_object_from_regional_candidate(
    session: Session,
    *,
    decisions: ProjectDecisions,
    source_key: str,
    page: int,
    candidate_run_id: str,
    regional_object_id: str,
    object_type: str,
    changed_by: str,
    after_object_id: str | None = None,
    before_object_id: str | None = None,
    geometry: list[dict[str, Any]] | None = None,
    digital_object_id: str | None = None,
    note: str | None = None,
) -> RegionalObjectAdditionResult:
    """Agrega texto recuperado de una parte de la página como objeto editable.

    La procedencia del reconocimiento parcial se conserva aunque la persona dibuje
    explícitamente otra caja para ubicar el nuevo objeto en la página.
    """
    _source, digital, _unit = _registration(
        session, source_key, digital_object_id=digital_object_id
    )
    run, _candidate_page_row = _candidate_page(
        session,
        digital_object_id=digital.id,
        page=page,
        run_id=candidate_run_id,
    )
    if run.engine != "tesseract_regions":
        raise ValueError(
            "Esta acción sólo puede usar texto recuperado al volver a leer una parte concreta de la página."
        )

    editable_page = session.scalar(
        select(EditablePage).where(
            EditablePage.digital_object_id == digital.id,
            EditablePage.page_number == page,
        )
    )
    if editable_page is None:
        raise ValueError(
            "La página todavía no está en Revisar documentos. Elegí primero una extracción completa para esa página."
        )

    regional = session.get(ExtractedObject, regional_object_id)
    if (
        regional is None
        or regional.extraction_run_id != run.id
        or regional.page_number != page
    ):
        raise ValueError("El texto recuperado que elegiste no pertenece a esta página.")
    added_text = regional.original_text
    if not added_text.strip():
        raise ValueError("La lectura parcial elegida no recuperó texto para agregar.")

    regional_attributes = dict(regional.attributes_json or {})
    source_geometry = list(regional.geometry_json or [])
    target_geometry = list(geometry) if geometry is not None else source_geometry
    provenance = {
        "regional_run_id": run.id,
        "regional_object_id": regional.id,
        "regional_profile_key": run.profile_key,
        "region_key": regional_attributes.get("region_key"),
        "region_label": regional_attributes.get("region_label"),
        "source_geometry": source_geometry,
        "placement_geometry_defined_by_user": geometry is not None,
    }
    editable = add_editable_object(
        session,
        decisions=decisions,
        source_key=source_key,
        page=page,
        object_type=object_type,
        text=added_text,
        created_by=changed_by,
        after_object_id=after_object_id,
        before_object_id=before_object_id,
        note=note
        or (
            "Texto agregado a partir de una lectura parcial de la página; "
            f"origen regional {run.id}."
        ),
        geometry=target_geometry,
        attributes={
            "regional_ocr_added": True,
            "regional_ocr_source": provenance,
        },
        revision_operation="regional_ocr_add",
    )
    session.flush()
    return RegionalObjectAdditionResult(
        editable_page_id=editable_page.id,
        editable_object_id=editable.id,
        regional_object_id=regional.id,
        regional_run_id=run.id,
        added_text=added_text,
    )


def _object_label(obj: EditableObject | None) -> str:
    if obj is None:
        return "Objeto"
    text = " ".join((obj.current_text or "").split())
    return text[:70] + ("…" if len(text) > 70 else "") or f"Objeto {obj.current_order_index + 1}"


def page_history_rows(
    session: Session,
    *,
    source_key: str,
    page: int,
) -> list[PageHistoryRow]:
    _source, digital, _unit = _registration(session, source_key)
    rows: list[PageHistoryRow] = []
    selection_revisions = session.scalars(
        select(ExtractionPageSelectionRevision)
        .where(
            ExtractionPageSelectionRevision.digital_object_id == digital.id,
            ExtractionPageSelectionRevision.page_number == page,
        )
        .order_by(ExtractionPageSelectionRevision.created_at)
    ).all()
    for item in selection_revisions:
        rows.append(
            PageHistoryRow(
                occurred_at=item.created_at,
                category="Selección OCR",
                operation=item.operation,
                title=(
                    "Se eligió una extracción para la página"
                    if item.previous_extraction_page_id is None
                    else "Se cambió la extracción seleccionada"
                ),
                actor=item.selected_by,
                note=item.note,
                details={
                    "run_id": item.extraction_run_id,
                    "page_id": item.extraction_page_id,
                    "previous_run_id": item.previous_extraction_run_id,
                    "previous_page_id": item.previous_extraction_page_id,
                },
            )
        )

    editable_page = session.scalar(
        select(EditablePage).where(
            EditablePage.digital_object_id == digital.id,
            EditablePage.page_number == page,
        )
    )
    if editable_page is None:
        return sorted(rows, key=lambda item: item.occurred_at, reverse=True)

    page_revisions = session.scalars(
        select(EditablePageRevision)
        .where(EditablePageRevision.editable_page_id == editable_page.id)
        .order_by(EditablePageRevision.created_at)
    ).all()
    page_titles = {
        "bootstrap": "Se inicializó la página editable",
        "import": "Se incorporó el estado editable existente",
        "mark_stale": "La edición quedó desactualizada",
        "reactivate": "La edición volvió a coincidir con la selección",
        "candidate_adopted": "Se aplicó otra extracción al texto de revisión",
        "manual_keep_edits": "Se vinculó otra extracción conservando la edición existente",
        "rebase": "Se trasladó la edición revisada a otra extracción",
        "review_status": "Cambió el estado de revisión de la página",
    }
    for item in page_revisions:
        rows.append(
            PageHistoryRow(
                occurred_at=item.created_at,
                category="Página editable",
                operation=item.operation,
                title=page_titles.get(item.operation, item.operation.replace("_", " ").capitalize()),
                actor=item.created_by,
                note=item.note,
                details={
                    "revision": item.revision_number,
                    "status": item.status,
                    "review_status": item.review_status,
                    "source_run_id": item.source_extraction_run_id,
                    "source_page_id": item.source_extraction_page_id,
                    **(item.details_json or {}),
                },
            )
        )

    objects = _page_objects(session, editable_page.id)
    object_by_id = {item.id: item for item in objects}
    object_ids = list(object_by_id)
    if object_ids:
        revisions = session.scalars(
            select(EditableObjectRevision)
            .where(EditableObjectRevision.editable_object_id.in_(object_ids))
            .order_by(EditableObjectRevision.created_at)
        ).all()
        object_titles = {
            "import": "Se importó un objeto desde OCR",
            "create": "Se agregó un objeto",
            "edit": "Se corrigió un objeto",
            "reorder": "Se cambió el orden de un objeto",
            "split": "Se dividió un objeto",
            "merge": "Se combinaron objetos",
            "delete": "Se eliminó un objeto",
            "restore": "Se restauró un objeto",
            "revert": "Se restauró una revisión anterior",
            "source_replaced": "El objeto quedó en una base OCR anterior",
            "candidate_adopted": "El fragmento de texto volvió a activarse desde otra extracción",
            "regional_ocr_replace": "Se corrigió el fragmento con una lectura parcial de la página",
            "regional_ocr_add": "Se agregó texto recuperado de una parte de la página",
            "rebase_import": "Se creó un fragmento de texto al trasladar la edición",
            "rebase_retired": "El fragmento anterior quedó retirado al trasladar la edición",
            "undo": "Se deshizo un cambio del objeto",
            "redo": "Se rehízo un cambio del objeto",
        }
        for item in revisions:
            obj = object_by_id.get(item.editable_object_id)
            rows.append(
                PageHistoryRow(
                    occurred_at=item.created_at,
                    category="Objeto",
                    operation=item.operation,
                    title=object_titles.get(
                        item.operation, item.operation.replace("_", " ").capitalize()
                    ),
                    actor=item.created_by,
                    note=item.note,
                    object_id=item.editable_object_id,
                    details={
                        "revision": item.revision_number,
                        "object": _object_label(obj),
                        "object_type": item.object_type,
                        "order": item.order_index + 1,
                        "lifecycle_status": item.lifecycle_status,
                    },
                )
            )

        comments = session.scalars(
            select(EditableObjectComment).where(
                EditableObjectComment.editable_object_id.in_(object_ids)
            )
        ).all()
        for item in comments:
            rows.append(
                PageHistoryRow(
                    occurred_at=item.created_at,
                    category="Anotación",
                    operation="comment",
                    title="Se agregó un comentario",
                    actor=item.created_by,
                    note=item.body,
                    object_id=item.editable_object_id,
                )
            )
        tags = session.scalars(
            select(EditableObjectTag).where(EditableObjectTag.editable_object_id.in_(object_ids))
        ).all()
        for item in tags:
            rows.append(
                PageHistoryRow(
                    occurred_at=item.created_at,
                    category="Anotación",
                    operation="tag",
                    title=f"Se agregó la etiqueta «{item.tag}»",
                    actor=item.created_by,
                    note=None,
                    object_id=item.editable_object_id,
                    details={"tag_kind": item.tag_kind},
                )
            )
        mention_revisions = session.execute(
            select(EntityMentionRevision, EntityMention)
            .join(EntityMention, EntityMentionRevision.mention_id == EntityMention.id)
            .where(EntityMention.editable_object_id.in_(object_ids))
        ).all()
        for revision, mention in mention_revisions:
            rows.append(
                PageHistoryRow(
                    occurred_at=revision.changed_at,
                    category="Entidad",
                    operation=revision.operation,
                    title=f"Cambió la mención «{mention.mention_text}»",
                    actor=revision.changed_by,
                    note=revision.note,
                    object_id=mention.editable_object_id,
                    details=revision.snapshot_json or {},
                )
            )

        review_events = session.scalars(
            select(ExchangeChangeEvent)
            .where(
                ExchangeChangeEvent.entity_type == "editable_object",
                ExchangeChangeEvent.entity_id.in_(object_ids),
            )
            .order_by(ExchangeChangeEvent.occurred_at)
        ).all()
        for event in review_events:
            changed = event.changed_fields_json or {}
            if "review_status" not in changed:
                continue
            rows.append(
                PageHistoryRow(
                    occurred_at=event.occurred_at,
                    category="Revisión",
                    operation="object_review_status",
                    title="Cambió el estado de revisión de un objeto",
                    actor=event.actor,
                    note=None,
                    object_id=event.entity_id,
                    details={"review_status": changed.get("review_status")},
                )
            )

    actions = session.scalars(
        select(EditablePageAction)
        .where(EditablePageAction.editable_page_id == editable_page.id)
        .order_by(EditablePageAction.created_at)
    ).all()
    for item in actions:
        rows.append(
            PageHistoryRow(
                occurred_at=item.created_at,
                category="Acción de página",
                operation=item.action_type,
                title=f"Se ejecutó: {item.action_type.replace('_', ' ')}",
                actor=item.created_by,
                note=item.note,
                object_id=item.selected_object_id,
                details={"sequence": item.sequence_number, "status": item.status},
            )
        )
        if item.undone_at is not None:
            rows.append(
                PageHistoryRow(
                    occurred_at=item.undone_at,
                    category="Acción de página",
                    operation="undo",
                    title="Se deshizo una acción de página",
                    actor=item.undone_by or "local_user",
                    note=item.note,
                    object_id=item.selected_object_id,
                    details={"sequence": item.sequence_number},
                )
            )
        if item.redone_at is not None:
            rows.append(
                PageHistoryRow(
                    occurred_at=item.redone_at,
                    category="Acción de página",
                    operation="redo",
                    title="Se rehízo una acción de página",
                    actor=item.redone_by or "local_user",
                    note=item.note,
                    object_id=item.selected_object_id,
                    details={"sequence": item.sequence_number},
                )
            )
    return sorted(rows, key=lambda item: item.occurred_at, reverse=True)


def _normalized_polygons(
    geometry: list[dict[str, Any]], *, page: int
) -> list[list[tuple[float, float]]]:
    polygons: list[list[tuple[float, float]]] = []
    for item in geometry:
        if item.get("page") not in {None, page}:
            continue
        polygon = item.get("polygon") or []
        if len(polygon) < 4 or item.get("coordinate_space", "normalized") != "normalized":
            continue
        try:
            points = [(float(point[0]), float(point[1])) for point in polygon]
        except (TypeError, ValueError, IndexError):
            continue
        if all(0 <= x <= 1 and 0 <= y <= 1 for x, y in points):
            polygons.append(points)
    return polygons


def render_candidate_overlay(
    image_path: str | Path,
    objects: list[CandidateObjectRow],
    *,
    page: int,
) -> Image.Image:
    """Dibuja el orden y la geometría de una candidata sin modificar el derivado."""
    with Image.open(image_path) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default()
    width, height = image.size
    for number, item in enumerate(objects, start=1):
        for polygon in _normalized_polygons(item.geometry, page=page):
            scaled = [(round(x * width), round(y * height)) for x, y in polygon]
            draw.line(scaled + [scaled[0]], fill="black", width=3)
            x, y = scaled[0]
            label = str(number)
            box = draw.textbbox((x, y), label, font=font)
            draw.rectangle((box[0] - 2, box[1] - 2, box[2] + 2, box[3] + 2), fill="white")
            draw.text((x, y), label, fill="black", font=font)
    return image
