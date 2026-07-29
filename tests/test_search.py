from __future__ import annotations

from pathlib import Path

import pytest
from archive_workbench.db import create_sqlite_engine, database_path, session_scope, upgrade_database
from archive_workbench.db.models import (
    ArchivalUnit,
    DigitalObject,
    EditableObject,
    EditableObjectComment,
    EditableObjectTag,
    EditablePage,
    ExtractedObject,
    ExtractionPage,
    ExtractionRun,
    Project,
    SourceRegistration,
)
from archive_workbench.identity import new_id
from archive_workbench.review_app import _apply_pending_navigation, _highlight_search_snippet
from archive_workbench.search import (
    build_match_expression,
    rebuild_search_index,
    search_editable_objects,
    search_index_status,
)


def _seed_search_project(
    root: Path, *, revision: str = "head"
) -> tuple[str, str]:
    upgrade_database(root, revision=revision)
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            project = Project(id="search_project", name="Search", decisions_json={})
            unit = ArchivalUnit(
                id=new_id(),
                project_id=project.id,
                level_key="documento",
                title="Documento teatral",
                created_by="tests",
                updated_by="tests",
            )
            digital = DigitalObject(
                id=new_id(),
                project_id=project.id,
                media_type="pdf",
                original_filename="doc.pdf",
                sha256="a" * 64,
                byte_size=1,
                page_count=1,
            )
            session.add(project)
            session.flush()
            session.add_all([unit, digital])
            session.flush()
            session.add(
                SourceRegistration(
                    id=new_id(),
                    project_id=project.id,
                    source_type="test_corpus",
                    source_key="doc_search",
                    digital_object_id=digital.id,
                    archival_unit_id=unit.id,
                    source_payload_json={},
                    registered_by="tests",
                )
            )
            run = ExtractionRun(
                id=new_id(),
                digital_object_id=digital.id,
                profile_key="test",
                engine="tesseract_tsv",
                source_sha256=digital.sha256,
                options_json={},
                options_hash="b" * 64,
                status="completed",
                is_current=True,
                total_pages=1,
                total_objects=1,
                total_paragraphs=1,
                total_characters=20,
                warnings_json=[],
                created_by="tests",
            )
            session.add(run)
            session.flush()
            extraction_page = ExtractionPage(
                id=new_id(),
                extraction_run_id=run.id,
                page_number=1,
                object_count=1,
                character_count=20,
                status="completed",
            )
            session.add(extraction_page)
            session.flush()
            original = ExtractedObject(
                id=new_id(),
                origin_id=new_id(),
                extraction_run_id=run.id,
                digital_object_id=digital.id,
                page_number=1,
                order_index=0,
                object_type="paragraph",
                original_text="actividad subversiva",
                geometry_json=[],
                attributes_json={},
            )
            session.add(original)
            session.flush()
            editable_page = EditablePage(
                id=new_id(),
                digital_object_id=digital.id,
                page_number=1,
                source_extraction_run_id=run.id,
                source_extraction_page_id=extraction_page.id,
                status="active",
                review_status="reviewed",
                bootstrapped_by="tests",
            )
            session.add(editable_page)
            session.flush()
            editable = EditableObject(
                id=new_id(),
                editable_page_id=editable_page.id,
                digital_object_id=digital.id,
                page_number=1,
                source_extracted_object_id=original.id,
                source_origin_id=original.origin_id,
                current_text="La actividad teatral fue investigada",
                current_object_type="paragraph",
                current_order_index=0,
                current_geometry_json=[],
                current_attributes_json={},
                lifecycle_status="active",
                review_status="approved",
                revision_number=1,
                created_by="tests",
                updated_by="tests",
            )
            session.add(editable)
            session.flush()
            session.add_all(
                [
                    EditableObjectComment(
                        id=new_id(),
                        editable_object_id=editable.id,
                        body="Revisar el nombre de la institución",
                        created_by="tests",
                    ),
                    EditableObjectTag(
                        id=new_id(),
                        editable_object_id=editable.id,
                        tag="teatro",
                        normalized_tag="teatro",
                        tag_kind="thematic",
                        created_by="tests",
                    ),
                    EditableObjectTag(
                        id=new_id(),
                        editable_object_id=editable.id,
                        tag="vigilancia",
                        normalized_tag="vigilancia",
                        tag_kind="conceptual",
                        created_by="tests",
                    ),
                ]
            )
            return editable.id, editable_page.id
    finally:
        engine.dispose()


