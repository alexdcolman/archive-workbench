#!/usr/bin/env python3
"""Crea un proyecto descartable AV-02 sin descargar material ni tocar project_data."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml

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
from archive_workbench.version import __version__


EXPECTED_CHANNEL_ID = "UCsZG_7l0cYIEtJNhajrFPYg"
EXPECTED_ACCESS_CONDITIONS = "Material autorizado para prueba AV-02."


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
    payload["project_name"] = "Proyecto de validación AV-02"
    payload["project_id"] = "av02_platform_validation"
    decisions_path.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )

    upgrade_database(destination)
    decisions = load_decisions(decisions_path)
    engine = create_sqlite_engine(database_path(destination))
    try:
        with session_scope(engine) as session:
            ensure_project(session, decisions)
            root_level = next(
                (
                    level
                    for level in sorted(decisions.archival_levels, key=lambda item: item.display_order)
                    if level.enabled and not level.parent_keys
                ),
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
                title="Testimonios audiovisuales autorizados",
                created_by="validation_script",
            )
            unit_id = unit.id
    finally:
        engine.dispose()

    result: dict[str, object] = {
        "version": __version__,
        "revision": current_revision(destination),
        "destination": str(destination),
        "project_id": "av02_platform_validation",
        "archival_unit_id": unit_id,
        "archival_unit_title": "Testimonios audiovisuales autorizados",
        "expected_channel_id": EXPECTED_CHANNEL_ID,
        "expected_access_conditions": EXPECTED_ACCESS_CONDITIONS,
        "platform_import_count": 0,
        "project_data_touched": False,
        "note": (
            "project_data no fue leído ni modificado; el script no descarga material "
            "y no elimina ni reemplaza proyectos"
        ),
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
