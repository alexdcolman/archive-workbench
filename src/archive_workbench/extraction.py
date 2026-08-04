from __future__ import annotations

import json
import os
from importlib import metadata
import shutil
import shlex
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator
from uuid import NAMESPACE_URL

import yaml
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from archive_workbench.sources import PROCESSABLE_SOURCE_TYPES
from archive_workbench.contracts.decisions import ProjectDecisions
from archive_workbench.contracts.extraction import (
    ExtractedObjectRecord,
    ExtractionManifest,
    ExtractionProfile,
    ImageManifestRecord,
    PageGeometry,
    ParagraphExportRecord,
)
from archive_workbench.db.models import (
    ArchivalUnit,
    DerivativeAsset,
    DigitalObject,
    EditablePage,
    ExtractedObject,
    ExtractionPage,
    ExtractionPageSelection,
    ExtractionPageSelectionRevision,
    ExtractionRun,
    PreprocessingRun,
    SourceRegistration,
)
from archive_workbench.domain.enums import ExtractionStatus, MediaType
from archive_workbench.identity import new_id, sha256_file, sha256_json, stable_id
from archive_workbench.io.jsonl import write_models_atomic
from archive_workbench.page_quality import assess_extraction_page_quality
from archive_workbench.tesseract_engine import (
    normalize_tesseract_result,
    prepare_image_variant,
    run_tesseract_page,
    text_quality_metrics,
    write_tesseract_raw,
)
from archive_workbench.surya_engine import (
    normalize_surya_page,
    resolve_surya_command,
    resolve_surya_torch_device,
    run_surya_cli_batch,
    surya_version,
)


@dataclass(slots=True)
class ToolCheck:
    name: str
    ok: bool
    detail: str
    required: bool = True


@dataclass(slots=True)
class ExtractionDoctorReport:
    checks: list[ToolCheck]

    @property
    def ready(self) -> bool:
        return all(check.ok for check in self.checks if check.required)


@dataclass(slots=True)
class ExtractionSummary:
    objects_seen: int = 0
    runs_created: int = 0
    runs_reused: int = 0
    failed: int = 0
    pages_processed: int = 0
    objects_created: int = 0
    paragraphs_created: int = 0
    characters_created: int = 0
    warnings: list[str] = field(default_factory=list)
    failed_source_keys: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ExtractionProfileResolution:
    requested: ExtractionProfile
    effective: ExtractionProfile
    requested_report: ExtractionDoctorReport
    effective_report: ExtractionDoctorReport
    fallback_used: bool = False
    reason: str | None = None

    @property
    def ready(self) -> bool:
        return self.effective_report.ready


@dataclass(slots=True)
class ExtractionStatusRow:
    source_key: str
    title: str
    media_type: str
    page_count: int | None
    run_status: str | None
    profile_key: str | None
    pages: int
    objects: int
    characters: int
    output_root: str | None
    quality_status: str | None
    quality_score: float | None


@dataclass(slots=True)
class ExtractionHistoryRow:
    run_id: str
    source_key: str
    profile_key: str | None
    status: str
    quality_status: str
    pages: int
    objects: int
    characters: int
    is_current: bool
    created_at: datetime


@dataclass(slots=True)
class SelectedExtractionStatusRow:
    source_key: str
    title: str
    page_count: int | None
    selected_pages: int
    missing_pages: list[int]
    profiles: list[str]
    rejected_pages: list[int]


class DoclingExecutionError(RuntimeError):
    """Error de Docling que conserva el diagnóstico completo del subproceso."""

    def __init__(self, message: str, *, log_text: str = "") -> None:
        super().__init__(message)
        self.log_text = log_text


def _accelerator_failure(text: str) -> bool:
    normalized = text.lower()
    markers = (
        "cudnn_",
        "cudnn status",
        "cuda error",
        "cuda runtime",
        "cuda out of memory",
        "cublas_status",
        "no kernel image",
    )
    return any(marker in normalized for marker in markers)


def _command_log(command: list[str], result: subprocess.CompletedProcess[str]) -> str:
    parts = [f"$ {shlex.join(command)}", f"exit_code={result.returncode}"]
    if result.stdout and result.stdout.strip():
        parts.extend(["--- stdout ---", result.stdout.strip()])
    if result.stderr and result.stderr.strip():
        parts.extend(["--- stderr ---", result.stderr.strip()])
    return "\n".join(parts)


DoclingBatchRunner = Callable[
    [list[tuple[int, Path]], Path, ExtractionProfile],
    tuple[dict[int, Path], str | None, str],
]
SuryaBatchRunner = Callable[
    [list[tuple[int, Path]], Path, ExtractionProfile],
    tuple[dict[int, Path], str | None, str],
]


LABEL_MAP: dict[str, str] = {
    "title": "title",
    "section_header": "section_heading",
    "paragraph": "paragraph",
    "text": "paragraph",
    "list_item": "list_item",
    "table": "table",
    "document_index": "table_of_contents",
    "picture": "figure",
    "chart": "chart",
    "caption": "caption",
    "footnote": "footnote",
    "page_header": "page_header",
    "page_footer": "page_footer",
    "handwritten_text": "handwritten_region",
    "field_heading": "form_field",
    "field_value": "form_field",
    "field_key": "form_field",
    "field_hint": "form_field",
    "field_item": "form_field",
    "form": "form_field",
    "key_value_region": "form_field",
    "field_region": "form_field",
}

CONTENT_COLLECTIONS = (
    "texts",
    "tables",
    "pictures",
    "key_value_items",
    "form_items",
    "field_regions",
    "field_items",
)


