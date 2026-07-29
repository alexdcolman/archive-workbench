from __future__ import annotations

import csv
import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from archive_workbench.db.models import (
    ArchivalUnit,
    AuthorityRecord,
    CorpusExportProfile,
    CorpusExportRun,
    DocumentPart,
    EditableObject,
    EditableObjectTag,
    EditablePage,
    EntityMention,
    EntityRelation,
    ExtractedObject,
    SourceRegistration,
    utc_now,
)
from archive_workbench.exchange import current_editable_state_sha256
from archive_workbench.identity import new_id
from archive_workbench.temporal import format_temporal_range, temporal_overlap

AGGREGATION_LEVELS = ("object", "page", "document_part", "document", "archival_unit")
TEXT_POLICIES = ("corrected_fallback_original", "corrected_only", "original_only")
OUTPUT_FORMATS = ("jsonl", "csv")
REVIEW_STATUSES = ("unreviewed", "needs_review", "reviewed", "approved")


@dataclass(slots=True)
class ExportProfileValues:
    name: str
    description: str | None = None
    aggregation_level: str = "document"
    text_policy: str = "corrected_fallback_original"
    output_format: str = "jsonl"
    include_object_types: tuple[str, ...] = ()
    include_review_statuses: tuple[str, ...] = ()
    include_page_review_statuses: tuple[str, ...] = ()
    temporal_start: date | None = None
    temporal_end: date | None = None
    temporal_include_undated: bool = False
    object_separator: str = "\n\n"
    page_separator: str = "\n\n"
    include_page_markers: bool = False


@dataclass(slots=True)
class ExportRecord:
    record_id: str
    aggregation_level: str
    codigo: str
    titulo: str
    texto: str
    source_key: str | None
    source_keys: list[str]
    digital_object_id: str | None
    digital_object_ids: list[str]
    archival_unit_id: str | None
    reference_code: str | None
    hierarchy_path: str | None
    document_part_id: str | None
    document_part_key: str | None
    document_part_title: str | None
    page_start: int
    page_end: int
    object_count: int
    object_ids: list[str]
    object_types: list[str]
    object_review_statuses: list[str]
    page_review_statuses: list[str]
    tags: list[str]
    entities: list[str]
    entity_temporal_ranges: list[str]
    relation_temporal_ranges: list[str]


@dataclass(slots=True)
class ExportPreview:
    total_records: int
    total_characters: int
    records: list[ExportRecord]


@dataclass(slots=True)
class ExportRunResult:
    run_id: str
    output_path: Path
    row_count: int
    character_count: int
    byte_size: int
    output_sha256: str
    corpus_state_sha256: str


@dataclass(slots=True)
class ExportRunRow:
    run_id: str
    profile_name: str
    output_format: str
    output_relative_path: str
    row_count: int
    character_count: int
    byte_size: int
    output_sha256: str
    corpus_state_sha256: str
    created_by: str
    created_at: datetime


@dataclass(slots=True)
class _Atom:
    object_id: str
    digital_object_id: str
    source_key: str | None
    archival_unit_id: str | None
    reference_code: str | None
    hierarchy_path: str | None
    unit_title: str | None
    part_id: str | None
    part_key: str | None
    part_title: str | None
    page_number: int
    order_index: int
    object_type: str
    object_review_status: str
    page_review_status: str
    text: str
    tags: tuple[str, ...]
    entities: tuple[str, ...]
    entity_temporal_ranges: tuple[str, ...]
    relation_temporal_ranges: tuple[str, ...]


def _clean_name(value: str) -> str:
    clean = " ".join(value.split())
    if not clean:
        raise ValueError("El perfil necesita un nombre")
    if len(clean) > 200:
        raise ValueError("El nombre del perfil no puede superar 200 caracteres")
    return clean


