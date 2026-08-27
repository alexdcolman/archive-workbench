from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import func, select

from archive_workbench.authorities import add_authority_alias, create_authority
from archive_workbench.authority_dictionary import (
    DICTIONARY_SCHEMA_VERSION,
    apply_authority_dictionary,
    authority_dictionary_example,
    authority_dictionary_schema,
    export_authority_dictionary_bytes,
    load_authority_dictionary,
    validate_authority_dictionary,
)
from archive_workbench.catalog import ensure_project
from archive_workbench.db import create_sqlite_engine, database_path, session_scope, upgrade_database
from archive_workbench.db.models import (
    AuthorityAlias,
    AuthorityRecord,
    AuthorityRevision,
    EntityRelation,
)
from archive_workbench.decisions import load_decisions
from archive_workbench.relations import create_entity_relation


def _setup(tmp_path: Path):
    root = tmp_path / "project"
    upgrade_database(root)
    decisions = load_decisions(Path(__file__).parents[1] / "config" / "decisions.yaml")
    engine = create_sqlite_engine(database_path(root))
    with session_scope(engine) as session:
        ensure_project(session, decisions)
    return root, decisions, engine


def _payload(*, existing_id: str | None = None) -> dict:
    cpm_resolution = (
        {"action": "use_existing", "authority_id": existing_id}
        if existing_id
        else {"action": "auto"}
    )
    return {
        "schema_version": "1.0",
        "dictionary_id": "control_disc02",
        "dictionary_name": "Control DISC-02",
        "target_project_id": "*",
        "source": {
            "title": "Diccionario controlado",
            "organization": "Equipo de prueba",
            "url": "https://example.org/diccionario-controlado",
        },
        "authorities": [
            {
                "local_id": "cpm",
                "entity_type": "organization",
                "preferred_name": "Comisión Provincial por la Memoria",
                "description": "Esta descripción no debe sobrescribir la ficha existente.",
                "aliases": [
                    {
                        "value": "Comisión por la Memoria",
                        "alias_type": "variant",
                    }
                ],
                "resolution": cpm_resolution,
            },
            {
                "local_id": "investigadora",
                "entity_type": "person",
                "preferred_name": "Investigadora de prueba",
                "aliases": [{"value": "Dra. Prueba", "alias_type": "title"}],
                "temporal_expression": "desde 1975",
            },
            {
                "local_id": "publicacion",
                "entity_type": "work",
                "preferred_name": "Publicación de prueba",
                "characteristics": {
                    "tipo": "artículo",
                    "idiomas": ["es", "en"],
                },
            },
        ],
        "relations": [
            {
                "local_id": "rel_autoria",
                "source_local_id": "investigadora",
                "relation_label": "publicó",
                "target_kind": "authority",
                "target_local_id": "publicacion",
                "evidence": {
                    "note": "Página legal de la publicación.",
                    "source_url": "https://example.org/publicacion",
                },
                "temporal_expression": "1978",
            }
        ],
    }


def test_schema_and_example_are_versioned_and_document_the_core_contract() -> None:
    schema = authority_dictionary_schema()
    example = authority_dictionary_example()

    assert schema["$id"].endswith("authority-dictionary-1.1.json")
    assert schema["properties"]["schema_version"]["default"] == DICTIONARY_SCHEMA_VERSION
    assert schema["properties"]["schema_version"]["enum"] == ["1.0", "1.1"]
    assert example["schema_version"] == DICTIONARY_SCHEMA_VERSION
    assert example["authorities"][0]["aliases"][0]["alias_type"] == "acronym"
    assert example["relations"][0]["evidence"]["note"]


