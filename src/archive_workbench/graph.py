from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import asdict, dataclass
import csv
from datetime import date
import hashlib
import json
import math
from pathlib import Path
import re
import unicodedata
from xml.etree import ElementTree as ET

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from archive_workbench.db.models import (
    ArchivalUnit,
    AuthorityRecord,
    DigitalObject,
    DocumentPart,
    EditableObject,
    EntityMention,
    EntityRelation,
    SourceRegistration,
)
from archive_workbench.sources import PROCESSABLE_SOURCE_TYPES
from archive_workbench.temporal import format_temporal_range, temporal_overlap

GRAPH_EDGE_TYPES = ("explicit", "mention", "shared_entity")
GRAPH_NODE_KINDS = ("entity", "archival_unit", "document_part")


@dataclass(slots=True)
class GraphNode:
    node_id: str
    kind: str
    record_id: str
    label: str
    context: str | None
    subtype: str | None
    review_status: str | None
    lifecycle_status: str | None
    temporal_expression: str | None = None
    temporal_start: date | None = None
    temporal_end: date | None = None
    temporal_approximate: bool = False
    degree: int = 0
    source_key: str | None = None
    page_number: int | None = None
    object_id: str | None = None


@dataclass(slots=True)
class GraphEdge:
    edge_id: str
    source: str
    target: str
    edge_type: str
    label: str
    explanation: str
    weight: int = 1
    relation_id: str | None = None
    review_status: str | None = None
    lifecycle_status: str | None = None
    evidence_note: str | None = None
    temporal_expression: str | None = None
    temporal_start: date | None = None
    temporal_end: date | None = None
    temporal_approximate: bool = False
    authority_ids: tuple[str, ...] = ()
    source_key: str | None = None
    page_number: int | None = None
    object_id: str | None = None


@dataclass(slots=True)
class GraphView:
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    truncated: bool
    total_nodes_before_limit: int
    total_edges_before_limit: int


@dataclass(slots=True)
class GraphConsistencyIssue:
    code: str
    severity: str
    message: str
    relation_id: str | None = None
    mention_id: str | None = None
    entity_id: str | None = None


def _node_id(kind: str, record_id: str) -> str:
    return f"{kind}:{record_id}"


def _normalized(value: str) -> str:
    text = unicodedata.normalize("NFKC", value).casefold()
    return re.sub(r"\s+", " ", text).strip()


def _edge_id(prefix: str, *parts: str) -> str:
    payload = "\x1f".join(parts).encode("utf-8")
    return f"{prefix}:{hashlib.sha256(payload).hexdigest()[:20]}"


def _source_registrations(session: Session, project_id: str) -> dict[str, SourceRegistration]:
    rows = session.scalars(
        select(SourceRegistration)
        .where(
            SourceRegistration.project_id == project_id,
            SourceRegistration.source_type.in_(PROCESSABLE_SOURCE_TYPES),
            SourceRegistration.digital_object_id.is_not(None),
        )
        .order_by(SourceRegistration.registered_at, SourceRegistration.id)
    ).all()
    result: dict[str, SourceRegistration] = {}
    for row in rows:
        if row.digital_object_id is not None:
            result.setdefault(row.digital_object_id, row)
    return result


def _document_target_for_object(
    editable: EditableObject,
    *,
    part_by_id: dict[str, DocumentPart],
    registration_by_digital: dict[str, SourceRegistration],
) -> tuple[str, str, str, str | None, int | None] | None:
    if editable.document_part_id and editable.document_part_id in part_by_id:
        part = part_by_id[editable.document_part_id]
        registration = registration_by_digital.get(editable.digital_object_id)
        return (
            "document_part",
            part.id,
            part.title,
            registration.source_key if registration else None,
            editable.page_number,
        )
    registration = registration_by_digital.get(editable.digital_object_id)
    if registration is None or registration.archival_unit_id is None:
        return None
    return (
        "archival_unit",
        registration.archival_unit_id,
        "",
        registration.source_key,
        editable.page_number,
    )


