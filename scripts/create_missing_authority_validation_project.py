#!/usr/bin/env python3
"""Crea una copia descartable con dos menciones sin entidad vinculada."""

from __future__ import annotations

import argparse
from pathlib import Path
import shutil

from sqlalchemy import select

from archive_workbench.authorities import (
    _append_mention_revision,
    create_authority,
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
from archive_workbench.editing import _append_revision
from archive_workbench.identity import new_id

_LINK_TEXT = "Mencion descartable alfa para vincular"
_PENDING_TEXT = "Mencion descartable beta para devolver a pendiente"


def _historical_unlinked_mention(
    session,
    *,
    editable: EditableObject,
    mention_text: str,
    start_offset: int,
    status: str,
) -> EntityMention:
    now = utc_now()
    mention = EntityMention(
        id=new_id(),
        editable_object_id=editable.id,
        authority_id=None,
        mention_text=mention_text,
        normalized_text=normalize_authority_text(mention_text),
        start_offset=start_offset,
        end_offset=start_offset + len(mention_text),
        object_revision_number=editable.revision_number,
        status=status,
        source="manual",
        confidence=None,
        note="Caso histórico descartable sin entidad vinculada.",
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

            suffix = f"\n{_LINK_TEXT}. {_PENDING_TEXT}."
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
                    "decisiones sobre menciones sin entidad."
                ),
                base_revision_number=base_revision,
            )

            link_start = original_length + 1
            pending_start = link_start + len(_LINK_TEXT) + 2
            link_mention = _historical_unlinked_mention(
                session,
                editable=editable,
                mention_text=_LINK_TEXT,
                start_offset=link_start,
                status="accepted",
            )
            pending_mention = _historical_unlinked_mention(
                session,
                editable=editable,
                mention_text=_PENDING_TEXT,
                start_offset=pending_start,
                status="modified",
            )
            target = create_authority(
                session,
                project_id=digital.project_id,
                entity_type="other",
                preferred_name="Entidad de destino para reparación",
                description=(
                    "Entidad descartable para validar una vinculación histórica reparada."
                ),
                created_by="archive-workbench-demo",
                review_status="reviewed",
            )
            project_id = digital.project_id
            result = {
                "link_mention_id": link_mention.id,
                "pending_mention_id": pending_mention.id,
                "target_authority_id": target.id,
            }

        with session_scope(engine) as session:
            cases = mention_repair_cases(session, project_id=project_id)
            case_ids = {
                case.mention_id for case in cases if case.code == "missing_authority"
            }
            expected = {
                result["link_mention_id"],
                result["pending_mention_id"],
            }
            if not expected.issubset(case_ids):
                raise RuntimeError(
                    "La copia descartable no produjo las dos alertas de entidad faltante."
                )
    finally:
        engine.dispose()

    print(f"Proyecto descartable creado: {destination}")
    print(f"Mención para vincular: {result['link_mention_id']}")
    print(f"Mención para devolver a pendiente: {result['pending_mention_id']}")
    print(f"Entidad de destino: {result['target_authority_id']}")
    print("Alertas esperadas: 2 × missing_authority")
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
        default=Path("project_data_missing_authority_validation"),
    )
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    create_validation_copy(args.source, args.destination, force=args.force)


if __name__ == "__main__":
    main()
