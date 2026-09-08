from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
import json
import re
import unicodedata
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from archive_workbench.db.models import (
    DiscoveryCandidate,
    DiscoveryCandidateContinuity,
    DiscoveryCandidateGroup,
    DiscoveryDecision,
    DiscoveryGroupAction,
    DiscoveryGroupMembership,
    DiscoveryRun,
    EditableObject,
    EditablePage,
    utc_now,
)
from archive_workbench.discovery_providers import (
    LOCAL_PROVIDER_KEY,
    LOCAL_PROVIDER_VERSION,
    LOCAL_PROVIDER_VERSIONS,
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
    run_profile_name: str
    run_started_at: datetime
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
class DiscoveryGroupLocationRow:
    location_key: str
    representative_candidate_id: str
    candidate_ids: tuple[str, ...]
    run_ids: tuple[str, ...]
    effective_text: str
    original_filename: str
    page_number: int
    editable_object_id: str
    object_revision_number: int
    start_offset: int
    end_offset: int
    detection_count: int
    run_count: int


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
    current_location_count: int
    run_count: int
    stale_member_count: int
    current_locations: tuple[DiscoveryGroupLocationRow, ...]
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


def remove_candidates_from_group(
    session: Session,
    *,
    project_id: str,
    group_id: str,
    candidate_ids: Iterable[str],
    changed_by: str,
    reason: str,
    source: str = "api",
) -> int:
    actor = _clean_required(changed_by, field="La persona responsable", maximum=200)
    clean_reason = _clean_required(reason, field="El fundamento")
    ids = tuple(dict.fromkeys(candidate_ids))
    if not ids:
        raise ValueError("Seleccioná al menos una referencia del grupo")
    group = session.get(DiscoveryCandidateGroup, group_id)
    if group is None or group.project_id != project_id:
        raise ValueError("El grupo no existe en este proyecto")
    memberships = list(
        session.scalars(
            select(DiscoveryGroupMembership).where(
                DiscoveryGroupMembership.group_id == group_id,
                DiscoveryGroupMembership.candidate_id.in_(ids),
                DiscoveryGroupMembership.membership_status == "active",
            )
        )
    )
    if len(memberships) != len(ids):
        raise ValueError("Alguna referencia seleccionada ya no es miembro activo de este grupo")
    now = utc_now()
    for membership in memberships:
        membership.membership_status = "removed"
        membership.removed_by = actor
        membership.removed_at = now
        membership.removal_reason = clean_reason
        membership.source = "manual"
        _append_action(
            session,
            group=group,
            action_type="member_removed",
            actor=actor,
            source=source,
            candidate_id=membership.candidate_id,
            reason=clean_reason,
        )
    session.flush()
    return len(memberships)


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
    return (
        remove_candidates_from_group(
            session,
            project_id=project_id,
            group_id=group_id,
            candidate_ids=(candidate_id,),
            changed_by=changed_by,
            reason=reason,
            source=source,
        )
        == 1
    )


def _current_group_locations(
    members: Iterable[DiscoveryGroupMemberRow],
) -> tuple[DiscoveryGroupLocationRow, ...]:
    buckets: dict[tuple[str, int, int, int], list[DiscoveryGroupMemberRow]] = {}
    for member in members:
        if member.membership_status != "active" or member.is_stale:
            continue
        key = (
            member.editable_object_id,
            member.object_revision_number,
            member.start_offset,
            member.end_offset,
        )
        buckets.setdefault(key, []).append(member)

    result: list[DiscoveryGroupLocationRow] = []
    for key, rows in buckets.items():
        ordered = sorted(rows, key=lambda item: (item.run_started_at, item.candidate_id))
        representative = ordered[-1]
        run_ids = tuple(dict.fromkeys(item.run_id for item in ordered))
        result.append(
            DiscoveryGroupLocationRow(
                location_key="|".join(str(part) for part in key),
                representative_candidate_id=representative.candidate_id,
                candidate_ids=tuple(item.candidate_id for item in ordered),
                run_ids=run_ids,
                effective_text=representative.effective_text,
                original_filename=representative.original_filename,
                page_number=representative.page_number,
                editable_object_id=representative.editable_object_id,
                object_revision_number=representative.object_revision_number,
                start_offset=representative.start_offset,
                end_offset=representative.end_offset,
                detection_count=len(ordered),
                run_count=len(run_ids),
            )
        )
    result.sort(
        key=lambda item: (
            item.original_filename.casefold(),
            item.page_number,
            item.start_offset,
            item.end_offset,
            item.location_key,
        )
    )
    return tuple(result)


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
    if not groups:
        return []

    # Cargar todas las pertenencias del proyecto de una vez. La implementación
    # anterior consultaba pertenencias grupo por grupo y, además, resolvía la
    # última decisión y el objeto editable candidato por candidato. En proyectos
    # con varias corridas históricas eso convertía esta lectura derivada en un
    # N+1 de cientos o miles de SELECT. La historia sigue íntegra; sólo cambia
    # cómo se materializa la vista de lectura.
    membership_query = (
        select(DiscoveryGroupMembership, DiscoveryCandidate, DiscoveryRun)
        .join(
            DiscoveryCandidate,
            DiscoveryCandidate.id == DiscoveryGroupMembership.candidate_id,
        )
        .join(DiscoveryRun, DiscoveryRun.id == DiscoveryCandidate.run_id)
        .where(DiscoveryGroupMembership.project_id == project_id)
    )
    if not include_removed:
        membership_query = membership_query.where(
            DiscoveryGroupMembership.membership_status == "active"
        )
    membership_rows = list(
        session.execute(
            membership_query.order_by(
                DiscoveryGroupMembership.group_id,
                DiscoveryCandidate.created_at,
                DiscoveryCandidate.id,
            )
        ).all()
    )

    candidate_ids = tuple(
        dict.fromkeys(candidate.id for _membership, candidate, _run in membership_rows)
    )
    object_ids = tuple(
        dict.fromkeys(
            candidate.editable_object_id for _membership, candidate, _run in membership_rows
        )
    )

    # Mantener lotes acotados evita depender del límite de parámetros IN de la
    # versión de SQLite distribuida en cada plataforma soportada.
    latest_decisions: dict[str, DiscoveryDecision] = {}
    for offset in range(0, len(candidate_ids), 500):
        batch = candidate_ids[offset : offset + 500]
        decisions = session.scalars(
            select(DiscoveryDecision)
            .where(DiscoveryDecision.candidate_id.in_(batch))
            .order_by(
                DiscoveryDecision.candidate_id,
                DiscoveryDecision.decision_number.desc(),
            )
        ).all()
        for decision in decisions:
            latest_decisions.setdefault(decision.candidate_id, decision)

    editable_objects: dict[str, EditableObject] = {}
    for offset in range(0, len(object_ids), 500):
        batch = object_ids[offset : offset + 500]
        for editable_object in session.scalars(
            select(EditableObject).where(EditableObject.id.in_(batch))
        ).all():
            editable_objects[editable_object.id] = editable_object

    members_by_group: dict[str, list[DiscoveryGroupMemberRow]] = {group.id: [] for group in groups}
    for membership, candidate, run in membership_rows:
        latest = latest_decisions.get(candidate.id)
        current = editable_objects.get(candidate.editable_object_id)
        is_stale = current is None or current.revision_number != candidate.object_revision_number
        if current is not None and not is_stale:
            is_stale = (
                current.current_text[candidate.start_offset : candidate.end_offset]
                != candidate.exact_text
            )

        members_by_group.setdefault(membership.group_id, []).append(
            DiscoveryGroupMemberRow(
                membership_id=membership.id,
                candidate_id=candidate.id,
                exact_text=candidate.exact_text,
                effective_text=(latest.reviewed_text if latest else candidate.exact_text),
                run_id=candidate.run_id,
                run_profile_name=run.profile_name,
                run_started_at=run.started_at,
                original_filename=candidate.original_filename,
                page_number=candidate.page_number,
                editable_object_id=candidate.editable_object_id,
                object_revision_number=candidate.object_revision_number,
                start_offset=candidate.start_offset,
                end_offset=candidate.end_offset,
                membership_status=membership.membership_status,
                source=membership.source,
                is_stale=is_stale,
            )
        )

    result: list[DiscoveryGroupRow] = []
    for group in groups:
        members = members_by_group.get(group.id, [])
        current_locations = _current_group_locations(members)
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
                current_location_count=len(current_locations),
                run_count=len({m.run_id for m in members if m.membership_status == "active"}),
                stale_member_count=sum(
                    m.is_stale for m in members if m.membership_status == "active"
                ),
                current_locations=current_locations,
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
    text: str,
    *,
    family: str,
    source_text: str,
    provider_version: str,
) -> tuple[int, int, str]:
    normalized = normalize_group_text(source_text)
    matches = [
        item
        for item in detect_local_candidates(
            text,
            families=(family,),
            provider_version=provider_version,
        )
        if normalize_group_text(item.exact_text) == normalized
    ]
    if len(matches) != 1:
        if not matches:
            raise ValueError("El proveedor local no volvió a detectar el candidato")
        raise ValueError("El proveedor local detectó más de un anclaje posible")
    item = matches[0]
    return item.start, item.end, item.exact_text


