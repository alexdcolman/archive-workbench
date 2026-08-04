from __future__ import annotations

from dataclasses import dataclass
import difflib
from datetime import date, datetime
import hashlib
import re
import unicodedata
from typing import Iterable, Mapping, Sequence

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from archive_workbench.analysis_audit import record_automatic_analysis_authorization
from archive_workbench.analysis_quality import (
    DEFAULT_AUTOMATIC_PAGE_REVIEW_STATUSES,
    PAGE_REVIEW_STATUSES,
    validate_automatic_quality_scope,
)
from archive_workbench.db.models import (
    AuthorityAlias,
    AuthorityRecord,
    AuthorityRevision,
    DigitalObject,
    EditableObject,
    EditableObjectRevision,
    EditablePage,
    EntityMention,
    EntityMentionRevision,
    Project,
    SourceRegistration,
    ArchivalUnit,
    utc_now,
)
from archive_workbench.identity import new_id
from archive_workbench.sources import PROCESSABLE_SOURCE_TYPES
from archive_workbench.temporal import parse_temporal_expression

AUTHORITY_TYPES = ("person", "organization", "place", "event", "work", "other")
AUTHORITY_REVIEW_STATUSES = ("unreviewed", "reviewed", "approved")
AUTHORITY_LIFECYCLE_STATUSES = ("active", "inactive")
ALIAS_TYPES = ("variant", "abbreviation", "acronym", "former_name", "title", "other")
MENTION_STATUSES = ("pending", "accepted", "rejected", "modified")
LINKED_MENTION_STATUSES = ("accepted", "modified")
MENTION_SOURCES = ("manual", "dictionary", "automatic")
_UNSET = object()


def _validated_page_review_statuses(
    values: Iterable[str],
    *,
    broader_scope_confirmed: bool = False,
    quality_scope_reason: str | None = None,
) -> tuple[str, ...]:
    return validate_automatic_quality_scope(
        values,
        broader_scope_confirmed=broader_scope_confirmed,
        confirmation_reason=quality_scope_reason,
    ).page_review_statuses


def record_mention_suggestion_authorization(
    session: Session,
    *,
    project_id: str,
    page_review_statuses: Iterable[str],
    broader_quality_scope_confirmed: bool = False,
    quality_scope_reason: str | None = None,
    actor: str,
    source: str,
    target_type: str | None = None,
    target_id: str | None = None,
    parameters: Mapping[str, object] | None = None,
) -> tuple[str, ...]:
    selected = _validated_page_review_statuses(
        page_review_statuses,
        broader_scope_confirmed=broader_quality_scope_confirmed,
        quality_scope_reason=quality_scope_reason,
    )
    record_automatic_analysis_authorization(
        session,
        project_id=project_id,
        analysis_kind="mention_suggestions",
        page_review_statuses=selected,
        broader_scope_confirmed=broader_quality_scope_confirmed,
        confirmed_by=actor,
        confirmation_reason=quality_scope_reason,
        source=source,
        target_type=target_type,
        target_id=target_id,
        parameters=parameters,
    )
    return selected


@dataclass(slots=True)
class AliasRow:
    alias_id: str
    alias: str
    normalized_alias: str
    alias_type: str
    note: str | None
    created_by: str
    created_at: datetime


@dataclass(slots=True)
class AuthorityRow:
    authority_id: str
    entity_type: str
    preferred_name: str
    normalized_name: str
    description: str | None
    temporal_expression: str | None
    temporal_start: date | None
    temporal_end: date | None
    temporal_precision: str | None
    temporal_approximate: bool
    temporal_note: str | None
    lifecycle_status: str
    review_status: str
    revision: int
    alias_count: int
    mention_count: int
    aliases: list[AliasRow]
    created_by: str
    created_at: datetime
    updated_by: str
    updated_at: datetime


@dataclass(slots=True)
class MentionRow:
    mention_id: str
    object_id: str
    authority_id: str | None
    authority_name: str | None
    authority_type: str | None
    mention_text: str
    start_offset: int | None
    end_offset: int | None
    object_revision_number: int
    current_object_revision: int
    status: str
    source: str
    confidence: float | None
    note: str | None
    revision: int
    source_key: str | None
    document_title: str | None
    page_number: int
    order_index: int
    created_by: str
    created_at: datetime
    updated_by: str
    updated_at: datetime

    @property
    def is_stale(self) -> bool:
        return self.object_revision_number != self.current_object_revision


@dataclass(slots=True)
class MentionRepairCase:
    code: str
    severity: str
    mention_id: str
    mention_revision: int
    object_id: str
    authority_id: str | None
    authority_name: str | None
    mention_text: str
    status: str
    stored_object_revision: int
    current_object_revision: int
    stored_start_offset: int | None
    stored_end_offset: int | None
    projected_start_offset: int | None
    projected_end_offset: int | None
    projected_text: str | None
    duplicate_mention_ids: tuple[str, ...]
    source_key: str | None
    document_title: str | None
    page_number: int
    order_index: int
    explanation: str
    snapshot_revision_number: int | None = None
    snapshot_operation: str | None = None
    snapshot_current: dict[str, object] | None = None
    snapshot_recorded: dict[str, object] | None = None
    snapshot_difference_fields: tuple[str, ...] = ()
    group_block_reason: str | None = None

    @property
    def can_relocate(self) -> bool:
        return self.code == "safe_relocation"

    @property
    def can_resolve_missing_authority(self) -> bool:
        return self.code == "missing_authority"

    @property
    def can_resolve_duplicate(self) -> bool:
        return (
            self.code == "duplicate_relocation"
            and len(self.duplicate_mention_ids) == 1
        )

    @property
    def can_resolve_duplicate_group(self) -> bool:
        return (
            self.code == "duplicate_group"
            and len(self.duplicate_mention_ids) >= 2
            and self.group_block_reason is None
        )

    @property
    def can_resolve_unresolved(self) -> bool:
        return self.code == "unresolved_relocation"

    @property
    def can_resolve_snapshot_divergence(self) -> bool:
        return (
            self.code == "snapshot_divergence"
            and self.snapshot_revision_number is not None
            and self.snapshot_current is not None
            and self.snapshot_recorded is not None
            and bool(self.snapshot_difference_fields)
        )


@dataclass(slots=True)
class SuggestionSummary:
    created: int
    already_present: int
    ambiguous: int
    candidates_scanned: int


@dataclass(slots=True)
class CorpusSuggestionSummary:
    objects_scanned: int
    created: int
    already_present: int
    ambiguous: int
    candidates_scanned: int


@dataclass(slots=True)
class MentionCandidateRow:
    candidate_key: str
    authority_id: str
    authority_name: str
    object_id: str
    object_revision_number: int
    mention_text: str
    matched_surface: str
    match_kind: str
    alias_type: str | None
    start_offset: int
    end_offset: int
    context_before: str
    context_after: str
    source_key: str | None
    document_title: str | None
    page_number: int
    order_index: int
    existing_mention_id: str | None
    existing_authority_id: str | None
    existing_authority_name: str | None
    existing_status: str | None

    @property
    def already_included(self) -> bool:
        return (
            self.existing_mention_id is not None
            and self.existing_authority_id == self.authority_id
        )

    @property
    def can_link_existing(self) -> bool:
        return self.existing_mention_id is not None and self.existing_authority_id is None

    @property
    def has_authority_conflict(self) -> bool:
        return (
            self.existing_mention_id is not None
            and self.existing_authority_id not in (None, self.authority_id)
        )


@dataclass(slots=True)
class MentionCandidateImportSummary:
    requested: int
    created: int
    linked_existing: int
    already_present: int


def normalize_authority_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def _project_id_for_object(session: Session, object_id: str) -> str:
    project_id = session.scalar(
        select(DigitalObject.project_id)
        .join(EditableObject, EditableObject.digital_object_id == DigitalObject.id)
        .where(EditableObject.id == object_id)
    )
    if project_id is None:
        raise ValueError(f"Objeto editable inexistente: {object_id}")
    return str(project_id)


def _aliases(session: Session, authority_id: str) -> list[AuthorityAlias]:
    return session.scalars(
        select(AuthorityAlias)
        .where(AuthorityAlias.authority_id == authority_id)
        .order_by(AuthorityAlias.normalized_alias, AuthorityAlias.id)
    ).all()


def _authority_snapshot(session: Session, authority: AuthorityRecord) -> dict[str, object]:
    aliases = _aliases(session, authority.id)
    return {
        "project_id": authority.project_id,
        "entity_type": authority.entity_type,
        "preferred_name": authority.preferred_name,
        "normalized_name": authority.normalized_name,
        "description": authority.description,
        "temporal_expression": authority.temporal_expression,
        "temporal_start": authority.temporal_start.isoformat() if authority.temporal_start else None,
        "temporal_end": authority.temporal_end.isoformat() if authority.temporal_end else None,
        "temporal_precision": authority.temporal_precision,
        "temporal_approximate": authority.temporal_approximate,
        "temporal_note": authority.temporal_note,
        "lifecycle_status": authority.lifecycle_status,
        "review_status": authority.review_status,
        "aliases": [
            {
                "id": row.id,
                "alias": row.alias,
                "normalized_alias": row.normalized_alias,
                "alias_type": row.alias_type,
                "note": row.note,
                "created_by": row.created_by,
                "created_at": row.created_at.isoformat(),
            }
            for row in aliases
        ],
    }


def _append_authority_revision(
    session: Session,
    authority: AuthorityRecord,
    *,
    operation: str,
    changed_by: str,
    note: str | None = None,
) -> AuthorityRevision:
    revision = AuthorityRevision(
        id=new_id(),
        authority_id=authority.id,
        revision_number=authority.revision,
        operation=operation,
        snapshot_json=_authority_snapshot(session, authority),
        note=note.strip() if note and note.strip() else None,
        changed_by=changed_by,
        changed_at=utc_now(),
    )
    session.add(revision)
    session.flush()
    return revision


def _mention_snapshot(mention: EntityMention) -> dict[str, object]:
    return {
        "editable_object_id": mention.editable_object_id,
        "authority_id": mention.authority_id,
        "mention_text": mention.mention_text,
        "normalized_text": mention.normalized_text,
        "start_offset": mention.start_offset,
        "end_offset": mention.end_offset,
        "object_revision_number": mention.object_revision_number,
        "status": mention.status,
        "source": mention.source,
        "confidence": mention.confidence,
        "note": mention.note,
    }


def _append_mention_revision(
    session: Session,
    mention: EntityMention,
    *,
    operation: str,
    changed_by: str,
    note: str | None = None,
) -> EntityMentionRevision:
    revision = EntityMentionRevision(
        id=new_id(),
        mention_id=mention.id,
        revision_number=mention.revision,
        operation=operation,
        snapshot_json=_mention_snapshot(mention),
        note=note.strip() if note and note.strip() else None,
        changed_by=changed_by,
        changed_at=utc_now(),
    )
    session.add(revision)
    session.flush()
    return revision


def create_authority(
    session: Session,
    *,
    project_id: str,
    entity_type: str,
    preferred_name: str,
    created_by: str,
    description: str | None = None,
    temporal_expression: str | None = None,
    temporal_note: str | None = None,
    review_status: str = "unreviewed",
    note: str | None = None,
) -> AuthorityRecord:
    clean = preferred_name.strip()
    if not clean:
        raise ValueError("El nombre preferido no puede estar vacío")
    if entity_type not in AUTHORITY_TYPES:
        raise ValueError(f"Tipo de entidad inválido: {entity_type}")
    if review_status not in AUTHORITY_REVIEW_STATUSES:
        raise ValueError(f"Estado de revisión inválido: {review_status}")
    if session.get(Project, project_id) is None:
        raise ValueError(f"Proyecto inexistente: {project_id}")
    temporal = parse_temporal_expression(temporal_expression)
    authority = AuthorityRecord(
        id=new_id(),
        project_id=project_id,
        entity_type=entity_type,
        preferred_name=clean,
        normalized_name=normalize_authority_text(clean),
        description=description.strip() if description and description.strip() else None,
        temporal_expression=temporal.expression,
        temporal_start=temporal.start,
        temporal_end=temporal.end,
        temporal_precision=temporal.precision,
        temporal_approximate=temporal.approximate,
        temporal_note=temporal_note.strip() if temporal_note and temporal_note.strip() else None,
        lifecycle_status="active",
        review_status=review_status,
        created_by=created_by,
        created_at=utc_now(),
        updated_by=created_by,
        updated_at=utc_now(),
        revision=1,
    )
    session.add(authority)
    session.flush()
    _append_authority_revision(
        session, authority, operation="create", changed_by=created_by, note=note
    )
    return authority


