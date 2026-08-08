#!/usr/bin/env python3
"""Crea dos proyectos vacíos descartables y un paquete para validar INT-01."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

import yaml

from archive_workbench.db import (
    create_sqlite_engine,
    current_revision,
    database_path,
    session_scope,
    upgrade_database,
)
from archive_workbench.db.models import Project, utc_now
from archive_workbench.exchange import (
    create_exchange_checkpoint,
    ensure_exchange_workspace,
    export_change_bundle,
    fork_exchange_workspace,
    inspect_change_bundle,
)
from archive_workbench.project_init import initialize_project

PROJECT_ID = "int01-google-drive-validation"


def _prepare_empty_project(destination: Path, *, force: bool) -> None:
    destination = destination.resolve()
    if destination.exists():
        if not force:
            raise SystemExit(
                f"El destino ya existe: {destination}. Elegí otra ruta o usá --force explícitamente."
            )
        shutil.rmtree(destination)
    repository_root = Path(__file__).resolve().parents[1]
    initialize_project(destination, template_root=repository_root / "config")
    decisions_path = destination / "config" / "decisions.yaml"
    decisions_payload = yaml.safe_load(decisions_path.read_text(encoding="utf-8"))
    if not isinstance(decisions_payload, dict):
        raise RuntimeError("La plantilla decisions.yaml no contiene un objeto YAML válido.")
    decisions_payload["project_name"] = "Validación INT-01 Google Drive"
    decisions_payload["project_id"] = PROJECT_ID
    decisions_path.write_text(
        yaml.safe_dump(decisions_payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    upgrade_database(destination)
    engine = create_sqlite_engine(database_path(destination))
    try:
        with session_scope(engine) as session:
            session.add(
                Project(
                    id=PROJECT_ID,
                    name="Validación INT-01 Google Drive",
                    decisions_schema_version="1.0",
                    decisions_json={},
                    created_at=utc_now(),
                    updated_at=utc_now(),
                )
            )
            session.flush()
            ensure_exchange_workspace(
                session,
                workspace_name="int01-emisora",
                changed_by="validation",
            )
            create_exchange_checkpoint(
                session,
                label="baseline_int01_sender",
                created_by="validation",
                note="Base vacía para validar transporte por Google Drive",
            )
    finally:
        engine.dispose()


def create_validation_projects(
    sender_destination: Path,
    receiver_destination: Path,
    *,
    force: bool,
) -> dict[str, object]:
    sender = sender_destination.resolve()
    receiver = receiver_destination.resolve()
    if sender == receiver:
        raise SystemExit("La copia emisora y la receptora deben usar rutas distintas.")

    _prepare_empty_project(sender, force=force)
    if receiver.exists():
        if not force:
            raise SystemExit(
                f"El destino ya existe: {receiver}. Elegí otra ruta o usá --force explícitamente."
            )
        shutil.rmtree(receiver)
    shutil.copytree(sender, receiver)
    upgrade_database(receiver)

    receiver_engine = create_sqlite_engine(database_path(receiver))
    try:
        with session_scope(receiver_engine) as session:
            receiver_workspace = fork_exchange_workspace(
                session,
                workspace_name="int01-receptora",
                created_by="validation",
                checkpoint_label="baseline_int01_receiver",
            )
    finally:
        receiver_engine.dispose()

    sender_engine = create_sqlite_engine(database_path(sender))
    try:
        with session_scope(sender_engine) as session:
            sender_workspace = ensure_exchange_workspace(session)
            bundle = export_change_bundle(
                session,
                project_root=sender,
                checkpoint_ref="baseline_int01_sender",
                created_by="validation",
            )
            sender_workspace_id = sender_workspace.id
            sender_workspace_name = sender_workspace.workspace_name
    finally:
        sender_engine.dispose()

    receiver_state = receiver_workspace.state_sha256
    if not receiver_state:
        raise RuntimeError("La copia receptora no obtuvo una huella de estado.")
    inspection = inspect_change_bundle(bundle.output_path)
    if inspection.manifest.base_checkpoint_state_sha256 != receiver_state:
        raise RuntimeError(
            "La copia receptora no comparte la base declarada por el paquete de validación."
        )

    payload = {
        "project_id": PROJECT_ID,
        "revision": current_revision(sender),
        "sender_root": str(sender),
        "sender_workspace_id": sender_workspace_id,
        "sender_workspace_name": sender_workspace_name,
        "receiver_root": str(receiver),
        "receiver_workspace_id": receiver_workspace.workspace_id,
        "receiver_workspace_name": receiver_workspace.workspace_name,
        "shared_state_sha256": receiver_state,
        "bundle_path": str(bundle.output_path),
        "bundle_id": bundle.bundle_id,
        "bundle_sha256": bundle.bundle_sha256,
        "bundle_event_count": bundle.event_count,
    }
    validation_path = receiver / "exchange" / "google_drive_validation.json"
    validation_path.parent.mkdir(parents=True, exist_ok=True)
    validation_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    payload["validation_path"] = str(validation_path)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sender-destination", type=Path, required=True)
    parser.add_argument("--receiver-destination", type=Path, required=True)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    result = create_validation_projects(
        args.sender_destination,
        args.receiver_destination,
        force=args.force,
    )
    print(f"Proyecto de validación: {result['project_id']}")
    print(f"Copia emisora: {result['sender_root']}")
    print(f"Identidad emisora: {result['sender_workspace_id']}")
    print(f"Copia receptora: {result['receiver_root']}")
    print(f"Identidad receptora: {result['receiver_workspace_id']}")
    print(f"Revisión: {result['revision']}")
    print(f"Paquete para subir: {result['bundle_path']}")
    print(f"Bundle: {result['bundle_id']}")
    print(f"SHA-256: {result['bundle_sha256']}")
    print(f"Eventos: {result['bundle_event_count']}")
    print(f"Datos de validación: {result['validation_path']}")
    print("No se usó ni modificó project_data.")


if __name__ == "__main__":
    main()
