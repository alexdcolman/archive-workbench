from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from archive_workbench.ai_handoff import (
    AIHandoffPreview,
    AIHandoffProposal,
    AIHandoffResolution,
    SUPPORTED_OUTPUT_SCHEMAS,
    VerifiedAIHandoffAsset,
    read_verified_ai_handoff_asset,
)
from archive_workbench.analysis_quality import ANALYSIS_QUALITY_POLICY_VERSION
from archive_workbench.db.models import (
    CorpusExportRun,
    ExternalAnalysisPackage,
    ExternalAnalysisPackageSource,
    ExternalAnalysisProposal,
    ExternalAnalysisReview,
    ExternalAnalysisSelection,
    SourceRegistration,
)
from archive_workbench.identity import new_id


class ExternalAnalysisError(ValueError):
    """Operación inválida sobre la capa persistente de análisis asistido."""


@dataclass(frozen=True)
class ExternalAnalysisProposalSummary:
    proposal_id: str
    package_id: str
    external_proposal_id: str
    target_id: str
    digital_object_id: str
    page_number: int
    source_key: str | None
    navigation_source_key: str | None
    original_filename: str | None
    output_schema_id: str
    warnings: tuple[str, ...]
    model_id: str | None
    producer_id: str | None
    producer_version: str | None
    imported_at: datetime
    status: str
    latest_review_id: str | None
    latest_revision: int | None
    latest_decision: str | None
    latest_reviewed_output: dict[str, Any] | None
    latest_reviewed_by: str | None
    latest_reviewed_at: datetime | None
    current_review_id: str | None


@dataclass(frozen=True)
class ExternalAnalysisProposalDetail:
    summary: ExternalAnalysisProposalSummary
    raw_output: dict[str, Any]
    provenance: dict[str, Any]
    latest_reviewed_output: dict[str, Any] | None
    latest_review_note: str | None


@dataclass(frozen=True)
class ExternalAnalysisHistoryRow:
    review_id: str
    proposal_id: str
    external_proposal_id: str
    target_id: str
    digital_object_id: str
    page_number: int
    source_key: str | None
    navigation_source_key: str | None
    original_filename: str | None
    output_schema_id: str
    reviewed_output: dict[str, Any] | None
    decision: str
    revision: int
    review_note: str | None
    reviewed_by: str
    reviewed_at: datetime
    model_id: str | None
    producer_id: str | None
    producer_version: str | None
    warnings: tuple[str, ...]
    is_current: bool


@dataclass(frozen=True)
class ExternalAnalysisPackageRow:
    package_id: str
    package_sha256: str
    producer_id: str | None
    producer_version: str | None
    model_id: str | None
    proposal_count: int
    imported_by: str
    imported_at: datetime
    exp01_sha256: str


@dataclass(frozen=True)
class ExternalAnalysisImportResult:
    package_id: str
    created: bool
    proposal_ids: tuple[str, ...]
    source_link_count: int


@dataclass(frozen=True)
class ExternalAnalysisReviewResult:
    review_id: str
    revision: int
    initial_selection_id: str | None


@dataclass(frozen=True)
class ExternalAnalysisSelectionResult:
    selection_id: str
    created: bool
    supersedes_selection_id: str | None


def _source_scope_snapshot(resolution: AIHandoffResolution) -> dict[str, Any]:
    usable = [row for row in resolution.source_matches if row.usable_for_incorporation]
    if not usable:
        raise ExternalAnalysisError("No existe una exportación de origen utilizable")
    snapshots = {
        (
            row.authorization.scope_key,
            tuple(row.authorization.page_review_statuses),
            row.authorization.broader_scope,
            row.authorization.parameters_sha256,
        )
        for row in usable
    }
    if len(snapshots) != 1:
        raise ExternalAnalysisError(
            "Las exportaciones equivalentes no conservan el mismo alcance de calidad"
        )
    scope_key, statuses, broader_scope, parameters_sha256 = next(iter(snapshots))
    return {
        "policy_version": ANALYSIS_QUALITY_POLICY_VERSION,
        "scope_key": scope_key,
        "page_review_statuses": list(statuses),
        "broader_scope": broader_scope,
        "parameters_sha256": parameters_sha256,
    }


def _resolution_by_proposal_id(resolution: AIHandoffResolution) -> dict[str, Any]:
    rows = {row.proposal_id: row for row in resolution.proposal_resolutions}
    if len(rows) != len(resolution.proposal_resolutions):
        raise ExternalAnalysisError("La resolución contiene proposal_id duplicados")
    return rows


