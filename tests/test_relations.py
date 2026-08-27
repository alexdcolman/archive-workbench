from __future__ import annotations

from pathlib import Path

from archive_workbench.authorities import create_authority
from archive_workbench.catalog import ensure_project
from archive_workbench.catalog_management import create_archival_unit
from archive_workbench.db import create_sqlite_engine, database_path, session_scope, upgrade_database
from archive_workbench.decisions import load_decisions
from archive_workbench.relations import (
    create_entity_relation,
    delete_entity_relation,
    entity_relation_revision_rows,
    entity_relation_rows,
    relation_target_choices,
    update_entity_relation,
)


def _setup(tmp_path: Path):
    root = tmp_path / "project"
    upgrade_database(root)
    decisions = load_decisions(Path(__file__).parents[1] / "config/decisions.yaml")
    engine = create_sqlite_engine(database_path(root))
    with session_scope(engine) as session:
        ensure_project(session, decisions)
    return root, decisions, engine


def test_entity_relation_is_versioned_and_can_be_deactivated(tmp_path: Path) -> None:
    _root, decisions, engine = _setup(tmp_path)
    try:
        with session_scope(engine) as session:
            source = create_authority(
                session,
                project_id=decisions.project_id,
                entity_type="person",
                preferred_name="Persona A",
                created_by="tests",
            )
            target = create_authority(
                session,
                project_id=decisions.project_id,
                entity_type="organization",
                preferred_name="Organización B",
                created_by="tests",
            )
            relation = create_entity_relation(
                session,
                project_id=decisions.project_id,
                source_authority_id=source.id,
                relation_label="integró",
                target_kind="entity",
                target_id=target.id,
                created_by="tests",
            )
            update_entity_relation(
                session,
                relation_id=relation.id,
                expected_revision=1,
                evidence_note="Informe, página 3",
                review_status="approved",
                lifecycle_status="inactive",
                changed_by="tests",
            )
            rows = entity_relation_rows(
                session,
                project_id=decisions.project_id,
                authority_id=source.id,
                include_inactive=True,
            )
            revisions = entity_relation_revision_rows(session, relation.id)
        assert rows[0].evidence_note == "Informe, página 3"
        assert rows[0].review_status == "approved"
        assert rows[0].lifecycle_status == "inactive"
        assert [row.operation for row in revisions] == ["update", "create"]
    finally:
        engine.dispose()



def test_archival_role_can_be_deleted_as_error_without_erasing_history(tmp_path: Path) -> None:
    _root, decisions, engine = _setup(tmp_path)
    try:
        with session_scope(engine) as session:
            source = create_authority(
                session,
                project_id=decisions.project_id,
                entity_type="organization",
                preferred_name="Productor equivocado",
                created_by="tests",
            )
            unit = create_archival_unit(
                session,
                decisions=decisions,
                project_id=decisions.project_id,
                parent_id=None,
                level_key="archivo",
                title="Archivo",
                created_by="tests",
            )
            relation = create_entity_relation(
                session,
                project_id=decisions.project_id,
                source_authority_id=source.id,
                relation_label="produjo",
                relation_kind="producer",
                target_kind="archival_unit",
                target_id=unit.id,
                evidence_note="Carga inicial",
                provenance_note="Catálogo",
                created_by="tests",
            )
            delete_entity_relation(
                session,
                relation_id=relation.id,
                expected_revision=1,
                changed_by="tests",
                note="Vínculo cargado por error",
            )
            visible = entity_relation_rows(
                session,
                project_id=decisions.project_id,
                archival_unit_id=unit.id,
                relation_kinds=("producer", "manager"),
                include_inactive=True,
            )
            revisions = entity_relation_revision_rows(session, relation.id)
            persisted = session.get(type(relation), relation.id)

        assert visible == []
        assert persisted is not None
        assert persisted.lifecycle_status == "deleted"
        assert persisted.source_authority_id == source.id
        assert [row.operation for row in revisions] == ["delete", "create"]
        assert revisions[0].note == "Vínculo cargado por error"
    finally:
        engine.dispose()

