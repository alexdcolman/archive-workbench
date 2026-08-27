from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from hashlib import sha256
import json
from typing import Any, Iterable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from archive_workbench.authorities import (
    create_authority,
    create_mention,
    normalize_authority_text,
)
from archive_workbench.db.models import (
    AuthorityRecord,
    DiscoveryCandidate,
    DiscoveryContextRecord,
    DiscoveryDecision,
    EditableObject,
    EntityMention,
    Project,
    utc_now,
)
from archive_workbench.identity import new_id
from archive_workbench.open_discovery import DISCOVERY_FAMILIES, family_label
from archive_workbench.temporal import parse_temporal_expression

DISCOVERY_DECISION_TYPES = ("accept", "reject", "modify", "defer")
DISCOVERY_ACCEPTANCE_MODES = (
    "existing_authority",
    "new_authority",
    "structured_record",
)
DISCOVERY_TERMINAL_STATUSES = ("accepted", "rejected")
DISCOVERY_CONTEXT_FAMILIES = ("time", "event", "action_process", "other")

_DECISION_LABELS = {
    "accept": "Aceptado",
    "reject": "Rechazado",
    "modify": "Modificado",
    "defer": "Aplazado",
    "restore": "Restaurado para revisión",
}
_STATUS_LABELS = {
    "pending": "Pendiente",
    "accepted": "Aceptado",
    "rejected": "Rechazado",
    "modified": "Modificado",
    "deferred": "Aplazado",
}
_ACCEPTANCE_LABELS = {
    "existing_authority": "Vínculo con una autoridad existente",
    "new_authority": "Nueva autoridad sin revisar",
    "structured_record": "Registro propio de la familia",
}


@dataclass(frozen=True, slots=True)
class EffectiveCandidateValues:
    text: str
    semantic_family: str
    subtype: str


@dataclass(frozen=True, slots=True)
class DiscoveryDecisionSummary:
    decision_id: str
    candidate_id: str
    decision_number: int
    decision_type: str
    candidate_status: str
    reviewed_text: str
    semantic_family: str
    reviewed_subtype: str
    acceptance_mode: str | None
    target_authority_id: str | None
    created_mention_id: str | None
    context_record_id: str | None


@dataclass(frozen=True, slots=True)
class DiscoveryDecisionRow:
    decision_id: str
    candidate_id: str
    decision_number: int
    decision_type: str
    decision_label: str
    reviewed_text: str
    semantic_family: str
    family_label: str
    reviewed_subtype: str
    acceptance_mode: str | None
    acceptance_label: str | None
    target_authority_id: str | None
    target_authority_name: str | None
    created_mention_id: str | None
    reason: str | None
    source: str
    candidate_state_sha256: str
    payload: dict[str, Any]
    decided_by: str
    decided_at: datetime


@dataclass(frozen=True, slots=True)
class DiscoveryContextRecordRow:
    record_id: str
    candidate_id: str
    decision_id: str
    semantic_family: str
    family_label: str
    subtype: str
    label: str
    description: str | None
    temporal_expression: str | None
    temporal_start: date | None
    temporal_end: date | None
    temporal_precision: str | None
    temporal_approximate: bool
    target_authority_id: str | None
    data: dict[str, Any]
    created_by: str
    created_at: datetime


def decision_label(value: str) -> str:
    return _DECISION_LABELS.get(value, value)


def candidate_status_label(value: str) -> str:
    return _STATUS_LABELS.get(value, value)


def acceptance_mode_label(value: str | None) -> str | None:
    return _ACCEPTANCE_LABELS.get(value, value) if value else None


def candidate_is_stale(session: Session, candidate: DiscoveryCandidate) -> bool:
    current = session.get(EditableObject, candidate.editable_object_id)
    if current is None or current.revision_number != candidate.object_revision_number:
        return True
    return current.current_text[candidate.start_offset : candidate.end_offset] != candidate.exact_text


def _clean_required(value: str, *, field: str, maximum: int = 2000) -> str:
    clean = " ".join((value or "").split())
    if not clean:
        raise ValueError(f"{field} no puede quedar vacío")
    if len(clean) > maximum:
        raise ValueError(f"{field} no puede superar {maximum} caracteres")
    return clean


