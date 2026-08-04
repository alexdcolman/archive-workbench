from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select

from archive_workbench.authorities import (
    _append_mention_revision,
    create_authority,
    create_mention,
    exact_mention_occurrences,
    mention_repair_cases,
    mention_revision_rows,
    normalize_authority_text,
    repair_duplicate_group,
    repair_duplicate_relocation,
    repair_missing_authority,
    repair_safe_relocation_group,
    repair_snapshot_divergence,
    repair_stale_mention,
    repair_unresolved_relocation,
)
from archive_workbench.db import create_sqlite_engine, database_path, session_scope
from archive_workbench.db.models import (
    AuthorityRecord,
    EditableObject,
    EntityMention,
    ExchangeChangeEvent,
    utc_now,
)
from archive_workbench.identity import new_id
from tests.test_search import _seed_search_project


def _seed_stale_mention(root: Path) -> tuple[str, str, str]:
    object_id, _page_id = _seed_search_project(root)
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            authority = create_authority(
                session,
                project_id="search_project",
                entity_type="event",
                preferred_name="Actividad teatral",
                created_by="tests",
            )
            mention = create_mention(
                session,
                object_id=object_id,
                mention_text="actividad teatral",
                authority_id=authority.id,
                created_by="tests",
            )
            mention_id = mention.id
            authority_id = authority.id
        with session_scope(engine) as session:
            editable = session.get(EditableObject, object_id)
            assert editable is not None
            editable.current_text = "Antecedente. La actividad teatral fue investigada"
            editable.revision_number = 2
    finally:
        engine.dispose()
    return object_id, authority_id, mention_id


def _seed_current_mention(root: Path) -> tuple[str, str, str]:
    object_id, _page_id = _seed_search_project(root)
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            authority = create_authority(
                session,
                project_id="search_project",
                entity_type="organization",
                preferred_name="Entidad vigente",
                created_by="tests",
            )
            mention = create_mention(
                session,
                object_id=object_id,
                mention_text="actividad",
                authority_id=authority.id,
                start_offset=3,
                end_offset=12,
                status="accepted",
                source="manual",
                note="Estado registrado",
                created_by="tests",
            )
            return object_id, authority.id, mention.id
    finally:
        engine.dispose()


def _seed_missing_authority(
    root: Path,
    *,
    status: str = "accepted",
) -> tuple[str, str, str]:
    object_id, _page_id = _seed_search_project(root)
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            target = create_authority(
                session,
                project_id="search_project",
                entity_type="event",
                preferred_name="Actividad",
                created_by="tests",
            )
            editable = session.get(EditableObject, object_id)
            assert editable is not None
            mention = EntityMention(
                id=new_id(),
                editable_object_id=object_id,
                authority_id=None,
                mention_text="actividad",
                normalized_text="actividad",
                start_offset=0,
                end_offset=9,
                object_revision_number=editable.revision_number,
                status=status,
                source="manual",
                confidence=None,
                note="Caso histórico sin entidad",
                created_by="tests",
                created_at=utc_now(),
                updated_by="tests",
                updated_at=utc_now(),
                revision=1,
            )
            session.add(mention)
            session.flush()
            _append_mention_revision(
                session,
                mention,
                operation="create",
                changed_by="tests",
                note=mention.note,
            )
            return object_id, target.id, mention.id
    finally:
        engine.dispose()


def test_safe_relocation_is_auditable_and_preserves_prior_snapshot(tmp_path: Path) -> None:
    root = tmp_path / "safe_relocation"
    _object_id, _authority_id, mention_id = _seed_stale_mention(root)
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            cases = mention_repair_cases(session, project_id="search_project")
            safe = next(case for case in cases if case.mention_id == mention_id)
            assert safe.code == "safe_relocation"
            assert safe.can_relocate
            assert safe.stored_object_revision == 1
            assert safe.current_object_revision == 2
            assert safe.projected_text == "actividad teatral"

            repaired = repair_stale_mention(
                session,
                mention_id=mention_id,
                expected_revision=safe.mention_revision,
                expected_start_offset=safe.projected_start_offset,
                expected_end_offset=safe.projected_end_offset,
                changed_by="alex",
                note="Validación de reubicación segura",
            )
            assert repaired.object_revision_number == 2
            assert repaired.start_offset == 16
            assert repaired.end_offset == 33
            assert repaired.mention_text == "actividad teatral"
            assert repaired.revision == 2

            revisions = mention_revision_rows(session, mention_id)
            assert [row.revision_number for row in revisions] == [1, 2]
            assert [row.operation for row in revisions] == ["create", "repair_relocation"]
            assert revisions[0].snapshot_json["object_revision_number"] == 1
            assert revisions[1].snapshot_json["object_revision_number"] == 2
            assert revisions[1].note == "Validación de reubicación segura"
            events = session.scalars(
                select(ExchangeChangeEvent)
                .where(
                    ExchangeChangeEvent.entity_type == "entity_mention",
                    ExchangeChangeEvent.entity_id == mention_id,
                )
                .order_by(ExchangeChangeEvent.sequence_number)
            ).all()
            assert [event.operation for event in events] == ["create", "update"]
            assert events[-1].new_revision == 2
            assert events[-1].changed_fields_json["object_revision_number"] == [1, 2]
            assert events[-1].changed_fields_json["start_offset"] == [3, 16]

        with session_scope(engine) as session:
            assert mention_repair_cases(session, project_id="search_project") == []
    finally:
        engine.dispose()


