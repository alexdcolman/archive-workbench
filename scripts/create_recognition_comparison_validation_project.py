#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from sqlalchemy import select

from archive_workbench.db import (
    create_sqlite_engine,
    current_revision,
    database_path,
    session_scope,
    upgrade_database,
)
from archive_workbench.db.models import AudiovisualMedia, DigitalObject, TranscriptionRun
from archive_workbench.identity import sha256_file
from archive_workbench.transcription_evaluation import (
    evaluate_transcription_run,
    reviewed_reference_run_id,
)
from archive_workbench.version import __version__

SOURCE_REVISION = "0045_audiovisual_transcription"
TARGET_REVISION = "0046_audiovisual_timeline_annotations"
QUALITY_PROFILE = "av03_quality_gpu_large_v3_v1"


def create_validation_project(source_root: Path, destination: Path) -> dict[str, object]:
    source_root = source_root.expanduser().resolve()
    destination = destination.expanduser().resolve()
    if not source_root.is_dir():
        raise RuntimeError(f"No existe el proyecto fuente: {source_root}")
    if destination.exists():
        raise RuntimeError(
            f"El destino ya existe y no se reemplazará: {destination}. Elegí otra carpeta."
        )
    source_db = database_path(source_root)
    if not source_db.is_file():
        raise RuntimeError(f"No existe la base fuente: {source_db}")
    source_revision = current_revision(source_root)
    if source_revision != SOURCE_REVISION:
        raise RuntimeError(
            f"La base fuente debe estar en {SOURCE_REVISION}; está en {source_revision or 'sin revisión'}."
        )
    source_sha_before = sha256_file(source_db)

    shutil.copytree(source_root, destination)
    upgrade_database(destination)
    if current_revision(destination) != TARGET_REVISION:
        raise RuntimeError("La copia no quedó en la revisión audiovisual esperada.")

    engine = create_sqlite_engine(database_path(destination))
    try:
        with session_scope(engine) as session:
            media = session.scalar(
                select(AudiovisualMedia)
                .join(DigitalObject, DigitalObject.id == AudiovisualMedia.digital_object_id)
                .where(AudiovisualMedia.title == "RememorArte Horacio BAU")
            )
            if media is None:
                raise RuntimeError("La copia no contiene el video RememorArte Horacio BAU.")
            reference_run_id = reviewed_reference_run_id(session, media_id=media.id, sample_size=5)
            if reference_run_id is None:
                raise RuntimeError(
                    "La copia no conserva una muestra humana completa para usar como referencia."
                )
            baseline = evaluate_transcription_run(session, run_id=reference_run_id, sample_size=5)
            quality_runs = session.scalars(
                select(TranscriptionRun).where(
                    TranscriptionRun.audiovisual_media_id == media.id,
                    TranscriptionRun.options_json["_av03_profile"].as_string() == QUALITY_PROFILE,
                )
            ).all()
            if quality_runs:
                raise RuntimeError("La copia ya contiene una corrida RC7; usá una carpeta nueva.")
    finally:
        engine.dispose()

    source_sha_after = sha256_file(source_db)
    if source_sha_before != source_sha_after:
        raise RuntimeError("La base fuente cambió mientras se preparaba la copia de validación.")

    return {
        "version": __version__,
        "source": str(source_root),
        "destination": str(destination),
        "source_revision": source_revision,
        "revision": current_revision(destination),
        "source_database_unchanged": True,
        "source_database_sha256": source_sha_after,
        "reference_run_id": reference_run_id,
        "baseline_model": baseline.model_name,
        "baseline_device": baseline.device,
        "baseline_wer": baseline.sample_wer,
        "baseline_cer": baseline.sample_cer,
        "baseline_sample_complete": baseline.sample_complete,
        "quality_run_count": 0,
        "note": "La validación reutiliza la referencia humana existente; project_data no se lee ni se modifica.",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source_root", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    try:
        result = create_validation_project(args.source_root, args.destination)
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