def _clean_optional(value: str | None, *, maximum: int = 4000) -> str | None:
    if value is None:
        return None
    clean = " ".join(value.split())
    if not clean:
        return None
    if len(clean) > maximum:
        raise ValueError(f"El texto no puede superar {maximum} caracteres")
    return clean


def _latest_decision(session: Session, candidate_id: str) -> DiscoveryDecision | None:
    return session.scalar(
        select(DiscoveryDecision)
        .where(DiscoveryDecision.candidate_id == candidate_id)
        .order_by(DiscoveryDecision.decision_number.desc())
        .limit(1)
    )


def effective_candidate_values(
    session: Session, candidate: DiscoveryCandidate
) -> EffectiveCandidateValues:
    latest = _latest_decision(session, candidate.id)
    if latest is None:
        return EffectiveCandidateValues(
            text=candidate.exact_text,
            semantic_family=candidate.semantic_family,
            subtype=candidate.suggested_subtype,
        )
    return EffectiveCandidateValues(
        text=latest.reviewed_text,
        semantic_family=latest.semantic_family,
        subtype=latest.reviewed_subtype,
    )


def allowed_acceptance_modes(semantic_family: str) -> tuple[str, ...]:
    if semantic_family in {"actor", "space", "work"}:
        return ("existing_authority", "new_authority")
    if semantic_family == "event":
        return DISCOVERY_ACCEPTANCE_MODES
    if semantic_family in {"time", "action_process", "other"}:
        return ("structured_record",)
    raise ValueError(f"Familia semántica inválida: {semantic_family}")


def allowed_authority_types(semantic_family: str, subtype: str) -> tuple[str, ...]:
    if semantic_family == "actor":
        if subtype == "person":
            return ("person",)
        if subtype == "organization":
            return ("organization",)
        return ("person", "organization", "other")
    if semantic_family == "space":
        return ("place",)
    if semantic_family == "event":
        return ("event",)
    if semantic_family == "work":
        return ("work",)
    return ()


def inferred_authority_type(semantic_family: str, subtype: str) -> str:
    allowed = allowed_authority_types(semantic_family, subtype)
    if not allowed:
        raise ValueError(
            f"La familia {family_label(semantic_family)} no se convierte en autoridad"
        )
    if len(allowed) == 1:
        return allowed[0]
    return "other"


def _candidate_state_sha256(candidate: DiscoveryCandidate) -> str:
    payload = {
        "candidate_id": candidate.id,
        "run_id": candidate.run_id,
        "editable_object_id": candidate.editable_object_id,
        "object_revision_number": candidate.object_revision_number,
        "start_offset": candidate.start_offset,
        "end_offset": candidate.end_offset,
        "exact_text": candidate.exact_text,
        "semantic_family": candidate.semantic_family,
        "suggested_subtype": candidate.suggested_subtype,
        "parameters_sha256": candidate.parameters_sha256,
    }
    rendered = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return sha256(rendered).hexdigest()


def _next_decision_number(session: Session, candidate_id: str) -> int:
    current = session.scalar(
        select(func.max(DiscoveryDecision.decision_number)).where(
            DiscoveryDecision.candidate_id == candidate_id
        )
    )
    return int(current or 0) + 1


def _ensure_project(session: Session, project_id: str) -> None:
    if session.get(Project, project_id) is None:
        raise ValueError(f"Proyecto inexistente: {project_id}")


def _resolve_authority(
    session: Session,
    *,
    project_id: str,
    authority_id: str,
    semantic_family: str,
    subtype: str,
) -> AuthorityRecord:
    authority = session.get(AuthorityRecord, authority_id)
    if authority is None or authority.project_id != project_id:
        raise ValueError("La autoridad seleccionada no existe en este proyecto")
    if authority.lifecycle_status != "active":
        raise ValueError("La autoridad seleccionada no está activa")
    allowed = allowed_authority_types(semantic_family, subtype)
    if authority.entity_type not in allowed:
        raise ValueError(
            "La autoridad seleccionada no es compatible con la familia y el subtipo revisados"
        )
    return authority


def _ensure_no_exact_authority_duplicate(
    session: Session, *, project_id: str, preferred_name: str
) -> None:
    normalized = normalize_authority_text(preferred_name)
    existing = session.scalar(
        select(AuthorityRecord).where(
            AuthorityRecord.project_id == project_id,
            AuthorityRecord.normalized_name == normalized,
            AuthorityRecord.lifecycle_status == "active",
        )
    )
    if existing is not None:
        raise ValueError(
            "Ya existe una autoridad activa con el mismo nombre normalizado; "
            "vinculá el candidato con esa autoridad en lugar de crear otra"
        )


