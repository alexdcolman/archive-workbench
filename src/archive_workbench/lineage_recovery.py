from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from archive_workbench.db.models import (
    ExchangeChangeEvent,
    ExchangeCheckpoint,
    ExchangeDryRun,
    ExchangeLineageCase,
    ExchangeLineageDecision,
    ExchangeLineageEvidence,
    ExchangeWorkspace,
    Project,
    utc_now,
)
from archive_workbench.identity import new_id, sha256_json
from archive_workbench.lineage_diagnostics import diagnose_unmatched_bundle_lineage


@dataclass(slots=True)
class LineageRecoverySummary:
    case_id: str
    decision_id: str
    bundle_id: str
    recovery_method: str
    local_checkpoint_id: str | None
    local_checkpoint_label: str | None
    local_checkpoint_sequence: int
    remote_workspace_id: str
    remote_sequence: int
    evidence_count: int
    parameters_sha256: str
    previous_dry_run_status: str
    current_dry_run_status: str


@dataclass(slots=True)
class LineageRecoveryRow:
    case_id: str
    decision_id: str
    bundle_id: str
    recovery_method: str
    local_checkpoint_label: str | None
    local_checkpoint_sequence: int
    remote_workspace_id: str
    remote_sequence: int
    evidence_count: int
    confirmed_by: str
    confirmation_reason: str
    source: str
    parameters_sha256: str
    created_at: datetime


def _single_project(session: Session) -> Project:
    rows = session.scalars(select(Project).order_by(Project.created_at, Project.id)).all()
    if not rows:
        raise ValueError("El proyecto todavía no está registrado en SQLite")
    if len(rows) != 1:
        raise ValueError("La base contiene más de un proyecto")
    return rows[0]


def _local_workspace(session: Session, workspace_id: str) -> ExchangeWorkspace:
    workspace = session.get(ExchangeWorkspace, workspace_id)
    if workspace is None:
        raise ValueError("La simulación refiere a una copia local inexistente")
    return workspace


def _current_sequence(session: Session, workspace_id: str) -> int:
    value = session.scalar(
        select(func.max(ExchangeChangeEvent.sequence_number)).where(
            ExchangeChangeEvent.workspace_id == workspace_id
        )
    )
    return int(value or 0)


def lineage_recovery_rows(session: Session) -> list[LineageRecoveryRow]:
    rows = session.scalars(
        select(ExchangeLineageDecision)
        .where(
            ExchangeLineageDecision.operation == "recover_lineage",
            ExchangeLineageDecision.result == "recovered",
        )
        .order_by(
            ExchangeLineageDecision.created_at.desc(),
            ExchangeLineageDecision.id,
        )
    ).all()
    return [
        LineageRecoveryRow(
            case_id=row.case_id,
            decision_id=row.id,
            bundle_id=row.target_bundle_id,
            recovery_method=row.recovery_method,
            local_checkpoint_label=row.local_checkpoint_label,
            local_checkpoint_sequence=row.local_checkpoint_sequence,
            remote_workspace_id=row.remote_workspace_id,
            remote_sequence=row.remote_sequence,
            evidence_count=len(row.evidence_ids_json or []),
            confirmed_by=row.confirmed_by,
            confirmation_reason=row.confirmation_reason,
            source=row.source,
            parameters_sha256=row.parameters_sha256,
            created_at=row.created_at,
        )
        for row in rows
    ]


