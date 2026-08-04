from __future__ import annotations

from datetime import date
from pathlib import Path

from archive_workbench.analysis_quality import (
    analysis_quality_scope,
    quality_scope_caption,
)
from archive_workbench.ui_navigation import rerun_app, rerun_view, request_app_view, tracked_tabs

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
    "object": "Objeto textual",
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


def _open_result(st, row) -> None:
    if not row.source_key or not row.object_ids:
        st.warning("Este resultado no tiene un objeto textual navegable.")
        return
    request_app_view(
        st,
        mode="review",
        source_key=row.source_key,
        page=row.page_start,
        object_id=row.object_ids[0],
    )
    rerun_app(st)


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
    st.header("Buscar por significado")
    st.caption(
        "Encontrá fragmentos cercanos por sentido aunque no usen las mismas palabras. "
        "Esta búsqueda es opcional, no modifica el corpus y sus resultados siempre deben revisarse en contexto."
    )
    dependency_ready = semantic_dependencies_available()
    if not dependency_ready:
        st.info(
            "Los perfiles pueden consultarse, pero falta instalar el componente opcional "
            "para construir o usar el índice semántico."
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

    selected_id = st.selectbox(
        "Perfil de búsqueda",
        options=[row.id for row in profiles],
        format_func=lambda value: next(row.name for row in profiles if row.id == value),
        key="semantic_profile_id",
    )
    selected = next(row for row in profiles if row.id == selected_id)
    if st.session_state.get("semantic_results_profile") != selected_id:
        st.session_state.pop("semantic_results", None)
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
        st.success("La búsqueda por significado está lista para usar.")
    else:
        st.warning(status.reason)
    with st.expander("Estado técnico del índice", expanded=False):
        cols = st.columns(4)
        cols[0].metric("Estado", "Actualizado" if status.is_current else "Pendiente")
        cols[1].metric("Fragmentos", status.vector_count)
        cols[2].metric("Dimensiones", status.dimensions or "-")
        cols[3].metric("Revisión del perfil", status.profile_revision)
        st.caption(status.reason)

    search_tab, profile_tab = tracked_tabs(
        st, ["Buscar", "Preparar búsqueda"], key="semantic_tabs"
    )
    with search_tab:
        with st.form("semantic_query_form", enter_to_submit=False):
            query = st.text_area(
                "Qué querés encontrar",
                value=st.session_state.get("semantic_query", ""),
                placeholder="Ej.: vigilancia de organizaciones políticas y culturales",
                height=90,
            )
            with st.expander("Opciones de búsqueda", expanded=False):
                st.caption(
                    "Los valores predeterminados sirven para una primera exploración. "
                    "La similitud mínima debe calibrarse con consultas reales del corpus."
                )
                left, middle, right = st.columns(3)
                with left:
                    top_k = st.number_input("Máximo de resultados", 1, 200, 20, 1)
                with middle:
                    minimum_score = st.slider(
                        "Similitud mínima",
                        min_value=-1.0,
                        max_value=1.0,
                        value=0.20,
                        step=0.01,
                        help="Es una similitud coseno, no una probabilidad.",
                    )
                with right:
                    device = st.selectbox(
                        "Dónde ejecutar la búsqueda",
                        ["auto", "cpu", "cuda"],
                        format_func=lambda value: _DEVICE_LABELS[value],
                    )
                temporal_enabled = st.checkbox(
                    "Acotar por fechas de entidades o relaciones vinculadas"
                )
                temporal_cols = st.columns(3)
                temporal_from = temporal_cols[0].date_input(
                    "Desde", value=date(1900, 1, 1), key="semantic_temporal_from"
                )
                temporal_to = temporal_cols[1].date_input(
                    "Hasta", value=date.today(), key="semantic_temporal_to"
                )
                temporal_include_undated = temporal_cols[2].checkbox(
                    "Incluir sin fecha", value=False, key="semantic_temporal_undated"
                )
            submit = st.form_submit_button(
                "Buscar por significado",
                type="primary",
                disabled=not dependency_ready or not status.is_current,
            )
        if submit:
            st.session_state["semantic_query"] = query
            engine = create_sqlite_engine(db_path)
            try:
                with session_scope(engine) as session:
                    profile = session.get(type(selected), selected.id)
                    results = semantic_search(
                        session,
                        project_root=project_root,
                        project_id=project_id,
                        profile=profile,
                        query=query,
                        top_k=int(top_k),
                        minimum_score=float(minimum_score),
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
        results = st.session_state.get("semantic_results")
        if results is not None:
            st.subheader(f"Resultados · {len(results)}")
            if not results:
                st.warning("No hubo resultados por encima de la similitud mínima.")
            for index, row in enumerate(results):
                with st.container(border=True):
                    header, action = st.columns([5, 1])
                    with header:
                        pages = (
                            f"página {row.page_start}"
                            if row.page_start == row.page_end
                            else f"páginas {row.page_start}–{row.page_end}"
                        )
                        st.markdown(f"**{row.title}** · {pages} · similitud **{row.score:.3f}**")
                        details = [row.source_key or "sin identificador técnico"]
                        if row.document_part_key:
                            details.append(f"parte {row.document_part_key}")
                        if row.hierarchy_path:
                            details.append(row.hierarchy_path)
                        st.caption(" · ".join(details))
                    with action:
                        if st.button(
                            "Abrir",
                            key=f"semantic_open_{index}_{row.chunk_id}",
                            disabled=not row.source_key or not row.object_ids,
                            use_container_width=True,
                        ):
                            _open_result(st, row)
                    st.write(row.excerpt)
                    st.caption(
                        "El puntaje ordena resultados de este perfil y modelo; no demuestra por sí solo una relación analítica."
                    )

    with profile_tab:
        st.caption(
            "Esta pantalla prepara el índice que usa la búsqueda. Los cambios no modifican el corpus, "
            "pero obligan a reconstruir el índice."
        )
        values = profile_values(selected)
        current_scope = analysis_quality_scope(values.include_page_review_statuses)
        if current_scope.is_default:
            st.info(quality_scope_caption(values.include_page_review_statuses))
        else:
            st.warning(quality_scope_caption(values.include_page_review_statuses))
        with st.form("semantic_profile_form", enter_to_submit=False):
            name = st.text_input("Nombre del perfil", value=values.name)
            description = st.text_area("Descripción", value=values.description or "", height=70)
            aggregation = st.selectbox(
                "Unidad que se buscará",
                options=list(SEMANTIC_AGGREGATION_LEVELS),
                index=list(SEMANTIC_AGGREGATION_LEVELS).index(values.aggregation_level),
                format_func=lambda value: _AGGREGATION_LABELS[value],
            )
            with st.expander("Contenido incluido", expanded=True):
                filter_left, filter_right = st.columns(2)
                with filter_left:
                    selected_types = st.multiselect(
                        "Tipos de objeto",
                        options=object_types,
                        default=list(values.include_object_types),
                        format_func=lambda value: object_type_labels.get(value, value),
                        help="Vacío significa todos los tipos activos.",
                    )
                    object_statuses = st.multiselect(
                        "Estados del objeto",
                        options=list(REVIEW_STATUSES),
                        default=list(values.include_review_statuses),
                        format_func=lambda value: _STATUS_LABELS[value],
                        help="Vacío significa todos.",
                    )
                with filter_right:
                    page_statuses = st.multiselect(
                        "Estados de página",
                        options=list(REVIEW_STATUSES),
                        default=list(values.include_page_review_statuses),
                        format_func=lambda value: _STATUS_LABELS[value],
                        help=(
                            "El alcance seguro usa solamente páginas aprobadas. Vacío "
                            "incluye todos los estados y requiere confirmación al guardar."
                        ),
                    )
            broader_quality_scope_confirmed = st.checkbox(
                "Confirmo que deseo incluir páginas no aprobadas en este análisis automático",
                value=False,
                help=(
                    "La comprobación se realiza al enviar el formulario. El botón no "
                    "depende de cambios reactivos dentro de st.form."
                ),
            )
            quality_scope_reason = st.text_area(
                "Fundamento del alcance ampliado",
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
            with st.expander("Configuración técnica del índice", expanded=False):
                model_name = st.text_input("Modelo", value=values.model_name)
                model_revision = st.text_input(
                    "Revisión del modelo",
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
                    "Superposición entre fragmentos",
                    0,
                    int(chunk_size) - 1,
                    min(values.chunk_overlap, int(chunk_size) - 1),
                    25,
                )
                query_prefix = st.text_input("Prefijo de consulta", value=values.query_prefix)
                document_prefix = st.text_input("Prefijo de documento", value=values.document_prefix)
                normalize = st.checkbox("Normalizar vectores", value=values.normalize_embeddings)
            save = st.form_submit_button("Guardar perfil")
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
                st.success("Perfil guardado. El índice anterior queda pendiente de reconstrucción.")
                st.session_state.pop("semantic_results", None)
                rerun_view(st)
            finally:
                engine.dispose()

        st.divider()
        st.subheader("Actualizar índice de búsqueda")
        st.caption(
            "La primera ejecución puede descargar el modelo. Reconstruí el índice después de cambiar el perfil o el corpus."
        )
        with st.expander("Modelo sugerido y opciones de ejecución", expanded=False):
            st.caption(
                f"Modelo inicial sugerido: `{DEFAULT_MODEL_NAME}` en revisión `{DEFAULT_MODEL_REVISION}`."
            )
            build_left, build_middle = st.columns(2)
            with build_left:
                build_device = st.selectbox(
                    "Dónde construir el índice",
                    ["auto", "cpu", "cuda"],
                    key="semantic_build_device",
                    format_func=lambda value: _DEVICE_LABELS[value],
                )
            with build_middle:
                batch_size = st.number_input(
                    "Cantidad por lote", 1, 512, 32, 1, key="semantic_build_batch"
                )
        build_clicked = st.button(
            "Construir o reconstruir índice",
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
