#!/usr/bin/env python3
"""Crea una copia descartable con texto controlado para validar DISC-01A."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil

from sqlalchemy import delete, func, select

from archive_workbench.db import (
    create_sqlite_engine,
    current_revision,
    database_path,
    session_scope,
    upgrade_database,
)
from archive_workbench.db.models import (
    AutomaticAnalysisAuthorization,
    AuthorityRecord,
    DiscoveryCandidate,
    DiscoveryProfile,
    DiscoveryRun,
    EditableObject,
    EditablePage,
    EntityMention,
    EntityRelation,
)
from archive_workbench.decisions import load_decisions
from archive_workbench.editing import update_editable_object

CONTROLLED_TEXT = (
    "El 24 de marzo de 1976 la Dra. Valentina Orbe participó en la ciudad de "
    "Puerto Niebla junto al Ministerio de Archivos Imaginarios. Durante el "
    "operativo Horizonte comenzó la investigación documental y se presentó "
    "la obra “Cuaderno del Delta”."
)
EXPECTED_FAMILIES = [
    "actor",
    "space",
    "time",
    "event",
    "action_process",
    "work",
]
EXPECTED_TEXTS = [
    "24 de marzo de 1976",
    "Dra. Valentina Orbe",
    "ciudad de Puerto Niebla",
    "Ministerio de Archivos Imaginarios",
    "operativo Horizonte",
    "investigación documental",
    "Cuaderno del Delta",
]


def create_validation_copy(
    source: Path,
    destination: Path,
    *,
    force: bool,
) -> dict[str, object]:
    source = source.resolve()
    destination = destination.resolve()
    if not database_path(source).is_file():
        raise SystemExit(f"No se encontró una base de proyecto en: {source}")
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

    decisions = load_decisions(destination / "config" / "decisions.yaml")
    engine = create_sqlite_engine(database_path(destination))
    try:
        with session_scope(engine) as session:
            session.execute(delete(DiscoveryCandidate))
            session.execute(delete(DiscoveryRun))
            session.execute(delete(DiscoveryProfile))
            session.execute(
                delete(AutomaticAnalysisAuthorization).where(
                    AutomaticAnalysisAuthorization.analysis_kind == "open_discovery"
                )
            )

            editable = session.scalars(
                select(EditableObject)
                .where(EditableObject.lifecycle_status == "active")
                .order_by(
                    EditableObject.digital_object_id,
                    EditableObject.page_number,
                    EditableObject.current_order_index,
                    EditableObject.id,
                )
            ).first()
            if editable is None:
                raise RuntimeError("La copia no contiene objetos editables activos.")
            page = session.get(EditablePage, editable.editable_page_id)
            if page is None:
                raise RuntimeError("El objeto de validación no conserva su página editable.")

            editable = update_editable_object(
                session,
                decisions=decisions,
                object_id=editable.id,
                expected_revision=editable.revision_number,
                edited_by="validation_script",
                text=CONTROLLED_TEXT,
                note="Texto controlado para validar DISC-01A.",
            )
            editable.review_status = "approved"
            page.review_status = "approved"
            page.reviewed_by = "validation_script"
            page.review_note = "Página aprobada para validar DISC-01A."
            session.flush()

            editable = session.get(EditableObject, editable.id)
            assert editable is not None
            canonical_counts = {
                "authority_records": int(
                    session.scalar(select(func.count()).select_from(AuthorityRecord)) or 0
                ),
                "entity_mentions": int(
                    session.scalar(select(func.count()).select_from(EntityMention)) or 0
                ),
                "entity_relations": int(
                    session.scalar(select(func.count()).select_from(EntityRelation)) or 0
                ),
            }
            payload = {
                "destination": str(destination),
                "revision": current_revision(destination),
                "editable_object_id": editable.id,
                "editable_page_id": page.id,
                "page_number": editable.page_number,
                "object_revision_number": editable.revision_number,
                "controlled_text": CONTROLLED_TEXT,
                "expected_families": EXPECTED_FAMILIES,
                "expected_texts": EXPECTED_TEXTS,
                "expected_candidate_count": len(EXPECTED_TEXTS),
                "canonical_counts_before": canonical_counts,
            }
    finally:
        engine.dispose()

    validation_dir = destination / "validation"
    validation_dir.mkdir(parents=True, exist_ok=True)
    validation_path = validation_dir / "disc01a.json"
    payload["validation_path"] = str(validation_path)
    validation_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    result = create_validation_copy(
        args.source,
        args.destination,
        force=args.force,
    )
    print(f"Proyecto descartable creado: {result['destination']}")
    print(f"Revisión de base: {result['revision']}")
    print(
        "Objeto controlado: "
        f"{result['editable_object_id']} · página {result['page_number']} · "
        f"revisión {result['object_revision_number']}"
    )
    print(
        "Familias esperadas: " + ", ".join(result["expected_families"])
    )
    print(f"Candidatos controlados esperados: {result['expected_candidate_count']}")
    print("La corrida puede hallar candidatos adicionales en otros documentos aprobados.")
    print(f"Datos de validación: {result['validation_path']}")
    print("No se crearon perfiles, corridas, candidatos ni registros canónicos.")
    print("El proyecto fuente no fue modificado.")


if __name__ == "__main__":
    main()
