from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import func, select
from typer.testing import CliRunner

from archive_workbench.cli import app
from archive_workbench.db import create_sqlite_engine, database_path, session_scope
from archive_workbench.db.models import (
    AuthorityRecord,
    DiscoveryCandidate,
    DiscoveryProfile,
    DiscoveryRun,
    EditableObject,
    EditablePage,
    EntityMention,
    EntityRelation,
)
from archive_workbench.open_discovery import (
    DiscoveryProfileValues,
    discovery_audit_payload,
    discovery_candidate_rows,
    run_open_discovery,
    save_discovery_profile,
)
from tests.test_search import _seed_search_project

_SAMPLE = (
    "El 24 de marzo de 1976 la Dra. Valentina Orbe participó en la ciudad de "
    "Puerto Niebla junto al Ministerio de Archivos Imaginarios. Durante el "
    "operativo Horizonte comenzó la investigación documental y se presentó "
    "la obra “Cuaderno del Delta”."
)


def _seed_discovery_project(root: Path) -> str:
    object_id, _page_id = _seed_search_project(root)
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            editable = session.get(EditableObject, object_id)
            assert editable is not None
            editable.current_text = _SAMPLE
            editable.revision_number = 2
            editable.review_status = "approved"
            page = session.get(EditablePage, editable.editable_page_id)
            assert page is not None
            page.review_status = "approved"
            session.flush()
    finally:
        engine.dispose()
    return object_id


def test_discovery_persists_reproducible_candidates_without_canonical_writes(
    tmp_path: Path,
) -> None:
    root = tmp_path / "discovery"
    object_id = _seed_discovery_project(root)
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            before = {
                "authorities": session.scalar(select(func.count()).select_from(AuthorityRecord)),
                "mentions": session.scalar(select(func.count()).select_from(EntityMention)),
                "relations": session.scalar(select(func.count()).select_from(EntityRelation)),
            }
            profile = save_discovery_profile(
                session,
                project_id="search_project",
                values=DiscoveryProfileValues(name="Perfil DISC-01A"),
                changed_by="tests",
                quality_scope_source="api",
            )
            summary = run_open_discovery(
                session,
                project_id="search_project",
                profile=profile,
                created_by="tests",
            )
            rows = discovery_candidate_rows(
                session,
                project_id="search_project",
                run_id=summary.run_id,
            )
            after = {
                "authorities": session.scalar(select(func.count()).select_from(AuthorityRecord)),
                "mentions": session.scalar(select(func.count()).select_from(EntityMention)),
                "relations": session.scalar(select(func.count()).select_from(EntityRelation)),
            }

            assert summary.object_count == 1
            assert summary.candidate_count == 7
            assert summary.family_counts == {
                "action_process": 1,
                "actor": 2,
                "event": 1,
                "space": 1,
                "time": 1,
                "work": 1,
            }
            assert before == after == {
                "authorities": 0,
                "mentions": 0,
                "relations": 0,
            }
            assert {row.semantic_family for row in rows} == {
                "actor",
                "space",
                "time",
                "event",
                "action_process",
                "work",
            }
            for row in rows:
                assert row.editable_object_id == object_id
                assert _SAMPLE[row.start_offset : row.end_offset] == row.exact_text
                assert row.object_revision_number == 2
                assert row.page_revision_number == 1
                assert row.provider_key == "local_deterministic"
                assert row.provider_version == "local_rules_v1"
                assert row.method == "conservative_regex_rules"
                assert len(row.parameters_sha256) == 64
                assert not row.is_stale
    finally:
        engine.dispose()


def test_discovery_rejects_unconfirmed_scope_and_changed_profile_authorization(
    tmp_path: Path,
) -> None:
    root = tmp_path / "discovery_quality"
    _seed_discovery_project(root)
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            with pytest.raises(ValueError, match="confirmá explícitamente"):
                save_discovery_profile(
                    session,
                    project_id="search_project",
                    values=DiscoveryProfileValues(
                        name="Ampliado",
                        include_page_review_statuses=("reviewed", "approved"),
                    ),
                    changed_by="tests",
                )
            profile = save_discovery_profile(
                session,
                project_id="search_project",
                values=DiscoveryProfileValues(name="Autorizado"),
                changed_by="tests",
            )
            profile.minimum_confidence = 0.8
            session.flush()
            with pytest.raises(ValueError, match="No existe una autorización vigente"):
                run_open_discovery(
                    session,
                    project_id="search_project",
                    profile=profile,
                    created_by="tests",
                )
            assert session.scalar(select(func.count()).select_from(DiscoveryRun)) == 0
            assert session.scalar(select(func.count()).select_from(DiscoveryCandidate)) == 0
    finally:
        engine.dispose()


