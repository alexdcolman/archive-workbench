from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

AI_EXECUTABLE_ENV = "ARCHIVE_WORKBENCH_AI_EXECUTABLE"
LEGACY_AI_EXECUTABLE_ENV = "ARCHIVE_WORKBENCH_AI01_EXECUTABLE"
AI_BRIDGE_DIR_ENV = "ARCHIVE_WORKBENCH_AI_BRIDGE_DIR"
AI_BRIDGE_TIMEOUT_ENV = "ARCHIVE_WORKBENCH_AI_BRIDGE_TIMEOUT_SECONDS"
EXPECTED_BRIDGE_PROTOCOL = "archive-workbench-ai-bridge/0.1"
EXPECTED_PROTOCOL = "archive-workbench-ai/0.1"
EXPECTED_HANDOFF_SCHEMA = "archive_workbench_ai_result_handoff/0.1"
EXPECTED_HANDOFF_SCHEMA_VERSION = "0.1"
EXPECTED_WORKFLOW = "complete_exp01"
SUPPORTED_PROFILES = ("H24", "L12")


class AIExecutionError(RuntimeError):
    """Error controlado al detectar o ejecutar Archive Workbench AI."""


@dataclass(frozen=True, slots=True)
class AICapabilities:
    executable: str
    plugin: str
    version: str
    profile_default_models: Mapping[str, str]
    transport: str = "cli"
    bridge_dir: Path | None = None

    def model_for_profile(self, profile: str) -> str:
        try:
            return str(self.profile_default_models[profile])
        except KeyError as exc:
            raise AIExecutionError(
                f"Archive Workbench AI no declara un modelo predeterminado para el perfil {profile}."
            ) from exc


@dataclass(frozen=True, slots=True)
class AIExecutionResult:
    analysis_id: str
    handoff_path: Path
    result_path: Path
    handoff_sha256: str
    result_sha256: str
    model_id: str
    target_count: int
    proposal_count: int
    internal_request_count: int


def resolve_ai_executable(explicit: str | None = None) -> str:
    candidate = (
        explicit
        or os.environ.get(AI_EXECUTABLE_ENV)
        or os.environ.get(LEGACY_AI_EXECUTABLE_ENV)
        or ""
    ).strip()
    if candidate:
        path = Path(candidate).expanduser()
        if not path.is_file():
            raise AIExecutionError(
                f"El ejecutable configurado en {AI_EXECUTABLE_ENV} no existe: {path}"
            )
        if not os.access(path, os.X_OK):
            raise AIExecutionError(f"Archive Workbench AI no es ejecutable: {path}")
        return str(path.resolve())
    discovered = shutil.which("aw-ai") or shutil.which("aw-ai01")
    if discovered:
        return str(Path(discovered).resolve())
    raise AIExecutionError(
        "Archive Workbench AI no está disponible. Instalá el componente o definí "
        f"{AI_EXECUTABLE_ENV} con la ruta de aw-ai."
    )


def _run_json(command: list[str], *, timeout: float | None = None) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AIExecutionError(f"No se pudo ejecutar Archive Workbench AI: {exc}") from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        if len(detail) > 2000:
            detail = detail[-2000:]
        suffix = f" Detalle: {detail}" if detail else ""
        raise AIExecutionError(
            f"Archive Workbench AI terminó con código {completed.returncode}.{suffix}"
        )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise AIExecutionError(
            "Archive Workbench AI devolvió una respuesta que no es JSON válido."
        ) from exc
    if not isinstance(payload, dict):
        raise AIExecutionError("Archive Workbench AI devolvió una respuesta JSON inesperada.")
    return payload