def _validate_import(
    preview: AIHandoffPreview,
    resolution: AIHandoffResolution,
) -> dict[str, Any]:
    if not resolution.incorporation_allowed:
        detail = "; ".join(resolution.blocking_reasons) or "origen no incorporable"
        raise ExternalAnalysisError(f"El handoff no puede incorporarse: {detail}")
    resolved = _resolution_by_proposal_id(resolution)
    expected = {proposal.proposal_id for proposal in preview.proposals}
    if set(resolved) != expected:
        raise ExternalAnalysisError(
            "La resolución no corresponde exactamente al handoff inspeccionado"
        )
    for proposal_id, row in resolved.items():
        if not row.acceptance_ready or not row.source_asset_sha256:
            raise ExternalAnalysisError(f"{proposal_id} no conserva un asset de origen verificado")
    return resolved


def rebuild_external_analysis_package_sources(
    session: Session,
    *,
    package_id: str,
) -> int:
    """Reconstruye vínculos locales package→EXP-01 únicamente por SHA-256.

    El identificador ``export_run_id`` pertenece a la copia local y nunca se
    transporta como identidad canónica entre workspaces. Un paquete recibido
    por continuidad puede quedar con cero vínculos si esa copia todavía no
    contiene una corrida EXP-01 equivalente.
    """

    package = session.get(ExternalAnalysisPackage, package_id)
    if package is None:
        raise ExternalAnalysisError(f"No existe el paquete externo {package_id}")
    matching_run_ids = set(
        session.scalars(
            select(CorpusExportRun.id).where(
                CorpusExportRun.project_id == package.project_id,
                CorpusExportRun.output_sha256 == package.exp01_sha256,
            )
        ).all()
    )
    existing = session.scalars(
        select(ExternalAnalysisPackageSource).where(
            ExternalAnalysisPackageSource.package_id == package_id
        )
    ).all()
    for row in existing:
        if row.export_run_id not in matching_run_ids:
            session.delete(row)
    existing_run_ids = {
        row.export_run_id for row in existing if row.export_run_id in matching_run_ids
    }
    for run_id in sorted(matching_run_ids - existing_run_ids):
        session.add(
            ExternalAnalysisPackageSource(
                id=new_id(),
                package_id=package_id,
                export_run_id=run_id,
                match_kind="sha256_exact",
            )
        )
    session.flush()
    return len(matching_run_ids)


def _refresh_package_sources(
    session: Session,
    *,
    package_id: str,
    resolution: AIHandoffResolution,
) -> int:
    existing_run_ids = set(
        session.scalars(
            select(ExternalAnalysisPackageSource.export_run_id).where(
                ExternalAnalysisPackageSource.package_id == package_id
            )
        ).all()
    )
    for match in resolution.source_matches:
        if match.export_run_id in existing_run_ids:
            continue
        session.add(
            ExternalAnalysisPackageSource(
                id=new_id(),
                package_id=package_id,
                export_run_id=match.export_run_id,
                match_kind="sha256_exact",
            )
        )
        existing_run_ids.add(match.export_run_id)
    session.flush()
    return len(existing_run_ids)