def test_unresolved_relocation_never_changes_the_mention(tmp_path: Path) -> None:
    root = tmp_path / "unresolved_relocation"
    object_id, _authority_id, mention_id = _seed_stale_mention(root)
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            editable = session.get(EditableObject, object_id)
            assert editable is not None
            editable.current_text = "El fragmento fue retirado por completo"
            editable.revision_number = 3

        with session_scope(engine) as session:
            case = next(
                case
                for case in mention_repair_cases(session, project_id="search_project")
                if case.mention_id == mention_id
            )
            assert case.code == "unresolved_relocation"
            assert not case.can_relocate
            with pytest.raises(ValueError, match="no puede localizarse de manera única"):
                repair_stale_mention(
                    session,
                    mention_id=mention_id,
                    expected_revision=case.mention_revision,
                    changed_by="tests",
                )
            mention = session.get(EntityMention, mention_id)
            assert mention is not None
            assert mention.object_revision_number == 1
            assert mention.revision == 1
    finally:
        engine.dispose()


def test_exact_mention_occurrences_preserve_literal_offsets() -> None:
    text = "Uno Mención repetida. Dos mención repetida."
    assert exact_mention_occurrences(text, "mención repetida") == [
        (4, 20),
        (26, 42),
    ]
    assert exact_mention_occurrences(text, "  ") == []


def test_unresolved_relocation_can_select_one_exact_occurrence(
    tmp_path: Path,
) -> None:
    root = tmp_path / "manual_unresolved_relocation"
    object_id, _authority_id, mention_id = _seed_stale_mention(root)
    engine = create_sqlite_engine(database_path(root))
    try:
        current_text = (
            "Primera actividad teatral. Segunda actividad teatral elegida."
        )
        with session_scope(engine) as session:
            editable = session.get(EditableObject, object_id)
            mention = session.get(EntityMention, mention_id)
            assert editable is not None and mention is not None
            # El cambio de mayúsculas impide que SequenceMatcher decida por sí solo.
            mention.mention_text = "ACTIVIDAD TEATRAL"
            mention.normalized_text = normalize_authority_text(mention.mention_text)
            revision = mention_revision_rows(session, mention_id)[-1]
            revision.snapshot_json = {
                **revision.snapshot_json,
                "mention_text": mention.mention_text,
                "normalized_text": mention.normalized_text,
            }
            editable.current_text = current_text
            editable.revision_number = 3

        with session_scope(engine) as session:
            case = next(
                case
                for case in mention_repair_cases(session, project_id="search_project")
                if case.mention_id == mention_id
            )
            assert case.code == "unresolved_relocation"
            assert case.can_resolve_unresolved
            occurrences = exact_mention_occurrences(
                current_text,
                "actividad teatral",
            )
            assert len(occurrences) == 2
            selected_start, selected_end = occurrences[1]

            repaired = repair_unresolved_relocation(
                session,
                mention_id=mention_id,
                expected_revision=case.mention_revision,
                expected_object_revision=case.current_object_revision,
                changed_by="alex",
                decision="relocate",
                selected_fragment="actividad teatral",
                expected_start_offset=selected_start,
                expected_end_offset=selected_end,
                note="Se eligió la segunda aparición después de leer el texto.",
            )
            assert repaired.status == "accepted"
            assert repaired.object_revision_number == 3
            assert (repaired.start_offset, repaired.end_offset) == occurrences[1]
            assert repaired.mention_text == "actividad teatral"
            revisions = mention_revision_rows(session, mention_id)
            assert [row.operation for row in revisions] == [
                "create",
                "repair_manual_relocation",
            ]
            assert revisions[-1].note == (
                "Se eligió la segunda aparición después de leer el texto."
            )
            events = session.scalars(
                select(ExchangeChangeEvent)
                .where(
                    ExchangeChangeEvent.entity_type == "entity_mention",
                    ExchangeChangeEvent.entity_id == mention_id,
                )
                .order_by(ExchangeChangeEvent.sequence_number)
            ).all()
            assert events[-1].operation == "update"
            assert events[-1].changed_fields_json["object_revision_number"] == [
                1,
                3,
            ]

        with session_scope(engine) as session:
            assert [
                case
                for case in mention_repair_cases(session, project_id="search_project")
                if case.mention_id == mention_id
            ] == []
    finally:
        engine.dispose()


def test_unresolved_relocation_can_mark_a_missing_fragment_as_absent(
    tmp_path: Path,
) -> None:
    root = tmp_path / "manual_absent_relocation"
    object_id, _authority_id, mention_id = _seed_stale_mention(root)
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            editable = session.get(EditableObject, object_id)
            assert editable is not None
            editable.current_text = "El fragmento fue retirado por completo"
            editable.revision_number = 3

        with session_scope(engine) as session:
            case = next(
                case
                for case in mention_repair_cases(session, project_id="search_project")
                if case.mention_id == mention_id
            )
            repaired = repair_unresolved_relocation(
                session,
                mention_id=mention_id,
                expected_revision=case.mention_revision,
                expected_object_revision=case.current_object_revision,
                changed_by="alex",
                decision="mark_absent",
                note="El fragmento ya no está en el texto vigente.",
            )
            assert repaired.status == "rejected"
            assert repaired.object_revision_number == 1
            revisions = mention_revision_rows(session, mention_id)
            assert [row.operation for row in revisions] == [
                "create",
                "repair_mark_absent",
            ]
            assert revisions[-1].snapshot_json["status"] == "rejected"
            events = session.scalars(
                select(ExchangeChangeEvent)
                .where(
                    ExchangeChangeEvent.entity_type == "entity_mention",
                    ExchangeChangeEvent.entity_id == mention_id,
                )
                .order_by(ExchangeChangeEvent.sequence_number)
            ).all()
            assert events[-1].operation == "update"
            assert events[-1].changed_fields_json["status"] == [
                "accepted",
                "rejected",
            ]

        with session_scope(engine) as session:
            assert [
                case
                for case in mention_repair_cases(session, project_id="search_project")
                if case.mention_id == mention_id
            ] == []
    finally:
        engine.dispose()


