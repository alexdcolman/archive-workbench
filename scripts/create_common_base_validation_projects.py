#!/usr/bin/env python3
"""Crea dos copias descartables con estado editable idéntico para validar EX-01C."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil

from archive_workbench.db import (
    create_sqlite_engine,
    current_revision,
    database_path,
    session_scope,
    upgrade_database,
)
from archive_workbench.exchange import (
    current_editable_state_sha256,
    fork_exchange_workspace,
)


def _copy_project(source: Path, destination: Path, *, force: bool) -> None:
    if destination.exists():
        if not force:
            raise SystemExit(
                f"El destino ya existe: {destination}. Usá --force para recrearlo."
            )
        shutil.rmtree(destination)
    shutil.copytree(source, destination)
    shutil.rmtree(destination / "exchange", ignore_errors=True)
    upgrade_database(destination)


def create_validation_projects(
    source: Path,
    initiator_destination: Path,
    counterpart_destination: Path,
    *,
    force: bool,
) -> dict[str, object]:
    source = source.resolve()
    initiator_destination = initiator_destination.resolve()
    counterpart_destination = counterpart_destination.resolve()
    if not database_path(source).is_file():
        raise SystemExit(f"No se encontró una base de proyecto en: {source}")
    if initiator_destination == counterpart_destination:
        raise SystemExit("Las dos copias descartables deben tener rutas diferentes.")

    _copy_project(source, initiator_destination, force=force)
    _copy_project(source, counterpart_destination, force=force)

    initiator_engine = create_sqlite_engine(database_path(initiator_destination))
    counterpart_engine = create_sqlite_engine(database_path(counterpart_destination))
    try:
        with session_scope(initiator_engine) as session:
            initiator = fork_exchange_workspace(
                session,
                workspace_name="ex01c-iniciadora",
                created_by="alex",
                checkpoint_label="baseline_ex01c_a",
            )
            initiator_state = initiator.state_sha256

        with session_scope(counterpart_engine) as session:
            counterpart = fork_exchange_workspace(
                session,
                workspace_name="ex01c-contraparte",
                created_by="alex",
                checkpoint_label="baseline_ex01c_b",
            )
            counterpart_state = counterpart.state_sha256

        if initiator_state != counterpart_state:
            raise RuntimeError(
                "Las copias descartables no quedaron con el mismo estado editable."
            )

        validation_dir = initiator_destination / "exchange" / "common_base"
        validation_dir.mkdir(parents=True, exist_ok=True)
        validation_path = validation_dir / "validation.json"
        payload = {
            "initiator_root": str(initiator_destination),
            "initiator_workspace_id": initiator.workspace_id,
            "initiator_workspace_name": initiator.workspace_name,
            "counterpart_root": str(counterpart_destination),
            "counterpart_workspace_id": counterpart.workspace_id,
            "counterpart_workspace_name": counterpart.workspace_name,
            "state_sha256": initiator_state,
            "revision": current_revision(initiator_destination),
        }
        validation_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return {**payload, "validation_path": validation_path}
    finally:
        initiator_engine.dispose()
        counterpart_engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--initiator-destination", type=Path, required=True)
    parser.add_argument("--counterpart-destination", type=Path, required=True)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    result = create_validation_projects(
        args.source,
        args.initiator_destination,
        args.counterpart_destination,
        force=args.force,
    )
    print(f"Copia iniciadora descartable: {result['initiator_root']}")
    print(f"Identidad iniciadora: {result['initiator_workspace_id']}")
    print(f"Copia contraparte descartable: {result['counterpart_root']}")
    print(f"Identidad contraparte: {result['counterpart_workspace_id']}")
    print(f"Revisión de base: {result['revision']}")
    print(f"Estado editable compartido: {result['state_sha256']}")
    print(f"Datos de validación: {result['validation_path']}")
    print("Las copias tienen identidades distintas y estado editable idéntico.")
    print("El proyecto fuente no fue modificado.")


if __name__ == "__main__":
    main()