def _validate(values: ExportProfileValues) -> ExportProfileValues:
    if values.aggregation_level not in AGGREGATION_LEVELS:
        raise ValueError("Nivel de agrupación inválido")
    if values.text_policy not in TEXT_POLICIES:
        raise ValueError("Política de texto inválida")
    if values.output_format not in OUTPUT_FORMATS:
        raise ValueError("Formato de salida inválido")
    invalid_review = set(values.include_review_statuses) - set(REVIEW_STATUSES)
    invalid_page = set(values.include_page_review_statuses) - set(REVIEW_STATUSES)
    if invalid_review or invalid_page:
        raise ValueError("Hay estados de revisión inválidos en el perfil")
    if len(values.object_separator) > 200 or len(values.page_separator) > 200:
        raise ValueError("Los separadores no pueden superar 200 caracteres")
    if values.temporal_start and values.temporal_end and values.temporal_start > values.temporal_end:
        raise ValueError("El inicio del filtro temporal es posterior al final")
    return ExportProfileValues(
        name=_clean_name(values.name),
        description=values.description.strip() if values.description and values.description.strip() else None,
        aggregation_level=values.aggregation_level,
        text_policy=values.text_policy,
        output_format=values.output_format,
        include_object_types=tuple(sorted(set(values.include_object_types))),
        include_review_statuses=tuple(sorted(set(values.include_review_statuses))),
        include_page_review_statuses=tuple(sorted(set(values.include_page_review_statuses))),
        temporal_start=values.temporal_start,
        temporal_end=values.temporal_end,
        temporal_include_undated=bool(values.temporal_include_undated),
        object_separator=values.object_separator,
        page_separator=values.page_separator,
        include_page_markers=bool(values.include_page_markers),
    )


def profile_values(profile: CorpusExportProfile) -> ExportProfileValues:
    return ExportProfileValues(
        name=profile.name,
        description=profile.description,
        aggregation_level=profile.aggregation_level,
        text_policy=profile.text_policy,
        output_format=profile.output_format,
        include_object_types=tuple(profile.include_object_types_json or []),
        include_review_statuses=tuple(profile.include_review_statuses_json or []),
        include_page_review_statuses=tuple(profile.include_page_review_statuses_json or []),
        temporal_start=profile.temporal_start,
        temporal_end=profile.temporal_end,
        temporal_include_undated=bool(profile.temporal_include_undated),
        object_separator=profile.object_separator,
        page_separator=profile.page_separator,
        include_page_markers=bool(profile.include_page_markers),
    )


def profile_snapshot(profile: CorpusExportProfile) -> dict[str, Any]:
    values = asdict(profile_values(profile))
    values.update({"id": profile.id, "revision": profile.revision})
    for key in ("include_object_types", "include_review_statuses", "include_page_review_statuses"):
        values[key] = list(values[key])
    for key in ("temporal_start", "temporal_end"):
        values[key] = values[key].isoformat() if values[key] else None
    return values


def save_export_profile(
    session: Session,
    *,
    project_id: str,
    values: ExportProfileValues,
    changed_by: str,
    profile_id: str | None = None,
) -> CorpusExportProfile:
    clean = _validate(values)
    profile = session.get(CorpusExportProfile, profile_id) if profile_id else None
    if profile is None:
        profile = session.scalar(
            select(CorpusExportProfile).where(
                CorpusExportProfile.project_id == project_id,
                CorpusExportProfile.name == clean.name,
            )
        )
    now = utc_now()
    if profile is None:
        profile = CorpusExportProfile(
            id=new_id(),
            project_id=project_id,
            name=clean.name,
            description=clean.description,
            aggregation_level=clean.aggregation_level,
            text_policy=clean.text_policy,
            output_format=clean.output_format,
            include_object_types_json=list(clean.include_object_types),
            include_review_statuses_json=list(clean.include_review_statuses),
            include_page_review_statuses_json=list(clean.include_page_review_statuses),
            temporal_start=clean.temporal_start,
            temporal_end=clean.temporal_end,
            temporal_include_undated=clean.temporal_include_undated,
            object_separator=clean.object_separator,
            page_separator=clean.page_separator,
            include_page_markers=clean.include_page_markers,
            created_by=changed_by,
            created_at=now,
            updated_by=changed_by,
            updated_at=now,
            revision=1,
        )
        session.add(profile)
    else:
        if profile.project_id != project_id:
            raise ValueError("El perfil pertenece a otro proyecto")
        duplicate = session.scalar(
            select(CorpusExportProfile).where(
                CorpusExportProfile.project_id == project_id,
                CorpusExportProfile.name == clean.name,
                CorpusExportProfile.id != profile.id,
            )
        )
        if duplicate is not None:
            raise ValueError(f"Ya existe otro perfil llamado {clean.name}")
        profile.name = clean.name
        profile.description = clean.description
        profile.aggregation_level = clean.aggregation_level
        profile.text_policy = clean.text_policy
        profile.output_format = clean.output_format
        profile.include_object_types_json = list(clean.include_object_types)
        profile.include_review_statuses_json = list(clean.include_review_statuses)
        profile.include_page_review_statuses_json = list(clean.include_page_review_statuses)
        profile.temporal_start = clean.temporal_start
        profile.temporal_end = clean.temporal_end
        profile.temporal_include_undated = clean.temporal_include_undated
        profile.object_separator = clean.object_separator
        profile.page_separator = clean.page_separator
        profile.include_page_markers = clean.include_page_markers
        profile.updated_by = changed_by
        profile.updated_at = now
        profile.revision += 1
    session.flush()
    return profile