def test_match_expression_targets_requested_fields() -> None:
    expression = build_match_expression(
        "contenido ideológico",
        fields=["current_text", "comments"],
        match_mode="all",
    )
    assert 'current_text:"contenido"' in expression
    assert 'comments:"ideológico"' in expression
    assert " AND " in expression


def test_search_finds_current_original_comment_and_tag(tmp_path: Path) -> None:
    root = tmp_path / "project"
    object_id, _page_id = _seed_search_project(root)
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            current = search_editable_objects(session, query="teatral", fields=["current_text"])
            original = search_editable_objects(session, query="subversiva", fields=["original_text"])
            comment = search_editable_objects(session, query="institución", fields=["comments"])
            tag = search_editable_objects(session, query="vigilancia", fields=["tags"])
    finally:
        engine.dispose()
    assert current[0].object_id == object_id and current[0].match_scope == "Texto revisado"
    assert original[0].match_scope == "OCR original"
    assert comment[0].match_scope == "Comentario"
    assert tag[0].match_scope == "Etiqueta"


def test_search_filters_by_status_and_tag_kind(tmp_path: Path) -> None:
    root = tmp_path / "project"
    _seed_search_project(root)
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            rows = search_editable_objects(
                session,
                query="teatro",
                fields=["tags"],
                object_review_statuses=["approved"],
                page_review_statuses=["reviewed"],
                tag_kinds=["thematic"],
            )
            none = search_editable_objects(
                session,
                query="teatro",
                fields=["tags"],
                tag_kinds=["workflow"],
            )
    finally:
        engine.dispose()
    assert len(rows) == 1
    assert none == []


def test_database_triggers_mark_search_index_dirty(tmp_path: Path) -> None:
    root = tmp_path / "project"
    object_id, _page_id = _seed_search_project(root)
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            rebuild_search_index(session)
            assert search_index_status(session).is_current
            session.add(
                EditableObjectComment(
                    id=new_id(),
                    editable_object_id=object_id,
                    body="Comentario agregado después",
                    created_by="tests",
                )
            )
            session.flush()
            assert not search_index_status(session).is_current
            rows = search_editable_objects(session, query="después", fields=["comments"])
            assert len(rows) == 1
            assert search_index_status(session).is_current
    finally:
        engine.dispose()


def test_pending_search_navigation_selects_document_page_and_object() -> None:
    class Document:
        editable_pages = [1, 2]

    class FakeStreamlit:
        def __init__(self) -> None:
            self.session_state = {
                "review_pending_navigation": {
                    "source_key": "doc",
                    "page": 2,
                    "object_id": "object-2",
                }
            }

    st = FakeStreamlit()
    _apply_pending_navigation(st, {"doc": Document()})
    assert st.session_state["review_app_mode"] == "review"
    assert st.session_state["review_source_key"] == "doc"
    assert st.session_state["review_page_number"] == 2
    assert st.session_state["review_pending_object_id"] == "object-2"


def test_search_snippet_escapes_html_and_preserves_highlight() -> None:
    rendered = _highlight_search_snippet("<script> [[HIT]]teatro[[/HIT]]")
    assert "<script>" not in rendered
    assert "&lt;script&gt;" in rendered
    assert "<mark>teatro</mark>" in rendered


def test_partial_word_search_finds_substrings_inside_words(tmp_path: Path) -> None:
    root = tmp_path / "project"
    object_id, _page_id = _seed_search_project(root)
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            editable = session.get(EditableObject, object_id)
            assert editable is not None
            editable.current_text += " y una caracterización marxista"
            session.flush()
            rows = search_editable_objects(
                session,
                query="vestig",
                fields=["current_text"],
                partial_words=True,
            )
            marx = search_editable_objects(
                session,
                query="marx",
                fields=["current_text"],
                partial_words=True,
            )
            with pytest.raises(ValueError, match="al menos 3 caracteres"):
                search_editable_objects(
                    session,
                    query="in",
                    fields=["current_text"],
                    partial_words=True,
                )
    finally:
        engine.dispose()
    assert rows and rows[0].object_id == object_id
    assert marx and marx[0].object_id == object_id


