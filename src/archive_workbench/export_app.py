from __future__ import annotations

from archive_workbench.ui_dates import DATE_INPUT_MIN, DATE_INPUT_MAX
from archive_workbench.ui_help import TAB_HELP, TASK_HELP
from datetime import date
from pathlib import Path

from archive_workbench.audiovisual import (
    AudiovisualExportOptions,
    audiovisual_media_rows,
    default_audiovisual_export_filename,
    preview_transcript_export,
    run_audiovisual_export,
)
from archive_workbench.analysis_quality import (
    DEFAULT_AUTOMATIC_PAGE_REVIEW_STATUSES,
    analysis_quality_scope,
    quality_scope_caption,
)
from archive_workbench.corpus_export import (
    AGGREGATION_LEVELS,
    OUTPUT_FORMATS,
    RUN_OUTPUT_FORMATS,
    REVIEW_STATUSES,
    TEXT_POLICIES,
    ExportProfileValues,
    default_export_filename,
    delete_export_profile,
    export_profile_rows,
    export_run_rows,
    preview_export,
    run_export,
    save_export_profile,
    set_export_profile_archived,
)
from archive_workbench.db import create_sqlite_engine, session_scope
from archive_workbench.ui_navigation import mount_choice_help, rerun_view, section_heading, tracked_tabs
from archive_workbench.visual_export import VisualExportOptions

_AGGREGATION_LABELS = {
    "object": "Un registro por bloque de texto",
    "page": "Un registro por página",
    "document_part": "Un registro por parte interna",
    "document": "Un registro por documento digital",
    "archival_unit": "Un registro por unidad archivística",
}
_TEXT_POLICY_LABELS = {
    "corrected_fallback_original": "Texto corregido; usar OCR si quedó vacío",
    "corrected_only": "Solo texto corregido",
    "original_only": "Solo OCR original",
}
_REVIEW_LABELS = {
    "unreviewed": "Sin revisar",
    "needs_review": "Requiere revisión",
    "reviewed": "Revisado",
    "approved": "Aprobado",
}
_OUTPUT_FORMAT_LABELS = {
    "jsonl": "JSONL · un registro por línea",
    "csv": "CSV · tabla",
    "visual_zip": "Exportar texto e imágenes (ZIP)",
}

_AUDIOVISUAL_TEXT_POLICY_LABELS = {
    "corrected_fallback_original": "Texto corregido; usar la transcripción original si quedó vacío",
    "corrected_only": "Solo texto corregido",
    "original_only": "Solo transcripción original",
}
_AUDIOVISUAL_RUN_SCOPE_LABELS = {
    "latest_completed_per_media": "Última transcripción completada de cada audio o video",
    "all_completed": "Todas las transcripciones completadas",
}
_AUDIOVISUAL_REVIEW_LABELS = {
    "unreviewed": "Sin revisar",
    "reviewed": "Revisado",
    "approved": "Aprobado",
}

_EXPORT_SELECTION_KEY = "export_profile_selected_id"
_EXPORT_SELECTOR_EPOCH_KEY = "export_profile_selector_epoch"
_EXPORT_PENDING_LIFECYCLE_KEY = "export_profile_pending_lifecycle"
_EXPORT_LIFECYCLE_ERROR_KEY = "export_profile_lifecycle_error"


def _request_profile_view_rebuild(st, *, selected_id: str | None) -> None:
    """Reconstruye el selector y el formulario dentro del fragmento actual.

    Las acciones de ciclo de vida cambian simultáneamente las opciones del selector y
    el árbol renderizado dentro de pestañas. La generación nueva del selector impide
    reutilizar el widget anterior. El rerun debe limitarse al fragmento que contiene
    toda la vista de Exportar: así Streamlit elimina su árbol anterior antes de montar
    el nuevo. Un rerun completo solicitado desde el fragmento podía dejar ambos árboles
    visibles durante el archivado.
    """

    st.session_state[_EXPORT_SELECTION_KEY] = selected_id
    st.session_state[_EXPORT_SELECTOR_EPOCH_KEY] = (
        int(st.session_state.get(_EXPORT_SELECTOR_EPOCH_KEY, 0)) + 1
    )
    rerun_view(st)



def _queue_profile_lifecycle_action(
    st,
    *,
    action: str,
    profile_id: str,
    confirm_key: str,
) -> None:
    """Encola una acción para ejecutarla antes de renderizar la vista siguiente.

    ``st.form_submit_button`` ejecuta su callback antes del rerun ordinario del
    formulario. Encolar aquí evita mutar la base y solicitar otro rerun a mitad del
    render, que podía dejar simultáneamente el árbol visual anterior y el nuevo.
    """

    if not bool(st.session_state.get(confirm_key, False)):
        labels = {
            "archive": "archivar",
            "restore": "restaurar",
            "delete": "eliminar",
        }
        verb = labels.get(action, "continuar")
        st.session_state[_EXPORT_LIFECYCLE_ERROR_KEY] = (
            f"Marcá la confirmación antes de {verb} esta configuración de exportación."
        )
        return

    st.session_state[_EXPORT_PENDING_LIFECYCLE_KEY] = {
        "action": action,
        "profile_id": profile_id,
    }


