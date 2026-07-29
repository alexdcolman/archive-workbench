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
    assert current_revision(root) == "0028_operational_readiness"

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
    assert current_revision(root) == "0028_operational_readiness"
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
    assert {"review_status", "review_note", "reviewed_by", "reviewed_at"} <= editable_page_columns
    assert {"review_status", "document_part_id"} <= editable_object_columns
    assert "document_part_id" in editable_revision_columns
    assert "tag_kind" in editable_tag_columns


def test_temporal_migration_upgrades_existing_031_database(tmp_path: Path) -> None:
    from sqlalchemy import inspect

    root = tmp_path / "project"
    upgrade_database(root, revision="0026_team_workflow")
    assert current_revision(root) == "0026_team_workflow"
    upgrade_database(root)
    assert current_revision(root) == "0028_operational_readiness"
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
    assert current_revision(root) == "0028_operational_readiness"
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
    assert current_revision(root) == "0028_operational_readiness"

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