def update_authority(
    session: Session,
    *,
    authority_id: str,
    expected_revision: int,
    changed_by: str,
    entity_type: str | None = None,
    preferred_name: str | None = None,
    description: str | None = None,
    temporal_expression: str | None = None,
    temporal_note: str | None = None,
    review_status: str | None = None,
    lifecycle_status: str | None = None,
    note: str | None = None,
) -> AuthorityRecord:
    authority = session.get(AuthorityRecord, authority_id)
    if authority is None:
        raise ValueError(f"Autoridad inexistente: {authority_id}")
    if authority.revision != expected_revision:
        raise ValueError(
            f"La autoridad está en revisión {authority.revision}; se esperaba {expected_revision}"
        )
    if entity_type is not None:
        if entity_type not in AUTHORITY_TYPES:
            raise ValueError(f"Tipo de entidad inválido: {entity_type}")
        authority.entity_type = entity_type
    if preferred_name is not None:
        clean = preferred_name.strip()
        if not clean:
            raise ValueError("El nombre preferido no puede estar vacío")
        authority.preferred_name = clean
        authority.normalized_name = normalize_authority_text(clean)
    if description is not None:
        authority.description = description.strip() or None
    if temporal_expression is not None:
        temporal = parse_temporal_expression(temporal_expression)
        authority.temporal_expression = temporal.expression
        authority.temporal_start = temporal.start
        authority.temporal_end = temporal.end
        authority.temporal_precision = temporal.precision
        authority.temporal_approximate = temporal.approximate
    if temporal_note is not None:
        authority.temporal_note = temporal_note.strip() or None
    if review_status is not None:
        if review_status not in AUTHORITY_REVIEW_STATUSES:
            raise ValueError(f"Estado de revisión inválido: {review_status}")
        authority.review_status = review_status
    if lifecycle_status is not None:
        if lifecycle_status not in AUTHORITY_LIFECYCLE_STATUSES:
            raise ValueError(f"Estado de ciclo de vida inválido: {lifecycle_status}")
        authority.lifecycle_status = lifecycle_status
    authority.revision += 1
    authority.updated_by = changed_by
    authority.updated_at = utc_now()
    session.flush()
    _append_authority_revision(
        session, authority, operation="update", changed_by=changed_by, note=note
    )
    return authority


def add_authority_alias(
    session: Session,
    *,
    authority_id: str,
    alias: str,
    alias_type: str,
    created_by: str,
    note: str | None = None,
) -> AuthorityAlias:
    authority = session.get(AuthorityRecord, authority_id)
    if authority is None:
        raise ValueError(f"Autoridad inexistente: {authority_id}")
    clean = alias.strip()
    if not clean:
        raise ValueError("El alias no puede estar vacío")
    if alias_type not in ALIAS_TYPES:
        raise ValueError(f"Tipo de alias inválido: {alias_type}")
    normalized = normalize_authority_text(clean)
    existing = session.scalar(
        select(AuthorityAlias).where(
            AuthorityAlias.authority_id == authority_id,
            AuthorityAlias.normalized_alias == normalized,
        )
    )
    if existing is not None:
        raise ValueError(f"El alias ya existe para esta autoridad: {clean}")
    row = AuthorityAlias(
        id=new_id(),
        authority_id=authority_id,
        alias=clean,
        normalized_alias=normalized,
        alias_type=alias_type,
        note=note.strip() if note and note.strip() else None,
        created_by=created_by,
        created_at=utc_now(),
    )
    session.add(row)
    authority.revision += 1
    authority.updated_by = created_by
    authority.updated_at = utc_now()
    session.flush()
    _append_authority_revision(
        session,
        authority,
        operation="alias_add",
        changed_by=created_by,
        note=note,
    )
    return row


def remove_authority_alias(
    session: Session,
    *,
    alias_id: str,
    removed_by: str,
    note: str | None = None,
) -> AuthorityRecord:
    alias = session.get(AuthorityAlias, alias_id)
    if alias is None:
        raise ValueError(f"Alias inexistente: {alias_id}")
    authority = session.get(AuthorityRecord, alias.authority_id)
    assert authority is not None
    session.delete(alias)
    session.flush()
    authority.revision += 1
    authority.updated_by = removed_by
    authority.updated_at = utc_now()
    session.flush()
    _append_authority_revision(
        session,
        authority,
        operation="alias_remove",
        changed_by=removed_by,
        note=note or f"Alias retirado: {alias.alias}",
    )
    return authority


def authority_rows(
    session: Session,
    *,
    project_id: str,
    query: str = "",
    entity_types: Iterable[str] = (),
    lifecycle_statuses: Iterable[str] = ("active",),
    temporal_start: date | None = None,
    temporal_end: date | None = None,
    include_undated: bool = False,
) -> list[AuthorityRow]:
    statement = select(AuthorityRecord).where(AuthorityRecord.project_id == project_id)
    selected_types = tuple(dict.fromkeys(entity_types))
    if selected_types:
        invalid = sorted(set(selected_types) - set(AUTHORITY_TYPES))
        if invalid:
            raise ValueError("Tipos de autoridad inválidos: " + ", ".join(invalid))
        statement = statement.where(AuthorityRecord.entity_type.in_(selected_types))
    statuses = tuple(dict.fromkeys(lifecycle_statuses))
    if statuses:
        statement = statement.where(AuthorityRecord.lifecycle_status.in_(statuses))
    if temporal_start is not None or temporal_end is not None:
        overlap_parts = []
        if temporal_start is not None:
            overlap_parts.append(
                or_(AuthorityRecord.temporal_end.is_(None), AuthorityRecord.temporal_end >= temporal_start)
            )
        if temporal_end is not None:
            overlap_parts.append(
                or_(AuthorityRecord.temporal_start.is_(None), AuthorityRecord.temporal_start <= temporal_end)
            )
        dated = or_(AuthorityRecord.temporal_start.is_not(None), AuthorityRecord.temporal_end.is_not(None))
        overlap = and_(*overlap_parts)
        statement = statement.where(or_(overlap, ~dated) if include_undated else and_(dated, overlap))
    clean_query = normalize_authority_text(query)
    if clean_query:
        alias_ids = select(AuthorityAlias.authority_id).where(
            AuthorityAlias.normalized_alias.contains(clean_query)
        )
        statement = statement.where(
            or_(
                AuthorityRecord.normalized_name.contains(clean_query),
                AuthorityRecord.description.ilike(f"%{query.strip()}%"),
                AuthorityRecord.id.in_(alias_ids),
            )
        )
    records = session.scalars(
        statement.order_by(
            AuthorityRecord.entity_type,
            AuthorityRecord.normalized_name,
            AuthorityRecord.id,
        )
    ).all()
    if not records:
        return []
    ids = [row.id for row in records]
    aliases = session.scalars(
        select(AuthorityAlias)
        .where(AuthorityAlias.authority_id.in_(ids))
        .order_by(AuthorityAlias.normalized_alias, AuthorityAlias.id)
    ).all()
    aliases_by: dict[str, list[AuthorityAlias]] = {authority_id: [] for authority_id in ids}
    for row in aliases:
        aliases_by.setdefault(row.authority_id, []).append(row)
    mention_counts = dict(
        session.execute(
            select(EntityMention.authority_id, func.count(EntityMention.id))
            .where(EntityMention.authority_id.in_(ids), EntityMention.status != "rejected")
            .group_by(EntityMention.authority_id)
        ).all()
    )
    result: list[AuthorityRow] = []
    for row in records:
        alias_rows = [
            AliasRow(
                alias_id=item.id,
                alias=item.alias,
                normalized_alias=item.normalized_alias,
                alias_type=item.alias_type,
                note=item.note,
                created_by=item.created_by,
                created_at=item.created_at,
            )
            for item in aliases_by.get(row.id, [])
        ]
        result.append(
            AuthorityRow(
                authority_id=row.id,
                entity_type=row.entity_type,
                preferred_name=row.preferred_name,
                normalized_name=row.normalized_name,
                description=row.description,
                temporal_expression=row.temporal_expression,
                temporal_start=row.temporal_start,
                temporal_end=row.temporal_end,
                temporal_precision=row.temporal_precision,
                temporal_approximate=bool(row.temporal_approximate),
                temporal_note=row.temporal_note,
                lifecycle_status=row.lifecycle_status,
                review_status=row.review_status,
                revision=row.revision,
                alias_count=len(alias_rows),
                mention_count=int(mention_counts.get(row.id, 0)),
                aliases=alias_rows,
                created_by=row.created_by,
                created_at=row.created_at,
                updated_by=row.updated_by,
                updated_at=row.updated_at,
            )
        )
    return result


def authority_revision_rows(session: Session, authority_id: str) -> list[AuthorityRevision]:
    return session.scalars(
        select(AuthorityRevision)
        .where(AuthorityRevision.authority_id == authority_id)
        .order_by(AuthorityRevision.revision_number)
    ).all()


def _validate_mention_link(*, status: str, authority_id: str | None) -> None:
    if status in LINKED_MENTION_STATUSES and authority_id is None:
        raise ValueError(
            "Las menciones aceptadas o modificadas deben estar vinculadas a una autoridad"
        )


def project_mention_span_to_current(
    session: Session,
    mention: EntityMention,
    *,
    editable_object: EditableObject | None = None,
) -> tuple[int, int] | None:
    """Proyecta una mención histórica sobre el texto vigente del mismo objeto.

    La proyección es conservadora: primero exige que el fragmento permanezca dentro
    de un bloque ``equal`` de ``SequenceMatcher``. Como respaldo, acepta una única
    aparición literal del texto de la mención. Si hay ambigüedad, no inventa una
    correspondencia.
    """
    if mention.start_offset is None or mention.end_offset is None:
        return None
    obj = editable_object or session.get(EditableObject, mention.editable_object_id)
    if obj is None:
        return None
    if mention.object_revision_number == obj.revision_number:
        if 0 <= mention.start_offset < mention.end_offset <= len(obj.current_text):
            return mention.start_offset, mention.end_offset
        return None

    old_revision = session.scalar(
        select(EditableObjectRevision).where(
            EditableObjectRevision.editable_object_id == mention.editable_object_id,
            EditableObjectRevision.revision_number == mention.object_revision_number,
        )
    )
    if old_revision is not None:
        old_text = old_revision.text or ""
        matcher = difflib.SequenceMatcher(
            None, old_text, obj.current_text or "", autojunk=False
        )
        for tag, old_start, old_end, new_start, _new_end in matcher.get_opcodes():
            if (
                tag == "equal"
                and old_start <= mention.start_offset
                and mention.end_offset <= old_end
            ):
                projected_start = new_start + (mention.start_offset - old_start)
                projected_end = projected_start + (mention.end_offset - mention.start_offset)
                if (
                    0 <= projected_start < projected_end <= len(obj.current_text)
                    and obj.current_text[projected_start:projected_end].casefold()
                    == mention.mention_text.casefold()
                ):
                    return projected_start, projected_end

    matches = list(
        re.finditer(re.escape(mention.mention_text), obj.current_text or "", flags=re.IGNORECASE)
    )
    if len(matches) == 1:
        return matches[0].start(), matches[0].end()
    return None


def exact_mention_occurrences(
    text: str,
    fragment: str,
) -> list[tuple[int, int]]:
    """Devuelve todas las apariciones literales, ignorando mayúsculas.

    La función no normaliza espacios ni acentos: una reparación manual debe
    señalar un fragmento que exista exactamente en el texto vigente.
    """
    clean = fragment.strip()
    if not clean:
        return []
    return [
        (match.start(), match.end())
        for match in re.finditer(re.escape(clean), text or "", flags=re.IGNORECASE)
    ]


