from __future__ import annotations

import json
import sqlite3
import zipfile
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from archive_workbench.contracts.changes import ChangeBundleManifest
from archive_workbench.db.models import (
    ExchangeBundleApplication,
    ExchangeBundleRecord,
    ExchangeCheckpoint,
    ExchangeDryRun,
    ExchangeWorkspace,
    Project,
)
from archive_workbench.exchange import inspect_change_bundle
from archive_workbench.identity import sha256_file, short_id
from archive_workbench.project_admin import inspect_project_backup


@dataclass(slots=True)
class LineageEvidenceFinding:
    artifact_type: str
    artifact_reference: str
    artifact_sha256: str | None
    verification_status: str
    strength: str
    code: str
    explanation: str
    project_id: str | None = None
    workspace_id: str | None = None
    sequence_number: int | None = None
    checkpoint_id: str | None = None
    checkpoint_label: str | None = None
    state_sha256: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class LineageRecoveryCandidate:
    fingerprint: str
    method: str
    explanation: str
    local_checkpoint_id: str | None
    local_checkpoint_label: str | None
    local_checkpoint_sequence: int | None
    local_checkpoint_state_sha256: str | None
    remote_workspace_id: str
    remote_sequence: int
    evidence_references: list[str]
    chain_bundle_ids: list[str] = field(default_factory=list)


@dataclass(slots=True)
class LineageDiagnosticReport:
    bundle_id: str
    bundle_sha256: str
    project_id: str
    local_workspace_id: str
    local_workspace_name: str
    source_workspace_id: str
    source_workspace_name: str
    base_checkpoint_id: str
    base_checkpoint_label: str
    base_checkpoint_state_sha256: str
    base_sequence: int
    classification: str
    summary: str
    findings: list[LineageEvidenceFinding]
    recovery_candidates: list[LineageRecoveryCandidate]
    contradiction_count: int


@dataclass(slots=True)
class _VerifiedBundle:
    reference: str
    sha256: str
    manifest: ChangeBundleManifest


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


def _resolve_bundle_record_path(project_root: Path, record: ExchangeBundleRecord) -> Path:
    if not record.relative_path:
        raise ValueError("El paquete recibido no conserva una ruta verificable")
    candidate = Path(record.relative_path).expanduser()
    if not candidate.is_absolute():
        candidate = project_root.resolve() / candidate
    candidate = candidate.resolve()
    if not candidate.is_file():
        raise ValueError(f"No existe el paquete recibido registrado: {candidate}")
    return candidate


def _direct_application_rows(
    session: Session,
    *,
    workspace_id: str,
    source_workspace_id: str,
    base_checkpoint_label: str,
    base_sequence: int,
) -> list[tuple[ExchangeBundleApplication, ExchangeBundleRecord, ExchangeCheckpoint | None]]:
    prefix = "bundle_"
    if not base_checkpoint_label.startswith(prefix):
        return []
    short_bundle_id = base_checkpoint_label[len(prefix) :].strip()
    if not short_bundle_id:
        return []
    rows = session.execute(
        select(ExchangeBundleApplication, ExchangeBundleRecord)
        .join(
            ExchangeBundleRecord,
            ExchangeBundleRecord.id == ExchangeBundleApplication.bundle_record_id,
        )
        .where(
            ExchangeBundleApplication.workspace_id == workspace_id,
            ExchangeBundleApplication.source_workspace_id == source_workspace_id,
            ExchangeBundleApplication.status == "applied",
            ExchangeBundleRecord.direction == "incoming",
            ExchangeBundleRecord.status == "applied",
            ExchangeBundleRecord.last_sequence == base_sequence,
            ExchangeBundleRecord.bundle_id.like(f"{short_bundle_id}%"),
        )
        .order_by(ExchangeBundleApplication.applied_at.desc())
    ).all()
    return [
        (application, record, session.get(ExchangeCheckpoint, application.checkpoint_id))
        for application, record in rows
    ]


def _checkpoint_candidates(
    session: Session,
    *,
    workspace_id: str,
    state_sha256: str,
) -> list[ExchangeCheckpoint]:
    return list(
        session.scalars(
            select(ExchangeCheckpoint)
            .where(
                ExchangeCheckpoint.workspace_id == workspace_id,
                ExchangeCheckpoint.state_sha256 == state_sha256,
            )
            .order_by(
                ExchangeCheckpoint.sequence_number.desc(),
                ExchangeCheckpoint.created_at.desc(),
                ExchangeCheckpoint.id,
            )
        ).all()
    )


