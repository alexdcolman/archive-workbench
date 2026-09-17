from __future__ import annotations

import hashlib
import json
import zipfile
from io import BytesIO
from pathlib import Path

from archive_workbench.ai_handoff import (
    inspect_ai_handoff_bytes,
    read_verified_ai_handoff_asset,
    resolve_ai_handoff,
)
from archive_workbench.corpus_export import run_export
from archive_workbench.db import create_sqlite_engine, database_path, session_scope
from archive_workbench.db.models import CorpusExportRun
from archive_workbench.identity import new_id
from tests.test_corpus_export import _profile, _seed_visual_export_material


def _handoff_for_export(
    export_path: Path,
    *,
    exp_sha256: str | None = None,
    digital_object_id: str | None = None,
    page_number: int | None = None,
    proposal_id: str = "proposal-real-page-1",
    result_id: str = "result-real-page-1",
    description: str = "Página documental de prueba.",
) -> bytes:
    with zipfile.ZipFile(export_path) as archive:
        exp_manifest = json.loads(archive.read("manifest.json"))
    page_asset = next(asset for asset in exp_manifest["assets"] if asset["kind"] == "page")
    exp_sha = exp_sha256 or hashlib.sha256(export_path.read_bytes()).hexdigest()
    result_sha = "b" * 64
    proposal = {
        "proposal_id": proposal_id,
        "result_id": result_id,
        "request_id": "request-real-1",
        "target_id": page_asset["asset_id"],
        "target_type": "page",
        "digital_object_id": digital_object_id or page_asset["digital_object_id"],
        "page_number": page_number if page_number is not None else page_asset["page_number"],
        "source_key": page_asset.get("source_key"),
        "original_filename": page_asset.get("original_filename"),
        "asset_path": page_asset["path"],
        "output_schema_id": "vision_describe/0.1",
        "output": {
            "description": description,
            "visible_text_notes": ["Texto visible"],
            "document_features": ["mecanografía"],
            "uncertainties": [],
        },
        "warnings": [],
        "provenance": {
            "exp01_sha256": exp_sha,
            "result_bundle_sha256": result_sha,
            "plugin": {"id": "archive-workbench-ai01", "version": "0.1.0.dev18"},
        },
    }
    proposals = (json.dumps(proposal, ensure_ascii=False, sort_keys=True) + "\n").encode()
    handoff_manifest = {
        "package_type": "archive_workbench_ai_result_handoff",
        "schema_version": "0.1",
        "protocol": "archive-workbench-ai/0.1",
        "created_at": "2026-09-16T00:00:00+00:00",
        "producer": {"id": "archive-workbench-ai01", "version": "0.1.0.dev18"},
        "request_id": "request-real-1",
        "source": {
            "exp01_sha256": exp_sha,
            "result_bundle_sha256": result_sha,
            "exp01_schema_version": exp_manifest["schema_version"],
        },
        "model": {"model_id": "gemma-4-26b-a4b"},
        "runtime": {"backend": "llama.cpp"},
        "prompt": {"prompt_sha256": "c" * 64},
        "policy": {
            "application": "proposed_only",
            "automatic_apply": False,
            "human_review_required": True,
        },
        "proposals_path": "results/proposals.jsonl",
        "proposals_sha256": hashlib.sha256(proposals).hexdigest(),
        "proposal_count": 1,
    }
    stream = BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(handoff_manifest))
        archive.writestr("results/proposals.jsonl", proposals)
    return stream.getvalue()


def _create_visual_export(root: Path):
    _seed_visual_export_material(root)
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            profile = _profile(
                session,
                aggregation="object",
                include_review_statuses=("approved",),
            )
            result = run_export(
                session,
                project_root=root,
                project_id="search_project",
                profile=profile,
                output_relative_path="exports/p3_source",
                output_format="visual_zip",
                created_by="tests",
            )
            run = session.get(CorpusExportRun, result.run_id)
            assert run is not None
            run_id = run.id
    finally:
        engine.dispose()
    return result, run_id


def test_resolution_verifies_local_exp01_authorization_page_and_exact_asset(tmp_path: Path) -> None:
    root = tmp_path / "project"
    result, run_id = _create_visual_export(root)
    preview = inspect_ai_handoff_bytes(_handoff_for_export(result.output_path))

    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            resolution = resolve_ai_handoff(
                session,
                project_root=root,
                project_id="search_project",
                preview=preview,
            )
            run = session.get(CorpusExportRun, run_id)
            assert run is not None
            verified = read_verified_ai_handoff_asset(
                project_root=root,
                project_id="search_project",
                run=run,
                proposal=preview.proposals[0],
                expected_exp01_sha256=preview.exp01_sha256,
            )
    finally:
        engine.dispose()

    assert resolution.incorporation_allowed is True
    assert resolution.blocking_reasons == ()
    assert len(resolution.source_matches) == 1
    source = resolution.source_matches[0]
    assert source.export_run_id == run_id
    assert source.materialization_status == "verified"
    assert source.usable_for_incorporation is True
    assert source.authorization.compatible_authorization_ids
    proposal = resolution.proposal_resolutions[0]
    assert proposal.target_status == "resolved"
    assert proposal.asset_status == "verified"
    assert proposal.acceptance_ready is True
    assert proposal.verified_export_run_ids == (run_id,)
    assert verified.sha256 == proposal.source_asset_sha256
    assert hashlib.sha256(verified.payload).hexdigest() == verified.sha256


