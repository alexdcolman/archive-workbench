#!/usr/bin/env python3
"""Valida DISC-01A sobre el objeto controlado sin suponer un corpus vacío."""

from __future__ import annotations

from collections import Counter
import argparse
import json
from pathlib import Path

from sqlalchemy import func, select, text

from archive_workbench.db import (
    create_sqlite_engine,
    current_revision,
    database_path,
    session_scope,
)
from archive_workbench.db.models import (
    AutomaticAnalysisAuthorization,
    AuthorityRecord,
    DiscoveryCandidate,
    DiscoveryProfile,
    DiscoveryRun,
    EditableObject,
    EntityMention,
    EntityRelation,
)

EXPECTED_FAMILIES = Counter(
    {
        "actor": 2,
        "space": 1,
        "time": 1,
        "event": 1,
        "action_process": 1,
        "work": 1,
    }
)


def validate_disc01a(root: Path) -> dict[str, object]:
    root = root.resolve()
    validation_path = root / "validation" / "disc01a.json"
    validation = json.loads(validation_path.read_text(encoding="utf-8"))
    engine = create_sqlite_engine(database_path(root))

    try:
        with session_scope(engine) as session:
            profiles = list(session.scalars(select(DiscoveryProfile)))
            runs = list(session.scalars(select(DiscoveryRun)))
            candidates = list(
                session.scalars(
                    select(DiscoveryCandidate).order_by(
                        DiscoveryCandidate.editable_object_id,
                        DiscoveryCandidate.start_offset,
                        DiscoveryCandidate.end_offset,
                        DiscoveryCandidate.semantic_family,
                    )
                )
            )
            controlled = [
                row
                for row in candidates
                if row.editable_object_id == validation["editable_object_id"]
            ]
            authorizations = list(
                session.scalars(
                    select(AutomaticAnalysisAuthorization).where(
                        AutomaticAnalysisAuthorization.analysis_kind
                        == "open_discovery"
                    )
                )
            )
            editable = session.get(
                EditableObject,
                validation["editable_object_id"],
            )
            assert editable is not None

            canonical_counts = {
                "authority_records": int(
                    session.scalar(select(func.count()).select_from(AuthorityRecord))
                    or 0
                ),
                "entity_mentions": int(
                    session.scalar(select(func.count()).select_from(EntityMention)) or 0
                ),
                "entity_relations": int(
                    session.scalar(select(func.count()).select_from(EntityRelation)) or 0
                ),
            }
            integrity = session.execute(text("PRAGMA integrity_check")).scalar_one()
            foreign_keys = session.execute(text("PRAGMA foreign_key_check")).all()

            assert len(profiles) == 1
            assert len(runs) == 1
            run = runs[0]
            assert run.status == "completed"
            assert run.object_count >= 1
            assert run.candidate_count == len(candidates)
            assert len(controlled) == validation["expected_candidate_count"]
            assert {row.exact_text for row in controlled} == set(
                validation["expected_texts"]
            )
            assert Counter(row.semantic_family for row in controlled) == EXPECTED_FAMILIES

            for row in controlled:
                assert (
                    editable.current_text[row.start_offset : row.end_offset]
                    == row.exact_text
                )
                assert row.object_revision_number == editable.revision_number
                assert len(row.parameters_sha256) == 64

            assert canonical_counts == validation["canonical_counts_before"]
            assert len(authorizations) == 1
            assert authorizations[0].source == "ui"
            assert authorizations[0].target_type == "discovery_profile"
            assert authorizations[0].page_review_statuses_json == ["approved"]
            assert current_revision(root) == "0040_discovery_grouping_continuity"
            assert integrity == "ok"
            assert foreign_keys == []

            return {
                "profiles": len(profiles),
                "runs": len(runs),
                "objects": run.object_count,
                "total_candidates": len(candidates),
                "controlled_candidates": len(controlled),
                "controlled_families": dict(sorted(EXPECTED_FAMILIES.items())),
                "canonical_counts": canonical_counts,
                "revision": current_revision(root),
                "integrity": integrity,
                "foreign_keys": foreign_keys,
            }
    finally:
        engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "project_root",
        nargs="?",
        type=Path,
        default=Path("project_data_open_discovery_validation"),
    )
    args = parser.parse_args()
    result = validate_disc01a(args.project_root)

    print("perfiles:", result["profiles"])
    print("corridas:", result["runs"])
    print("objetos recorridos:", result["objects"])
    print("candidatos totales:", result["total_candidates"])
    print("candidatos controlados:", result["controlled_candidates"])
    print("familias controladas:", result["controlled_families"])
    print("registros canónicos:", result["canonical_counts"])
    print("revisión:", result["revision"])
    print("integridad:", result["integrity"])
    print("claves foráneas:", result["foreign_keys"])


if __name__ == "__main__":
    main()
