#!/usr/bin/env python3
"""Prepara la corrida existente de DISC-01A para validar decisiones de DISC-01B."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from sqlalchemy import func, select

from archive_workbench.authorities import create_authority, normalize_authority_text
from archive_workbench.db import (
    create_sqlite_engine,
    current_revision,
    database_path,
    require_current_database,
    session_scope,
)
from archive_workbench.db.models import (
    AuthorityRecord,
    DiscoveryCandidate,
    DiscoveryContextRecord,
    DiscoveryDecision,
    DiscoveryRun,
    EntityMention,
    EntityRelation,
)

EXISTING_AUTHORITY_NAME = "Ministerio de Archivos Imaginarios"


def prepare_review_validation(root: Path) -> dict[str, object]:
    root = root.resolve()
    require_current_database(root)
    disc01a_path = root / "validation" / "disc01a.json"
    validation_a = json.loads(disc01a_path.read_text(encoding="utf-8"))
    expected_texts = list(validation_a["expected_texts"])
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            runs = list(session.scalars(select(DiscoveryRun)))
            if len(runs) != 1 or runs[0].status != "completed":
                raise RuntimeError("La copia debe conservar una única corrida completada de DISC-01A.")
            controlled = list(
                session.scalars(
                    select(DiscoveryCandidate).where(
                        DiscoveryCandidate.editable_object_id
                        == validation_a["editable_object_id"]
                    )
                )
            )
            by_text = {row.exact_text: row for row in controlled}
            missing = sorted(set(expected_texts) - set(by_text))
            if missing:
                raise RuntimeError(
                    "Faltan candidatos controlados de DISC-01A: " + ", ".join(missing)
                )
            controlled_ids = [by_text[text].id for text in expected_texts]
            decisions = int(
                session.scalar(
                    select(func.count())
                    .select_from(DiscoveryDecision)
                    .where(DiscoveryDecision.candidate_id.in_(controlled_ids))
                )
                or 0
            )
            if decisions:
                raise RuntimeError(
                    "La copia ya contiene decisiones sobre los candidatos controlados; "
                    "no se volvió a preparar."
                )

            normalized = normalize_authority_text(EXISTING_AUTHORITY_NAME)
            authority = session.scalar(
                select(AuthorityRecord).where(
                    AuthorityRecord.project_id == runs[0].project_id,
                    AuthorityRecord.normalized_name == normalized,
                    AuthorityRecord.lifecycle_status == "active",
                )
            )
            if authority is None:
                authority = create_authority(
                    session,
                    project_id=runs[0].project_id,
                    entity_type="organization",
                    preferred_name=EXISTING_AUTHORITY_NAME,
                    description="Autoridad controlada para validar el vínculo explícito de DISC-01B.",
                    review_status="approved",
                    created_by="validation_script",
                    note="Preparación descartable de DISC-01B después de la detección.",
                )

            counts = {
                "authority_records": int(
                    session.scalar(select(func.count()).select_from(AuthorityRecord)) or 0
                ),
                "entity_mentions": int(
                    session.scalar(select(func.count()).select_from(EntityMention)) or 0
                ),
                "entity_relations": int(
                    session.scalar(select(func.count()).select_from(EntityRelation)) or 0
                ),
                "discovery_decisions": int(
                    session.scalar(select(func.count()).select_from(DiscoveryDecision)) or 0
                ),
                "discovery_context_records": int(
                    session.scalar(select(func.count()).select_from(DiscoveryContextRecord)) or 0
                ),
            }
            payload = {
                "project_root": str(root),
                "revision": current_revision(root),
                "run_id": runs[0].id,
                "project_id": runs[0].project_id,
                "run_object_count": runs[0].object_count,
                "run_candidate_count": runs[0].candidate_count,
                "controlled_object_id": validation_a["editable_object_id"],
                "candidate_ids_by_text": {
                    text: by_text[text].id for text in expected_texts
                },
                "existing_authority_id": authority.id,
                "existing_authority_name": authority.preferred_name,
                "counts_after_preparation": counts,
            }
    finally:
        engine.dispose()

    output = root / "validation" / "disc01b.json"
    payload["validation_path"] = str(output)
    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "project_root",
        nargs="?",
        type=Path,
        default=Path("project_data_open_discovery_validation"),
    )
    args = parser.parse_args()
    result = prepare_review_validation(args.project_root)
    print("Copia preparada:", result["project_root"])
    print("Revisión:", result["revision"])
    print("Corrida conservada:", result["run_id"])
    print("Objetos recorridos conservados:", result["run_object_count"])
    print("Candidatos totales conservados:", result["run_candidate_count"])
    print(
        "Autoridad existente controlada:",
        result["existing_authority_name"],
        "|",
        result["existing_authority_id"],
    )
    print("Candidatos controlados:", len(result["candidate_ids_by_text"]))
    print("Datos de validación:", result["validation_path"])
    print("No se volvió a ejecutar el descubrimiento y no se creó ninguna decisión.")


if __name__ == "__main__":
    main()