def test_discovery_uses_approved_pages_and_marks_candidate_stale(tmp_path: Path) -> None:
    root = tmp_path / "discovery_stale"
    object_id = _seed_discovery_project(root)
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            editable = session.get(EditableObject, object_id)
            assert editable is not None
            page = session.get(EditablePage, editable.editable_page_id)
            assert page is not None
            page.review_status = "reviewed"
            profile = save_discovery_profile(
                session,
                project_id="search_project",
                values=DiscoveryProfileValues(name="Solo aprobadas"),
                changed_by="tests",
            )
            empty = run_open_discovery(
                session,
                project_id="search_project",
                profile=profile,
                created_by="tests",
            )
            assert empty.object_count == 0
            assert empty.candidate_count == 0

            page.review_status = "approved"
            completed = run_open_discovery(
                session,
                project_id="search_project",
                profile=profile,
                created_by="tests",
            )
            editable.current_text = "Texto sustituido después de la corrida."
            editable.revision_number += 1
            session.flush()
            rows = discovery_candidate_rows(
                session,
                project_id="search_project",
                run_id=completed.run_id,
            )
            assert rows
            assert all(row.is_stale for row in rows)
    finally:
        engine.dispose()


def test_discovery_skips_registered_authority_surface(tmp_path: Path) -> None:
    root = tmp_path / "discovery_known"
    _seed_discovery_project(root)
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            session.add(
                AuthorityRecord(
                    id="known-authority",
                    project_id="search_project",
                    entity_type="organization",
                    preferred_name="Ministerio de Archivos Imaginarios",
                    normalized_name="ministerio de archivos imaginarios",
                    description=None,
                    lifecycle_status="active",
                    review_status="approved",
                    created_by="tests",
                    updated_by="tests",
                )
            )
            profile = save_discovery_profile(
                session,
                project_id="search_project",
                values=DiscoveryProfileValues(name="Sin conocidos"),
                changed_by="tests",
            )
            summary = run_open_discovery(
                session,
                project_id="search_project",
                profile=profile,
                created_by="tests",
            )
            rows = discovery_candidate_rows(
                session,
                project_id="search_project",
                run_id=summary.run_id,
            )
            assert "Ministerio de Archivos Imaginarios" not in {
                row.exact_text for row in rows
            }
            assert summary.candidate_count == 6
    finally:
        engine.dispose()


def test_discovery_skips_non_rejected_mentions_without_lifecycle_field(
    tmp_path: Path,
) -> None:
    root = tmp_path / "discovery_mentions"
    object_id = _seed_discovery_project(root)
    accepted_text = "Dra. Valentina Orbe"
    accepted_start = _SAMPLE.index(accepted_text)
    rejected_text = "ciudad de Puerto Niebla"
    rejected_start = _SAMPLE.index(rejected_text)
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            session.add_all(
                [
                    EntityMention(
                        id="accepted-existing-mention",
                        editable_object_id=object_id,
                        authority_id=None,
                        mention_text=accepted_text,
                        normalized_text="dra valentina orbe",
                        start_offset=accepted_start,
                        end_offset=accepted_start + len(accepted_text),
                        object_revision_number=2,
                        status="accepted",
                        source="manual",
                        confidence=None,
                        note=None,
                        created_by="tests",
                        updated_by="tests",
                    ),
                    EntityMention(
                        id="rejected-existing-mention",
                        editable_object_id=object_id,
                        authority_id=None,
                        mention_text=rejected_text,
                        normalized_text="ciudad de puerto niebla",
                        start_offset=rejected_start,
                        end_offset=rejected_start + len(rejected_text),
                        object_revision_number=2,
                        status="rejected",
                        source="manual",
                        confidence=None,
                        note=None,
                        created_by="tests",
                        updated_by="tests",
                    ),
                    EntityMention(
                        id="mention-without-offsets",
                        editable_object_id=object_id,
                        authority_id=None,
                        mention_text="Referencia sin offsets",
                        normalized_text="referencia sin offsets",
                        start_offset=None,
                        end_offset=None,
                        object_revision_number=2,
                        status="pending",
                        source="manual",
                        confidence=None,
                        note=None,
                        created_by="tests",
                        updated_by="tests",
                    ),
                ]
            )
            profile = save_discovery_profile(
                session,
                project_id="search_project",
                values=DiscoveryProfileValues(name="Menciones existentes"),
                changed_by="tests",
            )
            summary = run_open_discovery(
                session,
                project_id="search_project",
                profile=profile,
                created_by="tests",
            )
            rows = discovery_candidate_rows(
                session,
                project_id="search_project",
                run_id=summary.run_id,
            )

            texts = {row.exact_text for row in rows}
            assert accepted_text not in texts
            assert rejected_text in texts
            assert summary.candidate_count == 6
    finally:
        engine.dispose()