def _active_mentions_at_current_span(
    session: Session,
    *,
    object_id: str,
    start_offset: int,
    end_offset: int,
    exclude_mention_id: str | None = None,
) -> list[EntityMention]:
    obj = session.get(EditableObject, object_id)
    if obj is None:
        return []
    statement = (
        select(EntityMention)
        .where(
            EntityMention.editable_object_id == object_id,
            EntityMention.status != "rejected",
        )
        .order_by(
            EntityMention.object_revision_number.desc(),
            EntityMention.revision.desc(),
            EntityMention.id,
        )
    )
    if exclude_mention_id is not None:
        statement = statement.where(EntityMention.id != exclude_mention_id)
    result: list[EntityMention] = []
    for mention in session.scalars(statement).all():
        projected = project_mention_span_to_current(
            session, mention, editable_object=obj
        )
        if projected == (start_offset, end_offset):
            result.append(mention)
    return result


def _active_mention_at_offsets(
    session: Session,
    *,
    object_id: str,
    object_revision_number: int,
    start_offset: int,
    end_offset: int,
    exclude_mention_id: str | None = None,
) -> EntityMention | None:
    obj = session.get(EditableObject, object_id)
    if obj is not None and object_revision_number == obj.revision_number:
        rows = _active_mentions_at_current_span(
            session,
            object_id=object_id,
            start_offset=start_offset,
            end_offset=end_offset,
            exclude_mention_id=exclude_mention_id,
        )
        return rows[0] if rows else None

    statement = select(EntityMention).where(
        EntityMention.editable_object_id == object_id,
        EntityMention.object_revision_number == object_revision_number,
        EntityMention.start_offset == start_offset,
        EntityMention.end_offset == end_offset,
        EntityMention.status != "rejected",
    )
    if exclude_mention_id is not None:
        statement = statement.where(EntityMention.id != exclude_mention_id)
    return session.scalar(statement.order_by(EntityMention.id).limit(1))


def _locate_mention(text: str, mention_text: str, occurrence: int) -> tuple[int, int]:
    if occurrence < 1:
        raise ValueError("La aparición debe ser 1 o mayor")
    matches = list(re.finditer(re.escape(mention_text), text, flags=re.IGNORECASE))
    if len(matches) < occurrence:
        raise ValueError(
            f"No existe la aparición {occurrence} de {mention_text!r} en el texto actual"
        )
    match = matches[occurrence - 1]
    return match.start(), match.end()


def create_mention(
    session: Session,
    *,
    object_id: str,
    mention_text: str,
    created_by: str,
    authority_id: str | None = None,
    start_offset: int | None = None,
    end_offset: int | None = None,
    occurrence: int = 1,
    status: str = "accepted",
    source: str = "manual",
    confidence: float | None = None,
    note: str | None = None,
) -> EntityMention:
    obj = session.get(EditableObject, object_id)
    if obj is None:
        authority = session.get(AuthorityRecord, object_id)
        if authority is not None:
            raise ValueError(
                f"El UUID {object_id} corresponde a la entidad {authority.preferred_name!r}, "
                "no a un objeto textual editable. Usá mention-scan-all para recorrer todo el corpus "
                "o copiá el UUID de un objeto desde la vista Revisión."
            )
        raise ValueError(
            f"Objeto textual editable inexistente: {object_id}. "
            "Usá mention-scan-all para recorrer todo el corpus sin buscar UUID manualmente."
        )
    clean = mention_text.strip()
    if not clean:
        raise ValueError("La mención no puede estar vacía")
    if status not in MENTION_STATUSES:
        raise ValueError(f"Estado de mención inválido: {status}")
    if source not in MENTION_SOURCES:
        raise ValueError(f"Origen de mención inválido: {source}")
    if confidence is not None and not 0 <= confidence <= 1:
        raise ValueError("confidence debe estar entre 0 y 1")
    if authority_id is not None:
        authority = session.get(AuthorityRecord, authority_id)
        if authority is None:
            raise ValueError(f"Autoridad inexistente: {authority_id}")
        if authority.project_id != _project_id_for_object(session, object_id):
            raise ValueError("La autoridad y el objeto pertenecen a proyectos diferentes")
    _validate_mention_link(status=status, authority_id=authority_id)
    if start_offset is None and end_offset is None:
        start_offset, end_offset = _locate_mention(obj.current_text, clean, occurrence)
    elif start_offset is None or end_offset is None:
        raise ValueError("start_offset y end_offset deben indicarse juntos")
    else:
        if start_offset < 0 or end_offset <= start_offset or end_offset > len(obj.current_text):
            raise ValueError("Los offsets están fuera del texto actual")
        if obj.current_text[start_offset:end_offset].casefold() != clean.casefold():
            raise ValueError("Los offsets no corresponden con el texto de la mención")
    if status != "rejected":
        existing = _active_mention_at_offsets(
            session,
            object_id=obj.id,
            object_revision_number=obj.revision_number,
            start_offset=start_offset,
            end_offset=end_offset,
        )
        if existing is not None:
            raise ValueError(
                "Ya existe una mención activa sobre el mismo fragmento; "
                "revisala o vinculala en lugar de crear otra"
            )
    mention = EntityMention(
        id=new_id(),
        editable_object_id=obj.id,
        authority_id=authority_id,
        mention_text=obj.current_text[start_offset:end_offset],
        normalized_text=normalize_authority_text(clean),
        start_offset=start_offset,
        end_offset=end_offset,
        object_revision_number=obj.revision_number,
        status=status,
        source=source,
        confidence=confidence,
        note=note.strip() if note and note.strip() else None,
        created_by=created_by,
        created_at=utc_now(),
        updated_by=created_by,
        updated_at=utc_now(),
        revision=1,
    )
    session.add(mention)
    session.flush()
    _append_mention_revision(
        session, mention, operation="create", changed_by=created_by, note=note
    )
    return mention


def update_mention(
    session: Session,
    *,
    mention_id: str,
    expected_revision: int,
    changed_by: str,
    authority_id: str | None | object = _UNSET,
    status: str | None = None,
    note: str | None = None,
) -> EntityMention:
    mention = session.get(EntityMention, mention_id)
    if mention is None:
        raise ValueError(f"Mención inexistente: {mention_id}")
    if mention.revision != expected_revision:
        raise ValueError(
            f"La mención está en revisión {mention.revision}; se esperaba {expected_revision}"
        )

    next_status = mention.status if status is None else status
    if next_status not in MENTION_STATUSES:
        raise ValueError(f"Estado de mención inválido: {next_status}")

    next_authority_id = mention.authority_id
    if authority_id is not _UNSET:
        next_authority_id = None if authority_id is None else str(authority_id)
    if next_authority_id is not None:
        authority = session.get(AuthorityRecord, next_authority_id)
        if authority is None:
            raise ValueError(f"Autoridad inexistente: {next_authority_id}")
        if authority.project_id != _project_id_for_object(session, mention.editable_object_id):
            raise ValueError("La autoridad y la mención pertenecen a proyectos diferentes")

    _validate_mention_link(status=next_status, authority_id=next_authority_id)
    if next_status != "rejected" and mention.start_offset is not None and mention.end_offset is not None:
        current_span = project_mention_span_to_current(session, mention)
        if current_span is not None:
            duplicates = _active_mentions_at_current_span(
                session,
                object_id=mention.editable_object_id,
                start_offset=current_span[0],
                end_offset=current_span[1],
                exclude_mention_id=mention.id,
            )
            if duplicates:
                raise ValueError(
                    "Ya existe otra mención activa sobre el mismo fragmento, "
                    "incluso si proviene de otra revisión textual; resolvé el "
                    "duplicado antes de guardar"
                )

    mention.status = next_status
    mention.authority_id = next_authority_id
    if note is not None:
        mention.note = note.strip() or None
    mention.revision += 1
    mention.updated_by = changed_by
    mention.updated_at = utc_now()
    session.flush()
    _append_mention_revision(
        session, mention, operation="update", changed_by=changed_by, note=note
    )
    return mention


def mention_rows(
    session: Session,
    *,
    project_id: str | None = None,
    object_id: str | None = None,
    authority_id: str | None = None,
    statuses: Iterable[str] = (),
) -> list[MentionRow]:
    statement = (
        select(EntityMention, EditableObject, AuthorityRecord, SourceRegistration, ArchivalUnit)
        .join(EditableObject, EditableObject.id == EntityMention.editable_object_id)
        .join(DigitalObject, DigitalObject.id == EditableObject.digital_object_id)
        .outerjoin(AuthorityRecord, AuthorityRecord.id == EntityMention.authority_id)
        .outerjoin(
            SourceRegistration,
            (SourceRegistration.digital_object_id == DigitalObject.id)
            & (SourceRegistration.source_type.in_(PROCESSABLE_SOURCE_TYPES)),
        )
        .outerjoin(ArchivalUnit, ArchivalUnit.id == SourceRegistration.archival_unit_id)
    )
    if project_id is not None:
        statement = statement.where(DigitalObject.project_id == project_id)
    if object_id is not None:
        statement = statement.where(EntityMention.editable_object_id == object_id)
    if authority_id is not None:
        statement = statement.where(EntityMention.authority_id == authority_id)
    selected_statuses = tuple(dict.fromkeys(statuses))
    if selected_statuses:
        invalid = sorted(set(selected_statuses) - set(MENTION_STATUSES))
        if invalid:
            raise ValueError("Estados de mención inválidos: " + ", ".join(invalid))
        statement = statement.where(EntityMention.status.in_(selected_statuses))
    rows = session.execute(
        statement.order_by(
            EditableObject.page_number,
            EditableObject.current_order_index,
            EntityMention.start_offset,
            EntityMention.id,
        )
    ).all()
    seen: set[str] = set()
    result: list[MentionRow] = []
    for mention, obj, authority, registration, unit in rows:
        # Un objeto puede tener más de un source_registration; elegimos una fila estable.
        if mention.id in seen:
            continue
        seen.add(mention.id)
        result.append(
            MentionRow(
                mention_id=mention.id,
                object_id=obj.id,
                authority_id=mention.authority_id,
                authority_name=authority.preferred_name if authority else None,
                authority_type=authority.entity_type if authority else None,
                mention_text=mention.mention_text,
                start_offset=mention.start_offset,
                end_offset=mention.end_offset,
                object_revision_number=mention.object_revision_number,
                current_object_revision=obj.revision_number,
                status=mention.status,
                source=mention.source,
                confidence=mention.confidence,
                note=mention.note,
                revision=mention.revision,
                source_key=registration.source_key if registration else None,
                document_title=unit.title if unit else None,
                page_number=obj.page_number,
                order_index=obj.current_order_index,
                created_by=mention.created_by,
                created_at=mention.created_at,
                updated_by=mention.updated_by,
                updated_at=mention.updated_at,
            )
        )
    return result



def mention_revision_rows(session: Session, mention_id: str) -> list[EntityMentionRevision]:
    return session.scalars(
        select(EntityMentionRevision)
        .where(EntityMentionRevision.mention_id == mention_id)
        .order_by(EntityMentionRevision.revision_number)
    ).all()


def _latest_mention_revision(
    session: Session,
    mention_id: str,
) -> EntityMentionRevision | None:
    return session.scalar(
        select(EntityMentionRevision)
        .where(EntityMentionRevision.mention_id == mention_id)
        .order_by(EntityMentionRevision.revision_number.desc())
        .limit(1)
    )


def _mention_snapshot_difference_fields(
    mention: EntityMention,
    latest: EntityMentionRevision | None,
) -> tuple[str, ...]:
    if latest is None:
        return ("revision", "missing_snapshot")
    current = _mention_snapshot(mention)
    recorded = latest.snapshot_json
    fields = [
        field
        for field in current
        if current.get(field) != recorded.get(field)
    ]
    if mention.revision != latest.revision_number:
        fields.insert(0, "revision")
    return tuple(fields)


def _mention_snapshot_is_current(
    session: Session,
    mention: EntityMention,
) -> bool:
    latest = _latest_mention_revision(session, mention.id)
    return bool(
        latest is not None
        and latest.revision_number == mention.revision
        and latest.snapshot_json == _mention_snapshot(mention)
    )