def incorporate_ai_handoff(
    session: Session,
    *,
    project_id: str,
    preview: AIHandoffPreview,
    resolution: AIHandoffResolution,
    imported_by: str,
) -> ExternalAnalysisImportResult:
    """Incorpora raw + procedencia de forma transaccional e idempotente por package SHA."""

    if not imported_by.strip():
        raise ExternalAnalysisError("imported_by no puede quedar vacío")
    resolved = _validate_import(preview, resolution)
    existing = session.scalar(
        select(ExternalAnalysisPackage).where(
            ExternalAnalysisPackage.project_id == project_id,
            ExternalAnalysisPackage.package_sha256 == preview.sha256,
        )
    )
    if existing is not None:
        if (
            existing.package_type != preview.package_type
            or existing.schema_version != preview.schema_version
            or existing.protocol != preview.protocol
            or existing.exp01_sha256 != preview.exp01_sha256
            or existing.result_bundle_sha256 != preview.result_bundle_sha256
            or existing.proposal_count != preview.proposal_count
        ):
            raise ExternalAnalysisError(
                "El package SHA ya existe con metadatos incompatibles; la base requiere revisión"
            )
        source_link_count = _refresh_package_sources(
            session,
            package_id=existing.id,
            resolution=resolution,
        )
        existing_proposal_ids = tuple(
            session.scalars(
                select(ExternalAnalysisProposal.id)
                .where(ExternalAnalysisProposal.package_id == existing.id)
                .order_by(ExternalAnalysisProposal.created_at, ExternalAnalysisProposal.id)
            ).all()
        )
        if len(existing_proposal_ids) != preview.proposal_count:
            raise ExternalAnalysisError(
                "El paquete existente no conserva la cantidad esperada de propuestas"
            )
        return ExternalAnalysisImportResult(
            package_id=existing.id,
            created=False,
            proposal_ids=existing_proposal_ids,
            source_link_count=source_link_count,
        )

    package = ExternalAnalysisPackage(
        id=new_id(),
        project_id=project_id,
        package_sha256=preview.sha256,
        package_type=preview.package_type,
        schema_version=preview.schema_version,
        protocol=preview.protocol,
        producer_id=preview.producer_id,
        producer_version=preview.producer_version,
        request_id=preview.request_id,
        exp01_sha256=preview.exp01_sha256,
        result_bundle_sha256=preview.result_bundle_sha256,
        model_json=deepcopy(preview.model),
        runtime_json=deepcopy(preview.runtime),
        prompt_json=deepcopy(preview.prompt),
        source_scope_json=_source_scope_snapshot(resolution),
        proposal_count=preview.proposal_count,
        manifest_json=deepcopy(preview.manifest),
        imported_by=imported_by,
    )
    session.add(package)
    session.flush()

    created_proposal_ids: list[str] = []
    for proposal in preview.proposals:
        row = resolved[proposal.proposal_id]
        if (
            proposal.digital_object_id is None
            or proposal.page_number is None
            or proposal.asset_path is None
        ):
            raise ExternalAnalysisError(
                f"{proposal.proposal_id} no conserva identidad completa de página"
            )
        internal_id = new_id()
        session.add(
            ExternalAnalysisProposal(
                id=internal_id,
                package_id=package.id,
                external_proposal_id=proposal.proposal_id,
                result_id=proposal.result_id,
                output_schema_id=proposal.output_schema_id,
                target_type=proposal.target_type,
                target_id=proposal.target_id,
                digital_object_id=proposal.digital_object_id,
                page_number=proposal.page_number,
                source_key=proposal.source_key,
                original_filename=proposal.original_filename,
                asset_path=proposal.asset_path,
                source_asset_sha256=row.source_asset_sha256,
                output_json=deepcopy(proposal.output),
                output_sha256=proposal.output_sha256,
                provenance_json=deepcopy(proposal.provenance),
                warnings_json=list(proposal.warnings),
            )
        )
        created_proposal_ids.append(internal_id)
    session.flush()
    source_link_count = _refresh_package_sources(
        session,
        package_id=package.id,
        resolution=resolution,
    )
    return ExternalAnalysisImportResult(
        package_id=package.id,
        created=True,
        proposal_ids=tuple(created_proposal_ids),
        source_link_count=source_link_count,
    )


def _validate_reviewed_output(output_schema_id: str, value: dict[str, Any]) -> None:
    if output_schema_id not in SUPPORTED_OUTPUT_SCHEMAS:
        raise ExternalAnalysisError(f"Schema de salida no soportado: {output_schema_id}")
    if output_schema_id == "vision_describe/0.1":
        expected = {"description", "visible_text_notes", "document_features", "uncertainties"}
        if set(value) != expected or not isinstance(value.get("description"), str):
            raise ExternalAnalysisError("La revisión no cumple vision_describe/0.1")
        for field in ("visible_text_notes", "document_features", "uncertainties"):
            items = value.get(field)
            if not isinstance(items, list) or any(not isinstance(item, str) for item in items):
                raise ExternalAnalysisError(f"La revisión contiene un {field} inválido")


def _package_for_proposal(
    session: Session,
    proposal: ExternalAnalysisProposal,
) -> ExternalAnalysisPackage:
    package = session.get(ExternalAnalysisPackage, proposal.package_id)
    if package is None:
        raise ExternalAnalysisError("La propuesta perdió su paquete de origen")
    return package


