from __future__ import annotations

from archive_workbench.ui_help import TAB_HELP, TASK_HELP
from collections import defaultdict
from pathlib import Path

from sqlalchemy import select

from archive_workbench.analysis_quality import analysis_quality_scope
from archive_workbench.db import create_sqlite_engine, session_scope
from archive_workbench.db.models import AuthorityRecord, EditableObject
from archive_workbench.discovery_grouping import (
    CONTINUITY_METHODS,
    create_manual_group,
    discovery_group_rows,
    project_discovery_candidate,
    rebuild_discovery_groups,
    remove_candidate_from_group,
)
from archive_workbench.discovery_review import (
    accept_discovery_candidates_as_new_authorities,
    acceptance_mode_label,
    allowed_acceptance_modes,
    allowed_authority_types,
    candidate_status_label,
    decision_label,
    discovery_decision_rows,
    reject_discovery_candidates,
    restore_rejected_discovery_candidate,
    review_discovery_candidate,
)
from archive_workbench.open_discovery import (
    DISCOVERY_FAMILIES,
    DISCOVERY_PROVIDER_KEY,
    DISCOVERY_PROVIDER_VERSION,
    DiscoveryProfileValues,
    discovery_candidate_rows,
    discovery_profile_rows,
    discovery_run_rows,
    family_label,
    run_open_discovery,
    save_discovery_profile,
)
from archive_workbench.ui_navigation import mount_choice_help, request_tab, rerun_view, tracked_tabs

_PAGE_STATUS_LABELS = {
    "unreviewed": "Sin revisar",
    "needs_review": "Requiere revisión",
    "reviewed": "Revisada",
    "approved": "Aprobada",
}
_OBJECT_STATUS_LABELS = {
    "unreviewed": "Sin revisar",
    "needs_review": "Requiere revisión",
    "reviewed": "Revisado",
    "approved": "Aprobado",
}
_AUTHORITY_TYPE_LABELS = {
    "person": "Persona",
    "organization": "Organización",
    "place": "Lugar",
    "event": "Acontecimiento",
    "work": "Obra / publicación",
    "other": "Otra entidad",
}
_DECISION_OPTIONS = {
    "accept": "Aceptar esta referencia",
    "reject": "Descartar esta referencia",
}


def _discovery_rules_label(provider_key: str, provider_version: str) -> str:
    if provider_key == DISCOVERY_PROVIDER_KEY and provider_version.startswith("local_rules_v"):
        return f"reglas {provider_version.removeprefix('local_rules_')}"
    return f"{provider_key} · {provider_version}"


def _run_action(st, *, db_path: Path, callback) -> object | None:
    engine = create_sqlite_engine(db_path)
    try:
        with session_scope(engine) as session:
            return callback(session)
    except (ValueError, RuntimeError, OSError) as exc:
        st.error(str(exc))
        return None
    finally:
        engine.dispose()


