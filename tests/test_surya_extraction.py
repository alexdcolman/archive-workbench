from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import fitz
from sqlalchemy import select

from archive_workbench.catalog import register_test_corpus
from archive_workbench.contracts.extraction import ExtractionProfile
from archive_workbench.contracts.test_corpus import TestCorpus as CorpusDefinition
from archive_workbench.db import (
    create_sqlite_engine,
    database_path,
    session_scope,
    upgrade_database,
)
from archive_workbench.db.models import ExtractedObject, ExtractionPage, ExtractionRun
from archive_workbench.decisions import load_decisions
from archive_workbench.extraction import (
    ExtractionDoctorReport,
    ExtractionProfileResolution,
    ExtractionSummary,
    ToolCheck,
    extract_documents,
    extract_documents_preferred,
    extraction_doctor,
    resolve_extraction_profile,
)
from archive_workbench.preprocessing import prepare_derivatives
from archive_workbench.surya_engine import (
    html_to_text,
    normalize_surya_page,
    list_surya_servers,
    resolve_surya_command,
    resolve_surya_torch_device,
    run_surya_cli_batch,
    stop_surya_servers,
)


def _payload() -> dict:
    return {
        "blocks": [
            {
                "label": "Text",
                "raw_label": "Text",
                "reading_order": 2,
                "html": "<p>Segundo párrafo</p>",
                "polygon": [[60, 200], [540, 200], [540, 280], [60, 280]],
                "bbox": [60, 200, 540, 280],
                "confidence": 0.88,
                "skipped": False,
                "error": False,
            },
            {
                "label": "SectionHeader",
                "raw_label": "SectionHeader",
                "reading_order": 0,
                "html": "<h2>INFORME</h2>",
                "polygon": [[60, 40], [540, 40], [540, 90], [60, 90]],
                "bbox": [60, 40, 540, 90],
                "confidence": 0.97,
                "skipped": False,
                "error": False,
            },
            {
                "label": "Picture",
                "raw_label": "Picture",
                "reading_order": 1,
                "html": "",
                "polygon": [[100, 100], [300, 100], [300, 190], [100, 190]],
                "bbox": [100, 100, 300, 190],
                "confidence": 0.91,
                "skipped": True,
                "error": False,
            },
        ],
        "image_bbox": [0, 0, 600, 400],
    }


