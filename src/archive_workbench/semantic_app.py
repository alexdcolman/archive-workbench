from __future__ import annotations

from collections import Counter
from archive_workbench.ui_dates import DATE_INPUT_MIN, DATE_INPUT_MAX
from archive_workbench.ui_help import TAB_HELP
from datetime import date
from pathlib import Path

from archive_workbench.analysis_quality import (
    analysis_quality_scope,
    quality_scope_caption,
)
from archive_workbench.ui_navigation import rerun_app, rerun_view, request_app_view, section_heading, tracked_tabs

from archive_workbench.db import create_sqlite_engine, session_scope
from archive_workbench.semantic_search import (
    DEFAULT_MODEL_NAME,
    DEFAULT_MODEL_REVISION,
    REVIEW_STATUSES,
    SEMANTIC_AGGREGATION_LEVELS,
    SemanticProfileValues,
    build_semantic_index,
    ensure_default_semantic_profile,
    profile_values,
    save_semantic_profile,
    semantic_dependencies_available,
    semantic_index_status,
    semantic_profile_rows,
    semantic_search,
)

_AGGREGATION_LABELS = {
    "object": "Bloque de texto",
    "page": "Página",
    "document_part": "Parte interna",
    "document": "Documento digital",
    "archival_unit": "Unidad archivística",
}
_STATUS_LABELS = {
    "unreviewed": "Sin revisar",
    "needs_review": "Requiere revisión",
    "reviewed": "Revisado",
    "approved": "Aprobado",
}
_DEVICE_LABELS = {
    "auto": "Automático",
    "cpu": "Procesador (CPU)",
    "cuda": "Placa NVIDIA (CUDA)",
}


def _semantic_navigation_entries(results) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    for row in results:
        if not row.source_key or not row.object_ids:
            continue
        entries.append(
            {
                "source_key": row.source_key,
                "page": row.page_start,
                "object_id": row.object_ids[0],
                "document_title": row.title,
                "chunk_id": row.chunk_id,
                "semantic_query_text": row.query_text,
            }
        )
    return entries


def queue_similar_semantic_search(
    st,
    *,
    query_text: str,
    chunk_id: str | None = None,
    object_id: str | None = None,
    profile_id: str | None = None,
) -> None:
    clean = query_text.strip()
    if not clean:
        return
    st.session_state["semantic_pending_query_text"] = clean
    st.session_state["semantic_pending_execute"] = True
    st.session_state.pop("semantic_exclude_chunk_id", None)
    st.session_state.pop("semantic_exclude_object_id", None)
    if chunk_id:
        st.session_state["semantic_exclude_chunk_id"] = str(chunk_id)
    if object_id:
        st.session_state["semantic_exclude_object_id"] = str(object_id)
    if profile_id:
        st.session_state["semantic_requested_profile_id"] = str(profile_id)
    st.session_state.pop("semantic_results", None)


def _open_result(st, row, *, results, query: str, profile_id: str) -> None:
    if not row.source_key or not row.object_ids:
        st.warning("Este resultado no está vinculado con un bloque de texto que pueda abrirse en Revisar documentos.")
        return
    entries = _semantic_navigation_entries(results)
    index = next(
        (position for position, entry in enumerate(entries) if entry["chunk_id"] == row.chunk_id),
        None,
    )
    if index is None:
        return
    st.session_state["review_search_navigation"] = {
        "origin": "semantic",
        "query": query,
        "index": index,
        "results": entries,
        "semantic_profile_id": profile_id,
    }
    request_app_view(
        st,
        mode="review",
        source_key=row.source_key,
        page=row.page_start,
        object_id=row.object_ids[0],
    )
    rerun_app(st)


