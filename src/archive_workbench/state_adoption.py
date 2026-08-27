from __future__ import annotations

import hashlib
import json
import zipfile
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from archive_workbench.db import create_sqlite_engine, database_path, session_scope
from archive_workbench.db.migrations import current_revision, require_current_database
from archive_workbench.db.models import (
    ArchivalFieldValue,
    ArchivalUnit,
    AudiovisualMedia,
    AudiovisualTimelineAnnotation,
    AudiovisualTimelineAnnotationRevision,
    AuthorityAlias,
    AuthorityRecord,
    DigitalObject,
    DigitalObjectUnitLink,
    DocumentPart,
    EditableObject,
    EditableObjectComment,
    EditableObjectTag,
    EditablePage,
    EditablePageAction,
    EntityMention,
    SegmentEntityMention,
    EntityRelation,
    ExchangeChangeEvent,
    ExchangeCommonBaseAgreement,
    ExchangeDryRun,
    ExchangeStateAdoption,
    ExchangeStateAdoptionRollback,
    ExchangeWorkspace,
    ExtractedObject,
    ExtractionPage,
    ExtractionPageSelection,
    ExtractionRun,
    Project,
    TranscriptSegment,
    TranscriptSegmentRevision,
    TranscriptionRun,
    WorkAssignment,
    utc_now,
)
from archive_workbench.exchange import (
    _editable_state_payload,
    current_editable_state_sha256,
    ensure_exchange_workspace,
)
from archive_workbench.identity import new_id, sha256_file, sha256_json, short_id, slugify
from archive_workbench.project_admin import (
    create_project_backup,
    inspect_project_backup,
    restore_project_backup,
)
from archive_workbench.version import __version__


STATE_ADOPTION_SCHEMA_VERSION = "1.2"
BASE_STATE_SECTIONS = (
    "selections",
    "pages",
    "objects",
    "comments",
    "tags",
    "page_actions",
    "authorities",
    "entity_mentions",
    "entity_relations",
    "work_assignments",
    "catalog_units",
    "digital_links",
)
AUDIOVISUAL_STATE_SECTIONS = (
    "audiovisual_media",
    "transcription_runs",
    "transcript_segments",
    "transcript_segment_revisions",
    "segment_entity_mentions",
)
TIMELINE_STATE_SECTIONS = (
    "audiovisual_timeline_annotations",
    "audiovisual_timeline_annotation_revisions",
)
STATE_SECTIONS_V11 = BASE_STATE_SECTIONS + AUDIOVISUAL_STATE_SECTIONS
STATE_SECTIONS_V12 = STATE_SECTIONS_V11 + TIMELINE_STATE_SECTIONS
STATE_SECTIONS = STATE_SECTIONS_V12


def _sections_for_state(state: dict[str, Any]) -> tuple[str, ...]:
    if any(section in state for section in TIMELINE_STATE_SECTIONS):
        return STATE_SECTIONS_V12
    if any(section in state for section in AUDIOVISUAL_STATE_SECTIONS):
        return STATE_SECTIONS_V11
    return BASE_STATE_SECTIONS


def _sections_for_schema(schema_version: str) -> tuple[str, ...]:
    if schema_version == "1.2":
        return STATE_SECTIONS_V12
    if schema_version == "1.1":
        return STATE_SECTIONS_V11
    return BASE_STATE_SECTIONS


class StateAdoptionManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0", "1.1", "1.2"] = STATE_ADOPTION_SCHEMA_VERSION
    artifact_type: Literal["state_adoption_package"] = "state_adoption_package"
    adoption_id: str = Field(min_length=36, max_length=36)
    project_id: str
    source_workspace_id: str = Field(min_length=36, max_length=36)
    source_workspace_name: str
    source_sequence: int = Field(ge=0)
    target_workspace_id: str = Field(min_length=36, max_length=36)
    target_workspace_name: str
    state_sha256: str = Field(min_length=64, max_length=64)
    foundation_sha256: str = Field(min_length=64, max_length=64)
    section_counts: dict[str, int]
    created_by: str
    creation_reason: str
    app_version: str
    database_revision: str
    created_at: datetime


@dataclass(slots=True)
class StateSectionImpact:
    section: str
    local_count: int
    incoming_count: int
    added: int
    removed: int
    changed: int
    unchanged: int


@dataclass(slots=True)
class StateAdoptionPackageSummary:
    adoption_id: str
    output_path: Path
    package_sha256: str
    manifest_sha256: str
    state_sha256: str
    foundation_sha256: str
    source_workspace_id: str
    target_workspace_id: str
    source_sequence: int
    section_counts: dict[str, int]


@dataclass(slots=True)
class StateAdoptionPreview:
    adoption_id: str
    package_path: Path
    package_sha256: str
    manifest_sha256: str
    project_id: str
    source_workspace_id: str
    source_workspace_name: str
    source_sequence: int
    target_workspace_id: str
    target_workspace_name: str
    local_state_sha256: str
    incoming_state_sha256: str
    foundation_sha256: str
    sections: list[StateSectionImpact]

    @property
    def total_added(self) -> int:
        return sum(row.added for row in self.sections)

    @property
    def total_removed(self) -> int:
        return sum(row.removed for row in self.sections)

    @property
    def total_changed(self) -> int:
        return sum(row.changed for row in self.sections)

    @property
    def is_identical(self) -> bool:
        return self.local_state_sha256 == self.incoming_state_sha256


@dataclass(slots=True)
class StateAdoptionSummary:
    adoption_id: str
    record_id: str
    previous_state_sha256: str
    adopted_state_sha256: str
    backup_path: Path
    backup_sha256: str
    package_sha256: str
    stale_dry_run_count: int
    impact: dict[str, Any]


@dataclass(slots=True)
class StateAdoptionRollbackSummary:
    adoption_id: str
    adoption_record_id: str
    rollback_record_id: str
    restored_state_sha256: str
    restored_backup: Path
    safety_backup: Path
    safety_backup_sha256: str
    stale_dry_run_count: int


@dataclass(slots=True)
class StateAdoptionRow:
    adoption_id: str
    record_id: str
    source_workspace_id: str
    source_workspace_name: str
    source_sequence: int
    previous_state_sha256: str
    adopted_state_sha256: str
    package_sha256: str
    backup_path: str
    applied_by: str
    application_reason: str
    source: str
    applied_at: datetime
    rolled_back: bool
    rolled_back_by: str | None
    rollback_reason: str | None
    rolled_back_at: datetime | None


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _manifest_bytes(model: BaseModel) -> bytes:
    return _canonical_json_bytes(model.model_dump(mode="json", exclude_none=True)) + b"\n"