def test_dictionary_validation_and_transactional_roundtrip_are_idempotent(tmp_path: Path) -> None:
    _root, decisions, engine = _setup(tmp_path)
    try:
        with session_scope(engine) as session:
            existing = create_authority(
                session,
                project_id=decisions.project_id,
                entity_type="organization",
                preferred_name="Comisión Provincial por la Memoria",
                description="Descripción canónica existente.",
                created_by="tests",
            )
            add_authority_alias(
                session,
                authority_id=existing.id,
                alias="CPM",
                alias_type="acronym",
                created_by="tests",
            )
            existing_id = existing.id

        source = json.dumps(_payload(existing_id=existing_id), ensure_ascii=False).encode()
        with session_scope(engine) as session:
            report = validate_authority_dictionary(
                session,
                project_id=decisions.project_id,
                source=source,
            )
            assert report.valid
            assert report.authority_create_count == 2
            assert report.authority_reuse_count == 1
            assert report.alias_add_count == 2
            assert report.relation_create_count == 1
            assert any(issue.code == "existing_authority_not_overwritten" for issue in report.issues)

        with session_scope(engine) as session:
            result = apply_authority_dictionary(
                session,
                project_id=decisions.project_id,
                source=source,
                changed_by="Alex",
            )
            assert result.authorities_created == 2
            assert result.authorities_reused == 1
            assert result.aliases_added == 2
            assert result.relations_created == 1

        with session_scope(engine) as session:
            authority_count = session.scalar(select(func.count()).select_from(AuthorityRecord))
            alias_count = session.scalar(select(func.count()).select_from(AuthorityAlias))
            relation_count = session.scalar(select(func.count()).select_from(EntityRelation))
            existing = session.get(AuthorityRecord, existing_id)
            assert authority_count == 3
            assert alias_count == 3
            assert relation_count == 1
            assert existing is not None
            assert existing.description == "Descripción canónica existente."
            work = session.scalar(
                select(AuthorityRecord).where(
                    AuthorityRecord.preferred_name == "Publicación de prueba"
                )
            )
            assert work is not None
            assert "Características importadas:" in (work.description or "")
            assert "- idiomas: es, en" in (work.description or "")

        with session_scope(engine) as session:
            second_report = validate_authority_dictionary(
                session,
                project_id=decisions.project_id,
                source=source,
            )
            assert second_report.valid
            assert second_report.authority_create_count == 0
            assert second_report.authority_reuse_count == 3
            assert second_report.alias_add_count == 0
            assert second_report.relation_create_count == 0
            assert second_report.relation_skip_count == 1
            second = apply_authority_dictionary(
                session,
                project_id=decisions.project_id,
                source=source,
                changed_by="Alex",
            )
            assert second.authorities_created == 0
            assert second.aliases_added == 0
            assert second.relations_created == 0
            assert second.relations_skipped == 1

        with session_scope(engine) as session:
            assert session.scalar(select(func.count()).select_from(AuthorityRecord)) == 3
            assert session.scalar(select(func.count()).select_from(AuthorityAlias)) == 3
            assert session.scalar(select(func.count()).select_from(EntityRelation)) == 1
            revisions = session.scalars(
                select(AuthorityRevision).where(AuthorityRevision.authority_id == existing_id)
            ).all()
            assert any("control_disc02" in (revision.note or "") for revision in revisions)
    finally:
        engine.dispose()


def test_ambiguous_existing_surface_requires_explicit_resolution(tmp_path: Path) -> None:
    _root, decisions, engine = _setup(tmp_path)
    try:
        with session_scope(engine) as session:
            existing = create_authority(
                session,
                project_id=decisions.project_id,
                entity_type="organization",
                preferred_name="Dirección de Inteligencia",
                created_by="tests",
            )
            add_authority_alias(
                session,
                authority_id=existing.id,
                alias="DIPPBA",
                alias_type="acronym",
                created_by="tests",
            )

        payload = {
            "schema_version": "1.0",
            "dictionary_id": "conflicto",
            "dictionary_name": "Conflicto",
            "source": {"title": "Control"},
            "authorities": [
                {
                    "local_id": "dippba_persona",
                    "entity_type": "person",
                    "preferred_name": "DIPPBA",
                }
            ],
            "relations": [],
        }
        with session_scope(engine) as session:
            report = validate_authority_dictionary(
                session,
                project_id=decisions.project_id,
                source=json.dumps(payload).encode(),
            )
            assert not report.valid
            issue = next(
                issue
                for issue in report.issues
                if issue.code == "authority_conflict_requires_resolution"
            )
            assert issue.candidate_ids == (existing.id,)

        payload["authorities"][0]["resolution"] = {"action": "create_new"}
        with session_scope(engine) as session:
            report = validate_authority_dictionary(
                session,
                project_id=decisions.project_id,
                source=json.dumps(payload).encode(),
            )
            assert report.valid
            assert report.authority_create_count == 1
            assert any(issue.code == "explicit_create_near_existing" for issue in report.issues)
    finally:
        engine.dispose()


def test_relation_without_evidence_is_rejected_by_the_versioned_format() -> None:
    payload = authority_dictionary_example()
    payload["relations"][0]["evidence"] = {}

    try:
        load_authority_dictionary(json.dumps(payload).encode())
    except ValueError as exc:
        assert "Cada relación necesita evidencia" in str(exc)
    else:
        raise AssertionError("El diccionario sin evidencia debía ser rechazado")


def test_invalid_dictionary_does_not_write_partial_authorities(tmp_path: Path) -> None:
    _root, decisions, engine = _setup(tmp_path)
    payload = _payload()
    payload["relations"][0]["target_local_id"] = "ausente"
    source = json.dumps(payload, ensure_ascii=False).encode()
    try:
        with session_scope(engine) as session:
            report = validate_authority_dictionary(
                session,
                project_id=decisions.project_id,
                source=source,
            )
            assert not report.valid
            assert any(issue.code == "unknown_relation_target" for issue in report.issues)
            try:
                apply_authority_dictionary(
                    session,
                    project_id=decisions.project_id,
                    source=source,
                    changed_by="tests",
                )
            except ValueError:
                pass
            else:
                raise AssertionError("La importación inválida debía fallar")
        with session_scope(engine) as session:
            assert session.scalar(select(func.count()).select_from(AuthorityRecord)) == 0
            assert session.scalar(select(func.count()).select_from(EntityRelation)) == 0
    finally:
        engine.dispose()