def load_extraction_profile(path: str | Path) -> ExtractionProfile:
    source = Path(path)
    try:
        payload = yaml.safe_load(source.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"No existe el perfil de extracción: {source}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"El perfil de extracción debe ser un objeto YAML: {source}")
    return ExtractionProfile.model_validate(payload)


def _run_probe(command: list[str], timeout: int = 30) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            command,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError:
        return False, "no encontrado en PATH"
    except subprocess.TimeoutExpired:
        return False, "no respondió dentro del tiempo esperado"
    output = (result.stdout or result.stderr or "").strip()
    first_line = output.splitlines()[0] if output else f"código {result.returncode}"
    return result.returncode == 0, first_line


def _surya_url_check(url: str) -> tuple[bool, str]:
    from urllib.error import HTTPError, URLError
    from urllib.request import urlopen

    endpoint = url.rstrip("/") + "/models"
    try:
        with urlopen(endpoint, timeout=5) as response:  # noqa: S310 - URL local/configurada
            status = int(getattr(response, "status", 200))
    except HTTPError as exc:
        return False, f"{endpoint}: HTTP {exc.code}"
    except (URLError, OSError, TimeoutError) as exc:
        return False, f"{endpoint}: {type(exc).__name__}: {exc}"
    return 200 <= status < 400, f"{endpoint}: HTTP {status}"


def _surya_local_backend_check(profile: ExtractionProfile) -> tuple[bool, str]:
    if profile.device == "cpu":
        ok, detail = _run_probe(["llama-server", "--version"])
        return ok, f"llama.cpp: {detail}"

    nvidia_ok, nvidia_detail = _run_probe(
        ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"]
    )
    docker_ok, docker_detail = _run_probe(["docker", "info", "--format", "{{json .Runtimes}}"])
    nvidia_runtime = docker_ok and "nvidia" in docker_detail.lower()
    gpu_ready = nvidia_ok and docker_ok and nvidia_runtime
    if profile.device == "cuda":
        return (
            gpu_ready,
            f"NVIDIA: {nvidia_detail}; Docker: {docker_detail}; "
            f"runtime nvidia {'disponible' if nvidia_runtime else 'no detectado'}",
        )

    cpu_ok, cpu_detail = _run_probe(["llama-server", "--version"])
    if gpu_ready:
        return True, f"ruta GPU disponible ({nvidia_detail})"
    if cpu_ok:
        return True, f"ruta CPU disponible ({cpu_detail}); GPU no lista: {nvidia_detail}"
    return False, (
        "no hay backend local utilizable: "
        f"GPU ({nvidia_detail}; {docker_detail}) y llama-server ({cpu_detail})"
    )


def _surya_auxiliary_torch_check(profile: ExtractionProfile) -> tuple[bool, str]:
    resolved_command = resolve_surya_command(profile.surya_command)
    command_path = Path(shutil.which(resolved_command) or resolved_command)
    sibling_python = command_path.parent / "python"
    runtime_python = sibling_python if sibling_python.is_file() else Path(sys.executable)

    env = os.environ.copy()
    if profile.surya_clean_library_path:
        env.pop("LD_LIBRARY_PATH", None)
    torch_device = resolve_surya_torch_device(profile)
    if torch_device != "auto":
        env["TORCH_DEVICE"] = torch_device
    script = r"""
import os
import torch
import torch.nn.functional as F

device = os.environ.get("TORCH_DEVICE", "auto")
resolved = device
if device == "auto":
    resolved = "cuda" if torch.cuda.is_available() else "cpu"
if resolved == "cuda":
    x = torch.zeros((1, 1, 8, 8), device="cuda")
    kernel = torch.ones((1, 1, 3, 3), device="cuda")
    F.conv2d(x, kernel)
    torch.cuda.synchronize()
else:
    torch.zeros((1, 1, 8, 8), device="cpu")
print(f"torch {torch.__version__}; dispositivo auxiliar {resolved}; CUDA {'disponible' if torch.cuda.is_available() else 'no disponible'}")
"""
    try:
        result = subprocess.run(
            [str(runtime_python), "-c", script],
            text=True,
            capture_output=True,
            timeout=60,
            check=False,
            env=env,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return False, f"{type(exc).__name__}: {exc}"
    output = (result.stdout or result.stderr or "").strip()
    detail = output.splitlines()[-1] if output else f"código {result.returncode}"
    return result.returncode == 0, detail


def extraction_doctor(profile: ExtractionProfile) -> ExtractionDoctorReport:
    checks: list[ToolCheck] = []

    docling_required = profile.backend == "docling_cli"
    docling_ok, probe_detail = _run_probe([profile.docling_command, "--help"])
    try:
        package_version = metadata.version("docling")
    except metadata.PackageNotFoundError:
        package_version = None
    detail = f"docling {package_version}" if docling_ok and package_version else probe_detail
    checks.append(ToolCheck("Docling CLI", docling_ok, detail, required=docling_required))

    tesseract_required = profile.backend == "tesseract_tsv" or (
        profile.backend == "docling_cli" and profile.ocr_engine == "tesseract"
    )
    tesseract_ok, tesseract_detail = _run_probe([profile.tesseract_command, "--version"])
    checks.append(
        ToolCheck("Tesseract", tesseract_ok, tesseract_detail, required=tesseract_required)
    )

    langs_ok = False
    langs_detail = "no requerido por este backend"
    if tesseract_required and tesseract_ok:
        try:
            result = subprocess.run(
                [profile.tesseract_command, "--list-langs"],
                text=True,
                capture_output=True,
                timeout=30,
                check=False,
            )
            languages = {
                line.strip()
                for line in result.stdout.splitlines()
                if line.strip() and not line.lower().startswith("list of available")
            }
            missing = [lang for lang in profile.ocr_languages if lang not in languages]
            langs_ok = result.returncode == 0 and not missing
            langs_detail = (
                f"disponibles: {', '.join(sorted(languages)) or '-'}"
                if not missing
                else f"faltan: {', '.join(missing)}"
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            langs_detail = "no se pudo consultar"
    checks.append(
        ToolCheck(
            "Idiomas OCR",
            langs_ok or not tesseract_required,
            langs_detail,
            required=tesseract_required,
        )
    )

    surya_required = profile.backend == "surya_cli"
    surya_command = resolve_surya_command(profile.surya_command)
    surya_ok, surya_detail = _run_probe([surya_command, "--help"])
    installed_version = surya_version(profile.surya_command) if surya_ok else None
    if installed_version:
        surya_detail = f"surya-ocr {installed_version}"
    checks.append(ToolCheck("Surya CLI", surya_ok, surya_detail, required=surya_required))
    if surya_required:
        inference_url = profile.surya_inference_url or os.environ.get("SURYA_INFERENCE_URL")
        if inference_url:
            backend_ok, backend_detail = _surya_url_check(inference_url)
            backend_name = "Servidor Surya configurado"
        else:
            backend_ok, backend_detail = _surya_local_backend_check(profile)
            backend_name = "Backend de inferencia Surya"
        checks.append(ToolCheck(backend_name, backend_ok, backend_detail, required=True))

    if surya_required:
        auxiliary_ok, auxiliary_detail = _surya_auxiliary_torch_check(profile)
        checks.append(
            ToolCheck(
                "Modelos auxiliares Surya",
                auxiliary_ok,
                auxiliary_detail,
                required=True,
            )
        )
    else:
        try:
            import torch  # type: ignore[import-not-found]
            import torch.nn.functional as torch_functional  # type: ignore[import-not-found]

            cuda = bool(torch.cuda.is_available())
            detail = f"torch {torch.__version__}; CUDA {'disponible' if cuda else 'no disponible'}"
            if cuda:
                detail += f"; {torch.cuda.get_device_name(0)}"
            checks.append(ToolCheck("Aceleración detectada", True, detail, required=False))
            if cuda:
                try:
                    sample = torch.zeros((1, 1, 8, 8), device="cuda")
                    kernel = torch.ones((1, 1, 3, 3), device="cuda")
                    torch_functional.conv2d(sample, kernel)
                    torch.cuda.synchronize()
                    checks.append(
                        ToolCheck(
                            "Runtime CUDA/cuDNN",
                            True,
                            "convolución CUDA ejecutada",
                            required=False,
                        )
                    )
                except Exception as exc:  # pragma: no cover - depende del host
                    fallback = (
                        f"; se usará fallback {profile.fallback_device}"
                        if profile.retry_on_accelerator_error and profile.fallback_device
                        else ""
                    )
                    checks.append(
                        ToolCheck(
                            "Runtime CUDA/cuDNN",
                            False,
                            f"{type(exc).__name__}: {exc}{fallback}",
                            required=False,
                        )
                    )
        except ImportError:
            checks.append(
                ToolCheck(
                    "Aceleración detectada",
                    True,
                    "PyTorch no importable en el entorno principal; los backends CLI pueden estar aislados",
                    required=False,
                )
            )

    return ExtractionDoctorReport(checks)


def _profile_path(project_root: str | Path, value: str) -> Path:
    path = Path(value).expanduser()
    if path.is_absolute():
        return path
    return Path(project_root) / path


def resolve_extraction_profile(
    project_root: str | Path,
    profile: ExtractionProfile,
) -> ExtractionProfileResolution:
    requested_report = extraction_doctor(profile)
    if requested_report.ready or not profile.fallback_profile:
        return ExtractionProfileResolution(
            requested=profile,
            effective=profile,
            requested_report=requested_report,
            effective_report=requested_report,
        )

    fallback_path = _profile_path(project_root, profile.fallback_profile)
    try:
        fallback = load_extraction_profile(fallback_path)
    except (OSError, ValueError) as exc:
        return ExtractionProfileResolution(
            requested=profile,
            effective=profile,
            requested_report=requested_report,
            effective_report=requested_report,
            reason=f"No se pudo cargar el fallback {fallback_path}: {exc}",
        )
    fallback_report = extraction_doctor(fallback)
    failures = [
        f"{check.name}: {check.detail}"
        for check in requested_report.checks
        if check.required and not check.ok
    ]
    reason = "; ".join(failures) or "el backend preferido no está disponible"
    return ExtractionProfileResolution(
        requested=profile,
        effective=fallback if fallback_report.ready else profile,
        requested_report=requested_report,
        effective_report=fallback_report if fallback_report.ready else requested_report,
        fallback_used=fallback_report.ready,
        reason=reason,
    )


def _fallback_profile(
    project_root: str | Path,
    profile: ExtractionProfile,
) -> tuple[ExtractionProfile, ExtractionDoctorReport] | None:
    if not profile.fallback_profile:
        return None
    try:
        fallback = load_extraction_profile(_profile_path(project_root, profile.fallback_profile))
    except (OSError, ValueError):
        return None
    report = extraction_doctor(fallback)
    return (fallback, report) if report.ready else None


def _merge_preferred_summaries(
    primary: ExtractionSummary,
    fallback: ExtractionSummary,
    *,
    fallback_profile: ExtractionProfile,
) -> ExtractionSummary:
    failed_keys = set(primary.failed_source_keys)
    recovered = failed_keys - set(fallback.failed_source_keys)
    warnings = list(primary.warnings)
    if recovered:
        warnings.append(
            "Fallback automático completado con "
            f"{fallback_profile.profile_key}: {', '.join(sorted(recovered))}"
        )
    warnings.extend(fallback.warnings)
    return ExtractionSummary(
        objects_seen=primary.objects_seen,
        runs_created=primary.runs_created + fallback.runs_created,
        runs_reused=primary.runs_reused + fallback.runs_reused,
        failed=fallback.failed,
        pages_processed=primary.pages_processed + fallback.pages_processed,
        objects_created=primary.objects_created + fallback.objects_created,
        paragraphs_created=primary.paragraphs_created + fallback.paragraphs_created,
        characters_created=primary.characters_created + fallback.characters_created,
        warnings=warnings,
        failed_source_keys=list(fallback.failed_source_keys),
    )


def extract_documents_preferred(
    session: Session,
    *,
    project_root: str | Path,
    decisions: ProjectDecisions,
    profile: ExtractionProfile,
    source_keys: set[str] | None = None,
    selected_pages: set[int] | None = None,
    force: bool = False,
    created_by: str = "local_user",
    selection_policy: str = "if_unselected",
    runner: DoclingBatchRunner | None = None,
    surya_runner: SuryaBatchRunner | None = None,
) -> ExtractionSummary:
    if runner is None:
        runner = run_docling_cli_batch
    if surya_runner is None:
        surya_runner = run_surya_cli_batch
    resolution = resolve_extraction_profile(project_root, profile)
    if not resolution.ready:
        failures = [
            f"{check.name}: {check.detail}"
            for check in resolution.effective_report.checks
            if check.required and not check.ok
        ]
        detail = "; ".join(failures) or resolution.reason or "entorno no disponible"
        raise RuntimeError(f"El entorno de extracción no está listo: {detail}")

    if resolution.fallback_used:
        summary = extract_documents(
            session,
            project_root=project_root,
            decisions=decisions,
            profile=resolution.effective,
            source_keys=source_keys,
            selected_pages=selected_pages,
            force=force,
            created_by=created_by,
            selection_policy=selection_policy,
            runner=runner,
            surya_runner=surya_runner,
        )
        summary.warnings.insert(
            0,
            "Backend preferido no disponible; se utilizó automáticamente "
            f"{resolution.effective.profile_key}. Motivo: {resolution.reason}",
        )
        return summary

    primary = extract_documents(
        session,
        project_root=project_root,
        decisions=decisions,
        profile=profile,
        source_keys=source_keys,
        selected_pages=selected_pages,
        force=force,
        created_by=created_by,
        selection_policy=selection_policy,
        runner=runner,
        surya_runner=surya_runner,
    )
    if not primary.failed_source_keys:
        return primary

    fallback_entry = _fallback_profile(project_root, profile)
    if fallback_entry is None:
        return primary
    fallback_profile, _fallback_report = fallback_entry
    failed_keys = set(primary.failed_source_keys)
    fallback_summary = extract_documents(
        session,
        project_root=project_root,
        decisions=decisions,
        profile=fallback_profile,
        source_keys=failed_keys,
        selected_pages=selected_pages,
        force=True,
        created_by=created_by,
        selection_policy=selection_policy,
        runner=runner,
        surya_runner=surya_runner,
    )
    return _merge_preferred_summaries(
        primary,
        fallback_summary,
        fallback_profile=fallback_profile,
    )


def _relative(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _docling_version(command: str) -> str | None:
    try:
        return metadata.version("docling")
    except metadata.PackageNotFoundError:
        ok, detail = _run_probe([command, "--help"])
        return detail if ok else None


def _tesseract_version(command: str) -> str | None:
    ok, detail = _run_probe([command, "--version"])
    return detail if ok else None


def _run_docling_cli_attempt(
    source_images: list[tuple[int, Path]],
    attempt_dir: Path,
    profile: ExtractionProfile,
    *,
    device: str,
) -> tuple[dict[int, Path], str]:
    input_dir = attempt_dir / "input"
    output_dir = attempt_dir / "output"
    input_dir.mkdir(parents=True, exist_ok=False)
    output_dir.mkdir(parents=True, exist_ok=False)

    expected_stems: dict[int, str] = {}
    for page_number, source_image in source_images:
        stem = f"page_{page_number:04d}"
        destination = input_dir / f"{stem}{source_image.suffix.lower()}"
        try:
            os.link(source_image, destination)
        except OSError:
            shutil.copy2(source_image, destination)
        expected_stems[page_number] = stem

    command = [
        profile.docling_command,
        "convert",
        "--from",
        "image",
        "--to",
        "json",
        "--image-export-mode",
        profile.image_export_mode,
        "--pipeline",
        profile.pipeline,
        "--ocr-engine",
        profile.ocr_engine,
        "--ocr-lang",
        ",".join(profile.ocr_languages),
        "--table-mode",
        profile.table_mode,
        "--device",
        device,
        "--num-threads",
        str(profile.num_threads),
        "--page-batch-size",
        str(profile.page_batch_size),
        "--document-timeout",
        str(profile.document_timeout_seconds),
        "--abort-on-error",
        "--output",
        str(output_dir),
    ]
    command.append("--force-ocr" if profile.force_ocr else "--no-force-ocr")
    command.append("--tables" if profile.extract_tables else "--no-tables")
    command.append("--ocr")
    if profile.psm is not None:
        command.extend(["--psm", str(profile.psm)])
    if profile.artifacts_path:
        command.extend(["--artifacts-path", profile.artifacts_path])
    command.append(str(input_dir))

    env = os.environ.copy()
    if profile.artifacts_path:
        env["DOCLING_ARTIFACTS_PATH"] = profile.artifacts_path

    timeout = profile.document_timeout_seconds * len(source_images) + 120
    try:
        result = subprocess.run(
            command,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
            env=env,
        )
    except FileNotFoundError as exc:
        raise DoclingExecutionError(
            f"No se encontró '{profile.docling_command}'. Instale el extra [extraction].",
            log_text=f"$ {shlex.join(command)}",
        ) from exc
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = exc.stderr.decode() if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        log_text = "\n".join(
            part for part in (f"$ {shlex.join(command)}", stdout.strip(), stderr.strip()) if part
        )
        raise DoclingExecutionError(
            "Docling superó el límite acumulado de "
            f"{timeout} segundos para {len(source_images)} página(s)",
            log_text=log_text,
        ) from exc

    log_text = _command_log(command, result)
    if result.returncode != 0:
        diagnostic = (result.stderr or result.stdout or "").strip()
        tail = "\n".join(diagnostic.splitlines()[-30:])
        raise DoclingExecutionError(
            f"Docling terminó con código {result.returncode} usando device={device}:\n{tail}",
            log_text=log_text,
        )

    candidates = sorted(output_dir.rglob("*.json"))
    by_stem = {item.stem: item for item in candidates}
    page_outputs: dict[int, Path] = {}
    missing: list[int] = []
    for page_number, stem in expected_stems.items():
        candidate = by_stem.get(stem)
        if candidate is None:
            missing.append(page_number)
        else:
            page_outputs[page_number] = candidate
    if missing:
        produced = ", ".join(item.relative_to(attempt_dir).as_posix() for item in candidates) or "ninguno"
        raise DoclingExecutionError(
            "Docling no produjo JSON para las páginas: "
            + ", ".join(str(page) for page in missing)
            + f". JSON encontrados: {produced}",
            log_text=log_text,
        )
    return page_outputs, log_text


def run_docling_cli_batch(
    source_images: list[tuple[int, Path]],
    work_dir: Path,
    profile: ExtractionProfile,
) -> tuple[dict[int, Path], str | None, str]:
    """Ejecuta Docling una vez por documento, con fallback CPU ante fallos CUDA/cuDNN."""
    if not source_images:
        raise ValueError("No se proporcionaron páginas para extraer")
    work_dir.mkdir(parents=True, exist_ok=False)

    attempts: list[tuple[str, str]] = []
    first_device = profile.device
    try:
        outputs, log_text = _run_docling_cli_attempt(
            source_images, work_dir / f"attempt_1_{first_device}", profile, device=first_device
        )
        attempts.append((first_device, log_text))
        return outputs, _docling_version(profile.docling_command), log_text
    except DoclingExecutionError as first_error:
        attempts.append((first_device, first_error.log_text))
        can_fallback = (
            profile.retry_on_accelerator_error
            and profile.fallback_device is not None
            and profile.fallback_device != first_device
            and _accelerator_failure(f"{first_error}\n{first_error.log_text}")
        )
        if not can_fallback:
            raise

    fallback_device = profile.fallback_device
    assert fallback_device is not None
    try:
        outputs, fallback_log = _run_docling_cli_attempt(
            source_images,
            work_dir / f"attempt_2_{fallback_device}",
            profile,
            device=fallback_device,
        )
        attempts.append((fallback_device, fallback_log))
    except DoclingExecutionError as fallback_error:
        attempts.append((fallback_device, fallback_error.log_text))
        combined = "\n\n".join(
            f"===== intento device={device} =====\n{log}" for device, log in attempts
        )
        raise DoclingExecutionError(
            f"Docling falló con device={first_device} y con fallback={fallback_device}: "
            f"{fallback_error}",
            log_text=combined,
        ) from fallback_error

    combined = "\n\n".join(
        f"===== intento device={device} =====\n{log}" for device, log in attempts
    )
    combined += f"\n\nARCHIVE_WORKBENCH_FALLBACK_DEVICE={fallback_device}"
    return outputs, _docling_version(profile.docling_command), combined

def _resolve_ref(payload: dict[str, Any], ref: str) -> dict[str, Any] | None:
    if not ref.startswith("#/"):
        return None
    current: Any = payload
    for part in ref[2:].split("/"):
        if isinstance(current, list):
            try:
                current = current[int(part)]
            except (ValueError, IndexError):
                return None
        elif isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current if isinstance(current, dict) else None


def _ref_value(value: Any) -> str | None:
    if isinstance(value, dict):
        candidate = value.get("$ref") or value.get("cref") or value.get("ref")
        return str(candidate) if candidate else None
    if isinstance(value, str) and value.startswith("#/"):
        return value
    return None


def _iter_docling_items(payload: dict[str, Any]) -> Iterator[tuple[str, dict[str, Any]]]:
    """Recorre el árbol de lectura; si falta, usa las colecciones de contenido."""
    seen: set[str] = set()

    def walk(node: dict[str, Any]) -> Iterator[tuple[str, dict[str, Any]]]:
        for child in node.get("children", []) or []:
            ref = _ref_value(child)
            if not ref or ref in seen:
                continue
            item = _resolve_ref(payload, ref)
            if item is None:
                continue
            seen.add(ref)
            if ref.startswith("#/groups/"):
                yield from walk(item)
                continue
            yield ref, item
            yield from walk(item)

    roots = [payload.get("body"), payload.get("furniture")]
    yielded = False
    for root in roots:
        if isinstance(root, dict):
            for value in walk(root):
                yielded = True
                yield value

    if yielded:
        return
    for collection in CONTENT_COLLECTIONS:
        items = payload.get(collection)
        if not isinstance(items, list):
            continue
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            ref = str(item.get("self_ref") or f"#/{collection}/{index}")
            if ref in seen:
                continue
            seen.add(ref)
            yield ref, item


def _table_text(item: dict[str, Any]) -> str:
    data = item.get("data")
    if not isinstance(data, dict):
        return str(item.get("text") or item.get("orig") or "")

    rows: list[list[str]] = []
    grid = data.get("grid")
    if isinstance(grid, list):
        for raw_row in grid:
            if not isinstance(raw_row, list):
                continue
            row: list[str] = []
            for cell in raw_row:
                if isinstance(cell, dict):
                    row.append(str(cell.get("text") or "").strip())
                else:
                    row.append(str(cell or "").strip())
            rows.append(row)

    if not rows:
        cells = data.get("table_cells") or data.get("cells")
        if isinstance(cells, list):
            parsed: list[tuple[int, int, str]] = []
            for cell in cells:
                if not isinstance(cell, dict):
                    continue
                row = int(cell.get("start_row_offset_idx", cell.get("row", 0)) or 0)
                col = int(cell.get("start_col_offset_idx", cell.get("col", 0)) or 0)
                parsed.append((row, col, str(cell.get("text") or "").strip()))
            if parsed:
                max_row = max(item[0] for item in parsed)
                max_col = max(item[1] for item in parsed)
                rows = [["" for _ in range(max_col + 1)] for _ in range(max_row + 1)]
                for row, col, text in parsed:
                    rows[row][col] = text

    if not rows:
        return str(item.get("text") or item.get("orig") or "")

    width = max(len(row) for row in rows)
    rows = [row + [""] * (width - len(row)) for row in rows]

    def escaped(value: str) -> str:
        return value.replace("|", "\\|").replace("\n", " ").strip()

    lines = ["| " + " | ".join(escaped(cell) for cell in rows[0]) + " |"]
    lines.append("| " + " | ".join("---" for _ in range(width)) + " |")
    lines.extend("| " + " | ".join(escaped(cell) for cell in row) + " |" for row in rows[1:])
    return "\n".join(lines)


def _item_text(item: dict[str, Any], label: str) -> str:
    if label in {"table", "document_index"}:
        return _table_text(item)
    for key in ("text", "orig", "value"):
        value = item.get(key)
        if isinstance(value, str):
            return value.strip()
    return ""


def _confidence(item: dict[str, Any]) -> float | None:
    candidates: list[Any] = [item.get("confidence")]
    meta = item.get("meta")
    if isinstance(meta, dict):
        candidates.extend([meta.get("confidence"), meta.get("score")])
    for value in candidates:
        if isinstance(value, (int, float)) and 0 <= float(value) <= 1:
            return float(value)
    return None


def _geometry(
    item: dict[str, Any], *, page_number: int, width: int, height: int
) -> list[PageGeometry]:
    result: list[PageGeometry] = []
    provenance = item.get("prov")
    if not isinstance(provenance, list):
        return result
    for prov in provenance:
        if not isinstance(prov, dict):
            continue
        bbox = prov.get("bbox")
        if not isinstance(bbox, dict):
            continue
        try:
            left = float(bbox["l"])
            right = float(bbox["r"])
            top_raw = float(bbox["t"])
            bottom_raw = float(bbox["b"])
        except (KeyError, TypeError, ValueError):
            continue
        origin = str(bbox.get("coord_origin") or "TOPLEFT").upper()
        if "BOTTOM" in origin:
            top = height - max(top_raw, bottom_raw)
            bottom = height - min(top_raw, bottom_raw)
        else:
            top = min(top_raw, bottom_raw)
            bottom = max(top_raw, bottom_raw)
        left, right = min(left, right), max(left, right)
        left = min(max(left, 0.0), float(width))
        right = min(max(right, 0.0), float(width))
        top = min(max(top, 0.0), float(height))
        bottom = min(max(bottom, 0.0), float(height))
        if right <= left or bottom <= top:
            continue
        polygon = [
            (left / width, top / height),
            (right / width, top / height),
            (right / width, bottom / height),
            (left / width, bottom / height),
        ]
        result.append(PageGeometry(page=page_number, polygon=polygon))
    return result


def normalize_docling_page(
    payload: dict[str, Any],
    *,
    digital_object_id: str,
    extraction_run_id: str,
    page_number: int,
    width: int,
    height: int,
    decisions: ProjectDecisions,
    order_start: int = 0,
) -> list[ExtractedObjectRecord]:
    type_settings = {item.key: item for item in decisions.object_types}
    ref_to_origin: dict[str, str] = {}
    ordered_items = list(_iter_docling_items(payload))
    for index, (ref, _item) in enumerate(ordered_items):
        ref_to_origin[ref] = stable_id(
            NAMESPACE_URL,
            "archive-workbench",
            digital_object_id,
            page_number,
            ref or index,
        )

    result: list[ExtractedObjectRecord] = []
    for index, (ref, item) in enumerate(ordered_items):
        label = str(item.get("label") or "unknown")
        object_type = LABEL_MAP.get(label, "unknown")
        settings = type_settings.get(object_type)
        parent_ref = _ref_value(item.get("parent"))
        attributes: dict[str, Any] = {
            "docling_ref": ref,
            "docling_label": label,
            "content_layer": item.get("content_layer"),
        }
        if parent_ref:
            attributes["docling_parent_ref"] = parent_ref
        result.append(
            ExtractedObjectRecord(
                object_id=ref_to_origin[ref],
                digital_object_id=digital_object_id,
                extraction_run_id=extraction_run_id,
                parent_object_id=ref_to_origin.get(parent_ref or ""),
                order_index=order_start + index,
                object_type=object_type,
                original_text=_item_text(item, label),
                geometry=_geometry(
                    item,
                    page_number=page_number,
                    width=width,
                    height=height,
                ),
                source_label=label,
                confidence=_confidence(item),
                hidden_by_default=(settings is not None and not settings.visible_by_default),
                attributes={key: value for key, value in attributes.items() if value is not None},
            )
        )
    return result


def _bbox_from_record(record: ExtractedObjectRecord) -> list[list[float]]:
    result: list[list[float]] = []
    for geometry in record.geometry:
        xs = [point[0] for point in geometry.polygon]
        ys = [point[1] for point in geometry.polygon]
        result.append([min(xs), min(ys), max(xs), max(ys)])
    return result


def _paragraph_records(
    objects: Iterable[ExtractedObjectRecord],
) -> list[ParagraphExportRecord]:
    result: list[ParagraphExportRecord] = []
    for item in objects:
        page = item.geometry[0].page if item.geometry else None
        result.append(
            ParagraphExportRecord(
                paragraph_id=item.object_id,
                digital_object_id=item.digital_object_id,
                extraction_run_id=item.extraction_run_id,
                page=page,
                order_index=item.order_index,
                object_type=item.object_type,
                text=item.original_text,
                bboxes=_bbox_from_record(item),
                origin_object_ids=[item.object_id],
            )
        )
    return result


def _image_records(
    assets: Iterable[DerivativeAsset], *, extraction_run_id: str
) -> list[ImageManifestRecord]:
    return [
        ImageManifestRecord(
            page_id=f"{asset.digital_object_id}:page:{asset.page_number}",
            digital_object_id=asset.digital_object_id,
            extraction_run_id=extraction_run_id,
            page=asset.page_number,
            sha256=asset.sha256,
            width=asset.width,
            height=asset.height,
            dpi=asset.dpi,
            path=asset.relative_path,
            mime_type=asset.mime_type,
        )
        for asset in assets
        if asset.kind == "preview"
    ]


def _current_assets(
    session: Session, digital_object_id: str
) -> tuple[PreprocessingRun, list[DerivativeAsset], list[DerivativeAsset]]:
    run = session.scalar(
        select(PreprocessingRun)
        .where(
            PreprocessingRun.digital_object_id == digital_object_id,
            PreprocessingRun.is_current.is_(True),
            PreprocessingRun.status.in_(["completed", "completed_with_warnings"]),
        )
        .order_by(PreprocessingRun.created_at.desc())
    )
    if run is None:
        raise RuntimeError("no tiene una corrida de preprocesamiento vigente")
    assets = session.scalars(
        select(DerivativeAsset)
        .where(DerivativeAsset.preprocessing_run_id == run.id)
        .order_by(DerivativeAsset.page_number, DerivativeAsset.kind)
    ).all()
    ocr_assets = [asset for asset in assets if asset.kind == "ocr"]
    preview_assets = [asset for asset in assets if asset.kind == "preview"]
    if not ocr_assets:
        raise RuntimeError("la corrida vigente no tiene derivados OCR")
    return run, ocr_assets, preview_assets


def _selected_registrations(
    session: Session, source_keys: set[str]
) -> list[tuple[SourceRegistration, DigitalObject, ArchivalUnit]]:
    statement = (
        select(SourceRegistration, DigitalObject, ArchivalUnit)
        .join(DigitalObject, SourceRegistration.digital_object_id == DigitalObject.id)
        .join(ArchivalUnit, SourceRegistration.archival_unit_id == ArchivalUnit.id)
        .where(SourceRegistration.source_type.in_(PROCESSABLE_SOURCE_TYPES))
        .order_by(SourceRegistration.source_key)
    )
    if source_keys:
        statement = statement.where(SourceRegistration.source_key.in_(source_keys))
    rows = list(session.execute(statement).all())
    found = {registration.source_key for registration, _, _ in rows}
    missing = source_keys - found
    if missing:
        raise ValueError(f"source_key no registrado: {', '.join(sorted(missing))}")
    return rows


def _persist_objects(session: Session, records: list[ExtractedObjectRecord]) -> None:
    for record in records:
        page_number = record.geometry[0].page if record.geometry else None
        session.add(
            ExtractedObject(
                id=new_id(),
                origin_id=record.object_id,
                extraction_run_id=record.extraction_run_id,
                digital_object_id=record.digital_object_id,
                parent_origin_id=record.parent_object_id,
                page_number=page_number,
                order_index=record.order_index,
                object_type=record.object_type,
                original_text=record.original_text,
                geometry_json=[item.model_dump(mode="json") for item in record.geometry],
                source_label=record.source_label,
                confidence=record.confidence,
                language=record.language,
                hidden_by_default=record.hidden_by_default,
                attributes_json=record.attributes,
            )
        )


def _append_selection_revision(
    session: Session,
    selection: ExtractionPageSelection,
    *,
    operation: str,
    selected_by: str,
    note: str | None,
    previous_extraction_run_id: str | None,
    previous_extraction_page_id: str | None,
    created_at: datetime | None = None,
) -> ExtractionPageSelectionRevision:
    revision_number = int(
        session.scalar(
            select(func.max(ExtractionPageSelectionRevision.revision_number)).where(
                ExtractionPageSelectionRevision.selection_id == selection.id
            )
        )
        or 0
    ) + 1
    revision = ExtractionPageSelectionRevision(
        id=new_id(),
        selection_id=selection.id,
        digital_object_id=selection.digital_object_id,
        page_number=selection.page_number,
        revision_number=revision_number,
        operation=operation,
        previous_extraction_run_id=previous_extraction_run_id,
        previous_extraction_page_id=previous_extraction_page_id,
        extraction_run_id=selection.extraction_run_id,
        extraction_page_id=selection.extraction_page_id,
        note=note,
        selected_by=selected_by,
        created_at=created_at or datetime.now(timezone.utc),
    )
    session.add(revision)
    return revision


def _apply_page_selections(
    session: Session,
    *,
    run: ExtractionRun,
    selected_by: str,
    policy: str,
    note: str | None = None,
    pages: set[int] | None = None,
) -> int:
    if policy not in {"never", "if_unselected", "replace"}:
        raise ValueError(f"Política de selección inválida: {policy}")
    if policy == "never":
        return 0
    page_rows = session.scalars(
        select(ExtractionPage)
        .where(ExtractionPage.extraction_run_id == run.id)
        .order_by(ExtractionPage.page_number)
    ).all()
    if pages:
        page_rows = [row for row in page_rows if row.page_number in pages]
    changed = 0
    now = datetime.now(timezone.utc)
    for page_row in page_rows:
        current = session.scalar(
            select(ExtractionPageSelection).where(
                ExtractionPageSelection.digital_object_id == run.digital_object_id,
                ExtractionPageSelection.page_number == page_row.page_number,
            )
        )
        if current is not None and policy == "if_unselected":
            continue
        if current is None:
            current = ExtractionPageSelection(
                id=new_id(),
                digital_object_id=run.digital_object_id,
                page_number=page_row.page_number,
                extraction_run_id=run.id,
                extraction_page_id=page_row.id,
                selected_by=selected_by,
                note=note,
                selected_at=now,
            )
            session.add(current)
            session.flush()
            _append_selection_revision(
                session,
                current,
                operation="select",
                selected_by=selected_by,
                note=note,
                previous_extraction_run_id=None,
                previous_extraction_page_id=None,
                created_at=now,
            )
        else:
            previous_run_id = current.extraction_run_id
            previous_page_id = current.extraction_page_id
            if previous_run_id == run.id and previous_page_id == page_row.id:
                continue
            current.extraction_run_id = run.id
            current.extraction_page_id = page_row.id
            current.selected_by = selected_by
            current.note = note
            current.selected_at = now
            _append_selection_revision(
                session,
                current,
                operation="replace",
                selected_by=selected_by,
                note=note,
                previous_extraction_run_id=previous_run_id,
                previous_extraction_page_id=previous_page_id,
                created_at=now,
            )
        editable_page = session.scalar(
            select(EditablePage).where(
                EditablePage.digital_object_id == run.digital_object_id,
                EditablePage.page_number == page_row.page_number,
            )
        )
        if editable_page is not None and editable_page.source_extraction_page_id != page_row.id:
            from archive_workbench.editing import _set_page_status

            _set_page_status(
                session,
                editable_page,
                status="stale",
                changed_by=selected_by,
                operation="mark_stale",
                note="La selección canónica cambió; la edición existente se conservó.",
                details={
                    "selected_extraction_run_id": run.id,
                    "selected_extraction_page_id": page_row.id,
                },
            )
        changed += 1
    session.flush()
    return changed


def select_extraction_pages(
    session: Session,
    *,
    source_key: str,
    selected_by: str,
    run_id: str | None = None,
    profile_key: str | None = None,
    pages: set[int] | None = None,
    note: str | None = None,
) -> tuple[ExtractionRun, int]:
    statement = (
        select(ExtractionRun)
        .join(DigitalObject, ExtractionRun.digital_object_id == DigitalObject.id)
        .join(SourceRegistration, SourceRegistration.digital_object_id == DigitalObject.id)
        .where(
            SourceRegistration.source_type.in_(PROCESSABLE_SOURCE_TYPES),
            SourceRegistration.source_key == source_key,
            ExtractionRun.status.in_(["completed", "completed_with_warnings"]),
        )
        .order_by(ExtractionRun.created_at.desc())
    )
    if run_id:
        statement = statement.where(ExtractionRun.id == run_id)
    if profile_key:
        statement = statement.where(ExtractionRun.profile_key == profile_key)
    run = session.scalar(statement)
    if run is None:
        raise ValueError(f"No se encontró una extracción utilizable para {source_key}")
    available = set(
        session.scalars(
            select(ExtractionPage.page_number).where(ExtractionPage.extraction_run_id == run.id)
        ).all()
    )
    requested = set(pages or available)
    missing = requested - available
    if missing:
        raise ValueError(
            "La corrida no contiene las páginas: " + ", ".join(map(str, sorted(missing)))
        )
    changed = _apply_page_selections(
        session,
        run=run,
        selected_by=selected_by,
        policy="replace",
        note=note,
        pages=requested,
    )
    return run, changed


def restore_profile_page_selections(
    session: Session,
    *,
    source_key: str,
    profile_key: str,
    pages: set[int],
    selected_by: str,
    note: str | None = None,
) -> list[tuple[int, str]]:
    """Restaura por página la corrida más reciente de un perfil histórico.

    Un mismo perfil puede haber sido ejecutado en varias corridas parciales. Por eso
    la búsqueda se hace página por página, en lugar de asumir que una sola corrida
    contiene todo el rango solicitado.
    """
    if not pages:
        raise ValueError("Debe indicar al menos una página para restaurar")

    restored: list[tuple[int, str]] = []
    for page_number in sorted(pages):
        statement = (
            select(ExtractionRun)
            .join(DigitalObject, ExtractionRun.digital_object_id == DigitalObject.id)
            .join(
                SourceRegistration,
                SourceRegistration.digital_object_id == DigitalObject.id,
            )
            .join(
                ExtractionPage,
                ExtractionPage.extraction_run_id == ExtractionRun.id,
            )
            .where(
                SourceRegistration.source_type.in_(PROCESSABLE_SOURCE_TYPES),
                SourceRegistration.source_key == source_key,
                ExtractionRun.profile_key == profile_key,
                ExtractionRun.status.in_(["completed", "completed_with_warnings"]),
                ExtractionPage.page_number == page_number,
            )
            .order_by(ExtractionRun.created_at.desc())
        )
        run = session.scalar(statement)
        if run is None:
            raise ValueError(
                f"No se encontró una corrida utilizable de {profile_key} "
                f"para {source_key}, página {page_number}"
            )
        _apply_page_selections(
            session,
            run=run,
            selected_by=selected_by,
            policy="replace",
            note=note,
            pages={page_number},
        )
        restored.append((page_number, run.id))

    return restored


def extraction_history_rows(
    session: Session, *, source_key: str | None = None
) -> list[ExtractionHistoryRow]:
    statement = (
        select(
            ExtractionRun.id,
            SourceRegistration.source_key,
            ExtractionRun.profile_key,
            ExtractionRun.status,
            ExtractionRun.quality_status,
            ExtractionRun.total_pages,
            ExtractionRun.total_objects,
            ExtractionRun.total_characters,
            ExtractionRun.is_current,
            ExtractionRun.created_at,
        )
        .join(DigitalObject, ExtractionRun.digital_object_id == DigitalObject.id)
        .join(SourceRegistration, SourceRegistration.digital_object_id == DigitalObject.id)
        .where(SourceRegistration.source_type.in_(PROCESSABLE_SOURCE_TYPES))
        .order_by(SourceRegistration.source_key, ExtractionRun.created_at.desc())
    )
    if source_key:
        statement = statement.where(SourceRegistration.source_key == source_key)
    return [
        ExtractionHistoryRow(
            run_id=row.id,
            source_key=row.source_key,
            profile_key=row.profile_key,
            status=row.status,
            quality_status=row.quality_status,
            pages=row.total_pages or 0,
            objects=row.total_objects or 0,
            characters=row.total_characters or 0,
            is_current=bool(row.is_current),
            created_at=row.created_at,
        )
        for row in session.execute(statement)
    ]


def selected_extraction_status_rows(session: Session) -> list[SelectedExtractionStatusRow]:
    registrations = session.execute(
        select(
            SourceRegistration.source_key,
            ArchivalUnit.title,
            DigitalObject.id.label("digital_object_id"),
            DigitalObject.page_count,
        )
        .join(DigitalObject, SourceRegistration.digital_object_id == DigitalObject.id)
        .join(ArchivalUnit, SourceRegistration.archival_unit_id == ArchivalUnit.id)
        .where(SourceRegistration.source_type.in_(PROCESSABLE_SOURCE_TYPES))
        .order_by(SourceRegistration.source_key)
    ).all()
    output: list[SelectedExtractionStatusRow] = []
    for registration in registrations:
        selections = session.execute(
            select(
                ExtractionPageSelection.page_number,
                ExtractionRun.profile_key,
                ExtractionRun.quality_status,
            )
            .join(
                ExtractionRun,
                ExtractionPageSelection.extraction_run_id == ExtractionRun.id,
            )
            .where(
                ExtractionPageSelection.digital_object_id == registration.digital_object_id
            )
            .order_by(ExtractionPageSelection.page_number)
        ).all()
        selected_pages = {row.page_number for row in selections}
        expected = set(range(1, (registration.page_count or 0) + 1))
        output.append(
            SelectedExtractionStatusRow(
                source_key=registration.source_key,
                title=registration.title,
                page_count=registration.page_count,
                selected_pages=len(selected_pages),
                missing_pages=sorted(expected - selected_pages),
                profiles=sorted({row.profile_key or "-" for row in selections}),
                rejected_pages=sorted(
                    row.page_number for row in selections if row.quality_status == "rejected"
                ),
            )
        )
    return output


def extract_documents(
    session: Session,
    *,
    project_root: str | Path,
    decisions: ProjectDecisions,
    profile: ExtractionProfile,
    source_keys: set[str] | None = None,
    selected_pages: set[int] | None = None,
    force: bool = False,
    created_by: str = "local_user",
    selection_policy: str = "if_unselected",
    runner: DoclingBatchRunner = run_docling_cli_batch,
    surya_runner: SuryaBatchRunner = run_surya_cli_batch,
) -> ExtractionSummary:
    root = Path(project_root)
    summary = ExtractionSummary()
    if not profile.use_ocr_derivatives:
        raise ValueError("La versión actual solo extrae desde derivados OCR versionados")
    if selection_policy not in {"never", "if_unselected", "replace"}:
        raise ValueError(f"Política de selección inválida: {selection_policy}")
    page_filter = set(selected_pages or [])
    if any(page < 1 for page in page_filter):
        raise ValueError("Los números de página deben ser mayores o iguales a 1")

    for registration, digital, _unit in _selected_registrations(session, source_keys or set()):
        summary.objects_seen += 1
        run: ExtractionRun | None = None
        try:
            preprocessing_run, ocr_assets, preview_assets = _current_assets(session, digital.id)
            if preprocessing_run.source_sha256 != digital.sha256:
                raise RuntimeError("el preprocesamiento vigente no corresponde al SHA-256 actual")
            if page_filter:
                available = {asset.page_number for asset in ocr_assets}
                unavailable = page_filter - available
                if unavailable:
                    raise RuntimeError(
                        f"páginas inexistentes: {', '.join(map(str, sorted(unavailable)))}"
                    )
                ocr_assets = [asset for asset in ocr_assets if asset.page_number in page_filter]
                preview_assets = [
                    asset for asset in preview_assets if asset.page_number in page_filter
                ]

            options = profile.model_dump(mode="json")
            options["selected_pages"] = sorted(asset.page_number for asset in ocr_assets)
            options["preprocessing_run_id"] = preprocessing_run.id
            options_hash = sha256_json(options)
            equivalent = session.scalar(
                select(ExtractionRun)
                .where(
                    ExtractionRun.digital_object_id == digital.id,
                    ExtractionRun.source_sha256 == digital.sha256,
                    ExtractionRun.options_hash == options_hash,
                    ExtractionRun.status.in_(["completed", "completed_with_warnings"]),
                )
                .order_by(ExtractionRun.created_at.desc())
            )
            if equivalent is not None and not force:
                if selection_policy != "never":
                    _apply_page_selections(
                        session,
                        run=equivalent,
                        selected_by=created_by,
                        policy=selection_policy,
                        note="Corrida equivalente reutilizada",
                    )
                summary.runs_reused += 1
                continue

            run_id = new_id()
            output_dir = root / "extraction" / digital.id / run_id
            raw_dir = output_dir / "raw"
            output_dir.mkdir(parents=True, exist_ok=False)
            run = ExtractionRun(
                id=run_id,
                digital_object_id=digital.id,
                preprocessing_run_id=preprocessing_run.id,
                profile_key=profile.profile_key,
                engine=profile.backend,
                source_sha256=digital.sha256,
                options_json=options,
                options_hash=options_hash,
                status=ExtractionStatus.RUNNING.value,
                is_current=False,
                output_root=_relative(output_dir, root),
                raw_pages_path=_relative(raw_dir, root),
                created_by=created_by,
            )
            session.add(run)
            session.flush()

            all_objects: list[ExtractedObjectRecord] = []
            warnings_out: list[str] = []
            engine_version: str | None = None
            order_start = 0

            ordered_assets = sorted(ocr_assets, key=lambda item: item.page_number)
            source_images: list[tuple[int, Path]] = []
            for asset in ordered_assets:
                source_image = root / asset.relative_path
                if not source_image.is_file():
                    raise RuntimeError(f"falta el derivado OCR {asset.relative_path}")
                actual_sha256 = sha256_file(source_image)
                if actual_sha256 != asset.sha256:
                    raise RuntimeError(
                        f"el derivado OCR fue modificado: {asset.relative_path}; "
                        "regenere los derivados antes de extraer"
                    )
                source_images.append((asset.page_number, source_image))

            if profile.backend == "docling_cli":
                page_json, engine_version, log_text = runner(
                    source_images, output_dir / ".work", profile
                )
                if log_text:
                    raw_dir.mkdir(parents=True, exist_ok=True)
                    (raw_dir / "docling.log").write_text(log_text, encoding="utf-8")
                if "ARCHIVE_WORKBENCH_FALLBACK_DEVICE=cpu" in log_text:
                    warnings_out.append(
                        "El intento con aceleración falló; Docling completó la extracción en CPU"
                    )

                for asset in ordered_assets:
                    json_path = page_json[asset.page_number]
                    payload = json.loads(json_path.read_text(encoding="utf-8"))
                    if not isinstance(payload, dict):
                        raise RuntimeError(
                            f"Docling produjo JSON inválido para página {asset.page_number}"
                        )
                    raw_destination = raw_dir / f"page_{asset.page_number:04d}.json"
                    raw_destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(json_path, raw_destination)

                    page_objects = normalize_docling_page(
                        payload,
                        digital_object_id=digital.id,
                        extraction_run_id=run_id,
                        page_number=asset.page_number,
                        width=asset.width,
                        height=asset.height,
                        decisions=decisions,
                        order_start=order_start,
                    )
                    order_start += len(page_objects)
                    characters = sum(len(item.original_text) for item in page_objects)
                    page_warning = None
                    if characters < profile.minimum_characters_per_page_warning:
                        page_warning = (
                            f"Página {asset.page_number}: solo {characters} caracteres reconocidos"
                        )
                        warnings_out.append(page_warning)
                    session.add(
                        ExtractionPage(
                            id=new_id(),
                            extraction_run_id=run_id,
                            page_number=asset.page_number,
                            source_asset_id=asset.id,
                            raw_json_path=_relative(raw_destination, root),
                            object_count=len(page_objects),
                            character_count=characters,
                            status=(
                                ExtractionStatus.COMPLETED_WITH_WARNINGS.value
                                if page_warning
                                else ExtractionStatus.COMPLETED.value
                            ),
                            warning_text=page_warning,
                        )
                    )
                    all_objects.extend(page_objects)
            elif profile.backend == "surya_cli":
                surya_sources = source_images
                if profile.image_variant != "original":
                    variant_dir = output_dir / ".work" / "surya_variants"
                    surya_sources = []
                    for page_number, source_image in source_images:
                        variant_path = variant_dir / f"page_{page_number:04d}.png"
                        prepare_image_variant(source_image, variant_path, profile.image_variant)
                        surya_sources.append((page_number, variant_path))
                page_json, engine_version, log_text = surya_runner(
                    surya_sources, output_dir / ".work" / "surya", profile
                )
                if log_text:
                    raw_dir.mkdir(parents=True, exist_ok=True)
                    (raw_dir / "surya.log").write_text(log_text, encoding="utf-8")
                if "ARCHIVE_WORKBENCH_FALLBACK_DEVICE=cpu" in log_text:
                    warnings_out.append(
                        "El backend acelerado de Surya falló; la extracción se completó "
                        "con llama.cpp en CPU"
                    )

                for asset in ordered_assets:
                    json_path = page_json[asset.page_number]
                    payload = json.loads(json_path.read_text(encoding="utf-8"))
                    if not isinstance(payload, dict):
                        raise RuntimeError(
                            f"Surya produjo JSON inválido para página {asset.page_number}"
                        )
                    raw_destination = raw_dir / f"page_{asset.page_number:04d}.json"
                    raw_destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(json_path, raw_destination)
                    page_objects = normalize_surya_page(
                        payload,
                        digital_object_id=digital.id,
                        extraction_run_id=run_id,
                        page_number=asset.page_number,
                        width=asset.width,
                        height=asset.height,
                        decisions=decisions,
                        order_start=order_start,
                    )
                    order_start += len(page_objects)
                    characters = sum(len(item.original_text) for item in page_objects)
                    page_warnings: list[str] = []
                    if characters < profile.minimum_characters_per_page_warning:
                        page_warnings.append(f"solo {characters} caracteres reconocidos")
                    blocks = payload.get("blocks")
                    if isinstance(blocks, list):
                        errors = sum(
                            bool(block.get("error"))
                            for block in blocks
                            if isinstance(block, dict)
                        )
                        if errors:
                            page_warnings.append(f"{errors} bloques informaron error")
                    page_warning = (
                        f"Página {asset.page_number}: " + "; ".join(page_warnings)
                        if page_warnings
                        else None
                    )
                    if page_warning:
                        warnings_out.append(page_warning)
                    session.add(
                        ExtractionPage(
                            id=new_id(),
                            extraction_run_id=run_id,
                            page_number=asset.page_number,
                            source_asset_id=asset.id,
                            raw_json_path=_relative(raw_destination, root),
                            object_count=len(page_objects),
                            character_count=characters,
                            status=(
                                ExtractionStatus.COMPLETED_WITH_WARNINGS.value
                                if page_warning
                                else ExtractionStatus.COMPLETED.value
                            ),
                            warning_text=page_warning,
                        )
                    )
                    all_objects.extend(page_objects)
            elif profile.backend == "tesseract_tsv":
                engine_version = _tesseract_version(profile.tesseract_command)
                variant_dir = output_dir / ".work" / "variants"
                page_scores: list[float] = []
                for asset in ordered_assets:
                    source_image = root / asset.relative_path
                    variant_path = variant_dir / f"page_{asset.page_number:04d}.png"
                    prepare_image_variant(source_image, variant_path, profile.image_variant)
                    result = run_tesseract_page(
                        variant_path,
                        page_number=asset.page_number,
                        tesseract_command=profile.tesseract_command,
                        languages=profile.ocr_languages,
                        psm=profile.psm if profile.psm is not None else 3,
                        image_variant=profile.image_variant,
                        timeout_seconds=profile.document_timeout_seconds,
                    )
                    raw_destination, _tsv_path, _txt_path = write_tesseract_raw(result, raw_dir)
                    page_objects = normalize_tesseract_result(
                        result,
                        digital_object_id=digital.id,
                        extraction_run_id=run_id,
                        order_start=order_start,
                        granularity=profile.object_granularity,
                    )
                    order_start += len(page_objects)
                    metrics = text_quality_metrics(result.full_text, result.lines)
                    page_scores.append(float(metrics["heuristic_score"]))
                    characters = int(metrics["character_count"])
                    page_warnings: list[str] = []
                    if characters < profile.minimum_characters_per_page_warning:
                        page_warnings.append(
                            f"solo {characters} caracteres reconocidos"
                        )
                    if float(metrics["heuristic_score"]) < 0.35:
                        page_warnings.append(
                            f"puntaje heurístico bajo ({float(metrics['heuristic_score']):.3f})"
                        )
                    page_warning = (
                        f"Página {asset.page_number}: " + "; ".join(page_warnings)
                        if page_warnings
                        else None
                    )
                    if page_warning:
                        warnings_out.append(page_warning)
                    session.add(
                        ExtractionPage(
                            id=new_id(),
                            extraction_run_id=run_id,
                            page_number=asset.page_number,
                            source_asset_id=asset.id,
                            raw_json_path=_relative(raw_destination, root),
                            object_count=len(page_objects),
                            character_count=characters,
                            status=(
                                ExtractionStatus.COMPLETED_WITH_WARNINGS.value
                                if page_warning
                                else ExtractionStatus.COMPLETED.value
                            ),
                            warning_text=page_warning,
                        )
                    )
                    all_objects.extend(page_objects)
                if page_scores:
                    run.quality_score = sum(page_scores) / len(page_scores)
            else:  # pragma: no cover - validado por Pydantic
                raise RuntimeError(f"Backend no soportado: {profile.backend}")

            paragraphs = _paragraph_records(all_objects)
            images = _image_records(preview_assets, extraction_run_id=run_id)
            objects_path = output_dir / decisions.jsonl.objects_filename
            paragraphs_path = output_dir / decisions.jsonl.paragraphs_filename
            images_path = output_dir / decisions.jsonl.images_filename
            manifest_path = output_dir / decisions.jsonl.manifest_filename
            write_models_atomic(objects_path, all_objects)
            write_models_atomic(paragraphs_path, paragraphs)
            write_models_atomic(images_path, images)
            _persist_objects(session, all_objects)
            session.flush()
            extraction_pages = list(
                session.scalars(
                    select(ExtractionPage)
                    .where(ExtractionPage.extraction_run_id == run_id)
                    .order_by(ExtractionPage.page_number)
                ).all()
            )
            for extraction_page in extraction_pages:
                try:
                    assess_extraction_page_quality(
                        session,
                        project_root=root,
                        extraction_page_id=extraction_page.id,
                        assessed_by="system:extraction",
                    )
                except (OSError, ValueError) as exc:
                    warnings_out.append(
                        f"Página {extraction_page.page_number}: "
                        f"no se pudo evaluar automáticamente la calidad ({exc})"
                    )

            character_count = sum(len(item.original_text) for item in all_objects)
            status = (
                ExtractionStatus.COMPLETED_WITH_WARNINGS
                if warnings_out
                else ExtractionStatus.COMPLETED
            )
            now = datetime.now(timezone.utc)
            manifest = ExtractionManifest(
                run_id=run_id,
                digital_object_id=digital.id,
                preprocessing_run_id=preprocessing_run.id,
                source_sha256=digital.sha256,
                source_media_type=MediaType(digital.media_type),
                profile=profile,
                engine=profile.backend,
                engine_version=engine_version,
                options=options,
                options_hash=options_hash,
                created_by=created_by,
                created_at=run.created_at,
                completed_at=now,
                status=status,
                warnings=warnings_out,
                pages_processed=sorted(asset.page_number for asset in ocr_assets),
                object_count=len(all_objects),
                paragraph_count=len(paragraphs),
                character_count=character_count,
                output_root=_relative(output_dir, root),
                raw_pages_path=_relative(raw_dir, root),
                objects_path=_relative(objects_path, root),
                paragraphs_path=_relative(paragraphs_path, root),
                images_path=_relative(images_path, root),
            )
            manifest_path.write_text(
                manifest.model_dump_json(indent=2, exclude_none=True), encoding="utf-8"
            )
            shutil.rmtree(output_dir / ".work", ignore_errors=True)

            session.execute(
                update(ExtractionRun)
                .where(
                    ExtractionRun.digital_object_id == digital.id,
                    ExtractionRun.id != run_id,
                )
                .values(is_current=False)
            )
            run.engine_version = engine_version
            run.status = status.value
            run.is_current = True
            run.manifest_path = _relative(manifest_path, root)
            run.objects_path = _relative(objects_path, root)
            run.paragraphs_path = _relative(paragraphs_path, root)
            run.images_path = _relative(images_path, root)
            run.total_pages = len(ocr_assets)
            run.total_objects = len(all_objects)
            run.total_paragraphs = len(paragraphs)
            run.total_characters = character_count
            run.warnings_json = warnings_out
            run.completed_at = now
            session.flush()
            if selection_policy != "never":
                _apply_page_selections(
                    session,
                    run=run,
                    selected_by=created_by,
                    policy=selection_policy,
                    note=f"Extracción {profile.profile_key}",
                )

            summary.runs_created += 1
            summary.pages_processed += len(ocr_assets)
            summary.objects_created += len(all_objects)
            summary.paragraphs_created += len(paragraphs)
            summary.characters_created += character_count
            summary.warnings.extend(f"{registration.source_key}: {item}" for item in warnings_out)
        except Exception as exc:
            summary.failed += 1
            summary.failed_source_keys.append(registration.source_key)
            summary.warnings.append(f"{registration.source_key}: {exc}")
            if run is not None:
                diagnostic_log = getattr(exc, "log_text", "")
                if diagnostic_log:
                    raw_dir = root / run.raw_pages_path
                    raw_dir.mkdir(parents=True, exist_ok=True)
                    log_name = "surya.log" if profile.backend == "surya_cli" else "docling.log"
                    (raw_dir / log_name).write_text(diagnostic_log, encoding="utf-8")
                run.status = ExtractionStatus.FAILED.value
                run.error_text = str(exc)
                run.completed_at = datetime.now(timezone.utc)
                session.flush()
    return summary


def review_current_extraction(
    session: Session,
    *,
    source_key: str,
    verdict: str,
    reviewed_by: str,
    note: str | None = None,
) -> ExtractionRun:
    allowed = {"accepted", "rejected", "needs_review", "unreviewed"}
    if verdict not in allowed:
        raise ValueError(f"Veredicto inválido: {verdict}")
    run = session.scalar(
        select(ExtractionRun)
        .join(DigitalObject, ExtractionRun.digital_object_id == DigitalObject.id)
        .join(SourceRegistration, SourceRegistration.digital_object_id == DigitalObject.id)
        .where(
            SourceRegistration.source_type.in_(PROCESSABLE_SOURCE_TYPES),
            SourceRegistration.source_key == source_key,
            ExtractionRun.is_current.is_(True),
        )
        .order_by(ExtractionRun.created_at.desc())
    )
    if run is None:
        raise ValueError(f"No hay extracción vigente para {source_key}")
    run.quality_status = verdict
    run.quality_note = note
    run.reviewed_by = reviewed_by
    run.reviewed_at = datetime.now(timezone.utc)
    session.flush()
    return run


def extraction_status_rows(session: Session) -> list[ExtractionStatusRow]:
    statement = (
        select(
            SourceRegistration.source_key,
            ArchivalUnit.title,
            DigitalObject.media_type,
            DigitalObject.page_count,
            ExtractionRun.status,
            ExtractionRun.profile_key,
            ExtractionRun.total_pages,
            ExtractionRun.total_objects,
            ExtractionRun.total_characters,
            ExtractionRun.output_root,
            ExtractionRun.quality_status,
            ExtractionRun.quality_score,
        )
        .join(DigitalObject, SourceRegistration.digital_object_id == DigitalObject.id)
        .join(ArchivalUnit, SourceRegistration.archival_unit_id == ArchivalUnit.id)
        .outerjoin(
            ExtractionRun,
            (ExtractionRun.digital_object_id == DigitalObject.id)
            & (ExtractionRun.is_current.is_(True)),
        )
        .where(SourceRegistration.source_type.in_(PROCESSABLE_SOURCE_TYPES))
        .order_by(SourceRegistration.source_key)
    )
    return [
        ExtractionStatusRow(
            source_key=row.source_key,
            title=row.title,
            media_type=row.media_type,
            page_count=row.page_count,
            run_status=row.status,
            profile_key=row.profile_key,
            pages=row.total_pages or 0,
            objects=row.total_objects or 0,
            characters=row.total_characters or 0,
            output_root=row.output_root,
            quality_status=row.quality_status,
            quality_score=row.quality_score,
        )
        for row in session.execute(statement)
    ]
