from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

from archive_workbench.ui_navigation import rerun_view, tracked_tabs

from archive_workbench.authorities import (
    AUTHORITY_TYPES,
    MentionRepairCase,
    authority_rows,
    exact_mention_occurrences,
    mention_repair_cases,
    mention_revision_rows,
    mention_rows,
    repair_duplicate_group,
    repair_duplicate_relocation,
    repair_missing_authority,
    repair_safe_relocation_group,
    repair_snapshot_divergence,
    repair_stale_mention,
    repair_unresolved_relocation,
)
from archive_workbench.ui_navigation import rerun_app, request_app_view

from archive_workbench.db import create_sqlite_engine, session_scope
from archive_workbench.db.models import EditableObject
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
_ISSUE_LABELS = {
    "duplicate_relation": "Relaciones duplicadas",
    "missing_evidence": "Relación sin evidencia",
    "unreviewed_relation": "Relación pendiente de revisión",
    "missing_target": "Destino inexistente",
    "duplicate_mention": "Menciones duplicadas",
    "stale_mention": "Mención sobre una versión anterior",
    "accepted_without_entity": "Mención aceptada sin entidad",
}
_MENTION_STATUS_LABELS = {
    "pending": "Pendiente",
    "accepted": "Aceptada",
    "rejected": "Rechazada",
    "modified": "Modificada",
}
_MENTION_REPAIR_LABELS = {
    "safe_relocation": "Reubicación segura disponible",
    "unresolved_relocation": "Ubicación no resuelta",
    "duplicate_relocation": "Coincidencia con otra mención activa",
    "duplicate_group": "Conjunto de menciones coincidentes",
    "missing_authority": "Mención aceptada sin entidad",
    "snapshot_divergence": "Divergencia entre fila e historial",
}
_MENTION_SOURCE_LABELS = {
    "manual": "Manual",
    "dictionary": "Diccionario",
    "automatic": "Automática",
}
_SNAPSHOT_FIELD_LABELS = {
    "revision": "Número de revisión",
    "missing_snapshot": "Snapshot histórico",
    "editable_object_id": "Objeto textual",
    "authority_id": "Entidad vinculada",
    "mention_text": "Fragmento de la mención",
    "normalized_text": "Texto normalizado",
    "start_offset": "Offset inicial",
    "end_offset": "Offset final",
    "object_revision_number": "Revisión textual",
    "status": "Estado",
    "source": "Procedencia",
    "confidence": "Confianza",
    "note": "Nota",
}


def _go_to(st, *, mode: str, selection_key: str | None = None, selection: str | None = None) -> None:
    request_app_view(st, mode=mode)
    if selection_key and selection:
        st.session_state[selection_key] = selection
    rerun_app(st)


def _snapshot_display_value(
    field: str,
    value: object,
    authority_map: dict[str, object],
) -> str:
    if field == "authority_id":
        if value is None:
            return "Sin entidad vinculada"
        row = authority_map.get(str(value))
        if row is not None:
            return str(getattr(row, "preferred_name", value))
        return f"Entidad no disponible ({value})"
    if field == "status":
        return _MENTION_STATUS_LABELS.get(str(value), str(value))
    if field == "source":
        return _MENTION_SOURCE_LABELS.get(str(value), str(value))
    if field == "missing_snapshot":
        return "No disponible"
    if value is None:
        return "Sin valor"
    if isinstance(value, bool):
        return "Sí" if value else "No"
    return str(value)


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
        request_app_view(
            st,
            mode="review",
            source_key=node.source_key,
            page=node.page_number or 1,
            object_id=node.object_id,
        )
        rerun_app(st)


def _navigate_edge_evidence(st, edge: GraphEdge) -> None:
    if edge.source_key:
        request_app_view(
            st,
            mode="review",
            source_key=edge.source_key,
            page=edge.page_number or 1,
            object_id=edge.object_id,
        )
        rerun_app(st)


def _repair_snapshot_divergence_action(
    st,
    *,
    db_path: Path,
    case: MentionRepairCase,
    actor: str,
    decision: str,
    note: str,
) -> None:
    if (
        case.snapshot_revision_number is None
        or case.snapshot_current is None
        or case.snapshot_recorded is None
    ):
        st.error("La alerta no contiene evidencia suficiente para reconciliarla.")
        return
    engine = create_sqlite_engine(db_path)
    try:
        with session_scope(engine) as session:
            repair_snapshot_divergence(
                session,
                mention_id=case.mention_id,
                expected_revision=case.mention_revision,
                expected_snapshot_revision=case.snapshot_revision_number,
                expected_current_snapshot=case.snapshot_current,
                expected_recorded_snapshot=case.snapshot_recorded,
                changed_by=actor or "local_user",
                decision=decision,
                note=note,
            )
    except (ValueError, RuntimeError, OSError) as exc:
        st.error(str(exc))
        return
    finally:
        engine.dispose()
    if decision == "adopt_current":
        message = (
            "Se conservó la fila vigente y se la registró como una nueva revisión. "
            "El historial anterior permanece intacto."
        )
    else:
        message = (
            "Se conservó la fila divergente en el historial y luego se restauró "
            "el último estado registrado mediante una revisión nueva."
        )
    st.session_state["mention_repair_notice"] = message
    rerun_view(st)