def mention_repair_cases(
    session: Session,
    *,
    project_id: str,
) -> list[MentionRepairCase]:
    """Devuelve alertas activas de menciones sin modificar ningún dato.

    Las menciones rechazadas quedan como evidencia histórica y no se presentan
    como trabajo pendiente. Una reubicación solo se considera segura cuando el
    fragmento tiene una proyección única al texto vigente, no colisiona con otra
    mención activa y el último snapshot coincide con la fila actual.
    """
    rows = mention_rows(session, project_id=project_id)
    cases: list[MentionRepairCase] = []
    emitted_duplicate_groups: set[tuple[str, int, int, tuple[str, ...]]] = set()
    for row in rows:
        if row.status == "rejected":
            continue
        mention = session.get(EntityMention, row.mention_id)
        editable = session.get(EditableObject, row.object_id)
        if mention is None or editable is None:
            continue

        latest_snapshot = _latest_mention_revision(session, mention.id)
        snapshot_current = bool(
            latest_snapshot is not None
            and latest_snapshot.revision_number == mention.revision
            and latest_snapshot.snapshot_json == _mention_snapshot(mention)
        )
        if not snapshot_current:
            current_snapshot = _mention_snapshot(mention)
            recorded_snapshot = (
                dict(latest_snapshot.snapshot_json)
                if latest_snapshot is not None
                else None
            )
            difference_fields = _mention_snapshot_difference_fields(
                mention,
                latest_snapshot,
            )
            if latest_snapshot is None:
                explanation = (
                    "La fila vigente no tiene un snapshot histórico con el que pueda "
                    "compararse. El caso permanece bloqueado porque falta evidencia "
                    "para una reconciliación segura."
                )
            else:
                explanation = (
                    "La fila vigente no coincide con el último estado registrado. "
                    "Compará ambos estados y elegí explícitamente cuál conservar; "
                    "la decisión agregará una revisión nueva sin modificar el historial previo."
                )
            cases.append(
                MentionRepairCase(
                    code="snapshot_divergence",
                    severity="error",
                    mention_id=row.mention_id,
                    mention_revision=row.revision,
                    object_id=row.object_id,
                    authority_id=row.authority_id,
                    authority_name=row.authority_name,
                    mention_text=row.mention_text,
                    status=row.status,
                    stored_object_revision=row.object_revision_number,
                    current_object_revision=row.current_object_revision,
                    stored_start_offset=row.start_offset,
                    stored_end_offset=row.end_offset,
                    projected_start_offset=None,
                    projected_end_offset=None,
                    projected_text=None,
                    duplicate_mention_ids=(),
                    source_key=row.source_key,
                    document_title=row.document_title,
                    page_number=row.page_number,
                    order_index=row.order_index,
                    explanation=explanation,
                    snapshot_revision_number=(
                        latest_snapshot.revision_number
                        if latest_snapshot is not None
                        else None
                    ),
                    snapshot_operation=(
                        latest_snapshot.operation
                        if latest_snapshot is not None
                        else None
                    ),
                    snapshot_current=current_snapshot,
                    snapshot_recorded=recorded_snapshot,
                    snapshot_difference_fields=difference_fields,
                )
            )
            continue

        missing_authority = (
            row.status in LINKED_MENTION_STATUSES and row.authority_id is None
        )
        if missing_authority:
            cases.append(
                MentionRepairCase(
                    code="missing_authority",
                    severity="error",
                    mention_id=row.mention_id,
                    mention_revision=row.revision,
                    object_id=row.object_id,
                    authority_id=None,
                    authority_name=None,
                    mention_text=row.mention_text,
                    status=row.status,
                    stored_object_revision=row.object_revision_number,
                    current_object_revision=row.current_object_revision,
                    stored_start_offset=row.start_offset,
                    stored_end_offset=row.end_offset,
                    projected_start_offset=None,
                    projected_end_offset=None,
                    projected_text=None,
                    duplicate_mention_ids=(),
                    source_key=row.source_key,
                    document_title=row.document_title,
                    page_number=row.page_number,
                    order_index=row.order_index,
                    explanation=(
                        "La mención figura como aceptada o modificada, pero no está vinculada "
                        "a una entidad. Debe asignarse una entidad o volverla pendiente."
                    ),
                )
            )

        if missing_authority:
            continue
        if not row.is_stale:
            continue
        projected = project_mention_span_to_current(
            session, mention, editable_object=editable
        )
        if projected is None:
            cases.append(
                MentionRepairCase(
                    code="unresolved_relocation",
                    severity="warning",
                    mention_id=row.mention_id,
                    mention_revision=row.revision,
                    object_id=row.object_id,
                    authority_id=row.authority_id,
                    authority_name=row.authority_name,
                    mention_text=row.mention_text,
                    status=row.status,
                    stored_object_revision=row.object_revision_number,
                    current_object_revision=row.current_object_revision,
                    stored_start_offset=row.start_offset,
                    stored_end_offset=row.end_offset,
                    projected_start_offset=None,
                    projected_end_offset=None,
                    projected_text=None,
                    duplicate_mention_ids=(),
                    source_key=row.source_key,
                    document_title=row.document_title,
                    page_number=row.page_number,
                    order_index=row.order_index,
                    explanation=(
                        "El fragmento no pudo localizarse de manera única en el texto vigente. "
                        "Requiere una decisión humana; no se modificará automáticamente."
                    ),
                )
            )
            continue

        duplicates = _active_mentions_at_current_span(
            session,
            object_id=row.object_id,
            start_offset=projected[0],
            end_offset=projected[1],
            exclude_mention_id=row.mention_id,
        )
        projected_text = editable.current_text[projected[0] : projected[1]]
        if duplicates:
            duplicate_ids = tuple(sorted(item.id for item in duplicates))
            group_ids = tuple(sorted({row.mention_id, *duplicate_ids}))
            if len(group_ids) > 2:
                group_key = (row.object_id, projected[0], projected[1], group_ids)
                if group_key in emitted_duplicate_groups:
                    continue
                emitted_duplicate_groups.add(group_key)
                group_mentions = [
                    session.get(EntityMention, mention_id)
                    for mention_id in group_ids
                ]
                inconsistent_ids = tuple(
                    mention.id
                    for mention in group_mentions
                    if mention is None or not _mention_snapshot_is_current(session, mention)
                )
                block_reason = None
                if inconsistent_ids:
                    block_reason = (
                        "Una o más menciones del conjunto no coinciden con su último "
                        "estado registrado. Resolvé primero esas divergencias y volvé "
                        "a evaluar el conjunto completo."
                    )
                cases.append(
                    MentionRepairCase(
                        code="duplicate_group",
                        severity="error" if block_reason else "warning",
                        mention_id=row.mention_id,
                        mention_revision=row.revision,
                        object_id=row.object_id,
                        authority_id=row.authority_id,
                        authority_name=row.authority_name,
                        mention_text=row.mention_text,
                        status=row.status,
                        stored_object_revision=row.object_revision_number,
                        current_object_revision=row.current_object_revision,
                        stored_start_offset=row.start_offset,
                        stored_end_offset=row.end_offset,
                        projected_start_offset=projected[0],
                        projected_end_offset=projected[1],
                        projected_text=projected_text,
                        duplicate_mention_ids=tuple(
                            mention_id
                            for mention_id in group_ids
                            if mention_id != row.mention_id
                        ),
                        source_key=row.source_key,
                        document_title=row.document_title,
                        page_number=row.page_number,
                        order_index=row.order_index,
                        explanation=(
                            f"Hay {len(group_ids)} menciones activas que convergen sobre "
                            "el mismo fragmento. Debe revisarse el conjunto completo y "
                            "elegirse una única mención para conservar."
                        ),
                        group_block_reason=block_reason,
                    )
                )
                continue

            cases.append(
                MentionRepairCase(
                    code="duplicate_relocation",
                    severity="warning",
                    mention_id=row.mention_id,
                    mention_revision=row.revision,
                    object_id=row.object_id,
                    authority_id=row.authority_id,
                    authority_name=row.authority_name,
                    mention_text=row.mention_text,
                    status=row.status,
                    stored_object_revision=row.object_revision_number,
                    current_object_revision=row.current_object_revision,
                    stored_start_offset=row.start_offset,
                    stored_end_offset=row.end_offset,
                    projected_start_offset=projected[0],
                    projected_end_offset=projected[1],
                    projected_text=projected_text,
                    duplicate_mention_ids=duplicate_ids,
                    source_key=row.source_key,
                    document_title=row.document_title,
                    page_number=row.page_number,
                    order_index=row.order_index,
                    explanation=(
                        "La ubicación vigente pudo identificarse, pero ya existe otra mención "
                        "activa sobre el mismo fragmento. Debe decidirse cuál conservar."
                    ),
                )
            )
            continue

        cases.append(
            MentionRepairCase(
                code="safe_relocation",
                severity="warning",
                mention_id=row.mention_id,
                mention_revision=row.revision,
                object_id=row.object_id,
                authority_id=row.authority_id,
                authority_name=row.authority_name,
                mention_text=row.mention_text,
                status=row.status,
                stored_object_revision=row.object_revision_number,
                current_object_revision=row.current_object_revision,
                stored_start_offset=row.start_offset,
                stored_end_offset=row.end_offset,
                projected_start_offset=projected[0],
                projected_end_offset=projected[1],
                projected_text=projected_text,
                duplicate_mention_ids=(),
                source_key=row.source_key,
                document_title=row.document_title,
                page_number=row.page_number,
                order_index=row.order_index,
                explanation=(
                    "El fragmento conserva una única ubicación verificable en el texto vigente "
                    "y no colisiona con otra mención activa."
                ),
            )
        )

    order = {
        "snapshot_divergence": 0,
        "missing_authority": 1,
        "duplicate_group": 2,
        "duplicate_relocation": 3,
        "unresolved_relocation": 4,
        "safe_relocation": 5,
    }
    return sorted(
        cases,
        key=lambda item: (
            order.get(item.code, 99),
            item.document_title or "",
            item.page_number,
            item.order_index,
            item.mention_id,
        ),
    )


def _restore_mention_snapshot_values(
    session: Session,
    mention: EntityMention,
    snapshot: dict[str, object],
) -> None:
    required_fields = set(_mention_snapshot(mention))
    if set(snapshot) != required_fields:
        raise ValueError(
            "El último snapshot no contiene exactamente los campos esperados; "
            "la reconciliación permanece bloqueada"
        )

    object_id = snapshot["editable_object_id"]
    if not isinstance(object_id, str) or session.get(EditableObject, object_id) is None:
        raise ValueError("El objeto textual registrado en el snapshot ya no existe")

    authority_id = snapshot["authority_id"]
    if authority_id is not None:
        authority = (
            session.get(AuthorityRecord, authority_id)
            if isinstance(authority_id, str)
            else None
        )
        if authority is None:
            raise ValueError("La entidad registrada en el snapshot ya no existe")
        if authority.project_id != _project_id_for_object(session, object_id):
            raise ValueError(
                "La entidad y el objeto registrados en el snapshot pertenecen "
                "a proyectos diferentes"
            )

    mention_text = snapshot["mention_text"]
    normalized_text = snapshot["normalized_text"]
    if not isinstance(mention_text, str) or not mention_text:
        raise ValueError("El snapshot no contiene un fragmento de mención válido")
    if not isinstance(normalized_text, str):
        raise ValueError("El snapshot no contiene un texto normalizado válido")

    start_offset = snapshot["start_offset"]
    end_offset = snapshot["end_offset"]
    if (start_offset is None) != (end_offset is None):
        raise ValueError("El snapshot contiene offsets incompletos")
    if start_offset is not None:
        if (
            not isinstance(start_offset, int)
            or not isinstance(end_offset, int)
            or start_offset < 0
            or end_offset < start_offset
        ):
            raise ValueError("El snapshot contiene offsets inválidos")

    object_revision_number = snapshot["object_revision_number"]
    if not isinstance(object_revision_number, int) or object_revision_number < 1:
        raise ValueError("El snapshot contiene una revisión textual inválida")

    status = snapshot["status"]
    source = snapshot["source"]
    if status not in MENTION_STATUSES:
        raise ValueError(f"El snapshot contiene un estado inválido: {status}")
    _validate_mention_link(status=str(status), authority_id=authority_id)
    if source not in MENTION_SOURCES:
        raise ValueError(f"El snapshot contiene una procedencia inválida: {source}")

    confidence = snapshot["confidence"]
    if confidence is not None and not isinstance(confidence, (int, float)):
        raise ValueError("El snapshot contiene una confianza inválida")
    note = snapshot["note"]
    if note is not None and not isinstance(note, str):
        raise ValueError("El snapshot contiene una nota inválida")

    mention.editable_object_id = object_id
    mention.authority_id = authority_id
    mention.mention_text = mention_text
    mention.normalized_text = normalized_text
    mention.start_offset = start_offset
    mention.end_offset = end_offset
    mention.object_revision_number = object_revision_number
    mention.status = status
    mention.source = source
    mention.confidence = float(confidence) if confidence is not None else None
    mention.note = note


