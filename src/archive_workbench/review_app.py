from __future__ import annotations

import argparse
import hashlib
import html
import json
import sys
from pathlib import Path
from typing import Callable

from archive_workbench.db import create_sqlite_engine, database_path, session_scope
from archive_workbench.catalog_app import render_catalog_view
from archive_workbench.authority_app import render_authorities_view
from archive_workbench.decisions import load_decisions
from archive_workbench.authorities import (
    AUTHORITY_TYPES,
    LINKED_MENTION_STATUSES,
    MENTION_STATUSES,
    authority_rows,
    create_mention,
    mention_rows,
    suggest_dictionary_mentions,
    update_mention,
)
from archive_workbench.editing import (
    add_editable_object,
    export_editable_layer,
    merge_editable_object,
    move_editable_object,
    object_revision_rows,
    revert_editable_object,
    set_editable_object_lifecycle,
    split_editable_object,
    update_editable_object,
)
from archive_workbench.page_actions import (
    execute_page_action,
    page_action_availability,
    redo_page_action,
    undo_page_action,
)
from archive_workbench.review import (
    ReviewObjectRow,
    render_review_overlay,
    review_document_rows,
    review_page_view,
)
from archive_workbench.review_annotations import (
    REVIEW_STATUSES,
    TAG_KINDS,
    add_object_comment,
    add_object_tag,
    object_comment_rows,
    remove_object_tag,
    set_object_review_status,
    set_page_review_status,
)
from archive_workbench.review_parts import (
    assign_editable_object_part,
    assign_page_objects_to_part,
)
from archive_workbench.review_canvas import clickable_review_canvas
from archive_workbench.search import (
    MATCH_MODES,
    SEARCH_FIELDS,
    rebuild_search_index,
    search_editable_objects,
    search_index_status,
)
from archive_workbench.graph_app import render_graph_view
from archive_workbench.export_app import render_export_view
from archive_workbench.admin_app import render_admin_view
from archive_workbench.semantic_app import render_semantic_search_view
from archive_workbench.processing_app import render_processing_view
from archive_workbench.work_app import render_work_view
from archive_workbench.home_app import render_home_view
from archive_workbench.exchange import (
    apply_change_bundle,
    bundle_application_rows,
    conflict_field_rows,
    dry_run_change_bundle,
    exchange_status,
    finalize_bundle_resolutions,
    incoming_bundle_rows,
    resolution_status,
    resolve_conflict_fields_bulk,
    save_conflict_resolution,
)

_STATUS_LABELS = {
    "unreviewed": "Sin revisar",
    "needs_review": "Requiere revisión",
    "reviewed": "Revisado",
    "approved": "Aprobado",
}
_ACTION_LABELS = {
    "edit": "edición",
    "lifecycle": "cambio de estado",
    "reorder": "reordenamiento",
    "merge": "combinación",
    "split": "división",
    "add": "alta de objeto",
    "revert": "restauración de revisión",
    "assign_part": "asignación de parte interna",
}
_TAG_KIND_LABELS = {
    "thematic": "Temática",
    "conceptual": "Conceptual",
    "workflow": "Flujo de trabajo",
    "unclassified": "Sin clasificar",
}

_AUTHORITY_TYPE_LABELS = {
    "person": "Persona",
    "organization": "Organismo / institución",
    "place": "Lugar",
    "event": "Acontecimiento",
    "work": "Obra / publicación",
    "other": "Otra entidad",
}
_MENTION_STATUS_LABELS = {
    "pending": "Pendiente",
    "accepted": "Aceptada",
    "rejected": "Rechazada",
    "modified": "Modificada",
}


def _project_root_from_argv(argv: list[str] | None = None) -> Path:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--project-root", required=True)
    args, _unknown = parser.parse_known_args(argv if argv is not None else sys.argv[1:])
    return Path(args.project_root).expanduser().resolve()


def _snippet(text: str, limit: int = 72) -> str:
    compact = " ".join(text.split())
    if not compact:
        return "[sin texto]"
    return compact if len(compact) <= limit else compact[: limit - 1] + "…"


def _object_label(item: ReviewObjectRow, labels: dict[str, str]) -> str:
    state = " · eliminado" if item.lifecycle_status == "deleted" else ""
    review = _STATUS_LABELS.get(item.review_status, item.review_status)
    annotations = []
    if item.tags:
        annotations.append(
            ", ".join(
                f"{_TAG_KIND_LABELS.get(tag.tag_kind, tag.tag_kind)}: #{tag.tag}"
                for tag in item.tags[:3]
            )
        )
    if item.comment_count:
        annotations.append(f"{item.comment_count} com.")
    if item.document_part_key:
        annotations.append("parte " + item.document_part_key)
    suffix = " · " + " · ".join(annotations) if annotations else ""
    return (
        f"{item.order_index + 1}. {labels.get(item.object_type, item.object_type)}"
        f" · rev {item.revision_number} · {review}{state}{suffix} · {_snippet(item.text)}"
    )


def _pending_selection_key(selection_key: str) -> str:
    return selection_key + "__pending"


def _run_action(
    st,
    action: Callable[[], str | None],
    *,
    selection_key: str | None = None,
    fallback_selection: str | None = None,
) -> None:
    try:
        selected = action()
    except (ValueError, RuntimeError, OSError) as exc:
        st.error(str(exc))
    else:
        selection = selected or fallback_selection
        if selection_key and selection:
            # No se modifica la clave del widget ya instanciado. La selección se
            # aplica al comienzo del siguiente rerun, antes de crear el selectbox.
            st.session_state[_pending_selection_key(selection_key)] = selection
        st.rerun()


def _database_action(db_path: Path, callback: Callable) -> str | None:
    engine = create_sqlite_engine(db_path)
    try:
        with session_scope(engine) as session:
            result = callback(session)
            if isinstance(result, str):
                return result
            object_id = getattr(result, "id", None)
            return str(object_id) if object_id else None
    finally:
        engine.dispose()



def _apply_pending_app_mode(st) -> None:
    pending = st.session_state.pop("review_pending_app_mode", None)
    if pending in {"home", "catalog", "processing", "work", "review", "search", "semantic", "authorities", "graph", "export", "exchange", "admin"}:
        st.session_state["review_app_mode"] = pending


def _apply_pending_navigation(st, document_map: dict[str, object]) -> None:
    pending = st.session_state.pop("review_pending_navigation", None)
    if not isinstance(pending, dict):
        return
    source_key = pending.get("source_key")
    if source_key not in document_map:
        return
    document = document_map[source_key]
    page_options = document.editable_pages
    try:
        page = int(pending.get("page"))
    except (TypeError, ValueError):
        page = page_options[0]
    if page not in page_options:
        page = page_options[0]
    st.session_state["review_app_mode"] = "review"
    st.session_state["review_source_key"] = source_key
    st.session_state["review_page_source"] = source_key
    st.session_state["review_page_number"] = page
    object_id = pending.get("object_id")
    if object_id:
        st.session_state["review_pending_object_id"] = str(object_id)


def _highlight_search_snippet(value: str) -> str:
    escaped = html.escape(value)
    return escaped.replace("[[HIT]]", "<mark>").replace("[[/HIT]]", "</mark>")