def test_discovery_audit_and_cli_expose_traceability(tmp_path: Path) -> None:
    root = tmp_path / "discovery_cli"
    _seed_discovery_project(root)
    runner = CliRunner()
    profile_result = runner.invoke(
        app,
        [
            "discovery-profile-save",
            str(root),
            "--name",
            "Perfil terminal",
            "--changed-by",
            "alex",
        ],
    )
    assert profile_result.exit_code == 0, profile_result.output
    assert "autoriz" not in profile_result.output.lower() or "OK" in profile_result.output

    run_result = runner.invoke(
        app,
        ["discovery-run", str(root), "Perfil terminal", "--created-by", "alex"],
    )
    assert run_result.exit_code == 0, run_result.output
    assert "candidatos 7" in run_result.output

    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            run_id = session.scalar(select(DiscoveryRun.id))
            assert run_id
            payload = discovery_audit_payload(
                session, project_id="search_project", run_id=run_id
            )
            assert payload["run"]["authorization_id"]
            assert payload["run"]["candidate_count"] == 7
            assert len(payload["candidates"]) == 7
    finally:
        engine.dispose()

    candidate_result = runner.invoke(
        app,
        ["discovery-candidates", str(root), "--run-id", run_id],
    )
    assert candidate_result.exit_code == 0, candidate_result.output
    assert "Dra. Valentina Orbe" in candidate_result.output
    assert "offsets=" in candidate_result.output
    assert "parámetros=" in candidate_result.output

    audit_path = tmp_path / "audit.json"
    audit_result = runner.invoke(
        app,
        ["discovery-audit", str(root), run_id, "--output", str(audit_path)],
    )
    assert audit_result.exit_code == 0, audit_result.output
    data = json.loads(audit_path.read_text(encoding="utf-8"))
    assert data["run"]["id"] == run_id
    assert data["candidates"][0]["parameters_sha256"]


def test_discovery_ui_keeps_profile_and_detection_controls_explicit() -> None:
    root = Path(__file__).parents[1]
    source = (root / "src/archive_workbench/discovery_app.py").read_text(
        encoding="utf-8"
    )
    assert "Propone actores, espacios, tiempos" in source
    assert "Guardar perfil de descubrimiento" in source
    assert "Ejecutar descubrimiento abierto" in source
    assert "Trazabilidad técnica" in source
    assert "nunca crean relaciones automáticamente" in source
    assert "disabled=" not in source[
        source.index('"Guardar perfil de descubrimiento"') :
        source.index('"Ejecutar descubrimiento abierto"')
    ]


