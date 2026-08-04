from __future__ import annotations

from pathlib import Path

from sqlalchemy import select

from archive_workbench.db import create_sqlite_engine, database_path, session_scope
from archive_workbench.db.models import EditableObject, EditablePage
from archive_workbench.identity import new_id
from archive_workbench.semantic_search import (
    SemanticProfileValues,
    build_semantic_index,
    save_semantic_profile,
    semantic_index_status,
    semantic_search,
)
from tests.test_search import _seed_search_project


class FakeSemanticBackend:
    @staticmethod
    def _vector(text: str) -> list[float]:
        value = text.casefold()
        cultural = sum(term in value for term in ("teat", "cultur", "investig", "vigil"))
        economic = sum(term in value for term in ("carne", "precio", "econom", "mercado"))
        if cultural == 0 and economic == 0:
            return [0.5, 0.5]
        return [float(cultural), float(economic)]

    def encode_documents(self, texts, *, batch_size: int):
        return [self._vector(text) for text in texts]

    def encode_queries(self, texts, *, batch_size: int):
        return [self._vector(text) for text in texts]


def _seed_second_object(root: Path) -> str:
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            page = session.scalar(select(EditablePage))
            assert page is not None
            row = EditableObject(
                id=new_id(),
                editable_page_id=page.id,
                digital_object_id=page.digital_object_id,
                page_number=page.page_number,
                source_extracted_object_id=None,
                source_origin_id=None,
                current_text="El precio de la carne aumentó en el mercado local",
                current_object_type="paragraph",
                current_order_index=1,
                current_geometry_json=[],
                current_attributes_json={"manual": True},
                lifecycle_status="active",
                review_status="approved",
                revision_number=1,
                created_by="tests",
                updated_by="tests",
            )
            session.add(row)
            session.flush()
            return row.id
    finally:
        engine.dispose()


def test_semantic_index_build_search_and_staleness(tmp_path: Path) -> None:
    root = tmp_path / "project"
    cultural_id, _page_id = _seed_search_project(root)
    economic_id = _seed_second_object(root)
    backend = FakeSemanticBackend()
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            profile = save_semantic_profile(
                session,
                project_id="search_project",
                values=SemanticProfileValues(
                    name="Prueba semántica",
                    model_name="fake/model",
                    model_revision="test",
                    aggregation_level="object",
                    query_prefix="",
                    document_prefix="",
                ),
                changed_by="tests",
            )
            summary = build_semantic_index(
                session,
                project_root=root,
                project_id="search_project",
                profile=profile,
                created_by="tests",
                backend=backend,
                batch_size=2,
            )
            assert summary.vector_count == 2
            assert summary.dimensions == 2
            status = semantic_index_status(
                session,
                project_root=root,
                project_id="search_project",
                profile=profile,
            )
            assert status.is_current
            results = semantic_search(
                session,
                project_root=root,
                project_id="search_project",
                profile=profile,
                query="vigilancia cultural",
                top_k=2,
                backend=backend,
            )
            assert results[0].object_ids == [cultural_id]
            assert results[1].object_ids == [economic_id]
            row = session.get(EditableObject, cultural_id)
            row.current_text += " y censurada"
            row.revision_number += 1
            session.flush()
            stale = semantic_index_status(
                session,
                project_root=root,
                project_id="search_project",
                profile=profile,
            )
            assert not stale.is_current
            assert "corpus cambió" in stale.reason
    finally:
        engine.dispose()


def test_profile_change_invalidates_index_without_deleting_files(tmp_path: Path) -> None:
    root = tmp_path / "project"
    _seed_search_project(root)
    backend = FakeSemanticBackend()
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            profile = save_semantic_profile(
                session,
                project_id="search_project",
                values=SemanticProfileValues(name="Perfil", model_name="fake/model"),
                changed_by="tests",
            )
            summary = build_semantic_index(
                session,
                project_root=root,
                project_id="search_project",
                profile=profile,
                created_by="tests",
                backend=backend,
            )
            assert summary.vectors_path.is_file()
            save_semantic_profile(
                session,
                project_id="search_project",
                profile_id=profile.id,
                values=SemanticProfileValues(
                    name="Perfil", model_name="fake/model", chunk_size=900
                ),
                changed_by="tests",
            )
            status = semantic_index_status(
                session,
                project_root=root,
                project_id="search_project",
                profile=profile,
            )
            assert not status.is_current
            assert "perfil cambió" in status.reason
            assert summary.vectors_path.is_file()
    finally:
        engine.dispose()


