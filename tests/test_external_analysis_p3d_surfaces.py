from __future__ import annotations

import csv
import io
import json
from pathlib import Path

from archive_workbench.ai_handoff import inspect_ai_handoff_bytes, resolve_ai_handoff
from archive_workbench.db import create_sqlite_engine, database_path, session_scope
from archive_workbench.db.models import ExternalAnalysisProposal
from archive_workbench.external_analysis import (
    external_analysis_current_review_ids_for_page,
    external_analysis_reviewed_export_rows,
    incorporate_ai_handoff,
    review_external_analysis_proposal,
)
from archive_workbench.external_analysis_export import export_reviewed_external_analysis
from tests.test_ai_handoff_resolution import _create_visual_export, _handoff_for_export


def _accepted_external_analysis(root: Path):
    export, _run_id = _create_visual_export(root)
    preview = inspect_ai_handoff_bytes(_handoff_for_export(export.output_path))
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            resolution = resolve_ai_handoff(
                session,
                project_root=root,
                project_id="search_project",
                preview=preview,
            )
            imported = incorporate_ai_handoff(
                session,
                project_id="search_project",
                preview=preview,
                resolution=resolution,
                imported_by="alex",
            )
            reviewed = review_external_analysis_proposal(
                session,
                proposal_id=imported.proposal_ids[0],
                decision="accepted",
                reviewed_by="alex",
                review_note="revisión humana",
            )
            proposal = session.get(ExternalAnalysisProposal, imported.proposal_ids[0])
            assert proposal is not None
            return proposal.id, reviewed.review_id, proposal.source_key, proposal.page_number
    finally:
        engine.dispose()


def test_inverse_navigation_lookup_reads_only_current_page_selection(tmp_path: Path) -> None:
    root = tmp_path / "project"
    _proposal_id, review_id, source_key, page_number = _accepted_external_analysis(root)
    assert source_key

    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            ids = external_analysis_current_review_ids_for_page(
                session,
                project_id="search_project",
                source_key=source_key,
                page_number=page_number,
            )
            missing = external_analysis_current_review_ids_for_page(
                session,
                project_id="search_project",
                source_key=source_key,
                page_number=page_number + 50,
            )
    finally:
        engine.dispose()

    assert ids == (review_id,)
    assert missing == ()


def test_reviewed_layer_export_preserves_review_and_vigency_trace(tmp_path: Path) -> None:
    root = tmp_path / "project"
    proposal_id, review_id, _source_key, _page_number = _accepted_external_analysis(root)

    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            rows = external_analysis_reviewed_export_rows(session, project_id="search_project")
            jsonl = export_reviewed_external_analysis(
                session,
                project_root=root,
                project_id="search_project",
                output_format="jsonl",
            )
            csv_artifact = export_reviewed_external_analysis(
                session,
                project_root=root,
                project_id="search_project",
                output_format="csv",
            )
    finally:
        engine.dispose()

    assert len(rows) == 1
    assert rows[0]["proposal_id"] == proposal_id
    assert rows[0]["review_id"] == review_id
    assert rows[0]["selection_id"]
    assert rows[0]["selected_by"] == "alex"
    assert rows[0]["reviewed_output"]

    json_path = root / jsonl.relative_path
    csv_path = root / csv_artifact.relative_path
    exported = json.loads(json_path.read_text(encoding="utf-8").strip())
    assert exported["export_schema"] == "archive_workbench_reviewed_external_analysis/0.1"
    assert exported["review_id"] == review_id
    assert exported["selection_id"] == rows[0]["selection_id"]

    csv_rows = list(csv.DictReader(io.StringIO(csv_path.read_text(encoding="utf-8"))))
    assert len(csv_rows) == 1
    assert csv_rows[0]["review_id"] == review_id
    assert csv_rows[0]["selection_id"] == rows[0]["selection_id"]
    assert csv_rows[0]["description"]


def test_p3d_ui_surfaces_remain_explicit_and_passive() -> None:
    root = Path(__file__).parents[1] / "src" / "archive_workbench"
    assisted = (root / "assisted_analysis_app.py").read_text(encoding="utf-8")
    review = (root / "review_app.py").read_text(encoding="utf-8")
    export = (root / "export_app.py").read_text(encoding="utf-8")

    assert "Comparar propuestas" in assisted
    assert "Elegir otra propuesta" in assisted
    assert "Página actual correspondiente" in assisted
    assert "No se verificó identidad binaria" in assisted
    assert assisted.count("page=selected.page_number") >= 2
    assert "active_tab" not in assisted

    assert "Ver análisis asistido de esta página" in review
    assert "external_analysis_current_review_ids_for_page" in review
    assert "request_assisted_analysis_document" in review

    assert '"assisted_analysis": "Análisis asistido revisado"' in export
    assert "Crear archivo de análisis asistido revisado" in export
    assert "export_reviewed_external_analysis" in export