def test_unresolved_relocation_rejects_absence_when_fragment_still_occurs(
    tmp_path: Path,
) -> None:
    root = tmp_path / "manual_absent_guard"
    object_id, _authority_id, mention_id = _seed_stale_mention(root)
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            editable = session.get(EditableObject, object_id)
            mention = session.get(EntityMention, mention_id)
            assert editable is not None and mention is not None
            mention.mention_text = "ACTIVIDAD TEATRAL"
            mention.normalized_text = normalize_authority_text(mention.mention_text)
            revision = mention_revision_rows(session, mention_id)[-1]
            revision.snapshot_json = {
                **revision.snapshot_json,
                "mention_text": mention.mention_text,
                "normalized_text": mention.normalized_text,
            }
            editable.current_text = (
                "Una actividad teatral y otra actividad teatral"
            )
            editable.revision_number = 3

        with session_scope(engine) as session:
            case = next(
                case
                for case in mention_repair_cases(session, project_id="search_project")
                if case.mention_id == mention_id
            )
            assert case.code == "unresolved_relocation"
            with pytest.raises(ValueError, match="todavía aparece"):
                repair_unresolved_relocation(
                    session,
                    mention_id=mention_id,
                    expected_revision=case.mention_revision,
                    expected_object_revision=case.current_object_revision,
                    changed_by="tests",
                    decision="mark_absent",
                )
    finally:
        engine.dispose()


def test_duplicate_projection_requires_human_decision(tmp_path: Path) -> None:
    root = tmp_path / "duplicate_relocation"
    object_id, authority_id, old_mention_id = _seed_stale_mention(root)
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            current = EntityMention(
                id=new_id(),
                editable_object_id=object_id,
                authority_id=authority_id,
                mention_text="actividad teatral",
                normalized_text=normalize_authority_text("actividad teatral"),
                start_offset=16,
                end_offset=33,
                object_revision_number=2,
                status="accepted",
                source="manual",
                confidence=None,
                note="Duplicado histórico sembrado para la regresión",
                created_by="tests",
                created_at=utc_now(),
                updated_by="tests",
                updated_at=utc_now(),
                revision=1,
            )
            session.add(current)
            session.flush()
            _append_mention_revision(
                session,
                current,
                operation="create",
                changed_by="tests",
                note=current.note,
            )
            current_id = current.id

        with session_scope(engine) as session:
            case = next(
                case
                for case in mention_repair_cases(session, project_id="search_project")
                if case.mention_id == old_mention_id
                and case.code == "duplicate_relocation"
            )
            assert case.duplicate_mention_ids == (current_id,)
            with pytest.raises(ValueError, match="otra mención activa"):
                repair_stale_mention(
                    session,
                    mention_id=old_mention_id,
                    expected_revision=case.mention_revision,
                    changed_by="tests",
                )
            old = session.get(EntityMention, old_mention_id)
            assert old is not None
            assert old.object_revision_number == 1
            assert old.revision == 1
    finally:
        engine.dispose()


def _add_current_duplicate(
    session,
    *,
    object_id: str,
    authority_id: str,
    note: str = "Duplicado vigente sembrado para la regresión",
) -> str:
    current = EntityMention(
        id=new_id(),
        editable_object_id=object_id,
        authority_id=authority_id,
        mention_text="actividad teatral",
        normalized_text=normalize_authority_text("actividad teatral"),
        start_offset=16,
        end_offset=33,
        object_revision_number=2,
        status="accepted",
        source="manual",
        confidence=None,
        note=note,
        created_by="tests",
        created_at=utc_now(),
        updated_by="tests",
        updated_at=utc_now(),
        revision=1,
    )
    session.add(current)
    session.flush()
    _append_mention_revision(
        session,
        current,
        operation="create",
        changed_by="tests",
        note=current.note,
    )
    return current.id


def test_duplicate_repair_can_keep_current_and_reject_historical(
    tmp_path: Path,
) -> None:
    root = tmp_path / "duplicate_keep_current"
    object_id, authority_id, historical_id = _seed_stale_mention(root)
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            current_id = _add_current_duplicate(
                session,
                object_id=object_id,
                authority_id=authority_id,
            )

        with session_scope(engine) as session:
            case = next(
                case
                for case in mention_repair_cases(session, project_id="search_project")
                if case.mention_id == historical_id
            )
            current = session.get(EntityMention, current_id)
            assert current is not None
            assert case.code == "duplicate_relocation"
            assert case.can_resolve_duplicate

            historical, kept = repair_duplicate_relocation(
                session,
                mention_id=historical_id,
                expected_revision=case.mention_revision,
                duplicate_mention_id=current_id,
                duplicate_expected_revision=current.revision,
                changed_by="alex",
                decision="keep_current",
                note="Se conserva la mención vigente verificada.",
            )
            assert historical.status == "rejected"
            assert historical.revision == 2
            assert kept.id == current_id
            assert kept.status == "accepted"
            assert kept.revision == 1
            assert [row.operation for row in mention_revision_rows(session, historical_id)] == [
                "create",
                "repair_duplicate_rejected",
            ]
            assert [row.operation for row in mention_revision_rows(session, current_id)] == [
                "create"
            ]

        with session_scope(engine) as session:
            assert [
                case
                for case in mention_repair_cases(session, project_id="search_project")
                if case.mention_id in {historical_id, current_id}
            ] == []
    finally:
        engine.dispose()


