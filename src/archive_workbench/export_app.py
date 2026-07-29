from __future__ import annotations

from datetime import date

from archive_workbench.corpus_export import (
    AGGREGATION_LEVELS,
    OUTPUT_FORMATS,
    REVIEW_STATUSES,
    TEXT_POLICIES,
    ExportProfileValues,
    default_export_filename,
    export_profile_rows,
    export_run_rows,
    preview_export,
    run_export,
    save_export_profile,
)
from archive_workbench.db import create_sqlite_engine, session_scope

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


def _save_profile_action(
    db_path,
    *,
    project_id: str,
    profile_id: str | None,
    values: ExportProfileValues,
    actor: str,
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
            )
            return profile.id
    finally:
        engine.dispose()


def _decode_separator(value: str) -> str:
    return value.replace("\\r", "\r").replace("\\n", "\n").replace("\\t", "\t")


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
    st.header("Exportar corpus")
    st.caption(
        "Los perfiles definen qué texto entra, cómo se agrupa y en qué formato se escribe. "
        "Cada ejecución registra el perfil exacto y el hash del estado exportado."
    )
    engine = create_sqlite_engine(db_path)
    try:
        with session_scope(engine) as session:
            profiles = export_profile_rows(session, project_id=project_id)
            runs = export_run_rows(session, project_id=project_id)
    finally:
        engine.dispose()

    options = [None] + [row.id for row in profiles]
    profile_by_id = {row.id: row for row in profiles}
    pending_profile = st.session_state.pop("export_pending_profile_selection", None)
    if pending_profile in profile_by_id:
        st.session_state["export_profile_selection"] = pending_profile
    selected_id = st.selectbox(
        "Perfil",
        options=options,
        format_func=lambda value: "Crear un perfil nuevo" if value is None else profile_by_id[value].name,
        key="export_profile_selection",
    )
    selected = profile_by_id.get(selected_id)

    configure_tab, preview_tab, run_tab, history_tab = st.tabs(
        ["Configurar", "Vista previa", "Exportar", "Historial"]
    )
    with configure_tab:
        default_types = list(selected.include_object_types_json or []) if selected else []
        default_object_statuses = list(selected.include_review_statuses_json or []) if selected else []
        default_page_statuses = list(selected.include_page_review_statuses_json or []) if selected else []
        default_temporal_enabled = bool(selected and (selected.temporal_start or selected.temporal_end))
        with st.form("corpus_export_profile_form"):
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
                    index=list(AGGREGATION_LEVELS).index(selected.aggregation_level) if selected else 3,
                    format_func=lambda value: _AGGREGATION_LABELS[value],
                )
                text_policy = st.selectbox(
                    "Texto",
                    options=list(TEXT_POLICIES),
                    index=list(TEXT_POLICIES).index(selected.text_policy) if selected else 0,
                    format_func=lambda value: _TEXT_POLICY_LABELS[value],
                )
                output_format = st.selectbox(
                    "Formato predeterminado",
                    options=list(OUTPUT_FORMATS),
                    index=list(OUTPUT_FORMATS).index(selected.output_format) if selected else 0,
                    format_func=str.upper,
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
                    value=selected.temporal_start if selected and selected.temporal_start else date.today(),
                    key=f"export_temporal_start_{selected.id if selected else 'new'}",
                )
                temporal_end = temporal_cols[1].date_input(
                    "Hasta",
                    value=selected.temporal_end if selected and selected.temporal_end else date.today(),
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
                )
            except (ValueError, RuntimeError, OSError, UnicodeDecodeError) as exc:
                st.error(str(exc))
            else:
                st.session_state["export_pending_profile_selection"] = saved_id
                st.success("Perfil guardado")
                st.rerun()

    with preview_tab:
        if selected is None:
            st.info("Guardá o seleccioná un perfil para generar la vista previa.")
        else:
            engine = create_sqlite_engine(db_path)
            try:
                with session_scope(engine) as session:
                    preview = preview_export(
                        session,
                        project_id=project_id,
                        profile=session.get(type(selected), selected.id),
                        limit=20,
                    )
            finally:
                engine.dispose()
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
                        f"{row.object_count} objetos · `{row.record_id}`"
                    )
                    st.text(row.texto[:3000] + ("…" if len(row.texto) > 3000 else ""))

    with run_tab:
        if selected is None:
            st.info("Seleccioná un perfil guardado.")
        else:
            format_value = st.selectbox(
                "Formato de esta ejecución",
                options=list(OUTPUT_FORMATS),
                index=list(OUTPUT_FORMATS).index(selected.output_format),
                format_func=str.upper,
                key="export_run_format",
            )
            suggested = default_export_filename(selected.name, format_value)
            output_relative = st.text_input(
                "Ruta de salida relativa a project_data",
                value=suggested,
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
                            result = run_export(
                                session,
                                project_root=project_root,
                                project_id=project_id,
                                profile=profile,
                                output_relative_path=output_relative,
                                output_format=format_value,
                                created_by=actor or "local_user",
                            )
                    finally:
                        engine.dispose()
                except (ValueError, RuntimeError, OSError) as exc:
                    st.error(str(exc))
                else:
                    st.success(
                        f"Exportación creada: {result.row_count} registros, "
                        f"{result.character_count} caracteres"
                    )
                    st.code(str(result.output_path.relative_to(project_root)))
                    st.caption(f"SHA-256: `{result.output_sha256}`")
                    st.rerun()

    with history_tab:
        if not runs:
            st.info("Todavía no hay exportaciones registradas.")
        for row in runs:
            with st.container(border=True):
                st.write(f"**{row.profile_name}** · {row.output_format.upper()}")
                st.code(row.output_relative_path)
                st.caption(
                    f"{row.row_count} registros · {row.character_count} caracteres · "
                    f"{row.byte_size} bytes · {row.created_by} · {row.created_at}"
                )
                st.caption(
                    f"Archivo `{row.output_sha256}` · estado `{row.corpus_state_sha256}`"
                )
