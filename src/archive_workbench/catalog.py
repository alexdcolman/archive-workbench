from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from sqlalchemy import func, inspect as sa_inspect, select
from sqlalchemy.orm import Session

from archive_workbench.contracts.decisions import ProjectDecisions
from archive_workbench.contracts.test_corpus import TestCorpus, TestDocument
from archive_workbench.db.models import (
    ArchivalUnit,
    ArchivalUnitRevision,
    AudiovisualDerivativeAsset,
    AudiovisualMedia,
    DigitalObject,
    DerivativeAsset,
    DigitalObjectUnitLink,
    DocumentPart,
    DocumentProcessingPlanRecord,
    EditableObject,
    EditableObjectComment,
    EditableObjectRevision,
    EditableObjectTag,
    EditablePage,
    EditablePageAction,
    PageProcessingAssignmentRecord,
    FileInstance,
    ExtractedObject,
    ExtractionPage,
    ExtractionRegion,
    ExtractionRun,
    SegmentEntityMention,
    PreprocessingRun,
    Project,
    SourceRegistration,
    TranscriptSegment,
    TranscriptSegmentRevision,
    TranscriptionRun,
)
from archive_workbench.domain.enums import FilePresence
from archive_workbench.identity import stable_id
from archive_workbench.inspection import inspect_input

_APP_NAMESPACE = UUID("aa1554a0-993d-4cf8-b2cc-82720464079f")


@dataclass(slots=True)
class RegistrationSummary:
    documents_seen: int = 0
    documents_registered: int = 0
    missing_files: int = 0
    digital_objects_created: int = 0
    digital_objects_reused: int = 0
    file_instances_created: int = 0
    file_instances_updated: int = 0
    archival_units_created: int = 0
    archival_units_reused: int = 0
    links_created: int = 0


@dataclass(slots=True)
class ScanSummary:
    checked: int = 0
    present: int = 0
    missing: int = 0
    modified: int = 0


def ensure_project(session: Session, decisions: ProjectDecisions) -> Project:
    project = session.get(Project, decisions.project_id)
    payload = decisions.model_dump(mode="json")
    if project is None:
        project = Project(
            id=decisions.project_id,
            name=decisions.project_name,
            decisions_schema_version="1.0",
            decisions_json=payload,
        )
        session.add(project)
    else:
        project.name = decisions.project_name
        project.decisions_json = payload
        project.updated_at = datetime.now(timezone.utc)
    session.flush()
    return project


def _unit_id(
    project_id: str,
    parent_id: str | None,
    level_key: str,
    identity_hint: str,
) -> str:
    return stable_id(
        _APP_NAMESPACE,
        "archival_unit",
        project_id,
        parent_id or "root",
        level_key,
        identity_hint,
    )


def _digital_object_id(project_id: str, sha256: str) -> str:
    return stable_id(_APP_NAMESPACE, "digital_object", project_id, sha256)


def _file_instance_id(storage_root: str, relative_path: str) -> str:
    return stable_id(_APP_NAMESPACE, "file_instance", storage_root, relative_path)


def _link_id(digital_object_id: str, archival_unit_id: str) -> str:
    return stable_id(_APP_NAMESPACE, "digital_object_unit_link", digital_object_id, archival_unit_id)


def _source_registration_id(project_id: str, source_type: str, source_key: str) -> str:
    return stable_id(_APP_NAMESPACE, "source_registration", project_id, source_type, source_key)


def _get_or_create_unit(
    session: Session,
    *,
    project_id: str,
    parent_id: str | None,
    level_key: str,
    title: str,
    actor: str,
    identity_hint: str | None = None,
) -> tuple[ArchivalUnit, bool]:
    identifier = _unit_id(project_id, parent_id, level_key, identity_hint or title)
    unit = session.get(ArchivalUnit, identifier)
    if unit is not None:
        if unit.title != title:
            unit.title = title
            unit.updated_by = actor
            unit.updated_at = datetime.now(timezone.utc)
            unit.revision += 1
        return unit, False
    unit = ArchivalUnit(
        id=identifier,
        project_id=project_id,
        parent_id=parent_id,
        level_key=level_key,
        title=title,
        registration_status="incomplete",
        completion_confirmed=False,
        created_by=actor,
        updated_by=actor,
    )
    session.add(unit)
    session.flush()
    return unit, True