def _repair_mention_action(
    st,
    *,
    db_path: Path,
    case: MentionRepairCase,
    actor: str,
    note: str,
) -> None:
    engine = create_sqlite_engine(db_path)
    try:
        with session_scope(engine) as session:
            repair_stale_mention(
                session,
                mention_id=case.mention_id,
                expected_revision=case.mention_revision,
                expected_start_offset=case.projected_start_offset,
                expected_end_offset=case.projected_end_offset,
                changed_by=actor or "local_user",
                note=note,
            )
    except (ValueError, RuntimeError, OSError) as exc:
        st.error(str(exc))
        return
    finally:
        engine.dispose()
    st.session_state["mention_repair_notice"] = (
        f"Mención reubicada en la revisión textual {case.current_object_revision}. "
        "El estado anterior quedó conservado en el historial."
    )
    rerun_view(st)


def _repair_missing_authority_action(
    st,
    *,
    db_path: Path,
    case: MentionRepairCase,
    actor: str,
    decision: str,
    authority_id: str | None,
    note: str,
) -> None:
    engine = create_sqlite_engine(db_path)
    try:
        with session_scope(engine) as session:
            repair_missing_authority(
                session,
                mention_id=case.mention_id,
                expected_revision=case.mention_revision,
                changed_by=actor or "local_user",
                decision=decision,
                authority_id=authority_id,
                note=note,
            )
    except (ValueError, RuntimeError, OSError) as exc:
        st.error(str(exc))
        return
    finally:
        engine.dispose()
    if decision == "link":
        message = (
            "La mención quedó vinculada a la entidad seleccionada. "
            "El estado anterior permanece en el historial."
        )
    else:
        message = (
            "La mención volvió al estado pendiente. "
            "El estado anterior permanece en el historial."
        )
    st.session_state["mention_repair_notice"] = message
    rerun_view(st)


def _repair_duplicate_action(
    st,
    *,
    db_path: Path,
    case: MentionRepairCase,
    duplicate_mention_id: str,
    duplicate_revision: int,
    actor: str,
    decision: str,
    note: str,
) -> None:
    engine = create_sqlite_engine(db_path)
    try:
        with session_scope(engine) as session:
            repair_duplicate_relocation(
                session,
                mention_id=case.mention_id,
                expected_revision=case.mention_revision,
                duplicate_mention_id=duplicate_mention_id,
                duplicate_expected_revision=duplicate_revision,
                changed_by=actor or "local_user",
                expected_object_revision=case.current_object_revision,
                expected_start_offset=case.projected_start_offset,
                expected_end_offset=case.projected_end_offset,
                decision=decision,
                note=note,
            )
    except (ValueError, RuntimeError, OSError) as exc:
        st.error(str(exc))
        return
    finally:
        engine.dispose()
    if decision == "keep_current":
        message = (
            "Se conservó la mención ya ubicada en el texto vigente y se retiró "
            "la mención histórica duplicada. El historial anterior permanece intacto."
        )
    else:
        message = (
            "Se conservó y reubicó la mención histórica; la mención vigente duplicada "
            "quedó retirada. Ambas decisiones quedaron registradas."
        )
    st.session_state["mention_repair_notice"] = message
    rerun_view(st)



def _repair_duplicate_group_action(
    st,
    *,
    db_path: Path,
    case: MentionRepairCase,
    mention_revisions: dict[str, int],
    winner_mention_id: str,
    actor: str,
    note: str,
) -> None:
    group_ids = (case.mention_id, *case.duplicate_mention_ids)
    if (
        case.projected_start_offset is None
        or case.projected_end_offset is None
    ):
        st.error("La alerta no contiene una ubicación vigente verificable.")
        return
    engine = create_sqlite_engine(db_path)
    try:
        with session_scope(engine) as session:
            repair_duplicate_group(
                session,
                mention_ids=group_ids,
                expected_revisions=mention_revisions,
                winner_mention_id=winner_mention_id,
                expected_object_revision=case.current_object_revision,
                expected_start_offset=case.projected_start_offset,
                expected_end_offset=case.projected_end_offset,
                changed_by=actor or "local_user",
                note=note,
            )
    except (ValueError, RuntimeError, OSError) as exc:
        st.error(str(exc))
        return
    finally:
        engine.dispose()
    st.session_state["mention_repair_notice"] = (
        f"Se revisó el conjunto completo de {len(group_ids)} menciones. "
        "Se conservó una sola y todas las decisiones quedaron registradas."
    )
    rerun_view(st)


def _repair_safe_group_action(
    st,
    *,
    db_path: Path,
    cases: list[MentionRepairCase],
    actor: str,
    note: str,
) -> None:
    engine = create_sqlite_engine(db_path)
    try:
        with session_scope(engine) as session:
            repair_safe_relocation_group(
                session,
                expected_cases=cases,
                changed_by=actor or "local_user",
                note=note,
            )
    except (ValueError, RuntimeError, OSError) as exc:
        st.error(str(exc))
        return
    finally:
        engine.dispose()
    st.session_state["mention_repair_notice"] = (
        f"Se reubicaron {len(cases)} menciones seguras en una sola operación "
        "verificable. Todos los estados anteriores permanecen en el historial."
    )
    rerun_view(st)