def test_open_discovery_validation_script_prepares_disposable_copy(
    tmp_path: Path,
) -> None:
    import shutil

    from scripts.create_open_discovery_validation_project import create_validation_copy

    source = tmp_path / "source"
    destination = tmp_path / "destination"
    object_id = _seed_discovery_project(source)
    (source / "config").mkdir(parents=True, exist_ok=True)
    shutil.copy(
        Path(__file__).parents[1] / "config" / "decisions.yaml",
        source / "config" / "decisions.yaml",
    )

    source_engine = create_sqlite_engine(database_path(source))
    try:
        with session_scope(source_engine) as session:
            original_text = session.get(EditableObject, object_id).current_text
    finally:
        source_engine.dispose()

    result = create_validation_copy(source, destination, force=False)
    assert result["revision"] == "0040_discovery_grouping_continuity"
    assert result["expected_candidate_count"] == 7
    assert Path(result["validation_path"]).is_file()

    source_engine = create_sqlite_engine(database_path(source))
    destination_engine = create_sqlite_engine(database_path(destination))
    try:
        with session_scope(source_engine) as session:
            assert session.get(EditableObject, object_id).current_text == original_text
        with session_scope(destination_engine) as session:
            controlled = session.get(EditableObject, result["editable_object_id"])
            assert controlled is not None
            assert controlled.current_text == _SAMPLE
            assert controlled.review_status == "approved"
            assert session.scalar(select(func.count()).select_from(DiscoveryProfile)) == 0
            assert session.scalar(select(func.count()).select_from(DiscoveryRun)) == 0
            assert session.scalar(select(func.count()).select_from(DiscoveryCandidate)) == 0
    finally:
        source_engine.dispose()
        destination_engine.dispose()


def _candidate_by_text(session, text: str) -> DiscoveryCandidate:
    row = session.scalar(
        select(DiscoveryCandidate).where(DiscoveryCandidate.exact_text == text)
    )
    assert row is not None
    return row


def test_discovery_review_persists_append_only_family_specific_decisions(
    tmp_path: Path,
) -> None:
    from archive_workbench.authorities import create_authority
    from archive_workbench.db.models import DiscoveryContextRecord, DiscoveryDecision
    from archive_workbench.discovery_review import (
        discovery_decision_rows,
        review_discovery_candidate,
    )

    root = tmp_path / "discovery_review"
    _seed_discovery_project(root)
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            profile = save_discovery_profile(
                session,
                project_id="search_project",
                values=DiscoveryProfileValues(name="Revisión DISC-01B"),
                changed_by="tests",
            )
            run_open_discovery(
                session,
                project_id="search_project",
                profile=profile,
                created_by="tests",
            )
            existing = create_authority(
                session,
                project_id="search_project",
                entity_type="organization",
                preferred_name="Ministerio de Archivos Imaginarios",
                review_status="approved",
                created_by="tests",
            )

            ministry = _candidate_by_text(session, "Ministerio de Archivos Imaginarios")
            review_discovery_candidate(
                session,
                project_id="search_project",
                candidate_id=ministry.id,
                decision_type="accept",
                acceptance_mode="existing_authority",
                authority_id=existing.id,
                decided_by="alex",
                source="ui",
            )

            person = _candidate_by_text(session, "Dra. Valentina Orbe")
            person_summary = review_discovery_candidate(
                session,
                project_id="search_project",
                candidate_id=person.id,
                decision_type="accept",
                acceptance_mode="new_authority",
                new_authority_name="Valentina Orbe",
                confirm_new_authority=True,
                reason="Validación de autoridad nueva.",
                decided_by="alex",
                source="ui",
            )
            created_person = session.get(AuthorityRecord, person_summary.target_authority_id)
            assert created_person is not None
            assert created_person.entity_type == "person"
            assert created_person.review_status == "unreviewed"

            time_candidate = _candidate_by_text(session, "24 de marzo de 1976")
            review_discovery_candidate(
                session,
                project_id="search_project",
                candidate_id=time_candidate.id,
                decision_type="accept",
                acceptance_mode="structured_record",
                decided_by="alex",
                description="Fecha conservada como dato propio.",
                source="ui",
            )

            event = _candidate_by_text(session, "operativo Horizonte")
            review_discovery_candidate(
                session,
                project_id="search_project",
                candidate_id=event.id,
                decision_type="accept",
                acceptance_mode="structured_record",
                decided_by="alex",
                description="Acontecimiento controlado.",
                source="ui",
            )

            action = _candidate_by_text(session, "investigación documental")
            review_discovery_candidate(
                session,
                project_id="search_project",
                candidate_id=action.id,
                decision_type="modify",
                reviewed_text="investigación documental del operativo",
                reason="Precisión analítica.",
                decided_by="alex",
                source="ui",
            )
            action_summary = review_discovery_candidate(
                session,
                project_id="search_project",
                candidate_id=action.id,
                decision_type="accept",
                acceptance_mode="structured_record",
                description="Proceso aceptado después de modificar la etiqueta.",
                decided_by="alex",
                source="ui",
            )
            assert action_summary.decision_number == 2
            assert action_summary.reviewed_text == "investigación documental del operativo"

            work = _candidate_by_text(session, "Cuaderno del Delta")
            review_discovery_candidate(
                session,
                project_id="search_project",
                candidate_id=work.id,
                decision_type="defer",
                reason="Requiere comprobar si es un título formal.",
                decided_by="alex",
                source="ui",
            )
            space = _candidate_by_text(session, "ciudad de Puerto Niebla")
            review_discovery_candidate(
                session,
                project_id="search_project",
                candidate_id=space.id,
                decision_type="reject",
                reason="Topónimo ficticio usado para la validación.",
                decided_by="alex",
                source="ui",
            )

            decisions = list(session.scalars(select(DiscoveryDecision)))
            records = list(session.scalars(select(DiscoveryContextRecord)))
            mentions = list(session.scalars(select(EntityMention)))
            relations = list(session.scalars(select(EntityRelation)))
            authorities = list(session.scalars(select(AuthorityRecord)))

            assert len(decisions) == 8
            assert len(records) == 3
            assert {row.semantic_family for row in records} == {
                "time",
                "event",
                "action_process",
            }
            assert len(mentions) == 2
            assert {row.authority_id for row in mentions} == {
                existing.id,
                created_person.id,
            }
            assert len(authorities) == 2
            assert relations == []
            assert _candidate_by_text(session, "Cuaderno del Delta").status == "deferred"
            assert _candidate_by_text(session, "ciudad de Puerto Niebla").status == "rejected"
            assert _candidate_by_text(session, "investigación documental").status == "accepted"
            rows = discovery_decision_rows(
                session,
                project_id="search_project",
                candidate_id=action.id,
            )
            assert [row.decision_number for row in reversed(rows)] == [1, 2]
    finally:
        engine.dispose()