def _temporal_values(
    semantic_family: str,
    *,
    reviewed_text: str,
    temporal_expression: str | None,
) -> tuple[str | None, date | None, date | None, str | None, bool, str | None]:
    expression = _clean_optional(temporal_expression)
    if semantic_family == "time" and expression is None:
        expression = reviewed_text
    if expression is None:
        return None, None, None, None, False, None
    try:
        parsed = parse_temporal_expression(expression)
    except ValueError as exc:
        return expression, None, None, None, False, str(exc)
    return (
        parsed.expression,
        parsed.start,
        parsed.end,
        parsed.precision,
        parsed.approximate,
        None,
    )


def review_discovery_candidate(
    session: Session,
    *,
    project_id: str,
    candidate_id: str,
    decision_type: str,
    decided_by: str,
    reason: str | None = None,
    reviewed_text: str | None = None,
    semantic_family: str | None = None,
    reviewed_subtype: str | None = None,
    acceptance_mode: str | None = None,
    authority_id: str | None = None,
    new_authority_name: str | None = None,
    description: str | None = None,
    temporal_expression: str | None = None,
    confirm_new_authority: bool = False,
    source: str = "api",
) -> DiscoveryDecisionSummary:
    """Registra una decisión explícita y sus escrituras explícitas en una transacción.

    La fila de decisión es append-only. El candidato conserva el snapshot original y
    solo actualiza su estado operativo. Ninguna aceptación crea relaciones.
    """

    _ensure_project(session, project_id)
    candidate = session.get(DiscoveryCandidate, candidate_id)
    if candidate is None or candidate.project_id != project_id:
        raise ValueError("El candidato no existe en este proyecto")
    if candidate_is_stale(session, candidate):
        raise ValueError(
            "El candidato está obsoleto porque cambió el texto o su revisión; "
            "volvé a detectarlo antes de decidir"
        )

    actor = _clean_required(decided_by, field="La persona responsable", maximum=200)
    if decision_type not in DISCOVERY_DECISION_TYPES:
        raise ValueError(f"Decisión inválida: {decision_type}")
    if source not in {"ui", "cli", "api", "script"}:
        raise ValueError(f"Origen de decisión inválido: {source}")

    latest = _latest_decision(session, candidate.id)
    if latest is not None and latest.decision_type in {"accept", "reject"}:
        raise ValueError("El candidato ya tiene una decisión terminal")

    effective = effective_candidate_values(session, candidate)
    next_text = _clean_required(
        reviewed_text if reviewed_text is not None else effective.text,
        field="El texto revisado",
        maximum=1000,
    )
    next_family = semantic_family or effective.semantic_family
    next_subtype = _clean_required(
        reviewed_subtype if reviewed_subtype is not None else effective.subtype,
        field="El subtipo revisado",
        maximum=100,
    )
    if next_family not in DISCOVERY_FAMILIES:
        raise ValueError(f"Familia semántica inválida: {next_family}")

    clean_reason = _clean_optional(reason)
    clean_description = _clean_optional(description)
    if decision_type in {"modify", "defer"} and clean_reason is None:
        raise ValueError("La decisión requiere un fundamento")
    if decision_type == "modify":
        if (
            next_text == effective.text
            and next_family == effective.semantic_family
            and next_subtype == effective.subtype
        ):
            raise ValueError("La modificación debe cambiar texto, familia o subtipo")

    target_authority: AuthorityRecord | None = None
    created_mention: EntityMention | None = None
    context_record: DiscoveryContextRecord | None = None
    payload: dict[str, Any] = {
        "original_text": candidate.exact_text,
        "original_family": candidate.semantic_family,
        "original_subtype": candidate.suggested_subtype,
        "object_revision_number": candidate.object_revision_number,
        "start_offset": candidate.start_offset,
        "end_offset": candidate.end_offset,
    }

    decision_id = new_id()
    decision_number = _next_decision_number(session, candidate.id)
    if decision_type == "accept":
        allowed_modes = allowed_acceptance_modes(next_family)
        if acceptance_mode not in allowed_modes:
            raise ValueError(
                "Destino de aceptación inválido para la familia revisada: "
                + ", ".join(allowed_modes)
            )

        if acceptance_mode == "existing_authority":
            if not authority_id:
                raise ValueError("Seleccioná una autoridad existente")
            target_authority = _resolve_authority(
                session,
                project_id=project_id,
                authority_id=authority_id,
                semantic_family=next_family,
                subtype=next_subtype,
            )
        elif acceptance_mode == "new_authority":
            if not confirm_new_authority:
                raise ValueError(
                    "Confirmá explícitamente la creación de una autoridad sin revisar"
                )
            preferred_name = _clean_required(
                new_authority_name or next_text,
                field="El nombre preferido de la nueva autoridad",
                maximum=500,
            )
            _ensure_no_exact_authority_duplicate(
                session, project_id=project_id, preferred_name=preferred_name
            )
            target_authority = create_authority(
                session,
                project_id=project_id,
                entity_type=inferred_authority_type(next_family, next_subtype),
                preferred_name=preferred_name,
                description=clean_description,
                temporal_expression=(
                    _clean_optional(temporal_expression)
                    if next_family == "event"
                    else None
                ),
                review_status="unreviewed",
                created_by=actor,
                note=(
                    f"Creada explícitamente desde la referencia encontrada {candidate.id}."
                    + (f" Nota: {clean_reason}" if clean_reason else "")
                ),
            )

        if target_authority is not None:
            created_mention = create_mention(
                session,
                object_id=candidate.editable_object_id,
                mention_text=candidate.exact_text,
                start_offset=candidate.start_offset,
                end_offset=candidate.end_offset,
                authority_id=target_authority.id,
                status="accepted",
                source="automatic",
                confidence=candidate.confidence,
                created_by=actor,
                note=(
                    f"Aceptada desde descubrimiento abierto, candidato {candidate.id}."
                    + (f" Fundamento: {clean_reason}" if clean_reason else "")
                ),
            )

        if next_family in DISCOVERY_CONTEXT_FAMILIES:
            (
                parsed_expression,
                temporal_start,
                temporal_end,
                temporal_precision,
                temporal_approximate,
                parse_warning,
            ) = _temporal_values(
                next_family,
                reviewed_text=next_text,
                temporal_expression=temporal_expression,
            )
            data: dict[str, Any] = {
                "source_exact_text": candidate.exact_text,
                "source_family": candidate.semantic_family,
                "source_subtype": candidate.suggested_subtype,
                "review_reason": clean_reason,
            }
            if parse_warning:
                data["temporal_parse_warning"] = parse_warning
            context_record = DiscoveryContextRecord(
                id=new_id(),
                project_id=project_id,
                candidate_id=candidate.id,
                decision_id=decision_id,
                semantic_family=next_family,
                subtype=next_subtype,
                label=next_text,
                normalized_label=normalize_authority_text(next_text),
                description=clean_description,
                temporal_expression=parsed_expression,
                temporal_start=temporal_start,
                temporal_end=temporal_end,
                temporal_precision=temporal_precision,
                temporal_approximate=temporal_approximate,
                editable_object_id=candidate.editable_object_id,
                editable_page_id=candidate.editable_page_id,
                digital_object_id=candidate.digital_object_id,
                document_part_id=candidate.document_part_id,
                object_revision_number=candidate.object_revision_number,
                start_offset=candidate.start_offset,
                end_offset=candidate.end_offset,
                target_authority_id=(target_authority.id if target_authority else None),
                data_json=data,
                lifecycle_status="active",
                created_by=actor,
                created_at=utc_now(),
            )

    decision = DiscoveryDecision(
        id=decision_id,
        project_id=project_id,
        candidate_id=candidate.id,
        decision_number=decision_number,
        decision_type=decision_type,
        reviewed_text=next_text,
        semantic_family=next_family,
        reviewed_subtype=next_subtype,
        acceptance_mode=acceptance_mode if decision_type == "accept" else None,
        target_authority_id=(target_authority.id if target_authority else None),
        created_mention_id=(created_mention.id if created_mention else None),
        reason=clean_reason,
        source=source,
        candidate_state_sha256=_candidate_state_sha256(candidate),
        payload_json=payload,
        decided_by=actor,
        decided_at=utc_now(),
    )
    session.add(decision)
    session.flush()
    if context_record is not None:
        session.add(context_record)

    status_by_decision = {
        "accept": "accepted",
        "reject": "rejected",
        "modify": "modified",
        "defer": "deferred",
    }
    candidate.status = status_by_decision[decision_type]
    session.flush()

    return DiscoveryDecisionSummary(
        decision_id=decision.id,
        candidate_id=candidate.id,
        decision_number=decision.decision_number,
        decision_type=decision.decision_type,
        candidate_status=candidate.status,
        reviewed_text=decision.reviewed_text,
        semantic_family=decision.semantic_family,
        reviewed_subtype=decision.reviewed_subtype,
        acceptance_mode=decision.acceptance_mode,
        target_authority_id=decision.target_authority_id,
        created_mention_id=decision.created_mention_id,
        context_record_id=context_record.id if context_record else None,
    )



