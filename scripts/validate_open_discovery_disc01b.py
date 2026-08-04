#!/usr/bin/env python3
"""Valida la revisión persistente de los candidatos controlados de DISC-01B."""

from __future__ import annotations

import argparse
from collections import Counter
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
    AuthorityRecord,
    DiscoveryCandidate,
    DiscoveryContextRecord,
    DiscoveryDecision,
    DiscoveryRun,
    EntityMention,
    EntityRelation,
)

EXPECTED_DECISIONS = {
    "24 de marzo de 1976": ["accept"],
    "Dra. Valentina Orbe": ["accept"],
    "ciudad de Puerto Niebla": ["reject"],
    "Ministerio de Archivos Imaginarios": ["accept"],
    "operativo Horizonte": ["accept"],
    "investigación documental": ["modify", "accept"],
    "Cuaderno del Delta": ["defer"],
}
EXPECTED_FINAL_STATUSES = {
    "24 de marzo de 1976": "accepted",
    "Dra. Valentina Orbe": "accepted",
    "ciudad de Puerto Niebla": "rejected",
    "Ministerio de Archivos Imaginarios": "accepted",
    "operativo Horizonte": "accepted",
    "investigación documental": "accepted",
    "Cuaderno del Delta": "deferred",
}


def validate_review(root: Path) -> dict[str, object]:
    root = root.resolve()
    validation_path = root / "validation" / "disc01b.json"
    validation = json.loads(validation_path.read_text(encoding="utf-8"))
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            runs = list(session.scalars(select(DiscoveryRun)))
            assert len(runs) == 1
            run = runs[0]
            assert run.id == validation["run_id"]
            assert run.status == "completed"
            assert run.object_count == validation["run_object_count"]
            assert run.candidate_count == validation["run_candidate_count"]

            candidate_ids_by_text = dict(validation["candidate_ids_by_text"])
            controlled_ids = set(candidate_ids_by_text.values())
            candidates = {
                row.id: row
                for row in session.scalars(
                    select(DiscoveryCandidate).where(
                        DiscoveryCandidate.id.in_(controlled_ids)
                    )
                )
            }
            assert set(candidates) == controlled_ids

            decisions = list(
                session.scalars(
                    select(DiscoveryDecision)
                    .where(DiscoveryDecision.candidate_id.in_(controlled_ids))
                    .order_by(
                        DiscoveryDecision.candidate_id,
                        DiscoveryDecision.decision_number,
                    )
                )
            )
            decisions_by_candidate: dict[str, list[DiscoveryDecision]] = {}
            for row in decisions:
                decisions_by_candidate.setdefault(row.candidate_id, []).append(row)

            for text_value, expected_types in EXPECTED_DECISIONS.items():
                candidate_id = candidate_ids_by_text[text_value]
                rows = decisions_by_candidate.get(candidate_id, [])
                assert [row.decision_type for row in rows] == expected_types
                assert [row.decision_number for row in rows] == list(
                    range(1, len(rows) + 1)
                )
                assert candidates[candidate_id].status == EXPECTED_FINAL_STATUSES[text_value]
                for row in rows:
                    assert len(row.candidate_state_sha256) == 64
                    assert row.decided_by == "alex"
                    assert row.source == "ui"

            action_rows = decisions_by_candidate[
                candidate_ids_by_text["investigación documental"]
            ]
            assert action_rows[0].reviewed_text == (
                "investigación documental del operativo"
            )
            assert action_rows[1].reviewed_text == (
                "investigación documental del operativo"
            )

            ministry_rows = decisions_by_candidate[
                candidate_ids_by_text["Ministerio de Archivos Imaginarios"]
            ]
            assert ministry_rows[-1].acceptance_mode == "existing_authority"
            assert (
                ministry_rows[-1].target_authority_id
                == validation["existing_authority_id"]
            )

            person_rows = decisions_by_candidate[
                candidate_ids_by_text["Dra. Valentina Orbe"]
            ]
            person_decision = person_rows[-1]
            assert person_decision.acceptance_mode == "new_authority"
            assert person_decision.target_authority_id is not None
            created_person = session.get(
                AuthorityRecord, person_decision.target_authority_id
            )
            assert created_person is not None
            assert created_person.entity_type == "person"
            assert created_person.preferred_name == "Valentina Orbe"
            assert created_person.review_status == "unreviewed"
            assert created_person.lifecycle_status == "active"

            context_records = list(
                session.scalars(
                    select(DiscoveryContextRecord).where(
                        DiscoveryContextRecord.candidate_id.in_(controlled_ids)
                    )
                )
            )
            assert len(context_records) == 3
            assert Counter(row.semantic_family for row in context_records) == Counter(
                {"time": 1, "event": 1, "action_process": 1}
            )
            assert {
                row.candidate_id for row in context_records
            } == {
                candidate_ids_by_text["24 de marzo de 1976"],
                candidate_ids_by_text["operativo Horizonte"],
                candidate_ids_by_text["investigación documental"],
            }

            mentions = list(
                session.scalars(
                    select(EntityMention).where(
                        EntityMention.id.in_(
                            [
                                row.created_mention_id
                                for row in decisions
                                if row.created_mention_id is not None
                            ]
                        )
                    )
                )
            )
            assert len(mentions) == 2
            assert {row.authority_id for row in mentions} == {
                validation["existing_authority_id"],
                created_person.id,
            }
            assert all(row.status == "accepted" for row in mentions)

            uncontrolled_decision_rows = list(
                session.scalars(
                    select(DiscoveryDecision)
                    .where(~DiscoveryDecision.candidate_id.in_(controlled_ids))
                    .order_by(
                        DiscoveryDecision.decided_at,
                        DiscoveryDecision.id,
                    )
                )
            )
            for row in uncontrolled_decision_rows:
                assert len(row.candidate_state_sha256) == 64
                assert row.decided_by
                assert row.source

            counts = {
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
                "discovery_decisions": int(
                    session.scalar(select(func.count()).select_from(DiscoveryDecision))
                    or 0
                ),
                "discovery_context_records": int(
                    session.scalar(
                        select(func.count()).select_from(DiscoveryContextRecord)
                    )
                    or 0
                ),
            }
            baseline = dict(validation["counts_after_preparation"])
            additional_decisions = (
                counts["discovery_decisions"]
                - baseline["discovery_decisions"]
                - len(decisions)
            )
            additional_context_records = (
                counts["discovery_context_records"]
                - baseline["discovery_context_records"]
                - len(context_records)
            )
            additional_authorities = (
                counts["authority_records"]
                - baseline["authority_records"]
                - 1
            )
            additional_mentions = (
                counts["entity_mentions"]
                - baseline["entity_mentions"]
                - len(mentions)
            )
            assert additional_decisions >= 0
            assert additional_context_records >= 0
            assert additional_authorities >= 0
            assert additional_mentions >= 0
            assert counts["entity_relations"] == baseline["entity_relations"]

            integrity = session.execute(text("PRAGMA integrity_check")).scalar_one()
            foreign_keys = session.execute(text("PRAGMA foreign_key_check")).all()
            assert current_revision(root) == "0040_discovery_grouping_continuity"
            assert integrity == "ok"
            assert foreign_keys == []

            result: dict[str, object] = {
                "objects_traversed": run.object_count,
                "total_candidates": run.candidate_count,
                "controlled_candidates": len(controlled_ids),
                "controlled_decisions": len(decisions),
                "additional_decisions": additional_decisions,
                "controlled_context_records": len(context_records),
                "additional_context_records": additional_context_records,
                "controlled_mentions": len(mentions),
                "additional_mentions": additional_mentions,
                "additional_authorities": additional_authorities,
                "created_authority": created_person.preferred_name,
                "counts": counts,
                "revision": current_revision(root),
                "integrity": integrity,
                "foreign_keys": foreign_keys,
            }
    finally:
        engine.dispose()
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "project_root",
        nargs="?",
        type=Path,
        default=Path("project_data_open_discovery_validation"),
    )
    args = parser.parse_args()
    result = validate_review(args.project_root)
    print("objetos recorridos:", result["objects_traversed"])
    print("candidatos totales:", result["total_candidates"])
    print("candidatos controlados:", result["controlled_candidates"])
    print("decisiones controladas:", result["controlled_decisions"])
    print("decisiones adicionales conservadas:", result["additional_decisions"])
    print("registros propios controlados:", result["controlled_context_records"])
    print("registros propios adicionales:", result["additional_context_records"])
    print("menciones controladas:", result["controlled_mentions"])
    print("menciones adicionales:", result["additional_mentions"])
    print("autoridad nueva:", result["created_authority"])
    print("conteos finales:", result["counts"])
    print("revisión:", result["revision"])
    print("integridad:", result["integrity"])
    print("claves foráneas:", result["foreign_keys"])


if __name__ == "__main__":
    main()