def test_discovery_review_blocks_stale_candidate_without_writes(tmp_path: Path) -> None:
    from archive_workbench.db.models import DiscoveryContextRecord, DiscoveryDecision
    from archive_workbench.discovery_review import review_discovery_candidate

    root = tmp_path / "discovery_review_stale"
    object_id = _seed_discovery_project(root)
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            profile = save_discovery_profile(
                session,
                project_id="search_project",
                values=DiscoveryProfileValues(name="Obsoleto"),
                changed_by="tests",
            )
            run_open_discovery(
                session,
                project_id="search_project",
                profile=profile,
                created_by="tests",
            )
            candidate = _candidate_by_text(session, "Dra. Valentina Orbe")
            editable = session.get(EditableObject, object_id)
            assert editable is not None
            editable.current_text += " Cambio posterior."
            editable.revision_number += 1
            session.flush()
            with pytest.raises(ValueError, match="obsoleto"):
                review_discovery_candidate(
                    session,
                    project_id="search_project",
                    candidate_id=candidate.id,
                    decision_type="reject",
                    reason="No debe escribirse.",
                    decided_by="alex",
                )
            assert session.scalar(select(func.count()).select_from(DiscoveryDecision)) == 0
            assert session.scalar(select(func.count()).select_from(DiscoveryContextRecord)) == 0
            assert session.scalar(select(func.count()).select_from(EntityMention)) == 0
            assert session.scalar(select(func.count()).select_from(AuthorityRecord)) == 0
    finally:
        engine.dispose()


