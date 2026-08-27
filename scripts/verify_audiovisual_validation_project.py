#!/usr/bin/env python3
"""Diagnóstico explícito de la validación manual AV-01 sobre un proyecto descartable."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from sqlalchemy import select, text

from archive_workbench.audiovisual import export_transcript_segments_bytes, search_transcript_segments
from archive_workbench.db import create_sqlite_engine, current_revision, database_path, session_scope
from archive_workbench.db.models import (
    AudiovisualMedia,
    DigitalObject,
    SegmentEntityMention,
    TranscriptSegment,
    TranscriptSegmentRevision,
    TranscriptionRun,
)
from archive_workbench.identity import sha256_file

EXPECTED_REVISION = "0047_authority_relation_profiles"
EXPECTED_CORRECTION = "La memoria conserva voces, documentos y testimonios."


def verify(root: Path) -> tuple[bool, dict[str, object]]:
    root = root.expanduser().resolve()
    failures: list[str] = []
    details: dict[str, object] = {"project": str(root)}

    if root.name == "project_data" or "archive_app/project_data" in root.as_posix():
        failures.append("La ruta apunta a project_data; esta verificación solo admite una base descartable.")
        return False, {**details, "failures": failures}
    if not root.is_dir():
        failures.append("El proyecto de validación no existe.")
        return False, {**details, "failures": failures}

    summary_path = root / "validation_summary.json"
    if not summary_path.is_file():
        failures.append("Falta validation_summary.json creado por el preparador AV-01.")
        return False, {**details, "failures": failures}
    summary = json.loads(summary_path.read_text(encoding="utf-8"))

    revision = current_revision(root)
    details["revision"] = revision
    if revision != EXPECTED_REVISION:
        failures.append(f"Revisión inesperada: {revision!r}; se esperaba {EXPECTED_REVISION!r}.")

    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            integrity = session.execute(text("PRAGMA quick_check")).scalar_one()
            foreign_keys = session.execute(text("PRAGMA foreign_key_check")).all()
            details["quick_check"] = integrity
            details["foreign_key_violations"] = len(foreign_keys)
            if integrity != "ok":
                failures.append(f"PRAGMA quick_check devolvió {integrity!r}.")
            if foreign_keys:
                failures.append(f"PRAGMA foreign_key_check devolvió {len(foreign_keys)} violaciones.")

            media_rows = session.execute(
                select(AudiovisualMedia, DigitalObject)
                .join(DigitalObject, DigitalObject.id == AudiovisualMedia.digital_object_id)
                .order_by(DigitalObject.original_filename)
            ).all()
            details["media"] = [digital.original_filename for _media, digital in media_rows]
            if len(media_rows) != 2:
                failures.append(f"Se esperaban 2 medios audiovisuales y hay {len(media_rows)}.")

            original_hashes = summary.get("original_sha256") or {}
            observed_hashes: dict[str, str] = {}
            video_media_id: str | None = None
            for media, digital in media_rows:
                source = root / "corpus" / "audiovisual" / digital.original_filename
                if not source.is_file():
                    failures.append(f"Falta el original {digital.original_filename}.")
                    continue
                observed_hashes[digital.original_filename] = sha256_file(source)
                expected_hash = original_hashes.get(digital.original_filename)
                if expected_hash and observed_hashes[digital.original_filename] != expected_hash:
                    failures.append(f"El SHA-256 del original cambió: {digital.original_filename}.")
                if digital.media_type == "video":
                    video_media_id = media.id
            details["original_sha256"] = observed_hashes

            corrected = session.scalars(
                select(TranscriptSegment).where(TranscriptSegment.corrected_text == EXPECTED_CORRECTION)
            ).all()
            details["expected_correction_count"] = len(corrected)
            if len(corrected) != 1:
                failures.append(
                    "No hay exactamente un segmento con la corrección manual esperada."
                )
            else:
                segment = corrected[0]
                if segment.review_status != "reviewed":
                    failures.append(
                        f"La corrección esperada tiene estado {segment.review_status!r}, no 'reviewed'."
                    )
                revisions = session.scalars(
                    select(TranscriptSegmentRevision)
                    .where(TranscriptSegmentRevision.segment_id == segment.id)
                    .order_by(TranscriptSegmentRevision.revision_number)
                ).all()
                details["corrected_segment_revision_count"] = len(revisions)
                if len(revisions) < 2 or revisions[-1].revision_number != segment.revision_number:
                    failures.append("La corrección no conserva correctamente su historial append-only.")

                mentions = session.scalars(
                    select(SegmentEntityMention).where(SegmentEntityMention.segment_id == segment.id)
                ).all()
                details["corrected_segment_mentions"] = [item.mention_text for item in mentions]
                if not any(item.normalized_text == "memoria" for item in mentions):
                    failures.append("Falta la mención manual 'Memoria' en el segmento corregido.")

            search_rows = search_transcript_segments(
                session,
                project_id="av01_audiovisual_validation",
                query="testimonios",
                limit=20,
            )
            details["search_testimonios_count"] = len(search_rows)
            if not search_rows:
                failures.append("La búsqueda audiovisual no recupera la corrección por 'testimonios'.")

            jsonl, export_count = export_transcript_segments_bytes(
                session,
                project_id="av01_audiovisual_validation",
                output_format="jsonl",
            )
            details["export_segment_count"] = export_count
            if EXPECTED_CORRECTION not in jsonl.decode("utf-8"):
                failures.append("La exportación JSONL no contiene la corrección manual esperada.")

            cpu_runs = []
            if video_media_id is not None:
                cpu_runs = session.scalars(
                    select(TranscriptionRun)
                    .where(
                        TranscriptionRun.audiovisual_media_id == video_media_id,
                        TranscriptionRun.backend == "faster_whisper",
                        TranscriptionRun.device == "cpu",
                    )
                    .order_by(TranscriptionRun.created_at)
                ).all()
            details["video_cpu_runs"] = [
                {"id": row.id, "status": row.status, "model": row.model_name, "error": row.error_text}
                for row in cpu_runs
            ]
            completed_cpu = [row for row in cpu_runs if row.status == "completed"]
            if not completed_cpu:
                failures.append("No hay una corrida faster_whisper completada en CPU sobre el video.")
            else:
                run = completed_cpu[-1]
                segment_count = int(
                    session.scalar(
                        select(text("count(*)")).select_from(TranscriptSegment).where(
                            TranscriptSegment.transcription_run_id == run.id
                        )
                    )
                    or 0
                )
                details["video_cpu_segment_count"] = segment_count
                if segment_count < 1:
                    failures.append("La corrida CPU completada no produjo segmentos.")
    finally:
        engine.dispose()

    details["failures"] = failures
    details["ok"] = not failures
    return not failures, details


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("project_root", type=Path)
    args = parser.parse_args()
    ok, details = verify(args.project_root)
    print(json.dumps(details, ensure_ascii=False, indent=2, sort_keys=True))
    if not ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