def _render_search_view(st, *, db_path: Path, document_map, type_labels: dict[str, str]) -> None:
    st.header("Búsqueda transversal")
    st.caption(
        "Busca en textos revisados, OCR original, comentarios y etiquetas. "
        "Los resultados abren directamente el objeto en la página correspondiente."
    )
    field_labels = {
        "current_text": "Texto revisado",
        "original_text": "OCR original",
        "comments": "Comentarios",
        "tags": "Etiquetas",
        "entities": "Entidades, menciones y relaciones",
    }
    mode_labels = {"all": "Todas las palabras", "any": "Cualquiera", "phrase": "Frase exacta"}
    with st.form("search_corpus_form"):
        query = st.text_input(
            "Buscar",
            value=st.session_state.get("review_search_query", ""),
            placeholder="Ej.: contenido ideológico marxista",
        )
        left, right = st.columns(2)
        with left:
            match_mode = st.selectbox(
                "Coincidencia",
                options=list(MATCH_MODES),
                format_func=lambda value: mode_labels[value],
            )
            fields = st.multiselect(
                "Campos",
                options=list(SEARCH_FIELDS),
                default=list(SEARCH_FIELDS),
                format_func=lambda value: field_labels[value],
            )
            source_keys = st.multiselect(
                "Documentos",
                options=list(document_map),
                format_func=lambda key: f"{document_map[key].title} · {key}",
            )
            part_key = st.text_input("Clave de parte interna", placeholder="Opcional")
        with right:
            object_types = st.multiselect(
                "Tipos de objeto",
                options=list(type_labels),
                format_func=lambda value: type_labels.get(value, value),
            )
            object_statuses = st.multiselect(
                "Estado del objeto",
                options=list(REVIEW_STATUSES),
                format_func=lambda value: _STATUS_LABELS[value],
            )
            page_statuses = st.multiselect(
                "Estado de la página",
                options=list(REVIEW_STATUSES),
                format_func=lambda value: _STATUS_LABELS[value],
            )
            tag_kinds = st.multiselect(
                "Categorías de etiqueta presentes",
                options=list(TAG_KINDS),
                format_func=lambda value: _TAG_KIND_LABELS[value],
            )
            temporal_filter = st.checkbox(
                "Filtrar por temporalidad de entidades o relaciones vinculadas",
                value=False,
            )
            temporal_columns = st.columns(2)
            temporal_start = temporal_columns[0].date_input(
                "Desde", key="review_search_temporal_start"
            )
            temporal_end = temporal_columns[1].date_input(
                "Hasta", key="review_search_temporal_end"
            )
            temporal_include_undated = st.checkbox(
                "Incluir vínculos sin fecha",
                value=False,
            )
            include_deleted = st.checkbox("Incluir objetos eliminados", value=False)
            partial_words = st.checkbox(
                "Buscar también dentro de las palabras",
                value=False,
                help="Permite que 'marx' encuentre 'marxista' o 'averig' encuentre 'averiguaciones'. Cada fragmento debe tener al menos 3 caracteres.",
            )
            limit = st.number_input("Máximo de resultados", min_value=10, max_value=500, value=50, step=10)
        submitted = st.form_submit_button("Buscar", type="primary")
    if submitted:
        st.session_state["review_search_query"] = query
        st.session_state["review_search_params"] = {
            "query": query,
            "match_mode": match_mode,
            "fields": fields,
            "source_keys": source_keys,
            "object_types": object_types,
            "object_review_statuses": object_statuses,
            "page_review_statuses": page_statuses,
            "lifecycle_statuses": ["active", "deleted"] if include_deleted else ["active"],
            "document_part_keys": [part_key.strip()] if part_key.strip() else [],
            "tag_kinds": tag_kinds,
            "temporal_start": temporal_start if temporal_filter else None,
            "temporal_end": temporal_end if temporal_filter else None,
            "temporal_include_undated": (
                temporal_include_undated if temporal_filter else False
            ),
            "partial_words": partial_words,
            "limit": int(limit),
        }
    params = st.session_state.get("review_search_params")
    control_left, control_right = st.columns([1, 4])
    with control_left:
        rebuild_clicked = st.button("Reconstruir índice")
    if rebuild_clicked:
        engine = create_sqlite_engine(db_path)
        try:
            with session_scope(engine) as session:
                summary = rebuild_search_index(session)
        except (ValueError, RuntimeError, OSError) as exc:
            st.error(str(exc))
        else:
            st.success(f"Índice reconstruido: {summary.object_count} objetos")
        finally:
            engine.dispose()
    if not params:
        st.info("Escribí una consulta para comenzar.")
        return
    try:
        engine = create_sqlite_engine(db_path)
        try:
            with session_scope(engine) as session:
                results = search_editable_objects(session, **params)
                status = search_index_status(session)
        finally:
            engine.dispose()
    except (ValueError, RuntimeError, OSError) as exc:
        st.error(str(exc))
        return
    with control_right:
        indexed = status.indexed_at or "sin fecha"
        st.caption(
            f"Índice actualizado · generación {status.indexed_generation} · {indexed} · "
            f"resultados {len(results)}"
        )
    if not results:
        st.warning("No se encontraron coincidencias con los filtros seleccionados.")
        return
    for index, row in enumerate(results):
        with st.container(border=True):
            header, action = st.columns([5, 1])
            with header:
                part = f" · parte `{row.document_part_key}`" if row.document_part_key else ""
                st.markdown(
                    f"**{row.document_title}** · página **{row.page_number}** · "
                    f"objeto **{row.order_index + 1}** · "
                    f"{type_labels.get(row.object_type, row.object_type)}{part}"
                )
                st.caption(
                    f"{row.source_key} · objeto {_STATUS_LABELS.get(row.object_review_status, row.object_review_status)} "
                    f"· página {_STATUS_LABELS.get(row.page_review_status, row.page_review_status)} "
                    f"· coincidencia en {row.match_scope}"
                )
            with action:
                if st.button("Abrir", key=f"open_search_{index}_{row.object_id}", use_container_width=True):
                    st.session_state["review_pending_navigation"] = {
                        "source_key": row.source_key,
                        "page": row.page_number,
                        "object_id": row.object_id,
                    }
                    st.rerun()
            st.markdown(_highlight_search_snippet(row.snippet), unsafe_allow_html=True)



def _format_exchange_value(value) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)
    return repr(value)


def _run_exchange_action(st, *, db_path: Path, callback: Callable) -> None:
    engine = create_sqlite_engine(db_path)
    try:
        with session_scope(engine) as session:
            message = callback(session)
    except (ValueError, RuntimeError, OSError, json.JSONDecodeError) as exc:
        st.error(str(exc))
        return
    finally:
        engine.dispose()
    st.session_state["exchange_flash"] = str(message or "Operación completada")
    st.rerun()