def _process_pending_profile_lifecycle(
    st,
    *,
    db_path,
    project_id: str,
    actor: str,
) -> None:
    """Aplica una acción encolada antes de construir selector, pestañas y formularios."""

    error = st.session_state.pop(_EXPORT_LIFECYCLE_ERROR_KEY, None)
    if error:
        st.error(str(error))

    pending = st.session_state.pop(_EXPORT_PENDING_LIFECYCLE_KEY, None)
    if not isinstance(pending, dict):
        return

    action = str(pending.get("action") or "")
    profile_id = str(pending.get("profile_id") or "")
    if not profile_id:
        st.error("No se pudo identificar la configuración de exportación solicitada.")
        return

    try:
        if action == "archive":
            name = _set_profile_archived_action(
                db_path,
                project_id=project_id,
                profile_id=profile_id,
                archived=True,
                actor=actor,
            )
            notice = f"Configuración de exportación archivada: {name}"
            selected_id: str | None = None
        elif action == "restore":
            name = _set_profile_archived_action(
                db_path,
                project_id=project_id,
                profile_id=profile_id,
                archived=False,
                actor=actor,
            )
            notice = f"Configuración de exportación restaurada: {name}"
            selected_id = profile_id
        elif action == "delete":
            name = _delete_profile_action(
                db_path,
                project_id=project_id,
                profile_id=profile_id,
            )
            notice = (
                f"Configuración de exportación eliminada: {name}. "
                "Las exportaciones históricas se conservaron."
            )
            selected_id = None
        else:
            st.error("La acción solicitada sobre esta configuración de exportación no es válida.")
            return
    except (ValueError, RuntimeError, OSError) as exc:
        st.error(str(exc))
        return

    st.session_state["export_notice"] = notice
    st.session_state[_EXPORT_SELECTION_KEY] = selected_id
    st.session_state[_EXPORT_SELECTOR_EPOCH_KEY] = (
        int(st.session_state.get(_EXPORT_SELECTOR_EPOCH_KEY, 0)) + 1
    )

def _save_profile_action(
    db_path,
    *,
    project_id: str,
    profile_id: str | None,
    values: ExportProfileValues,
    actor: str,
    broader_quality_scope_confirmed: bool = False,
    quality_scope_reason: str | None = None,
) -> str:
    engine = create_sqlite_engine(db_path)
    try:
        with session_scope(engine) as session:
            profile = save_export_profile(
                session,
                project_id=project_id,
                profile_id=profile_id,
                values=values,
                changed_by=actor or "local_user",
                broader_quality_scope_confirmed=broader_quality_scope_confirmed,
                quality_scope_reason=quality_scope_reason,
                quality_scope_source="ui",
            )
            return profile.id
    finally:
        engine.dispose()


def _set_profile_archived_action(
    db_path,
    *,
    project_id: str,
    profile_id: str,
    archived: bool,
    actor: str,
) -> str:
    engine = create_sqlite_engine(db_path)
    try:
        with session_scope(engine) as session:
            profile = set_export_profile_archived(
                session,
                project_id=project_id,
                profile_id=profile_id,
                archived=archived,
                changed_by=actor or "local_user",
            )
            return profile.name
    finally:
        engine.dispose()


def _delete_profile_action(
    db_path,
    *,
    project_id: str,
    profile_id: str,
) -> str:
    engine = create_sqlite_engine(db_path)
    try:
        with session_scope(engine) as session:
            return delete_export_profile(
                session,
                project_id=project_id,
                profile_id=profile_id,
            )
    finally:
        engine.dispose()


def _decode_separator(value: str) -> str:
    return value.replace("\\r", "\r").replace("\\n", "\n").replace("\\t", "\t")