def test_discovery_review_validates_destinations_reasons_and_terminal_state(
    tmp_path: Path,
) -> None:
    from archive_workbench.authorities import create_authority
    from archive_workbench.discovery_review import review_discovery_candidate

    root = tmp_path / "discovery_review_validation"
    _seed_discovery_project(root)
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            profile = save_discovery_profile(
                session,
                project_id="search_project",
                values=DiscoveryProfileValues(name="Validaciones"),
                changed_by="tests",
            )
            run_open_discovery(
                session,
                project_id="search_project",
                profile=profile,
                created_by="tests",
            )
            place = create_authority(
                session,
                project_id="search_project",
                entity_type="place",
                preferred_name="Lugar incompatible",
                created_by="tests",
            )
            actor = _candidate_by_text(session, "Dra. Valentina Orbe")
            with pytest.raises(ValueError, match="no es compatible"):
                review_discovery_candidate(
                    session,
                    project_id="search_project",
                    candidate_id=actor.id,
                    decision_type="accept",
                    acceptance_mode="existing_authority",
                    authority_id=place.id,
                    decided_by="alex",
                )
            with pytest.raises(ValueError, match="Confirmá explícitamente"):
                review_discovery_candidate(
                    session,
                    project_id="search_project",
                    candidate_id=actor.id,
                    decision_type="accept",
                    acceptance_mode="new_authority",
                    reason="Intento controlado.",
                    decided_by="alex",
                )
            with pytest.raises(ValueError, match="requiere un fundamento"):
                review_discovery_candidate(
                    session,
                    project_id="search_project",
                    candidate_id=actor.id,
                    decision_type="reject",
                    decided_by="alex",
                )
            with pytest.raises(ValueError, match="debe cambiar"):
                review_discovery_candidate(
                    session,
                    project_id="search_project",
                    candidate_id=actor.id,
                    decision_type="modify",
                    reason="Sin cambios.",
                    decided_by="alex",
                )
            review_discovery_candidate(
                session,
                project_id="search_project",
                candidate_id=actor.id,
                decision_type="defer",
                reason="Pendiente.",
                decided_by="alex",
            )
            review_discovery_candidate(
                session,
                project_id="search_project",
                candidate_id=actor.id,
                decision_type="reject",
                reason="Cierre posterior.",
                decided_by="alex",
            )
            with pytest.raises(ValueError, match="decisión terminal"):
                review_discovery_candidate(
                    session,
                    project_id="search_project",
                    candidate_id=actor.id,
                    decision_type="defer",
                    reason="No permitido.",
                    decided_by="alex",
                )
    finally:
        engine.dispose()


