from __future__ import annotations

import hashlib
import json
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from archive_workbench.db.migrations import current_revision
from archive_workbench.db.models import (
    ExchangeChangeEvent,
    ExchangeCommonBaseAgreement,
    ExchangeDryRun,
    ExchangeWorkspace,
    Project,
    utc_now,
)
from archive_workbench.exchange import (
    create_exchange_checkpoint,
    current_editable_state_sha256,
    ensure_exchange_workspace,
)
from archive_workbench.identity import new_id, sha256_file, sha256_json, short_id, slugify
from archive_workbench.version import __version__


COMMON_BASE_SCHEMA_VERSION = "1.0"
COMMON_BASE_ADOPTED_STATE = "reconciled"


class CommonBaseProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = COMMON_BASE_SCHEMA_VERSION
    artifact_type: Literal["common_base_proposal"] = "common_base_proposal"
    agreement_id: str = Field(min_length=36, max_length=36)
    project_id: str
    initiator_workspace_id: str = Field(min_length=36, max_length=36)
    initiator_workspace_name: str
    initiator_sequence: int = Field(ge=0)
    initiator_state_sha256: str = Field(min_length=64, max_length=64)
    counterpart_workspace_id: str = Field(min_length=36, max_length=36)
    counterpart_workspace_name: str
    adopted_state: Literal["reconciled"] = COMMON_BASE_ADOPTED_STATE
    proposed_by: str
    proposal_reason: str
    app_version: str
    database_revision: str
    created_at: datetime


class CommonBaseAgreementManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = COMMON_BASE_SCHEMA_VERSION
    artifact_type: Literal["common_base_agreement"] = "common_base_agreement"
    agreement_id: str = Field(min_length=36, max_length=36)
    project_id: str
    adopted_state: Literal["reconciled"] = COMMON_BASE_ADOPTED_STATE
    state_sha256: str = Field(min_length=64, max_length=64)
    checkpoint_label: str
    proposal_sha256: str = Field(min_length=64, max_length=64)
    initiator_workspace_id: str = Field(min_length=36, max_length=36)
    initiator_workspace_name: str
    initiator_sequence: int = Field(ge=0)
    initiator_confirmed_by: str
    initiator_confirmation_reason: str
    counterpart_workspace_id: str = Field(min_length=36, max_length=36)
    counterpart_workspace_name: str
    counterpart_sequence: int = Field(ge=0)
    counterpart_confirmed_by: str
    counterpart_confirmation_reason: str
    accepted_at: datetime
    app_version: str
    database_revision: str


@dataclass(slots=True)
class CommonBaseProposalSummary:
    agreement_id: str
    output_path: Path
    proposal_sha256: str
    artifact_sha256: str
    state_sha256: str
    initiator_workspace_id: str
    counterpart_workspace_id: str
    initiator_sequence: int


@dataclass(slots=True)
class CommonBaseAgreementSummary:
    agreement_id: str
    local_record_id: str
    local_role: str
    output_path: Path | None
    proposal_sha256: str
    manifest_sha256: str
    state_sha256: str
    checkpoint_id: str
    checkpoint_label: str
    local_workspace_id: str
    counterpart_workspace_id: str
    local_sequence: int
    counterpart_sequence: int
    stale_dry_run_count: int


@dataclass(slots=True)
class CommonBaseAgreementRow:
    agreement_id: str
    local_role: str
    local_workspace_id: str
    counterpart_workspace_id: str
    local_sequence: int
    counterpart_sequence: int
    state_sha256: str
    checkpoint_id: str
    checkpoint_label: str
    manifest_sha256: str
    proposal_sha256: str
    registered_by: str
    registration_reason: str
    source: str
    created_at: datetime


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _manifest_bytes(model: BaseModel) -> bytes:
    return _canonical_json_bytes(model.model_dump(mode="json", exclude_none=True)) + b"\n"


