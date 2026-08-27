from __future__ import annotations

import csv
import json
from pathlib import Path

from sqlalchemy import select
from xml.etree import ElementTree as ET

from archive_workbench.authorities import create_authority, create_mention
from archive_workbench.db import create_sqlite_engine, database_path, session_scope
from archive_workbench.db.models import (
    ArchivalUnit,
    DigitalObject,
    DigitalObjectUnitLink,
    DocumentPart,
)
from archive_workbench.identity import new_id
from archive_workbench.graph import (
    GRAPH_EDGE_TYPES,
    GraphEdge,
    GraphNode,
    GraphView,
    build_graph,
    export_graph,
    graph_consistency_issues,
    graph_layout,
    graph_parallel_edge_metadata,
    graph_payload,
)
from archive_workbench.graph_app import _DEFAULT_EDGE_TYPES
from archive_workbench.relations import create_entity_relation
from tests.test_search import _seed_search_project



def test_graph_structural_layers_are_opt_in_by_default() -> None:
    assert "hierarchy" not in _DEFAULT_EDGE_TYPES
    assert "document" not in _DEFAULT_EDGE_TYPES
    assert set(_DEFAULT_EDGE_TYPES) == set(GRAPH_EDGE_TYPES) - {"hierarchy", "document"}

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


def test_graph_contains_analytical_and_mention_edges(tmp_path: Path) -> None:
    root = tmp_path / "project"
    organization_id, person_id, relation_id = _seed_graph(root)
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            view = build_graph(session, project_id="search_project", max_nodes=100)
    finally:
        engine.dispose()
    assert {edge.edge_type for edge in view.edges} >= {"analytical", "mention"}
    assert any(edge.relation_id == relation_id for edge in view.edges)
    assert {node.record_id for node in view.nodes} >= {organization_id, person_id}
    mention_edge = next(edge for edge in view.edges if edge.edge_type == "mention")
    assert mention_edge.source_key == "doc_search"
    assert mention_edge.object_id is not None



def test_graph_layers_keep_archival_structure_documents_parts_and_roles_separate(tmp_path: Path) -> None:
    root = tmp_path / "project"
    organization_id, person_id, _relation_id = _seed_graph(root)
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            child = session.scalar(
                select(ArchivalUnit).where(ArchivalUnit.project_id == "search_project")
            )
            digital = session.scalar(
                select(DigitalObject).where(DigitalObject.project_id == "search_project")
            )
            assert child is not None and digital is not None
            parent = ArchivalUnit(
                id=new_id(),
                project_id="search_project",
                level_key="fondo",
                title="Fondo institucional",
                created_by="tests",
                updated_by="tests",
            )
            session.add(parent)
            session.flush()
            child.parent_id = parent.id
            link = DigitalObjectUnitLink(
                id=new_id(),
                digital_object_id=digital.id,
                archival_unit_id=child.id,
                relation_type="represents",
            )
            part = DocumentPart(
                id=new_id(),
                digital_object_id=digital.id,
                part_key="parte-1",
                title="Parte interna 1",
                part_type="document",
                page_start=1,
                page_end=1,
                page_sequence_json=[1],
                created_by="tests",
            )
            session.add_all([link, part])
            session.flush()
            producer = create_entity_relation(
                session,
                project_id="search_project",
                source_authority_id=organization_id,
                relation_kind="producer",
                relation_label="texto ignorado",
                target_kind="archival_unit",
                target_id=child.id,
                evidence_note="Inventario institucional",
                provenance_note="Guía del fondo, 1984",
                temporal_expression="1974 - 1976",
                created_by="tests",
            )
            manager = create_entity_relation(
                session,
                project_id="search_project",
                source_authority_id=person_id,
                relation_kind="manager",
                relation_label="texto ignorado",
                target_kind="archival_unit",
                target_id=child.id,
                evidence_note="Resolución administrativa",
                provenance_note="Expediente 12/1983",
                created_by="tests",
            )
            view = build_graph(session, project_id="search_project", max_nodes=100)

        edge_types = {edge.edge_type for edge in view.edges}
        assert edge_types >= {
            "hierarchy", "document", "part", "mention", "analytical", "producer", "manager"
        }
        node_kinds = {node.kind for node in view.nodes}
        assert node_kinds >= {"entity", "archival_unit", "digital_object", "document_part"}
        assert next(edge for edge in view.edges if edge.edge_id == producer.id).label == "produjo"
        assert next(edge for edge in view.edges if edge.edge_id == manager.id).label == "gestionó"
        document_edge = next(edge for edge in view.edges if edge.edge_id == link.id)
        assert document_edge.source == f"digital_object:{digital.id}"
        assert document_edge.target == f"archival_unit:{child.id}"
        assert document_edge.label == "representa"
        assert all(edge.provenance_note for edge in view.edges if edge.edge_type != "analytical")

        focused = build_graph(
            session,
            project_id="search_project",
            focus_node_id=f"digital_object:{digital.id}",
            max_depth=1,
            max_nodes=100,
        )
        assert f"digital_object:{digital.id}" in {node.node_id for node in focused.nodes}
        assert {edge.edge_type for edge in focused.edges} >= {"document", "part", "mention"}

        fondos = build_graph(
            session,
            project_id="search_project",
            archival_levels=("fondo",),
            max_nodes=100,
        )
        assert {node.subtype for node in fondos.nodes if node.kind == "archival_unit"} <= {"fondo"}
        assert not any(edge.edge_type in {"producer", "manager"} for edge in fondos.edges)
    finally:
        engine.dispose()

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
    from archive_workbench.relations import update_entity_relation

    root = tmp_path / "project"
    _organization_id, _person_id, relation_id = _seed_graph(root)
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            update_entity_relation(
                session,
                relation_id=relation_id,
                expected_revision=1,
                changed_by="tests",
                temporal_expression="1974 - 1976",
            )
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
    temporal_edge = next(item for item in payload["edges"] if item["relation_id"] == relation_id)
    assert temporal_edge["temporal_start"] == "1974-01-01"
    assert temporal_edge["temporal_end"] == "1976-12-31"
    with (output / "edges.csv").open(encoding="utf-8") as handle:
        assert len(list(csv.DictReader(handle))) == len(view.edges)
    assert ET.parse(output / "graph.graphml").getroot().tag.endswith("graphml")
    assert graph_layout(view) == graph_layout(view)


