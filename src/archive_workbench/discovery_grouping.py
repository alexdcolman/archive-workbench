from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import re
import unicodedata
from typing import Iterable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from archive_workbench.db.models import (
    DiscoveryCandidate,
    DiscoveryCandidateContinuity,
    DiscoveryCandidateGroup,
    DiscoveryGroupAction,
    DiscoveryGroupMembership,
    DiscoveryRun,
    EditableObject,
    EditablePage,
    utc_now,
)
from archive_workbench.discovery_review import (
    candidate_is_stale,
    effective_candidate_values,
)
from archive_workbench.exchange import current_editable_state_sha256
from archive_workbench.identity import new_id
from archive_workbench.open_discovery import detect_local_candidates

GROUPING_METHODS = ("exact", "normalized", "manual")
CONTINUITY_METHODS = ("exact_projection", "local_redetection")


@dataclass(frozen=True, slots=True)
class GroupingSummary:
    groups_created: int
    memberships_created: int
    duplicate_candidates: int


@dataclass(frozen=True, slots=True)
class DiscoveryGroupMemberRow:
    membership_id: str
    candidate_id: str
    exact_text: str
    effective_text: str
    run_id: str
    original_filename: str
    page_number: int
    editable_object_id: str
    object_revision_number: int
    start_offset: int
    end_offset: int
    membership_status: str
    source: str
    is_stale: bool


@dataclass(frozen=True, slots=True)
class DiscoveryGroupRow:
    group_id: str
    preferred_label: str
    normalized_label: str
    semantic_family: str
    suggested_subtype: str | None
    grouping_method: str
    lifecycle_status: str
    active_member_count: int
    run_count: int
    stale_member_count: int
    members: tuple[DiscoveryGroupMemberRow, ...]


@dataclass(frozen=True, slots=True)
class ContinuitySummary:
    continuity_id: str
    source_candidate_id: str
    target_candidate_id: str
    run_id: str
    method: str
    target_revision: int
    target_start_offset: int
    target_end_offset: int


@dataclass(frozen=True, slots=True)
class ContinuityRow:
    continuity_id: str
    source_candidate_id: str
    target_candidate_id: str
    method: str
    source_revision: int
    target_revision: int
    source_offsets: tuple[int, int]
    target_offsets: tuple[int, int]
    evidence_sha256: str
    created_by: str
    created_at: object