def _render_export_result(st, *, project_root) -> None:
    result = st.session_state.get("export_last_run")
    if not isinstance(result, dict):
        return

    if str(result["format"]) == "visual_zip":
        row_count = int(result["row_count"])
        page_count = int(result.get("page_image_count", 0))
        region_count = int(result.get("region_image_count", 0))
        figure_count = int(result.get("figure_image_count", 0))
        st.success(
            "Exportación creada correctamente: "
            f"{row_count} {'registro' if row_count == 1 else 'registros'} de texto · "
            f"{page_count} {'página' if page_count == 1 else 'páginas'} · "
            f"{region_count} {'recorte' if region_count == 1 else 'recortes'} · "
            f"{figure_count} {'figura' if figure_count == 1 else 'figuras'}."
        )
        if result.get("context_object_count"):
            st.caption(
                f"El ZIP conserva {result['context_object_count']} bloques de texto de contexto "
                "para las páginas y documentos incluidos."
            )
    else:
        st.success(
            "Exportación creada correctamente: "
            f"{result['row_count']} registros, {result['character_count']} caracteres, "
            f"formato {str(result['format']).upper()}."
        )
    output_path = project_root / str(result["relative_path"])
    st.caption(f"Archivo creado: **{output_path.name}**")
    with st.expander("Detalles técnicos de esta exportación", expanded=False):
        st.write(f"Ruta dentro del proyecto: `{result['relative_path']}`")
        st.write(f"Huella SHA-256: `{result['sha256']}`")
        st.write(f"Tamaño del archivo: {result['byte_size']} bytes")

    download_col, dismiss_col = st.columns(2)
    if output_path.is_file():
        download_col.download_button(
            "Descargar esta exportación",
            data=output_path.read_bytes(),
            file_name=output_path.name,
            mime=(
                "application/x-ndjson"
                if str(result["format"]) == "jsonl"
                else (
                    "application/zip"
                    if str(result["format"]) == "visual_zip"
                    else "text/csv"
                )
            ),
            use_container_width=True,
            key=f"export_download_{result['run_id']}",
        )
    else:
        download_col.warning("El archivo ya no está disponible en la ruta registrada.")
    if dismiss_col.button(
        "Cerrar confirmación",
        use_container_width=True,
        key=f"export_dismiss_{result['run_id']}",
    ):
        st.session_state.pop("export_last_run", None)
        rerun_view(st)