def _write_zip(path: Path, entries: dict[str, bytes]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    with zipfile.ZipFile(temp, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name in sorted(entries):
            info = zipfile.ZipInfo(name)
            info.date_time = (1980, 1, 1, 0, 0, 0)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o600 << 16
            archive.writestr(info, entries[name])
    temp.replace(path)


def _checksum_bytes(entries: dict[str, bytes]) -> bytes:
    return "".join(
        f"{hashlib.sha256(entries[name]).hexdigest()}  {name}\n"
        for name in sorted(entries)
    ).encode("utf-8")


def _read_verified_package(
    path: Path,
) -> tuple[StateAdoptionManifest, dict[str, Any], str, str]:
    artifact = path.expanduser().resolve()
    if not artifact.is_file():
        raise ValueError(f"No existe el paquete de estado: {artifact}")
    allowed = {"README.txt", "checksums.sha256", "manifest.json", "state.json"}
    try:
        with zipfile.ZipFile(artifact, "r") as archive:
            names = set(archive.namelist())
            unsafe = [
                name
                for name in names
                if Path(name).is_absolute() or ".." in Path(name).parts
            ]
            if unsafe:
                raise ValueError("El ZIP contiene rutas inseguras")
            if names != allowed:
                missing = sorted(allowed - names)
                extra = sorted(names - allowed)
                raise ValueError(
                    "El paquete no contiene exactamente los archivos esperados. "
                    f"Faltantes: {missing or '-'}; adicionales: {extra or '-'}"
                )
            entries = {name: archive.read(name) for name in names}
    except zipfile.BadZipFile as exc:
        raise ValueError("El paquete no es un ZIP válido") from exc

    expected: dict[str, str] = {}
    for raw in entries["checksums.sha256"].decode("utf-8").splitlines():
        if not raw.strip():
            continue
        pieces = raw.split(maxsplit=1)
        if len(pieces) != 2:
            raise ValueError("El archivo de checksums es inválido")
        expected[pieces[1].strip()] = pieces[0].strip().lower()
    if set(expected) != {"manifest.json", "state.json"}:
        raise ValueError("El archivo de checksums no cubre exactamente los manifiestos")
    for name in expected:
        if hashlib.sha256(entries[name]).hexdigest() != expected[name]:
            raise ValueError(f"El checksum no coincide para {name}")

    try:
        manifest = StateAdoptionManifest.model_validate_json(entries["manifest.json"])
        state = json.loads(entries["state.json"].decode("utf-8"))
    except Exception as exc:
        raise ValueError("El paquete no cumple el contrato de estado 1.0") from exc
    if not isinstance(state, dict):
        raise ValueError("state.json debe contener un objeto JSON")
    sections = _sections_for_schema(manifest.schema_version)
    if set(state) != {"project_id", *sections}:
        raise ValueError("state.json no contiene exactamente las secciones esperadas")
    if state.get("project_id") != manifest.project_id:
        raise ValueError("El proyecto de state.json no coincide con el manifiesto")
    observed_state_sha = sha256_json(state)
    if observed_state_sha != manifest.state_sha256:
        raise ValueError("La huella del estado no coincide con el manifiesto")
    observed_counts = {section: len(state.get(section) or []) for section in sections}
    if observed_counts != manifest.section_counts:
        raise ValueError("Las cantidades declaradas no coinciden con state.json")
    return (
        manifest,
        state,
        hashlib.sha256(entries["manifest.json"]).hexdigest(),
        sha256_file(artifact),
    )


def _single_project(session: Session) -> Project:
    rows = session.scalars(select(Project).order_by(Project.created_at, Project.id)).all()
    if not rows:
        raise ValueError("El proyecto todavía no está registrado en SQLite")
    if len(rows) != 1:
        raise ValueError("La base contiene más de un proyecto")
    return rows[0]


def _existing_workspace(session: Session, project_id: str) -> ExchangeWorkspace:
    workspace = session.scalar(
        select(ExchangeWorkspace).where(ExchangeWorkspace.project_id == project_id)
    )
    if workspace is None:
        raise ValueError("La copia todavía no tiene identidad de intercambio")
    return workspace


def _current_sequence(session: Session, workspace_id: str) -> int:
    return int(
        session.scalar(
            select(func.max(ExchangeChangeEvent.sequence_number)).where(
                ExchangeChangeEvent.workspace_id == workspace_id
            )
        )
        or 0
    )


def _referenced_ids(state: dict[str, Any]) -> dict[str, set[str]]:
    digital_ids: set[str] = set()
    run_ids: set[str] = set()
    page_ids: set[str] = set()
    extracted_ids: set[str] = set()
    part_ids: set[str] = set()
    for row in state["selections"]:
        digital_ids.add(row["digital_object_id"])
        run_ids.add(row["extraction_run_id"])
        page_ids.add(row["extraction_page_id"])
    for row in state["pages"]:
        digital_ids.add(row["digital_object_id"])
        run_ids.add(row["source_extraction_run_id"])
        page_ids.add(row["source_extraction_page_id"])
    for row in state["objects"]:
        digital_ids.add(row["digital_object_id"])
        if row.get("source_extracted_object_id"):
            extracted_ids.add(row["source_extracted_object_id"])
        if row.get("document_part_id"):
            part_ids.add(row["document_part_id"])
    for row in state["digital_links"]:
        digital_ids.add(row["digital_object_id"])
    for row in state.get("audiovisual_media", []):
        digital_ids.add(row["digital_object_id"])
    for row in state["entity_relations"]:
        if row.get("target_document_part_id"):
            part_ids.add(row["target_document_part_id"])
    return {
        "digital_objects": digital_ids,
        "extraction_runs": run_ids,
        "extraction_pages": page_ids,
        "extracted_objects": extracted_ids,
        "document_parts": part_ids,
    }


def _require_rows(
    session: Session,
    model: type,
    ids: set[str],
    *,
    label: str,
) -> list[Any]:
    if not ids:
        return []
    rows = session.scalars(select(model).where(model.id.in_(ids)).order_by(model.id)).all()
    observed = {row.id for row in rows}
    missing = sorted(ids - observed)
    if missing:
        raise ValueError(f"Faltan referencias de base para {label}: {missing[:5]}")
    return rows


def _foundation_payload(session: Session, state: dict[str, Any]) -> dict[str, Any]:
    project = _single_project(session)
    refs = _referenced_ids(state)
    digitals = _require_rows(
        session, DigitalObject, refs["digital_objects"], label="objetos digitales"
    )
    runs = _require_rows(session, ExtractionRun, refs["extraction_runs"], label="corridas OCR")
    pages = _require_rows(
        session, ExtractionPage, refs["extraction_pages"], label="páginas OCR"
    )
    extracted = _require_rows(
        session, ExtractedObject, refs["extracted_objects"], label="objetos OCR"
    )
    parts = _require_rows(
        session, DocumentPart, refs["document_parts"], label="partes documentales"
    )
    return {
        "project_id": project.id,
        "decisions_schema_version": project.decisions_schema_version,
        "decisions_sha256": sha256_json(project.decisions_json),
        "digital_objects": [
            {
                "id": row.id,
                "project_id": row.project_id,
                "media_type": row.media_type,
                "original_filename": row.original_filename,
                "sha256": row.sha256,
                "byte_size": row.byte_size,
                "page_count": row.page_count,
            }
            for row in digitals
        ],
        "extraction_runs": [
            {
                "id": row.id,
                "digital_object_id": row.digital_object_id,
                "source_sha256": row.source_sha256,
                "options_hash": row.options_hash,
                "engine": row.engine,
                "engine_version": row.engine_version,
            }
            for row in runs
        ],
        "extraction_pages": [
            {
                "id": row.id,
                "extraction_run_id": row.extraction_run_id,
                "page_number": row.page_number,
            }
            for row in pages
        ],
        "extracted_objects": [
            {
                "id": row.id,
                "origin_id": row.origin_id,
                "extraction_run_id": row.extraction_run_id,
                "digital_object_id": row.digital_object_id,
                "page_number": row.page_number,
                "order_index": row.order_index,
                "object_type": row.object_type,
                "original_text": row.original_text,
                "geometry": row.geometry_json or [],
                "attributes": row.attributes_json or {},
            }
            for row in extracted
        ],
        "document_parts": [
            {
                "id": row.id,
                "digital_object_id": row.digital_object_id,
                "part_key": row.part_key,
                "page_start": row.page_start,
                "page_end": row.page_end,
                "page_sequence": row.page_sequence_json or [],
            }
            for row in parts
        ],
    }


def _foundation_sha256(session: Session, state: dict[str, Any]) -> str:
    return sha256_json(_foundation_payload(session, state))


def create_state_adoption_package(
    session: Session,
    *,
    project_root: Path,
    target_workspace_id: str,
    target_workspace_name: str,
    created_by: str,
    creation_reason: str,
    package_confirmed: bool,
    destination: Path | None = None,
) -> StateAdoptionPackageSummary:
    actor = created_by.strip()
    reason = creation_reason.strip()
    target_id = target_workspace_id.strip()
    target_name = target_workspace_name.strip()
    if not package_confirmed:
        raise ValueError("Marcá la confirmación antes de crear el paquete de estado")
    if not actor:
        raise ValueError("Indicá quién crea el paquete de estado")
    if not reason:
        raise ValueError("Escribí el fundamento del paquete de estado")
    if not target_id or not target_name:
        raise ValueError("Indicá la identidad completa de la copia destinataria")

    project = _single_project(session)
    workspace = ensure_exchange_workspace(session, changed_by=actor)
    if workspace.id == target_id:
        raise ValueError("El paquete debe dirigirse a otra copia")
    state = _editable_state_payload(session, project.id)
    state_sha = sha256_json(state)
    foundation_sha = _foundation_sha256(session, state)
    adoption_id = new_id()
    sequence = _current_sequence(session, workspace.id)
    sections = _sections_for_state(state)
    schema_version = (
        "1.2"
        if sections == STATE_SECTIONS_V12
        else "1.1"
        if sections == STATE_SECTIONS_V11
        else "1.0"
    )
    section_counts = {section: len(state[section]) for section in sections}
    manifest = StateAdoptionManifest(
        schema_version=schema_version,
        adoption_id=adoption_id,
        project_id=project.id,
        source_workspace_id=workspace.id,
        source_workspace_name=workspace.workspace_name,
        source_sequence=sequence,
        target_workspace_id=target_id,
        target_workspace_name=target_name,
        state_sha256=state_sha,
        foundation_sha256=foundation_sha,
        section_counts=section_counts,
        created_by=actor,
        creation_reason=reason,
        app_version=__version__,
        database_revision=current_revision(project_root) or "unknown",
        created_at=datetime.now(timezone.utc),
    )
    manifest_bytes = _manifest_bytes(manifest)
    state_bytes = _canonical_json_bytes(state) + b"\n"
    if destination is None:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        destination = (
            project_root.resolve()
            / "exchange"
            / "state_adoption"
            / "outgoing"
            / f"{stamp}_{slugify(workspace.workspace_name, 28)}_{short_id(adoption_id)}_state.zip"
        )
    destination = destination.expanduser().resolve()
    payloads = {"manifest.json": manifest_bytes, "state.json": state_bytes}
    _write_zip(
        destination,
        {
            "README.txt": (
                "Archive Workbench — paquete completo de estado editable\n"
                "Debe previsualizarse y aplicarse únicamente en la copia destinataria indicada.\n"
            ).encode("utf-8"),
            "checksums.sha256": _checksum_bytes(payloads),
            **payloads,
        },
    )
    return StateAdoptionPackageSummary(
        adoption_id=adoption_id,
        output_path=destination,
        package_sha256=sha256_file(destination),
        manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
        state_sha256=state_sha,
        foundation_sha256=foundation_sha,
        source_workspace_id=workspace.id,
        target_workspace_id=target_id,
        source_sequence=sequence,
        section_counts=section_counts,
    )


def _section_map(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(row["id"]): row for row in rows}


def _impact(local_state: dict[str, Any], incoming_state: dict[str, Any]) -> list[StateSectionImpact]:
    result: list[StateSectionImpact] = []
    for section in _sections_for_state(incoming_state):
        local = _section_map(local_state.get(section, []))
        incoming = _section_map(incoming_state.get(section, []))
        local_ids = set(local)
        incoming_ids = set(incoming)
        common = local_ids & incoming_ids
        changed = sum(local[item] != incoming[item] for item in common)
        result.append(
            StateSectionImpact(
                section=section,
                local_count=len(local),
                incoming_count=len(incoming),
                added=len(incoming_ids - local_ids),
                removed=len(local_ids - incoming_ids),
                changed=changed,
                unchanged=len(common) - changed,
            )
        )
    return result


def preview_state_adoption(
    session: Session,
    *,
    package_path: Path,
) -> StateAdoptionPreview:
    manifest, state, manifest_sha, package_sha = _read_verified_package(package_path)
    project = _single_project(session)
    workspace = _existing_workspace(session, project.id)
    if manifest.project_id != project.id:
        raise ValueError("El paquete pertenece a otro proyecto")
    if manifest.target_workspace_id != workspace.id:
        raise ValueError("El paquete no está dirigido a esta copia")
    if manifest.target_workspace_name != workspace.workspace_name:
        raise ValueError("El nombre de la copia destinataria no coincide")
    if manifest.source_workspace_id == workspace.id:
        raise ValueError("La copia de origen y la destinataria deben ser distintas")
    local_foundation = _foundation_sha256(session, state)
    if local_foundation != manifest.foundation_sha256:
        raise ValueError(
            "La base documental u OCR de esta copia no coincide con la requerida por el paquete"
        )
    local_state = _editable_state_payload(session, project.id)
    if manifest.schema_version == "1.0" and any(
        section in local_state for section in AUDIOVISUAL_STATE_SECTIONS
    ):
        raise ValueError(
            "El paquete de estado 1.0 no incluye el estado audiovisual que ya existe en esta copia"
        )
    if manifest.schema_version in {"1.0", "1.1"} and any(
        section in local_state for section in TIMELINE_STATE_SECTIONS
    ):
        raise ValueError(
            "El paquete de estado no incluye las anotaciones audiovisuales que ya existen en esta copia"
        )
    return StateAdoptionPreview(
        adoption_id=manifest.adoption_id,
        package_path=package_path.expanduser().resolve(),
        package_sha256=package_sha,
        manifest_sha256=manifest_sha,
        project_id=project.id,
        source_workspace_id=manifest.source_workspace_id,
        source_workspace_name=manifest.source_workspace_name,
        source_sequence=manifest.source_sequence,
        target_workspace_id=manifest.target_workspace_id,
        target_workspace_name=manifest.target_workspace_name,
        local_state_sha256=sha256_json(local_state),
        incoming_state_sha256=manifest.state_sha256,
        foundation_sha256=manifest.foundation_sha256,
        sections=_impact(local_state, state),
    )


def _parse_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _parse_date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def _upsert(session: Session, model: type, row_id: str, values: dict[str, Any]) -> Any:
    row = session.get(model, row_id)
    if row is None:
        row = model(id=row_id, **values)
        session.add(row)
    else:
        for key, value in values.items():
            setattr(row, key, value)
    return row


def _delete_missing(rows: list[Any], keep_ids: set[str]) -> None:
    for row in rows:
        if row.id not in keep_ids:
            # La sesión se obtiene a través del estado ORM de la instancia.
            session = Session.object_session(row)
            assert session is not None
            session.delete(row)


def _synchronize_editable_state(
    session: Session,
    *,
    project_id: str,
    state: dict[str, Any],
    actor: str,
) -> None:
    now = utc_now()

    selection_ids = {row["id"] for row in state["selections"]}
    for item in state["selections"]:
        existing = session.get(ExtractionPageSelection, item["id"])
        _upsert(
            session,
            ExtractionPageSelection,
            item["id"],
            {
                "digital_object_id": item["digital_object_id"],
                "page_number": item["page_number"],
                "extraction_run_id": item["extraction_run_id"],
                "extraction_page_id": item["extraction_page_id"],
                "selected_by": existing.selected_by if existing else actor,
                "note": existing.note if existing else "Adopción de estado divergente",
                "selected_at": existing.selected_at if existing else now,
            },
        )

    page_ids = {row["id"] for row in state["pages"]}
    for item in state["pages"]:
        existing = session.get(EditablePage, item["id"])
        _upsert(
            session,
            EditablePage,
            item["id"],
            {
                "digital_object_id": item["digital_object_id"],
                "page_number": item["page_number"],
                "source_extraction_run_id": item["source_extraction_run_id"],
                "source_extraction_page_id": item["source_extraction_page_id"],
                "source_selection_id": item.get("source_selection_id"),
                "status": item["status"],
                "revision_number": item["revision_number"],
                "review_status": item["review_status"],
                "review_note": item.get("review_note"),
                "form_structure_json": item.get("form_structure") or {},
                "layout_structure_json": item.get("layout_structure") or {},
                "reviewed_by": actor if item["review_status"] != "unreviewed" else None,
                "reviewed_at": now if item["review_status"] != "unreviewed" else None,
                "bootstrapped_by": existing.bootstrapped_by if existing else actor,
                "bootstrapped_at": existing.bootstrapped_at if existing else now,
                "updated_at": now,
            },
        )

    object_ids = {row["id"] for row in state["objects"]}
    for item in state["objects"]:
        existing = session.get(EditableObject, item["id"])
        _upsert(
            session,
            EditableObject,
            item["id"],
            {
                "editable_page_id": item["editable_page_id"],
                "digital_object_id": item["digital_object_id"],
                "page_number": item["page_number"],
                "document_part_id": item.get("document_part_id"),
                "source_extracted_object_id": item.get("source_extracted_object_id"),
                "source_origin_id": existing.source_origin_id if existing else None,
                "current_text": item["text"],
                "current_object_type": item["object_type"],
                "current_order_index": item["order_index"],
                "current_geometry_json": item.get("geometry") or [],
                "current_attributes_json": item.get("attributes") or {},
                "lifecycle_status": item["lifecycle_status"],
                "review_status": item["review_status"],
                "revision_number": item["revision_number"],
                "created_by": existing.created_by if existing else actor,
                "created_at": existing.created_at if existing else now,
                "updated_by": actor,
                "updated_at": now,
            },
        )

    unit_ids = {row["id"] for row in state["catalog_units"]}
    for item in state["catalog_units"]:
        existing = session.get(ArchivalUnit, item["id"])
        _upsert(
            session,
            ArchivalUnit,
            item["id"],
            {
                "project_id": project_id,
                "parent_id": None,
                "level_key": item["level_key"],
                "reference_code": item.get("reference_code"),
                "title": item["title"],
                "registration_status": item["registration_status"],
                "completion_confirmed": bool(item["completion_confirmed"]),
                "completion_confirmed_at": (
                    now if item["completion_confirmed"] else None
                ),
                "completion_confirmed_by": (
                    actor if item["completion_confirmed"] else None
                ),
                "created_at": existing.created_at if existing else now,
                "created_by": existing.created_by if existing else actor,
                "updated_at": now,
                "updated_by": actor,
                "revision": item["revision"],
            },
        )
    session.flush()
    for item in state["catalog_units"]:
        session.get(ArchivalUnit, item["id"]).parent_id = item.get("parent_id")

    has_audiovisual_state = all(
        section in state for section in AUDIOVISUAL_STATE_SECTIONS
    )
    has_timeline_state = all(
        section in state for section in TIMELINE_STATE_SECTIONS
    )
    audiovisual_media_ids: set[str] = set()
    transcription_run_ids: set[str] = set()
    transcript_segment_ids: set[str] = set()
    transcript_segment_revision_ids: set[str] = set()
    segment_mention_ids: set[str] = set()

    authority_ids = {row["id"] for row in state["authorities"]}
    for item in state["authorities"]:
        existing = session.get(AuthorityRecord, item["id"])
        _upsert(
            session,
            AuthorityRecord,
            item["id"],
            {
                "project_id": project_id,
                "entity_type": item["entity_type"],
                "preferred_name": item["preferred_name"],
                "normalized_name": item["normalized_name"],
                "description": item.get("description"),
                "temporal_expression": item.get("temporal_expression"),
                "temporal_start": _parse_date(item.get("temporal_start")),
                "temporal_end": _parse_date(item.get("temporal_end")),
                "temporal_precision": item.get("temporal_precision"),
                "temporal_approximate": bool(item.get("temporal_approximate")),
                "temporal_note": item.get("temporal_note"),
                "profile_json": item.get("profile_json") or {},
                "lifecycle_status": item["lifecycle_status"],
                "review_status": item["review_status"],
                "created_by": existing.created_by if existing else actor,
                "created_at": existing.created_at if existing else now,
                "updated_by": actor,
                "updated_at": now,
                "revision": item["revision"],
            },
        )

    if has_audiovisual_state:
        audiovisual_media_ids = {row["id"] for row in state["audiovisual_media"]}
        for item in state["audiovisual_media"]:
            _upsert(
                session,
                AudiovisualMedia,
                item["id"],
                {
                    "digital_object_id": item["digital_object_id"],
                    "title": item.get("title"),
                    "producer": item.get("producer"),
                    "channel": item.get("channel"),
                    "responsible": item.get("responsible"),
                    "provenance": item.get("provenance"),
                    "recorded_date": _parse_date(item.get("recorded_date")),
                    "rights": item.get("rights"),
                    "description": item.get("description"),
                    "container_format": item.get("container_format"),
                    "duration_seconds": item.get("duration_seconds"),
                    "audio_codec": item.get("audio_codec"),
                    "video_codec": item.get("video_codec"),
                    "channels": item.get("channels"),
                    "sample_rate_hz": item.get("sample_rate_hz"),
                    "width": item.get("width"),
                    "height": item.get("height"),
                    "frame_rate": item.get("frame_rate"),
                    "technical_json": item.get("technical") or {},
                    "inspected_at": _parse_datetime(item.get("inspected_at")),
                    "updated_by": actor,
                    "updated_at": now,
                },
            )

        transcription_run_ids = {row["id"] for row in state["transcription_runs"]}
        for item in state["transcription_runs"]:
            _upsert(
                session,
                TranscriptionRun,
                item["id"],
                {
                    "audiovisual_media_id": item["audiovisual_media_id"],
                    # El paquete transporta el texto y su procedencia lógica, no binarios derivados.
                    "source_asset_id": None,
                    "backend": item["backend"],
                    "backend_version": item.get("backend_version"),
                    "model_name": item["model_name"],
                    "device": item["device"],
                    "language": item.get("language"),
                    "options_json": item.get("options") or {},
                    "status": item["status"],
                    "error_text": item.get("error_text"),
                    "created_by": item["created_by"],
                    "created_at": _parse_datetime(item["created_at"]),
                    "completed_at": _parse_datetime(item.get("completed_at")),
                },
            )

        transcript_segment_ids = {row["id"] for row in state["transcript_segments"]}
        for item in state["transcript_segments"]:
            _upsert(
                session,
                TranscriptSegment,
                item["id"],
                {
                    "transcription_run_id": item["transcription_run_id"],
                    "segment_index": item["segment_index"],
                    "start_time": item["start_time"],
                    "end_time": item["end_time"],
                    "original_text": item["original_text"],
                    "corrected_text": item.get("corrected_text"),
                    "review_status": item["review_status"],
                    "revision_number": item["revision_number"],
                    "updated_by": item["updated_by"],
                    "updated_at": _parse_datetime(item["updated_at"]),
                },
            )

        transcript_segment_revision_ids = {
            row["id"] for row in state["transcript_segment_revisions"]
        }
        for item in state["transcript_segment_revisions"]:
            _upsert(
                session,
                TranscriptSegmentRevision,
                item["id"],
                {
                    "segment_id": item["segment_id"],
                    "revision_number": item["revision_number"],
                    "operation": item["operation"],
                    "snapshot_json": item.get("snapshot") or {},
                    "note": item.get("note"),
                    "changed_by": item["changed_by"],
                    "changed_at": _parse_datetime(item["changed_at"]),
                },
            )

        segment_mention_ids = {row["id"] for row in state["segment_entity_mentions"]}
        for item in state["segment_entity_mentions"]:
            _upsert(
                session,
                SegmentEntityMention,
                item["id"],
                {
                    "segment_id": item["segment_id"],
                    "authority_id": item.get("authority_id"),
                    "mention_text": item["mention_text"],
                    "normalized_text": item["normalized_text"],
                    "start_offset": item.get("start_offset"),
                    "end_offset": item.get("end_offset"),
                    "segment_revision_number": item["segment_revision_number"],
                    "status": item["status"],
                    "source": item["source"],
                    "note": item.get("note"),
                    "created_by": item["created_by"],
                    "created_at": _parse_datetime(item["created_at"]),
                    "updated_by": item["updated_by"],
                    "updated_at": _parse_datetime(item["updated_at"]),
                },
            )

    timeline_annotation_ids: set[str] = set()
    timeline_annotation_revision_ids: set[str] = set()
    if has_timeline_state:
        timeline_annotation_ids = {
            row["id"] for row in state["audiovisual_timeline_annotations"]
        }
        for item in state["audiovisual_timeline_annotations"]:
            existing = session.get(AudiovisualTimelineAnnotation, item["id"])
            _upsert(
                session,
                AudiovisualTimelineAnnotation,
                item["id"],
                {
                    "audiovisual_media_id": item["audiovisual_media_id"],
                    "annotation_type": item["annotation_type"],
                    "start_time": item["start_time"],
                    "end_time": item["end_time"],
                    "label": item["label"],
                    "authority_id": item.get("authority_id"),
                    "status": item["status"],
                    "revision_number": item["revision_number"],
                    "created_by": item["created_by"],
                    "created_at": _parse_datetime(item["created_at"]),
                    "updated_by": actor,
                    "updated_at": _parse_datetime(item["updated_at"]) or now,
                },
            )

        timeline_annotation_revision_ids = {
            row["id"]
            for row in state["audiovisual_timeline_annotation_revisions"]
        }
        for item in state["audiovisual_timeline_annotation_revisions"]:
            _upsert(
                session,
                AudiovisualTimelineAnnotationRevision,
                item["id"],
                {
                    "annotation_id": item["annotation_id"],
                    "revision_number": item["revision_number"],
                    "operation": item["operation"],
                    "snapshot_json": item.get("snapshot") or {},
                    "changed_by": item["changed_by"],
                    "changed_at": _parse_datetime(item["changed_at"]),
                },
            )

    assignment_ids = {row["id"] for row in state["work_assignments"]}
    for item in state["work_assignments"]:
        existing = session.get(WorkAssignment, item["id"])
        _upsert(
            session,
            WorkAssignment,
            item["id"],
            {
                "project_id": project_id,
                "source_type": item["source_type"],
                "source_key": item["source_key"],
                "page_start": item.get("page_start"),
                "page_end": item.get("page_end"),
                "assignment_kind": item["assignment_kind"],
                "assignee": item["assignee"],
                "status": item["status"],
                "priority": item["priority"],
                "due_at": _parse_datetime(item.get("due_at")),
                "parent_assignment_id": None,
                "outcome": item.get("outcome"),
                "note": item.get("note"),
                "submitted_at": _parse_datetime(item.get("submitted_at")),
                "completed_at": _parse_datetime(item.get("completed_at")),
                "created_by": existing.created_by if existing else actor,
                "created_at": existing.created_at if existing else now,
                "updated_by": actor,
                "updated_at": now,
                "revision": item["revision"],
            },
        )
    session.flush()
    for item in state["work_assignments"]:
        session.get(WorkAssignment, item["id"]).parent_assignment_id = item.get(
            "parent_assignment_id"
        )

    comment_ids = {row["id"] for row in state["comments"]}
    for item in state["comments"]:
        _upsert(
            session,
            EditableObjectComment,
            item["id"],
            {
                "editable_object_id": item["editable_object_id"],
                "body": item["body"],
                "created_by": item["created_by"],
                "created_at": _parse_datetime(item["created_at"]),
            },
        )

    tag_ids = {row["id"] for row in state["tags"]}
    for item in state["tags"]:
        _upsert(
            session,
            EditableObjectTag,
            item["id"],
            {
                "editable_object_id": item["editable_object_id"],
                "tag": item["tag"],
                "normalized_tag": item["normalized_tag"],
                "tag_kind": item["tag_kind"],
                "created_by": item["created_by"],
                "created_at": _parse_datetime(item["created_at"]),
            },
        )

    action_ids = {row["id"] for row in state["page_actions"]}
    for item in state["page_actions"]:
        _upsert(
            session,
            EditablePageAction,
            item["id"],
            {
                "editable_page_id": item["editable_page_id"],
                "sequence_number": item["sequence_number"],
                "action_type": item["action_type"],
                "status": item["status"],
                "before_snapshot_json": item["before_snapshot"],
                "after_snapshot_json": item["after_snapshot"],
                "selected_object_id": item.get("selected_object_id"),
                "note": item.get("note"),
                "created_by": item["created_by"],
                "created_at": _parse_datetime(item["created_at"]),
                "undone_by": item.get("undone_by"),
                "undone_at": _parse_datetime(item.get("undone_at")),
                "redone_by": item.get("redone_by"),
                "redone_at": _parse_datetime(item.get("redone_at")),
            },
        )

    alias_rows = [alias for authority in state["authorities"] for alias in authority["aliases"]]
    alias_ids = {row["id"] for row in alias_rows}
    alias_authority = {
        alias["id"]: authority["id"]
        for authority in state["authorities"]
        for alias in authority["aliases"]
    }
    for item in alias_rows:
        _upsert(
            session,
            AuthorityAlias,
            item["id"],
            {
                "authority_id": alias_authority[item["id"]],
                "alias": item["alias"],
                "normalized_alias": item["normalized_alias"],
                "alias_type": item["alias_type"],
                "note": item.get("note"),
                "created_by": item["created_by"],
                "created_at": _parse_datetime(item["created_at"]),
            },
        )

    mention_ids = {row["id"] for row in state["entity_mentions"]}
    for item in state["entity_mentions"]:
        existing = session.get(EntityMention, item["id"])
        _upsert(
            session,
            EntityMention,
            item["id"],
            {
                "editable_object_id": item["editable_object_id"],
                "authority_id": item.get("authority_id"),
                "mention_text": item["mention_text"],
                "normalized_text": item["normalized_text"],
                "start_offset": item.get("start_offset"),
                "end_offset": item.get("end_offset"),
                "object_revision_number": item["object_revision_number"],
                "status": item["status"],
                "source": item["source"],
                "confidence": item.get("confidence"),
                "note": item.get("note"),
                "created_by": existing.created_by if existing else actor,
                "created_at": existing.created_at if existing else now,
                "updated_by": actor,
                "updated_at": now,
                "revision": item["revision"],
            },
        )

    relation_ids = {row["id"] for row in state["entity_relations"]}
    for item in state["entity_relations"]:
        existing = session.get(EntityRelation, item["id"])
        _upsert(
            session,
            EntityRelation,
            item["id"],
            {
                "project_id": project_id,
                "source_authority_id": item["source_authority_id"],
                "relation_kind": item.get("relation_kind", "analytical"),
                "relation_label": item["relation_label"],
                "target_authority_id": item.get("target_authority_id"),
                "target_archival_unit_id": item.get("target_archival_unit_id"),
                "target_document_part_id": item.get("target_document_part_id"),
                "evidence_note": item.get("evidence_note"),
                "provenance_note": item.get("provenance_note"),
                "temporal_expression": item.get("temporal_expression"),
                "temporal_start": _parse_date(item.get("temporal_start")),
                "temporal_end": _parse_date(item.get("temporal_end")),
                "temporal_precision": item.get("temporal_precision"),
                "temporal_approximate": bool(item.get("temporal_approximate")),
                "temporal_note": item.get("temporal_note"),
                "profile_json": item.get("profile_json") or {},
                "lifecycle_status": item["lifecycle_status"],
                "review_status": item["review_status"],
                "created_by": existing.created_by if existing else actor,
                "created_at": existing.created_at if existing else now,
                "updated_by": actor,
                "updated_at": now,
                "revision": item["revision"],
            },
        )

    link_ids = {row["id"] for row in state["digital_links"]}
    for item in state["digital_links"]:
        _upsert(
            session,
            DigitalObjectUnitLink,
            item["id"],
            {
                "digital_object_id": item["digital_object_id"],
                "archival_unit_id": item["archival_unit_id"],
                "relation_type": item["relation_type"],
                "page_start": item.get("page_start"),
                "page_end": item.get("page_end"),
            },
        )

    # Los valores descriptivos no exponen un ID en la huella canónica; se reemplazan
    # dentro de las unidades del proyecto y se recrean con IDs locales nuevos.
    existing_units = session.scalars(
        select(ArchivalUnit).where(ArchivalUnit.project_id == project_id)
    ).all()
    existing_unit_ids = {row.id for row in existing_units}
    for field in session.scalars(
        select(ArchivalFieldValue).where(
            ArchivalFieldValue.archival_unit_id.in_(existing_unit_ids)
        )
    ).all() if existing_unit_ids else []:
        session.delete(field)
    session.flush()
    for unit in state["catalog_units"]:
        for field in unit["fields"]:
            session.add(
                ArchivalFieldValue(
                    id=new_id(),
                    archival_unit_id=unit["id"],
                    field_key=field["field_key"],
                    value_state=field["value_state"],
                    value_json=field.get("value"),
                    sort_order=field["sort_order"],
                    source_note=field.get("source_note"),
                    created_at=now,
                    updated_at=now,
                )
            )

    session.flush()

    project_object_ids = {
        row.id
        for row in session.scalars(
            select(EditableObject)
            .join(DigitalObject, DigitalObject.id == EditableObject.digital_object_id)
            .where(DigitalObject.project_id == project_id)
        ).all()
    }
    project_page_ids = {
        row.id
        for row in session.scalars(
            select(EditablePage)
            .join(DigitalObject, DigitalObject.id == EditablePage.digital_object_id)
            .where(DigitalObject.project_id == project_id)
        ).all()
    }
    project_digital_ids = {
        row.id
        for row in session.scalars(
            select(DigitalObject).where(DigitalObject.project_id == project_id)
        ).all()
    }

    if has_audiovisual_state:
        project_av_media = session.scalars(
            select(AudiovisualMedia).where(
                AudiovisualMedia.digital_object_id.in_(project_digital_ids)
            )
        ).all() if project_digital_ids else []
        project_av_media_ids = {row.id for row in project_av_media}
        project_runs = session.scalars(
            select(TranscriptionRun).where(
                TranscriptionRun.audiovisual_media_id.in_(project_av_media_ids)
            )
        ).all() if project_av_media_ids else []
        project_run_ids = {row.id for row in project_runs}
        project_segments = session.scalars(
            select(TranscriptSegment).where(
                TranscriptSegment.transcription_run_id.in_(project_run_ids)
            )
        ).all() if project_run_ids else []
        project_segment_ids = {row.id for row in project_segments}
        _delete_missing(
            session.scalars(
                select(SegmentEntityMention).where(
                    SegmentEntityMention.segment_id.in_(project_segment_ids)
                )
            ).all() if project_segment_ids else [],
            segment_mention_ids,
        )
        _delete_missing(
            session.scalars(
                select(TranscriptSegmentRevision).where(
                    TranscriptSegmentRevision.segment_id.in_(project_segment_ids)
                )
            ).all() if project_segment_ids else [],
            transcript_segment_revision_ids,
        )
        _delete_missing(project_segments, transcript_segment_ids)
        session.flush()
        if has_timeline_state:
            project_timeline_annotations = session.scalars(
                select(AudiovisualTimelineAnnotation).where(
                    AudiovisualTimelineAnnotation.audiovisual_media_id.in_(project_av_media_ids)
                )
            ).all() if project_av_media_ids else []
            project_timeline_annotation_ids = {row.id for row in project_timeline_annotations}
            _delete_missing(
                session.scalars(
                    select(AudiovisualTimelineAnnotationRevision).where(
                        AudiovisualTimelineAnnotationRevision.annotation_id.in_(
                            project_timeline_annotation_ids
                        )
                    )
                ).all() if project_timeline_annotation_ids else [],
                timeline_annotation_revision_ids,
            )
            _delete_missing(project_timeline_annotations, timeline_annotation_ids)
            session.flush()
        _delete_missing(project_runs, transcription_run_ids)
        session.flush()
        _delete_missing(project_av_media, audiovisual_media_ids)
        session.flush()

    _delete_missing(
        session.scalars(
            select(EntityRelation).where(EntityRelation.project_id == project_id)
        ).all(),
        relation_ids,
    )
    _delete_missing(
        session.scalars(
            select(EntityMention).where(EntityMention.editable_object_id.in_(project_object_ids))
        ).all() if project_object_ids else [],
        mention_ids,
    )
    _delete_missing(
        session.scalars(
            select(AuthorityAlias).where(AuthorityAlias.authority_id.in_(authority_ids))
        ).all() if authority_ids else [],
        alias_ids,
    )
    _delete_missing(
        session.scalars(
            select(EditableObjectComment).where(
                EditableObjectComment.editable_object_id.in_(project_object_ids)
            )
        ).all() if project_object_ids else [],
        comment_ids,
    )
    _delete_missing(
        session.scalars(
            select(EditableObjectTag).where(
                EditableObjectTag.editable_object_id.in_(project_object_ids)
            )
        ).all() if project_object_ids else [],
        tag_ids,
    )
    _delete_missing(
        session.scalars(
            select(EditablePageAction).where(
                EditablePageAction.editable_page_id.in_(project_page_ids)
            )
        ).all() if project_page_ids else [],
        action_ids,
    )
    _delete_missing(
        session.scalars(
            select(DigitalObjectUnitLink).where(
                DigitalObjectUnitLink.digital_object_id.in_(project_digital_ids)
            )
        ).all() if project_digital_ids else [],
        link_ids,
    )
    session.flush()

    # Desvincular autorreferencias antes de eliminar filas locales descartadas.
    for assignment in session.scalars(
        select(WorkAssignment).where(WorkAssignment.project_id == project_id)
    ).all():
        if assignment.id not in assignment_ids:
            assignment.parent_assignment_id = None
    for unit in session.scalars(
        select(ArchivalUnit).where(ArchivalUnit.project_id == project_id)
    ).all():
        if unit.id not in unit_ids:
            unit.parent_id = None
    session.flush()

    _delete_missing(
        session.scalars(
            select(WorkAssignment).where(WorkAssignment.project_id == project_id)
        ).all(),
        assignment_ids,
    )
    _delete_missing(
        session.scalars(
            select(AuthorityRecord).where(AuthorityRecord.project_id == project_id)
        ).all(),
        authority_ids,
    )
    _delete_missing(
        session.scalars(
            select(EditableObject)
            .join(DigitalObject, DigitalObject.id == EditableObject.digital_object_id)
            .where(DigitalObject.project_id == project_id)
        ).all(),
        object_ids,
    )
    session.flush()
    _delete_missing(
        session.scalars(
            select(EditablePage)
            .join(DigitalObject, DigitalObject.id == EditablePage.digital_object_id)
            .where(DigitalObject.project_id == project_id)
        ).all(),
        page_ids,
    )
    _delete_missing(
        session.scalars(
            select(ExtractionPageSelection).where(
                ExtractionPageSelection.digital_object_id.in_(project_digital_ids)
            )
        ).all() if project_digital_ids else [],
        selection_ids,
    )
    _delete_missing(
        session.scalars(
            select(ArchivalUnit).where(ArchivalUnit.project_id == project_id)
        ).all(),
        unit_ids,
    )
    session.flush()


def _stale_active_dry_runs(session: Session) -> int:
    rows = session.scalars(
        select(ExchangeDryRun).where(
            ExchangeDryRun.lifecycle_status == "active",
            ExchangeDryRun.overall_status != "stale",
        )
    ).all()
    for row in rows:
        row.overall_status = "stale"
    return len(rows)


def _impact_json(preview: StateAdoptionPreview) -> dict[str, Any]:
    return {
        "local_state_sha256": preview.local_state_sha256,
        "incoming_state_sha256": preview.incoming_state_sha256,
        "totals": {
            "added": preview.total_added,
            "removed": preview.total_removed,
            "changed": preview.total_changed,
        },
        "sections": [asdict(row) for row in preview.sections],
    }


def apply_state_adoption(
    session: Session,
    *,
    project_root: Path,
    package_path: Path,
    applied_by: str,
    application_reason: str,
    adoption_confirmed: bool,
    source: str,
) -> StateAdoptionSummary:
    actor = applied_by.strip()
    reason = application_reason.strip()
    clean_source = source.strip().lower()
    if not adoption_confirmed:
        raise ValueError("Marcá la confirmación antes de adoptar el estado divergente")
    if not actor:
        raise ValueError("Indicá quién adopta el estado")
    if not reason:
        raise ValueError("Escribí el fundamento de la adopción")
    if clean_source not in {"ui", "cli", "api", "script"}:
        raise ValueError("El origen de la operación no es válido")

    preview = preview_state_adoption(session, package_path=package_path)
    if preview.is_identical:
        raise ValueError(
            "Las copias ya tienen un estado editable idéntico; corresponde establecer la base común sin adopción"
        )
    if session.scalar(
        select(ExchangeStateAdoption).where(
            ExchangeStateAdoption.package_sha256 == preview.package_sha256
        )
    ) is not None:
        raise ValueError("Este paquete de estado ya fue adoptado en la copia local")

    manifest, state, manifest_sha, package_sha = _read_verified_package(package_path)
    project = _single_project(session)
    workspace = _existing_workspace(session, project.id)
    backup = create_project_backup(
        project_root=project_root,
        created_by=actor,
        note=f"Antes de adoptar el estado divergente {manifest.adoption_id}",
    )
    _synchronize_editable_state(
        session,
        project_id=project.id,
        state=state,
        actor=actor,
    )
    observed = current_editable_state_sha256(session, project.id)
    if observed != manifest.state_sha256:
        raise ValueError(
            "La aplicación no produjo exactamente la huella declarada; se revirtió la transacción"
        )
    integrity = session.execute(text("PRAGMA integrity_check")).scalar_one()
    foreign_keys = session.execute(text("PRAGMA foreign_key_check")).all()
    if integrity != "ok" or foreign_keys:
        raise ValueError(
            "La aplicación no superó las comprobaciones de integridad; se revirtió la transacción"
        )
    stale_count = _stale_active_dry_runs(session)
    impact = _impact_json(preview)
    parameters_sha = sha256_json(
        {
            "schema_version": "ex01d-1",
            "operation": "adopt_remote_state",
            "adoption_id": manifest.adoption_id,
            "package_sha256": package_sha,
            "manifest_sha256": manifest_sha,
            "previous_state_sha256": preview.local_state_sha256,
            "adopted_state_sha256": manifest.state_sha256,
            "backup_sha256": backup.backup_sha256,
            "impact": impact,
            "source": clean_source,
            "applied_by": actor,
            "application_reason": reason,
        }
    )
    row = ExchangeStateAdoption(
        id=new_id(),
        adoption_id=manifest.adoption_id,
        project_id=project.id,
        local_workspace_id=workspace.id,
        source_workspace_id=manifest.source_workspace_id,
        source_workspace_name=manifest.source_workspace_name,
        source_sequence=manifest.source_sequence,
        target_workspace_id=manifest.target_workspace_id,
        target_workspace_name=manifest.target_workspace_name,
        previous_state_sha256=preview.local_state_sha256,
        adopted_state_sha256=manifest.state_sha256,
        foundation_sha256=manifest.foundation_sha256,
        package_path=str(package_path.expanduser().resolve()),
        package_sha256=package_sha,
        manifest_sha256=manifest_sha,
        manifest_version=manifest.schema_version,
        backup_path=str(backup.path),
        backup_sha256=backup.backup_sha256,
        backup_database_sha256=backup.database_sha256,
        backup_database_revision=backup.database_revision,
        impact_json=impact,
        source=clean_source,
        applied_by=actor,
        application_reason=reason,
        parameters_sha256=parameters_sha,
        stale_dry_run_count=stale_count,
        applied_at=utc_now(),
    )
    session.add(row)
    session.flush()
    return StateAdoptionSummary(
        adoption_id=manifest.adoption_id,
        record_id=row.id,
        previous_state_sha256=preview.local_state_sha256,
        adopted_state_sha256=manifest.state_sha256,
        backup_path=backup.path,
        backup_sha256=backup.backup_sha256,
        package_sha256=package_sha,
        stale_dry_run_count=stale_count,
        impact=impact,
    )


def state_adoption_rows(session: Session) -> list[StateAdoptionRow]:
    adoptions = session.scalars(
        select(ExchangeStateAdoption).order_by(
            ExchangeStateAdoption.applied_at.desc(), ExchangeStateAdoption.id
        )
    ).all()
    rollback_by_adoption = {
        row.adoption_record_id: row
        for row in session.scalars(select(ExchangeStateAdoptionRollback)).all()
    }
    return [
        StateAdoptionRow(
            adoption_id=row.adoption_id,
            record_id=row.id,
            source_workspace_id=row.source_workspace_id,
            source_workspace_name=row.source_workspace_name,
            source_sequence=row.source_sequence,
            previous_state_sha256=row.previous_state_sha256,
            adopted_state_sha256=row.adopted_state_sha256,
            package_sha256=row.package_sha256,
            backup_path=row.backup_path,
            applied_by=row.applied_by,
            application_reason=row.application_reason,
            source=row.source,
            applied_at=row.applied_at,
            rolled_back=row.id in rollback_by_adoption,
            rolled_back_by=(
                rollback_by_adoption[row.id].rolled_back_by
                if row.id in rollback_by_adoption
                else None
            ),
            rollback_reason=(
                rollback_by_adoption[row.id].rollback_reason
                if row.id in rollback_by_adoption
                else None
            ),
            rolled_back_at=(
                rollback_by_adoption[row.id].rolled_back_at
                if row.id in rollback_by_adoption
                else None
            ),
        )
        for row in adoptions
    ]


def rollback_state_adoption(
    *,
    project_root: Path,
    adoption_ref: str,
    rolled_back_by: str,
    rollback_reason: str,
    rollback_confirmed: bool,
    source: str,
) -> StateAdoptionRollbackSummary:
    actor = rolled_back_by.strip()
    reason = rollback_reason.strip()
    clean_source = source.strip().lower()
    if not rollback_confirmed:
        raise ValueError("Marcá la confirmación antes de restaurar el estado anterior")
    if not actor:
        raise ValueError("Indicá quién ejecuta el rollback")
    if not reason:
        raise ValueError("Escribí el fundamento del rollback")
    if clean_source not in {"ui", "cli", "api", "script"}:
        raise ValueError("El origen de la operación no es válido")

    root = project_root.resolve()
    require_current_database(root)
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            candidates = session.scalars(
                select(ExchangeStateAdoption).where(
                    (ExchangeStateAdoption.adoption_id == adoption_ref)
                    | (ExchangeStateAdoption.id == adoption_ref)
                )
            ).all()
            if len(candidates) != 1:
                raise ValueError("No se encontró una adopción única con esa referencia")
            adoption = candidates[0]
            if session.scalar(
                select(ExchangeStateAdoptionRollback).where(
                    ExchangeStateAdoptionRollback.adoption_record_id == adoption.id
                )
            ) is not None:
                raise ValueError("Esta adopción ya fue revertida")
            if session.scalar(
                select(ExchangeCommonBaseAgreement.id).where(
                    ExchangeCommonBaseAgreement.state_sha256
                    == adoption.adopted_state_sha256
                )
            ) is not None:
                raise ValueError(
                    "La adopción ya fue usada para registrar una base común; no puede revertirse automáticamente"
                )
            current_state = current_editable_state_sha256(session, adoption.project_id)
            if current_state != adoption.adopted_state_sha256:
                raise ValueError(
                    "El estado editable cambió después de la adopción; el rollback automático fue bloqueado"
                )
            payload = {
                column.name: getattr(adoption, column.name)
                for column in ExchangeStateAdoption.__table__.columns
            }
            backup_path = Path(adoption.backup_path)
            expected_backup_sha = adoption.backup_sha256
    finally:
        engine.dispose()

    backup_info = inspect_project_backup(backup_path)
    if backup_info.backup_sha256 != expected_backup_sha:
        raise ValueError("El backup previo a la adopción no conserva su SHA-256 registrado")
    restore = restore_project_backup(
        project_root=root,
        backup_path=backup_path,
        restored_by=actor,
        restore_config=False,
    )

    require_current_database(root)
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            project = _single_project(session)
            restored_state = current_editable_state_sha256(session, project.id)
            if restored_state != payload["previous_state_sha256"]:
                raise ValueError("El backup restaurado no reproduce el estado previo registrado")
            row = session.get(ExchangeStateAdoption, payload["id"])
            if row is None:
                row = ExchangeStateAdoption(**payload)
                session.add(row)
                session.flush()
            if session.scalar(
                select(ExchangeStateAdoptionRollback).where(
                    ExchangeStateAdoptionRollback.adoption_record_id == row.id
                )
            ) is not None:
                raise ValueError("La adopción restaurada ya tiene un rollback registrado")
            stale_count = _stale_active_dry_runs(session)
            parameters_sha = sha256_json(
                {
                    "schema_version": "ex01d-1",
                    "operation": "rollback_state_adoption",
                    "adoption_id": row.adoption_id,
                    "restored_state_sha256": restored_state,
                    "restored_backup_sha256": backup_info.backup_sha256,
                    "safety_backup_sha256": restore.safety_backup_sha256,
                    "source": clean_source,
                    "rolled_back_by": actor,
                    "rollback_reason": reason,
                }
            )
            rollback = ExchangeStateAdoptionRollback(
                id=new_id(),
                adoption_record_id=row.id,
                restored_state_sha256=restored_state,
                restored_backup_path=str(restore.restored_backup),
                restored_backup_sha256=backup_info.backup_sha256,
                safety_backup_path=str(restore.safety_backup),
                safety_backup_sha256=restore.safety_backup_sha256,
                source=clean_source,
                rolled_back_by=actor,
                rollback_reason=reason,
                parameters_sha256=parameters_sha,
                stale_dry_run_count=stale_count,
                rolled_back_at=utc_now(),
            )
            session.add(rollback)
            session.flush()
            integrity = session.execute(text("PRAGMA integrity_check")).scalar_one()
            foreign_keys = session.execute(text("PRAGMA foreign_key_check")).all()
            if integrity != "ok" or foreign_keys:
                raise ValueError("La base restaurada no superó las comprobaciones de integridad")
            return StateAdoptionRollbackSummary(
                adoption_id=row.adoption_id,
                adoption_record_id=row.id,
                rollback_record_id=rollback.id,
                restored_state_sha256=restored_state,
                restored_backup=restore.restored_backup,
                safety_backup=restore.safety_backup,
                safety_backup_sha256=restore.safety_backup_sha256,
                stale_dry_run_count=stale_count,
            )
    finally:
        engine.dispose()
