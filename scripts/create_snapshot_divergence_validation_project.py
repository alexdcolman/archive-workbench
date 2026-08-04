#!/usr/bin/env python3
"""Crea una copia descartable con dos divergencias fila/snapshot."""

from __future__ import annotations

import argparse
from pathlib import Path
import shutil

from sqlalchemy import select

from archive_workbench.authorities import (
    create_authority,
    create_mention,
    mention_repair_cases,
)
from archive_workbench.db import create_sqlite_engine, database_path, session_scope
from archive_workbench.db.models import DigitalObject, EditableObject, utc_now
from archive_workbench.editing import _append_revision

_ADOPT_TEXT = "Mencion divergente alfa para conservar fila vigente"
_RESTORE_TEXT = "Mencion divergente beta para restaurar historial"


def _authority(session, *, project_id: str, name: str):
    return create_authority(
        session,
        project_id=project_id,
        entity_type="other",
        preferred_name=name,
        description="Entidad descartable para validar una divergencia fila/snapshot.",
        created_by="archive-workbench-demo",
        review_status="reviewed",
    )


def create_validation_copy(
    source: Path,
    destination: Path,
    *,
    force: bool,
) -> dict[str, str]:
    source = source.resolve()
    destination = destination.resolve()
    if not database_path(source).exists():
        raise SystemExit(f"No se encontró una base de proyecto en: {source}")
    if destination.exists():
        if not force:
            raise SystemExit(
                f"El destino ya existe: {destination}. Usá --force para recrearlo."
            )
        shutil.rmtree(destination)
    shutil.copytree(source, destination)

    engine = create_sqlite_engine(database_path(destination))
    try:
        with session_scope(engine) as session:
            editable = session.scalar(
                select(EditableObject)
                .where(
                    EditableObject.lifecycle_status == "active",
                    EditableObject.current_text != "",
                )
                .order_by(
                    EditableObject.page_number,
                    EditableObject.current_order_index,
                    EditableObject.id,
                )
                .limit(1)
            )
            if editable is None:
                raise RuntimeError("La copia no contiene objetos textuales activos.")
            digital = session.get(DigitalObject, editable.digital_object_id)
            if digital is None:
                raise RuntimeError("No pudo localizarse el proyecto del objeto textual.")

            suffix = f"\n{_ADOPT_TEXT}. {_RESTORE_TEXT}."
            original_length = len(editable.current_text)
            base_revision = editable.revision_number
            editable.current_text += suffix
            editable.revision_number += 1
            editable.updated_by = "archive-workbench-demo"
            editable.updated_at = utc_now()
            session.flush()
            _append_revision(
                session,
                editable,
                operation="edit",
                created_by="archive-workbench-demo",
                note=(
                    "Edición descartable que agrega dos fragmentos completos para "
                    "validar la reconciliación de divergencias."
                ),
                base_revision_number=base_revision,
            )

            adopt_start = original_length + 1
            restore_start = adopt_start + len(_ADOPT_TEXT) + 2
            adopt_authority = _authority(
                session,
                project_id=digital.project_id,
                name="Entidad divergente alfa",
            )
            restore_authority = _authority(
                session,
                project_id=digital.project_id,
                name="Entidad divergente beta",
            )
            adopt = create_mention(
                session,
                object_id=editable.id,
                mention_text=_ADOPT_TEXT,
                authority_id=adopt_authority.id,
                start_offset=adopt_start,
                end_offset=adopt_start + len(_ADOPT_TEXT),
                status="accepted",
                source="manual",
                note="Nota registrada antes de la divergencia alfa.",
                created_by="archive-workbench-demo",
            )
            restore = create_mention(
                session,
                object_id=editable.id,
                mention_text=_RESTORE_TEXT,
                authority_id=restore_authority.id,
                start_offset=restore_start,
                end_offset=restore_start + len(_RESTORE_TEXT),
                status="accepted",
                source="manual",
                note="Nota registrada antes de la divergencia beta.",
                created_by="archive-workbench-demo",
            )

            # Simula dos escrituras históricas sin snapshot. La primera debe
            # conservarse; la segunda debe descartarse restaurando el historial.
            adopt.note = "Nota vigente verificada para conservar."
            adopt.updated_by = "legacy-import"
            adopt.updated_at = utc_now()

            restore.authority_id = None
            restore.status = "pending"
            restore.note = "Estado accidental sin respaldo histórico."
            restore.updated_by = "legacy-import"
            restore.updated_at = utc_now()
            session.flush()

            project_id = digital.project_id
            result = {
                "adopt_mention_id": adopt.id,
                "restore_mention_id": restore.id,
                "adopt_authority_id": adopt_authority.id,
                "restore_authority_id": restore_authority.id,
                "object_id": editable.id,
            }

        with session_scope(engine) as session:
            cases = {
                case.mention_id: case
                for case in mention_repair_cases(session, project_id=project_id)
                if case.code == "snapshot_divergence"
            }
            expected = {
                result["adopt_mention_id"],
                result["restore_mention_id"],
            }
            if not expected.issubset(cases):
                raise RuntimeError(
                    "La copia descartable no produjo las dos divergencias esperadas."
                )
            if not all(cases[mention_id].can_resolve_snapshot_divergence for mention_id in expected):
                raise RuntimeError(
                    "Alguna divergencia no contiene evidencia suficiente para reconciliarla."
                )
    finally:
        engine.dispose()

    print(f"Proyecto descartable creado: {destination}")
    print(f"Mención para conservar fila vigente: {result['adopt_mention_id']}")
    print(f"Mención para restaurar historial: {result['restore_mention_id']}")
    print("Alertas esperadas: 2 × snapshot_divergence")
    print("En alfa, conservá la fila vigente. En beta, restaurá el último estado registrado.")
    print("Abrí Explorar relaciones > Revisar alertas.")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source",
        type=Path,
        default=Path("project_data_rebase_validation"),
    )
    parser.add_argument(
        "--destination",
        type=Path,
        default=Path("project_data_snapshot_divergence_validation"),
    )
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    create_validation_copy(args.source, args.destination, force=args.force)


if __name__ == "__main__":
    main()