def _candidate_from_checkpoint(
    checkpoint: ExchangeCheckpoint,
    *,
    manifest: ChangeBundleManifest,
    method: str,
    reference: str,
    explanation: str,
) -> LineageRecoveryCandidate:
    return LineageRecoveryCandidate(
        fingerprint=(
            f"{method}:{checkpoint.id}:{manifest.source_workspace_id}:"
            f"{manifest.base_sequence}"
        ),
        method=method,
        explanation=explanation,
        local_checkpoint_id=checkpoint.id,
        local_checkpoint_label=checkpoint.label,
        local_checkpoint_sequence=checkpoint.sequence_number,
        local_checkpoint_state_sha256=checkpoint.state_sha256,
        remote_workspace_id=manifest.source_workspace_id,
        remote_sequence=manifest.base_sequence,
        evidence_references=[reference],
    )


def _read_manifest_file(path: Path) -> ChangeBundleManifest:
    return ChangeBundleManifest.model_validate_json(path.read_bytes())


def _sqlite_tables(connection: sqlite3.Connection) -> set[str]:
    return {
        str(row[0])
        for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }


@contextmanager
def _backup_connection(path: Path):
    with zipfile.ZipFile(path, "r") as archive:
        payload = archive.read("database.sqlite3")
    with tempfile.TemporaryDirectory(prefix="archive_workbench_lineage_") as tmp_name:
        database = Path(tmp_name) / "database.sqlite3"
        database.write_bytes(payload)
        connection = sqlite3.connect(
            f"file:{database.as_posix()}?mode=ro&immutable=1",
            uri=True,
        )
        try:
            yield connection
        finally:
            connection.close()