def repair_snapshot_divergence(
    session: Session,
    *,
    mention_id: str,
    expected_revision: int,
    expected_snapshot_revision: int,
    expected_current_snapshot: dict[str, object],
    expected_recorded_snapshot: dict[str, object],
    changed_by: str,
    decision: str,
    note: str | None = None,
) -> EntityMention:
    """Reconcilia una fila divergente sin alterar snapshots anteriores.

    ``decision="adopt_current"`` conserva los valores actuales y los registra
    como una nueva revisión explícita. ``decision="restore_snapshot"`` primero
    registra la fila divergente y luego repone los valores del último snapshot
    mediante otra revisión. Ninguna ruta modifica o elimina revisiones previas.
    """
    if decision not in {"adopt_current", "restore_snapshot"}:
        raise ValueError(f"Decisión de reconciliación inválida: {decision}")

    mention = session.get(EntityMention, mention_id)
    if mention is None:
        raise ValueError(f"Mención inexistente: {mention_id}")
    if mention.revision != expected_revision:
        raise ValueError(
            f"La mención está en revisión {mention.revision}; se esperaba {expected_revision}"
        )

    latest = _latest_mention_revision(session, mention.id)
    if latest is None:
        raise ValueError(
            "La mención no tiene un snapshot histórico verificable; "
            "la reconciliación permanece bloqueada"
        )
    if latest.revision_number != expected_snapshot_revision:
        raise ValueError(
            "El último snapshot cambió desde que se mostró la alerta; volvé a evaluarla"
        )
    if latest.snapshot_json != expected_recorded_snapshot:
        raise ValueError(
            "El contenido del último snapshot cambió desde que se mostró la alerta; "
            "volvé a evaluarla"
        )

    current_snapshot = _mention_snapshot(mention)
    if current_snapshot != expected_current_snapshot:
        raise ValueError(
            "La fila vigente cambió desde que se mostró la alerta; volvé a evaluarla"
        )
    if (
        latest.revision_number == mention.revision
        and latest.snapshot_json == current_snapshot
    ):
        raise ValueError("La fila vigente ya coincide con su último snapshot")

    actor = changed_by.strip() or "local_user"
    clean_note = note.strip() if note and note.strip() else None

    if decision == "restore_snapshot":
        # Antes de restaurar, la fila divergente se incorpora al historial para
        # que ningún valor observado desaparezca de la evidencia auditable.
        mention.revision = latest.revision_number + 1
        mention.updated_by = actor
        mention.updated_at = utc_now()
        session.flush()
        _append_mention_revision(
            session,
            mention,
            operation="repair_capture_divergent_row",
            changed_by=actor,
            note=(
                "Estado divergente conservado antes de restaurar el último "
                "snapshot registrado."
            ),
        )

        _restore_mention_snapshot_values(
            session,
            mention,
            dict(latest.snapshot_json),
        )
        mention.revision += 1
        mention.updated_by = actor
        mention.updated_at = utc_now()
        session.flush()
        _append_mention_revision(
            session,
            mention,
            operation="repair_restore_snapshot",
            changed_by=actor,
            note=(
                clean_note
                or (
                    "Se restauró el último estado registrado después de comparar "
                    "la fila vigente con su historial."
                )
            ),
        )
        return mention

    mention.revision = latest.revision_number + 1
    mention.updated_by = actor
    mention.updated_at = utc_now()
    session.flush()
    _append_mention_revision(
        session,
        mention,
        operation="repair_adopt_current_row",
        changed_by=actor,
        note=(
            clean_note
            or (
                "Se conservó la fila vigente y se la incorporó explícitamente "
                "al historial después de revisar la divergencia."
            )
        ),
    )
    return mention


def repair_stale_mention(
    session: Session,
    *,
    mention_id: str,
    expected_revision: int,
    changed_by: str,
    note: str | None = None,
    expected_start_offset: int | None = None,
    expected_end_offset: int | None = None,
) -> EntityMention:
    """Reubica una mención sobre el texto vigente y agrega una revisión auditable."""
    mention = session.get(EntityMention, mention_id)
    if mention is None:
        raise ValueError(f"Mención inexistente: {mention_id}")
    if mention.revision != expected_revision:
        raise ValueError(
            f"La mención está en revisión {mention.revision}; se esperaba {expected_revision}"
        )
    if mention.status == "rejected":
        raise ValueError("Una mención rechazada es evidencia histórica y no se reubica")
    editable = session.get(EditableObject, mention.editable_object_id)
    if editable is None:
        raise ValueError("El objeto textual de la mención ya no existe")
    if mention.object_revision_number == editable.revision_number:
        raise ValueError("La mención ya pertenece a la revisión textual vigente")
    if not _mention_snapshot_is_current(session, mention):
        raise ValueError(
            "La fila vigente no coincide con su último snapshot; revisá la divergencia antes de reparar"
        )

    projected = project_mention_span_to_current(
        session, mention, editable_object=editable
    )
    if projected is None:
        raise ValueError(
            "El fragmento no puede localizarse de manera única en el texto vigente"
        )
    if (
        expected_start_offset is not None
        and expected_end_offset is not None
        and projected != (expected_start_offset, expected_end_offset)
    ):
        raise ValueError(
            "La ubicación proyectada cambió desde la revisión de la alerta; volvé a evaluarla"
        )
    duplicates = _active_mentions_at_current_span(
        session,
        object_id=editable.id,
        start_offset=projected[0],
        end_offset=projected[1],
        exclude_mention_id=mention.id,
    )
    if duplicates:
        raise ValueError(
            "Ya existe otra mención activa sobre la ubicación vigente: "
            + ", ".join(sorted(item.id for item in duplicates))
        )

    old_revision = mention.object_revision_number
    mention.start_offset = projected[0]
    mention.end_offset = projected[1]
    mention.mention_text = editable.current_text[projected[0] : projected[1]]
    mention.normalized_text = normalize_authority_text(mention.mention_text)
    mention.object_revision_number = editable.revision_number
    mention.revision += 1
    mention.updated_by = changed_by
    mention.updated_at = utc_now()
    repair_note = (
        note.strip()
        if note and note.strip()
        else (
            f"Reubicación segura desde la revisión textual {old_revision} "
            f"a la {editable.revision_number}."
        )
    )
    session.flush()
    _append_mention_revision(
        session,
        mention,
        operation="repair_relocation",
        changed_by=changed_by,
        note=repair_note,
    )
    return mention


def repair_unresolved_relocation(
    session: Session,
    *,
    mention_id: str,
    expected_revision: int,
    expected_object_revision: int,
    changed_by: str,
    decision: str,
    selected_fragment: str | None = None,
    expected_start_offset: int | None = None,
    expected_end_offset: int | None = None,
    note: str | None = None,
) -> EntityMention:
    """Resuelve manualmente una ubicación ambigua sin borrar evidencia.

    ``decision="relocate"`` exige un fragmento literal y una ubicación exacta
    dentro del texto vigente. ``decision="mark_absent"`` retira la mención
    activa cuando el fragmento histórico ya no aparece en el texto actual.
    Ambas rutas agregan una revisión; ninguna modifica snapshots anteriores.
    """
    if decision not in {"relocate", "mark_absent"}:
        raise ValueError(f"Decisión de ubicación inválida: {decision}")

    mention = session.get(EntityMention, mention_id)
    if mention is None:
        raise ValueError(f"Mención inexistente: {mention_id}")
    if mention.revision != expected_revision:
        raise ValueError(
            f"La mención está en revisión {mention.revision}; se esperaba {expected_revision}"
        )
    if mention.status == "rejected":
        raise ValueError("La mención ya está retirada y solo se conserva como evidencia")
    if not _mention_snapshot_is_current(session, mention):
        raise ValueError(
            "La fila vigente no coincide con su último snapshot; revisá la divergencia antes de reparar"
        )

    editable = session.get(EditableObject, mention.editable_object_id)
    if editable is None:
        raise ValueError("El objeto textual de la mención ya no existe")
    if editable.revision_number != expected_object_revision:
        raise ValueError(
            "La revisión textual cambió desde que se mostró la alerta; volvé a evaluarla"
        )
    if mention.object_revision_number == editable.revision_number:
        raise ValueError("La mención ya pertenece a la revisión textual vigente")
    if project_mention_span_to_current(
        session,
        mention,
        editable_object=editable,
    ) is not None:
        raise ValueError(
            "La mención ya tiene una proyección verificable; volvé a evaluar la alerta"
        )

    original_occurrences = exact_mention_occurrences(
        editable.current_text,
        mention.mention_text,
    )

    if decision == "mark_absent":
        if original_occurrences:
            raise ValueError(
                "El fragmento histórico todavía aparece en el texto vigente; seleccioná una ubicación"
            )
        previous_status = mention.status
        mention.status = "rejected"
        mention.revision += 1
        mention.updated_by = changed_by
        mention.updated_at = utc_now()
        clean_note = (
            note.strip()
            if note and note.strip()
            else (
                f"La mención se retiró desde el estado {previous_status} porque el "
                f"fragmento ya no aparece en la revisión textual {editable.revision_number}."
            )
        )
        mention.note = clean_note
        session.flush()
        _append_mention_revision(
            session,
            mention,
            operation="repair_mark_absent",
            changed_by=changed_by,
            note=clean_note,
        )
        return mention

    clean_fragment = (selected_fragment or "").strip()
    if not clean_fragment:
        raise ValueError("Indicá un fragmento exacto del texto vigente")
    if expected_start_offset is None or expected_end_offset is None:
        raise ValueError("Seleccioná una aparición concreta del fragmento vigente")
    if (
        expected_start_offset < 0
        or expected_end_offset <= expected_start_offset
        or expected_end_offset > len(editable.current_text)
    ):
        raise ValueError("La ubicación seleccionada está fuera del texto vigente")

    current_fragment = editable.current_text[
        expected_start_offset:expected_end_offset
    ]
    if current_fragment.casefold() != clean_fragment.casefold():
        raise ValueError(
            "El fragmento o su ubicación cambiaron desde la selección; volvé a evaluarlos"
        )
    candidates = exact_mention_occurrences(editable.current_text, clean_fragment)
    if (expected_start_offset, expected_end_offset) not in candidates:
        raise ValueError("La aparición seleccionada ya no existe en el texto vigente")

    duplicates = _active_mentions_at_current_span(
        session,
        object_id=editable.id,
        start_offset=expected_start_offset,
        end_offset=expected_end_offset,
        exclude_mention_id=mention.id,
    )
    if duplicates:
        raise ValueError(
            "Ya existe otra mención activa sobre la ubicación seleccionada: "
            + ", ".join(sorted(item.id for item in duplicates))
        )

    old_revision = mention.object_revision_number
    mention.start_offset = expected_start_offset
    mention.end_offset = expected_end_offset
    mention.mention_text = current_fragment
    mention.normalized_text = normalize_authority_text(current_fragment)
    mention.object_revision_number = editable.revision_number
    mention.revision += 1
    mention.updated_by = changed_by
    mention.updated_at = utc_now()
    clean_note = (
        note.strip()
        if note and note.strip()
        else (
            f"Reubicación manual desde la revisión textual {old_revision} "
            f"a la {editable.revision_number}."
        )
    )
    mention.note = clean_note
    session.flush()
    _append_mention_revision(
        session,
        mention,
        operation="repair_manual_relocation",
        changed_by=changed_by,
        note=clean_note,
    )
    return mention


