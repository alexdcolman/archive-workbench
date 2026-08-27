#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

from sqlalchemy import select

from archive_workbench.audiovisual import timeline_annotation_rows
from archive_workbench.db import create_sqlite_engine, current_revision, database_path, session_scope
from archive_workbench.db.models import AudiovisualMedia, DigitalObject, TranscriptionRun

EXPECTED_REVISION = "0047_authority_relation_profiles"


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
            annotations = timeline_annotation_rows(session, media_id=media.id) if media else []
            runs = (
                session.scalars(
                    select(TranscriptionRun).where(
                        TranscriptionRun.audiovisual_media_id == media.id,
                        TranscriptionRun.status == "completed",
                    )
                ).all()
                if media
                else []
            )
    finally:
        engine.dispose()

    speakers = [row for row in annotations if row.annotation_type == "speaker"]
    notes = [row for row in annotations if row.annotation_type == "annotation"]
    provisional = [row for row in speakers if row.label == "Hablante RC6 A"]
    linked_horacio = [
        row
        for row in speakers
        if row.label == "Horacio Bau" and row.authority_name == "Horacio Bau"
    ]
    rc6_note = [row for row in notes if row.label.casefold() == "marca rc6"]

    ordered_speakers = sorted(speakers, key=lambda row: (row.start_time, row.end_time, row.annotation_id))
    adjacent_boundaries = [
        (left, right)
        for left, right in zip(ordered_speakers, ordered_speakers[1:])
        if abs(float(left.end_time) - float(right.start_time)) <= 0.05
    ]
    overlap_count = sum(
        1
        for left, right in zip(ordered_speakers, ordered_speakers[1:])
        if float(left.end_time) > float(right.start_time) + 0.05
    )
    # La UI sincronizada admite exploración libre, seek hacia atrás y múltiples
    # reasignaciones. La validación comprueba que existe al menos un cierre
    # automático real entre turnos, en vez de exigir una secuencia literal.
    turn_boundary_ok = bool(adjacent_boundaries)
    selected_horacio = linked_horacio[-1] if linked_horacio else None

    if not provisional:
        failures.append("Falta el hablante provisional 'Hablante RC6 A'.")
    if selected_horacio is None:
        failures.append("Falta un turno posterior de Horacio Bau vinculado a su autoridad.")
    if speakers and len(speakers) > 1 and not turn_boundary_ok:
        failures.append("No se observó ningún cierre automático entre turnos de hablante.")
    if not rc6_note:
        failures.append("Falta la anotación 'marca RC6'.")

    return {
        "ok": not failures,
        "project": str(project_root),
        "revision": revision,
        "quick_check": quick,
        "foreign_key_violations": len(fk),
        "timeline_annotation_count": len(annotations),
        "speaker_count": len(speakers),
        "annotation_count": len(notes),
        "provisional_speaker_present": bool(provisional),
        "horacio_bau_authority_linked": selected_horacio is not None,
        "speaker_turn_boundary_ok": turn_boundary_ok,
        "speaker_turn_boundary_count": len(adjacent_boundaries),
        "speaker_overlap_count": overlap_count,
        "rc6_note_present": bool(rc6_note),
        "transcription_run_count": len(runs),
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