def _render_profile_configuration(
    st,
    *,
    db_path: Path,
    project_id: str,
    actor: str,
    profiles,
    object_types,
):
    selected_profile = None
    profile_map = {row.id: row for row in profiles}
    pending_profile_id = st.session_state.pop("open_discovery_profile_selected__pending", None)
    if pending_profile_id in profile_map:
        st.session_state["open_discovery_profile_selected"] = pending_profile_id
    if profiles:
        selected_profile_id = st.selectbox(
            "Configuración para buscar entidades",
            options=list(profile_map),
            format_func=lambda value: profile_map[value].name,
            key="open_discovery_profile_selected",
        )
        selected_profile = profile_map[selected_profile_id]

    if selected_profile is not None:
        rules_label = _discovery_rules_label(
            selected_profile.provider_key, selected_profile.provider_version
        )
        if (
            selected_profile.provider_key == DISCOVERY_PROVIDER_KEY
            and selected_profile.provider_version != DISCOVERY_PROVIDER_VERSION
        ):
            current_label = _discovery_rules_label(
                DISCOVERY_PROVIDER_KEY, DISCOVERY_PROVIDER_VERSION
            )
            st.warning(
                f"Esta configuración usa {rules_label} históricas. "
                f"Las correcciones actuales de detección ({current_label}) no se aplican mientras siga usando esta versión."
            )
            if st.button(
                f"Actualizar esta configuración a {current_label}",
                type="primary",
                key=f"open_discovery_profile_upgrade_{selected_profile.id}_{selected_profile.revision}",
            ):
                stored_page_statuses = tuple(
                    selected_profile.include_page_review_statuses_json or ()
                )
                stored_quality_scope = analysis_quality_scope(stored_page_statuses)
                saved = _run_action(
                    st,
                    db_path=db_path,
                    callback=lambda session: save_discovery_profile(
                        session,
                        project_id=project_id,
                        profile_id=selected_profile.id,
                        values=DiscoveryProfileValues(
                            name=selected_profile.name,
                            description=selected_profile.description,
                            families=tuple(selected_profile.families_json or ()),
                            include_object_types=tuple(
                                selected_profile.include_object_types_json or ()
                            ),
                            include_object_review_statuses=tuple(
                                selected_profile.include_object_review_statuses_json or ()
                            ),
                            include_page_review_statuses=stored_page_statuses,
                            minimum_confidence=float(selected_profile.minimum_confidence),
                            provider_key=DISCOVERY_PROVIDER_KEY,
                            provider_version=DISCOVERY_PROVIDER_VERSION,
                        ),
                        changed_by=actor or "local_user",
                        broader_quality_scope_confirmed=(
                            stored_quality_scope.is_broader_than_default
                        ),
                        quality_scope_reason=(
                            "Actualización explícita de la configuración a las reglas de detección vigentes."
                            if stored_quality_scope.is_broader_than_default
                            else None
                        ),
                        quality_scope_source="ui",
                    ),
                )
                if saved is not None:
                    st.session_state["open_discovery_profile_selected__pending"] = saved.id
                    st.session_state["open_discovery_success"] = (
                        f"Configuración actualizada a {current_label}. Las búsquedas anteriores conservan sus reglas históricas."
                    )
                    rerun_view(st)
        else:
            st.caption(f"Versión de detección de esta configuración: {rules_label}.")

    profile_key = selected_profile.id if selected_profile else "new"

    profile_panel_open = st.toggle(
        "Configurar búsqueda de entidades",
        value=not profiles,
        key=f"open_discovery_profile_panel_{profile_key}",
    )
    if profile_panel_open:
        with st.container(border=True):
            default_name = selected_profile.name if selected_profile else "Descubrimiento local inicial"
            with st.container(horizontal=True, vertical_alignment="bottom", gap="small"):
                profile_name = st.text_input(
                    "Nombre de la configuración",
                    value=default_name,
                    key=f"open_discovery_profile_name_{profile_key}",
                    width="stretch",
                )
                profile_minimum_confidence = st.slider(
                    "Confianza mínima",
                    min_value=0.0,
                    max_value=1.0,
                    value=(
                        float(selected_profile.minimum_confidence)
                        if selected_profile
                        else 0.75
                    ),
                    step=0.01,
                    key=f"open_discovery_confidence_{profile_key}",
                    width=260,
                )
            profile_description = st.text_area(
                "Descripción (opcional)",
                value=(selected_profile.description or "") if selected_profile else "",
                height=70,
                key=f"open_discovery_profile_description_{profile_key}",
            )
            with st.container(horizontal=True, vertical_alignment="bottom", gap="small"):
                profile_families = st.multiselect(
                    "Tipos de referencia",
                    options=list(DISCOVERY_FAMILIES),
                    default=(
                        list(selected_profile.families_json or [])
                        if selected_profile
                        else list(DISCOVERY_FAMILIES[:-1])
                    ),
                    format_func=family_label,
                    key=f"open_discovery_profile_families_{profile_key}",
                    width="stretch",
                )
                profile_page_statuses = st.multiselect(
                    "Estado de las páginas",
                    options=list(_PAGE_STATUS_LABELS),
                    default=(
                        list(selected_profile.include_page_review_statuses_json or [])
                        if selected_profile
                        else ["approved"]
                    ),
                    format_func=lambda value: _PAGE_STATUS_LABELS[value],
                    help="Una selección vacía incluye páginas con cualquier estado de revisión.",
                    key=f"open_discovery_page_statuses_{profile_key}",
                    width="stretch",
                )
            with st.container(horizontal=True, vertical_alignment="bottom", gap="small"):
                profile_object_types = st.multiselect(
                    "Tipos de fragmento de texto",
                    options=list(object_types),
                    default=(
                        list(selected_profile.include_object_types_json or [])
                        if selected_profile
                        else []
                    ),
                    help="Una selección vacía incluye todos los tipos de fragmento de texto.",
                    key=f"open_discovery_object_types_{profile_key}",
                    width="stretch",
                )
                profile_object_statuses = st.multiselect(
                    "Estado de revisión del texto",
                    options=list(_OBJECT_STATUS_LABELS),
                    default=(
                        list(selected_profile.include_object_review_statuses_json or [])
                        if selected_profile
                        else []
                    ),
                    format_func=lambda value: _OBJECT_STATUS_LABELS[value],
                    help="Una selección vacía incluye fragmentos de texto con cualquier estado de revisión.",
                    key=f"open_discovery_object_statuses_{profile_key}",
                    width="stretch",
                )

            quality_scope = analysis_quality_scope(profile_page_statuses)
            quality_confirmed = quality_scope.is_broader_than_default
            quality_reason = (
                "Estados de revisión de página elegidos explícitamente en Buscar nuevas entidades."
                if quality_confirmed
                else None
            )
            if st.button(
                "Guardar configuración de búsqueda",
                type="primary",
                key=f"open_discovery_profile_save_{profile_key}",
            ):
                saved = _run_action(
                    st,
                    db_path=db_path,
                    callback=lambda session: save_discovery_profile(
                        session,
                        project_id=project_id,
                        profile_id=selected_profile.id if selected_profile else None,
                        values=DiscoveryProfileValues(
                            name=profile_name,
                            description=profile_description,
                            families=tuple(profile_families),
                            include_object_types=tuple(profile_object_types),
                            include_object_review_statuses=tuple(profile_object_statuses),
                            include_page_review_statuses=tuple(profile_page_statuses),
                            minimum_confidence=float(profile_minimum_confidence),
                            provider_key=(
                                selected_profile.provider_key
                                if selected_profile
                                else DISCOVERY_PROVIDER_KEY
                            ),
                            provider_version=(
                                selected_profile.provider_version
                                if selected_profile
                                else DISCOVERY_PROVIDER_VERSION
                            ),
                        ),
                        changed_by=actor or "local_user",
                        broader_quality_scope_confirmed=quality_confirmed,
                        quality_scope_reason=quality_reason,
                        quality_scope_source="ui",
                    ),
                )
                if saved is not None:
                    st.session_state["open_discovery_profile_selected__pending"] = saved.id
                    st.session_state["open_discovery_success"] = (
                        "Configuración de búsqueda guardada."
                    )
                    rerun_view(st)
    return selected_profile


