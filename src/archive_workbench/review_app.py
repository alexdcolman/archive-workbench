from __future__ import annotations

import argparse
import hashlib
import html
import json
import sys
from pathlib import Path

from typing import Callable

from archive_workbench.ui_navigation import (
    fragmented_view,
    rerun_app,
    rerun_view,
    request_app_view,
    tracked_tabs,
)

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
from archive_workbench.candidate_review import page_history_rows
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
from archive_workbench.lineage_diagnostics import diagnose_unmatched_bundle_lineage
from archive_workbench.lineage_recovery import (
    lineage_recovery_rows,
    recover_unmatched_bundle_lineage,
)
from archive_workbench.common_base import (
    accept_common_base_proposal,
    common_base_agreement_rows,
    create_common_base_proposal,
    finalize_common_base_agreement,
)
from archive_workbench.state_adoption import (
    apply_state_adoption,
    create_state_adoption_package,
    preview_state_adoption,
    state_adoption_rows,
)
from archive_workbench.exchange import (
    apply_change_bundle,
    bundle_application_rows,
    conflict_field_rows,
    dry_run_change_bundle,
    exchange_status,
    finalize_bundle_resolutions,
    incoming_bundle_diagnostics,
    incoming_bundle_rows,
    purge_incoming_bundle,
    resolution_status,
    resolve_conflict_fields_bulk,
    save_conflict_resolution,
    set_incoming_bundle_archived,
)