def _render_profile_editor(
    st,
    *,
    selected,
    db_path,
    project_id: str,
    actor: str,
    object_types: list[str],
    object_type_labels: dict[str, str],
    runs,
) -> None:
    default_types = list(selected.include_object_types_json or []) if selected else []
    default_object_statuses = (
        list(selected.include_review_statuses_json or []) if selected else []
    )
    default_page_statuses = (
        list(selected.include_page_review_statuses_json or [])
        if selected
        else list(DEFAULT_AUTOMATIC_PAGE_REVIEW_STATUSES)
    )
    default_temporal_enabled = bool(
        selected and (selected.temporal_start or selected.temporal_end)
    )
    initial_scope = analysis_quality_scope(default_page_statuses)
    if initial_scope.is_default:
        st.info(quality_scope_caption(default_page_statuses))
    else:
        st.warning(quality_scope_caption(default_page_statuses))
    temporal_filter_open = st.toggle(
        "Filtro temporal de entidades y relaciones",
        value=False,
        key="export_temporal_filter_open",
    )
    separator_options_open = st.toggle(
        "Cómo separar páginas y bloques de texto en el archivo exportado",
        value=False,
        key="export_separator_options_open",
    )
    temporal_enabled = default_temporal_enabled
    temporal_start = (
        selected.temporal_start
        if selected and selected.temporal_start
        else date.today()
    )
    temporal_end = (
        selected.temporal_end
        if selected and selected.temporal_end
        else date.today()
    )
    temporal_include_undated = (
        bool(selected.temporal_include_undated) if selected else False
    )
    object_separator = selected.object_separator if selected else "\n\n"
    page_separator = selected.page_separator if selected else "\n\n"
    include_page_markers = bool(selected.include_page_markers) if selected else False

    form_key = f"corpus_export_profile_form_{selected.id if selected else 'new'}"
    with st.form(form_key, enter_to_submit=False):
        name = st.text_input("Nombre de esta configuración de exportación", value=selected.name if selected else "")
        description = st.text_area(
            "Descripción opcional de esta configuración",
            value=selected.description or "" if selected else "",
        )
        left, right = st.columns(2)
        with left:
            aggregation = st.selectbox(
                "Cómo agrupar los textos en el archivo exportado",
                options=list(AGGREGATION_LEVELS),
                index=(
                    list(AGGREGATION_LEVELS).index(selected.aggregation_level)
                    if selected
                    else 3
                ),
                format_func=lambda value: _AGGREGATION_LABELS[value],
            )
            text_policy = st.selectbox(
                "Qué versión del texto querés exportar",
                options=list(TEXT_POLICIES),
                index=(
                    list(TEXT_POLICIES).index(selected.text_policy) if selected else 0
                ),
                format_func=lambda value: _TEXT_POLICY_LABELS[value],
            )
            output_format = st.selectbox(
                "Formato de archivo predeterminado",
                options=list(OUTPUT_FORMATS),
                index=(
                    list(OUTPUT_FORMATS).index(selected.output_format) if selected else 0
                ),
                format_func=lambda value: _OUTPUT_FORMAT_LABELS.get(value, value.upper()),
            )
        with right:
            include_types = st.multiselect(
                "Tipos de bloques de texto que querés exportar",
                options=object_types,
                default=[value for value in default_types if value in object_types],
                format_func=lambda value: object_type_labels.get(value, value),
            )
            include_statuses = st.multiselect(
                "Estados de revisión de los bloques de texto que querés exportar",
                options=list(REVIEW_STATUSES),
                default=default_object_statuses,
                format_func=lambda value: _REVIEW_LABELS[value],
            )
            include_page_statuses = st.multiselect(
                "Estados de revisión de las páginas que querés exportar",
                options=list(REVIEW_STATUSES),
                default=default_page_statuses,
                format_func=lambda value: _REVIEW_LABELS[value],
                help=(
                    "El alcance seguro usa solamente páginas aprobadas. Vacío incluye "
                    "todos los estados y requiere confirmación explícita al guardar."
                ),
            )
        broader_quality_scope_confirmed = st.checkbox(
            "Confirmo que esta exportación puede incluir páginas que todavía no fueron aprobadas",
            value=False,
            help=(
                "Solo es necesaria cuando el alcance de páginas no es exactamente "
                "Aprobada. La comprobación se realiza al guardar, no deshabilitando "
                "el botón dentro del formulario."
            ),
        )
        quality_scope_reason = st.text_area(
            "Por qué esta exportación debe incluir páginas todavía no aprobadas",
            value="",
            placeholder=(
                "Explicá por qué este análisis debe incluir páginas que todavía no están aprobadas."
            ),
            help=(
                "Solo es obligatorio cuando el alcance incluye páginas no aprobadas. "
                "Quedará registrado en la auditoría del proyecto."
            ),
            height=90,
        )
        if temporal_filter_open:
            with st.container(border=True):
                temporal_enabled = st.checkbox(
                    "Incluir sólo textos vinculados con entidades o relaciones de un período",
                    value=default_temporal_enabled,
                    help=(
                        "Incluye bloques de texto que mencionan una entidad o participan en una relación "
                        "cuyo período se superpone con el rango indicado."
                    ),
                )
                temporal_cols = st.columns(2)
                temporal_start = temporal_cols[0].date_input(
                    "Desde",
                    value=temporal_start,
                    min_value=DATE_INPUT_MIN,
                    max_value=DATE_INPUT_MAX,
                    key=f"export_temporal_start_{selected.id if selected else 'new'}",
                )
                temporal_end = temporal_cols[1].date_input(
                    "Hasta",
                    value=temporal_end,
                    min_value=DATE_INPUT_MIN,
                    max_value=DATE_INPUT_MAX,
                    key=f"export_temporal_end_{selected.id if selected else 'new'}",
                )
                temporal_include_undated = st.checkbox(
                    "Incluir registros vinculados solo con entidades o relaciones sin fecha",
                    value=temporal_include_undated,
                )
        if separator_options_open:
            with st.container(border=True):
                object_separator = st.text_input(
                    "Texto que separará los bloques de una misma página",
                    value=object_separator,
                )
                page_separator = st.text_input(
                    "Separador entre páginas",
                    value=page_separator,
                )
                include_page_markers = st.checkbox(
                    "Agregar marcas [Página N]",
                    value=include_page_markers,
                )
        submitted = st.form_submit_button("Guardar esta configuración de exportación", type="primary")

    if submitted:
        try:
            saved_id = _save_profile_action(
                db_path,
                project_id=project_id,
                profile_id=selected.id if selected else None,
                values=ExportProfileValues(
                    name=name,
                    description=description,
                    aggregation_level=aggregation,
                    text_policy=text_policy,
                    output_format=output_format,
                    include_object_types=tuple(include_types),
                    include_review_statuses=tuple(include_statuses),
                    include_page_review_statuses=tuple(include_page_statuses),
                    temporal_start=temporal_start if temporal_enabled else None,
                    temporal_end=temporal_end if temporal_enabled else None,
                    temporal_include_undated=(
                        temporal_include_undated if temporal_enabled else False
                    ),
                    object_separator=_decode_separator(object_separator),
                    page_separator=_decode_separator(page_separator),
                    include_page_markers=include_page_markers,
                ),
                actor=actor,
                broader_quality_scope_confirmed=broader_quality_scope_confirmed,
                quality_scope_reason=quality_scope_reason,
            )
        except (ValueError, RuntimeError, OSError, UnicodeDecodeError) as exc:
            st.error(str(exc))
        else:
            st.session_state["export_notice"] = "Configuración de exportación guardada"
            _request_profile_view_rebuild(st, selected_id=saved_id)

    if selected is not None:
        _render_profile_dependencies(st, profile_id=selected.id, runs=runs)
        st.divider()
        confirm_key = f"export_confirm_archive_{selected.id}"
        with st.form(
            f"export_archive_profile_{selected.id}",
            enter_to_submit=False,
        ):
            st.checkbox(
                "Confirmo que deseo archivar esta configuración de exportación",
                key=confirm_key,
            )
            st.form_submit_button(
                "Archivar esta configuración de exportación",
                on_click=_queue_profile_lifecycle_action,
                args=(st,),
                kwargs={
                    "action": "archive",
                    "profile_id": selected.id,
                    "confirm_key": confirm_key,
                },
            )



