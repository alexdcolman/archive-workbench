from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Mapping
from typing import Iterable

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from archive_workbench.db.models import (
    ArchivalUnit,
    AuthorityRecord,
    DigitalObject,
    DocumentPart,
    EntityRelation,
    EntityRelationRevision,
    Project,
    SourceRegistration,
    utc_now,
)
from archive_workbench.identity import new_id
from archive_workbench.sources import PROCESSABLE_SOURCE_TYPES
from archive_workbench.temporal import parse_temporal_expression, temporal_expression_overlap

RELATION_TARGET_KINDS = ("entity", "archival_unit", "document_part")
RELATION_KINDS = ("analytical", "producer", "manager")
ARCHIVAL_ROLE_KINDS = ("producer", "manager")
RELATION_KIND_LABELS = {
    "analytical": "Relación analítica",
    "producer": "Entidad productora",
    "manager": "Entidad gestora",
}
RELATION_KIND_EDGE_LABELS = {
    "producer": "produjo",
    "manager": "gestionó",
}
RELATION_REVIEW_STATUSES = ("unreviewed", "reviewed", "approved")
RELATION_LIFECYCLE_STATUSES = ("active", "inactive", "deleted")
RELATION_EDITABLE_LIFECYCLE_STATUSES = ("active", "inactive")
RELATION_ARCHIVAL_CATEGORIES = ("hierarchical", "temporal_succession", "family", "associative", "other")
_UNSET = object()


@dataclass(slots=True)
class RelationTargetChoice:
    target_kind: str
    target_id: str
    label: str
    context: str | None = None


@dataclass(slots=True)
class EntityRelationRow:
    relation_id: str
    source_authority_id: str
    source_name: str
    relation_kind: str
    relation_label: str
    target_kind: str
    target_id: str
    target_label: str
    target_context: str | None
    evidence_note: str | None
    provenance_note: str | None
    temporal_expression: str | None
    temporal_start: date | None
    temporal_end: date | None
    temporal_precision: str | None
    temporal_approximate: bool
    temporal_note: str | None
    profile: dict[str, object]
    lifecycle_status: str
    review_status: str
    revision: int
    created_by: str
    created_at: datetime
    updated_by: str
    updated_at: datetime


@dataclass(slots=True)
class EntityRelationRevisionRow:
    revision_number: int
    operation: str
    snapshot: dict[str, object]
    note: str | None
    changed_by: str
    changed_at: datetime


def _target_fields(target_kind: str, target_id: str) -> dict[str, str | None]:
    if target_kind not in RELATION_TARGET_KINDS:
        raise ValueError(f"Tipo de destino inválido: {target_kind}")
    return {
        "target_authority_id": target_id if target_kind == "entity" else None,
        "target_archival_unit_id": target_id if target_kind == "archival_unit" else None,
        "target_document_part_id": target_id if target_kind == "document_part" else None,
    }


def _relation_target(relation: EntityRelation) -> tuple[str, str]:
    if relation.target_authority_id is not None:
        return "entity", relation.target_authority_id
    if relation.target_archival_unit_id is not None:
        return "archival_unit", relation.target_archival_unit_id
    if relation.target_document_part_id is not None:
        return "document_part", relation.target_document_part_id
    raise ValueError(f"La relación {relation.id} no tiene destino")


def _validate_target(
    session: Session,
    *,
    project_id: str,
    source_authority_id: str,
    target_kind: str,
    target_id: str,
) -> None:
    if target_kind == "entity":
        target = session.get(AuthorityRecord, target_id)
        if target is None or target.project_id != project_id:
            raise ValueError("La entidad de destino no existe en este proyecto")
        if target.id == source_authority_id:
            raise ValueError("Una entidad no puede relacionarse consigo misma")
        return
    if target_kind == "archival_unit":
        target = session.get(ArchivalUnit, target_id)
        if target is None or target.project_id != project_id:
            raise ValueError("La unidad archivística de destino no existe en este proyecto")
        return
    if target_kind == "document_part":
        target = session.get(DocumentPart, target_id)
        if target is None:
            raise ValueError("La parte interna de destino no existe")
        digital = session.get(DigitalObject, target.digital_object_id)
        if digital is None or digital.project_id != project_id:
            raise ValueError("La parte interna de destino pertenece a otro proyecto")
        return
    raise ValueError(f"Tipo de destino inválido: {target_kind}")