def _render_decision_history(st, decisions) -> None:
    if not decisions:
        return
    with st.expander("Historial de decisiones", expanded=False):
        for item in sorted(decisions, key=lambda row: row.decision_number):
            st.write(
                f"**{item.decision_number}. {item.decision_label}** · "
                f"{item.reviewed_text} · {item.family_label}/{item.reviewed_subtype}"
            )
            details = [f"responsable: {item.decided_by}", f"origen: {item.source}"]
            if item.acceptance_label:
                details.append(f"destino: {item.acceptance_label}")
            if item.target_authority_name:
                details.append(f"entidad vinculada: {item.target_authority_name}")
            st.caption(" · ".join(details))
            if item.reason:
                st.caption(f"Fundamento: {item.reason}")


def _render_candidate_review(
    st,
    *,
    db_path: Path,
    project_id: str,
    actor: str,
    row,
    decisions,
    authorities,
) -> None:
    if row.status in {"accepted", "rejected"}:
        return

    review_panel_open = st.toggle(
        "Revisar esta referencia encontrada",
        value=False,
        key=f"discovery_candidate_review_panel_{row.candidate_id}",
        help="Abrí este panel para aceptar la referencia o descartarla.",
    )
    if not review_panel_open:
        return

    with st.container(border=True):
        if row.is_stale:
            st.warning(
                "El texto del documento cambió después de esta búsqueda. Antes de decidir sobre esta referencia, actualizá su ubicación desde «Duplicados y cambios de texto»."
            )
            return

        decision_type = st.radio(
            "Qué querés hacer con esta referencia",
            options=("accept", "reject"),
            format_func=lambda value: _DECISION_OPTIONS[value],
            horizontal=True,
            key=f"discovery_decision_type_{row.candidate_id}",
        )

        reviewed_text = row.effective_text
        reviewed_family = row.effective_family
        reviewed_subtype = row.effective_subtype
        acceptance_mode = None
        authority_id = None
        new_authority_name = None
        description = None
        temporal_expression = None
        confirm_new_authority = False

        if decision_type == "accept":
            correct_before_accept = st.checkbox(
                "Corregir el texto o el tipo antes de aceptar esta referencia",
                value=False,
                key=f"discovery_correct_before_accept_{row.candidate_id}",
            )
            if correct_before_accept:
                reviewed_text = st.text_input(
                    "Texto correcto de esta referencia",
                    value=row.effective_text,
                    key=f"discovery_reviewed_text_{row.candidate_id}",
                )
                reviewed_family = st.selectbox(
                    "Tipo general correcto de esta referencia",
                    options=list(DISCOVERY_FAMILIES),
                    index=list(DISCOVERY_FAMILIES).index(row.effective_family),
                    format_func=family_label,
                    key=f"discovery_reviewed_family_{row.candidate_id}",
                )
                reviewed_subtype = st.text_input(
                    "Tipo específico correcto de esta referencia",
                    value=row.effective_subtype,
                    key=f"discovery_reviewed_subtype_{row.candidate_id}",
                )

            modes = allowed_acceptance_modes(reviewed_family)
            acceptance_mode = st.radio(
                "Qué querés crear o vincular al aceptar esta referencia",
                options=list(modes),
                format_func=acceptance_mode_label,
                key=f"discovery_acceptance_mode_{row.candidate_id}",
            )
            if acceptance_mode == "existing_authority":
                compatible_types = allowed_authority_types(reviewed_family, reviewed_subtype)
                choices = [item for item in authorities if item.entity_type in compatible_types]
                if choices:
                    choice_map = {item.id: item for item in choices}
                    authority_id = st.selectbox(
                        "Entidad existente que corresponde a esta referencia",
                        options=list(choice_map),
                        format_func=lambda value: (
                            f"{choice_map[value].preferred_name} · "
                            f"{_AUTHORITY_TYPE_LABELS.get(choice_map[value].entity_type, choice_map[value].entity_type)} · "
                            f"{_OBJECT_STATUS_LABELS.get(choice_map[value].review_status, choice_map[value].review_status)}"
                        ),
                        key=f"discovery_authority_{row.candidate_id}",
                    )
                else:
                    st.warning("No hay entidades activas compatibles en este proyecto.")
            elif acceptance_mode == "new_authority":
                new_authority_name = st.text_input(
                    "Nombre de la nueva entidad",
                    value=reviewed_text,
                    key=f"discovery_new_authority_name_{row.candidate_id}",
                )
                description = st.text_area(
                    "Descripción inicial de la nueva entidad (opcional)",
                    value="",
                    height=80,
                    key=f"discovery_new_authority_description_{row.candidate_id}",
                )
                if reviewed_family == "event":
                    temporal_expression = st.text_input(
                        "Expresión temporal del acontecimiento (opcional)",
                        value="",
                        key=f"discovery_new_authority_temporal_{row.candidate_id}",
                    )
                confirm_new_authority = st.checkbox(
                    "Confirmo que quiero crear esta entidad con estado Sin revisar",
                    value=False,
                    key=f"discovery_new_authority_confirm_{row.candidate_id}",
                )
            else:
                description = st.text_area(
                    "Descripción adicional para esta referencia aceptada (opcional)",
                    value="",
                    height=80,
                    key=f"discovery_context_description_{row.candidate_id}",
                )
                if reviewed_family in {"time", "event"}:
                    temporal_expression = st.text_input(
                        "Expresión temporal (opcional)",
                        value=(reviewed_text if reviewed_family == "time" else ""),
                        key=f"discovery_context_temporal_{row.candidate_id}",
                    )

        note = st.text_area(
            "Nota sobre esta decisión (opcional)",
            value="",
            height=70,
            key=f"discovery_decision_note_{row.candidate_id}_{decision_type}",
        )
        button_label = (
            "Aceptar esta referencia" if decision_type == "accept" else "Descartar esta referencia"
        )
        if st.button(
            button_label,
            type="primary" if decision_type == "accept" else "secondary",
            key=f"discovery_decision_submit_{row.candidate_id}_{decision_type}",
        ):
            result = _run_action(
                st,
                db_path=db_path,
                callback=lambda session: review_discovery_candidate(
                    session,
                    project_id=project_id,
                    candidate_id=row.candidate_id,
                    decision_type=decision_type,
                    decided_by=actor or "local_user",
                    reason=note or None,
                    reviewed_text=reviewed_text,
                    semantic_family=reviewed_family,
                    reviewed_subtype=reviewed_subtype,
                    acceptance_mode=acceptance_mode,
                    authority_id=authority_id,
                    new_authority_name=new_authority_name,
                    description=description,
                    temporal_expression=temporal_expression,
                    confirm_new_authority=confirm_new_authority,
                    source="ui",
                ),
            )
            if result is not None:
                st.session_state["open_discovery_decision_success"] = (
                    "Referencia aceptada." if decision_type == "accept" else "Referencia descartada. Podés restaurarla desde «Referencias descartadas»."
                )
                rerun_view(st)