def build_graph(
    session: Session,
    *,
    project_id: str,
    edge_types: tuple[str, ...] = GRAPH_EDGE_TYPES,
    entity_types: tuple[str, ...] = (),
    review_statuses: tuple[str, ...] = (),
    include_inactive: bool = False,
    include_pending_mentions: bool = False,
    temporal_start: date | None = None,
    temporal_end: date | None = None,
    temporal_include_undated: bool = False,
    min_shared_entities: int = 1,
    focus_node_id: str | None = None,
    max_depth: int | None = None,
    max_nodes: int = 180,
) -> GraphView:
    invalid = sorted(set(edge_types) - set(GRAPH_EDGE_TYPES))
    if invalid:
        raise ValueError(f"Tipos de arista inválidos: {', '.join(invalid)}")
    if temporal_start is not None and temporal_end is not None and temporal_start > temporal_end:
        raise ValueError("El inicio del filtro temporal es posterior al final")
    if min_shared_entities < 1:
        raise ValueError("min_shared_entities debe ser al menos 1")
    if max_nodes < 2:
        raise ValueError("max_nodes debe ser al menos 2")

    authority_stmt = select(AuthorityRecord).where(AuthorityRecord.project_id == project_id)
    if not include_inactive:
        authority_stmt = authority_stmt.where(AuthorityRecord.lifecycle_status == "active")
    if entity_types:
        authority_stmt = authority_stmt.where(AuthorityRecord.entity_type.in_(entity_types))
    authorities = session.scalars(
        authority_stmt.order_by(AuthorityRecord.normalized_name, AuthorityRecord.id)
    ).all()
    all_authority_by_id = {row.id: row for row in authorities}

    relations_stmt = select(EntityRelation).where(EntityRelation.project_id == project_id)
    if not include_inactive:
        relations_stmt = relations_stmt.where(EntityRelation.lifecycle_status == "active")
    if review_statuses:
        relations_stmt = relations_stmt.where(EntityRelation.review_status.in_(review_statuses))
    relations = session.scalars(
        relations_stmt.order_by(EntityRelation.created_at, EntityRelation.id)
    ).all()
    temporal_filter_active = temporal_start is not None or temporal_end is not None
    if temporal_filter_active:
        relations = [
            row for row in relations
            if temporal_overlap(
                item_start=row.temporal_start,
                item_end=row.temporal_end,
                query_start=temporal_start,
                query_end=temporal_end,
                include_undated=temporal_include_undated,
            )
        ]
        relation_authority_ids = {
            item
            for row in relations
            for item in (row.source_authority_id, row.target_authority_id)
            if item is not None
        }
        authorities = [
            row for row in authorities
            if row.id in relation_authority_ids
            or temporal_overlap(
                item_start=row.temporal_start,
                item_end=row.temporal_end,
                query_start=temporal_start,
                query_end=temporal_end,
                include_undated=temporal_include_undated,
            )
        ]
    authority_by_id = {row.id: row for row in authorities}

    target_unit_ids = {
        row.target_archival_unit_id for row in relations if row.target_archival_unit_id is not None
    }
    target_part_ids = {
        row.target_document_part_id for row in relations if row.target_document_part_id is not None
    }
    units = {
        row.id: row
        for row in session.scalars(
            select(ArchivalUnit).where(
                ArchivalUnit.project_id == project_id,
                ArchivalUnit.id.in_(target_unit_ids) if target_unit_ids else False,
            )
        ).all()
    } if target_unit_ids else {}
    parts = {
        row.id: row
        for row in session.scalars(
            select(DocumentPart).where(DocumentPart.id.in_(target_part_ids))
        ).all()
    } if target_part_ids else {}

    registration_by_digital = _source_registrations(session, project_id)
    part_by_id = {
        row.id: row
        for row in session.scalars(
            select(DocumentPart)
            .join(DigitalObject, DigitalObject.id == DocumentPart.digital_object_id)
            .where(DigitalObject.project_id == project_id)
        ).all()
    }
    unit_ids_from_reg = {
        row.archival_unit_id
        for row in registration_by_digital.values()
        if row.archival_unit_id is not None
    }
    if unit_ids_from_reg:
        for row in session.scalars(
            select(ArchivalUnit).where(ArchivalUnit.id.in_(unit_ids_from_reg))
        ).all():
            units.setdefault(row.id, row)

    nodes: dict[str, GraphNode] = {}
    edges: dict[str, GraphEdge] = {}

    def add_entity(authority_id: str) -> str | None:
        authority = authority_by_id.get(authority_id)
        if authority is None:
            return None
        key = _node_id("entity", authority.id)
        nodes.setdefault(
            key,
            GraphNode(
                node_id=key,
                kind="entity",
                record_id=authority.id,
                label=authority.preferred_name,
                context=authority.description,
                subtype=authority.entity_type,
                review_status=authority.review_status,
                lifecycle_status=authority.lifecycle_status,
                temporal_expression=authority.temporal_expression,
                temporal_start=authority.temporal_start,
                temporal_end=authority.temporal_end,
                temporal_approximate=bool(authority.temporal_approximate),
            ),
        )
        return key

    def add_unit(unit_id: str) -> str | None:
        unit = units.get(unit_id)
        if unit is None:
            unit = session.get(ArchivalUnit, unit_id)
            if unit is None or unit.project_id != project_id:
                return None
            units[unit.id] = unit
        key = _node_id("archival_unit", unit.id)
        nodes.setdefault(
            key,
            GraphNode(
                node_id=key,
                kind="archival_unit",
                record_id=unit.id,
                label=unit.title,
                context=unit.reference_code,
                subtype=unit.level_key,
                review_status=unit.registration_status,
                lifecycle_status="active",
            ),
        )
        return key

    def add_part(part_id: str, *, source_key: str | None = None, page: int | None = None) -> str | None:
        part = part_by_id.get(part_id) or parts.get(part_id)
        if part is None:
            return None
        registration = registration_by_digital.get(part.digital_object_id)
        key = _node_id("document_part", part.id)
        nodes.setdefault(
            key,
            GraphNode(
                node_id=key,
                kind="document_part",
                record_id=part.id,
                label=part.title,
                context=f"págs. {part.page_start}-{part.page_end}",
                subtype=part.part_type,
                review_status=part.status,
                lifecycle_status="active",
                source_key=source_key or (registration.source_key if registration else None),
                page_number=page or part.page_start,
            ),
        )
        return key

    if "explicit" in edge_types:
        for relation in relations:
            source_key = add_entity(relation.source_authority_id)
            if source_key is None:
                continue
            if relation.target_authority_id is not None:
                target_key = add_entity(relation.target_authority_id)
                target_kind = "entity"
            elif relation.target_archival_unit_id is not None:
                target_key = add_unit(relation.target_archival_unit_id)
                target_kind = "archival_unit"
            elif relation.target_document_part_id is not None:
                target_key = add_part(relation.target_document_part_id)
                target_kind = "document_part"
            else:
                target_key = None
                target_kind = "unknown"
            if target_key is None:
                continue
            edges[relation.id] = GraphEdge(
                edge_id=relation.id,
                source=source_key,
                target=target_key,
                edge_type="explicit",
                label=relation.relation_label,
                explanation=(
                    "Relación analítica explícita registrada por el equipo entre una entidad "
                    f"y un destino de tipo {target_kind}."
                ),
                relation_id=relation.id,
                review_status=relation.review_status,
                lifecycle_status=relation.lifecycle_status,
                evidence_note=relation.evidence_note,
                temporal_expression=relation.temporal_expression,
                temporal_start=relation.temporal_start,
                temporal_end=relation.temporal_end,
                temporal_approximate=bool(relation.temporal_approximate),
            )

    mention_statuses = ["accepted", "modified"]
    if include_pending_mentions:
        mention_statuses.append("pending")
    mention_rows = session.execute(
        select(EntityMention, EditableObject)
        .join(EditableObject, EditableObject.id == EntityMention.editable_object_id)
        .join(DigitalObject, DigitalObject.id == EditableObject.digital_object_id)
        .where(
            DigitalObject.project_id == project_id,
            EntityMention.authority_id.is_not(None),
            EntityMention.status.in_(mention_statuses),
            EditableObject.lifecycle_status == "active",
        )
        .order_by(EntityMention.authority_id, EditableObject.digital_object_id, EditableObject.page_number)
    ).all()

    mention_groups: dict[tuple[str, str], dict[str, object]] = {}
    document_entities: dict[str, set[str]] = defaultdict(set)
    for mention, editable in mention_rows:
        authority_id = mention.authority_id
        if authority_id is None or authority_id not in authority_by_id:
            continue
        target = _document_target_for_object(
            editable,
            part_by_id=part_by_id,
            registration_by_digital=registration_by_digital,
        )
        if target is None:
            continue
        kind, record_id, _label, source_key, page = target
        if kind == "document_part":
            target_key = add_part(record_id, source_key=source_key, page=page)
        else:
            target_key = add_unit(record_id)
            node = nodes.get(target_key) if target_key else None
            if node and not node.source_key:
                node.source_key = source_key
                node.page_number = page
        entity_key = add_entity(authority_id)
        if entity_key is None or target_key is None:
            continue
        document_entities[target_key].add(authority_id)
        key = (authority_id, target_key)
        bucket = mention_groups.setdefault(
            key,
            {
                "count": 0,
                "texts": [],
                "source_key": source_key,
                "page": page,
                "object_id": editable.id,
                "stale": 0,
                "pending": 0,
            },
        )
        bucket["count"] = int(bucket["count"]) + 1
        texts = bucket["texts"]
        if isinstance(texts, list) and mention.mention_text not in texts:
            texts.append(mention.mention_text)
        if mention.object_revision_number != editable.revision_number:
            bucket["stale"] = int(bucket["stale"]) + 1
        if mention.status == "pending":
            bucket["pending"] = int(bucket["pending"]) + 1

    if "mention" in edge_types:
        for (authority_id, target_key), bucket in mention_groups.items():
            entity_key = _node_id("entity", authority_id)
            count = int(bucket["count"])
            texts = bucket["texts"] if isinstance(bucket["texts"], list) else []
            stale = int(bucket["stale"])
            pending = int(bucket["pending"])
            edge_key = _edge_id("mention", authority_id, target_key)
            explanation = (
                f"{count} mención{'es' if count != 1 else ''} vinculada"
                f"{'s' if count != 1 else ''} conecta{'n' if count != 1 else ''} "
                "la entidad con este documento o parte interna."
            )
            if pending:
                explanation += f" {pending} todavía está(n) pendiente(s) de revisión humana."
            if stale:
                explanation += f" {stale} corresponde(n) a una revisión textual anterior."
            edges[edge_key] = GraphEdge(
                edge_id=edge_key,
                source=entity_key,
                target=target_key,
                edge_type="mention",
                label=f"mencionada en ({count})",
                explanation=explanation,
                weight=count,
                evidence_note=", ".join(texts[:6]) or None,
                authority_ids=(authority_id,),
                source_key=str(bucket["source_key"]) if bucket["source_key"] else None,
                page_number=int(bucket["page"]) if bucket["page"] is not None else None,
                object_id=str(bucket["object_id"]) if bucket["object_id"] else None,
            )

    if "shared_entity" in edge_types:
        shared: dict[tuple[str, str], set[str]] = defaultdict(set)
        document_keys = sorted(document_entities)
        for index, left in enumerate(document_keys):
            left_entities = document_entities[left]
            for right in document_keys[index + 1 :]:
                common = left_entities & document_entities[right]
                if len(common) >= min_shared_entities:
                    shared[(left, right)].update(common)
        for (left, right), authority_ids in shared.items():
            names = [authority_by_id[item].preferred_name for item in sorted(authority_ids)]
            count = len(authority_ids)
            edge_key = _edge_id("shared", left, right, *sorted(authority_ids))
            edges[edge_key] = GraphEdge(
                edge_id=edge_key,
                source=left,
                target=right,
                edge_type="shared_entity",
                label=f"{count} entidad{'es' if count != 1 else ''} compartida{'s' if count != 1 else ''}",
                explanation=(
                    "Los dos documentos o partes contienen menciones vinculadas de las mismas "
                    "entidades. Esta arista es derivada y no constituye una afirmación analítica autónoma."
                ),
                weight=count,
                evidence_note=", ".join(names[:10]),
                authority_ids=tuple(sorted(authority_ids)),
            )

    # Mantener solamente el componente o vecindad solicitada.
    if focus_node_id and focus_node_id in nodes and max_depth is not None:
        adjacency: dict[str, set[str]] = defaultdict(set)
        for edge in edges.values():
            adjacency[edge.source].add(edge.target)
            adjacency[edge.target].add(edge.source)
        keep = {focus_node_id}
        queue = deque([(focus_node_id, 0)])
        while queue:
            current, depth = queue.popleft()
            if depth >= max_depth:
                continue
            for neighbor in adjacency.get(current, set()):
                if neighbor not in keep:
                    keep.add(neighbor)
                    queue.append((neighbor, depth + 1))
        nodes = {key: value for key, value in nodes.items() if key in keep}
        edges = {
            key: value
            for key, value in edges.items()
            if value.source in keep and value.target in keep
        }

    total_nodes = len(nodes)
    total_edges = len(edges)
    truncated = False
    if len(nodes) > max_nodes:
        degree: dict[str, int] = defaultdict(int)
        for edge in edges.values():
            degree[edge.source] += edge.weight
            degree[edge.target] += edge.weight
        ordered = sorted(
            nodes,
            key=lambda key: (
                key == focus_node_id,
                degree.get(key, 0),
                nodes[key].kind == "entity",
                nodes[key].label.casefold(),
            ),
            reverse=True,
        )
        keep = set(ordered[:max_nodes])
        if focus_node_id and focus_node_id in nodes:
            keep.add(focus_node_id)
        nodes = {key: value for key, value in nodes.items() if key in keep}
        edges = {
            key: value
            for key, value in edges.items()
            if value.source in keep and value.target in keep
        }
        truncated = True

    degree_counts: dict[str, int] = defaultdict(int)
    for edge in edges.values():
        degree_counts[edge.source] += 1
        degree_counts[edge.target] += 1
    for key, node in nodes.items():
        node.degree = degree_counts.get(key, 0)

    return GraphView(
        nodes=sorted(nodes.values(), key=lambda row: (row.kind, row.label.casefold(), row.node_id)),
        edges=sorted(edges.values(), key=lambda row: (row.edge_type, row.label.casefold(), row.edge_id)),
        truncated=truncated,
        total_nodes_before_limit=total_nodes,
        total_edges_before_limit=total_edges,
    )


