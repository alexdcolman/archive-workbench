from __future__ import annotations

import json
import math
import re
import statistics
import unicodedata
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from archive_workbench.audiovisual import TranscriptSegmentRow, transcript_segment_rows
from archive_workbench.db.models import AudiovisualMedia, TranscriptionRun


@dataclass(frozen=True, slots=True)
class EvaluationSample:
    ordinal: int
    segment_id: str
    segment_index: int
    start_time: float
    end_time: float
    reviewed: bool


@dataclass(frozen=True, slots=True)
class ReferenceWindowComparison:
    ordinal: int
    start_time: float
    end_time: float
    reference_text: str
    candidate_text: str
    candidate_context_text: str
    scoreable: bool
    cer: float | None
    wer: float | None


@dataclass(frozen=True, slots=True)
class TranscriptionReferenceComparison:
    reference_run_id: str
    candidate_run_id: str
    sample_size: int
    cer: float | None
    wer: float | None
    candidate_words: int
    reference_words: int
    windows: tuple[ReferenceWindowComparison, ...]

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["windows"] = [asdict(item) for item in self.windows]
        return payload


@dataclass(frozen=True, slots=True)
class TranscriptionEvaluation:
    run_id: str
    media_id: str
    status: str
    backend: str
    backend_version: str | None
    model_name: str
    device: str
    language: str | None
    compute_type: str | None
    created_at: str
    completed_at: str | None
    wall_seconds: float | None
    process_cpu_seconds: float | None
    average_cpu_cores: float | None
    peak_rss_mib: float | None
    peak_gpu_memory_mib: float | None
    media_duration_seconds: float | None
    realtime_factor: float | None
    segment_count: int
    speech_seconds: float
    speech_coverage_ratio: float | None
    median_segment_seconds: float | None
    max_segment_seconds: float | None
    total_gap_seconds: float
    short_segment_count: int
    long_segment_count: int
    empty_segment_count: int
    sample_size: int
    reviewed_sample_count: int
    sample_complete: bool
    sample_cer: float | None
    sample_wer: float | None
    sample_original_words: int
    sample_reference_words: int
    sample: tuple[EvaluationSample, ...]

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["sample"] = [asdict(item) for item in self.sample]
        return payload

    def to_json_bytes(self) -> bytes:
        return (json.dumps(self.as_dict(), ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _runtime_metrics(run: TranscriptionRun) -> dict[str, Any]:
    options = run.options_json or {}
    metrics = options.get("_runtime_metrics")
    return metrics if isinstance(metrics, dict) else {}


def _seconds_between(start: datetime | None, end: datetime | None) -> float | None:
    if start is None or end is None:
        return None
    value = (end - start).total_seconds()
    return max(0.0, float(value))


def _duration(row: TranscriptSegmentRow) -> float:
    return max(0.0, float(row.end_time) - float(row.start_time))


def _speech_seconds(rows: Iterable[TranscriptSegmentRow]) -> float:
    return sum(_duration(row) for row in rows)


def _total_gap_seconds(rows: list[TranscriptSegmentRow]) -> float:
    if len(rows) < 2:
        return 0.0
    total = 0.0
    previous_end = rows[0].end_time
    for row in rows[1:]:
        total += max(0.0, float(row.start_time) - float(previous_end))
        previous_end = max(float(previous_end), float(row.end_time))
    return total


def _sample_indices(size: int, *, sample_size: int) -> list[int]:
    if size <= 0 or sample_size <= 0:
        return []
    if size <= sample_size:
        return list(range(size))
    if sample_size == 1:
        return [size // 2]
    positions = [round(i * (size - 1) / (sample_size - 1)) for i in range(sample_size)]
    result: list[int] = []
    seen: set[int] = set()
    for index in positions:
        if index not in seen:
            result.append(index)
            seen.add(index)
    return result


def evaluation_sample(rows: list[TranscriptSegmentRow], *, sample_size: int = 5) -> tuple[EvaluationSample, ...]:
    result: list[EvaluationSample] = []
    for ordinal, index in enumerate(_sample_indices(len(rows), sample_size=sample_size), start=1):
        row = rows[index]
        reviewed = row.review_status in {"reviewed", "approved"} and row.corrected_text is not None
        result.append(
            EvaluationSample(
                ordinal=ordinal,
                segment_id=row.segment_id,
                segment_index=row.segment_index,
                start_time=float(row.start_time),
                end_time=float(row.end_time),
                reviewed=reviewed,
            )
        )
    return tuple(result)


def _normalize_words(text: str) -> list[str]:
    value = unicodedata.normalize("NFKC", text).casefold()
    value = re.sub(r"[^\wáéíóúüñ]+", " ", value, flags=re.UNICODE)
    return [token for token in value.split() if token]


def _normalize_chars(text: str) -> list[str]:
    return list(" ".join(_normalize_words(text)))


def _edit_distance(left: list[str], right: list[str]) -> int:
    if len(left) < len(right):
        left, right = right, left
    if not right:
        return len(left)
    previous = list(range(len(right) + 1))
    for i, left_item in enumerate(left, start=1):
        current = [i]
        for j, right_item in enumerate(right, start=1):
            substitution = previous[j - 1] + (left_item != right_item)
            insertion = current[j - 1] + 1
            deletion = previous[j] + 1
            current.append(min(substitution, insertion, deletion))
        previous = current
    return previous[-1]


def _error_rate(hypothesis: list[str], reference: list[str]) -> float | None:
    if not reference:
        return None
    return _edit_distance(hypothesis, reference) / len(reference)


def _sample_error_rates(
    rows: list[TranscriptSegmentRow],
    sample: tuple[EvaluationSample, ...],
) -> tuple[float | None, float | None, int, int]:
    by_id = {row.segment_id: row for row in rows}
    original_parts: list[str] = []
    reference_parts: list[str] = []
    for item in sample:
        row = by_id[item.segment_id]
        if not item.reviewed:
            continue
        original_parts.append(row.original_text)
        reference_parts.append(row.corrected_text or "")
    if not reference_parts:
        return None, None, 0, 0
    original_text = " ".join(original_parts)
    reference_text = " ".join(reference_parts)
    hypothesis_words = _normalize_words(original_text)
    reference_words = _normalize_words(reference_text)
    hypothesis_chars = _normalize_chars(original_text)
    reference_chars = _normalize_chars(reference_text)
    return (
        _error_rate(hypothesis_chars, reference_chars),
        _error_rate(hypothesis_words, reference_words),
        len(hypothesis_words),
        len(reference_words),
    )


def evaluate_transcription_run(
    session: Session,
    *,
    run_id: str,
    sample_size: int = 5,
) -> TranscriptionEvaluation:
    run = session.get(TranscriptionRun, run_id)
    if run is None:
        raise ValueError("La corrida de transcripción no existe")
    media = session.get(AudiovisualMedia, run.audiovisual_media_id)
    if media is None:
        raise ValueError("El medio audiovisual de la corrida no existe")

    rows = transcript_segment_rows(session, run_id=run.id)
    sample = evaluation_sample(rows, sample_size=sample_size)
    reviewed_count = sum(1 for item in sample if item.reviewed)
    cer, wer, original_words, reference_words = _sample_error_rates(rows, sample)

    durations = [_duration(row) for row in rows]
    speech_seconds = sum(durations)
    media_duration = float(media.duration_seconds) if media.duration_seconds is not None else None
    runtime = _runtime_metrics(run)
    wall_seconds = runtime.get("wall_seconds")
    if wall_seconds is None:
        wall_seconds = _seconds_between(run.created_at, run.completed_at)
    wall_seconds = float(wall_seconds) if wall_seconds is not None else None

    process_cpu_seconds = runtime.get("process_cpu_seconds")
    average_cpu_cores = runtime.get("average_cpu_cores")
    peak_rss_mib = runtime.get("peak_rss_mib")
    peak_gpu_memory_mib = runtime.get("peak_gpu_memory_mib")

    realtime_factor = None
    if wall_seconds is not None and media_duration and media_duration > 0:
        realtime_factor = wall_seconds / media_duration

    options = run.options_json or {}
    compute_type = options.get("compute_type")

    return TranscriptionEvaluation(
        run_id=run.id,
        media_id=run.audiovisual_media_id,
        status=run.status,
        backend=run.backend,
        backend_version=run.backend_version,
        model_name=run.model_name,
        device=run.device,
        language=run.language,
        compute_type=str(compute_type) if compute_type is not None else None,
        created_at=run.created_at.isoformat(),
        completed_at=run.completed_at.isoformat() if run.completed_at else None,
        wall_seconds=wall_seconds,
        process_cpu_seconds=(float(process_cpu_seconds) if process_cpu_seconds is not None else None),
        average_cpu_cores=(float(average_cpu_cores) if average_cpu_cores is not None else None),
        peak_rss_mib=(float(peak_rss_mib) if peak_rss_mib is not None else None),
        peak_gpu_memory_mib=(
            float(peak_gpu_memory_mib) if peak_gpu_memory_mib is not None else None
        ),
        media_duration_seconds=media_duration,
        realtime_factor=realtime_factor,
        segment_count=len(rows),
        speech_seconds=speech_seconds,
        speech_coverage_ratio=(
            min(1.0, speech_seconds / media_duration)
            if media_duration and media_duration > 0
            else None
        ),
        median_segment_seconds=(statistics.median(durations) if durations else None),
        max_segment_seconds=(max(durations) if durations else None),
        total_gap_seconds=_total_gap_seconds(rows),
        short_segment_count=sum(1 for value in durations if value < 0.75),
        long_segment_count=sum(1 for value in durations if value > 15.0),
        empty_segment_count=sum(1 for row in rows if not row.original_text.strip()),
        sample_size=len(sample),
        reviewed_sample_count=reviewed_count,
        sample_complete=bool(sample) and reviewed_count == len(sample),
        sample_cer=cer,
        sample_wer=wer,
        sample_original_words=original_words,
        sample_reference_words=reference_words,
        sample=sample,
    )


def transcription_runs_for_media(session: Session, *, media_id: str) -> list[TranscriptionRun]:
    return list(
        session.scalars(
            select(TranscriptionRun)
            .where(TranscriptionRun.audiovisual_media_id == media_id)
            .order_by(TranscriptionRun.created_at.desc(), TranscriptionRun.id.desc())
        ).all()
    )


def original_transcript_text(
    session: Session,
    *,
    run_id: str,
) -> str:
    """Devuelve solo la salida automática original de una corrida, sin revisiones humanas."""

    rows = transcript_segment_rows(session, run_id=run_id)
    return " ".join(row.original_text.strip() for row in rows if row.original_text.strip()).strip()


def _overlapping_original_text(
    rows: list[TranscriptSegmentRow],
    *,
    start_time: float,
    end_time: float,
) -> str:
    selected = [
        row
        for row in rows
        if min(float(row.end_time), end_time) - max(float(row.start_time), start_time) > 0
    ]
    if not selected:
        return ""
    return " ".join(
        row.original_text.strip() for row in selected if row.original_text.strip()
    ).strip()


def _text_for_reference_window(
    rows: list[TranscriptSegmentRow],
    *,
    start_time: float,
    end_time: float,
    tolerance_seconds: float = 0.05,
) -> tuple[str, str, bool]:
    """Devuelve el texto temporal disponible sin usar la referencia para recortarlo.

    CER/WER sólo son válidos si las fronteras de los segmentos candidatos coinciden
    con la ventana humana. Cuando la segmentación difiere y no hay timestamps por
    palabra, se conserva el contexto temporal completo y la ventana queda sin puntuar.
    """

    selected = [
        row
        for row in rows
        if min(float(row.end_time), end_time) - max(float(row.start_time), start_time) > 0
    ]
    if not selected:
        return "", "", False

    context = " ".join(
        row.original_text.strip() for row in selected if row.original_text.strip()
    ).strip()
    if not context:
        return "", "", False

    first_start = float(selected[0].start_time)
    last_end = float(selected[-1].end_time)
    starts_match = abs(first_start - start_time) <= tolerance_seconds
    ends_match = abs(last_end - end_time) <= tolerance_seconds
    contained = all(
        float(row.start_time) >= start_time - tolerance_seconds
        and float(row.end_time) <= end_time + tolerance_seconds
        for row in selected
    )
    scoreable = starts_match and ends_match and contained
    return context, context, scoreable


def compare_transcription_to_reviewed_reference(
    session: Session,
    *,
    reference_run_id: str,
    candidate_run_id: str,
    sample_size: int = 5,
) -> TranscriptionReferenceComparison:
    """Compara una corrida contra las mismas ventanas corregidas por una persona.

    Las referencias proceden de la muestra determinista revisada del run de referencia.
    Para evitar exigir una segunda corrección humana, la corrida candidata se proyecta
    sobre esos mismos intervalos temporales.
    """

    reference_rows = transcript_segment_rows(session, run_id=reference_run_id)
    candidate_rows = transcript_segment_rows(session, run_id=candidate_run_id)
    if not reference_rows:
        raise ValueError("La corrida de referencia no tiene segmentos.")
    if not candidate_rows:
        raise ValueError("La corrida candidata no tiene segmentos.")

    sample = evaluation_sample(reference_rows, sample_size=sample_size)
    by_id = {row.segment_id: row for row in reference_rows}
    windows: list[ReferenceWindowComparison] = []
    all_candidate: list[str] = []
    all_reference: list[str] = []
    for item in sample:
        row = by_id[item.segment_id]
        if not item.reviewed or row.corrected_text is None:
            continue
        reference_text = row.corrected_text.strip()
        candidate_text, candidate_context_text, scoreable = _text_for_reference_window(
            candidate_rows,
            start_time=float(item.start_time),
            end_time=float(item.end_time),
        )
        reference_words = _normalize_words(reference_text)
        candidate_words = _normalize_words(candidate_text)
        reference_chars = _normalize_chars(reference_text)
        candidate_chars = _normalize_chars(candidate_text)
        windows.append(
            ReferenceWindowComparison(
                ordinal=item.ordinal,
                start_time=float(item.start_time),
                end_time=float(item.end_time),
                reference_text=reference_text,
                candidate_text=candidate_text,
                candidate_context_text=candidate_context_text,
                scoreable=scoreable,
                cer=_error_rate(candidate_chars, reference_chars) if scoreable else None,
                wer=_error_rate(candidate_words, reference_words) if scoreable else None,
            )
        )
        all_candidate.append(candidate_text)
        all_reference.append(reference_text)

    if not windows:
        raise ValueError(
            "La corrida de referencia todavía no tiene una muestra humana completa para comparar."
        )

    all_windows_scoreable = all(window.scoreable for window in windows)
    candidate_text = " ".join(all_candidate)
    reference_text = " ".join(all_reference)
    candidate_words = _normalize_words(candidate_text)
    reference_words = _normalize_words(reference_text)
    candidate_chars = _normalize_chars(candidate_text)
    reference_chars = _normalize_chars(reference_text)
    return TranscriptionReferenceComparison(
        reference_run_id=reference_run_id,
        candidate_run_id=candidate_run_id,
        sample_size=len(windows),
        cer=(
            _error_rate(candidate_chars, reference_chars) if all_windows_scoreable else None
        ),
        wer=(
            _error_rate(candidate_words, reference_words) if all_windows_scoreable else None
        ),
        candidate_words=len(candidate_words),
        reference_words=len(reference_words),
        windows=tuple(windows),
    )


def reviewed_reference_run_id(
    session: Session,
    *,
    media_id: str,
    sample_size: int = 5,
) -> str | None:
    runs = list(
        session.scalars(
            select(TranscriptionRun)
            .where(
                TranscriptionRun.audiovisual_media_id == media_id,
                TranscriptionRun.status == "completed",
            )
            .order_by(TranscriptionRun.created_at, TranscriptionRun.id)
        ).all()
    )
    for run in runs:
        evaluation = evaluate_transcription_run(session, run_id=run.id, sample_size=sample_size)
        if evaluation.sample_complete:
            return run.id
    return None
