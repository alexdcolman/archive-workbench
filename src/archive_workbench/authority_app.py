from __future__ import annotations

from datetime import date
from pathlib import Path

from archive_workbench.analysis_quality import analysis_quality_scope, quality_scope_caption
from archive_workbench.ui_navigation import rerun_app, rerun_view, tracked_tabs, request_app_view

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
    RELATION_LIFECYCLE_STATUSES,
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
_ALIAS_LABELS = {
    "variant": "Variante",
    "abbreviation": "Abreviatura",
    "acronym": "Sigla",
    "former_name": "Nombre anterior",
    "title": "Tratamiento / título",
    "other": "Otro",
}


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
    st.subheader("Crear una entidad")
    st.caption(
        "Creá una ficha canónica cuando ya conocés la referencia. "
        "Las sugerencias automáticas se revisan en Descubrimiento abierto."
    )
    with st.form("authority_create", clear_on_submit=True, enter_to_submit=False):
        entity_type = st.selectbox(
            "Tipo", options=list(AUTHORITY_TYPES), format_func=lambda value: _TYPE_LABELS[value]
        )
        preferred_name = st.text_input("Nombre preferido")
        description = st.text_area("Descripción / nota de identificación", height=100)
        temporal_expression = st.text_input(
            "Período de existencia o vigencia",
            placeholder="Ej.: 1930 - 1990, 03/1975, años setenta, desde 1974",
            help="Puede ser una fecha exacta, un mes, un año, una década, un rango o un intervalo abierto.",
        )
        temporal_note = st.text_area(
            "Nota temporal",
            placeholder="Fuente, duda o criterio usado para fechar la entidad.",
            height=80,
        )
        review_status = st.selectbox(
            "Estado de revisión",
            options=list(AUTHORITY_REVIEW_STATUSES),
            format_func=lambda value: _REVIEW_LABELS[value],
        )
        create_submit = st.form_submit_button("Crear entidad", type="primary")
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
    query = st.text_input("Buscar nombre, nombre alternativo o descripción", key="authority_query")
    with st.expander("Filtros de entidades", expanded=False):
        filter_left, filter_right = st.columns(2)
        with filter_left:
            selected_types = st.multiselect(
                "Tipos de entidad",
                options=list(AUTHORITY_TYPES),
                format_func=lambda value: _TYPE_LABELS[value],
                key="authority_types",
            )
            include_inactive = st.checkbox("Incluir entidades dadas de baja", value=False)
        with filter_right:
            filter_temporal = st.checkbox("Filtrar por período de existencia", value=False)
            temporal_cols = st.columns(2)
            temporal_start = temporal_cols[0].date_input(
                "Desde", value=date(1900, 1, 1), key="authority_temporal_start", disabled=not filter_temporal
            )
            temporal_end = temporal_cols[1].date_input(
                "Hasta", value=date.today(), key="authority_temporal_end", disabled=not filter_temporal
            )
            include_undated = st.checkbox(
                "Incluir entidades sin fecha",
                value=False,
                disabled=not filter_temporal,
            )

    engine = create_sqlite_engine(db_path)
    try:
        with session_scope(engine) as session:
            rows = authority_rows(
                session,
                project_id=project_id,
                query=query,
                entity_types=selected_types,
                lifecycle_statuses=("active", "inactive") if include_inactive else ("active",),
                temporal_start=temporal_start if filter_temporal else None,
                temporal_end=temporal_end if filter_temporal else None,
                include_undated=include_undated if filter_temporal else False,
            )
    except (ValueError, RuntimeError, OSError) as exc:
        st.error(str(exc))
        return
    finally:
        engine.dispose()

    st.caption(f"Entidades encontradas: {len(rows)}")
    if not rows:
        st.info(
            "Todavía no hay entidades con esos filtros. Podés cambiar la búsqueda, "
            "crear una entidad o abrir Descubrimiento abierto desde las tareas superiores."
        )
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
        format_func=lambda key: (
            f"{row_map[key].preferred_name} · {_TYPE_LABELS[row_map[key].entity_type]} · "
            f"{row_map[key].mention_count} menciones"
        ),
        key="authority_selected",
    )
    selected = row_map[selected_id]

    with st.expander("Resumen de la entidad", expanded=False):
        summary_cols = st.columns(4)
        summary_cols[0].metric("Tipo", _TYPE_LABELS[selected.entity_type])
        summary_cols[1].metric("Revisión", selected.revision)
        summary_cols[2].metric("Nombres alternativos", selected.alias_count)
        summary_cols[3].metric("Menciones", selected.mention_count)
        if selected.temporal_expression:
            st.caption(f"Período registrado: **{selected.temporal_expression}**")

    st.caption("Elegí qué aspecto de la entidad querés revisar o completar.")
    detail_tab, alias_tab, mentions_tab, relations_tab, history_tab = tracked_tabs(
        st,
        [
            "Datos de la entidad",
            "Nombres alternativos",
            "Menciones en documentos",
            "Relaciones",
            "Historial",
        ],
        key="authority_tabs",
    )
    with detail_tab:
        with st.form(f"authority_edit_{selected.authority_id}_{selected.revision}", enter_to_submit=False):
            entity_type_edit = st.selectbox(
                "Tipo",
                options=list(AUTHORITY_TYPES),
                index=list(AUTHORITY_TYPES).index(selected.entity_type),
                format_func=lambda value: _TYPE_LABELS[value],
            )
            name_edit = st.text_input("Nombre preferido", value=selected.preferred_name)
            description_edit = st.text_area(
                "Descripción / nota de identificación",
                value=selected.description or "",
                height=140,
            )
            temporal_expression_edit = st.text_input(
                "Período de existencia o vigencia",
                value=selected.temporal_expression or "",
                placeholder="Ej.: 1930 - 1990, 03/1975, años setenta, desde 1974",
            )
            temporal_note_edit = st.text_area(
                "Nota temporal", value=selected.temporal_note or "", height=80
            )
            if selected.temporal_start or selected.temporal_end:
                st.caption(
                    "Rango normalizado: "
                    f"{selected.temporal_start.isoformat() if selected.temporal_start else 'sin inicio'} → "
                    f"{selected.temporal_end.isoformat() if selected.temporal_end else 'sin final'}"
                )
            review_edit = st.selectbox(
                "Estado de revisión",
                options=list(AUTHORITY_REVIEW_STATUSES),
                index=list(AUTHORITY_REVIEW_STATUSES).index(selected.review_status),
                format_func=lambda value: _REVIEW_LABELS[value],
            )
            lifecycle_edit = st.selectbox(
                "Estado del registro",
                options=list(AUTHORITY_LIFECYCLE_STATUSES),
                index=list(AUTHORITY_LIFECYCLE_STATUSES).index(selected.lifecycle_status),
                format_func=lambda value: _LIFECYCLE_LABELS[value],
            )
            edit_note = st.text_input("Nota de modificación")
            edit_submit = st.form_submit_button("Guardar nueva revisión", type="primary")
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

    with alias_tab:
        if selected.aliases:
            for alias in selected.aliases:
                left, right = st.columns([6, 1])
                left.write(
                    f"**{alias.alias}** · {_ALIAS_LABELS.get(alias.alias_type, alias.alias_type)}"
                )
                if alias.note:
                    left.caption(alias.note)
                if right.button("×", key=f"authority_alias_remove_{alias.alias_id}"):
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
        else:
            st.caption("Sin nombres alternativos registrados")
        with st.form(f"authority_alias_add_{selected.authority_id}", clear_on_submit=True, enter_to_submit=False):
            alias_value = st.text_input("Nuevo nombre alternativo")
            alias_type = st.selectbox(
                "Tipo de nombre alternativo",
                options=list(ALIAS_TYPES),
                format_func=lambda value: _ALIAS_LABELS[value],
            )
            alias_note = st.text_input("Nota")
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

    with mentions_tab:
        st.subheader("Encontrar nuevas menciones en el corpus")
        surfaces = [selected.preferred_name] + [alias.alias for alias in selected.aliases]
        st.caption(
            "Busca el nombre preferido y todos sus nombres alternativos en los textos corregidos. "
            "No modifica nada hasta que selecciones qué coincidencias incorporar."
        )
        st.caption("Formas buscadas: " + " · ".join(f"`{item}`" for item in surfaces))
        with st.expander("Opciones de búsqueda", expanded=False):
            candidate_page_statuses = st.multiselect(
                "Estados de página incluidos",
                options=["unreviewed", "needs_review", "reviewed", "approved"],
                default=["approved"],
                format_func=lambda value: _REVIEW_LABELS[value],
                key=f"authority_candidate_page_statuses_{selected.authority_id}",
                help=(
                    "Por seguridad, la búsqueda automática usa solamente páginas aprobadas. "
                    "Dejá la selección vacía únicamente para buscar en todos los estados."
                ),
            )
        candidate_quality_scope = analysis_quality_scope(candidate_page_statuses)
        candidate_quality_reason = ""
        if candidate_quality_scope.is_default:
            st.caption(quality_scope_caption(candidate_page_statuses))
            candidate_quality_confirmed = False
        else:
            st.warning(quality_scope_caption(candidate_page_statuses))
            candidate_quality_confirmed = st.checkbox(
                "Confirmo que deseo buscar menciones en páginas no aprobadas",
                value=False,
                key=f"authority_candidate_quality_confirm_{selected.authority_id}",
            )
            candidate_quality_reason = st.text_area(
                "Fundamento del alcance ampliado",
                value="",
                placeholder=(
                    "Explicá por qué esta búsqueda debe incluir páginas que todavía no están aprobadas."
                ),
                key=f"authority_candidate_quality_reason_{selected.authority_id}",
                height=90,
            )
        search_col, reset_col = st.columns([2, 1])
        if search_col.button(
            "Buscar coincidencias",
            type="primary",
            key=f"authority_candidate_search_{selected.authority_id}",
        ):
            engine = create_sqlite_engine(db_path)
            try:
                with session_scope(engine) as session:
                    record_mention_suggestion_authorization(
                        session,
                        project_id=project_id,
                        page_review_statuses=tuple(candidate_page_statuses),
                        broader_quality_scope_confirmed=candidate_quality_confirmed,
                        quality_scope_reason=candidate_quality_reason or None,
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
                    "quality_scope_reason": candidate_quality_reason or None,
                }
            finally:
                engine.dispose()
        if reset_col.button(
            "Limpiar resultados", key=f"authority_candidate_clear_{selected.authority_id}"
        ):
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
                candidate_quality_reason or None,
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
            metric_cols = st.columns(4)
            metric_cols[0].metric("Coincidencias", len(candidates))
            metric_cols[1].metric("Por incorporar", len(actionable_candidates))
            metric_cols[2].metric("Ya incorporadas", len(already_candidates))
            metric_cols[3].metric("Conflictos", len(conflict_candidates))
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
                    else "No se encontraron el nombre preferido ni sus nombres alternativos en el corpus."
                )
            else:
                status_to_create = st.selectbox(
                    "Estado que se asignará a las nuevas menciones",
                    options=["pending", "accepted"],
                    format_func=lambda value: "Pendiente de revisión" if value == "pending" else "Aceptada",
                    key=f"authority_candidate_status_{selected.authority_id}",
                    help="Lo más seguro es incorporarlas como pendientes y revisarlas después.",
                )
                selected_keys: list[str] = []
                for candidate in visible:
                    alias_info = (
                        "nombre preferido"
                        if candidate.match_kind == "preferred"
                        else f"nombre alternativo · {_ALIAS_LABELS.get(candidate.alias_type or 'other', candidate.alias_type or 'otro')}"
                    )
                    with st.container(border=True):
                        pick_col, body_col, open_col = st.columns([0.5, 6, 1])
                        picked = pick_col.checkbox(
                            "Seleccionar",
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
                            f"objeto {candidate.order_index + 1} · coincidencia por {alias_info}: "
                            f"{candidate.matched_surface!r}"
                        )
                        if candidate.already_included:
                            body_col.success(
                                f"Ya incorporada · estado {candidate.existing_status or 'desconocido'}"
                            )
                        elif candidate.can_link_existing:
                            body_col.warning(
                                "Ya existe una mención sin autoridad sobre este fragmento; "
                                "al incorporarla se vinculará ese registro en lugar de duplicarlo."
                            )
                        elif candidate.has_authority_conflict:
                            body_col.error(
                                "El mismo fragmento ya está vinculado a "
                                f"{candidate.existing_authority_name or 'otra autoridad'}."
                            )
                        if open_col.button(
                            "Abrir",
                            key=f"authority_candidate_open_{candidate.candidate_key}",
                        ):
                            if candidate.source_key:
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

        st.divider()
        st.subheader("Menciones ya vinculadas")
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
                    f"objeto {mention.order_index + 1} · `{mention.status}`"
                )
                heading.caption(
                    f"{mention.document_title or '[sin título]'} · {mention.source_key or '[sin fuente]'}"
                )
                if mention.is_stale:
                    heading.warning(
                        "La mención pertenece a una revisión anterior del texto; debe verificarse."
                    )
                if action.button("Abrir", key=f"authority_open_mention_{mention.mention_id}"):
                    if mention.source_key:
                        request_app_view(
                            st,
                            mode="review",
                            source_key=mention.source_key,
                            page=mention.page_number,
                            object_id=mention.object_id,
                        )
                        rerun_app(st)

    with relations_tab:
        st.caption(
            "Una relación es una afirmación analítica explícita del equipo, por ejemplo: "
            "“integró”, “dependió de” o “aparece en”. No se crea automáticamente a partir de una mención."
        )
        relation_temporal_filter = st.checkbox(
            "Filtrar relaciones por período de vigencia",
            key=f"relation_temporal_filter_{selected.authority_id}",
        )
        relation_filter_cols = st.columns(3)
        relation_filter_start = relation_filter_cols[0].date_input(
            "Desde", value=date(1900, 1, 1),
            key=f"relation_filter_start_{selected.authority_id}",
            disabled=not relation_temporal_filter,
        )
        relation_filter_end = relation_filter_cols[1].date_input(
            "Hasta", value=date.today(),
            key=f"relation_filter_end_{selected.authority_id}",
            disabled=not relation_temporal_filter,
        )
        relation_include_undated = relation_filter_cols[2].checkbox(
            "Incluir sin fecha", value=False,
            key=f"relation_filter_undated_{selected.authority_id}",
            disabled=not relation_temporal_filter,
        )
        engine = create_sqlite_engine(db_path)
        try:
            with session_scope(engine) as session:
                relations = entity_relation_rows(
                    session,
                    project_id=project_id,
                    authority_id=selected.authority_id,
                    include_inactive=True,
                    temporal_start=relation_filter_start if relation_temporal_filter else None,
                    temporal_end=relation_filter_end if relation_temporal_filter else None,
                    include_undated=(relation_include_undated if relation_temporal_filter else False),
                )
        finally:
            engine.dispose()
        if not relations:
            st.caption("Todavía no hay relaciones explícitas para esta entidad.")
        for relation in relations:
            with st.expander(
                f"{relation.source_name} — {relation.relation_label} → {relation.target_label}"
            ):
                if relation.target_context:
                    st.caption(relation.target_context)
                if relation.evidence_note:
                    st.write(relation.evidence_note)
                if relation.temporal_expression:
                    st.write(f"**Vigencia:** {relation.temporal_expression}")
                if relation.temporal_note:
                    st.caption(relation.temporal_note)
                st.caption(
                    f"Revisión: {_REVIEW_LABELS.get(relation.review_status, relation.review_status)} · "
                    f"Estado: {_LIFECYCLE_LABELS.get(relation.lifecycle_status, relation.lifecycle_status)} · "
                    f"versión {relation.revision}"
                )
                change_target = st.checkbox(
                    "Cambiar destino",
                    key=f"relation_change_target_{relation.relation_id}_{relation.revision}",
                    help="El destino actual se conserva salvo que actives esta opción.",
                )
                relation_target_kind_edit = None
                relation_target_id_edit = None
                relation_target_map = {}
                if change_target:
                    relation_target_kind_edit = st.selectbox(
                        "Nuevo tipo de destino",
                        options=list(RELATION_TARGET_KINDS),
                        index=list(RELATION_TARGET_KINDS).index(relation.target_kind),
                        format_func=lambda value: {
                            "entity": "Otra entidad",
                            "archival_unit": "Unidad del catálogo",
                            "document_part": "Parte interna de un documento",
                        }[value],
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

                st.caption(
                    "Enter no guarda ni da de baja la relación: las acciones requieren pulsar "
                    "un botón explícito."
                )
                with st.form(
                    f"relation_edit_{relation.relation_id}_{relation.revision}",
                    enter_to_submit=False,
                ):
                    relation_label_edit = st.text_input(
                        "Tipo de relación", value=relation.relation_label,
                        key=f"relation_label_{relation.relation_id}",
                    )
                    if change_target and relation_target_map:
                        relation_target_id_edit = st.selectbox(
                            "Nuevo destino",
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
                    evidence_edit = st.text_area(
                        "Evidencia / fundamento",
                        value=relation.evidence_note or "",
                        key=f"relation_evidence_{relation.relation_id}",
                    )
                    relation_temporal_edit = st.text_input(
                        "Período de vigencia",
                        value=relation.temporal_expression or "",
                        placeholder="Ej.: 03/1974 - 03/1976 o años setenta",
                        key=f"relation_temporal_{relation.relation_id}",
                    )
                    relation_temporal_note_edit = st.text_area(
                        "Nota temporal",
                        value=relation.temporal_note or "",
                        key=f"relation_temporal_note_{relation.relation_id}",
                    )
                    relation_review_edit = st.selectbox(
                        "Estado de revisión",
                        options=list(RELATION_REVIEW_STATUSES),
                        index=list(RELATION_REVIEW_STATUSES).index(relation.review_status),
                        format_func=lambda value: _REVIEW_LABELS[value],
                        key=f"relation_review_{relation.relation_id}",
                    )
                    relation_lifecycle_edit = st.selectbox(
                        "Estado de la relación",
                        options=list(RELATION_LIFECYCLE_STATUSES),
                        index=list(RELATION_LIFECYCLE_STATUSES).index(relation.lifecycle_status),
                        format_func=lambda value: {
                            "active": "Activa",
                            "inactive": "Dada de baja",
                        }[value],
                        help="La baja es lógica: conserva la relación y todo su historial.",
                        key=f"relation_lifecycle_{relation.relation_id}",
                    )
                    relation_note = st.text_input(
                        "Nota de modificación", key=f"relation_note_{relation.relation_id}"
                    )
                    relation_update_submit = st.form_submit_button(
                        "Guardar cambios", type="primary"
                    )
                if relation_update_submit:
                    if change_target and relation_target_id_edit is None:
                        st.error("Elegí un nuevo destino o desactivá ‘Cambiar destino’.")
                    else:
                        _run(
                            st,
                            db_path=db_path,
                            selection=selected.authority_id,
                            callback=lambda session, relation=relation: update_entity_relation(
                                session,
                                relation_id=relation.relation_id,
                                expected_revision=relation.revision,
                                relation_label=relation_label_edit,
                                target_kind=(relation_target_kind_edit if change_target else None),
                                target_id=(relation_target_id_edit if change_target else None),
                                evidence_note=evidence_edit,
                                temporal_expression=relation_temporal_edit,
                                temporal_note=relation_temporal_note_edit,
                                review_status=relation_review_edit,
                                lifecycle_status=relation_lifecycle_edit,
                                note=relation_note,
                                changed_by=actor or "local_user",
                            ),
                        )
                engine = create_sqlite_engine(db_path)
                try:
                    with session_scope(engine) as session:
                        relation_history = entity_relation_revision_rows(
                            session, relation.relation_id
                        )
                finally:
                    engine.dispose()
                with st.expander("Historial de esta relación"):
                    for revision in reversed(relation_history):
                        st.caption(
                            f"v{revision.revision_number} · {revision.operation} · "
                            f"{revision.changed_by} · {revision.changed_at.isoformat(timespec='minutes')}"
                        )
                        if revision.note:
                            st.write(revision.note)

        st.divider()
        st.subheader("Crear una relación")
        target_kind_labels = {
            "entity": "Otra entidad",
            "archival_unit": "Unidad del catálogo",
            "document_part": "Parte interna de un documento",
        }
        target_kind = st.selectbox(
            "Relacionar con",
            options=list(RELATION_TARGET_KINDS),
            format_func=lambda value: target_kind_labels[value],
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
            st.caption(
                "Enter no crea la relación. Revisá los datos y pulsá el botón explícito al final."
            )
            with st.form(
                f"relation_create_{selected.authority_id}_{target_kind}",
                clear_on_submit=True,
                enter_to_submit=False,
            ):
                relation_label = st.text_input(
                    "Relación",
                    placeholder="Ej.: integró, dependió de, aparece en",
                )
                target_id = st.selectbox(
                    "Destino",
                    options=list(target_map),
                    format_func=lambda value: (
                        f"{target_map[value].label}"
                        + (f" · {target_map[value].context}" if target_map[value].context else "")
                    ),
                )
                evidence_note = st.text_area("Evidencia / fundamento", height=100)
                relation_temporal = st.text_input(
                    "Período de vigencia",
                    placeholder="Ej.: 03/1974 - 03/1976, 1975 o años setenta",
                )
                relation_temporal_note = st.text_area(
                    "Nota temporal", placeholder="Fuente o grado de certeza.", height=80
                )
                relation_review = st.selectbox(
                    "Estado de revisión",
                    options=list(RELATION_REVIEW_STATUSES),
                    format_func=lambda value: _REVIEW_LABELS[value],
                )
                relation_create_submit = st.form_submit_button(
                    "Crear relación definitivamente", type="primary"
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



def render_authorities_view(
    st,
    *,
    db_path: Path,
    project_id: str,
    actor: str,
) -> None:
    st.header("Entidades y menciones")
    st.caption(
        "Elegí una tarea: revisar fichas y menciones existentes, crear una entidad "
        "o descubrir referencias nuevas en el corpus."
    )
    with st.expander("Qué es una entidad", expanded=False):
        st.write(
            "Una entidad es la ficha canónica de una persona, organismo, lugar u otro referente. "
            "En archivística y bibliotecología también se la llama registro de autoridad: reúne "
            "el nombre preferido, sus variantes y las menciones documentales. Las coincidencias "
            "automáticas siempre quedan pendientes de revisión humana."
        )

    entities_tab, create_tab, discovery_tab = tracked_tabs(
        st,
        ["Revisar entidades", "Crear entidad", "Descubrimiento abierto"],
        key="authority_main_tasks",
        default="Revisar entidades",
    )

    with entities_tab:
        _render_authority_workspace(
            st,
            db_path=db_path,
            project_id=project_id,
            actor=actor,
        )

    with create_tab:
        _render_authority_creation(
            st,
            db_path=db_path,
            project_id=project_id,
            actor=actor,
        )

    with discovery_tab:
        render_open_discovery_section(
            st,
            db_path=db_path,
            project_id=project_id,
            actor=actor,
        )
