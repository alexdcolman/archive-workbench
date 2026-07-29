from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import hashlib
import re
import unicodedata
from typing import Iterable, Sequence

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from archive_workbench.db.models import (
    AuthorityAlias,
    AuthorityRecord,
    AuthorityRevision,
    DigitalObject,
    EditableObject,
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


def _active_mention_at_offsets(
    session: Session,
    *,
    object_id: str,
    object_revision_number: int,
    start_offset: int,
    end_offset: int,
    exclude_mention_id: str | None = None,
) -> EntityMention | None:
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
        duplicate = _active_mention_at_offsets(
            session,
            object_id=mention.editable_object_id,
            object_revision_number=mention.object_revision_number,
            start_offset=mention.start_offset,
            end_offset=mention.end_offset,
            exclude_mention_id=mention.id,
        )
        if duplicate is not None:
            raise ValueError(
                "Ya existe otra mención activa sobre el mismo fragmento; "
                "resolvé el duplicado antes de guardar"
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


def suggest_dictionary_mentions(
    session: Session,
    *,
    object_id: str,
    created_by: str,
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
) -> CorpusSuggestionSummary:
    """Busca nombres y alias conocidos en todos los objetos textuales activos del corpus."""
    selected_sources = tuple(dict.fromkeys(item for item in source_keys if item))
    statement = (
        select(EditableObject.id)
        .join(DigitalObject, DigitalObject.id == EditableObject.digital_object_id)
        .where(
            DigitalObject.project_id == project_id,
            EditableObject.lifecycle_status == "active",
        )
        .order_by(
            EditableObject.digital_object_id,
            EditableObject.page_number,
            EditableObject.current_order_index,
            EditableObject.id,
        )
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
            session, object_id=object_id, created_by=created_by
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
    statement = (
        select(EditableObject, DigitalObject)
        .join(DigitalObject, DigitalObject.id == EditableObject.digital_object_id)
        .where(
            DigitalObject.project_id == authority.project_id,
            EditableObject.lifecycle_status == "active",
        )
        .order_by(
            EditableObject.digital_object_id,
            EditableObject.page_number,
            EditableObject.current_order_index,
            EditableObject.id,
        )
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
            if mention.start_offset is None or mention.end_offset is None:
                continue
            key = (
                mention.editable_object_id,
                mention.object_revision_number,
                mention.start_offset,
                mention.end_offset,
            )
            grouped.setdefault(key, []).append((mention, authority_name))
        for key, rows in grouped.items():
            same_authority = next(
                (row for row in rows if row[0].authority_id == authority.id), None
            )
            unlinked = next((row for row in rows if row[0].authority_id is None), None)
            existing_map[key] = same_authority or unlinked or rows[0]

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
