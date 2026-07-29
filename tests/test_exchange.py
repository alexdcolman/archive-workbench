from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import shutil
import zipfile

import fitz
import pytest
from typer.testing import CliRunner
from sqlalchemy import inspect, select

from archive_workbench.catalog import register_test_corpus
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
from archive_workbench.identity import new_id
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
        session.add(
            ExtractionPageSelection(
                id=new_id(),
                digital_object_id=digital.id,
                page_number=1,
                extraction_run_id=run.id,
                extraction_page_id=extraction_page.id,
                selected_by="tests",
            )
        )
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
    return engine, decisions, object_id


def test_exchange_migration_upgrades_existing_0012_database(tmp_path: Path) -> None:
    root = tmp_path / "project"
    upgrade_database(root, revision="0012_editable_search_fts")
    assert current_revision(root) == "0012_editable_search_fts"
    upgrade_database(root)
    assert current_revision(root) == "0028_operational_readiness"
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
    assert current_revision(root) == "0028_operational_readiness"
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
    assert current_revision(root) == "0028_operational_readiness"
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
    assert current_revision(root) == "0028_operational_readiness"
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
    assert current_revision(root) == "0028_operational_readiness"
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
    assert current_revision(root) == "0028_operational_readiness"
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
            assert relation.relation_label == "integró"
            assert relation.evidence_note == "Según el informe revisado."
            assert relation.temporal_expression == "03/1974 - 03/1976"
            assert relation.temporal_start.isoformat() == "1974-03-01"
            assert relation.temporal_end.isoformat() == "1976-03-31"
            assert relation.temporal_note == "Vigencia documentada"
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


def test_bundle_export_rejects_post_checkpoint_ocr_bootstrap_events(tmp_path: Path) -> None:
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
            with pytest.raises(ValueError, match=r"1 objetos OCR.*1 páginas.*1 documentos"):
                export_change_bundle(
                    session,
                    project_root=root,
                    checkpoint_ref="after_shared_baseline",
                    created_by="Alex",
                )
            assert session.scalar(select(ExchangeCheckpoint).where(ExchangeCheckpoint.label.like("bundle_%"))) is None
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