def export_profile_rows(session: Session, *, project_id: str) -> list[CorpusExportProfile]:
    return session.scalars(
        select(CorpusExportProfile)
        .where(CorpusExportProfile.project_id == project_id)
        .order_by(CorpusExportProfile.name, CorpusExportProfile.id)
    ).all()


def resolve_export_profile(
    session: Session, *, project_id: str, profile_ref: str
) -> CorpusExportProfile:
    profile = session.scalar(
        select(CorpusExportProfile).where(
            CorpusExportProfile.project_id == project_id,
            (CorpusExportProfile.id == profile_ref) | (CorpusExportProfile.name == profile_ref),
        )
    )
    if profile is None:
        raise ValueError(f"Perfil de exportación inexistente: {profile_ref}")
    return profile


def _unit_paths(units: Iterable[ArchivalUnit]) -> dict[str, str]:
    rows = {row.id: row for row in units}
    cache: dict[str, str] = {}

    def build(unit_id: str, trail: set[str] | None = None) -> str:
        if unit_id in cache:
            return cache[unit_id]
        trail = set() if trail is None else set(trail)
        if unit_id in trail:
            return rows[unit_id].title
        trail.add(unit_id)
        row = rows[unit_id]
        value = row.title if row.parent_id not in rows else f"{build(row.parent_id, trail)} / {row.title}"
        cache[unit_id] = value
        return value

    for unit_id in rows:
        build(unit_id)
    return cache


def _selected_text(current: str, original: str | None, policy: str) -> str:
    if policy == "original_only":
        return (original or "").strip()
    if policy == "corrected_only":
        return current.strip()
    return current.strip() or (original or "").strip()


