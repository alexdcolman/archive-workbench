from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from sqlalchemy import inspect, select, update
from sqlalchemy.exc import DatabaseError

from archive_workbench.ai_handoff import inspect_ai_handoff_bytes, resolve_ai_handoff
from archive_workbench.db import (
    create_sqlite_engine,
    current_revision,
    database_path,
    session_scope,
    upgrade_database,
)
from archive_workbench.db.models import (
    ExternalAnalysisPackage,
    ExternalAnalysisPackageSource,
    ExternalAnalysisProposal,
    ExternalAnalysisReview,
    ExternalAnalysisSelection,
)
from archive_workbench.external_analysis import (
    ExternalAnalysisError,
    incorporate_ai_handoff,
    latest_external_analysis_selection,
    review_external_analysis_proposal,
    set_external_analysis_current_review,
)
from tests.test_ai_handoff_resolution import _create_visual_export, _handoff_for_export


def _resolved_handoff(root: Path, export_path: Path, **handoff_kwargs):
    preview = inspect_ai_handoff_bytes(_handoff_for_export(export_path, **handoff_kwargs))
    engine = create_sqlite_engine(database_path(root))
    with session_scope(engine) as session:
        resolution = resolve_ai_handoff(
            session,
            project_root=root,
            project_id="search_project",
            preview=preview,
        )
    engine.dispose()
    assert resolution.incorporation_allowed is True
    return preview, resolution


def test_external_analysis_migration_upgrades_0048_and_adds_p3b_tables(tmp_path: Path) -> None:
    root = tmp_path / "project"
    upgrade_database(root, revision="0048_catalog_document_components")
    assert current_revision(root) == "0048_catalog_document_components"

    upgrade_database(root)
    assert current_revision(root) == "0050_external_analysis_continuity"
    engine = create_sqlite_engine(database_path(root))
    try:
        tables = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()

    assert {
        "external_analysis_packages",
        "external_analysis_package_sources",
        "external_analysis_proposals",
        "external_analysis_reviews",
        "external_analysis_selections",
    } <= tables


def test_incorporation_is_idempotent_and_preserves_raw_and_local_sources(tmp_path: Path) -> None:
    root = tmp_path / "project"
    export, _run_id = _create_visual_export(root)
    preview, resolution = _resolved_handoff(root, export.output_path)

    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            first = incorporate_ai_handoff(
                session,
                project_id="search_project",
                preview=preview,
                resolution=resolution,
                imported_by="alex",
            )
        with session_scope(engine) as session:
            second = incorporate_ai_handoff(
                session,
                project_id="search_project",
                preview=preview,
                resolution=resolution,
                imported_by="alex",
            )
            packages = session.scalars(select(ExternalAnalysisPackage)).all()
            proposals = session.scalars(select(ExternalAnalysisProposal)).all()
            sources = session.scalars(select(ExternalAnalysisPackageSource)).all()
    finally:
        engine.dispose()

    assert first.created is True
    assert second.created is False
    assert first.package_id == second.package_id
    assert len(packages) == 1
    assert len(proposals) == preview.proposal_count == 1
    assert len(sources) == 1
    assert proposals[0].output_json == preview.proposals[0].output
    assert proposals[0].output_sha256 == preview.proposals[0].output_sha256
    assert (
        proposals[0].source_asset_sha256 == resolution.proposal_resolutions[0].source_asset_sha256
    )
    assert packages[0].source_scope_json["scope_key"] == "approved_only"
    assert "export_run_id" not in packages[0].source_scope_json


def test_incorporation_refuses_unresolved_handoff_without_writing(tmp_path: Path) -> None:
    root = tmp_path / "project"
    export, _run_id = _create_visual_export(root)
    preview, resolution = _resolved_handoff(root, export.output_path)
    blocked = replace(
        resolution,
        incorporation_allowed=False,
        blocking_reasons=("control",),
    )

    engine = create_sqlite_engine(database_path(root))
    try:
        with pytest.raises(ExternalAnalysisError, match="no puede incorporarse"):
            with session_scope(engine) as session:
                incorporate_ai_handoff(
                    session,
                    project_id="search_project",
                    preview=preview,
                    resolution=blocked,
                    imported_by="alex",
                )
        with session_scope(engine) as session:
            assert session.scalars(select(ExternalAnalysisPackage)).all() == []
    finally:
        engine.dispose()