def _write_zip(path: Path, entries: dict[str, bytes]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    with zipfile.ZipFile(temp, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name in sorted(entries):
            info = zipfile.ZipInfo(name)
            info.date_time = (1980, 1, 1, 0, 0, 0)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o600 << 16
            archive.writestr(info, entries[name])
    temp.replace(path)


def _checksum_bytes(entries: dict[str, bytes]) -> bytes:
    return "".join(
        f"{hashlib.sha256(entries[name]).hexdigest()}  {name}\n"
        for name in sorted(entries)
    ).encode("utf-8")


def _read_verified_zip(path: Path, *, allowed: set[str]) -> dict[str, bytes]:
    artifact = path.expanduser().resolve()
    if not artifact.is_file():
        raise ValueError(f"No existe el artefacto: {artifact}")
    try:
        with zipfile.ZipFile(artifact, "r") as archive:
            names = set(archive.namelist())
            unsafe = [
                name
                for name in names
                if Path(name).is_absolute() or ".." in Path(name).parts
            ]
            if unsafe:
                raise ValueError("El ZIP contiene rutas inseguras")
            if names != allowed:
                missing = sorted(allowed - names)
                extra = sorted(names - allowed)
                raise ValueError(
                    "El artefacto no contiene exactamente los archivos esperados. "
                    f"Faltantes: {missing or '-'}; adicionales: {extra or '-'}"
                )
            entries = {name: archive.read(name) for name in names}
    except zipfile.BadZipFile as exc:
        raise ValueError("El artefacto no es un ZIP válido") from exc

    expected: dict[str, str] = {}
    for raw in entries["checksums.sha256"].decode("utf-8").splitlines():
        if not raw.strip():
            continue
        pieces = raw.split(maxsplit=1)
        if len(pieces) != 2:
            raise ValueError("El archivo de checksums es inválido")
        expected[pieces[1].strip()] = pieces[0].strip().lower()
    payload_names = allowed - {"README.txt", "checksums.sha256"}
    if set(expected) != payload_names:
        raise ValueError("El archivo de checksums no cubre exactamente los manifiestos")
    for name in payload_names:
        observed = hashlib.sha256(entries[name]).hexdigest()
        if observed != expected[name]:
            raise ValueError(f"El checksum no coincide para {name}")
    return entries


def inspect_common_base_proposal(
    path: Path,
) -> tuple[CommonBaseProposal, str, str, bytes]:
    entries = _read_verified_zip(
        path,
        allowed={"README.txt", "checksums.sha256", "proposal.json"},
    )
    payload = entries["proposal.json"]
    try:
        proposal = CommonBaseProposal.model_validate_json(payload)
    except Exception as exc:  # pydantic comunica detalles internos poco útiles aquí
        raise ValueError("El manifiesto de propuesta no cumple el contrato 1.0") from exc
    return proposal, hashlib.sha256(payload).hexdigest(), sha256_file(path), payload


def inspect_common_base_agreement(
    path: Path,
) -> tuple[CommonBaseAgreementManifest, CommonBaseProposal, str, str, bytes]:
    entries = _read_verified_zip(
        path,
        allowed={
            "README.txt",
            "agreement.json",
            "checksums.sha256",
            "proposal.json",
        },
    )
    agreement_payload = entries["agreement.json"]
    proposal_payload = entries["proposal.json"]
    try:
        agreement = CommonBaseAgreementManifest.model_validate_json(agreement_payload)
        proposal = CommonBaseProposal.model_validate_json(proposal_payload)
    except Exception as exc:
        raise ValueError("El manifiesto de acuerdo no cumple el contrato 1.0") from exc
    proposal_sha = hashlib.sha256(proposal_payload).hexdigest()
    if agreement.proposal_sha256 != proposal_sha:
        raise ValueError("El acuerdo no refiere al manifiesto de propuesta incluido")
    if agreement.agreement_id != proposal.agreement_id:
        raise ValueError("El acuerdo y la propuesta tienen identificadores distintos")
    if agreement.project_id != proposal.project_id:
        raise ValueError("El acuerdo y la propuesta pertenecen a proyectos distintos")
    if agreement.initiator_workspace_id != proposal.initiator_workspace_id:
        raise ValueError("El acuerdo cambió la identidad de la copia iniciadora")
    if agreement.counterpart_workspace_id != proposal.counterpart_workspace_id:
        raise ValueError("El acuerdo cambió la identidad de la contraparte")
    if agreement.initiator_sequence != proposal.initiator_sequence:
        raise ValueError("El acuerdo cambió la secuencia declarada por la copia iniciadora")
    if agreement.state_sha256 != proposal.initiator_state_sha256:
        raise ValueError("El acuerdo cambió la huella editable propuesta")
    return (
        agreement,
        proposal,
        hashlib.sha256(agreement_payload).hexdigest(),
        sha256_file(path),
        proposal_payload,
    )


def _single_project(session: Session) -> Project:
    rows = session.scalars(select(Project).order_by(Project.created_at, Project.id)).all()
    if not rows:
        raise ValueError("El proyecto todavía no está registrado en SQLite")
    if len(rows) != 1:
        raise ValueError("La base contiene más de un proyecto")
    return rows[0]


def _current_sequence(session: Session, workspace_id: str) -> int:
    value = session.scalar(
        select(func.max(ExchangeChangeEvent.sequence_number)).where(
            ExchangeChangeEvent.workspace_id == workspace_id
        )
    )
    return int(value or 0)


def _clean_confirmation(
    *, actor: str, reason: str, confirmed: bool, source: str
) -> tuple[str, str, str]:
    clean_actor = actor.strip()
    clean_reason = reason.strip()
    clean_source = source.strip().lower()
    if not confirmed:
        raise ValueError("Marcá la confirmación explícita antes de registrar el acuerdo")
    if not clean_actor:
        raise ValueError("Indicá quién confirma la operación")
    if not clean_reason:
        raise ValueError("Escribí el fundamento de la operación")
    if clean_source not in {"ui", "cli", "api", "script"}:
        raise ValueError("El origen de la operación no es válido")
    return clean_actor, clean_reason, clean_source


def _checkpoint_label(agreement_id: str) -> str:
    return f"common_base_{short_id(agreement_id)}"


def _stale_active_dry_runs(session: Session) -> int:
    rows = session.scalars(
        select(ExchangeDryRun).where(
            ExchangeDryRun.lifecycle_status == "active",
            ExchangeDryRun.overall_status != "stale",
        )
    ).all()
    for row in rows:
        row.overall_status = "stale"
    return len(rows)


def _existing_agreement(session: Session, agreement_id: str) -> ExchangeCommonBaseAgreement | None:
    return session.scalar(
        select(ExchangeCommonBaseAgreement).where(
            ExchangeCommonBaseAgreement.agreement_id == agreement_id
        )
    )


def create_common_base_proposal(
    session: Session,
    *,
    project_root: Path,
    counterpart_workspace_id: str,
    counterpart_workspace_name: str,
    proposed_by: str,
    proposal_reason: str,
    proposal_confirmed: bool,
    source: str,
    destination: Path | None = None,
) -> CommonBaseProposalSummary:
    actor, reason, _clean_source = _clean_confirmation(
        actor=proposed_by,
        reason=proposal_reason,
        confirmed=proposal_confirmed,
        source=source,
    )
    counterpart_id = counterpart_workspace_id.strip()
    counterpart_name = counterpart_workspace_name.strip()
    if not counterpart_id:
        raise ValueError("Indicá el identificador de la copia contraparte")
    if not counterpart_name:
        raise ValueError("Indicá el nombre de la copia contraparte")

    project = _single_project(session)
    workspace = ensure_exchange_workspace(session, changed_by=actor)
    if counterpart_id == workspace.id:
        raise ValueError("La propuesta debe dirigirse a otra copia")
    assert workspace.project_id is not None
    sequence = _current_sequence(session, workspace.id)
    state_sha = current_editable_state_sha256(session, project.id)
    agreement_id = new_id()
    proposal = CommonBaseProposal(
        agreement_id=agreement_id,
        project_id=project.id,
        initiator_workspace_id=workspace.id,
        initiator_workspace_name=workspace.workspace_name,
        initiator_sequence=sequence,
        initiator_state_sha256=state_sha,
        counterpart_workspace_id=counterpart_id,
        counterpart_workspace_name=counterpart_name,
        proposed_by=actor,
        proposal_reason=reason,
        app_version=__version__,
        database_revision=current_revision(project_root) or "unknown",
        created_at=datetime.now(timezone.utc),
    )
    proposal_bytes = _manifest_bytes(proposal)
    proposal_sha = hashlib.sha256(proposal_bytes).hexdigest()
    if destination is None:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        destination = (
            project_root.resolve()
            / "exchange"
            / "common_base"
            / "outgoing"
            / f"{timestamp}_{slugify(workspace.workspace_name, 32)}_{short_id(agreement_id)}_proposal.zip"
        )
    destination = destination.expanduser().resolve()
    payloads = {"proposal.json": proposal_bytes}
    _write_zip(
        destination,
        {
            "README.txt": (
                "Archive Workbench — propuesta de base común offline\n"
                "La propuesta no activa ningún acuerdo. La contraparte debe verificar y aceptar.\n"
            ).encode("utf-8"),
            "checksums.sha256": _checksum_bytes(payloads),
            **payloads,
        },
    )
    return CommonBaseProposalSummary(
        agreement_id=agreement_id,
        output_path=destination,
        proposal_sha256=proposal_sha,
        artifact_sha256=sha256_file(destination),
        state_sha256=state_sha,
        initiator_workspace_id=workspace.id,
        counterpart_workspace_id=counterpart_id,
        initiator_sequence=sequence,
    )


def _record_agreement(
    session: Session,
    *,
    project: Project,
    workspace: ExchangeWorkspace,
    agreement: CommonBaseAgreementManifest,
    proposal_sha256: str,
    manifest_sha256: str,
    local_role: str,
    local_sequence: int,
    counterpart_sequence: int,
    checkpoint_id: str,
    checkpoint_label: str,
    source: str,
    registered_by: str,
    registration_reason: str,
    parameters_sha256: str,
) -> ExchangeCommonBaseAgreement:
    row = ExchangeCommonBaseAgreement(
        id=new_id(),
        agreement_id=agreement.agreement_id,
        project_id=project.id,
        local_workspace_id=workspace.id,
        counterpart_workspace_id=(
            agreement.counterpart_workspace_id
            if local_role == "initiator"
            else agreement.initiator_workspace_id
        ),
        local_role=local_role,
        adopted_state=agreement.adopted_state,
        state_sha256=agreement.state_sha256,
        local_sequence=local_sequence,
        counterpart_sequence=counterpart_sequence,
        local_checkpoint_id=checkpoint_id,
        local_checkpoint_label=checkpoint_label,
        proposal_sha256=proposal_sha256,
        manifest_sha256=manifest_sha256,
        manifest_version=agreement.schema_version,
        initiator_workspace_id=agreement.initiator_workspace_id,
        initiator_workspace_name=agreement.initiator_workspace_name,
        initiator_sequence=agreement.initiator_sequence,
        initiator_confirmed_by=agreement.initiator_confirmed_by,
        initiator_confirmation_reason=agreement.initiator_confirmation_reason,
        counterpart_workspace_name=agreement.counterpart_workspace_name,
        counterpart_confirmed_by=agreement.counterpart_confirmed_by,
        counterpart_confirmation_reason=agreement.counterpart_confirmation_reason,
        source=source,
        registered_by=registered_by,
        registration_reason=registration_reason,
        parameters_sha256=parameters_sha256,
        result="active",
        created_at=agreement.accepted_at,
        registered_at=utc_now(),
    )
    session.add(row)
    session.flush()
    return row


def accept_common_base_proposal(
    session: Session,
    *,
    project_root: Path,
    proposal_path: Path,
    accepted_by: str,
    confirmation_reason: str,
    agreement_confirmed: bool,
    source: str,
    destination: Path | None = None,
) -> CommonBaseAgreementSummary:
    actor, reason, clean_source = _clean_confirmation(
        actor=accepted_by,
        reason=confirmation_reason,
        confirmed=agreement_confirmed,
        source=source,
    )
    proposal, proposal_sha, _artifact_sha, proposal_bytes = inspect_common_base_proposal(
        proposal_path
    )
    project = _single_project(session)
    workspace = ensure_exchange_workspace(session, changed_by=actor)
    if proposal.project_id != project.id:
        raise ValueError("La propuesta pertenece a otro proyecto")
    if proposal.counterpart_workspace_id != workspace.id:
        raise ValueError("La propuesta no está dirigida a esta copia")
    if proposal.counterpart_workspace_name != workspace.workspace_name:
        raise ValueError("El nombre de la contraparte no coincide con esta copia")
    if proposal.initiator_workspace_id == workspace.id:
        raise ValueError("Las dos partes del acuerdo deben ser copias distintas")
    if _existing_agreement(session, proposal.agreement_id) is not None:
        raise ValueError("Este acuerdo ya fue registrado en la copia local")

    local_sequence = _current_sequence(session, workspace.id)
    local_state = current_editable_state_sha256(session, project.id)
    if local_state != proposal.initiator_state_sha256:
        raise ValueError(
            "Los estados editables difieren. EX-01C solo admite copias ya reconciliadas e idénticas"
        )
    checkpoint_label = _checkpoint_label(proposal.agreement_id)
    agreement = CommonBaseAgreementManifest(
        agreement_id=proposal.agreement_id,
        project_id=proposal.project_id,
        state_sha256=local_state,
        checkpoint_label=checkpoint_label,
        proposal_sha256=proposal_sha,
        initiator_workspace_id=proposal.initiator_workspace_id,
        initiator_workspace_name=proposal.initiator_workspace_name,
        initiator_sequence=proposal.initiator_sequence,
        initiator_confirmed_by=proposal.proposed_by,
        initiator_confirmation_reason=proposal.proposal_reason,
        counterpart_workspace_id=workspace.id,
        counterpart_workspace_name=workspace.workspace_name,
        counterpart_sequence=local_sequence,
        counterpart_confirmed_by=actor,
        counterpart_confirmation_reason=reason,
        accepted_at=datetime.now(timezone.utc),
        app_version=__version__,
        database_revision=current_revision(project_root) or "unknown",
    )
    agreement_bytes = _manifest_bytes(agreement)
    manifest_sha = hashlib.sha256(agreement_bytes).hexdigest()
    if destination is None:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        destination = (
            project_root.resolve()
            / "exchange"
            / "common_base"
            / "outgoing"
            / f"{timestamp}_{short_id(agreement.agreement_id)}_agreement.zip"
        )
    destination = destination.expanduser().resolve()
    payloads = {
        "agreement.json": agreement_bytes,
        "proposal.json": proposal_bytes,
    }
    _write_zip(
        destination,
        {
            "README.txt": (
                "Archive Workbench — acuerdo bilateral de base común\n"
                "La copia iniciadora debe finalizar este mismo manifiesto antes de usar la base.\n"
            ).encode("utf-8"),
            "checksums.sha256": _checksum_bytes(payloads),
            **payloads,
        },
    )

    checkpoint = create_exchange_checkpoint(
        session,
        label=checkpoint_label,
        created_by=actor,
        note=(
            "Punto de control vinculado al acuerdo bilateral de base común "
            f"{agreement.agreement_id}"
        ),
    )
    if checkpoint.state_sha256 != agreement.state_sha256:
        raise ValueError("El estado editable cambió durante la aceptación del acuerdo")
    stale_count = _stale_active_dry_runs(session)
    parameters_sha = sha256_json(
        {
            "schema_version": "ex01c-1",
            "operation": "accept_common_base",
            "agreement": agreement.model_dump(mode="json"),
            "manifest_sha256": manifest_sha,
            "proposal_sha256": proposal_sha,
            "local_checkpoint_id": checkpoint.id,
            "source": clean_source,
            "registered_by": actor,
            "registration_reason": reason,
        }
    )
    row = _record_agreement(
        session,
        project=project,
        workspace=workspace,
        agreement=agreement,
        proposal_sha256=proposal_sha,
        manifest_sha256=manifest_sha,
        local_role="counterpart",
        local_sequence=local_sequence,
        counterpart_sequence=proposal.initiator_sequence,
        checkpoint_id=checkpoint.id,
        checkpoint_label=checkpoint.label,
        source=clean_source,
        registered_by=actor,
        registration_reason=reason,
        parameters_sha256=parameters_sha,
    )
    return CommonBaseAgreementSummary(
        agreement_id=agreement.agreement_id,
        local_record_id=row.id,
        local_role=row.local_role,
        output_path=destination,
        proposal_sha256=proposal_sha,
        manifest_sha256=manifest_sha,
        state_sha256=agreement.state_sha256,
        checkpoint_id=checkpoint.id,
        checkpoint_label=checkpoint.label,
        local_workspace_id=workspace.id,
        counterpart_workspace_id=proposal.initiator_workspace_id,
        local_sequence=local_sequence,
        counterpart_sequence=proposal.initiator_sequence,
        stale_dry_run_count=stale_count,
    )


def finalize_common_base_agreement(
    session: Session,
    *,
    project_root: Path,
    proposal_path: Path,
    agreement_path: Path,
    finalized_by: str,
    confirmation_reason: str,
    agreement_confirmed: bool,
    source: str,
) -> CommonBaseAgreementSummary:
    actor, reason, clean_source = _clean_confirmation(
        actor=finalized_by,
        reason=confirmation_reason,
        confirmed=agreement_confirmed,
        source=source,
    )
    proposal, proposal_sha, _proposal_artifact_sha, proposal_bytes = (
        inspect_common_base_proposal(proposal_path)
    )
    agreement, embedded_proposal, manifest_sha, _agreement_artifact_sha, embedded_bytes = (
        inspect_common_base_agreement(agreement_path)
    )
    if proposal_bytes != embedded_bytes or proposal != embedded_proposal:
        raise ValueError("El acuerdo no contiene exactamente la propuesta seleccionada")
    if agreement.proposal_sha256 != proposal_sha:
        raise ValueError("El acuerdo no coincide con la huella de la propuesta")

    project = _single_project(session)
    workspace = ensure_exchange_workspace(session, changed_by=actor)
    if agreement.project_id != project.id:
        raise ValueError("El acuerdo pertenece a otro proyecto")
    if agreement.initiator_workspace_id != workspace.id:
        raise ValueError("Este acuerdo debe finalizarse en la copia iniciadora")
    if agreement.counterpart_workspace_id == workspace.id:
        raise ValueError("Las dos partes del acuerdo deben ser copias distintas")
    if _existing_agreement(session, agreement.agreement_id) is not None:
        raise ValueError("Este acuerdo ya fue registrado en la copia local")

    local_sequence = _current_sequence(session, workspace.id)
    local_state = current_editable_state_sha256(session, project.id)
    if local_sequence != proposal.initiator_sequence:
        raise ValueError(
            "La secuencia de la copia iniciadora cambió después de crear la propuesta"
        )
    if local_state != agreement.state_sha256:
        raise ValueError(
            "El estado editable de la copia iniciadora ya no coincide con el acuerdo"
        )
    checkpoint = create_exchange_checkpoint(
        session,
        label=agreement.checkpoint_label,
        created_by=actor,
        note=(
            "Punto de control vinculado al acuerdo bilateral de base común "
            f"{agreement.agreement_id}"
        ),
    )
    if checkpoint.state_sha256 != agreement.state_sha256:
        raise ValueError("El estado editable cambió durante la finalización del acuerdo")
    stale_count = _stale_active_dry_runs(session)
    parameters_sha = sha256_json(
        {
            "schema_version": "ex01c-1",
            "operation": "finalize_common_base",
            "agreement": agreement.model_dump(mode="json"),
            "manifest_sha256": manifest_sha,
            "proposal_sha256": proposal_sha,
            "local_checkpoint_id": checkpoint.id,
            "source": clean_source,
            "registered_by": actor,
            "registration_reason": reason,
        }
    )
    row = _record_agreement(
        session,
        project=project,
        workspace=workspace,
        agreement=agreement,
        proposal_sha256=proposal_sha,
        manifest_sha256=manifest_sha,
        local_role="initiator",
        local_sequence=local_sequence,
        counterpart_sequence=agreement.counterpart_sequence,
        checkpoint_id=checkpoint.id,
        checkpoint_label=checkpoint.label,
        source=clean_source,
        registered_by=actor,
        registration_reason=reason,
        parameters_sha256=parameters_sha,
    )
    return CommonBaseAgreementSummary(
        agreement_id=agreement.agreement_id,
        local_record_id=row.id,
        local_role=row.local_role,
        output_path=None,
        proposal_sha256=proposal_sha,
        manifest_sha256=manifest_sha,
        state_sha256=agreement.state_sha256,
        checkpoint_id=checkpoint.id,
        checkpoint_label=checkpoint.label,
        local_workspace_id=workspace.id,
        counterpart_workspace_id=agreement.counterpart_workspace_id,
        local_sequence=local_sequence,
        counterpart_sequence=agreement.counterpart_sequence,
        stale_dry_run_count=stale_count,
    )


def common_base_agreement_rows(session: Session) -> list[CommonBaseAgreementRow]:
    rows = session.scalars(
        select(ExchangeCommonBaseAgreement).order_by(
            ExchangeCommonBaseAgreement.registered_at.desc(),
            ExchangeCommonBaseAgreement.id,
        )
    ).all()
    return [
        CommonBaseAgreementRow(
            agreement_id=row.agreement_id,
            local_role=row.local_role,
            local_workspace_id=row.local_workspace_id,
            counterpart_workspace_id=row.counterpart_workspace_id,
            local_sequence=row.local_sequence,
            counterpart_sequence=row.counterpart_sequence,
            state_sha256=row.state_sha256,
            checkpoint_id=row.local_checkpoint_id,
            checkpoint_label=row.local_checkpoint_label,
            manifest_sha256=row.manifest_sha256,
            proposal_sha256=row.proposal_sha256,
            registered_by=row.registered_by,
            registration_reason=row.registration_reason,
            source=row.source,
            created_at=row.registered_at,
        )
        for row in rows
    ]