def _continuity_local_provider_version(
    source: DiscoveryCandidate,
    source_run: DiscoveryRun,
) -> str:
    if (
        source.provider_key == LOCAL_PROVIDER_KEY
        and source.provider_version in LOCAL_PROVIDER_VERSIONS
    ):
        return source.provider_version
    snapshot = dict(source_run.profile_snapshot_json or {})
    if (
        snapshot.get("provider_key") == LOCAL_PROVIDER_KEY
        and snapshot.get("provider_version") in LOCAL_PROVIDER_VERSIONS
    ):
        return str(snapshot["provider_version"])
    return LOCAL_PROVIDER_VERSION


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
            DiscoveryCandidateContinuity.target_object_revision_number == current.revision_number,
        )
    )
    if existing is not None:
        raise ValueError("Este candidato ya fue proyectado a la revisión vigente")

    effective = effective_candidate_values(session, source)
    if method == "exact_projection":
        start, end = _unique_exact_position(current.current_text, source.exact_text)
        exact_text = current.current_text[start:end]
    else:
        local_provider_version = _continuity_local_provider_version(source, source_run)
        start, end, exact_text = _redetected_position(
            current.current_text,
            family=effective.semantic_family,
            source_text=source.exact_text,
            provider_version=local_provider_version,
        )

    parameters = {
        "method": method,
        "source_candidate_id": source.id,
        "source_revision": source.object_revision_number,
        "target_revision": current.revision_number,
        "source_text": source.exact_text,
        "family": effective.semantic_family,
        "subtype": effective.subtype,
        "source_local_provider_version": (
            _continuity_local_provider_version(source, source_run)
            if method == "local_redetection"
            else None
        ),
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


def discovery_continuity_rows(session: Session, *, project_id: str) -> list[ContinuityRow]:
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