def _render_grouping_and_continuity(
    st,
    *,
    db_path: Path,
    project_id: str,
    actor: str,
) -> None:
    groups_tab, continuity_tab = tracked_tabs(
        st,
        ["Revisar posibles referencias repetidas", "Actualizar referencias después de corregir el texto"],
        key="open_discovery_grouping_tasks",
        help_by_label=TAB_HELP["open_discovery_grouping_tasks"],
        default="Revisar posibles referencias repetidas",
    )

    with groups_tab:
        if st.button(
            "Buscar referencias que podrían corresponder al mismo referente",
            key="open_discovery_grouping_rebuild",
        ):
            summary = _run_action(
                st,
                db_path=db_path,
                callback=lambda session: rebuild_discovery_groups(
                    session,
                    project_id=project_id,
                    created_by=actor or "local_user",
                    source="ui",
                ),
            )
            if summary is not None:
                st.session_state["open_discovery_grouping_success"] = (
                    f"Agrupamiento actualizado: {summary.groups_created} grupos nuevos y {summary.memberships_created} referencias incorporadas a esos grupos."
                )
                rerun_view(st)

        success = st.session_state.pop("open_discovery_grouping_success", None)
        if success:
            st.success(success)

        engine = create_sqlite_engine(db_path)
        try:
            with session_scope(engine) as session:
                groups = discovery_group_rows(
                    session, project_id=project_id, include_removed=True
                )
                all_candidates = discovery_candidate_rows(
                    session, project_id=project_id, limit=10_000
                )
        finally:
            engine.dispose()

        if groups:
            group_map = {row.group_id: row for row in groups}
            pending_group_id = st.session_state.pop(
                "open_discovery_group_pending_selection", None
            )
            if pending_group_id in group_map:
                st.session_state["open_discovery_group_selected"] = pending_group_id
            elif st.session_state.get("open_discovery_group_selected") not in group_map:
                st.session_state["open_discovery_group_selected"] = next(iter(group_map))
            selected_group_id = st.selectbox(
                "Grupo de referencias que querés revisar",
                options=list(group_map),
                format_func=lambda value: (
                    f"{group_map[value].preferred_label} · "
                    f"{family_label(group_map[value].semantic_family)} · "
                    f"{group_map[value].active_member_count} miembros"
                ),
                key="open_discovery_group_selected",
            )
            selected_group = group_map[selected_group_id]
            st.caption(f"Referencias vigentes en este grupo: {selected_group.active_member_count} · referencias que necesitan volver a ubicarse: {selected_group.stale_member_count}")
            for member in selected_group.members:
                status = "separado" if member.membership_status != "active" else "activo"
                stale = " · obsoleto" if member.is_stale else ""
                st.write(f"- **{member.effective_text}** · {status}{stale} · {member.original_filename}, página {member.page_number}")

            active_members = [
                row for row in selected_group.members if row.membership_status == "active"
            ]
            if len(active_members) > 1:
                remove_map = {row.candidate_id: row for row in active_members}
                remove_candidate_id = st.selectbox(
                    "Referencia encontrada que no corresponde a este grupo",
                    options=list(remove_map),
                    format_func=lambda value: (
                        f"{remove_map[value].effective_text} · "
                        f"{remove_map[value].original_filename}, p. {remove_map[value].page_number}"
                    ),
                    key=f"open_discovery_group_remove_candidate_{selected_group_id}",
                )
                remove_reason = st.text_area(
                    "Por qué esta referencia debe quedar fuera del grupo",
                    value="",
                    height=70,
                    key=f"open_discovery_group_remove_reason_{selected_group_id}",
                )
                if st.button(
                    "Quitar esta referencia del grupo",
                    key=f"open_discovery_group_remove_submit_{selected_group_id}",
                ):
                    result = _run_action(
                        st,
                        db_path=db_path,
                        callback=lambda session: remove_candidate_from_group(
                            session,
                            project_id=project_id,
                            group_id=selected_group_id,
                            candidate_id=remove_candidate_id,
                            changed_by=actor or "local_user",
                            reason=remove_reason,
                            source="ui",
                        ),
                    )
                    if result is not None:
                        st.session_state["open_discovery_grouping_success"] = (
                            "La referencia fue quitada del grupo. Su búsqueda de origen y las decisiones anteriores siguen registradas."
                        )
                        rerun_view(st)
        else:
            st.caption("Todavía no hay referencias agrupadas. Podés detectar agrupaciones posibles o crear un grupo de forma manual.")

        manual_open = st.toggle(
            "Crear un grupo de referencias de forma manual",
            value=False,
            key="open_discovery_manual_group_panel",
        )
        if manual_open:
            candidate_map = {row.candidate_id: row for row in all_candidates}
            manual_ids = st.multiselect(
                "Referencias encontradas que querés reunir en este grupo",
                options=list(candidate_map),
                format_func=lambda value: (
                    f"{candidate_map[value].effective_text} · {candidate_map[value].original_filename}, página {candidate_map[value].page_number}"
                ),
                key="open_discovery_manual_group_candidates",
            )
            manual_label = st.text_input(
                "Nombre con el que identificarás este grupo",
                key="open_discovery_manual_group_label",
            )
            manual_family = st.selectbox(
                "Tipo de referencias reunidas en este grupo",
                options=list(DISCOVERY_FAMILIES),
                format_func=family_label,
                key="open_discovery_manual_group_family",
            )
            manual_reason = st.text_area(
                "Por qué estas referencias deben revisarse juntas",
                height=70,
                key="open_discovery_manual_group_reason",
            )
            if st.button(
                "Crear un grupo de referencias de forma manual",
                key="open_discovery_manual_group_submit",
            ):
                group = _run_action(
                    st,
                    db_path=db_path,
                    callback=lambda session: create_manual_group(
                        session,
                        project_id=project_id,
                        candidate_ids=manual_ids,
                        preferred_label=manual_label,
                        semantic_family=manual_family,
                        created_by=actor or "local_user",
                        reason=manual_reason,
                        source="ui",
                    ),
                )
                if group is not None:
                    st.session_state[
                        "open_discovery_group_pending_selection"
                    ] = group.id
                    st.session_state["open_discovery_grouping_success"] = (
                        "Grupo creado. Las referencias siguen siendo registros independientes y conservan su procedencia."
                    )
                    rerun_view(st)

    with continuity_tab:
        engine = create_sqlite_engine(db_path)
        try:
            with session_scope(engine) as session:
                all_candidates = discovery_candidate_rows(
                    session, project_id=project_id, limit=10_000
                )
        finally:
            engine.dispose()
        stale = [row for row in all_candidates if row.is_stale]
        if not stale:
            st.caption("No hay referencias encontradas que hayan quedado desactualizadas por cambios posteriores en el texto.")
        else:
            stale_map = {row.candidate_id: row for row in stale}
            source_candidate_id = st.selectbox(
                "Referencia que quedó desactualizada después de editar el texto",
                options=list(stale_map),
                format_func=lambda value: (
                    f"{stale_map[value].effective_text} · "
                    f"{stale_map[value].original_filename}, p. {stale_map[value].page_number} · "
                    f"versión del texto {stale_map[value].object_revision_number}"
                ),
                key="open_discovery_continuity_candidate",
            )
            method = st.radio(
                "Cómo buscar esta misma referencia en el texto corregido",
                options=list(CONTINUITY_METHODS),
                format_func=lambda value: (
                    "Buscar exactamente el mismo texto en la versión corregida"
                    if value == "exact_projection"
                    else "Volver a buscar esa referencia cerca de su ubicación anterior"
                ),
                key="open_discovery_continuity_method",
            )
            if st.button(
                "Buscar esta referencia en el texto corregido",
                key="open_discovery_continuity_submit",
            ):
                summary = _run_action(
                    st,
                    db_path=db_path,
                    callback=lambda session: project_discovery_candidate(
                        session,
                        project_id=project_id,
                        candidate_id=source_candidate_id,
                        method=method,
                        created_by=actor or "local_user",
                    ),
                )
                if summary is not None:
                    st.session_state["open_discovery_continuity_success"] = (
                        f"Continuidad creada: revisión {summary.target_revision}, "
                        f"offsets {summary.target_start_offset}:{summary.target_end_offset}."
                    )
                    rerun_view(st)
        continuity_success = st.session_state.pop(
            "open_discovery_continuity_success", None
        )
        if continuity_success:
            st.success(continuity_success)