def latest_external_analysis_selection(
    session: Session,
    *,
    project_id: str,
    target_type: str,
    target_id: str,
    output_schema_id: str,
) -> ExternalAnalysisSelection | None:
    return session.scalar(
        select(ExternalAnalysisSelection)
        .where(
            ExternalAnalysisSelection.project_id == project_id,
            ExternalAnalysisSelection.target_type == target_type,
            ExternalAnalysisSelection.target_id == target_id,
            ExternalAnalysisSelection.output_schema_id == output_schema_id,
        )
        .order_by(
            ExternalAnalysisSelection.selected_at.desc(),
            ExternalAnalysisSelection.id.desc(),
        )
        .limit(1)
    )


def _create_selection(
    session: Session,
    *,
    package: ExternalAnalysisPackage,
    proposal: ExternalAnalysisProposal,
    review: ExternalAnalysisReview,
    selected_by: str,
    supersedes: ExternalAnalysisSelection | None,
) -> ExternalAnalysisSelection:
    row = ExternalAnalysisSelection(
        id=new_id(),
        project_id=package.project_id,
        target_type=proposal.target_type,
        target_id=proposal.target_id,
        digital_object_id=proposal.digital_object_id,
        page_number=proposal.page_number,
        output_schema_id=proposal.output_schema_id,
        review_id=review.id,
        action="set",
        supersedes_selection_id=supersedes.id if supersedes is not None else None,
        selected_by=selected_by,
    )
    session.add(row)
    session.flush()
    return row


def review_external_analysis_proposal(
    session: Session,
    *,
    proposal_id: str,
    decision: str,
    reviewed_by: str,
    reviewed_output: dict[str, Any] | None = None,
    review_note: str | None = None,
) -> ExternalAnalysisReviewResult:
    """Agrega una revisión; la primera aceptación puede crear la vigencia inicial."""

    if decision not in {"accepted", "rejected"}:
        raise ExternalAnalysisError("decision debe ser accepted o rejected")
    if not reviewed_by.strip():
        raise ExternalAnalysisError("reviewed_by no puede quedar vacío")
    proposal = session.get(ExternalAnalysisProposal, proposal_id)
    if proposal is None:
        raise ExternalAnalysisError("La propuesta no existe")
    package = _package_for_proposal(session, proposal)

    snapshot: dict[str, Any] | None
    if decision == "accepted":
        snapshot = deepcopy(proposal.output_json if reviewed_output is None else reviewed_output)
        _validate_reviewed_output(proposal.output_schema_id, snapshot)
    else:
        if reviewed_output is not None:
            raise ExternalAnalysisError("Una revisión rechazada no guarda output revisado")
        snapshot = None

    latest_revision = session.scalar(
        select(func.max(ExternalAnalysisReview.revision)).where(
            ExternalAnalysisReview.proposal_id == proposal.id
        )
    )
    revision = int(latest_revision or 0) + 1
    review = ExternalAnalysisReview(
        id=new_id(),
        proposal_id=proposal.id,
        revision=revision,
        decision=decision,
        reviewed_output_json=snapshot,
        review_note=review_note,
        reviewed_by=reviewed_by,
        source_proposal_sha256=proposal.output_sha256,
    )
    session.add(review)
    session.flush()

    initial_selection_id: str | None = None
    if decision == "accepted":
        current = latest_external_analysis_selection(
            session,
            project_id=package.project_id,
            target_type=proposal.target_type,
            target_id=proposal.target_id,
            output_schema_id=proposal.output_schema_id,
        )
        if current is None:
            selection = _create_selection(
                session,
                package=package,
                proposal=proposal,
                review=review,
                selected_by=reviewed_by,
                supersedes=None,
            )
            initial_selection_id = selection.id

    return ExternalAnalysisReviewResult(
        review_id=review.id,
        revision=review.revision,
        initial_selection_id=initial_selection_id,
    )


def set_external_analysis_current_review(
    session: Session,
    *,
    review_id: str,
    selected_by: str,
) -> ExternalAnalysisSelectionResult:
    """Selecciona explícitamente una revisión aceptada como vigente para su target/schema."""

    if not selected_by.strip():
        raise ExternalAnalysisError("selected_by no puede quedar vacío")
    review = session.get(ExternalAnalysisReview, review_id)
    if review is None:
        raise ExternalAnalysisError("La revisión no existe")
    if review.decision != "accepted":
        raise ExternalAnalysisError("Sólo una revisión aceptada puede quedar vigente")
    proposal = session.get(ExternalAnalysisProposal, review.proposal_id)
    if proposal is None:
        raise ExternalAnalysisError("La revisión perdió su propuesta de origen")
    package = _package_for_proposal(session, proposal)
    current = latest_external_analysis_selection(
        session,
        project_id=package.project_id,
        target_type=proposal.target_type,
        target_id=proposal.target_id,
        output_schema_id=proposal.output_schema_id,
    )
    if current is not None and current.action == "set" and current.review_id == review.id:
        return ExternalAnalysisSelectionResult(
            selection_id=current.id,
            created=False,
            supersedes_selection_id=current.supersedes_selection_id,
        )

    selection = _create_selection(
        session,
        package=package,
        proposal=proposal,
        review=review,
        selected_by=selected_by,
        supersedes=current,
    )
    return ExternalAnalysisSelectionResult(
        selection_id=selection.id,
        created=True,
        supersedes_selection_id=current.id if current is not None else None,
    )