def _relation_snapshot(relation: EntityRelation) -> dict[str, object]:
    return {
        "project_id": relation.project_id,
        "source_authority_id": relation.source_authority_id,
        "relation_kind": relation.relation_kind,
        "relation_label": relation.relation_label,
        "target_authority_id": relation.target_authority_id,
        "target_archival_unit_id": relation.target_archival_unit_id,
        "target_document_part_id": relation.target_document_part_id,
        "evidence_note": relation.evidence_note,
        "provenance_note": relation.provenance_note,
        "temporal_expression": relation.temporal_expression,
        "temporal_start": relation.temporal_start.isoformat() if relation.temporal_start else None,
        "temporal_end": relation.temporal_end.isoformat() if relation.temporal_end else None,
        "temporal_precision": relation.temporal_precision,
        "temporal_approximate": relation.temporal_approximate,
        "temporal_note": relation.temporal_note,
        "profile_json": relation.profile_json or {},
        "lifecycle_status": relation.lifecycle_status,
        "review_status": relation.review_status,
    }


def _append_relation_revision(
    session: Session,
    relation: EntityRelation,
    *,
    operation: str,
    changed_by: str,
    note: str | None = None,
) -> EntityRelationRevision:
    revision = EntityRelationRevision(
        id=new_id(),
        relation_id=relation.id,
        revision_number=relation.revision,
        operation=operation,
        snapshot_json=_relation_snapshot(relation),
        note=note.strip() if note and note.strip() else None,
        changed_by=changed_by.strip() or "local_user",
        changed_at=utc_now(),
    )
    session.add(revision)
    session.flush()
    return revision


def _clean_optional(value: str | None) -> str | None:
    if value is None:
        return None
    return value.strip() or None


def _validate_relation_contract(
    *,
    relation_kind: str,
    relation_label: str | None,
    target_kind: str,
    evidence_note: str | None,
    provenance_note: str | None,
) -> tuple[str, str | None, str | None]:
    if relation_kind not in RELATION_KINDS:
        raise ValueError(f"Clase de relación inválida: {relation_kind}")
    clean_evidence = _clean_optional(evidence_note)
    clean_provenance = _clean_optional(provenance_note)
    if relation_kind in ARCHIVAL_ROLE_KINDS:
        if target_kind != "archival_unit":
            raise ValueError(
                "Las entidades productoras y gestoras solo pueden vincularse con una unidad archivística"
            )
        if clean_evidence is None:
            raise ValueError("El rol archivístico requiere evidencia")
        if clean_provenance is None:
            raise ValueError("El rol archivístico requiere procedencia")
        return RELATION_KIND_EDGE_LABELS[relation_kind], clean_evidence, clean_provenance
    clean_label = (relation_label or "").strip()
    if not clean_label:
        raise ValueError("La relación no puede quedar vacía")
    return clean_label, clean_evidence, clean_provenance


def create_entity_relation(
    session: Session,
    *,
    project_id: str,
    source_authority_id: str,
    relation_label: str,
    target_kind: str,
    target_id: str,
    created_by: str,
    relation_kind: str = "analytical",
    evidence_note: str | None = None,
    provenance_note: str | None = None,
    temporal_expression: str | None = None,
    temporal_note: str | None = None,
    profile_json: Mapping[str, object] | None = None,
    review_status: str = "unreviewed",
    note: str | None = None,
) -> EntityRelation:
    if session.get(Project, project_id) is None:
        raise ValueError(f"Proyecto inexistente: {project_id}")
    source = session.get(AuthorityRecord, source_authority_id)
    if source is None or source.project_id != project_id:
        raise ValueError("La entidad de origen no existe en este proyecto")
    if review_status not in RELATION_REVIEW_STATUSES:
        raise ValueError(f"Estado de revisión inválido: {review_status}")
    _validate_target(
        session,
        project_id=project_id,
        source_authority_id=source_authority_id,
        target_kind=target_kind,
        target_id=target_id,
    )
    clean_label, clean_evidence, clean_provenance = _validate_relation_contract(
        relation_kind=relation_kind,
        relation_label=relation_label,
        target_kind=target_kind,
        evidence_note=evidence_note,
        provenance_note=provenance_note,
    )
    targets = _target_fields(target_kind, target_id)
    temporal = parse_temporal_expression(temporal_expression)
    actor = created_by.strip() or "local_user"
    relation = EntityRelation(
        id=new_id(),
        project_id=project_id,
        source_authority_id=source_authority_id,
        relation_kind=relation_kind,
        relation_label=clean_label,
        evidence_note=clean_evidence,
        provenance_note=clean_provenance,
        temporal_expression=temporal.expression,
        temporal_start=temporal.start,
        temporal_end=temporal.end,
        temporal_precision=temporal.precision,
        temporal_approximate=temporal.approximate,
        temporal_note=_clean_optional(temporal_note),
        profile_json=dict(profile_json or {}) or None,
        lifecycle_status="active",
        review_status=review_status,
        created_by=actor,
        created_at=utc_now(),
        updated_by=actor,
        updated_at=utc_now(),
        revision=1,
        **targets,
    )
    session.add(relation)
    session.flush()
    _append_relation_revision(
        session, relation, operation="create", changed_by=actor, note=note
    )
    return relation


