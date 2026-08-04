from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from html.parser import HTMLParser
from importlib import metadata
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL

from archive_workbench.contracts.decisions import ProjectDecisions
from archive_workbench.contracts.extraction import (
    ExtractedObjectRecord,
    ExtractionProfile,
    PageGeometry,
)
from archive_workbench.identity import stable_id


SURYA_LABEL_MAP: dict[str, str] = {
    "Caption": "caption",
    "Footnote": "footnote",
    "Equation": "unknown",
    "ListGroup": "list_item",
    "PageHeader": "page_header",
    "PageFooter": "page_footer",
    "Picture": "figure",
    "SectionHeader": "section_heading",
    "Table": "table",
    "Text": "paragraph",
    "Figure": "figure",
    "Code": "paragraph",
    "Form": "form_field",
    "TableOfContents": "table_of_contents",
    "ChemicalBlock": "unknown",
    "Diagram": "figure",
    "Bibliography": "paragraph",
}


class SuryaExecutionError(RuntimeError):
    """Error del subproceso Surya con el diagnóstico completo preservado."""

    def __init__(self, message: str, *, log_text: str = "") -> None:
        super().__init__(message)
        self.log_text = log_text


@dataclass(frozen=True, slots=True)
class SuryaServerInfo:
    name: str
    status: str
    image: str
    running: bool


class _VisibleTextParser(HTMLParser):
    _BLOCK_TAGS = {
        "address",
        "article",
        "aside",
        "blockquote",
        "div",
        "figcaption",
        "footer",
        "form",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "header",
        "li",
        "main",
        "nav",
        "ol",
        "p",
        "pre",
        "section",
        "table",
        "tr",
        "ul",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def _separator(self, value: str = "\n") -> None:
        if not self.parts or self.parts[-1] != value:
            self.parts.append(value)

    def handle_starttag(self, tag: str, _attrs) -> None:
        tag = tag.lower()
        if tag == "br":
            self._separator()
        elif tag in {"td", "th"}:
            if self.parts and self.parts[-1] not in {"\n", "\t"}:
                self.parts.append("\t")
        elif tag in self._BLOCK_TAGS:
            self._separator()

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"td", "th"}:
            self.parts.append("\t")
        elif tag in self._BLOCK_TAGS:
            self._separator()

    def handle_data(self, data: str) -> None:
        if data:
            self.parts.append(data)


def html_to_text(value: str) -> str:
    parser = _VisibleTextParser()
    parser.feed(value or "")
    parser.close()
    lines: list[str] = []
    for line in "".join(parser.parts).splitlines():
        normalized = re.sub(r"[ \t\f\v]+", " ", line).strip()
        if normalized:
            lines.append(normalized)
    return "\n".join(lines)


def resolve_surya_command(command: str) -> str:
    path = Path(command).expanduser()
    if path.is_absolute():
        return str(path)
    if len(path.parts) > 1:
        return str((Path.cwd() / path).resolve())
    return command