def _navigation_source_keys(
    session: Session,
    *,
    project_id: str,
    digital_object_ids: set[str],
) -> dict[str, str]:
    if not digital_object_ids:
        return {}
    rows = session.scalars(
        select(SourceRegistration)
        .where(
            SourceRegistration.project_id == project_id,
            SourceRegistration.digital_object_id.in_(digital_object_ids),
        )
        .order_by(SourceRegistration.registered_at, SourceRegistration.id)
    ).all()
    result: dict[str, str] = {}
    for row in rows:
        if row.digital_object_id and row.digital_object_id not in result:
            result[row.digital_object_id] = row.source_key
    return result


def _current_review_ids(
    session: Session,
    *,
    project_id: str,
) -> dict[tuple[str, str, str], str | None]:
    rows = session.scalars(
        select(ExternalAnalysisSelection)
        .where(ExternalAnalysisSelection.project_id == project_id)
        .order_by(ExternalAnalysisSelection.selected_at, ExternalAnalysisSelection.id)
    ).all()
    current: dict[tuple[str, str, str], str | None] = {}
    for row in rows:
        key = (row.target_type, row.target_id, row.output_schema_id)
        current[key] = row.review_id if row.action == "set" else None
    return current


def external_analysis_package_rows(
    session: Session,
    *,
    project_id: str,
) -> list[ExternalAnalysisPackageRow]:
    rows = session.scalars(
        select(ExternalAnalysisPackage)
        .where(ExternalAnalysisPackage.project_id == project_id)
        .order_by(ExternalAnalysisPackage.imported_at.desc(), ExternalAnalysisPackage.id.desc())
    ).all()
    return [
        ExternalAnalysisPackageRow(
            package_id=row.id,
            package_sha256=row.package_sha256,
            producer_id=row.producer_id,
            producer_version=row.producer_version,
            model_id=(
                str(row.model_json.get("model_id"))
                if isinstance(row.model_json, dict) and row.model_json.get("model_id")
                else None
            ),
            proposal_count=row.proposal_count,
            imported_by=row.imported_by,
            imported_at=row.imported_at,
            exp01_sha256=row.exp01_sha256,
        )
        for row in rows
    ]