def _validate_capabilities_payload(
    payload: dict[str, Any],
    *,
    executable: str,
    transport: str,
    bridge_dir: Path | None = None,
) -> AICapabilities:
    protocols = payload.get("protocols")
    handoffs = payload.get("handoff_schema_ids")
    workflows = payload.get("workflows")
    workflow = workflows.get(EXPECTED_WORKFLOW) if isinstance(workflows, dict) else None
    if not isinstance(protocols, list) or EXPECTED_PROTOCOL not in protocols:
        raise AIExecutionError(
            f"La versión instalada de Archive Workbench AI no declara el protocolo {EXPECTED_PROTOCOL}."
        )
    if not isinstance(handoffs, list) or EXPECTED_HANDOFF_SCHEMA not in handoffs:
        raise AIExecutionError(
            "La versión instalada de Archive Workbench AI no declara el handoff requerido por Archive Workbench."
        )
    if not isinstance(workflow, dict) or workflow.get("command") != "analyze":
        raise AIExecutionError(
            "La versión instalada de Archive Workbench AI no ofrece el workflow complete_exp01."
        )
    if not workflow.get("consolidated_handoff") or not workflow.get("consolidated_result"):
        raise AIExecutionError("Archive Workbench AI no declara salida consolidada para EXP-01.")
    defaults = payload.get("profile_default_models")
    if not isinstance(defaults, dict):
        raise AIExecutionError(
            "Archive Workbench AI no declara modelos predeterminados por perfil."
        )
    clean_defaults = {
        profile: str(defaults[profile])
        for profile in SUPPORTED_PROFILES
        if isinstance(defaults.get(profile), str) and str(defaults[profile]).strip()
    }
    if set(clean_defaults) != set(SUPPORTED_PROFILES):
        raise AIExecutionError("Archive Workbench AI no declara los perfiles H24 y L12 requeridos.")
    if transport == "bridge" and payload.get("bridge_protocol") != EXPECTED_BRIDGE_PROTOCOL:
        raise AIExecutionError(
            "El puente local de Archive Workbench AI no usa un protocolo compatible."
        )
    return AICapabilities(
        executable=executable,
        plugin=str(payload.get("plugin") or "archive-workbench-ai"),
        version=str(payload.get("version") or "desconocida"),
        profile_default_models=clean_defaults,
        transport=transport,
        bridge_dir=bridge_dir,
    )


def _configured_bridge_dir(explicit: Path | str | None = None) -> Path | None:
    raw = str(explicit or os.environ.get(AI_BRIDGE_DIR_ENV) or "").strip()
    if not raw:
        return None
    return Path(raw).expanduser().resolve()


