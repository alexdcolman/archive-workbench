#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

from sqlalchemy import select

from archive_workbench.db import create_sqlite_engine, current_revision, database_path, session_scope
from archive_workbench.db.models import AudiovisualMedia, DigitalObject, TranscriptionRun
from archive_workbench.transcription_evaluation import (
    compare_transcription_to_reviewed_reference,
    evaluate_transcription_run,
    original_transcript_text,
    reviewed_reference_run_id,
)

EXPECTED_REVISION = "0046_audiovisual_timeline_annotations"
QUALITY_PROFILE = "av03_quality_gpu_large_v3_v1"
EXPECTED_TERMS = ("Trelew", "Horacio Bau", "Centro Cultural por la Memoria")


def verify(project_root: Path) -> dict[str, object]:
    project_root = project_root.expanduser().resolve()
    db_path = database_path(project_root)
    failures: list[str] = []
    with sqlite3.connect(db_path) as conn:
        quick = conn.execute("PRAGMA quick_check").fetchone()[0]
        fk = list(conn.execute("PRAGMA foreign_key_check"))
    revision = current_revision(project_root)
    if revision != EXPECTED_REVISION:
        failures.append(f"La revisión esperada es {EXPECTED_REVISION}; actual: {revision}.")
    if quick != "ok":
        failures.append(f"PRAGMA quick_check devolvió {quick!r}.")
    if fk:
        failures.append(f"Hay {len(fk)} violaciones de claves foráneas.")

    engine = create_sqlite_engine(db_path)
    reference_run_id = None
    baseline_eval = None
    quality_eval = None
    comparison = None
    quality_run = None
    detected_terms: dict[str, bool] = {}
    try:
        with session_scope(engine) as session:
            media = session.scalar(
                select(AudiovisualMedia)
                .join(DigitalObject, DigitalObject.id == AudiovisualMedia.digital_object_id)
                .where(AudiovisualMedia.title == "RememorArte Horacio BAU")
            )
            if media is None:
                failures.append("No se encontró el video RememorArte Horacio BAU.")
            else:
                reference_run_id = reviewed_reference_run_id(session, media_id=media.id, sample_size=5)
                if reference_run_id is None:
                    failures.append("No se encontró la corrida con referencia humana completa.")
                else:
                    baseline_eval = evaluate_transcription_run(
                        session, run_id=reference_run_id, sample_size=5
                    )
                quality_run = session.scalar(
                    select(TranscriptionRun)
                    .where(
                        TranscriptionRun.audiovisual_media_id == media.id,
                        TranscriptionRun.options_json["_av03_profile"].as_string() == QUALITY_PROFILE,
                    )
                    .order_by(TranscriptionRun.created_at.desc(), TranscriptionRun.id.desc())
                )
                if quality_run is None:
                    failures.append("No se encontró la corrida RC7 de mayor calidad.")
                elif quality_run.status != "completed":
                    failures.append(
                        "La corrida RC7 no terminó correctamente: "
                        + (quality_run.error_text or quality_run.status)
                    )
                elif reference_run_id is not None:
                    quality_eval = evaluate_transcription_run(
                        session, run_id=quality_run.id, sample_size=5
                    )
                    comparison = compare_transcription_to_reviewed_reference(
                        session,
                        reference_run_id=reference_run_id,
                        candidate_run_id=quality_run.id,
                        sample_size=5,
                    )
                    if comparison.cer is not None or comparison.wer is not None:
                        failures.append(
                            "large-v3 no debe publicar CER/WER sobre estas cinco ventanas: "
                            "su segmentación temporal difiere de la referencia y no hay timestamps por palabra."
                        )
                    if any(window.scoreable for window in comparison.windows):
                        failures.append(
                            "La comparación RC12 esperaba contexto temporal sin puntuación para las "
                            "cinco ventanas de large-v3 existentes."
                        )
                    candidate_text = original_transcript_text(session, run_id=quality_run.id).casefold()
                    detected_terms = {
                        term: term.casefold() in candidate_text for term in EXPECTED_TERMS
                    }
    finally:
        engine.dispose()

    baseline_wer = baseline_eval.sample_wer if baseline_eval else None
    baseline_cer = baseline_eval.sample_cer if baseline_eval else None
    candidate_wer = comparison.wer if comparison else None
    candidate_cer = comparison.cer if comparison else None
    return {
        "ok": not failures,
        "project": str(project_root),
        "revision": revision,
        "quick_check": quick,
        "foreign_key_violations": len(fk),
        "reference_run_id": reference_run_id,
        "quality_run_id": quality_run.id if quality_run else None,
        "quality_status": quality_run.status if quality_run else None,
        "quality_error": quality_run.error_text if quality_run else None,
        "baseline": (
            {
                "model": baseline_eval.model_name,
                "device": baseline_eval.device,
                "wall_seconds": baseline_eval.wall_seconds,
                "realtime_factor": baseline_eval.realtime_factor,
                "sample_cer": baseline_cer,
                "sample_wer": baseline_wer,
            }
            if baseline_eval
            else None
        ),
        "comparison_method": (
            "original_text; CER/WER sólo con fronteras temporales comparables; "
            "si difieren, contexto temporal original sin puntuación"
            if comparison
            else None
        ),
        "candidate": (
            {
                "model": quality_eval.model_name,
                "device": quality_eval.device,
                "compute_type": quality_eval.compute_type,
                "wall_seconds": quality_eval.wall_seconds,
                "realtime_factor": quality_eval.realtime_factor,
                "peak_gpu_memory_mib": quality_eval.peak_gpu_memory_mib,
                "reference_cer": candidate_cer,
                "reference_wer": candidate_wer,
                "scored_reference_windows": (
                    sum(1 for window in comparison.windows if window.scoreable)
                    if comparison is not None
                    else 0
                ),
                "expected_terms_detected_in_original_output": detected_terms,
                "reference_windows": (
                    comparison.as_dict()["windows"]
                    if comparison is not None
                    else []
                ),
            }
            if quality_eval
            else None
        ),
        "failures": failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("project_root", type=Path)
    args = parser.parse_args()
    result = verify(args.project_root)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