def external_analysis_proposal_summaries(
    session: Session,
    *,
    project_id: str,
) -> list[ExternalAnalysisProposalSummary]:
    rows = session.execute(
        select(
            ExternalAnalysisProposal.id,
            ExternalAnalysisProposal.package_id,
            ExternalAnalysisProposal.external_proposal_id,
            ExternalAnalysisProposal.target_type,
            ExternalAnalysisProposal.target_id,
            ExternalAnalysisProposal.digital_object_id,
            ExternalAnalysisProposal.page_number,
            ExternalAnalysisProposal.source_key,
            ExternalAnalysisProposal.original_filename,
            ExternalAnalysisProposal.output_schema_id,
            ExternalAnalysisProposal.warnings_json,
            ExternalAnalysisPackage.model_json,
            ExternalAnalysisPackage.producer_id,
            ExternalAnalysisPackage.producer_version,
            ExternalAnalysisPackage.imported_at,
        )
        .join(
            ExternalAnalysisPackage,
            ExternalAnalysisPackage.id == ExternalAnalysisProposal.package_id,
        )
        .where(ExternalAnalysisPackage.project_id == project_id)
        .order_by(ExternalAnalysisProposal.created_at, ExternalAnalysisProposal.id)
    ).all()
    if not rows:
        return []
    proposal_ids = [str(row.id) for row in rows]
    reviews = session.scalars(
        select(ExternalAnalysisReview)
        .where(ExternalAnalysisReview.proposal_id.in_(proposal_ids))
        .order_by(
            ExternalAnalysisReview.proposal_id,
            ExternalAnalysisReview.revision,
            ExternalAnalysisReview.id,
        )
    ).all()
    latest_by_proposal: dict[str, ExternalAnalysisReview] = {}
    for review in reviews:
        latest_by_proposal[review.proposal_id] = review
    current = _current_review_ids(session, project_id=project_id)
    digital_ids = {str(row.digital_object_id) for row in rows}
    source_keys = _navigation_source_keys(
        session, project_id=project_id, digital_object_ids=digital_ids
    )
    result: list[ExternalAnalysisProposalSummary] = []
    for row in rows:
        proposal_id = str(row.id)
        latest = latest_by_proposal.get(proposal_id)
        status = latest.decision if latest is not None else "pending"
        key = (str(row.target_type), str(row.target_id), str(row.output_schema_id))
        model_json = row.model_json if isinstance(row.model_json, dict) else {}
        result.append(
            ExternalAnalysisProposalSummary(
                proposal_id=proposal_id,
                package_id=str(row.package_id),
                external_proposal_id=str(row.external_proposal_id),
                target_id=str(row.target_id),
                digital_object_id=str(row.digital_object_id),
                page_number=int(row.page_number),
                source_key=str(row.source_key) if row.source_key else None,
                navigation_source_key=(
                    str(row.source_key)
                    if row.source_key
                    else source_keys.get(str(row.digital_object_id))
                ),
                original_filename=str(row.original_filename) if row.original_filename else None,
                output_schema_id=str(row.output_schema_id),
                warnings=tuple(row.warnings_json or ()),
                model_id=str(model_json.get("model_id")) if model_json.get("model_id") else None,
                producer_id=str(row.producer_id) if row.producer_id else None,
                producer_version=str(row.producer_version) if row.producer_version else None,
                imported_at=row.imported_at,
                status=status,
                latest_review_id=latest.id if latest is not None else None,
                latest_revision=latest.revision if latest is not None else None,
                latest_decision=latest.decision if latest is not None else None,
                latest_reviewed_output=(
                    deepcopy(latest.reviewed_output_json)
                    if latest is not None and latest.reviewed_output_json is not None
                    else None
                ),
                latest_reviewed_by=latest.reviewed_by if latest is not None else None,
                latest_reviewed_at=latest.reviewed_at if latest is not None else None,
                current_review_id=current.get(key),
            )
        )
    return result


def external_analysis_proposal_detail(
    session: Session,
    *,
    project_id: str,
    proposal_id: str,
) -> ExternalAnalysisProposalDetail:
    summaries = {
        row.proposal_id: row
        for row in external_analysis_proposal_summaries(session, project_id=project_id)
        if row.proposal_id == proposal_id
    }
    summary = summaries.get(proposal_id)
    if summary is None:
        raise ExternalAnalysisError("La propuesta no existe en este proyecto")
    proposal = session.get(ExternalAnalysisProposal, proposal_id)
    if proposal is None:
        raise ExternalAnalysisError("La propuesta no existe")
    latest = session.scalar(
        select(ExternalAnalysisReview)
        .where(ExternalAnalysisReview.proposal_id == proposal_id)
        .order_by(ExternalAnalysisReview.revision.desc(), ExternalAnalysisReview.id.desc())
        .limit(1)
    )
    return ExternalAnalysisProposalDetail(
        summary=summary,
        raw_output=deepcopy(proposal.output_json),
        provenance=deepcopy(proposal.provenance_json),
        latest_reviewed_output=(
            deepcopy(latest.reviewed_output_json)
            if latest is not None and latest.reviewed_output_json is not None
            else None
        ),
        latest_review_note=latest.review_note if latest is not None else None,
    )


