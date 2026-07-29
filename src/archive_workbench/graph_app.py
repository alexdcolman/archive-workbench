from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

from archive_workbench.authorities import AUTHORITY_TYPES
from archive_workbench.db import create_sqlite_engine, session_scope
from archive_workbench.graph import (
    GRAPH_EDGE_TYPES,
    GraphEdge,
    GraphNode,
    build_graph,
    export_graph,
    graph_consistency_issues,
)
from archive_workbench.graph_canvas import interactive_graph_canvas
from archive_workbench.temporal import format_temporal_range

_EDGE_LABELS = {
    "explicit": "Relaciones explícitas",
    "mention": "Menciones aceptadas",
    "shared_entity": "Entidades compartidas",
}
_NODE_LABELS = {
    "entity": "Entidad",
    "archival_unit": "Unidad archivística",
    "document_part": "Parte interna",
}
_ENTITY_TYPE_LABELS = {
    "person": "Persona",
    "organization": "Organismo / institución",
    "place": "Lugar",
    "event": "Acontecimiento",
    "work": "Obra / publicación",
    "other": "Otra entidad",
}
_REVIEW_LABELS = {
    "unreviewed": "Sin revisar",
    "reviewed": "Revisado",
    "approved": "Aprobado",
}
_SEVERITY_LABELS = {"error": "Error", "warning": "Advertencia", "info": "Información"}


def _go_to(st, *, mode: str, selection_key: str | None = None, selection: str | None = None) -> None:
    st.session_state["review_pending_app_mode"] = mode
    if selection_key and selection:
        st.session_state[selection_key] = selection
    st.rerun()


def _navigate_node(st, node: GraphNode) -> None:
    if node.kind == "entity":
        _go_to(
            st,
            mode="authorities",
            selection_key="authority_pending_selection",
            selection=node.record_id,
        )
        return
    if node.kind == "archival_unit":
        _go_to(
            st,
            mode="catalog",
            selection_key="catalog_pending_unit_id",
            selection=node.record_id,
        )
        return
    if node.kind == "document_part" and node.source_key:
        st.session_state["review_pending_navigation"] = {
            "source_key": node.source_key,
            "page": node.page_number or 1,
            "object_id": node.object_id,
        }
        st.rerun()


def _navigate_edge_evidence(st, edge: GraphEdge) -> None:
    if edge.source_key:
        st.session_state["review_pending_navigation"] = {
            "source_key": edge.source_key,
            "page": edge.page_number or 1,
            "object_id": edge.object_id,
        }
        st.rerun()


