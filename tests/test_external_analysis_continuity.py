from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path

import pytest
from sqlalchemy import select

from archive_workbench.db import (
    create_sqlite_engine,
    current_revision,
    database_path,
    session_scope,
    upgrade_database,
)
from archive_workbench.db.models import (
    CorpusExportRun,
    DigitalObject,
    ExchangeChangeEvent,
    ExchangeWorkspace,
    ExternalAnalysisPackage,
    ExternalAnalysisPackageSource,
    ExternalAnalysisProposal,
    ExternalAnalysisReview,
    ExternalAnalysisSelection,
)
from archive_workbench.exchange import (
    apply_change_bundle,
    create_exchange_checkpoint,
    dry_run_change_bundle,
    ensure_exchange_workspace,
    export_change_bundle,
)
from archive_workbench.identity import new_id
from archive_workbench.state_adoption import (
    apply_state_adoption,
    create_state_adoption_package,
    preview_state_adoption,
)
from tests.test_exchange import _reset_receiver_exchange_identity
from tests.test_search import _seed_search_project


def _append_reviewed_external_analysis(
    session, *, project_id: str = "search_project"
) -> tuple[str, str, str, str]:
    digital = session.scalar(select(DigitalObject).where(DigitalObject.project_id == project_id))
    assert digital is not None
    package_id = new_id()
    proposal_id = new_id()
    review_id = new_id()
    selection_id = new_id()
    session.add(
        ExternalAnalysisPackage(
            id=package_id,
            project_id=project_id,
            package_sha256="1" * 64,
            package_type="archive_workbench_ai_result_handoff",
            schema_version="0.1",
            protocol="archive-workbench-ai/0.1",
            producer_id="archive-workbench-ai01",
            producer_version="0.1.0.dev18",
            request_id="request-continuity",
            exp01_sha256="2" * 64,
            result_bundle_sha256="3" * 64,
            model_json={"model_id": "gemma-4-26b-a4b"},
            runtime_json={"backend": "llama.cpp"},
            prompt_json={"prompt_sha256": "4" * 64},
            source_scope_json={"scope_key": "approved_only"},
            proposal_count=1,
            manifest_json={"package_type": "archive_workbench_ai_result_handoff"},
            imported_by="Alex",
        )
    )
    session.flush()
    session.add(
        ExternalAnalysisProposal(
            id=proposal_id,
            package_id=package_id,
            external_proposal_id="proposal-continuity-1",
            result_id="result-continuity-1",
            output_schema_id="vision_describe/0.1",
            target_type="page",
            target_id=f"page:{digital.id}:1",
            digital_object_id=digital.id,
            page_number=1,
            source_key="doc_search",
            original_filename=digital.original_filename,
            asset_path="assets/page_0001.png",
            source_asset_sha256="5" * 64,
            output_json={"description": "Descripción automática."},
            output_sha256="6" * 64,
            provenance_json={"exp01_sha256": "2" * 64},
            warnings_json=[],
        )
    )
    session.flush()
    session.add(
        ExternalAnalysisReview(
            id=review_id,
            proposal_id=proposal_id,
            revision=1,
            decision="accepted",
            reviewed_output_json={"description": "Descripción revisada."},
            review_note="Revisada contra el asset exacto.",
            reviewed_by="Alex",
            source_proposal_sha256="6" * 64,
        )
    )
    session.flush()
    session.add(
        ExternalAnalysisSelection(
            id=selection_id,
            project_id=project_id,
            target_type="page",
            target_id=f"page:{digital.id}:1",
            digital_object_id=digital.id,
            page_number=1,
            output_schema_id="vision_describe/0.1",
            review_id=review_id,
            action="set",
            supersedes_selection_id=None,
            selected_by="Alex",
        )
    )
    session.flush()
    return package_id, proposal_id, review_id, selection_id


