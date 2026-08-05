from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
import re
from typing import Iterable

from sqlalchemy import and_, bindparam, select, text
from sqlalchemy.orm import Session

from archive_workbench.sources import PROCESSABLE_SOURCE_TYPES
from archive_workbench.temporal import temporal_overlap
from archive_workbench.db.models import (
    ArchivalUnit,
    AuthorityAlias,
    AuthorityRecord,
    DigitalObject,
    DocumentPart,
    EditableObject,
    EditableObjectComment,
    EditableObjectTag,
    EditablePage,
    ExtractedObject,
    EntityMention,
    EntityRelation,
    SourceRegistration,
)

SEARCH_FIELDS = ("current_text", "original_text", "comments", "tags", "entities")
MATCH_MODES = ("all", "any", "phrase")


@dataclass(slots=True)
class SearchIndexStatus:
    dirty_generation: int
    indexed_generation: int
    indexed_at: str | None

    @property
    def is_current(self) -> bool:
        return self.dirty_generation == self.indexed_generation


@dataclass(slots=True)
class SearchIndexSummary:
    object_count: int
    dirty_generation: int
    indexed_generation: int
    indexed_at: str


@dataclass(slots=True)
class SearchResultRow:
    object_id: str
    source_key: str
    document_title: str
    page_number: int
    order_index: int
    object_type: str
    object_review_status: str
    page_review_status: str
    lifecycle_status: str
    document_part_key: str | None
    document_part_title: str | None
    snippet: str
    match_scope: str
    rank: float


def search_index_status(session: Session) -> SearchIndexStatus:
    row = session.execute(
        text(
            "SELECT dirty_generation, indexed_generation, indexed_at "
            "FROM editable_search_state WHERE id = 1"
        )
    ).one_or_none()
    if row is None:
        raise RuntimeError("El índice de búsqueda no existe. Ejecutá db-upgrade.")
    return SearchIndexStatus(
        dirty_generation=int(row.dirty_generation),
        indexed_generation=int(row.indexed_generation),
        indexed_at=row.indexed_at,
    )


def _group_annotations(
    session: Session, object_ids: list[str]
) -> tuple[dict[str, list[str]], dict[str, dict[str, list[str]]]]:
    comments: dict[str, list[str]] = {object_id: [] for object_id in object_ids}
    tags: dict[str, dict[str, list[str]]] = {
        object_id: {
            "thematic": [],
            "conceptual": [],
            "workflow": [],
            "unclassified": [],
        }
        for object_id in object_ids
    }
    if not object_ids:
        return comments, tags
    for object_id, body in session.execute(
        select(EditableObjectComment.editable_object_id, EditableObjectComment.body)
        .where(EditableObjectComment.editable_object_id.in_(object_ids))
        .order_by(EditableObjectComment.created_at, EditableObjectComment.id)
    ).all():
        comments.setdefault(object_id, []).append(body)
    for object_id, tag_kind, tag in session.execute(
        select(
            EditableObjectTag.editable_object_id,
            EditableObjectTag.tag_kind,
            EditableObjectTag.tag,
        )
        .where(EditableObjectTag.editable_object_id.in_(object_ids))
        .order_by(EditableObjectTag.tag_kind, EditableObjectTag.normalized_tag)
    ).all():
        tags.setdefault(object_id, {}).setdefault(tag_kind, []).append(tag)
    return comments, tags