def accept_discovery_candidates_as_new_authorities(
    session: Session,
    *,
    project_id: str,
    candidate_ids: Iterable[str],
    decided_by: str,
    source: str = "api",
) -> tuple[DiscoveryDecisionSummary, ...]:
    """Acepta varias referencias y crea una entidad sin revisar por cada una, en una sola transacción."""

    selected_ids = tuple(dict.fromkeys(str(value) for value in candidate_ids if str(value)))
    if not selected_ids:
        raise ValueError("Seleccioná al menos una referencia")
    summaries: list[DiscoveryDecisionSummary] = []
    for candidate_id in selected_ids:
        candidate = session.get(DiscoveryCandidate, candidate_id)
        if candidate is None or candidate.project_id != project_id:
            raise ValueError("Una de las referencias seleccionadas no existe en este proyecto")
        effective = effective_candidate_values(session, candidate)
        if effective.semantic_family not in {"actor", "space", "event", "work"}:
            raise ValueError(
                f"La referencia «{effective.text}» no corresponde a una clase que pueda crear una entidad"
            )
        summaries.append(
            review_discovery_candidate(
                session,
                project_id=project_id,
                candidate_id=candidate_id,
                decision_type="accept",
                decided_by=decided_by,
                reviewed_text=effective.text,
                semantic_family=effective.semantic_family,
                reviewed_subtype=effective.subtype,
                acceptance_mode="new_authority",
                new_authority_name=effective.text,
                confirm_new_authority=True,
                reason="Creación conjunta confirmada desde la revisión de referencias encontradas.",
                source=source,
            )
        )
    return tuple(summaries)


