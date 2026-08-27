from __future__ import annotations

from archive_workbench.ui_dates import DATE_INPUT_MIN, DATE_INPUT_MAX
from archive_workbench.ui_help import SECTION_HELP, TAB_HELP, TASK_HELP
from datetime import date
import json
from pathlib import Path

from archive_workbench.analysis_quality import analysis_quality_scope
from archive_workbench.authority_dictionary import (
    apply_authority_dictionary,
    authority_dictionary_example_bytes,
    authority_dictionary_schema_bytes,
    export_authority_dictionary_bytes,
    validate_authority_dictionary,
)
from archive_workbench.ui_navigation import mount_choice_help, mount_heading_help, rerun_app, rerun_view, tracked_tabs, request_app_view

from archive_workbench.authorities import (
    ALIAS_TYPES,
    AUTHORITY_LIFECYCLE_STATUSES,
    AUTHORITY_REVIEW_STATUSES,
    AUTHORITY_TYPES,
    add_authority_alias,
    authority_mention_candidates,
    authority_revision_rows,
    authority_rows,
    create_authority,
    include_authority_mention_candidates,
    mention_rows,
    record_mention_suggestion_authorization,
    remove_authority_alias,
    update_authority,
)
from archive_workbench.db import create_sqlite_engine, session_scope
from archive_workbench.discovery_app import render_open_discovery_section
from archive_workbench.relations import (
    RELATION_ARCHIVAL_CATEGORIES,
    RELATION_EDITABLE_LIFECYCLE_STATUSES,
    RELATION_REVIEW_STATUSES,
    RELATION_TARGET_KINDS,
    create_entity_relation,
    entity_relation_revision_rows,
    entity_relation_rows,
    relation_target_choices,
    update_entity_relation,
)

_TYPE_LABELS = {
    "person": "Persona",
    "organization": "Organismo / institución",
    "family": "Familia",
    "place": "Lugar",
    "event": "Acontecimiento",
    "work": "Obra / publicación",
    "other": "Otra entidad",
}
_REVIEW_LABELS = {
    "unreviewed": "Sin revisar",
    "needs_review": "Requiere revisión",
    "reviewed": "Revisado",
    "approved": "Aprobado",
}
_LIFECYCLE_LABELS = {"active": "Activo", "inactive": "Inactivo"}
_PAGE_REVIEW_LABELS = {
    "unreviewed": "Sin revisar",
    "needs_review": "Requiere revisión",
    "reviewed": "Revisada",
    "approved": "Aprobada",
}
_MENTION_STATUS_LABELS = {
    "pending": "Pendiente",
    "accepted": "Aceptada",
    "rejected": "Rechazada",
    "modified": "Modificada",
}
_ALIAS_LABELS = {
    "parallel": "Forma paralela del nombre",
    "normalized_other_rules": "Forma normalizada según otras reglas",
    "variant": "Otra forma del nombre",
    "abbreviation": "Abreviatura",
    "acronym": "Sigla",
    "former_name": "Nombre anterior",
    "title": "Tratamiento / título",
    "other": "Otra forma",
}

_AUTHORITY_PROFILE_FIELDS = (
    ("entity_identifiers", "Identificadores de la entidad"),
    ("places", "Lugares"),
    ("legal_status", "Estatuto jurídico"),
    ("functions_activities", "Funciones, ocupaciones y actividades"),
    ("mandates_sources", "Atribuciones, mandatos y fuentes legales"),
    ("internal_structure", "Estructuras internas / genealogía"),
    ("general_context", "Contexto general"),
    ("authority_record_identifier", "Identificador del registro de autoridad"),
    ("responsible_institution", "Institución responsable de la descripción"),
    ("description_rules", "Reglas y convenciones de descripción"),
    ("detail_level", "Nivel de detalle"),
    ("language_script", "Lengua y escritura de la descripción"),
    ("sources", "Fuentes de la descripción"),
    ("maintenance_notes", "Notas de mantenimiento"),
)
_AUTHORITY_PROFILE_LABELS = dict(_AUTHORITY_PROFILE_FIELDS)
_RELATION_CATEGORY_LABELS = {
    "hierarchical": "Jerárquica",
    "temporal_succession": "Temporal / sucesión",
    "family": "Familiar",
    "associative": "Asociativa",
    "other": "Otra",
}
_RELATION_TARGET_LABELS = {
    "entity": "Otra entidad",
    "archival_unit": "Unidad del catálogo",
    "document_part": "Parte interna de un documento",
}


def _profile_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return "\n".join(str(item) for item in value if str(item).strip())
    return str(value)


def _display_profile_value(value: object) -> str:
    text = _profile_text(value).strip()
    return text or "Sin registrar"

_AUTHORITY_TASK_LABELS = {
    "review": "Revisar fichas y menciones",
    "create": "Crear una ficha",
    "import": "Importar o exportar fichas",
    "discover": "Buscar nuevas entidades",
}


def _alias_help(alias) -> str:
    details = [_ALIAS_LABELS.get(alias.alias_type, alias.alias_type)]
    if alias.note:
        details.append(alias.note)
    return " · ".join(details)


def _run(st, *, db_path: Path, callback, selection: str | None = None) -> None:
    engine = create_sqlite_engine(db_path)
    try:
        with session_scope(engine) as session:
            result = callback(session)
            selected = getattr(result, "id", None) or selection
    except (ValueError, RuntimeError, OSError) as exc:
        st.error(str(exc))
        return
    finally:
        engine.dispose()
    if selected:
        st.session_state["authority_pending_selection"] = str(selected)
    rerun_view(st)

def _render_authority_creation(
    st,
    *,
    db_path: Path,
    project_id: str,
    actor: str,
) -> None:
    st.subheader("Crear una ficha de entidad")
    with st.form("authority_create", clear_on_submit=True, enter_to_submit=False):
        entity_type = st.selectbox(
            "Tipo de entidad", options=list(AUTHORITY_TYPES), format_func=lambda value: _TYPE_LABELS[value]
        )
        preferred_name = st.text_input("Forma autorizada del nombre")
        description = st.text_area("Historia / nota biográfica (opcional)", height=100)
        temporal_expression = st.text_input(
            "Período de existencia o vigencia",
            placeholder="Ej.: 1946 - 2015; desde 2024",
            help="Puede registrar uno o varios períodos. Separe períodos discontinuos con punto y coma.",
        )
        temporal_note = st.text_area(
            "Nota sobre el período de esta entidad (opcional)",
            placeholder="Fuente, duda o criterio usado para fechar la entidad.",
            height=80,
        )
        review_status = st.selectbox(
            "Estado de revisión de esta ficha",
            options=list(AUTHORITY_REVIEW_STATUSES),
            format_func=lambda value: _REVIEW_LABELS[value],
        )
        create_submit = st.form_submit_button("Crear esta ficha de entidad", type="primary")
    if create_submit:
        _run(
            st,
            db_path=db_path,
            callback=lambda session: create_authority(
                session,
                project_id=project_id,
                entity_type=entity_type,
                preferred_name=preferred_name,
                description=description,
                temporal_expression=temporal_expression,
                temporal_note=temporal_note,
                review_status=review_status,
                created_by=actor or "local_user",
            ),
        )