def _load_atoms(
    session: Session, *, project_id: str, values: ExportProfileValues
) -> list[_Atom]:
    object_rows = session.execute(
        select(EditableObject, EditablePage, ExtractedObject, DocumentPart)
        .join(EditablePage, EditablePage.id == EditableObject.editable_page_id)
        .outerjoin(ExtractedObject, ExtractedObject.id == EditableObject.source_extracted_object_id)
        .outerjoin(DocumentPart, DocumentPart.id == EditableObject.document_part_id)
        .where(EditableObject.lifecycle_status == "active")
        .order_by(EditableObject.digital_object_id, EditableObject.page_number, EditableObject.current_order_index)
    ).all()
    if not object_rows:
        return []
    digital_ids = {row[0].digital_object_id for row in object_rows}
    registrations = session.scalars(
        select(SourceRegistration)
        .where(
            SourceRegistration.project_id == project_id,
            SourceRegistration.digital_object_id.in_(digital_ids),
        )
        .order_by(SourceRegistration.registered_at.desc(), SourceRegistration.id.desc())
    ).all()
    registration_by_digital: dict[str, SourceRegistration] = {}
    for row in registrations:
        if row.digital_object_id is None:
            continue
        current = registration_by_digital.get(row.digital_object_id)
        if current is None or (row.archival_unit_id and not current.archival_unit_id):
            registration_by_digital[row.digital_object_id] = row

    units = session.scalars(select(ArchivalUnit).where(ArchivalUnit.project_id == project_id)).all()
    unit_by_id = {row.id: row for row in units}
    paths = _unit_paths(units)
    object_ids = [row[0].id for row in object_rows]
    tags_by_object: dict[str, list[str]] = {}
    for tag in session.scalars(
        select(EditableObjectTag).where(EditableObjectTag.editable_object_id.in_(object_ids))
    ).all():
        tags_by_object.setdefault(tag.editable_object_id, []).append(tag.tag)
    authority_records = {
        row.id: row
        for row in session.scalars(
            select(AuthorityRecord).where(
                AuthorityRecord.project_id == project_id,
                AuthorityRecord.lifecycle_status == "active",
            )
        ).all()
    }
    mentions_by_object: dict[str, list[EntityMention]] = {}
    for mention in session.scalars(
        select(EntityMention).where(
            EntityMention.editable_object_id.in_(object_ids),
            EntityMention.status.in_(("accepted", "modified")),
            EntityMention.authority_id.is_not(None),
        )
    ).all():
        if mention.authority_id in authority_records:
            mentions_by_object.setdefault(mention.editable_object_id, []).append(mention)

    relations_by_authority: dict[str, list[EntityRelation]] = {}
    for relation in session.scalars(
        select(EntityRelation).where(
            EntityRelation.project_id == project_id,
            EntityRelation.lifecycle_status == "active",
        )
    ).all():
        relations_by_authority.setdefault(relation.source_authority_id, []).append(relation)
        if relation.target_authority_id:
            relations_by_authority.setdefault(relation.target_authority_id, []).append(relation)

    allowed_types = set(values.include_object_types)
    allowed_statuses = set(values.include_review_statuses)
    allowed_page_statuses = set(values.include_page_review_statuses)
    atoms: list[_Atom] = []
    for editable, page, original, part in object_rows:
        if allowed_types and editable.current_object_type not in allowed_types:
            continue
        if allowed_statuses and editable.review_status not in allowed_statuses:
            continue
        if allowed_page_statuses and page.review_status not in allowed_page_statuses:
            continue
        object_mentions = mentions_by_object.get(editable.id, [])
        linked_authorities = [
            authority_records[mention.authority_id]
            for mention in object_mentions
            if mention.authority_id in authority_records
        ]
        linked_relations = {
            relation.id: relation
            for authority in linked_authorities
            for relation in relations_by_authority.get(authority.id, [])
        }
        if values.temporal_start is not None or values.temporal_end is not None:
            temporal_matches = [
                temporal_overlap(
                    item_start=authority.temporal_start,
                    item_end=authority.temporal_end,
                    query_start=values.temporal_start,
                    query_end=values.temporal_end,
                    include_undated=values.temporal_include_undated,
                )
                for authority in linked_authorities
            ] + [
                temporal_overlap(
                    item_start=relation.temporal_start,
                    item_end=relation.temporal_end,
                    query_start=values.temporal_start,
                    query_end=values.temporal_end,
                    include_undated=values.temporal_include_undated,
                )
                for relation in linked_relations.values()
            ]
            if not temporal_matches or not any(temporal_matches):
                continue
        text = _selected_text(
            editable.current_text,
            original.original_text if original is not None else None,
            values.text_policy,
        )
        if not text:
            continue
        registration = registration_by_digital.get(editable.digital_object_id)
        unit = unit_by_id.get(registration.archival_unit_id) if registration and registration.archival_unit_id else None
        atoms.append(
            _Atom(
                object_id=editable.id,
                digital_object_id=editable.digital_object_id,
                source_key=registration.source_key if registration else None,
                archival_unit_id=unit.id if unit else None,
                reference_code=unit.reference_code if unit else None,
                hierarchy_path=paths.get(unit.id) if unit else None,
                unit_title=unit.title if unit else None,
                part_id=part.id if part else None,
                part_key=part.part_key if part else None,
                part_title=part.title if part else None,
                page_number=editable.page_number,
                order_index=editable.current_order_index,
                object_type=editable.current_object_type,
                object_review_status=editable.review_status,
                page_review_status=page.review_status,
                text=text,
                tags=tuple(sorted(set(tags_by_object.get(editable.id, [])))),
                entities=tuple(sorted({authority.preferred_name for authority in linked_authorities})),
                entity_temporal_ranges=tuple(sorted({
                    f"{authority.preferred_name}: {display}"
                    for authority in linked_authorities
                    if (display := format_temporal_range(
                        authority.temporal_expression,
                        authority.temporal_start,
                        authority.temporal_end,
                        bool(authority.temporal_approximate),
                    ))
                })),
                relation_temporal_ranges=tuple(sorted({
                    f"{relation.relation_label}: {display}"
                    for relation in linked_relations.values()
                    if (display := format_temporal_range(
                        relation.temporal_expression,
                        relation.temporal_start,
                        relation.temporal_end,
                        bool(relation.temporal_approximate),
                    ))
                })),
            )
        )
    return atoms


