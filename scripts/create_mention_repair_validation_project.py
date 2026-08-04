#!/usr/bin/env python3
"""Crea una copia descartable con una mención reubicable de forma segura."""

from __future__ import annotations

import argparse
from pathlib import Path
import re
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


def _unique_fragment(text: str) -> tuple[str, int, int]:
    clean = text or ""
    if not clean.strip():
        raise RuntimeError("El proyecto de origen no tiene un objeto textual no vacío.")
    words = list(re.finditer(r"\S+", clean))
    for word_count in (8, 12, 16, 24):
        if len(words) < word_count:
            continue
        for index in range(0, len(words) - word_count + 1):
            start = words[index].start()
            end = words[index + word_count - 1].end()
            fragment = clean[start:end]
            if clean.count(fragment) == 1:
                return fragment, start, end
    if words:
        start = words[0].start()
        end = words[-1].end()
        fragment = clean[start:end]
        if clean.count(fragment) == 1:
            return fragment, start, end
    return clean, 0, len(clean)


def create_validation_copy(source: Path, destination: Path, *, force: bool) -> str:
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

            fragment, start, end = _unique_fragment(editable.current_text)
            authority = create_authority(
                session,
                project_id=digital.project_id,
                entity_type="other",
                preferred_name="Entidad de validación de reparación",
                description=(
                    "Registro descartable creado para probar la reubicación auditada "
                    "de menciones."
                ),
                created_by="archive-workbench-demo",
                review_status="reviewed",
            )
            mention = create_mention(
                session,
                object_id=editable.id,
                mention_text=fragment,
                authority_id=authority.id,
                start_offset=start,
                end_offset=end,
                status="accepted",
                source="manual",
                note="Mención anterior a la edición descartable.",
                created_by="archive-workbench-demo",
            )

            base_revision = editable.revision_number
            editable.current_text = "Prefijo descartable de validación. " + editable.current_text
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
                    "Edición descartable que desplaza una mención sin alterar "
                    "su fragmento textual."
                ),
                base_revision_number=base_revision,
            )
            mention_id = mention.id
            project_id = digital.project_id

        with session_scope(engine) as session:
            case = next(
                case
                for case in mention_repair_cases(session, project_id=project_id)
                if case.mention_id == mention_id
            )
            stored_offsets = (case.stored_start_offset, case.stored_end_offset)
            projected_offsets = (
                case.projected_start_offset,
                case.projected_end_offset,
            )
    finally:
        engine.dispose()

    print(f"Proyecto descartable creado: {destination}")
    print(f"Mención reubicable: {mention_id}")
    print(f"Clasificación: {case.code}")
    print(f"Offsets almacenados: {stored_offsets[0]}–{stored_offsets[1]}")
    print(f"Offsets proyectados: {projected_offsets[0]}–{projected_offsets[1]}")
    print("Abrí Explorar relaciones > Revisar alertas.")
    return mention_id


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
        default=Path("project_data_mention_repair_validation"),
    )
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    create_validation_copy(args.source, args.destination, force=args.force)


if __name__ == "__main__":
    main()