def test_duplicate_repair_can_keep_historical_and_relocate_it(
    tmp_path: Path,
) -> None:
    root = tmp_path / "duplicate_keep_historical"
    object_id, authority_id, historical_id = _seed_stale_mention(root)
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            current_id = _add_current_duplicate(
                session,
                object_id=object_id,
                authority_id=authority_id,
            )

        with session_scope(engine) as session:
            case = next(
                case
                for case in mention_repair_cases(session, project_id="search_project")
                if case.mention_id == historical_id
            )
            current = session.get(EntityMention, current_id)
            assert current is not None

            historical, rejected = repair_duplicate_relocation(
                session,
                mention_id=historical_id,
                expected_revision=case.mention_revision,
                duplicate_mention_id=current_id,
                duplicate_expected_revision=current.revision,
                changed_by="alex",
                decision="keep_historical",
                note="Se conserva la mención histórica por su entidad y procedencia.",
            )
            assert historical.status == "accepted"
            assert historical.object_revision_number == 2
            assert (historical.start_offset, historical.end_offset) == (16, 33)
            assert historical.revision == 2
            assert rejected.status == "rejected"
            assert rejected.revision == 2
            assert [row.operation for row in mention_revision_rows(session, historical_id)] == [
                "create",
                "repair_duplicate_relocated",
            ]
            assert [row.operation for row in mention_revision_rows(session, current_id)] == [
                "create",
                "repair_duplicate_rejected",
            ]
            events = session.scalars(
                select(ExchangeChangeEvent)
                .where(
                    ExchangeChangeEvent.entity_type == "entity_mention",
                    ExchangeChangeEvent.entity_id.in_([historical_id, current_id]),
                )
                .order_by(ExchangeChangeEvent.sequence_number)
            ).all()
            assert [event.operation for event in events].count("update") == 2

        with session_scope(engine) as session:
            assert [
                case
                for case in mention_repair_cases(session, project_id="search_project")
                if case.mention_id in {historical_id, current_id}
            ] == []
    finally:
        engine.dispose()


def test_duplicate_group_can_keep_current_and_reject_all_others(
    tmp_path: Path,
) -> None:
    root = tmp_path / "duplicate_group_keep_current"
    object_id, authority_id, historical_id = _seed_stale_mention(root)
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            winner_id = _add_current_duplicate(
                session,
                object_id=object_id,
                authority_id=authority_id,
                note="Mención vigente elegida",
            )
            other_current_id = _add_current_duplicate(
                session,
                object_id=object_id,
                authority_id=authority_id,
                note="Mención vigente descartada",
            )

        with session_scope(engine) as session:
            group_cases = [
                case
                for case in mention_repair_cases(
                    session, project_id="search_project"
                )
                if case.code == "duplicate_group"
            ]
            assert len(group_cases) == 1
            case = group_cases[0]
            group_ids = (case.mention_id, *case.duplicate_mention_ids)
            assert set(group_ids) == {
                historical_id,
                winner_id,
                other_current_id,
            }
            assert case.can_resolve_duplicate_group
            rows = {
                mention_id: session.get(EntityMention, mention_id)
                for mention_id in group_ids
            }
            assert all(row is not None for row in rows.values())

            winner, losers = repair_duplicate_group(
                session,
                mention_ids=group_ids,
                expected_revisions={
                    mention_id: row.revision
                    for mention_id, row in rows.items()
                    if row is not None
                },
                winner_mention_id=winner_id,
                expected_object_revision=case.current_object_revision,
                expected_start_offset=case.projected_start_offset,
                expected_end_offset=case.projected_end_offset,
                changed_by="alex",
                note="Se conserva la mención vigente después de revisar el conjunto.",
            )
            assert winner.id == winner_id
            assert winner.status == "accepted"
            assert winner.revision == 2
            assert {row.id for row in losers} == {historical_id, other_current_id}
            assert all(row.status == "rejected" for row in losers)
            assert [
                row.operation
                for row in mention_revision_rows(session, winner_id)
            ] == ["create", "repair_group_duplicate_kept"]
            for loser_id in (historical_id, other_current_id):
                assert [
                    row.operation
                    for row in mention_revision_rows(session, loser_id)
                ] == ["create", "repair_group_duplicate_rejected"]
            events = session.scalars(
                select(ExchangeChangeEvent)
                .where(
                    ExchangeChangeEvent.entity_type == "entity_mention",
                    ExchangeChangeEvent.entity_id.in_(group_ids),
                )
                .order_by(ExchangeChangeEvent.sequence_number)
            ).all()
            assert [event.operation for event in events].count("update") == 3

        with session_scope(engine) as session:
            assert [
                case
                for case in mention_repair_cases(
                    session, project_id="search_project"
                )
                if case.mention_id in {
                    historical_id, winner_id, other_current_id
                }
            ] == []
    finally:
        engine.dispose()


def test_duplicate_group_can_keep_historical_and_relocate_it(
    tmp_path: Path,
) -> None:
    root = tmp_path / "duplicate_group_keep_historical"
    object_id, authority_id, historical_id = _seed_stale_mention(root)
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            current_a_id = _add_current_duplicate(
                session,
                object_id=object_id,
                authority_id=authority_id,
                note="Primer duplicado vigente",
            )
            current_b_id = _add_current_duplicate(
                session,
                object_id=object_id,
                authority_id=authority_id,
                note="Segundo duplicado vigente",
            )

        with session_scope(engine) as session:
            case = next(
                case
                for case in mention_repair_cases(
                    session, project_id="search_project"
                )
                if case.code == "duplicate_group"
            )
            group_ids = (case.mention_id, *case.duplicate_mention_ids)
            rows = {
                mention_id: session.get(EntityMention, mention_id)
                for mention_id in group_ids
            }
            winner, losers = repair_duplicate_group(
                session,
                mention_ids=group_ids,
                expected_revisions={
                    mention_id: row.revision
                    for mention_id, row in rows.items()
                    if row is not None
                },
                winner_mention_id=historical_id,
                expected_object_revision=case.current_object_revision,
                expected_start_offset=case.projected_start_offset,
                expected_end_offset=case.projected_end_offset,
                changed_by="alex",
                note="Se conserva la mención histórica por su procedencia.",
            )
            assert winner.id == historical_id
            assert winner.object_revision_number == 2
            assert (winner.start_offset, winner.end_offset) == (16, 33)
            assert [
                row.operation
                for row in mention_revision_rows(session, historical_id)
            ] == ["create", "repair_group_duplicate_relocated"]
            assert {row.id for row in losers} == {current_a_id, current_b_id}
            for loser in losers:
                assert loser.status == "rejected"
                assert [
                    row.operation
                    for row in mention_revision_rows(session, loser.id)
                ] == ["create", "repair_group_duplicate_rejected"]
    finally:
        engine.dispose()