def _group_entities(
    session: Session, object_ids: list[str]
) -> dict[str, dict[str, list[str]]]:
    grouped: dict[str, dict[str, list[str]]] = {
        object_id: {"names": [], "aliases": [], "mentions": [], "relations": []}
        for object_id in object_ids
    }
    if not object_ids:
        return grouped
    rows = session.execute(
        select(EntityMention, AuthorityRecord)
        .outerjoin(AuthorityRecord, AuthorityRecord.id == EntityMention.authority_id)
        .where(
            EntityMention.editable_object_id.in_(object_ids),
            EntityMention.status != "rejected",
        )
        .order_by(
            EntityMention.editable_object_id,
            EntityMention.start_offset,
            EntityMention.id,
        )
    ).all()
    authority_ids = sorted({authority.id for _mention, authority in rows if authority is not None})
    aliases_by: dict[str, list[str]] = {authority_id: [] for authority_id in authority_ids}
    if authority_ids:
        for authority_id, alias in session.execute(
            select(AuthorityAlias.authority_id, AuthorityAlias.alias)
            .where(AuthorityAlias.authority_id.in_(authority_ids))
            .order_by(AuthorityAlias.authority_id, AuthorityAlias.normalized_alias)
        ).all():
            aliases_by.setdefault(authority_id, []).append(alias)
    for mention, authority in rows:
        bucket = grouped.setdefault(
            mention.editable_object_id,
            {"names": [], "aliases": [], "mentions": [], "relations": []},
        )
        bucket["mentions"].append(mention.mention_text)
        if authority is not None:
            bucket["names"].append(authority.preferred_name)
            bucket["aliases"].extend(aliases_by.get(authority.id, []))
    authority_to_objects: dict[str, set[str]] = {}
    for mention, authority in rows:
        if authority is not None:
            authority_to_objects.setdefault(authority.id, set()).add(mention.editable_object_id)
    if authority_to_objects:
        related_ids = sorted(authority_to_objects)
        relations = session.scalars(
            select(EntityRelation).where(
                EntityRelation.lifecycle_status == "active",
                (EntityRelation.source_authority_id.in_(related_ids))
                | (EntityRelation.target_authority_id.in_(related_ids)),
            )
        ).all()
        relation_authority_ids = {
            relation.source_authority_id for relation in relations
        } | {
            relation.target_authority_id
            for relation in relations
            if relation.target_authority_id is not None
        }
        relation_authorities = {
            authority.id: authority.preferred_name
            for authority in session.scalars(
                select(AuthorityRecord).where(AuthorityRecord.id.in_(relation_authority_ids))
            ).all()
        }
        unit_ids = {
            relation.target_archival_unit_id
            for relation in relations
            if relation.target_archival_unit_id is not None
        }
        units = {
            unit.id: unit.title
            for unit in session.scalars(select(ArchivalUnit).where(ArchivalUnit.id.in_(unit_ids))).all()
        } if unit_ids else {}
        part_ids = {
            relation.target_document_part_id
            for relation in relations
            if relation.target_document_part_id is not None
        }
        parts = {
            part.id: part.title
            for part in session.scalars(select(DocumentPart).where(DocumentPart.id.in_(part_ids))).all()
        } if part_ids else {}
        for relation in relations:
            source_name = relation_authorities.get(relation.source_authority_id, "Entidad")
            if relation.target_authority_id is not None:
                target_name = relation_authorities.get(relation.target_authority_id, "Entidad")
            elif relation.target_archival_unit_id is not None:
                target_name = units.get(relation.target_archival_unit_id, "Unidad archivística")
            else:
                target_name = parts.get(relation.target_document_part_id, "Parte interna")
            relation_class = {
                "producer": "entidad productora",
                "manager": "entidad gestora",
            }.get(relation.relation_kind, "relación analítica")
            text_value = (
                f"{source_name} — {relation.relation_label} → {target_name} "
                f"[{relation_class}]"
            )
            if relation.provenance_note:
                text_value += f" · {relation.provenance_note}"
            participating = {relation.source_authority_id}
            if relation.target_authority_id is not None:
                participating.add(relation.target_authority_id)
            for authority_id in participating:
                for object_id in authority_to_objects.get(authority_id, set()):
                    grouped.setdefault(
                        object_id,
                        {"names": [], "aliases": [], "mentions": [], "relations": []},
                    )["relations"].append(text_value)
    for bucket in grouped.values():
        for key in bucket:
            bucket[key] = list(dict.fromkeys(bucket[key]))
    return grouped

