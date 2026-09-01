from __future__ import annotations

import csv
import difflib
import hashlib
import io
import json
import math
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any, Protocol

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from archive_workbench.contracts.audiovisual import (
    AudiovisualDescription,
    AudiovisualTechnicalMetadata,
    TranscriptSegmentInput,
    TranscriptionRequest,
)
from archive_workbench.db.models import (
    ArchivalUnit,
    AuthorityRecord,
    AudiovisualDerivativeAsset,
    AudiovisualMedia,
    AudiovisualTimelineAnnotation,
    AudiovisualTimelineAnnotationRevision,
    DigitalObject,
    DigitalObjectUnitLink,
    CorpusExportRun,
    FileInstance,
    SegmentEntityMention,
    SourceRegistration,
    TranscriptSegment,
    TranscriptSegmentRevision,
    TranscriptionRun,
    utc_now,
)
from archive_workbench.domain.enums import MediaType
from archive_workbench.identity import new_id, sha256_file
from archive_workbench.exchange import current_editable_state_sha256
from archive_workbench.sources import PROCESSABLE_SOURCE_TYPES

AUDIO_EXTENSIONS = {
    ".aac", ".aif", ".aiff", ".alac", ".flac", ".m4a", ".mp3", ".ogg", ".opus", ".wav", ".wma"
}
VIDEO_EXTENSIONS = {
    ".avi", ".m4v", ".mkv", ".mov", ".mp4", ".mpeg", ".mpg", ".mts", ".m2ts", ".ts", ".webm", ".wmv"
}
_BROWSER_AUDIO_EXTENSIONS = {".mp3", ".wav", ".ogg", ".m4a", ".aac", ".flac"}
_BROWSER_VIDEO_EXTENSIONS = {".mp4", ".webm", ".mov", ".m4v"}
MENTION_STATUSES = ("pending", "accepted", "rejected", "modified")
REVIEW_STATUSES = ("unreviewed", "reviewed", "approved")
TRANSCRIPTION_DISCARDED_STATUS = "discarded"
_TRANSCRIPTION_LIFECYCLE_HISTORY_KEY = "_lifecycle_history"


AUDIOVISUAL_EXPORT_TEXT_POLICIES = (
    "corrected_fallback_original",
    "corrected_only",
    "original_only",
)
AUDIOVISUAL_EXPORT_RUN_SCOPES = ("latest_completed_per_media", "all_completed")
AUDIOVISUAL_EXPORT_FORMATS = ("jsonl", "csv")
AUDIOVISUAL_EXPORT_SCHEMA_VERSION = "1.1"


@dataclass(slots=True, frozen=True)
class AudiovisualExportOptions:
    text_policy: str = "corrected_fallback_original"
    include_review_statuses: tuple[str, ...] = REVIEW_STATUSES
    run_scope: str = "latest_completed_per_media"
    media_ids: tuple[str, ...] | None = None
    include_timeline_annotations: bool = True


@dataclass(slots=True)
class AudiovisualExportPreview:
    total_records: int
    total_characters: int
    records: list[dict[str, Any]]


@dataclass(slots=True)
class AudiovisualExportRunResult:
    run_id: str
    output_path: Path
    row_count: int
    character_count: int
    byte_size: int
    output_sha256: str
    corpus_state_sha256: str


def _validate_audiovisual_export_options(options: AudiovisualExportOptions) -> AudiovisualExportOptions:
    if options.text_policy not in AUDIOVISUAL_EXPORT_TEXT_POLICIES:
        raise ValueError("Política de texto audiovisual inválida")
    invalid_statuses = set(options.include_review_statuses) - set(REVIEW_STATUSES)
    if invalid_statuses:
        raise ValueError("Hay estados de revisión de segmentos inválidos")
    if options.run_scope not in AUDIOVISUAL_EXPORT_RUN_SCOPES:
        raise ValueError("Alcance de corridas de transcripción inválido")
    return AudiovisualExportOptions(
        text_policy=options.text_policy,
        include_review_statuses=tuple(sorted(set(options.include_review_statuses))),
        run_scope=options.run_scope,
        media_ids=(
            tuple(sorted(set(options.media_ids)))
            if options.media_ids is not None
            else None
        ),
        include_timeline_annotations=bool(options.include_timeline_annotations),
    )


def _audiovisual_export_text(segment: TranscriptSegment, policy: str) -> tuple[str, str]:
    original = (segment.original_text or "").strip()
    corrected = (segment.corrected_text or "").strip()
    if policy == "original_only":
        return original, "original_transcription"
    if policy == "corrected_only":
        return corrected, "corrected_transcription"
    if corrected:
        return corrected, "corrected_transcription"
    return original, "original_transcription"


def _transcription_lifecycle_entry(*, action: str, actor: str, from_status: str, to_status: str, note: str | None) -> dict[str, Any]:
    return {
        "action": action,
        "actor": actor or "local_user",
        "at": utc_now().isoformat(),
        "from_status": from_status,
        "to_status": to_status,
        "note": _clean_optional(note),
    }


def discard_transcription_run(
    session: Session,
    *,
    run_id: str,
    actor: str,
    note: str | None = None,
) -> TranscriptionRun:
    """Retira una transcripción completada de los recorridos normales sin borrar su contenido."""

    run = session.get(TranscriptionRun, run_id)
    if run is None:
        raise ValueError("La transcripción no existe")
    if run.status == TRANSCRIPTION_DISCARDED_STATUS:
        return run
    if run.status != "completed":
        raise ValueError("Sólo se puede descartar una transcripción completada")
    options = dict(run.options_json or {})
    history = list(options.get(_TRANSCRIPTION_LIFECYCLE_HISTORY_KEY) or [])
    history.append(
        _transcription_lifecycle_entry(
            action="discard",
            actor=actor,
            from_status=run.status,
            to_status=TRANSCRIPTION_DISCARDED_STATUS,
            note=note,
        )
    )
    options[_TRANSCRIPTION_LIFECYCLE_HISTORY_KEY] = history
    options["_discarded_from_status"] = run.status
    run.options_json = options
    run.status = TRANSCRIPTION_DISCARDED_STATUS
    session.flush()
    return run


def restore_transcription_run(
    session: Session,
    *,
    run_id: str,
    actor: str,
    note: str | None = None,
) -> TranscriptionRun:
    """Restaura una transcripción descartada conservando la traza del descarte."""

    run = session.get(TranscriptionRun, run_id)
    if run is None:
        raise ValueError("La transcripción no existe")
    if run.status != TRANSCRIPTION_DISCARDED_STATUS:
        raise ValueError("La transcripción seleccionada no está descartada")
    options = dict(run.options_json or {})
    restore_status = str(options.get("_discarded_from_status") or "completed")
    if restore_status != "completed":
        restore_status = "completed"
    history = list(options.get(_TRANSCRIPTION_LIFECYCLE_HISTORY_KEY) or [])
    history.append(
        _transcription_lifecycle_entry(
            action="restore",
            actor=actor,
            from_status=TRANSCRIPTION_DISCARDED_STATUS,
            to_status=restore_status,
            note=note,
        )
    )
    options[_TRANSCRIPTION_LIFECYCLE_HISTORY_KEY] = history
    options.pop("_discarded_from_status", None)
    run.options_json = options
    run.status = restore_status
    session.flush()
    return run


def _process_rss_mib() -> float | None:
    status = Path(f"/proc/{os.getpid()}/status")
    try:
        text = status.read_text(encoding="utf-8")
    except OSError:
        return None
    for line in text.splitlines():
        if line.startswith("VmRSS:"):
            parts = line.split()
            if len(parts) >= 2:
                try:
                    return float(parts[1]) / 1024.0
                except ValueError:
                    return None
    return None


def _gpu_memory_mib_for_pid(pid: int) -> float | None:
    if shutil.which("nvidia-smi") is None:
        return None
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-compute-apps=pid,process_name,used_memory",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None

    rows: list[tuple[int, str, float]] = []
    for line in result.stdout.splitlines():
        parts = [part.strip() for part in line.split(",", 2)]
        if len(parts) != 3:
            continue
        try:
            row_pid = int(parts[0])
            memory = float(parts[2])
        except ValueError:
            continue
        rows.append((row_pid, parts[1], memory))

    direct = [memory for row_pid, _name, memory in rows if row_pid == pid]
    if direct:
        return sum(direct)

    containerized = bool(os.environ.get("ARCHIVE_WORKBENCH_RUNTIME_VARIANT")) or Path(
        "/.dockerenv"
    ).exists()
    if not containerized:
        return None

    # NVIDIA reports host-namespace PIDs even when nvidia-smi runs inside a
    # container, while os.getpid() belongs to the container PID namespace.
    # If exactly one compute process has the same executable basename as this
    # Python process, it is safe to use that host PID for this single-process
    # local application. Ambiguous matches deliberately remain unmeasured.
    executable = Path(sys.executable).name
    matching_pids = {
        row_pid
        for row_pid, process_name, _memory in rows
        if Path(process_name).name == executable
    }
    if len(matching_pids) != 1:
        return None
    host_pid = next(iter(matching_pids))
    values = [memory for row_pid, _name, memory in rows if row_pid == host_pid]
    return sum(values) if values else None


