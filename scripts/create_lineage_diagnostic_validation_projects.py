#!/usr/bin/env python3
"""Crea dos copias descartables para validar EX-01A sin tocar el proyecto fuente."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import zipfile

from sqlalchemy import select

from archive_workbench.db import (
    create_sqlite_engine,
    current_revision,
    database_path,
    session_scope,
    upgrade_database,
)
from archive_workbench.db.models import EditableObject
from archive_workbench.decisions import load_decisions
from archive_workbench.editing import update_editable_object
from archive_workbench.exchange import (
    dry_run_change_bundle,
    export_change_bundle,
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
    source_destination: Path,
    receiver_destination: Path,
    *,
    force: bool,
) -> dict[str, object]:
    source = source.resolve()
    source_destination = source_destination.resolve()
    receiver_destination = receiver_destination.resolve()
    if not database_path(source).is_file():
        raise SystemExit(f"No se encontró una base de proyecto en: {source}")
    if source_destination == receiver_destination:
        raise SystemExit("Las dos copias descartables deben tener rutas diferentes.")

    _copy_project(source, source_destination, force=force)
    _copy_project(source, receiver_destination, force=force)

    source_decisions = load_decisions(source_destination / "config" / "decisions.yaml")
    source_engine = create_sqlite_engine(database_path(source_destination))
    receiver_engine = create_sqlite_engine(database_path(receiver_destination))
    try:
        with session_scope(source_engine) as session:
            fork_exchange_workspace(
                session,
                workspace_name="ex01a-origen",
                created_by="alex",
                checkpoint_label="baseline_ex01a",
            )
            editable = session.scalar(
                select(EditableObject)
                .where(EditableObject.lifecycle_status == "active")
                .order_by(EditableObject.page_number, EditableObject.current_order_index)
                .limit(1)
            )
            if editable is None:
                raise RuntimeError("La copia fuente no contiene objetos editables activos.")
            object_id = editable.id
            original_text = editable.current_text
            first_revision = editable.revision_number

        with session_scope(receiver_engine) as session:
            fork_exchange_workspace(
                session,
                workspace_name="ex01a-receptora",
                created_by="alex",
                checkpoint_label="baseline_ex01a",
            )

        with session_scope(source_engine) as session:
            update_editable_object(
                session,
                decisions=source_decisions,
                object_id=object_id,
                expected_revision=first_revision,
                edited_by="alex",
                text=original_text + "\n[EX-01A: primer cambio remoto descartable]",
                note="Preparación descartable para validar la cadena de linaje.",
            )
        with session_scope(source_engine) as session:
            first_bundle = export_change_bundle(
                session,
                project_root=source_destination,
                checkpoint_ref="baseline_ex01a",
                created_by="alex",
            )

        with session_scope(source_engine) as session:
            editable = session.get(EditableObject, object_id)
            if editable is None:
                raise RuntimeError("El objeto editable desapareció durante la preparación.")
            update_editable_object(
                session,
                decisions=source_decisions,
                object_id=object_id,
                expected_revision=editable.revision_number,
                edited_by="alex",
                text=editable.current_text
                + "\n[EX-01A: segundo cambio remoto descartable]",
                note="Segundo tramo descartable para validar la cadena de linaje.",
            )
        with session_scope(source_engine) as session:
            second_bundle = export_change_bundle(
                session,
                project_root=source_destination,
                checkpoint_ref=first_bundle.next_checkpoint_label,
                created_by="alex",
            )

        with session_scope(receiver_engine) as session:
            dry_run = dry_run_change_bundle(
                session,
                project_root=receiver_destination,
                bundle_path=second_bundle.output_path,
                assessed_by="alex",
            )
            if dry_run.base_match_status != "unmatched":
                raise RuntimeError(
                    "La preparación no produjo el paquete sin base reconocida esperado."
                )

        evidence_dir = receiver_destination / "exchange" / "lineage_evidence"
        evidence_dir.mkdir(parents=True, exist_ok=True)
        evidence_bundle = evidence_dir / first_bundle.output_path.name
        shutil.copy2(first_bundle.output_path, evidence_bundle)
        manifest_path = evidence_dir / "manifesto_aislado_de_apoyo.json"
        with zipfile.ZipFile(first_bundle.output_path, "r") as archive:
            manifest_path.write_bytes(archive.read("manifest.json"))
        validation_path = evidence_dir / "validation.json"
        validation_path.write_text(
            json.dumps(
                {
                    "target_bundle_id": second_bundle.bundle_id,
                    "target_bundle_path": str(second_bundle.output_path),
                    "evidence_bundle_path": str(evidence_bundle),
                    "support_manifest_path": str(manifest_path),
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )

        return {
            "source": source_destination,
            "receiver": receiver_destination,
            "revision": current_revision(receiver_destination),
            "object_id": object_id,
            "target_bundle_id": second_bundle.bundle_id,
            "target_bundle_path": second_bundle.output_path,
            "evidence_bundle_path": evidence_bundle,
            "support_manifest_path": manifest_path,
            "validation_path": validation_path,
        }
    finally:
        source_engine.dispose()
        receiver_engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--source-destination", type=Path, required=True)
    parser.add_argument("--receiver-destination", type=Path, required=True)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    result = create_validation_projects(
        args.source,
        args.source_destination,
        args.receiver_destination,
        force=args.force,
    )
    print(f"Copia origen descartable: {result['source']}")
    print(f"Copia receptora descartable: {result['receiver']}")
    print(f"Revisión de base: {result['revision']}")
    print(f"Paquete sin base reconocida: {result['target_bundle_id']}")
    print(f"Ruta del paquete evaluado: {result['target_bundle_path']}")
    print(f"Evidencia concluyente: {result['evidence_bundle_path']}")
    print(f"Manifiesto aislado de apoyo: {result['support_manifest_path']}")
    print(f"Datos de validación: {result['validation_path']}")
    print("Sin evidencia adicional el diagnóstico debe ser insuficiente.")
    print("Con el paquete de evidencia debe ser recuperable mediante una cadena verificada.")
    print("El proyecto fuente no fue modificado.")


if __name__ == "__main__":
    main()