def test_acceptance_creates_review_snapshot_without_rewriting_raw_and_initial_vigency(
    tmp_path: Path,
) -> None:
    root = tmp_path / "project"
    export, _run_id = _create_visual_export(root)
    preview, resolution = _resolved_handoff(root, export.output_path)
    edited = dict(preview.proposals[0].output)
    edited["description"] = "Descripción revisada por una persona."

    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
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
                reviewed_output=edited,
                review_note="Revisado contra la imagen.",
            )
        with session_scope(engine) as session:
            proposal = session.get(ExternalAnalysisProposal, imported.proposal_ids[0])
            review = session.get(ExternalAnalysisReview, reviewed.review_id)
            assert proposal is not None and review is not None
            current = latest_external_analysis_selection(
                session,
                project_id="search_project",
                target_type=proposal.target_type,
                target_id=proposal.target_id,
                output_schema_id=proposal.output_schema_id,
            )
    finally:
        engine.dispose()

    assert proposal.output_json == preview.proposals[0].output
    assert review.reviewed_output_json == edited
    assert review.source_proposal_sha256 == preview.proposals[0].output_sha256
    assert reviewed.revision == 1
    assert reviewed.initial_selection_id is not None
    assert current is not None
    assert current.review_id == reviewed.review_id


def test_second_acceptance_does_not_replace_vigency_without_explicit_selection(
    tmp_path: Path,
) -> None:
    root = tmp_path / "project"
    export, _run_id = _create_visual_export(root)
    first_preview, first_resolution = _resolved_handoff(root, export.output_path)
    second_preview, second_resolution = _resolved_handoff(
        root,
        export.output_path,
        proposal_id="proposal-real-page-2",
        result_id="result-real-page-2",
        description="Segunda descripción automática.",
    )

    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            first_import = incorporate_ai_handoff(
                session,
                project_id="search_project",
                preview=first_preview,
                resolution=first_resolution,
                imported_by="alex",
            )
            first_review = review_external_analysis_proposal(
                session,
                proposal_id=first_import.proposal_ids[0],
                decision="accepted",
                reviewed_by="alex",
            )
        with session_scope(engine) as session:
            second_import = incorporate_ai_handoff(
                session,
                project_id="search_project",
                preview=second_preview,
                resolution=second_resolution,
                imported_by="alex",
            )
            second_review = review_external_analysis_proposal(
                session,
                proposal_id=second_import.proposal_ids[0],
                decision="accepted",
                reviewed_by="alex",
            )
            second_proposal = session.get(ExternalAnalysisProposal, second_import.proposal_ids[0])
            assert second_proposal is not None
            before = latest_external_analysis_selection(
                session,
                project_id="search_project",
                target_type=second_proposal.target_type,
                target_id=second_proposal.target_id,
                output_schema_id=second_proposal.output_schema_id,
            )
            assert before is not None
            switched = set_external_analysis_current_review(
                session,
                review_id=second_review.review_id,
                selected_by="alex",
            )
            repeated = set_external_analysis_current_review(
                session,
                review_id=second_review.review_id,
                selected_by="alex",
            )
        with session_scope(engine) as session:
            selections = session.scalars(
                select(ExternalAnalysisSelection).order_by(ExternalAnalysisSelection.selected_at)
            ).all()
    finally:
        engine.dispose()

    assert first_review.initial_selection_id is not None
    assert second_review.initial_selection_id is None
    assert before.review_id == first_review.review_id
    assert switched.created is True
    assert switched.supersedes_selection_id == first_review.initial_selection_id
    assert repeated.created is False
    assert repeated.selection_id == switched.selection_id
    assert len(selections) == 2
    assert selections[-1].review_id == second_review.review_id


def test_rejection_is_append_only_and_never_changes_current_selection(tmp_path: Path) -> None:
    root = tmp_path / "project"
    export, _run_id = _create_visual_export(root)
    preview, resolution = _resolved_handoff(root, export.output_path)

    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            imported = incorporate_ai_handoff(
                session,
                project_id="search_project",
                preview=preview,
                resolution=resolution,
                imported_by="alex",
            )
            accepted = review_external_analysis_proposal(
                session,
                proposal_id=imported.proposal_ids[0],
                decision="accepted",
                reviewed_by="alex",
            )
            rejected = review_external_analysis_proposal(
                session,
                proposal_id=imported.proposal_ids[0],
                decision="rejected",
                reviewed_by="alex",
                review_note="La segunda revisión rechaza la propuesta.",
            )
            proposal = session.get(ExternalAnalysisProposal, imported.proposal_ids[0])
            assert proposal is not None
            current = latest_external_analysis_selection(
                session,
                project_id="search_project",
                target_type=proposal.target_type,
                target_id=proposal.target_id,
                output_schema_id=proposal.output_schema_id,
            )
            reviews = session.scalars(
                select(ExternalAnalysisReview)
                .where(ExternalAnalysisReview.proposal_id == proposal.id)
                .order_by(ExternalAnalysisReview.revision)
            ).all()
    finally:
        engine.dispose()

    assert accepted.revision == 1
    assert rejected.revision == 2
    assert [row.decision for row in reviews] == ["accepted", "rejected"]
    assert reviews[-1].reviewed_output_json is None
    assert current is not None
    assert current.review_id == accepted.review_id


