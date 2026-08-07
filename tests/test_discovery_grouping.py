from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import func, select
from typer.testing import CliRunner

from archive_workbench.cli import app
from archive_workbench.db import create_sqlite_engine, database_path, session_scope
from archive_workbench.db.models import (
    DiscoveryCandidate,
    DiscoveryCandidateContinuity,
    DiscoveryCandidateGroup,
    DiscoveryGroupAction,
    DiscoveryGroupMembership,
    DiscoveryRun,
    EditableObject,
)
from archive_workbench.discovery_grouping import (
    create_manual_group,
    discovery_group_rows,
    project_discovery_candidate,
    rebuild_discovery_groups,
    remove_candidate_from_group,
)
from archive_workbench.discovery_review import review_discovery_candidate
from archive_workbench.open_discovery import (
    DiscoveryProfileValues,
    run_open_discovery,
    save_discovery_profile,
)
from tests.test_open_discovery import _seed_discovery_project


def _candidate(session, text: str, *, newest: bool = False) -> DiscoveryCandidate:
    query = select(DiscoveryCandidate).where(DiscoveryCandidate.exact_text == text)
    query = query.order_by(
        DiscoveryCandidate.created_at.desc() if newest else DiscoveryCandidate.created_at,
        DiscoveryCandidate.id.desc() if newest else DiscoveryCandidate.id,
    )
    row = session.scalar(query.limit(1))
    assert row is not None
    return row


def _two_runs(root: Path) -> tuple[str, str]:
    object_id = _seed_discovery_project(root)
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            profile = save_discovery_profile(
                session,
                project_id="search_project",
                values=DiscoveryProfileValues(name="Agrupamiento"),
                changed_by="tests",
            )
            first = run_open_discovery(
                session,
                project_id="search_project",
                profile=profile,
                created_by="tests",
            )
            second = run_open_discovery(
                session,
                project_id="search_project",
                profile=profile,
                created_by="tests",
            )
            return first.run_id, second.run_id
    finally:
        engine.dispose()


def test_grouping_proposes_duplicates_across_runs_and_preserves_provenance(
    tmp_path: Path,
) -> None:
    root = tmp_path / "groups"
    first_run, second_run = _two_runs(root)
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            second_person = session.scalar(
                select(DiscoveryCandidate).where(
                    DiscoveryCandidate.run_id == second_run,
                    DiscoveryCandidate.exact_text == "Dra. Valentina Orbe",
                )
            )
            assert second_person is not None
            review_discovery_candidate(
                session,
                project_id="search_project",
                candidate_id=second_person.id,
                decision_type="modify",
                reviewed_text="Dra Valentina Orbe",
                reason="Normalización controlada.",
                decided_by="tests",
            )
            summary = rebuild_discovery_groups(
                session,
                project_id="search_project",
                created_by="tests",
            )
            rows = discovery_group_rows(session, project_id="search_project")
            person = next(row for row in rows if row.normalized_label == "dra valentina orbe")
            assert summary.groups_created == 7
            assert summary.memberships_created == 14
            assert summary.duplicate_candidates == 14
            assert person.grouping_method == "normalized"
            assert person.active_member_count == 2
            assert person.run_count == 2
            assert {member.run_id for member in person.members} == {first_run, second_run}
            assert all(member.membership_status == "active" for member in person.members)
            assert session.scalar(select(func.count()).select_from(DiscoveryCandidate)) == 14
    finally:
        engine.dispose()