def _group_key(atom: _Atom, level: str) -> tuple[str, ...]:
    if level == "object":
        return (atom.object_id,)
    if level == "page":
        return (atom.digital_object_id, str(atom.page_number))
    if level == "document_part":
        return (atom.part_id or f"unassigned:{atom.digital_object_id}",)
    if level == "archival_unit":
        return (atom.archival_unit_id or f"unassigned:{atom.digital_object_id}",)
    return (atom.digital_object_id,)


def _combine_text(atoms: list[_Atom], values: ExportProfileValues) -> str:
    chunks: list[str] = []
    last_page: int | None = None
    for atom in atoms:
        if last_page is None or atom.page_number != last_page:
            if chunks:
                chunks.append(values.page_separator)
            if values.include_page_markers:
                chunks.append(f"[Página {atom.page_number}]\n")
        elif chunks:
            chunks.append(values.object_separator)
        chunks.append(atom.text)
        last_page = atom.page_number
    return "".join(chunks).strip()


def build_export_rows(
    session: Session, *, project_id: str, profile: CorpusExportProfile
) -> list[ExportRecord]:
    values = profile_values(profile)
    atoms = _load_atoms(session, project_id=project_id, values=values)
    groups: dict[tuple[str, ...], list[_Atom]] = {}
    for atom in atoms:
        groups.setdefault(_group_key(atom, values.aggregation_level), []).append(atom)
    records: list[ExportRecord] = []
    for key, members in sorted(
        groups.items(),
        key=lambda item: (
            item[1][0].hierarchy_path or "",
            item[1][0].source_key or "",
            item[1][0].page_number,
            item[1][0].order_index,
        ),
    ):
        members.sort(key=lambda item: (item.page_number, item.order_index, item.object_id))
        first = members[0]
        if values.aggregation_level == "object":
            title = first.unit_title or first.source_key or "Objeto textual"
        elif values.aggregation_level == "page":
            title = f"{first.unit_title or first.source_key or 'Documento'} — página {first.page_number}"
        elif values.aggregation_level == "document_part":
            title = first.part_title or f"{first.unit_title or first.source_key or 'Documento'} — sin parte asignada"
        elif values.aggregation_level == "archival_unit":
            title = first.unit_title or first.source_key or "Unidad sin catálogo"
        else:
            title = first.unit_title or first.source_key or "Documento"
        record_id = f"{values.aggregation_level}:{':'.join(key)}"
        records.append(
            ExportRecord(
                record_id=record_id,
                aggregation_level=values.aggregation_level,
                codigo=record_id,
                titulo=title,
                texto=_combine_text(members, values),
                source_key=(first.source_key if all(row.source_key == first.source_key for row in members) else None),
                source_keys=sorted({row.source_key for row in members if row.source_key}),
                digital_object_id=(first.digital_object_id if all(row.digital_object_id == first.digital_object_id for row in members) else None),
                digital_object_ids=sorted({row.digital_object_id for row in members}),
                archival_unit_id=first.archival_unit_id,
                reference_code=first.reference_code,
                hierarchy_path=first.hierarchy_path,
                document_part_id=first.part_id if all(row.part_id == first.part_id for row in members) else None,
                document_part_key=first.part_key if all(row.part_key == first.part_key for row in members) else None,
                document_part_title=first.part_title if all(row.part_title == first.part_title for row in members) else None,
                page_start=min(row.page_number for row in members),
                page_end=max(row.page_number for row in members),
                object_count=len(members),
                object_ids=[row.object_id for row in members],
                object_types=sorted({row.object_type for row in members}),
                object_review_statuses=sorted({row.object_review_status for row in members}),
                page_review_statuses=sorted({row.page_review_status for row in members}),
                tags=sorted({tag for row in members for tag in row.tags}),
                entities=sorted({entity for row in members for entity in row.entities}),
                entity_temporal_ranges=sorted({
                    item for row in members for item in row.entity_temporal_ranges
                }),
                relation_temporal_ranges=sorted({
                    item for row in members for item in row.relation_temporal_ranges
                }),
            )
        )
    return records


def preview_export(
    session: Session, *, project_id: str, profile: CorpusExportProfile, limit: int = 20
) -> ExportPreview:
    rows = build_export_rows(session, project_id=project_id, profile=profile)
    return ExportPreview(
        total_records=len(rows),
        total_characters=sum(len(row.texto) for row in rows),
        records=rows[: max(0, limit)],
    )