def test_relation_target_can_be_changed_and_is_versioned(tmp_path: Path) -> None:
    _root, decisions, engine = _setup(tmp_path)
    try:
        with session_scope(engine) as session:
            source = create_authority(
                session,
                project_id=decisions.project_id,
                entity_type="organization",
                preferred_name="Organismo de origen",
                created_by="tests",
            )
            original_target = create_authority(
                session,
                project_id=decisions.project_id,
                entity_type="organization",
                preferred_name="Destino inicial",
                created_by="tests",
            )
            replacement = create_archival_unit(
                session,
                decisions=decisions,
                project_id=decisions.project_id,
                parent_id=None,
                level_key="archivo",
                title="Destino corregido",
                created_by="tests",
            )
            relation = create_entity_relation(
                session,
                project_id=decisions.project_id,
                source_authority_id=source.id,
                relation_label="aparece en",
                target_kind="entity",
                target_id=original_target.id,
                created_by="tests",
            )
            update_entity_relation(
                session,
                relation_id=relation.id,
                expected_revision=1,
                target_kind="archival_unit",
                target_id=replacement.id,
                changed_by="tests",
                note="Corrección del destino",
            )
            rows = entity_relation_rows(
                session,
                project_id=decisions.project_id,
                authority_id=source.id,
                include_inactive=True,
            )
            revisions = entity_relation_revision_rows(session, relation.id)

        assert rows[0].target_kind == "archival_unit"
        assert rows[0].target_id == replacement.id
        assert rows[0].target_label == "Destino corregido"
        assert rows[0].revision == 2
        assert revisions[0].snapshot["target_archival_unit_id"] == replacement.id
        assert revisions[0].snapshot["target_authority_id"] is None
        assert revisions[0].note == "Corrección del destino"
        assert revisions[1].snapshot["target_authority_id"] == original_target.id
    finally:
        engine.dispose()


def test_relation_can_target_catalog_unit(tmp_path: Path) -> None:
    _root, decisions, engine = _setup(tmp_path)
    try:
        with session_scope(engine) as session:
            entity = create_authority(
                session,
                project_id=decisions.project_id,
                entity_type="organization",
                preferred_name="Organismo",
                created_by="tests",
            )
            unit = create_archival_unit(
                session,
                decisions=decisions,
                project_id=decisions.project_id,
                parent_id=None,
                level_key="archivo",
                title="Archivo documental",
                created_by="tests",
            )
            choices = relation_target_choices(
                session,
                project_id=decisions.project_id,
                target_kind="archival_unit",
            )
            relation = create_entity_relation(
                session,
                project_id=decisions.project_id,
                source_authority_id=entity.id,
                relation_label="aparece en",
                target_kind="archival_unit",
                target_id=unit.id,
                created_by="tests",
            )
            rows = entity_relation_rows(
                session,
                project_id=decisions.project_id,
                authority_id=entity.id,
            )
        assert any(choice.target_id == unit.id for choice in choices)
        assert relation.target_archival_unit_id == unit.id
        assert rows[0].target_label == "Archivo documental"
    finally:
        engine.dispose()


def test_authority_ui_defaults_candidate_search_to_approved_pages() -> None:
    source = (
        Path(__file__).parents[1]
        / "src"
        / "archive_workbench"
        / "authority_app.py"
    ).read_text(encoding="utf-8")

    assert '"Estado de las páginas"' in source
    assert 'default=["approved"]' in source
    assert "page_review_statuses=tuple(candidate_page_statuses)" in source
    assert "Estado de revisión que tendrán las menciones que incorpores" in source