def reject_discovery_candidates(
    session: Session,
    *,
    project_id: str,
    candidate_ids: Iterable[str],
    decided_by: str,
    reason: str | None = None,
    source: str = "api",
) -> tuple[DiscoveryDecisionSummary, ...]:
    """Descarta varias referencias de forma explícita y reversible desde el historial."""

    selected_ids = tuple(dict.fromkeys(str(value) for value in candidate_ids if str(value)))
    if not selected_ids:
        raise ValueError("Seleccioná al menos una referencia")
    return tuple(
        review_discovery_candidate(
            session,
            project_id=project_id,
            candidate_id=candidate_id,
            decision_type="reject",
            decided_by=decided_by,
            reason=reason,
            source=source,
        )
        for candidate_id in selected_ids
    )


def restore_rejected_discovery_candidate(
    session: Session,
    *,
    project_id: str,
    candidate_id: str,
    restored_by: str,
    source: str = "api",
) -> DiscoveryDecisionSummary:
    """Devuelve una referencia descartada a la cola de revisión sin borrar su historial."""

    _ensure_project(session, project_id)
    candidate = session.get(DiscoveryCandidate, candidate_id)
    if candidate is None or candidate.project_id != project_id:
        raise ValueError("La referencia no existe en este proyecto")
    latest = _latest_decision(session, candidate.id)
    if candidate.status != "rejected" or latest is None or latest.decision_type != "reject":
        raise ValueError("La referencia seleccionada no está descartada")
    actor = _clean_required(restored_by, field="La persona responsable", maximum=200)
    if source not in {"ui", "cli", "api", "script"}:
        raise ValueError(f"Origen de decisión inválido: {source}")
    effective = effective_candidate_values(session, candidate)
    decision = DiscoveryDecision(
        id=new_id(),
        project_id=project_id,
        candidate_id=candidate.id,
        decision_number=_next_decision_number(session, candidate.id),
        decision_type="restore",
        reviewed_text=effective.text,
        semantic_family=effective.semantic_family,
        reviewed_subtype=effective.subtype,
        acceptance_mode=None,
        target_authority_id=None,
        created_mention_id=None,
        reason="Restaurada para volver a revisarla.",
        source=source,
        candidate_state_sha256=_candidate_state_sha256(candidate),
        payload_json={"restored_rejection_decision_id": latest.id},
        decided_by=actor,
        decided_at=utc_now(),
    )
    session.add(decision)
    candidate.status = "pending"
    session.flush()
    return DiscoveryDecisionSummary(
        decision_id=decision.id,
        candidate_id=candidate.id,
        decision_number=decision.decision_number,
        decision_type=decision.decision_type,
        candidate_status=candidate.status,
        reviewed_text=decision.reviewed_text,
        semantic_family=decision.semantic_family,
        reviewed_subtype=decision.reviewed_subtype,
        acceptance_mode=None,
        target_authority_id=None,
        created_mention_id=None,
        context_record_id=None,
    )

