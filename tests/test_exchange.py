from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import json
import shutil
import zipfile

import fitz
import pytest
from typer.testing import CliRunner
from sqlalchemy import func, inspect, select, text

from archive_workbench.catalog import register_test_corpus
from archive_workbench.candidate_review import (
    adopt_candidate_page,
    resolve_candidate_keep_edits,
)
from archive_workbench.cli import app
from archive_workbench.catalog_management import create_archival_unit, register_local_file
from archive_workbench.contracts.test_corpus import TestCorpus as CorpusDefinition
from archive_workbench.db import (
    create_sqlite_engine,
    current_revision,
    database_path,
    session_scope,
    upgrade_database,
)
from archive_workbench.db.models import (
    ArchivalUnit,
    DigitalObject,
    DigitalObjectUnitLink,
    EditableObject,
    EditableObjectRevision,
    EditablePage,
    EditablePageRevision,
    EditablePageAction,
    FileInstance,
    ExchangeChangeEvent,
    ExchangeCheckpoint,
    ExtractedObject,
    ExtractionPage,
    ExtractionPageSelection,
    ExtractionRun,
    SourceRegistration,
    WorkAssignment,
)
from archive_workbench.decisions import load_decisions
from archive_workbench.editing import (
    bootstrap_editable_layer,
    set_editable_object_lifecycle,
    update_editable_object,
)
from archive_workbench.review_annotations import (
    add_object_comment,
    add_object_tag,
    set_object_review_status,
    set_page_review_status,
)
from archive_workbench.exchange import (
    apply_change_bundle,
    create_exchange_checkpoint,
    dry_run_change_bundle,
    ensure_exchange_workspace,
    exchange_status,
    export_change_bundle,
    fork_exchange_workspace,
    inspect_change_bundle,
)
from archive_workbench.extraction import select_extraction_pages
from archive_workbench.form_structure import ensure_group, form_structure, register_control
from archive_workbench.identity import new_id
from archive_workbench.page_actions import execute_page_action, redo_page_action, undo_page_action
from archive_workbench.work import (
    create_cross_review_assignment,
    create_work_assignment,
    update_work_assignment,
)