def update_entity_relation(
    session: Session,
    *,
    relation_id: str,
    expected_revision: int,
    changed_by: str,
    source_authority_id: str | None = None,
    relation_kind: str | None = None,
    relation_label: str | None = None,
    target_kind: str | None = None,
    target_id: str | None = None,
    evidence_note: str | None = None,
    provenance_note: str | None = None,
    temporal_expression: str | None = None,
    temporal_note: str | None = None,
    profile_json: Mapping[str, object] | None | object = _UNSET,
    review_status: str | None = None,
    lifecycle_status: str | None = None,
    note: str | None = None,
) -> EntityRelation:
    relation = session.get(EntityRelation, relation_id)
    if relation is None:
        raise ValueError(f"Relación inexistente: {relation_id}")
    if relation.revision != expected_revision:
        raise ValueError(
            f"La relación está en revisión {relation.revision}; se esperaba {expected_revision}"
        )
    if (target_kind is None) != (target_id is None):
        raise ValueError("target_kind y target_id deben indicarse juntos")

    prospective_source_id = source_authority_id or relation.source_authority_id
    source = session.get(AuthorityRecord, prospective_source_id)
    if source is None or source.project_id != relation.project_id:
        raise ValueError("La entidad de origen no existe en este proyecto")

    current_target_kind, current_target_id = _relation_target(relation)
    prospective_target_kind = target_kind or current_target_kind
    prospective_target_id = target_id or current_target_id
    _validate_target(
        session,
        project_id=relation.project_id,
        source_authority_id=prospective_source_id,
        target_kind=prospective_target_kind,
        target_id=prospective_target_id,
    )

    prospective_kind = relation_kind or relation.relation_kind
    if (
        relation_kind == "analytical"
        and relation.relation_kind != "analytical"
        and relation_label is None
    ):
        raise ValueError("Indicá la etiqueta al convertir un rol archivístico en relación analítica")
    prospective_label = relation_label if relation_label is not None else relation.relation_label
    prospective_evidence = (
        relation.evidence_note if evidence_note is None else _clean_optional(evidence_note)
    )
    prospective_provenance = (
        relation.provenance_note
        if provenance_note is None
        else _clean_optional(provenance_note)
    )
    clean_label, clean_evidence, clean_provenance = _validate_relation_contract(
        relation_kind=prospective_kind,
        relation_label=prospective_label,
        target_kind=prospective_target_kind,
        evidence_note=prospective_evidence,
        provenance_note=prospective_provenance,
    )

    relation.source_authority_id = prospective_source_id
    relation.relation_kind = prospective_kind
    relation.relation_label = clean_label
    targets = _target_fields(prospective_target_kind, prospective_target_id)
    relation.target_authority_id = targets["target_authority_id"]
    relation.target_archival_unit_id = targets["target_archival_unit_id"]
    relation.target_document_part_id = targets["target_document_part_id"]
    relation.evidence_note = clean_evidence
    relation.provenance_note = clean_provenance
    if temporal_expression is not None:
        temporal = parse_temporal_expression(temporal_expression)
        relation.temporal_expression = temporal.expression
        relation.temporal_start = temporal.start
        relation.temporal_end = temporal.end
        relation.temporal_precision = temporal.precision
        relation.temporal_approximate = temporal.approximate
    if temporal_note is not None:
        relation.temporal_note = _clean_optional(temporal_note)
    if profile_json is not _UNSET:
        relation.profile_json = dict(profile_json or {}) or None
    if review_status is not None:
        if review_status not in RELATION_REVIEW_STATUSES:
            raise ValueError(f"Estado de revisión inválido: {review_status}")
        relation.review_status = review_status
    if lifecycle_status is not None:
        if lifecycle_status not in RELATION_LIFECYCLE_STATUSES:
            raise ValueError(f"Estado de ciclo de vida inválido: {lifecycle_status}")
        relation.lifecycle_status = lifecycle_status
    relation.revision += 1
    relation.updated_by = changed_by.strip() or "local_user"
    relation.updated_at = utc_now()
    session.flush()
    _append_relation_revision(
        session, relation, operation="update", changed_by=changed_by, note=note
    )
    return relation