def test_transversal_entity_candidates_show_alias_and_can_be_included(tmp_path: Path) -> None:
    from archive_workbench.authorities import (
        add_authority_alias,
        authority_mention_candidates,
        include_authority_mention_candidates,
        mention_rows,
    )
    from tests.test_search import _seed_search_project
    from archive_workbench.db.models import EditableObject

    root = tmp_path / "candidate_project"
    object_id, _page_id = _seed_search_project(root)
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            obj = session.get(EditableObject, object_id)
            obj.current_text = "La DIPBA investigó a militantes. La Dirección de Inteligencia archivó el informe."
            entity = create_authority(
                session,
                project_id="search_project",
                entity_type="organization",
                preferred_name="Dirección de Inteligencia",
                created_by="tests",
            )
            add_authority_alias(
                session,
                authority_id=entity.id,
                alias="DIPBA",
                alias_type="acronym",
                created_by="tests",
            )
            candidates = authority_mention_candidates(
                session,
                authority_id=entity.id,
                include_existing=True,
                page_review_statuses=("approved",),
            )
            assert {row.match_kind for row in candidates} == {"preferred", "alias"}
            alias_candidate = next(row for row in candidates if row.match_kind == "alias")
            assert alias_candidate.matched_surface == "DIPBA"
            summary = include_authority_mention_candidates(
                session,
                authority_id=entity.id,
                candidate_keys=[row.candidate_key for row in candidates],
                created_by="tests",
                page_review_statuses=("approved",),
            )
            mentions = mention_rows(session, authority_id=entity.id)
        assert summary.created == 2
        assert len(mentions) == 2
        assert {row.mention_text for row in mentions} == {"DIPBA", "Dirección de Inteligencia"}
    finally:
        engine.dispose()


def test_transversal_entity_candidates_default_to_approved_pages(tmp_path: Path) -> None:
    from archive_workbench.authorities import authority_mention_candidates
    from archive_workbench.db.models import EditableObject, EditablePage
    from tests.test_search import _seed_search_project

    root = tmp_path / "candidate_quality_project"
    object_id, page_id = _seed_search_project(root)
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            obj = session.get(EditableObject, object_id)
            page = session.get(EditablePage, page_id)
            assert obj is not None
            assert page is not None
            obj.current_text = "Destino comun completamente distinto"
            entity = create_authority(
                session,
                project_id="search_project",
                entity_type="organization",
                preferred_name="Destino comun",
                created_by="tests",
            )

            page.review_status = "needs_review"
            assert authority_mention_candidates(
                session, authority_id=entity.id
            ) == []
            assert len(
                authority_mention_candidates(
                    session,
                    authority_id=entity.id,
                    page_review_statuses=("needs_review",),
                    broader_quality_scope_confirmed=True,
                    quality_scope_reason="Prueba explícita de alcance ampliado.",
                )
            ) == 1

            page.review_status = "approved"
            approved = authority_mention_candidates(
                session, authority_id=entity.id
            )

        assert len(approved) == 1
        assert approved[0].mention_text == "Destino comun"
    finally:
        engine.dispose()


def test_temporal_ranges_are_normalized_and_filter_entities_and_relations(tmp_path: Path) -> None:
    from datetime import date
    from archive_workbench.authorities import authority_rows

    _root, decisions, engine = _setup(tmp_path)
    try:
        with session_scope(engine) as session:
            source = create_authority(
                session,
                project_id=decisions.project_id,
                entity_type="organization",
                preferred_name="Dirección A",
                temporal_expression="años setenta",
                temporal_note="Fecha aproximada",
                created_by="tests",
            )
            target = create_authority(
                session,
                project_id=decisions.project_id,
                entity_type="organization",
                preferred_name="Ministerio B",
                temporal_expression="desde 1980",
                created_by="tests",
            )
            relation = create_entity_relation(
                session,
                project_id=decisions.project_id,
                source_authority_id=source.id,
                relation_label="dependió de",
                target_kind="entity",
                target_id=target.id,
                temporal_expression="03/1974 - 03/1976",
                created_by="tests",
            )
            entity_1975 = authority_rows(
                session,
                project_id=decisions.project_id,
                temporal_start=date(1975, 1, 1),
                temporal_end=date(1975, 12, 31),
            )
            relation_1975 = entity_relation_rows(
                session,
                project_id=decisions.project_id,
                temporal_start=date(1975, 1, 1),
                temporal_end=date(1975, 12, 31),
            )
            relation_1985 = entity_relation_rows(
                session,
                project_id=decisions.project_id,
                temporal_start=date(1985, 1, 1),
                temporal_end=date(1985, 12, 31),
            )
        assert [row.authority_id for row in entity_1975] == [source.id]
        assert relation_1975[0].relation_id == relation.id
        assert relation_1975[0].temporal_start == date(1974, 3, 1)
        assert relation_1975[0].temporal_end == date(1976, 3, 31)
        assert relation_1985 == []
    finally:
        engine.dispose()