def _repair_unresolved_action(
    st,
    *,
    db_path: Path,
    case: MentionRepairCase,
    actor: str,
    decision: str,
    selected_fragment: str | None,
    selected_start_offset: int | None,
    selected_end_offset: int | None,
    note: str,
) -> None:
    engine = create_sqlite_engine(db_path)
    try:
        with session_scope(engine) as session:
            repair_unresolved_relocation(
                session,
                mention_id=case.mention_id,
                expected_revision=case.mention_revision,
                expected_object_revision=case.current_object_revision,
                changed_by=actor or "local_user",
                decision=decision,
                selected_fragment=selected_fragment,
                expected_start_offset=selected_start_offset,
                expected_end_offset=selected_end_offset,
                note=note,
            )
    except (ValueError, RuntimeError, OSError) as exc:
        st.error(str(exc))
        return
    finally:
        engine.dispose()
    if decision == "relocate":
        message = (
            "La mención quedó reubicada manualmente sobre el fragmento seleccionado. "
            "La ubicación anterior permanece en el historial."
        )
    else:
        message = (
            "La mención quedó retirada porque el fragmento ya no está presente. "
            "El registro y todas sus revisiones permanecen conservados."
        )
    st.session_state["mention_repair_notice"] = message
    rerun_view(st)