def inspect_ai_capabilities(
    executable: str | None = None,
    *,
    bridge_dir: Path | str | None = None,
) -> AICapabilities:
    configured_bridge = _configured_bridge_dir(bridge_dir)
    if configured_bridge is not None:
        capabilities_path = configured_bridge / "capabilities.json"
        if not capabilities_path.is_file():
            raise AIExecutionError(
                "Archive Workbench AI no está iniciado para la distribución administrada. "
                "Abrí Archive Workbench desde su lanzador después de instalar Archive Workbench AI."
            )
        try:
            payload = json.loads(capabilities_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise AIExecutionError(
                "El puente local de Archive Workbench AI tiene capacidades inválidas."
            ) from exc
        if not isinstance(payload, dict):
            raise AIExecutionError(
                "El puente local de Archive Workbench AI devolvió capacidades inesperadas."
            )
        return _validate_capabilities_payload(
            payload, executable="", transport="bridge", bridge_dir=configured_bridge
        )

    resolved = resolve_ai_executable(executable)
    payload = _run_json([resolved, "capabilities", "--json"], timeout=30)
    return _validate_capabilities_payload(payload, executable=resolved, transport="cli")


def ai_authorization_parameters(
    *,
    capabilities: AICapabilities,
    hardware_profile: str,
    model_id: str,
    export_profile_id: str,
    export_profile_revision: int,
    scope_kind: str,
    selected_unit_ids: tuple[str, ...],
    selected_page_keys: tuple[tuple[str, int], ...],
    max_output_tokens: int = 512,
    temperature: float = 0.0,
    seed: int = 0,
) -> dict[str, Any]:
    if hardware_profile not in SUPPORTED_PROFILES:
        raise ValueError("El perfil de procesamiento debe ser H24 o L12")
    return {
        "component": capabilities.plugin,
        "component_version": capabilities.version,
        "workflow": EXPECTED_WORKFLOW,
        "protocol": EXPECTED_PROTOCOL,
        "handoff_schema": EXPECTED_HANDOFF_SCHEMA,
        "hardware_profile": hardware_profile,
        "backend": "llama_cpp",
        "model_id": model_id,
        "target_types": ["page"],
        "max_output_tokens": int(max_output_tokens),
        "temperature": float(temperature),
        "seed": int(seed),
        "export_profile_id": export_profile_id,
        "export_profile_revision": int(export_profile_revision),
        "scope_kind": scope_kind,
        "selected_unit_ids": list(selected_unit_ids),
        "selected_page_keys": [
            [digital_object_id, int(page_number)]
            for digital_object_id, page_number in selected_page_keys
        ],
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run_bridge_analysis(
    *,
    capabilities: AICapabilities,
    input_path: Path,
    handoff_output_path: Path,
    result_output_path: Path,
    hardware_profile: str,
    model_id: str,
    max_output_tokens: int,
    temperature: float,
    seed: int,
) -> AIExecutionResult:
    bridge_root = capabilities.bridge_dir
    if bridge_root is None:
        raise AIExecutionError("No se configuró el buzón local de Archive Workbench AI.")
    secret_path = bridge_root / "secret.token"
    if not secret_path.is_file():
        raise AIExecutionError("El compañero local de Archive Workbench AI no está inicializado.")
    try:
        authorization = secret_path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise AIExecutionError("No se pudo leer la autorización del compañero local.") from exc
    if len(authorization) < 32:
        raise AIExecutionError("La autorización del compañero local es inválida.")
    jobs_root = bridge_root / "jobs"
    jobs_root.mkdir(parents=True, exist_ok=True)
    job_id = str(uuid.uuid4())
    staging = jobs_root / f".{job_id}.tmp"
    job_dir = jobs_root / job_id
    staging.mkdir(parents=False, exist_ok=False)
    try:
        staged_input = staging / "input.exp01.zip"
        shutil.copyfile(input_path, staged_input)
        request = {
            "bridge_protocol": EXPECTED_BRIDGE_PROTOCOL,
            "job_id": job_id,
            "authorization": authorization,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "hardware_profile": hardware_profile,
            "model_id": model_id,
            "target_types": ["page"],
            "max_output_tokens": int(max_output_tokens),
            "temperature": float(temperature),
            "seed": int(seed),
            "input_sha256": _sha256(staged_input),
        }
        (staging / "request.json").write_text(
            json.dumps(request, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        (staging / "ready").write_text("ready\n", encoding="utf-8")
        staging.replace(job_dir)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    try:
        timeout = float(os.environ.get(AI_BRIDGE_TIMEOUT_ENV, "3600"))
    except ValueError:
        timeout = 3600.0
    deadline = time.monotonic() + max(1.0, timeout)
    response_path = job_dir / "response.json"
    while time.monotonic() < deadline:
        if response_path.is_file():
            break
        time.sleep(0.25)
    else:
        raise AIExecutionError(
            "Archive Workbench AI no terminó el análisis dentro del plazo configurado."
        )
    try:
        payload = json.loads(response_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AIExecutionError("El compañero local devolvió una respuesta inválida.") from exc
    if not isinstance(payload, dict) or payload.get("job_id") != job_id:
        raise AIExecutionError(
            "El compañero local devolvió una respuesta que no corresponde al trabajo solicitado."
        )
    if payload.get("status") != "ok":
        message = str(payload.get("message") or "El análisis asistido no pudo completarse.")
        raise AIExecutionError(message)
    source_handoff = job_dir / "handoff.zip"
    source_result = job_dir / "result.zip"
    if not source_handoff.is_file() or not source_result.is_file():
        raise AIExecutionError(
            "El compañero local no produjo los archivos result/handoff esperados."
        )
    if _sha256(source_handoff) != str(payload.get("handoff_sha256") or ""):
        raise AIExecutionError(
            "El handoff devuelto por el compañero local no supera la verificación de integridad."
        )
    if _sha256(source_result) != str(payload.get("result_sha256") or ""):
        raise AIExecutionError(
            "El resultado devuelto por el compañero local no supera la verificación de integridad."
        )
    shutil.copyfile(source_handoff, handoff_output_path)
    shutil.copyfile(source_result, result_output_path)
    (job_dir / "consumed").write_text(
        time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()) + "\n", encoding="utf-8"
    )
    if str(payload.get("handoff_schema_version")) != EXPECTED_HANDOFF_SCHEMA_VERSION:
        raise AIExecutionError(
            "La versión del resultado generado no es compatible con Archive Workbench."
        )
    return AIExecutionResult(
        analysis_id=str(payload.get("analysis_id") or ""),
        handoff_path=handoff_output_path,
        result_path=result_output_path,
        handoff_sha256=str(payload.get("handoff_sha256") or ""),
        result_sha256=str(payload.get("result_sha256") or ""),
        model_id=str(payload.get("model_id") or model_id),
        target_count=int(payload.get("target_count") or 0),
        proposal_count=int(payload.get("proposal_count") or 0),
        internal_request_count=int(payload.get("internal_request_count") or 0),
    )


def run_ai_analysis(
    *,
    capabilities: AICapabilities,
    input_path: Path,
    handoff_output_path: Path,
    result_output_path: Path,
    hardware_profile: str,
    model_id: str,
    max_output_tokens: int = 512,
    temperature: float = 0.0,
    seed: int = 0,
) -> AIExecutionResult:
    if hardware_profile not in SUPPORTED_PROFILES:
        raise AIExecutionError("El perfil de procesamiento debe ser H24 o L12.")
    if not input_path.is_file():
        raise AIExecutionError(f"No existe el EXP-01 de entrada: {input_path}")
    handoff_output_path.parent.mkdir(parents=True, exist_ok=True)
    result_output_path.parent.mkdir(parents=True, exist_ok=True)
    if capabilities.transport == "bridge":
        return _run_bridge_analysis(
            capabilities=capabilities,
            input_path=input_path,
            handoff_output_path=handoff_output_path,
            result_output_path=result_output_path,
            hardware_profile=hardware_profile,
            model_id=model_id,
            max_output_tokens=max_output_tokens,
            temperature=temperature,
            seed=seed,
        )
    payload = _run_json(
        [
            capabilities.executable,
            "analyze",
            "--input",
            str(input_path),
            "--output",
            str(handoff_output_path),
            "--result-output",
            str(result_output_path),
            "--profile",
            hardware_profile,
            "--backend",
            "llama_cpp",
            "--model",
            model_id,
            "--target-type",
            "page",
            "--max-output-tokens",
            str(max_output_tokens),
            "--temperature",
            str(temperature),
            "--seed",
            str(seed),
        ]
    )
    if payload.get("status") != "ok":
        raise AIExecutionError("Archive Workbench AI no informó un resultado exitoso.")
    if not handoff_output_path.is_file() or not result_output_path.is_file():
        raise AIExecutionError(
            "Archive Workbench AI no produjo los archivos result/handoff esperados."
        )
    if str(payload.get("handoff_schema_version")) != EXPECTED_HANDOFF_SCHEMA_VERSION:
        raise AIExecutionError(
            "La versión del resultado generado no es compatible con Archive Workbench."
        )
    return AIExecutionResult(
        analysis_id=str(payload.get("analysis_id") or ""),
        handoff_path=handoff_output_path,
        result_path=result_output_path,
        handoff_sha256=str(payload.get("handoff_sha256") or ""),
        result_sha256=str(payload.get("result_sha256") or ""),
        model_id=str(payload.get("model_id") or model_id),
        target_count=int(payload.get("target_count") or 0),
        proposal_count=int(payload.get("proposal_count") or 0),
        internal_request_count=int(payload.get("internal_request_count") or 0),
    )