def rebuild_search_index(session: Session) -> SearchIndexSummary:
    status = search_index_status(session)
    rows = session.execute(
        select(
            EditableObject,
            EditablePage,
            SourceRegistration,
            ArchivalUnit,
            DocumentPart,
            ExtractedObject,
        )
        .join(EditablePage, EditableObject.editable_page_id == EditablePage.id)
        .join(DigitalObject, EditableObject.digital_object_id == DigitalObject.id)
        .join(
            SourceRegistration,
            and_(
                SourceRegistration.digital_object_id == DigitalObject.id,
                SourceRegistration.source_type.in_(PROCESSABLE_SOURCE_TYPES),
            ),
        )
        .join(ArchivalUnit, SourceRegistration.archival_unit_id == ArchivalUnit.id)
        .outerjoin(DocumentPart, EditableObject.document_part_id == DocumentPart.id)
        .outerjoin(ExtractedObject, EditableObject.source_extracted_object_id == ExtractedObject.id)
        .order_by(
            SourceRegistration.source_key,
            EditableObject.page_number,
            EditableObject.current_order_index,
            EditableObject.id,
        )
    ).all()
    object_ids = [item[0].id for item in rows]
    comments, tags = _group_annotations(session, object_ids)
    entities = _group_entities(session, object_ids)
    session.execute(text("DELETE FROM editable_search_fts"))
    session.execute(text("DELETE FROM editable_search_trigram_fts"))
    payload: list[dict[str, object]] = []
    for editable, page, registration, unit, part, original in rows:
        object_tags = tags.get(editable.id, {})
        thematic = "\n".join(object_tags.get("thematic", []))
        conceptual = "\n".join(object_tags.get("conceptual", []))
        workflow = "\n".join(object_tags.get("workflow", []))
        unclassified = "\n".join(object_tags.get("unclassified", []))
        payload.append(
            {
                "object_id": editable.id,
                "source_key": registration.source_key,
                "document_title": unit.title,
                "page_number": editable.page_number,
                "order_index": editable.current_order_index,
                "object_type": editable.current_object_type,
                "object_review_status": editable.review_status,
                "page_review_status": page.review_status,
                "lifecycle_status": editable.lifecycle_status,
                "document_part_key": part.part_key if part is not None else "",
                "document_part_title": part.title if part is not None else "",
                "current_text": editable.current_text or "",
                "original_text": original.original_text if original is not None else "",
                "comments": "\n".join(comments.get(editable.id, [])),
                "thematic_tags": thematic,
                "conceptual_tags": conceptual,
                "workflow_tags": workflow,
                "unclassified_tags": unclassified,
                "all_tags": "\n".join(
                    value for value in (thematic, conceptual, workflow, unclassified) if value
                ),
                "authority_names": "\n".join(entities.get(editable.id, {}).get("names", [])),
                "authority_aliases": "\n".join(entities.get(editable.id, {}).get("aliases", [])),
                "mention_texts": "\n".join(entities.get(editable.id, {}).get("mentions", [])),
                "relation_texts": "\n".join(entities.get(editable.id, {}).get("relations", [])),
            }
        )
    if payload:
        insert_sql = """
            INSERT INTO {table} (
                object_id, source_key, document_title, page_number, order_index,
                object_type, object_review_status, page_review_status, lifecycle_status,
                document_part_key, document_part_title, current_text, original_text,
                comments, thematic_tags, conceptual_tags, workflow_tags,
                unclassified_tags, all_tags, authority_names, authority_aliases,
                mention_texts, relation_texts
            ) VALUES (
                :object_id, :source_key, :document_title, :page_number, :order_index,
                :object_type, :object_review_status, :page_review_status, :lifecycle_status,
                :document_part_key, :document_part_title, :current_text, :original_text,
                :comments, :thematic_tags, :conceptual_tags, :workflow_tags,
                :unclassified_tags, :all_tags, :authority_names, :authority_aliases,
                :mention_texts, :relation_texts
            )
        """
        for table in ("editable_search_fts", "editable_search_trigram_fts"):
            session.execute(text(insert_sql.format(table=table)), payload)
    indexed_at = datetime.now(timezone.utc).isoformat()
    session.execute(
        text(
            "UPDATE editable_search_state "
            "SET indexed_generation = dirty_generation, indexed_at = :indexed_at WHERE id = 1"
        ),
        {"indexed_at": indexed_at},
    )
    updated = search_index_status(session)
    return SearchIndexSummary(
        object_count=len(payload),
        dirty_generation=updated.dirty_generation,
        indexed_generation=updated.indexed_generation,
        indexed_at=indexed_at,
    )