def _render_discovery_run_setup(
    st,
    *,
    db_path: Path,
    project_id: str,
    actor: str,
) -> None:
    engine = create_sqlite_engine(db_path)
    try:
        with session_scope(engine) as session:
            profiles = discovery_profile_rows(session, project_id=project_id)
            object_types = session.scalars(
                select(EditableObject.current_object_type)
                .where(EditableObject.lifecycle_status == "active")
                .distinct()
                .order_by(EditableObject.current_object_type)
            ).all()
    finally:
        engine.dispose()

    selected_profile = _render_profile_configuration(
        st,
        db_path=db_path,
        project_id=project_id,
        actor=actor,
        profiles=profiles,
        object_types=object_types,
    )

    success = st.session_state.pop("open_discovery_success", None)
    if success:
        st.success(success)

    if selected_profile is None:
        st.info("Creá y guardá una configuración de búsqueda para iniciar la primera búsqueda.")
        return

    if (
        selected_profile.provider_key == DISCOVERY_PROVIDER_KEY
        and selected_profile.provider_version != DISCOVERY_PROVIDER_VERSION
    ):
        st.info(
            "Para ejecutar una búsqueda nueva desde la interfaz, actualizá primero esta configuración a las reglas vigentes. "
            "Las búsquedas históricas siguen disponibles para consulta y no se recalculan."
        )
        return

    if st.button(
        "Buscar nuevas entidades en los textos",
        type="primary",
        key=f"open_discovery_run_{selected_profile.id}_{selected_profile.revision}",
    ):
        summary = _run_action(
            st,
            db_path=db_path,
            callback=lambda session: run_open_discovery(
                session,
                project_id=project_id,
                profile=session.get(type(selected_profile), selected_profile.id),
                created_by=actor or "local_user",
            ),
        )
        if summary is not None:
            st.session_state["open_discovery_run_selected"] = summary.run_id
            st.session_state["open_discovery_run_success"] = (
                f"Búsqueda de entidades completada: {summary.candidate_count} referencias encontradas en "
                f"{summary.object_count} fragmentos de texto."
            )
            st.session_state["open_discovery_task__pending"] = "review"
            rerun_view(st)


