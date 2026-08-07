#!/usr/bin/env python3
"""Crea un proyecto descartable AV-01 sin tocar project_data ni destinos existentes."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

import yaml
from sqlalchemy import select

from archive_workbench.audiovisual import (
    audiovisual_media_rows,
    transcript_segment_rows,
)
from archive_workbench.catalog import ensure_project
from archive_workbench.catalog_management import create_archival_unit, register_local_file
from archive_workbench.db import (
    create_sqlite_engine,
    current_revision,
    database_path,
    session_scope,
    upgrade_database,
)
from archive_workbench.db.models import AudiovisualMedia, TranscriptSegment, TranscriptSegmentRevision, TranscriptionRun
from archive_workbench.decisions import load_decisions
from archive_workbench.identity import new_id, sha256_file
from archive_workbench.project_init import initialize_project
from archive_workbench.version import __version__
from archive_workbench.db.models import utc_now


def _seed_controlled_transcript(session, *, media_id: str) -> str:
    run = TranscriptionRun(
        id=new_id(),
        audiovisual_media_id=media_id,
        source_asset_id=None,
        backend="controlled_fixture",
        backend_version="1",
        model_name="validation_fixture",
        device="cpu",
        language="es",
        options_json={"fixture": "av01"},
        status="completed",
        created_by="validation_script",
        created_at=utc_now(),
        completed_at=utc_now(),
    )
    session.add(run)
    session.flush()
    definitions = [
        (0.0, 2.4, "Archivo de prueba."),
        (2.4, 5.7, "La memoria conserva voces y documentos."),
        (5.7, 8.2, "Este segmento puede corregirse manualmente."),
    ]
    for index, (start, end, text) in enumerate(definitions):
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
            updated_by="validation_script",
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
                snapshot_json={
                    "segment_index": index,
                    "start_time": start,
                    "end_time": end,
                    "original_text": text,
                    "corrected_text": None,
                    "review_status": "unreviewed",
                    "revision_number": 1,
                },
                note="Transcripción controlada para validar la interfaz AV-01",
                changed_by="validation_script",
                changed_at=utc_now(),
            )
        )
    session.flush()
    return run.id


def create_validation_project(destination: Path) -> dict[str, object]:
    destination = destination.expanduser().resolve()
    if destination.name == "project_data" or "archive_app/project_data" in destination.as_posix():
        raise SystemExit("El destino no puede ser project_data.")
    if destination.exists():
        raise SystemExit(
            f"El destino ya existe: {destination}. Elegí otra ruta; "
            "el script no elimina ni reemplaza proyectos."
        )

    repository_root = Path(__file__).resolve().parents[1]
    initialize_project(destination, template_root=repository_root / "config")
    decisions_path = destination / "config" / "decisions.yaml"
    payload = yaml.safe_load(decisions_path.read_text(encoding="utf-8"))
    payload["project_name"] = "Proyecto de validación AV-01"
    payload["project_id"] = "av01_audiovisual_validation"
    decisions_path.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )

    source_dir = repository_root / "examples" / "av01_validation"
    target_dir = destination / "corpus" / "audiovisual"
    target_dir.mkdir(parents=True, exist_ok=True)
    audio_source = source_dir / "testimonio_controlado.wav"
    video_source = source_dir / "testimonio_controlado.mp4"
    audio_target = target_dir / audio_source.name
    video_target = target_dir / video_source.name
    shutil.copy2(audio_source, audio_target)
    shutil.copy2(video_source, video_target)
    original_hashes = {
        audio_target.name: sha256_file(audio_target),
        video_target.name: sha256_file(video_target),
    }

    upgrade_database(destination)
    decisions = load_decisions(decisions_path)
    engine = create_sqlite_engine(database_path(destination))
    try:
        with session_scope(engine) as session:
            ensure_project(session, decisions)
            root_level = next(
                (level for level in sorted(decisions.archival_levels, key=lambda item: item.display_order)
                 if level.enabled and not level.parent_keys),
                None,
            )
            if root_level is None:
                raise RuntimeError("No existe un nivel archivístico raíz habilitado")
            unit = create_archival_unit(
                session,
                decisions=decisions,
                project_id=decisions.project_id,
                parent_id=None,
                level_key=root_level.key,
                title="Colección audiovisual de validación",
                created_by="validation_script",
            )
            audio_result = register_local_file(
                session,
                project_root=destination,
                project_id=decisions.project_id,
                archival_unit_id=unit.id,
                relative_path=audio_target.relative_to(destination).as_posix(),
                registered_by="validation_script",
            )
            video_result = register_local_file(
                session,
                project_root=destination,
                project_id=decisions.project_id,
                archival_unit_id=unit.id,
                relative_path=video_target.relative_to(destination).as_posix(),
                registered_by="validation_script",
            )
            audio_media = session.scalar(
                select(AudiovisualMedia).where(
                    AudiovisualMedia.digital_object_id == audio_result.digital_object_id
                )
            )
            if audio_media is None:
                raise RuntimeError("No se creó la ficha audiovisual del audio")
            controlled_run_id = _seed_controlled_transcript(session, media_id=audio_media.id)

        with session_scope(engine) as session:
            rows = audiovisual_media_rows(
                session, project_root=destination, project_id=decisions.project_id
            )
            controlled_segments = transcript_segment_rows(session, run_id=controlled_run_id)
    finally:
        engine.dispose()

    current_hashes = {
        audio_target.name: sha256_file(audio_target),
        video_target.name: sha256_file(video_target),
    }
    if current_hashes != original_hashes:
        raise RuntimeError("Un original audiovisual fue modificado durante la preparación")
    if len(rows) != 2:
        raise RuntimeError(f"Se esperaban 2 medios audiovisuales y se obtuvieron {len(rows)}")
    if len(controlled_segments) != 3:
        raise RuntimeError("La transcripción controlada no conserva sus tres segmentos")
    if any(row.duration_seconds is None for row in rows):
        raise RuntimeError("FFprobe no registró la duración de todos los medios")

    result: dict[str, object] = {
        "version": __version__,
        "revision": current_revision(destination),
        "destination": str(destination),
        "media_count": len(rows),
        "media_types": sorted(row.media_type for row in rows),
        "controlled_run_id": controlled_run_id,
        "controlled_segments": len(controlled_segments),
        "original_sha256": original_hashes,
        "originals_unchanged": True,
        "project_data_touched": False,
        "note": "project_data no fue leído ni modificado; el script no elimina ni reemplaza proyectos",
    }
    (destination / "validation_summary.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    result = create_validation_project(args.destination)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
