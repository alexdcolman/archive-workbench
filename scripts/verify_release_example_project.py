#!/usr/bin/env python3
"""Verifica el proyecto de ejemplo portable de la candidata de Archive Workbench."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import zipfile

from sqlalchemy import func, select

from archive_workbench.db import (
    create_sqlite_engine,
    current_revision,
    database_path,
    session_scope,
)
from archive_workbench.db.models import (
    AuthorityRecord,
    DigitalObject,
    EditableObject,
    EditablePage,
    EntityMention,
    EntityRelation,
    FileInstance,
    SourceRegistration,
)
from archive_workbench.identity import sha256_file

EXPECTED_REVISION = "0048_catalog_document_components"
EXPECTED_PROJECT_ID = "archive_workbench_ejemplo"
EXPECTED_SOURCE_KEYS = {
    "ejemplo_actividad_cultural",
    "ejemplo_reunion_vecinal",
}


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def verify_project(project: Path) -> dict[str, object]:
    project = project.expanduser().resolve()
    _require(project.is_dir(), f"No existe el proyecto: {project}")
    _require(
        (project / "config" / "decisions.yaml").is_file(),
        "Falta config/decisions.yaml",
    )
    _require(
        (project / "README_EJEMPLO.txt").is_file(),
        "Falta README_EJEMPLO.txt",
    )
    manifest_path = project / "release_example_manifest.json"
    _require(manifest_path.is_file(), "Falta release_example_manifest.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    _require(
        manifest.get("synthetic_data_only") is True, "El manifiesto no declara datos sintéticos"
    )
    _require(manifest.get("project_id") == EXPECTED_PROJECT_ID, "project_id inesperado")

    revision = current_revision(project)
    _require(
        revision == EXPECTED_REVISION,
        f"Revisión de base inesperada: {revision!r}",
    )

    engine = create_sqlite_engine(database_path(project))
    try:
        with session_scope(engine) as session:
            registrations = session.scalars(
                select(SourceRegistration).where(
                    SourceRegistration.project_id == EXPECTED_PROJECT_ID
                )
            ).all()
            keys = {row.source_key for row in registrations}
            _require(keys == EXPECTED_SOURCE_KEYS, f"source_keys inesperadas: {sorted(keys)}")

            digital_objects = session.scalars(
                select(DigitalObject).where(DigitalObject.project_id == EXPECTED_PROJECT_ID)
            ).all()
            _require(len(digital_objects) == 2, "Se esperaban exactamente 2 objetos digitales")
            digital_by_id = {row.id: row for row in digital_objects}

            file_instances = session.scalars(select(FileInstance)).all()
            _require(len(file_instances) == 2, "Se esperaban exactamente 2 copias físicas")
            for instance in file_instances:
                _require(instance.storage_root == "project", "storage_root no portable")
                path = project / instance.relative_path
                _require(path.is_file(), f"Archivo físico ausente: {instance.relative_path}")
                digital = digital_by_id.get(instance.digital_object_id)
                _require(digital is not None, "FileInstance sin DigitalObject del proyecto")
                digest = sha256_file(path)
                _require(digest == digital.sha256, f"SHA distinto en {instance.relative_path}")
                _require(
                    instance.verified_sha256 == digital.sha256,
                    f"SHA verificado incoherente en {instance.relative_path}",
                )

            editable_pages = session.scalar(select(func.count(EditablePage.id))) or 0
            editable_objects = (
                session.scalar(
                    select(func.count(EditableObject.id)).where(
                        EditableObject.lifecycle_status == "active"
                    )
                )
                or 0
            )
            authorities = (
                session.scalar(
                    select(func.count(AuthorityRecord.id)).where(
                        AuthorityRecord.project_id == EXPECTED_PROJECT_ID
                    )
                )
                or 0
            )
            mentions = session.scalar(select(func.count(EntityMention.id))) or 0
            relations = (
                session.scalar(
                    select(func.count(EntityRelation.id)).where(
                        EntityRelation.project_id == EXPECTED_PROJECT_ID,
                        EntityRelation.lifecycle_status == "active",
                    )
                )
                or 0
            )

            _require(editable_pages == 2, f"Se esperaban 2 páginas editables; hay {editable_pages}")
            _require(
                editable_objects == 2,
                f"Se esperaban 2 objetos editables activos; hay {editable_objects}",
            )
            _require(authorities == 4, f"Se esperaban 4 entidades; hay {authorities}")
            _require(mentions == 6, f"Se esperaban 6 menciones; hay {mentions}")
            _require(relations == 3, f"Se esperaban 3 relaciones; hay {relations}")
    finally:
        engine.dispose()

    return {
        "project": str(project),
        "revision": revision,
        "documents": 2,
        "editable_pages": 2,
        "editable_objects": 2,
        "authorities": 4,
        "mentions": 6,
        "relations": 3,
        "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
    }


def verify_archive(archive: Path, project_name: str) -> dict[str, object]:
    archive = archive.expanduser().resolve()
    _require(archive.is_file(), f"No existe el ZIP: {archive}")
    _require(zipfile.is_zipfile(archive), f"No es un ZIP válido: {archive}")
    with zipfile.ZipFile(archive) as bundle:
        names = bundle.namelist()
    _require(names, "El ZIP está vacío")
    prefix = f"{project_name}/"
    _require(
        all(name.startswith(prefix) for name in names), "El ZIP tiene rutas fuera del proyecto"
    )
    forbidden = (
        ".sqlite-wal",
        ".sqlite-shm",
        "__pycache__/",
        ".DS_Store",
    )
    _require(
        not any(any(token in name for token in forbidden) for name in names),
        "El ZIP contiene artefactos temporales o no portables",
    )
    _require(
        f"{prefix}release_example_manifest.json" in names,
        "El ZIP no contiene el manifiesto del ejemplo",
    )
    return {
        "archive": str(archive),
        "entries": len(names),
        "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--archive", type=Path)
    args = parser.parse_args()

    project_result = verify_project(args.project)
    print("PROYECTO DE EJEMPLO: OK")
    print(json.dumps(project_result, ensure_ascii=False, indent=2))
    if args.archive is not None:
        archive_result = verify_archive(args.archive, args.project.expanduser().resolve().name)
        print("ZIP PORTABLE: OK")
        print(json.dumps(archive_result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