def recover_unmatched_bundle_lineage(
    session: Session,
    *,
    project_root: Path,
    bundle_ref: str,
    evidence_paths: Iterable[Path] = (),
    recovered_by: str,
    confirmation_reason: str,
    recovery_confirmed: bool,
    source: str,
) -> LineageRecoverySummary:
    """Registra una recuperación única y append-only a partir de evidencia concluyente."""
    actor = recovered_by.strip()
    reason = confirmation_reason.strip()
    clean_source = source.strip().lower()
    if not recovery_confirmed:
        raise ValueError("Marcá la confirmación explícita antes de recuperar el linaje")
    if not actor:
        raise ValueError("Indicá quién confirma la recuperación")
    if not reason:
        raise ValueError("Escribí el fundamento de la recuperación")
    if clean_source not in {"ui", "cli", "api", "script"}:
        raise ValueError("El origen de la recuperación no es válido")

    dry = session.scalar(select(ExchangeDryRun).where(ExchangeDryRun.bundle_id == bundle_ref))
    if dry is None:
        raise ValueError("El paquete todavía no tiene una simulación persistida")
    existing = session.scalar(
        select(ExchangeLineageDecision).where(
            ExchangeLineageDecision.target_bundle_id == dry.bundle_id
        )
    )
    if existing is not None:
        raise ValueError(
            "El linaje de este paquete ya fue recuperado. Repetí la simulación; "
            "no se registró una segunda decisión."
        )
    if dry.lifecycle_status != "active":
        raise ValueError("El paquete está archivado. Restauralo antes de recuperar su linaje")
    if dry.base_match_status != "unmatched":
        raise ValueError("La simulación ya reconoce una base; no corresponde recuperar linaje")

    evidence = [Path(path).expanduser().resolve() for path in evidence_paths]
    report = diagnose_unmatched_bundle_lineage(
        session,
        project_root=project_root.resolve(),
        bundle_ref=dry.bundle_id,
        evidence_paths=evidence,
    )
    if report.classification != "recoverable" or len(report.recovery_candidates) != 1:
        raise ValueError(
            "La recuperación exige una única cadena concluyente. "
            f"Resultado actual: {report.classification}."
        )
    candidate = report.recovery_candidates[0]
    if candidate.remote_workspace_id != report.source_workspace_id:
        raise ValueError("La cadena concluyente refiere a otra copia de origen")
    if candidate.remote_sequence != report.base_sequence:
        raise ValueError("La cadena concluyente no alcanza la secuencia base del paquete")
    if candidate.local_checkpoint_sequence is None:
        raise ValueError("La evidencia no identifica una secuencia local comparable")

    project = _single_project(session)
    workspace = _local_workspace(session, dry.workspace_id)
    if project.id != report.project_id or workspace.id != report.local_workspace_id:
        raise ValueError("El diagnóstico ya no corresponde a esta copia local")
    current_sequence = _current_sequence(session, workspace.id)
    if candidate.local_checkpoint_sequence < 0:
        raise ValueError("La secuencia local recuperada no es válida")
    if candidate.local_checkpoint_sequence > current_sequence:
        raise ValueError(
            "La evidencia refiere a una secuencia local posterior al estado actual"
        )
    if candidate.local_checkpoint_id:
        checkpoint = session.get(ExchangeCheckpoint, candidate.local_checkpoint_id)
        if checkpoint is not None:
            if checkpoint.workspace_id != workspace.id:
                raise ValueError("El punto local concluyente pertenece a otra copia")
            if checkpoint.sequence_number != candidate.local_checkpoint_sequence:
                raise ValueError("La secuencia del punto local cambió desde el diagnóstico")
            if (
                candidate.local_checkpoint_state_sha256
                and checkpoint.state_sha256 != candidate.local_checkpoint_state_sha256
            ):
                raise ValueError("El estado del punto local cambió desde el diagnóstico")

    selected_references = set(candidate.evidence_references)
    diagnostic_payload = {
        "schema_version": "ex01b-1",
        "project_id": report.project_id,
        "local_workspace_id": report.local_workspace_id,
        "target_bundle_id": report.bundle_id,
        "target_bundle_sha256": report.bundle_sha256,
        "source_workspace_id": report.source_workspace_id,
        "target_base_checkpoint_id": report.base_checkpoint_id,
        "target_base_checkpoint_label": report.base_checkpoint_label,
        "target_base_state_sha256": report.base_checkpoint_state_sha256,
        "target_base_sequence": report.base_sequence,
        "classification": report.classification,
        "candidate_fingerprint": candidate.fingerprint,
        "candidate_method": candidate.method,
        "evidence": [
            {
                "reference": finding.artifact_reference,
                "sha256": finding.artifact_sha256,
                "verification_status": finding.verification_status,
                "strength": finding.strength,
                "code": finding.code,
                "selected": finding.artifact_reference in selected_references,
            }
            for finding in report.findings
        ],
    }
    diagnostic_hash = sha256_json(diagnostic_payload)
    decision_parameters_hash = sha256_json(
        {
            **diagnostic_payload,
            "operation": "recover_lineage",
            "recovery_confirmed": True,
            "confirmed_by": actor,
            "confirmation_reason": reason,
            "source": clean_source,
        }
    )

    now = utc_now()
    case = ExchangeLineageCase(
        id=new_id(),
        project_id=project.id,
        workspace_id=workspace.id,
        dry_run_id=dry.id,
        bundle_record_id=dry.bundle_record_id,
        bundle_id=dry.bundle_id,
        source_workspace_id=dry.source_workspace_id,
        diagnostic_classification=report.classification,
        candidate_fingerprint=candidate.fingerprint,
        diagnostic_parameters_sha256=diagnostic_hash,
        status="recovered",
        opened_by=actor,
        opened_at=now,
        closed_by=actor,
        closed_at=now,
    )
    session.add(case)
    session.flush()

    evidence_rows: list[ExchangeLineageEvidence] = []
    for finding in report.findings:
        row = ExchangeLineageEvidence(
            id=new_id(),
            case_id=case.id,
            artifact_type=finding.artifact_type,
            artifact_reference=finding.artifact_reference,
            artifact_sha256=finding.artifact_sha256,
            verification_status=finding.verification_status,
            strength=finding.strength,
            code=finding.code,
            explanation=finding.explanation,
            observed_project_id=finding.project_id,
            observed_workspace_id=finding.workspace_id,
            observed_sequence_number=finding.sequence_number,
            observed_checkpoint_id=finding.checkpoint_id,
            observed_checkpoint_label=finding.checkpoint_label,
            observed_state_sha256=finding.state_sha256,
            selected_for_decision=finding.artifact_reference in selected_references,
            details_json=dict(finding.details or {}),
            recorded_at=now,
        )
        session.add(row)
        evidence_rows.append(row)
    session.flush()
    selected_evidence_ids = [row.id for row in evidence_rows if row.selected_for_decision]
    if not selected_evidence_ids:
        raise ValueError("La cadena concluyente no dejó evidencia seleccionable")

    decision = ExchangeLineageDecision(
        id=new_id(),
        case_id=case.id,
        project_id=project.id,
        workspace_id=workspace.id,
        operation="recover_lineage",
        source=clean_source,
        target_bundle_id=report.bundle_id,
        target_bundle_sha256=report.bundle_sha256,
        source_workspace_id=report.source_workspace_id,
        target_base_checkpoint_id=report.base_checkpoint_id,
        target_base_checkpoint_label=report.base_checkpoint_label,
        target_base_state_sha256=report.base_checkpoint_state_sha256,
        target_base_sequence=report.base_sequence,
        candidate_fingerprint=candidate.fingerprint,
        recovery_method=candidate.method,
        local_checkpoint_id=candidate.local_checkpoint_id,
        local_checkpoint_label=candidate.local_checkpoint_label,
        local_checkpoint_sequence=candidate.local_checkpoint_sequence,
        local_checkpoint_state_sha256=candidate.local_checkpoint_state_sha256,
        remote_workspace_id=candidate.remote_workspace_id,
        remote_sequence=candidate.remote_sequence,
        evidence_ids_json=selected_evidence_ids,
        chain_bundle_ids_json=list(candidate.chain_bundle_ids),
        recovery_confirmed=True,
        confirmed_by=actor,
        confirmation_reason=reason,
        parameters_sha256=decision_parameters_hash,
        result="recovered",
        rejection_reason=None,
        created_at=now,
    )
    session.add(decision)

    previous_status = dry.overall_status
    dry.overall_status = "stale"
    dry.warnings_json = list(dry.warnings_json or []) + [
        "El linaje fue recuperado mediante una decisión append-only. "
        "Esta simulación quedó obsoleta y debe repetirse antes de resolver o aplicar."
    ]
    session.flush()

    return LineageRecoverySummary(
        case_id=case.id,
        decision_id=decision.id,
        bundle_id=report.bundle_id,
        recovery_method=candidate.method,
        local_checkpoint_id=candidate.local_checkpoint_id,
        local_checkpoint_label=candidate.local_checkpoint_label,
        local_checkpoint_sequence=candidate.local_checkpoint_sequence,
        remote_workspace_id=candidate.remote_workspace_id,
        remote_sequence=candidate.remote_sequence,
        evidence_count=len(evidence_rows),
        parameters_sha256=decision_parameters_hash,
        previous_dry_run_status=previous_status,
        current_dry_run_status=dry.overall_status,
    )