def render_graph_view(
    st,
    *,
    project_root: Path,
    db_path: Path,
    project_id: str,
    actor: str,
) -> None:
    st.header("Mapa de relaciones")
    st.caption(
        "Explorá personas, organizaciones, documentos y vínculos registrados o derivados del corpus."
    )
    repair_notice = st.session_state.pop("mention_repair_notice", None)
    if repair_notice:
        st.success(repair_notice)
    with st.expander("Cómo se construye este mapa", expanded=False):
        st.write(
            "Es una vista derivada: no guarda datos paralelos ni crea relaciones nuevas. "
            "Los vínculos continuos son afirmaciones explícitas; las menciones y entidades "
            "compartidas se calculan a partir del corpus y siempre explican de dónde salen."
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
    with st.expander("Filtros del mapa", expanded=False):
        with st.form("graph_filters", enter_to_submit=False):
            left, middle, right = st.columns(3)
            with left:
                edge_types = st.multiselect(
                    "Tipos de vínculo",
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
                max_nodes = st.selectbox("Máximo de elementos", options=[60, 120, 180, 300], index=2)
                focus_node_id = st.selectbox(
                    "Centrar en",
                    options=focus_options,
                    format_func=lambda value: (
                        "Todo el mapa"
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
            repair_cases = mention_repair_cases(session, project_id=project_id)
            repair_authorities = authority_rows(
                session,
                project_id=project_id,
                lifecycle_statuses=("active",),
            )
            repair_mention_ids = {case.mention_id for case in repair_cases}
            for case in repair_cases:
                repair_mention_ids.update(case.duplicate_mention_ids)
            repair_mentions = {
                row.mention_id: row
                for row in mention_rows(session, project_id=project_id)
                if row.mention_id in repair_mention_ids
            }
            repair_histories = {
                mention_id: [
                    {
                        "revision_number": revision.revision_number,
                        "operation": revision.operation,
                        "changed_by": revision.changed_by,
                        "changed_at": revision.changed_at,
                        "note": revision.note,
                        "snapshot": revision.snapshot_json,
                    }
                    for revision in mention_revision_rows(session, mention_id)
                ]
                for mention_id in repair_mention_ids
            }
            repair_object_ids = {case.object_id for case in repair_cases}
            repair_objects = {
                object_id: {
                    "text": editable.current_text,
                    "revision": editable.revision_number,
                }
                for object_id in repair_object_ids
                if (editable := session.get(EditableObject, object_id)) is not None
            }
    except (ValueError, RuntimeError, OSError) as exc:
        st.error(str(exc))
        return
    finally:
        engine.dispose()

    explicit_count = sum(edge.edge_type == "explicit" for edge in view.edges)
    mention_count = sum(edge.edge_type == "mention" for edge in view.edges)
    shared_count = sum(edge.edge_type == "shared_entity" for edge in view.edges)
    with st.expander("Resumen del mapa", expanded=False):
        metrics = st.columns(6)
        metrics[0].metric("Elementos", len(view.nodes))
        metrics[1].metric("Vínculos", len(view.edges))
        metrics[2].metric("Explícitos", explicit_count)
        metrics[3].metric("Menciones", mention_count)
        metrics[4].metric("Compartidos", shared_count)
        metrics[5].metric("Alertas", sum(item.severity != "info" for item in issues))
    if view.truncated:
        st.warning(
            f"La vista se limitó a {len(view.nodes)} elementos. Antes del límite había "
            f"{view.total_nodes_before_limit} elementos y {view.total_edges_before_limit} vínculos. "
            "Usá un foco o filtros más específicos para no perder contexto."
        )

    graph_tab, quality_tab, export_tab = tracked_tabs(
        st, ["Explorar", "Revisar alertas", "Exportar datos"], key="graph_tabs"
    )
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
                + "_entities_"
                + "_".join(sorted(entity_types))
                + "_reviews_"
                + "_".join(sorted(review_statuses))
                + f"_{include_inactive}_{include_pending_mentions}"
                + f"_{focus_node_id}_{depth_value}_{max_nodes}_{min_shared}"
                + f"_{temporal_enabled}_{temporal_from}_{temporal_to}_{temporal_include_undated}"
            ),
        )
        if clicked_node in node_ids and clicked_node != selected_node:
            st.session_state["graph_selected_node"] = clicked_node
            st.session_state.pop("graph_selected_edge", None)
            rerun_view(st)
        if clicked_edge in edge_ids and clicked_edge != selected_edge:
            st.session_state["graph_selected_edge"] = clicked_edge
            st.session_state.pop("graph_selected_node", None)
            rerun_view(st)
        if not hasattr(st.components, "v2"):
            st.info("El mapa interactivo requiere Streamlit 1.51 o posterior.")

        with st.expander("Cómo leer los elementos y vínculos", expanded=False):
            st.caption(
                "Círculo: entidad · rectángulo: unidad archivística · otra forma: parte interna. "
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
                st.caption(f"Conexiones visibles: {node.degree}")
                with st.expander("Detalles técnicos", expanded=False):
                    st.code(f"registro={node.record_id}")
                    st.code(f"nodo={node.node_id}")
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
                st.caption(f"Tipo: {_EDGE_LABELS[edge.edge_type]}")
                with st.expander("Detalles técnicos", expanded=False):
                    st.code(f"vinculo={edge.edge_id}")
                    st.code(f"peso={edge.weight}")
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
            st.info("Seleccioná un elemento o un vínculo para ver su explicación y abrir el registro de origen.")

    with quality_tab:
        st.caption(
            "Las alertas no cambian datos por sí mismas. Las reparaciones automáticas "
            "exigen una ubicación única; los casos ambiguos requieren una selección humana "
            "explícita y también quedan registrados."
        )

        st.subheader("Menciones que requieren revisión")
        st.caption(
            "Las menciones rechazadas se conservan como evidencia histórica y no aparecen "
            "como trabajo activo. Toda reparación agrega una revisión nueva; nunca reescribe "
            "silenciosamente las anteriores."
        )
        repair_metrics_top = st.columns(2)
        repair_metrics_top[0].metric("Alertas activas", len(repair_cases))
        repair_metrics_top[1].metric(
            "Reubicables con seguridad",
            sum(case.can_relocate for case in repair_cases),
        )
        repair_metrics_bottom = st.columns(2)
        repair_metrics_bottom[0].metric(
            "Requieren decisión humana",
            sum(
                case.code in {
                    "unresolved_relocation",
                    "duplicate_relocation",
                    "duplicate_group",
                }
                for case in repair_cases
            ),
        )
        repair_metrics_bottom[1].metric(
            "Errores de integridad",
            sum(case.severity == "error" for case in repair_cases),
        )
        if not repair_cases:
            st.success("No hay menciones activas que requieran reparación.")
        repair_authority_map = {
            row.authority_id: row for row in repair_authorities
        }
        repair_authority_options = list(repair_authority_map)

        safe_groups: dict[tuple[str, int], list[MentionRepairCase]] = {}
        for safe_case in repair_cases:
            if safe_case.can_relocate:
                safe_groups.setdefault(
                    (safe_case.object_id, safe_case.current_object_revision),
                    [],
                ).append(safe_case)
        actionable_safe_groups = [
            group
            for group in safe_groups.values()
            if len(group) >= 2
        ]
        if actionable_safe_groups:
            st.markdown("### Acciones agrupadas verificables")
            st.caption(
                "Solo se agrupan menciones cuya proyección es única, pertenece al "
                "mismo texto vigente y no colisiona con otras menciones activas. "
                "La operación se cancela completa si una condición cambia."
            )
        for safe_group in actionable_safe_groups:
            first_case = safe_group[0]
            with st.container(border=True):
                st.write(
                    f"**Reubicar {len(safe_group)} menciones seguras de una vez**"
                )
                st.caption(
                    f"{first_case.document_title or '[sin título]'} · "
                    f"página {first_case.page_number} · "
                    f"objeto {first_case.order_index + 1}"
                )
                for safe_case in safe_group:
                    st.write(
                        "- "
                        f"{safe_case.authority_name or 'Sin entidad vinculada'}: "
                        f"“{safe_case.projected_text or safe_case.mention_text}”"
                    )
                with st.form(
                    "mention_safe_group_form_"
                    f"{first_case.object_id}_{first_case.current_object_revision}",
                    enter_to_submit=False,
                ):
                    group_note = st.text_input(
                        "Fundamento de la reubicación agrupada",
                        value=(
                            "Las menciones comparten una proyección única y verificable "
                            "sobre el mismo texto vigente."
                        ),
                    )
                    confirm_safe_group = st.checkbox(
                        "Confirmo que deseo reubicar todas estas menciones seguras "
                        "en una sola operación registrada"
                    )
                    safe_group_submit = st.form_submit_button(
                        "Reubicar menciones seguras",
                        type="primary",
                    )
                if safe_group_submit and not confirm_safe_group:
                    st.error(
                        "Marcá la confirmación antes de ejecutar la reubicación agrupada."
                    )
                elif safe_group_submit:
                    _repair_safe_group_action(
                        st,
                        db_path=db_path,
                        cases=safe_group,
                        actor=actor,
                        note=group_note,
                    )

        for case in repair_cases:
            with st.container(border=True):
                st.write(
                    f"**{_MENTION_REPAIR_LABELS.get(case.code, case.code)} · "
                    f"“{case.mention_text}”**"
                )
                st.caption(
                    f"{case.document_title or '[sin título]'} · página {case.page_number} · "
                    f"objeto {case.order_index + 1}"
                )
                if case.authority_name:
                    st.write(f"**Entidad:** {case.authority_name}")
                st.write(case.explanation)
                if (
                    case.code == "snapshot_divergence"
                    and case.snapshot_recorded is not None
                    and case.snapshot_current is not None
                ):
                    st.markdown(
                        "**Comparar la fila vigente con el último estado registrado**"
                    )
                    st.caption(
                        "Último estado registrado: "
                        f"v{case.snapshot_revision_number} · "
                        f"{case.snapshot_operation or 'operación no identificada'}"
                    )
                    for field in case.snapshot_difference_fields:
                        label = _SNAPSHOT_FIELD_LABELS.get(field, field)
                        if field == "revision":
                            current_value = case.mention_revision
                            recorded_value = case.snapshot_revision_number
                        elif field == "missing_snapshot":
                            current_value = "Fila vigente disponible"
                            recorded_value = None
                        else:
                            current_value = case.snapshot_current.get(field)
                            recorded_value = case.snapshot_recorded.get(field)
                        compare_cols = st.columns(2)
                        with compare_cols[0]:
                            st.caption(f"Fila vigente · {label}")
                            st.write(
                                _snapshot_display_value(
                                    field,
                                    current_value,
                                    repair_authority_map,
                                )
                            )
                        with compare_cols[1]:
                            st.caption(f"Último estado registrado · {label}")
                            st.write(
                                _snapshot_display_value(
                                    field,
                                    recorded_value,
                                    repair_authority_map,
                                )
                            )
                if case.projected_text is not None:
                    st.write(f"**Fragmento vigente:** {case.projected_text}")
                    st.caption(
                        f"Revisión textual {case.stored_object_revision} → "
                        f"{case.current_object_revision}"
                    )
                duplicate_rows = [
                    repair_mentions[mention_id]
                    for mention_id in case.duplicate_mention_ids
                    if mention_id in repair_mentions
                ]
                if case.code == "duplicate_group":
                    primary_row = repair_mentions.get(case.mention_id)
                    group_rows = (
                        ([primary_row] if primary_row is not None else [])
                        + duplicate_rows
                    )
                    st.markdown("**Revisar el conjunto completo**")
                    for group_row in sorted(
                        group_rows,
                        key=lambda row: (
                            row.object_revision_number
                            == row.current_object_revision,
                            row.authority_name or "",
                            row.mention_id,
                        ),
                    ):
                        temporal_position = (
                            "Vigente"
                            if group_row.object_revision_number
                            == group_row.current_object_revision
                            else "Histórica"
                        )
                        st.write(
                            "- "
                            f"**{group_row.authority_name or 'Sin entidad vinculada'}** · "
                            f"{temporal_position} · "
                            f"{_MENTION_STATUS_LABELS.get(group_row.status, group_row.status)} · "
                            f"revisión de mención {group_row.revision}"
                        )
                    if case.group_block_reason:
                        st.error(case.group_block_reason)
                elif case.duplicate_mention_ids and len(duplicate_rows) == 1:
                    duplicate_row = duplicate_rows[0]
                    st.markdown("**Comparar las dos menciones**")
                    compare_cols = st.columns(2)
                    with compare_cols[0]:
                        st.caption("Mención histórica")
                        st.write(case.authority_name or "Sin entidad vinculada")
                        st.write(
                            f"Estado: {_MENTION_STATUS_LABELS.get(case.status, case.status)} · "
                            "revisión textual "
                            f"{case.stored_object_revision}"
                        )
                    with compare_cols[1]:
                        st.caption("Mención ya ubicada en el texto vigente")
                        st.write(duplicate_row.authority_name or "Sin entidad vinculada")
                        st.write(
                            f"Estado: {_MENTION_STATUS_LABELS.get(duplicate_row.status, duplicate_row.status)} · "
                            "revisión textual "
                            f"{duplicate_row.object_revision_number}"
                        )

                action_cols = st.columns(2)
                if case.source_key and action_cols[0].button(
                    "Abrir texto",
                    key=f"mention_repair_open_text_{case.code}_{case.mention_id}",
                ):
                    request_app_view(
                        st,
                        mode="review",
                        source_key=case.source_key,
                        page=case.page_number,
                        object_id=case.object_id,
                    )
                    rerun_app(st)
                if case.authority_id and action_cols[1].button(
                    "Abrir entidad",
                    key=f"mention_repair_open_entity_{case.code}_{case.mention_id}",
                ):
                    _go_to(
                        st,
                        mode="authorities",
                        selection_key="authority_pending_selection",
                        selection=case.authority_id,
                    )

                with st.expander("Detalles técnicos e historial de la alerta", expanded=False):
                    st.code(f"tipo={case.code}")
                    st.code(f"mencion={case.mention_id}")
                    st.code(f"revision_mencion={case.mention_revision}")
                    st.code(
                        "offsets_guardados="
                        f"{case.stored_start_offset}:{case.stored_end_offset}"
                    )
                    if case.projected_start_offset is not None:
                        st.code(
                            "offsets_proyectados="
                            f"{case.projected_start_offset}:{case.projected_end_offset}"
                        )
                    st.markdown("**Historial de la mención observada**")
                    for revision in reversed(repair_histories.get(case.mention_id, [])):
                        st.caption(
                            f"v{revision['revision_number']} · {revision['operation']} · "
                            f"{revision['changed_by']} · "
                            f"{revision['changed_at'].isoformat(timespec='minutes')}"
                        )
                        if revision["note"]:
                            st.write(revision["note"])
                        st.json(revision["snapshot"], expanded=False)
                    for duplicate_id in case.duplicate_mention_ids:
                        st.markdown("**Historial de la mención coincidente**")
                        st.code(f"mencion_coincidente={duplicate_id}")
                        for revision in reversed(repair_histories.get(duplicate_id, [])):
                            st.caption(
                                f"v{revision['revision_number']} · {revision['operation']} · "
                                f"{revision['changed_by']} · "
                                f"{revision['changed_at'].isoformat(timespec='minutes')}"
                            )
                            if revision["note"]:
                                st.write(revision["note"])
                            st.json(revision["snapshot"], expanded=False)

                if case.can_resolve_snapshot_divergence:
                    st.markdown("**Reconciliar la divergencia**")
                    divergence_decision = st.radio(
                        "Qué estado querés conservar",
                        options=["adopt_current", "restore_snapshot"],
                        format_func=lambda value: {
                            "adopt_current": (
                                "Conservar la fila vigente y registrarla en el historial"
                            ),
                            "restore_snapshot": (
                                "Restaurar el último estado registrado"
                            ),
                        }[value],
                        key=(
                            f"mention_snapshot_decision_{case.mention_id}_"
                            f"{case.mention_revision}"
                        ),
                    )
                    if divergence_decision == "adopt_current":
                        default_divergence_note = (
                            "Se conserva la fila vigente después de comparar todos los "
                            "campos divergentes con el último estado registrado."
                        )
                        confirmation_label = (
                            "Confirmo que revisé las diferencias y deseo conservar la fila "
                            "vigente como una nueva revisión"
                        )
                        submit_label = "Conservar fila vigente"
                    else:
                        default_divergence_note = (
                            "Se restaura el último estado registrado después de comparar "
                            "todos los campos divergentes."
                        )
                        confirmation_label = (
                            "Confirmo que revisé las diferencias y deseo restaurar el último "
                            "estado registrado como una nueva revisión"
                        )
                        submit_label = "Restaurar estado registrado"
                    with st.form(
                        f"mention_snapshot_form_{case.mention_id}_{case.mention_revision}",
                        enter_to_submit=False,
                    ):
                        divergence_note = st.text_input(
                            "Fundamento de la reconciliación",
                            value=default_divergence_note,
                        )
                        confirm_divergence = st.checkbox(confirmation_label)
                        divergence_submit = st.form_submit_button(
                            submit_label,
                            type="primary",
                        )
                    if divergence_submit and not confirm_divergence:
                        st.error(
                            "Marcá la confirmación antes de reconciliar la divergencia."
                        )
                    elif divergence_submit:
                        _repair_snapshot_divergence_action(
                            st,
                            db_path=db_path,
                            case=case,
                            actor=actor,
                            decision=divergence_decision,
                            note=divergence_note,
                        )

                if case.can_relocate:
                    with st.form(
                        f"mention_repair_form_{case.mention_id}_{case.mention_revision}",
                        enter_to_submit=False,
                    ):
                        repair_note = st.text_input(
                            "Nota de reparación",
                            value=(
                                f"Reubicación segura desde la revisión textual "
                                f"{case.stored_object_revision} a la "
                                f"{case.current_object_revision}."
                            ),
                        )
                        confirm_repair = st.checkbox(
                            "Confirmo que deseo reubicar esta mención y registrar una nueva revisión"
                        )
                        repair_submit = st.form_submit_button(
                            "Reubicar mención",
                            type="primary",
                        )
                    if repair_submit and not confirm_repair:
                        st.error("Marcá la confirmación antes de reubicar la mención.")
                    elif repair_submit:
                        _repair_mention_action(
                            st,
                            db_path=db_path,
                            case=case,
                            actor=actor,
                            note=repair_note,
                        )

                if case.can_resolve_unresolved:
                    object_info = repair_objects.get(case.object_id)
                    if object_info is None:
                        st.error("No pudo cargarse el texto vigente del objeto.")
                    else:
                        current_text = str(object_info["text"])
                        original_occurrences = exact_mention_occurrences(
                            current_text,
                            case.mention_text,
                        )
                        st.markdown("**Resolver la ubicación manualmente**")
                        with st.expander("Ver texto vigente completo", expanded=False):
                            st.text_area(
                                "Texto vigente del objeto",
                                value=current_text,
                                height=220,
                                disabled=True,
                                key=(
                                    f"mention_unresolved_text_{case.mention_id}_"
                                    f"{case.mention_revision}"
                                ),
                            )

                        decision_options = ["relocate"]
                        if not original_occurrences:
                            decision_options.append("mark_absent")
                        unresolved_decision = st.radio(
                            "Qué querés registrar",
                            options=decision_options,
                            format_func=lambda value: {
                                "relocate": (
                                    "Reubicar la mención en un fragmento del texto vigente"
                                ),
                                "mark_absent": (
                                    "Registrar que el fragmento ya no está presente"
                                ),
                            }[value],
                            key=(
                                f"mention_unresolved_decision_{case.mention_id}_"
                                f"{case.mention_revision}"
                            ),
                        )

                        selected_fragment: str | None = None
                        selected_start: int | None = None
                        selected_end: int | None = None
                        can_submit_unresolved = True
                        if unresolved_decision == "relocate":
                            selected_fragment = st.text_input(
                                "Fragmento exacto en el texto vigente",
                                value=case.mention_text,
                                key=(
                                    f"mention_unresolved_fragment_{case.mention_id}_"
                                    f"{case.mention_revision}"
                                ),
                                help=(
                                    "Pegá una frase que aparezca literalmente en el texto "
                                    "vigente. Después elegí la aparición correcta."
                                ),
                            )
                            occurrences = exact_mention_occurrences(
                                current_text,
                                selected_fragment,
                            )
                            if not occurrences:
                                st.warning(
                                    "Ese fragmento no aparece literalmente en el texto vigente."
                                )
                                can_submit_unresolved = False
                            else:
                                occurrence_options = list(range(len(occurrences)))

                                def _occurrence_label(index: int) -> str:
                                    start, end = occurrences[index]
                                    before = current_text[max(0, start - 45) : start]
                                    selected = current_text[start:end]
                                    after = current_text[end : min(len(current_text), end + 45)]
                                    return (
                                        f"Aparición {index + 1} · …{before}[{selected}]"
                                        f"{after}…"
                                    )

                                selected_occurrence = st.selectbox(
                                    "Aparición que corresponde a la mención",
                                    options=occurrence_options,
                                    format_func=_occurrence_label,
                                    key=(
                                        f"mention_unresolved_occurrence_{case.mention_id}_"
                                        f"{case.mention_revision}_{selected_fragment}"
                                    ),
                                )
                                selected_start, selected_end = occurrences[
                                    selected_occurrence
                                ]
                                st.caption(
                                    f"Ubicación seleccionada: {selected_start}:{selected_end}"
                                )
                            default_unresolved_note = (
                                "Reubicación manual después de revisar el texto vigente "
                                "y seleccionar la aparición correcta."
                            )
                            confirmation_label = (
                                "Confirmo que revisé el texto vigente y deseo reubicar "
                                "esta mención en la aparición seleccionada"
                            )
                            submit_label = "Reubicar mención manualmente"
                        else:
                            st.info(
                                "La mención dejará de estar activa, pero el fragmento, la "
                                "entidad vinculada y todas las revisiones seguirán conservados."
                            )
                            default_unresolved_note = (
                                "El fragmento histórico ya no aparece en el texto vigente."
                            )
                            confirmation_label = (
                                "Confirmo que revisé el texto vigente y que el fragmento "
                                "ya no está presente"
                            )
                            submit_label = "Retirar mención ausente"

                        with st.form(
                            f"mention_unresolved_form_{case.mention_id}_{case.mention_revision}",
                            enter_to_submit=False,
                        ):
                            unresolved_note = st.text_input(
                                "Fundamento de la decisión",
                                value=default_unresolved_note,
                            )
                            confirm_unresolved = st.checkbox(confirmation_label)
                            unresolved_submit = st.form_submit_button(
                                submit_label,
                                type="primary",
                                disabled=not can_submit_unresolved,
                            )
                        if unresolved_submit and not confirm_unresolved:
                            st.error(
                                "Marcá la confirmación antes de registrar la decisión."
                            )
                        elif unresolved_submit:
                            _repair_unresolved_action(
                                st,
                                db_path=db_path,
                                case=case,
                                actor=actor,
                                decision=unresolved_decision,
                                selected_fragment=selected_fragment,
                                selected_start_offset=selected_start,
                                selected_end_offset=selected_end,
                                note=unresolved_note,
                            )

                if case.can_resolve_duplicate_group:
                    group_ids = (case.mention_id, *case.duplicate_mention_ids)
                    group_rows = [
                        repair_mentions[mention_id]
                        for mention_id in group_ids
                        if mention_id in repair_mentions
                    ]
                    if len(group_rows) == len(group_ids):
                        st.markdown("**Resolver el conjunto completo**")

                        def _group_winner_label(mention_id: str) -> str:
                            row = repair_mentions[mention_id]
                            temporal_position = (
                                "vigente"
                                if row.object_revision_number
                                == row.current_object_revision
                                else "histórica"
                            )
                            return (
                                f"{row.authority_name or 'Sin entidad vinculada'} · "
                                f"{temporal_position} · "
                                f"{_MENTION_STATUS_LABELS.get(row.status, row.status)}"
                            )

                        with st.form(
                            "mention_duplicate_group_form_"
                            f"{case.mention_id}_{case.mention_revision}",
                            enter_to_submit=False,
                        ):
                            winner_id = st.selectbox(
                                "Mención que se conservará",
                                options=list(group_ids),
                                index=None,
                                placeholder="Elegí una mención después de comparar el conjunto",
                                format_func=_group_winner_label,
                            )
                            group_duplicate_note = st.text_input(
                                "Fundamento de la decisión conjunta",
                                value=(
                                    "Se conserva una única mención después de comparar "
                                    "entidades, estados, procedencia e historial del conjunto."
                                ),
                            )
                            confirm_duplicate_group = st.checkbox(
                                "Confirmo que revisé el conjunto completo, que deseo "
                                "conservar una sola mención y retirar las demás"
                            )
                            duplicate_group_submit = st.form_submit_button(
                                "Registrar decisión conjunta",
                                type="primary",
                            )
                        if duplicate_group_submit and winner_id is None:
                            st.error(
                                "Elegí la mención que se conservará antes de registrar la decisión."
                            )
                        elif duplicate_group_submit and not confirm_duplicate_group:
                            st.error(
                                "Marcá la confirmación antes de registrar la decisión conjunta."
                            )
                        elif duplicate_group_submit:
                            _repair_duplicate_group_action(
                                st,
                                db_path=db_path,
                                case=case,
                                mention_revisions={
                                    row.mention_id: row.revision
                                    for row in group_rows
                                },
                                winner_mention_id=winner_id,
                                actor=actor,
                                note=group_duplicate_note,
                            )

                if case.can_resolve_duplicate:
                    duplicate_id = case.duplicate_mention_ids[0]
                    duplicate_row = repair_mentions.get(duplicate_id)
                    if duplicate_row is not None:
                        st.markdown("**Resolver la duplicación**")
                        duplicate_decision = st.radio(
                            "Qué mención querés conservar",
                            options=["keep_current", "keep_historical"],
                            format_func=lambda value: {
                                "keep_current": (
                                    "Conservar la mención ya ubicada en el texto vigente"
                                ),
                                "keep_historical": (
                                    "Conservar la mención histórica y reubicarla"
                                ),
                            }[value],
                            key=(
                                f"mention_duplicate_decision_{case.mention_id}_"
                                f"{case.mention_revision}"
                            ),
                        )
                        if duplicate_decision == "keep_current":
                            default_duplicate_note = (
                                "Se conserva la mención ya ubicada en el texto vigente "
                                "después de comparar entidad, procedencia e historial."
                            )
                            confirmation_label = (
                                "Confirmo que deseo conservar la mención vigente y retirar "
                                "la mención histórica duplicada"
                            )
                        else:
                            default_duplicate_note = (
                                "Se conserva la mención histórica y se la reubica después "
                                "de comparar entidad, procedencia e historial."
                            )
                            confirmation_label = (
                                "Confirmo que deseo conservar y reubicar la mención histórica, "
                                "y retirar la mención vigente duplicada"
                            )
                        with st.form(
                            f"mention_duplicate_form_{case.mention_id}_{case.mention_revision}",
                            enter_to_submit=False,
                        ):
                            duplicate_note = st.text_input(
                                "Fundamento de la decisión",
                                value=default_duplicate_note,
                            )
                            confirm_duplicate = st.checkbox(confirmation_label)
                            duplicate_submit = st.form_submit_button(
                                "Registrar decisión sobre el duplicado",
                                type="primary",
                            )
                        if duplicate_submit and not confirm_duplicate:
                            st.error(
                                "Marcá la confirmación antes de registrar la decisión."
                            )
                        elif duplicate_submit:
                            _repair_duplicate_action(
                                st,
                                db_path=db_path,
                                case=case,
                                duplicate_mention_id=duplicate_id,
                                duplicate_revision=duplicate_row.revision,
                                actor=actor,
                                decision=duplicate_decision,
                                note=duplicate_note,
                            )

                if case.can_resolve_missing_authority:
                    st.markdown("**Resolver entidad faltante**")
                    decision_options = (
                        ["link", "return_pending"]
                        if repair_authority_options
                        else ["return_pending"]
                    )
                    missing_decision = st.radio(
                        "Qué querés hacer",
                        options=decision_options,
                        format_func=lambda value: {
                            "link": "Vincular a una entidad existente",
                            "return_pending": "Devolver la mención a pendiente",
                        }[value],
                        key=(
                            f"mention_missing_decision_{case.mention_id}_"
                            f"{case.mention_revision}"
                        ),
                    )
                    with st.form(
                        f"mention_missing_form_{case.mention_id}_{case.mention_revision}",
                        enter_to_submit=False,
                    ):
                        selected_authority_id: str | None = None
                        if missing_decision == "link":
                            selected_authority_id = st.selectbox(
                                "Entidad que corresponde a la mención",
                                options=repair_authority_options,
                                format_func=lambda value: (
                                    f"{repair_authority_map[value].preferred_name} · "
                                    f"{_ENTITY_TYPE_LABELS[repair_authority_map[value].entity_type]}"
                                ),
                            )
                            default_missing_note = (
                                "Vinculación reparada después de revisar la mención "
                                "y la entidad seleccionada."
                            )
                            confirmation_label = (
                                "Confirmo que deseo vincular esta mención y registrar "
                                "una nueva revisión"
                            )
                            submit_label = "Vincular mención"
                        else:
                            st.info(
                                "La mención seguirá registrada, pero volverá a requerir "
                                "una decisión humana antes de considerarse aceptada."
                            )
                            default_missing_note = (
                                "La mención vuelve a pendiente porque no tiene una "
                                "entidad verificable."
                            )
                            confirmation_label = (
                                "Confirmo que deseo devolver esta mención a pendiente "
                                "y registrar una nueva revisión"
                            )
                            submit_label = "Devolver a pendiente"
                        missing_note = st.text_input(
                            "Nota de reparación",
                            value=default_missing_note,
                        )
                        confirm_missing = st.checkbox(confirmation_label)
                        missing_submit = st.form_submit_button(
                            submit_label,
                            type="primary",
                        )
                    if missing_submit and not confirm_missing:
                        st.error("Marcá la confirmación antes de registrar la decisión.")
                    elif missing_submit:
                        _repair_missing_authority_action(
                            st,
                            db_path=db_path,
                            case=case,
                            actor=actor,
                            decision=missing_decision,
                            authority_id=selected_authority_id,
                            note=missing_note,
                        )

        st.divider()
        st.subheader("Otras alertas del mapa")
        st.caption(
            "Incluye relaciones duplicadas, falta de evidencia, destinos inexistentes y "
            "otros problemas que todavía no tienen una reparación automática."
        )
        severity_filter = st.multiselect(
            "Gravedad",
            options=["error", "warning", "info"],
            default=["error", "warning"],
            format_func=lambda value: _SEVERITY_LABELS[value],
            key="graph_issue_severity",
        )
        represented_mention_ids = {case.mention_id for case in repair_cases}
        visible_issues = [
            item
            for item in issues
            if item.severity in severity_filter
            and not (
                item.mention_id in represented_mention_ids
                and item.code in {"stale_mention", "accepted_without_entity"}
            )
        ]
        if not visible_issues:
            st.success("No hay otras alertas con esos filtros.")
        for index, issue in enumerate(visible_issues):
            with st.container(border=True):
                st.write(
                    f"**{_SEVERITY_LABELS.get(issue.severity, issue.severity)} · "
                    f"{_ISSUE_LABELS.get(issue.code, issue.code)}**"
                )
                st.write(issue.message)
                with st.expander("Detalles técnicos", expanded=False):
                    st.code(f"tipo={issue.code}")
                    if issue.relation_id:
                        st.code(f"relacion={issue.relation_id}")
                    if issue.mention_id:
                        st.code(f"mencion={issue.mention_id}")
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