def delete_entity_relation(
    session: Session,
    *,
    relation_id: str,
    expected_revision: int,
    changed_by: str,
    note: str | None = None,
) -> EntityRelation:
    """Retira un vínculo creado por error sin borrar su historial ni la entidad relacionada."""
    relation = session.get(EntityRelation, relation_id)
    if relation is None:
        raise ValueError(f"Relación inexistente: {relation_id}")
    if relation.revision != expected_revision:
        raise ValueError(
            f"La relación está en revisión {relation.revision}; se esperaba {expected_revision}"
        )
    if relation.lifecycle_status == "deleted":
        raise ValueError("La relación ya está eliminada")
    relation.lifecycle_status = "deleted"
    relation.revision += 1
    relation.updated_by = changed_by.strip() or "local_user"
    relation.updated_at = utc_now()
    session.flush()
    _append_relation_revision(
        session,
        relation,
        operation="delete",
        changed_by=changed_by,
        note=note or "Vínculo retirado porque fue registrado por error",
    )
    return relation

def relation_target_choices(
    session: Session,
    *,
    project_id: str,
    target_kind: str,
    exclude_authority_id: str | None = None,
) -> list[RelationTargetChoice]:
    if target_kind == "entity":
        rows = session.scalars(
            select(AuthorityRecord)
            .where(
                AuthorityRecord.project_id == project_id,
                AuthorityRecord.lifecycle_status == "active",
            )
            .order_by(AuthorityRecord.normalized_name, AuthorityRecord.id)
        ).all()
        return [
            RelationTargetChoice("entity", row.id, row.preferred_name, row.entity_type)
            for row in rows
            if row.id != exclude_authority_id
        ]
    if target_kind == "archival_unit":
        rows = session.scalars(
            select(ArchivalUnit)
            .where(ArchivalUnit.project_id == project_id)
            .order_by(ArchivalUnit.title, ArchivalUnit.id)
        ).all()
        return [
            RelationTargetChoice(
                "archival_unit", row.id, row.title, row.reference_code or row.level_key
            )
            for row in rows
        ]
    if target_kind == "document_part":
        rows = session.execute(
            select(DocumentPart, DigitalObject, SourceRegistration, ArchivalUnit)
            .join(DigitalObject, DigitalObject.id == DocumentPart.digital_object_id)
            .outerjoin(
                SourceRegistration,
                (SourceRegistration.digital_object_id == DigitalObject.id)
                & (SourceRegistration.source_type.in_(PROCESSABLE_SOURCE_TYPES)),
            )
            .outerjoin(ArchivalUnit, ArchivalUnit.id == SourceRegistration.archival_unit_id)
            .where(DigitalObject.project_id == project_id)
            .order_by(ArchivalUnit.title, DocumentPart.page_start, DocumentPart.id)
        ).all()
        seen: set[str] = set()
        result: list[RelationTargetChoice] = []
        for part, _digital, registration, unit in rows:
            if part.id in seen:
                continue
            seen.add(part.id)
            context = unit.title if unit is not None else (
                registration.source_key if registration is not None else f"págs. {part.page_start}-{part.page_end}"
            )
            result.append(RelationTargetChoice("document_part", part.id, part.title, context))
        return result
    raise ValueError(f"Tipo de destino inválido: {target_kind}")


