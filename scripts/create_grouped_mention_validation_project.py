#!/usr/bin/env python3
"""Crea una copia descartable para validar reparaciones conjuntas de menciones."""

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
from archive_workbench.db.models import DigitalObject, EditableObject, EntityMention, utc_now
from archive_workbench.editing import _append_revision
from archive_workbench.identity import new_id

_GROUP_FRAGMENT = "Mencion conjunta para elegir una entre tres"
_SAFE_FRAGMENTS = (
    "Mencion segura agrupada alfa",
    "Mencion segura agrupada beta",
    "Mencion segura agrupada gamma",
)
_PREFIX = "Prefijo descartable para desplazar todas las menciones. "


def _authority(session, *, project_id: str, name: str):
    return create_authority(
        session,
        project_id=project_id,
        entity_type="other",
        preferred_name=name,
        description="Entidad descartable para validar reparaciones conjuntas.",
        created_by="archive-workbench-demo",
        review_status="reviewed",
    )


def _current_mention(
    session,
    *,
    editable: EditableObject,
    authority_id: str,
    start_offset: int,
    note: str,
) -> EntityMention:
    now = utc_now()
    mention = EntityMention(
        id=new_id(),
        editable_object_id=editable.id,
        authority_id=authority_id,
        mention_text=_GROUP_FRAGMENT,
        normalized_text=normalize_authority_text(_GROUP_FRAGMENT),
        start_offset=start_offset,
        end_offset=start_offset + len(_GROUP_FRAGMENT),
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
        note=mention.note,
    )
    return mention


def create_validation_copy(
    source: Path,
    destination: Path,
    *,
    force: bool,
) -> dict[str, object]:
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

            appended = ". ".join((_GROUP_FRAGMENT, *_SAFE_FRAGMENTS)) + "."
            original_length = len(editable.current_text)
            separator = "\n"
            base_revision = editable.revision_number
            editable.current_text += separator + appended
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
                    "Edición descartable que agrega un conjunto coincidente y tres "
                    "menciones con proyección segura."
                ),
                base_revision_number=base_revision,
            )

            cursor = original_length + len(separator)
            group_start = cursor
            cursor += len(_GROUP_FRAGMENT) + 2
            safe_starts: list[int] = []
            for fragment in _SAFE_FRAGMENTS:
                safe_starts.append(cursor)
                cursor += len(fragment) + 2

            historical_alpha_authority = _authority(
                session,
                project_id=digital.project_id,
                name="Entidad conjunta histórica alfa",
            )
            historical_beta_authority = _authority(
                session,
                project_id=digital.project_id,
                name="Entidad conjunta histórica beta",
            )
            current_gamma_authority = _authority(
                session,
                project_id=digital.project_id,
                name="Entidad conjunta vigente gamma",
            )

            historical_alpha = create_mention(
                session,
                object_id=editable.id,
                mention_text=_GROUP_FRAGMENT,
                authority_id=historical_alpha_authority.id,
                start_offset=group_start,
                end_offset=group_start + len(_GROUP_FRAGMENT),
                status="accepted",
                source="manual",
                note="Mención histórica alfa del conjunto descartable.",
                created_by="archive-workbench-demo",
            )
            historical_beta = _current_mention(
                session,
                editable=editable,
                authority_id=historical_beta_authority.id,
                start_offset=group_start,
                note="Mención histórica beta del conjunto descartable.",
            )

            safe_ids: list[str] = []
            for index, (fragment, start_offset) in enumerate(
                zip(_SAFE_FRAGMENTS, safe_starts, strict=True),
                start=1,
            ):
                authority = _authority(
                    session,
                    project_id=digital.project_id,
                    name=f"Entidad segura agrupada {index}",
                )
                mention = create_mention(
                    session,
                    object_id=editable.id,
                    mention_text=fragment,
                    authority_id=authority.id,
                    start_offset=start_offset,
                    end_offset=start_offset + len(fragment),
                    status="accepted",
                    source="manual",
                    note="Mención segura anterior al desplazamiento descartable.",
                    created_by="archive-workbench-demo",
                )
                safe_ids.append(mention.id)

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
                    "Edición descartable que desplaza todas las menciones y permite "
                    "crear una tercera mención vigente sobre el conjunto."
                ),
                base_revision_number=base_revision,
            )

            current_gamma = _current_mention(
                session,
                editable=editable,
                authority_id=current_gamma_authority.id,
                start_offset=group_start + len(_PREFIX),
                note="Mención vigente gamma creada para la validación conjunta.",
            )
            project_id = digital.project_id
            result: dict[str, object] = {
                "object_id": editable.id,
                "group_ids": (
                    historical_alpha.id,
                    historical_beta.id,
                    current_gamma.id,
                ),
                "winner_id": historical_beta.id,
                "safe_ids": tuple(safe_ids),
            }

        with session_scope(engine) as session:
            cases = mention_repair_cases(session, project_id=project_id)
            group_cases = [case for case in cases if case.code == "duplicate_group"]
            safe_cases = [
                case
                for case in cases
                if case.code == "safe_relocation"
                and case.mention_id in set(result["safe_ids"])
            ]
            if len(group_cases) != 1:
                raise RuntimeError("La copia no produjo un único conjunto de tres menciones.")
            group_case = group_cases[0]
            group_ids = {group_case.mention_id, *group_case.duplicate_mention_ids}
            if group_ids != set(result["group_ids"]):
                raise RuntimeError(
                    "El conjunto coincidente no contiene las tres menciones esperadas."
                )
            if len(safe_cases) != 3 or not all(case.can_relocate for case in safe_cases):
                raise RuntimeError("La copia no produjo tres reubicaciones seguras agrupables.")
    finally:
        engine.dispose()

    print(f"Proyecto descartable creado: {destination}")
    print("Conjunto coincidente: 3 menciones")
    print(f"Mención que debe conservarse: {result['winner_id']}")
    print("Entidad elegida: Entidad conjunta histórica beta")
    print("Reubicaciones seguras agrupables: 3")
    print("Alertas esperadas: 1 × duplicate_group + 3 × safe_relocation")
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
        default=Path("project_data_grouped_mention_validation"),
    )
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    create_validation_copy(args.source, args.destination, force=args.force)


if __name__ == "__main__":
    main()