def render_graph_view(
    st,
    *,
    project_root: Path,
    db_path: Path,
    project_id: str,
    actor: str,
) -> None:
    st.header("Grafo documental")
    st.caption(
        "El grafo es una vista derivada: no guarda datos paralelos ni crea relaciones nuevas. "
        "Las aristas continuas son afirmaciones explícitas; las menciones y entidades compartidas "
        "se calculan a partir del corpus y explican siempre de dónde salen."
    )

    # Opciones de foco sobre un grafo amplio; no se renderizan todavía.
    engine = create_sqlite_engine(db_path)
    try:
        with session_scope(engine) as session:
            broad = build_graph(
                session,
                project_id=project_id,
                max_nodes=500,
                include_inactive=True,
                include_pending_mentions=True,
            )
    except (ValueError, RuntimeError, OSError) as exc:
        st.error(str(exc))
        return
    finally:
        engine.dispose()

    focus_options = [""] + [row.node_id for row in broad.nodes]
    focus_map = {row.node_id: row for row in broad.nodes}
    with st.expander("Filtros del grafo", expanded=True):
        with st.form("graph_filters"):
            left, middle, right = st.columns(3)
            with left:
                edge_types = st.multiselect(
                    "Tipos de arista",
                    options=list(GRAPH_EDGE_TYPES),
                    default=list(GRAPH_EDGE_TYPES),
                    format_func=lambda value: _EDGE_LABELS[value],
                )
                entity_types = st.multiselect(
                    "Tipos de entidad",
                    options=list(AUTHORITY_TYPES),
                    default=list(AUTHORITY_TYPES),
                    format_func=lambda value: _ENTITY_TYPE_LABELS[value],
                )
            with middle:
                review_statuses = st.multiselect(
                    "Revisión de relaciones explícitas",
                    options=["unreviewed", "reviewed", "approved"],
                    default=["unreviewed", "reviewed", "approved"],
                    format_func=lambda value: _REVIEW_LABELS[value],
                )
                include_inactive = st.checkbox("Incluir relaciones y entidades inactivas")
                include_pending_mentions = st.checkbox(
                    "Incluir menciones pendientes",
                    help="Las menciones pendientes se muestran como evidencia provisional; no equivalen a una aceptación humana.",
                )
            with right:
                min_shared = st.number_input(
                    "Entidades compartidas mínimas",
                    min_value=1,
                    max_value=20,
                    value=1,
                    step=1,
                )
                max_nodes = st.selectbox("Máximo de nodos", options=[60, 120, 180, 300], index=2)
                focus_node_id = st.selectbox(
                    "Centrar en",
                    options=focus_options,
                    format_func=lambda value: (
                        "Todo el grafo"
                        if not value
                        else f"{_NODE_LABELS[focus_map[value].kind]} · {focus_map[value].label}"
                    ),
                )
                depth_value = st.selectbox(
                    "Distancia desde el centro",
                    options=[1, 2, 3, 0],
                    format_func=lambda value: "Sin límite" if value == 0 else f"{value} salto(s)",
                    disabled=not bool(focus_node_id),
                )
            temporal_enabled = st.checkbox(
                "Filtrar por período de entidades o relaciones",
                help=(
                    "Conserva entidades cuyo período se superpone con el intervalo y también "
                    "las entidades necesarias para mostrar relaciones vigentes en ese período."
                ),
            )
            temporal_cols = st.columns(3)
            temporal_from = temporal_cols[0].date_input(
                "Desde", value=date(1900, 1, 1), key="graph_temporal_from"
            )
            temporal_to = temporal_cols[1].date_input(
                "Hasta", value=date.today(), key="graph_temporal_to"
            )
            temporal_include_undated = temporal_cols[2].checkbox(
                "Incluir sin fecha", value=False, key="graph_temporal_undated"
            )
            st.form_submit_button("Aplicar filtros", type="primary")

    engine = create_sqlite_engine(db_path)
    try:
        with session_scope(engine) as session:
            view = build_graph(
                session,
                project_id=project_id,
                edge_types=tuple(edge_types),
                entity_types=tuple(entity_types),
                review_statuses=tuple(review_statuses),
                include_inactive=include_inactive,
                include_pending_mentions=include_pending_mentions,
                temporal_start=temporal_from if temporal_enabled else None,
                temporal_end=temporal_to if temporal_enabled else None,
                temporal_include_undated=temporal_include_undated if temporal_enabled else False,
                min_shared_entities=int(min_shared),
                focus_node_id=focus_node_id or None,
                max_depth=None if depth_value == 0 or not focus_node_id else int(depth_value),
                max_nodes=int(max_nodes),
            )
            issues = graph_consistency_issues(session, project_id=project_id)
    except (ValueError, RuntimeError, OSError) as exc:
        st.error(str(exc))
        return
    finally:
        engine.dispose()

    explicit_count = sum(edge.edge_type == "explicit" for edge in view.edges)
    mention_count = sum(edge.edge_type == "mention" for edge in view.edges)
    shared_count = sum(edge.edge_type == "shared_entity" for edge in view.edges)
    metrics = st.columns(6)
    metrics[0].metric("Nodos", len(view.nodes))
    metrics[1].metric("Aristas", len(view.edges))
    metrics[2].metric("Explícitas", explicit_count)
    metrics[3].metric("Menciones", mention_count)
    metrics[4].metric("Compartidas", shared_count)
    metrics[5].metric("Alertas", sum(item.severity != "info" for item in issues))
    if view.truncated:
        st.warning(
            f"La vista se limitó a {len(view.nodes)} nodos. Antes del límite había "
            f"{view.total_nodes_before_limit} nodos y {view.total_edges_before_limit} aristas. "
            "Usá un foco o filtros más específicos para no perder contexto."
        )

    graph_tab, quality_tab, export_tab = st.tabs(["Explorar", "Consistencia", "Exportar"])
    with graph_tab:
        selected_node = st.session_state.get("graph_selected_node")
        selected_edge = st.session_state.get("graph_selected_edge")
        node_ids = {row.node_id for row in view.nodes}
        edge_ids = {row.edge_id for row in view.edges}
        if selected_node not in node_ids:
            selected_node = None
        if selected_edge not in edge_ids:
            selected_edge = None
        clicked_node, clicked_edge = interactive_graph_canvas(
            view,
            selected_node=selected_node,
            selected_edge=selected_edge,
            key=(
                "graph_canvas_"
                + "_".join(sorted(edge_types))
                + f"_{focus_node_id}_{depth_value}_{max_nodes}_{min_shared}"
                + f"_{temporal_enabled}_{temporal_from}_{temporal_to}_{temporal_include_undated}"
            ),
        )
        if clicked_node in node_ids and clicked_node != selected_node:
            st.session_state["graph_selected_node"] = clicked_node
            st.session_state.pop("graph_selected_edge", None)
            st.rerun()
        if clicked_edge in edge_ids and clicked_edge != selected_edge:
            st.session_state["graph_selected_edge"] = clicked_edge
            st.session_state.pop("graph_selected_node", None)
            st.rerun()
        if not hasattr(st.components, "v2"):
            st.info("El grafo interactivo requiere Streamlit 1.51 o posterior.")

        st.caption(
            "Leyenda: círculo de entidad · unidad archivística · parte interna. "
            "Línea continua: relación humana; guiones largos: mención; puntos: entidad compartida."
        )
        node_map = {row.node_id: row for row in view.nodes}
        edge_map = {row.edge_id: row for row in view.edges}
        selected_node = st.session_state.get("graph_selected_node")
        selected_edge = st.session_state.get("graph_selected_edge")
        if selected_node in node_map:
            node = node_map[selected_node]
            with st.container(border=True):
                st.subheader(node.label)
                st.write(f"**Tipo:** {_NODE_LABELS[node.kind]}")
                if node.subtype:
                    st.write(f"**Subtipo:** {node.subtype}")
                if node.context:
                    st.write(node.context)
                temporal_label = format_temporal_range(
                    node.temporal_expression,
                    node.temporal_start,
                    node.temporal_end,
                    node.temporal_approximate,
                )
                if temporal_label:
                    st.write(f"**Período:** {temporal_label}")
                st.caption(f"Conexiones visibles: {node.degree} · ID `{node.record_id}`")
                if st.button("Abrir registro", type="primary", key=f"graph_open_node_{node.node_id}"):
                    _navigate_node(st, node)
        elif selected_edge in edge_map:
            edge = edge_map[selected_edge]
            source = node_map.get(edge.source)
            target = node_map.get(edge.target)
            with st.container(border=True):
                st.subheader(edge.label)
                if source and target:
                    st.write(f"**{source.label}** → **{target.label}**")
                st.write(edge.explanation)
                st.caption(f"Tipo: {_EDGE_LABELS[edge.edge_type]} · peso {edge.weight}")
                if edge.review_status:
                    st.caption(f"Revisión: {_REVIEW_LABELS.get(edge.review_status, edge.review_status)}")
                temporal_label = format_temporal_range(
                    edge.temporal_expression,
                    edge.temporal_start,
                    edge.temporal_end,
                    edge.temporal_approximate,
                )
                if temporal_label:
                    st.write(f"**Vigencia:** {temporal_label}")
                if edge.evidence_note:
                    st.write("**Evidencia:** " + edge.evidence_note)
                actions = st.columns(2)
                if edge.relation_id and source and source.kind == "entity":
                    if actions[0].button("Abrir relación", key=f"graph_open_relation_{edge.edge_id}"):
                        _go_to(
                            st,
                            mode="authorities",
                            selection_key="authority_pending_selection",
                            selection=source.record_id,
                        )
                if edge.source_key:
                    if actions[1].button("Abrir evidencia textual", key=f"graph_open_evidence_{edge.edge_id}"):
                        _navigate_edge_evidence(st, edge)
        else:
            st.info("Seleccioná un nodo o una arista para ver su explicación y navegar al registro de origen.")

    with quality_tab:
        st.caption(
            "Estos controles no cambian datos. Señalan relaciones duplicadas, destinos inexistentes, "
            "falta de evidencia y menciones aceptadas que quedaron desactualizadas."
        )
        severity_filter = st.multiselect(
            "Gravedad",
            options=["error", "warning", "info"],
            default=["error", "warning"],
            format_func=lambda value: _SEVERITY_LABELS[value],
            key="graph_issue_severity",
        )
        visible_issues = [item for item in issues if item.severity in severity_filter]
        if not visible_issues:
            st.success("No hay incidencias con esos filtros.")
        for index, issue in enumerate(visible_issues):
            with st.container(border=True):
                st.write(f"**{_SEVERITY_LABELS.get(issue.severity, issue.severity)} · {issue.code}**")
                st.write(issue.message)
                if issue.relation_id:
                    st.caption(f"Relación `{issue.relation_id}`")
                if issue.mention_id:
                    st.caption(f"Mención `{issue.mention_id}`")
                if issue.entity_id and st.button(
                    "Abrir entidad",
                    key=f"graph_issue_entity_{index}_{issue.entity_id}",
                ):
                    _go_to(
                        st,
                        mode="authorities",
                        selection_key="authority_pending_selection",
                        selection=issue.entity_id,
                    )

    with export_tab:
        st.caption(
            "La exportación reproduce exactamente los filtros actuales y genera JSON, CSV y GraphML. "
            "GraphML puede abrirse en Gephi, Cytoscape u otras herramientas de redes."
        )
        default_name = "grafo_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        relative_dir = st.text_input(
            "Carpeta relativa a project_data",
            value=f"exports/{default_name}",
            key="graph_export_directory",
        )
        if st.button("Exportar vista y controles", type="primary"):
            target = (project_root / relative_dir).resolve()
            try:
                target.relative_to(project_root.resolve())
            except ValueError:
                st.error("La carpeta de exportación debe quedar dentro de project_data.")
            else:
                paths = export_graph(view, output_dir=target, issues=issues)
                st.success(f"Exportación creada en {target}")
                for path in paths:
                    st.code(str(path.relative_to(project_root)))
