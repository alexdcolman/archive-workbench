#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from sqlalchemy import select

from archive_workbench.db import create_sqlite_engine, current_revision, database_path, session_scope, upgrade_database
from archive_workbench.db.models import AuthorityRecord, Project
from archive_workbench.identity import new_id, sha256_file
from archive_workbench.version import __version__

SOURCE_REVISION = "0045_audiovisual_transcription"
TARGET_REVISION = "0047_authority_relation_profiles"


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
    source_db_sha_before = sha256_file(source_db)

    shutil.copytree(source_root, destination)
    upgrade_database(destination)
    if current_revision(destination) != TARGET_REVISION:
        raise RuntimeError("La copia de validación no quedó en la revisión audiovisual esperada.")

    engine = create_sqlite_engine(database_path(destination))
    try:
        with session_scope(engine) as session:
            project = session.scalar(select(Project).order_by(Project.created_at, Project.id))
            if project is None:
                raise RuntimeError("La copia no contiene un proyecto registrado.")
            authority = session.scalar(
                select(AuthorityRecord).where(
                    AuthorityRecord.project_id == project.id,
                    AuthorityRecord.normalized_name == "horacio bau",
                    AuthorityRecord.lifecycle_status == "active",
                )
            )
            if authority is None:
                authority = AuthorityRecord(
                    id=new_id(),
                    project_id=project.id,
                    entity_type="person",
                    preferred_name="Horacio Bau",
                    normalized_name="horacio bau",
                    description="Autoridad preparada para la validación AV-03 de hablantes.",
                    lifecycle_status="active",
                    review_status="reviewed",
                    created_by="AV-03 validation",
                    updated_by="AV-03 validation",
                    revision=1,
                )
                session.add(authority)
                session.flush()
            authority_id = authority.id
    finally:
        engine.dispose()

    source_db_sha_after = sha256_file(source_db)
    if source_db_sha_before != source_db_sha_after:
        raise RuntimeError("La base fuente cambió mientras se preparaba la copia de validación.")

    return {
        "version": __version__,
        "source": str(source_root),
        "destination": str(destination),
        "source_revision": source_revision,
        "revision": current_revision(destination),
        "source_database_unchanged": True,
        "source_database_sha256": source_db_sha_after,
        "prepared_authority": "Horacio Bau",
        "prepared_authority_id": authority_id,
        "note": "La validación usa una copia; el proyecto AV-03 anterior y project_data no se modifican.",
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
