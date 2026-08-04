#!/usr/bin/env python3
"""Valida agrupamiento, separación y continuidad textual de DISC-01C."""
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
    DiscoveryCandidateContinuity,
    DiscoveryCandidateGroup,
    DiscoveryContextRecord,
    DiscoveryDecision,
    DiscoveryGroupAction,
    DiscoveryGroupMembership,
    DiscoveryRun,
    EditableObject,
    EntityMention,
    EntityRelation,
)
from archive_workbench.discovery_grouping import discovery_group_rows
from archive_workbench.discovery_review import candidate_is_stale


def _count(session, model) -> int:
    return int(session.scalar(select(func.count()).select_from(model)) or 0)


def validate_grouping(root: Path) -> dict[str, object]:
    root = root.resolve()
    validation = json.loads(
        (root / "validation" / "disc01c.json").read_text(encoding="utf-8")
    )
    ids = dict(validation["candidate_ids"])
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            groups = discovery_group_rows(
                session, project_id=validation["project_id"], include_removed=True
            )
            auto_groups = [row for row in groups if row.grouping_method != "manual"]
            manual_groups = [row for row in groups if row.grouping_method == "manual"]
            assert len(auto_groups) >= 3
            assert len(manual_groups) == 1

            def active_ids(row):
                return {
                    member.candidate_id
                    for member in row.members
                    if member.membership_status == "active"
                }

            ministry_expected = {ids["ministry_original"], ids["ministry_duplicate"]}
            person_expected = {ids["person_original"], ids["person_normalized_variant"]}
            work_expected = {ids["work_original"], ids["work_duplicate"]}
            ministry_group = next(
                row for row in auto_groups if ministry_expected <= active_ids(row)
            )
            person_group = next(
                row for row in auto_groups if person_expected <= active_ids(row)
            )
            work_group = next(
                row for row in auto_groups if work_expected <= active_ids(row)
            )
            assert ministry_group.grouping_method == "exact"
            assert person_group.grouping_method == "normalized"
            assert ministry_expected <= active_ids(ministry_group)
            assert person_expected <= active_ids(person_group)

            continuities = list(session.scalars(select(DiscoveryCandidateContinuity)))
            assert len(continuities) == 1
            continuity = continuities[0]
            controlled_work_sources = {
                ids["work_original"],
                ids["work_duplicate"],
            }
            assert continuity.source_candidate_id in controlled_work_sources
            target = session.get(DiscoveryCandidate, continuity.target_candidate_id)
            source = session.get(DiscoveryCandidate, continuity.source_candidate_id)
            assert target is not None and source is not None
            current = session.get(EditableObject, source.editable_object_id)
            assert current is not None
            assert source.exact_text == "Cuaderno del Delta"
            assert source.editable_object_id == validation["controlled_object_id"]
            assert candidate_is_stale(session, source)
            assert not candidate_is_stale(session, target)
            assert target.object_revision_number == current.revision_number
            assert current.current_text[target.start_offset:target.end_offset] == target.exact_text
            assert target.exact_text == "Cuaderno del Delta"
            active_work_ids = {
                m.candidate_id for m in work_group.members if m.membership_status == "active"
            }
            assert {ids["work_original"], ids["work_duplicate"], target.id} <= active_work_ids

            manual = manual_groups[0]
            manual_members = {m.candidate_id: m for m in manual.members}
            assert ids["manual_event"] in manual_members
            additional_id = validation.get("additional_candidate_id")
            if additional_id:
                assert additional_id in manual_members
                assert manual_members[additional_id].membership_status == "removed"
            assert manual_members[ids["manual_event"]].membership_status == "active"

            actions = list(session.scalars(select(DiscoveryGroupAction)))
            action_counts = Counter(row.action_type for row in actions)
            assert action_counts["group_created"] == 4
            assert action_counts["member_removed"] == (1 if additional_id else 0)
            assert action_counts["member_added"] >= 8

            memberships = list(session.scalars(select(DiscoveryGroupMembership)))
            candidates = list(session.scalars(select(DiscoveryCandidate)))
            runs = list(session.scalars(select(DiscoveryRun)))
            baseline = dict(validation["counts_after_preparation"])
            canonical_counts = {
                "authority_records": _count(session, AuthorityRecord),
                "entity_mentions": _count(session, EntityMention),
                "entity_relations": _count(session, EntityRelation),
                "discovery_decisions": _count(session, DiscoveryDecision),
                "discovery_context_records": _count(session, DiscoveryContextRecord),
            }
            for key in canonical_counts:
                assert canonical_counts[key] == baseline[key]
            assert len(candidates) == baseline["discovery_candidates"] + 1
            assert len(runs) == baseline["discovery_runs"] + 1
            assert len(continuities) == 1
            assert len(memberships) >= 9

            integrity = session.execute(text("PRAGMA integrity_check")).scalar_one()
            foreign_keys = session.execute(text("PRAGMA foreign_key_check")).all()
            assert current_revision(root) == "0040_discovery_grouping_continuity"
            assert integrity == "ok"
            assert foreign_keys == []

            return {
                "groups": len(groups),
                "automatic_groups": len(auto_groups),
                "manual_groups": len(manual_groups),
                "manual_group_family": manual.semantic_family,
                "additional_automatic_groups": len(auto_groups) - 3,
                "memberships": len(memberships),
                "group_actions": len(actions),
                "continuities": len(continuities),
                "continuity_source": (
                    "original"
                    if continuity.source_candidate_id == ids["work_original"]
                    else "duplicate_equivalent"
                ),
                "candidates": len(candidates),
                "runs": len(runs),
                "canonical_counts": canonical_counts,
                "stale_candidates_visible": sum(
                    candidate_is_stale(session, row) for row in candidates
                ),
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
    result = validate_grouping(args.project_root)
    print("grupos totales:", result["groups"])
    print("grupos automáticos:", result["automatic_groups"])
    print("grupos manuales:", result["manual_groups"])
    print("familia del grupo manual:", result["manual_group_family"])
    print("grupos automáticos adicionales:", result["additional_automatic_groups"])
    print("pertenencias conservadas:", result["memberships"])
    print("acciones append-only:", result["group_actions"])
    print("continuidades:", result["continuities"])
    print("origen controlado de continuidad:", result["continuity_source"])
    print("candidatos totales:", result["candidates"])
    print("corridas totales:", result["runs"])
    print("candidatos obsoletos visibles:", result["stale_candidates_visible"])
    print("conteos canónicos:", result["canonical_counts"])
    print("revisión:", result["revision"])
    print("integridad:", result["integrity"])
    print("claves foráneas:", result["foreign_keys"])


if __name__ == "__main__":
    main()