def test_transversal_candidates_link_existing_unlinked_mention_without_duplication(
    tmp_path: Path,
) -> None:
    from archive_workbench.authorities import (
        authority_mention_candidates,
        create_mention,
        include_authority_mention_candidates,
        mention_rows,
    )
    from archive_workbench.db.models import EditableObject
    from tests.test_search import _seed_search_project

    root = tmp_path / "candidate_link_project"
    object_id, _page_id = _seed_search_project(root)
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            obj = session.get(EditableObject, object_id)
            assert obj is not None
            obj.current_text = "La SIDE remitió el parte."
            authority = create_authority(
                session,
                project_id="search_project",
                entity_type="organization",
                preferred_name="SIDE",
                created_by="tests",
            )
            orphan = create_mention(
                session,
                object_id=object_id,
                mention_text="SIDE",
                status="pending",
                created_by="tests",
            )

            candidates = authority_mention_candidates(
                session,
                authority_id=authority.id,
                include_existing=True,
                page_review_statuses=("approved",),
            )
            assert len(candidates) == 1
            assert candidates[0].can_link_existing
            assert not candidates[0].already_included

            summary = include_authority_mention_candidates(
                session,
                authority_id=authority.id,
                candidate_keys=[candidates[0].candidate_key],
                status="accepted",
                created_by="tests",
                page_review_statuses=("approved",),
            )
            mentions = mention_rows(session, object_id=object_id)

        assert summary.created == 0
        assert summary.linked_existing == 1
        assert summary.already_present == 0
        assert len(mentions) == 1
        assert mentions[0].mention_id == orphan.id
        assert mentions[0].authority_id == authority.id
        assert mentions[0].status == "accepted"
        assert mentions[0].revision == 2
    finally:
        engine.dispose()


def test_transversal_candidates_report_conflict_with_another_authority(
    tmp_path: Path,
) -> None:
    import pytest

    from archive_workbench.authorities import (
        authority_mention_candidates,
        create_mention,
        include_authority_mention_candidates,
        mention_rows,
    )
    from archive_workbench.db.models import EditableObject
    from tests.test_search import _seed_search_project

    root = tmp_path / "candidate_conflict_project"
    object_id, _page_id = _seed_search_project(root)
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            obj = session.get(EditableObject, object_id)
            assert obj is not None
            obj.current_text = "La SIDE remitió el parte."
            target = create_authority(
                session,
                project_id="search_project",
                entity_type="organization",
                preferred_name="SIDE",
                created_by="tests",
            )
            other = create_authority(
                session,
                project_id="search_project",
                entity_type="organization",
                preferred_name="Otra institución",
                created_by="tests",
            )
            create_mention(
                session,
                object_id=object_id,
                mention_text="SIDE",
                authority_id=other.id,
                status="pending",
                created_by="tests",
            )

            candidates = authority_mention_candidates(
                session,
                authority_id=target.id,
                include_existing=True,
                page_review_statuses=("approved",),
            )
            assert len(candidates) == 1
            assert candidates[0].has_authority_conflict
            assert candidates[0].existing_authority_name == "Otra institución"

            with pytest.raises(ValueError, match="ya está vinculada"):
                include_authority_mention_candidates(
                    session,
                    authority_id=target.id,
                    candidate_keys=[candidates[0].candidate_key],
                    created_by="tests",
                    page_review_statuses=("approved",),
                )
            mentions = mention_rows(session, object_id=object_id)

        assert len(mentions) == 1
        assert mentions[0].authority_id == other.id
    finally:
        engine.dispose()


