#!/usr/bin/env python3
"""Crea un proyecto descartable para validar DISC-02 sin tocar project_data."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil

import yaml

from archive_workbench.authorities import add_authority_alias, create_authority
from archive_workbench.catalog import ensure_project
from archive_workbench.catalog_management import create_archival_unit
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


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


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
    decisions_payload["project_name"] = "Proyecto de validación DISC-02"
    decisions_payload["project_id"] = "disc02_validation"
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
            existing = create_authority(
                session,
                project_id=decisions.project_id,
                entity_type="organization",
                preferred_name="Comisión Provincial por la Memoria",
                description="Ficha canónica previa al diccionario controlado.",
                created_by="validation_script",
                review_status="approved",
            )
            add_authority_alias(
                session,
                authority_id=existing.id,
                alias="CPM",
                alias_type="acronym",
                created_by="validation_script",
            )
            unit = create_archival_unit(
                session,
                decisions=decisions,
                project_id=decisions.project_id,
                parent_id=None,
                level_key="archivo",
                title="Archivo documental de control",
                created_by="validation_script",
            )
            existing_id = existing.id
            unit_id = unit.id
    finally:
        engine.dispose()

    validation = destination / "validation"
    validation.mkdir(parents=True, exist_ok=True)
    valid_dictionary = validation / "diccionario_autoridades_valido.json"
    valid_payload = {
        "schema_version": "1.0",
        "dictionary_id": "disc02_control_v1",
        "dictionary_name": "Diccionario controlado DISC-02",
        "target_project_id": decisions.project_id,
        "source": {
            "title": "Fuente controlada para validar DISC-02",
            "organization": "Equipo local de validación",
            "url": "https://example.org/disc02-control",
            "reference": "CONTROL-DISC02-001",
            "created_by": "validation_script",
        },
        "authorities": [
            {
                "local_id": "cpm",
                "entity_type": "organization",
                "preferred_name": "Comisión Provincial por la Memoria",
                "description": "Esta descripción no debe sobrescribir la ficha existente.",
                "aliases": [
                    {
                        "value": "Comisión por la Memoria",
                        "alias_type": "variant",
                        "note": "Variante verificada para el control.",
                    }
                ],
                "resolution": {
                    "action": "use_existing",
                    "authority_id": existing_id,
                },
            },
            {
                "local_id": "investigadora",
                "entity_type": "person",
                "preferred_name": "Investigadora control DISC-02",
                "aliases": [
                    {
                        "value": "Dra. Control",
                        "alias_type": "title",
                    }
                ],
                "temporal_expression": "desde 1975",
                "review_status": "reviewed",
            },
            {
                "local_id": "publicacion",
                "entity_type": "work",
                "preferred_name": "Publicación control DISC-02",
                "characteristics": {
                    "tipo_documental": "artículo",
                    "idiomas": ["es", "en"],
                },
                "review_status": "unreviewed",
            },
        ],
        "relations": [
            {
                "local_id": "rel_publico",
                "source_local_id": "investigadora",
                "relation_label": "publicó",
                "target_kind": "authority",
                "target_local_id": "publicacion",
                "evidence": {
                    "note": "Página legal de la publicación controlada.",
                    "source_url": "https://example.org/publicacion-control",
                },
                "temporal_expression": "1978",
            },
            {
                "local_id": "rel_gestiona",
                "source_local_id": "cpm",
                "relation_label": "gestiona",
                "target_kind": "archival_unit",
                "target_id": unit_id,
                "evidence": {
                    "note": "Relación controlada con una unidad archivística existente.",
                    "source_reference": "CONTROL-DISC02-001",
                },
                "review_status": "reviewed",
            },
        ],
    }
    _write_json(valid_dictionary, valid_payload)

    conflict_dictionary = validation / "diccionario_conflicto_sin_resolver.json"
    conflict_payload = {
        "schema_version": "1.0",
        "dictionary_id": "disc02_conflict",
        "dictionary_name": "Conflicto controlado DISC-02",
        "source": {"title": "Control de duplicados"},
        "authorities": [
            {
                "local_id": "cpm_ambiguo",
                "entity_type": "organization",
                "preferred_name": "CPM",
            }
        ],
        "relations": [],
    }
    _write_json(conflict_dictionary, conflict_payload)

    missing_evidence = validation / "diccionario_relacion_sin_evidencia.json"
    missing_evidence_payload = {
        "schema_version": "1.0",
        "dictionary_id": "disc02_no_evidence",
        "dictionary_name": "Relación sin evidencia",
        "source": {"title": "Control negativo"},
        "authorities": [
            {
                "local_id": "a",
                "entity_type": "person",
                "preferred_name": "Persona A",
            },
            {
                "local_id": "b",
                "entity_type": "organization",
                "preferred_name": "Organización B",
            },
        ],
        "relations": [
            {
                "local_id": "sin_evidencia",
                "source_local_id": "a",
                "relation_label": "integró",
                "target_kind": "authority",
                "target_local_id": "b",
                "evidence": {},
            }
        ],
    }
    _write_json(missing_evidence, missing_evidence_payload)

    manifest = {
        "version": "0.76.0",
        "database_revision": current_revision(destination),
        "project_root": str(destination),
        "project_name": decisions.project_name,
        "project_id": decisions.project_id,
        "existing_authority_id": existing_id,
        "target_archival_unit_id": unit_id,
        "valid_dictionary": str(valid_dictionary),
        "valid_dictionary_sha256": _sha256(valid_dictionary),
        "conflict_dictionary": str(conflict_dictionary),
        "conflict_dictionary_sha256": _sha256(conflict_dictionary),
        "missing_evidence_dictionary": str(missing_evidence),
        "missing_evidence_dictionary_sha256": _sha256(missing_evidence),
        "expected_authorities_create": 2,
        "expected_authorities_reuse": 1,
        "expected_aliases_add": 2,
        "expected_relations_create": 2,
        "project_data_touched": False,
    }
    manifest_path = validation / "manifest.json"
    _write_json(manifest_path, manifest)
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
    print(f"Diccionario válido: {manifest['valid_dictionary']}")
    print(
        "Simulación esperada: "
        f"crear {manifest['expected_authorities_create']} autoridades, "
        f"reutilizar {manifest['expected_authorities_reuse']}, "
        f"agregar {manifest['expected_aliases_add']} alias y "
        f"crear {manifest['expected_relations_create']} relaciones"
    )
    print(f"Conflicto controlado: {manifest['conflict_dictionary']}")
    print(f"Relación sin evidencia: {manifest['missing_evidence_dictionary']}")
    print(f"Manifiesto: {manifest['manifest']}")
    print("project_data no fue leído ni modificado.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