def test_graph_component_key_never_contains_reserved_delimiter() -> None:
    from archive_workbench.graph_canvas import _safe_component_key

    raw = "graph_canvas_analytical_mention_shared_entity__0_180_2"
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


def test_graph_filters_entities_and_analytical_relations_by_period(tmp_path: Path) -> None:
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
                edge_types=("analytical", "mention"),
                temporal_start=date(1975, 1, 1),
                temporal_end=date(1975, 12, 31),
                max_nodes=100,
            )
            outside = build_graph(
                session,
                project_id="search_project",
                edge_types=("analytical", "mention"),
                temporal_start=date(1985, 1, 1),
                temporal_end=date(1985, 12, 31),
                max_nodes=100,
            )
        analytical = next(edge for edge in in_period.edges if edge.relation_id == relation_id)
        assert analytical.temporal_expression == "03/1974 - 03/1976"
        assert any(node.record_id == organization_id for node in in_period.nodes)
        assert outside.edges == []
        assert outside.nodes == []
    finally:
        engine.dispose()


def _parallel_graph_view() -> GraphView:
    nodes = [
        GraphNode(
            node_id="entity:a",
            kind="entity",
            record_id="a",
            label="Entidad A",
            context="Contexto A",
            subtype="person",
            review_status="approved",
            lifecycle_status="active",
        ),
        GraphNode(
            node_id="entity:b",
            kind="entity",
            record_id="b",
            label="Entidad B",
            context="Contexto B",
            subtype="organization",
            review_status="approved",
            lifecycle_status="active",
        ),
    ]
    edges = [
        GraphEdge(
            edge_id="edge:3",
            source="entity:b",
            target="entity:a",
            edge_type="analytical",
            label="respondía a",
            explanation="Relación explícita registrada por el equipo.",
            evidence_note="Acta 3",
        ),
        GraphEdge(
            edge_id="edge:1",
            source="entity:a",
            target="entity:b",
            edge_type="analytical",
            label="investigaba a",
            explanation="Relación explícita registrada por el equipo.",
            evidence_note="Acta 1",
        ),
        GraphEdge(
            edge_id="edge:2",
            source="entity:a",
            target="entity:b",
            edge_type="mention",
            label="aparece en",
            explanation="Vínculo derivado de una mención aceptada.",
            source_key="doc-1",
            page_number=4,
        ),
    ]
    return GraphView(
        nodes=nodes,
        edges=edges,
        truncated=False,
        total_nodes_before_limit=2,
        total_edges_before_limit=3,
    )


def test_parallel_edges_receive_distinct_deterministic_slots_and_tooltips() -> None:
    view = _parallel_graph_view()
    first = graph_parallel_edge_metadata(view)
    second = graph_parallel_edge_metadata(
        GraphView(
            nodes=list(reversed(view.nodes)),
            edges=list(reversed(view.edges)),
            truncated=False,
            total_nodes_before_limit=2,
            total_edges_before_limit=3,
        )
    )
    assert first == second
    assert {row["parallel_count"] for row in first.values()} == {3}
    assert len({row["parallel_slot"] for row in first.values()}) == 3

    payload = graph_payload(view)
    edge_rows = {row["id"]: row for row in payload["edges"]}
    assert "Origen del vínculo" in edge_rows["edge:1"]["tooltip"]
    assert "Acta 1" in edge_rows["edge:1"]["tooltip"]
    assert "doc-1, página 4" in edge_rows["edge:2"]["tooltip"]
    assert all("parallel_slot" in row for row in payload["edges"])
    assert "Contexto A" in payload["nodes"][0]["tooltip"]