def _render_profile_dependencies(st, *, profile_id: str, runs) -> None:
    dependent = [row for row in runs if row.profile_id == profile_id]
    st.caption(
        f"Archivos exportados anteriormente con esta configuración: {len(dependent)}"
    )
    if dependent:
        with st.expander("Ver archivos exportados con esta configuración"):
            for row in dependent:
                st.write(
                    f"**{row.output_format.upper()}** · {row.row_count} registros · "
                    f"{row.created_at}"
                )
                st.code(row.output_relative_path)


def _render_archived_profile(
    st,
    *,
    selected,
    runs,
    db_path,
    project_id: str,
    actor: str,
) -> None:
    st.warning(
        "Esta configuración de exportación está archivada. No puede editarse ni usarse para crear nuevos archivos hasta que la restaures."
    )
    st.caption(
        f"Archivado por {selected.archived_by or '-'} · "
        f"{selected.archived_at or '-'} · revisión {selected.revision}"
    )
    _render_profile_dependencies(st, profile_id=selected.id, runs=runs)
    restore_confirm_key = f"export_confirm_restore_{selected.id}"
    with st.form(
        f"export_restore_profile_{selected.id}",
        enter_to_submit=False,
    ):
        st.checkbox(
            "Confirmo que deseo restaurar esta configuración de exportación",
            key=restore_confirm_key,
        )
        st.form_submit_button(
            "Restaurar esta configuración de exportación",
            on_click=_queue_profile_lifecycle_action,
            args=(st,),
            kwargs={
                "action": "restore",
                "profile_id": selected.id,
                "confirm_key": restore_confirm_key,
            },
        )

    st.divider()
    st.caption(
        "Eliminar esta configuración no borra los archivos exportados anteriormente: cada exportación conserva el nombre de la configuración, sus opciones y la huella registrada."
    )
    delete_confirm_key = f"export_confirm_delete_{selected.id}"
    with st.form(
        f"export_delete_profile_{selected.id}",
        enter_to_submit=False,
    ):
        st.checkbox(
            "Confirmo la eliminación definitiva de esta configuración archivada",
            key=delete_confirm_key,
        )
        st.form_submit_button(
            "Eliminar definitivamente esta configuración de exportación",
            on_click=_queue_profile_lifecycle_action,
            args=(st,),
            kwargs={
                "action": "delete",
                "profile_id": selected.id,
                "confirm_key": delete_confirm_key,
            },
        )


