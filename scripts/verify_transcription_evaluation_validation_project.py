#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path

from sqlalchemy import select

from archive_workbench.db import create_sqlite_engine, current_revision, database_path, session_scope
from archive_workbench.db.models import AudiovisualMedia, SourceRegistration, TranscriptSegment, TranscriptionRun
from archive_workbench.identity import sha256_file
from archive_workbench.audiovisual import transcript_document_text
from archive_workbench.transcription_evaluation import evaluate_transcription_run

EXPECTED_PLATFORM_ID = "CwWKigBOfjQ"
EXPECTED_CHANNEL_ID = "UCsZG_7l0cYIEtJNhajrFPYg"


def verify(root: Path) -> dict[str, object]:
    root = root.expanduser().resolve()
    failures: list[str] = []
    db = database_path(root)
    if not db.is_file():
        return {"ok": False, "project": str(root), "failures": [f"No existe la base: {db}"]}

    conn = sqlite3.connect(db)
    try:
        quick = conn.execute("PRAGMA quick_check").fetchone()[0]
        fk = list(conn.execute("PRAGMA foreign_key_check"))
    finally:
        conn.close()
    if quick != "ok":
        failures.append(f"PRAGMA quick_check devolvió {quick!r}")
    if fk:
        failures.append(f"Hay {len(fk)} violaciones de claves foráneas")

    engine = create_sqlite_engine(db)
    evaluation = None
    platform = None
    observed_sha = None
    run_count = 0
    timing_fingerprint = None
    transcript_characters = 0
    try:
        with session_scope(engine) as session:
            registrations = session.scalars(select(SourceRegistration)).all()
            for registration in registrations:
                payload = registration.source_payload_json or {}
                candidate = payload.get("platform_import") if isinstance(payload, dict) else None
                if isinstance(candidate, dict) and candidate.get("platform_id") == EXPECTED_PLATFORM_ID:
                    platform = candidate
                    digital_object_id = registration.digital_object_id
                    break
            else:
                digital_object_id = None
            if platform is None or digital_object_id is None:
                failures.append("No se encontró la procedencia del video AV-02 esperado")
            else:
                media = session.scalar(
                    select(AudiovisualMedia).where(AudiovisualMedia.digital_object_id == digital_object_id)
                )
                if media is None:
                    failures.append("No se encontró el medio audiovisual del video esperado")
                else:
                    runs = session.scalars(
                        select(TranscriptionRun)
                        .where(TranscriptionRun.audiovisual_media_id == media.id)
                        .order_by(TranscriptionRun.created_at.desc(), TranscriptionRun.id.desc())
                    ).all()
                    run_count = len(runs)
                    baseline = next(
                        (
                            run
                            for run in runs
                            if run.backend == "faster_whisper"
                            and run.model_name == "small"
                            and run.device == "cpu"
                            and str((run.options_json or {}).get("compute_type")) == "int8"
                        ),
                        None,
                    )
                    if baseline is None:
                        failures.append("Falta la corrida base faster_whisper · small · CPU · int8")
                    elif baseline.status != "completed":
                        failures.append(
                            f"La corrida base no terminó correctamente: {baseline.status} · {baseline.error_text or 'sin diagnóstico'}"
                        )
                    else:
                        evaluation = evaluate_transcription_run(session, run_id=baseline.id, sample_size=5)
                        timing_rows = session.scalars(
                            select(TranscriptSegment)
                            .where(TranscriptSegment.transcription_run_id == baseline.id)
                            .order_by(TranscriptSegment.segment_index)
                        ).all()
                        timing_payload = [
                            [row.id, float(row.start_time), float(row.end_time)]
                            for row in timing_rows
                        ]
                        timing_fingerprint = hashlib.sha256(
                            json.dumps(timing_payload, separators=(",", ":")).encode("utf-8")
                        ).hexdigest()
                        transcript_characters = len(
                            transcript_document_text(session, run_id=baseline.id)
                        )
                        if evaluation.segment_count <= 0:
                            failures.append("La corrida base no produjo segmentos")
                        if evaluation.wall_seconds is None or evaluation.wall_seconds <= 0:
                            failures.append("La corrida base no conservó un tiempo de ejecución válido")
                        if evaluation.peak_rss_mib is None or evaluation.peak_rss_mib <= 0:
                            failures.append("La corrida base no conservó memoria RAM observada")
                        if not evaluation.sample_complete:
                            failures.append(
                                f"La muestra humana está incompleta: {evaluation.reviewed_sample_count}/{evaluation.sample_size} segmentos revisados"
                            )

                relative_path = platform.get("incorporated_relative_path")
                expected_sha = platform.get("incorporated_sha256")
                if relative_path:
                    candidate_path = root / relative_path
                    if candidate_path.is_file():
                        observed_sha = sha256_file(candidate_path)
                        if observed_sha != expected_sha:
                            failures.append("El SHA-256 del video incorporado cambió")
                    else:
                        failures.append(f"Falta el video incorporado: {candidate_path}")
    finally:
        engine.dispose()

    result: dict[str, object] = {
        "ok": not failures,
        "project": str(root),
        "revision": current_revision(root),
        "quick_check": quick,
        "foreign_key_violations": len(fk),
        "platform_id": platform.get("platform_id") if platform else None,
        "channel_id": platform.get("channel_id") if platform else None,
        "title": platform.get("title") if platform else None,
        "observed_sha256": observed_sha,
        "transcription_run_count": run_count,
        "segment_timing_fingerprint": timing_fingerprint,
        "continuous_transcript_characters": transcript_characters,
        "failures": failures,
    }
    if evaluation is not None:
        result["baseline_evaluation"] = evaluation.as_dict()
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("project", type=Path)
    args = parser.parse_args()
    result = verify(args.project)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