def discovery_decision_rows(
    session: Session,
    *,
    project_id: str,
    candidate_id: str | None = None,
    limit: int = 1000,
) -> list[DiscoveryDecisionRow]:
    statement = select(DiscoveryDecision).where(
        DiscoveryDecision.project_id == project_id
    )
    if candidate_id is not None:
        statement = statement.where(DiscoveryDecision.candidate_id == candidate_id)
    rows = session.scalars(
        statement.order_by(
            DiscoveryDecision.decided_at.desc(),
            DiscoveryDecision.candidate_id,
            DiscoveryDecision.decision_number.desc(),
        ).limit(max(1, int(limit)))
    ).all()
    authority_ids = {row.target_authority_id for row in rows if row.target_authority_id}
    authorities = {
        row.id: row
        for row in session.scalars(
            select(AuthorityRecord).where(AuthorityRecord.id.in_(authority_ids))
        ).all()
    } if authority_ids else {}
    return [
        DiscoveryDecisionRow(
            decision_id=row.id,
            candidate_id=row.candidate_id,
            decision_number=row.decision_number,
            decision_type=row.decision_type,
            decision_label=decision_label(row.decision_type),
            reviewed_text=row.reviewed_text,
            semantic_family=row.semantic_family,
            family_label=family_label(row.semantic_family),
            reviewed_subtype=row.reviewed_subtype,
            acceptance_mode=row.acceptance_mode,
            acceptance_label=acceptance_mode_label(row.acceptance_mode),
            target_authority_id=row.target_authority_id,
            target_authority_name=(
                authorities[row.target_authority_id].preferred_name
                if row.target_authority_id in authorities
                else None
            ),
            created_mention_id=row.created_mention_id,
            reason=row.reason,
            source=row.source,
            candidate_state_sha256=row.candidate_state_sha256,
            payload=dict(row.payload_json or {}),
            decided_by=row.decided_by,
            decided_at=row.decided_at,
        )
        for row in rows
    ]


def discovery_context_record_rows(
    session: Session,
    *,
    project_id: str,
    candidate_ids: Iterable[str] = (),
) -> list[DiscoveryContextRecordRow]:
    statement = select(DiscoveryContextRecord).where(
        DiscoveryContextRecord.project_id == project_id
    )
    selected_ids = tuple(dict.fromkeys(candidate_ids))
    if selected_ids:
        statement = statement.where(DiscoveryContextRecord.candidate_id.in_(selected_ids))
    rows = session.scalars(
        statement.order_by(DiscoveryContextRecord.created_at, DiscoveryContextRecord.id)
    ).all()
    return [
        DiscoveryContextRecordRow(
            record_id=row.id,
            candidate_id=row.candidate_id,
            decision_id=row.decision_id,
            semantic_family=row.semantic_family,
            family_label=family_label(row.semantic_family),
            subtype=row.subtype,
            label=row.label,
            description=row.description,
            temporal_expression=row.temporal_expression,
            temporal_start=row.temporal_start,
            temporal_end=row.temporal_end,
            temporal_precision=row.temporal_precision,
            temporal_approximate=bool(row.temporal_approximate),
            target_authority_id=row.target_authority_id,
            data=dict(row.data_json or {}),
            created_by=row.created_by,
            created_at=row.created_at,
        )
        for row in rows
    ]
