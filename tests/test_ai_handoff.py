from __future__ import annotations

import hashlib
import json
import zipfile
from io import BytesIO

import pytest

from archive_workbench.ai_handoff import AIHandoffError, inspect_ai_handoff_bytes


def _handoff_bytes(
    *,
    automatic_apply: bool = False,
    tamper_proposals: bool = False,
    output_schema_id: str = "vision_describe/0.1",
    proposals_path: str = "results/proposals.jsonl",
    extra_member: bool = False,
    duplicate_manifest: bool = False,
) -> bytes:
    exp_sha = "1" * 64
    result_sha = "2" * 64
    proposal = {
        "proposal_id": "proposal-1",
        "result_id": "result-1",
        "request_id": "request-1",
        "target_id": "page:object-1:1",
        "target_type": "page",
        "digital_object_id": "object-1",
        "page_number": 1,
        "source_key": "catalog_legajo_n_15_a_c_100",
        "original_filename": "legajo n° 15 A.C 100.tiff",
        "asset_path": "images/pages/object-1_p0001.png",
        "output_schema_id": output_schema_id,
        "output": {
            "description": "Informe mecanografiado con anotaciones marginales.",
            "visible_text_notes": [],
            "document_features": ["mecanografía", "anotaciones manuscritas"],
            "uncertainties": [],
        },
        "warnings": [],
        "provenance": {
            "exp01_sha256": exp_sha,
            "result_bundle_sha256": result_sha,
            "plugin": {"id": "ai01", "version": "0.1.0.dev18"},
        },
    }
    proposals = (json.dumps(proposal, ensure_ascii=False, sort_keys=True) + "\n").encode()
    manifest = {
        "package_type": "archive_workbench_ai_result_handoff",
        "schema_version": "0.1",
        "protocol": "archive-workbench-ai/0.1",
        "created_at": "2026-09-16T00:00:00+00:00",
        "producer": {"id": "archive-workbench-ai01", "version": "0.1.0.dev18"},
        "request_id": "request-1",
        "source": {
            "exp01_sha256": exp_sha,
            "result_bundle_sha256": result_sha,
            "exp01_schema_version": "1.1",
        },
        "model": {"model_id": "unsloth/Qwen3.5-9B-GGUF:Q4_K_M"},
        "runtime": {"backend": "llama.cpp"},
        "prompt": {"prompt_sha256": "3" * 64},
        "policy": {
            "application": "proposed_only",
            "automatic_apply": automatic_apply,
            "human_review_required": True,
        },
        "proposals_path": proposals_path,
        "proposals_sha256": hashlib.sha256(proposals).hexdigest(),
        "proposal_count": 1,
    }
    stream = BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        if duplicate_manifest:
            archive.writestr("manifest.json", json.dumps(manifest))
        archive.writestr(
            proposals_path,
            proposals + (b" " if tamper_proposals else b""),
        )
        if extra_member:
            archive.writestr("unexpected.txt", "not allowed")
    return stream.getvalue()


def test_ai_handoff_preview_reads_dev18_proposed_only_bundle_without_applying() -> None:
    preview = inspect_ai_handoff_bytes(_handoff_bytes())

    assert preview.schema_version == "0.1"
    assert preview.protocol == "archive-workbench-ai/0.1"
    assert preview.producer_version == "0.1.0.dev18"
    assert preview.exp01_schema_version == "1.1"
    assert preview.proposal_count == 1
    assert preview.automatic_apply is False
    assert preview.human_review_required is True
    assert preview.model_id == "unsloth/Qwen3.5-9B-GGUF:Q4_K_M"
    assert preview.runtime["backend"] == "llama.cpp"
    proposal = preview.proposals[0]
    assert proposal.target_id == "page:object-1:1"
    assert proposal.digital_object_id == "object-1"
    assert proposal.page_number == 1
    assert proposal.original_filename == "legajo n° 15 A.C 100.tiff"
    assert proposal.output_schema_id == "vision_describe/0.1"
    assert "mecanografiado" in proposal.output["description"]
    assert len(proposal.output_sha256) == 64


def test_ai_handoff_preview_rejects_automatic_application() -> None:
    with pytest.raises(AIHandoffError, match="aplicación automática"):
        inspect_ai_handoff_bytes(_handoff_bytes(automatic_apply=True))


def test_ai_handoff_preview_rejects_modified_proposals() -> None:
    with pytest.raises(AIHandoffError, match="huella SHA-256"):
        inspect_ai_handoff_bytes(_handoff_bytes(tamper_proposals=True))


def test_ai_handoff_preview_rejects_unknown_output_schema() -> None:
    with pytest.raises(AIHandoffError, match="output_schema_id no está soportado"):
        inspect_ai_handoff_bytes(_handoff_bytes(output_schema_id="vision_describe/9.9"))


def test_ai_handoff_preview_rejects_members_outside_allowlist() -> None:
    with pytest.raises(AIHandoffError, match="fuera de la allowlist"):
        inspect_ai_handoff_bytes(_handoff_bytes(extra_member=True))


def test_ai_handoff_preview_rejects_duplicate_zip_members() -> None:
    with pytest.warns(UserWarning, match="Duplicate name"):
        payload = _handoff_bytes(duplicate_manifest=True)
    with pytest.raises(AIHandoffError, match="miembros duplicados"):
        inspect_ai_handoff_bytes(payload)


def test_ai_handoff_preview_rejects_unsafe_proposals_path() -> None:
    with pytest.raises(AIHandoffError, match="insegur"):
        inspect_ai_handoff_bytes(_handoff_bytes(proposals_path="../proposals.jsonl"))