def repair_missing_authority(
    session: Session,
    *,
    mention_id: str,
    expected_revision: int,
    changed_by: str,
    decision: str,
    authority_id: str | None = None,
    note: str | None = None,
) -> EntityMention:
    """Resuelve una mención enlazada que perdió su autoridad sin borrar historial.

    ``decision="link"`` conserva el estado aceptado o modificado y vincula una
    autoridad activa del mismo proyecto. ``decision="return_pending"`` devuelve
    la mención a revisión pendiente, sin autoridad. Ambas rutas agregan un nuevo
    snapshot auditable y nunca reescriben revisiones anteriores.
    """
    mention = session.get(EntityMention, mention_id)
    if mention is None:
        raise ValueError(f"Mención inexistente: {mention_id}")
    if mention.revision != expected_revision:
        raise ValueError(
            f"La mención está en revisión {mention.revision}; se esperaba {expected_revision}"
        )
    if mention.status not in LINKED_MENTION_STATUSES or mention.authority_id is not None:
        raise ValueError(
            "La mención ya no está aceptada o modificada sin una entidad vinculada"
        )
    if not _mention_snapshot_is_current(session, mention):
        raise ValueError(
            "La fila vigente no coincide con su último snapshot; revisá la divergencia antes de reparar"
        )
    if decision not in {"link", "return_pending"}:
        raise ValueError(f"Decisión de reparación inválida: {decision}")

    previous_status = mention.status
    if decision == "link":
        if authority_id is None:
            raise ValueError("Seleccioná una entidad para vincular la mención")
        authority = session.get(AuthorityRecord, authority_id)
        if authority is None:
            raise ValueError(f"Autoridad inexistente: {authority_id}")
        if authority.lifecycle_status != "active":
            raise ValueError("La entidad seleccionada no está activa")
        if authority.project_id != _project_id_for_object(
            session, mention.editable_object_id
        ):
            raise ValueError("La autoridad y la mención pertenecen a proyectos diferentes")
        mention.authority_id = authority.id
        operation = "repair_link_authority"
        default_note = (
            f"Vinculación reparada con la entidad {authority.preferred_name!r}; "
            f"se conserva el estado {previous_status}."
        )
    else:
        if authority_id is not None:
            raise ValueError(
                "No indiques una entidad al devolver la mención a estado pendiente"
            )
        mention.status = "pending"
        mention.authority_id = None
        operation = "repair_return_pending"
        default_note = (
            f"La mención se devolvió a pendiente desde el estado {previous_status} "
            "porque no tenía una entidad verificable."
        )

    clean_note = note.strip() if note and note.strip() else default_note
    mention.note = clean_note
    mention.revision += 1
    mention.updated_by = changed_by
    mention.updated_at = utc_now()
    session.flush()
    _append_mention_revision(
        session,
        mention,
        operation=operation,
        changed_by=changed_by,
        note=clean_note,
    )
    return mention


def repair_duplicate_relocation(
    session: Session,
    *,
    mention_id: str,
    expected_revision: int,
    duplicate_mention_id: str,
    duplicate_expected_revision: int,
    changed_by: str,
    expected_object_revision: int | None = None,
    expected_start_offset: int | None = None,
    expected_end_offset: int | None = None,
    decision: str,
    note: str | None = None,
) -> tuple[EntityMention, EntityMention]:
    """Resuelve una colisión entre una mención histórica y una vigente.

    ``decision="keep_current"`` conserva la mención ya ubicada en el texto
    vigente y rechaza la mención histórica. ``decision="keep_historical"``
    rechaza la mención vigente y reubica la histórica. Todas las escrituras
    agregan snapshots; ninguna revisión anterior se modifica.
    """
    if decision not in {"keep_current", "keep_historical"}:
        raise ValueError(f"Decisión de duplicado inválida: {decision}")

    historical = session.get(EntityMention, mention_id)
    if historical is None:
        raise ValueError(f"Mención histórica inexistente: {mention_id}")
    current = session.get(EntityMention, duplicate_mention_id)
    if current is None:
        raise ValueError(f"Mención vigente inexistente: {duplicate_mention_id}")
    if historical.id == current.id:
        raise ValueError("La mención histórica y la vigente deben ser diferentes")
    if historical.revision != expected_revision:
        raise ValueError(
            f"La mención histórica está en revisión {historical.revision}; "
            f"se esperaba {expected_revision}"
        )
    if current.revision != duplicate_expected_revision:
        raise ValueError(
            f"La mención vigente está en revisión {current.revision}; "
            f"se esperaba {duplicate_expected_revision}"
        )
    if historical.status == "rejected" or current.status == "rejected":
        raise ValueError("Una de las menciones ya fue rechazada; volvé a evaluar la alerta")
    if historical.editable_object_id != current.editable_object_id:
        raise ValueError("Las menciones duplicadas no pertenecen al mismo objeto textual")
    if not _mention_snapshot_is_current(session, historical):
        raise ValueError(
            "La mención histórica no coincide con su último snapshot; "
            "revisá la divergencia antes de reparar"
        )
    if not _mention_snapshot_is_current(session, current):
        raise ValueError(
            "La mención vigente no coincide con su último snapshot; "
            "revisá la divergencia antes de reparar"
        )

    editable = session.get(EditableObject, historical.editable_object_id)
    if editable is None:
        raise ValueError("El objeto textual de las menciones ya no existe")
    if historical.object_revision_number == editable.revision_number:
        raise ValueError("La mención indicada como histórica ya pertenece al texto vigente")
    if (
        expected_object_revision is not None
        and editable.revision_number != expected_object_revision
    ):
        raise ValueError(
            "El texto vigente cambió desde la revisión de la alerta; volvé a evaluarla"
        )

    projected = project_mention_span_to_current(
        session,
        historical,
        editable_object=editable,
    )
    if projected is None:
        raise ValueError("La ubicación histórica ya no puede proyectarse de manera única")
    if (
        expected_start_offset is not None
        and expected_end_offset is not None
        and projected != (expected_start_offset, expected_end_offset)
    ):
        raise ValueError(
            "La ubicación proyectada cambió desde la revisión de la alerta; "
            "volvé a evaluarla"
        )
    current_span = project_mention_span_to_current(
        session,
        current,
        editable_object=editable,
    )
    if current_span != projected:
        raise ValueError(
            "Las menciones ya no coinciden sobre la misma ubicación vigente; "
            "volvé a evaluar la alerta"
        )

    active_duplicates = _active_mentions_at_current_span(
        session,
        object_id=editable.id,
        start_offset=projected[0],
        end_offset=projected[1],
        exclude_mention_id=historical.id,
    )
    active_ids = tuple(sorted(item.id for item in active_duplicates))
    if active_ids != (current.id,):
        raise ValueError(
            "El conjunto de menciones activas cambió desde la revisión de la alerta; "
            "volvé a evaluarla"
        )

    actor = changed_by.strip() or "local_user"
    clean_note = note.strip() if note and note.strip() else None

    def reject_loser(loser: EntityMention, *, winner: EntityMention) -> None:
        loser.status = "rejected"
        loser.note = clean_note or (
            "Mención retirada como duplicada; se conserva la mención "
            f"{winner.id}."
        )
        loser.revision += 1
        loser.updated_by = actor
        loser.updated_at = utc_now()
        session.flush()
        _append_mention_revision(
            session,
            loser,
            operation="repair_duplicate_rejected",
            changed_by=actor,
            note=loser.note,
        )

    if decision == "keep_current":
        reject_loser(historical, winner=current)
        return historical, current

    reject_loser(current, winner=historical)
    historical.start_offset = projected[0]
    historical.end_offset = projected[1]
    historical.mention_text = editable.current_text[projected[0] : projected[1]]
    historical.normalized_text = normalize_authority_text(historical.mention_text)
    historical.object_revision_number = editable.revision_number
    historical.note = clean_note or (
        "Mención histórica conservada y reubicada después de retirar el duplicado "
        f"{current.id}."
    )
    historical.revision += 1
    historical.updated_by = actor
    historical.updated_at = utc_now()
    session.flush()
    _append_mention_revision(
        session,
        historical,
        operation="repair_duplicate_relocated",
        changed_by=actor,
        note=historical.note,
    )
    return historical, current



def repair_duplicate_group(
    session: Session,
    *,
    mention_ids: Sequence[str],
    expected_revisions: Mapping[str, int],
    winner_mention_id: str,
    expected_object_revision: int,
    expected_start_offset: int,
    expected_end_offset: int,
    changed_by: str,
    note: str | None = None,
) -> tuple[EntityMention, list[EntityMention]]:
    """Resuelve de manera atómica un conjunto de tres o más menciones coincidentes.

    Se conserva exactamente una mención. Todas las demás pasan a ``rejected`` y
    cada cambio agrega un snapshot nuevo. Si la ganadora pertenece a una revisión
    textual anterior, también se la reubica sobre el texto vigente.
    """
    group_ids = tuple(sorted(set(mention_ids)))
    if len(group_ids) < 3:
        raise ValueError(
            "La revisión conjunta exige al menos tres menciones activas coincidentes"
        )
    if winner_mention_id not in group_ids:
        raise ValueError("La mención elegida no pertenece al conjunto revisado")
    if set(expected_revisions) != set(group_ids):
        raise ValueError(
            "Las revisiones esperadas no describen exactamente el conjunto revisado"
        )

    mentions: list[EntityMention] = []
    for mention_id in group_ids:
        mention = session.get(EntityMention, mention_id)
        if mention is None:
            raise ValueError(f"Mención inexistente dentro del conjunto: {mention_id}")
        if mention.revision != expected_revisions[mention_id]:
            raise ValueError(
                f"La mención {mention_id} está en revisión {mention.revision}; "
                f"se esperaba {expected_revisions[mention_id]}"
            )
        if mention.status == "rejected":
            raise ValueError(
                "Una mención del conjunto ya fue retirada; volvé a evaluar la alerta"
            )
        if not _mention_snapshot_is_current(session, mention):
            raise ValueError(
                "Una mención del conjunto no coincide con su último snapshot; "
                "resolvé primero la divergencia"
            )
        mentions.append(mention)

    object_ids = {mention.editable_object_id for mention in mentions}
    if len(object_ids) != 1:
        raise ValueError("Las menciones del conjunto no pertenecen al mismo objeto textual")
    object_id = next(iter(object_ids))
    editable = session.get(EditableObject, object_id)
    if editable is None:
        raise ValueError("El objeto textual del conjunto ya no existe")
    if editable.revision_number != expected_object_revision:
        raise ValueError(
            "El texto vigente cambió desde la revisión del conjunto; volvé a evaluarlo"
        )

    expected_span = (expected_start_offset, expected_end_offset)
    if not (
        0 <= expected_start_offset < expected_end_offset <= len(editable.current_text)
    ):
        raise ValueError("La ubicación esperada del conjunto no es válida")
    for mention in mentions:
        projected = project_mention_span_to_current(
            session,
            mention,
            editable_object=editable,
        )
        if projected != expected_span:
            raise ValueError(
                "Una mención ya no converge sobre la ubicación revisada; "
                "volvé a evaluar el conjunto completo"
            )

    active_ids = tuple(
        sorted(
            mention.id
            for mention in _active_mentions_at_current_span(
                session,
                object_id=object_id,
                start_offset=expected_start_offset,
                end_offset=expected_end_offset,
            )
        )
    )
    if active_ids != group_ids:
        raise ValueError(
            "El conjunto de menciones activas cambió desde la revisión; "
            "volvé a evaluarlo completo"
        )

    actor = changed_by.strip() or "local_user"
    clean_note = note.strip() if note and note.strip() else (
        "Decisión conjunta sobre menciones coincidentes después de comparar "
        "entidad, estado, procedencia e historial."
    )
    winner = next(mention for mention in mentions if mention.id == winner_mention_id)
    losers = [mention for mention in mentions if mention.id != winner_mention_id]

    for loser in losers:
        loser.status = "rejected"
        loser.note = (
            f"{clean_note} Se conserva la mención {winner_mention_id}."
        )
        loser.revision += 1
        loser.updated_by = actor
        loser.updated_at = utc_now()
        session.flush()
        _append_mention_revision(
            session,
            loser,
            operation="repair_group_duplicate_rejected",
            changed_by=actor,
            note=loser.note,
        )

    winner.note = clean_note
    if winner.object_revision_number != editable.revision_number:
        winner.start_offset = expected_start_offset
        winner.end_offset = expected_end_offset
        winner.mention_text = editable.current_text[
            expected_start_offset:expected_end_offset
        ]
        winner.normalized_text = normalize_authority_text(winner.mention_text)
        winner.object_revision_number = editable.revision_number
        winner_operation = "repair_group_duplicate_relocated"
    else:
        winner_operation = "repair_group_duplicate_kept"
    winner.revision += 1
    winner.updated_by = actor
    winner.updated_at = utc_now()
    session.flush()
    _append_mention_revision(
        session,
        winner,
        operation=winner_operation,
        changed_by=actor,
        note=winner.note,
    )
    return winner, losers