def _render_authority_workspace(
    st,
    *,
    db_path: Path,
    project_id: str,
    actor: str,
) -> None:
    with st.container(horizontal=True, vertical_alignment="bottom", gap="small"):
        query = st.text_input(
            "Buscar nombre, nombre alternativo o historia",
            key="authority_query",
            placeholder="Buscar nombre, nombre alternativo o historia",
            label_visibility="collapsed",
            width="stretch",
        )
        selected_types = st.multiselect(
            "Tipo",
            options=list(AUTHORITY_TYPES),
            format_func=lambda value: _TYPE_LABELS[value],
            placeholder="Todos",
            key="authority_types",
            width=220,
        )
        lifecycle_scope = st.selectbox(
            "Estado de ficha",
            options=("active", "all"),
            format_func=lambda value: "Activas" if value == "active" else "Todas",
            key="authority_lifecycle_scope",
            width=170,
        )
        temporal_value = st.date_input(
            "Período",
            value=(),
            min_value=DATE_INPUT_MIN,
            max_value=DATE_INPUT_MAX,
            key="authority_temporal_range",
            format="DD/MM/YYYY",
            width=250,
        )

    if temporal_value is None:
        temporal_values: tuple[date, ...] = ()
    elif isinstance(temporal_value, tuple):
        temporal_values = temporal_value
    else:
        temporal_values = (temporal_value,)
    filter_temporal = bool(temporal_values)
    temporal_start = temporal_values[0] if temporal_values else None
    temporal_end = temporal_values[-1] if temporal_values else None
    include_undated = False
    if filter_temporal:
        include_undated = st.checkbox(
            "Incluir entidades sin fecha",
            value=False,
            key="authority_temporal_include_undated",
        )

    engine = create_sqlite_engine(db_path)
    try:
        with session_scope(engine) as session:
            rows = authority_rows(
                session,
                project_id=project_id,
                query=query,
                entity_types=selected_types,
                lifecycle_statuses=("active", "inactive") if lifecycle_scope == "all" else ("active",),
                temporal_start=temporal_start if filter_temporal else None,
                temporal_end=temporal_end if filter_temporal else None,
                include_undated=include_undated if filter_temporal else False,
            )
    except (ValueError, RuntimeError, OSError) as exc:
        st.error(str(exc))
        return
    finally:
        engine.dispose()

    if query.strip():
        result_label = f"{len(rows)} entidad" if len(rows) == 1 else f"{len(rows)} entidades"
        st.badge(result_label, color="primary")
    if not rows:
        st.info("No hay entidades que coincidan con los criterios elegidos.")
        return

    row_map = {row.authority_id: row for row in rows}
    pending = st.session_state.pop("authority_pending_selection", None)
    if pending in row_map:
        st.session_state["authority_selected"] = pending
    current = st.session_state.get("authority_selected")
    if current not in row_map:
        st.session_state["authority_selected"] = rows[0].authority_id

    selected_id = st.selectbox(
        "Entidad",
        options=list(row_map),
        format_func=lambda key: f"{row_map[key].preferred_name} · {_TYPE_LABELS[row_map[key].entity_type]}",
        key="authority_selected",
        label_visibility="collapsed",
    )
    selected = row_map[selected_id]

    st.subheader(selected.preferred_name)
    with st.container(horizontal=True, gap="xsmall"):
        st.badge(_TYPE_LABELS[selected.entity_type], color="primary")
        st.badge(_REVIEW_LABELS[selected.review_status], color="gray")
        mention_label = (
            f"{selected.mention_count} mención"
            if selected.mention_count == 1
            else f"{selected.mention_count} menciones"
        )
        st.badge(mention_label, color="blue")
        if selected.lifecycle_status == "inactive":
            st.badge("Dada de baja", color="red")
        if selected.temporal_expression:
            st.badge(selected.temporal_expression, color="gray")

    detail_tab, mentions_tab, relations_tab, history_tab = tracked_tabs(
        st,
        ["Ficha", "Menciones", "Relaciones", "Historial"],
        key="authority_tabs",
        help_by_label=TAB_HELP["authority_tabs"],
        default="Ficha",
    )
    with detail_tab:
        with st.container(horizontal=True, vertical_alignment="bottom", gap="small"):
            entity_type_edit = st.selectbox(
                "Tipo de entidad",
                options=list(AUTHORITY_TYPES),
                index=list(AUTHORITY_TYPES).index(selected.entity_type),
                format_func=lambda value: _TYPE_LABELS[value],
                key=f"authority_type_edit_{selected.authority_id}_{selected.revision}",
                width=230,
            )
            name_edit = st.text_input(
                "Forma autorizada del nombre",
                value=selected.preferred_name,
                key=f"authority_name_edit_{selected.authority_id}_{selected.revision}",
                width="stretch",
            )
            with st.popover("Agregar nombre alternativo", width="content"):
                with st.form(
                    f"authority_alias_add_{selected.authority_id}",
                    clear_on_submit=True,
                    enter_to_submit=False,
                ):
                    alias_value = st.text_input("Nombre alternativo")
                    alias_type = st.selectbox(
                        "Tipo",
                        options=list(ALIAS_TYPES),
                        format_func=lambda value: _ALIAS_LABELS[value],
                    )
                    alias_note = st.text_input("Nota (opcional)")
                    alias_submit = st.form_submit_button("Agregar nombre alternativo")
                if alias_submit:
                    _run(
                        st,
                        db_path=db_path,
                        selection=selected.authority_id,
                        callback=lambda session: add_authority_alias(
                            session,
                            authority_id=selected.authority_id,
                            alias=alias_value,
                            alias_type=alias_type,
                            note=alias_note,
                            created_by=actor or "local_user",
                        ),
                    )
                if selected.aliases:
                    st.divider()
                    for alias in selected.aliases:
                        with st.container(horizontal=True, vertical_alignment="center", gap="small"):
                            st.badge(alias.alias, color="gray", help=_alias_help(alias))
                            if st.button(
                                "Quitar alias",
                                key=f"authority_alias_remove_{alias.alias_id}",
                                help=f"Quitar {alias.alias!r} de esta ficha",
                            ):
                                _run(
                                    st,
                                    db_path=db_path,
                                    selection=selected.authority_id,
                                    callback=lambda session, alias_id=alias.alias_id: remove_authority_alias(
                                        session,
                                        alias_id=alias_id,
                                        removed_by=actor or "local_user",
                                    ),
                                )

        if selected.aliases:
            with st.container(horizontal=True, gap="xsmall"):
                for alias in selected.aliases:
                    st.badge(alias.alias, color="gray", help=_alias_help(alias))

        with st.form(
            f"authority_edit_{selected.authority_id}_{selected.revision}",
            enter_to_submit=False,
        ):
            description_edit = st.text_area(
                "Historia / nota biográfica",
                value=selected.description or "",
                height=110,
            )
            temporal_cols = st.columns(2)
            temporal_expression_edit = temporal_cols[0].text_input(
                "Fechas de existencia o vigencia",
                value=selected.temporal_expression or "",
                placeholder="Ej.: 1946 - 2015; desde 2024",
                help="Puede registrar uno o varios períodos discontinuos separados por punto y coma.",
            )
            temporal_note_edit = temporal_cols[1].text_area(
                "Nota sobre las fechas (opcional)",
                value=selected.temporal_note or "",
                height=80,
            )
            status_cols = st.columns(2)
            review_edit = status_cols[0].selectbox(
                "Estado de revisión de la ficha",
                options=list(AUTHORITY_REVIEW_STATUSES),
                index=list(AUTHORITY_REVIEW_STATUSES).index(selected.review_status),
                format_func=lambda value: _REVIEW_LABELS[value],
            )
            lifecycle_edit = status_cols[1].selectbox(
                "Estado de la ficha",
                options=list(AUTHORITY_LIFECYCLE_STATUSES),
                index=list(AUTHORITY_LIFECYCLE_STATUSES).index(selected.lifecycle_status),
                format_func=lambda value: _LIFECYCLE_LABELS[value],
            )
            edit_note = st.text_input("Nota sobre estos cambios (opcional)")
            edit_submit = st.form_submit_button("Guardar cambios", type="primary")
        if edit_submit:
            _run(
                st,
                db_path=db_path,
                selection=selected.authority_id,
                callback=lambda session: update_authority(
                    session,
                    authority_id=selected.authority_id,
                    expected_revision=selected.revision,
                    entity_type=entity_type_edit,
                    preferred_name=name_edit,
                    description=description_edit,
                    temporal_expression=temporal_expression_edit,
                    temporal_note=temporal_note_edit,
                    review_status=review_edit,
                    lifecycle_status=lifecycle_edit,
                    note=edit_note,
                    changed_by=actor or "local_user",
                ),
            )

        st.divider()
        st.markdown("#### Datos descriptivos complementarios")
        st.caption(
            "Estos datos son opcionales. No es necesario completar todos los campos: agregá solamente "
            "los que aporten información útil para esta entidad."
        )
        registered_profile = [
            (key, label, selected.profile.get(key))
            for key, label in _AUTHORITY_PROFILE_FIELDS
            if _profile_text(selected.profile.get(key)).strip()
        ]
        if registered_profile:
            for key, label, value in registered_profile:
                with st.container(border=True):
                    st.markdown(f"**{label}**")
                    st.caption(_display_profile_value(value))
        else:
            st.caption("Todavía no hay datos descriptivos complementarios registrados.")

        optional_profile_key = st.selectbox(
            "Dato descriptivo opcional que querés revisar o agregar",
            options=[""] + [key for key, _label in _AUTHORITY_PROFILE_FIELDS],
            format_func=lambda value: "Elegir un dato…" if not value else _AUTHORITY_PROFILE_LABELS[value],
            key=f"authority_profile_choice_{selected.authority_id}_{selected.revision}",
        )
        if optional_profile_key:
            with st.form(
                f"authority_profile_edit_{selected.authority_id}_{optional_profile_key}_{selected.revision}",
                enter_to_submit=False,
            ):
                profile_value = st.text_area(
                    _AUTHORITY_PROFILE_LABELS[optional_profile_key],
                    value=_profile_text(selected.profile.get(optional_profile_key)),
                    height=110,
                )
                profile_note = st.text_input("Nota sobre este cambio (opcional)")
                profile_submit = st.form_submit_button("Guardar este dato descriptivo", type="primary")
            if profile_submit:
                updated_profile = dict(selected.profile)
                cleaned = profile_value.strip()
                if cleaned:
                    updated_profile[optional_profile_key] = cleaned
                else:
                    updated_profile.pop(optional_profile_key, None)
                _run(
                    st,
                    db_path=db_path,
                    selection=selected.authority_id,
                    callback=lambda session: update_authority(
                        session,
                        authority_id=selected.authority_id,
                        expected_revision=selected.revision,
                        profile_json=updated_profile,
                        note=profile_note,
                        changed_by=actor or "local_user",
                    ),
                )

    with mentions_tab:
        st.subheader("Menciones vinculadas")
        engine = create_sqlite_engine(db_path)
        try:
            with session_scope(engine) as session:
                mentions = mention_rows(session, authority_id=selected.authority_id)
        finally:
            engine.dispose()
        if not mentions:
            st.caption("Esta entidad todavía no tiene menciones vinculadas.")
        for mention in mentions:
            with st.container(border=True):
                heading, action = st.columns([5, 1])
                heading.write(
                    f"**{mention.mention_text}** · página {mention.page_number} · "
                    f"bloque de texto {mention.order_index + 1} · {_MENTION_STATUS_LABELS.get(mention.status, mention.status)}"
                )
                heading.caption(mention.document_title or "Documento sin título")
                if mention.is_stale:
                    heading.warning(
                        "El texto del documento cambió después de vincular esta mención. Hay que comprobar si la mención sigue correspondiendo a la versión vigente."
                    )
                if action.button(
                    "Abrir en Revisar documentos",
                    key=f"authority_open_mention_{mention.mention_id}",
                    disabled=not bool(mention.source_key),
                ):
                    request_app_view(
                        st,
                        mode="review",
                        source_key=mention.source_key,
                        page=mention.page_number,
                        object_id=mention.object_id,
                    )
                    rerun_app(st)

        st.divider()
        st.subheader(
            "Buscar menciones",
            help=(
                "Busca el nombre principal y los nombres alternativos de esta entidad en los textos. "
                "Las coincidencias se revisan antes de incorporarlas."
            ),
        )
        surfaces = [selected.preferred_name] + [alias.alias for alias in selected.aliases]
        st.caption("Nombres buscados: " + " · ".join(f"`{item}`" for item in surfaces))

        with st.container(horizontal=True, vertical_alignment="bottom", gap="small"):
            candidate_page_statuses = st.multiselect(
                "Estado de las páginas",
                options=["unreviewed", "needs_review", "reviewed", "approved"],
                default=["approved"],
                format_func=lambda value: _PAGE_REVIEW_LABELS[value],
                key=f"authority_candidate_page_statuses_{selected.authority_id}",
                help="Elegí en qué estados de revisión de página querés buscar. Una selección vacía incluye todos los estados.",
                width="stretch",
            )
            search_clicked = st.button(
                "Buscar menciones de esta entidad",
                type="primary",
                key=f"authority_candidate_search_{selected.authority_id}",
            )
            clear_clicked = st.button(
                "Ocultar coincidencias",
                key=f"authority_candidate_clear_{selected.authority_id}",
            )

        candidate_quality_scope = analysis_quality_scope(candidate_page_statuses)
        candidate_quality_confirmed = candidate_quality_scope.is_broader_than_default
        candidate_quality_reason = (
            "Estados de revisión de página elegidos explícitamente en la pestaña Menciones."
            if candidate_quality_confirmed
            else None
        )

        if search_clicked:
            engine = create_sqlite_engine(db_path)
            try:
                with session_scope(engine) as session:
                    record_mention_suggestion_authorization(
                        session,
                        project_id=project_id,
                        page_review_statuses=tuple(candidate_page_statuses),
                        broader_quality_scope_confirmed=candidate_quality_confirmed,
                        quality_scope_reason=candidate_quality_reason,
                        actor=actor or "local_user",
                        source="ui",
                        target_type="authority",
                        target_id=selected.authority_id,
                        parameters={
                            "mode": "authority_candidates",
                            "authority_id": selected.authority_id,
                            "include_existing": True,
                        },
                    )
            except (ValueError, RuntimeError, OSError) as exc:
                st.error(str(exc))
            else:
                st.session_state["authority_candidate_entity"] = selected.authority_id
                st.session_state["authority_candidate_search_config"] = {
                    "authority_id": selected.authority_id,
                    "page_review_statuses": list(candidate_page_statuses),
                    "broader_quality_scope_confirmed": candidate_quality_confirmed,
                    "quality_scope_reason": candidate_quality_reason,
                }
            finally:
                engine.dispose()

        if clear_clicked:
            st.session_state.pop("authority_candidate_entity", None)
            st.session_state.pop("authority_candidate_search_config", None)
            for key in list(st.session_state):
                if str(key).startswith(f"authority_candidate_pick_{selected.authority_id}_"):
                    st.session_state.pop(key, None)
            rerun_view(st)

        if st.session_state.get("authority_candidate_entity") == selected.authority_id:
            search_config = st.session_state.get("authority_candidate_search_config") or {}
            searched_page_statuses = tuple(
                search_config.get("page_review_statuses", candidate_page_statuses)
            )
            searched_quality_confirmed = bool(
                search_config.get(
                    "broader_quality_scope_confirmed",
                    candidate_quality_confirmed,
                )
            )
            searched_quality_reason = search_config.get(
                "quality_scope_reason",
                candidate_quality_reason,
            )
            engine = create_sqlite_engine(db_path)
            try:
                with session_scope(engine) as session:
                    candidates = authority_mention_candidates(
                        session,
                        authority_id=selected.authority_id,
                        include_existing=True,
                        page_review_statuses=searched_page_statuses,
                        broader_quality_scope_confirmed=searched_quality_confirmed,
                        quality_scope_reason=searched_quality_reason,
                    )
            except (ValueError, RuntimeError, OSError) as exc:
                st.error(str(exc))
                candidates = []
            finally:
                engine.dispose()

            actionable_candidates = [
                item
                for item in candidates
                if not item.already_included and not item.has_authority_conflict
            ]
            already_candidates = [item for item in candidates if item.already_included]
            conflict_candidates = [item for item in candidates if item.has_authority_conflict]
            with st.container(horizontal=True, gap="xsmall"):
                if actionable_candidates:
                    st.badge(f"{len(actionable_candidates)} para revisar", color="orange")
                if already_candidates:
                    st.badge(f"{len(already_candidates)} ya vinculadas", color="green")
                if conflict_candidates:
                    st.badge(f"{len(conflict_candidates)} vinculadas a otra entidad", color="red")
                if not candidates:
                    st.badge("Sin coincidencias", color="gray")
            show_existing = False
            if already_candidates:
                show_existing = st.checkbox(
                    "Mostrar también las coincidencias ya incorporadas",
                    value=False,
                    key=f"authority_show_existing_{selected.authority_id}",
                )
            visible = candidates if show_existing else [
                item for item in candidates if not item.already_included
            ]
            if not visible:
                st.info(
                    "No hay coincidencias pendientes de incorporación."
                    if candidates
                    else "No se encontraron el nombre principal ni sus nombres alternativos en los documentos incluidos."
                )
            else:
                status_to_create = st.selectbox(
                    "Estado de revisión que tendrán las menciones que incorpores",
                    options=["pending", "accepted"],
                    format_func=lambda value: "Pendiente de revisión" if value == "pending" else "Aceptada",
                    key=f"authority_candidate_status_{selected.authority_id}",
                    help="Lo más seguro es incorporarlas como pendientes y revisarlas después.",
                )
                selected_keys: list[str] = []
                for candidate in visible:
                    alias_info = (
                        "nombre principal"
                        if candidate.match_kind == "preferred"
                        else f"nombre alternativo · {_ALIAS_LABELS.get(candidate.alias_type or 'other', candidate.alias_type or 'otro')}"
                    )
                    with st.container(border=True):
                        pick_col, body_col, open_col = st.columns([0.5, 6, 1])
                        picked = pick_col.checkbox(
                            "Vincular esta coincidencia a la entidad",
                            label_visibility="collapsed",
                            disabled=(
                                candidate.already_included
                                or candidate.has_authority_conflict
                            ),
                            key=(
                                f"authority_candidate_pick_{selected.authority_id}_"
                                f"{candidate.candidate_key}"
                            ),
                        )
                        if (
                            picked
                            and not candidate.already_included
                            and not candidate.has_authority_conflict
                        ):
                            selected_keys.append(candidate.candidate_key)
                        body_col.write(
                            f"…{candidate.context_before}**{candidate.mention_text}**"
                            f"{candidate.context_after}…"
                        )
                        body_col.caption(
                            f"{candidate.document_title or '[sin título]'} · página {candidate.page_number} · "
                            f"bloque de texto {candidate.order_index + 1} · coincidencia por {alias_info}: "
                            f"{candidate.matched_surface!r}"
                        )
                        if candidate.already_included:
                            body_col.success(
                                f"Ya incorporada · estado {candidate.existing_status or 'desconocido'}"
                            )
                        elif candidate.can_link_existing:
                            body_col.warning(
                                "Ya existe una mención sin entidad vinculada sobre este fragmento. Si la incorporás, Archive Workbench vinculará esa mención con la entidad seleccionada en lugar de crear un registro duplicado."
                            )
                        elif candidate.has_authority_conflict:
                            body_col.error(
                                "El mismo fragmento ya está vinculado a "
                                f"{candidate.existing_authority_name or 'otra entidad'}."
                            )
                        if open_col.button(
                            "Abrir este fragmento en Revisar documentos",
                            key=f"authority_candidate_open_{candidate.candidate_key}",
                            disabled=not bool(candidate.source_key),
                        ):
                            request_app_view(
                                st,
                                mode="review",
                                source_key=candidate.source_key,
                                page=candidate.page_number,
                                object_id=candidate.object_id,
                            )
                            rerun_app(st)
                action_left, action_right = st.columns(2)
                if action_left.button(
                    f"Incorporar seleccionadas ({len(selected_keys)})",
                    disabled=not selected_keys,
                    key=f"authority_candidate_add_selected_{selected.authority_id}",
                ):
                    _run(
                        st,
                        db_path=db_path,
                        selection=selected.authority_id,
                        callback=lambda session, keys=tuple(selected_keys): include_authority_mention_candidates(
                            session,
                            authority_id=selected.authority_id,
                            candidate_keys=keys,
                            status=status_to_create,
                            created_by=actor or "local_user",
                            page_review_statuses=searched_page_statuses,
                            broader_quality_scope_confirmed=searched_quality_confirmed,
                            quality_scope_reason=searched_quality_reason,
                        ),
                    )
                if action_right.button(
                    f"Incorporar todas ({len(actionable_candidates)})",
                    disabled=not actionable_candidates,
                    key=f"authority_candidate_add_all_{selected.authority_id}",
                ):
                    _run(
                        st,
                        db_path=db_path,
                        selection=selected.authority_id,
                        callback=lambda session, keys=tuple(
                            item.candidate_key for item in actionable_candidates
                        ): include_authority_mention_candidates(
                            session,
                            authority_id=selected.authority_id,
                            candidate_keys=keys,
                            status=status_to_create,
                            created_by=actor or "local_user",
                            page_review_statuses=searched_page_statuses,
                            broader_quality_scope_confirmed=searched_quality_confirmed,
                            quality_scope_reason=searched_quality_reason,
                        ),
                    )

    with relations_tab:
        relation_temporal_filter = st.checkbox(
            "Acotar por período de tiempo",
            key=f"relation_temporal_filter_{selected.authority_id}",
        )
        relation_filter_start = date(1900, 1, 1)
        relation_filter_end = date.today()
        relation_include_undated = False
        if relation_temporal_filter:
            with st.container(horizontal=True, vertical_alignment="bottom", gap="small"):
                relation_filter_start = st.date_input(
                    "Desde",
                    value=date(1900, 1, 1),
                    min_value=DATE_INPUT_MIN,
                    max_value=DATE_INPUT_MAX,
                    key=f"relation_filter_start_{selected.authority_id}",
                    width=210,
                )
                relation_filter_end = st.date_input(
                    "Hasta",
                    value=date.today(),
                    min_value=DATE_INPUT_MIN,
                    max_value=DATE_INPUT_MAX,
                    key=f"relation_filter_end_{selected.authority_id}",
                    width=210,
                )
                relation_include_undated = st.checkbox(
                    "Incluir sin fecha",
                    value=False,
                    key=f"relation_filter_undated_{selected.authority_id}",
                )
        engine = create_sqlite_engine(db_path)
        try:
            with session_scope(engine) as session:
                all_relations = entity_relation_rows(
                    session,
                    project_id=project_id,
                    authority_id=selected.authority_id,
                    relation_kinds=("analytical", "producer", "manager"),
                    include_inactive=True,
                    temporal_start=relation_filter_start if relation_temporal_filter else None,
                    temporal_end=relation_filter_end if relation_temporal_filter else None,
                    include_undated=(relation_include_undated if relation_temporal_filter else False),
                )
        finally:
            engine.dispose()

        catalog_roles = [row for row in all_relations if row.relation_kind in {"producer", "manager"}]
        relations = [row for row in all_relations if row.relation_kind == "analytical"]

        st.subheader(
            "Roles archivísticos",
            help="Roles de productor o responsable de gestión. Se registran y modifican desde Catálogo; en Entidades y menciones son de solo lectura.",
        )
        if not catalog_roles:
            st.caption("Sin roles archivísticos registrados.")
        for relation in catalog_roles:
            role_label = "Entidad productora" if relation.relation_kind == "producer" else "Entidad responsable de gestión"
            with st.container(border=True):
                st.write(f"**{role_label}** · {relation.target_label}")
                if relation.target_context:
                    st.caption(relation.target_context)
                if relation.temporal_expression:
                    st.write(f"**Vigencia:** {relation.temporal_expression}")
                if relation.evidence_note:
                    st.write(f"**Evidencia:** {relation.evidence_note}")
                if relation.provenance_note:
                    st.caption(f"Procedencia del vínculo: {relation.provenance_note}")
                st.caption("Solo lectura en esta sección · se modifica desde Catálogo")

        st.subheader(
            "Relaciones analíticas",
            help="Vínculos interpretativos sustentados por el corpus y registrados desde esta ficha.",
        )
        if not relations:
            st.caption("Todavía no hay relaciones analíticas creadas para esta entidad.")
        for relation in relations:
            relation_profile = dict(relation.profile or {})
            category = str(relation_profile.get("archival_category") or "")
            card_title = f"{relation.source_name} · {relation.relation_label} → {relation.target_label}"
            relation_panel_open = st.toggle(
                card_title,
                value=False,
                key=f"authority_relation_panel_{relation.relation_id}",
            )
            if relation_panel_open:
                with st.container(border=True):
                    fields = (
                        ("Entidad de origen", relation.source_name),
                        ("Nombre de la relación", relation.relation_label),
                        ("Categoría archivística", _RELATION_CATEGORY_LABELS.get(category, category)),
                        ("Tipo de registro relacionado", _RELATION_TARGET_LABELS.get(relation.target_kind, relation.target_kind)),
                        ("Registro relacionado", relation.target_label),
                        ("Contexto del registro relacionado", relation.target_context),
                        ("Contexto de la relación", relation_profile.get("context")),
                        ("Descripción de la relación", relation_profile.get("description")),
                        ("Fechas de vigencia", relation.temporal_expression),
                        ("Nota sobre las fechas", relation.temporal_note),
                        ("Evidencia", relation.evidence_note),
                        ("Fuente / procedencia", relation.provenance_note),
                        ("Estado de revisión", _REVIEW_LABELS.get(relation.review_status, relation.review_status)),
                        ("Estado dentro del proyecto", _LIFECYCLE_LABELS.get(relation.lifecycle_status, relation.lifecycle_status)),
                        ("Versión", str(relation.revision)),
                    )
                    for field_label, field_value in fields:
                        st.markdown(f"**{field_label}**")
                        st.caption(_display_profile_value(field_value))

                    edit_state_key = f"relation_edit_open_{relation.relation_id}"
                    edit_open = bool(st.session_state.get(edit_state_key, False))
                    if not edit_open and st.button(
                        "Modificar esta relación",
                        key=f"relation_edit_button_{relation.relation_id}_{relation.revision}",
                    ):
                        st.session_state[edit_state_key] = True
                        edit_open = True
                    elif edit_open and st.button(
                        "Cerrar edición",
                        key=f"relation_edit_close_{relation.relation_id}_{relation.revision}",
                    ):
                        st.session_state[edit_state_key] = False
                        edit_open = False

                    if edit_open:
                        st.divider()
                        change_target = st.checkbox(
                            "Cambiar la entidad o unidad relacionada",
                            key=f"relation_change_target_{relation.relation_id}_{relation.revision}",
                            help="El destino actual se conserva salvo que actives esta opción.",
                        )
                        relation_target_kind_edit = None
                        relation_target_id_edit = None
                        relation_target_map = {}
                        if change_target:
                            relation_target_kind_edit = st.selectbox(
                                "Qué clase de elemento será el nuevo destino",
                                options=list(RELATION_TARGET_KINDS),
                                index=list(RELATION_TARGET_KINDS).index(relation.target_kind),
                                format_func=lambda value: _RELATION_TARGET_LABELS[value],
                                key=f"relation_target_kind_edit_{relation.relation_id}",
                            )
                            engine = create_sqlite_engine(db_path)
                            try:
                                with session_scope(engine) as session:
                                    relation_targets = relation_target_choices(
                                        session,
                                        project_id=project_id,
                                        target_kind=relation_target_kind_edit,
                                        exclude_authority_id=relation.source_authority_id,
                                    )
                            finally:
                                engine.dispose()
                            relation_target_map = {target.target_id: target for target in relation_targets}
                            if not relation_target_map:
                                st.warning("No hay destinos disponibles de ese tipo.")

                        category_options = [""] + list(RELATION_ARCHIVAL_CATEGORIES)
                        category_index = category_options.index(category) if category in category_options else 0
                        with st.form(
                            f"relation_edit_{relation.relation_id}_{relation.revision}",
                            enter_to_submit=False,
                        ):
                            relation_label_edit = st.text_input(
                                "Nombre del vínculo entre los dos elementos",
                                value=relation.relation_label,
                                key=f"relation_label_{relation.relation_id}",
                            )
                            relation_category_edit = st.selectbox(
                                "Categoría archivística de la relación (opcional)",
                                options=category_options,
                                index=category_index,
                                format_func=lambda value: "Sin clasificar" if not value else _RELATION_CATEGORY_LABELS[value],
                                key=f"relation_category_{relation.relation_id}",
                            )
                            if change_target and relation_target_map:
                                relation_target_id_edit = st.selectbox(
                                    "Entidad o unidad que será el nuevo destino",
                                    options=list(relation_target_map),
                                    format_func=lambda value: (
                                        f"{relation_target_map[value].label}"
                                        + (
                                            f" · {relation_target_map[value].context}"
                                            if relation_target_map[value].context
                                            else ""
                                        )
                                    ),
                                    key=f"relation_target_id_edit_{relation.relation_id}",
                                )
                            else:
                                st.caption(f"Destino actual: {relation.target_label}")
                            relation_context_edit = st.text_area(
                                "Contexto de la relación (opcional)",
                                value=_profile_text(relation_profile.get("context")),
                                key=f"relation_context_{relation.relation_id}",
                            )
                            relation_description_edit = st.text_area(
                                "Descripción de la relación (opcional)",
                                value=_profile_text(relation_profile.get("description")),
                                key=f"relation_description_{relation.relation_id}",
                            )
                            evidence_edit = st.text_area(
                                "Evidencia documental o fundamento de esta relación",
                                value=relation.evidence_note or "",
                                key=f"relation_evidence_{relation.relation_id}",
                            )
                            provenance_edit = st.text_area(
                                "Fuente / procedencia de la información (opcional)",
                                value=relation.provenance_note or "",
                                key=f"relation_provenance_{relation.relation_id}",
                            )
                            relation_temporal_edit = st.text_input(
                                "Período de vigencia",
                                value=relation.temporal_expression or "",
                                placeholder="Ej.: 1946 - 2015; desde 2024",
                                key=f"relation_temporal_{relation.relation_id}",
                            )
                            relation_temporal_note_edit = st.text_area(
                                "Nota sobre el período de esta relación (opcional)",
                                value=relation.temporal_note or "",
                                key=f"relation_temporal_note_{relation.relation_id}",
                            )
                            relation_review_edit = st.selectbox(
                                "Estado de revisión de esta relación",
                                options=list(RELATION_REVIEW_STATUSES),
                                index=list(RELATION_REVIEW_STATUSES).index(relation.review_status),
                                format_func=lambda value: _REVIEW_LABELS[value],
                                key=f"relation_review_{relation.relation_id}",
                            )
                            relation_lifecycle_edit = st.selectbox(
                                "Vigencia de esta relación en el proyecto",
                                options=list(RELATION_EDITABLE_LIFECYCLE_STATUSES),
                                index=list(RELATION_EDITABLE_LIFECYCLE_STATUSES).index(relation.lifecycle_status),
                                format_func=lambda value: {"active": "Activa", "inactive": "Dada de baja"}[value],
                                help="La baja es lógica: conserva la relación y todo su historial.",
                                key=f"relation_lifecycle_{relation.relation_id}",
                            )
                            relation_note = st.text_input(
                                "Nota sobre estos cambios (opcional)",
                                key=f"relation_note_{relation.relation_id}",
                            )
                            relation_update_submit = st.form_submit_button(
                                "Guardar los cambios de esta relación", type="primary"
                            )
                        if relation_update_submit:
                            if change_target and relation_target_id_edit is None:
                                st.error("Elegí un nuevo destino o desactivá ‘Cambiar la entidad o unidad relacionada’.")
                            else:
                                updated_profile = dict(relation_profile)
                                if relation_category_edit:
                                    updated_profile["archival_category"] = relation_category_edit
                                else:
                                    updated_profile.pop("archival_category", None)
                                for profile_key, profile_value in (
                                    ("context", relation_context_edit),
                                    ("description", relation_description_edit),
                                ):
                                    if profile_value.strip():
                                        updated_profile[profile_key] = profile_value.strip()
                                    else:
                                        updated_profile.pop(profile_key, None)
                                _run(
                                    st,
                                    db_path=db_path,
                                    selection=selected.authority_id,
                                    callback=lambda session, relation=relation, updated_profile=updated_profile: update_entity_relation(
                                        session,
                                        relation_id=relation.relation_id,
                                        expected_revision=relation.revision,
                                        relation_label=relation_label_edit,
                                        target_kind=(relation_target_kind_edit if change_target else None),
                                        target_id=(relation_target_id_edit if change_target else None),
                                        evidence_note=evidence_edit,
                                        provenance_note=provenance_edit,
                                        temporal_expression=relation_temporal_edit,
                                        temporal_note=relation_temporal_note_edit,
                                        review_status=relation_review_edit,
                                        lifecycle_status=relation_lifecycle_edit,
                                        profile_json=updated_profile,
                                        note=relation_note,
                                        changed_by=actor or "local_user",
                                    ),
                                )

                    engine = create_sqlite_engine(db_path)
                    try:
                        with session_scope(engine) as session:
                            relation_history = entity_relation_revision_rows(session, relation.relation_id)
                    finally:
                        engine.dispose()
                    with st.expander("Historial de esta relación", expanded=False):
                        for revision in reversed(relation_history):
                            st.caption(
                                f"v{revision.revision_number} · {revision.operation} · "
                                f"{revision.changed_by} · {revision.changed_at.isoformat(timespec='minutes')}"
                            )
                            if revision.note:
                                st.write(revision.note)

        st.divider()
        create_relation_open = st.toggle(
            "Crear una relación analítica",
            value=False,
            key=f"relation_create_panel_{selected.authority_id}",
            help=(
                "Registra un vínculo interpretativo sustentado por el corpus. "
                "Los roles archivísticos de productor o responsable de gestión se registran desde Catálogo."
            ),
        )
        if create_relation_open:
            with st.container(border=True):
                target_kind = st.selectbox(
                    "Tipo de registro con el que querés relacionar esta entidad",
                    options=list(RELATION_TARGET_KINDS),
                    format_func=lambda value: _RELATION_TARGET_LABELS[value],
                    key=f"relation_target_kind_{selected.authority_id}",
                )
                engine = create_sqlite_engine(db_path)
                try:
                    with session_scope(engine) as session:
                        targets = relation_target_choices(
                            session,
                            project_id=project_id,
                            target_kind=target_kind,
                            exclude_authority_id=selected.authority_id,
                        )
                finally:
                    engine.dispose()
                target_map = {target.target_id: target for target in targets}
                if not target_map:
                    st.info("No hay destinos disponibles de este tipo.")
                else:
                    with st.form(
                        f"relation_create_{selected.authority_id}_{target_kind}",
                        clear_on_submit=True,
                        enter_to_submit=False,
                    ):
                        relation_label = st.text_input(
                            "Cómo se relaciona esta entidad con el registro elegido",
                            placeholder="Ej.: integró, dependió de, aparece en",
                        )
                        target_id = st.selectbox(
                            "Registro con el que querés relacionar esta entidad",
                            options=list(target_map),
                            format_func=lambda value: (
                                f"{target_map[value].label}"
                                + (f" · {target_map[value].context}" if target_map[value].context else "")
                            ),
                        )
                        relation_category = st.selectbox(
                            "Categoría archivística de la relación (opcional)",
                            options=[""] + list(RELATION_ARCHIVAL_CATEGORIES),
                            format_func=lambda value: "Sin clasificar" if not value else _RELATION_CATEGORY_LABELS[value],
                        )
                        relation_context = st.text_area("Contexto de la relación (opcional)")
                        relation_description = st.text_area("Descripción de la relación (opcional)")
                        evidence_note = st.text_area(
                            "Evidencia documental o fundamento de esta relación", height=100
                        )
                        relation_temporal = st.text_input(
                            "Período de vigencia",
                            placeholder="Ej.: 03/1974 - 03/1976, 1975 o años setenta",
                        )
                        relation_temporal_note = st.text_area(
                            "Nota sobre el período de esta relación (opcional)",
                            placeholder="Fuente o grado de certeza.",
                            height=80,
                        )
                        relation_review = st.selectbox(
                            "Estado de revisión de esta relación",
                            options=list(RELATION_REVIEW_STATUSES),
                            format_func=lambda value: _REVIEW_LABELS[value],
                        )
                        relation_create_submit = st.form_submit_button(
                            "Crear esta relación", type="primary"
                        )
                    if relation_create_submit:
                        _run(
                            st,
                            db_path=db_path,
                            selection=selected.authority_id,
                            callback=lambda session: create_entity_relation(
                                session,
                                project_id=project_id,
                                source_authority_id=selected.authority_id,
                                relation_label=relation_label,
                                target_kind=target_kind,
                                target_id=target_id,
                                evidence_note=evidence_note,
                                profile_json={
                                    key: value
                                    for key, value in {
                                        "archival_category": relation_category,
                                        "context": relation_context.strip(),
                                        "description": relation_description.strip(),
                                    }.items()
                                    if value
                                },
                                temporal_expression=relation_temporal,
                                temporal_note=relation_temporal_note,
                                review_status=relation_review,
                                created_by=actor or "local_user",
                            ),
                        )

    with history_tab:
        engine = create_sqlite_engine(db_path)
        try:
            with session_scope(engine) as session:
                revisions = authority_revision_rows(session, selected.authority_id)
        finally:
            engine.dispose()
        for revision in reversed(revisions):
            with st.expander(
                f"Revisión {revision.revision_number} · {revision.operation} · "
                f"{revision.changed_by} · {revision.changed_at.isoformat(timespec='minutes')}"
            ):
                if revision.note:
                    st.write(revision.note)
                st.json(revision.snapshot_json)