def _render_audiovisual_export_view(
    st,
    *,
    project_root,
    db_path,
    project_id: str,
    actor: str,
) -> None:
    _render_export_result(st, project_root=project_root)
    engine = create_sqlite_engine(db_path)
    try:
        with session_scope(engine) as session:
            media_rows = audiovisual_media_rows(
                session, project_root=project_root, project_id=project_id
            )
            all_runs = export_run_rows(session, project_id=project_id)
    finally:
        engine.dispose()
    audiovisual_runs = [
        row
        for row in all_runs
        if row.profile_snapshot.get("material_type") == "audiovisual_transcript_segments"
    ]
    media_by_id = {row.media_id: row for row in media_rows}
    media_options = list(media_by_id)

    configure_tab, preview_tab, run_tab, history_tab = tracked_tabs(
        st,
        [
            "Configurar qué exportar",
            "Revisar textos que se exportarán",
            "Crear archivo de exportación",
            "Historial de exportaciones",
        ],
        key="export_audiovisual_tabs",
        help_by_label=TAB_HELP["export_tabs"],
    )

    with configure_tab:
        if not media_rows:
            st.info("Todavía no hay audios o videos con transcripciones disponibles para exportar.")
        selected_media = st.multiselect(
            "Audios y videos cuyas transcripciones querés exportar",
            options=media_options,
            default=media_options,
            format_func=lambda value: (
                media_by_id[value].title
                or media_by_id[value].original_filename
                or media_by_id[value].source_key
            ),
            key="export_av_media_ids",
        )
        run_scope = st.selectbox(
            "Qué versiones de las transcripciones querés incluir",
            options=list(_AUDIOVISUAL_RUN_SCOPE_LABELS),
            format_func=lambda value: _AUDIOVISUAL_RUN_SCOPE_LABELS[value],
            key="export_av_run_scope",
        )
        text_policy = st.selectbox(
            "Qué versión del texto de cada segmento querés exportar",
            options=list(_AUDIOVISUAL_TEXT_POLICY_LABELS),
            format_func=lambda value: _AUDIOVISUAL_TEXT_POLICY_LABELS[value],
            key="export_av_text_policy",
        )
        include_statuses = st.multiselect(
            "Estado de revisión de los segmentos que querés incluir",
            options=list(_AUDIOVISUAL_REVIEW_LABELS),
            default=list(_AUDIOVISUAL_REVIEW_LABELS),
            format_func=lambda value: _AUDIOVISUAL_REVIEW_LABELS[value],
            key="export_av_review_statuses",
        )
        include_annotations = st.checkbox(
            "Incluir marcas temporales de hablantes y anotaciones",
            value=True,
            key="export_av_include_annotations",
        )

    options = AudiovisualExportOptions(
        text_policy=text_policy,
        include_review_statuses=tuple(include_statuses),
        run_scope=run_scope,
        media_ids=tuple(selected_media),
        include_timeline_annotations=include_annotations,
    )

    with preview_tab:
        preview = None
        try:
            engine = create_sqlite_engine(db_path)
            try:
                with session_scope(engine) as session:
                    preview = preview_transcript_export(
                        session, project_id=project_id, options=options, limit=20
                    )
            finally:
                engine.dispose()
        except (ValueError, RuntimeError, OSError) as exc:
            st.warning(str(exc))
        if preview is not None:
            cols = st.columns(2)
            cols[0].metric("Segmentos de transcripción que se exportarán", preview.total_records)
            cols[1].metric("Caracteres de transcripción que se exportarán", preview.total_characters)
            if not preview.records:
                st.warning("La configuración actual no incluye ningún segmento de transcripción.")
            for row in preview.records:
                with st.container(border=True):
                    title = row.get("media_title") or row.get("original_filename") or row.get("source_key")
                    st.write(f"**{title}**")
                    st.caption(
                        f"{row['start_time']:.3f}–{row['end_time']:.3f} s · "
                        f"{_AUDIOVISUAL_REVIEW_LABELS.get(str(row['review_status']), row['review_status'])} · "
                        f"{row['text_source']}"
                    )
                    text = str(row.get("text") or "")
                    st.text(text[:3000] + ("…" if len(text) > 3000 else ""))
                    with st.expander("Detalles técnicos del segmento", expanded=False):
                        st.code(str(row["segment_id"]), language=None)

    with run_tab:
        av_format = st.selectbox(
            "Qué archivo querés crear",
            options=("jsonl", "csv"),
            format_func=lambda value: _OUTPUT_FORMAT_LABELS[value],
            key="export_av_run_format",
        )
        suggested = default_audiovisual_export_filename(av_format)
        output_relative = st.text_input(
            "Nombre o ruta del archivo dentro del proyecto",
            value=suggested,
            help="Se guarda dentro de la carpeta del proyecto, normalmente en exports/.",
            key=f"export_av_run_path_{av_format}",
        )
        if st.button(
            "Crear archivo con las transcripciones seleccionadas",
            type="primary",
            key="export_av_create_file",
        ):
            try:
                engine = create_sqlite_engine(db_path)
                try:
                    with session_scope(engine) as session:
                        result = run_audiovisual_export(
                            session,
                            project_root=project_root,
                            project_id=project_id,
                            options=options,
                            output_relative_path=output_relative,
                            output_format=av_format,
                            created_by=actor or "local_user",
                        )
                finally:
                    engine.dispose()
            except (ValueError, RuntimeError, OSError) as exc:
                st.error(str(exc))
            else:
                st.session_state["export_last_run"] = {
                    "run_id": result.run_id,
                    "relative_path": str(result.output_path.relative_to(project_root)),
                    "format": av_format,
                    "row_count": result.row_count,
                    "character_count": result.character_count,
                    "byte_size": result.byte_size,
                    "sha256": result.output_sha256,
                }
                rerun_view(st)

    with history_tab:
        if not audiovisual_runs:
            st.info("Todavía no se creó ningún archivo de transcripciones para este proyecto.")
        for row in audiovisual_runs:
            with st.container(border=True):
                st.write(
                    f"**Transcripciones de audio y video** · "
                    f"{_OUTPUT_FORMAT_LABELS.get(row.output_format, row.output_format.upper())}"
                )
                st.caption(
                    f"{Path(row.output_relative_path).name} · "
                    f"{row.row_count} segmentos · {row.character_count} caracteres · "
                    f"{row.created_by} · {row.created_at}"
                )
                with st.expander("Detalles técnicos de la exportación", expanded=False):
                    options_snapshot = dict(row.profile_snapshot.get("options") or {})
                    st.write(f"Ruta dentro del proyecto: `{row.output_relative_path}`")
                    st.write(f"Tamaño del archivo: {row.byte_size} bytes")
                    st.write(f"Política de texto: `{options_snapshot.get('text_policy', '-')}`")
                    st.write(f"Alcance de transcripciones: `{options_snapshot.get('run_scope', '-')}`")
                    st.write(f"Huella del archivo: `{row.output_sha256}`")
                    st.write(f"Huella del estado del corpus: `{row.corpus_state_sha256}`")


