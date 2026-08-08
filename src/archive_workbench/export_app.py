from __future__ import annotations

from datetime import date

from archive_workbench.audiovisual import export_transcript_segments_bytes
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
from archive_workbench.ui_navigation import rerun_view, tracked_tabs
from archive_workbench.visual_export import VisualExportOptions

_AGGREGATION_LABELS = {
    "object": "Un registro por objeto textual",
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
            f"Marcá la confirmación antes de {verb} el perfil."
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
        st.error("No se pudo identificar el perfil solicitado.")
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
            notice = f"Perfil archivado: {name}"
            selected_id: str | None = None
        elif action == "restore":
            name = _set_profile_archived_action(
                db_path,
                project_id=project_id,
                profile_id=profile_id,
                archived=False,
                actor=actor,
            )
            notice = f"Perfil restaurado: {name}"
            selected_id = profile_id
        elif action == "delete":
            name = _delete_profile_action(
                db_path,
                project_id=project_id,
                profile_id=profile_id,
            )
            notice = (
                f"Perfil eliminado: {name}. "
                "Las exportaciones históricas se conservaron."
            )
            selected_id = None
        else:
            st.error("La acción solicitada sobre el perfil no es válida.")
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
                f"El ZIP conserva {result['context_object_count']} objetos textuales de contexto "
                "para las páginas y documentos incluidos."
            )
    else:
        st.success(
            "Exportación creada correctamente: "
            f"{result['row_count']} registros, {result['character_count']} caracteres, "
            f"formato {str(result['format']).upper()}."
        )
    st.code(str(result["relative_path"]))
    st.caption(f"SHA-256: `{result['sha256']}` · {result['byte_size']} bytes")

    output_path = project_root / str(result["relative_path"])
    download_col, dismiss_col = st.columns(2)
    if output_path.is_file():
        download_col.download_button(
            "Descargar archivo",
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
    form_key = f"corpus_export_profile_form_{selected.id if selected else 'new'}"
    with st.form(form_key, enter_to_submit=False):
        name = st.text_input("Nombre del perfil", value=selected.name if selected else "")
        description = st.text_area(
            "Descripción opcional",
            value=selected.description or "" if selected else "",
        )
        left, right = st.columns(2)
        with left:
            aggregation = st.selectbox(
                "Agrupar",
                options=list(AGGREGATION_LEVELS),
                index=(
                    list(AGGREGATION_LEVELS).index(selected.aggregation_level)
                    if selected
                    else 3
                ),
                format_func=lambda value: _AGGREGATION_LABELS[value],
            )
            text_policy = st.selectbox(
                "Texto",
                options=list(TEXT_POLICIES),
                index=(
                    list(TEXT_POLICIES).index(selected.text_policy) if selected else 0
                ),
                format_func=lambda value: _TEXT_POLICY_LABELS[value],
            )
            output_format = st.selectbox(
                "Formato predeterminado",
                options=list(OUTPUT_FORMATS),
                index=(
                    list(OUTPUT_FORMATS).index(selected.output_format) if selected else 0
                ),
                format_func=lambda value: _OUTPUT_FORMAT_LABELS.get(value, value.upper()),
            )
        with right:
            include_types = st.multiselect(
                "Tipos de objeto; vacío = todos",
                options=object_types,
                default=[value for value in default_types if value in object_types],
                format_func=lambda value: object_type_labels.get(value, value),
            )
            include_statuses = st.multiselect(
                "Estado de revisión del objeto; vacío = todos",
                options=list(REVIEW_STATUSES),
                default=default_object_statuses,
                format_func=lambda value: _REVIEW_LABELS[value],
            )
            include_page_statuses = st.multiselect(
                "Estado de revisión de la página; vacío = todos",
                options=list(REVIEW_STATUSES),
                default=default_page_statuses,
                format_func=lambda value: _REVIEW_LABELS[value],
                help=(
                    "El alcance seguro usa solamente páginas aprobadas. Vacío incluye "
                    "todos los estados y requiere confirmación explícita al guardar."
                ),
            )
        broader_quality_scope_confirmed = st.checkbox(
            "Confirmo que deseo incluir páginas no aprobadas en este análisis automático",
            value=False,
            help=(
                "Solo es necesaria cuando el alcance de páginas no es exactamente "
                "Aprobada. La comprobación se realiza al guardar, no deshabilitando "
                "el botón dentro del formulario."
            ),
        )
        quality_scope_reason = st.text_area(
            "Fundamento del alcance ampliado",
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
        with st.expander("Filtro temporal de entidades y relaciones"):
            temporal_enabled = st.checkbox(
                "Filtrar registros por temporalidad vinculada",
                value=default_temporal_enabled,
                help=(
                    "Incluye objetos que mencionan una entidad o participan en una relación "
                    "cuyo período se superpone con el rango indicado."
                ),
            )
            temporal_cols = st.columns(2)
            temporal_start = temporal_cols[0].date_input(
                "Desde",
                value=(
                    selected.temporal_start
                    if selected and selected.temporal_start
                    else date.today()
                ),
                key=f"export_temporal_start_{selected.id if selected else 'new'}",
            )
            temporal_end = temporal_cols[1].date_input(
                "Hasta",
                value=(
                    selected.temporal_end
                    if selected and selected.temporal_end
                    else date.today()
                ),
                key=f"export_temporal_end_{selected.id if selected else 'new'}",
            )
            temporal_include_undated = st.checkbox(
                "Incluir registros vinculados solo con entidades o relaciones sin fecha",
                value=bool(selected.temporal_include_undated) if selected else False,
            )
        with st.expander("Separadores y marcas"):
            object_separator = st.text_input(
                "Separador entre objetos de una misma página",
                value=selected.object_separator if selected else "\n\n",
            )
            page_separator = st.text_input(
                "Separador entre páginas",
                value=selected.page_separator if selected else "\n\n",
            )
            include_page_markers = st.checkbox(
                "Agregar marcas [Página N]",
                value=bool(selected.include_page_markers) if selected else False,
            )
        submitted = st.form_submit_button("Guardar perfil", type="primary")

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
            st.session_state["export_notice"] = "Perfil guardado"
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
                "Confirmo que deseo archivar este perfil",
                key=confirm_key,
            )
            st.form_submit_button(
                "Archivar perfil",
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
        f"Exportaciones históricas vinculadas a este perfil: {len(dependent)}"
    )
    if dependent:
        with st.expander("Ver exportaciones vinculadas"):
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
        "Este perfil está archivado. No puede editarse ni ejecutar nuevas exportaciones "
        "hasta restaurarlo."
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
            "Confirmo que deseo restaurar este perfil",
            key=restore_confirm_key,
        )
        st.form_submit_button(
            "Restaurar perfil",
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
        "Eliminar el perfil no borra las exportaciones históricas: cada ejecución "
        "conserva el nombre, la configuración completa y los hashes registrados."
    )
    delete_confirm_key = f"export_confirm_delete_{selected.id}"
    with st.form(
        f"export_delete_profile_{selected.id}",
        enter_to_submit=False,
    ):
        st.checkbox(
            "Confirmo la eliminación definitiva de este perfil archivado",
            key=delete_confirm_key,
        )
        st.form_submit_button(
            "Eliminar perfil definitivamente",
            on_click=_queue_profile_lifecycle_action,
            args=(st,),
            kwargs={
                "action": "delete",
                "profile_id": selected.id,
                "confirm_key": delete_confirm_key,
            },
        )


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
    st.header("Exportar corpus")
    export_surface = st.radio(
        "Contenido",
        options=("documentos", "audiovisual"),
        format_func=lambda value: (
            "Documentos revisados" if value == "documentos" else "Segmentos de audio y video"
        ),
        horizontal=True,
        key="export_surface",
    )
    if export_surface == "audiovisual":
        st.caption(
            "Exportá la transcripción segmentada vigente con tiempos, revisión, backend e identidad verificable del original."
        )
        av_format = st.selectbox(
            "Formato",
            options=("jsonl", "csv"),
            format_func=lambda value: _OUTPUT_FORMAT_LABELS[value],
            key="export_av_format",
        )
        av_engine = create_sqlite_engine(db_path)
        try:
            with session_scope(av_engine) as session:
                av_payload, av_rows = export_transcript_segments_bytes(
                    session, project_id=project_id, output_format=av_format
                )
        finally:
            av_engine.dispose()
        st.metric("Segmentos", av_rows)
        st.download_button(
            "Descargar segmentos audiovisuales",
            data=av_payload,
            file_name=f"transcripciones_audiovisuales.{av_format}",
            mime="application/x-ndjson" if av_format == "jsonl" else "text/csv",
            type="primary",
            key=f"export_av_download_{av_format}",
        )
        with st.expander("Campos incluidos", expanded=False):
            st.write(
                "Cada fila conserva source_key, objeto digital, nombre y SHA-256 del original, "
                "corrida/backend/modelo/dispositivo, segmento, tiempos, texto, estado y revisión."
            )
        return
    st.caption(
        "Los perfiles definen qué contenido entra, cómo se agrupa y qué tipo de archivo se crea. "
        "Cada exportación conserva la configuración exacta y la huella verificable del corpus."
    )
    with st.expander("Cómo preparar una exportación", expanded=False):
        st.write(
            "Primero configurá y guardá un perfil. Después revisá una muestra del contenido y, "
            "cuando sea correcto, creá el archivo. El historial conserva las exportaciones "
            "anteriores aunque el perfil se archive o se elimine."
        )

    notice = st.session_state.pop("export_notice", None)
    if notice:
        st.success(str(notice))
    _render_export_result(st, project_root=project_root)

    show_archived = st.checkbox(
        "Mostrar perfiles archivados",
        value=False,
        key="export_show_archived",
    )
    engine = create_sqlite_engine(db_path)
    try:
        with session_scope(engine) as session:
            profiles = export_profile_rows(
                session,
                project_id=project_id,
                include_archived=show_archived,
            )
            runs = export_run_rows(session, project_id=project_id)
    finally:
        engine.dispose()

    options = [None] + [row.id for row in profiles]
    profile_by_id = {row.id: row for row in profiles}
    current_selection = st.session_state.get(_EXPORT_SELECTION_KEY)
    if current_selection not in options:
        current_selection = None
        st.session_state[_EXPORT_SELECTION_KEY] = None

    selector_epoch = int(st.session_state.get(_EXPORT_SELECTOR_EPOCH_KEY, 0))
    selected_id = st.selectbox(
        "Perfil de exportación",
        options=options,
        index=options.index(current_selection),
        format_func=lambda value: (
            "Crear un perfil nuevo"
            if value is None
            else (
                f"[Archivado] {profile_by_id[value].name}"
                if profile_by_id[value].lifecycle_status == "archived"
                else profile_by_id[value].name
            )
        ),
        key=f"export_profile_selector_{selector_epoch}",
    )
    st.session_state[_EXPORT_SELECTION_KEY] = selected_id
    selected = profile_by_id.get(selected_id)

    configure_tab, preview_tab, run_tab, history_tab = tracked_tabs(
        st,
        ["Configurar perfil", "Revisar contenido", "Crear archivo", "Historial"],
        key="export_tabs",
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
            st.info("Guardá o seleccioná un perfil para generar la vista previa.")
        elif selected.lifecycle_status == "archived":
            st.info("Restaurá el perfil para generar una vista previa.")
        else:
            preview = None
            engine = create_sqlite_engine(db_path)
            try:
                with session_scope(engine) as session:
                    profile = session.get(type(selected), selected.id)
                    if profile is None:
                        raise ValueError("El perfil ya no existe")
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
                    "La vista previa quedará disponible después de guardar el perfil "
                    "con la política de calidad vigente."
                )
            else:
                cols = st.columns(2)
                cols[0].metric("Registros", preview.total_records)
                cols[1].metric("Caracteres", preview.total_characters)
                if selected.temporal_start or selected.temporal_end:
                    st.caption(
                        "Filtro temporal: "
                        f"{selected.temporal_start.isoformat() if selected.temporal_start else 'sin inicio'} → "
                        f"{selected.temporal_end.isoformat() if selected.temporal_end else 'sin final'}"
                    )
                if not preview.records:
                    st.warning("El perfil no selecciona ningún texto.")
                for row in preview.records:
                    with st.container(border=True):
                        st.write(f"**{row.titulo}**")
                        st.caption(
                            f"{row.aggregation_level} · páginas {row.page_start}–{row.page_end} · "
                            f"{row.object_count} objetos"
                        )
                        st.text(row.texto[:3000] + ("…" if len(row.texto) > 3000 else ""))
                        with st.expander("Detalles técnicos del registro", expanded=False):
                            st.code(row.record_id, language=None)

    with run_tab:
        if selected is None:
            st.info("Seleccioná un perfil guardado.")
        elif selected.lifecycle_status == "archived":
            st.info("Restaurá el perfil antes de crear una nueva exportación.")
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
                        "Páginas completas",
                        value=True,
                        key=f"export_visual_pages_{selected.id}",
                    )
                    include_regions = st.checkbox(
                        "Recortes regionales",
                        value=True,
                        key=f"export_visual_regions_{selected.id}",
                    )
                    include_figures = st.checkbox(
                        "Figuras",
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
                    "También se incluye, como contexto, el texto de otros objetos de las páginas y "
                    "documentos seleccionados. Ese texto queda separado del contenido principal."
                )
            suggested = default_export_filename(selected.name, format_value)
            output_relative = st.text_input(
                "Nombre o ruta del archivo dentro del proyecto",
                value=suggested,
                help="Se guarda dentro de project_data. Podés usar una subcarpeta, por ejemplo exports/corpus.jsonl.",
                key=f"export_run_path_{selected.id}_{format_value}",
            )
            if st.button("Crear exportación", type="primary"):
                try:
                    engine = create_sqlite_engine(db_path)
                    try:
                        with session_scope(engine) as session:
                            profile = session.get(type(selected), selected.id)
                            if profile is None:
                                raise ValueError("El perfil ya no existe")
                            if profile.lifecycle_status != "active":
                                raise ValueError("El perfil está archivado")
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
            st.info("Todavía no hay exportaciones registradas.")
        for row in runs:
            with st.container(border=True):
                st.write(
                    f"**{row.profile_name}** · "
                    f"{_OUTPUT_FORMAT_LABELS.get(row.output_format, row.output_format.upper())}"
                )
                st.code(row.output_relative_path)
                st.caption(
                    f"{row.row_count} registros · {row.character_count} caracteres · "
                    f"{row.byte_size} bytes · {row.created_by} · {row.created_at}"
                )
                with st.expander("Detalles técnicos de la exportación", expanded=False):
                    st.write(f"Huella del archivo: `{row.output_sha256}`")
                    st.write(f"Huella del estado del corpus: `{row.corpus_state_sha256}`")