def ensure_search_index(session: Session) -> SearchIndexStatus:
    status = search_index_status(session)
    if not status.is_current:
        rebuild_search_index(session)
        status = search_index_status(session)
    return status


def _quote_fts(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _terms(query: str) -> list[str]:
    return [item for item in re.findall(r"[\wÀ-ÖØ-öø-ÿ'-]+", query, flags=re.UNICODE) if item]


def build_match_expression(
    query: str,
    *,
    fields: Iterable[str] = SEARCH_FIELDS,
    match_mode: str = "all",
) -> str:
    query = query.strip()
    if not query:
        raise ValueError("La consulta de búsqueda está vacía")
    if match_mode not in MATCH_MODES:
        raise ValueError(f"Modo de búsqueda inválido: {match_mode}")
    columns = _search_columns(fields)

    def across_columns(value: str) -> str:
        phrase = _quote_fts(value)
        return "(" + " OR ".join(f"{column}:{phrase}" for column in columns) + ")"

    if match_mode == "phrase":
        return across_columns(query)
    terms = _terms(query)
    if not terms:
        return across_columns(query)
    joiner = " AND " if match_mode == "all" else " OR "
    return joiner.join(across_columns(term) for term in terms)


def _search_columns(fields: Iterable[str]) -> list[str]:
    selected = tuple(dict.fromkeys(fields))
    if not selected:
        raise ValueError("Seleccioná al menos un campo de búsqueda")
    invalid = sorted(set(selected) - set(SEARCH_FIELDS))
    if invalid:
        raise ValueError("Campos de búsqueda inválidos: " + ", ".join(invalid))
    columns: list[str] = []
    for field in selected:
        if field == "tags":
            columns.append("all_tags")
        elif field == "entities":
            columns.extend(("authority_names", "authority_aliases", "mention_texts", "relation_texts"))
        else:
            columns.append(field)
    return list(dict.fromkeys(columns))


def _partial_highlight(value: str, needles: list[str], *, window: int = 220) -> str:
    if not value:
        return ""
    lower = value.casefold()
    positions = [(lower.find(needle.casefold()), needle) for needle in needles if needle]
    positions = [(position, needle) for position, needle in positions if position >= 0]
    if not positions:
        return ""
    first = min(position for position, _needle in positions)
    start = max(0, first - window // 3)
    end = min(len(value), start + window)
    fragment = value[start:end]
    for needle in sorted(set(needles), key=len, reverse=True):
        fragment = re.sub(
            re.escape(needle),
            lambda match: f"[[HIT]]{match.group(0)}[[/HIT]]",
            fragment,
            flags=re.IGNORECASE,
        )
    if start:
        fragment = "… " + fragment
    if end < len(value):
        fragment += " …"
    return fragment


def _expanding_clause(
    clauses: list[str], params: dict[str, object], name: str, column: str, values: Iterable[str]
) -> None:
    values = tuple(dict.fromkeys(values))
    if values:
        clauses.append(f"{column} IN :{name}")
        params[name] = values


def object_ids_matching_temporal(
    session: Session,
    *,
    object_ids: Iterable[str],
    temporal_start: date | None,
    temporal_end: date | None,
    include_undated: bool = False,
) -> set[str]:
    """Devuelve objetos vinculados con entidades o relaciones que se superponen al período."""
    selected = tuple(dict.fromkeys(str(value) for value in object_ids if value))
    if temporal_start is None and temporal_end is None:
        return set(selected)
    if temporal_start is not None and temporal_end is not None and temporal_start > temporal_end:
        raise ValueError("El inicio del filtro temporal es posterior al final")
    if not selected:
        return set()

    mention_rows = session.execute(
        select(EntityMention.editable_object_id, AuthorityRecord)
        .join(AuthorityRecord, AuthorityRecord.id == EntityMention.authority_id)
        .where(
            EntityMention.editable_object_id.in_(selected),
            EntityMention.status != "rejected",
        )
    ).all()
    authority_to_objects: dict[str, set[str]] = {}
    matched: set[str] = set()
    for object_id, authority in mention_rows:
        authority_to_objects.setdefault(authority.id, set()).add(object_id)
        if temporal_overlap(
            item_start=authority.temporal_start,
            item_end=authority.temporal_end,
            query_start=temporal_start,
            query_end=temporal_end,
            include_undated=include_undated,
        ):
            matched.add(object_id)

    authority_ids = tuple(authority_to_objects)
    if authority_ids:
        relations = session.scalars(
            select(EntityRelation).where(
                EntityRelation.lifecycle_status == "active",
                (EntityRelation.source_authority_id.in_(authority_ids))
                | (EntityRelation.target_authority_id.in_(authority_ids)),
            )
        ).all()
        for relation in relations:
            if not temporal_overlap(
                item_start=relation.temporal_start,
                item_end=relation.temporal_end,
                query_start=temporal_start,
                query_end=temporal_end,
                include_undated=include_undated,
            ):
                continue
            matched.update(authority_to_objects.get(relation.source_authority_id, set()))
            if relation.target_authority_id:
                matched.update(authority_to_objects.get(relation.target_authority_id, set()))
    return matched


def search_editable_objects(
    session: Session,
    *,
    query: str,
    match_mode: str = "all",
    fields: Iterable[str] = SEARCH_FIELDS,
    source_keys: Iterable[str] = (),
    object_types: Iterable[str] = (),
    object_review_statuses: Iterable[str] = (),
    page_review_statuses: Iterable[str] = (),
    lifecycle_statuses: Iterable[str] = ("active",),
    document_part_keys: Iterable[str] = (),
    tag_kinds: Iterable[str] = (),
    temporal_start: date | None = None,
    temporal_end: date | None = None,
    temporal_include_undated: bool = False,
    partial_words: bool = False,
    limit: int = 50,
) -> list[SearchResultRow]:
    if not 1 <= limit <= 500:
        raise ValueError("limit debe estar entre 1 y 500")
    if temporal_start and temporal_end and temporal_start > temporal_end:
        raise ValueError("El inicio del filtro temporal es posterior al final")
    ensure_search_index(session)
    selected_columns = _search_columns(fields)
    fragments = _terms(query)
    if partial_words:
        too_short = [item for item in fragments if len(item) < 3]
        if too_short:
            raise ValueError(
                "La búsqueda por fragmentos requiere al menos 3 caracteres por término: "
                + ", ".join(too_short)
            )
        if not fragments:
            raise ValueError("La consulta de búsqueda está vacía")
    table = "editable_search_trigram_fts" if partial_words else "editable_search_fts"
    clauses: list[str] = []
    params: dict[str, object] = {"limit": limit}
    if partial_words:
        terms_for_match = [query.strip()] if match_mode == "phrase" else fragments
        term_clauses: list[str] = []
        for index, fragment in enumerate(terms_for_match):
            key = f"fragment_{index}"
            params[key] = f"%{fragment}%"
            term_clauses.append(
                "(" + " OR ".join(f"{column} LIKE :{key}" for column in selected_columns) + ")"
            )
        joiner = " AND " if match_mode in {"all", "phrase"} else " OR "
        clauses.append("(" + joiner.join(term_clauses) + ")")
    else:
        params["match"] = build_match_expression(query, fields=fields, match_mode=match_mode)
        clauses.append(f"{table} MATCH :match")
    expanding: list[str] = []
    filters = (
        ("source_keys", "source_key", source_keys),
        ("object_types", "object_type", object_types),
        ("object_review_statuses", "object_review_status", object_review_statuses),
        ("page_review_statuses", "page_review_status", page_review_statuses),
        ("lifecycle_statuses", "lifecycle_status", lifecycle_statuses),
        ("document_part_keys", "document_part_key", document_part_keys),
    )
    for name, column, values in filters:
        before = len(clauses)
        _expanding_clause(clauses, params, name, column, values)
        if len(clauses) > before:
            expanding.append(name)
    kind_columns = {
        "thematic": "thematic_tags",
        "conceptual": "conceptual_tags",
        "workflow": "workflow_tags",
        "unclassified": "unclassified_tags",
    }
    selected_kinds = tuple(dict.fromkeys(tag_kinds))
    invalid_kinds = sorted(set(selected_kinds) - set(kind_columns))
    if invalid_kinds:
        raise ValueError("Categorías de etiqueta inválidas: " + ", ".join(invalid_kinds))
    if selected_kinds:
        clauses.append(
            "(" + " OR ".join(f"{kind_columns[kind]} <> ''" for kind in selected_kinds) + ")"
        )
    if temporal_start is not None or temporal_end is not None:
        params["temporal_start"] = temporal_start.isoformat() if temporal_start else None
        params["temporal_end"] = temporal_end.isoformat() if temporal_end else None
        dated_authority = "" if temporal_include_undated else (
            "AND (ar.temporal_start IS NOT NULL OR ar.temporal_end IS NOT NULL) "
        )
        dated_relation = "" if temporal_include_undated else (
            "AND (er.temporal_start IS NOT NULL OR er.temporal_end IS NOT NULL) "
        )
        clauses.append(
            f"""(
                EXISTS (
                    SELECT 1
                    FROM entity_mentions em
                    JOIN authority_records ar ON ar.id = em.authority_id
                    WHERE em.editable_object_id = {table}.object_id
                      AND em.status <> 'rejected'
                      {dated_authority}
                      AND (:temporal_start IS NULL OR ar.temporal_end IS NULL OR ar.temporal_end >= :temporal_start)
                      AND (:temporal_end IS NULL OR ar.temporal_start IS NULL OR ar.temporal_start <= :temporal_end)
                )
                OR EXISTS (
                    SELECT 1
                    FROM entity_mentions em
                    JOIN entity_relations er
                      ON er.source_authority_id = em.authority_id
                      OR er.target_authority_id = em.authority_id
                    WHERE em.editable_object_id = {table}.object_id
                      AND em.status <> 'rejected'
                      AND er.lifecycle_status = 'active'
                      {dated_relation}
                      AND (:temporal_start IS NULL OR er.temporal_end IS NULL OR er.temporal_end >= :temporal_start)
                      AND (:temporal_end IS NULL OR er.temporal_start IS NULL OR er.temporal_start <= :temporal_end)
                )
            )"""
        )
    if partial_words:
        statement = text(
            f"""
            SELECT
                object_id, source_key, document_title, page_number, order_index,
                object_type, object_review_status, page_review_status, lifecycle_status,
                NULLIF(document_part_key, '') AS document_part_key,
                NULLIF(document_part_title, '') AS document_part_title,
                current_text, original_text, comments, all_tags,
                authority_names, authority_aliases, mention_texts, relation_texts,
                0.0 AS rank
            FROM {table}
            WHERE {' AND '.join(clauses)}
            ORDER BY source_key, CAST(page_number AS INTEGER), CAST(order_index AS INTEGER)
            LIMIT :limit
            """
        )
    else:
        statement = text(
            f"""
            SELECT
                object_id, source_key, document_title, page_number, order_index,
                object_type, object_review_status, page_review_status, lifecycle_status,
                NULLIF(document_part_key, '') AS document_part_key,
                NULLIF(document_part_title, '') AS document_part_title,
                snippet({table}, 11, '[[HIT]]', '[[/HIT]]', ' … ', 24) AS current_snippet,
                snippet({table}, 12, '[[HIT]]', '[[/HIT]]', ' … ', 24) AS original_snippet,
                snippet({table}, 13, '[[HIT]]', '[[/HIT]]', ' … ', 24) AS comment_snippet,
                snippet({table}, 18, '[[HIT]]', '[[/HIT]]', ' … ', 24) AS tag_snippet,
                snippet({table}, 19, '[[HIT]]', '[[/HIT]]', ' … ', 24) AS authority_name_snippet,
                snippet({table}, 20, '[[HIT]]', '[[/HIT]]', ' … ', 24) AS authority_alias_snippet,
                snippet({table}, 21, '[[HIT]]', '[[/HIT]]', ' … ', 24) AS mention_snippet,
                snippet({table}, 22, '[[HIT]]', '[[/HIT]]', ' … ', 24) AS relation_snippet,
                bm25({table}) AS rank
            FROM {table}
            WHERE {' AND '.join(clauses)}
            ORDER BY rank, source_key, CAST(page_number AS INTEGER), CAST(order_index AS INTEGER)
            LIMIT :limit
            """
        )
    for name in expanding:
        statement = statement.bindparams(bindparam(name, expanding=True))
    rows = session.execute(statement, params).mappings().all()
    result: list[SearchResultRow] = []
    scopes = (
        ("Texto revisado", "current_snippet", "current_text"),
        ("OCR original", "original_snippet", "original_text"),
        ("Comentario", "comment_snippet", "comments"),
        ("Etiqueta", "tag_snippet", "all_tags"),
        ("Nombre de entidad", "authority_name_snippet", "authority_names"),
        ("Alias de entidad", "authority_alias_snippet", "authority_aliases"),
        ("Mención de entidad", "mention_snippet", "mention_texts"),
        ("Relación analítica", "relation_snippet", "relation_texts"),
    )
    highlight_terms = [query.strip()] if match_mode == "phrase" else fragments
    for row in rows:
        match_scope = "Texto revisado"
        snippet = ""
        if partial_words:
            for label, _snippet_key, raw_key in scopes:
                if raw_key not in selected_columns:
                    continue
                candidate = _partial_highlight(str(row[raw_key] or ""), highlight_terms)
                if candidate:
                    match_scope = label
                    snippet = candidate
                    break
        else:
            snippet = str(row["current_snippet"] or "")
            for label, snippet_key, _raw_key in scopes:
                candidate = str(row[snippet_key] or "")
                if "[[HIT]]" in candidate:
                    match_scope = label
                    snippet = candidate
                    break
        if not snippet:
            snippet = "[sin fragmento disponible]"
        result.append(
            SearchResultRow(
                object_id=str(row["object_id"]),
                source_key=str(row["source_key"]),
                document_title=str(row["document_title"]),
                page_number=int(row["page_number"]),
                order_index=int(row["order_index"]),
                object_type=str(row["object_type"]),
                object_review_status=str(row["object_review_status"]),
                page_review_status=str(row["page_review_status"]),
                lifecycle_status=str(row["lifecycle_status"]),
                document_part_key=row["document_part_key"],
                document_part_title=row["document_part_title"],
                snippet=snippet,
                match_scope=match_scope,
                rank=float(row["rank"]),
            )
        )
    return result