def graph_consistency_issues(session: Session, *, project_id: str) -> list[GraphConsistencyIssue]:
    issues: list[GraphConsistencyIssue] = []
    relations = session.scalars(
        select(EntityRelation)
        .where(EntityRelation.project_id == project_id)
        .order_by(EntityRelation.created_at, EntityRelation.id)
    ).all()
    authority_ids = {
        relation.source_authority_id for relation in relations
    } | {
        relation.target_authority_id
        for relation in relations
        if relation.target_authority_id is not None
    }
    authorities = {
        row.id: row
        for row in session.scalars(
            select(AuthorityRecord).where(AuthorityRecord.id.in_(authority_ids))
        ).all()
    } if authority_ids else {}
    unit_ids = {
        relation.target_archival_unit_id
        for relation in relations
        if relation.target_archival_unit_id is not None
    }
    units = {
        row.id: row
        for row in session.scalars(select(ArchivalUnit).where(ArchivalUnit.id.in_(unit_ids))).all()
    } if unit_ids else {}
    part_ids = {
        relation.target_document_part_id
        for relation in relations
        if relation.target_document_part_id is not None
    }
    parts = {
        row.id: row
        for row in session.scalars(select(DocumentPart).where(DocumentPart.id.in_(part_ids))).all()
    } if part_ids else {}

    duplicate_groups: dict[tuple[str, str, str, str], list[EntityRelation]] = defaultdict(list)
    for relation in relations:
        if relation.lifecycle_status != "active":
            continue
        if relation.target_authority_id is not None:
            target_kind, target_id = "entity", relation.target_authority_id
        elif relation.target_archival_unit_id is not None:
            target_kind, target_id = "archival_unit", relation.target_archival_unit_id
        elif relation.target_document_part_id is not None:
            target_kind, target_id = "document_part", relation.target_document_part_id
        else:
            target_kind, target_id = "missing", ""
        duplicate_groups[
            (relation.source_authority_id, _normalized(relation.relation_label), target_kind, target_id)
        ].append(relation)

        source = authorities.get(relation.source_authority_id)
        if source is None:
            issues.append(
                GraphConsistencyIssue(
                    code="orphan_source",
                    severity="error",
                    message="La relación no tiene una entidad de origen existente.",
                    relation_id=relation.id,
                )
            )
        elif source.lifecycle_status != "active":
            issues.append(
                GraphConsistencyIssue(
                    code="inactive_source",
                    severity="warning",
                    message=f"La relación está activa pero la entidad de origen “{source.preferred_name}” está inactiva.",
                    relation_id=relation.id,
                    entity_id=source.id,
                )
            )

        target_missing = (
            target_kind == "entity" and target_id not in authorities
        ) or (
            target_kind == "archival_unit" and target_id not in units
        ) or (
            target_kind == "document_part" and target_id not in parts
        ) or target_kind == "missing"
        if target_missing:
            issues.append(
                GraphConsistencyIssue(
                    code="orphan_target",
                    severity="error",
                    message="La relación no tiene un destino existente.",
                    relation_id=relation.id,
                )
            )
        elif target_kind == "entity" and authorities[target_id].lifecycle_status != "active":
            issues.append(
                GraphConsistencyIssue(
                    code="inactive_target",
                    severity="warning",
                    message=(
                        "La relación está activa pero la entidad de destino “"
                        f"{authorities[target_id].preferred_name}” está inactiva."
                    ),
                    relation_id=relation.id,
                    entity_id=target_id,
                )
            )
        if not relation.evidence_note or not relation.evidence_note.strip():
            issues.append(
                GraphConsistencyIssue(
                    code="missing_evidence",
                    severity="warning",
                    message=(
                        f"La relación “{relation.relation_label}” no tiene evidencia o fundamento registrado."
                    ),
                    relation_id=relation.id,
                    entity_id=relation.source_authority_id,
                )
            )
        if relation.review_status == "unreviewed":
            issues.append(
                GraphConsistencyIssue(
                    code="unreviewed_relation",
                    severity="info",
                    message=f"La relación “{relation.relation_label}” todavía no fue revisada.",
                    relation_id=relation.id,
                    entity_id=relation.source_authority_id,
                )
            )

    for group in duplicate_groups.values():
        if len(group) < 2:
            continue
        ids = ", ".join(item.id for item in group)
        for relation in group:
            issues.append(
                GraphConsistencyIssue(
                    code="duplicate_relation",
                    severity="warning",
                    message=f"Hay {len(group)} relaciones activas equivalentes: {ids}.",
                    relation_id=relation.id,
                    entity_id=relation.source_authority_id,
                )
            )

    from archive_workbench.authorities import project_mention_span_to_current

    active_mention_rows = session.execute(
        select(EntityMention, EditableObject)
        .join(EditableObject, EditableObject.id == EntityMention.editable_object_id)
        .join(DigitalObject, DigitalObject.id == EditableObject.digital_object_id)
        .where(
            DigitalObject.project_id == project_id,
            EntityMention.status != "rejected",
        )
        .order_by(
            EntityMention.editable_object_id,
            EntityMention.object_revision_number,
            EntityMention.id,
        )
    ).all()
    logical_mention_groups: dict[
        tuple[str, int, int, int], list[EntityMention]
    ] = defaultdict(list)
    for mention, editable in active_mention_rows:
        projected = project_mention_span_to_current(
            session, mention, editable_object=editable
        )
        if projected is None:
            continue
        logical_mention_groups[
            (editable.id, editable.revision_number, projected[0], projected[1])
        ].append(mention)
    for group in logical_mention_groups.values():
        if len(group) < 2:
            continue
        ids = ", ".join(item.id for item in group)
        authorities = sorted(
            {item.authority_id or "sin autoridad" for item in group}
        )
        issues.append(
            GraphConsistencyIssue(
                code="duplicate_mention",
                severity="warning",
                message=(
                    f"Hay {len(group)} menciones activas que representan el mismo "
                    "fragmento vigente, incluso entre revisiones textuales. "
                    f"Menciones: {ids}. Autoridades: {', '.join(authorities)}."
                ),
                mention_id=group[0].id,
                entity_id=group[0].authority_id,
            )
        )

    mention_rows = session.execute(
        select(EntityMention, EditableObject)
        .join(EditableObject, EditableObject.id == EntityMention.editable_object_id)
        .join(DigitalObject, DigitalObject.id == EditableObject.digital_object_id)
        .where(
            DigitalObject.project_id == project_id,
            EntityMention.status.in_(["accepted", "modified"]),
        )
    ).all()
    for mention, editable in mention_rows:
        if mention.authority_id is None:
            issues.append(
                GraphConsistencyIssue(
                    code="accepted_without_entity",
                    severity="error",
                    message="Una mención aceptada o modificada no está vinculada a ninguna entidad.",
                    mention_id=mention.id,
                )
            )
        if mention.object_revision_number != editable.revision_number:
            issues.append(
                GraphConsistencyIssue(
                    code="stale_mention",
                    severity="warning",
                    message=(
                        f"La mención “{mention.mention_text}” pertenece a la revisión "
                        f"{mention.object_revision_number}, pero el texto está en la revisión {editable.revision_number}."
                    ),
                    mention_id=mention.id,
                    entity_id=mention.authority_id,
                )
            )

    severity_order = {"error": 0, "warning": 1, "info": 2}
    return sorted(
        issues,
        key=lambda row: (severity_order.get(row.severity, 9), row.code, row.message),
    )