def _write_pdf(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = fitz.open()
    page = doc.new_page(width=600, height=400)
    page.insert_text((50, 80), "Documento")
    doc.save(path)
    doc.close()


def _corpus() -> CorpusDefinition:
    return CorpusDefinition.model_validate(
        {
            "corpus_name": "Intercambio",
            "created_by": "tests",
            "created_at": datetime.now(timezone.utc),
            "documents": [
                {
                    "test_id": "doc_exchange",
                    "local_path": "corpus/doc.pdf",
                    "short_description": "Documento para intercambio",
                    "archival_location": {
                        "fondo": "SiCH",
                        "documento": "Documento para intercambio",
                    },
                    "input_characteristics": {
                        "format": "pdf",
                        "scanned": True,
                        "digital_text_layer": False,
                        "multipage_tiff": False,
                        "poor_contrast": False,
                        "skewed_pages": False,
                        "landscape_pages": False,
                        "mixed_orientations": False,
                        "typewritten": True,
                        "handwritten_notes": False,
                        "stamps": False,
                        "tables_or_forms": False,
                        "multiple_internal_documents": False,
                    },
                    "expected_extraction": {"minimum_page_coverage_percent": 95},
                }
            ],
        }
    )


def _seed_project(
    root: Path, *, revision: str = "head"
) -> tuple[object, object, str]:
    _write_pdf(root / "corpus/doc.pdf")
    decisions = load_decisions(Path(__file__).parents[1] / "config/decisions.yaml")
    upgrade_database(root, revision=revision)
    engine = create_sqlite_engine(database_path(root))
    with session_scope(engine) as session:
        register_test_corpus(
            session,
            project_root=root,
            decisions=decisions,
            corpus=_corpus(),
        )
        registration = session.scalar(
            select(SourceRegistration).where(
                SourceRegistration.source_key == "doc_exchange"
            )
        )
        assert registration and registration.digital_object_id
        digital = session.get(DigitalObject, registration.digital_object_id)
        assert digital
        run = ExtractionRun(
            id=new_id(),
            digital_object_id=digital.id,
            profile_key="test_profile",
            engine="tesseract_tsv",
            engine_version="5",
            source_sha256=digital.sha256,
            options_json={},
            options_hash="a" * 64,
            status="completed",
            is_current=True,
            created_by="tests",
            total_pages=1,
            total_objects=1,
            total_paragraphs=1,
            total_characters=9,
            warnings_json=[],
        )
        session.add(run)
        session.flush()
        extraction_page = ExtractionPage(
            id=new_id(),
            extraction_run_id=run.id,
            page_number=1,
            object_count=1,
            character_count=9,
            status="completed",
        )
        session.add(extraction_page)
        session.flush()
        source = ExtractedObject(
            id=new_id(),
            origin_id=new_id(),
            extraction_run_id=run.id,
            digital_object_id=digital.id,
            page_number=1,
            order_index=0,
            object_type="paragraph",
            original_text="Texto OCR",
            geometry_json=[],
            attributes_json={},
        )
        session.add(source)
        selection = ExtractionPageSelection(
            id=new_id(),
            digital_object_id=digital.id,
            page_number=1,
            extraction_run_id=run.id,
            extraction_page_id=extraction_page.id,
            selected_by="tests",
        )
        session.add(selection)
        historical_seed = {
            "digital_object_id": digital.id,
            "extraction_run_id": run.id,
            "extraction_page_id": extraction_page.id,
            "selection_id": selection.id,
            "source_object_id": source.id,
            "source_origin_id": source.origin_id,
            "text": source.original_text,
            "object_type": source.object_type,
            "order_index": source.order_index,
            "geometry_json": source.geometry_json or [],
            "attributes_json": {
                **(source.attributes_json or {}),
                "source_label": source.source_label,
                "source_confidence": source.confidence,
                "source_language": source.language,
            },
        }

    if revision in {
        "head",
        "0029_extraction_candidate_history",
        "0030_source_replaced_exchange",
    }:
        with session_scope(engine) as session:
            bootstrap_editable_layer(
                session,
                decisions=decisions,
                created_by="Alex",
                source_keys={"doc_exchange"},
            )
        with session_scope(engine) as session:
            object_id = session.scalar(select(EditableObject.id))
            assert object_id
    else:
        # Los modelos ORM representan la revisión actual. Para probar migraciones
        # desde 0012–0017 se insertan los registros con el esquema histórico real,
        # sin consultar columnas agregadas posteriormente como
        # editable_pages.revision_number.
        now = datetime.now(timezone.utc)
        page_id = new_id()
        object_id = new_id()
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO editable_pages (
                        id, digital_object_id, page_number,
                        source_extraction_run_id, source_extraction_page_id,
                        source_selection_id, status, bootstrapped_by,
                        bootstrapped_at, updated_at, review_status,
                        review_note, reviewed_by, reviewed_at
                    ) VALUES (
                        :id, :digital_object_id, 1,
                        :source_extraction_run_id, :source_extraction_page_id,
                        :source_selection_id, 'active', 'Alex',
                        :created_at, :created_at, 'unreviewed',
                        NULL, NULL, NULL
                    )
                    """
                ),
                {
                    "id": page_id,
                    "digital_object_id": historical_seed["digital_object_id"],
                    "source_extraction_run_id": historical_seed["extraction_run_id"],
                    "source_extraction_page_id": historical_seed["extraction_page_id"],
                    "source_selection_id": historical_seed["selection_id"],
                    "created_at": now,
                },
            )
            connection.execute(
                text(
                    """
                    INSERT INTO editable_objects (
                        id, editable_page_id, digital_object_id, page_number,
                        source_extracted_object_id, source_origin_id,
                        current_text, current_object_type, current_order_index,
                        current_geometry_json, current_attributes_json,
                        lifecycle_status, revision_number, created_by,
                        created_at, updated_by, updated_at, review_status,
                        document_part_id
                    ) VALUES (
                        :id, :editable_page_id, :digital_object_id, 1,
                        :source_extracted_object_id, :source_origin_id,
                        :current_text, :current_object_type, :current_order_index,
                        :current_geometry_json, :current_attributes_json,
                        'active', 1, 'Alex',
                        :created_at, 'Alex', :created_at, 'unreviewed',
                        NULL
                    )
                    """
                ),
                {
                    "id": object_id,
                    "editable_page_id": page_id,
                    "digital_object_id": historical_seed["digital_object_id"],
                    "source_extracted_object_id": historical_seed["source_object_id"],
                    "source_origin_id": historical_seed["source_origin_id"],
                    "current_text": historical_seed["text"],
                    "current_object_type": historical_seed["object_type"],
                    "current_order_index": historical_seed["order_index"],
                    "current_geometry_json": json.dumps(
                        historical_seed["geometry_json"], ensure_ascii=False
                    ),
                    "current_attributes_json": json.dumps(
                        historical_seed["attributes_json"], ensure_ascii=False
                    ),
                    "created_at": now,
                },
            )
            connection.execute(
                text(
                    """
                    INSERT INTO editable_object_revisions (
                        id, editable_object_id, revision_number,
                        base_revision_number, operation, text, object_type,
                        order_index, geometry_json, attributes_json,
                        lifecycle_status, note, created_by, created_at,
                        document_part_id
                    ) VALUES (
                        :id, :editable_object_id, 1,
                        NULL, 'import', :text, :object_type,
                        :order_index, :geometry_json, :attributes_json,
                        'active',
                        'Importado desde la extracción seleccionada; OCR original inmutable',
                        'Alex', :created_at, NULL
                    )
                    """
                ),
                {
                    "id": new_id(),
                    "editable_object_id": object_id,
                    "text": historical_seed["text"],
                    "object_type": historical_seed["object_type"],
                    "order_index": historical_seed["order_index"],
                    "geometry_json": json.dumps(
                        historical_seed["geometry_json"], ensure_ascii=False
                    ),
                    "attributes_json": json.dumps(
                        historical_seed["attributes_json"], ensure_ascii=False
                    ),
                    "created_at": now,
                },
            )

    return engine, decisions, object_id


def test_exchange_migration_upgrades_existing_0012_database(tmp_path: Path) -> None:
    root = tmp_path / "project"
    upgrade_database(root, revision="0012_editable_search_fts")
    assert current_revision(root) == "0012_editable_search_fts"
    upgrade_database(root)
    assert current_revision(root) == "0043_form_structure_review"
    engine = create_sqlite_engine(database_path(root))
    try:
        tables = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()
    assert {
        "exchange_workspaces",
        "exchange_change_events",
        "exchange_checkpoints",
        "exchange_bundle_records",
        "exchange_dry_runs",
        "exchange_incoming_event_assessments",
    } <= tables



def test_dry_run_migration_upgrades_populated_0013_database(tmp_path: Path) -> None:
    root = tmp_path / "project"
    engine, _decisions, object_id = _seed_project(
        root, revision="0013_offline_exchange_log"
    )
    try:
        with session_scope(engine) as session:
            assert session.get(EditableObject, object_id) is not None
    finally:
        engine.dispose()
    assert current_revision(root) == "0013_offline_exchange_log"
    upgrade_database(root)
    assert current_revision(root) == "0043_form_structure_review"
    engine = create_sqlite_engine(database_path(root))
    try:
        tables = set(inspect(engine).get_table_names())
        with session_scope(engine) as session:
            assert session.get(EditableObject, object_id) is not None
    finally:
        engine.dispose()
    assert {"exchange_dry_runs", "exchange_incoming_event_assessments"} <= tables

def test_checkpoint_sets_baseline_and_edit_creates_event(tmp_path: Path) -> None:
    root = tmp_path / "project"
    engine, decisions, object_id = _seed_project(root)
    try:
        with session_scope(engine) as session:
            workspace = ensure_exchange_workspace(
                session, workspace_name="alex-pc", changed_by="Alex"
            )
            baseline = create_exchange_checkpoint(
                session, label="baseline", created_by="Alex"
            )
            assert workspace.workspace_name == "alex-pc"
            assert baseline.sequence_number == 2  # vínculo digital + importación inicial editable
        with session_scope(engine) as session:
            update_editable_object(
                session,
                decisions=decisions,
                object_id=object_id,
                expected_revision=1,
                edited_by="Alex",
                text="Texto corregido",
            )
        with session_scope(engine) as session:
            events = session.scalars(
                select(ExchangeChangeEvent).order_by(ExchangeChangeEvent.sequence_number)
            ).all()
            assert len(events) == 3
            assert events[-1].entity_id == object_id
            assert events[-1].changed_fields_json["text"] == ["Texto OCR", "Texto corregido"]
            status = exchange_status(session)
            assert status.pending_event_count == 1
    finally:
        engine.dispose()


def test_bundle_export_and_inspection_are_verifiable(tmp_path: Path) -> None:
    root = tmp_path / "project"
    engine, decisions, object_id = _seed_project(root)
    try:
        with session_scope(engine) as session:
            ensure_exchange_workspace(
                session, workspace_name="alex-pc", changed_by="Alex"
            )
            baseline = create_exchange_checkpoint(
                session, label="baseline", created_by="Alex"
            )
        with session_scope(engine) as session:
            update_editable_object(
                session,
                decisions=decisions,
                object_id=object_id,
                expected_revision=1,
                edited_by="Alex",
                text="Texto corregido",
            )
        with session_scope(engine) as session:
            summary = export_change_bundle(
                session,
                project_root=root,
                checkpoint_ref=baseline.id,
                created_by="Alex",
            )
            assert summary.event_count == 1
            assert summary.output_path.is_file()
        inspection = inspect_change_bundle(summary.output_path)
        assert inspection.event_count == 1
        assert inspection.manifest.source_workspace_name == "alex-pc"
        assert inspection.manifest.base_checkpoint_label == "baseline"
        with session_scope(engine) as session:
            checkpoints = session.scalars(select(ExchangeCheckpoint)).all()
            assert len(checkpoints) == 2
            assert exchange_status(session).pending_event_count == 0
    finally:
        engine.dispose()


def test_bundle_tampering_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "project"
    engine, decisions, object_id = _seed_project(root)
    try:
        with session_scope(engine) as session:
            create_exchange_checkpoint(session, label="baseline", created_by="Alex")
        with session_scope(engine) as session:
            update_editable_object(
                session,
                decisions=decisions,
                object_id=object_id,
                expected_revision=1,
                edited_by="Alex",
                text="Texto corregido",
            )
        with session_scope(engine) as session:
            summary = export_change_bundle(
                session,
                project_root=root,
                checkpoint_ref="baseline",
                created_by="Alex",
            )
        tampered = root / "exchange/incoming/tampered.zip"
        tampered.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(summary.output_path, "r") as source, zipfile.ZipFile(
            tampered, "w"
        ) as target:
            for name in source.namelist():
                payload = source.read(name)
                if name == "changes.jsonl":
                    payload += b"{}\n"
                target.writestr(name, payload)
        with pytest.raises(ValueError, match="checksum"):
            inspect_change_bundle(tampered)
    finally:
        engine.dispose()


def test_empty_bundle_keeps_equal_sequence_bounds(tmp_path: Path) -> None:
    root = tmp_path / "project"
    engine, _decisions, _object_id = _seed_project(root)
    try:
        with session_scope(engine) as session:
            checkpoint = create_exchange_checkpoint(
                session, label="baseline", created_by="Alex"
            )
        with session_scope(engine) as session:
            summary = export_change_bundle(
                session,
                project_root=root,
                checkpoint_ref=checkpoint.id,
                created_by="Alex",
            )
        inspection = inspect_change_bundle(summary.output_path)
        assert summary.event_count == 0
        assert inspection.manifest.base_sequence == inspection.manifest.last_sequence
        assert inspection.first_sequence is None
    finally:
        engine.dispose()


def test_annotations_and_review_status_are_logged(tmp_path: Path) -> None:
    root = tmp_path / "project"
    engine, _decisions, object_id = _seed_project(root)
    try:
        with session_scope(engine) as session:
            baseline = create_exchange_checkpoint(
                session, label="baseline", created_by="Alex"
            )
            obj = session.get(EditableObject, object_id)
            assert obj
            editable_page_id = obj.editable_page_id
        with session_scope(engine) as session:
            add_object_comment(
                session, object_id=object_id, body="Revisar nombre", created_by="Alex"
            )
            add_object_tag(
                session,
                object_id=object_id,
                tag="vigilancia",
                tag_kind="conceptual",
                created_by="Alex",
            )
            set_object_review_status(
                session, object_id=object_id, status="reviewed", changed_by="Alex"
            )
            set_page_review_status(
                session,
                editable_page_id=editable_page_id,
                status="needs_review",
                changed_by="Alex",
                note="Falta revisar sello",
            )
        with session_scope(engine) as session:
            rows = session.scalars(
                select(ExchangeChangeEvent)
                .where(ExchangeChangeEvent.sequence_number > baseline.sequence_number)
                .order_by(ExchangeChangeEvent.sequence_number)
            ).all()
            assert [row.entity_type for row in rows] == [
                "editable_object_comment",
                "editable_object_tag",
                "editable_object",
                "editable_page",
            ]
            assert rows[2].changed_fields_json["review_status"] == [
                "unreviewed",
                "reviewed",
            ]
            assert rows[3].changed_fields_json["review_note"] == [
                None,
                "Falta revisar sello",
            ]
    finally:
        engine.dispose()


def test_existing_editable_state_becomes_baseline_without_invented_events(
    tmp_path: Path,
) -> None:
    root = tmp_path / "project"
    engine, _decisions, _object_id = _seed_project(
        root, revision="0012_editable_search_fts"
    )
    engine.dispose()
    assert current_revision(root) == "0012_editable_search_fts"
    upgrade_database(root)
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            assert session.scalar(select(ExchangeChangeEvent.id)) is None
            checkpoint = create_exchange_checkpoint(
                session, label="baseline", created_by="Alex"
            )
            assert checkpoint.sequence_number == 0
            assert len(checkpoint.state_sha256) == 64
    finally:
        engine.dispose()


def _reset_receiver_exchange_identity(root: Path, workspace_name: str) -> tuple[object, str]:
    from archive_workbench.db.models import (
        ExchangeBundleRecord,
        ExchangeChangeEvent,
        ExchangeDryRun,
        ExchangeIncomingEventAssessment,
        ExchangeWorkspace,
    )

    engine = create_sqlite_engine(database_path(root))
    with session_scope(engine) as session:
        session.query(ExchangeIncomingEventAssessment).delete()
        session.query(ExchangeDryRun).delete()
        session.query(ExchangeBundleRecord).delete()
        session.query(ExchangeCheckpoint).delete()
        session.query(ExchangeChangeEvent).delete()
        session.query(ExchangeWorkspace).delete()
        workspace = ensure_exchange_workspace(
            session, workspace_name=workspace_name, changed_by="Receiver"
        )
        checkpoint = create_exchange_checkpoint(
            session, label="baseline", created_by="Receiver"
        )
        workspace_id = workspace.id
        assert checkpoint.sequence_number == 0
    return engine, workspace_id


def _source_and_receiver(tmp_path: Path) -> tuple[Path, object, object, str, Path, object, str]:
    import shutil

    source_root = tmp_path / "source"
    source_engine, decisions, object_id = _seed_project(source_root)
    with session_scope(source_engine) as session:
        ensure_exchange_workspace(
            session, workspace_name="source-pc", changed_by="Source"
        )
        create_exchange_checkpoint(session, label="baseline", created_by="Source")
    source_engine.dispose()
    receiver_root = tmp_path / "receiver"
    shutil.copytree(source_root, receiver_root)
    receiver_engine, receiver_workspace_id = _reset_receiver_exchange_identity(
        receiver_root, "receiver-pc"
    )
    source_engine = create_sqlite_engine(database_path(source_root))
    return (
        source_root,
        source_engine,
        decisions,
        object_id,
        receiver_root,
        receiver_engine,
        receiver_workspace_id,
    )


def test_dry_run_classifies_clean_incoming_event_as_applicable(tmp_path: Path) -> None:
    from archive_workbench.db.models import ExchangeDryRun, ExchangeIncomingEventAssessment
    from archive_workbench.exchange import dry_run_change_bundle

    (
        source_root,
        source_engine,
        decisions,
        object_id,
        receiver_root,
        receiver_engine,
        _receiver_workspace_id,
    ) = _source_and_receiver(tmp_path)
    try:
        with session_scope(source_engine) as session:
            update_editable_object(
                session,
                decisions=decisions,
                object_id=object_id,
                expected_revision=1,
                edited_by="Source",
                text="Cambio remoto",
            )
        with session_scope(source_engine) as session:
            bundle = export_change_bundle(
                session,
                project_root=source_root,
                checkpoint_ref="baseline",
                created_by="Source",
            )
        with session_scope(receiver_engine) as session:
            before = session.get(EditableObject, object_id).current_text
            summary = dry_run_change_bundle(
                session,
                project_root=receiver_root,
                bundle_path=bundle.output_path,
                assessed_by="Receiver",
            )
            after = session.get(EditableObject, object_id).current_text
            assert before == after == "Texto OCR"
            assert summary.base_match_status == "matched"
            assert summary.overall_status == "ready_to_apply"
            assert summary.counts == {
                "apply": 1,
                "duplicate": 0,
                "review": 0,
                "conflict": 0,
            }
            assert summary.report_json_path.is_file()
            assert summary.report_markdown_path.is_file()
            assert session.scalar(select(ExchangeDryRun.id))
            assessment = session.scalar(select(ExchangeIncomingEventAssessment))
            assert assessment and assessment.disposition == "apply"
    finally:
        source_engine.dispose()
        receiver_engine.dispose()


def test_dry_run_detects_same_field_conflict(tmp_path: Path) -> None:
    from archive_workbench.exchange import dry_run_change_bundle

    (
        source_root,
        source_engine,
        decisions,
        object_id,
        receiver_root,
        receiver_engine,
        _receiver_workspace_id,
    ) = _source_and_receiver(tmp_path)
    try:
        with session_scope(source_engine) as session:
            update_editable_object(
                session,
                decisions=decisions,
                object_id=object_id,
                expected_revision=1,
                edited_by="Source",
                text="Cambio remoto",
            )
        with session_scope(receiver_engine) as session:
            update_editable_object(
                session,
                decisions=decisions,
                object_id=object_id,
                expected_revision=1,
                edited_by="Receiver",
                text="Cambio local",
            )
        with session_scope(source_engine) as session:
            bundle = export_change_bundle(
                session,
                project_root=source_root,
                checkpoint_ref="baseline",
                created_by="Source",
            )
        with session_scope(receiver_engine) as session:
            summary = dry_run_change_bundle(
                session,
                project_root=receiver_root,
                bundle_path=bundle.output_path,
                assessed_by="Receiver",
            )
            assert summary.overall_status == "conflicts"
            assert summary.counts["conflict"] == 1
            assert session.get(EditableObject, object_id).current_text == "Cambio local"
    finally:
        source_engine.dispose()
        receiver_engine.dispose()


def test_dry_run_recognizes_equivalent_local_change_as_duplicate(tmp_path: Path) -> None:
    from archive_workbench.exchange import dry_run_change_bundle

    (
        source_root,
        source_engine,
        decisions,
        object_id,
        receiver_root,
        receiver_engine,
        _receiver_workspace_id,
    ) = _source_and_receiver(tmp_path)
    try:
        for engine, actor in ((source_engine, "Source"), (receiver_engine, "Receiver")):
            with session_scope(engine) as session:
                update_editable_object(
                    session,
                    decisions=decisions,
                    object_id=object_id,
                    expected_revision=1,
                    edited_by=actor,
                    text="Mismo cambio",
                )
        with session_scope(source_engine) as session:
            bundle = export_change_bundle(
                session,
                project_root=source_root,
                checkpoint_ref="baseline",
                created_by="Source",
            )
        with session_scope(receiver_engine) as session:
            summary = dry_run_change_bundle(
                session,
                project_root=receiver_root,
                bundle_path=bundle.output_path,
                assessed_by="Receiver",
            )
            assert summary.counts["duplicate"] == 1
            assert summary.overall_status == "ready_to_apply"
    finally:
        source_engine.dispose()
        receiver_engine.dispose()


def test_dry_run_recognizes_applied_bundle_lineage_after_local_resolution(
    tmp_path: Path,
) -> None:
    from archive_workbench.exchange import (
        finalize_bundle_resolutions,
        resolve_conflict_fields_bulk,
    )

    (
        source_root,
        source_engine,
        decisions,
        object_id,
        receiver_root,
        receiver_engine,
        _receiver_workspace_id,
    ) = _source_and_receiver(tmp_path)
    try:
        with session_scope(source_engine) as session:
            update_editable_object(
                session,
                decisions=decisions,
                object_id=object_id,
                expected_revision=1,
                edited_by="Source",
                text="Texto remoto",
            )
        with session_scope(receiver_engine) as session:
            update_editable_object(
                session,
                decisions=decisions,
                object_id=object_id,
                expected_revision=1,
                edited_by="Receiver",
                text="Texto local",
            )
        with session_scope(source_engine) as session:
            first_bundle = export_change_bundle(
                session,
                project_root=source_root,
                checkpoint_ref="baseline",
                created_by="Source",
            )
        with session_scope(receiver_engine) as session:
            first_dry = dry_run_change_bundle(
                session,
                project_root=receiver_root,
                bundle_path=first_bundle.output_path,
                assessed_by="Receiver",
            )
            assert first_dry.overall_status == "conflicts"
            resolve_conflict_fields_bulk(
                session,
                bundle_ref=first_bundle.bundle_id,
                choice="local",
                resolved_by="Receiver",
            )
            finalize_bundle_resolutions(
                session,
                bundle_ref=first_bundle.bundle_id,
                finalized_by="Receiver",
            )
        with session_scope(receiver_engine) as session:
            apply_change_bundle(
                session,
                project_root=receiver_root,
                bundle_ref=first_bundle.bundle_id,
                applied_by="Receiver",
            )
            assert session.get(EditableObject, object_id).current_text == "Texto local"

        with session_scope(source_engine) as session:
            update_editable_object(
                session,
                decisions=decisions,
                object_id=object_id,
                expected_revision=2,
                edited_by="Source",
                object_type="title",
            )
            second_bundle = export_change_bundle(
                session,
                project_root=source_root,
                checkpoint_ref=first_bundle.next_checkpoint_label,
                created_by="Source",
            )

        with session_scope(receiver_engine) as session:
            second_dry = dry_run_change_bundle(
                session,
                project_root=receiver_root,
                bundle_path=second_bundle.output_path,
                assessed_by="Receiver",
            )
            assert second_dry.base_match_status == "matched"
            assert second_dry.overall_status == "ready_to_apply"
            assert second_dry.counts == {
                "apply": 1,
                "duplicate": 0,
                "review": 0,
                "conflict": 0,
            }
            report = second_dry.report_json_path.read_text(encoding="utf-8")
            assert "bundle previamente aplicado" in report
        with session_scope(receiver_engine) as session:
            apply_change_bundle(
                session,
                project_root=receiver_root,
                bundle_ref=second_bundle.bundle_id,
                applied_by="Receiver",
            )
            obj = session.get(EditableObject, object_id)
            assert obj.current_text == "Texto local"
            assert obj.current_object_type == "title"
    finally:
        source_engine.dispose()
        receiver_engine.dispose()


def test_dry_run_without_common_checkpoint_requires_review(tmp_path: Path) -> None:
    from archive_workbench.exchange import dry_run_change_bundle

    (
        source_root,
        source_engine,
        decisions,
        object_id,
        receiver_root,
        receiver_engine,
        _receiver_workspace_id,
    ) = _source_and_receiver(tmp_path)
    try:
        with session_scope(source_engine) as session:
            update_editable_object(
                session,
                decisions=decisions,
                object_id=object_id,
                expected_revision=1,
                edited_by="Source",
                text="Cambio remoto",
            )
        with session_scope(source_engine) as session:
            bundle = export_change_bundle(
                session,
                project_root=source_root,
                checkpoint_ref="baseline",
                created_by="Source",
            )
        with session_scope(receiver_engine) as session:
            session.query(ExchangeCheckpoint).delete()
        with session_scope(receiver_engine) as session:
            summary = dry_run_change_bundle(
                session,
                project_root=receiver_root,
                bundle_path=bundle.output_path,
                assessed_by="Receiver",
            )
            assert summary.base_match_status == "unmatched"
            assert summary.overall_status == "needs_review"
            assert summary.counts["review"] == 1
    finally:
        source_engine.dispose()
        receiver_engine.dispose()


def test_fork_workspace_changes_identity_but_preserves_editable_state(tmp_path: Path) -> None:
    from archive_workbench.exchange import fork_exchange_workspace

    root = tmp_path / "project"
    engine, _decisions, object_id = _seed_project(root)
    try:
        with session_scope(engine) as session:
            old = ensure_exchange_workspace(
                session, workspace_name="original", changed_by="Alex"
            )
            create_exchange_checkpoint(session, label="old-baseline", created_by="Alex")
            old_id = old.id
            text_before = session.get(EditableObject, object_id).current_text
        with session_scope(engine) as session:
            summary = fork_exchange_workspace(
                session,
                workspace_name="receiver-copy",
                created_by="Alex",
            )
            assert summary.previous_workspace_id == old_id
            assert summary.workspace_id != old_id
            assert summary.workspace_name == "receiver-copy"
            assert session.get(EditableObject, object_id).current_text == text_before
            assert exchange_status(session).current_sequence == 0
            checkpoints = session.scalars(select(ExchangeCheckpoint)).all()
            assert len(checkpoints) == 1
            assert checkpoints[0].label == "baseline"
    finally:
        engine.dispose()


def test_transactional_apply_migration_upgrades_populated_0014_database(tmp_path: Path) -> None:
    from archive_workbench.db.models import ExchangeDryRun

    root = tmp_path / "project"
    engine, _decisions, object_id = _seed_project(
        root, revision="0014_exchange_dry_run"
    )
    try:
        with session_scope(engine) as session:
            assert session.get(EditableObject, object_id) is not None
    finally:
        engine.dispose()
    assert current_revision(root) == "0014_exchange_dry_run"
    upgrade_database(root)
    assert current_revision(root) == "0043_form_structure_review"
    engine = create_sqlite_engine(database_path(root))
    try:
        tables = set(inspect(engine).get_table_names())
        columns = {
            row["name"]
            for row in inspect(engine).get_columns("exchange_incoming_event_assessments")
        }
        with session_scope(engine) as session:
            assert session.get(EditableObject, object_id) is not None
            assert session.scalar(select(ExchangeDryRun.id)) is None
    finally:
        engine.dispose()
    assert "exchange_bundle_applications" in tables
    assert {"application_id", "applied_at"} <= columns


def test_apply_ready_bundle_is_transactional_and_creates_backup(tmp_path: Path) -> None:
    from archive_workbench.db.models import (
        ExchangeBundleApplication,
        ExchangeDryRun,
        ExchangeIncomingEventAssessment,
    )
    from archive_workbench.exchange import apply_change_bundle, dry_run_change_bundle
    from archive_workbench.identity import sha256_file

    (
        source_root,
        source_engine,
        decisions,
        object_id,
        receiver_root,
        receiver_engine,
        _receiver_workspace_id,
    ) = _source_and_receiver(tmp_path)
    try:
        with session_scope(source_engine) as session:
            update_editable_object(
                session,
                decisions=decisions,
                object_id=object_id,
                expected_revision=1,
                edited_by="Source",
                text="Cambio remoto aplicado",
            )
        with session_scope(source_engine) as session:
            bundle = export_change_bundle(
                session,
                project_root=source_root,
                checkpoint_ref="baseline",
                created_by="Source",
            )
        with session_scope(receiver_engine) as session:
            dry = dry_run_change_bundle(
                session,
                project_root=receiver_root,
                bundle_path=bundle.output_path,
                assessed_by="Receiver",
            )
            assert dry.overall_status == "ready_to_apply"
        with session_scope(receiver_engine) as session:
            summary = apply_change_bundle(
                session,
                project_root=receiver_root,
                bundle_ref=bundle.bundle_id,
                applied_by="Receiver",
            )
            assert summary.applied_event_count == 1
            assert summary.duplicate_event_count == 0
            assert summary.backup_path.is_file()
            assert sha256_file(summary.backup_path) == summary.backup_sha256
            assert session.get(EditableObject, object_id).current_text == "Cambio remoto aplicado"
        with session_scope(receiver_engine) as session:
            app = session.scalar(select(ExchangeBundleApplication))
            assert app and app.status == "applied"
            dry_row = session.scalar(select(ExchangeDryRun))
            assert dry_row and dry_row.overall_status == "applied"
            assessment = session.scalar(select(ExchangeIncomingEventAssessment))
            assert assessment and assessment.application_status == "applied"
            assert assessment.application_id == app.id
            assert app.checkpoint_id
    finally:
        source_engine.dispose()
        receiver_engine.dispose()


def test_apply_refuses_conflicted_bundle_before_backup(tmp_path: Path) -> None:
    from archive_workbench.exchange import apply_change_bundle, dry_run_change_bundle

    (
        source_root,
        source_engine,
        decisions,
        object_id,
        receiver_root,
        receiver_engine,
        _receiver_workspace_id,
    ) = _source_and_receiver(tmp_path)
    try:
        with session_scope(source_engine) as session:
            update_editable_object(
                session,
                decisions=decisions,
                object_id=object_id,
                expected_revision=1,
                edited_by="Source",
                text="Cambio remoto",
            )
        with session_scope(receiver_engine) as session:
            update_editable_object(
                session,
                decisions=decisions,
                object_id=object_id,
                expected_revision=1,
                edited_by="Receiver",
                text="Cambio local",
            )
        with session_scope(source_engine) as session:
            bundle = export_change_bundle(
                session,
                project_root=source_root,
                checkpoint_ref="baseline",
                created_by="Source",
            )
        with session_scope(receiver_engine) as session:
            dry = dry_run_change_bundle(
                session,
                project_root=receiver_root,
                bundle_path=bundle.output_path,
                assessed_by="Receiver",
            )
            assert dry.overall_status == "conflicts"
        with pytest.raises(ValueError, match="no puede aplicarse"):
            with session_scope(receiver_engine) as session:
                apply_change_bundle(
                    session,
                    project_root=receiver_root,
                    bundle_ref=bundle.bundle_id,
                    applied_by="Receiver",
                )
        assert not list((receiver_root / "exchange/backups").glob("*.sqlite3"))
        with session_scope(receiver_engine) as session:
            assert session.get(EditableObject, object_id).current_text == "Cambio local"
    finally:
        source_engine.dispose()
        receiver_engine.dispose()


def test_apply_duplicate_bundle_marks_event_without_replaying_change(tmp_path: Path) -> None:
    from archive_workbench.db.models import ExchangeIncomingEventAssessment
    from archive_workbench.exchange import apply_change_bundle, dry_run_change_bundle

    (
        source_root,
        source_engine,
        decisions,
        object_id,
        receiver_root,
        receiver_engine,
        _receiver_workspace_id,
    ) = _source_and_receiver(tmp_path)
    try:
        for engine, actor in ((source_engine, "Source"), (receiver_engine, "Receiver")):
            with session_scope(engine) as session:
                update_editable_object(
                    session,
                    decisions=decisions,
                    object_id=object_id,
                    expected_revision=1,
                    edited_by=actor,
                    text="Mismo cambio",
                )
        with session_scope(source_engine) as session:
            bundle = export_change_bundle(
                session,
                project_root=source_root,
                checkpoint_ref="baseline",
                created_by="Source",
            )
        with session_scope(receiver_engine) as session:
            dry = dry_run_change_bundle(
                session,
                project_root=receiver_root,
                bundle_path=bundle.output_path,
                assessed_by="Receiver",
            )
            assert dry.counts["duplicate"] == 1
        with session_scope(receiver_engine) as session:
            summary = apply_change_bundle(
                session,
                project_root=receiver_root,
                bundle_ref=bundle.bundle_id,
                applied_by="Receiver",
            )
            assert summary.applied_event_count == 0
            assert summary.duplicate_event_count == 1
            assert session.get(EditableObject, object_id).revision_number == 2
        with session_scope(receiver_engine) as session:
            assessment = session.scalar(select(ExchangeIncomingEventAssessment))
            assert assessment and assessment.application_status == "skipped_duplicate"
    finally:
        source_engine.dispose()
        receiver_engine.dispose()


def test_applied_bundle_cannot_be_applied_twice(tmp_path: Path) -> None:
    from archive_workbench.exchange import apply_change_bundle, dry_run_change_bundle

    (
        source_root,
        source_engine,
        decisions,
        object_id,
        receiver_root,
        receiver_engine,
        _receiver_workspace_id,
    ) = _source_and_receiver(tmp_path)
    try:
        with session_scope(source_engine) as session:
            update_editable_object(
                session,
                decisions=decisions,
                object_id=object_id,
                expected_revision=1,
                edited_by="Source",
                text="Cambio remoto",
            )
        with session_scope(source_engine) as session:
            bundle = export_change_bundle(
                session,
                project_root=source_root,
                checkpoint_ref="baseline",
                created_by="Source",
            )
        with session_scope(receiver_engine) as session:
            dry_run_change_bundle(
                session,
                project_root=receiver_root,
                bundle_path=bundle.output_path,
                assessed_by="Receiver",
            )
        with session_scope(receiver_engine) as session:
            apply_change_bundle(
                session,
                project_root=receiver_root,
                bundle_ref=bundle.bundle_id,
                applied_by="Receiver",
            )
        with pytest.raises(ValueError, match="ya fue aplicado"):
            with session_scope(receiver_engine) as session:
                apply_change_bundle(
                    session,
                    project_root=receiver_root,
                    bundle_ref=bundle.bundle_id,
                    applied_by="Receiver",
                )
    finally:
        source_engine.dispose()
        receiver_engine.dispose()



def test_delete_event_only_contains_lifecycle_precondition(tmp_path: Path) -> None:
    root = tmp_path / "project"
    engine, _decisions, object_id = _seed_project(root)
    try:
        with session_scope(engine) as session:
            create_exchange_checkpoint(session, label="baseline", created_by="Alex")
        with session_scope(engine) as session:
            set_editable_object_lifecycle(
                session,
                object_id=object_id,
                expected_revision=1,
                lifecycle_status="deleted",
                changed_by="Alex",
            )
        with session_scope(engine) as session:
            event = session.scalar(
                select(ExchangeChangeEvent)
                .where(ExchangeChangeEvent.operation == "delete")
                .order_by(ExchangeChangeEvent.sequence_number.desc())
            )
            assert event
            assert event.changed_fields_json == {
                "lifecycle_status": ["active", "deleted"]
            }
    finally:
        engine.dispose()


def test_apply_delete_bundle_preserves_text_and_deletes_logically(tmp_path: Path) -> None:
    from archive_workbench.exchange import apply_change_bundle, dry_run_change_bundle

    (
        source_root,
        source_engine,
        _decisions,
        object_id,
        receiver_root,
        receiver_engine,
        _receiver_workspace_id,
    ) = _source_and_receiver(tmp_path)
    try:
        with session_scope(source_engine) as session:
            set_editable_object_lifecycle(
                session,
                object_id=object_id,
                expected_revision=1,
                lifecycle_status="deleted",
                changed_by="Source",
            )
        with session_scope(source_engine) as session:
            bundle = export_change_bundle(
                session,
                project_root=source_root,
                checkpoint_ref="baseline",
                created_by="Source",
            )
        with session_scope(receiver_engine) as session:
            dry = dry_run_change_bundle(
                session,
                project_root=receiver_root,
                bundle_path=bundle.output_path,
                assessed_by="Receiver",
            )
            assert dry.overall_status == "ready_to_apply"
            assert dry.counts["apply"] == 1
        with session_scope(receiver_engine) as session:
            apply_change_bundle(
                session,
                project_root=receiver_root,
                bundle_ref=bundle.bundle_id,
                applied_by="Receiver",
            )
            obj = session.get(EditableObject, object_id)
            assert obj
            assert obj.lifecycle_status == "deleted"
            assert obj.current_text == "Texto OCR"
            assert obj.revision_number == 2
    finally:
        source_engine.dispose()
        receiver_engine.dispose()


def test_delete_then_restore_roundtrip_can_be_applied(tmp_path: Path) -> None:
    from archive_workbench.exchange import apply_change_bundle, dry_run_change_bundle

    (
        source_root,
        source_engine,
        _decisions,
        object_id,
        receiver_root,
        receiver_engine,
        _receiver_workspace_id,
    ) = _source_and_receiver(tmp_path)
    try:
        with session_scope(source_engine) as session:
            set_editable_object_lifecycle(
                session,
                object_id=object_id,
                expected_revision=1,
                lifecycle_status="deleted",
                changed_by="Source",
            )
        with session_scope(source_engine) as session:
            delete_bundle = export_change_bundle(
                session,
                project_root=source_root,
                checkpoint_ref="baseline",
                created_by="Source",
            )
        with session_scope(receiver_engine) as session:
            dry_run_change_bundle(
                session,
                project_root=receiver_root,
                bundle_path=delete_bundle.output_path,
                assessed_by="Receiver",
            )
        with session_scope(receiver_engine) as session:
            apply_change_bundle(
                session,
                project_root=receiver_root,
                bundle_ref=delete_bundle.bundle_id,
                applied_by="Receiver",
            )

        with session_scope(source_engine) as session:
            set_editable_object_lifecycle(
                session,
                object_id=object_id,
                expected_revision=2,
                lifecycle_status="active",
                changed_by="Source",
            )
        with session_scope(source_engine) as session:
            restore_bundle = export_change_bundle(
                session,
                project_root=source_root,
                checkpoint_ref=None,
                created_by="Source",
            )
        with session_scope(receiver_engine) as session:
            dry = dry_run_change_bundle(
                session,
                project_root=receiver_root,
                bundle_path=restore_bundle.output_path,
                assessed_by="Receiver",
            )
            assert dry.overall_status == "ready_to_apply"
        with session_scope(receiver_engine) as session:
            apply_change_bundle(
                session,
                project_root=receiver_root,
                bundle_ref=restore_bundle.bundle_id,
                applied_by="Receiver",
            )
            obj = session.get(EditableObject, object_id)
            assert obj and obj.lifecycle_status == "active"
            assert obj.current_text == "Texto OCR"
            assert obj.revision_number == 3
    finally:
        source_engine.dispose()
        receiver_engine.dispose()


def test_apply_rejects_stale_dry_run_before_creating_backup(tmp_path: Path) -> None:
    from archive_workbench.exchange import (
        apply_change_bundle,
        dry_run_change_bundle,
        incoming_bundle_rows,
    )

    (
        source_root,
        source_engine,
        decisions,
        object_id,
        receiver_root,
        receiver_engine,
        _receiver_workspace_id,
    ) = _source_and_receiver(tmp_path)
    try:
        with session_scope(source_engine) as session:
            update_editable_object(
                session,
                decisions=decisions,
                object_id=object_id,
                expected_revision=1,
                edited_by="Source",
                text="Cambio remoto",
            )
        with session_scope(source_engine) as session:
            bundle = export_change_bundle(
                session,
                project_root=source_root,
                checkpoint_ref="baseline",
                created_by="Source",
            )
        with session_scope(receiver_engine) as session:
            dry_run_change_bundle(
                session,
                project_root=receiver_root,
                bundle_path=bundle.output_path,
                assessed_by="Receiver",
            )
        with session_scope(receiver_engine) as session:
            add_object_comment(
                session,
                object_id=object_id,
                body="Cambio local posterior al dry-run",
                created_by="Receiver",
            )
        with session_scope(receiver_engine) as session:
            assert incoming_bundle_rows(session)[0].status == "stale"
        with pytest.raises(ValueError, match="dry-run caducó"):
            with session_scope(receiver_engine) as session:
                apply_change_bundle(
                    session,
                    project_root=receiver_root,
                    bundle_ref=bundle.bundle_id,
                    applied_by="Receiver",
                )
        assert not list((receiver_root / "exchange/backups").glob("*.sqlite3"))
    finally:
        source_engine.dispose()
        receiver_engine.dispose()


def test_legacy_delete_event_with_spurious_text_is_normalized(tmp_path: Path) -> None:
    import hashlib
    import json

    from archive_workbench.exchange import apply_change_bundle, dry_run_change_bundle

    (
        source_root,
        source_engine,
        _decisions,
        object_id,
        receiver_root,
        receiver_engine,
        _receiver_workspace_id,
    ) = _source_and_receiver(tmp_path)
    try:
        with session_scope(source_engine) as session:
            set_editable_object_lifecycle(
                session,
                object_id=object_id,
                expected_revision=1,
                lifecycle_status="deleted",
                changed_by="Source",
            )
        with session_scope(source_engine) as session:
            bundle = export_change_bundle(
                session,
                project_root=source_root,
                checkpoint_ref="baseline",
                created_by="Source",
            )

        legacy = source_root / "exchange/outgoing/legacy_delete.zip"
        with zipfile.ZipFile(bundle.output_path, "r") as archive:
            manifest = json.loads(archive.read("manifest.json"))
            event = json.loads(archive.read("changes.jsonl").decode("utf-8").strip())
        event["changed_fields"]["text"] = [None, "Texto OCR"]
        changes_bytes = (
            json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            + "\n"
        ).encode("utf-8")
        manifest["changes_sha256"] = hashlib.sha256(changes_bytes).hexdigest()
        manifest_bytes = json.dumps(
            manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        checksums = (
            f"{hashlib.sha256(manifest_bytes).hexdigest()}  manifest.json\n"
            f"{hashlib.sha256(changes_bytes).hexdigest()}  changes.jsonl\n"
        ).encode("utf-8")
        with zipfile.ZipFile(legacy, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", manifest_bytes)
            archive.writestr("changes.jsonl", changes_bytes)
            archive.writestr("checksums.sha256", checksums)

        with session_scope(receiver_engine) as session:
            dry = dry_run_change_bundle(
                session,
                project_root=receiver_root,
                bundle_path=legacy,
                assessed_by="Receiver",
            )
            assert dry.overall_status == "ready_to_apply"
        with session_scope(receiver_engine) as session:
            apply_change_bundle(
                session,
                project_root=receiver_root,
                bundle_ref=bundle.bundle_id,
                applied_by="Receiver",
            )
            obj = session.get(EditableObject, object_id)
            assert obj and obj.lifecycle_status == "deleted"
            assert obj.current_text == "Texto OCR"
    finally:
        source_engine.dispose()
        receiver_engine.dispose()


def test_delete_precondition_migration_upgrades_populated_0015_database(tmp_path: Path) -> None:
    root = tmp_path / "project"
    engine, _decisions, object_id = _seed_project(
        root, revision="0015_exchange_transactional_apply"
    )
    try:
        with session_scope(engine) as session:
            assert session.get(EditableObject, object_id) is not None
    finally:
        engine.dispose()
    assert current_revision(root) == "0015_exchange_transactional_apply"
    upgrade_database(root)
    assert current_revision(root) == "0043_form_structure_review"
    engine = create_sqlite_engine(database_path(root))
    try:
        columns = {
            row["name"] for row in inspect(engine).get_columns("exchange_dry_runs")
        }
        with session_scope(engine) as session:
            assert session.get(EditableObject, object_id) is not None
    finally:
        engine.dispose()
    assert {"assessed_state_sha256", "assessed_sequence_number"} <= columns


def test_conflict_resolution_migration_upgrades_populated_0016_database(tmp_path: Path) -> None:
    root = tmp_path / "project"
    engine, _decisions, object_id = _seed_project(
        root, revision="0016_exchange_delete_preconditions"
    )
    engine.dispose()
    assert current_revision(root) == "0016_exchange_delete_preconditions"
    upgrade_database(root)
    assert current_revision(root) == "0043_form_structure_review"
    engine = create_sqlite_engine(database_path(root))
    try:
        tables = set(inspect(engine).get_table_names())
        with session_scope(engine) as session:
            assert session.get(EditableObject, object_id) is not None
    finally:
        engine.dispose()
    assert "exchange_conflict_resolutions" in tables


def test_conflict_can_be_resolved_field_by_field_and_applied(tmp_path: Path) -> None:
    from archive_workbench.exchange import (
        apply_change_bundle,
        conflict_field_rows,
        dry_run_change_bundle,
        finalize_bundle_resolutions,
        resolution_status,
        save_conflict_resolution,
    )

    (
        source_root,
        source_engine,
        decisions,
        object_id,
        receiver_root,
        receiver_engine,
        _receiver_workspace_id,
    ) = _source_and_receiver(tmp_path)
    try:
        with session_scope(source_engine) as session:
            update_editable_object(
                session,
                decisions=decisions,
                object_id=object_id,
                expected_revision=1,
                edited_by="Source",
                text="Cambio remoto",
            )
        with session_scope(receiver_engine) as session:
            update_editable_object(
                session,
                decisions=decisions,
                object_id=object_id,
                expected_revision=1,
                edited_by="Receiver",
                text="Cambio local",
            )
        with session_scope(source_engine) as session:
            bundle = export_change_bundle(
                session,
                project_root=source_root,
                checkpoint_ref="baseline",
                created_by="Source",
            )
        with session_scope(receiver_engine) as session:
            dry = dry_run_change_bundle(
                session,
                project_root=receiver_root,
                bundle_path=bundle.output_path,
                assessed_by="Receiver",
            )
            assert dry.overall_status == "conflicts"
            rows = conflict_field_rows(session, bundle.bundle_id)
            assert len(rows) == 1
            assert rows[0].field_name == "text"
            assert rows[0].base_value == "Texto OCR"
            assert rows[0].local_value == "Cambio local"
            assert rows[0].incoming_value == "Cambio remoto"
            save_conflict_resolution(
                session,
                bundle_ref=bundle.bundle_id,
                event_id=rows[0].event_id,
                field_name="text",
                choice="incoming",
                resolved_by="Receiver",
            )
            assert resolution_status(session, bundle.bundle_id).overall_status == "ready_to_finalize"
            final = finalize_bundle_resolutions(
                session,
                bundle_ref=bundle.bundle_id,
                finalized_by="Receiver",
            )
            assert final.overall_status == "ready_to_apply_resolved"
        with session_scope(receiver_engine) as session:
            summary = apply_change_bundle(
                session,
                project_root=receiver_root,
                bundle_ref=bundle.bundle_id,
                applied_by="Receiver",
            )
            assert summary.applied_event_count == 1
            assert session.get(EditableObject, object_id).current_text == "Cambio remoto"
    finally:
        source_engine.dispose()
        receiver_engine.dispose()


def test_conflict_custom_resolution_is_applied(tmp_path: Path) -> None:
    from archive_workbench.exchange import (
        apply_change_bundle,
        conflict_field_rows,
        dry_run_change_bundle,
        finalize_bundle_resolutions,
        save_conflict_resolution,
    )

    (
        source_root,
        source_engine,
        decisions,
        object_id,
        receiver_root,
        receiver_engine,
        _receiver_workspace_id,
    ) = _source_and_receiver(tmp_path)
    try:
        with session_scope(source_engine) as session:
            update_editable_object(
                session, decisions=decisions, object_id=object_id,
                expected_revision=1, edited_by="Source", text="Remoto",
            )
        with session_scope(receiver_engine) as session:
            update_editable_object(
                session, decisions=decisions, object_id=object_id,
                expected_revision=1, edited_by="Receiver", text="Local",
            )
        with session_scope(source_engine) as session:
            bundle = export_change_bundle(
                session, project_root=source_root, checkpoint_ref="baseline", created_by="Source"
            )
        with session_scope(receiver_engine) as session:
            dry_run_change_bundle(
                session, project_root=receiver_root, bundle_path=bundle.output_path,
                assessed_by="Receiver",
            )
            row = conflict_field_rows(session, bundle.bundle_id)[0]
            save_conflict_resolution(
                session, bundle_ref=bundle.bundle_id, event_id=row.event_id,
                field_name="text", choice="custom", custom_value="Texto conciliado",
                resolved_by="Receiver",
            )
            finalize_bundle_resolutions(
                session, bundle_ref=bundle.bundle_id, finalized_by="Receiver"
            )
        with session_scope(receiver_engine) as session:
            apply_change_bundle(
                session, project_root=receiver_root, bundle_ref=bundle.bundle_id,
                applied_by="Receiver",
            )
            assert session.get(EditableObject, object_id).current_text == "Texto conciliado"
    finally:
        source_engine.dispose()
        receiver_engine.dispose()


def test_conflicted_event_can_be_explicitly_skipped(tmp_path: Path) -> None:
    from archive_workbench.exchange import (
        apply_change_bundle,
        conflict_field_rows,
        dry_run_change_bundle,
        finalize_bundle_resolutions,
        skip_conflicted_event,
    )

    (
        source_root,
        source_engine,
        decisions,
        object_id,
        receiver_root,
        receiver_engine,
        _receiver_workspace_id,
    ) = _source_and_receiver(tmp_path)
    try:
        with session_scope(source_engine) as session:
            update_editable_object(
                session, decisions=decisions, object_id=object_id,
                expected_revision=1, edited_by="Source", text="Remoto",
            )
        with session_scope(receiver_engine) as session:
            update_editable_object(
                session, decisions=decisions, object_id=object_id,
                expected_revision=1, edited_by="Receiver", text="Local",
            )
        with session_scope(source_engine) as session:
            bundle = export_change_bundle(
                session, project_root=source_root, checkpoint_ref="baseline", created_by="Source"
            )
        with session_scope(receiver_engine) as session:
            dry_run_change_bundle(
                session, project_root=receiver_root, bundle_path=bundle.output_path,
                assessed_by="Receiver",
            )
            event_id = conflict_field_rows(session, bundle.bundle_id)[0].event_id
            skip_conflicted_event(
                session, bundle_ref=bundle.bundle_id, event_id=event_id,
                resolved_by="Receiver", note="Se conserva la versión local",
            )
            finalize_bundle_resolutions(
                session, bundle_ref=bundle.bundle_id, finalized_by="Receiver"
            )
        with session_scope(receiver_engine) as session:
            summary = apply_change_bundle(
                session, project_root=receiver_root, bundle_ref=bundle.bundle_id,
                applied_by="Receiver",
            )
            assert summary.applied_event_count == 0
            assert summary.duplicate_event_count == 0
            assert summary.kept_local_event_count == 1
            assert session.get(EditableObject, object_id).current_text == "Local"
    finally:
        source_engine.dispose()
        receiver_engine.dispose()


def test_resolution_ignores_fields_already_equal_to_incoming(tmp_path: Path) -> None:
    from archive_workbench.contracts.changes import ChangeEvent
    from archive_workbench.db.models import Project
    from archive_workbench.exchange import (
        _event_auto_matched_fields,
        _event_fields_requiring_decision,
        ensure_exchange_workspace,
    )

    root = tmp_path / "project"
    engine, _decisions, object_id = _seed_project(root)
    try:
        with session_scope(engine) as session:
            obj = session.get(EditableObject, object_id)
            project = session.scalar(select(Project))
            workspace = ensure_exchange_workspace(session, workspace_name="local")
            assert obj is not None and project is not None
            event = ChangeEvent(
                event_id="00000000-0000-0000-0000-000000000001",
                project_id=project.id,
                workspace_id=workspace.id,
                sequence_number=1,
                transaction_id="00000000-0000-0000-0000-000000000002",
                entity_type="editable_object",
                entity_id=obj.id,
                operation="update",
                changed_fields={
                    "attributes": [None, obj.current_attributes_json or {}],
                    "geometry": [None, obj.current_geometry_json or []],
                    "lifecycle_status": [None, obj.lifecycle_status],
                    "object_type": [None, obj.current_object_type],
                    "order_index": [None, obj.current_order_index],
                    "text": [None, "Texto remoto"],
                },
                actor="Source",
            )
            assert _event_fields_requiring_decision(session, event) == ["text"]
            assert set(_event_auto_matched_fields(session, event)) == {
                "attributes",
                "geometry",
                "lifecycle_status",
                "object_type",
                "order_index",
            }
    finally:
        engine.dispose()


def test_bulk_resolution_and_finalize_are_idempotent(tmp_path: Path) -> None:
    from archive_workbench.exchange import (
        apply_change_bundle,
        conflict_field_rows,
        dry_run_change_bundle,
        finalize_bundle_resolutions,
        resolve_conflict_fields_bulk,
    )

    (
        source_root,
        source_engine,
        decisions,
        object_id,
        receiver_root,
        receiver_engine,
        _receiver_workspace_id,
    ) = _source_and_receiver(tmp_path)
    try:
        with session_scope(source_engine) as session:
            update_editable_object(
                session, decisions=decisions, object_id=object_id,
                expected_revision=1, edited_by="Source", text="Remoto",
            )
        with session_scope(receiver_engine) as session:
            update_editable_object(
                session, decisions=decisions, object_id=object_id,
                expected_revision=1, edited_by="Receiver", text="Local",
            )
        with session_scope(source_engine) as session:
            bundle = export_change_bundle(
                session, project_root=source_root, checkpoint_ref="baseline", created_by="Source"
            )
        with session_scope(receiver_engine) as session:
            dry_run_change_bundle(
                session, project_root=receiver_root, bundle_path=bundle.output_path,
                assessed_by="Receiver",
            )
            event_id = conflict_field_rows(session, bundle.bundle_id)[0].event_id
            bulk = resolve_conflict_fields_bulk(
                session,
                bundle_ref=bundle.bundle_id,
                event_id=event_id,
                choice="incoming",
                resolved_by="Receiver",
            )
            assert bulk.resolved_field_count == 1
            first = finalize_bundle_resolutions(
                session, bundle_ref=bundle.bundle_id, finalized_by="Receiver"
            )
            second = finalize_bundle_resolutions(
                session, bundle_ref=bundle.bundle_id, finalized_by="Receiver"
            )
            assert first.overall_status == "ready_to_apply_resolved"
            assert second.overall_status == "ready_to_apply_resolved"
            assert second.already_finalized is True
        with session_scope(receiver_engine) as session:
            summary = apply_change_bundle(
                session, project_root=receiver_root, bundle_ref=bundle.bundle_id,
                applied_by="Receiver",
            )
            assert summary.applied_event_count == 1
            assert summary.kept_local_event_count == 0
            assert session.get(EditableObject, object_id).current_text == "Remoto"
    finally:
        source_engine.dispose()
        receiver_engine.dispose()


def test_bulk_local_resolution_is_counted_separately(tmp_path: Path) -> None:
    from archive_workbench.exchange import (
        apply_change_bundle,
        dry_run_change_bundle,
        finalize_bundle_resolutions,
        resolve_conflict_fields_bulk,
    )

    (
        source_root,
        source_engine,
        decisions,
        object_id,
        receiver_root,
        receiver_engine,
        _receiver_workspace_id,
    ) = _source_and_receiver(tmp_path)
    try:
        with session_scope(source_engine) as session:
            update_editable_object(
                session, decisions=decisions, object_id=object_id,
                expected_revision=1, edited_by="Source", text="Remoto",
            )
        with session_scope(receiver_engine) as session:
            update_editable_object(
                session, decisions=decisions, object_id=object_id,
                expected_revision=1, edited_by="Receiver", text="Local",
            )
        with session_scope(source_engine) as session:
            bundle = export_change_bundle(
                session, project_root=source_root, checkpoint_ref="baseline", created_by="Source"
            )
        with session_scope(receiver_engine) as session:
            dry_run_change_bundle(
                session, project_root=receiver_root, bundle_path=bundle.output_path,
                assessed_by="Receiver",
            )
            bulk = resolve_conflict_fields_bulk(
                session,
                bundle_ref=bundle.bundle_id,
                choice="local",
                resolved_by="Receiver",
            )
            assert bulk.resolved_field_count == 1
            finalize_bundle_resolutions(
                session, bundle_ref=bundle.bundle_id, finalized_by="Receiver"
            )
        with session_scope(receiver_engine) as session:
            summary = apply_change_bundle(
                session, project_root=receiver_root, bundle_ref=bundle.bundle_id,
                applied_by="Receiver",
            )
            assert summary.applied_event_count == 0
            assert summary.duplicate_event_count == 0
            assert summary.kept_local_event_count == 1
            assert session.get(EditableObject, object_id).current_text == "Local"
    finally:
        source_engine.dispose()
        receiver_engine.dispose()


def test_resolution_usability_migration_upgrades_populated_0017_database(tmp_path: Path) -> None:
    root = tmp_path / "project"
    engine, _decisions, object_id = _seed_project(
        root, revision="0017_exchange_conflict_resolutions"
    )
    try:
        with session_scope(engine) as session:
            assert session.get(EditableObject, object_id) is not None
    finally:
        engine.dispose()
    assert current_revision(root) == "0017_exchange_conflict_resolutions"
    upgrade_database(root)
    assert current_revision(root) == "0043_form_structure_review"
    engine = create_sqlite_engine(database_path(root))
    try:
        columns = {
            row["name"] for row in inspect(engine).get_columns("exchange_bundle_applications")
        }
        with session_scope(engine) as session:
            assert session.get(EditableObject, object_id) is not None
    finally:
        engine.dispose()
    assert "kept_local_event_count" in columns


def test_catalog_units_and_digital_links_exchange_without_copying_local_file(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "source"
    receiver_root = tmp_path / "receiver"
    engine, decisions, _object_id = _seed_project(source_root)
    try:
        with session_scope(engine) as session:
            ensure_exchange_workspace(
                session, workspace_name="source", changed_by="Alex"
            )
            create_exchange_checkpoint(session, label="baseline", created_by="Alex")
    finally:
        engine.dispose()

    shutil.copytree(source_root, receiver_root)
    receiver_engine = create_sqlite_engine(database_path(receiver_root))
    try:
        with session_scope(receiver_engine) as session:
            fork_exchange_workspace(
                session,
                workspace_name="receiver",
                created_by="Alex",
            )
    finally:
        receiver_engine.dispose()

    _write_pdf(source_root / "corpus" / "nuevo_catalogo.pdf")
    source_engine = create_sqlite_engine(database_path(source_root))
    try:
        with session_scope(source_engine) as session:
            unit = create_archival_unit(
                session,
                decisions=decisions,
                project_id=decisions.project_id,
                parent_id=None,
                level_key="archivo",
                title="Archivo incorporado por intercambio",
                created_by="Alex",
            )
            result = register_local_file(
                session,
                project_root=source_root,
                project_id=decisions.project_id,
                archival_unit_id=unit.id,
                relative_path="corpus/nuevo_catalogo.pdf",
                registered_by="Alex",
            )
            unit_id = unit.id
            digital_id = result.digital_object_id
        with session_scope(source_engine) as session:
            bundle = export_change_bundle(
                session,
                project_root=source_root,
                checkpoint_ref="baseline",
                created_by="Alex",
            )
        assert bundle.event_count == 2
    finally:
        source_engine.dispose()

    receiver_engine = create_sqlite_engine(database_path(receiver_root))
    try:
        with session_scope(receiver_engine) as session:
            dry = dry_run_change_bundle(
                session,
                project_root=receiver_root,
                bundle_path=bundle.output_path,
                assessed_by="Alex",
            )
            assert dry.overall_status == "ready_to_apply"
            assert dry.counts["apply"] == 2
        with session_scope(receiver_engine) as session:
            applied = apply_change_bundle(
                session,
                project_root=receiver_root,
                bundle_ref=str(bundle.output_path),
                applied_by="Alex",
            )
            assert applied.applied_event_count == 2
        with session_scope(receiver_engine) as session:
            received_unit = session.get(ArchivalUnit, unit_id)
            links = session.scalars(
                select(DigitalObjectUnitLink).where(
                    DigitalObjectUnitLink.archival_unit_id == unit_id
                )
            ).all()
            files = session.scalars(
                select(FileInstance).where(FileInstance.digital_object_id == digital_id)
            ).all()
        assert received_unit is not None
        assert received_unit.title == "Archivo incorporado por intercambio"
        assert len(links) == 1
        assert files == []
    finally:
        receiver_engine.dispose()


def test_catalog_updates_and_moves_exchange_transactionally(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    receiver_root = tmp_path / "receiver"
    engine, decisions, _object_id = _seed_project(source_root)
    try:
        with session_scope(engine) as session:
            archivo = create_archival_unit(
                session,
                decisions=decisions,
                project_id=decisions.project_id,
                parent_id=None,
                level_key="archivo",
                title="Archivo",
                created_by="Alex",
            )
            fondo_a = create_archival_unit(
                session,
                decisions=decisions,
                project_id=decisions.project_id,
                parent_id=archivo.id,
                level_key="fondo",
                title="Fondo A",
                created_by="Alex",
            )
            fondo_b = create_archival_unit(
                session,
                decisions=decisions,
                project_id=decisions.project_id,
                parent_id=archivo.id,
                level_key="fondo",
                title="Fondo B",
                created_by="Alex",
            )
            serie = create_archival_unit(
                session,
                decisions=decisions,
                project_id=decisions.project_id,
                parent_id=fondo_a.id,
                level_key="serie",
                title="Serie original",
                created_by="Alex",
            )
            serie_id = serie.id
            fondo_b_id = fondo_b.id
            ensure_exchange_workspace(
                session, workspace_name="source", changed_by="Alex"
            )
            create_exchange_checkpoint(session, label="baseline", created_by="Alex")
    finally:
        engine.dispose()

    shutil.copytree(source_root, receiver_root)
    receiver_engine = create_sqlite_engine(database_path(receiver_root))
    try:
        with session_scope(receiver_engine) as session:
            fork_exchange_workspace(
                session, workspace_name="receiver", created_by="Alex"
            )
    finally:
        receiver_engine.dispose()

    from archive_workbench.catalog_management import move_archival_unit, update_archival_unit

    source_engine = create_sqlite_engine(database_path(source_root))
    try:
        with session_scope(source_engine) as session:
            update_archival_unit(
                session,
                decisions=decisions,
                unit_id=serie_id,
                changed_by="Alex",
                title="Serie corregida",
                reference_code="SER-1",
                registration_status="provisional",
                completion_confirmed=False,
                field_values={},
            )
            move_archival_unit(
                session,
                decisions=decisions,
                unit_id=serie_id,
                new_parent_id=fondo_b_id,
                changed_by="Alex",
            )
        with session_scope(source_engine) as session:
            bundle = export_change_bundle(
                session,
                project_root=source_root,
                checkpoint_ref="baseline",
                created_by="Alex",
            )
        assert bundle.event_count == 2
    finally:
        source_engine.dispose()

    receiver_engine = create_sqlite_engine(database_path(receiver_root))
    try:
        with session_scope(receiver_engine) as session:
            dry = dry_run_change_bundle(
                session,
                project_root=receiver_root,
                bundle_path=bundle.output_path,
                assessed_by="Alex",
            )
            assert dry.overall_status == "ready_to_apply"
        with session_scope(receiver_engine) as session:
            applied = apply_change_bundle(
                session,
                project_root=receiver_root,
                bundle_ref=str(bundle.output_path),
                applied_by="Alex",
            )
            assert applied.applied_event_count == 2
        with session_scope(receiver_engine) as session:
            received = session.get(ArchivalUnit, serie_id)
        assert received is not None
        assert received.title == "Serie corregida"
        assert received.reference_code == "SER-1"
        assert received.parent_id == fondo_b_id
        assert received.revision == 3
    finally:
        receiver_engine.dispose()


def test_authorities_aliases_and_mentions_travel_in_bundle(tmp_path: Path) -> None:
    from archive_workbench.authorities import (
        add_authority_alias,
        create_authority,
        create_mention,
        mention_rows,
    )
    from archive_workbench.db.models import AuthorityAlias, AuthorityRecord

    (
        source_root,
        source_engine,
        decisions,
        object_id,
        receiver_root,
        receiver_engine,
        _receiver_workspace_id,
    ) = _source_and_receiver(tmp_path)
    try:
        with session_scope(source_engine) as session:
            authority = create_authority(
                session,
                project_id=decisions.project_id,
                entity_type="organization",
                preferred_name="Dirección de Inteligencia",
                temporal_expression="años setenta",
                temporal_note="Período aproximado",
                created_by="Source",
            )
            authority_id = authority.id
            add_authority_alias(
                session,
                authority_id=authority.id,
                alias="DIPBA",
                alias_type="acronym",
                created_by="Source",
            )
            create_mention(
                session,
                object_id=object_id,
                mention_text="Texto OCR",
                authority_id=authority.id,
                created_by="Source",
            )
        with session_scope(source_engine) as session:
            bundle = export_change_bundle(
                session,
                project_root=source_root,
                checkpoint_ref="baseline",
                created_by="Source",
            )
            assert bundle.event_count == 3

        with session_scope(receiver_engine) as session:
            dry = dry_run_change_bundle(
                session,
                project_root=receiver_root,
                bundle_path=bundle.output_path,
                assessed_by="Receiver",
            )
            assert dry.overall_status == "ready_to_apply"
        with session_scope(receiver_engine) as session:
            applied = apply_change_bundle(
                session,
                project_root=receiver_root,
                bundle_ref=str(bundle.output_path),
                applied_by="Receiver",
            )
            assert applied.applied_event_count == 3
        with session_scope(receiver_engine) as session:
            authority = session.get(AuthorityRecord, authority_id)
            assert authority is not None
            assert authority.preferred_name == "Dirección de Inteligencia"
            assert authority.temporal_expression == "años setenta"
            assert authority.temporal_start.isoformat() == "1970-01-01"
            assert authority.temporal_end.isoformat() == "1979-12-31"
            assert authority.temporal_note == "Período aproximado"
            assert authority.revision == 2
            alias = session.scalar(
                select(AuthorityAlias).where(AuthorityAlias.authority_id == authority_id)
            )
            assert alias is not None and alias.alias == "DIPBA"
            mentions = mention_rows(session, authority_id=authority_id)
            assert len(mentions) == 1
            assert mentions[0].mention_text == "Texto OCR"
            assert mentions[0].status == "accepted"
    finally:
        source_engine.dispose()
        receiver_engine.dispose()


def test_missing_authority_repair_travels_as_a_mention_update(
    tmp_path: Path,
) -> None:
    from archive_workbench.authorities import (
        _append_mention_revision,
        create_authority,
        repair_missing_authority,
    )
    from archive_workbench.db.models import EntityMention

    source_root = tmp_path / "source_missing_authority"
    source_engine, decisions, object_id = _seed_project(source_root)
    try:
        with session_scope(source_engine) as session:
            target = create_authority(
                session,
                project_id=decisions.project_id,
                entity_type="organization",
                preferred_name="Entidad reparada",
                created_by="Source",
            )
            target_id = target.id
            editable = session.get(EditableObject, object_id)
            assert editable is not None
            mention = EntityMention(
                id=new_id(),
                editable_object_id=object_id,
                authority_id=None,
                mention_text="Texto OCR",
                normalized_text="texto ocr",
                start_offset=0,
                end_offset=9,
                object_revision_number=editable.revision_number,
                status="accepted",
                source="manual",
                confidence=None,
                note="Estado histórico sin entidad",
                created_by="Source",
                updated_by="Source",
                revision=1,
            )
            session.add(mention)
            session.flush()
            _append_mention_revision(
                session,
                mention,
                operation="create",
                changed_by="Source",
                note=mention.note,
            )
            mention_id = mention.id
            ensure_exchange_workspace(
                session,
                workspace_name="source-pc",
                changed_by="Source",
            )
            create_exchange_checkpoint(
                session,
                label="baseline",
                created_by="Source",
            )

        source_engine.dispose()
        receiver_root = tmp_path / "receiver_missing_authority"
        shutil.copytree(source_root, receiver_root)
        receiver_engine, _receiver_workspace_id = _reset_receiver_exchange_identity(
            receiver_root,
            "receiver-pc",
        )
        source_engine = create_sqlite_engine(database_path(source_root))

        with session_scope(source_engine) as session:
            repair_missing_authority(
                session,
                mention_id=mention_id,
                expected_revision=1,
                changed_by="Source",
                decision="link",
                authority_id=target_id,
                note="Entidad verificada antes del intercambio",
            )
        with session_scope(source_engine) as session:
            bundle = export_change_bundle(
                session,
                project_root=source_root,
                checkpoint_ref="baseline",
                created_by="Source",
            )
            assert bundle.event_count == 1

        with session_scope(receiver_engine) as session:
            dry = dry_run_change_bundle(
                session,
                project_root=receiver_root,
                bundle_path=bundle.output_path,
                assessed_by="Receiver",
            )
            assert dry.overall_status == "ready_to_apply"
        with session_scope(receiver_engine) as session:
            applied = apply_change_bundle(
                session,
                project_root=receiver_root,
                bundle_ref=str(bundle.output_path),
                applied_by="Receiver",
            )
            assert applied.applied_event_count == 1
        with session_scope(receiver_engine) as session:
            received = session.get(EntityMention, mention_id)
            assert received is not None
            assert received.authority_id == target_id
            assert received.status == "accepted"
            assert received.revision == 2
    finally:
        source_engine.dispose()
        if "receiver_engine" in locals():
            receiver_engine.dispose()


def test_explicit_entity_relations_travel_in_bundle(tmp_path: Path) -> None:
    from archive_workbench.authorities import create_authority
    from archive_workbench.db.models import EntityRelation
    from archive_workbench.relations import create_entity_relation

    (
        source_root,
        source_engine,
        decisions,
        _object_id,
        receiver_root,
        receiver_engine,
        _receiver_workspace_id,
    ) = _source_and_receiver(tmp_path)
    try:
        with session_scope(source_engine) as session:
            person = create_authority(
                session,
                project_id=decisions.project_id,
                entity_type="person",
                preferred_name="Juan Pérez",
                created_by="Source",
            )
            organization = create_authority(
                session,
                project_id=decisions.project_id,
                entity_type="organization",
                preferred_name="Partido Obrero",
                created_by="Source",
            )
            relation = create_entity_relation(
                session,
                project_id=decisions.project_id,
                source_authority_id=person.id,
                relation_label="integró",
                target_kind="entity",
                target_id=organization.id,
                evidence_note="Según el informe revisado.",
                temporal_expression="03/1974 - 03/1976",
                temporal_note="Vigencia documentada",
                created_by="Source",
            )
            relation_id = relation.id
        with session_scope(source_engine) as session:
            bundle = export_change_bundle(
                session,
                project_root=source_root,
                checkpoint_ref="baseline",
                created_by="Source",
            )
            assert bundle.event_count == 3
        with session_scope(receiver_engine) as session:
            dry = dry_run_change_bundle(
                session,
                project_root=receiver_root,
                bundle_path=bundle.output_path,
                assessed_by="Receiver",
            )
            assert dry.overall_status == "ready_to_apply"
        with session_scope(receiver_engine) as session:
            applied = apply_change_bundle(
                session,
                project_root=receiver_root,
                bundle_ref=str(bundle.output_path),
                applied_by="Receiver",
            )
            assert applied.applied_event_count == 3
        with session_scope(receiver_engine) as session:
            relation = session.get(EntityRelation, relation_id)
            assert relation is not None
            assert relation.relation_kind == "analytical"
            assert relation.relation_label == "integró"
            assert relation.evidence_note == "Según el informe revisado."
            assert relation.provenance_note is None
            assert relation.temporal_expression == "03/1974 - 03/1976"
            assert relation.temporal_start.isoformat() == "1974-03-01"
            assert relation.temporal_end.isoformat() == "1976-03-31"
            assert relation.temporal_note == "Vigencia documentada"
            assert relation.revision == 1
    finally:
        source_engine.dispose()
        receiver_engine.dispose()


def test_catalog_authority_role_travels_with_kind_provenance_and_period(
    tmp_path: Path,
) -> None:
    from archive_workbench.authorities import create_authority
    from archive_workbench.db.models import EntityRelation
    from archive_workbench.relations import create_entity_relation

    (
        source_root,
        source_engine,
        decisions,
        _object_id,
        receiver_root,
        receiver_engine,
        _receiver_workspace_id,
    ) = _source_and_receiver(tmp_path)
    try:
        with session_scope(source_engine) as session:
            unit = session.scalar(
                select(ArchivalUnit).order_by(ArchivalUnit.created_at, ArchivalUnit.id)
            )
            assert unit is not None
            producer = create_authority(
                session,
                project_id=decisions.project_id,
                entity_type="organization",
                preferred_name="Dirección de Inteligencia",
                created_by="Source",
            )
            relation = create_entity_relation(
                session,
                project_id=decisions.project_id,
                source_authority_id=producer.id,
                relation_kind="producer",
                relation_label="texto libre que no debe conservarse",
                target_kind="archival_unit",
                target_id=unit.id,
                evidence_note="Membrete del documento.",
                provenance_note="Descripción archivística controlada.",
                temporal_expression="1974 - 1976",
                temporal_note="Período documentado",
                created_by="Source",
            )
            relation_id = relation.id
            unit_id = unit.id

        with session_scope(source_engine) as session:
            bundle = export_change_bundle(
                session,
                project_root=source_root,
                checkpoint_ref="baseline",
                created_by="Source",
            )
            assert bundle.event_count == 2
        with session_scope(receiver_engine) as session:
            dry = dry_run_change_bundle(
                session,
                project_root=receiver_root,
                bundle_path=bundle.output_path,
                assessed_by="Receiver",
            )
            assert dry.overall_status == "ready_to_apply"
        with session_scope(receiver_engine) as session:
            applied = apply_change_bundle(
                session,
                project_root=receiver_root,
                bundle_ref=str(bundle.output_path),
                applied_by="Receiver",
            )
            assert applied.applied_event_count == 2
        with session_scope(receiver_engine) as session:
            relation = session.get(EntityRelation, relation_id)
            assert relation is not None
            assert relation.relation_kind == "producer"
            assert relation.relation_label == "produjo"
            assert relation.target_archival_unit_id == unit_id
            assert relation.evidence_note == "Membrete del documento."
            assert relation.provenance_note == "Descripción archivística controlada."
            assert relation.temporal_expression == "1974 - 1976"
            assert relation.temporal_start.isoformat() == "1974-01-01"
            assert relation.temporal_end.isoformat() == "1976-12-31"
            assert relation.temporal_note == "Período documentado"
            assert relation.revision == 1
    finally:
        source_engine.dispose()
        receiver_engine.dispose()


def test_catalog_link_removal_travels_without_deleting_file_or_digital_object(
    tmp_path: Path,
) -> None:
    from archive_workbench.catalog_management import unlink_digital_object_from_unit

    source_root = tmp_path / "source"
    source_engine, _decisions, _object_id = _seed_project(source_root)
    try:
        with session_scope(source_engine) as session:
            link = session.scalar(select(DigitalObjectUnitLink))
            assert link is not None
            link_id = link.id
            digital_id = link.digital_object_id
            ensure_exchange_workspace(session, workspace_name="source", changed_by="Alex")
            create_exchange_checkpoint(session, label="baseline", created_by="Alex")
    finally:
        source_engine.dispose()

    receiver_root = tmp_path / "receiver"
    shutil.copytree(source_root, receiver_root)
    receiver_engine = create_sqlite_engine(database_path(receiver_root))
    try:
        with session_scope(receiver_engine) as session:
            fork_exchange_workspace(session, workspace_name="receiver", created_by="Alex")
    finally:
        receiver_engine.dispose()

    source_engine = create_sqlite_engine(database_path(source_root))
    try:
        with session_scope(source_engine) as session:
            unlink_digital_object_from_unit(session, link_id=link_id, removed_by="Alex")
        with session_scope(source_engine) as session:
            bundle = export_change_bundle(
                session,
                project_root=source_root,
                checkpoint_ref="baseline",
                created_by="Alex",
            )
            assert bundle.event_count == 1
    finally:
        source_engine.dispose()

    receiver_engine = create_sqlite_engine(database_path(receiver_root))
    try:
        with session_scope(receiver_engine) as session:
            dry = dry_run_change_bundle(
                session,
                project_root=receiver_root,
                bundle_path=bundle.output_path,
                assessed_by="Alex",
            )
            assert dry.overall_status == "ready_to_apply"
            assert dry.counts["apply"] == 1
        with session_scope(receiver_engine) as session:
            applied = apply_change_bundle(
                session,
                project_root=receiver_root,
                bundle_ref=str(bundle.output_path),
                applied_by="Alex",
            )
            assert applied.applied_event_count == 1
        with session_scope(receiver_engine) as session:
            assert session.get(DigitalObjectUnitLink, link_id) is None
            assert session.get(DigitalObject, digital_id) is not None
            assert session.scalar(
                select(FileInstance).where(FileInstance.digital_object_id == digital_id)
            ) is not None
    finally:
        receiver_engine.dispose()


def test_work_assignments_exchange_with_history_and_cross_review_fields(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    source_engine, decisions, _object_id = _seed_project(source_root)
    try:
        with session_scope(source_engine) as session:
            ensure_exchange_workspace(session, workspace_name="source", changed_by="Alex")
            create_exchange_checkpoint(session, label="baseline", created_by="Alex")
    finally:
        source_engine.dispose()

    receiver_root = tmp_path / "receiver"
    shutil.copytree(source_root, receiver_root)
    receiver_engine = create_sqlite_engine(database_path(receiver_root))
    try:
        with session_scope(receiver_engine) as session:
            fork_exchange_workspace(session, workspace_name="receiver", created_by="María")
    finally:
        receiver_engine.dispose()

    source_engine = create_sqlite_engine(database_path(source_root))
    try:
        with session_scope(source_engine) as session:
            assignment = create_work_assignment(
                session,
                project_id=decisions.project_id,
                source_type="test_corpus",
                source_key="doc_exchange",
                assignment_kind="primary_review",
                assignee="Alex",
                created_by="Alex",
                page_start=1,
                page_end=1,
                priority="high",
            )
            update_work_assignment(
                session,
                assignment_id=assignment.id,
                expected_revision=1,
                changed_by="Alex",
                status="submitted",
            )
            assignment_id = assignment.id
            cross = create_cross_review_assignment(
                session,
                primary_assignment_id=assignment.id,
                assignee="María",
                created_by="Alex",
            )
            cross_id = cross.id
        with session_scope(source_engine) as session:
            bundle = export_change_bundle(
                session,
                project_root=source_root,
                checkpoint_ref="baseline",
                created_by="Alex",
            )
            assert bundle.event_count == 3
    finally:
        source_engine.dispose()

    receiver_engine = create_sqlite_engine(database_path(receiver_root))
    try:
        with session_scope(receiver_engine) as session:
            dry = dry_run_change_bundle(
                session,
                project_root=receiver_root,
                bundle_path=bundle.output_path,
                assessed_by="María",
            )
            assert dry.overall_status == "ready_to_apply"
            assert dry.counts["apply"] == 3
        with session_scope(receiver_engine) as session:
            applied = apply_change_bundle(
                session,
                project_root=receiver_root,
                bundle_ref=str(bundle.output_path),
                applied_by="María",
            )
            assert applied.applied_event_count == 3
        with session_scope(receiver_engine) as session:
            received = session.get(WorkAssignment, assignment_id)
            assert received is not None
            assert received.assignee == "Alex"
            assert received.status == "submitted"
            assert received.priority == "high"
            assert received.revision == 2
            received_cross = session.get(WorkAssignment, cross_id)
            assert received_cross is not None
            assert received_cross.parent_assignment_id == assignment_id
            assert received_cross.assignment_kind == "cross_review"
            assert received_cross.assignee == "María"
    finally:
        receiver_engine.dispose()


def test_incoming_object_create_materializes_missing_editable_page_from_selection(
    tmp_path: Path,
) -> None:
    from archive_workbench.contracts.changes import ChangeEvent
    from archive_workbench.db.models import EditablePage
    from archive_workbench.exchange import (
        _apply_incoming_event,
        _assess_current_state,
        _parent_reference_problem,
    )

    root = tmp_path / "project"
    engine, _decisions, object_id = _seed_project(root)
    try:
        with session_scope(engine) as session:
            workspace = ensure_exchange_workspace(
                session, workspace_name="receiver", changed_by="Receiver"
            )
            obj = session.get(EditableObject, object_id)
            assert obj is not None
            page_id = obj.editable_page_id
            event = ChangeEvent(
                event_id=new_id(),
                project_id=workspace.project_id,
                workspace_id="source-workspace",
                sequence_number=1,
                transaction_id=new_id(),
                entity_type="editable_object",
                entity_id=obj.id,
                operation="create",
                base_revision=None,
                new_revision=1,
                changed_fields={
                    "editable_page_id": [None, obj.editable_page_id],
                    "digital_object_id": [None, obj.digital_object_id],
                    "page_number": [None, obj.page_number],
                    "source_extracted_object_id": [None, obj.source_extracted_object_id],
                    "source_origin_id": [None, obj.source_origin_id],
                    "text": [None, obj.current_text],
                    "object_type": [None, obj.current_object_type],
                    "order_index": [None, obj.current_order_index],
                    "geometry": [None, obj.current_geometry_json or []],
                    "attributes": [None, obj.current_attributes_json or {}],
                    "lifecycle_status": [None, obj.lifecycle_status],
                    "review_status": [None, obj.review_status],
                    "document_part_id": [None, obj.document_part_id],
                },
                actor="Source",
            )
            page = session.get(EditablePage, page_id)
            assert page is not None
            session.delete(obj)
            session.flush()
            session.delete(page)
            session.flush()
            assert session.get(EditablePage, page_id) is None
            assert session.get(EditableObject, object_id) is None

            assert _parent_reference_problem(session, event, set()) is None
            disposition, _reason, _fields = _assess_current_state(session, event, set())
            assert disposition == "apply"

            _apply_incoming_event(
                session,
                event=event,
                applied_by="Receiver",
                source_workspace_name="source",
            )
            restored_page = session.get(EditablePage, page_id)
            restored_object = session.get(EditableObject, object_id)
            assert restored_page is not None
            assert restored_object is not None
            assert restored_page.source_selection_id is not None
            assert restored_object.editable_page_id == page_id
    finally:
        engine.dispose()


def test_incoming_chain_accepts_schema_enrichment_equivalent_datetimes_and_empty_update() -> None:
    from archive_workbench.contracts.changes import ChangeEvent
    from archive_workbench.exchange import (
        _advance_incoming_state,
        _assess_prior_incoming_state,
    )

    authority_id = new_id()
    common = {
        "project_id": new_id(),
        "workspace_id": new_id(),
        "transaction_id": new_id(),
        "entity_type": "authority_record",
        "entity_id": authority_id,
        "actor": "Source",
    }
    create = ChangeEvent(
        **common,
        event_id=new_id(),
        sequence_number=1,
        operation="create",
        new_revision=1,
        changed_fields={
            "preferred_name": [None, "SIDE"],
            "aliases": [None, []],
        },
    )
    incoming_state: dict[tuple[str, str], dict[str, object]] = {}
    _advance_incoming_state(create, "apply", incoming_state)

    enrich = ChangeEvent(
        **common,
        event_id=new_id(),
        sequence_number=2,
        operation="update",
        base_revision=1,
        new_revision=2,
        changed_fields={
            "temporal_approximate": [None, 0],
            "aliases": [
                [],
                [
                    {
                        "id": "alias-1",
                        "alias": "SIDE",
                        "created_at": "2026-07-27T18:29:42.094666+00:00",
                    }
                ],
            ],
        },
    )
    result = _assess_prior_incoming_state(enrich, incoming_state)
    assert result is not None and result[0] == "apply"
    _advance_incoming_state(enrich, "apply", incoming_state)

    equivalent_datetime = ChangeEvent(
        **common,
        event_id=new_id(),
        sequence_number=3,
        operation="update",
        base_revision=2,
        new_revision=3,
        changed_fields={
            "aliases": [
                [
                    {
                        "id": "alias-1",
                        "alias": "SIDE",
                        "created_at": "2026-07-27T18:29:42.094666",
                    }
                ],
                [],
            ]
        },
    )
    result = _assess_prior_incoming_state(equivalent_datetime, incoming_state)
    assert result is not None and result[0] == "apply"
    _advance_incoming_state(equivalent_datetime, "apply", incoming_state)

    empty = ChangeEvent(
        **common,
        event_id=new_id(),
        sequence_number=4,
        operation="update",
        base_revision=3,
        new_revision=4,
        changed_fields={},
    )
    result = _assess_prior_incoming_state(empty, incoming_state)
    assert result is not None
    assert result[0] == "duplicate"
    assert "cambios efectivos" in result[1]


def _add_shared_candidate(session, *, digital: DigitalObject) -> tuple[str, str, str]:
    run = ExtractionRun(
        id=new_id(),
        digital_object_id=digital.id,
        profile_key="candidate_profile",
        engine="tesseract_tsv",
        engine_version="5",
        source_sha256=digital.sha256,
        options_json={"candidate": True},
        options_hash="b" * 64,
        status="completed",
        is_current=True,
        created_by="tests",
        total_pages=1,
        total_objects=1,
        total_paragraphs=1,
        total_characters=15,
        warnings_json=[],
    )
    session.add(run)
    session.flush()
    page = ExtractionPage(
        id=new_id(),
        extraction_run_id=run.id,
        page_number=1,
        object_count=1,
        character_count=15,
        status="completed",
    )
    session.add(page)
    source = ExtractedObject(
        id=new_id(),
        origin_id=new_id(),
        extraction_run_id=run.id,
        digital_object_id=digital.id,
        page_number=1,
        order_index=0,
        object_type="paragraph",
        original_text="Texto candidato",
        geometry_json=[],
        attributes_json={},
    )
    session.add(source)
    session.flush()
    return run.id, page.id, source.id


def _candidate_source_and_receiver(tmp_path: Path):
    source_root = tmp_path / "source"
    source_engine, decisions, object_id = _seed_project(source_root)
    with session_scope(source_engine) as session:
        digital = session.scalar(select(DigitalObject))
        assert digital is not None
        candidate_run_id, candidate_page_id, candidate_object_id = _add_shared_candidate(
            session, digital=digital
        )
        ensure_exchange_workspace(
            session, workspace_name="source-pc", changed_by="Source"
        )
        create_exchange_checkpoint(session, label="baseline", created_by="Source")
    source_engine.dispose()
    receiver_root = tmp_path / "receiver"
    shutil.copytree(source_root, receiver_root)
    receiver_engine, receiver_workspace_id = _reset_receiver_exchange_identity(
        receiver_root, "receiver-pc"
    )
    source_engine = create_sqlite_engine(database_path(source_root))
    return (
        source_root, source_engine, decisions, object_id, receiver_root, receiver_engine,
        receiver_workspace_id, candidate_run_id, candidate_page_id, candidate_object_id,
    )


def test_bundle_transports_candidate_adoption_when_ocr_dependencies_exist(
    tmp_path: Path,
) -> None:
    from archive_workbench.db.models import EditablePage, EditablePageRevision

    (
        source_root, source_engine, decisions, _object_id, receiver_root, receiver_engine,
        _receiver_workspace_id, candidate_run_id, candidate_page_id, candidate_object_id,
    ) = _candidate_source_and_receiver(tmp_path)
    try:
        with session_scope(source_engine) as session:
            result = adopt_candidate_page(
                session,
                decisions=decisions,
                source_key="doc_exchange",
                page=1,
                candidate_run_id=candidate_run_id,
                adopted_by="Source",
                note="Candidata compartida",
            )
            assert result.objects_activated == 1
        with session_scope(source_engine) as session:
            bundle = export_change_bundle(
                session,
                project_root=source_root,
                checkpoint_ref="baseline",
                created_by="Source",
            )
            assert bundle.event_count >= 4

        with session_scope(receiver_engine) as session:
            dry = dry_run_change_bundle(
                session,
                project_root=receiver_root,
                bundle_path=bundle.output_path,
                assessed_by="Receiver",
            )
            assert dry.overall_status == "ready_to_apply"
            assert dry.counts["review"] == 0
            assert dry.counts["conflict"] == 0
        with session_scope(receiver_engine) as session:
            applied = apply_change_bundle(
                session,
                project_root=receiver_root,
                bundle_ref=bundle.bundle_id,
                applied_by="Receiver",
            )
            assert applied.applied_event_count == bundle.event_count
        with session_scope(receiver_engine) as session:
            selection = session.scalar(select(ExtractionPageSelection))
            page = session.scalar(select(EditablePage))
            active = session.scalars(
                select(EditableObject).where(EditableObject.lifecycle_status == "active")
            ).all()
            assert selection is not None and page is not None
            assert selection.extraction_run_id == candidate_run_id
            assert selection.extraction_page_id == candidate_page_id
            assert page.source_extraction_run_id == candidate_run_id
            assert page.source_extraction_page_id == candidate_page_id
            assert len(active) == 1
            assert active[0].source_extracted_object_id == candidate_object_id
            assert active[0].current_text == "Texto candidato"
            adopted_revision = session.scalar(
                select(EditablePageRevision).where(
                    EditablePageRevision.operation == "candidate_adopted"
                )
            )
            assert adopted_revision is not None
            assert adopted_revision.note == "Candidata compartida"
            assert adopted_revision.details_json["objects_activated"] == 1
            assert adopted_revision.details_json["objects_retired"] == 1
            assert adopted_revision.details_json["previous_extraction_run_id"] != candidate_run_id
            assert adopted_revision.details_json["previous_extraction_page_id"] != candidate_page_id
    finally:
        source_engine.dispose()
        receiver_engine.dispose()


def test_bundle_transports_manual_keep_edits_when_ocr_dependencies_exist(
    tmp_path: Path,
) -> None:
    from archive_workbench.db.models import EditablePage, EditablePageRevision

    (
        source_root, source_engine, decisions, object_id, receiver_root, receiver_engine,
        _receiver_workspace_id, candidate_run_id, candidate_page_id, _candidate_object_id,
    ) = _candidate_source_and_receiver(tmp_path)
    try:
        with session_scope(source_engine) as session:
            obj = session.get(EditableObject, object_id)
            assert obj is not None
            update_editable_object(
                session,
                decisions=decisions,
                object_id=obj.id,
                expected_revision=obj.revision_number,
                edited_by="Source",
                text="Corrección humana preservada",
            )
            resolve_candidate_keep_edits(
                session,
                source_key="doc_exchange",
                page=1,
                candidate_run_id=candidate_run_id,
                resolved_by="Source",
                note="Conservar corrección humana",
            )
        with session_scope(source_engine) as session:
            bundle = export_change_bundle(
                session,
                project_root=source_root,
                checkpoint_ref="baseline",
                created_by="Source",
            )
        with session_scope(receiver_engine) as session:
            dry = dry_run_change_bundle(
                session,
                project_root=receiver_root,
                bundle_path=bundle.output_path,
                assessed_by="Receiver",
            )
            assert dry.overall_status == "ready_to_apply"
        with session_scope(receiver_engine) as session:
            apply_change_bundle(
                session,
                project_root=receiver_root,
                bundle_ref=bundle.bundle_id,
                applied_by="Receiver",
            )
        with session_scope(receiver_engine) as session:
            selection = session.scalar(select(ExtractionPageSelection))
            page = session.scalar(select(EditablePage))
            obj = session.get(EditableObject, object_id)
            assert selection is not None and page is not None and obj is not None
            assert selection.extraction_run_id == candidate_run_id
            assert page.source_extraction_run_id == candidate_run_id
            assert page.source_extraction_page_id == candidate_page_id
            assert obj.current_text == "Corrección humana preservada"
            assert obj.lifecycle_status == "active"
            kept_revision = session.scalar(
                select(EditablePageRevision).where(
                    EditablePageRevision.operation == "manual_keep_edits"
                )
            )
            assert kept_revision is not None
            assert kept_revision.note == "Conservar corrección humana"
            assert kept_revision.details_json["strategy"] == "keep_existing_editable_objects"
            assert object_id in kept_revision.details_json["retained_editable_object_ids"]
            assert kept_revision.details_json["candidate_object_ids_not_imported"]
    finally:
        source_engine.dispose()
        receiver_engine.dispose()


def test_bundle_applies_sequential_candidate_decisions_from_one_checkpoint(
    tmp_path: Path,
) -> None:
    from archive_workbench.db.models import EditablePage, EditablePageRevision

    (
        source_root, source_engine, decisions, _object_id, receiver_root, receiver_engine,
        _receiver_workspace_id, candidate_run_id, _candidate_page_id, candidate_object_id,
    ) = _candidate_source_and_receiver(tmp_path)
    try:
        with session_scope(source_engine) as session:
            original_selection = session.scalar(select(ExtractionPageSelection))
            assert original_selection is not None
            original_run_id = original_selection.extraction_run_id
            original_page_id = original_selection.extraction_page_id

            adopt_candidate_page(
                session,
                decisions=decisions,
                source_key="doc_exchange",
                page=1,
                candidate_run_id=candidate_run_id,
                adopted_by="Source",
                note="Primera adopción",
            )
            active = session.scalar(
                select(EditableObject).where(
                    EditableObject.lifecycle_status == "active",
                    EditableObject.source_extracted_object_id == candidate_object_id,
                )
            )
            assert active is not None
            update_editable_object(
                session,
                decisions=decisions,
                object_id=active.id,
                expected_revision=active.revision_number,
                edited_by="Source",
                text="Corrección sobre la candidata",
            )
            _run, changed = select_extraction_pages(
                session,
                source_key="doc_exchange",
                run_id=original_run_id,
                pages={1},
                selected_by="Source",
                note="Volver a la selección anterior",
            )
            assert changed == 1
            resolve_candidate_keep_edits(
                session,
                source_key="doc_exchange",
                page=1,
                candidate_run_id=original_run_id,
                resolved_by="Source",
                note="Conservar la edición al volver a la selección anterior",
            )

        with session_scope(source_engine) as session:
            bundle = export_change_bundle(
                session,
                project_root=source_root,
                checkpoint_ref="baseline",
                created_by="Source",
            )
        with session_scope(receiver_engine) as session:
            dry = dry_run_change_bundle(
                session,
                project_root=receiver_root,
                bundle_path=bundle.output_path,
                assessed_by="Receiver",
            )
            assert dry.overall_status == "ready_to_apply"
            assert dry.counts["review"] == 0
            assert dry.counts["conflict"] == 0
        with session_scope(receiver_engine) as session:
            apply_change_bundle(
                session,
                project_root=receiver_root,
                bundle_ref=bundle.bundle_id,
                applied_by="Receiver",
            )
        with session_scope(receiver_engine) as session:
            selection = session.scalar(select(ExtractionPageSelection))
            page = session.scalar(select(EditablePage))
            active = session.scalar(
                select(EditableObject).where(
                    EditableObject.lifecycle_status == "active",
                    EditableObject.source_extracted_object_id == candidate_object_id,
                )
            )
            assert selection is not None and page is not None and active is not None
            assert selection.extraction_run_id == original_run_id
            assert selection.extraction_page_id == original_page_id
            assert page.source_extraction_run_id == original_run_id
            assert page.source_extraction_page_id == original_page_id
            assert active.current_text == "Corrección sobre la candidata"
            revisions = session.scalars(
                select(EditablePageRevision).where(
                    EditablePageRevision.operation.in_(
                        ["candidate_adopted", "manual_keep_edits"]
                    )
                )
            ).all()
            assert [row.operation for row in revisions] == [
                "candidate_adopted",
                "manual_keep_edits",
            ]
            assert revisions[-1].note == (
                "Conservar la edición al volver a la selección anterior"
            )
    finally:
        source_engine.dispose()
        receiver_engine.dispose()


def test_bundle_requires_shared_ocr_dependencies_for_candidate_decisions(
    tmp_path: Path,
) -> None:
    (
        source_root, source_engine, decisions, _object_id, receiver_root, receiver_engine,
        _receiver_workspace_id, candidate_run_id, _candidate_page_id, _candidate_object_id,
    ) = _candidate_source_and_receiver(tmp_path)
    try:
        with session_scope(source_engine) as session:
            adopt_candidate_page(
                session, decisions=decisions, source_key="doc_exchange", page=1,
                candidate_run_id=candidate_run_id, adopted_by="Source",
            )
        with session_scope(source_engine) as session:
            bundle = export_change_bundle(
                session, project_root=source_root, checkpoint_ref="baseline",
                created_by="Source",
            )
        with session_scope(receiver_engine) as session:
            candidate_objects = session.scalars(
                select(ExtractedObject).where(
                    ExtractedObject.extraction_run_id == candidate_run_id
                )
            ).all()
            for row in candidate_objects:
                session.delete(row)
            candidate_pages = session.scalars(
                select(ExtractionPage).where(ExtractionPage.extraction_run_id == candidate_run_id)
            ).all()
            for row in candidate_pages:
                session.delete(row)
            candidate_run = session.get(ExtractionRun, candidate_run_id)
            assert candidate_run is not None
            session.delete(candidate_run)
        with session_scope(receiver_engine) as session:
            dry = dry_run_change_bundle(
                session, project_root=receiver_root, bundle_path=bundle.output_path,
                assessed_by="Receiver",
            )
            assert dry.overall_status == "needs_review"
            assert dry.counts["review"] >= 1
    finally:
        source_engine.dispose()
        receiver_engine.dispose()


def test_bundle_exports_post_checkpoint_ocr_bootstrap_events_with_shared_dependency(
    tmp_path: Path,
) -> None:
    root = tmp_path / "project"
    engine, _decisions, object_id = _seed_project(root)
    try:
        with session_scope(engine) as session:
            workspace = ensure_exchange_workspace(
                session, workspace_name="alex-pc", changed_by="Alex"
            )
            checkpoint = create_exchange_checkpoint(
                session, label="after_shared_baseline", created_by="Alex"
            )
            obj = session.get(EditableObject, object_id)
            assert obj is not None
            session.add(
                ExchangeChangeEvent(
                    id=new_id(),
                    workspace_id=workspace.id,
                    project_id=workspace.project_id,
                    sequence_number=checkpoint.sequence_number + 1,
                    transaction_id=new_id(),
                    entity_type="editable_object",
                    entity_id=new_id(),
                    operation="create",
                    base_revision=None,
                    new_revision=1,
                    changed_fields_json={
                        "editable_page_id": [None, obj.editable_page_id],
                        "digital_object_id": [None, obj.digital_object_id],
                        "page_number": [None, obj.page_number],
                        "source_extracted_object_id": [None, obj.source_extracted_object_id],
                        "text": [None, "OCR posterior"],
                    },
                    actor="Alex",
                    occurred_at=datetime.now(timezone.utc),
                )
            )
        with session_scope(engine) as session:
            bundle = export_change_bundle(
                session,
                project_root=root,
                checkpoint_ref="after_shared_baseline",
                created_by="Alex",
            )
            assert bundle.event_count == 1
            assert bundle.output_path.is_file()
            assert session.scalar(
                select(ExchangeCheckpoint).where(ExchangeCheckpoint.label.like("bundle_%"))
            ) is not None
    finally:
        engine.dispose()


def test_exchange_fork_copy_recreates_required_project_directories(tmp_path: Path) -> None:
    root = tmp_path / "project"
    engine, _decisions, _object_id = _seed_project(root)
    engine.dispose()
    shutil.rmtree(root / "exchange", ignore_errors=True)

    result = CliRunner().invoke(
        app,
        [
            "exchange-fork-copy",
            str(root),
            "--workspace-name",
            "receiver-copy",
            "--created-by",
            "tests",
            "--confirm-copy",
        ],
    )

    assert result.exit_code == 0, result.output
    assert (root / "exchange/incoming").is_dir()
    assert (root / "exchange/outgoing").is_dir()



def test_source_replaced_trigger_is_canonical_without_base_revision(
    tmp_path: Path,
) -> None:
    """Retirar un objeto solo publica active → deleted, incluso sin base histórica."""
    (
        source_root, source_engine, decisions, object_id, _receiver_root, receiver_engine,
        _receiver_workspace_id, candidate_run_id, _candidate_page_id, _candidate_object_id,
    ) = _candidate_source_and_receiver(tmp_path)
    try:
        receiver_engine.dispose()
        with session_scope(source_engine) as session:
            revisions = session.scalars(
                select(EditableObjectRevision).where(
                    EditableObjectRevision.editable_object_id == object_id
                )
            ).all()
            for revision in revisions:
                session.delete(revision)
        with session_scope(source_engine) as session:
            adopt_candidate_page(
                session,
                decisions=decisions,
                source_key="doc_exchange",
                page=1,
                candidate_run_id=candidate_run_id,
                adopted_by="Source",
                note="Adopción sin revisión base",
            )
        with session_scope(source_engine) as session:
            obj = session.get(EditableObject, object_id)
            assert obj is not None and obj.lifecycle_status == "deleted"
            event = session.scalar(
                select(ExchangeChangeEvent).where(
                    ExchangeChangeEvent.entity_type == "editable_object",
                    ExchangeChangeEvent.entity_id == object_id,
                    ExchangeChangeEvent.new_revision == 2,
                )
            )
            assert event is not None
            assert event.operation == "update"
            assert event.changed_fields_json == {
                "lifecycle_status": ["active", "deleted"]
            }
    finally:
        source_engine.dispose()


def test_0030_repairs_legacy_source_replaced_bundle_end_to_end(
    tmp_path: Path,
) -> None:
    """Un evento defectuoso de 0029 se reexporta y aplica sin conflictos falsos."""
    source_root = tmp_path / "source"
    source_engine, decisions, object_id = _seed_project(
        source_root, revision="0029_extraction_candidate_history"
    )
    with session_scope(source_engine) as session:
        digital = session.scalar(select(DigitalObject))
        assert digital is not None
        candidate_run_id, candidate_page_id, candidate_object_id = _add_shared_candidate(
            session, digital=digital
        )
        revisions = session.scalars(
            select(EditableObjectRevision).where(
                EditableObjectRevision.editable_object_id == object_id
            )
        ).all()
        for revision in revisions:
            session.delete(revision)
        ensure_exchange_workspace(
            session, workspace_name="source-pc", changed_by="Source"
        )
        create_exchange_checkpoint(session, label="baseline", created_by="Source")
    source_engine.dispose()

    receiver_root = tmp_path / "receiver"
    shutil.copytree(source_root, receiver_root)
    receiver_engine, _receiver_workspace_id = _reset_receiver_exchange_identity(
        receiver_root, "receiver-pc"
    )
    receiver_engine.dispose()
    source_engine = create_sqlite_engine(database_path(source_root))

    # La acción se realiza todavía con el trigger defectuoso de 0029.
    with session_scope(source_engine) as session:
        adopt_candidate_page(
            session,
            decisions=decisions,
            source_key="doc_exchange",
            page=1,
            candidate_run_id=candidate_run_id,
            adopted_by="Source",
            note="Adopción registrada en 0029",
        )
    with session_scope(source_engine) as session:
        malformed = session.scalar(
            select(ExchangeChangeEvent).where(
                ExchangeChangeEvent.entity_type == "editable_object",
                ExchangeChangeEvent.entity_id == object_id,
                ExchangeChangeEvent.new_revision == 2,
            )
        )
        assert malformed is not None
        assert malformed.changed_fields_json["text"][0] is None
        assert malformed.changed_fields_json["lifecycle_status"] == [None, "deleted"]
    source_engine.dispose()

    # Ambas copias reciben 0030. La migración completa la revisión base sin
    # generar nuevos eventos y la exportación corrige el evento ya existente.
    upgrade_database(source_root)
    upgrade_database(receiver_root)
    assert current_revision(source_root) == "0043_form_structure_review"
    assert current_revision(receiver_root) == "0043_form_structure_review"
    source_engine = create_sqlite_engine(database_path(source_root))
    receiver_engine = create_sqlite_engine(database_path(receiver_root))
    try:
        for engine in (source_engine, receiver_engine):
            with session_scope(engine) as session:
                baseline = session.get(
                    EditableObjectRevision,
                    session.scalar(
                        select(EditableObjectRevision.id).where(
                            EditableObjectRevision.editable_object_id == object_id,
                            EditableObjectRevision.revision_number == 1,
                        )
                    ),
                )
                assert baseline is not None
                assert baseline.operation == "import"
                assert baseline.lifecycle_status == "active"

        with session_scope(source_engine) as session:
            bundle = export_change_bundle(
                session,
                project_root=source_root,
                checkpoint_ref="baseline",
                created_by="Source",
            )
        inspection = inspect_change_bundle(bundle.output_path)
        assert inspection.event_count >= 4
        with zipfile.ZipFile(bundle.output_path) as archive:
            events = [
                json.loads(line)
                for line in archive.read("changes.jsonl").decode("utf-8").splitlines()
                if line.strip()
            ]
        retired = next(
            event for event in events
            if event["entity_type"] == "editable_object"
            and event["entity_id"] == object_id
            and event["new_revision"] == 2
        )
        assert retired["changed_fields"]["lifecycle_status"] == [
            "active",
            "deleted",
        ]
        assert retired["changed_fields"]["revision_operation"] == [
            None,
            "source_replaced",
        ]

        with session_scope(receiver_engine) as session:
            dry = dry_run_change_bundle(
                session,
                project_root=receiver_root,
                bundle_path=bundle.output_path,
                assessed_by="Receiver",
            )
            assert dry.overall_status == "ready_to_apply"
            assert dry.counts["conflict"] == 0
            assert dry.counts["review"] == 0
            assert dry.counts["apply"] == bundle.event_count
        with session_scope(receiver_engine) as session:
            applied = apply_change_bundle(
                session,
                project_root=receiver_root,
                bundle_ref=bundle.bundle_id,
                applied_by="Receiver",
            )
            assert applied.applied_event_count == bundle.event_count
        with session_scope(receiver_engine) as session:
            old_object = session.get(EditableObject, object_id)
            new_object = session.scalar(
                select(EditableObject).where(
                    EditableObject.source_extracted_object_id == candidate_object_id
                )
            )
            selection = session.scalar(select(ExtractionPageSelection))
            assert old_object is not None and old_object.lifecycle_status == "deleted"
            assert new_object is not None and new_object.lifecycle_status == "active"
            assert selection is not None
            assert selection.extraction_run_id == candidate_run_id
            assert selection.extraction_page_id == candidate_page_id
    finally:
        source_engine.dispose()
        receiver_engine.dispose()



def test_form_structure_travels_in_bundle_with_page_revision_history(
    tmp_path: Path,
) -> None:
    (
        source_root,
        source_engine,
        _decisions,
        object_id,
        receiver_root,
        receiver_engine,
        _receiver_workspace_id,
    ) = _source_and_receiver(tmp_path)
    try:
        with session_scope(source_engine) as session:
            obj = session.get(EditableObject, object_id)
            assert obj is not None

            def action():
                group_id = ensure_group(
                    session,
                    editable_page_id=obj.editable_page_id,
                    label="Datos personales",
                    changed_by="Source",
                )
                return register_control(
                    session,
                    editable_page_id=obj.editable_page_id,
                    state="marked",
                    label="Afiliado",
                    changed_by="Source",
                    label_object_id=obj.id,
                    group_id=group_id,
                    source="manual",
                    evidence_note="Visible en el formulario",
                )

            execute_page_action(
                session,
                editable_page_id=obj.editable_page_id,
                action_type="form_structure",
                changed_by="Source",
                selected_object_id=obj.id,
                note="Confirmación de formulario",
                action=action,
            )
            page_id = obj.editable_page_id

        with session_scope(source_engine) as session:
            bundle = export_change_bundle(
                session,
                project_root=source_root,
                checkpoint_ref="baseline",
                created_by="Source",
            )
        with session_scope(receiver_engine) as session:
            dry = dry_run_change_bundle(
                session,
                project_root=receiver_root,
                bundle_path=bundle.output_path,
                assessed_by="Receiver",
            )
            assert dry.overall_status == "ready_to_apply"
            assert dry.counts["conflict"] == 0
        with session_scope(receiver_engine) as session:
            applied = apply_change_bundle(
                session,
                project_root=receiver_root,
                bundle_ref=bundle.bundle_id,
                applied_by="Receiver",
            )
            assert applied.applied_event_count >= 1

        with session_scope(source_engine) as source_session, session_scope(
            receiver_engine
        ) as receiver_session:
            source_structure = form_structure(
                source_session, editable_page_id=page_id
            ).model_dump(mode="json")
            receiver_structure = form_structure(
                receiver_session, editable_page_id=page_id
            ).model_dump(mode="json")
            assert receiver_structure == source_structure
            source_page = source_session.get(EditablePage, page_id)
            receiver_page = receiver_session.get(EditablePage, page_id)
            assert source_page is not None and receiver_page is not None
            assert receiver_page.revision_number == source_page.revision_number == 3
            assert source_structure["groups"][0]["label"] == "Datos personales"
            assert source_structure["controls"][0]["state"] == "marked"
            receiver_operations = receiver_session.scalars(
                select(EditablePageRevision.operation)
                .where(EditablePageRevision.editable_page_id == page_id)
                .order_by(EditablePageRevision.revision_number)
            ).all()
            source_operations = source_session.scalars(
                select(EditablePageRevision.operation)
                .where(EditablePageRevision.editable_page_id == page_id)
                .order_by(EditablePageRevision.revision_number)
            ).all()
            assert receiver_operations == source_operations == [
                "bootstrap",
                "form_structure",
                "form_structure",
            ]
            source_action = source_session.scalar(
                select(EditablePageAction).where(
                    EditablePageAction.editable_page_id == page_id,
                    EditablePageAction.action_type == "form_structure",
                )
            )
            receiver_action = receiver_session.get(
                EditablePageAction, source_action.id if source_action else ""
            )
            assert source_action is not None and receiver_action is not None
            assert receiver_action.before_snapshot_json == source_action.before_snapshot_json
            assert receiver_action.after_snapshot_json == source_action.after_snapshot_json
    finally:
        source_engine.dispose()
        receiver_engine.dispose()

def test_bundle_preserves_object_revision_operations_and_page_undo_redo_history(
    tmp_path: Path,
) -> None:
    (
        source_root,
        source_engine,
        decisions,
        object_id,
        receiver_root,
        receiver_engine,
        _receiver_workspace_id,
    ) = _source_and_receiver(tmp_path)
    try:
        with session_scope(source_engine) as session:
            obj = session.get(EditableObject, object_id)
            assert obj is not None
            execute_page_action(
                session,
                editable_page_id=obj.editable_page_id,
                action_type="edit",
                changed_by="Source",
                selected_object_id=obj.id,
                note="Corrección transportable",
                action=lambda: update_editable_object(
                    session,
                    decisions=decisions,
                    object_id=obj.id,
                    expected_revision=obj.revision_number,
                    edited_by="Source",
                    text="Texto corregido",
                ),
            )
            undo_page_action(
                session, editable_page_id=obj.editable_page_id, changed_by="Source"
            )
            redo_page_action(
                session, editable_page_id=obj.editable_page_id, changed_by="Source"
            )

        with session_scope(source_engine) as session:
            bundle = export_change_bundle(
                session,
                project_root=source_root,
                checkpoint_ref="baseline",
                created_by="Source",
            )
        with session_scope(receiver_engine) as session:
            dry = dry_run_change_bundle(
                session,
                project_root=receiver_root,
                bundle_path=bundle.output_path,
                assessed_by="Receiver",
            )
            assert dry.overall_status == "ready_to_apply"
            assert dry.counts["conflict"] == 0
        with session_scope(receiver_engine) as session:
            apply_change_bundle(
                session,
                project_root=receiver_root,
                bundle_ref=bundle.bundle_id,
                applied_by="Receiver",
            )

        with session_scope(source_engine) as source_session, session_scope(
            receiver_engine
        ) as receiver_session:
            source_operations = source_session.scalars(
                select(EditableObjectRevision.operation)
                .where(EditableObjectRevision.editable_object_id == object_id)
                .order_by(EditableObjectRevision.revision_number)
            ).all()
            receiver_operations = receiver_session.scalars(
                select(EditableObjectRevision.operation)
                .where(EditableObjectRevision.editable_object_id == object_id)
                .order_by(EditableObjectRevision.revision_number)
            ).all()
            assert receiver_operations == source_operations == [
                "import",
                "edit",
                "undo",
                "redo",
            ]
            source_action = source_session.scalar(select(EditablePageAction))
            receiver_action = receiver_session.get(
                EditablePageAction, source_action.id if source_action else ""
            )
            assert source_action is not None and receiver_action is not None
            assert receiver_action.action_type == source_action.action_type == "edit"
            assert receiver_action.status == source_action.status == "active"
            assert receiver_action.before_snapshot_json == source_action.before_snapshot_json
            assert receiver_action.after_snapshot_json == source_action.after_snapshot_json
            assert receiver_action.undone_at == source_action.undone_at
            assert receiver_action.redone_at == source_action.redone_at
    finally:
        source_engine.dispose()
        receiver_engine.dispose()


def test_0031_backfills_legacy_page_action_and_preserves_history_end_to_end(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "source"
    source_engine, decisions, object_id = _seed_project(
        source_root, revision="0030_source_replaced_exchange"
    )
    with session_scope(source_engine) as session:
        obj = session.get(EditableObject, object_id)
        assert obj is not None
        execute_page_action(
            session,
            editable_page_id=obj.editable_page_id,
            action_type="edit",
            changed_by="Source",
            selected_object_id=obj.id,
            note="Acción común anterior",
            action=lambda: update_editable_object(
                session,
                decisions=decisions,
                object_id=obj.id,
                expected_revision=obj.revision_number,
                edited_by="Source",
                text="Texto común",
            ),
        )
        ensure_exchange_workspace(
            session, workspace_name="source-pc", changed_by="Source"
        )
        create_exchange_checkpoint(
            session, label="baseline_actions", created_by="Source"
        )
    source_engine.dispose()

    receiver_root = tmp_path / "receiver"
    shutil.copytree(source_root, receiver_root)
    receiver_engine, _receiver_workspace_id = _reset_receiver_exchange_identity(
        receiver_root, "receiver-pc"
    )
    receiver_engine.dispose()

    source_engine = create_sqlite_engine(database_path(source_root))
    with session_scope(source_engine) as session:
        obj = session.get(EditableObject, object_id)
        assert obj is not None
        execute_page_action(
            session,
            editable_page_id=obj.editable_page_id,
            action_type="edit",
            changed_by="Source",
            selected_object_id=obj.id,
            note="Acción posterior transportada",
            action=lambda: update_editable_object(
                session,
                decisions=decisions,
                object_id=obj.id,
                expected_revision=obj.revision_number,
                edited_by="Source",
                text="Texto final",
            ),
        )
        undo_page_action(
            session, editable_page_id=obj.editable_page_id, changed_by="Source"
        )
        redo_page_action(
            session, editable_page_id=obj.editable_page_id, changed_by="Source"
        )
    source_engine.dispose()

    upgrade_database(source_root)
    upgrade_database(receiver_root)
    assert current_revision(source_root) == "0043_form_structure_review"
    assert current_revision(receiver_root) == "0043_form_structure_review"

    source_engine = create_sqlite_engine(database_path(source_root))
    receiver_engine = create_sqlite_engine(database_path(receiver_root))
    try:
        with session_scope(source_engine) as session:
            bundle = export_change_bundle(
                session,
                project_root=source_root,
                checkpoint_ref="baseline_actions",
                created_by="Source",
            )
        with session_scope(receiver_engine) as session:
            dry = dry_run_change_bundle(
                session,
                project_root=receiver_root,
                bundle_path=bundle.output_path,
                assessed_by="Receiver",
            )
            assert dry.overall_status == "ready_to_apply"
            assert dry.counts["conflict"] == 0
            assert dry.counts["review"] == 0
            assert dry.counts["duplicate"] == 1
            assert dry.counts["apply"] == 4
        with session_scope(receiver_engine) as session:
            applied = apply_change_bundle(
                session,
                project_root=receiver_root,
                bundle_ref=bundle.bundle_id,
                applied_by="Receiver",
            )
            assert applied.applied_event_count == 4
            assert applied.duplicate_event_count == 1

        with session_scope(source_engine) as source_session, session_scope(
            receiver_engine
        ) as receiver_session:
            source_operations = source_session.scalars(
                select(EditableObjectRevision.operation)
                .where(EditableObjectRevision.editable_object_id == object_id)
                .order_by(EditableObjectRevision.revision_number)
            ).all()
            receiver_operations = receiver_session.scalars(
                select(EditableObjectRevision.operation)
                .where(EditableObjectRevision.editable_object_id == object_id)
                .order_by(EditableObjectRevision.revision_number)
            ).all()
            assert receiver_operations == source_operations == [
                "import",
                "edit",
                "edit",
                "undo",
                "redo",
            ]
            source_actions = source_session.scalars(
                select(EditablePageAction).order_by(EditablePageAction.sequence_number)
            ).all()
            receiver_actions = receiver_session.scalars(
                select(EditablePageAction).order_by(EditablePageAction.sequence_number)
            ).all()
            assert len(source_actions) == len(receiver_actions) == 2
            assert [row.id for row in receiver_actions] == [row.id for row in source_actions]
            assert receiver_actions[1].status == source_actions[1].status == "active"
            assert receiver_actions[1].undone_at == source_actions[1].undone_at
            assert receiver_actions[1].redone_at == source_actions[1].redone_at
    finally:
        source_engine.dispose()
        receiver_engine.dispose()


def test_incoming_bundle_diagnostics_and_lifecycle_management(tmp_path: Path) -> None:
    from archive_workbench.exchange import (
        incoming_bundle_diagnostics,
        incoming_bundle_rows,
        purge_incoming_bundle,
        set_incoming_bundle_archived,
    )

    (
        source_root,
        source_engine,
        decisions,
        object_id,
        receiver_root,
        receiver_engine,
        _receiver_workspace_id,
    ) = _source_and_receiver(tmp_path)
    try:
        with session_scope(source_engine) as session:
            update_editable_object(
                session,
                decisions=decisions,
                object_id=object_id,
                expected_revision=1,
                edited_by="Source",
                text="Cambio remoto pendiente",
            )
        with session_scope(source_engine) as session:
            bundle = export_change_bundle(
                session,
                project_root=source_root,
                checkpoint_ref="baseline",
                created_by="Source",
            )
        with session_scope(receiver_engine) as session:
            dry_run_change_bundle(
                session,
                project_root=receiver_root,
                bundle_path=bundle.output_path,
                assessed_by="Receiver",
            )
        with session_scope(receiver_engine) as session:
            local = session.get(EditableObject, object_id)
            assert local is not None
            update_editable_object(
                session,
                decisions=decisions,
                object_id=object_id,
                expected_revision=local.revision_number,
                edited_by="Receiver",
                text="Cambio local posterior al dry-run",
            )
        with session_scope(receiver_engine) as session:
            rows = incoming_bundle_rows(session)
            assert rows[0].status == "stale"
            diagnostics = incoming_bundle_diagnostics(
                session,
                bundle_ref=bundle.bundle_id,
            )
            assert diagnostics.state_changed is True
            assert diagnostics.sequence_changed is True
            assert diagnostics.local_events_after_assessment
            assert diagnostics.local_events_after_assessment[-1].actor == "Receiver"
            assert diagnostics.local_events_after_assessment[-1].entity_id == object_id

            set_incoming_bundle_archived(
                session,
                bundle_ref=bundle.bundle_id,
                archived=True,
                changed_by="Receiver",
                note="Obsoleto de prueba",
            )
            assert incoming_bundle_rows(session) == []
            archived = incoming_bundle_rows(session, include_archived=True)
            assert archived[0].lifecycle_status == "archived"
            assert archived[0].archive_note == "Obsoleto de prueba"

            set_incoming_bundle_archived(
                session,
                bundle_ref=bundle.bundle_id,
                archived=False,
                changed_by="Receiver",
            )
            assert incoming_bundle_rows(session)[0].lifecycle_status == "active"
            set_incoming_bundle_archived(
                session,
                bundle_ref=bundle.bundle_id,
                archived=True,
                changed_by="Receiver",
            )
            plan = purge_incoming_bundle(session, bundle_ref=bundle.bundle_id)
            assert plan.bundle_id == bundle.bundle_id
            assert any(value.endswith(".zip") for value in plan.relative_paths)
            assert incoming_bundle_rows(session, include_archived=True) == []
    finally:
        source_engine.dispose()
        receiver_engine.dispose()


def test_unmatched_bundle_with_multiple_creations_exposes_all_review_fields(
    tmp_path: Path,
) -> None:
    from archive_workbench.authorities import create_authority
    from archive_workbench.exchange import conflict_field_rows

    (
        source_root,
        source_engine,
        decisions,
        _object_id,
        receiver_root,
        receiver_engine,
        _receiver_workspace_id,
    ) = _source_and_receiver(tmp_path)
    try:
        with session_scope(source_engine) as session:
            for index in range(3):
                create_authority(
                    session,
                    project_id=decisions.project_id,
                    entity_type="organization",
                    preferred_name=f"Entidad remota {index + 1}",
                    review_status="approved",
                    created_by="Source",
                )
        with session_scope(source_engine) as session:
            bundle = export_change_bundle(
                session,
                project_root=source_root,
                checkpoint_ref="baseline",
                created_by="Source",
            )
            assert bundle.event_count == 3
        with session_scope(receiver_engine) as session:
            session.query(ExchangeCheckpoint).delete()
        with session_scope(receiver_engine) as session:
            summary = dry_run_change_bundle(
                session,
                project_root=receiver_root,
                bundle_path=bundle.output_path,
                assessed_by="Receiver",
            )
            assert summary.base_match_status == "unmatched"
            assert summary.counts == {
                "apply": 0,
                "duplicate": 0,
                "review": 3,
                "conflict": 0,
            }
            fields = conflict_field_rows(session, bundle.bundle_id)
            assert len({row.event_id for row in fields}) == 3
            assert len(fields) == 21
            assert {row.operation for row in fields} == {"create"}
    finally:
        source_engine.dispose()
        receiver_engine.dispose()


def _table_counts(engine) -> dict[str, int]:
    with engine.connect() as connection:
        names = inspect(engine).get_table_names()
        return {
            name: int(connection.execute(text(f'SELECT COUNT(*) FROM "{name}"')).scalar_one())
            for name in names
            if not name.startswith("sqlite_")
        }


def _rewrite_bundle_manifest(
    source: Path,
    destination: Path,
    *,
    updates: dict[str, object],
) -> Path:
    with zipfile.ZipFile(source, "r") as archive:
        entries = {name: archive.read(name) for name in archive.namelist()}
    manifest = json.loads(entries["manifest.json"].decode("utf-8"))
    manifest.update(updates)
    manifest_bytes = (
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")
    entries["manifest.json"] = manifest_bytes
    entries["checksums.sha256"] = (
        f"{__import__('hashlib').sha256(manifest_bytes).hexdigest()}  manifest.json\n"
        f"{__import__('hashlib').sha256(entries['changes.jsonl']).hexdigest()}  changes.jsonl\n"
    ).encode("utf-8")
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, payload in entries.items():
            archive.writestr(name, payload)
    return destination


def test_lineage_diagnostic_is_read_only_and_insufficient_without_evidence(
    tmp_path: Path,
) -> None:
    from archive_workbench.lineage_diagnostics import diagnose_unmatched_bundle_lineage

    (
        source_root,
        source_engine,
        decisions,
        object_id,
        receiver_root,
        receiver_engine,
        _receiver_workspace_id,
    ) = _source_and_receiver(tmp_path)
    try:
        with session_scope(source_engine) as session:
            update_editable_object(
                session,
                decisions=decisions,
                object_id=object_id,
                expected_revision=1,
                edited_by="Source",
                text="Cambio remoto",
            )
        with session_scope(source_engine) as session:
            bundle = export_change_bundle(
                session,
                project_root=source_root,
                checkpoint_ref="baseline",
                created_by="Source",
            )
        with session_scope(receiver_engine) as session:
            session.query(ExchangeCheckpoint).delete()
        with session_scope(receiver_engine) as session:
            dry = dry_run_change_bundle(
                session,
                project_root=receiver_root,
                bundle_path=bundle.output_path,
                assessed_by="Receiver",
            )
            assert dry.base_match_status == "unmatched"

        before = _table_counts(receiver_engine)
        with session_scope(receiver_engine) as session:
            report = diagnose_unmatched_bundle_lineage(
                session,
                project_root=receiver_root,
                bundle_ref=bundle.bundle_id,
            )
            assert not session.new
            assert not session.dirty
            assert not session.deleted
        after = _table_counts(receiver_engine)

        assert before == after
        assert report.classification == "insufficient"
        assert report.recovery_candidates == []
        assert report.findings[0].code == "target_bundle_verified"
    finally:
        source_engine.dispose()
        receiver_engine.dispose()


def test_lineage_diagnostic_detects_exact_local_checkpoint(tmp_path: Path) -> None:
    from archive_workbench.lineage_diagnostics import diagnose_unmatched_bundle_lineage

    (
        source_root,
        source_engine,
        decisions,
        object_id,
        receiver_root,
        receiver_engine,
        _receiver_workspace_id,
    ) = _source_and_receiver(tmp_path)
    try:
        with session_scope(source_engine) as session:
            update_editable_object(
                session,
                decisions=decisions,
                object_id=object_id,
                expected_revision=1,
                edited_by="Source",
                text="Cambio remoto",
            )
        with session_scope(source_engine) as session:
            bundle = export_change_bundle(
                session,
                project_root=source_root,
                checkpoint_ref="baseline",
                created_by="Source",
            )
        with session_scope(receiver_engine) as session:
            session.query(ExchangeCheckpoint).delete()
        with session_scope(receiver_engine) as session:
            dry_run_change_bundle(
                session,
                project_root=receiver_root,
                bundle_path=bundle.output_path,
                assessed_by="Receiver",
            )
        with session_scope(receiver_engine) as session:
            checkpoint = create_exchange_checkpoint(
                session,
                label="evidencia-recuperada",
                created_by="Receiver",
            )
        with session_scope(receiver_engine) as session:
            report = diagnose_unmatched_bundle_lineage(
                session,
                project_root=receiver_root,
                bundle_ref=bundle.bundle_id,
            )
        assert report.classification == "recoverable"
        assert len(report.recovery_candidates) == 1
        assert report.recovery_candidates[0].method == "local_exact_checkpoint"
        assert report.recovery_candidates[0].local_checkpoint_id == checkpoint.id
        assert any(row.code == "local_exact_checkpoint" for row in report.findings)
    finally:
        source_engine.dispose()
        receiver_engine.dispose()


def test_lineage_diagnostic_connects_verified_bundle_chain(tmp_path: Path) -> None:
    from archive_workbench.lineage_diagnostics import diagnose_unmatched_bundle_lineage

    (
        source_root,
        source_engine,
        decisions,
        object_id,
        receiver_root,
        receiver_engine,
        _receiver_workspace_id,
    ) = _source_and_receiver(tmp_path)
    try:
        with session_scope(source_engine) as session:
            update_editable_object(
                session,
                decisions=decisions,
                object_id=object_id,
                expected_revision=1,
                edited_by="Source",
                text="Cambio remoto 1",
            )
        with session_scope(source_engine) as session:
            first = export_change_bundle(
                session,
                project_root=source_root,
                checkpoint_ref="baseline",
                created_by="Source",
            )
        with session_scope(source_engine) as session:
            update_editable_object(
                session,
                decisions=decisions,
                object_id=object_id,
                expected_revision=2,
                edited_by="Source",
                text="Cambio remoto 2",
            )
        with session_scope(source_engine) as session:
            second = export_change_bundle(
                session,
                project_root=source_root,
                checkpoint_ref=first.next_checkpoint_label,
                created_by="Source",
            )
        with session_scope(receiver_engine) as session:
            dry = dry_run_change_bundle(
                session,
                project_root=receiver_root,
                bundle_path=second.output_path,
                assessed_by="Receiver",
            )
            assert dry.base_match_status == "unmatched"
        with session_scope(receiver_engine) as session:
            report = diagnose_unmatched_bundle_lineage(
                session,
                project_root=receiver_root,
                bundle_ref=second.bundle_id,
                evidence_paths=[first.output_path],
            )
        assert report.classification == "recoverable"
        assert len(report.recovery_candidates) == 1
        candidate = report.recovery_candidates[0]
        assert candidate.method == "verified_bundle_chain"
        assert candidate.chain_bundle_ids == [first.bundle_id]
    finally:
        source_engine.dispose()
        receiver_engine.dispose()


def test_lineage_diagnostic_marks_bifurcated_bundle_chain_ambiguous(
    tmp_path: Path,
) -> None:
    from archive_workbench.lineage_diagnostics import diagnose_unmatched_bundle_lineage

    (
        source_root,
        source_engine,
        decisions,
        object_id,
        receiver_root,
        receiver_engine,
        _receiver_workspace_id,
    ) = _source_and_receiver(tmp_path)
    try:
        with session_scope(source_engine) as session:
            update_editable_object(
                session,
                decisions=decisions,
                object_id=object_id,
                expected_revision=1,
                edited_by="Source",
                text="Cambio remoto 1",
            )
        with session_scope(source_engine) as session:
            first = export_change_bundle(
                session,
                project_root=source_root,
                checkpoint_ref="baseline",
                created_by="Source",
            )
        with session_scope(source_engine) as session:
            update_editable_object(
                session,
                decisions=decisions,
                object_id=object_id,
                expected_revision=2,
                edited_by="Source",
                text="Cambio remoto 2",
            )
        with session_scope(source_engine) as session:
            second = export_change_bundle(
                session,
                project_root=source_root,
                checkpoint_ref=first.next_checkpoint_label,
                created_by="Source",
            )
        compact = first.bundle_id.replace("-", "")
        colliding_id = compact[:8] + "f" * 24
        alternate = _rewrite_bundle_manifest(
            first.output_path,
            tmp_path / "alternate.zip",
            updates={"bundle_id": colliding_id},
        )
        with session_scope(receiver_engine) as session:
            dry_run_change_bundle(
                session,
                project_root=receiver_root,
                bundle_path=second.output_path,
                assessed_by="Receiver",
            )
        with session_scope(receiver_engine) as session:
            report = diagnose_unmatched_bundle_lineage(
                session,
                project_root=receiver_root,
                bundle_ref=second.bundle_id,
                evidence_paths=[first.output_path, alternate],
            )
        assert report.classification == "ambiguous"
        assert report.contradiction_count >= 1
        assert len(report.recovery_candidates) == 2
        assert any(row.code == "bundle_chain_bifurcation" for row in report.findings)
    finally:
        source_engine.dispose()
        receiver_engine.dispose()


def test_lineage_diagnostic_reads_same_copy_backup_without_restoring_it(
    tmp_path: Path,
) -> None:
    from archive_workbench.lineage_diagnostics import diagnose_unmatched_bundle_lineage
    from archive_workbench.project_admin import create_project_backup

    (
        source_root,
        source_engine,
        decisions,
        object_id,
        receiver_root,
        receiver_engine,
        _receiver_workspace_id,
    ) = _source_and_receiver(tmp_path)
    try:
        backup = create_project_backup(
            project_root=receiver_root,
            created_by="Receiver",
            note="Evidencia EX-01A",
        )
        with session_scope(source_engine) as session:
            update_editable_object(
                session,
                decisions=decisions,
                object_id=object_id,
                expected_revision=1,
                edited_by="Source",
                text="Cambio remoto",
            )
        with session_scope(source_engine) as session:
            bundle = export_change_bundle(
                session,
                project_root=source_root,
                checkpoint_ref="baseline",
                created_by="Source",
            )
        with session_scope(receiver_engine) as session:
            session.query(ExchangeCheckpoint).delete()
        with session_scope(receiver_engine) as session:
            dry_run_change_bundle(
                session,
                project_root=receiver_root,
                bundle_path=bundle.output_path,
                assessed_by="Receiver",
            )
        before_db = database_path(receiver_root).read_bytes()
        with session_scope(receiver_engine) as session:
            report = diagnose_unmatched_bundle_lineage(
                session,
                project_root=receiver_root,
                bundle_ref=bundle.bundle_id,
                evidence_paths=[backup.path],
            )
        assert database_path(receiver_root).read_bytes() == before_db
        assert report.classification == "recoverable"
        assert report.recovery_candidates[0].method == "backup_exact_checkpoint"
        assert any(row.code == "backup_exact_checkpoint" for row in report.findings)
    finally:
        source_engine.dispose()
        receiver_engine.dispose()


def test_lineage_diagnostic_rejects_tampered_backup_and_isolated_manifest(
    tmp_path: Path,
) -> None:
    from archive_workbench.lineage_diagnostics import diagnose_unmatched_bundle_lineage
    from archive_workbench.project_admin import create_project_backup

    (
        source_root,
        source_engine,
        decisions,
        object_id,
        receiver_root,
        receiver_engine,
        _receiver_workspace_id,
    ) = _source_and_receiver(tmp_path)
    try:
        backup = create_project_backup(
            project_root=receiver_root,
            created_by="Receiver",
        )
        with session_scope(source_engine) as session:
            update_editable_object(
                session,
                decisions=decisions,
                object_id=object_id,
                expected_revision=1,
                edited_by="Source",
                text="Cambio remoto",
            )
        with session_scope(source_engine) as session:
            bundle = export_change_bundle(
                session,
                project_root=source_root,
                checkpoint_ref="baseline",
                created_by="Source",
            )
        with session_scope(receiver_engine) as session:
            session.query(ExchangeCheckpoint).delete()
        with session_scope(receiver_engine) as session:
            dry_run_change_bundle(
                session,
                project_root=receiver_root,
                bundle_path=bundle.output_path,
                assessed_by="Receiver",
            )

        tampered = tmp_path / "tampered_backup.zip"
        with zipfile.ZipFile(backup.path, "r") as archive:
            entries = {name: archive.read(name) for name in archive.namelist()}
        entries["database.sqlite3"] += b"alterado"
        with zipfile.ZipFile(tampered, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, payload in entries.items():
                archive.writestr(name, payload)

        manifest_path = tmp_path / "manifest.json"
        with zipfile.ZipFile(bundle.output_path, "r") as archive:
            manifest_path.write_bytes(archive.read("manifest.json"))
        with session_scope(receiver_engine) as session:
            report = diagnose_unmatched_bundle_lineage(
                session,
                project_root=receiver_root,
                bundle_ref=bundle.bundle_id,
                evidence_paths=[tampered, manifest_path],
            )
        assert report.classification == "insufficient"
        assert any(row.code == "unrecognized_artifact" for row in report.findings)
        assert any(row.code == "isolated_manifest" for row in report.findings)
    finally:
        source_engine.dispose()
        receiver_engine.dispose()


def test_exchange_lineage_diagnose_cli_reports_read_only_result(tmp_path: Path) -> None:
    (
        source_root,
        source_engine,
        decisions,
        object_id,
        receiver_root,
        receiver_engine,
        _receiver_workspace_id,
    ) = _source_and_receiver(tmp_path)
    try:
        with session_scope(source_engine) as session:
            update_editable_object(
                session,
                decisions=decisions,
                object_id=object_id,
                expected_revision=1,
                edited_by="Source",
                text="Cambio remoto",
            )
        with session_scope(source_engine) as session:
            bundle = export_change_bundle(
                session,
                project_root=source_root,
                checkpoint_ref="baseline",
                created_by="Source",
            )
        with session_scope(receiver_engine) as session:
            session.query(ExchangeCheckpoint).delete()
        with session_scope(receiver_engine) as session:
            dry_run_change_bundle(
                session,
                project_root=receiver_root,
                bundle_path=bundle.output_path,
                assessed_by="Receiver",
            )
        result = CliRunner().invoke(
            app,
            ["exchange-lineage-diagnose", str(receiver_root), bundle.bundle_id],
        )
        assert result.exit_code == 0, result.output
        assert "insuficiente" in result.output
        assert "No se escribió ningún dato" in result.output
    finally:
        source_engine.dispose()
        receiver_engine.dispose()


def test_lineage_diagnostic_detects_previous_application(tmp_path: Path) -> None:
    from archive_workbench.db.models import ExchangeBundleApplication, ExchangeBundleRecord
    from archive_workbench.lineage_diagnostics import diagnose_unmatched_bundle_lineage

    (
        source_root,
        source_engine,
        decisions,
        object_id,
        receiver_root,
        receiver_engine,
        _receiver_workspace_id,
    ) = _source_and_receiver(tmp_path)
    try:
        with session_scope(source_engine) as session:
            update_editable_object(
                session,
                decisions=decisions,
                object_id=object_id,
                expected_revision=1,
                edited_by="Source",
                text="Cambio remoto 1",
            )
        with session_scope(source_engine) as session:
            first = export_change_bundle(
                session,
                project_root=source_root,
                checkpoint_ref="baseline",
                created_by="Source",
            )
        with session_scope(receiver_engine) as session:
            dry_run_change_bundle(
                session,
                project_root=receiver_root,
                bundle_path=first.output_path,
                assessed_by="Receiver",
            )
        with session_scope(receiver_engine) as session:
            apply_change_bundle(
                session,
                project_root=receiver_root,
                bundle_ref=first.bundle_id,
                applied_by="Receiver",
            )
        with session_scope(source_engine) as session:
            update_editable_object(
                session,
                decisions=decisions,
                object_id=object_id,
                expected_revision=2,
                edited_by="Source",
                text="Cambio remoto 2",
            )
        with session_scope(source_engine) as session:
            second = export_change_bundle(
                session,
                project_root=source_root,
                checkpoint_ref=first.next_checkpoint_label,
                created_by="Source",
            )

        with session_scope(receiver_engine) as session:
            application = session.scalar(
                select(ExchangeBundleApplication).where(
                    ExchangeBundleApplication.bundle_id == first.bundle_id
                )
            )
            assert application and application.checkpoint_id
            checkpoint = session.get(ExchangeCheckpoint, application.checkpoint_id)
            record = session.get(ExchangeBundleRecord, application.bundle_record_id)
            assert checkpoint and record
            application.status = "temporarily_hidden"
            checkpoint.state_sha256 = "0" * 64
        with session_scope(receiver_engine) as session:
            dry = dry_run_change_bundle(
                session,
                project_root=receiver_root,
                bundle_path=second.output_path,
                assessed_by="Receiver",
            )
            assert dry.base_match_status == "unmatched"
        with session_scope(receiver_engine) as session:
            application = session.scalar(
                select(ExchangeBundleApplication).where(
                    ExchangeBundleApplication.bundle_id == first.bundle_id
                )
            )
            assert application
            application.status = "applied"
        with session_scope(receiver_engine) as session:
            report = diagnose_unmatched_bundle_lineage(
                session,
                project_root=receiver_root,
                bundle_ref=second.bundle_id,
            )
        assert report.classification == "recoverable"
        assert len(report.recovery_candidates) == 1
        assert report.recovery_candidates[0].method == "local_applied_bundle"
        assert any(row.code == "local_applied_bundle" for row in report.findings)
    finally:
        source_engine.dispose()
        receiver_engine.dispose()


def test_lineage_diagnostic_rejects_backup_from_different_project(tmp_path: Path) -> None:
    from archive_workbench.lineage_diagnostics import diagnose_unmatched_bundle_lineage
    from archive_workbench.project_admin import create_project_backup

    (
        source_root,
        source_engine,
        decisions,
        object_id,
        receiver_root,
        receiver_engine,
        _receiver_workspace_id,
    ) = _source_and_receiver(tmp_path)
    try:
        backup = create_project_backup(
            project_root=receiver_root,
            created_by="Receiver",
        )
        foreign_backup = tmp_path / "foreign_project_backup.zip"
        with zipfile.ZipFile(backup.path, "r") as archive:
            entries = {name: archive.read(name) for name in archive.namelist()}
        manifest = json.loads(entries["manifest.json"].decode("utf-8"))
        manifest["project_id"] = "otro-proyecto"
        entries["manifest.json"] = (
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8")
        with zipfile.ZipFile(
            foreign_backup, "w", compression=zipfile.ZIP_DEFLATED
        ) as archive:
            for name, payload in entries.items():
                archive.writestr(name, payload)

        with session_scope(source_engine) as session:
            update_editable_object(
                session,
                decisions=decisions,
                object_id=object_id,
                expected_revision=1,
                edited_by="Source",
                text="Cambio remoto",
            )
        with session_scope(source_engine) as session:
            bundle = export_change_bundle(
                session,
                project_root=source_root,
                checkpoint_ref="baseline",
                created_by="Source",
            )
        with session_scope(receiver_engine) as session:
            session.query(ExchangeCheckpoint).delete()
        with session_scope(receiver_engine) as session:
            dry_run_change_bundle(
                session,
                project_root=receiver_root,
                bundle_path=bundle.output_path,
                assessed_by="Receiver",
            )
        with session_scope(receiver_engine) as session:
            report = diagnose_unmatched_bundle_lineage(
                session,
                project_root=receiver_root,
                bundle_ref=bundle.bundle_id,
                evidence_paths=[foreign_backup],
            )
        assert report.classification == "insufficient"
        assert any(
            row.code == "different_project" and row.artifact_type == "project_backup"
            for row in report.findings
        )
    finally:
        source_engine.dispose()
        receiver_engine.dispose()


def test_lineage_validation_script_creates_recoverable_discardable_pair(
    tmp_path: Path,
) -> None:
    import importlib.util

    from archive_workbench.lineage_diagnostics import diagnose_unmatched_bundle_lineage

    base = tmp_path / "base"
    base_engine, _decisions, _object_id = _seed_project(base)
    base_engine.dispose()
    (base / "config").mkdir(parents=True, exist_ok=True)
    shutil.copy2(
        Path(__file__).parents[1] / "config" / "decisions.yaml",
        base / "config" / "decisions.yaml",
    )

    script_path = (
        Path(__file__).parents[1]
        / "scripts"
        / "create_lineage_diagnostic_validation_projects.py"
    )
    spec = importlib.util.spec_from_file_location("lineage_validation_script", script_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    source = tmp_path / "validation_source"
    receiver = tmp_path / "validation_receiver"
    result = module.create_validation_projects(
        base,
        source,
        receiver,
        force=False,
    )
    assert result["revision"] == "0043_form_structure_review"

    engine = create_sqlite_engine(database_path(receiver))
    try:
        with session_scope(engine) as session:
            insufficient = diagnose_unmatched_bundle_lineage(
                session,
                project_root=receiver,
                bundle_ref=str(result["target_bundle_id"]),
            )
        with session_scope(engine) as session:
            recoverable = diagnose_unmatched_bundle_lineage(
                session,
                project_root=receiver,
                bundle_ref=str(result["target_bundle_id"]),
                evidence_paths=[Path(result["evidence_bundle_path"])],
            )
        assert insufficient.classification == "insufficient"
        assert recoverable.classification == "recoverable"
        assert recoverable.recovery_candidates[0].method == "verified_bundle_chain"

        counts = _table_counts(engine)
        assert counts["exchange_checkpoints"] == 1
        assert counts["exchange_bundle_applications"] == 0
        assert counts["exchange_bundle_records"] == 1
        assert counts["exchange_dry_runs"] == 1

        cli_result = CliRunner().invoke(
            app,
            [
                "exchange-lineage-diagnose",
                str(receiver),
                str(result["target_bundle_id"]),
                "--evidence",
                str(result["evidence_bundle_path"]),
            ],
        )
        assert cli_result.exit_code == 0, cli_result.output
        assert "recuperable" in cli_result.output
        assert "verified_bundle_chain" in cli_result.output
        assert "No se escribió ningún dato" in cli_result.output

        tables = set(inspect(engine).get_table_names())
        assert {
            "exchange_lineage_cases",
            "exchange_lineage_evidence",
            "exchange_lineage_decisions",
        } <= tables
        with session_scope(engine) as session:
            from archive_workbench.db.models import (
                ExchangeLineageCase,
                ExchangeLineageDecision,
                ExchangeLineageEvidence,
            )

            assert session.scalar(select(ExchangeLineageCase.id)) is None
            assert session.scalar(select(ExchangeLineageEvidence.id)) is None
            assert session.scalar(select(ExchangeLineageDecision.id)) is None
    finally:
        engine.dispose()


def _create_lineage_recovery_validation_pair(tmp_path: Path) -> dict[str, object]:
    import importlib.util

    base = tmp_path / "lineage_base"
    base_engine, _decisions, _object_id = _seed_project(base)
    base_engine.dispose()
    (base / "config").mkdir(parents=True, exist_ok=True)
    shutil.copy2(
        Path(__file__).parents[1] / "config" / "decisions.yaml",
        base / "config" / "decisions.yaml",
    )
    script_path = (
        Path(__file__).parents[1]
        / "scripts"
        / "create_lineage_diagnostic_validation_projects.py"
    )
    spec = importlib.util.spec_from_file_location(
        "lineage_recovery_validation_script", script_path
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.create_validation_projects(
        base,
        tmp_path / "lineage_source",
        tmp_path / "lineage_receiver",
        force=False,
    )


def test_lineage_recovery_rejects_incomplete_confirmation_without_writing(
    tmp_path: Path,
) -> None:
    from archive_workbench.db.models import (
        ExchangeLineageCase,
        ExchangeLineageDecision,
        ExchangeLineageEvidence,
    )
    from archive_workbench.lineage_recovery import recover_unmatched_bundle_lineage

    result = _create_lineage_recovery_validation_pair(tmp_path)
    engine = create_sqlite_engine(database_path(Path(result["receiver"])))
    try:
        with pytest.raises(ValueError, match="confirmación explícita"):
            with session_scope(engine) as session:
                recover_unmatched_bundle_lineage(
                    session,
                    project_root=Path(result["receiver"]),
                    bundle_ref=str(result["target_bundle_id"]),
                    evidence_paths=[Path(result["evidence_bundle_path"])],
                    recovered_by="alex",
                    confirmation_reason="Prueba incompleta.",
                    recovery_confirmed=False,
                    source="ui",
                )
        with session_scope(engine) as session:
            assert session.scalar(select(ExchangeLineageCase.id)) is None
            assert session.scalar(select(ExchangeLineageEvidence.id)) is None
            assert session.scalar(select(ExchangeLineageDecision.id)) is None
    finally:
        engine.dispose()


def test_lineage_recovery_is_append_only_invalidates_dry_run_and_reruns_matched(
    tmp_path: Path,
) -> None:
    from archive_workbench.db.models import (
        ExchangeDryRun,
        ExchangeLineageCase,
        ExchangeLineageDecision,
        ExchangeLineageEvidence,
    )
    from archive_workbench.lineage_recovery import recover_unmatched_bundle_lineage

    result = _create_lineage_recovery_validation_pair(tmp_path)
    receiver = Path(result["receiver"])
    engine = create_sqlite_engine(database_path(receiver))
    try:
        with session_scope(engine) as session:
            before_text = session.scalar(select(EditableObject.current_text))
            summary = recover_unmatched_bundle_lineage(
                session,
                project_root=receiver,
                bundle_ref=str(result["target_bundle_id"]),
                evidence_paths=[Path(result["evidence_bundle_path"])],
                recovered_by="alex",
                confirmation_reason="Validación automatizada EX-01B.",
                recovery_confirmed=True,
                source="ui",
            )
            after_text = session.scalar(select(EditableObject.current_text))
            assert before_text == after_text
            assert summary.recovery_method == "verified_bundle_chain"
            assert summary.current_dry_run_status == "stale"

        with session_scope(engine) as session:
            cases = session.scalars(select(ExchangeLineageCase)).all()
            evidence = session.scalars(select(ExchangeLineageEvidence)).all()
            decisions = session.scalars(select(ExchangeLineageDecision)).all()
            dry = session.scalar(
                select(ExchangeDryRun).where(
                    ExchangeDryRun.bundle_id == str(result["target_bundle_id"])
                )
            )
            assert len(cases) == 1
            assert len(evidence) >= 2
            assert len(decisions) == 1
            assert dry and dry.overall_status == "stale"
            decision = decisions[0]
            assert decision.operation == "recover_lineage"
            assert decision.result == "recovered"
            assert decision.recovery_confirmed is True
            assert decision.confirmed_by == "alex"
            assert decision.confirmation_reason == "Validación automatizada EX-01B."
            assert decision.recovery_method == "verified_bundle_chain"
            assert decision.remote_sequence == decision.target_base_sequence
            assert len(decision.parameters_sha256) == 64
            assert decision.evidence_ids_json
            assert all(
                row.case_id == cases[0].id and row.id in decision.evidence_ids_json
                for row in evidence
                if row.selected_for_decision
            )

        with pytest.raises(ValueError, match="ya fue recuperado"):
            with session_scope(engine) as session:
                recover_unmatched_bundle_lineage(
                    session,
                    project_root=receiver,
                    bundle_ref=str(result["target_bundle_id"]),
                    evidence_paths=[Path(result["evidence_bundle_path"])],
                    recovered_by="alex",
                    confirmation_reason="Intento repetido.",
                    recovery_confirmed=True,
                    source="ui",
                )

        with session_scope(engine) as session:
            rerun = dry_run_change_bundle(
                session,
                project_root=receiver,
                bundle_path=Path(result["target_bundle_path"]),
                assessed_by="alex",
            )
            assert rerun.repeated_assessment is True
            assert rerun.base_match_status == "matched"
            assert rerun.base_match_method == "recovered_lineage"
            assert rerun.common_checkpoint_label == "baseline_ex01a"
        with session_scope(engine) as session:
            dry = session.scalar(
                select(ExchangeDryRun).where(
                    ExchangeDryRun.bundle_id == str(result["target_bundle_id"])
                )
            )
            assert dry
            assert dry.base_match_status == "matched"
            assert dry.base_match_method == "recovered_lineage"
            assert dry.overall_status != "stale"
            assert session.scalar(select(func.count(ExchangeLineageCase.id))) == 1
            assert session.scalar(select(func.count(ExchangeLineageDecision.id))) == 1
            integrity = session.execute(text("PRAGMA integrity_check")).scalar_one()
            foreign_keys = session.execute(text("PRAGMA foreign_key_check")).all()
            assert integrity == "ok"
            assert foreign_keys == []
    finally:
        engine.dispose()


def test_exchange_lineage_recover_cli_requires_confirmation_and_lists_decision(
    tmp_path: Path,
) -> None:
    result = _create_lineage_recovery_validation_pair(tmp_path)
    receiver = str(result["receiver"])
    bundle_id = str(result["target_bundle_id"])
    evidence = str(result["evidence_bundle_path"])

    rejected = CliRunner().invoke(
        app,
        [
            "exchange-lineage-recover",
            receiver,
            bundle_id,
            "--evidence",
            evidence,
            "--recovered-by",
            "alex",
            "--reason",
            "Validación CLI EX-01B.",
        ],
    )
    assert rejected.exit_code != 0
    assert "confirmación explícita" in rejected.output

    recovered = CliRunner().invoke(
        app,
        [
            "exchange-lineage-recover",
            receiver,
            bundle_id,
            "--evidence",
            evidence,
            "--recovered-by",
            "alex",
            "--reason",
            "Validación CLI EX-01B.",
            "--confirm-recovery",
        ],
    )
    assert recovered.exit_code == 0, recovered.output
    assert "linaje recuperado" in recovered.output
    assert "verified_bundle_chain" in recovered.output
    assert "simulación anterior quedó obsoleta" in recovered.output
    assert "No se modificó el corpus" in recovered.output

    listed = CliRunner().invoke(
        app,
        ["exchange-lineage-recoveries", receiver],
    )
    assert listed.exit_code == 0, listed.output
    assert bundle_id in listed.output
    assert "Validación CLI EX-01B." in listed.output
    assert "Total: 1 recuperaciones" in listed.output


def _create_common_base_pair(tmp_path: Path) -> dict[str, object]:
    (
        initiator_root,
        initiator_engine,
        decisions,
        object_id,
        counterpart_root,
        counterpart_engine,
        counterpart_workspace_id,
    ) = _source_and_receiver(tmp_path)
    with session_scope(initiator_engine) as session:
        initiator_workspace = ensure_exchange_workspace(session)
        initiator_workspace_id = initiator_workspace.id
        initiator_workspace_name = initiator_workspace.workspace_name
    with session_scope(counterpart_engine) as session:
        counterpart_workspace = ensure_exchange_workspace(session)
        counterpart_workspace_name = counterpart_workspace.workspace_name
    return {
        "initiator_root": initiator_root,
        "initiator_engine": initiator_engine,
        "counterpart_root": counterpart_root,
        "counterpart_engine": counterpart_engine,
        "initiator_workspace_id": initiator_workspace_id,
        "initiator_workspace_name": initiator_workspace_name,
        "counterpart_workspace_id": counterpart_workspace_id,
        "counterpart_workspace_name": counterpart_workspace_name,
        "decisions": decisions,
        "object_id": object_id,
    }


def test_common_base_rejects_different_editable_state_without_writing(
    tmp_path: Path,
) -> None:
    from archive_workbench.common_base import (
        accept_common_base_proposal,
        create_common_base_proposal,
    )
    from archive_workbench.db.models import ExchangeCommonBaseAgreement

    pair = _create_common_base_pair(tmp_path)
    initiator_engine = pair["initiator_engine"]
    counterpart_engine = pair["counterpart_engine"]
    try:
        with session_scope(initiator_engine) as session:
            proposal = create_common_base_proposal(
                session,
                project_root=pair["initiator_root"],
                counterpart_workspace_id=pair["counterpart_workspace_id"],
                counterpart_workspace_name=pair["counterpart_workspace_name"],
                proposed_by="alex",
                proposal_reason="Validación de rechazo por divergencia.",
                proposal_confirmed=True,
                source="ui",
            )
        with session_scope(counterpart_engine) as session:
            editable = session.get(EditableObject, pair["object_id"])
            assert editable
            update_editable_object(
                session,
                decisions=pair["decisions"],
                object_id=editable.id,
                expected_revision=editable.revision_number,
                edited_by="alex",
                text=editable.current_text + "\nEstado divergente",
            )
        with pytest.raises(ValueError, match="estados editables difieren"):
            with session_scope(counterpart_engine) as session:
                accept_common_base_proposal(
                    session,
                    project_root=pair["counterpart_root"],
                    proposal_path=proposal.output_path,
                    accepted_by="alex",
                    confirmation_reason="No debe escribirse.",
                    agreement_confirmed=True,
                    source="ui",
                )
        with session_scope(counterpart_engine) as session:
            assert session.scalar(select(ExchangeCommonBaseAgreement.id)) is None
            assert session.scalar(select(func.count(ExchangeCheckpoint.id))) == 1
    finally:
        initiator_engine.dispose()
        counterpart_engine.dispose()


def test_common_base_bilateral_agreement_is_append_only_and_recognizes_next_bundle(
    tmp_path: Path,
) -> None:
    from archive_workbench.common_base import (
        accept_common_base_proposal,
        common_base_agreement_rows,
        create_common_base_proposal,
        finalize_common_base_agreement,
    )
    from archive_workbench.db.models import ExchangeCommonBaseAgreement, ExchangeDryRun

    pair = _create_common_base_pair(tmp_path)
    initiator_engine = pair["initiator_engine"]
    counterpart_engine = pair["counterpart_engine"]
    try:
        with session_scope(initiator_engine) as session:
            pre_bundle = export_change_bundle(
                session,
                project_root=pair["initiator_root"],
                checkpoint_ref="baseline",
                created_by="alex",
            )
        with session_scope(counterpart_engine) as session:
            pre_dry = dry_run_change_bundle(
                session,
                project_root=pair["counterpart_root"],
                bundle_path=pre_bundle.output_path,
                assessed_by="alex",
            )
            assert pre_dry.base_match_status == "matched"
        with session_scope(initiator_engine) as session:
            proposal = create_common_base_proposal(
                session,
                project_root=pair["initiator_root"],
                counterpart_workspace_id=pair["counterpart_workspace_id"],
                counterpart_workspace_name=pair["counterpart_workspace_name"],
                proposed_by="alex",
                proposal_reason="Validación EX-01C iniciadora.",
                proposal_confirmed=True,
                source="cli",
            )
        with session_scope(counterpart_engine) as session:
            accepted = accept_common_base_proposal(
                session,
                project_root=pair["counterpart_root"],
                proposal_path=proposal.output_path,
                accepted_by="alex",
                confirmation_reason="Validación EX-01C contraparte.",
                agreement_confirmed=True,
                source="ui",
            )
            assert accepted.stale_dry_run_count == 1
        assert accepted.output_path is not None
        with session_scope(initiator_engine) as session:
            finalized = finalize_common_base_agreement(
                session,
                project_root=pair["initiator_root"],
                proposal_path=proposal.output_path,
                agreement_path=accepted.output_path,
                finalized_by="alex",
                confirmation_reason="Validación EX-01C finalización.",
                agreement_confirmed=True,
                source="cli",
            )

        assert accepted.agreement_id == finalized.agreement_id
        assert accepted.manifest_sha256 == finalized.manifest_sha256
        assert accepted.proposal_sha256 == finalized.proposal_sha256
        assert accepted.state_sha256 == finalized.state_sha256
        assert accepted.checkpoint_label == finalized.checkpoint_label
        assert accepted.checkpoint_id != finalized.checkpoint_id
        assert accepted.local_role == "counterpart"
        assert finalized.local_role == "initiator"

        with session_scope(initiator_engine) as session:
            initiator_rows = common_base_agreement_rows(session)
            assert len(initiator_rows) == 1
            assert initiator_rows[0].agreement_id == accepted.agreement_id
        with session_scope(counterpart_engine) as session:
            counterpart_rows = common_base_agreement_rows(session)
            assert len(counterpart_rows) == 1
            assert counterpart_rows[0].agreement_id == accepted.agreement_id
            stale = session.scalar(
                select(ExchangeDryRun).where(ExchangeDryRun.bundle_id == pre_bundle.bundle_id)
            )
            assert stale and stale.overall_status == "stale"

        with pytest.raises(ValueError, match="ya fue registrado"):
            with session_scope(counterpart_engine) as session:
                accept_common_base_proposal(
                    session,
                    project_root=pair["counterpart_root"],
                    proposal_path=proposal.output_path,
                    accepted_by="alex",
                    confirmation_reason="Intento repetido.",
                    agreement_confirmed=True,
                    source="ui",
                )
        with pytest.raises(ValueError, match="ya fue registrado"):
            with session_scope(initiator_engine) as session:
                finalize_common_base_agreement(
                    session,
                    project_root=pair["initiator_root"],
                    proposal_path=proposal.output_path,
                    agreement_path=accepted.output_path,
                    finalized_by="alex",
                    confirmation_reason="Intento repetido.",
                    agreement_confirmed=True,
                    source="cli",
                )

        with session_scope(initiator_engine) as session:
            post_bundle = export_change_bundle(
                session,
                project_root=pair["initiator_root"],
                checkpoint_ref=finalized.checkpoint_label,
                created_by="alex",
            )
            assert post_bundle.event_count == 0
        with session_scope(counterpart_engine) as session:
            post_dry = dry_run_change_bundle(
                session,
                project_root=pair["counterpart_root"],
                bundle_path=post_bundle.output_path,
                assessed_by="alex",
            )
            assert post_dry.base_match_status == "matched"
            assert post_dry.base_match_method == "common_base_agreement"
            assert post_dry.common_checkpoint_label == accepted.checkpoint_label
            assert session.scalar(select(func.count(ExchangeCommonBaseAgreement.id))) == 1
            assert session.execute(text("PRAGMA integrity_check")).scalar_one() == "ok"
            assert session.execute(text("PRAGMA foreign_key_check")).all() == []
    finally:
        initiator_engine.dispose()
        counterpart_engine.dispose()


def test_common_base_cli_requires_confirmation_and_lists_same_agreement(
    tmp_path: Path,
) -> None:
    pair = _create_common_base_pair(tmp_path)
    pair["initiator_engine"].dispose()
    pair["counterpart_engine"].dispose()

    rejected = CliRunner().invoke(
        app,
        [
            "exchange-common-base-propose",
            str(pair["initiator_root"]),
            "--counterpart-workspace-id",
            str(pair["counterpart_workspace_id"]),
            "--counterpart-workspace-name",
            str(pair["counterpart_workspace_name"]),
            "--proposed-by",
            "alex",
            "--reason",
            "Validación CLI EX-01C.",
        ],
    )
    assert rejected.exit_code != 0
    assert "confirmación explícita" in rejected.output

    proposal_path = tmp_path / "proposal.zip"
    proposed = CliRunner().invoke(
        app,
        [
            "exchange-common-base-propose",
            str(pair["initiator_root"]),
            "--counterpart-workspace-id",
            str(pair["counterpart_workspace_id"]),
            "--counterpart-workspace-name",
            str(pair["counterpart_workspace_name"]),
            "--proposed-by",
            "alex",
            "--reason",
            "Validación CLI EX-01C.",
            "--confirm-proposal",
            "--destination",
            str(proposal_path),
        ],
    )
    assert proposed.exit_code == 0, proposed.output
    assert "no activó ningún acuerdo" in proposed.output

    agreement_path = tmp_path / "agreement.zip"
    accepted = CliRunner().invoke(
        app,
        [
            "exchange-common-base-accept",
            str(pair["counterpart_root"]),
            str(proposal_path),
            "--accepted-by",
            "alex",
            "--reason",
            "Validación CLI contraparte.",
            "--confirm-agreement",
            "--destination",
            str(agreement_path),
        ],
    )
    assert accepted.exit_code == 0, accepted.output
    assert "acuerdo aceptado" in accepted.output

    finalized = CliRunner().invoke(
        app,
        [
            "exchange-common-base-finalize",
            str(pair["initiator_root"]),
            str(agreement_path),
            "--proposal",
            str(proposal_path),
            "--finalized-by",
            "alex",
            "--reason",
            "Validación CLI iniciadora.",
            "--confirm-agreement",
        ],
    )
    assert finalized.exit_code == 0, finalized.output
    assert "acuerdo finalizado" in finalized.output

    left = CliRunner().invoke(
        app,
        ["exchange-common-base-agreements", str(pair["initiator_root"])],
    )
    right = CliRunner().invoke(
        app,
        ["exchange-common-base-agreements", str(pair["counterpart_root"])],
    )
    assert left.exit_code == right.exit_code == 0
    assert "rol=initiator" in left.output
    assert "rol=counterpart" in right.output
    assert "Total: 1 acuerdos" in left.output
    assert "Total: 1 acuerdos" in right.output


def test_common_base_validation_script_creates_distinct_identical_copies(
    tmp_path: Path,
) -> None:
    import importlib.util

    base = tmp_path / "common_base_source"
    base_engine, _decisions, _object_id = _seed_project(base)
    base_engine.dispose()
    (base / "config").mkdir(parents=True, exist_ok=True)
    shutil.copy2(
        Path(__file__).parents[1] / "config" / "decisions.yaml",
        base / "config" / "decisions.yaml",
    )
    script_path = (
        Path(__file__).parents[1]
        / "scripts"
        / "create_common_base_validation_projects.py"
    )
    spec = importlib.util.spec_from_file_location(
        "common_base_validation_script", script_path
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    result = module.create_validation_projects(
        base,
        tmp_path / "common_base_a",
        tmp_path / "common_base_b",
        force=False,
    )
    assert result["revision"] == "0043_form_structure_review"
    assert result["initiator_workspace_id"] != result["counterpart_workspace_id"]
    assert len(str(result["state_sha256"])) == 64
    assert Path(result["validation_path"]).is_file()


def _create_state_adoption_pair(tmp_path: Path) -> dict[str, object]:
    pair = _create_common_base_pair(tmp_path)
    with session_scope(pair["initiator_engine"]) as session:
        editable = session.get(EditableObject, pair["object_id"])
        assert editable
        update_editable_object(
            session,
            decisions=pair["decisions"],
            object_id=editable.id,
            expected_revision=editable.revision_number,
            edited_by="alex",
            text="Estado remoto adoptable",
        )
        group_id = ensure_group(
            session,
            editable_page_id=editable.editable_page_id,
            label="Datos adoptables",
            changed_by="alex",
        )
        register_control(
            session,
            editable_page_id=editable.editable_page_id,
            state="marked",
            label="Validado",
            changed_by="alex",
            label_object_id=editable.id,
            group_id=group_id,
            source="manual",
            evidence_note="Estructura remota adoptable",
        )
    with session_scope(pair["counterpart_engine"]) as session:
        editable = session.get(EditableObject, pair["object_id"])
        assert editable
        update_editable_object(
            session,
            decisions=pair["decisions"],
            object_id=editable.id,
            expected_revision=editable.revision_number,
            edited_by="alex",
            text="Estado local divergente",
        )
    return pair


def test_state_adoption_preview_is_read_only_and_incomplete_apply_writes_nothing(
    tmp_path: Path,
) -> None:
    from archive_workbench.db.models import ExchangeStateAdoption
    from archive_workbench.exchange import current_editable_state_sha256
    from archive_workbench.state_adoption import (
        apply_state_adoption,
        create_state_adoption_package,
        preview_state_adoption,
    )

    pair = _create_state_adoption_pair(tmp_path)
    try:
        with session_scope(pair["initiator_engine"]) as session:
            package = create_state_adoption_package(
                session,
                project_root=pair["initiator_root"],
                target_workspace_id=pair["counterpart_workspace_id"],
                target_workspace_name=pair["counterpart_workspace_name"],
                created_by="alex",
                creation_reason="Validación EX-01D paquete.",
                package_confirmed=True,
            )
        with session_scope(pair["counterpart_engine"]) as session:
            project_id = session.scalar(select(DigitalObject.project_id))
            assert project_id
            before = current_editable_state_sha256(session, project_id)
            before_counts = {
                "adoptions": session.scalar(select(func.count(ExchangeStateAdoption.id))),
                "checkpoints": session.scalar(select(func.count(ExchangeCheckpoint.id))),
            }
            preview = preview_state_adoption(
                session,
                package_path=package.output_path,
            )
            assert preview.local_state_sha256 == before
            assert preview.incoming_state_sha256 == package.state_sha256
            assert preview.total_changed >= 1
            assert preview.total_added == 0
            assert preview.total_removed == 0
            assert current_editable_state_sha256(session, project_id) == before
            assert before_counts == {
                "adoptions": session.scalar(select(func.count(ExchangeStateAdoption.id))),
                "checkpoints": session.scalar(select(func.count(ExchangeCheckpoint.id))),
            }
            with pytest.raises(ValueError, match="confirmación"):
                apply_state_adoption(
                    session,
                    project_root=pair["counterpart_root"],
                    package_path=package.output_path,
                    applied_by="alex",
                    application_reason="No debe escribirse.",
                    adoption_confirmed=False,
                    source="ui",
                )
            assert session.scalar(select(ExchangeStateAdoption.id)) is None
            assert current_editable_state_sha256(session, project_id) == before
        assert not list((pair["counterpart_root"] / "backups" / "project").glob("*.zip"))
    finally:
        pair["initiator_engine"].dispose()
        pair["counterpart_engine"].dispose()


def test_state_adoption_is_transactional_audited_and_rollback_restores_previous_state(
    tmp_path: Path,
) -> None:
    from archive_workbench.db.models import (
        ExchangeStateAdoption,
        ExchangeStateAdoptionRollback,
    )
    from archive_workbench.exchange import current_editable_state_sha256
    from archive_workbench.state_adoption import (
        apply_state_adoption,
        create_state_adoption_package,
        rollback_state_adoption,
        state_adoption_rows,
    )

    pair = _create_state_adoption_pair(tmp_path)
    try:
        with session_scope(pair["initiator_engine"]) as session:
            source_project_id = session.scalar(select(DigitalObject.project_id))
            assert source_project_id
            source_state = current_editable_state_sha256(session, source_project_id)
            package = create_state_adoption_package(
                session,
                project_root=pair["initiator_root"],
                target_workspace_id=pair["counterpart_workspace_id"],
                target_workspace_name=pair["counterpart_workspace_name"],
                created_by="alex",
                creation_reason="Validación EX-01D paquete.",
                package_confirmed=True,
            )
        with session_scope(pair["counterpart_engine"]) as session:
            target_project_id = session.scalar(select(DigitalObject.project_id))
            assert target_project_id
            previous_state = current_editable_state_sha256(session, target_project_id)
            summary = apply_state_adoption(
                session,
                project_root=pair["counterpart_root"],
                package_path=package.output_path,
                applied_by="alex",
                application_reason="Validación EX-01D adopción.",
                adoption_confirmed=True,
                source="ui",
            )
            assert summary.previous_state_sha256 == previous_state
            assert summary.adopted_state_sha256 == source_state
            assert summary.backup_path.is_file()
            assert len(summary.backup_sha256) == 64
            assert current_editable_state_sha256(session, target_project_id) == source_state
            editable = session.get(EditableObject, pair["object_id"])
            assert editable and editable.current_text == "Estado remoto adoptable"
            adopted_structure = form_structure(
                session, editable_page_id=editable.editable_page_id
            )
            assert adopted_structure.groups[0].label == "Datos adoptables"
            assert adopted_structure.controls[0].state == "marked"
            assert session.scalar(select(func.count(ExchangeStateAdoption.id))) == 1
            assert session.execute(text("PRAGMA integrity_check")).scalar_one() == "ok"
            assert session.execute(text("PRAGMA foreign_key_check")).all() == []
            adoption_id = summary.adoption_id

        pair["counterpart_engine"].dispose()
        rollback = rollback_state_adoption(
            project_root=pair["counterpart_root"],
            adoption_ref=adoption_id,
            rolled_back_by="alex",
            rollback_reason="Validación EX-01D rollback.",
            rollback_confirmed=True,
            source="cli",
        )
        assert rollback.restored_state_sha256 == previous_state
        assert rollback.safety_backup.is_file()

        pair["counterpart_engine"] = create_sqlite_engine(
            database_path(pair["counterpart_root"])
        )
        with session_scope(pair["counterpart_engine"]) as session:
            editable = session.get(EditableObject, pair["object_id"])
            assert editable and editable.current_text == "Estado local divergente"
            restored_structure = form_structure(
                session, editable_page_id=editable.editable_page_id
            )
            assert restored_structure.groups == []
            assert restored_structure.controls == []
            rows = state_adoption_rows(session)
            assert len(rows) == 1
            assert rows[0].rolled_back is True
            assert rows[0].rollback_reason == "Validación EX-01D rollback."
            assert session.scalar(select(func.count(ExchangeStateAdoption.id))) == 1
            assert session.scalar(select(func.count(ExchangeStateAdoptionRollback.id))) == 1
            assert session.execute(text("PRAGMA integrity_check")).scalar_one() == "ok"
            assert session.execute(text("PRAGMA foreign_key_check")).all() == []
    finally:
        pair["initiator_engine"].dispose()
        pair["counterpart_engine"].dispose()


def test_state_adoption_cli_preview_apply_and_list(tmp_path: Path) -> None:
    from archive_workbench.state_adoption import create_state_adoption_package

    pair = _create_state_adoption_pair(tmp_path)
    try:
        with session_scope(pair["initiator_engine"]) as session:
            package = create_state_adoption_package(
                session,
                project_root=pair["initiator_root"],
                target_workspace_id=pair["counterpart_workspace_id"],
                target_workspace_name=pair["counterpart_workspace_name"],
                created_by="alex",
                creation_reason="Validación CLI EX-01D.",
                package_confirmed=True,
            )
    finally:
        pair["initiator_engine"].dispose()
        pair["counterpart_engine"].dispose()

    preview = CliRunner().invoke(
        app,
        [
            "exchange-state-adoption-preview",
            str(pair["counterpart_root"]),
            str(package.output_path),
        ],
    )
    assert preview.exit_code == 0, preview.output
    assert "Vista previa de solo lectura" in preview.output
    assert "cambiar" in preview.output

    rejected = CliRunner().invoke(
        app,
        [
            "exchange-state-adopt",
            str(pair["counterpart_root"]),
            str(package.output_path),
            "--applied-by",
            "alex",
            "--reason",
            "Validación CLI EX-01D.",
        ],
    )
    assert rejected.exit_code != 0
    assert "confirmación" in rejected.output

    applied = CliRunner().invoke(
        app,
        [
            "exchange-state-adopt",
            str(pair["counterpart_root"]),
            str(package.output_path),
            "--applied-by",
            "alex",
            "--reason",
            "Validación CLI EX-01D.",
            "--confirm-adoption",
        ],
    )
    assert applied.exit_code == 0, applied.output
    assert "estado divergente adoptado" in applied.output
    assert "Backup previo" in applied.output

    listed = CliRunner().invoke(
        app,
        ["exchange-state-adoptions", str(pair["counterpart_root"])],
    )
    assert listed.exit_code == 0, listed.output
    assert package.adoption_id in listed.output
    assert "activa" in listed.output
    assert "Total: 1 adopciones" in listed.output


def test_state_adoption_validation_script_creates_divergent_copies_and_package(
    tmp_path: Path,
) -> None:
    import importlib.util

    base = tmp_path / "state_adoption_source"
    base_engine, _decisions, _object_id = _seed_project(base)
    base_engine.dispose()
    (base / "config").mkdir(parents=True, exist_ok=True)
    shutil.copy2(
        Path(__file__).parents[1] / "config" / "decisions.yaml",
        base / "config" / "decisions.yaml",
    )
    script_path = (
        Path(__file__).parents[1]
        / "scripts"
        / "create_state_adoption_validation_projects.py"
    )
    spec = importlib.util.spec_from_file_location(
        "state_adoption_validation_script", script_path
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    result = module.create_validation_projects(
        base,
        tmp_path / "state_adoption_origin",
        tmp_path / "state_adoption_target",
        force=False,
    )
    assert result["revision"] == "0043_form_structure_review"
    assert result["source_workspace_id"] != result["target_workspace_id"]
    assert result["source_state_sha256"] != result["target_state_sha256"]
    assert Path(result["package_path"]).is_file()
    assert Path(result["validation_path"]).is_file()
