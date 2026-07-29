from __future__ import annotations

import csv
import json
from pathlib import Path

from archive_workbench.corpus_export import (
    ExportProfileValues,
    build_export_rows,
    export_run_rows,
    preview_export,
    run_export,
    save_export_profile,
)
from archive_workbench.db import create_sqlite_engine, database_path, session_scope
from archive_workbench.db.models import EditableObject, EditablePage
from tests.test_search import _seed_search_project


def _profile(session, *, aggregation: str = "document", **kwargs):
    return save_export_profile(
        session,
        project_id="search_project",
        values=ExportProfileValues(
            name=f"Perfil {aggregation}",
            aggregation_level=aggregation,
            **kwargs,
        ),
        changed_by="tests",
    )


def test_export_profile_groups_document_and_uses_corrected_text(tmp_path: Path) -> None:
    root = tmp_path / "project"
    object_id, _page_id = _seed_search_project(root)
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            profile = _profile(session)
            rows = build_export_rows(session, project_id="search_project", profile=profile)
    finally:
        engine.dispose()
    assert len(rows) == 1
    assert rows[0].object_ids == [object_id]
    assert rows[0].texto == "La actividad teatral fue investigada"
    assert rows[0].titulo == "Documento teatral"
    assert rows[0].tags == ["teatro", "vigilancia"]


def test_export_filters_review_status_and_supports_original_text(tmp_path: Path) -> None:
    root = tmp_path / "project"
    _seed_search_project(root)
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            original = _profile(
                session,
                aggregation="object",
                text_policy="original_only",
                include_review_statuses=("approved",),
            )
            rows = build_export_rows(session, project_id="search_project", profile=original)
            assert rows[0].texto == "actividad subversiva"
            original.include_review_statuses_json = ["needs_review"]
            session.flush()
            assert build_export_rows(session, project_id="search_project", profile=original) == []
    finally:
        engine.dispose()


def test_page_export_inserts_marker_and_separators(tmp_path: Path) -> None:
    root = tmp_path / "project"
    _seed_search_project(root)
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            existing = session.query(EditableObject).one()
            page = session.get(EditablePage, existing.editable_page_id)
            second = EditableObject(
                id="second-object",
                editable_page_id=existing.editable_page_id,
                digital_object_id=existing.digital_object_id,
                page_number=1,
                source_extracted_object_id=None,
                source_origin_id=None,
                current_text="Segundo párrafo",
                current_object_type="paragraph",
                current_order_index=1,
                current_geometry_json=[],
                current_attributes_json={},
                lifecycle_status="active",
                review_status="approved",
                revision_number=1,
                created_by="tests",
                updated_by="tests",
            )
            session.add(second)
            session.flush()
            profile = _profile(
                session,
                aggregation="page",
                include_page_markers=True,
                object_separator=" | ",
            )
            rows = build_export_rows(session, project_id="search_project", profile=profile)
    finally:
        engine.dispose()
    assert rows[0].texto == "[Página 1]\nLa actividad teatral fue investigada | Segundo párrafo"
    assert rows[0].object_count == 2


def test_run_export_writes_jsonl_and_registers_hashes(tmp_path: Path) -> None:
    root = tmp_path / "project"
    _seed_search_project(root)
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            profile = _profile(session)
            result = run_export(
                session,
                project_root=root,
                project_id="search_project",
                profile=profile,
                output_relative_path="exports/corpus",
                created_by="tests",
            )
            history = export_run_rows(session, project_id="search_project")
    finally:
        engine.dispose()
    assert result.output_path == root / "exports" / "corpus.jsonl"
    payload = json.loads(result.output_path.read_text(encoding="utf-8").splitlines()[0])
    assert payload["codigo"].startswith("document:")
    assert payload["texto"] == "La actividad teatral fue investigada"
    assert history[0].output_sha256 == result.output_sha256
    assert len(result.corpus_state_sha256) == 64


def test_run_export_writes_csv_lists_as_json(tmp_path: Path) -> None:
    root = tmp_path / "project"
    _seed_search_project(root)
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            profile = _profile(session, aggregation="object", output_format="csv")
            result = run_export(
                session,
                project_root=root,
                project_id="search_project",
                profile=profile,
                output_relative_path="exports/corpus.csv",
                created_by="tests",
            )
    finally:
        engine.dispose()
    with result.output_path.open(encoding="utf-8") as handle:
        row = next(csv.DictReader(handle))
    assert json.loads(row["tags"]) == ["teatro", "vigilancia"]


def test_preview_does_not_write_or_register_run(tmp_path: Path) -> None:
    root = tmp_path / "project"
    _seed_search_project(root)
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            profile = _profile(session)
            preview = preview_export(session, project_id="search_project", profile=profile, limit=1)
            history = export_run_rows(session, project_id="search_project")
    finally:
        engine.dispose()
    assert preview.total_records == 1
    assert len(preview.records) == 1
    assert history == []


def test_export_filters_by_entity_period_and_includes_temporal_metadata(tmp_path: Path) -> None:
    from datetime import date
    from archive_workbench.authorities import create_authority, create_mention

    root = tmp_path / "project"
    object_id, _page_id = _seed_search_project(root)
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            entity = create_authority(
                session,
                project_id="search_project",
                entity_type="event",
                preferred_name="Actividad teatral",
                temporal_expression="años setenta",
                created_by="tests",
            )
            create_mention(
                session,
                object_id=object_id,
                mention_text="teatral",
                authority_id=entity.id,
                created_by="tests",
            )
            profile = _profile(
                session,
                aggregation="object",
                temporal_start=date(1975, 1, 1),
                temporal_end=date(1975, 12, 31),
            )
            rows = build_export_rows(session, project_id="search_project", profile=profile)
            profile.temporal_start = date(1985, 1, 1)
            profile.temporal_end = date(1985, 12, 31)
            session.flush()
            outside = build_export_rows(session, project_id="search_project", profile=profile)
        assert rows[0].object_ids == [object_id]
        assert rows[0].entity_temporal_ranges == ["Actividad teatral: años setenta"]
        assert outside == []
    finally:
        engine.dispose()