def _safe_output_path(project_root: Path, relative_path: str, output_format: str) -> tuple[Path, str]:
    raw = relative_path.strip()
    if not raw:
        raise ValueError("Indicá una ruta de salida relativa a project_data")
    candidate = (project_root / raw).resolve()
    try:
        relative = candidate.relative_to(project_root.resolve())
    except ValueError as exc:
        raise ValueError("La exportación debe quedar dentro de project_data") from exc
    extension = f".{output_format}"
    if candidate.suffix.lower() != extension:
        candidate = candidate.with_suffix(extension)
        relative = candidate.relative_to(project_root.resolve())
    return candidate, relative.as_posix()


def _jsonable_record(record: ExportRecord) -> dict[str, Any]:
    return asdict(record)


def _write_jsonl(path: Path, rows: list[ExportRecord]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(_jsonable_record(row), ensure_ascii=False, sort_keys=True) + "\n")


def _write_csv(path: Path, rows: list[ExportRecord]) -> None:
    fieldnames = list(asdict(rows[0]).keys()) if rows else list(ExportRecord.__dataclass_fields__)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            payload = _jsonable_record(row)
            for key in (
                "source_keys", "digital_object_ids", "object_ids", "object_types", "object_review_statuses",
                "page_review_statuses", "tags", "entities", "entity_temporal_ranges",
                "relation_temporal_ranges",
            ):
                payload[key] = json.dumps(payload[key], ensure_ascii=False)
            writer.writerow(payload)


def run_export(
    session: Session,
    *,
    project_root: Path,
    project_id: str,
    profile: CorpusExportProfile,
    output_relative_path: str,
    created_by: str,
    output_format: str | None = None,
    overwrite: bool = False,
) -> ExportRunResult:
    selected_format = output_format or profile.output_format
    if selected_format not in OUTPUT_FORMATS:
        raise ValueError("Formato de salida inválido")
    rows = build_export_rows(session, project_id=project_id, profile=profile)
    output_path, relative = _safe_output_path(project_root, output_relative_path, selected_format)
    if output_path.exists() and not overwrite:
        raise ValueError(
            f"La salida ya existe: {relative}. Elegí otro nombre o habilitá sobrescritura explícita."
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_name(output_path.name + ".tmp")
    try:
        if selected_format == "jsonl":
            _write_jsonl(temporary, rows)
        else:
            _write_csv(temporary, rows)
        temporary.replace(output_path)
    finally:
        temporary.unlink(missing_ok=True)
    digest = hashlib.sha256(output_path.read_bytes()).hexdigest()
    state_digest = current_editable_state_sha256(session, project_id)
    run = CorpusExportRun(
        id=new_id(),
        project_id=project_id,
        profile_id=profile.id,
        profile_name=profile.name,
        profile_snapshot_json=profile_snapshot(profile),
        corpus_state_sha256=state_digest,
        output_format=selected_format,
        output_relative_path=relative,
        row_count=len(rows),
        character_count=sum(len(row.texto) for row in rows),
        byte_size=output_path.stat().st_size,
        output_sha256=digest,
        created_by=created_by,
        created_at=utc_now(),
    )
    session.add(run)
    session.flush()
    return ExportRunResult(
        run_id=run.id,
        output_path=output_path,
        row_count=run.row_count,
        character_count=run.character_count,
        byte_size=run.byte_size,
        output_sha256=digest,
        corpus_state_sha256=state_digest,
    )


def export_run_rows(session: Session, *, project_id: str) -> list[ExportRunRow]:
    rows = session.scalars(
        select(CorpusExportRun)
        .where(CorpusExportRun.project_id == project_id)
        .order_by(CorpusExportRun.created_at.desc(), CorpusExportRun.id.desc())
    ).all()
    return [
        ExportRunRow(
            run_id=row.id,
            profile_name=row.profile_name,
            output_format=row.output_format,
            output_relative_path=row.output_relative_path,
            row_count=row.row_count,
            character_count=row.character_count,
            byte_size=row.byte_size,
            output_sha256=row.output_sha256,
            corpus_state_sha256=row.corpus_state_sha256,
            created_by=row.created_by,
            created_at=row.created_at,
        )
        for row in rows
    ]


def default_export_filename(profile_name: str, output_format: str, now: datetime | None = None) -> str:
    timestamp = (now or utc_now()).strftime("%Y%m%dT%H%M%SZ")
    slug = re.sub(r"[^a-z0-9]+", "_", profile_name.casefold()).strip("_") or "corpus"
    return f"exports/{slug}_{timestamp}.{output_format}"