def test_duplicate_group_rejects_a_stale_comparison(tmp_path: Path) -> None:
    root = tmp_path / "duplicate_group_stale"
    object_id, authority_id, historical_id = _seed_stale_mention(root)
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            current_a_id = _add_current_duplicate(
                session,
                object_id=object_id,
                authority_id=authority_id,
            )
            current_b_id = _add_current_duplicate(
                session,
                object_id=object_id,
                authority_id=authority_id,
            )

        with session_scope(engine) as session:
            case = next(
                case
                for case in mention_repair_cases(
                    session, project_id="search_project"
                )
                if case.code == "duplicate_group"
            )
            group_ids = (case.mention_id, *case.duplicate_mention_ids)
            expected_revisions = {
                mention_id: session.get(EntityMention, mention_id).revision
                for mention_id in group_ids
            }

        with session_scope(engine) as session:
            changed = session.get(EntityMention, current_b_id)
            assert changed is not None
            changed.note = "Cambio posterior sin confirmar"
            changed.revision += 1
            _append_mention_revision(
                session,
                changed,
                operation="update",
                changed_by="tests",
                note=changed.note,
            )

        with session_scope(engine) as session:
            with pytest.raises(ValueError, match="está en revisión"):
                repair_duplicate_group(
                    session,
                    mention_ids=group_ids,
                    expected_revisions=expected_revisions,
                    winner_mention_id=current_a_id,
                    expected_object_revision=case.current_object_revision,
                    expected_start_offset=case.projected_start_offset,
                    expected_end_offset=case.projected_end_offset,
                    changed_by="tests",
                )
            historical = session.get(EntityMention, historical_id)
            current_a = session.get(EntityMention, current_a_id)
            assert historical is not None and current_a is not None
            assert historical.status == "accepted"
            assert current_a.status == "accepted"
    finally:
        engine.dispose()


def test_safe_relocations_can_be_applied_as_one_atomic_group(
    tmp_path: Path,
) -> None:
    root = tmp_path / "safe_relocation_group"
    object_id, _page_id = _seed_search_project(root)
    engine = create_sqlite_engine(database_path(root))
    fragments = ("La", "actividad teatral", "investigada")
    mention_ids: list[str] = []
    try:
        with session_scope(engine) as session:
            editable = session.get(EditableObject, object_id)
            assert editable is not None
            for index, fragment in enumerate(fragments):
                start = editable.current_text.index(fragment)
                authority = create_authority(
                    session,
                    project_id="search_project",
                    entity_type="other",
                    preferred_name=f"Entidad segura {index + 1}",
                    created_by="tests",
                )
                mention = create_mention(
                    session,
                    object_id=object_id,
                    mention_text=fragment,
                    authority_id=authority.id,
                    start_offset=start,
                    end_offset=start + len(fragment),
                    status="accepted",
                    source="manual",
                    created_by="tests",
                )
                mention_ids.append(mention.id)
            editable.current_text = "Prefijo agrupado. " + editable.current_text
            editable.revision_number = 2

        with session_scope(engine) as session:
            cases = [
                case
                for case in mention_repair_cases(
                    session, project_id="search_project"
                )
                if case.mention_id in mention_ids
            ]
            assert len(cases) == 3
            assert all(case.can_relocate for case in cases)
            repaired = repair_safe_relocation_group(
                session,
                expected_cases=cases,
                changed_by="alex",
                note="Reubicación agrupada validada.",
            )
            assert {row.id for row in repaired} == set(mention_ids)
            assert all(row.object_revision_number == 2 for row in repaired)
            for mention_id in mention_ids:
                assert [
                    row.operation
                    for row in mention_revision_rows(session, mention_id)
                ] == ["create", "repair_group_relocation"]
            events = session.scalars(
                select(ExchangeChangeEvent)
                .where(
                    ExchangeChangeEvent.entity_type == "entity_mention",
                    ExchangeChangeEvent.entity_id.in_(mention_ids),
                )
                .order_by(ExchangeChangeEvent.sequence_number)
            ).all()
            assert [event.operation for event in events].count("update") == 3

        with session_scope(engine) as session:
            assert [
                case
                for case in mention_repair_cases(
                    session, project_id="search_project"
                )
                if case.mention_id in mention_ids
            ] == []
    finally:
        engine.dispose()

def test_snapshot_divergence_blocks_automatic_repair(tmp_path: Path) -> None:
    root = tmp_path / "snapshot_divergence"
    _object_id, _authority_id, mention_id = _seed_stale_mention(root)
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            mention = session.get(EntityMention, mention_id)
            assert mention is not None
            mention.note = "Cambio histórico sin snapshot"

        with session_scope(engine) as session:
            cases = [
                case
                for case in mention_repair_cases(session, project_id="search_project")
                if case.mention_id == mention_id
            ]
            assert [case.code for case in cases] == ["snapshot_divergence"]
            with pytest.raises(ValueError, match="no coincide con su último snapshot"):
                repair_stale_mention(
                    session,
                    mention_id=mention_id,
                    expected_revision=1,
                    changed_by="tests",
                )
    finally:
        engine.dispose()