def _render_dictionary_import(
    st,
    *,
    db_path: Path,
    project_id: str,
    actor: str,
) -> None:
    st.subheader("Exportar, editar e importar fichas de entidades y relaciones")
    st.caption(
        "Podés descargar las fichas actuales, editarlas fuera de Archive Workbench y volver a importarlas. "
        "La simulación distingue registros nuevos, reutilizados y actualizados; nada se guarda hasta que confirmes. "
        "La plantilla conserva los perfiles descriptivos, temporalidad, evidencia y nombres alternativos. Los alias "
        "que quites del archivo no se borran automáticamente: las eliminaciones siguen requiriendo una decisión explícita en la aplicación."
    )
    export_engine = create_sqlite_engine(db_path)
    try:
        with session_scope(export_engine) as session:
            current_template = export_authority_dictionary_bytes(
                session, project_id=project_id
            )
    finally:
        export_engine.dispose()
    download_current, download_example, download_schema = st.columns(3)
    with download_current:
        st.download_button(
            "Descargar fichas actuales para editar",
            data=current_template,
            file_name="fichas_entidades_relaciones.json",
            mime="application/json",
            use_container_width=True,
        )
    with download_example:
        st.download_button(
            "Descargar un ejemplo de archivo JSON",
            data=authority_dictionary_example_bytes(),
            file_name="diccionario_autoridades_ejemplo.json",
            mime="application/json",
            use_container_width=True,
        )
    with download_schema:
        st.download_button(
            "Descargar especificación técnica",
            data=authority_dictionary_schema_bytes(),
            file_name="authority_dictionary.schema.json",
            mime="application/schema+json",
            use_container_width=True,
        )

    uploaded = st.file_uploader(
        "Archivo JSON con fichas nuevas o editadas que querés revisar",
        type=["json"],
        key="authority_dictionary_upload",
    )
    if uploaded is None:
        st.info(
            "Elegí un archivo JSON para simular qué fichas y relaciones se crearían, reutilizarían o actualizarían. "
            "Si hay conflictos, Archive Workbench los muestra antes de permitir guardar cambios."
        )
        return

    content = uploaded.getvalue()
    engine = create_sqlite_engine(db_path)
    try:
        with session_scope(engine) as session:
            report = validate_authority_dictionary(
                session, project_id=project_id, source=content
            )
    except (ValueError, RuntimeError, OSError) as exc:
        st.error(str(exc))
        return
    finally:
        engine.dispose()

    st.write(f"**{report.dictionary_name}** · esquema {report.schema_version}")
    metrics = st.columns(7)
    metrics[0].metric("Entidades nuevas", report.authority_create_count)
    metrics[1].metric("Entidades actualizadas", report.authority_update_count)
    metrics[2].metric("Entidades reutilizadas", report.authority_reuse_count)
    metrics[3].metric("Alias nuevos", report.alias_add_count)
    metrics[4].metric("Relaciones nuevas", report.relation_create_count)
    metrics[5].metric("Relaciones actualizadas", report.relation_update_count)
    metrics[6].metric("Errores", report.error_count)

    st.download_button(
        "Descargar informe de simulación",
        data=(
            json.dumps(report.as_dict(), ensure_ascii=False, indent=2) + "\n"
        ).encode("utf-8"),
        file_name=f"{report.dictionary_id}_simulation.json",
        mime="application/json",
    )

    st.markdown("#### Entidades")
    st.dataframe(
        [
            {
                "ID local": plan.local_id,
                "Nombre principal de la entidad": plan.preferred_name,
                "Tipo": _TYPE_LABELS.get(plan.entity_type, plan.entity_type),
                "Acción": plan.action,
                "Ficha existente": plan.existing_authority_id or "",
                "Alias nuevos": ", ".join(alias.value for alias in plan.aliases_to_add),
            }
            for plan in report.authority_plans
        ],
        use_container_width=True,
        hide_index=True,
    )
    st.markdown("#### Relaciones")
    st.dataframe(
        [
            {
                "ID local": plan.local_id,
                "Relación": plan.relation_label,
                "Origen": plan.source_local_id,
                "Destino": plan.target_local_id or plan.target_id or "",
                "Acción": plan.action,
            }
            for plan in report.relation_plans
        ],
        use_container_width=True,
        hide_index=True,
    )

    if report.issues:
        st.markdown("#### Errores y advertencias")
        for issue in report.issues:
            location = issue.section
            if issue.item_id:
                location += f" · {issue.item_id}"
            if issue.field:
                location += f" · {issue.field}"
            message = f"{location}: {issue.message}"
            if issue.severity == "error":
                st.error(message)
            else:
                st.warning(message)

    with st.form("authority_dictionary_apply", enter_to_submit=False):
        confirmation = st.text_input(
            "Para guardar estos cambios en el proyecto, escribí IMPORTAR",
            key="authority_dictionary_confirmation",
        )
        submit = st.form_submit_button(
            "Guardar en el proyecto los datos de este diccionario",
            type="primary",
        )
    if submit:
        if confirmation.strip() != "IMPORTAR":
            st.error("La confirmación debe ser exactamente IMPORTAR.")
        elif not report.valid:
            st.error("El diccionario tiene errores y no puede aplicarse.")
        else:
            engine = create_sqlite_engine(db_path)
            try:
                with session_scope(engine) as session:
                    result = apply_authority_dictionary(
                        session,
                        project_id=project_id,
                        source=content,
                        changed_by=actor or "local_user",
                    )
            except (ValueError, RuntimeError, OSError) as exc:
                st.error(str(exc))
            else:
                st.success(
                    "Archivo importado: "
                    f"{result.authorities_created} entidades creadas, "
                    f"{result.authorities_updated} actualizadas, "
                    f"{result.authorities_reused} reutilizadas, "
                    f"{result.aliases_added} alias, "
                    f"{result.relations_created} relaciones nuevas y "
                    f"{result.relations_updated} relaciones actualizadas."
                )
            finally:
                engine.dispose()