def test_entities_are_searchable_by_canonical_name_alias_and_mention(tmp_path: Path) -> None:
    from archive_workbench.authorities import (
        add_authority_alias,
        create_authority,
        create_mention,
    )

    root = tmp_path / "project"
    object_id, _page_id = _seed_search_project(root)
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            authority = create_authority(
                session,
                project_id="search_project",
                entity_type="organization",
                preferred_name="Dirección de Inteligencia",
                created_by="tests",
            )
            add_authority_alias(
                session,
                authority_id=authority.id,
                alias="DIPBA",
                alias_type="acronym",
                created_by="tests",
            )
            create_mention(
                session,
                object_id=object_id,
                mention_text="actividad teatral",
                authority_id=authority.id,
                created_by="tests",
            )
        with session_scope(engine) as session:
            canonical = search_editable_objects(
                session, query="Inteligencia", fields=["entities"]
            )
            alias = search_editable_objects(session, query="DIPBA", fields=["entities"])
            partial = search_editable_objects(
                session,
                query="direc",
                fields=["entities"],
                partial_words=True,
            )
    finally:
        engine.dispose()
    assert canonical and canonical[0].object_id == object_id
    assert canonical[0].match_scope == "Nombre de entidad"
    assert alias and alias[0].match_scope == "Alias de entidad"
    assert partial and partial[0].object_id == object_id


def test_dictionary_suggestions_preserve_offsets_and_become_stale(tmp_path: Path) -> None:
    from archive_workbench.authorities import (
        add_authority_alias,
        authority_revision_rows,
        create_authority,
        mention_rows,
        suggest_dictionary_mentions,
    )

    root = tmp_path / "project"
    object_id, _page_id = _seed_search_project(root)
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            authority = create_authority(
                session,
                project_id="search_project",
                entity_type="other",
                preferred_name="Actividad teatral",
                created_by="tests",
            )
            add_authority_alias(
                session,
                authority_id=authority.id,
                alias="teatro",
                alias_type="variant",
                created_by="tests",
            )
            summary = suggest_dictionary_mentions(
                session, object_id=object_id, created_by="tests"
            )
            assert summary.created == 1
            revisions = authority_revision_rows(session, authority.id)
            assert [row.revision_number for row in revisions] == [1, 2]
            rows = mention_rows(session, object_id=object_id)
            assert rows[0].mention_text == "actividad teatral"
            assert rows[0].start_offset == 3
            assert rows[0].status == "pending"
            obj = session.get(EditableObject, object_id)
            assert obj is not None
            obj.current_text = "Texto cambiado"
            obj.revision_number += 1
            session.flush()
            stale = mention_rows(session, object_id=object_id)
            assert stale[0].is_stale
    finally:
        engine.dispose()


def test_accepted_mention_requires_authority_and_unlinking_requires_pending(
    tmp_path: Path,
) -> None:
    from archive_workbench.authorities import (
        create_authority,
        create_mention,
        mention_rows,
        update_mention,
    )

    root = tmp_path / "project"
    object_id, _page_id = _seed_search_project(root)
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            with pytest.raises(ValueError, match="vinculadas a una autoridad"):
                create_mention(
                    session,
                    object_id=object_id,
                    mention_text="actividad teatral",
                    created_by="tests",
                )

            authority = create_authority(
                session,
                project_id="search_project",
                entity_type="organization",
                preferred_name="Organismo de prueba",
                created_by="tests",
            )
            mention = create_mention(
                session,
                object_id=object_id,
                mention_text="actividad teatral",
                authority_id=authority.id,
                created_by="tests",
            )
            with pytest.raises(ValueError, match="vinculadas a una autoridad"):
                update_mention(
                    session,
                    mention_id=mention.id,
                    expected_revision=mention.revision,
                    authority_id=None,
                    changed_by="tests",
                )
            update_mention(
                session,
                mention_id=mention.id,
                expected_revision=mention.revision,
                authority_id=None,
                status="pending",
                changed_by="tests",
            )
            rows = mention_rows(session, object_id=object_id)
            assert rows[0].authority_id is None
            assert rows[0].status == "pending"
            assert rows[0].revision == 2
    finally:
        engine.dispose()


