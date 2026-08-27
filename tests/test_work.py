from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import fitz
import pytest
from sqlalchemy import inspect

from archive_workbench.catalog import register_test_corpus
from archive_workbench.contracts.test_corpus import TestCorpus as CorpusDefinition
from archive_workbench.db import (
    create_sqlite_engine,
    current_revision,
    database_path,
    session_scope,
    upgrade_database,
)
from archive_workbench.decisions import load_decisions
from archive_workbench.work import (
    create_cross_review_assignment,
    create_work_assignment,
    cross_review_candidate_rows,
    update_work_assignment,
    work_assignment_revision_rows,
    work_assignment_rows,
    workload_summary_rows,
)


def _write_pdf(path: Path, pages: int = 2) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = fitz.open()
    for number in range(1, pages + 1):
        page = doc.new_page(width=600, height=400)
        page.insert_text((50, 80), f"Documento página {number}")
    doc.save(path)
    doc.close()


def _corpus() -> CorpusDefinition:
    return CorpusDefinition.model_validate(
        {
            "corpus_name": "Trabajo",
            "created_by": "tests",
            "created_at": datetime.now(timezone.utc),
            "documents": [
                {
                    "test_id": "doc_work",
                    "local_path": "corpus/doc.pdf",
                    "short_description": "Documento de trabajo",
                    "archival_location": {
                        "fondo": "Fondo de prueba",
                        "legajo": "Legajo 1",
                        "documento": "Documento de trabajo",
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


def _seed(root: Path):
    _write_pdf(root / "corpus/doc.pdf")
    decisions = load_decisions(Path(__file__).parents[1] / "config/decisions.yaml")
    upgrade_database(root)
    engine = create_sqlite_engine(database_path(root))
    with session_scope(engine) as session:
        register_test_corpus(
            session,
            project_root=root,
            decisions=decisions,
            corpus=_corpus(),
        )
    return decisions, engine


def test_primary_and_cross_review_assignments_are_versioned(tmp_path: Path) -> None:
    root = tmp_path / "project"
    decisions, engine = _seed(root)
    try:
        with session_scope(engine) as session:
            primary = create_work_assignment(
                session,
                project_id=decisions.project_id,
                source_type="test_corpus",
                source_key="doc_work",
                page_start=1,
                page_end=2,
                assignment_kind="primary_review",
                assignee="Alex",
                created_by="Alex",
                priority="high",
                note="Primera revisión",
            )
            update_work_assignment(
                session,
                assignment_id=primary.id,
                expected_revision=1,
                changed_by="Alex",
                status="submitted",
                change_note="Revisión enviada",
            )
            primary_id = primary.id
        with session_scope(engine) as session:
            cross = create_cross_review_assignment(
                session,
                primary_assignment_id=primary_id,
                assignee="María",
                created_by="Alex",
            )
            update_work_assignment(
                session,
                assignment_id=cross.id,
                expected_revision=1,
                changed_by="María",
                status="completed",
                outcome="changes_requested",
                assignment_note="Corregir la página 2",
            )
            cross_id = cross.id
        with session_scope(engine) as session:
            rows = work_assignment_rows(session, project_id=decisions.project_id)
            history = work_assignment_revision_rows(session, assignment_id=cross_id)
            candidates = cross_review_candidate_rows(
                session, project_id=decisions.project_id
            )
        cross_row = next(row for row in rows if row.assignment_id == cross_id)
        assert cross_row.parent_assignee == "Alex"
        assert cross_row.status == "completed"
        assert cross_row.outcome == "changes_requested"
        assert [row.revision_number for row in history] == [2, 1]
        assert candidates[0].completed_cross_reviews == 1
    finally:
        engine.dispose()


def test_cross_review_must_be_assigned_to_another_person(tmp_path: Path) -> None:
    root = tmp_path / "project"
    decisions, engine = _seed(root)
    try:
        with session_scope(engine) as session:
            primary = create_work_assignment(
                session,
                project_id=decisions.project_id,
                source_type="test_corpus",
                source_key="doc_work",
                assignment_kind="primary_review",
                assignee="Alex",
                created_by="Alex",
            )
            update_work_assignment(
                session,
                assignment_id=primary.id,
                expected_revision=1,
                changed_by="Alex",
                status="submitted",
            )
            primary_id = primary.id
        with session_scope(engine) as session:
            with pytest.raises(ValueError, match="otra persona"):
                create_cross_review_assignment(
                    session,
                    primary_assignment_id=primary_id,
                    assignee="alex",
                    created_by="Alex",
                )
    finally:
        engine.dispose()


def test_workload_summary_counts_statuses_and_types(tmp_path: Path) -> None:
    root = tmp_path / "project"
    decisions, engine = _seed(root)
    try:
        with session_scope(engine) as session:
            assignment = create_work_assignment(
                session,
                project_id=decisions.project_id,
                source_type="test_corpus",
                source_key="doc_work",
                assignment_kind="processing",
                assignee="Alex",
                created_by="Alex",
            )
            update_work_assignment(
                session,
                assignment_id=assignment.id,
                expected_revision=1,
                changed_by="Alex",
                status="in_progress",
            )
        with session_scope(engine) as session:
            rows = workload_summary_rows(session, project_id=decisions.project_id)
        assert rows[0].assignee == "Alex"
        assert rows[0].in_progress == 1
        assert rows[0].processing == 1
    finally:
        engine.dispose()


def test_team_workflow_migration_upgrades_existing_030_database(tmp_path: Path) -> None:
    root = tmp_path / "project"
    upgrade_database(root, revision="0025_processing_dashboard")
    assert current_revision(root) == "0025_processing_dashboard"
    upgrade_database(root)
    assert current_revision(root) == "0047_authority_relation_profiles"
    engine = create_sqlite_engine(database_path(root))
    try:
        tables = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()
    assert {"work_assignments", "work_assignment_revisions"}.issubset(tables)