def repair_safe_relocation_group(
    session: Session,
    *,
    expected_cases: Sequence[MentionRepairCase],
    changed_by: str,
    note: str | None = None,
) -> list[EntityMention]:
    """Reubica atómicamente varias menciones seguras del mismo objeto textual."""
    cases = list(expected_cases)
    if len(cases) < 2:
        raise ValueError(
            "La operación agrupada exige al menos dos reubicaciones seguras"
        )
    if any(not case.can_relocate for case in cases):
        raise ValueError(
            "El conjunto contiene una mención que no tiene reubicación segura"
        )
    mention_ids = [case.mention_id for case in cases]
    if len(set(mention_ids)) != len(mention_ids):
        raise ValueError("El conjunto contiene menciones repetidas")
    object_ids = {case.object_id for case in cases}
    if len(object_ids) != 1:
        raise ValueError(
            "Las reubicaciones agrupadas deben pertenecer al mismo objeto textual"
        )
    object_id = next(iter(object_ids))
    editable = session.get(EditableObject, object_id)
    if editable is None:
        raise ValueError("El objeto textual del conjunto ya no existe")
    expected_object_revisions = {case.current_object_revision for case in cases}
    if expected_object_revisions != {editable.revision_number}:
        raise ValueError(
            "El texto vigente cambió desde la revisión del conjunto; volvé a evaluarlo"
        )

    validated: list[tuple[EntityMention, int, int]] = []
    for case in cases:
        mention = session.get(EntityMention, case.mention_id)
        if mention is None:
            raise ValueError(f"Mención inexistente: {case.mention_id}")
        if mention.revision != case.mention_revision:
            raise ValueError(
                f"La mención {mention.id} cambió desde la revisión del conjunto"
            )
        if mention.status == "rejected":
            raise ValueError(
                "Una mención del conjunto ya fue retirada; volvé a evaluarlo"
            )
        if not _mention_snapshot_is_current(session, mention):
            raise ValueError(
                "Una mención del conjunto no coincide con su último snapshot"
            )
        if mention.object_revision_number == editable.revision_number:
            raise ValueError(
                "Una mención del conjunto ya pertenece al texto vigente"
            )
        projected = project_mention_span_to_current(
            session, mention, editable_object=editable
        )
        expected_span = (case.projected_start_offset, case.projected_end_offset)
        if projected != expected_span or None in expected_span:
            raise ValueError(
                "Una ubicación proyectada cambió desde la revisión del conjunto"
            )
        assert projected is not None
        collisions = _active_mentions_at_current_span(
            session,
            object_id=object_id,
            start_offset=projected[0],
            end_offset=projected[1],
            exclude_mention_id=mention.id,
        )
        if collisions:
            raise ValueError(
                "Una ubicación segura ahora está ocupada por otra mención; "
                "volvé a evaluar el conjunto"
            )
        validated.append((mention, projected[0], projected[1]))

    actor = changed_by.strip() or "local_user"
    clean_note = note.strip() if note and note.strip() else (
        f"Reubicación agrupada de {len(validated)} menciones con proyección única "
        "sobre el mismo texto vigente."
    )
    repaired: list[EntityMention] = []
    for mention, start_offset, end_offset in validated:
        mention.start_offset = start_offset
        mention.end_offset = end_offset
        mention.mention_text = editable.current_text[start_offset:end_offset]
        mention.normalized_text = normalize_authority_text(mention.mention_text)
        mention.object_revision_number = editable.revision_number
        mention.note = clean_note
        mention.revision += 1
        mention.updated_by = actor
        mention.updated_at = utc_now()
        session.flush()
        _append_mention_revision(
            session,
            mention,
            operation="repair_group_relocation",
            changed_by=actor,
            note=clean_note,
        )
        repaired.append(mention)
    return repaired

def suggest_dictionary_mentions(
    session: Session,
    *,
    object_id: str,
    created_by: str,
    page_review_statuses: Iterable[str] = DEFAULT_AUTOMATIC_PAGE_REVIEW_STATUSES,
    broader_quality_scope_confirmed: bool = False,
    quality_scope_reason: str | None = None,
    quality_scope_source: str = "api",
    _authorization_recorded: bool = False,
) -> SuggestionSummary:
    obj = session.get(EditableObject, object_id)
    if obj is None:
        entity = session.get(AuthorityRecord, object_id)
        if entity is not None:
            raise ValueError(
                f"El UUID {object_id} corresponde a la entidad {entity.preferred_name!r}, "
                "no a un objeto textual editable. Usá mention-scan-all para recorrer todo "
                "el corpus o copiá el UUID de un objeto desde la vista Revisión."
            )
        raise ValueError(
            f"Objeto textual editable inexistente: {object_id}. "
            "Usá mention-scan-all para recorrer todo el corpus sin buscar UUID manualmente."
        )
    project_id = _project_id_for_object(session, object_id)
    if _authorization_recorded:
        selected_page_statuses = _validated_page_review_statuses(
            page_review_statuses,
            broader_scope_confirmed=broader_quality_scope_confirmed,
            quality_scope_reason=quality_scope_reason,
        )
    else:
        selected_page_statuses = record_mention_suggestion_authorization(
            session,
            project_id=project_id,
            page_review_statuses=page_review_statuses,
            broader_quality_scope_confirmed=broader_quality_scope_confirmed,
            quality_scope_reason=quality_scope_reason,
            actor=created_by,
            source=quality_scope_source,
            target_type="editable_object",
            target_id=object_id,
            parameters={"mode": "dictionary_object", "object_id": object_id},
        )
    page = session.get(EditablePage, obj.editable_page_id)
    if selected_page_statuses and (
        page is None or page.review_status not in selected_page_statuses
    ):
        current = page.review_status if page is not None else "desconocido"
        raise ValueError(
            "La página no cumple el filtro de calidad para sugerencias automáticas "
            f"(estado actual: {current})"
        )
    authorities = session.scalars(
        select(AuthorityRecord)
        .where(
            AuthorityRecord.project_id == project_id,
            AuthorityRecord.lifecycle_status == "active",
        )
        .order_by(AuthorityRecord.id)
    ).all()
    authority_ids = [row.id for row in authorities]
    aliases = session.scalars(
        select(AuthorityAlias).where(AuthorityAlias.authority_id.in_(authority_ids))
    ).all() if authority_ids else []
    surfaces: dict[str, list[tuple[str, str]]] = {}
    display: dict[tuple[str, str], str] = {}
    for authority in authorities:
        normalized = normalize_authority_text(authority.preferred_name)
        if len(normalized) >= 3:
            surfaces.setdefault(normalized, []).append((authority.id, "preferred"))
            display[(authority.id, normalized)] = authority.preferred_name
    for alias in aliases:
        if len(alias.normalized_alias) >= 3:
            surfaces.setdefault(alias.normalized_alias, []).append((alias.authority_id, "alias"))
            display[(alias.authority_id, alias.normalized_alias)] = alias.alias
    existing = {
        (row.start_offset, row.end_offset, row.object_revision_number)
        for row in session.scalars(
            select(EntityMention).where(
                EntityMention.editable_object_id == object_id,
                EntityMention.status != "rejected",
            )
        ).all()
        if row.start_offset is not None and row.end_offset is not None
    }
    matches: list[tuple[int, int, str, str]] = []
    ambiguous = 0
    for normalized, candidates in surfaces.items():
        # Las variantes se buscan con su grafía registrada para preservar offsets.
        unique_authorities = sorted({candidate[0] for candidate in candidates})
        if len(unique_authorities) != 1:
            ambiguous += 1
            continue
        authority_id = unique_authorities[0]
        surface = display[(authority_id, normalized)]
        for match in re.finditer(re.escape(surface), obj.current_text, flags=re.IGNORECASE):
            before = obj.current_text[match.start() - 1] if match.start() else ""
            after = obj.current_text[match.end()] if match.end() < len(obj.current_text) else ""
            if (before and (before.isalnum() or before == "_")) or (
                after and (after.isalnum() or after == "_")
            ):
                continue
            matches.append((match.start(), match.end(), authority_id, surface))
    # Prioriza menciones largas y evita solapamientos producidos por nombre + alias.
    matches.sort(key=lambda item: (item[0], -(item[1] - item[0]), item[2]))
    occupied: list[tuple[int, int]] = []
    created = 0
    already = 0
    for start, end, authority_id, _surface in matches:
        if any(start < other_end and end > other_start for other_start, other_end in occupied):
            continue
        occupied.append((start, end))
        key = (start, end, obj.revision_number)
        if key in existing:
            already += 1
            continue
        create_mention(
            session,
            object_id=object_id,
            mention_text=obj.current_text[start:end],
            authority_id=authority_id,
            start_offset=start,
            end_offset=end,
            status="pending",
            source="dictionary",
            confidence=1.0,
            created_by=created_by,
            note="Coincidencia con nombre preferido o alias del registro de autoridades",
        )
        existing.add(key)
        created += 1
    return SuggestionSummary(
        created=created,
        already_present=already,
        ambiguous=ambiguous,
        candidates_scanned=len(surfaces),
    )

def suggest_dictionary_mentions_all(
    session: Session,
    *,
    project_id: str,
    created_by: str,
    source_keys: Iterable[str] = (),
    page_review_statuses: Iterable[str] = DEFAULT_AUTOMATIC_PAGE_REVIEW_STATUSES,
    broader_quality_scope_confirmed: bool = False,
    quality_scope_reason: str | None = None,
    quality_scope_source: str = "api",
) -> CorpusSuggestionSummary:
    """Busca nombres y alias conocidos en todos los objetos textuales activos del corpus."""
    selected_sources = tuple(dict.fromkeys(item for item in source_keys if item))
    selected_page_statuses = record_mention_suggestion_authorization(
        session,
        project_id=project_id,
        page_review_statuses=page_review_statuses,
        broader_quality_scope_confirmed=broader_quality_scope_confirmed,
        quality_scope_reason=quality_scope_reason,
        actor=created_by,
        source=quality_scope_source,
        target_type="project",
        target_id=project_id,
        parameters={"mode": "dictionary_corpus", "source_keys": list(selected_sources)},
    )
    statement = (
        select(EditableObject.id)
        .join(DigitalObject, DigitalObject.id == EditableObject.digital_object_id)
        .join(EditablePage, EditablePage.id == EditableObject.editable_page_id)
        .where(
            DigitalObject.project_id == project_id,
            EditableObject.lifecycle_status == "active",
            EditablePage.status == "active",
        )
        .order_by(
            EditableObject.digital_object_id,
            EditableObject.page_number,
            EditableObject.current_order_index,
            EditableObject.id,
        )
    )
    if selected_page_statuses:
        statement = statement.where(
            EditablePage.review_status.in_(selected_page_statuses)
        )
    if selected_sources:
        statement = (
            statement
            .join(
                SourceRegistration,
                SourceRegistration.digital_object_id == DigitalObject.id,
            )
            .where(
                SourceRegistration.source_type.in_(PROCESSABLE_SOURCE_TYPES),
                SourceRegistration.source_key.in_(selected_sources),
            )
        )
    object_ids = list(dict.fromkeys(session.scalars(statement).all()))
    total = CorpusSuggestionSummary(
        objects_scanned=0,
        created=0,
        already_present=0,
        ambiguous=0,
        candidates_scanned=0,
    )
    for object_id in object_ids:
        summary = suggest_dictionary_mentions(
            session,
            object_id=object_id,
            created_by=created_by,
            page_review_statuses=selected_page_statuses,
            broader_quality_scope_confirmed=broader_quality_scope_confirmed,
            quality_scope_reason=quality_scope_reason,
            quality_scope_source=quality_scope_source,
            _authorization_recorded=True,
        )
        total.objects_scanned += 1
        total.created += summary.created
        total.already_present += summary.already_present
        total.ambiguous += summary.ambiguous
        total.candidates_scanned = max(
            total.candidates_scanned, summary.candidates_scanned
        )
    return total