_STATUS_LABELS = {
    "unreviewed": "Sin revisar",
    "needs_review": "Requiere revisión",
    "reviewed": "Revisado",
    "approved": "Aprobado",
}
_LIFECYCLE_LABELS = {
    "active": "Activo",
    "deleted": "Eliminado",
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

_VIEW_LABELS = {
    "home": "Inicio",
    "catalog": "Catálogo documental",
    "processing": "Procesar documentos",
    "work": "Organizar trabajo",
    "review": "Revisar documentos",
    "search": "Buscar texto",
    "semantic": "Buscar por significado",
    "authorities": "Entidades y menciones",
    "graph": "Explorar relaciones",
    "export": "Preparar corpus",
    "exchange": "Intercambiar cambios",
    "admin": "Administrar y recuperar",
}

_VIEW_DESCRIPTIONS = {
    "home": "Resumen del proyecto y accesos al recorrido recomendado.",
    "catalog": "Registrá documentos, archivos y datos descriptivos del corpus.",
    "processing": "Generá y compará extracciones antes de adoptar una versión editable.",
    "work": "Planificá tareas, responsables y estados de avance.",
    "review": "Corregí texto, estructura, anotaciones y estados de calidad.",
    "search": "Localizá palabras o expresiones exactas en el texto revisado.",
    "semantic": "Buscá fragmentos cercanos por significado mediante un índice opcional.",
    "authorities": "Gestioná personas, organizaciones, lugares, menciones y relaciones.",
    "graph": "Explorá vínculos explícitos y capas derivadas del corpus.",
    "export": "Creá conjuntos reproducibles para análisis y trabajo externo.",
    "exchange": "Compartí cambios entre copias mediante paquetes verificables y simulación previa.",
    "admin": "Validá, respaldá, recuperá y mantené el proyecto.",
}

_WORKFLOW_STEPS = (
    "catalog",
    "processing",
    "work",
    "review",
    "search",
    "semantic",
    "authorities",
    "graph",
    "export",
    "exchange",
    "admin",
)

_VIEW_PHASES = {
    "catalog": "1. Preparar el corpus",
    "processing": "1. Preparar el corpus",
    "work": "2. Organizar y revisar",
    "review": "2. Organizar y revisar",
    "search": "3. Explorar y describir",
    "semantic": "3. Explorar y describir",
    "authorities": "3. Explorar y describir",
    "graph": "3. Explorar y describir",
    "export": "4. Preparar resultados",
    "exchange": "5. Compartir y preservar",
    "admin": "5. Compartir y preservar",
}

_VIEW_GUIDANCE = {
    "catalog": (
        "Registrar los documentos y describir su procedencia antes de procesarlos.",
        "Tener los archivos originales identificados y una decisión básica sobre fondo, serie o colección.",
        "Procesar los documentos y comparar las extracciones disponibles.",
    ),
    "processing": (
        "Generar, comparar y seleccionar una extracción candidata sin alterar el original.",
        "Haber registrado el documento en el catálogo y disponer del archivo local.",
        "Organizar tareas o abrir la página seleccionada en revisión.",
    ),
    "work": (
        "Distribuir tareas, responsables y estados de avance del equipo.",
        "Contar con documentos registrados o páginas listas para revisar.",
        "Revisar texto, estructura y calidad documental.",
    ),
    "review": (
        "Corregir la capa editable y dejar cada decisión humana registrada en el historial.",
        "Haber adoptado una extracción candidata para la página.",
        "Buscar, registrar menciones y explorar relaciones.",
    ),
    "search": (
        "Localizar palabras y expresiones exactas en el texto revisado.",
        "Tener páginas editables; los filtros de calidad determinan qué contenido se consulta.",
        "Abrir resultados en revisión o continuar con entidades y menciones.",
    ),
    "semantic": (
        "Encontrar fragmentos próximos por significado mediante un índice reconstruible.",
        "Tener instalado el componente semántico y un perfil de índice actualizado.",
        "Revisar los resultados en su contexto; la similitud no demuestra una relación analítica.",
    ),
    "authorities": (
        "Gestionar personas, organizaciones, lugares, acontecimientos, menciones y relaciones.",
        "Tener texto revisado o diccionarios externos que puedan verificarse.",
        "Explorar las relaciones o preparar un corpus para análisis.",
    ),
    "graph": (
        "Explorar vínculos explícitos y capas derivadas sin modificar los registros de origen.",
        "Tener entidades o relaciones registradas y revisar los filtros temporales o de estado.",
        "Volver a entidades para corregir datos o preparar una exportación.",
    ),
    "export": (
        "Crear conjuntos reproducibles para análisis externo, con filtros e historial verificable.",
        "Definir qué estados de calidad y qué unidad de análisis deben incluirse.",
        "Usar los archivos exportados en herramientas externas o compartir cambios entre copias.",
    ),
    "exchange": (
        "Compartir cambios entre copias mediante paquetes verificables y una simulación previa.",
        "Acordar una base común o revisar explícitamente los casos sin linaje verificable.",
        "Aplicar el paquete con copia de seguridad o pasar a la administración del proyecto.",
    ),
    "admin": (
        "Validar, crear copias de seguridad, probar la recuperación y preparar una restauración.",
        "Detener la aplicación antes de una restauración real y conservar una copia reciente.",
        "Volver al inicio para revisar el estado general del proyecto.",
    ),
}

_EXCHANGE_STATUS_LABELS = {
    "needs_review": "Requiere decisiones",
    "ready_to_apply": "Listo para aplicar",
    "ready_to_apply_resolved": "Listo para aplicar",
    "ready_to_finalize": "Decisiones completas",
    "resolving": "En resolución",
    "pending": "Pendiente",
    "stale": "Simulación desactualizada",
    "applied": "Aplicado",
    "assessed": "Evaluado",
}

_EXCHANGE_BASE_LABELS = {
    "matched": "Base común verificada",
    "unmatched": "Sin base común verificada",
}

_EXCHANGE_OPERATION_LABELS = {
    "create": "crear",
    "update": "actualizar",
    "delete": "retirar",
    "restore": "restaurar",
}


def _render_section_guidance(st, app_mode: str) -> None:
    """Muestra orientación contextual sin ocultar controles ni cambiar el flujo de dominio."""

    guidance = _VIEW_GUIDANCE.get(app_mode)
    if guidance is None:
        return
    objective, prerequisite, next_step = guidance
    step_number = _WORKFLOW_STEPS.index(app_mode) + 1
    with st.container(border=True):
        st.caption(
            f"Paso {step_number} de {len(_WORKFLOW_STEPS)} · "
            f"{_VIEW_PHASES[app_mode]}"
        )
        st.write(f"**Objetivo de esta sección:** {objective}")
        with st.expander("Antes de empezar y qué sigue"):
            st.write(f"**Conviene tener:** {prerequisite}")
            st.write(f"**Paso habitual siguiente:** {next_step}")


def _request_workflow_step(st, app_mode: str) -> None:
    request_app_view(st, mode=app_mode)
    rerun_app(st)


def _render_global_input_policy(st) -> None:
    """Oculta instrucciones de teclado que contradicen la política de acciones explícitas."""
    st.markdown(
        """
        <style>
        [data-testid="InputInstructions"] {
            display: none !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _render_wrapping_detail(st, label: str, value: object) -> None:
    """Presenta un dato breve sin el recorte con puntos suspensivos de ``st.metric``."""

    with st.container(border=True):
        st.caption(label)
        st.write(f"**{value}**")


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
        rerun_view(st)


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
    st.header("Buscar texto")
    st.caption(
        "Encontrá palabras o frases en todo el corpus. La búsqueda básica necesita solamente "
        "una consulta; los filtros opcionales permiten acotar documentos, estados y anotaciones."
    )
    field_labels = {
        "current_text": "Texto revisado",
        "original_text": "OCR original",
        "comments": "Comentarios",
        "tags": "Etiquetas",
        "entities": "Entidades, menciones y relaciones",
    }
    mode_labels = {
        "all": "Deben aparecer todas las palabras",
        "any": "Puede aparecer cualquiera de las palabras",
        "phrase": "Debe aparecer la frase exacta",
    }
    with st.form("search_corpus_form", enter_to_submit=False):
        query = st.text_input(
            "Qué querés encontrar",
            value=st.session_state.get("review_search_query", ""),
            placeholder="Ej.: contenido ideológico marxista",
        )
        match_mode = st.selectbox(
            "Cómo combinar las palabras",
            options=list(MATCH_MODES),
            format_func=lambda value: mode_labels[value],
        )
        partial_words = st.checkbox(
            "Buscar también dentro de las palabras",
            value=False,
            help=(
                "Permite que 'marx' encuentre 'marxista' o 'averig' encuentre "
                "'averiguaciones'. Cada fragmento debe tener al menos 3 caracteres."
            ),
        )
        with st.expander("Filtros opcionales", expanded=False):
            st.caption(
                "Si no elegís filtros, la búsqueda recorre todos los documentos, tipos y estados disponibles."
            )
            left, right = st.columns(2)
            with left:
                fields = st.multiselect(
                    "Dónde buscar",
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
                object_types = st.multiselect(
                    "Tipos de objeto",
                    options=list(type_labels),
                    format_func=lambda value: type_labels.get(value, value),
                )
                tag_kinds = st.multiselect(
                    "Categorías de etiqueta presentes",
                    options=list(TAG_KINDS),
                    format_func=lambda value: _TAG_KIND_LABELS[value],
                )
            with right:
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
                include_deleted = st.checkbox("Incluir objetos dados de baja", value=False)
                limit = st.number_input(
                    "Máximo de resultados", min_value=10, max_value=500, value=50, step=10
                )
            temporal_filter = st.checkbox(
                "Acotar por fechas de entidades o relaciones vinculadas",
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

    with st.expander("Mantenimiento del índice de texto", expanded=False):
        st.caption(
            "Reconstruí el índice solamente si la aplicación indica que está pendiente o si "
            "los cambios recientes todavía no aparecen en los resultados."
        )
        rebuild_clicked = st.button("Reconstruir índice de texto")
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

    params = st.session_state.get("review_search_params")
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

    st.subheader(f"Resultados · {len(results)}")
    with st.expander("Detalles técnicos del índice", expanded=False):
        indexed = status.indexed_at or "sin fecha"
        st.caption(
            f"Generación indexada: {status.indexed_generation} · última actualización: {indexed}"
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
                    request_app_view(
                        st,
                        mode="review",
                        source_key=row.source_key,
                        page=row.page_number,
                        object_id=row.object_id,
                    )
                    rerun_app(st)
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
    rerun_view(st)


def _purge_exchange_entry(
    st,
    *,
    project_root: Path,
    db_path: Path,
    bundle_ref: str,
) -> None:
    engine = create_sqlite_engine(db_path)
    try:
        with session_scope(engine) as session:
            plan = purge_incoming_bundle(session, bundle_ref=bundle_ref)
    except (ValueError, RuntimeError, OSError) as exc:
        st.error(str(exc))
        return
    finally:
        engine.dispose()

    root = project_root.resolve()
    removed = 0
    failed = 0
    for value in plan.relative_paths:
        candidate = Path(value)
        if not candidate.is_absolute():
            candidate = root / candidate
        candidate = candidate.resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            continue
        if candidate.is_file():
            try:
                candidate.unlink()
            except OSError:
                failed += 1
            else:
                removed += 1
    suffix = f"; {failed} archivo(s) no pudieron retirarse" if failed else ""
    st.session_state["exchange_flash"] = (
        f"Entrada {plan.bundle_id[:8]} eliminada; {removed} archivo(s) internos retirados"
        f"{suffix}"
    )
    st.session_state.pop("exchange_selected_bundle", None)
    rerun_view(st)


def _exchange_event_summary(event) -> str:
    fields = event.changed_fields
    label = (
        fields.get("preferred_name")
        or fields.get("name")
        or fields.get("title")
        or fields.get("current_text")
    )
    suffix = f" · {str(label)[:100]}" if label else ""
    operation = _EXCHANGE_OPERATION_LABELS.get(event.operation, event.operation)
    return (
        f"secuencia {event.sequence_number} · {operation} · "
        f"{event.actor} · {event.occurred_at}{suffix}"
    )


def _render_exchange_view(st, *, project_root: Path, db_path: Path, reviewer: str) -> None:
    st.header("Intercambio entre copias")
    st.caption(
        "Recibí, simulá y resolvé paquetes de intercambio sin modificar el corpus hasta "
        "su aplicación transaccional con una copia de seguridad."
    )
    flash = st.session_state.pop("exchange_flash", None)
    if flash:
        st.success(flash)

    show_archived = st.checkbox(
        "Mostrar paquetes archivados",
        value=False,
        key="exchange_show_archived",
    )
    engine = create_sqlite_engine(db_path)
    try:
        with session_scope(engine) as session:
            workspace = exchange_status(session)
            incoming = incoming_bundle_rows(session, include_archived=show_archived)
            applications = bundle_application_rows(session)
            recoveries = lineage_recovery_rows(session)
            common_base_agreements = common_base_agreement_rows(session)
            state_adoptions = state_adoption_rows(session)
    except (ValueError, RuntimeError, OSError) as exc:
        st.error(str(exc))
        return
    finally:
        engine.dispose()

    cols = st.columns(4)
    cols[0].metric("Copia", workspace.workspace_name)
    cols[1].metric("Secuencia local", workspace.current_sequence)
    cols[2].metric("Eventos pendientes", workspace.pending_event_count)
    cols[3].metric("Paquetes visibles", len(incoming))

    with st.expander("Reconciliar estados divergentes", expanded=False):
        st.caption(
            "EX-01D permite que una copia adopte explícitamente el estado editable completo "
            "de otra. La vista previa no escribe; la adopción crea primero un backup, aplica "
            "todo en una transacción y exige registrar después la base común bilateral."
        )
        adoption_step = st.radio(
            "Operación de estado",
            options=["Crear paquete de estado", "Previsualizar y adoptar"],
            horizontal=True,
            key="exchange_state_adoption_step",
        )
        if adoption_step == "Crear paquete de estado":
            with st.form("exchange_state_package_create", enter_to_submit=False):
                target_workspace_id = st.text_input(
                    "Identificador de la copia destinataria",
                    key="exchange_state_package_target_id",
                )
                target_workspace_name = st.text_input(
                    "Nombre de la copia destinataria",
                    key="exchange_state_package_target_name",
                )
                package_created_by = st.text_input(
                    "Responsable de crear el paquete",
                    value=reviewer or "local_user",
                    key="exchange_state_package_created_by",
                )
                package_reason = st.text_area(
                    "Fundamento del paquete de estado",
                    key="exchange_state_package_reason",
                )
                package_confirmed = st.checkbox(
                    "Confirmo que el paquete contiene el estado editable completo para la copia indicada",
                    key="exchange_state_package_confirmed",
                )
                package_submitted = st.form_submit_button(
                    "Crear paquete de estado",
                    type="primary",
                )
            if package_submitted:
                if not target_workspace_id.strip():
                    st.error("Indicá el identificador de la copia destinataria.")
                elif not target_workspace_name.strip():
                    st.error("Indicá el nombre de la copia destinataria.")
                elif not package_created_by.strip():
                    st.error("Indicá quién crea el paquete.")
                elif not package_reason.strip():
                    st.error("Escribí el fundamento del paquete.")
                elif not package_confirmed:
                    st.error("Marcá la confirmación antes de crear el paquete.")
                else:
                    _run_exchange_action(
                        st,
                        db_path=db_path,
                        callback=lambda session: (
                            lambda summary: (
                                f"Paquete de estado {summary.adoption_id} creado en "
                                f"{summary.output_path}. No se modificó el corpus."
                            )
                        )(
                            create_state_adoption_package(
                                session,
                                project_root=project_root,
                                target_workspace_id=target_workspace_id,
                                target_workspace_name=target_workspace_name,
                                created_by=package_created_by,
                                creation_reason=package_reason,
                                package_confirmed=package_confirmed,
                            )
                        ),
                    )
        else:
            state_package_path = st.text_input(
                "Ruta del ZIP completo de estado",
                key="exchange_state_adoption_package_path",
            )
            if st.button(
                "Previsualizar impacto sin escribir",
                key="exchange_state_adoption_preview_button",
            ):
                if not state_package_path.strip():
                    st.error("Indicá la ruta del paquete de estado.")
                else:
                    preview_engine = create_sqlite_engine(db_path)
                    try:
                        with session_scope(preview_engine) as session:
                            preview = preview_state_adoption(
                                session,
                                package_path=Path(state_package_path),
                            )
                        st.session_state["exchange_state_adoption_preview"] = preview
                    except (ValueError, RuntimeError, OSError) as exc:
                        st.error(str(exc))
                    finally:
                        preview_engine.dispose()

            preview = st.session_state.get("exchange_state_adoption_preview")
            if preview is not None and str(preview.package_path) == str(
                Path(state_package_path).expanduser().resolve()
            ):
                st.write(
                    f"**Estado local:** `{preview.local_state_sha256}`  \n"
                    f"**Estado recibido:** `{preview.incoming_state_sha256}`"
                )
                st.write(
                    f"Impacto: agregar **{preview.total_added}**, quitar "
                    f"**{preview.total_removed}**, cambiar **{preview.total_changed}**."
                )
                changed_sections = [
                    row
                    for row in preview.sections
                    if row.added or row.removed or row.changed
                ]
                if changed_sections:
                    st.dataframe(
                        [
                            {
                                "Sección": row.section,
                                "Local": row.local_count,
                                "Recibido": row.incoming_count,
                                "Agregar": row.added,
                                "Quitar": row.removed,
                                "Cambiar": row.changed,
                            }
                            for row in changed_sections
                        ],
                        hide_index=True,
                        use_container_width=True,
                    )
                with st.form("exchange_state_adoption_apply", enter_to_submit=False):
                    adoption_applied_by = st.text_input(
                        "Responsable de la adopción",
                        value=reviewer or "local_user",
                        key="exchange_state_adoption_applied_by",
                    )
                    adoption_reason = st.text_area(
                        "Fundamento de la adopción",
                        key="exchange_state_adoption_reason",
                    )
                    adoption_confirmed = st.checkbox(
                        "Confirmo que deseo crear un backup y reemplazar transaccionalmente el estado editable local",
                        key="exchange_state_adoption_confirmed",
                    )
                    adoption_submitted = st.form_submit_button(
                        "Adoptar estado recibido",
                        type="primary",
                    )
                if adoption_submitted:
                    if not adoption_applied_by.strip():
                        st.error("Indicá quién adopta el estado.")
                    elif not adoption_reason.strip():
                        st.error("Escribí el fundamento de la adopción.")
                    elif not adoption_confirmed:
                        st.error("Marcá la confirmación antes de adoptar el estado.")
                    else:
                        _run_exchange_action(
                            st,
                            db_path=db_path,
                            callback=lambda session: (
                                lambda summary: (
                                    f"Estado {summary.adoption_id} adoptado. Backup previo: "
                                    f"{summary.backup_path}. Ahora deben comprobarse los hashes "
                                    "y registrarse la base común bilateral."
                                )
                            )(
                                apply_state_adoption(
                                    session,
                                    project_root=project_root,
                                    package_path=Path(state_package_path),
                                    applied_by=adoption_applied_by,
                                    application_reason=adoption_reason,
                                    adoption_confirmed=adoption_confirmed,
                                    source="ui",
                                )
                            ),
                        )

        if state_adoptions:
            st.markdown("**Adopciones registradas en esta copia**")
            for adoption in state_adoptions:
                status = "revertida" if adoption.rolled_back else "activa"
                st.write(
                    f"`{adoption.adoption_id}` · {status} · origen "
                    f"{adoption.source_workspace_name}"
                )
                st.caption(
                    f"{adoption.previous_state_sha256} → {adoption.adopted_state_sha256} · "
                    f"responsable {adoption.applied_by}"
                )
            st.info(
                "El rollback reemplaza el archivo SQLite y debe ejecutarse con Streamlit "
                "cerrado mediante exchange-state-adoption-rollback."
            )

    with st.expander("Establecer una base común entre copias", expanded=False):
        st.caption(
            "EX-01C solo admite copias del mismo proyecto cuyo estado editable ya sea "
            "idéntico. La propuesta viaja primero a la contraparte; después el mismo "
            "acuerdo completado vuelve a la copia iniciadora."
        )
        common_base_step = st.radio(
            "Paso bilateral",
            options=["Crear propuesta", "Aceptar propuesta", "Finalizar acuerdo"],
            horizontal=True,
            key="exchange_common_base_step",
        )
        if common_base_step == "Crear propuesta":
            with st.form("exchange_common_base_proposal", enter_to_submit=False):
                counterpart_id = st.text_input(
                    "Identificador de la copia contraparte",
                    key="exchange_common_base_counterpart_id",
                )
                counterpart_name = st.text_input(
                    "Nombre de la copia contraparte",
                    key="exchange_common_base_counterpart_name",
                )
                proposed_by = st.text_input(
                    "Responsable de la propuesta",
                    value=reviewer or "local_user",
                    key="exchange_common_base_proposed_by",
                )
                proposal_reason = st.text_area(
                    "Fundamento de la propuesta",
                    key="exchange_common_base_proposal_reason",
                )
                proposal_confirmed = st.checkbox(
                    "Confirmo la creación del manifiesto de propuesta",
                    key="exchange_common_base_proposal_confirmed",
                )
                proposal_submitted = st.form_submit_button(
                    "Crear propuesta de base común",
                    type="primary",
                )
            if proposal_submitted:
                if not counterpart_id.strip():
                    st.error("Indicá el identificador de la copia contraparte.")
                elif not counterpart_name.strip():
                    st.error("Indicá el nombre de la copia contraparte.")
                elif not proposed_by.strip():
                    st.error("Indicá quién crea la propuesta.")
                elif not proposal_reason.strip():
                    st.error("Escribí el fundamento de la propuesta.")
                elif not proposal_confirmed:
                    st.error("Marcá la confirmación antes de crear la propuesta.")
                else:
                    _run_exchange_action(
                        st,
                        db_path=db_path,
                        callback=lambda session: (
                            lambda summary: (
                                f"Propuesta {summary.agreement_id} creada en "
                                f"{summary.output_path}. Todavía no se activó ningún acuerdo."
                            )
                        )(
                            create_common_base_proposal(
                                session,
                                project_root=project_root,
                                counterpart_workspace_id=counterpart_id,
                                counterpart_workspace_name=counterpart_name,
                                proposed_by=proposed_by,
                                proposal_reason=proposal_reason,
                                proposal_confirmed=proposal_confirmed,
                                source="ui",
                            )
                        ),
                    )
        elif common_base_step == "Aceptar propuesta":
            with st.form("exchange_common_base_accept", enter_to_submit=False):
                proposal_path_text = st.text_input(
                    "Ruta del ZIP de propuesta recibido",
                    key="exchange_common_base_accept_proposal_path",
                )
                accepted_by = st.text_input(
                    "Responsable de la aceptación",
                    value=reviewer or "local_user",
                    key="exchange_common_base_accepted_by",
                )
                accept_reason = st.text_area(
                    "Fundamento de la aceptación",
                    key="exchange_common_base_accept_reason",
                )
                accept_confirmed = st.checkbox(
                    "Confirmo que esta copia es la contraparte indicada y que su estado editable es idéntico",
                    key="exchange_common_base_accept_confirmed",
                )
                accept_submitted = st.form_submit_button(
                    "Aceptar y completar acuerdo",
                    type="primary",
                )
            if accept_submitted:
                if not proposal_path_text.strip():
                    st.error("Indicá la ruta del ZIP de propuesta.")
                elif not accepted_by.strip():
                    st.error("Indicá quién acepta la propuesta.")
                elif not accept_reason.strip():
                    st.error("Escribí el fundamento de la aceptación.")
                elif not accept_confirmed:
                    st.error("Marcá la confirmación antes de aceptar el acuerdo.")
                else:
                    _run_exchange_action(
                        st,
                        db_path=db_path,
                        callback=lambda session: (
                            lambda summary: (
                                f"Acuerdo {summary.agreement_id} registrado en esta copia. "
                                f"Manifiesto completado: {summary.output_path}. La copia "
                                "iniciadora todavía debe finalizarlo."
                            )
                        )(
                            accept_common_base_proposal(
                                session,
                                project_root=project_root,
                                proposal_path=Path(proposal_path_text),
                                accepted_by=accepted_by,
                                confirmation_reason=accept_reason,
                                agreement_confirmed=accept_confirmed,
                                source="ui",
                            )
                        ),
                    )
        else:
            with st.form("exchange_common_base_finalize", enter_to_submit=False):
                original_proposal_path = st.text_input(
                    "Ruta del ZIP de propuesta original",
                    key="exchange_common_base_finalize_proposal_path",
                )
                completed_agreement_path = st.text_input(
                    "Ruta del ZIP de acuerdo completado",
                    key="exchange_common_base_finalize_agreement_path",
                )
                finalized_by = st.text_input(
                    "Responsable de la finalización",
                    value=reviewer or "local_user",
                    key="exchange_common_base_finalized_by",
                )
                finalize_reason = st.text_area(
                    "Fundamento de la finalización",
                    key="exchange_common_base_finalize_reason",
                )
                finalize_confirmed = st.checkbox(
                    "Confirmo el manifiesto bilateral y su estado editable idéntico",
                    key="exchange_common_base_finalize_confirmed",
                )
                finalize_submitted = st.form_submit_button(
                    "Finalizar acuerdo en esta copia",
                    type="primary",
                )
            if finalize_submitted:
                if not original_proposal_path.strip():
                    st.error("Indicá la ruta de la propuesta original.")
                elif not completed_agreement_path.strip():
                    st.error("Indicá la ruta del acuerdo completado.")
                elif not finalized_by.strip():
                    st.error("Indicá quién finaliza el acuerdo.")
                elif not finalize_reason.strip():
                    st.error("Escribí el fundamento de la finalización.")
                elif not finalize_confirmed:
                    st.error("Marcá la confirmación antes de finalizar el acuerdo.")
                else:
                    _run_exchange_action(
                        st,
                        db_path=db_path,
                        callback=lambda session: (
                            lambda summary: (
                                f"Acuerdo {summary.agreement_id} finalizado. Nueva base común: "
                                f"{summary.checkpoint_label}."
                            )
                        )(
                            finalize_common_base_agreement(
                                session,
                                project_root=project_root,
                                proposal_path=Path(original_proposal_path),
                                agreement_path=Path(completed_agreement_path),
                                finalized_by=finalized_by,
                                confirmation_reason=finalize_reason,
                                agreement_confirmed=finalize_confirmed,
                                source="ui",
                            )
                        ),
                    )

        if common_base_agreements:
            st.markdown("**Acuerdos registrados en esta copia**")
            for agreement in common_base_agreements:
                st.write(
                    f"`{agreement.agreement_id}` · rol {agreement.local_role} · "
                    f"punto `{agreement.checkpoint_label}`"
                )
                st.caption(
                    f"Contraparte {agreement.counterpart_workspace_id} · "
                    f"estado {agreement.state_sha256} · "
                    f"responsable {agreement.registered_by}"
                )

    with st.expander("Recibir y evaluar un paquete ZIP", expanded=not incoming):
        uploaded = st.file_uploader(
            "Paquete de intercambio",
            type=["zip"],
            key="exchange_bundle_upload",
        )
        if uploaded is not None:
            st.caption(f"{uploaded.name} · {uploaded.size} bytes")
        if st.button(
            "Simular evaluación",
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
                    f"Simulación {summary.bundle_id[:8]}: "
                    f"{_EXCHANGE_STATUS_LABELS.get(summary.overall_status, summary.overall_status)} · "
                    f"A {summary.counts.get('apply', 0)} · "
                    f"D {summary.counts.get('duplicate', 0)} · "
                    f"R {summary.counts.get('review', 0)} · "
                    f"C {summary.counts.get('conflict', 0)}"
                )

            _run_exchange_action(st, db_path=db_path, callback=callback)

    if not incoming:
        st.info("Todavía no hay paquetes recibidos con el filtro actual.")
        return

    incoming_map = {row.bundle_id: row for row in incoming}
    recovery_map = {row.bundle_id: row for row in recoveries}
    current_selection = st.session_state.get("exchange_selected_bundle")
    if current_selection not in incoming_map:
        st.session_state.pop("exchange_selected_bundle", None)
    selected_bundle = st.selectbox(
        "Paquete recibido",
        options=list(incoming_map),
        format_func=lambda key: (
            ("[Archivado] " if incoming_map[key].lifecycle_status == "archived" else "")
            + f"{incoming_map[key].source_workspace_name} · {key[:8]} · "
            + _EXCHANGE_STATUS_LABELS.get(
                incoming_map[key].status,
                incoming_map[key].status,
            )
        ),
        key="exchange_selected_bundle",
    )
    selected = incoming_map[selected_bundle]
    selected_recovery = recovery_map.get(selected_bundle)
    counts = selected.counts
    status_label = _EXCHANGE_STATUS_LABELS.get(selected.status, selected.status)
    base_label = _EXCHANGE_BASE_LABELS.get(
        selected.base_match_status,
        selected.base_match_status,
    )
    st.write(
        f"**Estado:** {status_label} · **Base:** {base_label} · "
        f"**Eventos:** {selected.event_count} · "
        f"aplicables {counts.get('apply', 0)} · "
        f"duplicados {counts.get('duplicate', 0)} · "
        f"a revisar {counts.get('review', 0)} · "
        f"conflictos {counts.get('conflict', 0)}"
    )
    with st.expander("Detalles técnicos", expanded=False):
        st.code(
            f"paquete={selected.bundle_id}\n"
            f"estado={selected.status}\n"
            f"base={selected.base_match_status}\n"
            f"metodo_base={selected.base_match_method}",
            language="text",
        )
    if selected.lifecycle_status == "archived":
        st.caption(
            f"Archivado por {selected.archived_by or '-'} · "
            f"{selected.archived_at or '-'}"
            + (f" · {selected.archive_note}" if selected.archive_note else "")
        )

    engine = create_sqlite_engine(db_path)
    try:
        with session_scope(engine) as session:
            status = resolution_status(session, selected_bundle)
            conflict_rows = conflict_field_rows(session, selected_bundle)
            diagnostics = (
                incoming_bundle_diagnostics(session, bundle_ref=selected_bundle)
                if selected.status == "stale"
                else None
            )
    except ValueError:
        status = None
        conflict_rows = []
        diagnostics = None
    finally:
        engine.dispose()

    if status is not None and status.event_count:
        st.caption(
            f"Campos que requieren decisión: {status.resolved_field_count}/{status.field_count} · "
            f"coincidencias automáticas: {status.auto_matched_field_count} · "
            f"pendientes: {status.unresolved_field_count}"
        )

    if selected_recovery is not None:
        st.success(
            "El linaje de este paquete ya fue recuperado de manera append-only. "
            "La simulación anterior quedó obsoleta y debe repetirse."
        )
        with st.expander("Decisión de recuperación", expanded=False):
            st.write(
                f"Método: `{selected_recovery.recovery_method}` · punto local "
                f"`{selected_recovery.local_checkpoint_label or '-'}` · "
                f"secuencia remota {selected_recovery.remote_sequence}"
            )
            st.write(
                f"Responsable: {selected_recovery.confirmed_by} · "
                f"origen: {selected_recovery.source}"
            )
            st.write(f"Fundamento: {selected_recovery.confirmation_reason}")
            st.code(
                f"caso={selected_recovery.case_id}\n"
                f"decision={selected_recovery.decision_id}\n"
                f"parametros_sha256={selected_recovery.parameters_sha256}",
                language="text",
            )

    if selected.base_match_status == "unmatched":
        st.warning(
            "No se encontró un punto de control que demuestre una base común con este paquete. "
            "Por seguridad, todos sus eventos se tratan como revisables: conservar valores "
            "locales no crea parentesco y aceptar datos recibidos no reconstruye por sí solo "
            "el linaje faltante."
        )
        st.info(
            "La recuperación o creación de una base común verificada requiere un procedimiento "
            "independiente. El diagnóstico siguiente es estrictamente de solo lectura: no crea "
            "linaje, no modifica decisiones y no toca el corpus."
        )
        with st.expander("Diagnosticar evidencia de linaje", expanded=False):
            st.caption(
                "La SQLite vigente y el paquete recibido se examinan siempre. Agregá, una ruta "
                "por línea, únicamente los paquetes, manifest.json o backups que quieras "
                "verificar como evidencia adicional."
            )
            evidence_text = st.text_area(
                "Rutas de evidencia adicional",
                key=f"exchange_lineage_evidence_{selected_bundle}",
                placeholder=(
                    "/ruta/al/paquete_anterior.zip\n"
                    "/ruta/al/project_backup.zip\n"
                    "/ruta/al/manifest.json"
                ),
            )
            if st.button(
                "Ejecutar diagnóstico de solo lectura",
                key=f"exchange_lineage_diagnose_{selected_bundle}",
            ):
                evidence_paths = [
                    Path(line.strip()).expanduser()
                    for line in evidence_text.splitlines()
                    if line.strip()
                ]
                diagnostic_engine = create_sqlite_engine(db_path)
                try:
                    with session_scope(diagnostic_engine) as session:
                        lineage_report = diagnose_unmatched_bundle_lineage(
                            session,
                            project_root=project_root,
                            bundle_ref=selected_bundle,
                            evidence_paths=evidence_paths,
                        )
                    st.session_state[
                        f"exchange_lineage_report_{selected_bundle}"
                    ] = lineage_report
                except (ValueError, OSError) as exc:
                    st.error(str(exc))
                finally:
                    diagnostic_engine.dispose()

            lineage_report = st.session_state.get(
                f"exchange_lineage_report_{selected_bundle}"
            )
            if lineage_report is not None:
                labels = {
                    "recoverable": "Recuperable",
                    "ambiguous": "Ambiguo",
                    "insufficient": "Insuficiente",
                }
                label = labels.get(
                    lineage_report.classification, lineage_report.classification
                )
                if lineage_report.classification == "recoverable":
                    st.success(f"Resultado: {label}. {lineage_report.summary}")
                elif lineage_report.classification == "ambiguous":
                    st.warning(f"Resultado: {label}. {lineage_report.summary}")
                else:
                    st.info(f"Resultado: {label}. {lineage_report.summary}")
                st.caption(
                    f"Evidencias: {len(lineage_report.findings)} · "
                    f"cadenas concluyentes: {len(lineage_report.recovery_candidates)} · "
                    f"contradicciones: {lineage_report.contradiction_count}"
                )
                for index, finding in enumerate(lineage_report.findings, start=1):
                    with st.expander(
                        f"{index}. {finding.strength} · {finding.code}",
                        expanded=finding.strength in {"conclusive", "rejected"},
                    ):
                        st.write(finding.explanation)
                        st.code(
                            f"artefacto={finding.artifact_reference}\n"
                            f"sha256={finding.artifact_sha256 or '-'}\n"
                            f"proyecto={finding.project_id or '-'}\n"
                            f"copia={finding.workspace_id or '-'}\n"
                            "secuencia="
                            f"{finding.sequence_number if finding.sequence_number is not None else '-'}\n"
                            f"checkpoint={finding.checkpoint_id or '-'}\n"
                            f"estado={finding.state_sha256 or '-'}",
                            language="text",
                        )
                if lineage_report.recovery_candidates:
                    st.markdown("**Cadenas concluyentes identificadas**")
                    for candidate in lineage_report.recovery_candidates:
                        st.write(
                            f"{candidate.method} · punto "
                            f"`{candidate.local_checkpoint_label or '-'}` · "
                            f"secuencia remota {candidate.remote_sequence}"
                        )
                        if candidate.chain_bundle_ids:
                            st.caption(
                                "Paquetes: " + " → ".join(candidate.chain_bundle_ids)
                            )
                if lineage_report.classification == "recoverable":
                    if selected_recovery is None:
                        candidate = lineage_report.recovery_candidates[0]
                        st.warning(
                            "La recuperación no aplica eventos ni modifica el corpus, pero "
                            "registra una decisión permanente e invalida esta simulación."
                        )
                        with st.form(
                            f"exchange_lineage_recover_{selected_bundle}",
                            enter_to_submit=False,
                        ):
                            recovered_by = st.text_input(
                                "Responsable de la recuperación",
                                value=reviewer or "local_user",
                                key=f"exchange_lineage_recovered_by_{selected_bundle}",
                            )
                            recovery_reason = st.text_area(
                                "Fundamento",
                                key=f"exchange_lineage_reason_{selected_bundle}",
                            )
                            recovery_confirmed = st.checkbox(
                                "Confirmo esta cadena concluyente y acepto invalidar la simulación anterior",
                                key=f"exchange_lineage_confirm_{selected_bundle}",
                            )
                            recovery_submitted = st.form_submit_button(
                                "Recuperar linaje",
                                type="primary",
                            )
                        if recovery_submitted:
                            evidence_paths = [
                                Path(line.strip()).expanduser()
                                for line in evidence_text.splitlines()
                                if line.strip()
                            ]
                            if not recovered_by.strip():
                                st.error("Indicá quién confirma la recuperación.")
                            elif not recovery_reason.strip():
                                st.error("Escribí el fundamento de la recuperación.")
                            elif not recovery_confirmed:
                                st.error(
                                    "Marcá la confirmación antes de recuperar el linaje."
                                )
                            else:
                                _run_exchange_action(
                                    st,
                                    db_path=db_path,
                                    callback=lambda session: (
                                        lambda summary: (
                                            "Linaje recuperado mediante "
                                            f"{summary.recovery_method}. La simulación "
                                            "anterior quedó obsoleta; volvé a simular "
                                            "antes de resolver o aplicar."
                                        )
                                    )(
                                        recover_unmatched_bundle_lineage(
                                            session,
                                            project_root=project_root,
                                            bundle_ref=selected_bundle,
                                            evidence_paths=evidence_paths,
                                            recovered_by=recovered_by,
                                            confirmation_reason=recovery_reason,
                                            recovery_confirmed=recovery_confirmed,
                                            source="ui",
                                        )
                                    ),
                                )
                    else:
                        st.caption(
                            "La recuperación ya fue registrada. Volvé a simular el paquete "
                            "para que use la base recuperada."
                        )
                else:
                    st.caption(
                        "Este resultado no habilita escrituras. Solo una cadena concluyente "
                        "y única permite recuperar linaje."
                    )

    if selected.status == "stale":
        st.warning(
            "La simulación quedó desactualizada porque la copia local cambió después de la "
            "evaluación. Volvé a simular antes de aplicar el paquete."
        )
        if diagnostics is not None:
            st.caption(
                "Secuencia evaluada: "
                f"{diagnostics.assessed_sequence_number if diagnostics.assessed_sequence_number is not None else '-'} · "
                f"secuencia actual: {diagnostics.current_sequence_number} · "
                f"hash de estado cambiado: {'sí' if diagnostics.state_changed else 'no'}"
            )
            if diagnostics.local_events_after_assessment:
                with st.expander(
                    "Cambios locales posteriores a la simulación",
                    expanded=True,
                ):
                    for event in diagnostics.local_events_after_assessment:
                        st.write(_exchange_event_summary(event))
            elif diagnostics.state_changed:
                st.caption(
                    "El hash editable cambió, pero no hay un evento de intercambio posterior "
                    "que permita atribuirlo a una sola operación."
                )

    if selected.lifecycle_status == "archived":
        st.info(
            "La entrada archivada queda fuera de la vista operativa normal. Restaurala para "
            "volver a evaluar o resolver el paquete."
        )
        with st.form(
            f"exchange_restore_{selected_bundle}",
            enter_to_submit=False,
        ):
            confirm_restore = st.checkbox(
                "Confirmo que deseo restaurar esta entrada",
                key=f"exchange_confirm_restore_{selected_bundle}",
            )
            restore_submitted = st.form_submit_button("Restaurar entrada")
        if restore_submitted:
            if not confirm_restore:
                st.error("Marcá la confirmación antes de restaurar la entrada.")
            else:
                _run_exchange_action(
                    st,
                    db_path=db_path,
                    callback=lambda session: (
                        set_incoming_bundle_archived(
                            session,
                            bundle_ref=selected_bundle,
                            archived=False,
                            changed_by=reviewer or "local_user",
                        ),
                        "Entrada restaurada",
                    )[1],
                )
        if selected.status != "applied":
            st.caption(
                "Eliminar la entrada retira la simulación, sus decisiones, el ZIP recibido "
                "y los reportes internos. No modifica el corpus ni los eventos locales."
            )
            with st.form(
                f"exchange_purge_{selected_bundle}",
                enter_to_submit=False,
            ):
                confirm_purge = st.checkbox(
                    "Confirmo que deseo eliminar definitivamente esta entrada archivada",
                    key=f"exchange_confirm_purge_{selected_bundle}",
                )
                purge_submitted = st.form_submit_button("Eliminar entrada")
            if purge_submitted:
                if not confirm_purge:
                    st.error("Marcá la confirmación antes de eliminar la entrada.")
                else:
                    _purge_exchange_entry(
                        st,
                        project_root=project_root,
                        db_path=db_path,
                        bundle_ref=selected_bundle,
                    )
        if applications:
            with st.expander("Aplicaciones anteriores"):
                for row in applications:
                    st.write(
                        f"`{row.bundle_id}` · aplicados {row.applied_event_count} · "
                        f"duplicados {row.duplicate_event_count} · "
                        f"conservados localmente {row.kept_local_event_count} · "
                        f"punto de control `{row.checkpoint_label}`"
                    )
        return

    if conflict_rows:
        st.subheader("Resolución de conflictos")
        contains_creations = any(row.operation == "create" for row in conflict_rows)
        bulk_options = ["local"] if contains_creations else ["local", "incoming"]
        if contains_creations:
            st.caption(
                "La decisión conjunta «Aceptar todos los valores recibidos» no está disponible "
                "porque el paquete contiene creaciones sin una base común verificable. Cada "
                "creación debe revisarse por evento o por campo."
            )
        with st.form(
            f"exchange_bulk_commit_{selected_bundle}",
            enter_to_submit=False,
        ):
            confirm_bulk = st.checkbox(
                "Confirmo que deseo aplicar una misma decisión a todos los campos pendientes",
                key=f"exchange_confirm_bulk_{selected_bundle}",
            )
            bulk_choice = st.radio(
                "Decisión conjunta",
                options=bulk_options,
                format_func=lambda value: {
                    "local": "Conservar todos los valores locales",
                    "incoming": "Aceptar todos los valores recibidos",
                }[value],
                horizontal=True,
                key=f"exchange_bulk_choice_{selected_bundle}",
            )
            bulk_submitted = st.form_submit_button(
                "Aplicar decisión conjunta",
                use_container_width=True,
            )
        if bulk_submitted:
            if not confirm_bulk:
                st.error("Marcá la confirmación antes de aplicar la decisión conjunta.")
            else:
                _run_exchange_action(
                    st,
                    db_path=db_path,
                    callback=lambda session: (
                        lambda result: (
                            f"Resueltos {result.resolved_field_count} campos como {bulk_choice}; "
                            f"{result.auto_matched_field_count} coincidían automáticamente"
                        )
                    )(
                        resolve_conflict_fields_bulk(
                            session,
                            bundle_ref=selected_bundle,
                            choice=bulk_choice,
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
                f"Evento {event_id[:8]} · "
                f"{_EXCHANGE_OPERATION_LABELS.get(first.operation, first.operation)} · "
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
                        disabled=first.operation == "create",
                        help=(
                            "Las creaciones sin base común deben revisarse campo por campo"
                            if first.operation == "create"
                            else None
                        ),
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
                    default_choice = (
                        row.choice
                        if row.choice in {"local", "incoming", "custom"}
                        else "local"
                    )
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
                                        json.loads(custom_text)
                                        if choice == "custom" and as_json
                                        else custom_text
                                        if choice == "custom"
                                        else None
                                    ),
                                    resolved_by=reviewer or "local_user",
                                )
                            ),
                        )

    if status is not None:
        controls = st.columns(2)
        with controls[0]:
            can_finalize = status.overall_status in {
                "ready_to_finalize",
                "ready_to_apply_resolved",
            }
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
                            "El paquete ya estaba finalizado"
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
            with st.form(
                f"exchange_apply_commit_{selected_bundle}",
                enter_to_submit=False,
            ):
                confirm_apply = st.checkbox(
                    "Confirmo la aplicación con copia de seguridad",
                    key=f"exchange_confirm_apply_{selected_bundle}",
                )
                apply_submitted = st.form_submit_button(
                    "Aplicar paquete",
                    type="primary",
                    disabled=(
                        selected.status
                        not in {"ready_to_apply", "ready_to_apply_resolved"}
                    ),
                    use_container_width=True,
                )
            if apply_submitted:
                if not confirm_apply:
                    st.error("Marcá la confirmación antes de aplicar el paquete.")
                else:
                    _run_exchange_action(
                        st,
                        db_path=db_path,
                        callback=lambda session: (
                            lambda result: (
                                f"Paquete aplicado: {result.applied_event_count} cambios, "
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

    st.divider()
    with st.form(
        f"exchange_archive_{selected_bundle}",
        enter_to_submit=False,
    ):
        archive_note = st.text_input(
            "Nota de archivo opcional",
            key=f"exchange_archive_note_{selected_bundle}",
        )
        confirm_archive = st.checkbox(
            "Confirmo que deseo archivar esta entrada",
            key=f"exchange_confirm_archive_{selected_bundle}",
        )
        archive_submitted = st.form_submit_button("Archivar paquete")
    if archive_submitted:
        if not confirm_archive:
            st.error("Marcá la confirmación antes de archivar el paquete.")
        else:
            _run_exchange_action(
                st,
                db_path=db_path,
                callback=lambda session: (
                    set_incoming_bundle_archived(
                        session,
                        bundle_ref=selected_bundle,
                        archived=True,
                        changed_by=reviewer or "local_user",
                        note=archive_note,
                    ),
                    "Entrada archivada",
                )[1],
            )

    if applications:
        with st.expander("Aplicaciones anteriores"):
            for row in applications:
                st.write(
                    f"`{row.bundle_id}` · aplicados {row.applied_event_count} · "
                    f"duplicados {row.duplicate_event_count} · "
                    f"conservados localmente {row.kept_local_event_count} · "
                    f"punto de control `{row.checkpoint_label}`"
                )

def main() -> None:
    import streamlit as st

    st.set_page_config(page_title="Archive Workbench", layout="wide")
    _render_global_input_policy(st)
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
            "Sección",
            options=list(_VIEW_LABELS),
            format_func=lambda value: _VIEW_LABELS[value],
            key="review_app_mode",
        )
        st.caption(_VIEW_DESCRIPTIONS[app_mode])
        show_section_guidance = False
        if app_mode in _WORKFLOW_STEPS:
            step_index = _WORKFLOW_STEPS.index(app_mode)
            st.caption(
                f"{_VIEW_PHASES[app_mode]} · "
                f"paso {step_index + 1} de {len(_WORKFLOW_STEPS)}"
            )
            show_section_guidance = st.checkbox(
                "Mostrar orientación de la sección",
                value=True,
                key="review_show_section_guidance",
            )
            previous_step = _WORKFLOW_STEPS[step_index - 1] if step_index > 0 else None
            next_step = (
                _WORKFLOW_STEPS[step_index + 1]
                if step_index < len(_WORKFLOW_STEPS) - 1
                else None
            )
            previous_col, next_col = st.columns(2)
            with previous_col:
                if st.button(
                    "← Sección anterior",
                    key="workflow_previous_section",
                    disabled=previous_step is None,
                    use_container_width=True,
                ):
                    _request_workflow_step(st, previous_step)
            with next_col:
                if st.button(
                    "Sección siguiente →",
                    key="workflow_next_section",
                    disabled=next_step is None,
                    use_container_width=True,
                ):
                    _request_workflow_step(st, next_step)
    def render_active_view() -> None:
        if show_section_guidance:
            _render_section_guidance(st, app_mode)
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
        st.header("Revisar documentos")
        st.caption(
            "Compará la imagen con el texto editable y registrá cada corrección sin alterar el original."
        )
        with st.expander("Cómo funciona la revisión", expanded=False):
            st.write(
                "La imagen y el OCR de origen permanecen inmutables. Cada guardado crea una nueva "
                "revisión y el historial conserva quién hizo el cambio, cuándo y con qué nota."
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
                        rerun_view(st)
            with next_col:
                if st.button("Siguiente →", use_container_width=True):
                    index = page_options.index(st.session_state["review_page_number"])
                    if index < len(page_options) - 1:
                        st.session_state["review_page_number"] = page_options[index + 1]
                        rerun_view(st)
            page = st.selectbox("Página física", options=page_options, key="review_page_number")
            with st.expander("Opciones de visualización", expanded=False):
                show_boxes = st.checkbox("Mostrar cajas OCR", value=True)
                include_deleted = st.checkbox("Mostrar objetos eliminados", value=False)
            with st.expander("Resumen del documento", expanded=False):
                st.write(f"Páginas editables: **{len(document.editable_pages)}/{document.page_count}**")
                st.write(f"Objetos activos: **{document.active_objects}**")
                if document.deleted_objects:
                    st.write(f"Objetos eliminados: **{document.deleted_objects}**")
                if document.stale_pages:
                    st.warning("Capa desactualizada en páginas: " + ", ".join(map(str, document.stale_pages)))
            with st.expander("Herramientas de la capa editable", expanded=False):
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
            with st.expander("Estado de revisión de la página", expanded=False):
                with st.form(f"page_review_{view.editable_page_id}", enter_to_submit=False):
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

        with st.expander("Deshacer o rehacer cambios", expanded=False):
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
                    "Opera sobre la última acción completa de esta página, incluidos "
                    "reordenamientos, combinaciones y divisiones."
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
                    rerun_view(st)
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
            st.subheader("Revisar objetos de la página")
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
                with st.expander("Datos del objeto seleccionado", expanded=False):
                    metadata_a, metadata_b = st.columns(2)
                    with metadata_a:
                        _render_wrapping_detail(st, "Orden", selected.order_index + 1)
                    with metadata_b:
                        _render_wrapping_detail(st, "Revisión", selected.revision_number)
                    metadata_c, metadata_d = st.columns(2)
                    with metadata_c:
                        _render_wrapping_detail(
                            st,
                            "Estado",
                            _LIFECYCLE_LABELS.get(
                                selected.lifecycle_status,
                                selected.lifecycle_status,
                            ),
                        )
                    with metadata_d:
                        _render_wrapping_detail(
                            st,
                            "Revisión humana",
                            _STATUS_LABELS[selected.review_status],
                        )
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

                st.caption("Elegí la tarea que querés realizar sobre el objeto seleccionado.")
                (
                    edit_tab,
                    structure_tab,
                    annotations_tab,
                    attributes_tab,
                    entities_tab,
                    history_tab,
                    add_tab,
                ) = tracked_tabs(
                    st,
                    [
                        "Editar texto",
                        "Orden y estructura",
                        "Anotaciones",
                        "Datos adicionales",
                        "Menciones",
                        "Historial",
                        "Agregar objeto",
                    ],
                    key="review_object_tabs",
                )
                with edit_tab:
                    with st.form(f"edit_{selected.object_id}_{selected.revision_number}", enter_to_submit=False):
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
                    with st.form(f"lifecycle_{selected.object_id}_{selected.revision_number}", enter_to_submit=False):
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
                            f"assign_part_{selected.object_id}_{selected.revision_number}",
                            enter_to_submit=False,
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

                        with st.form(f"assign_page_part_{view.editable_page_id}", enter_to_submit=False):
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
                    with st.form(f"split_{selected.object_id}_{selected.revision_number}", enter_to_submit=False):
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
                    with st.form(f"object_review_{selected.object_id}", enter_to_submit=False):
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
                    with st.form(f"add_tag_{selected.object_id}", clear_on_submit=True, enter_to_submit=False):
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
                    with st.form(f"comment_{selected.object_id}", clear_on_submit=True, enter_to_submit=False):
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

                with attributes_tab:
                    st.caption(
                        "Atributos vigentes del objeto. Incluyen procedencia OCR, "
                        "clasificaciones, valores analíticos y metadatos trasladados durante un rebase."
                    )
                    if selected.attributes:
                        st.metric("Atributos", len(selected.attributes))
                        st.json(selected.attributes, expanded=True)
                    else:
                        st.info("Este objeto no tiene atributos vigentes.")

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
                                    f"mention_update_{mention.mention_id}_{mention.revision}",
                                    enter_to_submit=False,
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
                            "Buscar nombres conocidos y alternativos",
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
                                quality_scope_source="ui",
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
                        enter_to_submit=False,
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
                            timeline = page_history_rows(
                                history_session, source_key=source_key, page=page
                            )
                            history = object_revision_rows(
                                history_session, object_id=selected.object_id
                            )
                    finally:
                        history_engine.dispose()

                    scope = st.radio(
                        "Mostrar",
                        options=["page", "object"],
                        format_func=lambda value: {
                            "page": "Toda la página",
                            "object": "Solo el objeto seleccionado",
                        }[value],
                        horizontal=True,
                        key=f"history_scope_{source_key}_{page}_{selected.object_id}",
                    )
                    visible_timeline = (
                        timeline
                        if scope == "page"
                        else [item for item in timeline if item.object_id == selected.object_id]
                    )
                    if not visible_timeline:
                        st.caption("Todavía no hay acontecimientos para este filtro.")
                    for index, item in enumerate(visible_timeline):
                        label = (
                            f"{item.title} · {item.actor} · "
                            f"{item.occurred_at.isoformat(timespec='minutes')}"
                        )
                        with st.expander(label, expanded=index == 0):
                            st.caption(f"{item.category} · {item.operation}")
                            if item.note:
                                st.write(item.note)
                            simple_details = []
                            if item.details.get("revision") is not None:
                                simple_details.append(f"revisión {item.details['revision']}")
                            if item.details.get("object"):
                                simple_details.append(str(item.details["object"]))
                            if item.details.get("object_type"):
                                simple_details.append(
                                    type_labels.get(
                                        str(item.details["object_type"]),
                                        str(item.details["object_type"]),
                                    )
                                )
                            if item.details.get("order") is not None:
                                simple_details.append(f"orden {item.details['order']}")
                            if item.details.get("status"):
                                simple_details.append(f"estado {item.details['status']}")
                            if item.details.get("review_status"):
                                simple_details.append(
                                    "revisión "
                                    + _STATUS_LABELS.get(
                                        str(item.details["review_status"]),
                                        str(item.details["review_status"]),
                                    )
                                )
                            if simple_details:
                                st.caption(" · ".join(simple_details))

                    previous_revisions = [
                        item.revision_number
                        for item in history
                        if item.revision_number < selected.revision_number
                    ]
                    if previous_revisions:
                        with st.expander("Restaurar una revisión anterior"):
                            with st.form(
                                f"revert_{selected.object_id}_{selected.revision_number}",
                                enter_to_submit=False,
                            ):
                                target_revision = st.selectbox(
                                    "Contenido a restaurar",
                                    options=previous_revisions,
                                    format_func=lambda number: f"Revisión {number}",
                                )
                                revert_note = st.text_input("Nota de restauración")
                                revert_submit = st.form_submit_button(
                                    "Crear revisión de restauración"
                                )
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
                    with st.form(f"add_{source_key}_{page}_{selected.object_id}", enter_to_submit=False):
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
                with st.form(f"add_empty_{source_key}_{page}", enter_to_submit=False):
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

    fragmented_view(st, render_active_view, mode=app_mode)

if __name__ == "__main__":
    main()