def test_semantic_search_can_post_filter_by_entity_period(tmp_path: Path) -> None:
    from datetime import date
    from archive_workbench.authorities import create_authority, create_mention

    root = tmp_path / "project"
    cultural_id, _page_id = _seed_search_project(root)
    _seed_second_object(root)
    backend = FakeSemanticBackend()
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            entity = create_authority(
                session,
                project_id="search_project",
                entity_type="event",
                preferred_name="Actividad cultural",
                temporal_expression="1970 - 1979",
                created_by="tests",
            )
            create_mention(
                session,
                object_id=cultural_id,
                mention_text="teatral",
                authority_id=entity.id,
                created_by="tests",
            )
            profile = save_semantic_profile(
                session,
                project_id="search_project",
                values=SemanticProfileValues(
                    name="Temporal", model_name="fake/model", model_revision="test",
                    query_prefix="", document_prefix="",
                ),
                changed_by="tests",
            )
            build_semantic_index(
                session,
                project_root=root,
                project_id="search_project",
                profile=profile,
                created_by="tests",
                backend=backend,
            )
            rows = semantic_search(
                session,
                project_root=root,
                project_id="search_project",
                profile=profile,
                query="vigilancia cultural",
                top_k=10,
                temporal_start=date(1975, 1, 1),
                temporal_end=date(1975, 12, 31),
                backend=backend,
            )
        assert [row.object_ids for row in rows] == [[cultural_id]]
    finally:
        engine.dispose()


def test_authority_alias_change_does_not_invalidate_object_semantic_index(tmp_path: Path) -> None:
    from archive_workbench.authorities import add_authority_alias, create_authority

    root = tmp_path / "project"
    _seed_search_project(root)
    backend = FakeSemanticBackend()
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            profile = save_semantic_profile(
                session,
                project_id="search_project",
                values=SemanticProfileValues(
                    name="Objetos",
                    model_name="fake/model",
                    aggregation_level="object",
                ),
                changed_by="tests",
            )
            build_semantic_index(
                session,
                project_root=root,
                project_id="search_project",
                profile=profile,
                created_by="tests",
                backend=backend,
            )
            authority = create_authority(
                session,
                project_id="search_project",
                entity_type="organization",
                preferred_name="Organismo de prueba",
                created_by="tests",
            )
            add_authority_alias(
                session,
                authority_id=authority.id,
                alias="ODP",
                alias_type="acronym",
                created_by="tests",
            )
            status = semantic_index_status(
                session,
                project_root=root,
                project_id="search_project",
                profile=profile,
            )
            assert status.is_current
            assert status.reason == "Índice actualizado"
    finally:
        engine.dispose()


def test_semantic_execution_requires_current_quality_authorization(tmp_path: Path) -> None:
    import pytest

    root = tmp_path / "authorized_semantic_project"
    _seed_search_project(root)
    backend = FakeSemanticBackend()
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            profile = save_semantic_profile(
                session,
                project_id="search_project",
                values=SemanticProfileValues(
                    name="Autorización semántica",
                    model_name="fake/model",
                    query_prefix="",
                    document_prefix="",
                ),
                changed_by="tests",
            )
            profile.chunk_size = 777
            session.flush()
            with pytest.raises(ValueError, match="autorización vigente"):
                build_semantic_index(
                    session,
                    project_root=root,
                    project_id="search_project",
                    profile=profile,
                    created_by="tests",
                    backend=backend,
                )

            save_semantic_profile(
                session,
                project_id="search_project",
                profile_id=profile.id,
                values=SemanticProfileValues(
                    name=profile.name,
                    model_name="fake/model",
                    query_prefix="",
                    document_prefix="",
                    chunk_size=777,
                ),
                changed_by="tests",
            )
            summary = build_semantic_index(
                session,
                project_root=root,
                project_id="search_project",
                profile=profile,
                created_by="tests",
                backend=backend,
            )
            assert summary.vector_count == 1
    finally:
        engine.dispose()