def _render_exchange_view(st, *, project_root: Path, db_path: Path, reviewer: str) -> None:
    st.header("Intercambio offline")
    st.caption(
        "Recibe, evalúa y resuelve bundles sin modificar el corpus hasta la aplicación "
        "transaccional con backup."
    )
    flash = st.session_state.pop("exchange_flash", None)
    if flash:
        st.success(flash)

    engine = create_sqlite_engine(db_path)
    try:
        with session_scope(engine) as session:
            workspace = exchange_status(session)
            incoming = incoming_bundle_rows(session)
            applications = bundle_application_rows(session)
    except (ValueError, RuntimeError, OSError) as exc:
        st.error(str(exc))
        return
    finally:
        engine.dispose()

    cols = st.columns(4)
    cols[0].metric("Copia", workspace.workspace_name)
    cols[1].metric("Secuencia local", workspace.current_sequence)
    cols[2].metric("Eventos pendientes", workspace.pending_event_count)
    cols[3].metric("Bundles recibidos", len(incoming))

    with st.expander("Recibir y evaluar un bundle ZIP", expanded=not incoming):
        uploaded = st.file_uploader("Bundle", type=["zip"], key="exchange_bundle_upload")
        if uploaded is not None:
            st.caption(f"{uploaded.name} · {uploaded.size} bytes")
        if st.button(
            "Ejecutar dry-run",
            type="primary",
            disabled=uploaded is None,
            key="exchange_upload_dry_run",
        ):
            assert uploaded is not None
            payload = uploaded.getvalue()
            digest = hashlib.sha256(payload).hexdigest()[:16]
            upload_dir = project_root / "exchange" / "ui_uploads"
            upload_dir.mkdir(parents=True, exist_ok=True)
            temp_path = upload_dir / f"{digest}.zip"
            temp_path.write_bytes(payload)

            def callback(session):
                summary = dry_run_change_bundle(
                    session,
                    project_root=project_root,
                    bundle_path=temp_path,
                    assessed_by=reviewer or "local_user",
                )
                return (
                    f"Dry-run {summary.bundle_id}: {summary.overall_status} · "
                    f"A {summary.counts.get('apply', 0)} · "
                    f"D {summary.counts.get('duplicate', 0)} · "
                    f"R {summary.counts.get('review', 0)} · "
                    f"C {summary.counts.get('conflict', 0)}"
                )

            _run_exchange_action(st, db_path=db_path, callback=callback)

    if not incoming:
        st.info("Todavía no hay bundles recibidos.")
        return

    incoming_map = {row.bundle_id: row for row in incoming}
    selected_bundle = st.selectbox(
        "Bundle recibido",
        options=list(incoming_map),
        format_func=lambda key: (
            f"{incoming_map[key].source_workspace_name} · {key[:8]} · "
            f"{incoming_map[key].status}"
        ),
        key="exchange_selected_bundle",
    )
    selected = incoming_map[selected_bundle]
    counts = selected.counts
    st.write(
        f"**Estado:** `{selected.status}` · **base:** `{selected.base_match_status}` · "
        f"**eventos:** {selected.event_count} · "
        f"A {counts.get('apply', 0)} · D {counts.get('duplicate', 0)} · "
        f"R {counts.get('review', 0)} · C {counts.get('conflict', 0)}"
    )

    engine = create_sqlite_engine(db_path)
    try:
        with session_scope(engine) as session:
            status = resolution_status(session, selected_bundle)
            conflict_rows = conflict_field_rows(session, selected_bundle)
    except ValueError:
        status = None
        conflict_rows = []
    finally:
        engine.dispose()

    if status is not None and status.event_count:
        st.caption(
            f"Campos que requieren decisión: {status.resolved_field_count}/{status.field_count} · "
            f"coincidencias automáticas: {status.auto_matched_field_count} · "
            f"pendientes: {status.unresolved_field_count}"
        )

    if selected.status == "stale":
        st.warning("El dry-run está caduco. Volvé a evaluarlo desde la CLI o cargá nuevamente el ZIP.")

    if conflict_rows:
        st.subheader("Resolución de conflictos")
        confirm_bulk = st.checkbox(
            "Confirmo que deseo aplicar una misma decisión a todos los campos pendientes",
            key=f"exchange_confirm_bulk_{selected_bundle}",
        )
        bulk_local, bulk_incoming = st.columns(2)
        with bulk_local:
            if st.button(
                "Conservar todos los valores locales",
                disabled=not confirm_bulk,
                use_container_width=True,
                key=f"exchange_bulk_local_{selected_bundle}",
            ):
                _run_exchange_action(
                    st,
                    db_path=db_path,
                    callback=lambda session: (
                        lambda result: (
                            f"Resueltos {result.resolved_field_count} campos como local; "
                            f"{result.auto_matched_field_count} coincidían automáticamente"
                        )
                    )(
                        resolve_conflict_fields_bulk(
                            session,
                            bundle_ref=selected_bundle,
                            choice="local",
                            resolved_by=reviewer or "local_user",
                        )
                    ),
                )
        with bulk_incoming:
            if st.button(
                "Aceptar todos los valores recibidos",
                disabled=not confirm_bulk,
                use_container_width=True,
                key=f"exchange_bulk_incoming_{selected_bundle}",
            ):
                _run_exchange_action(
                    st,
                    db_path=db_path,
                    callback=lambda session: (
                        lambda result: (
                            f"Resueltos {result.resolved_field_count} campos como incoming; "
                            f"{result.auto_matched_field_count} coincidían automáticamente"
                        )
                    )(
                        resolve_conflict_fields_bulk(
                            session,
                            bundle_ref=selected_bundle,
                            choice="incoming",
                            resolved_by=reviewer or "local_user",
                        )
                    ),
                )

        by_event: dict[str, list] = {}
        for row in conflict_rows:
            by_event.setdefault(row.event_id, []).append(row)
        for event_id, rows in by_event.items():
            first = rows[0]
            with st.expander(
                f"Evento {event_id[:8]} · {first.entity_type}/{first.entity_id[:8]} · "
                f"{len(rows)} campo(s)",
                expanded=len(by_event) == 1,
            ):
                event_local, event_incoming = st.columns(2)
                with event_local:
                    if st.button(
                        "Todo local en este evento",
                        key=f"exchange_event_local_{selected_bundle}_{event_id}",
                        use_container_width=True,
                    ):
                        _run_exchange_action(
                            st,
                            db_path=db_path,
                            callback=lambda session, event_id=event_id: (
                                lambda result: f"Evento resuelto: {result.resolved_field_count} campos locales"
                            )(
                                resolve_conflict_fields_bulk(
                                    session,
                                    bundle_ref=selected_bundle,
                                    event_id=event_id,
                                    choice="local",
                                    resolved_by=reviewer or "local_user",
                                )
                            ),
                        )
                with event_incoming:
                    if st.button(
                        "Todo recibido en este evento",
                        key=f"exchange_event_incoming_{selected_bundle}_{event_id}",
                        use_container_width=True,
                    ):
                        _run_exchange_action(
                            st,
                            db_path=db_path,
                            callback=lambda session, event_id=event_id: (
                                lambda result: f"Evento resuelto: {result.resolved_field_count} campos recibidos"
                            )(
                                resolve_conflict_fields_bulk(
                                    session,
                                    bundle_ref=selected_bundle,
                                    event_id=event_id,
                                    choice="incoming",
                                    resolved_by=reviewer or "local_user",
                                )
                            ),
                        )
                for row in rows:
                    st.markdown(f"**Campo `{row.field_name}`**")
                    base_col, local_col, incoming_col = st.columns(3)
                    base_col.caption("Base")
                    base_col.code(_format_exchange_value(row.base_value), language="text")
                    local_col.caption("Local")
                    local_col.code(_format_exchange_value(row.local_value), language="text")
                    incoming_col.caption("Recibido")
                    incoming_col.code(_format_exchange_value(row.incoming_value), language="text")
                    choice_key = f"exchange_choice_{selected_bundle}_{event_id}_{row.field_name}"
                    default_choice = row.choice if row.choice in {"local", "incoming", "custom"} else "local"
                    choice = st.radio(
                        "Decisión",
                        options=["local", "incoming", "custom"],
                        index=["local", "incoming", "custom"].index(default_choice),
                        horizontal=True,
                        key=choice_key,
                    )
                    custom_text = ""
                    as_json = False
                    if choice == "custom":
                        custom_text = st.text_area(
                            "Valor conciliado",
                            value=_format_exchange_value(row.resolved_value),
                            key=f"exchange_custom_{selected_bundle}_{event_id}_{row.field_name}",
                        )
                        as_json = st.checkbox(
                            "Interpretar como JSON",
                            value=isinstance(row.local_value, (dict, list)),
                            key=f"exchange_custom_json_{selected_bundle}_{event_id}_{row.field_name}",
                        )
                    if st.button(
                        "Guardar decisión",
                        key=f"exchange_save_{selected_bundle}_{event_id}_{row.field_name}",
                    ):
                        _run_exchange_action(
                            st,
                            db_path=db_path,
                            callback=lambda session, row=row, choice=choice, custom_text=custom_text, as_json=as_json: (
                                lambda saved: f"Decisión guardada: {saved.field_name} → {saved.choice}"
                            )(
                                save_conflict_resolution(
                                    session,
                                    bundle_ref=selected_bundle,
                                    event_id=row.event_id,
                                    field_name=row.field_name,
                                    choice=choice,
                                    custom_value=(
                                        json.loads(custom_text) if choice == "custom" and as_json
                                        else custom_text if choice == "custom"
                                        else None
                                    ),
                                    resolved_by=reviewer or "local_user",
                                )
                            ),
                        )

    if status is not None:
        controls = st.columns(2)
        with controls[0]:
            can_finalize = status.overall_status in {"ready_to_finalize", "ready_to_apply_resolved"}
            if st.button(
                "Finalizar resoluciones",
                disabled=not can_finalize,
                use_container_width=True,
                key=f"exchange_finalize_{selected_bundle}",
            ):
                _run_exchange_action(
                    st,
                    db_path=db_path,
                    callback=lambda session: (
                        lambda result: (
                            "El bundle ya estaba finalizado"
                            if result.already_finalized
                            else "Resoluciones finalizadas"
                        )
                    )(
                        finalize_bundle_resolutions(
                            session,
                            bundle_ref=selected_bundle,
                            finalized_by=reviewer or "local_user",
                        )
                    ),
                )
        with controls[1]:
            confirm_apply = st.checkbox(
                "Confirmar aplicación con backup",
                key=f"exchange_confirm_apply_{selected_bundle}",
            )
            if st.button(
                "Aplicar bundle",
                type="primary",
                disabled=(
                    not confirm_apply
                    or selected.status not in {"ready_to_apply", "ready_to_apply_resolved"}
                ),
                use_container_width=True,
                key=f"exchange_apply_{selected_bundle}",
            ):
                _run_exchange_action(
                    st,
                    db_path=db_path,
                    callback=lambda session: (
                        lambda result: (
                            f"Bundle aplicado: {result.applied_event_count} cambios, "
                            f"{result.duplicate_event_count} duplicados y "
                            f"{result.kept_local_event_count} conservados localmente"
                        )
                    )(
                        apply_change_bundle(
                            session,
                            project_root=project_root,
                            bundle_ref=selected_bundle,
                            applied_by=reviewer or "local_user",
                        )
                    ),
                )

    if applications:
        with st.expander("Aplicaciones anteriores"):
            for row in applications:
                st.write(
                    f"`{row.bundle_id}` · aplicados {row.applied_event_count} · "
                    f"duplicados {row.duplicate_event_count} · "
                    f"local {row.kept_local_event_count} · checkpoint `{row.checkpoint_label}`"
                )