def test_active_mentions_cannot_duplicate_the_same_offsets(tmp_path: Path) -> None:
    from archive_workbench.authorities import create_authority, create_mention

    root = tmp_path / "project"
    object_id, _page_id = _seed_search_project(root)
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            first = create_authority(
                session,
                project_id="search_project",
                entity_type="organization",
                preferred_name="Organismo A",
                created_by="tests",
            )
            second = create_authority(
                session,
                project_id="search_project",
                entity_type="organization",
                preferred_name="Organismo B",
                created_by="tests",
            )
            create_mention(
                session,
                object_id=object_id,
                mention_text="actividad teatral",
                authority_id=first.id,
                status="pending",
                created_by="tests",
            )
            with pytest.raises(ValueError, match="mención activa sobre el mismo fragmento"):
                create_mention(
                    session,
                    object_id=object_id,
                    mention_text="actividad teatral",
                    authority_id=second.id,
                    status="pending",
                    created_by="tests",
                )
    finally:
        engine.dispose()


def test_explicit_relations_are_searchable_from_entity_mentions(tmp_path: Path) -> None:
    from archive_workbench.authorities import create_authority, create_mention
    from archive_workbench.relations import create_entity_relation

    root = tmp_path / "project"
    object_id, _page_id = _seed_search_project(root)
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            source = create_authority(
                session,
                project_id="search_project",
                entity_type="person",
                preferred_name="Juan Pérez",
                created_by="tests",
            )
            target = create_authority(
                session,
                project_id="search_project",
                entity_type="organization",
                preferred_name="Partido Obrero",
                created_by="tests",
            )
            create_mention(
                session,
                object_id=object_id,
                mention_text="actividad teatral",
                authority_id=source.id,
                created_by="tests",
            )
            create_entity_relation(
                session,
                project_id="search_project",
                source_authority_id=source.id,
                relation_label="integró",
                target_kind="entity",
                target_id=target.id,
                created_by="tests",
            )
        with session_scope(engine) as session:
            rows = search_editable_objects(
                session,
                query="Partido Obrero",
                fields=["entities"],
                match_mode="phrase",
            )
    finally:
        engine.dispose()
    assert rows and rows[0].object_id == object_id
    assert rows[0].match_scope == "Relación analítica"


def test_scan_command_reports_entity_uuid_confusion_and_scan_all_is_safe(tmp_path: Path) -> None:
    from archive_workbench.authorities import (
        create_authority,
        suggest_dictionary_mentions,
        suggest_dictionary_mentions_all,
    )

    root = tmp_path / "project"
    _object_id, _page_id = _seed_search_project(root)
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            entity = create_authority(
                session,
                project_id="search_project",
                entity_type="organization",
                preferred_name="Entidad ausente del texto",
                created_by="tests",
            )
            with pytest.raises(ValueError, match="corresponde a la entidad"):
                suggest_dictionary_mentions(
                    session, object_id=entity.id, created_by="tests"
                )
            summary = suggest_dictionary_mentions_all(
                session,
                project_id="search_project",
                created_by="tests",
            )
            assert summary.objects_scanned == 1
            assert summary.created == 0
    finally:
        engine.dispose()


def test_literal_search_filters_results_by_entity_period(tmp_path: Path) -> None:
    from datetime import date
    from archive_workbench.authorities import create_authority, create_mention

    root = tmp_path / "project"
    object_id, _page_id = _seed_search_project(root)
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            entity = create_authority(
                session,
                project_id="search_project",
                entity_type="event",
                preferred_name="Actividad teatral",
                temporal_expression="años setenta",
                created_by="tests",
            )
            create_mention(
                session,
                object_id=object_id,
                mention_text="teatral",
                authority_id=entity.id,
                created_by="tests",
            )
            rebuild_search_index(session)
            in_period = search_editable_objects(
                session,
                query="teatral",
                fields=["current_text"],
                temporal_start=date(1975, 1, 1),
                temporal_end=date(1975, 12, 31),
            )
            outside = search_editable_objects(
                session,
                query="teatral",
                fields=["current_text"],
                temporal_start=date(1985, 1, 1),
                temporal_end=date(1985, 12, 31),
            )
        assert [row.object_id for row in in_period] == [object_id]
        assert outside == []
    finally:
        engine.dispose()