def external_analysis_history_rows(
    session: Session,
    *,
    project_id: str,
) -> list[ExternalAnalysisHistoryRow]:
    rows = session.execute(
        select(
            ExternalAnalysisReview.id,
            ExternalAnalysisReview.proposal_id,
            ExternalAnalysisReview.decision,
            ExternalAnalysisReview.revision,
            ExternalAnalysisReview.reviewed_output_json,
            ExternalAnalysisReview.review_note,
            ExternalAnalysisReview.reviewed_by,
            ExternalAnalysisReview.reviewed_at,
            ExternalAnalysisProposal.external_proposal_id,
            ExternalAnalysisProposal.target_id,
            ExternalAnalysisProposal.digital_object_id,
            ExternalAnalysisProposal.page_number,
            ExternalAnalysisProposal.source_key,
            ExternalAnalysisProposal.original_filename,
            ExternalAnalysisProposal.output_schema_id,
            ExternalAnalysisProposal.warnings_json,
            ExternalAnalysisPackage.model_json,
            ExternalAnalysisPackage.producer_id,
            ExternalAnalysisPackage.producer_version,
        )
        .join(
            ExternalAnalysisProposal,
            ExternalAnalysisProposal.id == ExternalAnalysisReview.proposal_id,
        )
        .join(
            ExternalAnalysisPackage,
            ExternalAnalysisPackage.id == ExternalAnalysisProposal.package_id,
        )
        .where(ExternalAnalysisPackage.project_id == project_id)
        .order_by(ExternalAnalysisReview.reviewed_at.desc(), ExternalAnalysisReview.id.desc())
    ).all()
    if not rows:
        return []
    current_ids = {
        review_id
        for review_id in _current_review_ids(session, project_id=project_id).values()
        if review_id is not None
    }
    digital_ids = {str(row.digital_object_id) for row in rows}
    source_keys = _navigation_source_keys(
        session, project_id=project_id, digital_object_ids=digital_ids
    )
    result: list[ExternalAnalysisHistoryRow] = []
    for row in rows:
        model_json = row.model_json if isinstance(row.model_json, dict) else {}
        result.append(
            ExternalAnalysisHistoryRow(
                review_id=str(row.id),
                proposal_id=str(row.proposal_id),
                external_proposal_id=str(row.external_proposal_id),
                target_id=str(row.target_id),
                digital_object_id=str(row.digital_object_id),
                page_number=int(row.page_number),
                source_key=str(row.source_key) if row.source_key else None,
                navigation_source_key=(
                    str(row.source_key)
                    if row.source_key
                    else source_keys.get(str(row.digital_object_id))
                ),
                original_filename=str(row.original_filename) if row.original_filename else None,
                output_schema_id=str(row.output_schema_id),
                reviewed_output=(
                    deepcopy(row.reviewed_output_json)
                    if row.reviewed_output_json is not None
                    else None
                ),
                decision=str(row.decision),
                revision=int(row.revision),
                review_note=str(row.review_note) if row.review_note else None,
                reviewed_by=str(row.reviewed_by),
                reviewed_at=row.reviewed_at,
                model_id=str(model_json.get("model_id")) if model_json.get("model_id") else None,
                producer_id=str(row.producer_id) if row.producer_id else None,
                producer_version=str(row.producer_version) if row.producer_version else None,
                warnings=tuple(row.warnings_json or ()),
                is_current=str(row.id) in current_ids,
            )
        )
    return result


def external_analysis_current_rows(
    session: Session,
    *,
    project_id: str,
) -> list[ExternalAnalysisHistoryRow]:
    return [
        row
        for row in external_analysis_history_rows(session, project_id=project_id)
        if row.is_current and row.decision == "accepted"
    ]


def external_analysis_current_review_ids_for_page(
    session: Session,
    *,
    project_id: str,
    source_key: str,
    page_number: int,
) -> tuple[str, ...]:
    """Devuelve las revisiones vigentes de una página sin cargar el historial completo."""

    digital_object_id = session.scalar(
        select(SourceRegistration.digital_object_id).where(
            SourceRegistration.project_id == project_id,
            SourceRegistration.source_key == source_key,
        )
    )
    if not digital_object_id:
        return ()
    selections = session.scalars(
        select(ExternalAnalysisSelection)
        .where(
            ExternalAnalysisSelection.project_id == project_id,
            ExternalAnalysisSelection.digital_object_id == digital_object_id,
            ExternalAnalysisSelection.page_number == int(page_number),
        )
        .order_by(ExternalAnalysisSelection.selected_at, ExternalAnalysisSelection.id)
    ).all()
    latest: dict[tuple[str, str, str], ExternalAnalysisSelection] = {}
    for selection in selections:
        latest[(selection.target_type, selection.target_id, selection.output_schema_id)] = selection
    return tuple(
        selection.review_id
        for selection in latest.values()
        if selection.action == "set" and selection.review_id is not None
    )