def _inspect_backup_evidence(
    path: Path,
    *,
    project_id: str,
    local_workspace_id: str,
    target: ChangeBundleManifest,
) -> tuple[list[LineageEvidenceFinding], list[LineageRecoveryCandidate], bool]:
    reference = str(path.resolve())
    findings: list[LineageEvidenceFinding] = []
    candidates: list[LineageRecoveryCandidate] = []
    contradiction = False
    try:
        info = inspect_project_backup(path)
    except Exception as exc:
        return (
            [
                LineageEvidenceFinding(
                    artifact_type="project_backup",
                    artifact_reference=reference,
                    artifact_sha256=sha256_file(path) if path.is_file() else None,
                    verification_status="rejected",
                    strength="rejected",
                    code="invalid_backup",
                    explanation=f"Backup rechazado: {exc}",
                )
            ],
            [],
            False,
        )
    if info.project_id != project_id:
        return (
            [
                LineageEvidenceFinding(
                    artifact_type="project_backup",
                    artifact_reference=reference,
                    artifact_sha256=info.backup_sha256,
                    verification_status="rejected",
                    strength="rejected",
                    code="different_project",
                    explanation="El backup pertenece a otro proyecto.",
                    project_id=info.project_id,
                    details={"database_revision": info.database_revision},
                )
            ],
            [],
            False,
        )

    with _backup_connection(path) as connection:
        tables = _sqlite_tables(connection)
        required = {
            "exchange_workspaces",
            "exchange_checkpoints",
            "exchange_bundle_records",
            "exchange_bundle_applications",
        }
        if not required <= tables:
            findings.append(
                LineageEvidenceFinding(
                    artifact_type="project_backup",
                    artifact_reference=reference,
                    artifact_sha256=info.backup_sha256,
                    verification_status="verified",
                    strength="supporting",
                    code="backup_without_exchange_history",
                    explanation=(
                        "El backup es íntegro y pertenece al proyecto, pero no contiene "
                        "todas las tablas históricas necesarias para demostrar linaje."
                    ),
                    project_id=info.project_id,
                    details={"database_revision": info.database_revision},
                )
            )
            return findings, candidates, contradiction

        workspace_rows = connection.execute(
            "SELECT id, project_id, workspace_name FROM exchange_workspaces ORDER BY created_at, id"
        ).fetchall()
        matching_workspaces = [row for row in workspace_rows if str(row[0]) == local_workspace_id]
        if len(matching_workspaces) != 1:
            findings.append(
                LineageEvidenceFinding(
                    artifact_type="project_backup",
                    artifact_reference=reference,
                    artifact_sha256=info.backup_sha256,
                    verification_status="rejected",
                    strength="rejected",
                    code="different_local_workspace",
                    explanation=(
                        "El backup no conserva la identidad de la copia local vigente y no puede "
                        "usarse para recuperar su linaje."
                    ),
                    project_id=info.project_id,
                    details={
                        "database_revision": info.database_revision,
                        "workspace_ids": [str(row[0]) for row in workspace_rows],
                    },
                )
            )
            return findings, candidates, contradiction

        checkpoint_rows = connection.execute(
            """
            SELECT id, label, sequence_number, state_sha256
            FROM exchange_checkpoints
            WHERE workspace_id = ? AND state_sha256 = ?
            ORDER BY sequence_number DESC, created_at DESC, id
            """,
            (local_workspace_id, target.base_checkpoint_state_sha256),
        ).fetchall()
        for checkpoint_id, label, sequence, state_sha in checkpoint_rows:
            finding = LineageEvidenceFinding(
                artifact_type="project_backup",
                artifact_reference=reference,
                artifact_sha256=info.backup_sha256,
                verification_status="verified",
                strength="conclusive",
                code="backup_exact_checkpoint",
                explanation=(
                    "El backup íntegro de esta misma copia conserva un punto de control con "
                    "el SHA-256 exacto declarado por el paquete."
                ),
                project_id=project_id,
                workspace_id=local_workspace_id,
                sequence_number=int(sequence),
                checkpoint_id=str(checkpoint_id),
                checkpoint_label=str(label),
                state_sha256=str(state_sha),
                details={"database_revision": info.database_revision},
            )
            findings.append(finding)
            candidates.append(
                LineageRecoveryCandidate(
                    fingerprint=(
                        f"backup_exact:{checkpoint_id}:{target.source_workspace_id}:"
                        f"{target.base_sequence}"
                    ),
                    method="backup_exact_checkpoint",
                    explanation=finding.explanation,
                    local_checkpoint_id=str(checkpoint_id),
                    local_checkpoint_label=str(label),
                    local_checkpoint_sequence=int(sequence),
                    local_checkpoint_state_sha256=str(state_sha),
                    remote_workspace_id=target.source_workspace_id,
                    remote_sequence=target.base_sequence,
                    evidence_references=[reference],
                )
            )

        prefix = "bundle_"
        short_bundle = (
            target.base_checkpoint_label[len(prefix) :].strip()
            if target.base_checkpoint_label.startswith(prefix)
            else ""
        )
        if short_bundle:
            application_rows = connection.execute(
                """
                SELECT a.checkpoint_id, r.bundle_id, c.label, c.sequence_number, c.state_sha256
                FROM exchange_bundle_applications AS a
                JOIN exchange_bundle_records AS r ON r.id = a.bundle_record_id
                LEFT JOIN exchange_checkpoints AS c ON c.id = a.checkpoint_id
                WHERE a.workspace_id = ?
                  AND a.source_workspace_id = ?
                  AND a.status = 'applied'
                  AND r.direction = 'incoming'
                  AND r.status = 'applied'
                  AND r.last_sequence = ?
                  AND r.bundle_id LIKE ?
                ORDER BY a.applied_at DESC, a.id
                """,
                (
                    local_workspace_id,
                    target.source_workspace_id,
                    target.base_sequence,
                    f"{short_bundle}%",
                ),
            ).fetchall()
            for checkpoint_id, bundle_id, label, sequence, state_sha in application_rows:
                if checkpoint_id is None:
                    findings.append(
                        LineageEvidenceFinding(
                            artifact_type="project_backup",
                            artifact_reference=reference,
                            artifact_sha256=info.backup_sha256,
                            verification_status="verified",
                            strength="supporting",
                            code="backup_application_without_checkpoint",
                            explanation=(
                                "El backup conserva una aplicación compatible, pero perdió la "
                                "referencia a su punto de control local."
                            ),
                            project_id=project_id,
                            workspace_id=local_workspace_id,
                            details={"bundle_id": str(bundle_id)},
                        )
                    )
                    continue
                explanation = (
                    "El backup íntegro de esta misma copia conserva una aplicación anterior "
                    "del paquete que alcanzó exactamente la secuencia remota declarada."
                )
                findings.append(
                    LineageEvidenceFinding(
                        artifact_type="project_backup",
                        artifact_reference=reference,
                        artifact_sha256=info.backup_sha256,
                        verification_status="verified",
                        strength="conclusive",
                        code="backup_applied_bundle",
                        explanation=explanation,
                        project_id=project_id,
                        workspace_id=local_workspace_id,
                        sequence_number=int(sequence),
                        checkpoint_id=str(checkpoint_id),
                        checkpoint_label=str(label),
                        state_sha256=str(state_sha),
                        details={"bundle_id": str(bundle_id)},
                    )
                )
                candidates.append(
                    LineageRecoveryCandidate(
                        fingerprint=(
                            f"backup_application:{checkpoint_id}:{bundle_id}:"
                            f"{target.source_workspace_id}:{target.base_sequence}"
                        ),
                        method="backup_applied_bundle",
                        explanation=explanation,
                        local_checkpoint_id=str(checkpoint_id),
                        local_checkpoint_label=str(label),
                        local_checkpoint_sequence=int(sequence),
                        local_checkpoint_state_sha256=str(state_sha),
                        remote_workspace_id=target.source_workspace_id,
                        remote_sequence=target.base_sequence,
                        evidence_references=[reference],
                    )
                )

        if not checkpoint_rows and not (short_bundle and application_rows):
            findings.append(
                LineageEvidenceFinding(
                    artifact_type="project_backup",
                    artifact_reference=reference,
                    artifact_sha256=info.backup_sha256,
                    verification_status="verified",
                    strength="supporting",
                    code="backup_without_matching_lineage",
                    explanation=(
                        "El backup es íntegro, pertenece al proyecto y conserva la misma copia, "
                        "pero no contiene el punto o la aplicación requeridos por este paquete."
                    ),
                    project_id=project_id,
                    workspace_id=local_workspace_id,
                    details={"database_revision": info.database_revision},
                )
            )
    return findings, candidates, contradiction