def test_resolution_preserves_all_local_runs_with_same_exp01_hash(tmp_path: Path) -> None:
    root = tmp_path / "project"
    result, first_run_id = _create_visual_export(root)
    preview = inspect_ai_handoff_bytes(_handoff_for_export(result.output_path))

    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            first = session.get(CorpusExportRun, first_run_id)
            assert first is not None
            second = CorpusExportRun(
                id=new_id(),
                project_id=first.project_id,
                profile_id=first.profile_id,
                profile_name=first.profile_name,
                profile_snapshot_json=dict(first.profile_snapshot_json),
                corpus_state_sha256=first.corpus_state_sha256,
                output_format=first.output_format,
                output_relative_path=first.output_relative_path,
                row_count=first.row_count,
                character_count=first.character_count,
                byte_size=first.byte_size,
                output_sha256=first.output_sha256,
                created_by="tests-duplicate-run",
                created_at=first.created_at,
            )
            session.add(second)
            session.flush()
            second_run_id = second.id
            resolution = resolve_ai_handoff(
                session,
                project_root=root,
                project_id="search_project",
                preview=preview,
            )
    finally:
        engine.dispose()

    assert resolution.incorporation_allowed is True
    assert {row.export_run_id for row in resolution.source_matches} == {
        first_run_id,
        second_run_id,
    }
    assert set(resolution.proposal_resolutions[0].verified_export_run_ids) == {
        first_run_id,
        second_run_id,
    }


def test_resolution_blocks_when_registered_exp01_file_is_missing(tmp_path: Path) -> None:
    root = tmp_path / "project"
    result, _run_id = _create_visual_export(root)
    preview = inspect_ai_handoff_bytes(_handoff_for_export(result.output_path))
    result.output_path.unlink()

    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            resolution = resolve_ai_handoff(
                session,
                project_root=root,
                project_id="search_project",
                preview=preview,
            )
    finally:
        engine.dispose()

    assert resolution.incorporation_allowed is False
    assert resolution.source_matches[0].materialization_status == "unavailable"
    assert resolution.proposal_resolutions[0].asset_status == "unverified"


def test_resolution_blocks_when_page_identity_does_not_exist(tmp_path: Path) -> None:
    root = tmp_path / "project"
    result, _run_id = _create_visual_export(root)
    preview = inspect_ai_handoff_bytes(
        _handoff_for_export(result.output_path, digital_object_id="missing-object")
    )

    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            resolution = resolve_ai_handoff(
                session,
                project_root=root,
                project_id="search_project",
                preview=preview,
            )
    finally:
        engine.dispose()

    assert resolution.incorporation_allowed is False
    proposal = resolution.proposal_resolutions[0]
    assert proposal.target_status == "missing"
    assert proposal.acceptance_ready is False


def test_resolution_blocks_when_exact_exp01_asset_hash_is_invalid(tmp_path: Path) -> None:
    root = tmp_path / "project"
    result, run_id = _create_visual_export(root)
    with zipfile.ZipFile(result.output_path) as archive:
        contents = {info.filename: archive.read(info) for info in archive.infolist()}
        manifest = json.loads(contents["manifest.json"])
    page_asset = next(asset for asset in manifest["assets"] if asset["kind"] == "page")
    original = bytearray(contents[page_asset["path"]])
    original[len(original) // 2] ^= 0x01
    contents[page_asset["path"]] = bytes(original)
    with zipfile.ZipFile(result.output_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, payload in contents.items():
            archive.writestr(name, payload)
    tampered_sha = hashlib.sha256(result.output_path.read_bytes()).hexdigest()

    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            run = session.get(CorpusExportRun, run_id)
            assert run is not None
            run.output_sha256 = tampered_sha
            run.byte_size = result.output_path.stat().st_size
            session.flush()
            preview = inspect_ai_handoff_bytes(
                _handoff_for_export(result.output_path, exp_sha256=tampered_sha)
            )
            resolution = resolve_ai_handoff(
                session,
                project_root=root,
                project_id="search_project",
                preview=preview,
            )
    finally:
        engine.dispose()

    assert resolution.incorporation_allowed is False
    proposal = resolution.proposal_resolutions[0]
    assert proposal.target_status == "resolved"
    assert proposal.asset_status == "unverified"
    assert "SHA-256" in (proposal.issue or "")


def test_resolution_blocks_when_export_authorization_evidence_is_missing(tmp_path: Path) -> None:
    from sqlalchemy import delete

    from archive_workbench.db.models import AutomaticAnalysisAuthorization

    root = tmp_path / "project"
    result, _run_id = _create_visual_export(root)
    preview = inspect_ai_handoff_bytes(_handoff_for_export(result.output_path))

    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            session.execute(delete(AutomaticAnalysisAuthorization))
            session.flush()
            resolution = resolve_ai_handoff(
                session,
                project_root=root,
                project_id="search_project",
                preview=preview,
            )
    finally:
        engine.dispose()

    assert resolution.incorporation_allowed is False
    source = resolution.source_matches[0]
    assert source.materialization_status == "verified"
    assert source.authorization.compatible_authorization_ids == ()
    assert source.usable_for_incorporation is False


def test_resolution_keeps_unknown_source_inspectable_but_not_incorporable(tmp_path: Path) -> None:
    root = tmp_path / "project"
    result, _run_id = _create_visual_export(root)
    preview = inspect_ai_handoff_bytes(_handoff_for_export(result.output_path))

    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            for run in session.query(CorpusExportRun).all():
                session.delete(run)
            session.flush()
            resolution = resolve_ai_handoff(
                session,
                project_root=root,
                project_id="search_project",
                preview=preview,
            )
    finally:
        engine.dispose()

    assert resolution.source_matches == ()
    assert resolution.incorporation_allowed is False
    assert any("CorpusExportRun" in reason for reason in resolution.blocking_reasons)