class _TranscriptionRuntimeMonitor:
    def __init__(self, *, device: str, interval_seconds: float = 0.25) -> None:
        self.device = device
        self.interval_seconds = interval_seconds
        self.pid = os.getpid()
        self.peak_rss_mib: float | None = None
        self.peak_gpu_memory_mib: float | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _sample(self) -> None:
        rss = _process_rss_mib()
        if rss is not None:
            self.peak_rss_mib = rss if self.peak_rss_mib is None else max(self.peak_rss_mib, rss)
        if self.device == "cuda":
            gpu = _gpu_memory_mib_for_pid(self.pid)
            if gpu is not None:
                self.peak_gpu_memory_mib = (
                    gpu
                    if self.peak_gpu_memory_mib is None
                    else max(self.peak_gpu_memory_mib, gpu)
                )

    def start(self) -> None:
        self._sample()

        def run() -> None:
            while not self._stop.wait(self.interval_seconds):
                self._sample()

        self._thread = threading.Thread(target=run, name="aw-av-runtime-monitor", daemon=True)
        self._thread.start()

    def stop(self) -> dict[str, float | None]:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=max(1.0, self.interval_seconds * 4))
        self._sample()
        return {
            "peak_rss_mib": self.peak_rss_mib,
            "peak_gpu_memory_mib": self.peak_gpu_memory_mib,
        }


@dataclass(slots=True)
class AudiovisualMediaRow:
    media_id: str
    digital_object_id: str
    source_key: str
    archival_title: str
    original_filename: str
    media_type: str
    local_path: str | None
    title: str | None
    duration_seconds: float | None
    container_format: str | None
    audio_codec: str | None
    video_codec: str | None
    latest_run_id: str | None
    latest_run_status: str | None
    segment_count: int


@dataclass(slots=True)
class TranscriptSegmentRow:
    segment_id: str
    run_id: str
    segment_index: int
    start_time: float
    end_time: float
    original_text: str
    corrected_text: str | None
    review_status: str
    revision_number: int

    @property
    def text(self) -> str:
        return self.corrected_text if self.corrected_text is not None else self.original_text


@dataclass(slots=True)
class SegmentSearchRow:
    segment_id: str
    run_id: str
    media_id: str
    source_key: str
    title: str
    original_filename: str
    start_time: float
    end_time: float
    text: str
    review_status: str


@dataclass(slots=True)
class TimelineAnnotationRow:
    annotation_id: str
    media_id: str
    annotation_type: str
    start_time: float
    end_time: float
    label: str
    authority_id: str | None
    authority_name: str | None
    status: str
    revision_number: int


@dataclass(slots=True)
class SegmentMentionRow:
    mention_id: str
    segment_id: str
    authority_id: str | None
    authority_name: str | None
    mention_text: str
    start_offset: int | None
    end_offset: int | None
    segment_revision_number: int
    current_segment_revision: int
    status: str
    note: str | None

    @property
    def is_stale(self) -> bool:
        return self.segment_revision_number != self.current_segment_revision


class TranscriptionBackend(Protocol):
    key: str

    def version(self) -> str | None: ...

    def transcribe(
        self,
        source: Path,
        *,
        model_name: str,
        device: str,
        language: str | None,
        options: dict[str, Any],
    ) -> list[TranscriptSegmentInput]: ...


class FasterWhisperBackend:
    key = "faster_whisper"

    def version(self) -> str | None:
        try:
            from importlib.metadata import version

            return version("faster-whisper")
        except Exception:
            return None

    def transcribe(
        self,
        source: Path,
        *,
        model_name: str,
        device: str,
        language: str | None,
        options: dict[str, Any],
    ) -> list[TranscriptSegmentInput]:
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:  # pragma: no cover - depende del extra opcional
            raise RuntimeError(
                "Falta el backend audiovisual. Instalá Archive Workbench con el extra "
                "audiovisual para usar faster-whisper."
            ) from exc

        compute_type = str(options.get("compute_type") or ("int8" if device == "cpu" else "float16"))
        cpu_threads = int(options.get("cpu_threads") or 0)
        model_kwargs: dict[str, Any] = {"device": device, "compute_type": compute_type}
        if cpu_threads > 0:
            model_kwargs["cpu_threads"] = cpu_threads
        model = WhisperModel(model_name, **model_kwargs)
        transcribe_kwargs: dict[str, Any] = {
            "beam_size": int(options.get("beam_size") or 5),
            "vad_filter": bool(options.get("vad_filter", True)),
        }
        if language:
            transcribe_kwargs["language"] = language
        hotwords = str(options.get("hotwords") or "").strip()
        if hotwords:
            transcribe_kwargs["hotwords"] = hotwords
        segments, _info = model.transcribe(str(source), **transcribe_kwargs)
        return [
            TranscriptSegmentInput(
                start_time=float(item.start),
                end_time=float(item.end),
                text=(item.text or "").strip(),
            )
            for item in segments
            if float(item.end) >= float(item.start)
        ]


_BACKENDS: dict[str, TranscriptionBackend] = {"faster_whisper": FasterWhisperBackend()}


def register_transcription_backend(backend: TranscriptionBackend) -> None:
    _BACKENDS[backend.key] = backend


def transcription_backend_keys() -> tuple[str, ...]:
    return tuple(sorted(_BACKENDS))


_FASTER_WHISPER_MODELS = (
    "tiny",
    "base",
    "small",
    "medium",
    "large-v1",
    "large-v2",
    "large-v3",
    "turbo",
)


def transcription_model_names(backend: str) -> tuple[str, ...]:
    if backend == "faster_whisper":
        return _FASTER_WHISPER_MODELS
    return ()


def transcription_compute_types(device: str) -> tuple[str, ...]:
    normalized = "cuda" if device == "cuda" else "cpu"
    fallback = (
        ("float16", "int8_float16", "int8", "float32", "int8_float32")
        if normalized == "cuda"
        else ("int8", "float32", "int8_float32", "int16")
    )
    try:
        import ctranslate2

        supported = set(ctranslate2.get_supported_compute_types(normalized))
    except Exception:  # pragma: no cover - depende del runtime opcional y del hardware
        return fallback

    preferred_order = (
        ("float16", "int8_float16", "int8", "float32", "int8_float32", "bfloat16", "int16")
        if normalized == "cuda"
        else ("int8", "float32", "int8_float32", "int16", "bfloat16")
    )
    ordered = tuple(item for item in preferred_order if item in supported)
    extras = tuple(sorted(supported.difference(ordered)))
    return ordered + extras or fallback


def _parse_fraction(value: object) -> float | None:
    if value in {None, "", "0/0", "N/A"}:
        return None
    text = str(value)
    if "/" in text:
        numerator, denominator = text.split("/", 1)
        try:
            denominator_value = float(denominator)
            if denominator_value == 0:
                return None
            return float(numerator) / denominator_value
        except ValueError:
            return None
    try:
        return float(text)
    except ValueError:
        return None