def _json_ready(view: GraphView) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "nodes": [asdict(row) for row in view.nodes],
        "edges": [
            {**asdict(row), "authority_ids": list(row.authority_ids)} for row in view.edges
        ],
        "truncated": view.truncated,
        "total_nodes_before_limit": view.total_nodes_before_limit,
        "total_edges_before_limit": view.total_edges_before_limit,
    }


def export_graph(
    view: GraphView,
    *,
    output_dir: str | Path,
    issues: list[GraphConsistencyIssue] | None = None,
) -> list[Path]:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []

    json_path = root / "graph.json"
    payload = _json_ready(view)
    if issues is not None:
        payload["consistency_issues"] = [asdict(row) for row in issues]
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    paths.append(json_path)

    nodes_path = root / "nodes.csv"
    with nodes_path.open("w", newline="", encoding="utf-8") as handle:
        fieldnames = list(asdict(view.nodes[0]).keys()) if view.nodes else [
            "node_id", "kind", "record_id", "label", "context", "subtype",
            "review_status", "lifecycle_status", "degree", "source_key",
            "page_number", "object_id",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in view.nodes:
            writer.writerow(asdict(row))
    paths.append(nodes_path)

    edges_path = root / "edges.csv"
    with edges_path.open("w", newline="", encoding="utf-8") as handle:
        fieldnames = list(asdict(view.edges[0]).keys()) if view.edges else [
            "edge_id", "source", "target", "edge_type", "label", "explanation",
            "weight", "relation_id", "review_status", "lifecycle_status",
            "evidence_note", "authority_ids", "source_key", "page_number", "object_id",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in view.edges:
            item = asdict(row)
            item["authority_ids"] = "|".join(row.authority_ids)
            writer.writerow(item)
    paths.append(edges_path)

    graphml_path = root / "graph.graphml"
    ns = "http://graphml.graphdrawing.org/xmlns"
    ET.register_namespace("", ns)
    graphml = ET.Element(f"{{{ns}}}graphml")
    key_specs = [
        ("node_label", "node", "label", "string"),
        ("node_kind", "node", "kind", "string"),
        ("node_context", "node", "context", "string"),
        ("edge_label", "edge", "label", "string"),
        ("edge_type", "edge", "edge_type", "string"),
        ("edge_weight", "edge", "weight", "int"),
        ("edge_explanation", "edge", "explanation", "string"),
    ]
    for key_id, target, name, attr_type in key_specs:
        ET.SubElement(
            graphml,
            f"{{{ns}}}key",
            id=key_id,
            **{"for": target, "attr.name": name, "attr.type": attr_type},
        )
    graph = ET.SubElement(graphml, f"{{{ns}}}graph", id="archive_workbench", edgedefault="directed")
    for node in view.nodes:
        element = ET.SubElement(graph, f"{{{ns}}}node", id=node.node_id)
        for key_id, value in (
            ("node_label", node.label),
            ("node_kind", node.kind),
            ("node_context", node.context or ""),
        ):
            data = ET.SubElement(element, f"{{{ns}}}data", key=key_id)
            data.text = str(value)
    for edge in view.edges:
        element = ET.SubElement(
            graph,
            f"{{{ns}}}edge",
            id=edge.edge_id,
            source=edge.source,
            target=edge.target,
        )
        for key_id, value in (
            ("edge_label", edge.label),
            ("edge_type", edge.edge_type),
            ("edge_weight", edge.weight),
            ("edge_explanation", edge.explanation),
        ):
            data = ET.SubElement(element, f"{{{ns}}}data", key=key_id)
            data.text = str(value)
    ET.ElementTree(graphml).write(graphml_path, encoding="utf-8", xml_declaration=True)
    paths.append(graphml_path)

    if issues is not None:
        issues_path = root / "consistency_issues.csv"
        with issues_path.open("w", newline="", encoding="utf-8") as handle:
            fieldnames = ["code", "severity", "message", "relation_id", "mention_id", "entity_id"]
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for issue in issues:
                writer.writerow(asdict(issue))
        paths.append(issues_path)
    return paths


def graph_payload(view: GraphView, *, selected_node: str | None = None, selected_edge: str | None = None) -> dict[str, object]:
    """Payload serializable para el componente interactivo."""
    return {
        "nodes": [
            {
                "id": row.node_id,
                "label": row.label,
                "kind": row.kind,
                "subtype": row.subtype,
                "degree": row.degree,
                "selected": row.node_id == selected_node,
            }
            for row in view.nodes
        ],
        "edges": [
            {
                "id": row.edge_id,
                "source": row.source,
                "target": row.target,
                "label": row.label,
                "edge_type": row.edge_type,
                "weight": row.weight,
                "selected": row.edge_id == selected_edge,
            }
            for row in view.edges
        ],
        "selected_node": selected_node,
        "selected_edge": selected_edge,
    }


def graph_layout(view: GraphView, *, width: float = 1000.0, height: float = 720.0) -> dict[str, tuple[float, float]]:
    """Layout de fuerzas determinista y sin dependencias externas."""
    node_ids = [row.node_id for row in view.nodes]
    if not node_ids:
        return {}
    if len(node_ids) == 1:
        return {node_ids[0]: (width / 2, height / 2)}
    positions: dict[str, list[float]] = {}
    radius = min(width, height) * 0.36
    for index, node_id in enumerate(node_ids):
        digest = hashlib.sha256(node_id.encode("utf-8")).digest()
        jitter = (int.from_bytes(digest[:2], "big") / 65535.0 - 0.5) * 0.22
        angle = 2 * math.pi * index / len(node_ids) + jitter
        positions[node_id] = [
            width / 2 + radius * math.cos(angle),
            height / 2 + radius * math.sin(angle),
        ]
    edge_pairs = [(edge.source, edge.target, max(1, edge.weight)) for edge in view.edges]
    area = width * height
    k = math.sqrt(area / max(1, len(node_ids)))
    temperature = min(width, height) * 0.12
    for iteration in range(90):
        displacement = {node_id: [0.0, 0.0] for node_id in node_ids}
        for index, left in enumerate(node_ids):
            lx, ly = positions[left]
            for right in node_ids[index + 1 :]:
                rx, ry = positions[right]
                dx, dy = lx - rx, ly - ry
                distance = max(1.0, math.hypot(dx, dy))
                force = k * k / distance
                fx, fy = dx / distance * force, dy / distance * force
                displacement[left][0] += fx
                displacement[left][1] += fy
                displacement[right][0] -= fx
                displacement[right][1] -= fy
        for source, target, weight in edge_pairs:
            sx, sy = positions[source]
            tx, ty = positions[target]
            dx, dy = sx - tx, sy - ty
            distance = max(1.0, math.hypot(dx, dy))
            force = (distance * distance / k) * min(2.0, 0.65 + math.log1p(weight) * 0.25)
            fx, fy = dx / distance * force, dy / distance * force
            displacement[source][0] -= fx
            displacement[source][1] -= fy
            displacement[target][0] += fx
            displacement[target][1] += fy
        cooling = temperature * (1.0 - iteration / 90)
        for node_id in node_ids:
            dx, dy = displacement[node_id]
            distance = max(1.0, math.hypot(dx, dy))
            x, y = positions[node_id]
            x += dx / distance * min(distance, cooling)
            y += dy / distance * min(distance, cooling)
            positions[node_id] = [
                min(width - 55, max(55, x)),
                min(height - 55, max(55, y)),
            ]
    return {key: (round(value[0], 2), round(value[1], 2)) for key, value in positions.items()}