def test_raw_and_human_history_reject_in_place_updates(tmp_path: Path) -> None:
    root = tmp_path / "project"
    export, _run_id = _create_visual_export(root)
    preview, resolution = _resolved_handoff(root, export.output_path)

    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
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
            )
            proposal_id = imported.proposal_ids[0]
            review_id = reviewed.review_id
            selection_id = reviewed.initial_selection_id
        assert selection_id is not None

        for statement in (
            update(ExternalAnalysisProposal)
            .where(ExternalAnalysisProposal.id == proposal_id)
            .values(original_filename="mutado.tiff"),
            update(ExternalAnalysisReview)
            .where(ExternalAnalysisReview.id == review_id)
            .values(review_note="mutado"),
            update(ExternalAnalysisSelection)
            .where(ExternalAnalysisSelection.id == selection_id)
            .values(selected_by="otra-persona"),
        ):
            with pytest.raises(DatabaseError, match="append-only"):
                with engine.begin() as connection:
                    connection.execute(statement)
    finally:
        engine.dispose()


def test_p3c_rows_keep_list_queries_light_and_recover_exact_asset_on_demand(
    tmp_path: Path,
) -> None:
    from archive_workbench.external_analysis import (
        external_analysis_current_rows,
        external_analysis_history_rows,
        external_analysis_package_rows,
        external_analysis_proposal_detail,
        external_analysis_proposal_summaries,
        read_external_analysis_proposal_asset,
    )

    root = tmp_path / "project"
    export, _run_id = _create_visual_export(root)
    preview, resolution = _resolved_handoff(root, export.output_path)
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            imported = incorporate_ai_handoff(
                session,
                project_id="search_project",
                preview=preview,
                resolution=resolution,
                imported_by="alex",
            )
        with session_scope(engine) as session:
            packages = external_analysis_package_rows(session, project_id="search_project")
            summaries = external_analysis_proposal_summaries(session, project_id="search_project")
            detail = external_analysis_proposal_detail(
                session,
                project_id="search_project",
                proposal_id=imported.proposal_ids[0],
            )
            asset = read_external_analysis_proposal_asset(
                session,
                project_root=root,
                project_id="search_project",
                proposal_id=imported.proposal_ids[0],
            )
            assert external_analysis_history_rows(session, project_id="search_project") == []
            assert external_analysis_current_rows(session, project_id="search_project") == []
    finally:
        engine.dispose()

    assert len(packages) == 1
    assert packages[0].model_id == "gemma-4-26b-a4b"
    assert len(summaries) == 1
    assert summaries[0].status == "pending"
    assert summaries[0].current_review_id is None
    assert summaries[0].navigation_source_key
    assert detail.raw_output == preview.proposals[0].output
    assert detail.provenance == preview.proposals[0].provenance
    assert asset.sha256 == resolution.proposal_resolutions[0].source_asset_sha256


def test_p3c_history_and_current_rows_follow_review_and_explicit_vigency(tmp_path: Path) -> None:
    from archive_workbench.external_analysis import (
        external_analysis_current_rows,
        external_analysis_history_rows,
        external_analysis_proposal_summaries,
    )

    root = tmp_path / "project"
    export, _run_id = _create_visual_export(root)
    first_preview, first_resolution = _resolved_handoff(root, export.output_path)
    second_preview, second_resolution = _resolved_handoff(
        root,
        export.output_path,
        proposal_id="proposal-p3c-second",
        result_id="result-p3c-second",
        description="Segunda descripción para P3-C.",
    )
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            first_import = incorporate_ai_handoff(
                session,
                project_id="search_project",
                preview=first_preview,
                resolution=first_resolution,
                imported_by="alex",
            )
            first_review = review_external_analysis_proposal(
                session,
                proposal_id=first_import.proposal_ids[0],
                decision="accepted",
                reviewed_by="alex",
            )
            second_import = incorporate_ai_handoff(
                session,
                project_id="search_project",
                preview=second_preview,
                resolution=second_resolution,
                imported_by="alex",
            )
            second_review = review_external_analysis_proposal(
                session,
                proposal_id=second_import.proposal_ids[0],
                decision="accepted",
                reviewed_by="alex",
            )
        with session_scope(engine) as session:
            summaries_before = external_analysis_proposal_summaries(
                session, project_id="search_project"
            )
            current_before = external_analysis_current_rows(session, project_id="search_project")
            set_external_analysis_current_review(
                session,
                review_id=second_review.review_id,
                selected_by="alex",
            )
        with session_scope(engine) as session:
            history_after = external_analysis_history_rows(session, project_id="search_project")
            current_after = external_analysis_current_rows(session, project_id="search_project")
    finally:
        engine.dispose()

    assert {row.status for row in summaries_before} == {"accepted"}
    assert len(current_before) == 1
    assert current_before[0].review_id == first_review.review_id
    assert len(history_after) == 2
    assert len(current_after) == 1
    assert current_after[0].review_id == second_review.review_id
    assert current_after[0].reviewed_output == second_preview.proposals[0].output