def test_manual_group_and_separation_keep_append_only_history(tmp_path: Path) -> None:
    root = tmp_path / "manual_group"
    _two_runs(root)
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            candidates = list(
                session.scalars(
                    select(DiscoveryCandidate)
                    .where(DiscoveryCandidate.exact_text == "operativo Horizonte")
                    .order_by(DiscoveryCandidate.created_at, DiscoveryCandidate.id)
                )
            )
            group = create_manual_group(
                session,
                project_id="search_project",
                candidate_ids=[row.id for row in candidates],
                preferred_label="Operativo Horizonte",
                semantic_family="event",
                created_by="tests",
                reason="Agrupamiento manual controlado.",
            )
            remove_candidate_from_group(
                session,
                project_id="search_project",
                group_id=group.id,
                candidate_id=candidates[1].id,
                changed_by="tests",
                reason="Separación controlada.",
            )
            rebuild_discovery_groups(
                session,
                project_id="search_project",
                created_by="tests",
            )
            memberships = list(
                session.scalars(
                    select(DiscoveryGroupMembership)
                    .where(DiscoveryGroupMembership.group_id == group.id)
                    .order_by(DiscoveryGroupMembership.added_at)
                )
            )
            actions = list(
                session.scalars(
                    select(DiscoveryGroupAction)
                    .where(DiscoveryGroupAction.group_id == group.id)
                    .order_by(DiscoveryGroupAction.created_at, DiscoveryGroupAction.id)
                )
            )
            assert [row.membership_status for row in memberships].count("active") == 1
            assert [row.membership_status for row in memberships].count("removed") == 1
            assert [row.action_type for row in actions] == [
                "group_created",
                "member_added",
                "member_added",
                "member_removed",
            ]
            assert session.get(DiscoveryCandidate, candidates[1].id) is not None
    finally:
        engine.dispose()


def test_continuity_projects_stale_candidate_and_keeps_old_candidate_visible(
    tmp_path: Path,
) -> None:
    root = tmp_path / "continuity"
    _two_runs(root)
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            rebuild_discovery_groups(
                session,
                project_id="search_project",
                created_by="tests",
            )
            source = _candidate(session, "Cuaderno del Delta")
            editable = session.get(EditableObject, source.editable_object_id)
            assert editable is not None
            editable.current_text = "Prefacio agregado. " + editable.current_text
            editable.revision_number += 1
            session.flush()
            summary = project_discovery_candidate(
                session,
                project_id="search_project",
                candidate_id=source.id,
                method="exact_projection",
                created_by="tests",
            )
            target = session.get(DiscoveryCandidate, summary.target_candidate_id)
            continuity = session.get(
                DiscoveryCandidateContinuity, summary.continuity_id
            )
            assert target is not None
            assert continuity is not None
            assert target.object_revision_number == editable.revision_number
            assert editable.current_text[target.start_offset : target.end_offset] == target.exact_text
            assert target.exact_text == "Cuaderno del Delta"
            assert session.get(DiscoveryCandidate, source.id) is source
            group_rows = discovery_group_rows(session, project_id="search_project")
            work_group = next(row for row in group_rows if row.semantic_family == "work")
            assert {member.candidate_id for member in work_group.members} >= {
                source.id,
                target.id,
            }
            assert any(member.candidate_id == source.id and member.is_stale for member in work_group.members)
            assert any(member.candidate_id == target.id and not member.is_stale for member in work_group.members)
            with pytest.raises(ValueError, match="ya fue proyectado"):
                project_discovery_candidate(
                    session,
                    project_id="search_project",
                    candidate_id=source.id,
                    method="exact_projection",
                    created_by="tests",
                )
    finally:
        engine.dispose()


def test_continuity_rejects_ambiguous_exact_projection(tmp_path: Path) -> None:
    root = tmp_path / "ambiguous"
    _seed_discovery_project(root)
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            profile = save_discovery_profile(
                session,
                project_id="search_project",
                values=DiscoveryProfileValues(name="Ambiguo"),
                changed_by="tests",
            )
            run_open_discovery(
                session,
                project_id="search_project",
                profile=profile,
                created_by="tests",
            )
            source = _candidate(session, "Cuaderno del Delta")
            editable = session.get(EditableObject, source.editable_object_id)
            assert editable is not None
            editable.current_text += " Cuaderno del Delta"
            editable.revision_number += 1
            session.flush()
            with pytest.raises(ValueError, match="varias veces"):
                project_discovery_candidate(
                    session,
                    project_id="search_project",
                    candidate_id=source.id,
                    method="exact_projection",
                    created_by="tests",
                )
            assert session.scalar(
                select(func.count()).select_from(DiscoveryCandidateContinuity)
            ) == 0
    finally:
        engine.dispose()


