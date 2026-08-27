#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

from sqlalchemy import select

from archive_workbench.audiovisual import timeline_annotation_rows
from archive_workbench.db import create_sqlite_engine, current_revision, database_path, session_scope
from archive_workbench.db.models import AudiovisualMedia, DigitalObject, TranscriptionRun

EXPECTED_REVISION = "0047_authority_relation_profiles"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def create_validation_project(source: Path, destination: Path) -> dict[str, object]:
    source = source.expanduser().resolve()
    destination = destination.expanduser().resolve()
    source_db = database_path(source)
    if not source_db.is_file():
        raise RuntimeError(f"No existe la base fuente: {source_db}")
    if current_revision(source) != EXPECTED_REVISION:
        raise RuntimeError(
            f"La base fuente debe estar en {EXPECTED_REVISION}; actual: {current_revision(source)}"
        )
    if destination.exists():
        raise RuntimeError(
            f"El destino ya existe y no se reemplazará automáticamente: {destination}"
        )

    before_sha = _sha256(source_db)
    shutil.copytree(source, destination)
    after_sha = _sha256(source_db)
    if before_sha != after_sha:
        raise RuntimeError("La base fuente cambió durante la copia; no avances.")

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
            annotations = timeline_annotation_rows(session, media_id=media.id)
            run_count = len(
                session.scalars(
                    select(TranscriptionRun).where(
                        TranscriptionRun.audiovisual_media_id == media.id,
                        TranscriptionRun.status == "completed",
                    )
                ).all()
            )
    finally:
        engine.dispose()

    return {
        "source": str(source),
        "destination": str(destination),
        "revision": current_revision(destination),
        "source_database_sha256": before_sha,
        "source_database_unchanged": before_sha == after_sha,
        "starting_timeline_annotation_count": len(annotations),
        "transcription_run_count": run_count,
        "note": "La fuente RC5 se conserva intacta; project_data no se lee ni se modifica.",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    result = create_validation_project(args.source, args.destination)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