def external_analysis_reviewed_export_rows(
    session: Session,
    *,
    project_id: str,
) -> list[dict[str, Any]]:
    """Materializa la capa vigente revisada con la selección que le da vigencia."""

    history_by_id = {
        row.review_id: row
        for row in external_analysis_history_rows(session, project_id=project_id)
        if row.decision == "accepted"
    }
    selections = session.scalars(
        select(ExternalAnalysisSelection)
        .where(ExternalAnalysisSelection.project_id == project_id)
        .order_by(ExternalAnalysisSelection.selected_at, ExternalAnalysisSelection.id)
    ).all()
    latest: dict[tuple[str, str, str], ExternalAnalysisSelection] = {}
    for selection in selections:
        latest[(selection.target_type, selection.target_id, selection.output_schema_id)] = selection

    records: list[dict[str, Any]] = []
    for selection in latest.values():
        if selection.action != "set" or selection.review_id is None:
            continue
        row = history_by_id.get(selection.review_id)
        if row is None:
            continue
        records.append(
            {
                "selection_id": selection.id,
                "selected_by": selection.selected_by,
                "selected_at": selection.selected_at.isoformat(),
                "review_id": row.review_id,
                "proposal_id": row.proposal_id,
                "external_proposal_id": row.external_proposal_id,
                "target_id": row.target_id,
                "digital_object_id": row.digital_object_id,
                "page_number": row.page_number,
                "source_key": row.source_key,
                "navigation_source_key": row.navigation_source_key,
                "original_filename": row.original_filename,
                "output_schema_id": row.output_schema_id,
                "model_id": row.model_id,
                "producer_id": row.producer_id,
                "producer_version": row.producer_version,
                "review_revision": row.revision,
                "reviewed_by": row.reviewed_by,
                "reviewed_at": row.reviewed_at.isoformat(),
                "review_note": row.review_note,
                "warnings": list(row.warnings),
                "reviewed_output": deepcopy(row.reviewed_output),
            }
        )
    records.sort(
        key=lambda item: (
            str(
                item.get("original_filename") or item.get("source_key") or item["digital_object_id"]
            ),
            int(item["page_number"]),
            str(item["output_schema_id"]),
            str(item["review_id"]),
        )
    )
    return records


def read_external_analysis_proposal_asset(
    session: Session,
    *,
    project_root: Path,
    project_id: str,
    proposal_id: str,
) -> VerifiedAIHandoffAsset:
    proposal = session.get(ExternalAnalysisProposal, proposal_id)
    if proposal is None:
        raise ExternalAnalysisError("La propuesta no existe")
    package = _package_for_proposal(session, proposal)
    if package.project_id != project_id:
        raise ExternalAnalysisError("La propuesta pertenece a otro proyecto")
    source_ids = tuple(
        session.scalars(
            select(ExternalAnalysisPackageSource.export_run_id).where(
                ExternalAnalysisPackageSource.package_id == package.id
            )
        ).all()
    )
    if not source_ids:
        raise ExternalAnalysisError("El paquete no conserva una exportación EXP-01 vinculada")
    runs = session.scalars(
        select(CorpusExportRun)
        .where(
            CorpusExportRun.project_id == project_id,
            CorpusExportRun.id.in_(source_ids),
        )
        .order_by(CorpusExportRun.created_at.desc(), CorpusExportRun.id.desc())
    ).all()
    persisted = AIHandoffProposal(
        proposal_id=proposal.external_proposal_id,
        result_id=proposal.result_id,
        request_id=package.request_id,
        target_id=proposal.target_id,
        target_type=proposal.target_type,
        digital_object_id=proposal.digital_object_id,
        page_number=proposal.page_number,
        source_key=proposal.source_key,
        original_filename=proposal.original_filename,
        asset_path=proposal.asset_path,
        output_schema_id=proposal.output_schema_id,
        output=deepcopy(proposal.output_json),
        output_sha256=proposal.output_sha256,
        warnings=tuple(proposal.warnings_json or ()),
        provenance=deepcopy(proposal.provenance_json),
    )
    errors: list[str] = []
    for run in runs:
        try:
            asset = read_verified_ai_handoff_asset(
                project_root=project_root,
                project_id=project_id,
                run=run,
                proposal=persisted,
                expected_exp01_sha256=package.exp01_sha256,
            )
        except (ValueError, OSError) as exc:
            errors.append(str(exc))
            continue
        if asset.sha256 != proposal.source_asset_sha256:
            errors.append(
                "El SHA-256 del asset revalidado no coincide con la propuesta incorporada"
            )
            continue
        return asset
    detail = "; ".join(dict.fromkeys(errors)) or "no se pudo revalidar ninguna copia EXP-01"
    raise ExternalAnalysisError(f"No se pudo recuperar el asset exacto de origen: {detail}")