def test_0050_backfills_existing_p3c_analysis_in_dependency_order(tmp_path: Path) -> None:
    root = tmp_path / "project"
    _seed_search_project(root, revision="0049_external_analysis_layer")
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            ensure_exchange_workspace(session, workspace_name="source", changed_by="Alex")
            ids = _append_reviewed_external_analysis(session)
        with session_scope(engine) as session:
            assert (
                session.scalars(
                    select(ExchangeChangeEvent).where(
                        ExchangeChangeEvent.entity_type.like("external_analysis_%")
                    )
                ).all()
                == []
            )
    finally:
        engine.dispose()

    upgrade_database(root)
    assert current_revision(root) == "0050_external_analysis_continuity"
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            events = session.scalars(
                select(ExchangeChangeEvent)
                .where(ExchangeChangeEvent.entity_type.like("external_analysis_%"))
                .order_by(ExchangeChangeEvent.sequence_number)
            ).all()
    finally:
        engine.dispose()

    assert [row.entity_type for row in events] == [
        "external_analysis_package",
        "external_analysis_proposal",
        "external_analysis_review",
        "external_analysis_selection",
    ]
    assert [row.entity_id for row in events] == list(ids)
    assert events[1].changed_fields_json["package_sha256"][1] == "1" * 64
    assert events[2].changed_fields_json["external_proposal_id"][1] == "proposal-continuity-1"
    assert events[3].changed_fields_json["review_revision"][1] == 1


