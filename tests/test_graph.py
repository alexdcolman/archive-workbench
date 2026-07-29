from __future__ import annotations

import csv
import json
from pathlib import Path
from xml.etree import ElementTree as ET

from archive_workbench.authorities import create_authority, create_mention
from archive_workbench.db import create_sqlite_engine, database_path, session_scope
from archive_workbench.graph import (
    build_graph,
    export_graph,
    graph_consistency_issues,
    graph_layout,
)
from archive_workbench.relations import create_entity_relation
from tests.test_search import _seed_search_project


def _seed_graph(root: Path) -> tuple[str, str, str]:
    object_id, _page_id = _seed_search_project(root)
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            organization = create_authority(
                session,
                project_id="search_project",
                entity_type="organization",
                preferred_name="Dirección de Inteligencia",
                created_by="tests",
                review_status="approved",
            )
            person = create_authority(
                session,
                project_id="search_project",
                entity_type="person",
                preferred_name="Persona investigada",
                created_by="tests",
            )
            editable = session.get(__import__("archive_workbench.db.models", fromlist=["EditableObject"]).EditableObject, object_id)
            assert editable is not None
            editable.current_text += " por la Dirección de Inteligencia"
            editable.revision_number += 1
            session.flush()
            create_mention(
                session,
                object_id=object_id,
                mention_text="Dirección de Inteligencia",
                authority_id=organization.id,
                created_by="tests",
            )
            relation = create_entity_relation(
                session,
                project_id="search_project",
                source_authority_id=person.id,
                relation_label="fue investigada por",
                target_kind="entity",
                target_id=organization.id,
                created_by="tests",
            )
            return organization.id, person.id, relation.id
    finally:
        engine.dispose()


def test_graph_contains_explicit_and_mention_edges(tmp_path: Path) -> None:
    root = tmp_path / "project"
    organization_id, person_id, relation_id = _seed_graph(root)
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            view = build_graph(session, project_id="search_project", max_nodes=100)
    finally:
        engine.dispose()
    assert {edge.edge_type for edge in view.edges} >= {"explicit", "mention"}
    assert any(edge.relation_id == relation_id for edge in view.edges)
    assert {node.record_id for node in view.nodes} >= {organization_id, person_id}
    mention_edge = next(edge for edge in view.edges if edge.edge_type == "mention")
    assert mention_edge.source_key == "doc_search"
    assert mention_edge.object_id is not None


def test_graph_focus_keeps_requested_neighborhood(tmp_path: Path) -> None:
    root = tmp_path / "project"
    organization_id, _person_id, _relation_id = _seed_graph(root)
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            view = build_graph(
                session,
                project_id="search_project",
                focus_node_id=f"entity:{organization_id}",
                max_depth=1,
                max_nodes=100,
            )
    finally:
        engine.dispose()
    assert f"entity:{organization_id}" in {node.node_id for node in view.nodes}
    assert all(
        edge.source in {node.node_id for node in view.nodes}
        and edge.target in {node.node_id for node in view.nodes}
        for edge in view.edges
    )


def test_consistency_detects_duplicate_and_missing_evidence(tmp_path: Path) -> None:
    root = tmp_path / "project"
    organization_id, person_id, relation_id = _seed_graph(root)
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            create_entity_relation(
                session,
                project_id="search_project",
                source_authority_id=person_id,
                relation_label="  fue   investigada POR ",
                target_kind="entity",
                target_id=organization_id,
                created_by="tests",
            )
            issues = graph_consistency_issues(session, project_id="search_project")
    finally:
        engine.dispose()
    assert any(issue.code == "duplicate_relation" and issue.relation_id == relation_id for issue in issues)
    assert sum(issue.code == "missing_evidence" for issue in issues) == 2


def test_graph_export_writes_json_csv_and_graphml(tmp_path: Path) -> None:
    root = tmp_path / "project"
    _seed_graph(root)
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            view = build_graph(session, project_id="search_project", max_nodes=100)
            issues = graph_consistency_issues(session, project_id="search_project")
    finally:
        engine.dispose()
    output = tmp_path / "export"
    paths = export_graph(view, output_dir=output, issues=issues)
    assert {path.name for path in paths} == {
        "graph.json", "nodes.csv", "edges.csv", "graph.graphml", "consistency_issues.csv"
    }
    payload = json.loads((output / "graph.json").read_text(encoding="utf-8"))
    assert len(payload["nodes"]) == len(view.nodes)
    with (output / "edges.csv").open(encoding="utf-8") as handle:
        assert len(list(csv.DictReader(handle))) == len(view.edges)
    assert ET.parse(output / "graph.graphml").getroot().tag.endswith("graphml")
    assert graph_layout(view) == graph_layout(view)


def test_graph_component_key_never_contains_reserved_delimiter() -> None:
    from archive_workbench.graph_canvas import _safe_component_key

    raw = "graph_canvas_explicit_mention_shared_entity__0_180_2"
    first = _safe_component_key(raw)
    assert "__" not in first
    assert first.startswith("awg-")
    assert first == _safe_component_key(raw)
    assert first != _safe_component_key(raw + "changed")


def test_graph_canvas_passes_safe_key_to_renderer(monkeypatch) -> None:
    from types import SimpleNamespace
    from archive_workbench.graph import GraphView
    import archive_workbench.graph_canvas as canvas

    captured: dict[str, object] = {}

    def fake_renderer(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(selected_node=None, selected_edge=None)

    monkeypatch.setattr(canvas, "_renderer", lambda: fake_renderer)
    view = GraphView(
        nodes=[],
        edges=[],
        truncated=False,
        total_nodes_before_limit=0,
        total_edges_before_limit=0,
    )
    assert canvas.interactive_graph_canvas(
        view,
        selected_node=None,
        selected_edge=None,
        key="graph_canvas_shared_entity__0_180_1",
    ) == (None, None)
    assert isinstance(captured["key"], str)
    assert "__" not in captured["key"]


def test_graph_filters_entities_and_explicit_relations_by_period(tmp_path: Path) -> None:
    from datetime import date
    from archive_workbench.authorities import update_authority
    from archive_workbench.relations import update_entity_relation

    root = tmp_path / "project"
    organization_id, _person_id, relation_id = _seed_graph(root)
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            organization = session.get(
                __import__("archive_workbench.db.models", fromlist=["AuthorityRecord"]).AuthorityRecord,
                organization_id,
            )
            relation = session.get(
                __import__("archive_workbench.db.models", fromlist=["EntityRelation"]).EntityRelation,
                relation_id,
            )
            update_authority(
                session,
                authority_id=organization.id,
                expected_revision=organization.revision,
                temporal_expression="años setenta",
                changed_by="tests",
            )
            update_entity_relation(
                session,
                relation_id=relation.id,
                expected_revision=relation.revision,
                temporal_expression="03/1974 - 03/1976",
                changed_by="tests",
            )
            in_period = build_graph(
                session,
                project_id="search_project",
                temporal_start=date(1975, 1, 1),
                temporal_end=date(1975, 12, 31),
                max_nodes=100,
            )
            outside = build_graph(
                session,
                project_id="search_project",
                temporal_start=date(1985, 1, 1),
                temporal_end=date(1985, 12, 31),
                max_nodes=100,
            )
        explicit = next(edge for edge in in_period.edges if edge.relation_id == relation_id)
        assert explicit.temporal_expression == "03/1974 - 03/1976"
        assert any(node.record_id == organization_id for node in in_period.nodes)
        assert outside.edges == []
        assert outside.nodes == []
    finally:
        engine.dispose()