def test_transversal_candidates_detect_same_fragment_across_text_revisions(
    tmp_path: Path,
) -> None:
    import pytest

    from archive_workbench.authorities import (
        add_authority_alias,
        authority_mention_candidates,
        create_mention,
    )
    from archive_workbench.db.models import EditableObject, EditableObjectRevision, EntityMention
    from archive_workbench.graph import graph_consistency_issues
    from archive_workbench.identity import new_id
    from tests.test_search import _seed_search_project

    root = tmp_path / "candidate_revision_project"
    object_id, _page_id = _seed_search_project(root)
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            obj = session.get(EditableObject, object_id)
            assert obj is not None
            obj.current_text = "Destino comun completamente distinto"
            session.add(
                EditableObjectRevision(
                    id=new_id(),
                    editable_object_id=obj.id,
                    revision_number=1,
                    base_revision_number=None,
                    operation="bootstrap",
                    text=obj.current_text,
                    object_type=obj.current_object_type,
                    order_index=obj.current_order_index,
                    geometry_json=obj.current_geometry_json,
                    attributes_json=obj.current_attributes_json,
                    lifecycle_status=obj.lifecycle_status,
                    document_part_id=obj.document_part_id,
                    created_by="tests",
                )
            )
            original = create_authority(
                session,
                project_id="search_project",
                entity_type="organization",
                preferred_name="Destino comun",
                created_by="tests",
            )
            alternative = create_authority(
                session,
                project_id="search_project",
                entity_type="organization",
                preferred_name="Destino alternativo",
                created_by="tests",
            )
            add_authority_alias(
                session,
                authority_id=alternative.id,
                alias="Destino comun",
                alias_type="variant",
                created_by="tests",
            )
            create_mention(
                session,
                object_id=obj.id,
                mention_text="Destino comun",
                authority_id=original.id,
                status="accepted",
                created_by="tests",
            )

            obj.current_text = "Texto agregado. Destino comun completamente distinto"
            obj.revision_number = 2
            session.add(
                EditableObjectRevision(
                    id=new_id(),
                    editable_object_id=obj.id,
                    revision_number=2,
                    base_revision_number=1,
                    operation="edit",
                    text=obj.current_text,
                    object_type=obj.current_object_type,
                    order_index=obj.current_order_index,
                    geometry_json=obj.current_geometry_json,
                    attributes_json=obj.current_attributes_json,
                    lifecycle_status=obj.lifecycle_status,
                    document_part_id=obj.document_part_id,
                    created_by="tests",
                )
            )
            session.flush()

            candidates = authority_mention_candidates(
                session,
                authority_id=alternative.id,
                include_existing=True,
                page_review_statuses=("approved",),
            )
            assert len(candidates) == 1
            assert candidates[0].has_authority_conflict
            assert candidates[0].existing_authority_name == "Destino comun"

            with pytest.raises(ValueError, match="mención activa sobre el mismo fragmento"):
                create_mention(
                    session,
                    object_id=obj.id,
                    mention_text="Destino comun",
                    authority_id=alternative.id,
                    status="pending",
                    created_by="tests",
                )

            # Simula un duplicado histórico ya existente para validar el diagnóstico.
            duplicate = EntityMention(
                id=new_id(),
                editable_object_id=obj.id,
                authority_id=alternative.id,
                mention_text="Destino comun",
                normalized_text="destino comun",
                start_offset=16,
                end_offset=29,
                object_revision_number=2,
                status="pending",
                source="dictionary",
                confidence=1.0,
                note="Duplicado histórico de prueba",
                created_by="tests",
                updated_by="tests",
                revision=1,
            )
            session.add(duplicate)
            session.flush()
            issues = graph_consistency_issues(session, project_id="search_project")
            assert any(issue.code == "duplicate_mention" for issue in issues)
    finally:
        engine.dispose()