def _candidate_key(
    authority_id: str, object_id: str, object_revision_number: int, start: int, end: int
) -> str:
    raw = f"{authority_id}|{object_id}|{object_revision_number}|{start}|{end}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def _candidate_context(text: str, start: int, end: int, radius: int = 90) -> tuple[str, str]:
    before = text[max(0, start - radius):start]
    after = text[end:min(len(text), end + radius)]
    return before, after


def authority_mention_candidates(
    session: Session,
    *,
    authority_id: str,
    source_keys: Iterable[str] = (),
    include_existing: bool = True,
    page_review_statuses: Iterable[str] = DEFAULT_AUTOMATIC_PAGE_REVIEW_STATUSES,
    broader_quality_scope_confirmed: bool = False,
    quality_scope_reason: str | None = None,
) -> list[MentionCandidateRow]:
    """Encuentra nombres y alias de una entidad en todo el corpus sin modificar la base."""
    authority = session.get(AuthorityRecord, authority_id)
    if authority is None:
        raise ValueError(f"Entidad inexistente: {authority_id}")
    if authority.lifecycle_status != "active":
        raise ValueError("Solo se pueden buscar menciones de entidades activas")

    surfaces: list[tuple[str, str, str | None]] = [
        (authority.preferred_name, "preferred", None)
    ]
    surfaces.extend(
        (row.alias, "alias", row.alias_type) for row in _aliases(session, authority.id)
    )
    deduped: dict[str, tuple[str, str, str | None]] = {}
    for surface, kind, alias_type in surfaces:
        clean = surface.strip()
        normalized = normalize_authority_text(clean)
        if len(normalized) < 2:
            continue
        deduped.setdefault(normalized, (clean, kind, alias_type))
    ordered_surfaces = sorted(
        deduped.values(), key=lambda item: (-len(item[0]), item[0].casefold())
    )

    selected_sources = tuple(dict.fromkeys(item for item in source_keys if item))
    selected_page_statuses = _validated_page_review_statuses(
        page_review_statuses,
        broader_scope_confirmed=broader_quality_scope_confirmed,
        quality_scope_reason=quality_scope_reason,
    )
    statement = (
        select(EditableObject, DigitalObject)
        .join(DigitalObject, DigitalObject.id == EditableObject.digital_object_id)
        .join(EditablePage, EditablePage.id == EditableObject.editable_page_id)
        .where(
            DigitalObject.project_id == authority.project_id,
            EditableObject.lifecycle_status == "active",
            EditablePage.status == "active",
        )
        .order_by(
            EditableObject.digital_object_id,
            EditableObject.page_number,
            EditableObject.current_order_index,
            EditableObject.id,
        )
    )
    if selected_page_statuses:
        statement = statement.where(
            EditablePage.review_status.in_(selected_page_statuses)
        )
    if selected_sources:
        statement = (
            statement.join(
                SourceRegistration,
                SourceRegistration.digital_object_id == DigitalObject.id,
            )
            .where(
                SourceRegistration.source_type.in_(PROCESSABLE_SOURCE_TYPES),
                SourceRegistration.source_key.in_(selected_sources),
            )
        )
    object_pairs: list[tuple[EditableObject, DigitalObject]] = []
    seen_objects: set[str] = set()
    for obj, digital in session.execute(statement).all():
        if obj.id in seen_objects:
            continue
        seen_objects.add(obj.id)
        object_pairs.append((obj, digital))

    digital_ids = sorted({digital.id for _, digital in object_pairs})
    source_map: dict[str, tuple[str | None, str | None]] = {}
    if digital_ids:
        source_rows = session.execute(
            select(SourceRegistration, ArchivalUnit)
            .outerjoin(ArchivalUnit, ArchivalUnit.id == SourceRegistration.archival_unit_id)
            .where(
                SourceRegistration.digital_object_id.in_(digital_ids),
                SourceRegistration.source_type.in_(PROCESSABLE_SOURCE_TYPES),
            )
            .order_by(SourceRegistration.digital_object_id, SourceRegistration.source_key)
        ).all()
        for registration, unit in source_rows:
            source_map.setdefault(
                str(registration.digital_object_id),
                (registration.source_key, unit.title if unit else None),
            )

    object_ids = [obj.id for obj, _ in object_pairs]
    object_map = {obj.id: obj for obj, _ in object_pairs}
    existing_map: dict[
        tuple[str, int, int, int], tuple[EntityMention, str | None]
    ] = {}
    if object_ids:
        existing_rows = session.execute(
            select(EntityMention, AuthorityRecord.preferred_name)
            .outerjoin(AuthorityRecord, AuthorityRecord.id == EntityMention.authority_id)
            .where(
                EntityMention.editable_object_id.in_(object_ids),
                EntityMention.status != "rejected",
            )
            .order_by(
                EntityMention.editable_object_id,
                EntityMention.object_revision_number,
                EntityMention.start_offset,
                EntityMention.end_offset,
                EntityMention.id,
            )
        ).all()
        grouped: dict[
            tuple[str, int, int, int], list[tuple[EntityMention, str | None]]
        ] = {}
        for mention, authority_name in existing_rows:
            obj = object_map.get(mention.editable_object_id)
            if obj is None:
                continue
            projected = project_mention_span_to_current(
                session, mention, editable_object=obj
            )
            if projected is None:
                continue
            key = (
                mention.editable_object_id,
                obj.revision_number,
                projected[0],
                projected[1],
            )
            grouped.setdefault(key, []).append((mention, authority_name))
        for key, rows in grouped.items():
            conflict = next(
                (
                    row
                    for row in rows
                    if row[0].authority_id not in (None, authority.id)
                ),
                None,
            )
            same_authority = next(
                (row for row in rows if row[0].authority_id == authority.id), None
            )
            unlinked = next((row for row in rows if row[0].authority_id is None), None)
            existing_map[key] = conflict or same_authority or unlinked or rows[0]

    candidates: list[MentionCandidateRow] = []
    for obj, digital in object_pairs:
        text = obj.current_text or ""
        occupied: list[tuple[int, int]] = []
        local_matches: list[tuple[int, int, str, str, str | None]] = []
        for surface, kind, alias_type in ordered_surfaces:
            for match in re.finditer(re.escape(surface), text, flags=re.IGNORECASE):
                before_char = text[match.start() - 1] if match.start() else ""
                after_char = text[match.end()] if match.end() < len(text) else ""
                if (before_char and (before_char.isalnum() or before_char == "_")) or (
                    after_char and (after_char.isalnum() or after_char == "_")
                ):
                    continue
                local_matches.append(
                    (match.start(), match.end(), surface, kind, alias_type)
                )
        local_matches.sort(key=lambda item: (item[0], -(item[1] - item[0]), item[2]))
        for start, end, surface, kind, alias_type in local_matches:
            if any(start < other_end and end > other_start for other_start, other_end in occupied):
                continue
            occupied.append((start, end))
            existing_row = existing_map.get((obj.id, obj.revision_number, start, end))
            existing = existing_row[0] if existing_row else None
            existing_authority_name = existing_row[1] if existing_row else None
            if (
                existing is not None
                and existing.authority_id == authority.id
                and not include_existing
            ):
                continue
            context_before, context_after = _candidate_context(text, start, end)
            source_key, title = source_map.get(digital.id, (None, None))
            candidates.append(
                MentionCandidateRow(
                    candidate_key=_candidate_key(
                        authority.id, obj.id, obj.revision_number, start, end
                    ),
                    authority_id=authority.id,
                    authority_name=authority.preferred_name,
                    object_id=obj.id,
                    object_revision_number=obj.revision_number,
                    mention_text=text[start:end],
                    matched_surface=surface,
                    match_kind=kind,
                    alias_type=alias_type,
                    start_offset=start,
                    end_offset=end,
                    context_before=context_before,
                    context_after=context_after,
                    source_key=source_key,
                    document_title=title,
                    page_number=obj.page_number,
                    order_index=obj.current_order_index,
                    existing_mention_id=existing.id if existing else None,
                    existing_authority_id=existing.authority_id if existing else None,
                    existing_authority_name=existing_authority_name,
                    existing_status=existing.status if existing else None,
                )
            )
    return candidates


def include_authority_mention_candidates(
    session: Session,
    *,
    authority_id: str,
    candidate_keys: Sequence[str],
    created_by: str,
    status: str = "pending",
    source_keys: Iterable[str] = (),
    page_review_statuses: Iterable[str] = DEFAULT_AUTOMATIC_PAGE_REVIEW_STATUSES,
    broader_quality_scope_confirmed: bool = False,
    quality_scope_reason: str | None = None,
) -> MentionCandidateImportSummary:
    """Incorpora coincidencias nuevas o vincula menciones existentes sin autoridad."""
    if status not in MENTION_STATUSES:
        raise ValueError(f"Estado de mención inválido: {status}")
    requested_keys = tuple(dict.fromkeys(candidate_keys))
    if not requested_keys:
        return MentionCandidateImportSummary(
            requested=0, created=0, linked_existing=0, already_present=0
        )
    current = {
        row.candidate_key: row
        for row in authority_mention_candidates(
            session,
            authority_id=authority_id,
            source_keys=source_keys,
            include_existing=True,
            page_review_statuses=page_review_statuses,
            broader_quality_scope_confirmed=broader_quality_scope_confirmed,
            quality_scope_reason=quality_scope_reason,
        )
    }
    missing = [key for key in requested_keys if key not in current]
    if missing:
        raise ValueError(
            "Una o más coincidencias ya no corresponden al texto actual; repetí la búsqueda"
        )
    created = 0
    linked = 0
    already = 0
    for key in requested_keys:
        candidate = current[key]
        if candidate.already_included:
            already += 1
            continue
        if candidate.has_authority_conflict:
            raise ValueError(
                f"La coincidencia {candidate.mention_text!r} ya está vinculada a "
                f"{candidate.existing_authority_name or 'otra autoridad'}"
            )
        note = (
            "Coincidencia transversal con nombre preferido"
            if candidate.match_kind == "preferred"
            else f"Coincidencia transversal con alias {candidate.matched_surface!r}"
        )
        if candidate.can_link_existing:
            existing = session.get(EntityMention, candidate.existing_mention_id)
            if existing is None:
                raise ValueError("La mención existente ya no está disponible; repetí la búsqueda")
            update_mention(
                session,
                mention_id=existing.id,
                expected_revision=existing.revision,
                authority_id=authority_id,
                status=status,
                note=note,
                changed_by=created_by,
            )
            linked += 1
            continue
        create_mention(
            session,
            object_id=candidate.object_id,
            mention_text=candidate.mention_text,
            authority_id=authority_id,
            start_offset=candidate.start_offset,
            end_offset=candidate.end_offset,
            status=status,
            source="dictionary",
            confidence=1.0,
            created_by=created_by,
            note=note,
        )
        created += 1
    return MentionCandidateImportSummary(
        requested=len(requested_keys),
        created=created,
        linked_existing=linked,
        already_present=already,
    )