def _write_pdf(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    document = fitz.open()
    page = document.new_page(width=600, height=400)
    page.insert_text((60, 80), "Documento de prueba")
    document.save(path)
    document.close()


def _corpus() -> CorpusDefinition:
    return CorpusDefinition.model_validate(
        {
            "corpus_name": "Prueba Surya",
            "created_by": "tests",
            "created_at": datetime.now(timezone.utc),
            "documents": [
                {
                    "test_id": "documento_surya",
                    "local_path": "corpus/caja/documento.pdf",
                    "short_description": "Documento Surya",
                    "archival_location": {
                        "fondo": "SiCH",
                        "caja": "Caja 1",
                        "documento": "Documento Surya",
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
                        "text_orientation": "upright",
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


def test_resolve_surya_command_keeps_bare_command_and_resolves_runtime_path(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)

    assert resolve_surya_command("surya_ocr") == "surya_ocr"
    assert resolve_surya_command(".venv-surya/bin/surya_ocr") == str(
        (tmp_path / ".venv-surya/bin/surya_ocr").resolve()
    )


def test_surya_torch_device_follows_requested_backend_when_auto() -> None:
    assert resolve_surya_torch_device(
        ExtractionProfile(backend="surya_cli", device="cpu")
    ) == "cpu"
    assert resolve_surya_torch_device(
        ExtractionProfile(backend="surya_cli", device="cuda")
    ) == "cuda"
    assert resolve_surya_torch_device(
        ExtractionProfile(backend="surya_cli", device="auto")
    ) == "auto"
    assert resolve_surya_torch_device(
        ExtractionProfile(
            backend="surya_cli",
            device="cuda",
            surya_torch_device="cpu",
        )
    ) == "cpu"


def test_html_to_text_keeps_visible_structure() -> None:
    assert html_to_text("<h2>Título</h2><p>Uno<br>Dos</p>") == "Título\nUno\nDos"


def test_normalize_surya_page_preserves_layout_order_types_and_geometry() -> None:
    decisions = load_decisions(Path(__file__).parents[1] / "config/decisions.yaml")
    records = normalize_surya_page(
        _payload(),
        digital_object_id="digital-1",
        extraction_run_id="run-1",
        page_number=1,
        width=600,
        height=400,
        decisions=decisions,
    )

    assert [record.object_type for record in records] == [
        "section_heading",
        "figure",
        "paragraph",
    ]
    assert [record.order_index for record in records] == [0, 1, 2]
    assert records[0].original_text == "INFORME"
    assert records[1].original_text == ""
    assert records[1].attributes["skipped"] is True
    assert records[2].confidence == 0.88
    assert records[0].geometry[0].polygon[0] == (0.1, 0.1)
    assert records[0].geometry[0].polygon[2] == (0.9, 0.225)


def test_surya_runner_uses_vllm_for_cuda_and_maps_pages(tmp_path: Path, monkeypatch) -> None:
    import archive_workbench.surya_engine as module

    source = tmp_path / "source.png"
    source.write_bytes(b"image")
    calls: list[tuple[list[str], dict[str, str]]] = []

    def fake_run(command, **kwargs):
        env = dict(kwargs["env"])
        calls.append((list(command), env))
        output_dir = Path(command[command.index("--output_dir") + 1])
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "results.json").write_text(
            json.dumps({"page_0001": [_payload()]}), encoding="utf-8"
        )
        return subprocess.CompletedProcess(command, 0, stdout="done", stderr="")

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    monkeypatch.setattr(module, "surya_version", lambda _command: "0.22.0")
    monkeypatch.setenv("LD_LIBRARY_PATH", "/usr/local/cuda-12.8/lib64")
    profile = ExtractionProfile(
        backend="surya_cli",
        device="cuda",
        surya_parallel=3,
        surya_keep_server=True,
        surya_torch_device="cpu",
        surya_clean_library_path=True,
        fallback_device="cpu",
    )

    outputs, version, log = run_surya_cli_batch(
        [(1, source)], tmp_path / "work", profile
    )

    assert version == "0.22.0"
    assert json.loads(outputs[1].read_text(encoding="utf-8"))["blocks"]
    assert calls[0][1]["SURYA_INFERENCE_BACKEND"] == "vllm"
    assert calls[0][1]["SURYA_INFERENCE_PARALLEL"] == "3"
    assert calls[0][1]["TORCH_DEVICE"] == "cpu"
    assert "LD_LIBRARY_PATH" not in calls[0][1]
    assert "--keep_server" in calls[0][0]
    assert "SURYA_INFERENCE_BACKEND=vllm" in log
    assert "TORCH_DEVICE=cpu" in log
    assert "SURYA_INFERENCE_KEEP_ALIVE=1" in log


def test_managed_container_forces_bundled_llamacpp_backend(
    tmp_path: Path, monkeypatch
) -> None:
    import archive_workbench.surya_engine as module

    source = tmp_path / "source.png"
    source.write_bytes(b"image")
    captured_env: dict[str, str] = {}

    def fake_run(command, **kwargs):
        captured_env.update(kwargs["env"])
        output_dir = Path(command[command.index("--output_dir") + 1])
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "results.json").write_text(
            json.dumps({"page_0001": [_payload()]}), encoding="utf-8"
        )
        return subprocess.CompletedProcess(command, 0, stdout="done", stderr="")

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    monkeypatch.setattr(module, "surya_version", lambda _command: "0.22.1")
    monkeypatch.setenv("ARCHIVE_WORKBENCH_SURYA_BACKEND", "llamacpp")
    monkeypatch.setenv("LLAMA_CPP_BINARY", "/opt/llama/llama-server")
    monkeypatch.setenv("LD_LIBRARY_PATH", "/opt/llama")

    outputs, _version, log = run_surya_cli_batch(
        [(1, source)],
        tmp_path / "work",
        ExtractionProfile(
            backend="surya_cli",
            device="cuda",
            surya_torch_device="cpu",
            surya_clean_library_path=True,
        ),
    )

    assert outputs[1].is_file()
    assert captured_env["SURYA_INFERENCE_BACKEND"] == "llamacpp"
    assert captured_env["TORCH_DEVICE"] == "cpu"
    assert captured_env["LD_LIBRARY_PATH"] == "/opt/llama"
    assert captured_env["SURYA_INFERENCE_TIMEOUT_SECONDS"] == "900"
    assert captured_env["SURYA_MAX_TOKENS_FULL_PAGE"] == "8192"
    assert "SURYA_INFERENCE_BACKEND=llamacpp" in log
    assert "SURYA_INFERENCE_TIMEOUT_SECONDS=900" in log
    assert "SURYA_MAX_TOKENS_FULL_PAGE=8192" in log
    assert "ARCHIVE_WORKBENCH_CLEAN_LD_LIBRARY_PATH=0" in log


def test_managed_llamacpp_respects_explicit_surya_limits(
    tmp_path: Path, monkeypatch
) -> None:
    import archive_workbench.surya_engine as module

    source = tmp_path / "source.png"
    source.write_bytes(b"image")
    captured_env: dict[str, str] = {}

    def fake_run(command, **kwargs):
        captured_env.update(kwargs["env"])
        output_dir = Path(command[command.index("--output_dir") + 1])
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "results.json").write_text(
            json.dumps({"page_0001": [_payload()]}), encoding="utf-8"
        )
        return subprocess.CompletedProcess(command, 0, stdout="done", stderr="")

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    monkeypatch.setattr(module, "surya_version", lambda _command: "0.22.1")
    monkeypatch.setenv("ARCHIVE_WORKBENCH_SURYA_BACKEND", "llamacpp")
    monkeypatch.setenv("SURYA_INFERENCE_TIMEOUT_SECONDS", "1200")
    monkeypatch.setenv("SURYA_MAX_TOKENS_FULL_PAGE", "6144")

    outputs, _version, log = run_surya_cli_batch(
        [(1, source)],
        tmp_path / "work",
        ExtractionProfile(backend="surya_cli", device="cpu"),
    )

    assert outputs[1].is_file()
    assert captured_env["SURYA_INFERENCE_TIMEOUT_SECONDS"] == "1200"
    assert captured_env["SURYA_MAX_TOKENS_FULL_PAGE"] == "6144"
    assert "SURYA_INFERENCE_TIMEOUT_SECONDS=1200" in log
    assert "SURYA_MAX_TOKENS_FULL_PAGE=6144" in log


def test_surya_runner_cpu_profile_sets_auxiliary_cpu_when_auto(
    tmp_path: Path, monkeypatch
) -> None:
    import archive_workbench.surya_engine as module

    source = tmp_path / "source.png"
    source.write_bytes(b"image")
    captured_env: dict[str, str] = {}

    def fake_run(command, **kwargs):
        captured_env.update(kwargs["env"])
        output_dir = Path(command[command.index("--output_dir") + 1])
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "results.json").write_text(
            json.dumps({"page_0001": [_payload()]}), encoding="utf-8"
        )
        return subprocess.CompletedProcess(command, 0, stdout="done", stderr="")

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    monkeypatch.setattr(module, "surya_version", lambda _command: "0.22.0")
    monkeypatch.delenv("ARCHIVE_WORKBENCH_SURYA_BACKEND", raising=False)
    monkeypatch.delenv("SURYA_INFERENCE_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("SURYA_MAX_TOKENS_FULL_PAGE", raising=False)

    outputs, _version, log = run_surya_cli_batch(
        [(1, source)],
        tmp_path / "work",
        ExtractionProfile(backend="surya_cli", device="cpu"),
    )

    assert outputs[1].is_file()
    assert captured_env["SURYA_INFERENCE_BACKEND"] == "llamacpp"
    assert captured_env["TORCH_DEVICE"] == "cpu"
    assert "SURYA_INFERENCE_TIMEOUT_SECONDS" not in captured_env
    assert "SURYA_MAX_TOKENS_FULL_PAGE" not in captured_env
    assert "TORCH_DEVICE=cpu" in log


def test_surya_runner_falls_back_once_to_cpu(tmp_path: Path, monkeypatch) -> None:
    import archive_workbench.surya_engine as module

    source = tmp_path / "source.png"
    source.write_bytes(b"image")
    backends: list[str] = []

    def fake_run(command, **kwargs):
        backend = kwargs["env"].get("SURYA_INFERENCE_BACKEND", "auto")
        backends.append(backend)
        if backend == "vllm":
            return subprocess.CompletedProcess(
                command, 1, stdout="", stderr="CUDA backend unavailable"
            )
        output_dir = Path(command[command.index("--output_dir") + 1])
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "results.json").write_text(
            json.dumps({"page_0001.png": [_payload()]}), encoding="utf-8"
        )
        return subprocess.CompletedProcess(command, 0, stdout="done", stderr="")

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    monkeypatch.setattr(module, "surya_version", lambda _command: "0.22.0")
    profile = ExtractionProfile(
        backend="surya_cli",
        device="cuda",
        fallback_device="cpu",
        retry_on_accelerator_error=True,
    )

    outputs, _version, log = run_surya_cli_batch(
        [(1, source)], tmp_path / "work", profile
    )

    assert outputs[1].is_file()
    assert backends == ["vllm", "llamacpp"]
    assert "ARCHIVE_WORKBENCH_FALLBACK_DEVICE=cpu" in log


def test_surya_doctor_does_not_require_tesseract(tmp_path: Path, monkeypatch) -> None:
    import archive_workbench.extraction as module

    def fake_probe(command, timeout=30):
        del timeout
        if command[0] == "surya_ocr":
            return True, "surya"
        if command[0] == "llama-server":
            return True, "llama.cpp"
        return False, "ausente"

    monkeypatch.setattr(module, "_run_probe", fake_probe)
    monkeypatch.setattr(module, "surya_version", lambda _command: "0.22.0")
    monkeypatch.setattr(
        module,
        "_surya_auxiliary_torch_check",
        lambda profile: (
            resolve_surya_torch_device(profile) == "cpu",
            f"dispositivo auxiliar {resolve_surya_torch_device(profile)}",
        ),
    )
    report = extraction_doctor(
        ExtractionProfile(backend="surya_cli", device="cpu", surya_command="surya_ocr")
    )

    assert report.ready is True
    checks = {check.name: check for check in report.checks}
    assert checks["Surya CLI"].required is True
    assert checks["Backend de inferencia Surya"].ok is True
    assert checks["Modelos auxiliares Surya"].ok is True
    assert "dispositivo auxiliar cpu" in checks["Modelos auxiliares Surya"].detail
    assert checks["Tesseract"].required is False


def test_managed_gpu_surya_doctor_does_not_require_nested_docker(monkeypatch) -> None:
    import archive_workbench.extraction as module

    calls: list[list[str]] = []

    def fake_probe(command, timeout=30):
        del timeout
        calls.append(list(command))
        if command[0] == "/opt/llama/llama-server":
            return True, "llama.cpp CUDA"
        if command[0] == "nvidia-smi":
            return True, "NVIDIA GeForce RTX 3090, 24576 MiB"
        if command[0] == "surya_ocr":
            return True, "surya"
        if command[0] == "docker":
            raise AssertionError("el runtime administrado no debe requerir Docker anidado")
        return True, "ok"

    monkeypatch.setattr(module, "_run_probe", fake_probe)
    monkeypatch.setattr(module, "surya_version", lambda _command: "0.22.1")
    monkeypatch.setattr(
        module,
        "_surya_auxiliary_torch_check",
        lambda _profile: (True, "torch cpu; CUDA disponible"),
    )
    monkeypatch.setenv("ARCHIVE_WORKBENCH_SURYA_BACKEND", "llamacpp")
    monkeypatch.setenv("ARCHIVE_WORKBENCH_RUNTIME_VARIANT", "gpu")
    monkeypatch.setenv("LLAMA_CPP_BINARY", "/opt/llama/llama-server")

    report = extraction_doctor(
        ExtractionProfile(backend="surya_cli", device="auto", surya_command="surya_ocr")
    )

    assert report.ready is True
    checks = {check.name: check for check in report.checks}
    backend = checks["Backend de inferencia Surya"]
    assert backend.ok is True
    assert "ruta GPU administrada" in backend.detail
    assert "NVIDIA GeForce RTX 3090" in backend.detail
    assert not any(call[0] == "docker" for call in calls)


def test_managed_surya_doctor_probes_configured_bundled_llama_binary(monkeypatch) -> None:
    import archive_workbench.extraction as module

    calls: list[list[str]] = []

    def fake_probe(command, timeout=30):
        del timeout
        calls.append(list(command))
        return True, "ok"

    monkeypatch.setattr(module, "_run_probe", fake_probe)
    monkeypatch.setattr(module, "surya_version", lambda _command: "0.22.1")
    monkeypatch.setattr(
        module,
        "_surya_auxiliary_torch_check",
        lambda _profile: (True, "torch cpu"),
    )
    monkeypatch.setenv("ARCHIVE_WORKBENCH_SURYA_BACKEND", "llamacpp")
    monkeypatch.setenv("LLAMA_CPP_BINARY", "/opt/llama/llama-server")

    report = extraction_doctor(
        ExtractionProfile(backend="surya_cli", device="cpu", surya_command="surya_ocr")
    )

    assert report.ready is True
    assert ["/opt/llama/llama-server", "--version"] in calls


def test_surya_extraction_is_persisted_as_candidate(tmp_path: Path) -> None:
    root = tmp_path / "project"
    _write_pdf(root / "corpus/caja/documento.pdf")
    decisions = load_decisions(Path(__file__).parents[1] / "config/decisions.yaml")
    profile = ExtractionProfile(
        profile_key="surya_test_v1",
        backend="surya_cli",
        device="cpu",
        minimum_characters_per_page_warning=5,
    )

    def fake_runner(source_images, output_dir, _profile):
        output_dir.mkdir(parents=True, exist_ok=True)
        outputs = {}
        for page_number, source_image in source_images:
            assert source_image.is_file()
            path = output_dir / f"page_{page_number:04d}.json"
            path.write_text(json.dumps(_payload()), encoding="utf-8")
            outputs[page_number] = path
        return outputs, "0.22.0", "SURYA_INFERENCE_BACKEND=llamacpp"

    upgrade_database(root)
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            register_test_corpus(
                session,
                project_root=root,
                decisions=decisions,
                corpus=_corpus(),
            )
        with session_scope(engine) as session:
            prepare_derivatives(session, project_root=root, decisions=decisions)
        with session_scope(engine) as session:
            summary = extract_documents(
                session,
                project_root=root,
                decisions=decisions,
                profile=profile,
                created_by="Alex",
                selection_policy="never",
                surya_runner=fake_runner,
            )
        with session_scope(engine) as session:
            run = session.scalar(select(ExtractionRun))
            page = session.scalar(select(ExtractionPage))
            objects = session.scalars(
                select(ExtractedObject).order_by(ExtractedObject.order_index)
            ).all()
    finally:
        engine.dispose()

    assert summary.failed == 0
    assert summary.runs_created == 1
    assert summary.objects_created == 3
    assert run is not None and run.engine == "surya_cli"
    assert run.engine_version == "0.22.0"
    assert run.is_current is True
    assert page is not None and page.object_count == 3
    assert [item.object_type for item in objects] == [
        "section_heading",
        "figure",
        "paragraph",
    ]


def test_surya_server_status_and_stop_use_managed_container_names(monkeypatch) -> None:
    import archive_workbench.surya_engine as module

    calls: list[list[str]] = []

    def fake_run(command, **kwargs):
        del kwargs
        calls.append(list(command))
        if command[1] == "ps":
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=(
                    "surya-vllm-123\tUp 2 minutes\tvllm/vllm-openai:v0.20.1\n"
                    "surya-vllm-456\tExited (0) 1 hour ago\tvllm/vllm-openai:v0.20.1\n"
                ),
                stderr="",
            )
        if command[1] == "stop":
            return subprocess.CompletedProcess(command, 0, stdout=command[-1], stderr="")
        raise AssertionError(command)

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    servers = list_surya_servers()
    stopped = stop_surya_servers()

    assert [(item.name, item.running) for item in servers] == [
        ("surya-vllm-123", True),
        ("surya-vllm-456", False),
    ]
    assert stopped == ["surya-vllm-123"]
    assert ["docker", "stop", "surya-vllm-123"] in calls
    assert ["docker", "stop", "surya-vllm-456"] not in calls


def test_preferred_profile_resolves_to_docling_fallback(tmp_path: Path, monkeypatch) -> None:
    import archive_workbench.extraction as module

    fallback_path = tmp_path / "config/extraction_docling_es.yaml"
    fallback_path.parent.mkdir(parents=True)
    fallback_path.write_text(
        "schema_version: '1.0'\n"
        "profile_key: docling_fallback\n"
        "backend: docling_cli\n",
        encoding="utf-8",
    )
    primary = ExtractionProfile(
        profile_key="surya_preferred",
        backend="surya_cli",
        fallback_profile="config/extraction_docling_es.yaml",
    )

    def fake_doctor(profile):
        ready = profile.backend == "docling_cli"
        return ExtractionDoctorReport(
            [ToolCheck(profile.backend, ready, "ok" if ready else "ausente", required=True)]
        )

    monkeypatch.setattr(module, "extraction_doctor", fake_doctor)
    resolution = resolve_extraction_profile(tmp_path, primary)

    assert resolution.ready is True
    assert resolution.fallback_used is True
    assert resolution.effective.profile_key == "docling_fallback"
    assert resolution.effective.backend == "docling_cli"
    assert "surya_cli: ausente" in (resolution.reason or "")


def test_runtime_failure_retries_only_failed_sources_with_fallback(monkeypatch) -> None:
    import archive_workbench.extraction as module

    primary = ExtractionProfile(
        profile_key="surya_preferred",
        backend="surya_cli",
        fallback_profile="config/extraction_docling_es.yaml",
    )
    fallback = ExtractionProfile(profile_key="docling_fallback", backend="docling_cli")
    ready = ExtractionDoctorReport([ToolCheck("runtime", True, "ok", required=True)])
    resolution = ExtractionProfileResolution(
        requested=primary,
        effective=primary,
        requested_report=ready,
        effective_report=ready,
    )
    calls: list[tuple[str, set[str] | None, bool]] = []

    monkeypatch.setattr(module, "resolve_extraction_profile", lambda *_args: resolution)
    monkeypatch.setattr(module, "_fallback_profile", lambda *_args: (fallback, ready))

    def fake_extract(_session, *, profile, source_keys=None, force=False, **_kwargs):
        calls.append((profile.profile_key, source_keys, force))
        if profile.backend == "surya_cli":
            return ExtractionSummary(
                objects_seen=2,
                runs_created=1,
                failed=1,
                pages_processed=1,
                objects_created=5,
                characters_created=100,
                warnings=["doc_b: Surya falló"],
                failed_source_keys=["doc_b"],
            )
        return ExtractionSummary(
            objects_seen=1,
            runs_created=1,
            pages_processed=1,
            objects_created=4,
            characters_created=90,
        )

    monkeypatch.setattr(module, "extract_documents", fake_extract)
    summary = extract_documents_preferred(
        object(),
        project_root=".",
        decisions=object(),
        profile=primary,
        source_keys={"doc_a", "doc_b"},
        selection_policy="never",
    )

    assert calls == [
        ("surya_preferred", {"doc_a", "doc_b"}, False),
        ("docling_fallback", {"doc_b"}, True),
    ]
    assert summary.failed == 0
    assert summary.pages_processed == 2
    assert summary.objects_created == 9
    assert summary.characters_created == 190
    assert summary.failed_source_keys == []
    assert any("Fallback automático completado" in item for item in summary.warnings)