def render_authorities_view(
    st,
    *,
    db_path: Path,
    project_id: str,
    actor: str,
) -> None:
    st.markdown(
        '## <abbr title="Ficha estable que identifica a una persona, organización, lugar, acontecimiento, obra u otro referente del corpus." style="text-decoration: underline dotted; text-underline-offset: .15em; cursor: help;">Entidades</abbr> y <abbr title="Referencia concreta a una entidad dentro de un documento o una transcripción." style="text-decoration: underline dotted; text-underline-offset: .15em; cursor: help;">menciones</abbr>',
        unsafe_allow_html=True,
    )
    mount_heading_help(
        st,
        label="Entidades y menciones",
        help_text=SECTION_HELP["Entidades y menciones"],
    )
    task = st.selectbox(
        "Tarea en Entidades y menciones",
        options=list(_AUTHORITY_TASK_LABELS),
        format_func=lambda value: _AUTHORITY_TASK_LABELS[value],
        key="authority_main_task",
        label_visibility="collapsed",
    )
    task_label = _AUTHORITY_TASK_LABELS[task]
    mount_choice_help(
        st,
        key="authority_main_task",
        label=task_label,
        help_text=TASK_HELP["authority_main_task"][task_label],
    )

    if task == "review":
        _render_authority_workspace(
            st,
            db_path=db_path,
            project_id=project_id,
            actor=actor,
        )
    elif task == "create":
        _render_authority_creation(
            st,
            db_path=db_path,
            project_id=project_id,
            actor=actor,
        )
    elif task == "import":
        _render_dictionary_import(
            st,
            db_path=db_path,
            project_id=project_id,
            actor=actor,
        )
    else:
        render_open_discovery_section(
            st,
            db_path=db_path,
            project_id=project_id,
            actor=actor,
        )