def _manifest_predecessors(
    node: _VerifiedBundle,
    bundles: list[_VerifiedBundle],
) -> list[_VerifiedBundle]:
    prefix = "bundle_"
    label = node.manifest.base_checkpoint_label
    if not label.startswith(prefix):
        return []
    expected_short = label[len(prefix) :].strip()
    if not expected_short:
        return []
    return [
        candidate
        for candidate in bundles
        if candidate.manifest.bundle_id != node.manifest.bundle_id
        and candidate.manifest.project_id == node.manifest.project_id
        and candidate.manifest.source_workspace_id == node.manifest.source_workspace_id
        and candidate.manifest.last_sequence == node.manifest.base_sequence
        and short_id(candidate.manifest.bundle_id, len(expected_short)) == expected_short
    ]


def _chain_candidates(
    session: Session,
    *,
    local_workspace_id: str,
    target: _VerifiedBundle,
    bundles: list[_VerifiedBundle],
) -> tuple[list[LineageRecoveryCandidate], list[LineageEvidenceFinding], bool]:
    findings: list[LineageEvidenceFinding] = []
    candidates: list[LineageRecoveryCandidate] = []
    ambiguous = False

    def walk(node: _VerifiedBundle, chain: list[_VerifiedBundle], seen: set[str]) -> None:
        nonlocal ambiguous
        if node.manifest.bundle_id in seen:
            ambiguous = True
            findings.append(
                LineageEvidenceFinding(
                    artifact_type="change_bundle",
                    artifact_reference=node.reference,
                    artifact_sha256=node.sha256,
                    verification_status="rejected",
                    strength="rejected",
                    code="bundle_chain_cycle",
                    explanation="La cadena de paquetes contiene un ciclo imposible.",
                    project_id=node.manifest.project_id,
                    workspace_id=node.manifest.source_workspace_id,
                )
            )
            return

        checkpoints = _checkpoint_candidates(
            session,
            workspace_id=local_workspace_id,
            state_sha256=node.manifest.base_checkpoint_state_sha256,
        )
        direct_apps = _direct_application_rows(
            session,
            workspace_id=local_workspace_id,
            source_workspace_id=node.manifest.source_workspace_id,
            base_checkpoint_label=node.manifest.base_checkpoint_label,
            base_sequence=node.manifest.base_sequence,
        )
        anchors: list[tuple[str, ExchangeCheckpoint, str]] = []
        if checkpoints:
            anchors.append(("checkpoint", checkpoints[0], node.reference))
        for application, record, checkpoint in direct_apps:
            if checkpoint is not None:
                anchors.append((f"application:{record.bundle_id}", checkpoint, node.reference))

        for anchor_kind, checkpoint, anchor_reference in anchors:
            ordered = list(reversed(chain))
            bundle_ids = [item.manifest.bundle_id for item in ordered]
            references = [anchor_reference] + [item.reference for item in ordered]
            explanation = (
                "Una cadena continua de paquetes íntegros conecta un punto local reconocido "
                "con la base declarada por el paquete recibido."
            )
            candidates.append(
                LineageRecoveryCandidate(
                    fingerprint=(
                        f"bundle_chain:{anchor_kind}:{checkpoint.id}:"
                        + ":".join(bundle_ids)
                    ),
                    method="verified_bundle_chain",
                    explanation=explanation,
                    local_checkpoint_id=checkpoint.id,
                    local_checkpoint_label=checkpoint.label,
                    local_checkpoint_sequence=checkpoint.sequence_number,
                    local_checkpoint_state_sha256=checkpoint.state_sha256,
                    remote_workspace_id=target.manifest.source_workspace_id,
                    remote_sequence=target.manifest.base_sequence,
                    evidence_references=list(dict.fromkeys(references)),
                    chain_bundle_ids=bundle_ids,
                )
            )

        predecessors = _manifest_predecessors(node, bundles)
        if len(predecessors) > 1:
            ambiguous = True
            findings.append(
                LineageEvidenceFinding(
                    artifact_type="change_bundle",
                    artifact_reference=node.reference,
                    artifact_sha256=node.sha256,
                    verification_status="verified",
                    strength="supporting",
                    code="bundle_chain_bifurcation",
                    explanation=(
                        "Más de un paquete íntegro puede ocupar el mismo tramo anterior; "
                        "la cadena no es única."
                    ),
                    project_id=node.manifest.project_id,
                    workspace_id=node.manifest.source_workspace_id,
                    sequence_number=node.manifest.base_sequence,
                    details={
                        "predecessor_bundle_ids": [
                            predecessor.manifest.bundle_id for predecessor in predecessors
                        ]
                    },
                )
            )
        for predecessor in predecessors:
            walk(predecessor, chain + [predecessor], seen | {node.manifest.bundle_id})

    predecessors = _manifest_predecessors(target, bundles)
    if len(predecessors) > 1:
        ambiguous = True
        findings.append(
            LineageEvidenceFinding(
                artifact_type="change_bundle",
                artifact_reference=target.reference,
                artifact_sha256=target.sha256,
                verification_status="verified",
                strength="supporting",
                code="bundle_chain_bifurcation",
                explanation=(
                    "Más de un paquete íntegro puede preceder directamente al paquete recibido."
                ),
                project_id=target.manifest.project_id,
                workspace_id=target.manifest.source_workspace_id,
                sequence_number=target.manifest.base_sequence,
                details={"predecessor_bundle_ids": [p.manifest.bundle_id for p in predecessors]},
            )
        )
    for predecessor in predecessors:
        walk(predecessor, [predecessor], {target.manifest.bundle_id})
    return candidates, findings, ambiguous