def test_graph_layout_separates_node_centers() -> None:
    nodes = [
        GraphNode(
            node_id=f"entity:{index}",
            kind="entity",
            record_id=str(index),
            label=f"Entidad {index}",
            context=None,
            subtype="person",
            review_status="approved",
            lifecycle_status="active",
        )
        for index in range(16)
    ]
    view = GraphView(
        nodes=nodes,
        edges=[],
        truncated=False,
        total_nodes_before_limit=len(nodes),
        total_edges_before_limit=0,
    )
    positions = graph_layout(view, width=1000, height=720)
    distances = []
    node_ids = sorted(positions)
    for index, left in enumerate(node_ids):
        for right in node_ids[index + 1 :]:
            lx, ly = positions[left]
            rx, ry = positions[right]
            distances.append(((lx - rx) ** 2 + (ly - ry) ** 2) ** 0.5)
    assert min(distances) >= 80


def test_graph_canvas_uses_curved_paths_arrows_and_automatic_label_displacement() -> None:
    import archive_workbench.graph_canvas as canvas

    assert "makeSvg('path'" in canvas._COMPONENT_JS
    assert "parallel_slot" in canvas._COMPONENT_JS
    assert "labelCollision" in canvas._COMPONENT_JS
    assert "addTitle(path" in canvas._COMPONENT_JS
    assert "labelPlacement" in canvas._COMPONENT_JS
    assert 'id="awg-arrowhead"' in canvas._COMPONENT_HTML
    assert "path.setAttribute('marker-end', 'url(#awg-arrowhead)')" in canvas._COMPONENT_JS
    assert "edge.edge_type !== 'shared_entity'" in canvas._COMPONENT_JS
    assert "targetNodeRadius" in canvas._COMPONENT_JS


def test_graph_canvas_supports_local_fullscreen_legend_and_quieter_structural_labels() -> None:
    import archive_workbench.graph_canvas as canvas

    assert 'data-action="fullscreen"' in canvas._COMPONENT_HTML
    assert 'data-action="legend"' in canvas._COMPONENT_HTML
    assert 'Abrir el grafo en pantalla completa' in canvas._COMPONENT_HTML
    assert 'Unidad del catálogo' in canvas._COMPONENT_HTML
    assert 'Estructura archivística' in canvas._COMPONENT_HTML
    assert '<div class="awg-root">' in canvas._COMPONENT_HTML
    assert "const root = parentElement.querySelector('.awg-root')" in canvas._COMPONENT_JS
    assert "root.classList.toggle('awg-detail-labels'" in canvas._COMPONENT_JS
    assert "parentElement.classList" not in canvas._COMPONENT_JS
    assert "root.requestFullscreen" in canvas._COMPONENT_JS
    assert "parentElement.requestFullscreen" not in canvas._COMPONENT_JS
    assert 'document.exitFullscreen' in canvas._COMPONENT_JS
    assert "legendButton.onclick" in canvas._COMPONENT_JS
    assert "'contiene'" in canvas._COMPONENT_JS
    assert "'contiene parte'" in canvas._COMPONENT_JS
    assert "'es parte de'" in canvas._COMPONENT_JS
    assert "'forma parte de'" in canvas._COMPONENT_JS
    assert "repetitiveStructuralLabels.has(normalizedEdgeLabel)" in canvas._COMPONENT_JS
    assert "['hierarchy', 'document', 'part'].includes(edge.edge_type)" in canvas._COMPONENT_JS
    assert "state.scale >= 1.45" in canvas._COMPONENT_JS
    assert '.awg-edge-label.repetitive { opacity: 0; }' in canvas._COMPONENT_CSS
    assert '.awg-edge-group:hover .awg-edge-label.repetitive' in canvas._COMPONENT_CSS

    local_controls = canvas._COMPONENT_JS[canvas._COMPONENT_JS.index('const syncLegend'):]
    assert "setTriggerValue(" not in local_controls


def test_graph_distance_filter_is_never_disabled_after_submit() -> None:
    source = (
        Path(__file__).parents[1] / "src" / "archive_workbench" / "graph_app.py"
    ).read_text(encoding="utf-8")
    block = source[
        source.index('"Cantidad de relaciones a mostrar desde el elemento central"') :
        source.index("temporal_enabled = st.checkbox")
    ]
    assert "disabled=" not in block
    assert "Sin foco, el mapa conserva todos los elementos" in block