def _run_json_command(command: list[str], *, timeout: int = 60) -> dict[str, Any]:
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(f"No se encontró {command[0]} en PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"{command[0]} no respondió dentro del tiempo esperado") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(f"Falló {command[0]}: {detail or f'código {result.returncode}'}")
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{command[0]} devolvió JSON inválido") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"{command[0]} devolvió una estructura inesperada")
    return payload


def probe_audiovisual(path: str | Path, *, media_type: MediaType) -> AudiovisualTechnicalMetadata:
    source = Path(path)
    if media_type not in {MediaType.AUDIO, MediaType.VIDEO}:
        raise ValueError("probe_audiovisual requiere un archivo de audio o video")
    payload = _run_json_command(
        [
            "ffprobe",
            "-v", "error",
            "-show_format",
            "-show_streams",
            "-of", "json",
            str(source),
        ]
    )
    streams = payload.get("streams") if isinstance(payload.get("streams"), list) else []
    format_info = payload.get("format") if isinstance(payload.get("format"), dict) else {}
    audio_stream = next((item for item in streams if item.get("codec_type") == "audio"), None)
    video_stream = next((item for item in streams if item.get("codec_type") == "video"), None)
    duration = _parse_fraction(format_info.get("duration"))
    if duration is None:
        duration = _parse_fraction((video_stream or audio_stream or {}).get("duration"))
    sample_rate = (audio_stream or {}).get("sample_rate")
    try:
        sample_rate_hz = int(sample_rate) if sample_rate is not None else None
    except (TypeError, ValueError):
        sample_rate_hz = None
    return AudiovisualTechnicalMetadata(
        media_type=media_type,
        container_format=str(format_info.get("format_name") or "") or None,
        duration_seconds=duration,
        audio_codec=str((audio_stream or {}).get("codec_name") or "") or None,
        video_codec=str((video_stream or {}).get("codec_name") or "") or None,
        channels=(int(audio_stream["channels"]) if audio_stream and audio_stream.get("channels") else None),
        sample_rate_hz=sample_rate_hz,
        width=(int(video_stream["width"]) if video_stream and video_stream.get("width") else None),
        height=(int(video_stream["height"]) if video_stream and video_stream.get("height") else None),
        frame_rate=_parse_fraction((video_stream or {}).get("avg_frame_rate")),
        raw_probe=payload,
    )


def ffmpeg_version() -> str:
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("No se encontró ffmpeg en PATH")
    result = subprocess.run(
        ["ffmpeg", "-version"], capture_output=True, text=True, check=False, timeout=30
    )
    if result.returncode != 0:
        raise RuntimeError("No se pudo consultar la versión de ffmpeg")
    return (result.stdout.splitlines() or ["ffmpeg"])[0].strip()


def _local_path(session: Session, project_root: Path, digital_object_id: str) -> Path:
    rows = session.scalars(
        select(FileInstance)
        .where(FileInstance.digital_object_id == digital_object_id)
        .order_by(FileInstance.presence != "present", FileInstance.relative_path)
    ).all()
    for row in rows:
        candidate = project_root / row.relative_path
        if candidate.is_file():
            return candidate
    raise FileNotFoundError("No hay una copia local disponible para este medio")


def ensure_audiovisual_media(
    session: Session,
    *,
    project_root: str | Path,
    digital_object_id: str,
    actor: str,
    description: AudiovisualDescription | None = None,
) -> AudiovisualMedia:
    digital = session.get(DigitalObject, digital_object_id)
    if digital is None:
        raise ValueError("El objeto digital no existe")
    media_type = MediaType(digital.media_type)
    if media_type not in {MediaType.AUDIO, MediaType.VIDEO}:
        raise ValueError("El objeto digital no es audiovisual")
    root = Path(project_root).resolve()
    source = _local_path(session, root, digital.id)
    technical = probe_audiovisual(source, media_type=media_type)
    row = session.scalar(
        select(AudiovisualMedia).where(AudiovisualMedia.digital_object_id == digital.id)
    )
    if row is None:
        row = AudiovisualMedia(
            id=new_id(),
            digital_object_id=digital.id,
            title=Path(digital.original_filename).stem,
            updated_by=actor or "local_user",
            updated_at=utc_now(),
        )
        session.add(row)
    row.container_format = technical.container_format
    row.duration_seconds = technical.duration_seconds
    row.audio_codec = technical.audio_codec
    row.video_codec = technical.video_codec
    row.channels = technical.channels
    row.sample_rate_hz = technical.sample_rate_hz
    row.width = technical.width
    row.height = technical.height
    row.frame_rate = technical.frame_rate
    row.technical_json = technical.raw_probe
    row.inspected_at = utc_now()
    row.updated_by = actor or "local_user"
    row.updated_at = utc_now()
    if description is not None:
        _apply_description(row, description)
    session.flush()
    return row


def _clean_optional(value: str | None) -> str | None:
    cleaned = value.strip() if value else ""
    return cleaned or None


def _apply_description(row: AudiovisualMedia, description: AudiovisualDescription) -> None:
    row.title = _clean_optional(description.title)
    row.producer = _clean_optional(description.producer)
    row.channel = _clean_optional(description.channel)
    row.responsible = _clean_optional(description.responsible)
    row.provenance = _clean_optional(description.provenance)
    row.recorded_date = description.recorded_date
    row.rights = _clean_optional(description.rights)
    row.description = _clean_optional(description.description)


def update_audiovisual_description(
    session: Session,
    *,
    media_id: str,
    description: AudiovisualDescription,
    actor: str,
) -> AudiovisualMedia:
    row = session.get(AudiovisualMedia, media_id)
    if row is None:
        raise ValueError("El medio audiovisual no existe")
    _apply_description(row, description)
    row.updated_by = actor or "local_user"
    row.updated_at = utc_now()
    session.flush()
    return row


def audiovisual_media_rows(
    session: Session,
    *,
    project_root: str | Path,
    project_id: str,
) -> list[AudiovisualMediaRow]:
    root = Path(project_root).resolve()
    records = session.execute(
        select(AudiovisualMedia, DigitalObject, SourceRegistration, ArchivalUnit)
        .join(DigitalObject, AudiovisualMedia.digital_object_id == DigitalObject.id)
        .join(SourceRegistration, SourceRegistration.digital_object_id == DigitalObject.id)
        .join(ArchivalUnit, SourceRegistration.archival_unit_id == ArchivalUnit.id)
        .where(
            DigitalObject.project_id == project_id,
            DigitalObject.media_type.in_((MediaType.AUDIO.value, MediaType.VIDEO.value)),
            SourceRegistration.source_type.in_(PROCESSABLE_SOURCE_TYPES),
        )
        .order_by(ArchivalUnit.title, DigitalObject.original_filename)
    ).all()
    output: list[AudiovisualMediaRow] = []
    seen: set[str] = set()
    for media, digital, registration, unit in records:
        if media.id in seen:
            continue
        seen.add(media.id)
        local_path: str | None = None
        for file_row in session.scalars(
            select(FileInstance)
            .where(FileInstance.digital_object_id == digital.id)
            .order_by(FileInstance.presence != "present", FileInstance.relative_path)
        ).all():
            if (root / file_row.relative_path).is_file():
                local_path = file_row.relative_path
                break
        latest = session.scalar(
            select(TranscriptionRun)
            .where(
                TranscriptionRun.audiovisual_media_id == media.id,
                TranscriptionRun.status != TRANSCRIPTION_DISCARDED_STATUS,
            )
            .order_by(TranscriptionRun.created_at.desc())
        )
        count = 0
        if latest is not None:
            count = len(
                session.scalars(
                    select(TranscriptSegment.id).where(TranscriptSegment.transcription_run_id == latest.id)
                ).all()
            )
        output.append(
            AudiovisualMediaRow(
                media_id=media.id,
                digital_object_id=digital.id,
                source_key=registration.source_key,
                archival_title=unit.title,
                original_filename=digital.original_filename,
                media_type=digital.media_type,
                local_path=local_path,
                title=media.title,
                duration_seconds=media.duration_seconds,
                container_format=media.container_format,
                audio_codec=media.audio_codec,
                video_codec=media.video_codec,
                latest_run_id=latest.id if latest else None,
                latest_run_status=latest.status if latest else None,
                segment_count=count,
            )
        )
    return output


def _safe_output_dir(project_root: Path, media_id: str) -> Path:
    output = project_root / "derivatives" / "audiovisual" / media_id
    output.mkdir(parents=True, exist_ok=True)
    return output


def _record_derivative(
    session: Session,
    *,
    media: AudiovisualMedia,
    digital: DigitalObject,
    project_root: Path,
    output_path: Path,
    asset_kind: str,
    command: list[str],
    actor: str,
    container_format: str | None,
    codec: str | None,
) -> AudiovisualDerivativeAsset:
    digest = sha256_file(output_path)
    relative = output_path.relative_to(project_root).as_posix()
    existing = session.scalar(
        select(AudiovisualDerivativeAsset).where(
            AudiovisualDerivativeAsset.audiovisual_media_id == media.id,
            AudiovisualDerivativeAsset.asset_kind == asset_kind,
            AudiovisualDerivativeAsset.sha256 == digest,
        )
    )
    if existing is not None:
        return existing
    row = AudiovisualDerivativeAsset(
        id=new_id(),
        audiovisual_media_id=media.id,
        asset_kind=asset_kind,
        relative_path=relative,
        sha256=digest,
        byte_size=output_path.stat().st_size,
        mime_type=mimetypes.guess_type(output_path.name)[0],
        container_format=container_format,
        codec=codec,
        source_sha256=digital.sha256,
        ffmpeg_version=ffmpeg_version(),
        command_json=command,
        created_by=actor or "local_user",
        created_at=utc_now(),
    )
    session.add(row)
    session.flush()
    return row


def _run_ffmpeg(command: list[str], *, timeout: int = 3600) -> None:
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("No se encontró ffmpeg en PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("ffmpeg excedió el tiempo de ejecución permitido") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise RuntimeError("Falló ffmpeg: " + (detail[-3000:] if detail else "sin diagnóstico"))


def ensure_transcription_audio(
    session: Session,
    *,
    project_root: str | Path,
    media_id: str,
    actor: str,
) -> AudiovisualDerivativeAsset:
    root = Path(project_root).resolve()
    media = session.get(AudiovisualMedia, media_id)
    if media is None:
        raise ValueError("El medio audiovisual no existe")
    digital = session.get(DigitalObject, media.digital_object_id)
    if digital is None:
        raise ValueError("El original audiovisual no existe")
    source = _local_path(session, root, digital.id)
    output_dir = _safe_output_dir(root, media.id)
    output = output_dir / f"transcription_{digital.sha256[:16]}.wav"
    if not output.is_file():
        temporary = output.with_suffix(".wav.tmp")
        command = [
            "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(source), "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", "-f", "wav", str(temporary),
        ]
        _run_ffmpeg(command)
        temporary.replace(output)
    command = [
        "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(source), "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(output),
    ]
    return _record_derivative(
        session,
        media=media,
        digital=digital,
        project_root=root,
        output_path=output,
        asset_kind="transcription_audio",
        command=command,
        actor=actor,
        container_format="wav",
        codec="pcm_s16le",
    )


def resolve_playback_path(
    session: Session,
    *,
    project_root: str | Path,
    media_id: str,
) -> Path | None:
    root = Path(project_root).resolve()
    media = session.get(AudiovisualMedia, media_id)
    if media is None:
        raise ValueError("El medio audiovisual no existe")
    digital = session.get(DigitalObject, media.digital_object_id)
    if digital is None:
        raise ValueError("El original audiovisual no existe")
    try:
        source = _local_path(session, root, digital.id)
    except FileNotFoundError:
        source = None
    if source is not None:
        extension = source.suffix.lower()
        if digital.media_type == MediaType.AUDIO.value and extension in _BROWSER_AUDIO_EXTENSIONS:
            return source
        if digital.media_type == MediaType.VIDEO.value and extension in _BROWSER_VIDEO_EXTENSIONS:
            return source
    asset = session.scalar(
        select(AudiovisualDerivativeAsset)
        .where(
            AudiovisualDerivativeAsset.audiovisual_media_id == media.id,
            AudiovisualDerivativeAsset.asset_kind == "playback",
        )
        .order_by(AudiovisualDerivativeAsset.created_at.desc())
    )
    if asset is None:
        return None
    candidate = root / asset.relative_path
    return candidate if candidate.is_file() else None


def ensure_playback_asset(
    session: Session,
    *,
    project_root: str | Path,
    media_id: str,
    actor: str,
) -> Path:
    root = Path(project_root).resolve()
    media = session.get(AudiovisualMedia, media_id)
    if media is None:
        raise ValueError("El medio audiovisual no existe")
    digital = session.get(DigitalObject, media.digital_object_id)
    if digital is None:
        raise ValueError("El original audiovisual no existe")
    source = _local_path(session, root, digital.id)
    extension = source.suffix.lower()
    if digital.media_type == MediaType.AUDIO.value and extension in _BROWSER_AUDIO_EXTENSIONS:
        return source
    if digital.media_type == MediaType.VIDEO.value and extension in _BROWSER_VIDEO_EXTENSIONS:
        return source
    output_dir = _safe_output_dir(root, media.id)
    if digital.media_type == MediaType.AUDIO.value:
        output = output_dir / f"playback_{digital.sha256[:16]}.mp3"
        command = [
            "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
            "-vn", "-c:a", "libmp3lame", "-q:a", "3", str(output),
        ]
        container_format, codec = "mp3", "mp3"
    else:
        output = output_dir / f"playback_{digital.sha256[:16]}.mp4"
        command = [
            "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-c:a", "aac", "-movflags", "+faststart", str(output),
        ]
        container_format, codec = "mp4", "h264+aac"
    if not output.is_file():
        temporary = output.with_name(output.stem + ".tmp" + output.suffix)
        command_for_write = command[:-1] + [str(temporary)]
        _run_ffmpeg(command_for_write)
        temporary.replace(output)
    _record_derivative(
        session,
        media=media,
        digital=digital,
        project_root=root,
        output_path=output,
        asset_kind="playback",
        command=command,
        actor=actor,
        container_format=container_format,
        codec=codec,
    )
    return output


def transcribe_audiovisual(
    session: Session,
    *,
    project_root: str | Path,
    media_id: str,
    request: TranscriptionRequest,
    actor: str,
) -> TranscriptionRun:
    media = session.get(AudiovisualMedia, media_id)
    if media is None:
        raise ValueError("El medio audiovisual no existe")
    backend = _BACKENDS.get(request.backend)
    if backend is None:
        raise ValueError(f"Backend de transcripción desconocido: {request.backend}")
    source_asset = ensure_transcription_audio(
        session, project_root=project_root, media_id=media.id, actor=actor
    )
    root = Path(project_root).resolve()
    source = root / source_asset.relative_path
    effective_options = dict(request.options)
    effective_options.setdefault("beam_size", 5)
    effective_options.setdefault("vad_filter", True)
    run = TranscriptionRun(
        id=new_id(),
        audiovisual_media_id=media.id,
        source_asset_id=source_asset.id,
        backend=request.backend,
        backend_version=backend.version(),
        model_name=request.model_name,
        device=request.device,
        language=request.language,
        options_json=dict(effective_options),
        status="running",
        created_by=actor or "local_user",
        created_at=utc_now(),
    )
    session.add(run)
    session.flush()
    monitor = _TranscriptionRuntimeMonitor(device=request.device)
    wall_started = time.perf_counter()
    cpu_started = time.process_time()
    monitor.start()
    try:
        segments = backend.transcribe(
            source,
            model_name=request.model_name,
            device=request.device,
            language=request.language,
            options=dict(effective_options),
        )
        previous_end = 0.0
        for index, item in enumerate(segments):
            start = max(0.0, float(item.start_time))
            end = max(start, float(item.end_time))
            if start + 1e-6 < previous_end:
                raise ValueError("El backend devolvió segmentos temporales solapados o desordenados")
            previous_end = end
            text = item.text.strip()
            segment = TranscriptSegment(
                id=new_id(),
                transcription_run_id=run.id,
                segment_index=index,
                start_time=start,
                end_time=end,
                original_text=text,
                corrected_text=None,
                review_status="unreviewed",
                revision_number=1,
                updated_by=actor or "local_user",
                updated_at=utc_now(),
            )
            session.add(segment)
            session.flush()
            session.add(
                TranscriptSegmentRevision(
                    id=new_id(),
                    segment_id=segment.id,
                    revision_number=1,
                    operation="baseline",
                    snapshot_json=_segment_snapshot(segment),
                    note=None,
                    changed_by=actor or "local_user",
                    changed_at=utc_now(),
                )
            )
        run.status = "completed"
        run.completed_at = utc_now()
    except Exception as exc:
        run.status = "failed"
        run.error_text = str(exc)
        run.completed_at = utc_now()
    finally:
        sampled = monitor.stop()
        wall_seconds = max(0.0, time.perf_counter() - wall_started)
        process_cpu_seconds = max(0.0, time.process_time() - cpu_started)
        runtime_metrics = {
            "wall_seconds": wall_seconds,
            "process_cpu_seconds": process_cpu_seconds,
            "average_cpu_cores": (process_cpu_seconds / wall_seconds if wall_seconds > 0 else None),
            **sampled,
        }
        stored_options = dict(run.options_json or {})
        stored_options["_runtime_metrics"] = runtime_metrics
        run.options_json = stored_options
    session.flush()
    return run


def _segment_snapshot(segment: TranscriptSegment) -> dict[str, Any]:
    return {
        "segment_index": segment.segment_index,
        "start_time": segment.start_time,
        "end_time": segment.end_time,
        "original_text": segment.original_text,
        "corrected_text": segment.corrected_text,
        "review_status": segment.review_status,
        "revision_number": segment.revision_number,
    }


def transcript_segment_rows(session: Session, *, run_id: str) -> list[TranscriptSegmentRow]:
    rows = session.scalars(
        select(TranscriptSegment)
        .where(TranscriptSegment.transcription_run_id == run_id)
        .order_by(TranscriptSegment.segment_index)
    ).all()
    return [
        TranscriptSegmentRow(
            segment_id=row.id,
            run_id=row.transcription_run_id,
            segment_index=row.segment_index,
            start_time=row.start_time,
            end_time=row.end_time,
            original_text=row.original_text,
            corrected_text=row.corrected_text,
            review_status=row.review_status,
            revision_number=row.revision_number,
        )
        for row in rows
    ]



@dataclass(slots=True)
class TranscriptDocumentUpdate:
    run_id: str
    changed_segment_count: int
    total_segment_count: int
    review_status: str | None


def _transcript_document_layout(
    rows: list[TranscriptSegmentRow],
) -> tuple[str, list[int]]:
    """Construye texto legible y conserva el final textual de cada anclaje."""

    chunks: list[str] = []
    ends: list[int] = []
    cursor = 0
    paragraph_chars = 0
    previous: TranscriptSegmentRow | None = None
    for row in rows:
        text = row.text.strip()
        if not text:
            ends.append(cursor)
            previous = row
            continue
        if previous is not None and chunks:
            gap = max(0.0, float(row.start_time) - float(previous.end_time))
            previous_text = previous.text.rstrip()
            paragraph_break = (
                gap >= 1.5
                or paragraph_chars >= 700
                or (paragraph_chars >= 420 and previous_text.endswith((".", "?", "!", "…")))
            )
            separator = "\n\n" if paragraph_break else " "
            chunks.append(separator)
            cursor += len(separator)
            paragraph_chars = 0 if paragraph_break else paragraph_chars + len(separator)
        chunks.append(text)
        cursor += len(text)
        paragraph_chars += len(text)
        ends.append(cursor)
        previous = row
    return "".join(chunks).strip(), ends


def transcript_document_text(session: Session, *, run_id: str) -> str:
    """Devuelve la transcripción vigente como un único texto editable."""

    rows = transcript_segment_rows(session, run_id=run_id)
    text, _ends = _transcript_document_layout(rows)
    return text


def _mapped_boundary(
    matcher: difflib.SequenceMatcher,
    *,
    old_pos: int,
    new_length: int,
) -> int:
    """Transfiere una frontera del texto anterior al texto editado."""

    opcodes = matcher.get_opcodes()
    last_new = 0
    for tag, i1, i2, j1, j2 in opcodes:
        if old_pos < i1:
            return max(0, min(new_length, last_new))
        if i1 <= old_pos <= i2:
            if tag == "equal":
                return max(0, min(new_length, j1 + (old_pos - i1)))
            if i2 == i1:
                return max(0, min(new_length, j2))
            ratio = (old_pos - i1) / (i2 - i1)
            mapped = round(j1 + ratio * (j2 - j1))
            return max(0, min(new_length, mapped))
        last_new = j2
    return new_length


def update_transcript_document(
    session: Session,
    *,
    run_id: str,
    corrected_text: str,
    actor: str,
    review_status: str | None = None,
    note: str | None = None,
) -> TranscriptDocumentUpdate:
    """Guarda una edición continua conservando las fronteras temporales existentes.

    Los segmentos siguen siendo los anclajes de tiempo. La interfaz no obliga a
    editarlos uno por uno: las fronteras se transfieren al texto corregido mediante
    una alineación textual y sólo los segmentos cuyo contenido cambió reciben una
    nueva revisión.
    """

    if review_status is not None and review_status not in REVIEW_STATUSES:
        raise ValueError(f"Estado de revisión inválido: {review_status}")
    run = session.get(TranscriptionRun, run_id)
    if run is None:
        raise ValueError("La corrida de transcripción no existe")
    rows = session.scalars(
        select(TranscriptSegment)
        .where(TranscriptSegment.transcription_run_id == run_id)
        .order_by(TranscriptSegment.segment_index)
    ).all()
    if not rows:
        raise ValueError("La corrida seleccionada no tiene segmentos")

    new_text = corrected_text.strip()
    if not new_text:
        raise ValueError("La transcripción no puede quedar vacía")

    current_parts = [
        (row.corrected_text if row.corrected_text is not None else row.original_text).strip()
        for row in rows
    ]
    row_views = [
        TranscriptSegmentRow(
            segment_id=row.id,
            run_id=row.transcription_run_id,
            segment_index=row.segment_index,
            start_time=row.start_time,
            end_time=row.end_time,
            original_text=row.original_text,
            corrected_text=row.corrected_text,
            review_status=row.review_status,
            revision_number=row.revision_number,
        )
        for row in rows
    ]
    old_text, old_ends = _transcript_document_layout(row_views)

    if old_text == new_text and review_status is None:
        return TranscriptDocumentUpdate(
            run_id=run_id,
            changed_segment_count=0,
            total_segment_count=len(rows),
            review_status=None,
        )

    # Se transfieren únicamente los finales de segmento. Así el texto editado
    # queda cubierto de punta a punta, incluso cuando una inserción cae justo
    # sobre una frontera temporal.
    matcher = difflib.SequenceMatcher(a=old_text, b=new_text, autojunk=False)
    new_ends: list[int] = []
    previous_end = 0
    for index, old_end in enumerate(old_ends):
        mapped_end = (
            len(new_text)
            if index == len(old_ends) - 1
            else _mapped_boundary(matcher, old_pos=old_end, new_length=len(new_text))
        )
        mapped_end = max(previous_end, min(len(new_text), mapped_end))
        new_ends.append(mapped_end)
        previous_end = mapped_end

    redistributed: list[str] = []
    previous_end = 0
    for new_end in new_ends:
        redistributed.append(new_text[previous_end:new_end].strip())
        previous_end = new_end

    # Evita que una coma o un punto insertados en una frontera queden como
    # primer carácter del segmento siguiente y reaparezcan con un espacio
    # artificial al reconstruir el texto continuo.
    leading_punctuation = set(",.;:!?%)]}»”’")
    for index in range(1, len(redistributed)):
        while redistributed[index] and redistributed[index][0] in leading_punctuation:
            redistributed[index - 1] = redistributed[index - 1].rstrip() + redistributed[index][0]
            redistributed[index] = redistributed[index][1:].lstrip()

    changed = 0
    now = utc_now()
    editor = actor or "local_user"
    clean_note = _clean_optional(note)
    for row, value, previous in zip(rows, redistributed, current_parts, strict=True):
        next_status = review_status if review_status is not None else row.review_status
        if value == previous and next_status == row.review_status:
            continue
        row.corrected_text = value
        row.review_status = next_status
        row.revision_number += 1
        row.updated_by = editor
        row.updated_at = now
        session.flush()
        session.add(
            TranscriptSegmentRevision(
                id=new_id(),
                segment_id=row.id,
                revision_number=row.revision_number,
                operation="continuous_edit",
                snapshot_json=_segment_snapshot(row),
                note=clean_note,
                changed_by=editor,
                changed_at=now,
            )
        )
        changed += 1
    session.flush()
    return TranscriptDocumentUpdate(
        run_id=run_id,
        changed_segment_count=changed,
        total_segment_count=len(rows),
        review_status=review_status,
    )

def update_transcript_segment(
    session: Session,
    *,
    segment_id: str,
    corrected_text: str,
    review_status: str,
    actor: str,
    note: str | None = None,
) -> TranscriptSegment:
    if review_status not in REVIEW_STATUSES:
        raise ValueError(f"Estado de revisión inválido: {review_status}")
    segment = session.get(TranscriptSegment, segment_id)
    if segment is None:
        raise ValueError("El segmento no existe")
    text = corrected_text.strip()
    if not text:
        raise ValueError("El texto corregido no puede quedar vacío")
    segment.corrected_text = text
    segment.review_status = review_status
    segment.revision_number += 1
    segment.updated_by = actor or "local_user"
    segment.updated_at = utc_now()
    session.flush()
    session.add(
        TranscriptSegmentRevision(
            id=new_id(),
            segment_id=segment.id,
            revision_number=segment.revision_number,
            operation="edit",
            snapshot_json=_segment_snapshot(segment),
            note=_clean_optional(note),
            changed_by=actor or "local_user",
            changed_at=utc_now(),
        )
    )
    session.flush()
    return segment


def segment_revision_rows(session: Session, *, segment_id: str) -> list[TranscriptSegmentRevision]:
    return session.scalars(
        select(TranscriptSegmentRevision)
        .where(TranscriptSegmentRevision.segment_id == segment_id)
        .order_by(TranscriptSegmentRevision.revision_number.desc())
    ).all()


def _normalize_mention(value: str) -> str:
    return " ".join(value.casefold().split())


def create_segment_mention(
    session: Session,
    *,
    segment_id: str,
    mention_text: str,
    authority_id: str | None,
    status: str,
    actor: str,
    note: str | None = None,
) -> SegmentEntityMention:
    if status not in MENTION_STATUSES:
        raise ValueError(f"Estado de mención inválido: {status}")
    segment = session.get(TranscriptSegment, segment_id)
    if segment is None:
        raise ValueError("El segmento no existe")
    text = mention_text.strip()
    if not text:
        raise ValueError("La mención no puede estar vacía")
    current_text = segment.corrected_text if segment.corrected_text is not None else segment.original_text
    start = current_text.casefold().find(text.casefold())
    start_offset = start if start >= 0 else None
    end_offset = start + len(text) if start >= 0 else None
    if authority_id is not None and session.get(AuthorityRecord, authority_id) is None:
        raise ValueError("La autoridad seleccionada no existe")
    row = SegmentEntityMention(
        id=new_id(),
        segment_id=segment.id,
        authority_id=authority_id,
        mention_text=text,
        normalized_text=_normalize_mention(text),
        start_offset=start_offset,
        end_offset=end_offset,
        segment_revision_number=segment.revision_number,
        status=status,
        source="manual",
        note=_clean_optional(note),
        created_by=actor or "local_user",
        created_at=utc_now(),
        updated_by=actor or "local_user",
        updated_at=utc_now(),
    )
    session.add(row)
    session.flush()
    return row


def segment_mention_rows(session: Session, *, segment_id: str) -> list[SegmentMentionRow]:
    rows = session.execute(
        select(SegmentEntityMention, TranscriptSegment, AuthorityRecord)
        .join(TranscriptSegment, SegmentEntityMention.segment_id == TranscriptSegment.id)
        .outerjoin(AuthorityRecord, SegmentEntityMention.authority_id == AuthorityRecord.id)
        .where(SegmentEntityMention.segment_id == segment_id)
        .order_by(SegmentEntityMention.created_at, SegmentEntityMention.id)
    ).all()
    return [
        SegmentMentionRow(
            mention_id=mention.id,
            segment_id=mention.segment_id,
            authority_id=mention.authority_id,
            authority_name=authority.preferred_name if authority else None,
            mention_text=mention.mention_text,
            start_offset=mention.start_offset,
            end_offset=mention.end_offset,
            segment_revision_number=mention.segment_revision_number,
            current_segment_revision=segment.revision_number,
            status=mention.status,
            note=mention.note,
        )
        for mention, segment, authority in rows
    ]


def _timeline_annotation_snapshot(row: AudiovisualTimelineAnnotation) -> dict[str, Any]:
    return {
        "audiovisual_media_id": row.audiovisual_media_id,
        "annotation_type": row.annotation_type,
        "start_time": row.start_time,
        "end_time": row.end_time,
        "label": row.label,
        "authority_id": row.authority_id,
        "status": row.status,
        "revision_number": row.revision_number,
    }


def create_timeline_annotation(
    session: Session,
    *,
    media_id: str,
    annotation_type: str,
    start_time: float,
    end_time: float,
    label: str,
    authority_id: str | None,
    actor: str,
) -> AudiovisualTimelineAnnotation:
    media = session.get(AudiovisualMedia, media_id)
    if media is None:
        raise ValueError("No se encontró el medio audiovisual seleccionado.")
    kind = annotation_type.strip().lower()
    if kind not in {"speaker", "annotation"}:
        raise ValueError("Elegí si querés registrar un hablante o una anotación.")
    clean_label = " ".join(label.split()).strip()
    if not clean_label:
        if kind == "speaker":
            raise ValueError("Escribí el nombre o la etiqueta del hablante.")
        raise ValueError("Escribí la anotación que querés asociar al tramo.")
    start = float(start_time)
    end = float(end_time)
    if start < 0 or end < start:
        raise ValueError("El tramo temporal seleccionado no es válido.")
    if media.duration_seconds is not None and end > float(media.duration_seconds) + 0.25:
        raise ValueError("El tramo seleccionado supera la duración del medio.")

    authority = None
    if authority_id:
        authority = session.get(AuthorityRecord, authority_id)
        if authority is None:
            raise ValueError("La autoridad seleccionada ya no existe.")
        digital = session.get(DigitalObject, media.digital_object_id)
        if digital is None or authority.project_id != digital.project_id:
            raise ValueError("La autoridad seleccionada pertenece a otro proyecto.")

    now = utc_now()
    row = AudiovisualTimelineAnnotation(
        id=new_id(),
        audiovisual_media_id=media_id,
        annotation_type=kind,
        start_time=start,
        end_time=end,
        label=clean_label,
        authority_id=authority.id if authority is not None else None,
        status="active",
        revision_number=1,
        created_by=actor,
        created_at=now,
        updated_by=actor,
        updated_at=now,
    )
    session.add(row)
    session.flush()
    session.add(
        AudiovisualTimelineAnnotationRevision(
            id=new_id(),
            annotation_id=row.id,
            revision_number=1,
            operation="create",
            snapshot_json=_timeline_annotation_snapshot(row),
            changed_by=actor,
            changed_at=now,
        )
    )
    session.flush()
    return row


def _update_timeline_annotation(
    session: Session,
    *,
    row: AudiovisualTimelineAnnotation,
    start_time: float | None = None,
    end_time: float | None = None,
    label: str | None = None,
    authority_id: str | None = None,
    change_authority: bool = False,
    actor: str,
) -> AudiovisualTimelineAnnotation:
    if start_time is not None:
        row.start_time = float(start_time)
    if end_time is not None:
        row.end_time = float(end_time)
    if row.start_time < 0 or row.end_time < row.start_time:
        raise ValueError("El tramo temporal seleccionado no es válido.")
    if label is not None:
        clean_label = " ".join(label.split()).strip()
        if not clean_label:
            raise ValueError("Escribí el nombre o la etiqueta del hablante.")
        row.label = clean_label
    if change_authority:
        row.authority_id = authority_id
    row.revision_number += 1
    row.updated_by = actor
    row.updated_at = utc_now()
    session.flush()
    session.add(
        AudiovisualTimelineAnnotationRevision(
            id=new_id(),
            annotation_id=row.id,
            revision_number=row.revision_number,
            operation="update",
            snapshot_json=_timeline_annotation_snapshot(row),
            changed_by=actor,
            changed_at=row.updated_at,
        )
    )
    session.flush()
    return row


def assign_speaker_from_time(
    session: Session,
    *,
    media_id: str,
    time_seconds: float,
    label: str,
    authority_id: str | None,
    actor: str,
) -> AudiovisualTimelineAnnotation:
    """Abre un turno de hablante desde el tiempo actual y cierra el turno anterior."""

    media = session.get(AudiovisualMedia, media_id)
    if media is None:
        raise ValueError("No se encontró el medio audiovisual seleccionado.")
    duration = float(media.duration_seconds or 0.0)
    current = max(0.0, float(time_seconds))
    if duration > 0:
        current = min(current, duration)

    clean_label = " ".join(label.split()).strip()
    if not clean_label:
        raise ValueError("Elegí o escribí quién está hablando.")
    if authority_id:
        authority = session.get(AuthorityRecord, authority_id)
        if authority is None:
            raise ValueError("La autoridad seleccionada ya no existe.")
        digital = session.get(DigitalObject, media.digital_object_id)
        if digital is None or authority.project_id != digital.project_id:
            raise ValueError("La autoridad seleccionada pertenece a otro proyecto.")

    speakers = session.scalars(
        select(AudiovisualTimelineAnnotation)
        .where(
            AudiovisualTimelineAnnotation.audiovisual_media_id == media_id,
            AudiovisualTimelineAnnotation.annotation_type == "speaker",
            AudiovisualTimelineAnnotation.status == "active",
        )
        .order_by(
            AudiovisualTimelineAnnotation.start_time,
            AudiovisualTimelineAnnotation.id,
        )
    ).all()
    epsilon = 0.01
    future_starts = [
        float(row.start_time)
        for row in speakers
        if float(row.start_time) > current + epsilon
    ]
    next_boundary = min(future_starts) if future_starts else duration
    if next_boundary < current:
        next_boundary = current

    same_start = next(
        (row for row in speakers if abs(float(row.start_time) - current) <= epsilon),
        None,
    )
    if same_start is not None:
        return _update_timeline_annotation(
            session,
            row=same_start,
            end_time=max(current, next_boundary),
            label=clean_label,
            authority_id=authority_id,
            change_authority=True,
            actor=actor,
        )

    covering = [
        row
        for row in speakers
        if float(row.start_time) < current - epsilon and float(row.end_time) > current + epsilon
    ]
    if covering:
        previous = max(covering, key=lambda row: float(row.start_time))
        if previous.label == clean_label and previous.authority_id == authority_id:
            return previous
        _update_timeline_annotation(
            session,
            row=previous,
            end_time=current,
            actor=actor,
        )

    return create_timeline_annotation(
        session,
        media_id=media_id,
        annotation_type="speaker",
        start_time=current,
        end_time=max(current, next_boundary),
        label=clean_label,
        authority_id=authority_id,
        actor=actor,
    )


def assign_speaker_to_segment(
    session: Session,
    *,
    media_id: str,
    start_time: float,
    end_time: float,
    label: str,
    authority_id: str | None,
    actor: str,
) -> AudiovisualTimelineAnnotation:
    """Asigna un hablante sólo al segmento indicado sin alterar los tramos vecinos."""

    media = session.get(AudiovisualMedia, media_id)
    if media is None:
        raise ValueError("No se encontró el medio audiovisual seleccionado.")
    start = max(0.0, float(start_time))
    end = max(start, float(end_time))
    duration = float(media.duration_seconds or 0.0)
    if duration > 0:
        start = min(start, duration)
        end = min(max(start, end), duration)
    if end <= start:
        raise ValueError("El segmento seleccionado no tiene una duración válida.")

    clean_label = " ".join(label.split()).strip()
    if not clean_label:
        raise ValueError("Elegí o escribí quién está hablando.")
    if authority_id:
        authority = session.get(AuthorityRecord, authority_id)
        if authority is None:
            raise ValueError("La autoridad seleccionada ya no existe.")
        digital = session.get(DigitalObject, media.digital_object_id)
        if digital is None or authority.project_id != digital.project_id:
            raise ValueError("La autoridad seleccionada pertenece a otro proyecto.")

    speakers = session.scalars(
        select(AudiovisualTimelineAnnotation)
        .where(
            AudiovisualTimelineAnnotation.audiovisual_media_id == media_id,
            AudiovisualTimelineAnnotation.annotation_type == "speaker",
            AudiovisualTimelineAnnotation.status == "active",
        )
        .order_by(
            AudiovisualTimelineAnnotation.start_time,
            AudiovisualTimelineAnnotation.id,
        )
    ).all()
    epsilon = 0.001

    # Si el mismo hablante ya cubre por completo el segmento, no se crea una marca redundante.
    for row in speakers:
        if (
            row.label == clean_label
            and row.authority_id == authority_id
            and float(row.start_time) <= start + epsilon
            and float(row.end_time) >= end - epsilon
        ):
            return row

    overlapping = [
        row
        for row in speakers
        if float(row.end_time) > start + epsilon and float(row.start_time) < end - epsilon
    ]
    for row in overlapping:
        old_start = float(row.start_time)
        old_end = float(row.end_time)
        old_label = row.label
        old_authority_id = row.authority_id

        if old_start < start - epsilon and old_end > end + epsilon:
            # El turno existente atraviesa todo el segmento: se conservan sus dos lados.
            _update_timeline_annotation(
                session, row=row, end_time=start, actor=actor
            )
            create_timeline_annotation(
                session,
                media_id=media_id,
                annotation_type="speaker",
                start_time=end,
                end_time=old_end,
                label=old_label,
                authority_id=old_authority_id,
                actor=actor,
            )
        elif old_start < start - epsilon:
            # Se conserva sólo la parte anterior al segmento.
            _update_timeline_annotation(
                session, row=row, end_time=start, actor=actor
            )
        elif old_end > end + epsilon:
            # Se conserva sólo la parte posterior al segmento.
            _update_timeline_annotation(
                session, row=row, start_time=end, actor=actor
            )
        else:
            # La marca existente está enteramente dentro del segmento reemplazado.
            archive_timeline_annotation(session, annotation_id=row.id, actor=actor)

    return create_timeline_annotation(
        session,
        media_id=media_id,
        annotation_type="speaker",
        start_time=start,
        end_time=end,
        label=clean_label,
        authority_id=authority_id,
        actor=actor,
    )


def timeline_annotation_rows(
    session: Session,
    *,
    media_id: str,
    include_archived: bool = False,
) -> list[TimelineAnnotationRow]:
    statement = (
        select(AudiovisualTimelineAnnotation, AuthorityRecord.preferred_name)
        .outerjoin(AuthorityRecord, AuthorityRecord.id == AudiovisualTimelineAnnotation.authority_id)
        .where(AudiovisualTimelineAnnotation.audiovisual_media_id == media_id)
        .order_by(
            AudiovisualTimelineAnnotation.start_time,
            AudiovisualTimelineAnnotation.end_time,
            AudiovisualTimelineAnnotation.id,
        )
    )
    if not include_archived:
        statement = statement.where(AudiovisualTimelineAnnotation.status == "active")
    rows = session.execute(statement).all()
    return [
        TimelineAnnotationRow(
            annotation_id=row.id,
            media_id=row.audiovisual_media_id,
            annotation_type=row.annotation_type,
            start_time=row.start_time,
            end_time=row.end_time,
            label=row.label,
            authority_id=row.authority_id,
            authority_name=authority_name,
            status=row.status,
            revision_number=row.revision_number,
        )
        for row, authority_name in rows
    ]


def archive_timeline_annotation(
    session: Session,
    *,
    annotation_id: str,
    actor: str,
) -> AudiovisualTimelineAnnotation:
    row = session.get(AudiovisualTimelineAnnotation, annotation_id)
    if row is None:
        raise ValueError("La marca temporal seleccionada ya no existe.")
    if row.status == "archived":
        return row
    row.status = "archived"
    row.revision_number += 1
    row.updated_by = actor
    row.updated_at = utc_now()
    session.flush()
    session.add(
        AudiovisualTimelineAnnotationRevision(
            id=new_id(),
            annotation_id=row.id,
            revision_number=row.revision_number,
            operation="archive",
            snapshot_json=_timeline_annotation_snapshot(row),
            changed_by=actor,
            changed_at=row.updated_at,
        )
    )
    session.flush()
    return row


def _speaker_for_segment(
    row: TranscriptSegmentRow,
    annotations: list[TimelineAnnotationRow],
) -> TimelineAnnotationRow | None:
    candidates = [
        mark
        for mark in annotations
        if mark.annotation_type == "speaker"
        and mark.end_time > row.start_time
        and mark.start_time < row.end_time
    ]
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda mark: min(row.end_time, mark.end_time) - max(row.start_time, mark.start_time),
    )


def transcript_with_timeline_marks(
    session: Session,
    *,
    run_id: str,
) -> str:
    run = session.get(TranscriptionRun, run_id)
    if run is None:
        raise ValueError("No se encontró la corrida de transcripción seleccionada.")
    segments = transcript_segment_rows(session, run_id=run_id)
    annotations = timeline_annotation_rows(session, media_id=run.audiovisual_media_id)
    if not annotations:
        return transcript_document_text(session, run_id=run_id)

    notes = [mark for mark in annotations if mark.annotation_type == "annotation"]
    note_index = 0
    lines: list[str] = []
    current_speaker: str | None = None
    current_text: list[str] = []

    def flush() -> None:
        nonlocal current_text
        if not current_text:
            return
        text = " ".join(part for part in current_text if part).strip()
        if text:
            lines.append(f"{current_speaker}: {text}" if current_speaker else text)
        current_text = []

    for segment in segments:
        while note_index < len(notes) and notes[note_index].start_time < segment.end_time:
            note = notes[note_index]
            if note.start_time >= segment.start_time:
                flush()
                lines.append(f"[{format_timestamp(note.start_time)} · {note.label}]")
            note_index += 1
        speaker = _speaker_for_segment(segment, annotations)
        speaker_label = None
        if speaker is not None:
            speaker_label = speaker.authority_name or speaker.label
        if speaker_label != current_speaker:
            flush()
            current_speaker = speaker_label
        text = segment.text.strip()
        if text:
            current_text.append(text)
    flush()
    while note_index < len(notes):
        note = notes[note_index]
        lines.append(f"[{format_timestamp(note.start_time)} · {note.label}]")
        note_index += 1
    return "\n\n".join(lines).strip()


def search_transcript_segments(
    session: Session,
    *,
    project_id: str,
    query: str,
    limit: int = 100,
) -> list[SegmentSearchRow]:
    needle = query.strip()
    if not needle:
        return []
    pattern = f"%{needle}%"
    rows = session.execute(
        select(
            TranscriptSegment,
            TranscriptionRun,
            AudiovisualMedia,
            DigitalObject,
            SourceRegistration,
        )
        .join(TranscriptionRun, TranscriptSegment.transcription_run_id == TranscriptionRun.id)
        .join(AudiovisualMedia, TranscriptionRun.audiovisual_media_id == AudiovisualMedia.id)
        .join(DigitalObject, AudiovisualMedia.digital_object_id == DigitalObject.id)
        .join(SourceRegistration, SourceRegistration.digital_object_id == DigitalObject.id)
        .where(
            DigitalObject.project_id == project_id,
            SourceRegistration.source_type.in_(PROCESSABLE_SOURCE_TYPES),
            TranscriptionRun.status == "completed",
            or_(
                TranscriptSegment.corrected_text.ilike(pattern),
                TranscriptSegment.original_text.ilike(pattern),
            ),
        )
        .order_by(DigitalObject.original_filename, TranscriptSegment.start_time)
        .limit(max(1, int(limit)))
    ).all()
    output: list[SegmentSearchRow] = []
    seen: set[str] = set()
    for segment, run, media, digital, registration in rows:
        if segment.id in seen:
            continue
        seen.add(segment.id)
        output.append(
            SegmentSearchRow(
                segment_id=segment.id,
                run_id=run.id,
                media_id=media.id,
                source_key=registration.source_key,
                title=media.title or digital.original_filename,
                original_filename=digital.original_filename,
                start_time=segment.start_time,
                end_time=segment.end_time,
                text=segment.corrected_text if segment.corrected_text is not None else segment.original_text,
                review_status=segment.review_status,
            )
        )
    return output


def format_timestamp(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    whole = int(seconds)
    hours, remainder = divmod(whole, 3600)
    minutes, secs = divmod(remainder, 60)
    milliseconds = int(round((seconds - whole) * 1000))
    if milliseconds == 1000:
        seconds += 1
        return format_timestamp(seconds)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}.{milliseconds:03d}"
    return f"{minutes:02d}:{secs:02d}.{milliseconds:03d}"


def _selected_transcription_run_ids(
    session: Session,
    *,
    project_id: str,
    options: AudiovisualExportOptions,
) -> set[str]:
    query = (
        select(TranscriptionRun)
        .join(AudiovisualMedia, TranscriptionRun.audiovisual_media_id == AudiovisualMedia.id)
        .join(DigitalObject, AudiovisualMedia.digital_object_id == DigitalObject.id)
        .where(
            DigitalObject.project_id == project_id,
            TranscriptionRun.status == "completed",
        )
    )
    if options.media_ids is not None:
        if not options.media_ids:
            return set()
        query = query.where(AudiovisualMedia.id.in_(options.media_ids))
    runs = session.scalars(
        query.order_by(
            TranscriptionRun.audiovisual_media_id,
            TranscriptionRun.created_at,
            TranscriptionRun.id,
        )
    ).all()
    if options.run_scope == "all_completed":
        return {row.id for row in runs}
    latest_by_media: dict[str, TranscriptionRun] = {}
    for row in runs:
        latest_by_media[row.audiovisual_media_id] = row
    return {row.id for row in latest_by_media.values()}


def _export_rows(
    session: Session,
    *,
    project_id: str,
    options: AudiovisualExportOptions | None = None,
) -> list[dict[str, Any]]:
    selected_options = _validate_audiovisual_export_options(
        options or AudiovisualExportOptions(
            run_scope="all_completed", include_review_statuses=REVIEW_STATUSES
        )
    )
    run_ids = _selected_transcription_run_ids(
        session,
        project_id=project_id,
        options=selected_options,
    )
    if not run_ids:
        return []
    if not selected_options.include_review_statuses:
        return []
    query = (
        select(
            TranscriptSegment,
            TranscriptionRun,
            AudiovisualMedia,
            DigitalObject,
            SourceRegistration,
        )
        .join(TranscriptionRun, TranscriptSegment.transcription_run_id == TranscriptionRun.id)
        .join(AudiovisualMedia, TranscriptionRun.audiovisual_media_id == AudiovisualMedia.id)
        .join(DigitalObject, AudiovisualMedia.digital_object_id == DigitalObject.id)
        .join(SourceRegistration, SourceRegistration.digital_object_id == DigitalObject.id)
        .where(
            DigitalObject.project_id == project_id,
            SourceRegistration.source_type.in_(PROCESSABLE_SOURCE_TYPES),
            TranscriptionRun.id.in_(run_ids),
        )
    )
    if selected_options.include_review_statuses:
        query = query.where(
            TranscriptSegment.review_status.in_(selected_options.include_review_statuses)
        )
    rows = session.execute(
        query.order_by(
            DigitalObject.original_filename,
            TranscriptionRun.created_at,
            TranscriptSegment.segment_index,
        )
    ).all()
    media_ids = {media.id for _, _, media, _, _ in rows}
    annotation_map: dict[str, list[TimelineAnnotationRow]] = {media_id: [] for media_id in media_ids}
    if selected_options.include_timeline_annotations:
        for media_id in media_ids:
            annotation_map[media_id] = timeline_annotation_rows(session, media_id=media_id)

    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for segment, run, media, digital, registration in rows:
        if segment.id in seen:
            continue
        seen.add(segment.id)
        text, text_source = _audiovisual_export_text(segment, selected_options.text_policy)
        if not text:
            continue
        platform_payload = (registration.source_payload_json or {}).get("platform_import")
        if not isinstance(platform_payload, dict):
            platform_payload = {}
        overlapping_annotations = [
            mark
            for mark in annotation_map.get(media.id, [])
            if mark.end_time > segment.start_time and mark.start_time < segment.end_time
        ]
        result.append(
            {
                "export_schema_version": AUDIOVISUAL_EXPORT_SCHEMA_VERSION,
                "record_type": "archive_workbench.audiovisual_transcript_segment",
                "project_id": project_id,
                "export_configuration": asdict(selected_options),
                "source_key": registration.source_key,
                "source_type": registration.source_type,
                "source_origin": (registration.source_payload_json or {}).get("origin"),
                "platform": platform_payload.get("platform"),
                "platform_id": platform_payload.get("platform_id"),
                "source_url": platform_payload.get("webpage_url"),
                "source_access_conditions": platform_payload.get("access_conditions"),
                "digital_object_id": digital.id,
                "original_filename": digital.original_filename,
                "original_sha256": digital.sha256,
                "media_type": digital.media_type,
                "media_id": media.id,
                "media_title": media.title,
                "transcription_run_id": run.id,
                "transcription_run_created_at": run.created_at.isoformat(),
                "backend": run.backend,
                "backend_version": run.backend_version,
                "model_name": run.model_name,
                "device": run.device,
                "language": run.language,
                "segment_id": segment.id,
                "segment_index": segment.segment_index,
                "start_time": segment.start_time,
                "end_time": segment.end_time,
                "text": text,
                "text_source": text_source,
                "original_text": segment.original_text,
                "corrected_text": segment.corrected_text,
                "review_status": segment.review_status,
                "revision_number": segment.revision_number,
                "timeline_annotations": [
                    {
                        "type": mark.annotation_type,
                        "start_time": mark.start_time,
                        "end_time": mark.end_time,
                        "label": mark.label,
                        "authority_id": mark.authority_id,
                        "authority_name": mark.authority_name,
                    }
                    for mark in overlapping_annotations
                ],
            }
        )
    return result


def _serialize_audiovisual_rows(rows: list[dict[str, Any]], output_format: str) -> bytes:
    if output_format == "jsonl":
        payload = "".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows
        )
        return payload.encode("utf-8")
    if output_format == "csv":
        buffer = io.StringIO(newline="")
        fieldnames = list(rows[0]) if rows else [
            "export_schema_version", "record_type", "project_id", "export_configuration",
            "source_key", "source_type",
            "source_origin", "platform", "platform_id", "source_url",
            "source_access_conditions", "digital_object_id", "original_filename",
            "original_sha256", "media_type", "media_id", "media_title",
            "transcription_run_id", "transcription_run_created_at", "backend",
            "backend_version", "model_name", "device", "language", "segment_id",
            "segment_index", "start_time", "end_time", "text", "text_source",
            "original_text", "corrected_text", "review_status", "revision_number",
            "timeline_annotations",
        ]
        writer = csv.DictWriter(buffer, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            payload = dict(row)
            if isinstance(payload.get("export_configuration"), dict):
                payload["export_configuration"] = json.dumps(
                    payload["export_configuration"], ensure_ascii=False
                )
            payload["timeline_annotations"] = json.dumps(
                payload.get("timeline_annotations") or [], ensure_ascii=False
            )
            writer.writerow(payload)
        return buffer.getvalue().encode("utf-8")
    raise ValueError("Formato audiovisual de exportación inválido")


def export_transcript_segments_bytes(
    session: Session,
    *,
    project_id: str,
    output_format: str,
    options: AudiovisualExportOptions | None = None,
) -> tuple[bytes, int]:
    if output_format not in AUDIOVISUAL_EXPORT_FORMATS:
        raise ValueError("Formato audiovisual de exportación inválido")
    rows = _export_rows(session, project_id=project_id, options=options)
    return _serialize_audiovisual_rows(rows, output_format), len(rows)


def preview_transcript_export(
    session: Session,
    *,
    project_id: str,
    options: AudiovisualExportOptions,
    limit: int = 20,
) -> AudiovisualExportPreview:
    rows = _export_rows(session, project_id=project_id, options=options)
    return AudiovisualExportPreview(
        total_records=len(rows),
        total_characters=sum(len(str(row.get("text") or "")) for row in rows),
        records=rows[: max(0, limit)],
    )


def default_audiovisual_export_filename(output_format: str) -> str:
    if output_format not in AUDIOVISUAL_EXPORT_FORMATS:
        raise ValueError("Formato audiovisual de exportación inválido")
    timestamp = utc_now().strftime("%Y%m%dT%H%M%SZ")
    return f"exports/transcripciones_audiovisuales_{timestamp}.{output_format}"


def _safe_audiovisual_export_output_path(
    project_root: Path, relative_path: str, output_format: str
) -> tuple[Path, str]:
    raw = relative_path.strip()
    if not raw:
        raise ValueError("Indicá una ruta de salida relativa a la carpeta del proyecto")
    candidate = (project_root / raw).resolve()
    try:
        relative = candidate.relative_to(project_root.resolve())
    except ValueError as exc:
        raise ValueError("La exportación debe quedar dentro de la carpeta del proyecto") from exc
    extension = f".{output_format}"
    if candidate.suffix.lower() != extension:
        candidate = candidate.with_suffix(extension)
        relative = candidate.relative_to(project_root.resolve())
    return candidate, relative.as_posix()


def run_audiovisual_export(
    session: Session,
    *,
    project_root: Path,
    project_id: str,
    options: AudiovisualExportOptions,
    output_relative_path: str,
    output_format: str,
    created_by: str,
    overwrite: bool = False,
) -> AudiovisualExportRunResult:
    if output_format not in AUDIOVISUAL_EXPORT_FORMATS:
        raise ValueError("Formato audiovisual de exportación inválido")
    selected_options = _validate_audiovisual_export_options(options)
    rows = _export_rows(session, project_id=project_id, options=selected_options)
    output_path, relative = _safe_audiovisual_export_output_path(
        project_root, output_relative_path, output_format
    )
    if output_path.exists() and not overwrite:
        raise ValueError(
            f"La salida ya existe: {relative}. Elegí otro nombre o habilitá sobrescritura explícita."
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    state_digest = current_editable_state_sha256(session, project_id)
    run_id = new_id()
    exported_at = utc_now()
    for row in rows:
        row["export_run_id"] = run_id
        row["exported_at"] = exported_at.isoformat()
        row["corpus_state_sha256"] = state_digest
    payload = _serialize_audiovisual_rows(rows, output_format)
    temporary = output_path.with_name(output_path.name + ".tmp")
    try:
        temporary.write_bytes(payload)
        temporary.replace(output_path)
    finally:
        temporary.unlink(missing_ok=True)
    digest = hashlib.sha256(payload).hexdigest()
    snapshot = {
        "material_type": "audiovisual_transcript_segments",
        "schema_version": AUDIOVISUAL_EXPORT_SCHEMA_VERSION,
        "options": asdict(selected_options),
    }
    character_count = sum(len(str(row.get("text") or "")) for row in rows)
    session.add(
        CorpusExportRun(
            id=run_id,
            project_id=project_id,
            profile_id=None,
            profile_name="Transcripciones de audio y video",
            profile_snapshot_json=snapshot,
            corpus_state_sha256=state_digest,
            output_format=output_format,
            output_relative_path=relative,
            row_count=len(rows),
            character_count=character_count,
            byte_size=output_path.stat().st_size,
            output_sha256=digest,
            created_by=created_by or "local_user",
            created_at=exported_at,
        )
    )
    session.flush()
    return AudiovisualExportRunResult(
        run_id=run_id,
        output_path=output_path,
        row_count=len(rows),
        character_count=character_count,
        byte_size=output_path.stat().st_size,
        output_sha256=digest,
        corpus_state_sha256=state_digest,
    )