def diagnose_unmatched_bundle_lineage(
    session: Session,
    *,
    project_root: Path,
    bundle_ref: str,
    evidence_paths: Iterable[Path] = (),
) -> LineageDiagnosticReport:
    """Diagnostica evidencia de linaje sin modificar SQLite ni crear archivos persistentes."""
    project = _single_project(session)
    dry = session.scalar(select(ExchangeDryRun).where(ExchangeDryRun.bundle_id == bundle_ref))
    if dry is None:
        candidate = Path(bundle_ref).expanduser()
        if candidate.is_file():
            inspection = inspect_change_bundle(candidate)
            dry = session.scalar(
                select(ExchangeDryRun).where(
                    ExchangeDryRun.bundle_id == inspection.manifest.bundle_id
                )
            )
    if dry is None:
        raise ValueError("El paquete todavía no tiene una simulación persistida")
    if dry.base_match_status != "unmatched":
        raise ValueError("El diagnóstico EX-01A solo corresponde a paquetes sin base reconocida")
    if dry.lifecycle_status != "active":
        raise ValueError("Restaurá la entrada archivada antes de diagnosticar su linaje")

    workspace = _local_workspace(session, dry.workspace_id)
    record = session.get(ExchangeBundleRecord, dry.bundle_record_id)
    if record is None:
        raise ValueError("La simulación perdió el registro del paquete recibido")
    stored_path = _resolve_bundle_record_path(project_root, record)
    inspection = inspect_change_bundle(stored_path)
    target = inspection.manifest
    if target.bundle_id != dry.bundle_id:
        raise ValueError("El ZIP registrado no corresponde a la simulación seleccionada")
    if inspection.bundle_sha256 != record.bundle_sha256:
        raise ValueError("El ZIP registrado cambió después de la simulación")
    if target.project_id != project.id:
        raise ValueError("El paquete pertenece a otro proyecto")
    if target.source_workspace_id != dry.source_workspace_id:
        raise ValueError("La identidad de origen no coincide con la simulación")

    findings: list[LineageEvidenceFinding] = [
        LineageEvidenceFinding(
            artifact_type="received_bundle",
            artifact_reference=str(stored_path),
            artifact_sha256=inspection.bundle_sha256,
            verification_status="verified",
            strength="supporting",
            code="target_bundle_verified",
            explanation=(
                "El paquete recibido es íntegro y declara la base cuyo linaje debe demostrarse."
            ),
            project_id=target.project_id,
            workspace_id=target.source_workspace_id,
            sequence_number=target.base_sequence,
            checkpoint_id=target.base_checkpoint_id,
            checkpoint_label=target.base_checkpoint_label,
            state_sha256=target.base_checkpoint_state_sha256,
        )
    ]
    candidates: list[LineageRecoveryCandidate] = []
    contradictions = 0

    checkpoints = _checkpoint_candidates(
        session,
        workspace_id=workspace.id,
        state_sha256=target.base_checkpoint_state_sha256,
    )
    if checkpoints:
        checkpoint = checkpoints[0]
        explanation = (
            "La SQLite vigente conserva un punto de control con el SHA-256 exacto "
            "de la base declarada."
        )
        findings.append(
            LineageEvidenceFinding(
                artifact_type="local_database",
                artifact_reference=str((project_root / "data/archive_workbench.sqlite3").resolve()),
                artifact_sha256=None,
                verification_status="verified",
                strength="conclusive",
                code="local_exact_checkpoint",
                explanation=explanation,
                project_id=project.id,
                workspace_id=workspace.id,
                sequence_number=checkpoint.sequence_number,
                checkpoint_id=checkpoint.id,
                checkpoint_label=checkpoint.label,
                state_sha256=checkpoint.state_sha256,
                details={"matching_checkpoint_count": len(checkpoints)},
            )
        )
        candidates.append(
            _candidate_from_checkpoint(
                checkpoint,
                manifest=target,
                method="local_exact_checkpoint",
                reference="local_database",
                explanation=explanation,
            )
        )

    application_rows = _direct_application_rows(
        session,
        workspace_id=workspace.id,
        source_workspace_id=target.source_workspace_id,
        base_checkpoint_label=target.base_checkpoint_label,
        base_sequence=target.base_sequence,
    )
    for application, bundle_record, checkpoint in application_rows:
        if checkpoint is None:
            findings.append(
                LineageEvidenceFinding(
                    artifact_type="local_database",
                    artifact_reference="local_database",
                    artifact_sha256=None,
                    verification_status="verified",
                    strength="supporting",
                    code="local_application_without_checkpoint",
                    explanation=(
                        "La SQLite vigente conserva una aplicación compatible, pero la referencia "
                        "al punto de control local ya no existe."
                    ),
                    project_id=project.id,
                    workspace_id=workspace.id,
                    details={
                        "bundle_id": bundle_record.bundle_id,
                        "application_id": application.id,
                    },
                )
            )
            continue
        explanation = (
            "La SQLite vigente conserva una aplicación anterior del mismo origen que alcanzó "
            "exactamente la secuencia remota declarada."
        )
        findings.append(
            LineageEvidenceFinding(
                artifact_type="local_database",
                artifact_reference="local_database",
                artifact_sha256=None,
                verification_status="verified",
                strength="conclusive",
                code="local_applied_bundle",
                explanation=explanation,
                project_id=project.id,
                workspace_id=workspace.id,
                sequence_number=checkpoint.sequence_number,
                checkpoint_id=checkpoint.id,
                checkpoint_label=checkpoint.label,
                state_sha256=checkpoint.state_sha256,
                details={"bundle_id": bundle_record.bundle_id, "application_id": application.id},
            )
        )
        candidates.append(
            LineageRecoveryCandidate(
                fingerprint=(
                    f"local_application:{checkpoint.id}:{bundle_record.bundle_id}:"
                    f"{target.source_workspace_id}:{target.base_sequence}"
                ),
                method="local_applied_bundle",
                explanation=explanation,
                local_checkpoint_id=checkpoint.id,
                local_checkpoint_label=checkpoint.label,
                local_checkpoint_sequence=checkpoint.sequence_number,
                local_checkpoint_state_sha256=checkpoint.state_sha256,
                remote_workspace_id=target.source_workspace_id,
                remote_sequence=target.base_sequence,
                evidence_references=["local_database"],
            )
        )

    verified_bundles: list[_VerifiedBundle] = []
    seen_path_refs: set[str] = set()
    bundle_ids: dict[str, str] = {}
    for raw_path in evidence_paths:
        path = Path(raw_path).expanduser().resolve()
        reference = str(path)
        if reference in seen_path_refs:
            continue
        seen_path_refs.add(reference)
        if not path.is_file():
            findings.append(
                LineageEvidenceFinding(
                    artifact_type="unknown",
                    artifact_reference=reference,
                    artifact_sha256=None,
                    verification_status="rejected",
                    strength="rejected",
                    code="missing_artifact",
                    explanation="El artefacto indicado no existe o no es un archivo.",
                )
            )
            continue

        if path.suffix.lower() == ".json":
            try:
                manifest = _read_manifest_file(path)
            except Exception as exc:
                findings.append(
                    LineageEvidenceFinding(
                        artifact_type="bundle_manifest",
                        artifact_reference=reference,
                        artifact_sha256=sha256_file(path),
                        verification_status="rejected",
                        strength="rejected",
                        code="invalid_manifest",
                        explanation=f"Manifiesto rechazado: {exc}",
                    )
                )
                continue
            if manifest.project_id != project.id:
                findings.append(
                    LineageEvidenceFinding(
                        artifact_type="bundle_manifest",
                        artifact_reference=reference,
                        artifact_sha256=sha256_file(path),
                        verification_status="rejected",
                        strength="rejected",
                        code="different_project",
                        explanation="El manifiesto pertenece a otro proyecto.",
                        project_id=manifest.project_id,
                    )
                )
                continue
            findings.append(
                LineageEvidenceFinding(
                    artifact_type="bundle_manifest",
                    artifact_reference=reference,
                    artifact_sha256=sha256_file(path),
                    verification_status="verified",
                    strength="supporting",
                    code="isolated_manifest",
                    explanation=(
                        "El manifiesto es estructuralmente válido, pero aislado no demuestra "
                        "integridad del paquete ni lo ancla a un punto local."
                    ),
                    project_id=manifest.project_id,
                    workspace_id=manifest.source_workspace_id,
                    sequence_number=manifest.last_sequence,
                    checkpoint_id=manifest.base_checkpoint_id,
                    checkpoint_label=manifest.base_checkpoint_label,
                    state_sha256=manifest.base_checkpoint_state_sha256,
                )
            )
            continue

        bundle_error: Exception | None = None
        try:
            bundle_inspection = inspect_change_bundle(path)
        except Exception as exc:
            bundle_error = exc
        else:
            manifest = bundle_inspection.manifest
            if manifest.project_id != project.id:
                findings.append(
                    LineageEvidenceFinding(
                        artifact_type="change_bundle",
                        artifact_reference=reference,
                        artifact_sha256=bundle_inspection.bundle_sha256,
                        verification_status="rejected",
                        strength="rejected",
                        code="different_project",
                        explanation="El paquete pertenece a otro proyecto.",
                        project_id=manifest.project_id,
                    )
                )
                continue
            if manifest.source_workspace_id != target.source_workspace_id:
                findings.append(
                    LineageEvidenceFinding(
                        artifact_type="change_bundle",
                        artifact_reference=reference,
                        artifact_sha256=bundle_inspection.bundle_sha256,
                        verification_status="rejected",
                        strength="rejected",
                        code="different_source_workspace",
                        explanation="El paquete pertenece a otra copia de origen.",
                        project_id=manifest.project_id,
                        workspace_id=manifest.source_workspace_id,
                    )
                )
                continue
            previous_sha = bundle_ids.get(manifest.bundle_id)
            if previous_sha is not None and previous_sha != bundle_inspection.bundle_sha256:
                contradictions += 1
                findings.append(
                    LineageEvidenceFinding(
                        artifact_type="change_bundle",
                        artifact_reference=reference,
                        artifact_sha256=bundle_inspection.bundle_sha256,
                        verification_status="rejected",
                        strength="rejected",
                        code="conflicting_duplicate_bundle",
                        explanation=(
                            "Dos paquetes íntegros usan el mismo identificador con contenido "
                            "diferente; la evidencia es contradictoria."
                        ),
                        project_id=manifest.project_id,
                        workspace_id=manifest.source_workspace_id,
                        details={"bundle_id": manifest.bundle_id},
                    )
                )
                continue
            bundle_ids[manifest.bundle_id] = bundle_inspection.bundle_sha256
            verified = _VerifiedBundle(reference, bundle_inspection.bundle_sha256, manifest)
            verified_bundles.append(verified)
            findings.append(
                LineageEvidenceFinding(
                    artifact_type="change_bundle",
                    artifact_reference=reference,
                    artifact_sha256=bundle_inspection.bundle_sha256,
                    verification_status="verified",
                    strength="supporting",
                    code="verified_bundle",
                    explanation=(
                        "El paquete es íntegro y puede participar en una cadena; su valor "
                        "probatorio depende de que conecte secuencias sin huecos."
                    ),
                    project_id=manifest.project_id,
                    workspace_id=manifest.source_workspace_id,
                    sequence_number=manifest.last_sequence,
                    checkpoint_id=manifest.base_checkpoint_id,
                    checkpoint_label=manifest.base_checkpoint_label,
                    state_sha256=manifest.base_checkpoint_state_sha256,
                    details={"bundle_id": manifest.bundle_id},
                )
            )
            continue

        backup_findings, backup_candidates, backup_contradiction = _inspect_backup_evidence(
            path,
            project_id=project.id,
            local_workspace_id=workspace.id,
            target=target,
        )
        if (
            len(backup_findings) == 1
            and backup_findings[0].code == "invalid_backup"
            and bundle_error is not None
        ):
            backup_findings[0].artifact_type = "unknown"
            backup_findings[0].code = "unrecognized_artifact"
            backup_findings[0].explanation = (
                f"El archivo no es un paquete de intercambio válido ({bundle_error}) ni un "
                f"backup de proyecto válido ({backup_findings[0].explanation})."
            )
        findings.extend(backup_findings)
        candidates.extend(backup_candidates)
        contradictions += int(backup_contradiction)

    target_verified = _VerifiedBundle(str(stored_path), inspection.bundle_sha256, target)
    chain_candidates, chain_findings, chain_ambiguous = _chain_candidates(
        session,
        local_workspace_id=workspace.id,
        target=target_verified,
        bundles=verified_bundles,
    )
    candidates.extend(chain_candidates)
    findings.extend(chain_findings)
    if chain_ambiguous:
        contradictions += 1

    unique: dict[str, LineageRecoveryCandidate] = {}
    for candidate in candidates:
        operational_key = ":".join(
            [
                candidate.local_checkpoint_id or "-",
                candidate.local_checkpoint_state_sha256 or "-",
                candidate.remote_workspace_id,
                str(candidate.remote_sequence),
                ",".join(candidate.chain_bundle_ids),
            ]
        )
        existing = unique.get(operational_key)
        if existing is None:
            unique[operational_key] = candidate
        else:
            existing.evidence_references = list(
                dict.fromkeys(existing.evidence_references + candidate.evidence_references)
            )
            if existing.method != candidate.method:
                existing.explanation += (
                    " La misma cadena queda corroborada por más de un tipo de evidencia."
                )
    final_candidates = list(unique.values())

    # Candidatos diferentes pueden ser compatibles en sentido histórico, pero EX-01 exige
    # una única cadena operativa antes de permitir cualquier escritura posterior.
    if contradictions or len(final_candidates) > 1:
        classification = "ambiguous"
        summary = (
            "La evidencia contiene más de una cadena o explicación posible. No debe "
            "recuperarse linaje hasta resolver la contradicción."
        )
    elif len(final_candidates) == 1:
        classification = "recoverable"
        summary = (
            "Existe una cadena concluyente y única. EX-01A no escribe nada; una fase posterior "
            "podrá presentar esta evidencia para confirmación explícita."
        )
    else:
        classification = "insufficient"
        summary = (
            "No existe evidencia concluyente suficiente. Resolver campos o aplicar decisiones "
            "de contenido no crea parentesco."
        )

    return LineageDiagnosticReport(
        bundle_id=target.bundle_id,
        bundle_sha256=inspection.bundle_sha256,
        project_id=project.id,
        local_workspace_id=workspace.id,
        local_workspace_name=workspace.workspace_name,
        source_workspace_id=target.source_workspace_id,
        source_workspace_name=target.source_workspace_name,
        base_checkpoint_id=target.base_checkpoint_id,
        base_checkpoint_label=target.base_checkpoint_label,
        base_checkpoint_state_sha256=target.base_checkpoint_state_sha256,
        base_sequence=target.base_sequence,
        classification=classification,
        summary=summary,
        findings=findings,
        recovery_candidates=final_candidates,
        contradiction_count=contradictions,
    )
