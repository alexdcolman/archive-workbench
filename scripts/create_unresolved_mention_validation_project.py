#!/usr/bin/env python3
"""Crea una copia descartable con una ubicación ambigua y un fragmento ausente."""

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

_AMBIGUOUS_OLD = "MENCION AMBIGUA REPETIDA"
_AMBIGUOUS_CURRENT = "Mencion ambigua repetida"
_ABSENT = "FRAGMENTO RETIRADO DEL TEXTO VIGENTE"


def _authority(session, *, project_id: str, name: str):
    return create_authority(
        session,
        project_id=project_id,
        entity_type="other",
        preferred_name=name,
        description="Entidad descartable para validar una ubicación manual.",
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

            original_text = editable.current_text
            old_suffix = f"\n{_AMBIGUOUS_OLD}. {_ABSENT}."
            base_revision = editable.revision_number
            editable.current_text = original_text + old_suffix
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
                    "Edición descartable que incorpora dos fragmentos históricos para "
                    "validar decisiones manuales de ubicación."
                ),
                base_revision_number=base_revision,
            )

            ambiguous_start = len(original_text) + 1
            absent_start = ambiguous_start + len(_AMBIGUOUS_OLD) + 2
            ambiguous_authority = _authority(
                session,
                project_id=digital.project_id,
                name="Entidad de ubicación ambigua",
            )
            absent_authority = _authority(
                session,
                project_id=digital.project_id,
                name="Entidad de fragmento ausente",
            )
            ambiguous = create_mention(
                session,
                object_id=editable.id,
                mention_text=_AMBIGUOUS_OLD,
                authority_id=ambiguous_authority.id,
                start_offset=ambiguous_start,
                end_offset=ambiguous_start + len(_AMBIGUOUS_OLD),
                status="accepted",
                source="manual",
                note="Mención histórica que tendrá dos apariciones posibles.",
                created_by="archive-workbench-demo",
            )
            absent = create_mention(
                session,
                object_id=editable.id,
                mention_text=_ABSENT,
                authority_id=absent_authority.id,
                start_offset=absent_start,
                end_offset=absent_start + len(_ABSENT),
                status="accepted",
                source="manual",
                note="Mención histórica cuyo fragmento será retirado.",
                created_by="archive-workbench-demo",
            )

            current_suffix = (
                f"\nPrimera aparición: {_AMBIGUOUS_CURRENT}. "
                f"Segunda aparición elegida: {_AMBIGUOUS_CURRENT}."
            )
            base_revision = editable.revision_number
            editable.current_text = original_text + current_suffix
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
                    "Edición descartable que duplica un fragmento con cambio de mayúsculas "
                    "y retira el segundo fragmento."
                ),
                base_revision_number=base_revision,
            )

            project_id = digital.project_id
            result = {
                "ambiguous_mention_id": ambiguous.id,
                "absent_mention_id": absent.id,
                "object_id": editable.id,
            }

        with session_scope(engine) as session:
            cases = {
                case.mention_id: case
                for case in mention_repair_cases(session, project_id=project_id)
                if case.code == "unresolved_relocation"
            }
            if result["ambiguous_mention_id"] not in cases:
                raise RuntimeError("No se creó la alerta de ubicación ambigua esperada.")
            if result["absent_mention_id"] not in cases:
                raise RuntimeError("No se creó la alerta de fragmento ausente esperada.")
    finally:
        engine.dispose()

    print(f"Proyecto descartable creado: {destination}")
    print(f"Mención ambigua: {result['ambiguous_mention_id']}")
    print(f"Mención ausente: {result['absent_mention_id']}")
    print("Alertas esperadas: 2 × unresolved_relocation")
    print("Elegí la segunda aparición para la mención ambigua.")
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
        default=Path("project_data_unresolved_mention_validation"),
    )
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    create_validation_copy(args.source, args.destination, force=args.force)


if __name__ == "__main__":
    main()