def normalize_group_text(value: str) -> str:
    text = unicodedata.normalize("NFKC", value).casefold()
    text = re.sub(r"[^\w]+", " ", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip()


def _clean_required(value: str, *, field: str, maximum: int = 2000) -> str:
    clean = " ".join((value or "").split())
    if not clean:
        raise ValueError(f"{field} no puede quedar vacío")
    if len(clean) > maximum:
        raise ValueError(f"{field} no puede superar {maximum} caracteres")
    return clean


def _candidate(session: Session, project_id: str, candidate_id: str) -> DiscoveryCandidate:
    row = session.get(DiscoveryCandidate, candidate_id)
    if row is None or row.project_id != project_id:
        raise ValueError("El candidato no existe en este proyecto")
    return row


def _append_action(
    session: Session,
    *,
    group: DiscoveryCandidateGroup,
    action_type: str,
    actor: str,
    source: str,
    candidate_id: str | None = None,
    reason: str | None = None,
    payload: dict[str, object] | None = None,
) -> DiscoveryGroupAction:
    action = DiscoveryGroupAction(
        id=new_id(),
        project_id=group.project_id,
        group_id=group.id,
        candidate_id=candidate_id,
        action_type=action_type,
        reason=reason,
        source=source,
        payload_json=payload or {},
        created_by=actor,
        created_at=utc_now(),
    )
    session.add(action)
    return action


def _add_membership(
    session: Session,
    *,
    group: DiscoveryCandidateGroup,
    candidate: DiscoveryCandidate,
    actor: str,
    source: str,
    reason: str | None = None,
) -> bool:
    existing = session.scalar(
        select(DiscoveryGroupMembership).where(
            DiscoveryGroupMembership.group_id == group.id,
            DiscoveryGroupMembership.candidate_id == candidate.id,
        )
    )
    if existing is not None:
        if existing.membership_status == "active":
            return False
        # Una separación manual no se revierte por una reconstrucción automática.
        if source == "automatic" and existing.source == "manual":
            return False
        existing.membership_status = "active"
        existing.source = source
        existing.added_by = actor
        existing.added_at = utc_now()
        existing.removed_by = None
        existing.removed_at = None
        existing.removal_reason = None
        _append_action(
            session,
            group=group,
            action_type="member_restored",
            actor=actor,
            source=source,
            candidate_id=candidate.id,
            reason=reason,
        )
        return True
    membership = DiscoveryGroupMembership(
        id=new_id(),
        project_id=group.project_id,
        group_id=group.id,
        candidate_id=candidate.id,
        membership_status="active",
        source=source,
        added_by=actor,
        added_at=utc_now(),
        removed_by=None,
        removed_at=None,
        removal_reason=None,
    )
    session.add(membership)
    _append_action(
        session,
        group=group,
        action_type="member_added",
        actor=actor,
        source=source,
        candidate_id=candidate.id,
        reason=reason,
    )
    return True


def rebuild_discovery_groups(
    session: Session,
    *,
    project_id: str,
    created_by: str,
    source: str = "api",
) -> GroupingSummary:
    actor = _clean_required(created_by, field="La persona responsable", maximum=200)
    candidates = list(
        session.scalars(
            select(DiscoveryCandidate)
            .where(DiscoveryCandidate.project_id == project_id)
            .order_by(DiscoveryCandidate.created_at, DiscoveryCandidate.id)
        )
    )
    buckets: dict[tuple[str, str], list[tuple[DiscoveryCandidate, str, str]]] = {}
    for candidate in candidates:
        effective = effective_candidate_values(session, candidate)
        normalized = normalize_group_text(effective.text)
        if not normalized:
            continue
        buckets.setdefault((effective.semantic_family, normalized), []).append(
            (candidate, effective.text, effective.subtype)
        )

    groups_created = 0
    memberships_created = 0
    duplicate_candidates = 0
    for (family, normalized), rows in buckets.items():
        if len(rows) < 2:
            continue
        duplicate_candidates += len(rows)
        exact_forms = {" ".join(text.casefold().split()) for _, text, _ in rows}
        method = "exact" if len(exact_forms) == 1 else "normalized"
        group = session.scalar(
            select(DiscoveryCandidateGroup).where(
                DiscoveryCandidateGroup.project_id == project_id,
                DiscoveryCandidateGroup.semantic_family == family,
                DiscoveryCandidateGroup.normalized_label == normalized,
                DiscoveryCandidateGroup.grouping_method.in_(("exact", "normalized")),
                DiscoveryCandidateGroup.lifecycle_status == "active",
            )
        )
        if group is None:
            preferred = rows[0][1]
            subtypes = {subtype for _, _, subtype in rows}
            group = DiscoveryCandidateGroup(
                id=new_id(),
                project_id=project_id,
                preferred_label=preferred,
                normalized_label=normalized,
                semantic_family=family,
                suggested_subtype=(next(iter(subtypes)) if len(subtypes) == 1 else None),
                grouping_method=method,
                lifecycle_status="active",
                created_by=actor,
                created_at=utc_now(),
                updated_by=actor,
                updated_at=utc_now(),
            )
            session.add(group)
            session.flush()
            _append_action(
                session,
                group=group,
                action_type="group_created",
                actor=actor,
                source=source,
                payload={"method": method, "normalized_label": normalized},
            )
            groups_created += 1
        for candidate, _text, _subtype in rows:
            if _add_membership(
                session,
                group=group,
                candidate=candidate,
                actor=actor,
                source="automatic",
            ):
                memberships_created += 1
    session.flush()
    return GroupingSummary(
        groups_created=groups_created,
        memberships_created=memberships_created,
        duplicate_candidates=duplicate_candidates,
    )


def create_manual_group(
    session: Session,
    *,
    project_id: str,
    candidate_ids: Iterable[str],
    preferred_label: str,
    semantic_family: str,
    created_by: str,
    reason: str,
    source: str = "api",
) -> DiscoveryCandidateGroup:
    actor = _clean_required(created_by, field="La persona responsable", maximum=200)
    clean_reason = _clean_required(reason, field="El fundamento")
    label = _clean_required(preferred_label, field="La etiqueta del grupo", maximum=1000)
    ids = tuple(dict.fromkeys(candidate_ids))
    if len(ids) < 2:
        raise ValueError("Un grupo manual requiere al menos dos candidatos")
    candidates = [_candidate(session, project_id, candidate_id) for candidate_id in ids]
    group = DiscoveryCandidateGroup(
        id=new_id(),
        project_id=project_id,
        preferred_label=label,
        normalized_label=normalize_group_text(label),
        semantic_family=semantic_family,
        suggested_subtype=None,
        grouping_method="manual",
        lifecycle_status="active",
        created_by=actor,
        created_at=utc_now(),
        updated_by=actor,
        updated_at=utc_now(),
    )
    session.add(group)
    session.flush()
    _append_action(
        session,
        group=group,
        action_type="group_created",
        actor=actor,
        source=source,
        reason=clean_reason,
        payload={"method": "manual"},
    )
    for candidate in candidates:
        _add_membership(
            session,
            group=group,
            candidate=candidate,
            actor=actor,
            source="manual",
            reason=clean_reason,
        )
    session.flush()
    return group


def add_candidate_to_group(
    session: Session,
    *,
    project_id: str,
    group_id: str,
    candidate_id: str,
    changed_by: str,
    reason: str,
    source: str = "api",
) -> bool:
    actor = _clean_required(changed_by, field="La persona responsable", maximum=200)
    clean_reason = _clean_required(reason, field="El fundamento")
    group = session.get(DiscoveryCandidateGroup, group_id)
    if group is None or group.project_id != project_id:
        raise ValueError("El grupo no existe en este proyecto")
    candidate = _candidate(session, project_id, candidate_id)
    return _add_membership(
        session,
        group=group,
        candidate=candidate,
        actor=actor,
        source="manual",
        reason=clean_reason,
    )


def remove_candidate_from_group(
    session: Session,
    *,
    project_id: str,
    group_id: str,
    candidate_id: str,
    changed_by: str,
    reason: str,
    source: str = "api",
) -> bool:
    actor = _clean_required(changed_by, field="La persona responsable", maximum=200)
    clean_reason = _clean_required(reason, field="El fundamento")
    group = session.get(DiscoveryCandidateGroup, group_id)
    if group is None or group.project_id != project_id:
        raise ValueError("El grupo no existe en este proyecto")
    membership = session.scalar(
        select(DiscoveryGroupMembership).where(
            DiscoveryGroupMembership.group_id == group_id,
            DiscoveryGroupMembership.candidate_id == candidate_id,
        )
    )
    if membership is None or membership.membership_status != "active":
        raise ValueError("El candidato no es miembro activo de este grupo")
    membership.membership_status = "removed"
    membership.removed_by = actor
    membership.removed_at = utc_now()
    membership.removal_reason = clean_reason
    membership.source = "manual"
    _append_action(
        session,
        group=group,
        action_type="member_removed",
        actor=actor,
        source=source,
        candidate_id=candidate_id,
        reason=clean_reason,
    )
    session.flush()
    return True


def discovery_group_rows(
    session: Session, *, project_id: str, include_removed: bool = False
) -> list[DiscoveryGroupRow]:
    groups = list(
        session.scalars(
            select(DiscoveryCandidateGroup)
            .where(DiscoveryCandidateGroup.project_id == project_id)
            .order_by(
                DiscoveryCandidateGroup.semantic_family,
                DiscoveryCandidateGroup.normalized_label,
                DiscoveryCandidateGroup.created_at,
            )
        )
    )
    result: list[DiscoveryGroupRow] = []
    for group in groups:
        query = (
            select(DiscoveryGroupMembership, DiscoveryCandidate)
            .join(
                DiscoveryCandidate,
                DiscoveryCandidate.id == DiscoveryGroupMembership.candidate_id,
            )
            .where(DiscoveryGroupMembership.group_id == group.id)
        )
        if not include_removed:
            query = query.where(DiscoveryGroupMembership.membership_status == "active")
        rows = list(session.execute(query.order_by(DiscoveryCandidate.created_at)).all())
        members: list[DiscoveryGroupMemberRow] = []
        for membership, candidate in rows:
            effective = effective_candidate_values(session, candidate)
            members.append(
                DiscoveryGroupMemberRow(
                    membership_id=membership.id,
                    candidate_id=candidate.id,
                    exact_text=candidate.exact_text,
                    effective_text=effective.text,
                    run_id=candidate.run_id,
                    original_filename=candidate.original_filename,
                    page_number=candidate.page_number,
                    editable_object_id=candidate.editable_object_id,
                    object_revision_number=candidate.object_revision_number,
                    start_offset=candidate.start_offset,
                    end_offset=candidate.end_offset,
                    membership_status=membership.membership_status,
                    source=membership.source,
                    is_stale=candidate_is_stale(session, candidate),
                )
            )
        result.append(
            DiscoveryGroupRow(
                group_id=group.id,
                preferred_label=group.preferred_label,
                normalized_label=group.normalized_label,
                semantic_family=group.semantic_family,
                suggested_subtype=group.suggested_subtype,
                grouping_method=group.grouping_method,
                lifecycle_status=group.lifecycle_status,
                active_member_count=sum(m.membership_status == "active" for m in members),
                run_count=len({m.run_id for m in members if m.membership_status == "active"}),
                stale_member_count=sum(m.is_stale for m in members if m.membership_status == "active"),
                members=tuple(members),
            )
        )
    return result


def _unique_exact_position(text: str, needle: str) -> tuple[int, int]:
    starts = [match.start() for match in re.finditer(re.escape(needle), text)]
    if len(starts) != 1:
        if not starts:
            raise ValueError("El texto exacto ya no aparece en la revisión vigente")
        raise ValueError("El texto exacto aparece varias veces; la proyección es ambigua")
    start = starts[0]
    return start, start + len(needle)


def _redetected_position(
    text: str, *, family: str, source_text: str
) -> tuple[int, int, str]:
    normalized = normalize_group_text(source_text)
    matches = [
        item
        for item in detect_local_candidates(text, families=(family,))
        if normalize_group_text(item.exact_text) == normalized
    ]
    if len(matches) != 1:
        if not matches:
            raise ValueError("El proveedor local no volvió a detectar el candidato")
        raise ValueError("El proveedor local detectó más de un anclaje posible")
    item = matches[0]
    return item.start, item.end, item.exact_text


def project_discovery_candidate(
    session: Session,
    *,
    project_id: str,
    candidate_id: str,
    method: str,
    created_by: str,
) -> ContinuitySummary:
    actor = _clean_required(created_by, field="La persona responsable", maximum=200)
    if method not in CONTINUITY_METHODS:
        raise ValueError("Método de continuidad inválido")
    source = _candidate(session, project_id, candidate_id)
    if not candidate_is_stale(session, source):
        raise ValueError("El candidato todavía coincide con la revisión vigente")
    current = session.get(EditableObject, source.editable_object_id)
    page = session.get(EditablePage, source.editable_page_id)
    source_run = session.get(DiscoveryRun, source.run_id)
    if current is None or page is None or source_run is None:
        raise ValueError("No se pudo reconstruir la procedencia del candidato")
    existing = session.scalar(
        select(DiscoveryCandidateContinuity).where(
            DiscoveryCandidateContinuity.source_candidate_id == source.id,
            DiscoveryCandidateContinuity.target_object_revision_number
            == current.revision_number,
        )
    )
    if existing is not None:
        raise ValueError("Este candidato ya fue proyectado a la revisión vigente")

    effective = effective_candidate_values(session, source)
    if method == "exact_projection":
        start, end = _unique_exact_position(current.current_text, source.exact_text)
        exact_text = current.current_text[start:end]
    else:
        start, end, exact_text = _redetected_position(
            current.current_text,
            family=effective.semantic_family,
            source_text=source.exact_text,
        )

    parameters = {
        "method": method,
        "source_candidate_id": source.id,
        "source_revision": source.object_revision_number,
        "target_revision": current.revision_number,
        "source_text": source.exact_text,
        "family": effective.semantic_family,
        "subtype": effective.subtype,
    }
    parameters_sha256 = sha256(
        json.dumps(parameters, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()
    run = DiscoveryRun(
        id=new_id(),
        project_id=project_id,
        profile_id=source.profile_id,
        authorization_id=source_run.authorization_id,
        profile_name=f"Continuidad de {source_run.profile_name}",
        profile_snapshot_json={
            **dict(source_run.profile_snapshot_json or {}),
            "continuity_source_candidate_id": source.id,
            "continuity_method": method,
        },
        provider_key="continuity",
        provider_version="continuity_v1",
        method=method,
        parameters_sha256=parameters_sha256,
        corpus_state_sha256=current_editable_state_sha256(session, project_id),
        page_review_statuses_json=list(source_run.page_review_statuses_json or ()),
        status="completed",
        object_count=1,
        candidate_count=1,
        family_counts_json={effective.semantic_family: 1},
        created_by=actor,
        started_at=utc_now(),
        finished_at=utc_now(),
        error_message=None,
    )
    session.add(run)
    session.flush()
    target = DiscoveryCandidate(
        id=new_id(),
        project_id=project_id,
        run_id=run.id,
        profile_id=source.profile_id,
        editable_object_id=source.editable_object_id,
        editable_page_id=source.editable_page_id,
        digital_object_id=source.digital_object_id,
        document_part_id=current.document_part_id,
        source_key=source.source_key,
        original_filename=source.original_filename,
        page_number=source.page_number,
        object_revision_number=current.revision_number,
        page_revision_number=page.revision_number,
        start_offset=start,
        end_offset=end,
        exact_text=exact_text,
        context_before=current.current_text[max(0, start - 90) : start],
        context_after=current.current_text[end : min(len(current.current_text), end + 90)],
        semantic_family=effective.semantic_family,
        suggested_subtype=effective.subtype,
        confidence=source.confidence,
        method=method,
        provider_key="continuity",
        provider_version="continuity_v1",
        model_name=None,
        model_version=None,
        explanation=(
            "Proyección exacta única sobre la revisión textual vigente."
            if method == "exact_projection"
            else "Nueva detección local única sobre la revisión textual vigente."
        ),
        parameters_sha256=parameters_sha256,
        status="pending",
        created_at=utc_now(),
    )
    session.add(target)
    session.flush()
    evidence = {
        **parameters,
        "target_candidate_id": target.id,
        "target_offsets": [start, end],
        "target_exact_text": exact_text,
    }
    continuity = DiscoveryCandidateContinuity(
        id=new_id(),
        project_id=project_id,
        source_candidate_id=source.id,
        target_candidate_id=target.id,
        method=method,
        source_object_revision_number=source.object_revision_number,
        target_object_revision_number=current.revision_number,
        source_start_offset=source.start_offset,
        source_end_offset=source.end_offset,
        target_start_offset=start,
        target_end_offset=end,
        evidence_sha256=sha256(
            json.dumps(evidence, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
                "utf-8"
            )
        ).hexdigest(),
        created_by=actor,
        created_at=utc_now(),
    )
    session.add(continuity)
    # La nueva procedencia acompaña al candidato fuente en sus grupos activos.
    memberships = list(
        session.scalars(
            select(DiscoveryGroupMembership).where(
                DiscoveryGroupMembership.candidate_id == source.id,
                DiscoveryGroupMembership.membership_status == "active",
            )
        )
    )
    for membership in memberships:
        group = session.get(DiscoveryCandidateGroup, membership.group_id)
        if group is not None:
            _add_membership(
                session,
                group=group,
                candidate=target,
                actor=actor,
                source="continuity",
                reason=f"Continuidad desde {source.id}",
            )
    session.flush()
    return ContinuitySummary(
        continuity_id=continuity.id,
        source_candidate_id=source.id,
        target_candidate_id=target.id,
        run_id=run.id,
        method=method,
        target_revision=current.revision_number,
        target_start_offset=start,
        target_end_offset=end,
    )


def discovery_continuity_rows(
    session: Session, *, project_id: str
) -> list[ContinuityRow]:
    rows = list(
        session.scalars(
            select(DiscoveryCandidateContinuity)
            .where(DiscoveryCandidateContinuity.project_id == project_id)
            .order_by(DiscoveryCandidateContinuity.created_at, DiscoveryCandidateContinuity.id)
        )
    )
    return [
        ContinuityRow(
            continuity_id=row.id,
            source_candidate_id=row.source_candidate_id,
            target_candidate_id=row.target_candidate_id,
            method=row.method,
            source_revision=row.source_object_revision_number,
            target_revision=row.target_object_revision_number,
            source_offsets=(row.source_start_offset, row.source_end_offset),
            target_offsets=(row.target_start_offset, row.target_end_offset),
            evidence_sha256=row.evidence_sha256,
            created_by=row.created_by,
            created_at=row.created_at,
        )
        for row in rows
    ]