def test_snapshot_divergence_can_adopt_current_row_as_new_revision(
    tmp_path: Path,
) -> None:
    root = tmp_path / "snapshot_adopt_current"
    _object_id, _authority_id, mention_id = _seed_current_mention(root)
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            mention = session.get(EntityMention, mention_id)
            assert mention is not None
            mention.note = "Nota vigente sin snapshot"

        with session_scope(engine) as session:
            case = next(
                case
                for case in mention_repair_cases(
                    session,
                    project_id="search_project",
                )
                if case.mention_id == mention_id
            )
            assert case.code == "snapshot_divergence"
            assert case.can_resolve_snapshot_divergence
            assert case.snapshot_revision_number == 1
            assert case.snapshot_operation == "create"
            assert case.snapshot_difference_fields == ("note",)
            assert case.snapshot_current is not None
            assert case.snapshot_recorded is not None

            repaired = repair_snapshot_divergence(
                session,
                mention_id=mention_id,
                expected_revision=case.mention_revision,
                expected_snapshot_revision=case.snapshot_revision_number,
                expected_current_snapshot=case.snapshot_current,
                expected_recorded_snapshot=case.snapshot_recorded,
                changed_by="alex",
                decision="adopt_current",
                note="La fila vigente fue verificada contra el historial.",
            )
            assert repaired.note == "Nota vigente sin snapshot"
            assert repaired.revision == 2
            revisions = mention_revision_rows(session, mention_id)
            assert [row.operation for row in revisions] == [
                "create",
                "repair_adopt_current_row",
            ]
            assert revisions[-1].snapshot_json["note"] == "Nota vigente sin snapshot"
            assert revisions[-1].note == (
                "La fila vigente fue verificada contra el historial."
            )

        with session_scope(engine) as session:
            assert [
                case
                for case in mention_repair_cases(
                    session,
                    project_id="search_project",
                )
                if case.mention_id == mention_id
            ] == []
    finally:
        engine.dispose()


def test_snapshot_divergence_can_restore_latest_snapshot_as_new_revision(
    tmp_path: Path,
) -> None:
    root = tmp_path / "snapshot_restore_history"
    _object_id, authority_id, mention_id = _seed_current_mention(root)
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            mention = session.get(EntityMention, mention_id)
            assert mention is not None
            mention.authority_id = None
            mention.status = "pending"
            mention.note = "Fila accidental que debe descartarse"

        with session_scope(engine) as session:
            case = next(
                case
                for case in mention_repair_cases(
                    session,
                    project_id="search_project",
                )
                if case.mention_id == mention_id
            )
            assert case.code == "snapshot_divergence"
            assert case.can_resolve_snapshot_divergence
            assert set(case.snapshot_difference_fields) == {
                "authority_id",
                "status",
                "note",
            }
            assert case.snapshot_current is not None
            assert case.snapshot_recorded is not None

            repaired = repair_snapshot_divergence(
                session,
                mention_id=mention_id,
                expected_revision=case.mention_revision,
                expected_snapshot_revision=case.snapshot_revision_number or 0,
                expected_current_snapshot=case.snapshot_current,
                expected_recorded_snapshot=case.snapshot_recorded,
                changed_by="alex",
                decision="restore_snapshot",
                note="Se restaura el estado documentado.",
            )
            assert repaired.authority_id == authority_id
            assert repaired.status == "accepted"
            assert repaired.note == "Estado registrado"
            assert repaired.revision == 3
            revisions = mention_revision_rows(session, mention_id)
            assert [row.operation for row in revisions] == [
                "create",
                "repair_capture_divergent_row",
                "repair_restore_snapshot",
            ]
            assert revisions[1].snapshot_json["authority_id"] is None
            assert revisions[1].snapshot_json["status"] == "pending"
            assert revisions[1].snapshot_json["note"] == (
                "Fila accidental que debe descartarse"
            )
            assert revisions[-1].snapshot_json == revisions[0].snapshot_json
            assert revisions[-1].note == "Se restaura el estado documentado."

        with session_scope(engine) as session:
            assert [
                case
                for case in mention_repair_cases(
                    session,
                    project_id="search_project",
                )
                if case.mention_id == mention_id
            ] == []
    finally:
        engine.dispose()


def test_snapshot_divergence_repair_rejects_stale_comparison(
    tmp_path: Path,
) -> None:
    root = tmp_path / "snapshot_stale_comparison"
    _object_id, _authority_id, mention_id = _seed_current_mention(root)
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            mention = session.get(EntityMention, mention_id)
            assert mention is not None
            mention.note = "Primera divergencia"

        with session_scope(engine) as session:
            case = next(
                case
                for case in mention_repair_cases(
                    session,
                    project_id="search_project",
                )
                if case.mention_id == mention_id
            )
            assert case.snapshot_current is not None
            assert case.snapshot_recorded is not None
            mention = session.get(EntityMention, mention_id)
            assert mention is not None
            mention.note = "La fila cambió después de mostrar la alerta"
            session.flush()
            with pytest.raises(ValueError, match="fila vigente cambió"):
                repair_snapshot_divergence(
                    session,
                    mention_id=mention_id,
                    expected_revision=case.mention_revision,
                    expected_snapshot_revision=case.snapshot_revision_number or 0,
                    expected_current_snapshot=case.snapshot_current,
                    expected_recorded_snapshot=case.snapshot_recorded,
                    changed_by="tests",
                    decision="adopt_current",
                )
    finally:
        engine.dispose()


def test_missing_authority_can_be_linked_with_auditable_revision(
    tmp_path: Path,
) -> None:
    root = tmp_path / "missing_authority_link"
    _object_id, target_id, mention_id = _seed_missing_authority(root)
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            case = next(
                case
                for case in mention_repair_cases(session, project_id="search_project")
                if case.mention_id == mention_id
            )
            assert case.code == "missing_authority"
            assert case.can_resolve_missing_authority

            repaired = repair_missing_authority(
                session,
                mention_id=mention_id,
                expected_revision=case.mention_revision,
                changed_by="alex",
                decision="link",
                authority_id=target_id,
                note="Entidad verificada en el corpus",
            )
            assert repaired.authority_id == target_id
            assert repaired.status == "accepted"
            assert repaired.revision == 2
            revisions = mention_revision_rows(session, mention_id)
            assert [row.operation for row in revisions] == [
                "create",
                "repair_link_authority",
            ]
            assert revisions[-1].note == "Entidad verificada en el corpus"
            events = session.scalars(
                select(ExchangeChangeEvent)
                .where(
                    ExchangeChangeEvent.entity_type == "entity_mention",
                    ExchangeChangeEvent.entity_id == mention_id,
                )
                .order_by(ExchangeChangeEvent.sequence_number)
            ).all()
            assert events[-1].operation == "update"
            assert events[-1].changed_fields_json["authority_id"] == [
                None,
                target_id,
            ]

        with session_scope(engine) as session:
            assert [
                case
                for case in mention_repair_cases(session, project_id="search_project")
                if case.mention_id == mention_id
            ] == []
    finally:
        engine.dispose()