def _render_discovery_candidate_workspace(
    st,
    *,
    db_path: Path,
    project_id: str,
    actor: str,
) -> None:
    run_success = st.session_state.pop("open_discovery_run_success", None)
    if run_success:
        st.success(run_success)
    decision_success = st.session_state.pop("open_discovery_decision_success", None)
    if decision_success:
        st.success(decision_success)

    engine = create_sqlite_engine(db_path)
    try:
        with session_scope(engine) as session:
            runs = discovery_run_rows(session, project_id=project_id, limit=25)
            authorities = session.scalars(
                select(AuthorityRecord)
                .where(
                    AuthorityRecord.project_id == project_id,
                    AuthorityRecord.lifecycle_status == "active",
                )
                .order_by(AuthorityRecord.normalized_name, AuthorityRecord.id)
            ).all()
    finally:
        engine.dispose()

    if not runs:
        st.info(
            "Todavía no hay búsquedas de nuevas entidades ejecutadas. Elegí «Ejecutar búsqueda de entidades» para crear la primera."
        )
        return

    run_map = {row.run_id: row for row in runs}
    current_run = st.session_state.get("open_discovery_run_selected")
    if current_run not in run_map:
        st.session_state["open_discovery_run_selected"] = runs[0].run_id

    with st.container(horizontal=True, vertical_alignment="bottom", gap="small"):
        selected_run_id = st.selectbox(
            "Búsqueda de entidades",
            options=list(run_map),
            format_func=lambda value: (
                f"{run_map[value].started_at.isoformat(timespec='minutes')} · "
                f"{run_map[value].profile_name} · "
                f"{_discovery_rules_label(run_map[value].provider_key, run_map[value].provider_version)} · "
                f"{run_map[value].candidate_count} referencias"
            ),
            key="open_discovery_run_selected",
            width="stretch",
        )
        candidate_families = st.multiselect(
            "Tipos de referencia",
            options=list(DISCOVERY_FAMILIES),
            default=[],
            format_func=family_label,
            placeholder="Todos los tipos",
            key=f"open_discovery_candidate_family_filter_{selected_run_id}",
            width="stretch",
        )

    selected_run = run_map[selected_run_id]
    selected_rules_label = _discovery_rules_label(
        selected_run.provider_key, selected_run.provider_version
    )
    if (
        selected_run.provider_key == DISCOVERY_PROVIDER_KEY
        and selected_run.provider_version != DISCOVERY_PROVIDER_VERSION
    ):
        st.caption(
            f"Esta búsqueda fue generada con {selected_rules_label} históricas. Instalar reglas nuevas no modifica sus referencias ya registradas."
        )
    else:
        st.caption(f"Esta búsqueda fue generada con {selected_rules_label}.")

    engine = create_sqlite_engine(db_path)
    try:
        with session_scope(engine) as session:
            candidates = discovery_candidate_rows(
                session,
                project_id=project_id,
                run_id=selected_run_id,
                limit=None,
            )
            decisions = discovery_decision_rows(
                session, project_id=project_id, limit=10_000
            )
    finally:
        engine.dispose()

    if not candidates:
        st.info("Esta búsqueda no encontró referencias con la configuración elegida.")
        return

    decisions_by = defaultdict(list)
    for item in decisions:
        decisions_by[item.candidate_id].append(item)

    matching_candidates = [
        row
        for row in candidates
        if not candidate_families or row.effective_family in candidate_families
    ]
    active_candidates_all = [
        row for row in matching_candidates if row.status not in {"accepted", "rejected"}
    ]
    rejected_candidates_all = [
        row for row in matching_candidates if row.status == "rejected"
    ]
    accepted_candidate_count = sum(
        row.status == "accepted" for row in matching_candidates
    )

    display_choice = st.selectbox(
        "Cuántas referencias mostrar",
        options=("100", "250", "500", "1000", "Todas"),
        index=2,
        key=f"open_discovery_visible_candidate_limit_{selected_run_id}",
        help=(
            "Controla cuántas referencias pendientes y descartadas se dibujan en esta vista. "
            "El total de la búsqueda y el total que coincide con los filtros se muestran siempre."
        ),
    )
    visible_limit = None if display_choice == "Todas" else int(display_choice)
    active_candidates = (
        active_candidates_all
        if visible_limit is None
        else active_candidates_all[:visible_limit]
    )
    rejected_candidates = (
        rejected_candidates_all
        if visible_limit is None
        else rejected_candidates_all[:visible_limit]
    )

    total_count = len(candidates)
    matching_count = len(matching_candidates)
    count_summary = (
        "Esta búsqueda contiene "
        f"{total_count:,} referencias en total. "
        f"Con los tipos elegidos coinciden {matching_count:,}: "
        f"{len(active_candidates_all):,} referencias pendientes, "
        f"{accepted_candidate_count:,} referencias aceptadas y "
        f"{len(rejected_candidates_all):,} referencias descartadas."
    )
    st.caption(count_summary.replace(",", "."))

    review_modes_key = f"open_discovery_review_modes_{selected_run_id}"
    pending_tab, bulk_tab, discarded_tab = tracked_tabs(
        st,
        [
            "Revisar una por una",
            "Trabajar con varias referencias",
            "Referencias descartadas",
        ],
        key=review_modes_key,
        default="Revisar una por una",
        help_by_label=TAB_HELP["open_discovery_review_modes"],
    )

    with pending_tab:
        st.badge(
            f"Mostrando {len(active_candidates):,} de {len(active_candidates_all):,} referencias pendientes".replace(",", "."),
            color="primary",
        )
        if not active_candidates:
            st.info("No hay referencias pendientes que coincidan con los tipos seleccionados.")
        for row in active_candidates:
            with st.container(border=True):
                with st.container(horizontal=True, vertical_alignment="center", gap="small"):
                    st.markdown(
                        f"**{row.effective_text}** · {family_label(row.effective_family)} / "
                        f"{row.effective_subtype} · **{candidate_status_label(row.status)}**"
                    )
                    st.badge(
                        "Confianza —" if row.confidence is None else f"Confianza {row.confidence:.2f}",
                        color="gray",
                    )
                st.caption(
                    f"{row.original_filename} · página {row.page_number} · versión del texto {row.object_revision_number}"
                )
                st.write(
                    f"…{row.context_before}**{row.exact_text}**{row.context_after}…"
                )
                if (
                    row.effective_text != row.exact_text
                    or row.effective_family != row.semantic_family
                ):
                    st.caption(
                        "Referencia encontrada originalmente: "
                        f"{row.exact_text} · {row.family_label}/{row.suggested_subtype}"
                    )
                if row.is_stale:
                    st.warning(
                        "El texto del documento cambió después de esta búsqueda. Actualizá la ubicación de esta referencia desde «Duplicados y cambios de texto» antes de decidir."
                    )
                _render_candidate_review(
                    st,
                    db_path=db_path,
                    project_id=project_id,
                    actor=actor,
                    row=row,
                    decisions=decisions_by.get(row.candidate_id, []),
                    authorities=authorities,
                )
                _render_decision_history(
                    st, decisions_by.get(row.candidate_id, [])
                )
                with st.expander("Trazabilidad técnica", expanded=False):
                    st.write(row.explanation)
                    st.code(
                        "\n".join(
                            [
                                f"candidate_id={row.candidate_id}",
                                f"run_id={row.run_id}",
                                f"editable_page_id={row.editable_page_id}",
                                f"page_revision_number={row.page_revision_number}",
                                f"provider={row.provider_key}",
                                f"provider_version={row.provider_version}",
                                f"method={row.method}",
                                f"parameters_sha256={row.parameters_sha256}",
                                f"decision_count={row.decision_count}",
                            ]
                        )
                    )

    with bulk_tab:
        st.caption("Seleccioná referencias y elegí una acción para todo el conjunto.")
        active_map = {
            row.candidate_id: row for row in active_candidates if not row.is_stale
        }
        if not active_map:
            st.info(
                "No hay referencias pendientes disponibles para crear entidades o descartar en conjunto con los tipos seleccionados."
            )
        else:
            with st.form(
                f"open_discovery_bulk_form_{selected_run_id}",
                enter_to_submit=False,
            ):
                selected_bulk_ids = st.multiselect(
                    "Referencias pendientes que querés seleccionar",
                    options=list(active_map),
                    format_func=lambda value: (
                        f"{active_map[value].effective_text} · "
                        f"{family_label(active_map[value].effective_family)} · "
                        f"{active_map[value].original_filename}, p. {active_map[value].page_number}"
                    ),
                    key=f"open_discovery_bulk_candidates_{selected_run_id}",
                )
                confirm_bulk = st.checkbox(
                    "Confirmo que quiero aplicar a todas las referencias seleccionadas la acción del botón que pulse",
                    value=False,
                    key=f"open_discovery_bulk_confirm_{selected_run_id}",
                )
                create_column, reject_column = st.columns(2)
                with create_column:
                    bulk_create_submit = st.form_submit_button(
                        "Crear una entidad Sin revisar por cada referencia seleccionada",
                        type="primary",
                        use_container_width=True,
                    )
                with reject_column:
                    bulk_reject_submit = st.form_submit_button(
                        "Descartar las referencias seleccionadas",
                        use_container_width=True,
                    )

            if bulk_create_submit or bulk_reject_submit:
                if not selected_bulk_ids:
                    st.error("Seleccioná al menos una referencia antes de confirmar esta acción.")
                elif not confirm_bulk:
                    st.error(
                        "Marcá la confirmación antes de crear entidades o descartar las referencias seleccionadas."
                    )
                elif bulk_create_submit:
                    result = _run_action(
                        st,
                        db_path=db_path,
                        callback=lambda session, ids=tuple(selected_bulk_ids): accept_discovery_candidates_as_new_authorities(
                            session,
                            project_id=project_id,
                            candidate_ids=ids,
                            decided_by=actor or "local_user",
                            source="ui",
                        ),
                    )
                    if result is not None:
                        st.session_state["open_discovery_decision_success"] = (
                            f"Se crearon {len(result)} entidades con estado Sin revisar y se vinculó cada referencia seleccionada con su entidad."
                        )
                        request_tab(
                            st,
                            key=review_modes_key,
                            label="Trabajar con varias referencias",
                        )
                        rerun_view(st)
                else:
                    result = _run_action(
                        st,
                        db_path=db_path,
                        callback=lambda session, ids=tuple(selected_bulk_ids): reject_discovery_candidates(
                            session,
                            project_id=project_id,
                            candidate_ids=ids,
                            decided_by=actor or "local_user",
                            source="ui",
                        ),
                    )
                    if result is not None:
                        st.session_state["open_discovery_decision_success"] = (
                            f"Se descartaron {len(result)} referencias. Podés restaurarlas desde la pestaña «Referencias descartadas»."
                        )
                        request_tab(
                            st,
                            key=review_modes_key,
                            label="Trabajar con varias referencias",
                        )
                        rerun_view(st)

    with discarded_tab:
        st.badge(
            f"Mostrando {len(rejected_candidates):,} de {len(rejected_candidates_all):,} referencias descartadas".replace(",", "."),
            color="gray",
        )
        if not rejected_candidates:
            st.info("No hay referencias descartadas en esta búsqueda.")
        for row in rejected_candidates:
            with st.container(border=True):
                st.write(
                    f"**{row.effective_text}** · {family_label(row.effective_family)} · "
                    f"{row.original_filename}, página {row.page_number}"
                )
                _render_decision_history(
                    st, decisions_by.get(row.candidate_id, [])
                )
                if st.button(
                    "Restaurar esta referencia para revisarla",
                    key=f"open_discovery_restore_{row.candidate_id}",
                ):
                    result = _run_action(
                        st,
                        db_path=db_path,
                        callback=lambda session, candidate_id=row.candidate_id: restore_rejected_discovery_candidate(
                            session,
                            project_id=project_id,
                            candidate_id=candidate_id,
                            restored_by=actor or "local_user",
                            source="ui",
                        ),
                    )
                    if result is not None:
                        st.session_state["open_discovery_decision_success"] = (
                            "Referencia restaurada. Volvió a la lista de referencias pendientes de revisión."
                        )
                        request_tab(
                            st,
                            key=review_modes_key,
                            label="Referencias descartadas",
                        )
                        rerun_view(st)