def entity_relation_rows(
    session: Session,
    *,
    project_id: str,
    authority_id: str | None = None,
    archival_unit_id: str | None = None,
    relation_kinds: tuple[str, ...] = (),
    include_inactive: bool = False,
    temporal_start: date | None = None,
    temporal_end: date | None = None,
    include_undated: bool = False,
) -> list[EntityRelationRow]:
    invalid_kinds = sorted(set(relation_kinds) - set(RELATION_KINDS))
    if invalid_kinds:
        raise ValueError(f"Clases de relación inválidas: {', '.join(invalid_kinds)}")
    statement = select(EntityRelation).where(EntityRelation.project_id == project_id)
    if authority_id is not None:
        statement = statement.where(
            or_(
                EntityRelation.source_authority_id == authority_id,
                EntityRelation.target_authority_id == authority_id,
            )
        )
    if archival_unit_id is not None:
        statement = statement.where(
            EntityRelation.target_archival_unit_id == archival_unit_id
        )
    if relation_kinds:
        statement = statement.where(EntityRelation.relation_kind.in_(relation_kinds))
    if include_inactive:
        statement = statement.where(EntityRelation.lifecycle_status.in_(RELATION_EDITABLE_LIFECYCLE_STATUSES))
    else:
        statement = statement.where(EntityRelation.lifecycle_status == "active")
    if temporal_start is not None or temporal_end is not None:
        if temporal_start is not None and temporal_end is not None and temporal_start > temporal_end:
            raise ValueError("El inicio del filtro temporal es posterior al final")
        overlap_parts = []
        if temporal_start is not None:
            overlap_parts.append(
                or_(EntityRelation.temporal_end.is_(None), EntityRelation.temporal_end >= temporal_start)
            )
        if temporal_end is not None:
            overlap_parts.append(
                or_(EntityRelation.temporal_start.is_(None), EntityRelation.temporal_start <= temporal_end)
            )
        dated = or_(EntityRelation.temporal_start.is_not(None), EntityRelation.temporal_end.is_not(None))
        overlap = and_(*overlap_parts)
        statement = statement.where(or_(overlap, ~dated) if include_undated else and_(dated, overlap))
    relations = session.scalars(
        statement.order_by(EntityRelation.created_at, EntityRelation.id)
    ).all()
    if temporal_start is not None or temporal_end is not None:
        relations = [
            row
            for row in relations
            if temporal_expression_overlap(
                expression=row.temporal_expression,
                item_start=row.temporal_start,
                item_end=row.temporal_end,
                query_start=temporal_start,
                query_end=temporal_end,
                include_undated=include_undated,
            )
        ]
    authority_ids = {
        row.source_authority_id for row in relations
    } | {row.target_authority_id for row in relations if row.target_authority_id}
    authorities = {
        row.id: row
        for row in session.scalars(
            select(AuthorityRecord).where(AuthorityRecord.id.in_(authority_ids))
        ).all()
    } if authority_ids else {}
    unit_ids = {row.target_archival_unit_id for row in relations if row.target_archival_unit_id}
    units = {
        row.id: row
        for row in session.scalars(select(ArchivalUnit).where(ArchivalUnit.id.in_(unit_ids))).all()
    } if unit_ids else {}
    part_ids = {row.target_document_part_id for row in relations if row.target_document_part_id}
    parts = {
        row.id: row
        for row in session.scalars(select(DocumentPart).where(DocumentPart.id.in_(part_ids))).all()
    } if part_ids else {}
    result: list[EntityRelationRow] = []
    for relation in relations:
        kind, target_id = _relation_target(relation)
        if kind == "entity":
            target = authorities.get(target_id)
            target_label = target.preferred_name if target else "Entidad inexistente"
            context = target.entity_type if target else None
        elif kind == "archival_unit":
            target = units.get(target_id)
            target_label = target.title if target else "Unidad inexistente"
            context = target.reference_code if target else None
        else:
            target = parts.get(target_id)
            target_label = target.title if target else "Parte interna inexistente"
            context = (
                f"págs. {target.page_start}-{target.page_end}" if target else None
            )
        source = authorities.get(relation.source_authority_id)
        result.append(
            EntityRelationRow(
                relation_id=relation.id,
                source_authority_id=relation.source_authority_id,
                source_name=source.preferred_name if source else "Entidad inexistente",
                relation_kind=relation.relation_kind,
                relation_label=relation.relation_label,
                target_kind=kind,
                target_id=target_id,
                target_label=target_label,
                target_context=context,
                evidence_note=relation.evidence_note,
                provenance_note=relation.provenance_note,
                temporal_expression=relation.temporal_expression,
                temporal_start=relation.temporal_start,
                temporal_end=relation.temporal_end,
                temporal_precision=relation.temporal_precision,
                temporal_approximate=bool(relation.temporal_approximate),
                temporal_note=relation.temporal_note,
                profile=dict(relation.profile_json or {}),
                lifecycle_status=relation.lifecycle_status,
                review_status=relation.review_status,
                revision=relation.revision,
                created_by=relation.created_by,
                created_at=relation.created_at,
                updated_by=relation.updated_by,
                updated_at=relation.updated_at,
            )
        )
    return result


def entity_relation_revision_rows(
    session: Session, relation_id: str
) -> list[EntityRelationRevisionRow]:
    rows = session.scalars(
        select(EntityRelationRevision)
        .where(EntityRelationRevision.relation_id == relation_id)
        .order_by(EntityRelationRevision.revision_number.desc())
    ).all()
    return [
        EntityRelationRevisionRow(
            revision_number=row.revision_number,
            operation=row.operation,
            snapshot=row.snapshot_json,
            note=row.note,
            changed_by=row.changed_by,
            changed_at=row.changed_at,
        )
        for row in rows
    ]