def _render_semantic_distribution(st, results) -> None:
    document_counts = Counter(row.title for row in results)
    part_counts = Counter(
        (row.title, row.document_part_key)
        for row in results
        if row.document_part_key
    )
    pages = {
        (row.source_key, page)
        for row in results
        if row.source_key
        for page in range(row.page_start, row.page_end + 1)
    }
    with st.expander("Distribución de los resultados", expanded=False):
        st.write(
            f"**{len(results)} resultados mostrados en {len(document_counts)} documentos"
            + (f" y {len(pages)} páginas.**" if pages else ".**")
        )
        st.write("**Por documento**")
        st.dataframe(
            [
                {"Documento": title, "Resultados mostrados": count}
                for title, count in document_counts.most_common()
            ],
            hide_index=True,
            use_container_width=True,
        )
        if part_counts:
            st.write("**Por parte interna del documento**")
            st.dataframe(
                [
                    {
                        "Documento": document,
                        "Parte interna": part,
                        "Resultados mostrados": count,
                    }
                    for (document, part), count in part_counts.most_common()
                ],
                hide_index=True,
                use_container_width=True,
            )


def render_semantic_search_view(
    st,
    *,
    project_root: Path,
    db_path: Path,
    project_id: str,
    actor: str,
    object_types: list[str],
    object_type_labels: dict[str, str],
) -> None:
    section_heading(st, "Búsqueda semántica")
    dependency_ready = semantic_dependencies_available()
    if not dependency_ready:
        st.info(
            "Podés consultar las configuraciones de búsqueda semántica guardadas, pero este equipo no tiene instalado el componente opcional necesario para construir o consultar el índice de textos."
        )
        with st.expander("Ver comando técnico de instalación"):
            st.code('pip install -e ".[semantic]"', language="bash")

    engine = create_sqlite_engine(db_path)
    try:
        with session_scope(engine) as session:
            profiles = semantic_profile_rows(session, project_id=project_id)
            if not profiles:
                profile = ensure_default_semantic_profile(
                    session, project_id=project_id, changed_by=actor or "local_user"
                )
                profiles = [profile]
    except (ValueError, RuntimeError, OSError) as exc:
        st.error(str(exc))
        engine.dispose()
        return
    finally:
        engine.dispose()

    profile_ids = [row.id for row in profiles]
    requested_profile = st.session_state.pop("semantic_requested_profile_id", None)
    preferred_profile = requested_profile or st.session_state.get("semantic_results_profile")
    if st.session_state.get("semantic_profile_id") not in profile_ids:
        st.session_state.pop("semantic_profile_id", None)
    default_profile_index = (
        profile_ids.index(preferred_profile) if preferred_profile in profile_ids else 0
    )
    selected_id = st.selectbox(
        "Configuración de búsqueda semántica",
        options=profile_ids,
        index=default_profile_index,
        format_func=lambda value: next(row.name for row in profiles if row.id == value),
        key="semantic_profile_id",
    )
    selected = next(row for row in profiles if row.id == selected_id)
    if st.session_state.get("semantic_results_profile") != selected_id:
        st.session_state.pop("semantic_results", None)
        st.session_state.pop("semantic_results_query", None)
        st.session_state.pop("semantic_results_seed_chunk_id", None)
        st.session_state.pop("semantic_results_seed_object_id", None)
        st.session_state["semantic_results_profile"] = selected_id

    engine = create_sqlite_engine(db_path)
    try:
        with session_scope(engine) as session:
            status = semantic_index_status(
                session,
                project_root=project_root,
                project_id=project_id,
                profile=selected,
            )
    except (ValueError, RuntimeError, OSError) as exc:
        st.error(str(exc))
        engine.dispose()
        return
    finally:
        engine.dispose()

    if status.is_current:
        st.caption("Índice listo para buscar.")
    else:
        st.warning(status.reason)
    with st.expander("Datos técnicos del índice de búsqueda por significado", expanded=False):
        cols = st.columns(4)
        cols[0].metric("Estado del índice de búsqueda semántica", "Actualizado" if status.is_current else "Pendiente")
        cols[1].metric("Fragmentos de texto indexados", status.vector_count)
        cols[2].metric("Dimensiones técnicas del índice", status.dimensions or "-")
        cols[3].metric("Versión de esta configuración", status.profile_revision)
        st.caption(status.reason)

    search_tab, profile_tab = tracked_tabs(
        st,
        ["Buscar en los textos", "Configurar el índice de búsqueda"],
        key="semantic_tabs",
        help_by_label=TAB_HELP["semantic_tabs"],
    )
    with search_tab:
        pending_query_text = st.session_state.pop("semantic_pending_query_text", None)
        if pending_query_text is not None:
            st.session_state["semantic_query"] = str(pending_query_text)
            st.session_state["semantic_query_input"] = str(pending_query_text)
        saved_params = st.session_state.get("semantic_search_params")
        if not isinstance(saved_params, dict):
            saved_params = {}
        top_k = int(saved_params.get("top_k", 20))
        minimum_score = float(saved_params.get("minimum_score", 0.20))
        device = str(saved_params.get("device", "auto"))
        temporal_enabled = bool(saved_params.get("temporal_enabled", False))
        temporal_from = saved_params.get("temporal_from") or date(1900, 1, 1)
        temporal_to = saved_params.get("temporal_to") or date.today()
        temporal_include_undated = bool(saved_params.get("temporal_include_undated", False))
        options_open = st.toggle(
            "Más opciones de búsqueda semántica",
            value=False,
            key="semantic_search_options_open",
            help=(
                "Permite limitar la cantidad de resultados, fijar un umbral mínimo de similitud, "
                "acotar por fechas vinculadas y elegir el equipo que ejecutará la consulta."
            ),
        )
        with st.form("semantic_query_form", enter_to_submit=False):
            query = st.text_area(
                "Qué querés encontrar",
                value=st.session_state.get("semantic_query", ""),
                placeholder="Buscar por significado en los textos",
                height=70,
                key="semantic_query_input",
                label_visibility="collapsed",
            )
            if options_open:
                left, middle, right = st.columns(3)
                with left:
                    top_k = st.number_input(
                        "Cantidad máxima de resultados que querés ver",
                        1,
                        200,
                        int(top_k),
                        1,
                    )
                with middle:
                    minimum_score = st.slider(
                        "Umbral mínimo de similitud coseno",
                        min_value=-1.0,
                        max_value=1.0,
                        value=float(minimum_score),
                        step=0.01,
                        help=(
                            "Excluye resultados con una similitud menor. Es una puntuación de cercanía "
                            "entre vectores, no una probabilidad ni un porcentaje de relevancia."
                        ),
                    )
                with right:
                    device = st.selectbox(
                        "Equipo que realizará esta búsqueda",
                        ["auto", "cpu", "cuda"],
                        index=["auto", "cpu", "cuda"].index(device) if device in {"auto", "cpu", "cuda"} else 0,
                        format_func=lambda value: _DEVICE_LABELS[value],
                    )
                temporal_enabled = st.checkbox(
                    "Acotar por fechas de entidades o relaciones vinculadas",
                    value=temporal_enabled,
                )
                temporal_cols = st.columns(3)
                temporal_from = temporal_cols[0].date_input(
                    "Desde", value=temporal_from, min_value=DATE_INPUT_MIN, max_value=DATE_INPUT_MAX, key="semantic_temporal_from"
                )
                temporal_to = temporal_cols[1].date_input(
                    "Hasta", value=temporal_to, min_value=DATE_INPUT_MIN, max_value=DATE_INPUT_MAX, key="semantic_temporal_to"
                )
                temporal_include_undated = temporal_cols[2].checkbox(
                    "Incluir resultados sin fecha vinculada", value=temporal_include_undated, key="semantic_temporal_undated"
                )
            submit = st.form_submit_button(
                "Buscar por significado",
                type="primary",
                disabled=not dependency_ready or not status.is_current,
            )
        pending_execute = bool(st.session_state.pop("semantic_pending_execute", False))
        if submit or pending_execute:
            st.session_state["review_search_navigation"] = None
            query_to_run = query if submit else str(st.session_state.get("semantic_query") or query)
            if submit:
                st.session_state["semantic_query"] = query_to_run
                st.session_state.pop("semantic_exclude_chunk_id", None)
                st.session_state.pop("semantic_exclude_object_id", None)
            params = {
                "top_k": int(top_k),
                "minimum_score": float(minimum_score),
                "device": device,
                "temporal_enabled": bool(temporal_enabled),
                "temporal_from": temporal_from,
                "temporal_to": temporal_to,
                "temporal_include_undated": bool(temporal_include_undated),
            }
            st.session_state["semantic_search_params"] = params
            excluded_chunk_id = st.session_state.pop("semantic_exclude_chunk_id", None)
            excluded_object_id = st.session_state.pop("semantic_exclude_object_id", None)
            engine = create_sqlite_engine(db_path)
            try:
                with session_scope(engine) as session:
                    profile = session.get(type(selected), selected.id)
                    results = semantic_search(
                        session,
                        project_root=project_root,
                        project_id=project_id,
                        profile=profile,
                        query=query_to_run,
                        top_k=int(top_k),
                        minimum_score=float(minimum_score),
                        exclude_chunk_ids=(str(excluded_chunk_id),) if excluded_chunk_id else (),
                        exclude_object_ids=(str(excluded_object_id),) if excluded_object_id else (),
                        temporal_start=temporal_from if temporal_enabled else None,
                        temporal_end=temporal_to if temporal_enabled else None,
                        temporal_include_undated=(
                            temporal_include_undated if temporal_enabled else False
                        ),
                        device=device,
                    )
            except (ValueError, RuntimeError, OSError) as exc:
                st.error(str(exc))
                results = None
            finally:
                engine.dispose()
            if results is not None:
                st.session_state["semantic_results"] = results
                st.session_state["semantic_results_query"] = query_to_run
                st.session_state["semantic_results_seed_chunk_id"] = excluded_chunk_id
                st.session_state["semantic_results_seed_object_id"] = excluded_object_id
        results = st.session_state.get("semantic_results")
        if results is not None:
            st.subheader(f"Resultados · {len(results)}")
            if not results:
                st.warning("No hubo resultados por encima de la similitud mínima.")
            else:
                st.caption(
                    "La similitud coseno ordena los resultados; no es una probabilidad ni demuestra por sí sola una relación analítica."
                )
                if st.session_state.get("semantic_results_seed_chunk_id") or st.session_state.get(
                    "semantic_results_seed_object_id"
                ):
                    st.caption("El pasaje usado como punto de partida se excluyó de estos resultados.")
                _render_semantic_distribution(st, results)
            results_query = str(
                st.session_state.get("semantic_results_query")
                or st.session_state.get("semantic_query")
                or ""
            )
            for index, row in enumerate(results):
                with st.container(border=True):
                    header, action = st.columns([4, 2])
                    with header:
                        pages = (
                            f"página {row.page_start}"
                            if row.page_start == row.page_end
                            else f"páginas {row.page_start}–{row.page_end}"
                        )
                        st.markdown(f"**{row.title}** · {pages} · similitud coseno **{row.score:.3f}**")
                        details = []
                        if row.document_part_key:
                            details.append(f"parte {row.document_part_key}")
                        if row.hierarchy_path:
                            details.append(row.hierarchy_path)
                        st.caption(" · ".join(details))
                    with action:
                        if st.button(
                            "Abrir este resultado en el documento",
                            key=f"semantic_open_{index}_{row.chunk_id}",
                            disabled=not row.source_key or not row.object_ids,
                            use_container_width=True,
                        ):
                            _open_result(
                                st,
                                row,
                                results=results,
                                query=results_query,
                                profile_id=selected_id,
                            )
                        if st.button(
                            "Buscar pasajes similares a este resultado",
                            key=f"semantic_similar_{index}_{row.chunk_id}",
                            use_container_width=True,
                        ):
                            queue_similar_semantic_search(
                                st,
                                query_text=row.query_text,
                                chunk_id=row.chunk_id,
                                profile_id=selected_id,
                            )
                            rerun_view(st)
                    st.write(row.excerpt)

    with profile_tab:
        values = profile_values(selected)
        current_scope = analysis_quality_scope(values.include_page_review_statuses)
        if current_scope.is_default:
            st.info(quality_scope_caption(values.include_page_review_statuses))
        else:
            st.warning(quality_scope_caption(values.include_page_review_statuses))
        technical_build_options_open = st.toggle(
            "Opciones técnicas para construir el índice",
            value=False,
            key="semantic_profile_build_options_open",
        )
        model_name = values.model_name
        model_revision = values.model_revision or ""
        chunk_size = values.chunk_size
        chunk_overlap = min(values.chunk_overlap, int(chunk_size) - 1)
        query_prefix = values.query_prefix
        document_prefix = values.document_prefix
        normalize = values.normalize_embeddings
        with st.form("semantic_profile_form", enter_to_submit=False):
            name = st.text_input("Nombre de esta configuración de búsqueda", value=values.name)
            description = st.text_area("Descripción de esta configuración de búsqueda", value=values.description or "", height=70)
            aggregation = st.selectbox(
                "Nivel del corpus en el que querés agrupar los resultados",
                options=list(SEMANTIC_AGGREGATION_LEVELS),
                index=list(SEMANTIC_AGGREGATION_LEVELS).index(values.aggregation_level),
                format_func=lambda value: _AGGREGATION_LABELS[value],
            )
            st.markdown("**Contenido del índice**")
            filter_left, filter_middle, filter_right = st.columns(3)
            with filter_left:
                selected_types = st.multiselect(
                    "Tipos de bloques de texto que querés incluir",
                    options=object_types,
                    default=list(values.include_object_types),
                    format_func=lambda value: object_type_labels.get(value, value),
                    help="Si no elegís ningún tipo, se incluirán todos los bloques de texto activos.",
                )
            with filter_middle:
                object_statuses = st.multiselect(
                    "Estados de revisión de los bloques de texto que querés incluir",
                    options=list(REVIEW_STATUSES),
                    default=list(values.include_review_statuses),
                    format_func=lambda value: _STATUS_LABELS[value],
                    help="Si no elegís ningún estado, se incluirán bloques de texto con cualquier estado de revisión.",
                )
            with filter_right:
                page_statuses = st.multiselect(
                    "Estados de revisión de las páginas que querés incluir",
                    options=list(REVIEW_STATUSES),
                    default=list(values.include_page_review_statuses),
                    format_func=lambda value: _STATUS_LABELS[value],
                    help=(
                        "El alcance seguro usa solamente páginas aprobadas. Vacío "
                        "incluye todos los estados y requiere confirmación al guardar."
                    ),
                )
            broader_quality_scope_confirmed = st.checkbox(
                "Confirmo que el índice de búsqueda puede incluir páginas que todavía no fueron aprobadas",
                value=False,
                help=(
                    "La comprobación se realiza al enviar el formulario. El botón no "
                    "depende de cambios reactivos dentro de st.form."
                ),
            )
            quality_scope_reason = st.text_area(
                "Por qué el índice debe incluir páginas todavía no aprobadas",
                value="",
                placeholder=(
                    "Explicá por qué el índice debe incluir páginas que todavía no están aprobadas."
                ),
                help=(
                    "Solo es obligatorio cuando el alcance incluye páginas no aprobadas. "
                    "Quedará registrado en la auditoría del proyecto."
                ),
                height=90,
            )
            if technical_build_options_open:
                with st.container(border=True):
                    model_name = st.text_input("Modelo técnico para representar el significado de los textos", value=values.model_name)
                    model_revision = st.text_input(
                        "Versión del modelo técnico",
                        value=values.model_revision or "",
                        help="Fijarla permite reconstruir el mismo modelo aunque el repositorio cambie.",
                    )
                    chunk_size = st.number_input(
                        "Tamaño máximo del fragmento (caracteres)",
                        200,
                        20_000,
                        values.chunk_size,
                        100,
                    )
                    chunk_overlap = st.number_input(
                        "Caracteres compartidos entre fragmentos consecutivos",
                        0,
                        int(chunk_size) - 1,
                        min(values.chunk_overlap, int(chunk_size) - 1),
                        25,
                    )
                    query_prefix = st.text_input("Prefijo técnico agregado a las consultas", value=values.query_prefix)
                    document_prefix = st.text_input("Prefijo técnico agregado a los textos del corpus", value=values.document_prefix)
                    normalize = st.checkbox("Normalizar las representaciones numéricas de los textos", value=values.normalize_embeddings)
            save = st.form_submit_button("Guardar configuración de búsqueda semántica")
        if save:
            engine = create_sqlite_engine(db_path)
            try:
                with session_scope(engine) as session:
                    save_semantic_profile(
                        session,
                        project_id=project_id,
                        profile_id=selected.id,
                        values=SemanticProfileValues(
                            name=name,
                            description=description,
                            model_name=model_name,
                            model_revision=model_revision,
                            aggregation_level=aggregation,
                            include_object_types=tuple(selected_types),
                            include_review_statuses=tuple(object_statuses),
                            include_page_review_statuses=tuple(page_statuses),
                            chunk_size=int(chunk_size),
                            chunk_overlap=int(chunk_overlap),
                            query_prefix=query_prefix,
                            document_prefix=document_prefix,
                            normalize_embeddings=normalize,
                        ),
                        changed_by=actor or "local_user",
                        broader_quality_scope_confirmed=broader_quality_scope_confirmed,
                        quality_scope_reason=quality_scope_reason,
                        quality_scope_source="ui",
                    )
            except (ValueError, RuntimeError, OSError) as exc:
                st.error(str(exc))
            else:
                st.success("Configuración de búsqueda semántica guardada. El índice anterior queda desactualizado hasta que lo reconstruyas.")
                st.session_state.pop("semantic_results", None)
                rerun_view(st)
            finally:
                engine.dispose()

        st.divider()
        st.subheader("Índice de búsqueda semántica")
        technical_build_options_open = st.toggle(
            "Opciones técnicas para construir el índice",
            value=False,
            key="semantic_index_build_options_open",
        )
        build_device = str(
            st.session_state.get("semantic_build_device__remembered", "auto")
        )
        if build_device not in {"auto", "cpu", "cuda"}:
            build_device = "auto"
        batch_size = int(
            st.session_state.get("semantic_build_batch__remembered", 32)
        )
        batch_size = max(1, min(512, batch_size))
        if technical_build_options_open:
            with st.container(border=True):
                st.caption(
                    f"Modelo inicial sugerido: `{DEFAULT_MODEL_NAME}` en revisión `{DEFAULT_MODEL_REVISION}`."
                )
                build_left, build_middle = st.columns(2)
                with build_left:
                    if "semantic_build_device" not in st.session_state:
                        st.session_state["semantic_build_device"] = build_device
                    build_device = st.selectbox(
                        "Equipo que construirá el índice",
                        ["auto", "cpu", "cuda"],
                        key="semantic_build_device",
                        format_func=lambda value: _DEVICE_LABELS[value],
                    )
                    st.session_state["semantic_build_device__remembered"] = build_device
                with build_middle:
                    if "semantic_build_batch" not in st.session_state:
                        st.session_state["semantic_build_batch"] = batch_size
                    batch_size = st.number_input(
                        "Cantidad de fragmentos procesados por lote",
                        1,
                        512,
                        key="semantic_build_batch",
                    )
                    st.session_state["semantic_build_batch__remembered"] = int(batch_size)
        build_clicked = st.button(
            "Construir o reconstruir el índice de búsqueda semántica",
            type="primary",
            disabled=not dependency_ready,
            use_container_width=True,
        )
        if build_clicked:
            engine = create_sqlite_engine(db_path)
            try:
                with st.spinner("Codificando el corpus y escribiendo el índice local…"):
                    with session_scope(engine) as session:
                        profile = session.get(type(selected), selected.id)
                        summary = build_semantic_index(
                            session,
                            project_root=project_root,
                            project_id=project_id,
                            profile=profile,
                            created_by=actor or "local_user",
                            device=build_device,
                            batch_size=int(batch_size),
                        )
            except (ValueError, RuntimeError, OSError) as exc:
                st.error(str(exc))
            else:
                st.success(
                    f"Índice construido: {summary.vector_count} fragmentos · {summary.dimensions} dimensiones"
                )
                st.session_state.pop("semantic_results", None)
                rerun_view(st)
            finally:
                engine.dispose()