def _build_archival_path(
    session: Session,
    decisions: ProjectDecisions,
    document: TestDocument,
    actor: str,
) -> tuple[ArchivalUnit, int, int]:
    ordered_levels = sorted(
        (level for level in decisions.archival_levels if level.enabled),
        key=lambda item: item.display_order,
    )
    location = document.archival_location
    parent_id: str | None = None
    final_unit: ArchivalUnit | None = None
    created = 0
    reused = 0

    for level in ordered_levels:
        raw_value: str | int | None
        if level.key == "archivo":
            raw_value = decisions.project_name
        elif level.key == "documento":
            raw_value = location.get(level.key) or document.short_description
        else:
            raw_value = location.get(level.key)
        if raw_value is None or str(raw_value).strip() == "":
            continue
        title = str(raw_value).strip()
        identity_hint = (
            f"test_corpus:{document.test_id}" if level.key == "documento" else None
        )
        unit, was_created = _get_or_create_unit(
            session,
            project_id=decisions.project_id,
            parent_id=parent_id,
            level_key=level.key,
            title=title,
            actor=actor,
            identity_hint=identity_hint,
        )
        if was_created:
            created += 1
        else:
            reused += 1
        final_unit = unit
        parent_id = unit.id

    if final_unit is None:
        raise ValueError(f"{document.test_id}: no se pudo construir ninguna unidad archivística")
    return final_unit, created, reused


def register_test_corpus(
    session: Session,
    *,
    project_root: str | Path,
    decisions: ProjectDecisions,
    corpus: TestCorpus,
    allow_missing: bool = False,
) -> RegistrationSummary:
    root = Path(project_root)
    ensure_project(session, decisions)
    summary = RegistrationSummary()

    for document in corpus.documents:
        summary.documents_seen += 1
        source_path = root / document.local_path
        if not source_path.is_file():
            summary.missing_files += 1
            if allow_missing:
                continue
            raise FileNotFoundError(f"{document.test_id}: no existe {source_path}")

        inspection = inspect_input(source_path)
        digital_id = _digital_object_id(decisions.project_id, inspection.sha256)
        digital = session.get(DigitalObject, digital_id)
        if digital is None:
            digital = DigitalObject(
                id=digital_id,
                project_id=decisions.project_id,
                media_type=inspection.media_type.value,
                original_filename=source_path.name,
                sha256=inspection.sha256,
                byte_size=inspection.byte_size,
                page_count=inspection.page_count,
            )
            session.add(digital)
            session.flush()
            summary.digital_objects_created += 1
        else:
            summary.digital_objects_reused += 1

        relative_path = document.local_path.replace("\\", "/")
        file_id = _file_instance_id("project", relative_path)
        file_instance = session.get(FileInstance, file_id)
        stat = source_path.stat()
        if file_instance is None:
            file_instance = FileInstance(
                id=file_id,
                digital_object_id=digital.id,
                storage_root="project",
                relative_path=relative_path,
                presence=FilePresence.PRESENT.value,
                byte_size_seen=stat.st_size,
                mtime_ns=stat.st_mtime_ns,
                last_seen_at=datetime.now(timezone.utc),
                verified_sha256=inspection.sha256,
            )
            session.add(file_instance)
            summary.file_instances_created += 1
        else:
            file_instance.digital_object_id = digital.id
            file_instance.presence = FilePresence.PRESENT.value
            file_instance.byte_size_seen = stat.st_size
            file_instance.mtime_ns = stat.st_mtime_ns
            file_instance.last_seen_at = datetime.now(timezone.utc)
            file_instance.verified_sha256 = inspection.sha256
            summary.file_instances_updated += 1

        final_unit, created_units, reused_units = _build_archival_path(
            session, decisions, document, corpus.created_by
        )
        summary.archival_units_created += created_units
        summary.archival_units_reused += reused_units

        link_id = _link_id(digital.id, final_unit.id)
        if session.get(DigitalObjectUnitLink, link_id) is None:
            session.add(
                DigitalObjectUnitLink(
                    id=link_id,
                    digital_object_id=digital.id,
                    archival_unit_id=final_unit.id,
                    relation_type="represents",
                )
            )
            summary.links_created += 1

        source_id = _source_registration_id(
            decisions.project_id, "test_corpus", document.test_id
        )
        registration = session.get(SourceRegistration, source_id)
        payload = document.model_dump(mode="json")
        if registration is None:
            registration = SourceRegistration(
                id=source_id,
                project_id=decisions.project_id,
                source_type="test_corpus",
                source_key=document.test_id,
                digital_object_id=digital.id,
                archival_unit_id=final_unit.id,
                source_payload_json=payload,
                registered_by=corpus.created_by,
            )
            session.add(registration)
        else:
            registration.digital_object_id = digital.id
            registration.archival_unit_id = final_unit.id
            registration.source_payload_json = payload
            registration.registered_at = datetime.now(timezone.utc)
            registration.registered_by = corpus.created_by

        summary.documents_registered += 1

    session.flush()
    return summary