def test_external_analysis_exchange_preserves_reviewed_state_and_rebuilds_local_sources(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "source"
    _seed_search_project(source_root)
    source_engine = create_sqlite_engine(database_path(source_root))
    try:
        with session_scope(source_engine) as session:
            ensure_exchange_workspace(session, workspace_name="source", changed_by="Alex")
            create_exchange_checkpoint(session, label="baseline", created_by="Alex")
    finally:
        source_engine.dispose()

    receiver_root = tmp_path / "receiver"
    shutil.copytree(source_root, receiver_root)
    receiver_engine, _ = _reset_receiver_exchange_identity(receiver_root, "receiver")
    receiver_engine.dispose()

    source_engine = create_sqlite_engine(database_path(source_root))
    try:
        with session_scope(source_engine) as session:
            ids = _append_reviewed_external_analysis(session)
        with session_scope(source_engine) as session:
            bundle = export_change_bundle(
                session,
                project_root=source_root,
                checkpoint_ref="baseline",
                created_by="Alex",
            )
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
            assert dry.counts["review"] == 0
            assert dry.counts["conflict"] == 0
            assert dry.counts["apply"] == 4
        with session_scope(receiver_engine) as session:
            applied = apply_change_bundle(
                session,
                project_root=receiver_root,
                bundle_ref=bundle.bundle_id,
                applied_by="Alex",
            )
            assert applied.applied_event_count == 4
        with session_scope(receiver_engine) as session:
            package = session.get(ExternalAnalysisPackage, ids[0])
            proposal = session.get(ExternalAnalysisProposal, ids[1])
            review = session.get(ExternalAnalysisReview, ids[2])
            selection = session.get(ExternalAnalysisSelection, ids[3])
            sources = session.scalars(
                select(ExternalAnalysisPackageSource).where(
                    ExternalAnalysisPackageSource.package_id == ids[0]
                )
            ).all()
    finally:
        receiver_engine.dispose()

    assert package is not None and package.package_sha256 == "1" * 64
    assert proposal is not None and proposal.output_json["description"] == "Descripción automática."
    assert review is not None and review.reviewed_output_json == {
        "description": "Descripción revisada."
    }
    assert selection is not None and selection.review_id == review.id
    # package_sources es local/reconstruible: sin CorpusExportRun equivalente no viaja ningún export_run_id.
    assert sources == []


def test_state_adoption_14_transports_reviewed_analysis_and_rebuilds_local_sources(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "source"
    _seed_search_project(source_root)
    source_engine = create_sqlite_engine(database_path(source_root))
    try:
        with session_scope(source_engine) as session:
            ensure_exchange_workspace(session, workspace_name="source", changed_by="Alex")
    finally:
        source_engine.dispose()

    receiver_root = tmp_path / "receiver"
    shutil.copytree(source_root, receiver_root)
    receiver_engine, receiver_workspace_id = _reset_receiver_exchange_identity(
        receiver_root, "receiver"
    )
    try:
        with session_scope(receiver_engine) as session:
            local_export_run_id = new_id()
            session.add(
                CorpusExportRun(
                    id=local_export_run_id,
                    project_id="search_project",
                    profile_id=None,
                    profile_name="EXP-01 local equivalente",
                    profile_snapshot_json={"material_type": "documents"},
                    corpus_state_sha256="7" * 64,
                    output_format="zip",
                    output_relative_path="exports/equivalent.zip",
                    row_count=1,
                    character_count=20,
                    byte_size=100,
                    output_sha256="2" * 64,
                    created_by="Alex",
                )
            )
            receiver_workspace = session.get(ExchangeWorkspace, receiver_workspace_id)
            assert receiver_workspace is not None
            receiver_workspace_name = receiver_workspace.workspace_name
    finally:
        receiver_engine.dispose()

    source_engine = create_sqlite_engine(database_path(source_root))
    try:
        with session_scope(source_engine) as session:
            ids = _append_reviewed_external_analysis(session)
            package = create_state_adoption_package(
                session,
                project_root=source_root,
                target_workspace_id=receiver_workspace_id,
                target_workspace_name=receiver_workspace_name,
                created_by="Alex",
                creation_reason="Validar adopción P3-D schema 1.4.",
                package_confirmed=True,
            )
            assert set(package.section_counts) >= {
                "external_analysis_packages",
                "external_analysis_proposals",
                "external_analysis_reviews",
                "external_analysis_selections",
            }
            with zipfile.ZipFile(package.output_path, "r") as archive:
                manifest = json.loads(archive.read("manifest.json"))
            assert manifest["schema_version"] == "1.4"
    finally:
        source_engine.dispose()

    receiver_engine = create_sqlite_engine(database_path(receiver_root))
    try:
        with session_scope(receiver_engine) as session:
            preview = preview_state_adoption(session, package_path=package.output_path)
            impacts = {row.section: row for row in preview.sections}
            assert impacts["external_analysis_packages"].added == 1
            assert impacts["external_analysis_proposals"].added == 1
            assert impacts["external_analysis_reviews"].added == 1
            assert impacts["external_analysis_selections"].added == 1
        with session_scope(receiver_engine) as session:
            summary = apply_state_adoption(
                session,
                project_root=receiver_root,
                package_path=package.output_path,
                applied_by="Alex",
                application_reason="Validar continuidad P3-D.",
                adoption_confirmed=True,
                source="ui",
            )
            assert summary.adopted_state_sha256 == package.state_sha256
        with session_scope(receiver_engine) as session:
            imported_package = session.get(ExternalAnalysisPackage, ids[0])
            proposal = session.get(ExternalAnalysisProposal, ids[1])
            review = session.get(ExternalAnalysisReview, ids[2])
            selection = session.get(ExternalAnalysisSelection, ids[3])
            sources = session.scalars(
                select(ExternalAnalysisPackageSource).where(
                    ExternalAnalysisPackageSource.package_id == ids[0]
                )
            ).all()
    finally:
        receiver_engine.dispose()

    assert imported_package is not None and imported_package.exp01_sha256 == "2" * 64
    assert proposal is not None and proposal.output_schema_id == "vision_describe/0.1"
    assert review is not None and review.decision == "accepted"
    assert selection is not None and selection.review_id == review.id
    assert len(sources) == 1
    assert sources[0].export_run_id == local_export_run_id


def test_state_adoption_14_does_not_delete_local_append_only_analysis(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    _seed_search_project(source_root)
    source_engine = create_sqlite_engine(database_path(source_root))
    try:
        with session_scope(source_engine) as session:
            ensure_exchange_workspace(session, workspace_name="source", changed_by="Alex")
    finally:
        source_engine.dispose()

    receiver_root = tmp_path / "receiver"
    shutil.copytree(source_root, receiver_root)
    receiver_engine, receiver_workspace_id = _reset_receiver_exchange_identity(
        receiver_root, "receiver"
    )
    try:
        with session_scope(receiver_engine) as session:
            local_ids = _append_reviewed_external_analysis(session)
            receiver_workspace = session.get(ExchangeWorkspace, receiver_workspace_id)
            assert receiver_workspace is not None
            receiver_workspace_name = receiver_workspace.workspace_name
    finally:
        receiver_engine.dispose()

    source_engine = create_sqlite_engine(database_path(source_root))
    try:
        with session_scope(source_engine) as session:
            _append_reviewed_external_analysis(session)
            package = create_state_adoption_package(
                session,
                project_root=source_root,
                target_workspace_id=receiver_workspace_id,
                target_workspace_name=receiver_workspace_name,
                created_by="Alex",
                creation_reason="Validar protección append-only P3-D.",
                package_confirmed=True,
            )
    finally:
        source_engine.dispose()

    receiver_engine = create_sqlite_engine(database_path(receiver_root))
    try:
        with session_scope(receiver_engine) as session:
            with pytest.raises(ValueError, match="borrar historial append-only"):
                preview_state_adoption(session, package_path=package.output_path)
        with session_scope(receiver_engine) as session:
            assert session.get(ExternalAnalysisPackage, local_ids[0]) is not None
            assert session.get(ExternalAnalysisReview, local_ids[2]) is not None
            assert session.get(ExternalAnalysisSelection, local_ids[3]) is not None
    finally:
        receiver_engine.dispose()