def test_missing_authority_can_return_to_pending_without_losing_history(
    tmp_path: Path,
) -> None:
    root = tmp_path / "missing_authority_pending"
    _object_id, _target_id, mention_id = _seed_missing_authority(
        root,
        status="modified",
    )
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            case = next(
                case
                for case in mention_repair_cases(session, project_id="search_project")
                if case.mention_id == mention_id
            )
            repaired = repair_missing_authority(
                session,
                mention_id=mention_id,
                expected_revision=case.mention_revision,
                changed_by="alex",
                decision="return_pending",
                note="La entidad no puede verificarse todavía",
            )
            assert repaired.authority_id is None
            assert repaired.status == "pending"
            assert repaired.revision == 2
            revisions = mention_revision_rows(session, mention_id)
            assert [row.operation for row in revisions] == [
                "create",
                "repair_return_pending",
            ]
            assert revisions[0].snapshot_json["status"] == "modified"
            assert revisions[1].snapshot_json["status"] == "pending"
            events = session.scalars(
                select(ExchangeChangeEvent)
                .where(
                    ExchangeChangeEvent.entity_type == "entity_mention",
                    ExchangeChangeEvent.entity_id == mention_id,
                )
                .order_by(ExchangeChangeEvent.sequence_number)
            ).all()
            assert events[-1].operation == "update"
            assert events[-1].changed_fields_json["status"] == [
                "modified",
                "pending",
            ]

        with session_scope(engine) as session:
            assert [
                case
                for case in mention_repair_cases(session, project_id="search_project")
                if case.mention_id == mention_id
            ] == []
    finally:
        engine.dispose()


def test_missing_authority_repair_rejects_stale_form_and_inactive_entity(
    tmp_path: Path,
) -> None:
    root = tmp_path / "missing_authority_guards"
    _object_id, target_id, mention_id = _seed_missing_authority(root)
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            target = session.get(AuthorityRecord, target_id)
            assert target is not None
            target.lifecycle_status = "inactive"

        with session_scope(engine) as session:
            with pytest.raises(ValueError, match="no está activa"):
                repair_missing_authority(
                    session,
                    mention_id=mention_id,
                    expected_revision=1,
                    changed_by="tests",
                    decision="link",
                    authority_id=target_id,
                )

        with session_scope(engine) as session:
            repair_missing_authority(
                session,
                mention_id=mention_id,
                expected_revision=1,
                changed_by="tests",
                decision="return_pending",
            )
            with pytest.raises(ValueError, match="se esperaba 1"):
                repair_missing_authority(
                    session,
                    mention_id=mention_id,
                    expected_revision=1,
                    changed_by="tests",
                    decision="return_pending",
                )
    finally:
        engine.dispose()


def test_missing_authority_with_snapshot_divergence_is_not_actionable(
    tmp_path: Path,
) -> None:
    root = tmp_path / "missing_authority_snapshot_divergence"
    _object_id, target_id, mention_id = _seed_missing_authority(root)
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            mention = session.get(EntityMention, mention_id)
            assert mention is not None
            mention.note = "Cambio sin snapshot"

        with session_scope(engine) as session:
            cases = [
                case
                for case in mention_repair_cases(session, project_id="search_project")
                if case.mention_id == mention_id
            ]
            assert [case.code for case in cases] == ["snapshot_divergence"]
            with pytest.raises(ValueError, match="no coincide con su último snapshot"):
                repair_missing_authority(
                    session,
                    mention_id=mention_id,
                    expected_revision=1,
                    changed_by="tests",
                    decision="link",
                    authority_id=target_id,
                )
    finally:
        engine.dispose()