def render_export_view(
    st,
    *,
    project_root,
    db_path,
    project_id: str,
    actor: str,
    object_types: list[str],
    object_type_labels: dict[str, str],
) -> None:
    _process_pending_profile_lifecycle(
        st,
        db_path=db_path,
        project_id=project_id,
        actor=actor,
    )
    section_heading(st, "Exportar corpus")
    export_surface = st.radio(
        "Tipo de material que querés exportar",
        options=("documentos", "audiovisual"),
        format_func=lambda value: (
            "Documentos revisados" if value == "documentos" else "Segmentos de audio y video"
        ),
        horizontal=True,
        key="export_surface",
    )
    export_surface_label = (
        "Documentos revisados" if export_surface == "documentos" else "Segmentos de audio y video"
    )
    mount_choice_help(
        st,
        key="export_surface",
        label=export_surface_label,
        help_text=TASK_HELP["export_surface"][export_surface_label],
    )
    if export_surface == "audiovisual":
        _render_audiovisual_export_view(
            st,
            project_root=project_root,
            db_path=db_path,
            project_id=project_id,
            actor=actor,
        )
        return

    notice = st.session_state.pop("export_notice", None)
    if notice:
        st.success(str(notice))
    _render_export_result(st, project_root=project_root)

    profile_col, archived_col = st.columns([4, 1.3])
    with archived_col:
        show_archived = st.checkbox(
            "Archivadas",
            value=False,
            key="export_show_archived",
            help="Mostrar también configuraciones de exportación archivadas.",
        )
    engine = create_sqlite_engine(db_path)
    try:
        with session_scope(engine) as session:
            profiles = export_profile_rows(
                session,
                project_id=project_id,
                include_archived=show_archived,
            )
            runs = [
                row
                for row in export_run_rows(session, project_id=project_id)
                if row.profile_snapshot.get("material_type") != "audiovisual_transcript_segments"
            ]
    finally:
        engine.dispose()

    options = [None] + [row.id for row in profiles]
    profile_by_id = {row.id: row for row in profiles}
    current_selection = st.session_state.get(_EXPORT_SELECTION_KEY)
    if current_selection not in options:
        current_selection = None
        st.session_state[_EXPORT_SELECTION_KEY] = None

    selector_epoch = int(st.session_state.get(_EXPORT_SELECTOR_EPOCH_KEY, 0))
    with profile_col:
        selected_id = st.selectbox(
            "Configuración de exportación",
            options=options,
            index=options.index(current_selection),
            format_func=lambda value: (
                "Crear una configuración de exportación nueva"
                if value is None
                else (
                    f"[Archivado] {profile_by_id[value].name}"
                    if profile_by_id[value].lifecycle_status == "archived"
                    else profile_by_id[value].name
                )
            ),
            key=f"export_profile_selector_{selector_epoch}",
            label_visibility="collapsed",
        )
    st.session_state[_EXPORT_SELECTION_KEY] = selected_id
    selected = profile_by_id.get(selected_id)

    configure_tab, preview_tab, run_tab, history_tab = tracked_tabs(
        st,
        ["Configurar qué exportar", "Revisar textos que se exportarán", "Crear archivo de exportación", "Historial de exportaciones"],
        key="export_tabs",
        help_by_label=TAB_HELP["export_tabs"],
    )
    with configure_tab:
        if selected is not None and selected.lifecycle_status == "archived":
            _render_archived_profile(
                st,
                selected=selected,
                db_path=db_path,
                project_id=project_id,
                actor=actor,
                runs=runs,
            )
        else:
            _render_profile_editor(
                st,
                selected=selected,
                db_path=db_path,
                project_id=project_id,
                actor=actor,
                object_types=object_types,
                object_type_labels=object_type_labels,
                runs=runs,
            )

    with preview_tab:
        if selected is None:
            st.info("Guardá o seleccioná una configuración de exportación para ver una muestra de los textos que incluirá.")
        elif selected.lifecycle_status == "archived":
            st.info("Restaurá esta configuración de exportación para volver a generar una muestra de textos.")
        else:
            preview = None
            engine = create_sqlite_engine(db_path)
            try:
                with session_scope(engine) as session:
                    profile = session.get(type(selected), selected.id)
                    if profile is None:
                        raise ValueError("La configuración de exportación ya no existe")
                    preview = preview_export(
                        session,
                        project_id=project_id,
                        profile=profile,
                        limit=20,
                    )
            except (ValueError, RuntimeError, OSError) as exc:
                st.warning(str(exc))
            finally:
                engine.dispose()
            if preview is None:
                st.info(
                    "La muestra de textos quedará disponible después de guardar la configuración de exportación con los estados de revisión elegidos."
                )
            else:
                cols = st.columns(2)
                cols[0].metric("Bloques de texto que se exportarán", preview.total_records)
                cols[1].metric("Caracteres de texto que se exportarán", preview.total_characters)
                if selected.temporal_start or selected.temporal_end:
                    st.caption(
                        "Filtro temporal: "
                        f"{selected.temporal_start.isoformat() if selected.temporal_start else 'sin inicio'} → "
                        f"{selected.temporal_end.isoformat() if selected.temporal_end else 'sin final'}"
                    )
                if not preview.records:
                    st.warning("La configuración de exportación actual no incluye ningún texto.")
                for row in preview.records:
                    with st.container(border=True):
                        st.write(f"**{row.titulo}**")
                        st.caption(
                            f"{row.aggregation_level} · páginas {row.page_start}–{row.page_end} · "
                            f"{row.object_count} bloques de texto"
                        )
                        st.text(row.texto[:3000] + ("…" if len(row.texto) > 3000 else ""))
                        with st.expander("Detalles técnicos del registro", expanded=False):
                            st.code(row.record_id, language=None)

    with run_tab:
        if selected is None:
            st.info("Seleccioná una configuración de exportación guardada.")
        elif selected.lifecycle_status == "archived":
            st.info("Restaurá esta configuración de exportación antes de crear un archivo nuevo.")
        else:
            format_value = st.selectbox(
                "Qué archivo querés crear",
                options=list(RUN_OUTPUT_FORMATS),
                index=list(RUN_OUTPUT_FORMATS).index(selected.output_format),
                format_func=lambda value: _OUTPUT_FORMAT_LABELS.get(value, value.upper()),
                key="export_run_format",
            )
            visual_options = None
            if format_value == "visual_zip":
                st.caption(
                    "El ZIP reúne el texto exportado con las imágenes relacionadas y un manifiesto "
                    "que conserva su origen, relaciones y huellas de verificación."
                )
                customize_visual = st.toggle(
                    "Elegir qué imágenes incluir",
                    value=False,
                    key=f"export_visual_customize_{selected.id}",
                    help="Si lo dejás desactivado se incluyen páginas, recortes regionales y figuras.",
                )
                include_pages = True
                include_regions = True
                include_figures = True
                if customize_visual:
                    st.write("**Imágenes incluidas**")
                    include_pages = st.checkbox(
                        "Incluir imágenes de páginas completas",
                        value=True,
                        key=f"export_visual_pages_{selected.id}",
                    )
                    include_regions = st.checkbox(
                        "Recortes de zonas trabajadas por separado",
                        value=True,
                        key=f"export_visual_regions_{selected.id}",
                    )
                    include_figures = st.checkbox(
                        "Incluir imágenes de figuras",
                        value=True,
                        key=f"export_visual_figures_{selected.id}",
                    )
                visual_options = VisualExportOptions(
                    include_pages=include_pages,
                    include_regions=include_regions,
                    include_figures=include_figures,
                    include_context=True,
                )
                st.caption(
                    "También puede incluirse como contexto el texto de otros bloques de las páginas y documentos seleccionados. Ese texto se identifica por separado para no confundirlo con el contenido principal exportado."
                )
            suggested = default_export_filename(selected.name, format_value)
            output_relative = st.text_input(
                "Nombre o ruta del archivo dentro del proyecto",
                value=suggested,
                help="Se guarda dentro de la carpeta del proyecto. Podés usar una subcarpeta, por ejemplo exports/corpus.jsonl.",
                key=f"export_run_path_{selected.id}_{format_value}",
            )
            if st.button("Crear archivo con los textos seleccionados", type="primary"):
                try:
                    engine = create_sqlite_engine(db_path)
                    try:
                        with session_scope(engine) as session:
                            profile = session.get(type(selected), selected.id)
                            if profile is None:
                                raise ValueError("La configuración de exportación ya no existe")
                            if profile.lifecycle_status != "active":
                                raise ValueError("La configuración de exportación está archivada")
                            result = run_export(
                                session,
                                project_root=project_root,
                                project_id=project_id,
                                profile=profile,
                                output_relative_path=output_relative,
                                output_format=format_value,
                                created_by=actor or "local_user",
                                visual_options=visual_options,
                            )
                    finally:
                        engine.dispose()
                except (ValueError, RuntimeError, OSError) as exc:
                    st.error(str(exc))
                else:
                    st.session_state["export_last_run"] = {
                        "run_id": result.run_id,
                        "relative_path": str(result.output_path.relative_to(project_root)),
                        "format": format_value,
                        "row_count": result.row_count,
                        "character_count": result.character_count,
                        "byte_size": result.byte_size,
                        "sha256": result.output_sha256,
                        "page_image_count": result.page_image_count,
                        "region_image_count": result.region_image_count,
                        "figure_image_count": result.figure_image_count,
                        "context_object_count": result.context_object_count,
                    }
                    rerun_view(st)

    with history_tab:
        if not runs:
            st.info("Todavía no se creó ningún archivo de exportación para este proyecto.")
        for row in runs:
            with st.container(border=True):
                st.write(
                    f"**{row.profile_name}** · "
                    f"{_OUTPUT_FORMAT_LABELS.get(row.output_format, row.output_format.upper())}"
                )
                st.caption(
                    f"{Path(row.output_relative_path).name} · "
                    f"{row.row_count} registros · {row.character_count} caracteres · "
                    f"{row.created_by} · {row.created_at}"
                )
                with st.expander("Detalles técnicos de la exportación", expanded=False):
                    st.write(f"Ruta dentro del proyecto: `{row.output_relative_path}`")
                    st.write(f"Tamaño del archivo: {row.byte_size} bytes")
                    st.write(f"Huella del archivo: `{row.output_sha256}`")
                    st.write(f"Huella del estado del corpus: `{row.corpus_state_sha256}`")