def surya_version(command: str) -> str | None:
    resolved_command = resolve_surya_command(command)
    command_path = Path(resolved_command)
    sibling_python = command_path.parent / "python"
    if command_path.parent != Path(".") and sibling_python.is_file():
        try:
            result = subprocess.run(
                [
                    str(sibling_python),
                    "-c",
                    "import importlib.metadata as m; print(m.version('surya-ocr'))",
                ],
                text=True,
                capture_output=True,
                timeout=30,
                check=False,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            result = None
        if result is not None and result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip().splitlines()[0]

    try:
        return metadata.version("surya-ocr")
    except metadata.PackageNotFoundError:
        pass

    try:
        result = subprocess.run(
            [resolved_command, "--version"],
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    output = (result.stdout or result.stderr or "").strip()
    return output.splitlines()[0] if result.returncode == 0 and output else None


def _backend_from_profile(profile: ExtractionProfile) -> str | None:
    if profile.device == "cuda":
        return "vllm"
    if profile.device == "cpu":
        return "llamacpp"
    return None


def resolve_surya_torch_device(profile: ExtractionProfile) -> str:
    """Resuelve el dispositivo auxiliar sin contradecir el backend solicitado."""

    if profile.surya_torch_device != "auto":
        return profile.surya_torch_device
    if profile.device in {"cpu", "cuda"}:
        return profile.device
    return "auto"


def _accelerator_backend_failure(text: str) -> bool:
    normalized = text.casefold()
    markers = (
        "cuda",
        "cudnn",
        "cublas",
        "vllm",
        "nvidia",
        "gpu",
        "docker",
        "container",
        "out of memory",
        "connection refused",
        "failed to start inference",
    )
    return any(marker in normalized for marker in markers)


def _command_log(
    command: list[str],
    result: subprocess.CompletedProcess[str],
    *,
    backend: str | None,
    inference_url: str | None,
    torch_device: str,
    clean_library_path: bool,
    keep_server: bool,
) -> str:
    parts = [f"$ {shlex.join(command)}", f"exit_code={result.returncode}"]
    parts.append(f"SURYA_INFERENCE_BACKEND={backend or 'auto'}")
    parts.append(f"SURYA_INFERENCE_URL={inference_url or '-'}")
    parts.append(f"TORCH_DEVICE={torch_device}")
    parts.append(f"ARCHIVE_WORKBENCH_CLEAN_LD_LIBRARY_PATH={int(clean_library_path)}")
    parts.append(f"SURYA_INFERENCE_KEEP_ALIVE={int(keep_server)}")
    if result.stdout and result.stdout.strip():
        parts.extend(["--- stdout ---", result.stdout.strip()])
    if result.stderr and result.stderr.strip():
        parts.extend(["--- stderr ---", result.stderr.strip()])
    return "\n".join(parts)


def list_surya_servers() -> list[SuryaServerInfo]:
    """Lista contenedores vLLM creados por Surya sin alterar su estado."""

    try:
        result = subprocess.run(
            [
                "docker",
                "ps",
                "-a",
                "--filter",
                "name=surya-vllm-",
                "--format",
                "{{.Names}}\t{{.Status}}\t{{.Image}}",
            ],
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []
    if result.returncode != 0:
        return []
    servers: list[SuryaServerInfo] = []
    for line in result.stdout.splitlines():
        parts = line.split("\t", 2)
        if len(parts) != 3:
            continue
        name, status, image = (part.strip() for part in parts)
        servers.append(
            SuryaServerInfo(
                name=name,
                status=status,
                image=image,
                running=status.casefold().startswith("up "),
            )
        )
    return servers


def stop_surya_servers() -> list[str]:
    """Detiene los contenedores vLLM persistentes creados por Surya."""

    stopped: list[str] = []
    for server in list_surya_servers():
        if not server.running:
            continue
        try:
            result = subprocess.run(
                ["docker", "stop", server.name],
                text=True,
                capture_output=True,
                timeout=120,
                check=False,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
        if result.returncode == 0:
            stopped.append(server.name)
    return stopped


def _find_results_json(output_dir: Path) -> Path:
    direct = output_dir / "results.json"
    if direct.is_file():
        return direct
    candidates = sorted(output_dir.rglob("results.json"))
    if not candidates:
        raise SuryaExecutionError(
            "Surya terminó sin producir results.json",
            log_text=f"Directorio de salida: {output_dir}",
        )
    return candidates[0]


def _payload_for_stem(results: dict[str, Any], stem: str) -> dict[str, Any] | None:
    candidates = [stem, f"{stem}.png", f"{stem}.jpg", f"{stem}.jpeg", f"{stem}.webp"]
    value: Any = None
    for key in candidates:
        if key in results:
            value = results[key]
            break
    if value is None:
        matching = [item for key, item in results.items() if Path(str(key)).stem == stem]
        if len(matching) == 1:
            value = matching[0]
    if isinstance(value, list) and len(value) == 1 and isinstance(value[0], dict):
        return value[0]
    if isinstance(value, dict):
        return value
    return None


def _run_surya_attempt(
    source_images: list[tuple[int, Path]],
    attempt_dir: Path,
    profile: ExtractionProfile,
    *,
    backend: str | None,
) -> tuple[dict[int, Path], str]:
    input_dir = attempt_dir / "input"
    output_dir = attempt_dir / "output"
    pages_dir = attempt_dir / "pages"
    input_dir.mkdir(parents=True, exist_ok=False)
    output_dir.mkdir(parents=True, exist_ok=False)
    pages_dir.mkdir(parents=True, exist_ok=False)

    expected_stems: dict[int, str] = {}
    for page_number, source_image in source_images:
        stem = f"page_{page_number:04d}"
        suffix = source_image.suffix.lower() or ".png"
        destination = input_dir / f"{stem}{suffix}"
        try:
            os.link(source_image, destination)
        except OSError:
            shutil.copy2(source_image, destination)
        expected_stems[page_number] = stem

    resolved_command = resolve_surya_command(profile.surya_command)
    command = [
        resolved_command,
        str(input_dir),
        "--output_dir",
        str(output_dir),
    ]
    if profile.surya_keep_server:
        command.append("--keep_server")

    env = os.environ.copy()
    if profile.surya_clean_library_path:
        env.pop("LD_LIBRARY_PATH", None)
    if backend:
        env["SURYA_INFERENCE_BACKEND"] = backend
    if profile.surya_inference_url:
        env["SURYA_INFERENCE_URL"] = profile.surya_inference_url
    env["SURYA_INFERENCE_PARALLEL"] = str(profile.surya_parallel)
    env["SURYA_INFERENCE_KEEP_ALIVE"] = "1" if profile.surya_keep_server else "0"
    torch_device = resolve_surya_torch_device(profile)
    if torch_device != "auto":
        env["TORCH_DEVICE"] = torch_device

    timeout = profile.document_timeout_seconds * len(source_images) + 300
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
        raise SuryaExecutionError(
            f"No se encontró '{profile.surya_command}'. Ejecute scripts/install_surya_runtime.sh o configure una ruta absoluta al ejecutable surya_ocr.",
            log_text=f"$ {shlex.join(command)}",
        ) from exc
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = exc.stderr.decode() if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        log_text = "\n".join(
            part
            for part in (
                f"$ {shlex.join(command)}",
                f"SURYA_INFERENCE_BACKEND={backend or 'auto'}",
                f"TORCH_DEVICE={env.get('TORCH_DEVICE', 'auto')}",
                f"ARCHIVE_WORKBENCH_CLEAN_LD_LIBRARY_PATH={int(profile.surya_clean_library_path)}",
                stdout.strip(),
                stderr.strip(),
            )
            if part
        )
        raise SuryaExecutionError(
            f"Surya superó {timeout} segundos para {len(source_images)} página(s)",
            log_text=log_text,
        ) from exc

    log_text = _command_log(
        command,
        result,
        backend=backend,
        inference_url=env.get("SURYA_INFERENCE_URL"),
        torch_device=env.get("TORCH_DEVICE", "auto"),
        clean_library_path=profile.surya_clean_library_path,
        keep_server=profile.surya_keep_server,
    )
    if result.returncode != 0:
        diagnostic = (result.stderr or result.stdout or "").strip()
        tail = "\n".join(diagnostic.splitlines()[-40:])
        raise SuryaExecutionError(
            f"Surya terminó con código {result.returncode} usando "
            f"backend={backend or 'auto'}:\n{tail}",
            log_text=log_text,
        )

    results_path = _find_results_json(output_dir)
    try:
        results = json.loads(results_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SuryaExecutionError(
            f"No se pudo leer la salida de Surya: {results_path}",
            log_text=log_text,
        ) from exc
    if not isinstance(results, dict):
        raise SuryaExecutionError(
            "Surya produjo results.json con una estructura inesperada",
            log_text=log_text,
        )

    page_outputs: dict[int, Path] = {}
    missing: list[int] = []
    for page_number, stem in expected_stems.items():
        page_payload = _payload_for_stem(results, stem)
        if page_payload is None:
            missing.append(page_number)
            continue
        destination = pages_dir / f"page_{page_number:04d}.json"
        destination.write_text(
            json.dumps(page_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        page_outputs[page_number] = destination
    if missing:
        raise SuryaExecutionError(
            "Surya no produjo resultados para las páginas: "
            + ", ".join(map(str, missing))
            + ". Claves encontradas: "
            + (", ".join(map(str, results)) or "ninguna"),
            log_text=log_text,
        )
    return page_outputs, log_text


def run_surya_cli_batch(
    source_images: list[tuple[int, Path]],
    work_dir: Path,
    profile: ExtractionProfile,
) -> tuple[dict[int, Path], str | None, str]:
    if not source_images:
        raise ValueError("No se proporcionaron páginas a Surya")
    first_backend = _backend_from_profile(profile)
    try:
        outputs, log_text = _run_surya_attempt(
            source_images,
            work_dir / "attempt_1",
            profile,
            backend=first_backend,
        )
        return outputs, surya_version(profile.surya_command), log_text
    except SuryaExecutionError as first_error:
        can_fallback = (
            profile.retry_on_accelerator_error
            and profile.fallback_device == "cpu"
            and first_backend != "llamacpp"
            and not (profile.surya_inference_url or os.environ.get("SURYA_INFERENCE_URL"))
            and _accelerator_backend_failure(
                f"{first_error}\n{first_error.log_text}"
            )
        )
        if not can_fallback:
            raise
        outputs, fallback_log = _run_surya_attempt(
            source_images,
            work_dir / "attempt_2_cpu",
            profile,
            backend="llamacpp",
        )
        combined = "\n\n".join(
            [
                first_error.log_text,
                "ARCHIVE_WORKBENCH_FALLBACK_DEVICE=cpu",
                fallback_log,
            ]
        )
        return outputs, surya_version(profile.surya_command), combined


def _geometry_from_surya(
    block: dict[str, Any], *, page_number: int, width: int, height: int
) -> list[PageGeometry]:
    polygon = block.get("polygon")
    points: list[tuple[float, float]] = []
    if isinstance(polygon, list) and len(polygon) >= 4:
        for point in polygon[:4]:
            if not isinstance(point, (list, tuple)) or len(point) < 2:
                points = []
                break
            try:
                points.append((float(point[0]), float(point[1])))
            except (TypeError, ValueError):
                points = []
                break
    if not points:
        bbox = block.get("bbox")
        if isinstance(bbox, list) and len(bbox) >= 4:
            try:
                left, top, right, bottom = map(float, bbox[:4])
                points = [(left, top), (right, top), (right, bottom), (left, bottom)]
            except (TypeError, ValueError):
                points = []
    if not points or width <= 0 or height <= 0:
        return []
    normalized = [
        (
            min(max(x / width, 0.0), 1.0),
            min(max(y / height, 0.0), 1.0),
        )
        for x, y in points
    ]
    try:
        return [PageGeometry(page=page_number, polygon=normalized)]
    except ValueError:
        return []


def normalize_surya_page(
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
    blocks = payload.get("blocks")
    if not isinstance(blocks, list):
        raise ValueError("La página de Surya no contiene una lista 'blocks'")
    type_settings = {item.key: item for item in decisions.object_types}
    ordered: list[tuple[int, int, dict[str, Any]]] = []
    for index, block in enumerate(blocks):
        if not isinstance(block, dict):
            continue
        try:
            reading_order = int(block.get("reading_order", index))
        except (TypeError, ValueError):
            reading_order = index
        ordered.append((reading_order, index, block))
    ordered.sort(key=lambda item: (item[0], item[1]))

    result: list[ExtractedObjectRecord] = []
    for reading_order, source_index, block in ordered:
        label = str(block.get("label") or "Text")
        if label == "BlankPage":
            continue
        object_type = SURYA_LABEL_MAP.get(label, "unknown")
        if object_type not in type_settings:
            object_type = "unknown"
        html = str(block.get("html") or "")
        text = html_to_text(html)
        settings = type_settings.get(object_type)
        raw_label = str(block.get("raw_label") or label)
        geometry = _geometry_from_surya(
            block,
            page_number=page_number,
            width=width,
            height=height,
        )
        try:
            confidence_raw = block.get("confidence")
            confidence = float(confidence_raw) if confidence_raw is not None else None
        except (TypeError, ValueError):
            confidence = None
        if confidence is not None and not 0 <= confidence <= 1:
            confidence = None
        object_id = stable_id(
            NAMESPACE_URL,
            "archive-workbench",
            digital_object_id,
            page_number,
            "surya",
            reading_order,
            raw_label,
            geometry[0].model_dump_json() if geometry else source_index,
        )
        result.append(
            ExtractedObjectRecord(
                object_id=object_id,
                digital_object_id=digital_object_id,
                extraction_run_id=extraction_run_id,
                order_index=order_start + len(result),
                object_type=object_type,
                original_text=text,
                geometry=geometry,
                source_label=label,
                confidence=confidence,
                hidden_by_default=(settings is not None and not settings.visible_by_default),
                attributes={
                    "backend": "surya_cli",
                    "surya_label": label,
                    "surya_raw_label": raw_label,
                    "reading_order": reading_order,
                    "html": html,
                    "skipped": bool(block.get("skipped", False)),
                    "error": bool(block.get("error", False)),
                    "token_count_estimate": block.get("count"),
                },
            )
        )
    return result
