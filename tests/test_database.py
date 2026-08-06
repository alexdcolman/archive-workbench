from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import fitz

from archive_workbench.catalog import database_counts, register_test_corpus, scan_file_instances
from archive_workbench.contracts.test_corpus import TestCorpus as CorpusDefinition
from archive_workbench.db import (
    create_sqlite_engine,
    current_revision,
    database_path,
    session_scope,
    upgrade_database,
)
from archive_workbench.decisions import load_decisions


def _write_pdf(path: Path, pages: int = 1) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    document = fitz.open()
    for _ in range(pages):
        document.new_page(width=600, height=400)
    document.save(path)
    document.close()


def _corpus() -> CorpusDefinition:
    return CorpusDefinition.model_validate(
        {
            "corpus_name": "Prueba",
            "created_by": "Alex",
            "created_at": datetime.now(timezone.utc),
            "documents": [
                {
                    "test_id": "documento_prueba",
                    "local_path": "corpus/caja/a.pdf",
                    "short_description": "Documento de prueba",
                    "archival_location": {
                        "fondo": "SiCH",
                        "caja": "Caja 1",
                        "documento": "Documento A",
                    },
                    "input_characteristics": {
                        "format": "pdf",
                        "scanned": True,
                        "digital_text_layer": False,
                        "multipage_tiff": False,
                        "poor_contrast": False,
                        "skewed_pages": False,
                        "landscape_pages": True,
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


def test_migration_and_registration_are_idempotent(tmp_path: Path) -> None:
    root = tmp_path / "project"
    _write_pdf(root / "corpus/caja/a.pdf")
    decisions = load_decisions(Path(__file__).parents[1] / "config/decisions.yaml")
    corpus = _corpus()

    upgrade_database(root)
    assert current_revision(root) == "0044_layout_structure_review"

    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            first = register_test_corpus(
                session,
                project_root=root,
                decisions=decisions,
                corpus=corpus,
            )
        with session_scope(engine) as session:
            second = register_test_corpus(
                session,
                project_root=root,
                decisions=decisions,
                corpus=corpus,
            )
        with session_scope(engine) as session:
            counts = database_counts(session)
    finally:
        engine.dispose()

    assert first.digital_objects_created == 1
    assert first.archival_units_created == 4
    assert second.digital_objects_created == 0
    assert counts["digital_objects"] == 1
    assert counts["file_instances"] == 1
    assert counts["archival_units"] == 4
    assert counts["source_registrations"] == 1


def test_scan_detects_modified_file(tmp_path: Path) -> None:
    root = tmp_path / "project"
    path = root / "corpus/caja/a.pdf"
    _write_pdf(path, pages=1)
    decisions = load_decisions(Path(__file__).parents[1] / "config/decisions.yaml")
    corpus = _corpus()
    upgrade_database(root)
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            register_test_corpus(
                session,
                project_root=root,
                decisions=decisions,
                corpus=corpus,
            )
        _write_pdf(path, pages=2)
        with session_scope(engine) as session:
            summary = scan_file_instances(session, root)
    finally:
        engine.dispose()
    assert summary.checked == 1
    assert summary.modified == 1


def test_quality_and_page_selection_migrations_upgrade_existing_0003_database(tmp_path: Path) -> None:
    from sqlalchemy import inspect

    root = tmp_path / "project"
    upgrade_database(root, revision="0003_extraction_objects")
    assert current_revision(root) == "0003_extraction_objects"
    upgrade_database(root)
    assert current_revision(root) == "0044_layout_structure_review"
    engine = create_sqlite_engine(database_path(root))
    try:
        inspector = inspect(engine)
        columns = {item["name"] for item in inspector.get_columns("extraction_runs")}
        editable_page_columns = {
            item["name"] for item in inspector.get_columns("editable_pages")
        }
        editable_object_columns = {
            item["name"] for item in inspector.get_columns("editable_objects")
        }
        editable_revision_columns = {
            item["name"] for item in inspector.get_columns("editable_object_revisions")
        }
        editable_tag_columns = {
            item["name"] for item in inspector.get_columns("editable_object_tags")
        }
        tables = set(inspector.get_table_names())
    finally:
        engine.dispose()
    assert {
        "quality_status",
        "quality_score",
        "quality_note",
        "reviewed_by",
        "reviewed_at",
    } <= columns
    assert "extraction_page_selections" in tables
    assert "extraction_page_selection_revisions" in tables
    assert "editable_page_revisions" in tables
    assert "extraction_regions" in tables
    assert "document_parts" in tables
    assert "document_processing_plans" in tables
    assert "page_processing_assignments" in tables
    assert "regions_path" in columns
    assert "editable_pages" in tables
    assert "editable_objects" in tables
    assert "editable_object_revisions" in tables
    assert "editable_page_actions" in tables
    assert "editable_object_comments" in tables
    assert "editable_object_tags" in tables
    assert "archival_unit_revisions" in tables
    assert "editable_search_state" in tables
    assert "editable_search_fts" in tables
    assert {
        "revision_number",
        "review_status",
        "review_note",
        "reviewed_by",
        "reviewed_at",
    } <= editable_page_columns
    assert {"review_status", "document_part_id"} <= editable_object_columns
    assert "document_part_id" in editable_revision_columns
    assert "tag_kind" in editable_tag_columns


def test_temporal_migration_upgrades_existing_031_database(tmp_path: Path) -> None:
    from sqlalchemy import inspect

    root = tmp_path / "project"
    upgrade_database(root, revision="0026_team_workflow")
    assert current_revision(root) == "0026_team_workflow"
    upgrade_database(root)
    assert current_revision(root) == "0044_layout_structure_review"
    engine = create_sqlite_engine(database_path(root))
    try:
        inspector = inspect(engine)
        authority_columns = {row["name"] for row in inspector.get_columns("authority_records")}
        relation_columns = {row["name"] for row in inspector.get_columns("entity_relations")}
        profile_columns = {row["name"] for row in inspector.get_columns("corpus_export_profiles")}
    finally:
        engine.dispose()
    expected = {
        "temporal_expression", "temporal_start", "temporal_end",
        "temporal_precision", "temporal_approximate", "temporal_note",
    }
    assert expected.issubset(authority_columns)
    assert expected.issubset(relation_columns)
    assert {"temporal_start", "temporal_end", "temporal_include_undated"}.issubset(profile_columns)


def test_operational_readiness_migration_upgrades_existing_032_database(tmp_path: Path) -> None:
    from sqlalchemy import inspect

    root = tmp_path / "project"
    upgrade_database(root, revision="0027_temporal_authorities_relations")
    assert current_revision(root) == "0027_temporal_authorities_relations"
    upgrade_database(root)
    assert current_revision(root) == "0044_layout_structure_review"
    engine = create_sqlite_engine(database_path(root))
    try:
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
        columns = {
            row["name"] for row in inspector.get_columns("project_recovery_checks")
        }
    finally:
        engine.dispose()
    assert "project_recovery_checks" in tables
    assert {
        "backup_relative_path",
        "backup_sha256",
        "source_database_revision",
        "upgraded_database_revision",
        "status",
        "details_json",
        "tested_by",
        "tested_at",
    }.issubset(columns)


def test_temporal_migration_preserves_authority_mentions_and_relations(tmp_path: Path) -> None:
    """0027 must add temporal columns without recreating authority_records."""
    import json

    from sqlalchemy import text

    from archive_workbench.identity import new_id
    from tests.test_search import _seed_search_project

    root = tmp_path / "project"
    object_id, _page_id = _seed_search_project(root, revision="0026_team_workflow")
    assert current_revision(root) == "0026_team_workflow"

    source_authority_id = new_id()
    target_authority_id = new_id()
    mention_id = new_id()
    relation_id = new_id()
    now = "2026-07-24T13:00:00+00:00"

    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            authority_sql = text(
                """
                INSERT INTO authority_records (
                    id, project_id, entity_type, preferred_name, normalized_name,
                    description, lifecycle_status, review_status, created_by,
                    created_at, updated_by, updated_at, revision
                ) VALUES (
                    :id, 'search_project', 'organization', :name, :normalized_name,
                    NULL, 'active', 'approved', 'tests', :now, 'tests', :now, 1
                )
                """
            )
            session.execute(
                authority_sql,
                {
                    "id": source_authority_id,
                    "name": "Secretaría de Inteligencia de Estado",
                    "normalized_name": "secretaria de inteligencia de estado",
                    "now": now,
                },
            )
            session.execute(
                authority_sql,
                {
                    "id": target_authority_id,
                    "name": "Servicio de Informaciones del Chubut",
                    "normalized_name": "servicio de informaciones del chubut",
                    "now": now,
                },
            )
            session.execute(
                text(
                    """
                    INSERT INTO authority_aliases (
                        id, authority_id, alias, normalized_alias, alias_type,
                        note, created_by, created_at
                    ) VALUES (
                        :id, :authority_id, 'SIDE', 'side', 'acronym',
                        NULL, 'tests', :now
                    )
                    """
                ),
                {"id": new_id(), "authority_id": source_authority_id, "now": now},
            )
            session.execute(
                text(
                    """
                    INSERT INTO authority_revisions (
                        id, authority_id, revision_number, operation, snapshot_json,
                        note, changed_by, changed_at
                    ) VALUES (
                        :id, :authority_id, 1, 'create', :snapshot,
                        NULL, 'tests', :now
                    )
                    """
                ),
                {
                    "id": new_id(),
                    "authority_id": source_authority_id,
                    "snapshot": json.dumps(
                        {
                            "id": source_authority_id,
                            "project_id": "search_project",
                            "entity_type": "organization",
                            "preferred_name": "Secretaría de Inteligencia de Estado",
                            "normalized_name": "secretaria de inteligencia de estado",
                            "description": None,
                            "lifecycle_status": "active",
                            "review_status": "approved",
                            "aliases": ["SIDE"],
                        }
                    ),
                    "now": now,
                },
            )
            session.execute(
                text(
                    """
                    INSERT INTO entity_mentions (
                        id, editable_object_id, authority_id, mention_text,
                        normalized_text, start_offset, end_offset,
                        object_revision_number, status, source, confidence, note,
                        created_by, created_at, updated_by, updated_at, revision
                    ) VALUES (
                        :id, :object_id, :authority_id, 'SIDE', 'side', 0, 4,
                        1, 'accepted', 'dictionary', 1.0, NULL,
                        'tests', :now, 'tests', :now, 1
                    )
                    """
                ),
                {
                    "id": mention_id,
                    "object_id": object_id,
                    "authority_id": source_authority_id,
                    "now": now,
                },
            )
            session.execute(
                text(
                    """
                    INSERT INTO entity_mention_revisions (
                        id, mention_id, revision_number, operation, snapshot_json,
                        note, changed_by, changed_at
                    ) VALUES (
                        :id, :mention_id, 1, 'create', :snapshot,
                        NULL, 'tests', :now
                    )
                    """
                ),
                {
                    "id": new_id(),
                    "mention_id": mention_id,
                    "snapshot": json.dumps(
                        {
                            "id": mention_id,
                            "editable_object_id": object_id,
                            "authority_id": source_authority_id,
                            "mention_text": "SIDE",
                            "normalized_text": "side",
                            "start_offset": 0,
                            "end_offset": 4,
                            "object_revision_number": 1,
                            "status": "accepted",
                            "source": "dictionary",
                            "confidence": 1.0,
                            "note": None,
                        }
                    ),
                    "now": now,
                },
            )
            session.execute(
                text(
                    """
                    INSERT INTO entity_relations (
                        id, project_id, source_authority_id, relation_label,
                        target_authority_id, target_archival_unit_id,
                        target_document_part_id, evidence_note, lifecycle_status,
                        review_status, created_by, created_at, updated_by,
                        updated_at, revision
                    ) VALUES (
                        :id, 'search_project', :source_id, 'dependió de', :target_id,
                        NULL, NULL, 'Documento, página 1', 'active', 'approved',
                        'tests', :now, 'tests', :now, 1
                    )
                    """
                ),
                {
                    "id": relation_id,
                    "source_id": target_authority_id,
                    "target_id": source_authority_id,
                    "now": now,
                },
            )
            session.execute(
                text(
                    """
                    INSERT INTO entity_relation_revisions (
                        id, relation_id, revision_number, operation, snapshot_json,
                        note, changed_by, changed_at
                    ) VALUES (
                        :id, :relation_id, 1, 'create', :snapshot,
                        NULL, 'tests', :now
                    )
                    """
                ),
                {
                    "id": new_id(),
                    "relation_id": relation_id,
                    "snapshot": json.dumps(
                        {
                            "id": relation_id,
                            "project_id": "search_project",
                            "source_authority_id": target_authority_id,
                            "relation_label": "dependió de",
                            "target_authority_id": source_authority_id,
                            "target_archival_unit_id": None,
                            "target_document_part_id": None,
                            "evidence_note": "Documento, página 1",
                            "lifecycle_status": "active",
                            "review_status": "approved",
                        }
                    ),
                    "now": now,
                },
            )
    finally:
        engine.dispose()

    upgrade_database(root)
    assert current_revision(root) == "0044_layout_structure_review"

    engine = create_sqlite_engine(database_path(root))
    try:
        with engine.connect() as connection:
            mention = connection.exec_driver_sql(
                "SELECT authority_id, status FROM entity_mentions WHERE id = ?",
                (mention_id,),
            ).one()
            relation = connection.exec_driver_sql(
                """
                SELECT source_authority_id, target_authority_id,
                       lifecycle_status, review_status
                FROM entity_relations
                WHERE id = ?
                """,
                (relation_id,),
            ).one()
            counts = {
                table: connection.exec_driver_sql(
                    f"SELECT COUNT(*) FROM {table}"
                ).scalar_one()
                for table in (
                    "authority_records",
                    "authority_aliases",
                    "authority_revisions",
                    "entity_mentions",
                    "entity_mention_revisions",
                    "entity_relations",
                    "entity_relation_revisions",
                )
            }
            foreign_key_errors = connection.exec_driver_sql(
                "PRAGMA foreign_key_check"
            ).all()
    finally:
        engine.dispose()

    assert mention == (source_authority_id, "accepted")
    assert relation == (
        target_authority_id,
        source_authority_id,
        "active",
        "approved",
    )
    assert counts == {
        "authority_records": 2,
        "authority_aliases": 1,
        "authority_revisions": 1,
        "entity_mentions": 1,
        "entity_mention_revisions": 1,
        "entity_relations": 1,
        "entity_relation_revisions": 1,
    }
    assert foreign_key_errors == []


def test_candidate_history_migration_preserves_populated_0331_database(tmp_path: Path) -> None:
    from sqlalchemy import select, text

    from archive_workbench.db.models import (
        DigitalObject,
        EditableObject,
        EditablePage,
        EditablePageRevision,
        ExtractionPage,
        ExtractionPageSelection,
        ExtractionPageSelectionRevision,
        ExtractionRun,
    )
    from archive_workbench.identity import new_id
    from tests.test_search import _seed_search_project

    root = tmp_path / "project"
    object_id, page_id = _seed_search_project(
        root, revision="0028_operational_readiness"
    )
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            digital_id = session.scalar(text("SELECT id FROM digital_objects LIMIT 1"))
            run_id = session.scalar(text("SELECT id FROM extraction_runs LIMIT 1"))
            extraction_page_id = session.scalar(
                text("SELECT id FROM extraction_pages LIMIT 1")
            )
            assert digital_id and run_id and extraction_page_id
            selection_id = new_id()
            session.execute(
                text(
                    """
                    INSERT INTO extraction_page_selections (
                        id, digital_object_id, page_number, extraction_run_id,
                        extraction_page_id, selected_by, note, selected_at
                    ) VALUES (
                        :id, :digital_object_id, 1, :run_id,
                        :page_id, 'tests', 'selección 0.33.1', CURRENT_TIMESTAMP
                    )
                    """
                ),
                {
                    "id": selection_id,
                    "digital_object_id": digital_id,
                    "run_id": run_id,
                    "page_id": extraction_page_id,
                },
            )
            session.execute(
                text(
                    "UPDATE editable_pages SET source_selection_id = :selection_id "
                    "WHERE id = :page_id"
                ),
                {"selection_id": selection_id, "page_id": page_id},
            )
    finally:
        engine.dispose()

    upgrade_database(root)
    assert current_revision(root) == "0044_layout_structure_review"
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            page = session.get(EditablePage, page_id)
            obj = session.get(EditableObject, object_id)
            selection = session.get(ExtractionPageSelection, selection_id)
            assert page is not None and page.revision_number == 1
            assert obj is not None and obj.editable_page_id == page_id
            assert selection is not None
            page_revision = session.scalar(
                select(EditablePageRevision).where(
                    EditablePageRevision.editable_page_id == page_id
                )
            )
            selection_revision = session.scalar(
                select(ExtractionPageSelectionRevision).where(
                    ExtractionPageSelectionRevision.selection_id == selection_id
                )
            )
            assert page_revision is not None and page_revision.operation == "import"
            assert selection_revision is not None and selection_revision.operation == "import"
    finally:
        engine.dispose()


def test_require_current_database_rejects_outdated_schema_without_migrating(tmp_path: Path) -> None:
    import pytest
    from archive_workbench.db import DatabaseRevisionError, require_current_database

    root = tmp_path / "project"
    upgrade_database(root, revision="0030_source_replaced_exchange")

    with pytest.raises(DatabaseRevisionError, match="No se aplicó ninguna migración"):
        require_current_database(root)

    assert current_revision(root) == "0030_source_replaced_exchange"


def test_page_quality_migration_from_0031_is_explicit_and_empty(tmp_path: Path) -> None:
    from sqlalchemy import inspect, text
    from typer.testing import CliRunner
    from archive_workbench.cli import app

    root = tmp_path / "project"
    upgrade_database(root, revision="0031_page_action_exchange")
    assert current_revision(root) == "0031_page_action_exchange"

    status = CliRunner().invoke(app, ["db-status", str(root)])
    assert status.exit_code == 0, status.output
    assert "Revisión: 0031_page_action_exchange" in status.output
    assert current_revision(root) == "0031_page_action_exchange"

    upgrade_database(root)
    assert current_revision(root) == "0044_layout_structure_review"
    engine = create_sqlite_engine(database_path(root))
    try:
        assert "extraction_page_quality_assessments" in inspect(engine).get_table_names()
        with session_scope(engine) as session:
            count = session.execute(
                text("SELECT COUNT(*) FROM extraction_page_quality_assessments")
            ).scalar_one()
            assert count == 0
    finally:
        engine.dispose()


def test_export_exchange_lifecycle_migration_upgrades_existing_0032_database(
    tmp_path: Path,
) -> None:
    from sqlalchemy import inspect

    root = tmp_path / "project"
    upgrade_database(root, revision="0032_page_quality_assessments")
    assert current_revision(root) == "0032_page_quality_assessments"

    engine = create_sqlite_engine(database_path(root))
    try:
        inspector = inspect(engine)
        assert "lifecycle_status" not in {
            row["name"] for row in inspector.get_columns("corpus_export_profiles")
        }
        assert "lifecycle_status" not in {
            row["name"] for row in inspector.get_columns("exchange_dry_runs")
        }
        with engine.begin() as connection:
            connection.exec_driver_sql(
                """
                INSERT INTO projects (
                    id, name, decisions_schema_version, decisions_json,
                    created_at, updated_at
                ) VALUES (
                    'migration_project', 'Migración', '1', '{}',
                    CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                )
                """
            )
            connection.exec_driver_sql(
                """
                INSERT INTO corpus_export_profiles (
                    id, project_id, name, aggregation_level, text_policy,
                    created_by, created_at, updated_by, updated_at
                ) VALUES (
                    'profile-0032', 'migration_project', 'Perfil previo',
                    'document', 'corrected_fallback_original',
                    'tests', CURRENT_TIMESTAMP, 'tests', CURRENT_TIMESTAMP
                )
                """
            )
            connection.exec_driver_sql(
                """
                INSERT INTO exchange_workspaces (
                    id, project_id, workspace_name, created_by,
                    created_at, updated_at
                ) VALUES (
                    'workspace-0032', 'migration_project', 'copia-previa',
                    'tests', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                )
                """
            )
            connection.exec_driver_sql(
                """
                INSERT INTO exchange_bundle_records (
                    id, workspace_id, bundle_id, direction, bundle_sha256,
                    relative_path, base_sequence, last_sequence, event_count,
                    status, created_by, created_at
                ) VALUES (
                    'record-0032', 'workspace-0032',
                    '00000000-0000-0000-0000-000000000032', 'incoming',
                    'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
                    'exchange/incoming/previo.zip', 0, 1, 1,
                    'assessed', 'tests', CURRENT_TIMESTAMP
                )
                """
            )
            connection.exec_driver_sql(
                """
                INSERT INTO exchange_dry_runs (
                    id, workspace_id, bundle_record_id, bundle_id,
                    source_workspace_id, source_workspace_name,
                    base_match_status, overall_status, counts_json, warnings_json,
                    assessed_by, assessed_at, assessed_state_sha256,
                    assessed_sequence_number
                ) VALUES (
                    'dry-0032', 'workspace-0032', 'record-0032',
                    '00000000-0000-0000-0000-000000000032',
                    'source-0032', 'origen-previo', 'matched', 'ready_to_apply',
                    '{"apply": 1, "duplicate": 0, "review": 0, "conflict": 0}',
                    '[]', 'tests', CURRENT_TIMESTAMP,
                    'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb', 0
                )
                """
            )
    finally:
        engine.dispose()

    upgrade_database(root)
    assert current_revision(root) == "0044_layout_structure_review"

    engine = create_sqlite_engine(database_path(root))
    try:
        inspector = inspect(engine)
        profile_columns = {
            row["name"]: row for row in inspector.get_columns("corpus_export_profiles")
        }
        dry_run_columns = {
            row["name"]: row for row in inspector.get_columns("exchange_dry_runs")
        }
        profile_indexes = {
            row["name"] for row in inspector.get_indexes("corpus_export_profiles")
        }
        dry_run_indexes = {
            row["name"] for row in inspector.get_indexes("exchange_dry_runs")
        }
        with engine.connect() as connection:
            profile_row = connection.exec_driver_sql(
                "SELECT name, lifecycle_status FROM corpus_export_profiles "
                "WHERE id = 'profile-0032'"
            ).one()
            dry_run_row = connection.exec_driver_sql(
                "SELECT source_workspace_name, lifecycle_status, archive_note "
                "FROM exchange_dry_runs WHERE id = 'dry-0032'"
            ).one()
    finally:
        engine.dispose()

    assert {"lifecycle_status", "archived_by", "archived_at"} <= set(
        profile_columns
    )
    assert {
        "lifecycle_status",
        "archived_by",
        "archived_at",
        "archive_note",
    } <= set(dry_run_columns)
    assert profile_columns["lifecycle_status"]["nullable"] is False
    assert dry_run_columns["lifecycle_status"]["nullable"] is False
    assert "active" in str(profile_columns["lifecycle_status"]["default"])
    assert "active" in str(dry_run_columns["lifecycle_status"]["default"])
    assert "ix_corpus_export_profiles_lifecycle" in profile_indexes
    assert "ix_exchange_dry_runs_lifecycle" in dry_run_indexes
    assert profile_row == ("Perfil previo", "active")
    assert dry_run_row == ("origen-previo", "active", None)


def test_analysis_authorization_migration_upgrades_existing_0033_database(
    tmp_path: Path,
) -> None:
    from sqlalchemy import inspect, text

    root = tmp_path / "project"
    upgrade_database(root, revision="0033_export_exchange_lifecycle")
    assert current_revision(root) == "0033_export_exchange_lifecycle"

    engine = create_sqlite_engine(database_path(root))
    try:
        assert "automatic_analysis_authorizations" not in inspect(engine).get_table_names()
        with engine.begin() as connection:
            connection.exec_driver_sql(
                """
                INSERT INTO projects (
                    id, name, decisions_schema_version, decisions_json,
                    created_at, updated_at
                ) VALUES (
                    'analysis-migration-project', 'Migración de análisis', '1', '{}',
                    CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                )
                """
            )
            connection.exec_driver_sql(
                """
                INSERT INTO corpus_export_profiles (
                    id, project_id, name, aggregation_level, text_policy,
                    output_format, include_page_review_statuses_json,
                    lifecycle_status, created_by, created_at, updated_by, updated_at
                ) VALUES (
                    'profile-before-0034', 'analysis-migration-project',
                    'Perfil anterior', 'document', 'corrected_fallback_original',
                    'jsonl', '[\"approved\"]', 'active',
                    'tests', CURRENT_TIMESTAMP, 'tests', CURRENT_TIMESTAMP
                )
                """
            )
    finally:
        engine.dispose()

    upgrade_database(root)
    assert current_revision(root) == "0044_layout_structure_review"

    engine = create_sqlite_engine(database_path(root))
    try:
        inspector = inspect(engine)
        assert "automatic_analysis_authorizations" in inspector.get_table_names()
        columns = {
            row["name"]: row
            for row in inspector.get_columns("automatic_analysis_authorizations")
        }
        assert {
            "id",
            "project_id",
            "policy_version",
            "analysis_kind",
            "page_review_statuses_json",
            "scope_key",
            "broader_scope_confirmed",
            "confirmed_by",
            "confirmation_reason",
            "source",
            "target_type",
            "target_id",
            "parameters_sha256",
            "created_at",
        } <= set(columns)
        with engine.connect() as connection:
            profile = connection.exec_driver_sql(
                "SELECT name, include_page_review_statuses_json "
                "FROM corpus_export_profiles WHERE id = 'profile-before-0034'"
            ).one()
            authorization_count = connection.exec_driver_sql(
                "SELECT COUNT(*) FROM automatic_analysis_authorizations"
            ).scalar_one()
            integrity = connection.execute(text("PRAGMA integrity_check")).scalar_one()
            foreign_keys = connection.execute(text("PRAGMA foreign_key_check")).all()
    finally:
        engine.dispose()

    assert profile == ("Perfil anterior", '["approved"]')
    assert authorization_count == 0
    assert integrity == "ok"
    assert foreign_keys == []


def test_lineage_recovery_migration_upgrades_existing_0034_database(
    tmp_path: Path,
) -> None:
    from sqlalchemy import inspect, text

    root = tmp_path / "project"
    upgrade_database(root, revision="0034_automatic_analysis_authorizations")
    assert current_revision(root) == "0034_automatic_analysis_authorizations"

    engine = create_sqlite_engine(database_path(root))
    try:
        inspector = inspect(engine)
        assert "exchange_lineage_cases" not in inspector.get_table_names()
        assert "base_match_method" not in {
            row["name"] for row in inspector.get_columns("exchange_dry_runs")
        }
        with engine.begin() as connection:
            connection.exec_driver_sql(
                """
                INSERT INTO projects (
                    id, name, decisions_schema_version, decisions_json,
                    created_at, updated_at
                ) VALUES (
                    'lineage-migration-project', 'Migración de linaje', '1', '{}',
                    CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                )
                """
            )
            connection.exec_driver_sql(
                """
                INSERT INTO exchange_workspaces (
                    id, project_id, workspace_name, created_by, created_at, updated_at
                ) VALUES (
                    'workspace-before-0035', 'lineage-migration-project',
                    'Copia previa', 'tests', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                )
                """
            )
            connection.exec_driver_sql(
                """
                INSERT INTO exchange_bundle_records (
                    id, workspace_id, bundle_id, direction, bundle_sha256,
                    relative_path, base_sequence, last_sequence, event_count,
                    status, counterpart_workspace_id, created_by, created_at
                ) VALUES (
                    'record-before-0035', 'workspace-before-0035',
                    'bundle-before-0035', 'incoming',
                    'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
                    'exchange/incoming/prior.zip', 0, 1, 1,
                    'assessed', 'remote-before-0035', 'tests', CURRENT_TIMESTAMP
                )
                """
            )
            connection.exec_driver_sql(
                """
                INSERT INTO exchange_dry_runs (
                    id, workspace_id, bundle_record_id, bundle_id,
                    source_workspace_id, source_workspace_name,
                    common_checkpoint_id, common_checkpoint_label,
                    common_checkpoint_sequence, base_match_status,
                    overall_status, counts_json, warnings_json,
                    report_json_path, report_markdown_path,
                    assessed_state_sha256, assessed_sequence_number,
                    assessed_by, assessed_at, lifecycle_status,
                    archived_by, archived_at, archive_note
                ) VALUES (
                    'dry-before-0035', 'workspace-before-0035',
                    'record-before-0035', 'bundle-before-0035',
                    'remote-before-0035', 'Copia remota',
                    NULL, NULL, NULL, 'unmatched',
                    'needs_review', '{}', '[]',
                    NULL, NULL, NULL, 0,
                    'tests', CURRENT_TIMESTAMP, 'active',
                    NULL, NULL, NULL
                )
                """
            )
    finally:
        engine.dispose()

    upgrade_database(root)
    assert current_revision(root) == "0044_layout_structure_review"

    engine = create_sqlite_engine(database_path(root))
    try:
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
        assert {
            "exchange_lineage_cases",
            "exchange_lineage_evidence",
            "exchange_lineage_decisions",
        } <= tables
        dry_columns = {
            row["name"]: row for row in inspector.get_columns("exchange_dry_runs")
        }
        assert "base_match_method" in dry_columns
        assert dry_columns["base_match_method"]["nullable"] is False
        with engine.connect() as connection:
            preserved = connection.exec_driver_sql(
                """
                SELECT source_workspace_name, base_match_status, base_match_method
                FROM exchange_dry_runs WHERE id = 'dry-before-0035'
                """
            ).one()
            counts = {
                table: connection.exec_driver_sql(
                    f'SELECT COUNT(*) FROM "{table}"'
                ).scalar_one()
                for table in (
                    "exchange_lineage_cases",
                    "exchange_lineage_evidence",
                    "exchange_lineage_decisions",
                )
            }
            integrity = connection.execute(text("PRAGMA integrity_check")).scalar_one()
            foreign_keys = connection.execute(text("PRAGMA foreign_key_check")).all()
    finally:
        engine.dispose()

    assert preserved == ("Copia remota", "unmatched", "unknown")
    assert counts == {
        "exchange_lineage_cases": 0,
        "exchange_lineage_evidence": 0,
        "exchange_lineage_decisions": 0,
    }
    assert integrity == "ok"
    assert foreign_keys == []


def test_common_base_migration_upgrades_existing_0035_database(tmp_path: Path) -> None:
    from sqlalchemy import inspect

    root = tmp_path / "project_common_base"
    upgrade_database(root, revision="0035_exchange_lineage_recovery")
    assert current_revision(root) == "0035_exchange_lineage_recovery"
    upgrade_database(root)
    assert current_revision(root) == "0044_layout_structure_review"
    engine = create_sqlite_engine(database_path(root))
    try:
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
        columns = {
            row["name"]
            for row in inspector.get_columns("exchange_common_base_agreements")
        }
    finally:
        engine.dispose()
    assert "exchange_common_base_agreements" in tables
    assert {
        "agreement_id",
        "local_workspace_id",
        "counterpart_workspace_id",
        "state_sha256",
        "local_checkpoint_id",
        "manifest_sha256",
        "proposal_sha256",
        "registered_by",
        "registration_reason",
    } <= columns


def test_state_adoption_migration_upgrades_existing_0036_database(
    tmp_path: Path,
) -> None:
    from sqlalchemy import inspect, text

    root = tmp_path / "project_state_adoption"
    upgrade_database(root, revision="0036_exchange_common_base_agreements")
    assert current_revision(root) == "0036_exchange_common_base_agreements"
    upgrade_database(root)
    assert current_revision(root) == "0044_layout_structure_review"

    engine = create_sqlite_engine(database_path(root))
    try:
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
        adoption_columns = {
            row["name"] for row in inspector.get_columns("exchange_state_adoptions")
        }
        rollback_columns = {
            row["name"]
            for row in inspector.get_columns("exchange_state_adoption_rollbacks")
        }
        with engine.connect() as connection:
            integrity = connection.execute(text("PRAGMA integrity_check")).scalar_one()
            foreign_keys = connection.execute(text("PRAGMA foreign_key_check")).all()
    finally:
        engine.dispose()

    assert {
        "exchange_state_adoptions",
        "exchange_state_adoption_rollbacks",
    } <= tables
    assert {
        "adoption_id",
        "previous_state_sha256",
        "adopted_state_sha256",
        "backup_path",
        "backup_sha256",
        "impact_json",
        "parameters_sha256",
    } <= adoption_columns
    assert {
        "adoption_record_id",
        "restored_state_sha256",
        "safety_backup_path",
        "rollback_reason",
        "parameters_sha256",
    } <= rollback_columns
    assert integrity == "ok"
    assert foreign_keys == []


def test_open_discovery_migration_upgrades_existing_0037_database(tmp_path: Path) -> None:
    from sqlalchemy import inspect, text

    root = tmp_path / "project_open_discovery"
    upgrade_database(root, revision="0037_exchange_state_adoptions")
    assert current_revision(root) == "0037_exchange_state_adoptions"
    upgrade_database(root)
    assert current_revision(root) == "0044_layout_structure_review"

    engine = create_sqlite_engine(database_path(root))
    try:
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
        profile_columns = {
            row["name"] for row in inspector.get_columns("discovery_profiles")
        }
        run_columns = {row["name"] for row in inspector.get_columns("discovery_runs")}
        candidate_columns = {
            row["name"] for row in inspector.get_columns("discovery_candidates")
        }
        with engine.connect() as connection:
            counts = {
                table: connection.exec_driver_sql(
                    f'SELECT COUNT(*) FROM "{table}"'
                ).scalar_one()
                for table in (
                    "discovery_profiles",
                    "discovery_runs",
                    "discovery_candidates",
                )
            }
            integrity = connection.execute(text("PRAGMA integrity_check")).scalar_one()
            foreign_keys = connection.execute(text("PRAGMA foreign_key_check")).all()
    finally:
        engine.dispose()

    assert {"discovery_profiles", "discovery_runs", "discovery_candidates"} <= tables
    assert {
        "provider_key",
        "provider_version",
        "families_json",
        "include_page_review_statuses_json",
        "minimum_confidence",
        "revision",
    } <= profile_columns
    assert {
        "authorization_id",
        "profile_snapshot_json",
        "parameters_sha256",
        "corpus_state_sha256",
        "family_counts_json",
    } <= run_columns
    assert {
        "editable_object_id",
        "object_revision_number",
        "start_offset",
        "end_offset",
        "exact_text",
        "semantic_family",
        "suggested_subtype",
        "provider_version",
        "explanation",
    } <= candidate_columns
    assert counts == {
        "discovery_profiles": 0,
        "discovery_runs": 0,
        "discovery_candidates": 0,
    }
    assert integrity == "ok"
    assert foreign_keys == []


def test_discovery_decisions_migration_upgrades_existing_0038_database(
    tmp_path: Path,
) -> None:
    from sqlalchemy import inspect, text

    root = tmp_path / "project_discovery_decisions"
    upgrade_database(root, revision="0038_open_discovery")
    assert current_revision(root) == "0038_open_discovery"
    upgrade_database(root)
    assert current_revision(root) == "0044_layout_structure_review"

    engine = create_sqlite_engine(database_path(root))
    try:
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
        decision_columns = {
            row["name"] for row in inspector.get_columns("discovery_decisions")
        }
        context_columns = {
            row["name"]
            for row in inspector.get_columns("discovery_context_records")
        }
        with engine.connect() as connection:
            counts = {
                table: connection.exec_driver_sql(
                    f'SELECT COUNT(*) FROM "{table}"'
                ).scalar_one()
                for table in (
                    "discovery_decisions",
                    "discovery_context_records",
                )
            }
            integrity = connection.execute(text("PRAGMA integrity_check")).scalar_one()
            foreign_keys = connection.execute(text("PRAGMA foreign_key_check")).all()
    finally:
        engine.dispose()

    assert {"discovery_decisions", "discovery_context_records"} <= tables
    assert {
        "candidate_id",
        "decision_number",
        "decision_type",
        "reviewed_text",
        "semantic_family",
        "reviewed_subtype",
        "acceptance_mode",
        "target_authority_id",
        "created_mention_id",
        "candidate_state_sha256",
        "decided_by",
    } <= decision_columns
    assert {
        "candidate_id",
        "decision_id",
        "semantic_family",
        "subtype",
        "label",
        "temporal_expression",
        "editable_object_id",
        "object_revision_number",
        "target_authority_id",
        "data_json",
    } <= context_columns
    assert counts == {
        "discovery_decisions": 0,
        "discovery_context_records": 0,
    }
    assert integrity == "ok"
    assert foreign_keys == []


def test_discovery_grouping_continuity_migration_upgrades_existing_0039_database(
    tmp_path: Path,
) -> None:
    from sqlalchemy import inspect, text

    root = tmp_path / "project_discovery_grouping"
    upgrade_database(root, revision="0039_discovery_decisions")
    assert current_revision(root) == "0039_discovery_decisions"
    upgrade_database(root)
    assert current_revision(root) == "0044_layout_structure_review"

    engine = create_sqlite_engine(database_path(root))
    try:
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
        with engine.connect() as connection:
            counts = {
                table: connection.exec_driver_sql(
                    f'SELECT COUNT(*) FROM "{table}"'
                ).scalar_one()
                for table in (
                    "discovery_candidate_groups",
                    "discovery_group_memberships",
                    "discovery_group_actions",
                    "discovery_candidate_continuities",
                )
            }
            integrity = connection.execute(text("PRAGMA integrity_check")).scalar_one()
            foreign_keys = connection.execute(text("PRAGMA foreign_key_check")).all()
    finally:
        engine.dispose()

    assert {
        "discovery_candidate_groups",
        "discovery_group_memberships",
        "discovery_group_actions",
        "discovery_candidate_continuities",
    } <= tables
    assert counts == {
        "discovery_candidate_groups": 0,
        "discovery_group_memberships": 0,
        "discovery_group_actions": 0,
        "discovery_candidate_continuities": 0,
    }
    assert integrity == "ok"
    assert foreign_keys == []


def test_catalog_authority_roles_migration_preserves_relations_and_enforces_contract(
    tmp_path: Path,
) -> None:
    from sqlalchemy import inspect, text
    from sqlalchemy.exc import IntegrityError

    from archive_workbench.db.models import ArchivalUnit, AuthorityRecord, Project

    root = tmp_path / "project_catalog_roles"
    upgrade_database(root, revision="0040_discovery_grouping_continuity")
    assert current_revision(root) == "0040_discovery_grouping_continuity"

    engine = create_sqlite_engine(database_path(root))
    try:
        now = datetime.now(timezone.utc)
        with session_scope(engine) as session:
            session.add(
                Project(
                    id="catalog_roles_project",
                    name="Catalog roles",
                    decisions_json={},
                )
            )
            session.flush()
            session.add(
                AuthorityRecord(
                    id="authority-producer",
                    project_id="catalog_roles_project",
                    entity_type="organization",
                    preferred_name="Organismo productor",
                    normalized_name="organismo productor",
                    lifecycle_status="active",
                    review_status="approved",
                    created_by="tests",
                    created_at=now,
                    updated_by="tests",
                    updated_at=now,
                    revision=1,
                )
            )
            session.add(
                ArchivalUnit(
                    id="unit-role-target",
                    project_id="catalog_roles_project",
                    level_key="fondo",
                    title="Fondo de prueba",
                    registration_status="complete",
                    created_by="tests",
                    created_at=now,
                    updated_by="tests",
                    updated_at=now,
                    revision=1,
                )
            )
            session.flush()
            session.execute(
                text(
                    """
                    INSERT INTO entity_relations (
                        id, project_id, source_authority_id, relation_label,
                        target_authority_id, target_archival_unit_id, target_document_part_id,
                        evidence_note, temporal_expression, temporal_start, temporal_end,
                        temporal_precision, temporal_approximate, temporal_note,
                        lifecycle_status, review_status, created_by, created_at,
                        updated_by, updated_at, revision
                    ) VALUES (
                        'legacy-relation', 'catalog_roles_project', 'authority-producer',
                        'custodió', NULL, 'unit-role-target', NULL,
                        'Inventario previo', NULL, NULL, NULL,
                        NULL, 0, NULL, 'active', 'approved', 'tests', :now,
                        'tests', :now, 1
                    )
                    """
                ),
                {"now": now},
            )
    finally:
        engine.dispose()

    upgrade_database(root)
    assert current_revision(root) == "0044_layout_structure_review"

    engine = create_sqlite_engine(database_path(root))
    try:
        inspector = inspect(engine)
        relation_columns = {row["name"] for row in inspector.get_columns("entity_relations")}
        relation_indexes = {row["name"] for row in inspector.get_indexes("entity_relations")}
        with engine.connect() as connection:
            legacy = connection.execute(
                text(
                    "SELECT relation_kind, provenance_note FROM entity_relations "
                    "WHERE id = 'legacy-relation'"
                )
            ).one()
            integrity = connection.execute(text("PRAGMA integrity_check")).scalar_one()
            foreign_keys = connection.execute(text("PRAGMA foreign_key_check")).all()
        assert legacy.relation_kind == "analytical"
        assert legacy.provenance_note is None
        assert {"relation_kind", "provenance_note"} <= relation_columns
        assert "ix_entity_relations_project_kind_target_unit" in relation_indexes
        assert integrity == "ok"
        assert foreign_keys == []

        with engine.begin() as connection:
            try:
                connection.execute(
                    text(
                        """
                        INSERT INTO entity_relations (
                            id, project_id, source_authority_id, relation_kind, relation_label,
                            target_archival_unit_id, evidence_note, provenance_note,
                            lifecycle_status, review_status, created_by, created_at,
                            updated_by, updated_at, revision
                        ) VALUES (
                            'invalid-role', 'catalog_roles_project', 'authority-producer',
                            'producer', 'nombre libre', 'unit-role-target',
                            'Inventario', 'Guía', 'active', 'approved', 'tests', :now,
                            'tests', :now, 1
                        )
                        """
                    ),
                    {"now": now},
                )
            except IntegrityError:
                pass
            else:
                raise AssertionError("La base aceptó un rol archivístico con etiqueta no canónica")

        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO entity_relations (
                        id, project_id, source_authority_id, relation_kind, relation_label,
                        target_archival_unit_id, evidence_note, provenance_note,
                        lifecycle_status, review_status, created_by, created_at,
                        updated_by, updated_at, revision
                    ) VALUES (
                        'valid-role', 'catalog_roles_project', 'authority-producer',
                        'producer', 'produjo', 'unit-role-target',
                        'Inventario', 'Guía', 'active', 'approved', 'tests', :now,
                        'tests', :now, 1
                    )
                    """
                ),
                {"now": now},
            )
    finally:
        engine.dispose()


def test_preprocessing_geometry_migration_preserves_existing_derivative_assets(
    tmp_path: Path,
) -> None:
    from datetime import datetime, timezone

    from sqlalchemy import inspect, text

    root = tmp_path / "project"
    _write_pdf(root / "corpus/caja/a.pdf")
    decisions = load_decisions(Path(__file__).parents[1] / "config/decisions.yaml")
    corpus = _corpus()

    upgrade_database(root, revision="0041_catalog_authority_roles_graph_layers")
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            register_test_corpus(
                session,
                project_root=root,
                decisions=decisions,
                corpus=corpus,
            )
        now = datetime.now(timezone.utc).isoformat()
        with engine.begin() as connection:
            digital_object_id = connection.execute(
                text("SELECT id FROM digital_objects LIMIT 1")
            ).scalar_one()
            connection.execute(
                text(
                    """
                    INSERT INTO preprocessing_runs (
                        id, digital_object_id, source_sha256, profile_key,
                        options_json, options_hash, backend, backend_version,
                        status, is_current, output_root, manifest_path,
                        warnings_json, created_at, completed_at
                    ) VALUES (
                        'legacy-run', :digital_object_id,
                        (SELECT sha256 FROM digital_objects WHERE id = :digital_object_id),
                        'default', '{}', :options_hash, 'pillow', NULL,
                        'completed', 1, 'derivatives/legacy', NULL,
                        '[]', :now, :now
                    )
                    """
                ),
                {
                    "digital_object_id": digital_object_id,
                    "options_hash": "0" * 64,
                    "now": now,
                },
            )
            connection.execute(
                text(
                    """
                    INSERT INTO derivative_assets (
                        id, preprocessing_run_id, digital_object_id, page_number,
                        kind, relative_path, mime_type, sha256, byte_size,
                        width, height, dpi, source_width, source_height,
                        source_dpi, rotation_applied, backend, created_at
                    ) VALUES (
                        'legacy-asset', 'legacy-run', :digital_object_id, 1,
                        'ocr', 'derivatives/legacy/page.png', 'image/png',
                        :sha256, 10, 100, 200, 300, 100, 200, 300, 0,
                        'pillow', :now
                    )
                    """
                ),
                {
                    "digital_object_id": digital_object_id,
                    "sha256": "1" * 64,
                    "now": now,
                },
            )
    finally:
        engine.dispose()

    upgrade_database(root)
    assert current_revision(root) == "0044_layout_structure_review"
    engine = create_sqlite_engine(database_path(root))
    try:
        columns = {
            item["name"] for item in inspect(engine).get_columns("derivative_assets")
        }
        with engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT analysis_json, transformations_json "
                    "FROM derivative_assets WHERE id = 'legacy-asset'"
                )
            ).one()
    finally:
        engine.dispose()

    assert {"analysis_json", "transformations_json"} <= columns
    assert row.analysis_json == "{}"
    assert row.transformations_json == "{}"


def test_form_structure_migration_preserves_editable_pages_and_revision_history(
    tmp_path: Path,
) -> None:
    from sqlalchemy import inspect, text

    root = tmp_path / "project"
    _write_pdf(root / "corpus/caja/a.pdf")
    decisions = load_decisions(Path(__file__).parents[1] / "config/decisions.yaml")
    corpus = _corpus()

    upgrade_database(root, revision="0042_preprocessing_geometry_trace")
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            register_test_corpus(
                session,
                project_root=root,
                decisions=decisions,
                corpus=corpus,
            )
        now = datetime.now(timezone.utc).isoformat()
        with engine.begin() as connection:
            digital = connection.execute(
                text("SELECT id, sha256 FROM digital_objects LIMIT 1")
            ).one()
            connection.execute(
                text(
                    """
                    INSERT INTO extraction_runs (
                        id, digital_object_id, engine, source_sha256, options_hash,
                        status, is_current, warnings_json, created_at,
                        total_pages, total_objects, total_paragraphs,
                        total_characters, quality_status
                    ) VALUES (
                        'legacy-form-run', :digital_object_id, 'tesseract_tsv',
                        :source_sha256, :options_hash, 'completed', 1, '[]', :now,
                        1, 0, 0, 0, 'needs_review'
                    )
                    """
                ),
                {
                    "digital_object_id": digital.id,
                    "source_sha256": digital.sha256,
                    "options_hash": "2" * 64,
                    "now": now,
                },
            )
            connection.execute(
                text(
                    """
                    INSERT INTO extraction_pages (
                        id, extraction_run_id, page_number, object_count,
                        character_count, status, created_at
                    ) VALUES (
                        'legacy-form-extraction-page', 'legacy-form-run', 1,
                        0, 0, 'completed', :now
                    )
                    """
                ),
                {"now": now},
            )
            connection.execute(
                text(
                    """
                    INSERT INTO editable_pages (
                        id, digital_object_id, page_number,
                        source_extraction_run_id, source_extraction_page_id,
                        status, bootstrapped_by, bootstrapped_at, updated_at,
                        review_status, revision_number
                    ) VALUES (
                        'legacy-editable-page', :digital_object_id, 1,
                        'legacy-form-run', 'legacy-form-extraction-page',
                        'active', 'tests', :now, :now, 'unreviewed', 1
                    )
                    """
                ),
                {"digital_object_id": digital.id, "now": now},
            )
            connection.execute(
                text(
                    """
                    INSERT INTO editable_page_revisions (
                        id, editable_page_id, revision_number,
                        base_revision_number, operation,
                        source_extraction_run_id, source_extraction_page_id,
                        status, review_status, details_json,
                        created_by, created_at
                    ) VALUES (
                        'legacy-editable-page-revision', 'legacy-editable-page', 1,
                        NULL, 'import', 'legacy-form-run',
                        'legacy-form-extraction-page', 'active', 'unreviewed',
                        '{}', 'tests', :now
                    )
                    """
                ),
                {"now": now},
            )
    finally:
        engine.dispose()

    upgrade_database(root)
    assert current_revision(root) == "0044_layout_structure_review"

    engine = create_sqlite_engine(database_path(root))
    try:
        inspector = inspect(engine)
        page_columns = {
            item["name"] for item in inspector.get_columns("editable_pages")
        }
        revision_columns = {
            item["name"]
            for item in inspector.get_columns("editable_page_revisions")
        }
        triggers = {
            row[0]
            for row in engine.connect().execute(
                text(
                    "SELECT name FROM sqlite_master "
                    "WHERE type = 'trigger' AND name = "
                    "'trg_exchange_page_form_structure_au'"
                )
            )
        }
        with engine.connect() as connection:
            page_value = connection.execute(
                text(
                    "SELECT form_structure_json FROM editable_pages "
                    "WHERE id = 'legacy-editable-page'"
                )
            ).scalar_one()
            revision_value = connection.execute(
                text(
                    "SELECT form_structure_json FROM editable_page_revisions "
                    "WHERE id = 'legacy-editable-page-revision'"
                )
            ).scalar_one()
            integrity = connection.execute(text("PRAGMA integrity_check")).scalar_one()
            foreign_keys = connection.execute(text("PRAGMA foreign_key_check")).all()
    finally:
        engine.dispose()

    assert "form_structure_json" in page_columns
    assert "form_structure_json" in revision_columns
    assert page_value == "{}"
    assert revision_value == "{}"
    assert triggers == {"trg_exchange_page_form_structure_au"}
    assert integrity == "ok"
    assert foreign_keys == []


def test_layout_structure_migration_preserves_pages_and_adds_exchange_trigger(
    tmp_path: Path,
) -> None:
    from datetime import datetime, timezone
    from sqlalchemy import inspect, text

    root = tmp_path / "project"
    _write_pdf(root / "corpus/caja/a.pdf")
    decisions = load_decisions(Path(__file__).parents[1] / "config/decisions.yaml")
    upgrade_database(root, revision="0043_form_structure_review")
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            register_test_corpus(
                session,
                project_root=root,
                decisions=decisions,
                corpus=_corpus(),
            )
        now = datetime.now(timezone.utc).isoformat()
        with engine.begin() as connection:
            digital = connection.execute(
                text("SELECT id, sha256 FROM digital_objects LIMIT 1")
            ).one()
            connection.execute(
                text(
                    """
                    INSERT INTO extraction_runs (
                        id, digital_object_id, engine, source_sha256, options_hash,
                        status, is_current, warnings_json, created_at,
                        total_pages, total_objects, total_paragraphs,
                        total_characters, quality_status
                    ) VALUES (
                        'legacy-layout-run', :digital_object_id, 'tesseract_tsv',
                        :source_sha256, :options_hash, 'completed', 1, '[]', :now,
                        1, 0, 0, 0, 'needs_review'
                    )
                    """
                ),
                {
                    "digital_object_id": digital.id,
                    "source_sha256": digital.sha256,
                    "options_hash": "5" * 64,
                    "now": now,
                },
            )
            connection.execute(
                text(
                    """
                    INSERT INTO extraction_pages (
                        id, extraction_run_id, page_number, object_count,
                        character_count, status, created_at
                    ) VALUES (
                        'legacy-layout-extraction-page', 'legacy-layout-run', 1,
                        0, 0, 'completed', :now
                    )
                    """
                ),
                {"now": now},
            )
            connection.execute(
                text(
                    """
                    INSERT INTO editable_pages (
                        id, digital_object_id, page_number,
                        source_extraction_run_id, source_extraction_page_id,
                        status, bootstrapped_by, bootstrapped_at, updated_at,
                        review_status, revision_number, form_structure_json
                    ) VALUES (
                        'legacy-layout-page', :digital_object_id, 1,
                        'legacy-layout-run', 'legacy-layout-extraction-page',
                        'active', 'tests', :now, :now, 'unreviewed', 1, '{}'
                    )
                    """
                ),
                {"digital_object_id": digital.id, "now": now},
            )
            connection.execute(
                text(
                    """
                    INSERT INTO editable_page_revisions (
                        id, editable_page_id, revision_number,
                        base_revision_number, operation,
                        source_extraction_run_id, source_extraction_page_id,
                        status, review_status, form_structure_json, details_json,
                        created_by, created_at
                    ) VALUES (
                        'legacy-layout-page-revision', 'legacy-layout-page', 1,
                        NULL, 'import', 'legacy-layout-run',
                        'legacy-layout-extraction-page', 'active', 'unreviewed',
                        '{}', '{}', 'tests', :now
                    )
                    """
                ),
                {"now": now},
            )
    finally:
        engine.dispose()

    upgrade_database(root)
    assert current_revision(root) == "0044_layout_structure_review"
    engine = create_sqlite_engine(database_path(root))
    try:
        inspector = inspect(engine)
        page_columns = {row["name"] for row in inspector.get_columns("editable_pages")}
        revision_columns = {
            row["name"] for row in inspector.get_columns("editable_page_revisions")
        }
        with engine.connect() as connection:
            page_value = connection.execute(
                text(
                    "SELECT layout_structure_json FROM editable_pages "
                    "WHERE id = 'legacy-layout-page'"
                )
            ).scalar_one()
            revision_value = connection.execute(
                text(
                    "SELECT layout_structure_json FROM editable_page_revisions "
                    "WHERE id = 'legacy-layout-page-revision'"
                )
            ).scalar_one()
            trigger = connection.execute(
                text(
                    "SELECT name FROM sqlite_master WHERE type='trigger' "
                    "AND name='trg_exchange_page_layout_structure_au'"
                )
            ).scalar_one()
            integrity = connection.execute(text("PRAGMA integrity_check")).scalar_one()
            foreign_keys = connection.execute(text("PRAGMA foreign_key_check")).all()
    finally:
        engine.dispose()

    assert "layout_structure_json" in page_columns
    assert "layout_structure_json" in revision_columns
    assert page_value == "{}"
    assert revision_value == "{}"
    assert trigger == "trg_exchange_page_layout_structure_au"
    assert integrity == "ok"
    assert foreign_keys == []
