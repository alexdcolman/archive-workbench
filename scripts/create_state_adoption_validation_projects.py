#!/usr/bin/env python3
"""Crea dos copias divergentes y un paquete de estado para validar EX-01D."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil

from sqlalchemy import select

from archive_workbench.db import (
    create_sqlite_engine,
    current_revision,
    database_path,
    session_scope,
    upgrade_database,
)
from archive_workbench.db.models import EditableObject, Project
from archive_workbench.decisions import load_decisions
from archive_workbench.editing import update_editable_object
from archive_workbench.exchange import (
    current_editable_state_sha256,
    fork_exchange_workspace,
)
from archive_workbench.state_adoption import create_state_adoption_package


def _copy_project(source: Path, destination: Path, *, force: bool) -> None:
    if destination.exists():
        if not force:
            raise SystemExit(
                f"El destino ya existe: {destination}. Usá --force para recrearlo."
            )
        shutil.rmtree(destination)
    shutil.copytree(source, destination)
    shutil.rmtree(destination / "exchange", ignore_errors=True)
    shutil.rmtree(destination / "backups", ignore_errors=True)
    upgrade_database(destination)


def _change_first_object(
    root: Path,
    *,
    text_suffix: str,
    actor: str,
) -> tuple[str, str]:
    decisions = load_decisions(root / "config" / "decisions.yaml")
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            editable = session.scalars(
                select(EditableObject).order_by(
                    EditableObject.digital_object_id,
                    EditableObject.page_number,
                    EditableObject.current_order_index,
                    EditableObject.id,
                )
            ).first()
            if editable is None:
                raise RuntimeError("El proyecto fuente no tiene objetos editables.")
            update_editable_object(
                session,
                decisions=decisions,
                object_id=editable.id,
                expected_revision=editable.revision_number,
                edited_by=actor,
                text=f"{editable.current_text}\n{text_suffix}",
            )
            return editable.id, editable.current_text
    finally:
        engine.dispose()


def create_validation_projects(
    source: Path,
    source_destination: Path,
    target_destination: Path,
    *,
    force: bool,
) -> dict[str, object]:
    source = source.resolve()
    source_destination = source_destination.resolve()
    target_destination = target_destination.resolve()
    if not database_path(source).is_file():
        raise SystemExit(f"No se encontró una base de proyecto en: {source}")
    if source_destination == target_destination:
        raise SystemExit("Las copias descartables deben tener rutas diferentes.")

    _copy_project(source, source_destination, force=force)
    _copy_project(source, target_destination, force=force)

    source_engine = create_sqlite_engine(database_path(source_destination))
    target_engine = create_sqlite_engine(database_path(target_destination))
    try:
        with session_scope(source_engine) as session:
            source_workspace = fork_exchange_workspace(
                session,
                workspace_name="ex01d-origen",
                created_by="alex",
                checkpoint_label="baseline_ex01d_source",
            )
        with session_scope(target_engine) as session:
            target_workspace = fork_exchange_workspace(
                session,
                workspace_name="ex01d-destino",
                created_by="alex",
                checkpoint_label="baseline_ex01d_target",
            )
    finally:
        source_engine.dispose()
        target_engine.dispose()

    object_id, _ = _change_first_object(
        source_destination,
        text_suffix="Estado remoto EX-01D",
        actor="alex",
    )
    target_object_id, _ = _change_first_object(
        target_destination,
        text_suffix="Estado local EX-01D",
        actor="alex",
    )
    if object_id != target_object_id:
        raise RuntimeError("Las copias no conservan el mismo objeto editable de referencia.")

    source_engine = create_sqlite_engine(database_path(source_destination))
    target_engine = create_sqlite_engine(database_path(target_destination))
    try:
        with session_scope(source_engine) as session:
            source_project_id = session.scalar(select(Project.id))
            assert source_project_id
            source_state = current_editable_state_sha256(
                session, source_project_id
            )
            package = create_state_adoption_package(
                session,
                project_root=source_destination,
                target_workspace_id=target_workspace.workspace_id,
                target_workspace_name=target_workspace.workspace_name,
                created_by="alex",
                creation_reason="Validación EX-01D paquete inicial.",
                package_confirmed=True,
            )
        with session_scope(target_engine) as session:
            target_project_id = session.scalar(select(Project.id))
            assert target_project_id
            target_state = current_editable_state_sha256(
                session, target_project_id
            )
    finally:
        source_engine.dispose()
        target_engine.dispose()

    if source_state == target_state:
        raise RuntimeError("Las copias descartables no quedaron divergentes.")

    validation_dir = target_destination / "exchange" / "state_adoption"
    validation_dir.mkdir(parents=True, exist_ok=True)
    validation_path = validation_dir / "validation.json"
    payload = {
        "source_root": str(source_destination),
        "source_workspace_id": source_workspace.workspace_id,
        "source_workspace_name": source_workspace.workspace_name,
        "target_root": str(target_destination),
        "target_workspace_id": target_workspace.workspace_id,
        "target_workspace_name": target_workspace.workspace_name,
        "object_id": object_id,
        "source_state_sha256": source_state,
        "target_state_sha256": target_state,
        "package_path": str(package.output_path),
        "package_sha256": package.package_sha256,
        "adoption_id": package.adoption_id,
        "revision": current_revision(target_destination),
    }
    validation_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {**payload, "validation_path": validation_path}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--source-destination", type=Path, required=True)
    parser.add_argument("--target-destination", type=Path, required=True)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    result = create_validation_projects(
        args.source,
        args.source_destination,
        args.target_destination,
        force=args.force,
    )
    print(f"Copia origen descartable: {result['source_root']}")
    print(f"Identidad origen: {result['source_workspace_id']}")
    print(f"Copia destinataria descartable: {result['target_root']}")
    print(f"Identidad destinataria: {result['target_workspace_id']}")
    print(f"Revisión de base: {result['revision']}")
    print(f"Estado origen: {result['source_state_sha256']}")
    print(f"Estado destinatario: {result['target_state_sha256']}")
    print(f"Paquete inicial: {result['package_path']}")
    print(f"Datos de validación: {result['validation_path']}")
    print("Las copias tienen identidades distintas y estados editables divergentes.")
    print("El proyecto fuente no fue modificado.")


if __name__ == "__main__":
    main()
