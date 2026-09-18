from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

from archive_workbench.ai_execution import (
    AICapabilities,
    EXPECTED_HANDOFF_SCHEMA,
    EXPECTED_HANDOFF_SCHEMA_VERSION,
    EXPECTED_PROTOCOL,
    ai_authorization_parameters,
    inspect_ai_capabilities,
    resolve_ai_executable,
    run_ai_analysis,
)


def _capabilities_payload() -> dict[str, object]:
    return {
        "plugin": "archive-workbench-ai",
        "version": "0.1.0.dev20",
        "protocols": [EXPECTED_PROTOCOL],
        "handoff_schema_ids": [EXPECTED_HANDOFF_SCHEMA],
        "workflows": {
            "complete_exp01": {
                "command": "analyze",
                "internal_request_max_targets": 3,
                "consolidated_result": True,
                "consolidated_handoff": True,
            }
        },
        "profile_default_models": {
            "H24": "ggml-org/gemma-4-26B-A4B-it-GGUF:Q4_0",
            "L12": "unsloth/Qwen3.5-9B-GGUF:Q4_K_M",
        },
    }


def test_capabilities_require_complete_exp01_and_consolidated_handoff(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    executable = tmp_path / "aw-ai"
    executable.write_text("#!/bin/sh\n", encoding="utf-8")
    executable.chmod(0o755)

    def fake_run(command, **kwargs):
        assert command == [str(executable.resolve()), "capabilities", "--json"]
        assert kwargs["capture_output"] is True
        assert kwargs["text"] is True
        return subprocess.CompletedProcess(command, 0, json.dumps(_capabilities_payload()), "")

    monkeypatch.setattr("archive_workbench.ai_execution.subprocess.run", fake_run)
    capabilities = inspect_ai_capabilities(str(executable))

    assert capabilities.version == "0.1.0.dev20"
    assert capabilities.model_for_profile("H24") == "ggml-org/gemma-4-26B-A4B-it-GGUF:Q4_0"
    assert capabilities.model_for_profile("L12") == "unsloth/Qwen3.5-9B-GGUF:Q4_K_M"


def test_authorization_parameters_record_external_contract_and_scope() -> None:
    capabilities = AICapabilities(
        executable="/opt/aw-ai",
        plugin="archive-workbench-ai",
        version="0.1.0.dev20",
        profile_default_models={"H24": "model-h24", "L12": "model-l12"},
    )
    payload = ai_authorization_parameters(
        capabilities=capabilities,
        hardware_profile="H24",
        model_id="model-h24",
        export_profile_id="profile-1",
        export_profile_revision=7,
        scope_kind="explicit_pages",
        selected_unit_ids=(),
        selected_page_keys=(("digital-1", 2),),
    )

    assert payload["workflow"] == "complete_exp01"
    assert payload["protocol"] == EXPECTED_PROTOCOL
    assert payload["handoff_schema"] == EXPECTED_HANDOFF_SCHEMA
    assert payload["backend"] == "llama_cpp"
    assert payload["target_types"] == ["page"]
    assert payload["selected_page_keys"] == [["digital-1", 2]]


def test_run_analysis_uses_high_level_analyze_and_requires_both_outputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    input_path = tmp_path / "input.zip"
    input_path.write_bytes(b"EXP01")
    handoff_path = tmp_path / "handoff.zip"
    result_path = tmp_path / "result.zip"
    capabilities = AICapabilities(
        executable="/opt/aw-ai",
        plugin="archive-workbench-ai",
        version="0.1.0.dev20",
        profile_default_models={"H24": "model-h24", "L12": "model-l12"},
    )

    def fake_run(command, **kwargs):
        assert command[0:2] == ["/opt/aw-ai", "analyze"]
        assert "run" not in command
        assert command[command.index("--profile") + 1] == "H24"
        assert command[command.index("--target-type") + 1] == "page"
        handoff_path.write_bytes(b"handoff")
        result_path.write_bytes(b"result")
        payload = {
            "status": "ok",
            "analysis_id": "analysis-1",
            "handoff_sha256": "h1",
            "result_sha256": "r1",
            "target_count": 5,
            "proposal_count": 5,
            "internal_request_count": 2,
            "model_id": "model-h24",
            "handoff_schema_version": EXPECTED_HANDOFF_SCHEMA_VERSION,
        }
        return subprocess.CompletedProcess(command, 0, json.dumps(payload), "")

    monkeypatch.setattr("archive_workbench.ai_execution.subprocess.run", fake_run)
    result = run_ai_analysis(
        capabilities=capabilities,
        input_path=input_path,
        handoff_output_path=handoff_path,
        result_output_path=result_path,
        hardware_profile="H24",
        model_id="model-h24",
    )

    assert result.target_count == 5
    assert result.internal_request_count == 2
    assert result.handoff_path == handoff_path
    assert result.result_path == result_path


def test_resolve_ai_executable_prefers_new_environment_variable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    executable = tmp_path / "aw-ai"
    executable.write_text("#!/bin/sh\n", encoding="utf-8")
    executable.chmod(0o755)
    monkeypatch.setenv("ARCHIVE_WORKBENCH_AI_EXECUTABLE", str(executable))
    monkeypatch.setenv("ARCHIVE_WORKBENCH_AI01_EXECUTABLE", "/legacy/ignored")
    assert resolve_ai_executable() == str(executable.resolve())


def test_resolve_ai_executable_accepts_legacy_environment_variable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    executable = tmp_path / "aw-ai01"
    executable.write_text("#!/bin/sh\n", encoding="utf-8")
    executable.chmod(0o755)
    monkeypatch.delenv("ARCHIVE_WORKBENCH_AI_EXECUTABLE", raising=False)
    monkeypatch.setenv("ARCHIVE_WORKBENCH_AI01_EXECUTABLE", str(executable))
    assert resolve_ai_executable() == str(executable.resolve())


def test_bridge_capabilities_are_loaded_without_host_executable(tmp_path: Path) -> None:
    root = tmp_path / "bridge"
    root.mkdir()
    payload = _capabilities_payload()
    payload["bridge_protocol"] = "archive-workbench-ai-bridge/0.1"
    (root / "capabilities.json").write_text(json.dumps(payload), encoding="utf-8")

    capabilities = inspect_ai_capabilities(bridge_dir=root)

    assert capabilities.transport == "bridge"
    assert capabilities.executable == ""
    assert capabilities.bridge_dir == root.resolve()
    assert capabilities.model_for_profile("H24") == "ggml-org/gemma-4-26B-A4B-it-GGUF:Q4_0"


def test_bridge_analysis_exchanges_only_fixed_job_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "bridge"
    (root / "jobs").mkdir(parents=True)
    (root / "secret.token").write_text("a" * 64 + "\n", encoding="utf-8")
    input_path = tmp_path / "input.zip"
    input_path.write_bytes(b"EXP01")
    handoff_path = tmp_path / "handoff.zip"
    result_path = tmp_path / "result.zip"
    capabilities = AICapabilities(
        executable="",
        plugin="archive-workbench-ai",
        version="0.1.0.dev22",
        profile_default_models={"H24": "model-h24", "L12": "model-l12"},
        transport="bridge",
        bridge_dir=root,
    )
    handled = False

    def fake_sleep(_seconds: float) -> None:
        nonlocal handled
        if handled:
            return
        jobs = [
            path
            for path in (root / "jobs").iterdir()
            if path.is_dir() and not path.name.startswith(".")
        ]
        if not jobs:
            return
        job = jobs[0]
        request = json.loads((job / "request.json").read_text(encoding="utf-8"))
        assert request["bridge_protocol"] == "archive-workbench-ai-bridge/0.1"
        assert request["authorization"] == "a" * 64
        assert set(path.name for path in job.iterdir()) == {
            "input.exp01.zip",
            "request.json",
            "ready",
        }
        (job / "handoff.zip").write_bytes(b"handoff")
        (job / "result.zip").write_bytes(b"result")
        import hashlib

        response = {
            "status": "ok",
            "bridge_protocol": "archive-workbench-ai-bridge/0.1",
            "job_id": job.name,
            "analysis_id": "analysis-bridge",
            "handoff_sha256": hashlib.sha256(b"handoff").hexdigest(),
            "result_sha256": hashlib.sha256(b"result").hexdigest(),
            "model_id": "model-h24",
            "target_count": 1,
            "proposal_count": 1,
            "internal_request_count": 1,
            "handoff_schema_version": EXPECTED_HANDOFF_SCHEMA_VERSION,
        }
        (job / "response.json").write_text(json.dumps(response), encoding="utf-8")
        handled = True

    monkeypatch.setattr("archive_workbench.ai_execution.time.sleep", fake_sleep)
    result = run_ai_analysis(
        capabilities=capabilities,
        input_path=input_path,
        handoff_output_path=handoff_path,
        result_output_path=result_path,
        hardware_profile="H24",
        model_id="model-h24",
    )

    assert result.analysis_id == "analysis-bridge"
    assert handoff_path.read_bytes() == b"handoff"
    assert result_path.read_bytes() == b"result"
    job = next(
        path
        for path in (root / "jobs").iterdir()
        if path.is_dir() and not path.name.startswith(".")
    )
    assert (job / "consumed").is_file()
