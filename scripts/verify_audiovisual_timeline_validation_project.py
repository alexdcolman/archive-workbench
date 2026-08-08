#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

from sqlalchemy import select

from archive_workbench.audiovisual import timeline_annotation_rows, transcript_with_timeline_marks
from archive_workbench.db import create_sqlite_engine, current_revision, database_path, session_scope
from archive_workbench.db.models import AudiovisualMedia, DigitalObject, TranscriptionRun

EXPECTED_REVISION = "0046_audiovisual_timeline_annotations"


def verify(project_root: Path) -> dict[str, object]:
    project_root = project_root.expanduser().resolve()
    db_path = database_path(project_root)
    failures: list[str] = []
    if not db_path.is_file():
        return {"ok": False, "project": str(project_root), "failures": ["No existe la base SQLite."]}

    raw = sqlite3.connect(db_path)
    try:
        quick = raw.execute("PRAGMA quick_check").fetchone()[0]
        fk = list(raw.execute("PRAGMA foreign_key_check"))
    finally:
        raw.close()
    revision = current_revision(project_root)
    if revision != EXPECTED_REVISION:
        failures.append(f"Revisión esperada {EXPECTED_REVISION}; actual: {revision}.")
    if quick != "ok":
        failures.append(f"PRAGMA quick_check devolvió {quick!r}.")
    if fk:
        failures.append(f"Hay {len(fk)} violaciones de claves foráneas.")

    engine = create_sqlite_engine(db_path)
    try:
        with session_scope(engine) as session:
            media = session.scalar(
                select(AudiovisualMedia)
                .join(DigitalObject, DigitalObject.id == AudiovisualMedia.digital_object_id)
                .where(AudiovisualMedia.title == "RememorArte Horacio BAU")
            )
            if media is None:
                failures.append("No se encontró el video de validación RememorArte Horacio BAU.")
                annotations = []
                marked_transcript = ""
                run = None
            else:
                annotations = timeline_annotation_rows(session, media_id=media.id)
                run = session.scalar(
                    select(TranscriptionRun)
                    .where(
                        TranscriptionRun.audiovisual_media_id == media.id,
                        TranscriptionRun.status == "completed",
                    )
                    .order_by(TranscriptionRun.created_at, TranscriptionRun.id)
                )
                marked_transcript = (
                    transcript_with_timeline_marks(session, run_id=run.id) if run is not None else ""
                )

            speakers = [row for row in annotations if row.annotation_type == "speaker"]
            notes = [row for row in annotations if row.annotation_type == "annotation"]
            expected_speaker = next((row for row in speakers if row.label == "Horacio Bau"), None)
            expected_note = next((row for row in notes if row.label.casefold() == "sonríe".casefold()), None)
            if expected_speaker is None:
                failures.append("Falta una marca de hablante llamada Horacio Bau.")
            elif expected_speaker.authority_name != "Horacio Bau":
                failures.append("La marca Horacio Bau no está vinculada a la autoridad Horacio Bau.")
            if expected_note is None:
                failures.append("Falta una anotación temporal 'sonríe'.")
            if expected_speaker is not None and "Horacio Bau:" not in marked_transcript:
                failures.append("La vista integrada no muestra el hablante Horacio Bau.")
            if expected_note is not None and "sonríe" not in marked_transcript.casefold():
                failures.append("La vista integrada no muestra la anotación 'sonríe'.")

            result = {
                "ok": not failures,
                "project": str(project_root),
                "revision": revision,
                "quick_check": quick,
                "foreign_key_violations": len(fk),
                "timeline_annotation_count": len(annotations),
                "speaker_count": len(speakers),
                "annotation_count": len(notes),
                "horacio_bau_authority_linked": bool(
                    expected_speaker is not None and expected_speaker.authority_name == "Horacio Bau"
                ),
                "integrated_transcript_has_speaker": "Horacio Bau:" in marked_transcript,
                "integrated_transcript_has_note": "sonríe" in marked_transcript.casefold(),
                "transcription_run_count": 1 if run is not None else 0,
                "failures": failures,
            }
    finally:
        engine.dispose()
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("project_root", type=Path)
    args = parser.parse_args()
    result = verify(args.project_root)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