def scan_file_instances(session: Session, project_root: str | Path) -> ScanSummary:
    root = Path(project_root)
    summary = ScanSummary()
    rows = session.execute(
        select(FileInstance, DigitalObject).join(
            DigitalObject, FileInstance.digital_object_id == DigitalObject.id
        )
    ).all()

    for file_instance, digital in rows:
        summary.checked += 1
        path = root / file_instance.relative_path
        if not path.is_file():
            file_instance.presence = FilePresence.MISSING.value
            file_instance.last_seen_at = datetime.now(timezone.utc)
            summary.missing += 1
            continue

        inspection = inspect_input(path)
        stat = path.stat()
        file_instance.byte_size_seen = stat.st_size
        file_instance.mtime_ns = stat.st_mtime_ns
        file_instance.last_seen_at = datetime.now(timezone.utc)
        file_instance.verified_sha256 = inspection.sha256
        if inspection.sha256 == digital.sha256:
            file_instance.presence = FilePresence.PRESENT.value
            summary.present += 1
        else:
            file_instance.presence = FilePresence.MODIFIED.value
            summary.modified += 1
    session.flush()
    return summary


def database_counts(session: Session) -> dict[str, int]:
    models = {
        "projects": Project,
        "archival_units": ArchivalUnit,
        "archival_unit_revisions": ArchivalUnitRevision,
        "digital_objects": DigitalObject,
        "file_instances": FileInstance,
        "digital_object_unit_links": DigitalObjectUnitLink,
        "source_registrations": SourceRegistration,
        "preprocessing_runs": PreprocessingRun,
        "derivative_assets": DerivativeAsset,
        "extraction_runs": ExtractionRun,
        "extraction_pages": ExtractionPage,
        "extraction_regions": ExtractionRegion,
        "extracted_objects": ExtractedObject,
        "document_parts": DocumentPart,
        "document_processing_plans": DocumentProcessingPlanRecord,
        "page_processing_assignments": PageProcessingAssignmentRecord,
        "editable_pages": EditablePage,
        "editable_objects": EditableObject,
        "editable_object_revisions": EditableObjectRevision,
        "editable_page_actions": EditablePageAction,
        "editable_object_comments": EditableObjectComment,
        "editable_object_tags": EditableObjectTag,
        "audiovisual_media": AudiovisualMedia,
        "audiovisual_derivative_assets": AudiovisualDerivativeAsset,
        "transcription_runs": TranscriptionRun,
        "transcript_segments": TranscriptSegment,
        "transcript_segment_revisions": TranscriptSegmentRevision,
        "segment_entity_mentions": SegmentEntityMention,
    }
    inspector = sa_inspect(session.get_bind())
    return {
        key: int(session.scalar(select(func.count()).select_from(model)) or 0)
        for key, model in models.items()
        if inspector.has_table(model.__tablename__)
    }


@dataclass(slots=True)
class InventoryRow:
    source_key: str
    title: str
    registration_status: str
    media_type: str | None
    page_count: int | None
    presence: str | None
    relative_path: str | None


def inventory_rows(session: Session) -> list[InventoryRow]:
    statement = (
        select(
            SourceRegistration.source_key,
            ArchivalUnit.title,
            ArchivalUnit.registration_status,
            DigitalObject.media_type,
            DigitalObject.page_count,
            FileInstance.presence,
            FileInstance.relative_path,
        )
        .join(ArchivalUnit, SourceRegistration.archival_unit_id == ArchivalUnit.id)
        .outerjoin(DigitalObject, SourceRegistration.digital_object_id == DigitalObject.id)
        .outerjoin(FileInstance, FileInstance.digital_object_id == DigitalObject.id)
        .order_by(SourceRegistration.source_key, FileInstance.relative_path)
    )
    seen: set[str] = set()
    result: list[InventoryRow] = []
    for row in session.execute(statement):
        if row.source_key in seen:
            continue
        seen.add(row.source_key)
        result.append(
            InventoryRow(
                source_key=row.source_key,
                title=row.title,
                registration_status=row.registration_status,
                media_type=row.media_type,
                page_count=row.page_count,
                presence=row.presence,
                relative_path=row.relative_path,
            )
        )
    return result