def render_open_discovery_section(
    st,
    *,
    db_path: Path,
    project_id: str,
    actor: str,
) -> None:
    task_labels = {
        "review": "Revisar referencias encontradas",
        "run": "Ejecutar búsqueda de entidades",
        "grouping": "Duplicados y cambios de texto",
    }
    pending = st.session_state.pop("open_discovery_task__pending", None)
    if pending in task_labels:
        st.session_state["open_discovery_task"] = pending
    task = st.selectbox(
        "Tarea para buscar nuevas entidades",
        options=list(task_labels),
        format_func=lambda value: task_labels[value],
        key="open_discovery_task",
        label_visibility="collapsed",
    )
    task_label = task_labels[task]
    mount_choice_help(
        st,
        key="open_discovery_task",
        label=task_label,
        help_text=TASK_HELP["open_discovery_task"][task_label],
    )

    if task == "review":
        _render_discovery_candidate_workspace(
            st,
            db_path=db_path,
            project_id=project_id,
            actor=actor,
        )
    elif task == "run":
        _render_discovery_run_setup(
            st,
            db_path=db_path,
            project_id=project_id,
            actor=actor,
        )
    else:
        _render_grouping_and_continuity(
            st,
            db_path=db_path,
            project_id=project_id,
            actor=actor,
        )
