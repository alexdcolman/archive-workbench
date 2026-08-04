#!/usr/bin/env python3
"""Crea una copia descartable con dos pares de menciones duplicadas."""

from __future__ import annotations

import argparse
from pathlib import Path
import shutil

from sqlalchemy import select

from archive_workbench.authorities import (
    _append_mention_revision,
    create_authority,
    create_mention,
    mention_repair_cases,
    normalize_authority_text,
)
from archive_workbench.db import create_sqlite_engine, database_path, session_scope
from archive_workbench.db.models import (
    DigitalObject,
    EditableObject,
    EntityMention,
    utc_now,
)
from archive_workbench.identity import new_id
from archive_workbench.editing import _append_revision

_ALPHA = "Mencion duplicada alfa para conservar la vigente"
_BETA = "Mencion duplicada beta para conservar la historica"
_PREFIX = "Prefijo descartable para desplazar menciones. "


def _authority(session, *, project_id: str, name: str):
    return create_authority(
        session,
        project_id=project_id,
        entity_type="other",
        preferred_name=name,
        description="Entidad descartable para validar una decisión sobre duplicados.",
        created_by="archive-workbench-demo",
        review_status="reviewed",
    )


def _current_duplicate(
    session,
    *,
    editable: EditableObject,
    authority_id: str,
    mention_text: str,
    start_offset: int,
    note: str,
) -> EntityMention:
    """Inserta corrupción histórica deliberada solo dentro de la copia descartable."""
    now = utc_now()
    mention = EntityMention(
        id=new_id(),
        editable_object_id=editable.id,
        authority_id=authority_id,
        mention_text=mention_text,
        normalized_text=normalize_authority_text(mention_text),
        start_offset=start_offset,
        end_offset=start_offset + len(mention_text),
        object_revision_number=editable.revision_number,
        status="accepted",
        source="manual",
        confidence=None,
        note=note,
        created_by="archive-workbench-demo",
        created_at=now,
        updated_by="archive-workbench-demo",
        updated_at=now,
        revision=1,
    )
    session.add(mention)
    session.flush()
    _append_mention_revision(
        session,
        mention,
        operation="create",
        changed_by="archive-workbench-demo",
        note=note,
    )
    return mention


def create_validation_copy(source: Path, destination: Path, *, force: bool) -> dict[str, str]:
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

            suffix = f"\n{_ALPHA}. {_BETA}."
            base_revision = editable.revision_number
            original_length = len(editable.current_text)
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
                    "Edición descartable que agrega dos frases completas para validar "
                    "decisiones sobre menciones duplicadas."
                ),
                base_revision_number=base_revision,
            )

            alpha_start = original_length + 1
            beta_start = alpha_start + len(_ALPHA) + 2
            alpha_historical_authority = _authority(
                session,
                project_id=digital.project_id,
                name="Entidad histórica alfa",
            )
            alpha_current_authority = _authority(
                session,
                project_id=digital.project_id,
                name="Entidad vigente alfa",
            )
            beta_historical_authority = _authority(
                session,
                project_id=digital.project_id,
                name="Entidad histórica beta",
            )
            beta_current_authority = _authority(
                session,
                project_id=digital.project_id,
                name="Entidad vigente beta",
            )

            alpha_historical = create_mention(
                session,
                object_id=editable.id,
                mention_text=_ALPHA,
                authority_id=alpha_historical_authority.id,
                start_offset=alpha_start,
                end_offset=alpha_start + len(_ALPHA),
                status="accepted",
                source="manual",
                note="Mención histórica alfa anterior al desplazamiento descartable.",
                created_by="archive-workbench-demo",
            )
            beta_historical = create_mention(
                session,
                object_id=editable.id,
                mention_text=_BETA,
                authority_id=beta_historical_authority.id,
                start_offset=beta_start,
                end_offset=beta_start + len(_BETA),
                status="accepted",
                source="manual",
                note="Mención histórica beta anterior al desplazamiento descartable.",
                created_by="archive-workbench-demo",
            )

            base_revision = editable.revision_number
            editable.current_text = _PREFIX + editable.current_text
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
                    "Edición descartable que desplaza las menciones históricas y permite "
                    "crear dos menciones vigentes coincidentes."
                ),
                base_revision_number=base_revision,
            )

            alpha_current_start = alpha_start + len(_PREFIX)
            beta_current_start = beta_start + len(_PREFIX)
            alpha_current = _current_duplicate(
                session,
                editable=editable,
                authority_id=alpha_current_authority.id,
                mention_text=_ALPHA,
                start_offset=alpha_current_start,
                note="Mención vigente alfa creada para la validación descartable.",
            )
            beta_current = _current_duplicate(
                session,
                editable=editable,
                authority_id=beta_current_authority.id,
                mention_text=_BETA,
                start_offset=beta_current_start,
                note="Mención vigente beta creada para la validación descartable.",
            )

            project_id = digital.project_id
            result = {
                "alpha_historical_id": alpha_historical.id,
                "alpha_current_id": alpha_current.id,
                "beta_historical_id": beta_historical.id,
                "beta_current_id": beta_current.id,
            }

        with session_scope(engine) as session:
            cases = {
                case.mention_id: case
                for case in mention_repair_cases(session, project_id=project_id)
                if case.code == "duplicate_relocation"
            }
            for historical_key, current_key in (
                ("alpha_historical_id", "alpha_current_id"),
                ("beta_historical_id", "beta_current_id"),
            ):
                case = cases.get(result[historical_key])
                if case is None or case.duplicate_mention_ids != (result[current_key],):
                    raise RuntimeError(
                        "La copia descartable no produjo los dos pares de duplicados esperados."
                    )
    finally:
        engine.dispose()

    print(f"Proyecto descartable creado: {destination}")
    print(f"Alfa histórica: {result['alpha_historical_id']}")
    print(f"Alfa vigente: {result['alpha_current_id']}")
    print(f"Beta histórica: {result['beta_historical_id']}")
    print(f"Beta vigente: {result['beta_current_id']}")
    print("Alertas esperadas: 2 × duplicate_relocation")
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
        default=Path("project_data_duplicate_mention_validation"),
    )
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    create_validation_copy(args.source, args.destination, force=args.force)


if __name__ == "__main__":
    main()