def test_relation_cannot_reference_the_same_local_authority(tmp_path: Path) -> None:
    _root, decisions, engine = _setup(tmp_path)
    payload = {
        "schema_version": "1.0",
        "dictionary_id": "self_relation",
        "dictionary_name": "Self relation",
        "source": {"title": "Control"},
        "authorities": [
            {
                "local_id": "misma",
                "entity_type": "person",
                "preferred_name": "Misma persona",
            }
        ],
        "relations": [
            {
                "local_id": "rel_misma",
                "source_local_id": "misma",
                "relation_label": "conoce a",
                "target_kind": "authority",
                "target_local_id": "misma",
                "evidence": {"note": "Control negativo."},
            }
        ],
    }
    try:
        with session_scope(engine) as session:
            report = validate_authority_dictionary(
                session,
                project_id=decisions.project_id,
                source=json.dumps(payload).encode(),
            )
            assert not report.valid
            assert any(issue.code == "self_relation" for issue in report.issues)
    finally:
        engine.dispose()


def test_exported_authority_relation_template_updates_existing_descriptions(tmp_path: Path) -> None:
    _root, decisions, engine = _setup(tmp_path)
    try:
        with session_scope(engine) as session:
            source = create_authority(
                session,
                project_id=decisions.project_id,
                entity_type="organization",
                preferred_name="Organismo de prueba",
                description="Historia original",
                temporal_expression="1946 - 2015; desde 2024",
                profile_json={"places": "Buenos Aires"},
                review_status="reviewed",
                created_by="tests",
            )
            target = create_authority(
                session,
                project_id=decisions.project_id,
                entity_type="organization",
                preferred_name="Organismo relacionado",
                profile_json={"legal_status": "Organismo estatal"},
                created_by="tests",
            )
            add_authority_alias(
                session,
                authority_id=source.id,
                alias="OP",
                alias_type="acronym",
                created_by="tests",
            )
            relation = create_entity_relation(
                session,
                project_id=decisions.project_id,
                source_authority_id=source.id,
                relation_label="dependió de",
                target_kind="entity",
                target_id=target.id,
                relation_kind="analytical",
                evidence_note="Decreto original",
                temporal_expression="1950 - 1960",
                profile_json={"archival_category": "hierarchical", "description": "Descripción original"},
                review_status="reviewed",
                created_by="tests",
            )
            source_id = source.id
            relation_id = relation.id

        with session_scope(engine) as session:
            exported = export_authority_dictionary_bytes(
                session, project_id=decisions.project_id
            )
        payload = json.loads(exported)
        assert payload["schema_version"] == "1.1"
        source_payload = next(
            item for item in payload["authorities"]
            if item["resolution"]["authority_id"] == source_id
        )
        relation_payload = next(
            item for item in payload["relations"]
            if item["resolution"]["relation_id"] == relation_id
        )
        assert source_payload["resolution"]["action"] == "update_existing"
        assert source_payload["profile"] == {"places": "Buenos Aires"}
        assert relation_payload["resolution"]["action"] == "update_existing"
        assert relation_payload["profile"]["description"] == "Descripción original"

        source_payload["description"] = "Historia revisada desde plantilla"
        source_payload["profile"]["places"] = "Buenos Aires; La Plata"
        relation_payload["evidence"]["note"] = "Decreto revisado"
        relation_payload["profile"]["description"] = "Descripción revisada desde plantilla"
        edited = json.dumps(payload, ensure_ascii=False).encode()

        with session_scope(engine) as session:
            report = validate_authority_dictionary(
                session, project_id=decisions.project_id, source=edited
            )
            assert report.valid
            assert report.authority_update_count == 2
            assert report.relation_update_count == 1
            result = apply_authority_dictionary(
                session,
                project_id=decisions.project_id,
                source=edited,
                changed_by="Alex",
            )
            assert result.authorities_updated == 2
            assert result.relations_updated == 1

        with session_scope(engine) as session:
            updated_source = session.get(AuthorityRecord, source_id)
            updated_relation = session.get(EntityRelation, relation_id)
            assert updated_source is not None
            assert updated_source.description == "Historia revisada desde plantilla"
            assert updated_source.profile_json == {"places": "Buenos Aires; La Plata"}
            assert updated_relation is not None
            assert updated_relation.evidence_note == "Decreto revisado"
            assert updated_relation.profile_json["description"] == "Descripción revisada desde plantilla"
    finally:
        engine.dispose()
