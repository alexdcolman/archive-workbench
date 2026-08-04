from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from typing import Callable

from archive_workbench.ui_navigation import rerun_app, rerun_view, request_app_view, tracked_tabs

from archive_workbench.catalog import ensure_project, scan_file_instances
from archive_workbench.catalog_management import (
    REGISTRATION_STATUSES,
    RELATION_TYPES,
    archival_field_rows,
    archival_revision_rows,
    catalog_summary,
    catalog_unit_rows,
    create_archival_unit,
    digital_object_choices,
    link_existing_digital_object,
    move_archival_unit,
    remove_file_instance,
    register_local_file,
    register_uploaded_file,
    undo_last_archival_move,
    unlink_digital_object_from_unit,
    search_catalog_units,
    unit_digital_objects,
    update_archival_unit,
)
from archive_workbench.db import create_sqlite_engine, session_scope
from archive_workbench.db.models import ArchivalUnit

_STATUS_LABELS = {
    "incomplete": "Incompleto",
    "provisional": "Provisional",
    "complete": "Completo",
}
_FIELD_STATE_LABELS = {
    "provided": "Informado",
    "no_information": "Sin información",
    "not_applicable": "No corresponde",
    "pending": "Pendiente",
}
_RELATION_LABELS = {
    "represents": "Representa",
    "contains": "Contiene",
    "is_part_of": "Es parte de",
    "alternate_representation": "Representación alternativa",
}
_RELATION_HELP = {
    "represents": (
        "El objeto digital corresponde a esta unidad archivística completa. "
        "Es la opción habitual para un PDF o TIFF que digitaliza un documento o legajo entero."
    ),
    "contains": (
        "El objeto digital reúne esta unidad junto con otras. Se usa, por ejemplo, cuando un único PDF "
        "contiene varios documentos o legajos y esta unidad ocupa solo ciertas páginas."
    ),
    "is_part_of": (
        "El objeto digital representa solo una parte de esta unidad. Se usa cuando una unidad completa "
        "está distribuida en varios archivos digitales."
    ),
    "alternate_representation": (
        "Es otra representación del mismo contenido: una nueva digitalización, una versión corregida, "
        "un PDF derivado o una copia en otro formato, sin reemplazar la representación principal."
    ),
}
_PRESENCE_LABELS = {
    "present": "Disponible",
    "missing": "Ausente",
    "modified": "Modificado",
    "unverified": "Sin verificar",
}
_OPERATION_LABELS = {
    "baseline": "Estado inicial",
    "create": "Creación",
    "update": "Actualización descriptiva",
    "move": "Movimiento en la jerarquía",
    "undo_move": "Reversión de movimiento",
}


def _run_catalog_action(st, *, db_path: Path, callback: Callable, unit_id: str | None = None) -> None:
    engine = create_sqlite_engine(db_path)
    try:
        with session_scope(engine) as session:
            result = callback(session)
    except (ValueError, RuntimeError, OSError, FileNotFoundError) as exc:
        st.error(str(exc))
        return
    finally:
        engine.dispose()
    message = result
    target_unit_id = unit_id
    if isinstance(result, tuple) and len(result) == 2:
        message, target_unit_id = result
    if target_unit_id:
        st.session_state["catalog_pending_unit_id"] = str(target_unit_id)
    if message:
        st.session_state["catalog_flash"] = str(message)
    rerun_view(st)


def _unit_label(row, level_labels: dict[str, str]) -> str:
    indent = "　" * row.depth
    status = _STATUS_LABELS.get(row.registration_status, row.registration_status)
    files = f" · {row.digital_object_count} obj." if row.digital_object_count else ""
    return f"{indent}{level_labels.get(row.level_key, row.level_key)} · {row.title} · {status}{files}"


def _field_payload(existing_by_key: dict[str, list], field_def, values: str, state: str) -> dict:
    notes = [row.source_note for row in existing_by_key.get(field_def.key, []) if row.source_note]
    return {
        "state": state,
        "values": [line.strip() for line in values.splitlines() if line.strip()],
        "source_note": notes[0] if notes else None,
    }