def test_validation_script_creates_a_disposable_safe_case(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from scripts.create_mention_repair_validation_project import create_validation_copy

    source = tmp_path / "source_project"
    destination = tmp_path / "validation_copy"
    _seed_search_project(source)

    mention_id = create_validation_copy(source, destination, force=False)
    output = capsys.readouterr().out
    assert "Clasificación: safe_relocation" in output
    assert "Offsets almacenados:" in output
    assert "Offsets proyectados:" in output

    engine = create_sqlite_engine(database_path(destination))
    try:
        with session_scope(engine) as session:
            case = next(
                case
                for case in mention_repair_cases(session, project_id="search_project")
                if case.mention_id == mention_id
            )
            assert case.code == "safe_relocation"
            assert case.projected_text
    finally:
        engine.dispose()


def test_validation_fragment_keeps_complete_words() -> None:
    from scripts.create_mention_repair_validation_project import _unique_fragment

    text = "Destino comun completamente distinto para las dos anotaciones"
    fragment, start, end = _unique_fragment(text)
    assert fragment == text
    assert (start, end) == (0, len(text))


def test_missing_authority_validation_script_creates_two_decision_paths(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from scripts.create_missing_authority_validation_project import (
        create_validation_copy,
    )

    source = tmp_path / "source_project"
    destination = tmp_path / "missing_authority_copy"
    _seed_search_project(source)

    result = create_validation_copy(source, destination, force=False)
    output = capsys.readouterr().out
    assert "Alertas esperadas: 2 × missing_authority" in output
    assert "Mención para vincular:" in output
    assert "Mención para devolver a pendiente:" in output

    engine = create_sqlite_engine(database_path(destination))
    try:
        with session_scope(engine) as session:
            cases = {
                case.mention_id: case
                for case in mention_repair_cases(
                    session,
                    project_id="search_project",
                )
                if case.code == "missing_authority"
            }
            assert set(cases) >= {
                result["link_mention_id"],
                result["pending_mention_id"],
            }
            assert cases[result["link_mention_id"]].mention_text.endswith(
                "para vincular"
            )
            assert cases[result["pending_mention_id"]].mention_text.endswith(
                "a pendiente"
            )
    finally:
        engine.dispose()


def test_duplicate_validation_script_creates_two_explicit_decision_paths(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from scripts.create_duplicate_mention_validation_project import (
        create_validation_copy,
    )

    source = tmp_path / "source_project"
    destination = tmp_path / "duplicate_copy"
    _seed_search_project(source)

    result = create_validation_copy(source, destination, force=False)
    output = capsys.readouterr().out
    assert "Alertas esperadas: 2 × duplicate_relocation" in output
    assert "Alfa histórica:" in output
    assert "Beta vigente:" in output

    engine = create_sqlite_engine(database_path(destination))
    try:
        with session_scope(engine) as session:
            cases = {
                case.mention_id: case
                for case in mention_repair_cases(
                    session,
                    project_id="search_project",
                )
                if case.code == "duplicate_relocation"
            }
            assert cases[result["alpha_historical_id"]].duplicate_mention_ids == (
                result["alpha_current_id"],
            )
            assert cases[result["beta_historical_id"]].duplicate_mention_ids == (
                result["beta_current_id"],
            )
            assert cases[result["alpha_historical_id"]].can_resolve_duplicate
            assert cases[result["beta_historical_id"]].can_resolve_duplicate
    finally:
        engine.dispose()


def test_unresolved_validation_script_creates_ambiguous_and_absent_cases(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from scripts.create_unresolved_mention_validation_project import (
        create_validation_copy,
    )

    source = tmp_path / "source_project"
    destination = tmp_path / "unresolved_copy"
    _seed_search_project(source)

    result = create_validation_copy(source, destination, force=False)
    output = capsys.readouterr().out
    assert "Alertas esperadas: 2 × unresolved_relocation" in output
    assert "Mención ambigua:" in output
    assert "Mención ausente:" in output

    engine = create_sqlite_engine(database_path(destination))
    try:
        with session_scope(engine) as session:
            cases = {
                case.mention_id: case
                for case in mention_repair_cases(
                    session,
                    project_id="search_project",
                )
                if case.code == "unresolved_relocation"
            }
            assert result["ambiguous_mention_id"] in cases
            assert result["absent_mention_id"] in cases
            assert cases[result["ambiguous_mention_id"]].can_resolve_unresolved
            assert cases[result["absent_mention_id"]].can_resolve_unresolved

            ambiguous = session.get(
                EntityMention,
                result["ambiguous_mention_id"],
            )
            absent = session.get(EntityMention, result["absent_mention_id"])
            assert ambiguous is not None and absent is not None
            editable = session.get(EditableObject, result["object_id"])
            assert editable is not None
            assert len(
                exact_mention_occurrences(
                    editable.current_text,
                    ambiguous.mention_text,
                )
            ) == 2
            assert exact_mention_occurrences(
                editable.current_text,
                absent.mention_text,
            ) == []
    finally:
        engine.dispose()


def test_snapshot_divergence_validation_script_creates_two_decision_paths(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from scripts.create_snapshot_divergence_validation_project import (
        create_validation_copy,
    )

    source = tmp_path / "source_project"
    destination = tmp_path / "snapshot_divergence_copy"
    _seed_search_project(source)

    result = create_validation_copy(source, destination, force=False)
    output = capsys.readouterr().out
    assert "Alertas esperadas: 2 × snapshot_divergence" in output
    assert "Mención para conservar fila vigente:" in output
    assert "Mención para restaurar historial:" in output

    engine = create_sqlite_engine(database_path(destination))
    try:
        with session_scope(engine) as session:
            cases = {
                case.mention_id: case
                for case in mention_repair_cases(
                    session,
                    project_id="search_project",
                )
                if case.code == "snapshot_divergence"
            }
            assert result["adopt_mention_id"] in cases
            assert result["restore_mention_id"] in cases
            assert cases[result["adopt_mention_id"]].can_resolve_snapshot_divergence
            assert cases[result["restore_mention_id"]].can_resolve_snapshot_divergence
            assert cases[result["adopt_mention_id"]].snapshot_difference_fields == (
                "note",
            )
            assert set(
                cases[result["restore_mention_id"]].snapshot_difference_fields
            ) == {"authority_id", "status", "note"}
    finally:
        engine.dispose()


def test_grouped_validation_script_creates_joint_and_safe_cases(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from scripts.create_grouped_mention_validation_project import (
        create_validation_copy,
    )

    source = tmp_path / "source_project"
    destination = tmp_path / "grouped_copy"
    _seed_search_project(source)

    result = create_validation_copy(source, destination, force=False)
    output = capsys.readouterr().out
    assert "Alertas esperadas: 1 × duplicate_group + 3 × safe_relocation" in output
    assert "Entidad elegida: Entidad conjunta histórica beta" in output
    assert "Reubicaciones seguras agrupables: 3" in output

    engine = create_sqlite_engine(database_path(destination))
    try:
        with session_scope(engine) as session:
            cases = mention_repair_cases(session, project_id="search_project")
            group_cases = [case for case in cases if case.code == "duplicate_group"]
            safe_cases = [
                case
                for case in cases
                if case.code == "safe_relocation"
                and case.mention_id in set(result["safe_ids"])
            ]
            assert len(group_cases) == 1
            group_case = group_cases[0]
            assert group_case.can_resolve_duplicate_group
            assert {
                group_case.mention_id,
                *group_case.duplicate_mention_ids,
            } == set(result["group_ids"])
            assert len(safe_cases) == 3
            assert all(case.can_relocate for case in safe_cases)
            assert {case.object_id for case in safe_cases} == {result["object_id"]}
    finally:
        engine.dispose()