def test_discovery_review_cli_registers_and_lists_decision(tmp_path: Path) -> None:
    root = tmp_path / "discovery_review_cli"
    _seed_discovery_project(root)
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "discovery-profile-save",
            str(root),
            "--name",
            "Perfil CLI B",
            "--changed-by",
            "alex",
        ],
    )
    assert result.exit_code == 0, result.output
    result = runner.invoke(
        app,
        ["discovery-run", str(root), "Perfil CLI B", "--created-by", "alex"],
    )
    assert result.exit_code == 0, result.output
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            candidate = _candidate_by_text(session, "Cuaderno del Delta")
            candidate_id = candidate.id
    finally:
        engine.dispose()
    result = runner.invoke(
        app,
        [
            "discovery-decide",
            str(root),
            candidate_id,
            "--decision",
            "defer",
            "--decided-by",
            "alex",
            "--reason",
            "Validación desde terminal.",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "estado deferred" in result.output
    result = runner.invoke(
        app,
        ["discovery-decisions", str(root), "--candidate-id", candidate_id],
    )
    assert result.exit_code == 0, result.output
    assert "Validación desde terminal." in result.output
    assert "Total: 1 decisiones" in result.output


def test_discovery_review_ui_offers_explicit_append_only_actions() -> None:
    root = Path(__file__).parents[1]
    source = (root / "src/archive_workbench/discovery_app.py").read_text(
        encoding="utf-8"
    )
    assert 'key=f"discovery_candidate_review_panel_{row.candidate_id}"' in source
    assert 'help="El panel permanece abierto mientras cambiás la decisión o su destino."' in source
    assert 'with st.expander("Revisar candidato", expanded=False):' not in source
    assert 'key=f"open_discovery_profile_panel_{profile_key}"' in source
    assert 'with st.expander("Configurar perfil", expanded=not profiles):' not in source
    assert '"Registrar decisión"' in source
    assert '"Historial de decisiones"' in source
    assert '"Confirmo la creación de una autoridad nueva con estado Sin revisar"' in source
    assert "Las decisiones son append-only" in source
    assert "create_entity_relation" not in source
    assert "st.form(" not in source
    assert "disabled=" not in source


def test_open_discovery_review_validation_preparation_preserves_existing_run(
    tmp_path: Path,
) -> None:
    import shutil

    from archive_workbench.db import upgrade_database
    from archive_workbench.db.models import DiscoveryDecision
    from scripts.prepare_open_discovery_review_validation import prepare_review_validation

    source = tmp_path / "source_b"
    destination = tmp_path / "destination_b"
    _seed_discovery_project(source)
    (source / "config").mkdir(parents=True, exist_ok=True)
    shutil.copy(
        Path(__file__).parents[1] / "config" / "decisions.yaml",
        source / "config" / "decisions.yaml",
    )
    engine = create_sqlite_engine(database_path(source))
    try:
        with session_scope(engine) as session:
            profile = save_discovery_profile(
                session,
                project_id="search_project",
                values=DiscoveryProfileValues(name="Existente"),
                changed_by="tests",
            )
            run = run_open_discovery(
                session,
                project_id="search_project",
                profile=profile,
                created_by="tests",
            )
            controlled = session.scalar(select(EditableObject))
            assert controlled is not None
            payload = {
                "editable_object_id": controlled.id,
                "expected_texts": [
                    "24 de marzo de 1976",
                    "Dra. Valentina Orbe",
                    "ciudad de Puerto Niebla",
                    "Ministerio de Archivos Imaginarios",
                    "operativo Horizonte",
                    "investigación documental",
                    "Cuaderno del Delta",
                ],
            }
    finally:
        engine.dispose()
    shutil.copytree(source, destination)
    upgrade_database(destination)
    (destination / "validation").mkdir(exist_ok=True)
    (destination / "validation" / "disc01a.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )
    result = prepare_review_validation(destination)
    assert result["revision"] == "0040_discovery_grouping_continuity"
    assert result["run_id"] == run.run_id
    assert len(result["candidate_ids_by_text"]) == 7
    engine = create_sqlite_engine(database_path(destination))
    try:
        with session_scope(engine) as session:
            assert session.scalar(select(func.count()).select_from(DiscoveryRun)) == 1
            assert session.scalar(select(func.count()).select_from(DiscoveryDecision)) == 0
            authority = session.get(AuthorityRecord, result["existing_authority_id"])
            assert authority is not None
            assert authority.review_status == "approved"
    finally:
        engine.dispose()


def test_open_discovery_review_validation_script_checks_controlled_decisions(
    tmp_path: Path,
) -> None:
    from archive_workbench.discovery_review import review_discovery_candidate
    from scripts.prepare_open_discovery_review_validation import prepare_review_validation
    from scripts.validate_open_discovery_disc01b import validate_review

    root = tmp_path / "disc01b_validation"
    controlled_object_id = _seed_discovery_project(root)
    (root / "validation").mkdir(parents=True, exist_ok=True)
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            editable = session.get(EditableObject, controlled_object_id)
            assert editable is not None
            editable.current_text += " También hubo una manifestación."
            editable.revision_number += 1
            session.flush()
            profile = save_discovery_profile(
                session,
                project_id="search_project",
                values=DiscoveryProfileValues(name="Validación B"),
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

    validation = prepare_review_validation(root)
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            ids = validation["candidate_ids_by_text"]
            assert isinstance(ids, dict)
            review_discovery_candidate(
                session,
                project_id="search_project",
                candidate_id=ids["Ministerio de Archivos Imaginarios"],
                decision_type="accept",
                acceptance_mode="existing_authority",
                authority_id=str(validation["existing_authority_id"]),
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
                description="Fecha controlada.",
                decided_by="alex",
                source="ui",
            )
            review_discovery_candidate(
                session,
                project_id="search_project",
                candidate_id=ids["operativo Horizonte"],
                decision_type="accept",
                acceptance_mode="structured_record",
                description="Acontecimiento controlado.",
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
                description="Proceso controlado.",
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
            extra = _candidate_by_text(session, "manifestación")
            review_discovery_candidate(
                session,
                project_id="search_project",
                candidate_id=extra.id,
                decision_type="accept",
                acceptance_mode="structured_record",
                decided_by="alex",
                source="ui",
            )
    finally:
        engine.dispose()

    result = validate_review(root)
    assert result["controlled_candidates"] == 7
    assert result["controlled_decisions"] == 8
    assert result["additional_decisions"] == 1
    assert result["controlled_context_records"] == 3
    assert result["additional_context_records"] == 1
    assert result["controlled_mentions"] == 2
    assert result["additional_mentions"] == 0
    assert result["created_authority"] == "Valentina Orbe"