def main() -> None:
    import streamlit as st

    st.set_page_config(page_title="Archive Workbench", layout="wide")
    project_root = _project_root_from_argv()
    decisions_path = project_root / "config" / "decisions.yaml"
    db_path = database_path(project_root)
    if not decisions_path.is_file() or not db_path.is_file():
        st.error(
            "El proyecto no está inicializado o no tiene base de datos. "
            "Ejecutá primero archive-workbench db-upgrade."
        )
        st.stop()

    decisions = load_decisions(decisions_path)
    type_definitions = [item for item in decisions.object_types if item.editable]
    type_keys = [item.key for item in type_definitions]
    type_labels = {item.key: item.label for item in type_definitions}
    engine = create_sqlite_engine(db_path)
    try:
        with session_scope(engine) as session:
            documents = review_document_rows(session)
    finally:
        engine.dispose()

    st.title("Archive Workbench")
    document_map = {item.source_key: item for item in documents}
    _apply_pending_app_mode(st)
    _apply_pending_navigation(st, document_map)
    with st.sidebar:
        st.header("Navegación")
        reviewer = st.text_input("Responsable", value="alex")
        app_mode = st.radio(
            "Vista",
            options=["home", "catalog", "processing", "work", "review", "search", "semantic", "authorities", "graph", "export", "exchange", "admin"],
            format_func=lambda value: {
                "home": "Inicio",
                "catalog": "Catálogo",
                "processing": "Procesamiento",
                "work": "Trabajo",
                "review": "Revisión",
                "search": "Búsqueda literal",
                "semantic": "Búsqueda semántica",
                "authorities": "Entidades",
                "graph": "Grafo",
                "export": "Exportar",
                "exchange": "Intercambio",
                "admin": "Administración",
            }[value],
            key="review_app_mode",
        )
    if app_mode == "home":
        render_home_view(
            st,
            project_root=project_root,
            db_path=db_path,
            actor=reviewer,
        )
        return
    if app_mode == "catalog":
        render_catalog_view(
            st,
            project_root=project_root,
            db_path=db_path,
            decisions=decisions,
            actor=reviewer,
        )
        return
    if app_mode == "processing":
        render_processing_view(
            st,
            project_root=project_root,
            db_path=db_path,
            decisions=decisions,
            project_id=decisions.project_id,
            actor=reviewer,
        )
        return
    if app_mode == "work":
        render_work_view(
            st,
            project_root=project_root,
            db_path=db_path,
            project_id=decisions.project_id,
            actor=reviewer,
        )
        return
    if app_mode == "authorities":
        render_authorities_view(
            st,
            db_path=db_path,
            project_id=decisions.project_id,
            actor=reviewer,
        )
        return
    if app_mode == "graph":
        render_graph_view(
            st,
            project_root=project_root,
            db_path=db_path,
            project_id=decisions.project_id,
            actor=reviewer,
        )
        return
    if app_mode == "export":
        render_export_view(
            st,
            project_root=project_root,
            db_path=db_path,
            project_id=decisions.project_id,
            actor=reviewer,
            object_types=type_keys,
            object_type_labels=type_labels,
        )
        return
    if app_mode == "semantic":
        render_semantic_search_view(
            st,
            project_root=project_root,
            db_path=db_path,
            project_id=decisions.project_id,
            actor=reviewer,
            object_types=type_keys,
            object_type_labels=type_labels,
        )
        return
    if app_mode == "search":
        if not documents:
            st.info("No hay documentos inicializados en la capa editable para buscar.")
            return
        _render_search_view(
            st,
            db_path=db_path,
            document_map=document_map,
            type_labels=type_labels,
        )
        return
    if app_mode == "exchange":
        _render_exchange_view(
            st,
            project_root=project_root,
            db_path=db_path,
            reviewer=reviewer,
        )
        return
    if app_mode == "admin":
        render_admin_view(
            st,
            project_root=project_root,
            db_path=db_path,
            actor=reviewer,
        )
        return
    st.header("Revisión documental")
    st.caption(
        "La imagen y el OCR de origen permanecen inmutables. Cada guardado crea una nueva revisión."
    )
    if not documents:
        st.info("No hay documentos inicializados en la capa editable.")
        st.code(
            "archive-workbench editor-bootstrap project_data "
            "--source-key CLAVE --created-by NOMBRE"
        )
        return

    with st.sidebar:
        source_key = st.selectbox(
            "Documento",
            options=list(document_map),
            format_func=lambda key: f"{document_map[key].title} · {key}",
            key="review_source_key",
        )
        document = document_map[source_key]
        state_source = st.session_state.get("review_page_source")
        if state_source != source_key:
            st.session_state["review_page_source"] = source_key
            st.session_state["review_page_number"] = document.editable_pages[0]
        page_options = document.editable_pages
        current_page = st.session_state.get("review_page_number", page_options[0])
        if current_page not in page_options:
            st.session_state["review_page_number"] = page_options[0]
        previous_col, next_col = st.columns(2)
        with previous_col:
            if st.button("← Anterior", use_container_width=True):
                index = page_options.index(st.session_state["review_page_number"])
                if index > 0:
                    st.session_state["review_page_number"] = page_options[index - 1]
                    st.rerun()
        with next_col:
            if st.button("Siguiente →", use_container_width=True):
                index = page_options.index(st.session_state["review_page_number"])
                if index < len(page_options) - 1:
                    st.session_state["review_page_number"] = page_options[index + 1]
                    st.rerun()
        page = st.selectbox("Página física", options=page_options, key="review_page_number")
        show_boxes = st.checkbox("Mostrar cajas OCR", value=True)
        include_deleted = st.checkbox("Mostrar objetos eliminados", value=False)
        st.divider()
        st.write(f"Páginas editables: **{len(document.editable_pages)}/{document.page_count}**")
        st.write(f"Objetos activos: **{document.active_objects}**")
        if document.deleted_objects:
            st.write(f"Objetos eliminados: **{document.deleted_objects}**")
        if document.stale_pages:
            st.warning("Capa desactualizada en páginas: " + ", ".join(map(str, document.stale_pages)))
        if st.button("Exportar estado editable", use_container_width=True):
            def export_action() -> str | None:
                def callback(session):
                    summary = export_editable_layer(
                        session,
                        project_root=project_root,
                        source_key=source_key,
                    )
                    st.session_state["last_export"] = str(summary.output_root)
                return _database_action(db_path, callback)

            _run_action(st, export_action)
        if st.session_state.get("last_export"):
            st.caption("Última exportación: " + st.session_state["last_export"])

    engine = create_sqlite_engine(db_path)
    try:
        with session_scope(engine) as session:
            view = review_page_view(
                session,
                project_root=project_root,
                source_key=source_key,
                page=page,
                include_deleted=include_deleted,
            )
            availability = page_action_availability(
                session, editable_page_id=view.editable_page_id
            )
    finally:
        engine.dispose()

    with st.sidebar:
        st.divider()
        st.subheader("Estado de la página")
        with st.form(f"page_review_{view.editable_page_id}"):
            page_status = st.selectbox(
                "Revisión",
                options=list(REVIEW_STATUSES),
                index=list(REVIEW_STATUSES).index(view.page_review_status),
                format_func=lambda value: _STATUS_LABELS[value],
            )
            page_note = st.text_area("Nota de página", value=view.page_review_note or "", height=90)
            page_review_submit = st.form_submit_button("Guardar estado")
        if page_review_submit:
            _run_action(
                st,
                lambda: _database_action(
                    db_path,
                    lambda session: set_page_review_status(
                        session,
                        editable_page_id=view.editable_page_id,
                        status=page_status,
                        changed_by=reviewer or "local_user",
                        note=page_note,
                    ),
                ),
            )

    if view.is_stale:
        st.warning(
            "La extracción seleccionada para esta página cambió después de crear la capa editable. "
            "Las correcciones se conservan, pero no deben mezclarse automáticamente con el nuevo OCR."
        )

    objects_by_id = {item.object_id: item for item in view.objects}
    object_ids = list(objects_by_id)
    object_state_key = f"review_object_{source_key}_{page}_{include_deleted}"
    search_target_object = st.session_state.pop("review_pending_object_id", None)
    if search_target_object in objects_by_id:
        st.session_state[_pending_selection_key(object_state_key)] = search_target_object
    pending_selection = st.session_state.pop(
        _pending_selection_key(object_state_key), None
    )
    if pending_selection in objects_by_id:
        st.session_state[object_state_key] = pending_selection
    selected_id = st.session_state.get(object_state_key)
    if selected_id not in objects_by_id:
        selected_id = object_ids[0] if object_ids else None
        st.session_state[object_state_key] = selected_id

    undo_col, redo_col, action_info_col = st.columns([1, 1, 4])
    with undo_col:
        undo_clicked = st.button(
            "↶ Deshacer",
            disabled=not availability.can_undo,
            use_container_width=True,
            help=(
                "Deshacer " + _ACTION_LABELS.get(availability.undo_label or "", availability.undo_label or "")
                if availability.can_undo
                else "No hay acciones nuevas para deshacer"
            ),
        )
    with redo_col:
        redo_clicked = st.button(
            "↷ Rehacer",
            disabled=not availability.can_redo,
            use_container_width=True,
            help=(
                "Rehacer " + _ACTION_LABELS.get(availability.redo_label or "", availability.redo_label or "")
                if availability.can_redo
                else "No hay acciones para rehacer"
            ),
        )
    with action_info_col:
        st.caption(
            "Deshacer/rehacer opera sobre la última acción completa de esta página, "
            "incluidos reordenamientos, combinaciones y divisiones."
        )
    if undo_clicked:
        _run_action(
            st,
            lambda: _database_action(
                db_path,
                lambda session: undo_page_action(
                    session,
                    editable_page_id=view.editable_page_id,
                    changed_by=reviewer or "local_user",
                ),
            ),
            selection_key=object_state_key,
            fallback_selection=selected_id,
        )
    if redo_clicked:
        _run_action(
            st,
            lambda: _database_action(
                db_path,
                lambda session: redo_page_action(
                    session,
                    editable_page_id=view.editable_page_id,
                    changed_by=reviewer or "local_user",
                ),
            ),
            selection_key=object_state_key,
            fallback_selection=selected_id,
        )

    image_column, editor_column = st.columns([1.15, 1], gap="large")
    with image_column:
        st.subheader(f"{view.title} · página {page}/{view.page_count}")
        if view.preview_path is None:
            st.info("No se encontró el derivado de vista para esta página.")
        elif show_boxes:
            clicked_id = clickable_review_canvas(
                view.preview_path,
                view.objects,
                page=page,
                selected_object_id=selected_id,
                show_deleted=include_deleted,
                key=f"review_canvas_{source_key}_{page}_{include_deleted}",
            )
            if clicked_id in objects_by_id and clicked_id != selected_id:
                st.session_state[object_state_key] = clicked_id
                st.rerun()
            if clicked_id is None and not hasattr(st.components, "v2"):
                overlay = render_review_overlay(
                    view.preview_path,
                    view.objects,
                    page=page,
                    selected_object_id=selected_id,
                    show_deleted=include_deleted,
                )
                st.image(overlay, use_container_width=True)
                st.info(
                    "La selección directa requiere Streamlit 1.51 o posterior. "
                    "La lista de objetos sigue disponible."
                )
        else:
            st.image(str(view.preview_path), use_container_width=True)
        st.caption(
            "Las cajas son interactivas. Acercá con los botones o Ctrl+rueda y arrastrá "
            "el fondo para recorrer la página."
        )

    with editor_column:
        st.subheader("Objetos editables")
        if not object_ids:
            st.info("Esta página no tiene objetos visibles con el filtro actual.")
        else:
            selected_id = st.selectbox(
                "Objeto",
                options=object_ids,
                format_func=lambda oid: _object_label(objects_by_id[oid], type_labels),
                key=object_state_key,
            )
            selected = objects_by_id[selected_id]
            metadata_a, metadata_b, metadata_c, metadata_d = st.columns(4)
            metadata_a.metric("Orden", selected.order_index + 1)
            metadata_b.metric("Revisión", selected.revision_number)
            metadata_c.metric("Estado", selected.lifecycle_status)
            metadata_d.metric("Revisión humana", _STATUS_LABELS[selected.review_status])
            if selected.document_part_title:
                st.caption(
                    f"Parte interna: **{selected.document_part_title}** "
                    f"(`{selected.document_part_key}`)"
                )
            else:
                st.caption("Parte interna: sin asignar")
            if selected.manually_added:
                st.caption("Objeto agregado manualmente")
            else:
                confidence = selected.attributes.get("source_confidence")
                if confidence is not None:
                    st.caption(f"Confianza OCR de origen: {float(confidence):.1%}")

            edit_tab, structure_tab, annotations_tab, entities_tab, history_tab, add_tab = st.tabs(
                ["Editar", "Estructura", "Anotaciones", "Entidades", "Historial", "Agregar objeto"]
            )
            with edit_tab:
                with st.form(f"edit_{selected.object_id}_{selected.revision_number}"):
                    new_text = st.text_area("Texto corregido", value=selected.text, height=260)
                    type_index = type_keys.index(selected.object_type) if selected.object_type in type_keys else 0
                    new_type = st.selectbox(
                        "Tipo de objeto",
                        options=type_keys,
                        index=type_index,
                        format_func=lambda key: type_labels.get(key, key),
                    )
                    note = st.text_input("Nota de revisión")
                    save = st.form_submit_button("Guardar nueva revisión", type="primary")
                if save:
                    def save_callback(session):
                        return execute_page_action(
                            session,
                            editable_page_id=view.editable_page_id,
                            action_type="edit",
                            changed_by=reviewer or "local_user",
                            selected_object_id=selected.object_id,
                            note=note or None,
                            action=lambda: update_editable_object(
                                session,
                                decisions=decisions,
                                object_id=selected.object_id,
                                expected_revision=selected.revision_number,
                                edited_by=reviewer or "local_user",
                                text=new_text,
                                object_type=new_type,
                                note=note or None,
                            ),
                        )
                    _run_action(
                        st,
                        lambda: _database_action(db_path, save_callback),
                        selection_key=object_state_key,
                        fallback_selection=selected.object_id,
                    )

                if selected.original_text is not None:
                    with st.expander("Ver OCR original inmutable"):
                        st.text(selected.original_text)

                lifecycle_label = (
                    "Restaurar objeto" if selected.lifecycle_status == "deleted" else "Marcar como eliminado"
                )
                with st.form(f"lifecycle_{selected.object_id}_{selected.revision_number}"):
                    lifecycle_note = st.text_input("Motivo", key=f"life_note_{selected.object_id}")
                    lifecycle_submit = st.form_submit_button(lifecycle_label)
                if lifecycle_submit:
                    target_status = "active" if selected.lifecycle_status == "deleted" else "deleted"
                    def lifecycle_callback(session):
                        return execute_page_action(
                            session,
                            editable_page_id=view.editable_page_id,
                            action_type="lifecycle",
                            changed_by=reviewer or "local_user",
                            selected_object_id=selected.object_id,
                            note=lifecycle_note or None,
                            action=lambda: set_editable_object_lifecycle(
                                session,
                                object_id=selected.object_id,
                                expected_revision=selected.revision_number,
                                lifecycle_status=target_status,
                                changed_by=reviewer or "local_user",
                                note=lifecycle_note or None,
                            ),
                        )
                    _run_action(
                        st,
                        lambda: _database_action(db_path, lifecycle_callback),
                        selection_key=object_state_key,
                        fallback_selection=selected.object_id,
                    )

            with structure_tab:
                st.write("**Parte interna**")
                if view.parts:
                    part_map = {item.part_id: item for item in view.parts}
                    part_options = [None, *part_map]
                    current_part = (
                        selected.document_part_id
                        if selected.document_part_id in part_map
                        else None
                    )
                    with st.form(
                        f"assign_part_{selected.object_id}_{selected.revision_number}"
                    ):
                        selected_part_id = st.selectbox(
                            "Asignación del objeto",
                            options=part_options,
                            index=part_options.index(current_part),
                            format_func=lambda value: (
                                "Sin asignar"
                                if value is None
                                else f"{part_map[value].title} · {part_map[value].part_type}"
                            ),
                        )
                        part_note = st.text_input("Nota de asignación")
                        assign_part_submit = st.form_submit_button(
                            "Guardar parte del objeto"
                        )
                    if assign_part_submit:
                        def assign_part_callback(session):
                            return execute_page_action(
                                session,
                                editable_page_id=view.editable_page_id,
                                action_type="assign_part",
                                changed_by=reviewer or "local_user",
                                selected_object_id=selected.object_id,
                                note=part_note or None,
                                action=lambda: assign_editable_object_part(
                                    session,
                                    object_id=selected.object_id,
                                    part_id=selected_part_id,
                                    expected_revision=selected.revision_number,
                                    changed_by=reviewer or "local_user",
                                    note=part_note or None,
                                ),
                            )
                        _run_action(
                            st,
                            lambda: _database_action(db_path, assign_part_callback),
                            selection_key=object_state_key,
                            fallback_selection=selected.object_id,
                        )

                    with st.form(f"assign_page_part_{view.editable_page_id}"):
                        page_part_id = st.selectbox(
                            "Asignar todos los objetos activos de la página",
                            options=part_options,
                            format_func=lambda value: (
                                "Sin asignar"
                                if value is None
                                else f"{part_map[value].title} · {part_map[value].part_type}"
                            ),
                            key=f"page_part_choice_{view.editable_page_id}",
                        )
                        bulk_note = st.text_input("Nota para la asignación conjunta")
                        bulk_part_submit = st.form_submit_button(
                            "Aplicar a toda la página"
                        )
                    if bulk_part_submit:
                        def bulk_part_callback(session):
                            return execute_page_action(
                                session,
                                editable_page_id=view.editable_page_id,
                                action_type="assign_part",
                                changed_by=reviewer or "local_user",
                                selected_object_id=selected.object_id,
                                note=bulk_note or None,
                                action=lambda: assign_page_objects_to_part(
                                    session,
                                    editable_page_id=view.editable_page_id,
                                    part_id=page_part_id,
                                    changed_by=reviewer or "local_user",
                                    note=bulk_note or None,
                                ),
                            )
                        _run_action(
                            st,
                            lambda: _database_action(db_path, bulk_part_callback),
                            selection_key=object_state_key,
                            fallback_selection=selected.object_id,
                        )
                else:
                    st.caption(
                        "Esta página no pertenece a una parte interna registrada."
                    )
                st.divider()
                st.caption(
                    "Estas operaciones se registran como una acción de página y pueden deshacerse."
                )
                active_orders = [item.order_index for item in view.objects if item.lifecycle_status == "active"]
                move_left, move_right = st.columns(2)
                with move_left:
                    move_up = st.button(
                        "↑ Mover arriba",
                        use_container_width=True,
                        disabled=selected.lifecycle_status != "active" or selected.order_index <= 0,
                        key=f"move_up_{selected.object_id}_{selected.revision_number}",
                    )
                with move_right:
                    move_down = st.button(
                        "↓ Mover abajo",
                        use_container_width=True,
                        disabled=(
                            selected.lifecycle_status != "active"
                            or not active_orders
                            or selected.order_index >= max(active_orders)
                        ),
                        key=f"move_down_{selected.object_id}_{selected.revision_number}",
                    )
                if move_up or move_down:
                    direction = "up" if move_up else "down"
                    def move_callback(session):
                        return execute_page_action(
                            session,
                            editable_page_id=view.editable_page_id,
                            action_type="reorder",
                            changed_by=reviewer or "local_user",
                            selected_object_id=selected.object_id,
                            action=lambda: move_editable_object(
                                session,
                                object_id=selected.object_id,
                                expected_revision=selected.revision_number,
                                direction=direction,
                                changed_by=reviewer or "local_user",
                            ),
                        )
                    _run_action(
                        st,
                        lambda: _database_action(db_path, move_callback),
                        selection_key=object_state_key,
                        fallback_selection=selected.object_id,
                    )

                st.divider()
                st.write("**Combinar con un objeto adyacente**")
                separator_label = st.selectbox(
                    "Separación entre textos",
                    options=["blank_line", "line", "space", "none"],
                    format_func=lambda value: {
                        "blank_line": "Línea en blanco",
                        "line": "Salto de línea",
                        "space": "Espacio",
                        "none": "Sin separación",
                    }[value],
                    key=f"merge_separator_{selected.object_id}",
                )
                separators = {"blank_line": "\n\n", "line": "\n", "space": " ", "none": ""}
                merge_previous_col, merge_next_col = st.columns(2)
                with merge_previous_col:
                    merge_previous = st.button(
                        "Combinar con anterior",
                        use_container_width=True,
                        disabled=selected.lifecycle_status != "active" or selected.order_index <= 0,
                        key=f"merge_prev_{selected.object_id}_{selected.revision_number}",
                    )
                with merge_next_col:
                    merge_next = st.button(
                        "Combinar con siguiente",
                        use_container_width=True,
                        disabled=(
                            selected.lifecycle_status != "active"
                            or not active_orders
                            or selected.order_index >= max(active_orders)
                        ),
                        key=f"merge_next_{selected.object_id}_{selected.revision_number}",
                    )
                if merge_previous or merge_next:
                    direction = "previous" if merge_previous else "next"
                    def merge_callback(session):
                        return execute_page_action(
                            session,
                            editable_page_id=view.editable_page_id,
                            action_type="merge",
                            changed_by=reviewer or "local_user",
                            selected_object_id=selected.object_id,
                            action=lambda: merge_editable_object(
                                session,
                                object_id=selected.object_id,
                                expected_revision=selected.revision_number,
                                direction=direction,
                                separator=separators[separator_label],
                                changed_by=reviewer or "local_user",
                            ),
                        )
                    _run_action(
                        st,
                        lambda: _database_action(db_path, merge_callback),
                        selection_key=object_state_key,
                        fallback_selection=selected.object_id,
                    )

                st.divider()
                st.write("**Dividir el objeto seleccionado**")
                split_marker = "[[DIVIDIR]]"
                with st.form(f"split_{selected.object_id}_{selected.revision_number}"):
                    split_source = st.text_area(
                        f"Insertá {split_marker} en el punto de división",
                        value=selected.text,
                        height=250,
                    )
                    split_note = st.text_input("Nota de división")
                    split_submit = st.form_submit_button(
                        "Dividir en dos objetos",
                        disabled=selected.lifecycle_status != "active",
                    )
                if split_submit:
                    if split_source.count(split_marker) != 1:
                        st.error(f"El texto debe contener exactamente una marca {split_marker}.")
                    else:
                        left_text, right_text = split_source.split(split_marker, 1)
                        def split_callback(session):
                            return execute_page_action(
                                session,
                                editable_page_id=view.editable_page_id,
                                action_type="split",
                                changed_by=reviewer or "local_user",
                                selected_object_id=selected.object_id,
                                note=split_note or None,
                                action=lambda: split_editable_object(
                                    session,
                                    object_id=selected.object_id,
                                    expected_revision=selected.revision_number,
                                    left_text=left_text,
                                    right_text=right_text,
                                    changed_by=reviewer or "local_user",
                                    note=split_note or None,
                                ),
                            )
                        _run_action(
                            st,
                            lambda: _database_action(db_path, split_callback),
                            selection_key=object_state_key,
                            fallback_selection=selected.object_id,
                        )

            with annotations_tab:
                with st.form(f"object_review_{selected.object_id}"):
                    object_review_status = st.selectbox(
                        "Estado de revisión del objeto",
                        options=list(REVIEW_STATUSES),
                        index=list(REVIEW_STATUSES).index(selected.review_status),
                        format_func=lambda value: _STATUS_LABELS[value],
                    )
                    object_review_submit = st.form_submit_button("Guardar estado del objeto")
                if object_review_submit:
                    _run_action(
                        st,
                        lambda: _database_action(
                            db_path,
                            lambda session: set_object_review_status(
                                session,
                                object_id=selected.object_id,
                                status=object_review_status,
                                changed_by=reviewer or "local_user",
                            ),
                        ),
                        selection_key=object_state_key,
                        fallback_selection=selected.object_id,
                    )

                st.write("**Etiquetas**")
                if selected.tags:
                    for tag in selected.tags:
                        tag_col, remove_col = st.columns([5, 1])
                        tag_col.write(
                            f"**{_TAG_KIND_LABELS.get(tag.tag_kind, tag.tag_kind)}:** "
                            f"`{tag.tag}`"
                        )
                        if remove_col.button(
                            "×", key=f"remove_tag_{selected.object_id}_{tag.tag_id}"
                        ):
                            _run_action(
                                st,
                                lambda tag_id=tag.tag_id: _database_action(
                                    db_path,
                                    lambda session: remove_object_tag(
                                        session,
                                        object_id=selected.object_id,
                                        tag_id=tag_id,
                                    ),
                                ),
                                selection_key=object_state_key,
                                fallback_selection=selected.object_id,
                            )
                else:
                    st.caption("Sin etiquetas")
                with st.form(f"add_tag_{selected.object_id}", clear_on_submit=True):
                    tag_kind = st.selectbox(
                        "Categoría",
                        options=list(TAG_KINDS),
                        format_func=lambda value: _TAG_KIND_LABELS[value],
                    )
                    new_tag = st.text_input("Nueva etiqueta")
                    tag_submit = st.form_submit_button("Agregar etiqueta")
                if tag_submit:
                    def add_tag_callback(session):
                        add_object_tag(
                            session,
                            object_id=selected.object_id,
                            tag=new_tag,
                            tag_kind=tag_kind,
                            created_by=reviewer or "local_user",
                        )
                        return selected.object_id
                    _run_action(
                        st,
                        lambda: _database_action(db_path, add_tag_callback),
                        selection_key=object_state_key,
                        fallback_selection=selected.object_id,
                    )

                st.write("**Comentarios**")
                # Los comentarios se leen en una sesión separada para mantener la UI simple.
                comments_engine = create_sqlite_engine(db_path)
                try:
                    with session_scope(comments_engine) as comments_session:
                        comment_rows = object_comment_rows(
                            comments_session, object_id=selected.object_id
                        )
                finally:
                    comments_engine.dispose()
                if comment_rows:
                    for comment in reversed(comment_rows):
                        st.markdown(
                            f"**{comment.created_by}** · {comment.created_at.isoformat(timespec='minutes')}"
                        )
                        st.write(comment.body)
                else:
                    st.caption("Sin comentarios")
                with st.form(f"comment_{selected.object_id}", clear_on_submit=True):
                    comment_body = st.text_area("Nuevo comentario", height=100)
                    comment_submit = st.form_submit_button("Agregar comentario")
                if comment_submit:
                    def add_comment_callback(session):
                        add_object_comment(
                            session,
                            object_id=selected.object_id,
                            body=comment_body,
                            created_by=reviewer or "local_user",
                        )
                        return selected.object_id
                    _run_action(
                        st,
                        lambda: _database_action(db_path, add_comment_callback),
                        selection_key=object_state_key,
                        fallback_selection=selected.object_id,
                    )

            with entities_tab:
                entities_engine = create_sqlite_engine(db_path)
                try:
                    with session_scope(entities_engine) as entities_session:
                        object_mentions = mention_rows(
                            entities_session, object_id=selected.object_id
                        )
                        available_authorities = authority_rows(
                            entities_session,
                            project_id=decisions.project_id,
                            lifecycle_statuses=("active",),
                        )
                finally:
                    entities_engine.dispose()
                authority_map = {
                    row.authority_id: row for row in available_authorities
                }
                authority_options = [None, *authority_map]

                st.write("**Menciones vinculadas a este objeto**")
                if object_mentions:
                    for mention in object_mentions:
                        with st.container(border=True):
                            mention_header, mention_state = st.columns([4, 2])
                            mention_header.write(
                                f"**{mention.mention_text}** · "
                                f"{mention.authority_name or 'sin autoridad canónica'}"
                            )
                            mention_header.caption(
                                f"offsets {mention.start_offset}:{mention.end_offset} · "
                                f"origen {mention.source} · revisión textual "
                                f"{mention.object_revision_number}"
                            )
                            if mention.is_stale:
                                mention_header.warning(
                                    "El texto fue editado después de crear esta mención. "
                                    "Verificá los offsets antes de aceptarla."
                                )
                            with mention_state.form(
                                f"mention_update_{mention.mention_id}_{mention.revision}"
                            ):
                                status_choice = st.selectbox(
                                    "Estado",
                                    options=list(MENTION_STATUSES),
                                    index=list(MENTION_STATUSES).index(mention.status),
                                    format_func=lambda value: _MENTION_STATUS_LABELS[value],
                                )
                                authority_choice = st.selectbox(
                                    "Autoridad",
                                    options=authority_options,
                                    index=(
                                        authority_options.index(mention.authority_id)
                                        if mention.authority_id in authority_options
                                        else 0
                                    ),
                                    format_func=lambda value: (
                                        "Sin vincular"
                                        if value is None
                                        else (
                                            f"{authority_map[value].preferred_name} · "
                                            f"{_AUTHORITY_TYPE_LABELS[authority_map[value].entity_type]}"
                                        )
                                    ),
                                )
                                mention_note = st.text_input(
                                    "Nota", value=mention.note or ""
                                )
                                mention_submit = st.form_submit_button("Guardar")
                            if mention_submit:
                                if (
                                    authority_choice is None
                                    and status_choice in LINKED_MENTION_STATUSES
                                ):
                                    st.error(
                                        "Una mención aceptada o modificada debe estar "
                                        "vinculada a una autoridad."
                                    )
                                else:
                                    _run_action(
                                        st,
                                        lambda mention=mention, status_choice=status_choice,
                                        authority_choice=authority_choice,
                                        mention_note=mention_note: _database_action(
                                            db_path,
                                            lambda session: update_mention(
                                                session,
                                                mention_id=mention.mention_id,
                                                expected_revision=mention.revision,
                                                status=status_choice,
                                                authority_id=authority_choice,
                                                note=mention_note,
                                                changed_by=reviewer or "local_user",
                                            ),
                                        ),
                                        selection_key=object_state_key,
                                        fallback_selection=selected.object_id,
                                    )
                else:
                    st.caption("Sin menciones registradas")

                scan_col, note_col = st.columns([2, 3])
                with scan_col:
                    scan_dictionary = st.button(
                        "Buscar nombres y alias conocidos",
                        use_container_width=True,
                        key=f"entity_scan_{selected.object_id}_{selected.revision_number}",
                    )
                with note_col:
                    st.caption(
                        "Crea sugerencias pendientes usando solamente el diccionario "
                        "de autoridades del proyecto."
                    )
                if scan_dictionary:
                    result_holder: dict[str, object] = {}

                    def scan_callback(session):
                        summary = suggest_dictionary_mentions(
                            session,
                            object_id=selected.object_id,
                            created_by=reviewer or "local_user",
                        )
                        result_holder["summary"] = summary
                        return selected.object_id

                    _run_action(
                        st,
                        lambda: _database_action(db_path, scan_callback),
                        selection_key=object_state_key,
                        fallback_selection=selected.object_id,
                    )

                st.divider()
                st.write("**Agregar una mención manual**")
                if not available_authorities:
                    st.info(
                        "Primero creá un registro en la vista Entidades. "
                        "También podés registrar una mención sin vincular."
                    )
                with st.form(
                    f"mention_create_{selected.object_id}_{selected.revision_number}",
                    clear_on_submit=True,
                ):
                    manual_text = st.text_input(
                        "Texto exacto de la mención",
                        placeholder="Debe aparecer en el texto corregido actual",
                    )
                    manual_occurrence = st.number_input(
                        "Aparición",
                        min_value=1,
                        value=1,
                        step=1,
                        help="Usá 2, 3, etc. cuando el mismo texto aparece varias veces.",
                    )
                    manual_authority = st.selectbox(
                        "Autoridad canónica",
                        options=authority_options,
                        format_func=lambda value: (
                            "Sin vincular"
                            if value is None
                            else (
                                f"{authority_map[value].preferred_name} · "
                                f"{_AUTHORITY_TYPE_LABELS[authority_map[value].entity_type]}"
                            )
                        ),
                    )
                    manual_status = st.selectbox(
                        "Estado",
                        options=list(MENTION_STATUSES),
                        index=list(MENTION_STATUSES).index("accepted"),
                        format_func=lambda value: _MENTION_STATUS_LABELS[value],
                    )
                    manual_note = st.text_input("Nota")
                    manual_submit = st.form_submit_button("Agregar mención")
                if manual_submit:
                    if manual_authority is None and manual_status in LINKED_MENTION_STATUSES:
                        st.error(
                            "Una mención aceptada o modificada debe estar vinculada "
                            "a una autoridad. Usá Pendiente o Rechazada para dejarla sin vincular."
                        )
                    else:
                        _run_action(
                            st,
                            lambda: _database_action(
                                db_path,
                                lambda session: create_mention(
                                    session,
                                    object_id=selected.object_id,
                                    mention_text=manual_text,
                                    occurrence=int(manual_occurrence),
                                    authority_id=manual_authority,
                                    status=manual_status,
                                    source="manual",
                                    note=manual_note,
                                    created_by=reviewer or "local_user",
                                ),
                            ),
                            selection_key=object_state_key,
                            fallback_selection=selected.object_id,
                        )

            with history_tab:
                history_engine = create_sqlite_engine(db_path)
                try:
                    with session_scope(history_engine) as history_session:
                        history = object_revision_rows(history_session, object_id=selected.object_id)
                finally:
                    history_engine.dispose()
                for revision in reversed(history):
                    label = (
                        f"Revisión {revision.revision_number} · {revision.operation} · "
                        f"{revision.created_by} · {revision.created_at.isoformat(timespec='minutes')}"
                    )
                    with st.expander(label, expanded=revision.revision_number == selected.revision_number):
                        st.caption(
                            f"Tipo: {type_labels.get(revision.object_type, revision.object_type)} · "
                            f"orden {revision.order_index + 1} · estado {revision.lifecycle_status}"
                        )
                        if revision.note:
                            st.write(revision.note)
                        st.text(revision.text)
                previous_revisions = [
                    item.revision_number
                    for item in history
                    if item.revision_number < selected.revision_number
                ]
                if previous_revisions:
                    with st.form(f"revert_{selected.object_id}_{selected.revision_number}"):
                        target_revision = st.selectbox(
                            "Restaurar contenido desde",
                            options=previous_revisions,
                            format_func=lambda number: f"Revisión {number}",
                        )
                        revert_note = st.text_input("Nota de restauración")
                        revert_submit = st.form_submit_button("Crear revisión de restauración")
                    if revert_submit:
                        def revert_callback(session):
                            return execute_page_action(
                                session,
                                editable_page_id=view.editable_page_id,
                                action_type="revert",
                                changed_by=reviewer or "local_user",
                                selected_object_id=selected.object_id,
                                note=revert_note or None,
                                action=lambda: revert_editable_object(
                                    session,
                                    object_id=selected.object_id,
                                    target_revision=target_revision,
                                    expected_revision=selected.revision_number,
                                    reverted_by=reviewer or "local_user",
                                    note=revert_note or None,
                                ),
                            )
                        _run_action(
                            st,
                            lambda: _database_action(db_path, revert_callback),
                            selection_key=object_state_key,
                            fallback_selection=selected.object_id,
                        )

            with add_tab:
                with st.form(f"add_{source_key}_{page}_{selected.object_id}"):
                    added_type = st.selectbox(
                        "Tipo",
                        options=type_keys,
                        format_func=lambda key: type_labels.get(key, key),
                        key=f"add_type_{source_key}_{page}",
                    )
                    placement = st.selectbox(
                        "Ubicación",
                        options=["after", "before", "end"],
                        format_func=lambda value: {
                            "after": "Después del objeto seleccionado",
                            "before": "Antes del objeto seleccionado",
                            "end": "Al final de la página",
                        }[value],
                    )
                    added_text = st.text_area("Texto", height=180)
                    added_note = st.text_input("Nota")
                    add_submit = st.form_submit_button("Agregar objeto")
                if add_submit:
                    new_selection: dict[str, str | None] = {"id": None}
                    def add_callback(session):
                        def add_operation():
                            obj = add_editable_object(
                                session,
                                decisions=decisions,
                                source_key=source_key,
                                page=page,
                                object_type=added_type,
                                text=added_text,
                                created_by=reviewer or "local_user",
                                after_object_id=selected.object_id if placement == "after" else None,
                                before_object_id=selected.object_id if placement == "before" else None,
                                note=added_note or None,
                                document_part_id=selected.document_part_id,
                            )
                            new_selection["id"] = obj.id
                            return obj
                        return execute_page_action(
                            session,
                            editable_page_id=view.editable_page_id,
                            action_type="add",
                            changed_by=reviewer or "local_user",
                            selected_object_id=selected.object_id,
                            note=added_note or None,
                            action=add_operation,
                        )
                    def perform_add() -> str | None:
                        _database_action(db_path, add_callback)
                        return new_selection["id"]
                    _run_action(
                        st,
                        perform_add,
                        selection_key=object_state_key,
                        fallback_selection=selected.object_id,
                    )

        if not object_ids:
            with st.form(f"add_empty_{source_key}_{page}"):
                added_type = st.selectbox(
                    "Tipo", options=type_keys, format_func=lambda key: type_labels.get(key, key)
                )
                added_text = st.text_area("Texto", height=180)
                add_submit = st.form_submit_button("Agregar primer objeto")
            if add_submit:
                new_selection: dict[str, str | None] = {"id": None}
                def add_first_callback(session):
                    def add_operation():
                        obj = add_editable_object(
                            session,
                            decisions=decisions,
                            source_key=source_key,
                            page=page,
                            object_type=added_type,
                            text=added_text,
                            created_by=reviewer or "local_user",
                        )
                        new_selection["id"] = obj.id
                        return obj
                    return execute_page_action(
                        session,
                        editable_page_id=view.editable_page_id,
                        action_type="add",
                        changed_by=reviewer or "local_user",
                        selected_object_id=None,
                        action=add_operation,
                    )
                def perform_add_first() -> str | None:
                    _database_action(db_path, add_first_callback)
                    return new_selection["id"]
                _run_action(
                    st,
                    perform_add_first,
                    selection_key=object_state_key,
                )


if __name__ == "__main__":
    main()