def test_grouping_cli_rebuilds_lists_and_projects(tmp_path: Path) -> None:
    root = tmp_path / "cli"
    _two_runs(root)
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["discovery-groups-rebuild", str(root), "--created-by", "alex"],
    )
    assert result.exit_code == 0, result.output
    assert "candidatos duplicados 14" in result.output
    result = runner.invoke(app, ["discovery-groups", str(root)])
    assert result.exit_code == 0, result.output
    assert "Total: 7 grupos" in result.output

    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            source = _candidate(session, "Cuaderno del Delta")
            editable = session.get(EditableObject, source.editable_object_id)
            assert editable is not None
            editable.current_text = "Inicio. " + editable.current_text
            editable.revision_number += 1
            candidate_id = source.id
    finally:
        engine.dispose()
    result = runner.invoke(
        app,
        [
            "discovery-candidate-project",
            str(root),
            candidate_id,
            "--method",
            "exact_projection",
            "--created-by",
            "alex",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "OK: continuidad" in result.output
    result = runner.invoke(app, ["discovery-continuities", str(root)])
    assert result.exit_code == 0, result.output
    assert "Total: 1 continuidades" in result.output


def test_grouping_ui_uses_persistent_secondary_navigation() -> None:
    source = (
        Path(__file__).parents[1] / "src/archive_workbench/discovery_app.py"
    ).read_text(encoding="utf-8")
    assert 'key="open_discovery_grouping_tasks"' in source
    assert 'key="open_discovery_manual_group_panel"' in source
    assert '"Revisar grupos"' in source
    assert '"Continuidad textual"' in source
    assert '"Actualizar grupos propuestos"' in source
    assert '"Crear grupo manual"' in source
    assert '"Separar candidato"' in source
    assert '"Crear continuidad"' in source
    assert 'with st.expander("Agrupar candidatos' not in source
    assert 'with st.expander("Continuidad' not in source


def test_disc01c_preparation_and_validation_script_preserve_disc01b_state(
    tmp_path: Path,
) -> None:
    import json

    from archive_workbench.discovery_review import review_discovery_candidate
    from scripts.prepare_open_discovery_grouping_validation import (
        prepare_grouping_validation,
    )
    from scripts.prepare_open_discovery_review_validation import prepare_review_validation
    from scripts.validate_open_discovery_disc01c import validate_grouping

    import shutil

    root = tmp_path / "disc01c_validation"
    controlled_object_id = _seed_discovery_project(root)
    (root / "validation").mkdir(parents=True, exist_ok=True)
    (root / "config").mkdir(parents=True, exist_ok=True)
    shutil.copy(
        Path(__file__).parents[1] / "config" / "decisions.yaml",
        root / "config" / "decisions.yaml",
    )
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            editable = session.get(EditableObject, controlled_object_id)
            assert editable is not None
            editable.current_text += " También hubo una manifestación."
            editable.revision_number += 1
            profile = save_discovery_profile(
                session,
                project_id="search_project",
                values=DiscoveryProfileValues(name="Validación C"),
                changed_by="tests",
            )
            run_open_discovery(
                session,
                project_id="search_project",
                profile=profile,
                created_by="tests",
            )
            expected_texts = [
                "24 de marzo de 1976",
                "Dra. Valentina Orbe",
                "ciudad de Puerto Niebla",
                "Ministerio de Archivos Imaginarios",
                "operativo Horizonte",
                "investigación documental",
                "Cuaderno del Delta",
            ]
            (root / "validation" / "disc01a.json").write_text(
                json.dumps(
                    {
                        "editable_object_id": controlled_object_id,
                        "expected_texts": expected_texts,
                    }
                ),
                encoding="utf-8",
            )
    finally:
        engine.dispose()

    validation_b = prepare_review_validation(root)
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            ids = dict(validation_b["candidate_ids_by_text"])
            review_discovery_candidate(
                session,
                project_id="search_project",
                candidate_id=ids["Ministerio de Archivos Imaginarios"],
                decision_type="accept",
                acceptance_mode="existing_authority",
                authority_id=str(validation_b["existing_authority_id"]),
                decided_by="alex",
                source="ui",
            )
            review_discovery_candidate(
                session,
                project_id="search_project",
                candidate_id=ids["Dra. Valentina Orbe"],
                decision_type="accept",
                acceptance_mode="new_authority",
                new_authority_name="Valentina Orbe",
                confirm_new_authority=True,
                reason="Validación DISC-01B autoridad nueva.",
                decided_by="alex",
                source="ui",
            )
            review_discovery_candidate(
                session,
                project_id="search_project",
                candidate_id=ids["24 de marzo de 1976"],
                decision_type="accept",
                acceptance_mode="structured_record",
                decided_by="alex",
                source="ui",
            )
            review_discovery_candidate(
                session,
                project_id="search_project",
                candidate_id=ids["operativo Horizonte"],
                decision_type="accept",
                acceptance_mode="structured_record",
                decided_by="alex",
                source="ui",
            )
            review_discovery_candidate(
                session,
                project_id="search_project",
                candidate_id=ids["investigación documental"],
                decision_type="modify",
                reviewed_text="investigación documental del operativo",
                reason="Validación DISC-01B modificación.",
                decided_by="alex",
                source="ui",
            )
            review_discovery_candidate(
                session,
                project_id="search_project",
                candidate_id=ids["investigación documental"],
                decision_type="accept",
                acceptance_mode="structured_record",
                decided_by="alex",
                source="ui",
            )
            review_discovery_candidate(
                session,
                project_id="search_project",
                candidate_id=ids["Cuaderno del Delta"],
                decision_type="defer",
                reason="Validación DISC-01B aplazamiento.",
                decided_by="alex",
                source="ui",
            )
            review_discovery_candidate(
                session,
                project_id="search_project",
                candidate_id=ids["ciudad de Puerto Niebla"],
                decision_type="reject",
                reason="Validación DISC-01B rechazo.",
                decided_by="alex",
                source="ui",
            )
            manifestation = _candidate(session, "manifestación")
            review_discovery_candidate(
                session,
                project_id="search_project",
                candidate_id=manifestation.id,
                decision_type="accept",
                acceptance_mode="structured_record",
                decided_by="alex",
                source="ui",
            )
    finally:
        engine.dispose()

    validation_c = prepare_grouping_validation(root)
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            summary = rebuild_discovery_groups(
                session,
                project_id="search_project",
                created_by="alex",
                source="ui",
            )
            assert summary.groups_created == 3
            candidate_ids = dict(validation_c["candidate_ids"])
            manual = create_manual_group(
                session,
                project_id="search_project",
                candidate_ids=[
                    candidate_ids["manual_event"],
                    str(validation_c["additional_candidate_id"]),
                ],
                preferred_label="Acontecimientos controlados",
                semantic_family="event",
                created_by="alex",
                reason="Validación DISC-01C grupo manual.",
                source="ui",
            )
            remove_candidate_from_group(
                session,
                project_id="search_project",
                group_id=manual.id,
                candidate_id=str(validation_c["additional_candidate_id"]),
                changed_by="alex",
                reason="Validación DISC-01C separación.",
                source="ui",
            )
            project_discovery_candidate(
                session,
                project_id="search_project",
                candidate_id=candidate_ids["work_duplicate"],
                method="exact_projection",
                created_by="alex",
            )
    finally:
        engine.dispose()

    result = validate_grouping(root)
    assert result["automatic_groups"] == 3
    assert result["manual_groups"] == 1
    assert result["continuities"] == 1
    assert result["canonical_counts"]["discovery_decisions"] == 9