def test_archival_roles_are_controlled_versioned_and_filterable_by_unit(tmp_path: Path) -> None:
    import pytest

    _root, decisions, engine = _setup(tmp_path)
    try:
        with session_scope(engine) as session:
            authority = create_authority(
                session,
                project_id=decisions.project_id,
                entity_type="organization",
                preferred_name="Dirección General del Archivo",
                created_by="tests",
            )
            unit = create_archival_unit(
                session,
                decisions=decisions,
                project_id=decisions.project_id,
                parent_id=None,
                level_key="archivo",
                title="Archivo institucional",
                created_by="tests",
            )
            with pytest.raises(ValueError, match="evidencia"):
                create_entity_relation(
                    session,
                    project_id=decisions.project_id,
                    source_authority_id=authority.id,
                    relation_kind="producer",
                    relation_label="texto libre",
                    target_kind="archival_unit",
                    target_id=unit.id,
                    provenance_note="Inventario 1984",
                    created_by="tests",
                )
            with pytest.raises(ValueError, match="procedencia"):
                create_entity_relation(
                    session,
                    project_id=decisions.project_id,
                    source_authority_id=authority.id,
                    relation_kind="manager",
                    relation_label="texto libre",
                    target_kind="archival_unit",
                    target_id=unit.id,
                    evidence_note="Resolución 12/1983",
                    created_by="tests",
                )

            producer = create_entity_relation(
                session,
                project_id=decisions.project_id,
                source_authority_id=authority.id,
                relation_kind="producer",
                relation_label="texto libre no canónico",
                target_kind="archival_unit",
                target_id=unit.id,
                evidence_note="Inventario institucional",
                provenance_note="Guía del fondo, 1984",
                temporal_expression="1974 - 1976",
                created_by="tests",
            )
            manager = create_entity_relation(
                session,
                project_id=decisions.project_id,
                source_authority_id=authority.id,
                relation_kind="manager",
                relation_label="otro texto libre",
                target_kind="archival_unit",
                target_id=unit.id,
                evidence_note="Resolución administrativa",
                provenance_note="Expediente 12/1983",
                temporal_expression="desde 1983",
                created_by="tests",
            )
            update_entity_relation(
                session,
                relation_id=manager.id,
                expected_revision=1,
                evidence_note="Resolución administrativa, foja 4",
                provenance_note="Expediente 12/1983, Archivo General",
                review_status="approved",
                changed_by="tests",
                note="Se precisó la evidencia",
            )
            rows = entity_relation_rows(
                session,
                project_id=decisions.project_id,
                archival_unit_id=unit.id,
                relation_kinds=("producer", "manager"),
                include_inactive=True,
            )
            histories = {
                row.relation_id: entity_relation_revision_rows(session, row.relation_id)
                for row in rows
            }

        by_kind = {row.relation_kind: row for row in rows}
        assert by_kind["producer"].relation_label == "produjo"
        assert by_kind["manager"].relation_label == "gestionó"
        assert by_kind["producer"].source_authority_id == by_kind["manager"].source_authority_id
        assert by_kind["producer"].temporal_expression == "1974 - 1976"
        assert by_kind["manager"].temporal_expression == "desde 1983"
        assert by_kind["manager"].provenance_note == "Expediente 12/1983, Archivo General"
        assert [row.operation for row in histories[manager.id]] == ["update", "create"]
        assert histories[manager.id][0].snapshot["relation_kind"] == "manager"
        assert histories[manager.id][0].snapshot["provenance_note"] == (
            "Expediente 12/1983, Archivo General"
        )
        assert producer.id in histories
    finally:
        engine.dispose()


def test_authority_and_relation_profiles_are_structured_and_queryable(tmp_path: Path) -> None:
    from archive_workbench.authorities import authority_rows

    _root, decisions, engine = _setup(tmp_path)
    try:
        with session_scope(engine) as session:
            source = create_authority(
                session,
                project_id=decisions.project_id,
                entity_type="organization",
                preferred_name="SIDE",
                temporal_expression="1946 - 2015; desde 2024",
                profile_json={
                    "legal_status": "Organismo estatal",
                    "functions_activities": "Inteligencia de Estado",
                },
                created_by="tests",
            )
            target = create_authority(
                session,
                project_id=decisions.project_id,
                entity_type="organization",
                preferred_name="Presidencia",
                created_by="tests",
            )
            relation = create_entity_relation(
                session,
                project_id=decisions.project_id,
                source_authority_id=source.id,
                relation_label="dependió de",
                target_kind="entity",
                target_id=target.id,
                temporal_expression="1946 - 2015; desde 2024",
                profile_json={
                    "archival_category": "hierarchical",
                    "context": "Dependencia institucional",
                },
                created_by="tests",
            )
            source_rows = authority_rows(session, project_id=decisions.project_id, query="SIDE")
            relation_rows = entity_relation_rows(
                session,
                project_id=decisions.project_id,
                authority_id=source.id,
                include_inactive=True,
            )
        source_row = next(row for row in source_rows if row.authority_id == source.id)
        assert source_row.profile["legal_status"] == "Organismo estatal"
        assert source_row.temporal_precision == "set"
        assert relation_rows[0].relation_id == relation.id
        assert relation_rows[0].profile["archival_category"] == "hierarchical"
        assert relation_rows[0].profile["context"] == "Dependencia institucional"
    finally:
        engine.dispose()
