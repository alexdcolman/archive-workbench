#!/usr/bin/env python3
"""Crea un proyecto descartable para validar CAT-01 sin tocar project_data."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil

import yaml

from archive_workbench.catalog import ensure_project
from archive_workbench.catalog_templates import export_catalog_template_bytes
from archive_workbench.db import (
    create_sqlite_engine,
    current_revision,
    database_path,
    session_scope,
    upgrade_database,
)
from archive_workbench.decisions import load_decisions
from archive_workbench.project_init import initialize_project


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def create_validation_project(destination: Path, *, force: bool) -> dict[str, object]:
    destination = destination.expanduser().resolve()
    if destination.exists():
        if not force:
            raise SystemExit(
                f"El destino ya existe: {destination}. Usá --force solo con autorización expresa."
            )
        shutil.rmtree(destination)

    repository_root = Path(__file__).resolve().parents[1]
    initialize_project(destination, template_root=repository_root / "config")
    decisions_path = destination / "config" / "decisions.yaml"
    decisions_payload = yaml.safe_load(decisions_path.read_text(encoding="utf-8"))
    decisions_payload["project_name"] = "Proyecto de validación CAT-01"
    decisions_payload["project_id"] = "cat01_validation"
    decisions_path.write_text(
        yaml.safe_dump(decisions_payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    upgrade_database(destination)
    decisions = load_decisions(decisions_path)
    engine = create_sqlite_engine(database_path(destination))
    try:
        with session_scope(engine) as session:
            ensure_project(session, decisions)
    finally:
        engine.dispose()

    validation = destination / "validation"
    validation.mkdir(parents=True, exist_ok=True)
    source_example = repository_root / "examples" / "plantilla_catalogo_dippba.xlsx"
    valid_template = validation / "plantilla_catalogo_dippba.xlsx"
    shutil.copy2(source_example, valid_template)

    invalid_rows = [
        {
            "local_id": "archivo_control",
            "level_key": "archivo",
            "title": "Archivo control",
            "registration_status": "provisional",
        },
        {
            "local_id": "fondo_control",
            "parent_local_id": "archivo_control",
            "level_key": "fondo",
            "title": "Fondo control",
            "registration_status": "provisional",
        },
        {
            "local_id": "documento_invalido",
            "parent_local_id": "fondo_control",
            "level_key": "documento",
            "title": "Documento que no puede depender directamente del fondo",
            "registration_status": "provisional",
        },
    ]
    invalid_template = validation / "plantilla_invalida_documento_bajo_fondo.xlsx"
    invalid_template.write_bytes(
        export_catalog_template_bytes(
            None,
            decisions=decisions,
            project_id=decisions.project_id,
            template_name="Control negativo CAT-01",
            target_project_id="*",
            structure_parent_overrides={
                "archivo": [],
                "fondo": ["archivo"],
                "seccion": ["fondo"],
                "subseccion": ["seccion"],
                "serie": ["seccion", "subseccion"],
                "subserie": ["serie"],
                "caja": ["serie", "subserie"],
                "legajo": ["serie", "subserie", "caja"],
                "tomo": ["legajo"],
                "documento": ["caja", "legajo", "tomo"],
            },
            seed_rows=invalid_rows,
            source_note=(
                "Control negativo: el documento depende directamente del fondo y debe ser rechazado."
            ),
        )
    )

    manifest = {
        "version": "0.75.0",
        "database_revision": current_revision(destination),
        "project_root": str(destination),
        "project_name": decisions.project_name,
        "project_id": decisions.project_id,
        "valid_template": str(valid_template),
        "valid_template_sha256": _sha256(valid_template),
        "invalid_template": str(invalid_template),
        "invalid_template_sha256": _sha256(invalid_template),
        "expected_valid_rows": 155,
        "expected_invalid_code": "invalid_parent_level",
        "project_data_touched": False,
    }
    manifest_path = validation / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    manifest["manifest"] = str(manifest_path)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    manifest = create_validation_project(args.destination, force=args.force)
    print(f"Proyecto descartable creado: {manifest['project_root']}")
    print(f"Revisión de base: {manifest['database_revision']}")
    print(f"Proyecto de validación: {manifest['project_name']} ({manifest['project_id']})")
    print(f"Plantilla DIPPBA: {manifest['valid_template']}")
    print(f"Filas esperadas: {manifest['expected_valid_rows']}")
    print(f"Control negativo: {manifest['invalid_template']}")
    print(f"Manifiesto: {manifest['manifest']}")
    print("project_data no fue leído ni modificado.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