def render_catalog_view(st, *, project_root: Path, db_path: Path, decisions, actor: str) -> None:
    st.header("Catálogo documental")
    st.caption(
        "Organizá la estructura documental, describí cada unidad y vinculá sus archivos sin "
        "alterar los originales."
    )
    flash = st.session_state.pop("catalog_flash", None)
    if flash:
        st.success(flash)

    engine = create_sqlite_engine(db_path)
    try:
        with session_scope(engine) as session:
            ensure_project(session, decisions)
            summary = catalog_summary(session, decisions.project_id)
            all_rows = catalog_unit_rows(session, decisions.project_id)
    finally:
        engine.dispose()

    with st.expander("Resumen del catálogo", expanded=not all_rows):
        metrics = st.columns(6)
        metrics[0].metric("Unidades", summary.units)
        metrics[1].metric("Incompletas", summary.incomplete_units)
        metrics[2].metric("Objetos digitales", summary.digital_objects)
        metrics[3].metric("Copias locales", summary.file_instances)
        metrics[4].metric("Disponibles", summary.present_files)
        metrics[5].metric("Ausentes", summary.missing_files)

    level_defs = sorted(
        [item for item in decisions.archival_levels if item.enabled],
        key=lambda item: item.display_order,
    )
    level_labels = {item.key: item.label for item in level_defs}
    level_map = {item.key: item for item in level_defs}

    root_levels = [item.key for item in level_defs if not item.parent_keys]
    with st.expander("Crear la primera unidad del catálogo", expanded=not all_rows):
        st.caption(
            "Este formulario crea una unidad en la raíz. Para agregar una Caja, Legajo o Documento "
            "dentro de otra unidad, primero seleccionala en el índice y usá ‘Agregar una unidad hija’."
        )
        if not root_levels:
            st.info("La configuración no habilita niveles en la raíz del catálogo.")
        else:
            with st.form("catalog_create_root_unit", enter_to_submit=False):
                level_key = st.selectbox(
                    "Nivel inicial",
                    options=root_levels,
                    format_func=lambda key: level_labels[key],
                )
                title = st.text_input("Título")
                reference_code = st.text_input("Código de referencia")
                note = st.text_input("Nota de creación", placeholder="Opcional")
                submit_create = st.form_submit_button("Crear en la raíz", type="primary")
            if submit_create:
                def callback(session):
                    unit = create_archival_unit(
                        session,
                        decisions=decisions,
                        project_id=decisions.project_id,
                        parent_id=None,
                        level_key=level_key,
                        title=title,
                        reference_code=reference_code,
                        created_by=actor or "local_user",
                        note=note,
                    )
                    return f"Unidad creada: {unit.title}", unit.id

                _run_catalog_action(st, db_path=db_path, callback=callback)

    query = st.text_input(
        "Buscar en el catálogo",
        placeholder="Título, código, descripción o nombre de archivo",
        key="catalog_query",
    )
    with st.expander("Filtros del catálogo", expanded=False):
        filter_cols = st.columns(2)
        with filter_cols[0]:
            level_filter = st.selectbox(
                "Nivel documental",
                options=[""] + [item.key for item in level_defs],
                format_func=lambda value: "Todos" if not value else level_labels[value],
                key="catalog_level_filter",
            )
        with filter_cols[1]:
            status_filter = st.selectbox(
                "Estado de descripción",
                options=[""] + list(REGISTRATION_STATUSES),
                format_func=lambda value: "Todos" if not value else _STATUS_LABELS[value],
                key="catalog_status_filter",
            )

    engine = create_sqlite_engine(db_path)
    try:
        with session_scope(engine) as session:
            visible_rows = search_catalog_units(
                session,
                project_id=decisions.project_id,
                query=query,
                level_key=level_filter or None,
                registration_status=status_filter or None,
            )
    finally:
        engine.dispose()

    if not visible_rows:
        st.info("No hay unidades que coincidan con los filtros.")
        return

    by_id = {row.id: row for row in all_rows}
    visible_by_id = {row.id: row for row in visible_rows}
    pending = st.session_state.pop("catalog_pending_unit_id", None)
    if pending in visible_by_id:
        st.session_state["catalog_selected_unit"] = pending
    selected_id = st.session_state.get("catalog_selected_unit")
    if selected_id not in visible_by_id:
        selected_id = visible_rows[0].id
        st.session_state["catalog_selected_unit"] = selected_id

    tree_col, detail_col = st.columns([0.85, 2.15], gap="large")
    with tree_col:
        st.subheader("Unidades del catálogo")
        selected_id = st.selectbox(
            "Unidad",
            options=[row.id for row in visible_rows],
            format_func=lambda value: _unit_label(visible_by_id[value], level_labels),
            key="catalog_selected_unit",
            label_visibility="collapsed",
        )
        selected_row = by_id[selected_id]
        st.caption(selected_row.path)
        if selected_row.reference_code:
            st.code(selected_row.reference_code)
        with st.expander("Datos de la unidad", expanded=False):
            st.write(
                f"Unidades hijas: **{selected_row.child_count}** · objetos digitales: "
                f"**{selected_row.digital_object_count}** · revisión interna: **{selected_row.revision}**"
            )
        child_levels = [
            item.key for item in level_defs if selected_row.level_key in item.parent_keys
        ]
        if child_levels:
            with st.expander(f"Agregar una unidad hija a {selected_row.title}", expanded=False):
                st.caption(
                    f"La nueva unidad quedará dentro de: {selected_row.path}. "
                    "Por ejemplo, al elegir Documento dentro de una Caja, el Documento aparecerá como hijo de esa Caja."
                )
                with st.form(f"catalog_create_child_{selected_row.id}", clear_on_submit=True, enter_to_submit=False):
                    child_level = st.selectbox(
                        "Nivel de la unidad hija",
                        options=child_levels,
                        format_func=lambda key: level_labels[key],
                    )
                    child_title = st.text_input("Título de la unidad hija")
                    child_reference = st.text_input("Código de referencia")
                    child_note = st.text_input("Nota de creación", placeholder="Opcional")
                    child_submit = st.form_submit_button("Crear dentro de esta unidad", type="primary")
                if child_submit:
                    def create_child_callback(session):
                        child = create_archival_unit(
                            session,
                            decisions=decisions,
                            project_id=decisions.project_id,
                            parent_id=selected_row.id,
                            level_key=child_level,
                            title=child_title,
                            reference_code=child_reference,
                            created_by=actor or "local_user",
                            note=child_note,
                        )
                        return f"Unidad hija creada: {child.title}", child.id

                    _run_catalog_action(st, db_path=db_path, callback=create_child_callback)
        else:
            st.caption("Este nivel no admite unidades hijas según la configuración del proyecto.")

    engine = create_sqlite_engine(db_path)
    try:
        with session_scope(engine) as session:
            unit = session.get(ArchivalUnit, selected_id)
            assert unit is not None
            fields = archival_field_rows(session, selected_id)
            digital_objects = unit_digital_objects(session, selected_id)
            revisions = archival_revision_rows(session, selected_id)
            object_choices = digital_object_choices(session, decisions.project_id)
    finally:
        engine.dispose()

    existing_by_key: dict[str, list] = defaultdict(list)
    for row in fields:
        existing_by_key[row.field_key].append(row)

    with detail_col:
        st.subheader(f"{level_labels.get(unit.level_key, unit.level_key)} · {unit.title}")
        description_tab, files_tab, structure_tab, history_tab = tracked_tabs(
            st,
            ["Descripción", "Objetos y archivos", "Estructura", "Historial"],
            key="catalog_detail_tabs",
        )

        with description_tab:
            applicable_fields = [
                item
                for item in decisions.descriptive_fields
                if item.enabled
                and item.key != "reference_code"
                and ("all" in item.applies_to_levels or unit.level_key in item.applies_to_levels)
            ]
            with st.form(f"catalog_description_{unit.id}", enter_to_submit=False):
                title = st.text_input("Título", value=unit.title)
                reference_code = st.text_input(
                    "Código de referencia", value=unit.reference_code or ""
                )
                registration_status = st.selectbox(
                    "Estado del registro",
                    options=list(REGISTRATION_STATUSES),
                    index=list(REGISTRATION_STATUSES).index(unit.registration_status),
                    format_func=lambda value: _STATUS_LABELS[value],
                )
                completion_confirmed = st.checkbox(
                    "Descripción completada y confirmada manualmente",
                    value=bool(unit.completion_confirmed),
                )
                st.divider()
                field_widgets: dict[str, tuple[str, str]] = {}
                for definition in applicable_fields:
                    rows = existing_by_key.get(definition.key, [])
                    current_state = rows[0].value_state if rows else "pending"
                    values = "\n".join(str(row.value) for row in rows if row.value is not None)
                    st.markdown(f"**{definition.label}**")
                    state_col, value_col = st.columns([1, 2.5])
                    with state_col:
                        state = st.selectbox(
                            "Estado",
                            options=list(decisions.catalog.field_value_states),
                            index=list(decisions.catalog.field_value_states).index(current_state),
                            format_func=lambda value: _FIELD_STATE_LABELS.get(value, value),
                            key=f"catalog_field_state_{unit.id}_{definition.key}",
                        )
                    with value_col:
                        value = st.text_area(
                            "Valor" + (" · uno por línea" if definition.repeatable else ""),
                            value=values,
                            height=72 if definition.repeatable else 68,
                            help="El valor solo se guarda cuando el estado es Informado.",
                            key=f"catalog_field_value_{unit.id}_{definition.key}",
                        )
                    field_widgets[definition.key] = (state, value)
                note = st.text_input("Nota sobre esta modificación", placeholder="Opcional")
                save_description = st.form_submit_button(
                    "Guardar descripción", type="primary"
                )
            if save_description:
                payload = {
                    definition.key: _field_payload(
                        existing_by_key,
                        definition,
                        field_widgets[definition.key][1],
                        field_widgets[definition.key][0],
                    )
                    for definition in applicable_fields
                }
                _run_catalog_action(
                    st,
                    db_path=db_path,
                    unit_id=unit.id,
                    callback=lambda session: (
                        update_archival_unit(
                            session,
                            decisions=decisions,
                            unit_id=unit.id,
                            changed_by=actor or "local_user",
                            title=title,
                            reference_code=reference_code,
                            registration_status=registration_status,
                            completion_confirmed=completion_confirmed,
                            field_values=payload,
                            note=note,
                        ),
                        "Descripción actualizada",
                    )[1],
                )

        with files_tab:
            scan_col, info_col = st.columns([1, 3])
            with scan_col:
                if st.button("Verificar archivos", use_container_width=True):
                    _run_catalog_action(
                        st,
                        db_path=db_path,
                        unit_id=unit.id,
                        callback=lambda session: (
                            lambda result: (
                                f"Archivos verificados: {result.checked}; disponibles {result.present}; "
                                f"ausentes {result.missing}; modificados {result.modified}"
                            )
                        )(scan_file_instances(session, project_root)),
                    )
            with info_col:
                st.caption(
                    "La verificación recalcula presencia e integridad. No reemplaza automáticamente "
                    "un objeto digital cuando el contenido del archivo cambió."
                )

            if not digital_objects:
                st.info("Esta unidad todavía no tiene objetos digitales asociados.")
            for item in digital_objects:
                with st.expander(
                    f"{item.original_filename} · {item.media_type} · {item.page_count or '?'} pág.",
                    expanded=len(digital_objects) == 1,
                ):
                    st.write(
                        f"**Relación:** {_RELATION_LABELS.get(item.relation_type, item.relation_type)} · "
                        f"**SHA-256:** `{item.sha256[:16]}…` · **tamaño:** {item.byte_size:,} bytes"
                    )
                    pcols = st.columns(4)
                    pcols[0].metric("Preprocesamiento", item.preprocessing_status)
                    pcols[1].metric("Extracción", item.extraction_status)
                    pcols[2].metric("Páginas seleccionadas", item.selected_pages)
                    pcols[3].metric(
                        "Revisión",
                        f"{item.reviewed_pages}/{item.editable_pages}",
                    )
                    if item.page_start or item.page_end:
                        st.caption(f"Páginas vinculadas: {item.page_start or '?'}–{item.page_end or '?'}")
                    if not item.files:
                        st.warning("El objeto digital no tiene una instancia local registrada.")
                    if item.source_key:
                        st.caption(f"Identificador para el procesamiento: `{item.source_key}`")
                    for local in item.files:
                        file_left, file_action = st.columns([5, 2])
                        file_left.write(
                            f"`{local.relative_path}` · "
                            f"**{_PRESENCE_LABELS.get(local.presence, local.presence)}**"
                        )
                        with file_action.popover("Retirar copia local"):
                            st.caption(
                                "Retirar el registro local no elimina el objeto digital ni su asociación archivística. "
                                "Borrar físicamente el archivo puede afectar otras unidades que reutilicen el mismo contenido."
                            )
                            delete_physical = st.checkbox(
                                "Borrar también el PDF/TIFF del disco",
                                key=f"catalog_delete_physical_{local.id}",
                            )
                            confirmation = st.text_input(
                                "Escribí ELIMINAR para confirmar" if delete_physical else "Escribí RETIRAR para confirmar",
                                key=f"catalog_remove_file_confirm_{local.id}",
                            )
                            expected = "ELIMINAR" if delete_physical else "RETIRAR"
                            if st.button(
                                "Confirmar",
                                disabled=confirmation.strip() != expected,
                                key=f"catalog_remove_file_{local.id}",
                            ):
                                def remove_file_callback(session, file_id=local.id, physical=delete_physical):
                                    result = remove_file_instance(
                                        session,
                                        project_root=project_root,
                                        file_instance_id=file_id,
                                        delete_physical=physical,
                                        removed_by=actor or "local_user",
                                    )
                                    action = "Archivo físico eliminado y copia local retirada" if result.physical_deleted else "Copia local retirada del catálogo"
                                    return f"{action}: {result.relative_path}"

                                _run_catalog_action(
                                    st, db_path=db_path, unit_id=unit.id, callback=remove_file_callback
                                )

                    st.divider()
                    st.write("**Qué hacer después**")
                    if not item.files:
                        st.info(
                            "Asociá una copia local antes de procesar. El registro archivístico y el objeto digital se conservan aunque el archivo no esté disponible."
                        )
                    elif item.preprocessing_status == "not_started":
                        st.write("1. Generar imágenes derivadas para OCR y vista previa:")
                        st.code(
                            f"archive-workbench prepare-derivatives project_data --source-key {item.source_key}",
                            language="bash",
                        )
                    elif item.extraction_status == "not_started":
                        st.write("2. Ejecutar o planificar la extracción OCR:")
                        st.code(
                            f"archive-workbench extract project_data --source-key {item.source_key} --created-by {actor or 'local_user'}",
                            language="bash",
                        )
                    elif item.editable_pages == 0:
                        st.write("3. Crear la capa editable desde la extracción seleccionada:")
                        st.code(
                            f"archive-workbench editor-bootstrap project_data --source-key {item.source_key} --created-by {actor or 'local_user'}",
                            language="bash",
                        )
                    else:
                        st.success(
                            f"El documento ya tiene {item.editable_pages} páginas en la capa de revisión. "
                            "Podés abrirlo desde Revisión o localizar su contenido desde Búsqueda."
                        )
                        if item.source_key and st.button(
                            "Abrir en Revisión", key=f"catalog_open_review_{item.link_id}"
                        ):
                            request_app_view(
                                st, mode="review", source_key=item.source_key, page=1
                            )
                            rerun_app(st)

                    with st.popover("Quitar asociación con esta unidad"):
                        st.warning(
                            f"Se quitará el vínculo entre {item.original_filename} y {unit.title}. "
                            "El archivo y el objeto digital se conservarán."
                        )
                        with st.form(
                            f"catalog_unlink_commit_{item.link_id}",
                            enter_to_submit=False,
                        ):
                            unlink_confirm = st.checkbox(
                                "Confirmo que quiero quitar solamente esta asociación",
                                key=f"catalog_unlink_confirm_{item.link_id}",
                            )
                            unlink_submitted = st.form_submit_button(
                                "Quitar asociación",
                                disabled=not unlink_confirm,
                            )
                        if unlink_submitted:
                            def unlink_callback(session, link_id=item.link_id):
                                result = unlink_digital_object_from_unit(
                                    session, link_id=link_id, removed_by=actor or "local_user"
                                )
                                return (
                                    f"Asociación quitada: {result.original_filename}. "
                                    f"Vínculos restantes: {result.remaining_links}"
                                )

                            _run_catalog_action(
                                st, db_path=db_path, unit_id=unit.id, callback=unlink_callback
                            )

            with st.expander("Seleccionar un archivo y copiarlo dentro del proyecto"):
                st.caption(
                    "El selector abre el diálogo de archivos del sistema. Archive Workbench copia el "
                    "archivo dentro de project_data y registra únicamente su ruta relativa."
                )
                with st.form(f"catalog_upload_file_{unit.id}", enter_to_submit=False):
                    uploaded_file = st.file_uploader(
                        "Archivo",
                        type=["pdf", "tif", "tiff", "png", "jpg", "jpeg", "webp"],
                    )
                    destination_dir = st.text_input(
                        "Carpeta de destino relativa a project_data",
                        value="corpus/importados",
                    )
                    upload_relation = st.selectbox(
                        "Relación",
                        options=list(RELATION_TYPES),
                        format_func=lambda value: _RELATION_LABELS[value],
                        key=f"catalog_upload_relation_{unit.id}",
                    )
                    st.caption(_RELATION_HELP[upload_relation])
                    upload_pages = st.columns(2)
                    with upload_pages[0]:
                        upload_page_start = st.number_input(
                            "Página inicial", min_value=0, value=0, key=f"catalog_upload_start_{unit.id}"
                        )
                    with upload_pages[1]:
                        upload_page_end = st.number_input(
                            "Página final", min_value=0, value=0, key=f"catalog_upload_end_{unit.id}"
                        )
                    upload_submit = st.form_submit_button("Copiar, registrar y asociar", type="primary")
                if upload_submit:
                    if uploaded_file is None:
                        st.error("Seleccioná un archivo")
                    else:
                        upload_name = uploaded_file.name
                        upload_content = uploaded_file.getvalue()

                        def upload_callback(session):
                            result = register_uploaded_file(
                                session,
                                project_root=project_root,
                                project_id=decisions.project_id,
                                archival_unit_id=unit.id,
                                original_filename=upload_name,
                                content=upload_content,
                                destination_dir=destination_dir,
                                relation_type=upload_relation,
                                page_start=int(upload_page_start) or None,
                                page_end=int(upload_page_end) or None,
                                registered_by=actor or "local_user",
                            )
                            action = (
                                "Archivo ya presente y reutilizado"
                                if result.reused_existing_path
                                else "Archivo copiado, registrado y asociado"
                            )
                            return f"{action}: {result.relative_path}"

                        _run_catalog_action(
                            st,
                            db_path=db_path,
                            unit_id=unit.id,
                            callback=upload_callback,
                        )

            with st.expander("Asociar un archivo que ya está dentro del proyecto"):
                st.caption(
                    "Usá esta opción cuando el archivo ya se encuentra físicamente dentro de project_data."
                )
                with st.form(f"catalog_attach_file_{unit.id}", enter_to_submit=False):
                    relative_path = st.text_input(
                        "Ruta relativa",
                        placeholder="corpus/caja/documento.pdf",
                    )
                    relation_type = st.selectbox(
                        "Relación",
                        options=list(RELATION_TYPES),
                        format_func=lambda value: _RELATION_LABELS[value],
                    )
                    st.caption(_RELATION_HELP[relation_type])
                    page_cols = st.columns(2)
                    with page_cols[0]:
                        page_start = st.number_input("Página inicial", min_value=0, value=0)
                    with page_cols[1]:
                        page_end = st.number_input("Página final", min_value=0, value=0)
                    attach_submit = st.form_submit_button("Registrar y asociar", type="primary")
                if attach_submit:
                    _run_catalog_action(
                        st,
                        db_path=db_path,
                        unit_id=unit.id,
                        callback=lambda session: (
                            lambda result: (
                                "Archivo asociado; contenido duplicado reutilizado"
                                if result.duplicate_content
                                else "Archivo registrado y asociado"
                            )
                        )(
                            register_local_file(
                                session,
                                project_root=project_root,
                                project_id=decisions.project_id,
                                archival_unit_id=unit.id,
                                relative_path=relative_path,
                                relation_type=relation_type,
                                page_start=int(page_start) or None,
                                page_end=int(page_end) or None,
                                registered_by=actor or "local_user",
                            )
                        ),
                    )

            linked_ids = {row.id for row in digital_objects}
            available = [row for row in object_choices if row.id not in linked_ids]
            if available:
                with st.expander("Vincular un objeto digital ya registrado"):
                    selected_object_id = st.selectbox(
                        "Objeto digital",
                        options=[row.id for row in available],
                        format_func=lambda value: next(
                            f"{row.original_filename} · {row.media_type} · {row.sha256[:10]}…"
                            for row in available
                            if row.id == value
                        ),
                        key=f"catalog_existing_digital_{unit.id}",
                    )
                    existing_relation = st.selectbox(
                        "Relación con la unidad",
                        options=list(RELATION_TYPES),
                        format_func=lambda value: _RELATION_LABELS[value],
                        key=f"catalog_existing_relation_{unit.id}",
                    )
                    st.caption(_RELATION_HELP[existing_relation])
                    if st.button("Vincular objeto", key=f"catalog_link_existing_{unit.id}"):
                        _run_catalog_action(
                            st,
                            db_path=db_path,
                            unit_id=unit.id,
                            callback=lambda session: (
                                link_existing_digital_object(
                                    session,
                                    project_id=decisions.project_id,
                                    archival_unit_id=unit.id,
                                    digital_object_id=selected_object_id,
                                    relation_type=existing_relation,
                                    registered_by=actor or "local_user",
                                ),
                                "Objeto digital vinculado",
                            )[1],
                        )

        with structure_tab:
            current_parent = unit.parent_id
            possible_parents = [
                row
                for row in all_rows
                if row.id != unit.id and row.level_key in level_map[unit.level_key].parent_keys
            ]
            parent_options = [None] if not level_map[unit.level_key].parent_keys else []
            parent_options += [row.id for row in possible_parents]
            st.write(f"**Ubicación actual:** {by_id[unit.id].path}")
            st.caption(
                "La unidad padre es la unidad que contiene directamente a esta. Al moverla, "
                "también se desplaza toda su rama de unidades hijas, sin cambiar identidades, archivos ni historial."
            )
            if parent_options:
                with st.form(f"catalog_move_{unit.id}", enter_to_submit=False):
                    default_index = (
                        parent_options.index(current_parent)
                        if current_parent in parent_options
                        else 0
                    )
                    new_parent = st.selectbox(
                        "Mover esta unidad dentro de",
                        options=parent_options,
                        index=default_index,
                        format_func=lambda value: "[raíz]" if value is None else by_id[value].path,
                    )
                    move_note = st.text_input("Motivo del movimiento", placeholder="Opcional")
                    move_submit = st.form_submit_button(
                        "Confirmar movimiento", disabled=new_parent == current_parent
                    )
                if move_submit:
                    _run_catalog_action(
                        st,
                        db_path=db_path,
                        unit_id=unit.id,
                        callback=lambda session: (
                            move_archival_unit(
                                session,
                                decisions=decisions,
                                unit_id=unit.id,
                                new_parent_id=new_parent,
                                changed_by=actor or "local_user",
                                note=move_note,
                            ),
                            "Unidad movida",
                        )[1],
                    )
                latest_revision = revisions[0] if revisions else None
                if latest_revision and latest_revision.operation in {"move", "undo_move"}:
                    st.caption(
                        "El último cambio de esta unidad fue un movimiento. Deshacer crea una nueva revisión; no borra el historial."
                    )
                    if st.button("Deshacer último movimiento", key=f"catalog_undo_move_{unit.id}_{unit.revision}"):
                        _run_catalog_action(
                            st,
                            db_path=db_path,
                            unit_id=unit.id,
                            callback=lambda session: (
                                undo_last_archival_move(
                                    session,
                                    decisions=decisions,
                                    unit_id=unit.id,
                                    changed_by=actor or "local_user",
                                ),
                                "Movimiento deshecho",
                            )[1],
                        )
            else:
                st.info("No hay ubicaciones alternativas válidas para este nivel.")
            st.caption(
                "La aplicación impide ciclos y movimientos hacia niveles no admitidos por decisions.yaml."
            )

        with history_tab:
            if not revisions:
                st.info("La unidad todavía no tiene revisiones registradas desde esta etapa.")
            for revision in revisions:
                with st.expander(
                    f"Rev. {revision.revision_number} · "
                    f"{_OPERATION_LABELS.get(revision.operation, revision.operation)} · "
                    f"{revision.changed_by}",
                    expanded=False,
                ):
                    st.caption(revision.changed_at.isoformat())
                    if revision.note:
                        st.write(revision.note)
                    snapshot = revision.snapshot
                    st.json(
                        {
                            "parent_id": snapshot.get("parent_id"),
                            "level_key": snapshot.get("level_key"),
                            "reference_code": snapshot.get("reference_code"),
                            "title": snapshot.get("title"),
                            "registration_status": snapshot.get("registration_status"),
                            "completion_confirmed": snapshot.get("completion_confirmed"),
                            "fields": snapshot.get("fields", []),
                        },
                        expanded=False,
                    )
