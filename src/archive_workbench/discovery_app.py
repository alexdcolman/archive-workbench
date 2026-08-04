from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from sqlalchemy import select

from archive_workbench.analysis_quality import analysis_quality_scope, quality_scope_caption
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
    DISCOVERY_DECISION_TYPES,
    acceptance_mode_label,
    allowed_acceptance_modes,
    allowed_authority_types,
    candidate_status_label,
    decision_label,
    discovery_decision_rows,
    review_discovery_candidate,
)
from archive_workbench.open_discovery import (
    DISCOVERY_FAMILIES,
    DiscoveryProfileValues,
    discovery_candidate_rows,
    discovery_profile_rows,
    discovery_run_rows,
    family_label,
    run_open_discovery,
    save_discovery_profile,
)
from archive_workbench.ui_navigation import rerun_view

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
    "work": "Obra",
    "other": "Otra entidad",
}
_DECISION_OPTIONS = {
    "accept": "Aceptar",
    "reject": "Rechazar",
    "modify": "Modificar propuesta",
    "defer": "Aplazar",
}


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
    if profiles:
        selected_profile_id = st.selectbox(
            "Perfil de descubrimiento",
            options=list(profile_map),
            format_func=lambda value: (
                f"{profile_map[value].name} · v{profile_map[value].revision} · "
                f"{profile_map[value].provider_key}"
            ),
            key="open_discovery_profile_selected",
        )
        selected_profile = profile_map[selected_profile_id]
    profile_key = selected_profile.id if selected_profile else "new"

    profile_panel_open = st.toggle(
        "Configurar perfil",
        value=not profiles,
        key=f"open_discovery_profile_panel_{profile_key}",
        help="El panel permanece abierto mientras cambiás sus controles.",
    )
    if profile_panel_open:
        with st.container(border=True):
            default_name = selected_profile.name if selected_profile else "Descubrimiento local inicial"
            profile_name = st.text_input(
                "Nombre",
                value=default_name,
                key=f"open_discovery_profile_name_{profile_key}",
            )
            profile_description = st.text_area(
                "Descripción",
                value=(selected_profile.description or "") if selected_profile else (
                    "Proveedor local determinista para revisar el circuito de descubrimiento abierto."
                ),
                height=80,
                key=f"open_discovery_profile_description_{profile_key}",
            )
            profile_families = st.multiselect(
                "Familias semánticas",
                options=list(DISCOVERY_FAMILIES),
                default=(
                    list(selected_profile.families_json or [])
                    if selected_profile
                    else list(DISCOVERY_FAMILIES[:-1])
                ),
                format_func=family_label,
                key=f"open_discovery_profile_families_{profile_key}",
            )
            filter_cols = st.columns(2)
            with filter_cols[0]:
                profile_object_types = st.multiselect(
                    "Tipos de objeto incluidos",
                    options=list(object_types),
                    default=(
                        list(selected_profile.include_object_types_json or [])
                        if selected_profile
                        else []
                    ),
                    help="Una selección vacía incluye todos los tipos de objeto.",
                    key=f"open_discovery_object_types_{profile_key}",
                )
                profile_object_statuses = st.multiselect(
                    "Estados de revisión de objeto",
                    options=list(_OBJECT_STATUS_LABELS),
                    default=(
                        list(selected_profile.include_object_review_statuses_json or [])
                        if selected_profile
                        else []
                    ),
                    format_func=lambda value: _OBJECT_STATUS_LABELS[value],
                    help="Una selección vacía incluye todos los estados de objeto.",
                    key=f"open_discovery_object_statuses_{profile_key}",
                )
            with filter_cols[1]:
                profile_page_statuses = st.multiselect(
                    "Estados de página incluidos",
                    options=list(_PAGE_STATUS_LABELS),
                    default=(
                        list(selected_profile.include_page_review_statuses_json or [])
                        if selected_profile
                        else ["approved"]
                    ),
                    format_func=lambda value: _PAGE_STATUS_LABELS[value],
                    help=(
                        "Por seguridad, el valor predeterminado incluye únicamente páginas aprobadas. "
                        "Una selección vacía significa todos los estados."
                    ),
                    key=f"open_discovery_page_statuses_{profile_key}",
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
                )

            quality_scope = analysis_quality_scope(profile_page_statuses)
            quality_confirmed = False
            quality_reason = ""
            if quality_scope.is_default:
                st.caption(quality_scope_caption(profile_page_statuses))
            else:
                st.warning(quality_scope_caption(profile_page_statuses))
                quality_confirmed = st.checkbox(
                    "Confirmo que deseo descubrir candidatos en páginas no aprobadas",
                    value=False,
                    key=f"open_discovery_quality_confirm_{profile_key}",
                )
                quality_reason = st.text_area(
                    "Fundamento del alcance ampliado",
                    value="",
                    placeholder=(
                        "Explicá por qué esta corrida debe incluir páginas "
                        "que todavía no están aprobadas."
                    ),
                    height=80,
                    key=f"open_discovery_quality_reason_{profile_key}",
                )
            if st.button(
                "Guardar perfil de descubrimiento",
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
                        ),
                        changed_by=actor or "local_user",
                        broader_quality_scope_confirmed=quality_confirmed,
                        quality_scope_reason=quality_reason or None,
                        quality_scope_source="ui",
                    ),
                )
                if saved is not None:
                    st.session_state["open_discovery_profile_selected"] = saved.id
                    st.session_state["open_discovery_success"] = (
                        "Perfil guardado y autorización registrada."
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
                details.append(f"autoridad: {item.target_authority_name}")
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
        st.caption("La decisión es terminal; el historial permanece disponible.")
        return

    review_panel_open = st.toggle(
        "Revisar candidato",
        value=False,
        key=f"discovery_candidate_review_panel_{row.candidate_id}",
        help="El panel permanece abierto mientras cambiás la decisión o su destino.",
    )
    if not review_panel_open:
        return

    with st.container(border=True):
        if row.is_stale:
            st.warning(
                "El texto o la revisión del objeto cambió. Cualquier intento de decisión será "
                "rechazado hasta volver a detectar el candidato."
            )
        decision_type = st.selectbox(
            "Decisión",
            options=list(DISCOVERY_DECISION_TYPES),
            format_func=lambda value: _DECISION_OPTIONS[value],
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

        if decision_type == "modify":
            reviewed_text = st.text_input(
                "Texto o etiqueta revisada",
                value=row.effective_text,
                key=f"discovery_reviewed_text_{row.candidate_id}",
            )
            reviewed_family = st.selectbox(
                "Familia revisada",
                options=list(DISCOVERY_FAMILIES),
                index=list(DISCOVERY_FAMILIES).index(row.effective_family),
                format_func=family_label,
                key=f"discovery_reviewed_family_{row.candidate_id}",
            )
            reviewed_subtype = st.text_input(
                "Subtipo revisado",
                value=row.effective_subtype,
                key=f"discovery_reviewed_subtype_{row.candidate_id}",
            )
        elif decision_type == "accept":
            modes = allowed_acceptance_modes(row.effective_family)
            acceptance_mode = st.radio(
                "Destino de la aceptación",
                options=list(modes),
                format_func=acceptance_mode_label,
                key=f"discovery_acceptance_mode_{row.candidate_id}",
            )
            if acceptance_mode == "existing_authority":
                compatible_types = allowed_authority_types(
                    row.effective_family, row.effective_subtype
                )
                choices = [
                    item for item in authorities if item.entity_type in compatible_types
                ]
                if choices:
                    choice_map = {item.id: item for item in choices}
                    authority_id = st.selectbox(
                        "Autoridad existente",
                        options=list(choice_map),
                        format_func=lambda value: (
                            f"{choice_map[value].preferred_name} · "
                            f"{_AUTHORITY_TYPE_LABELS.get(choice_map[value].entity_type, choice_map[value].entity_type)} · "
                            f"{choice_map[value].review_status}"
                        ),
                        key=f"discovery_authority_{row.candidate_id}",
                    )
                else:
                    st.warning("No hay autoridades activas compatibles en este proyecto.")
            elif acceptance_mode == "new_authority":
                new_authority_name = st.text_input(
                    "Nombre preferido de la nueva autoridad",
                    value=row.effective_text,
                    key=f"discovery_new_authority_name_{row.candidate_id}",
                )
                description = st.text_area(
                    "Descripción inicial",
                    value="",
                    height=80,
                    key=f"discovery_new_authority_description_{row.candidate_id}",
                )
                if row.effective_family == "event":
                    temporal_expression = st.text_input(
                        "Expresión temporal del acontecimiento (opcional)",
                        value="",
                        key=f"discovery_new_authority_temporal_{row.candidate_id}",
                    )
                confirm_new_authority = st.checkbox(
                    "Confirmo la creación de una autoridad nueva con estado Sin revisar",
                    value=False,
                    key=f"discovery_new_authority_confirm_{row.candidate_id}",
                )
            else:
                description = st.text_area(
                    "Descripción o nota propia de la familia (opcional)",
                    value="",
                    height=80,
                    key=f"discovery_context_description_{row.candidate_id}",
                )
                if row.effective_family in {"time", "event"}:
                    temporal_expression = st.text_input(
                        "Expresión temporal (opcional)",
                        value=(row.effective_text if row.effective_family == "time" else ""),
                        key=f"discovery_context_temporal_{row.candidate_id}",
                    )

        reason = st.text_area(
            "Fundamento",
            value="",
            help=(
                "Es obligatorio para rechazar, modificar, aplazar o crear una autoridad nueva. "
                "En las demás aceptaciones puede dejarse vacío."
            ),
            height=75,
            key=f"discovery_decision_reason_{row.candidate_id}_{decision_type}",
        )
        if st.button(
            "Registrar decisión",
            type="primary",
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
                    reason=reason or None,
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
                    f"Decisión registrada: {decision_label(result.decision_type)}."
                )
                rerun_view(st)



def _render_grouping_and_continuity(
    st,
    *,
    db_path: Path,
    project_id: str,
    actor: str,
) -> None:
    panel_open = st.toggle(
        "Agrupar candidatos y mantener continuidad",
        value=False,
        key="open_discovery_grouping_continuity_panel",
        help=(
            "Agrupa candidatos repetidos sin fusionar sus procedencias y permite "
            "crear un nuevo anclaje cuando una revisión textual volvió obsoleto al anterior."
        ),
    )
    if not panel_open:
        return

    with st.container(border=True):
        st.caption(
            "Estas operaciones no borran candidatos, decisiones ni procedencias. "
            "Los grupos y vínculos de continuidad conservan un historial auditable."
        )
        grouping_open = st.toggle(
            "Agrupamiento y duplicados",
            value=False,
            key="open_discovery_grouping_panel",
        )
        if grouping_open:
            if st.button(
                "Actualizar grupos propuestos",
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
                        f"Agrupamiento actualizado: {summary.groups_created} grupos nuevos y "
                        f"{summary.memberships_created} pertenencias nuevas."
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
                    "Grupo",
                    options=list(group_map),
                    format_func=lambda value: (
                        f"{group_map[value].preferred_label} · "
                        f"{family_label(group_map[value].semantic_family)} · "
                        f"{group_map[value].active_member_count} miembros"
                    ),
                    key="open_discovery_group_selected",
                )
                selected_group = group_map[selected_group_id]
                st.caption(
                    f"Método: {selected_group.grouping_method} · "
                    f"corridas: {selected_group.run_count} · "
                    f"miembros obsoletos: {selected_group.stale_member_count}"
                )
                for member in selected_group.members:
                    status = "separado" if member.membership_status != "active" else "activo"
                    stale = " · obsoleto" if member.is_stale else ""
                    st.write(
                        f"- **{member.effective_text}** · {status}{stale} · "
                        f"{member.original_filename}, p. {member.page_number} · "
                        f"corrida `{member.run_id}` · candidato `{member.candidate_id}`"
                    )

                active_members = [
                    row for row in selected_group.members if row.membership_status == "active"
                ]
                if len(active_members) > 1:
                    remove_map = {row.candidate_id: row for row in active_members}
                    remove_candidate_id = st.selectbox(
                        "Candidato que debe separarse del grupo",
                        options=list(remove_map),
                        format_func=lambda value: (
                            f"{remove_map[value].effective_text} · "
                            f"{remove_map[value].original_filename}, p. {remove_map[value].page_number}"
                        ),
                        key=f"open_discovery_group_remove_candidate_{selected_group_id}",
                    )
                    remove_reason = st.text_area(
                        "Fundamento de la separación",
                        value="",
                        height=70,
                        key=f"open_discovery_group_remove_reason_{selected_group_id}",
                    )
                    if st.button(
                        "Separar candidato",
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
                                "Candidato separado; el grupo y la procedencia histórica se conservaron."
                            )
                            rerun_view(st)
            else:
                st.caption("Todavía no hay grupos. Actualizá las propuestas o creá uno manual.")

            manual_open = st.toggle(
                "Crear grupo manual",
                value=False,
                key="open_discovery_manual_group_panel",
            )
            if manual_open:
                candidate_map = {row.candidate_id: row for row in all_candidates}
                manual_ids = st.multiselect(
                    "Candidatos del grupo",
                    options=list(candidate_map),
                    format_func=lambda value: (
                        f"{candidate_map[value].effective_text} · "
                        f"{candidate_map[value].original_filename}, p. {candidate_map[value].page_number} · "
                        f"candidato {value[:8]} · corrida {candidate_map[value].run_id[:8]}"
                    ),
                    key="open_discovery_manual_group_candidates",
                )
                manual_label = st.text_input(
                    "Etiqueta del grupo",
                    key="open_discovery_manual_group_label",
                )
                manual_family = st.selectbox(
                    "Familia del grupo",
                    options=list(DISCOVERY_FAMILIES),
                    format_func=family_label,
                    key="open_discovery_manual_group_family",
                )
                manual_reason = st.text_area(
                    "Fundamento del agrupamiento manual",
                    height=70,
                    key="open_discovery_manual_group_reason",
                )
                if st.button(
                    "Crear grupo manual",
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
                            "Grupo manual creado sin fusionar candidatos ni procedencias."
                        )
                        rerun_view(st)

        continuity_open = st.toggle(
            "Continuidad después de editar texto",
            value=False,
            key="open_discovery_continuity_panel",
        )
        if continuity_open:
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
                st.caption("No hay candidatos obsoletos que requieran continuidad.")
            else:
                stale_map = {row.candidate_id: row for row in stale}
                source_candidate_id = st.selectbox(
                    "Candidato obsoleto",
                    options=list(stale_map),
                    format_func=lambda value: (
                        f"{stale_map[value].effective_text} · "
                        f"{stale_map[value].original_filename}, p. {stale_map[value].page_number} · "
                        f"rev. {stale_map[value].object_revision_number} · "
                        f"candidato {value[:8]} · corrida {stale_map[value].run_id[:8]}"
                    ),
                    key="open_discovery_continuity_candidate",
                )
                method = st.radio(
                    "Método",
                    options=list(CONTINUITY_METHODS),
                    format_func=lambda value: (
                        "Proyección exacta única"
                        if value == "exact_projection"
                        else "Nueva detección local"
                    ),
                    key="open_discovery_continuity_method",
                )
                st.caption(
                    "La operación crea un candidato nuevo para la revisión vigente y mantiene "
                    "visible el candidato obsoleto como procedencia histórica."
                )
                if st.button(
                    "Crear continuidad",
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

def render_open_discovery_section(
    st,
    *,
    db_path: Path,
    project_id: str,
    actor: str,
) -> None:
    st.caption(
        "Propone actores, espacios, tiempos, acontecimientos, acciones, procesos y obras "
        "a partir del texto. Las corridas crean candidatos; las decisiones humanas quedan "
        "registradas por separado y nunca crean relaciones automáticamente."
    )

    engine = create_sqlite_engine(db_path)
    try:
        with session_scope(engine) as session:
            profiles = discovery_profile_rows(session, project_id=project_id)
            runs = discovery_run_rows(session, project_id=project_id, limit=25)
            object_types = session.scalars(
                select(EditableObject.current_object_type)
                .where(EditableObject.lifecycle_status == "active")
                .distinct()
                .order_by(EditableObject.current_object_type)
            ).all()
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
    decision_success = st.session_state.pop("open_discovery_decision_success", None)
    if decision_success:
        st.success(decision_success)

    if selected_profile is None:
        st.info("Guardá un perfil antes de ejecutar el descubrimiento.")
        return

    st.caption(
        "La ejecución usa el perfil exactamente como fue autorizado. Cambiar cualquier parámetro "
        "obliga a guardar nuevamente el perfil."
    )
    if st.button(
        "Ejecutar descubrimiento abierto",
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
                f"Corrida completada: {summary.candidate_count} candidatos en "
                f"{summary.object_count} objetos."
            )
            rerun_view(st)

    run_success = st.session_state.pop("open_discovery_run_success", None)
    if run_success:
        st.success(run_success)

    engine = create_sqlite_engine(db_path)
    try:
        with session_scope(engine) as session:
            runs = discovery_run_rows(session, project_id=project_id, limit=25)
    finally:
        engine.dispose()
    if not runs:
        st.caption("Todavía no hay corridas registradas.")
        return

    run_map = {row.run_id: row for row in runs}
    current_run = st.session_state.get("open_discovery_run_selected")
    if current_run not in run_map:
        st.session_state["open_discovery_run_selected"] = runs[0].run_id
    selected_run_id = st.selectbox(
        "Corrida registrada",
        options=list(run_map),
        format_func=lambda value: (
            f"{run_map[value].started_at.isoformat(timespec='minutes')} · "
            f"{run_map[value].profile_name} · {run_map[value].candidate_count} candidatos"
        ),
        key="open_discovery_run_selected",
    )
    selected_run = run_map[selected_run_id]
    metrics = st.columns(3)
    metrics[0].metric("Objetos recorridos", selected_run.object_count)
    metrics[1].metric("Candidatos", selected_run.candidate_count)
    metrics[2].metric("Estado", selected_run.status)
    st.caption(
        f"Proveedor: {selected_run.provider_key}@{selected_run.provider_version} · "
        f"Páginas: {', '.join(selected_run.page_review_statuses) or 'todos los estados'}"
    )

    engine = create_sqlite_engine(db_path)
    try:
        with session_scope(engine) as session:
            candidates = discovery_candidate_rows(
                session,
                project_id=project_id,
                run_id=selected_run_id,
                limit=500,
            )
            decisions = discovery_decision_rows(
                session, project_id=project_id, limit=10_000
            )
    finally:
        engine.dispose()
    if not candidates:
        st.info("La corrida no produjo candidatos con el umbral configurado.")
        return

    decisions_by = defaultdict(list)
    for item in decisions:
        decisions_by[item.candidate_id].append(item)

    filters = st.columns(2)
    with filters[0]:
        candidate_families = st.multiselect(
            "Filtrar candidatos por familia",
            options=list(DISCOVERY_FAMILIES),
            default=[],
            format_func=family_label,
            key=f"open_discovery_candidate_family_filter_{selected_run_id}",
        )
    with filters[1]:
        candidate_statuses = st.multiselect(
            "Filtrar por estado de decisión",
            options=["pending", "modified", "deferred", "accepted", "rejected"],
            default=[],
            format_func=candidate_status_label,
            key=f"open_discovery_candidate_status_filter_{selected_run_id}",
        )
    visible = [
        row
        for row in candidates
        if (not candidate_families or row.effective_family in candidate_families)
        and (not candidate_statuses or row.status in candidate_statuses)
    ]
    st.caption(f"Candidatos visibles: {len(visible)}")
    for row in visible:
        with st.container(border=True):
            head, confidence = st.columns([5, 1])
            head.write(
                f"**{row.effective_text}** · {family_label(row.effective_family)} / "
                f"{row.effective_subtype} · **{candidate_status_label(row.status)}**"
            )
            confidence.metric(
                "Confianza", "—" if row.confidence is None else f"{row.confidence:.2f}"
            )
            head.caption(
                f"{row.source_key or row.original_filename} · página {row.page_number} · "
                f"objeto {row.editable_object_id} · offsets {row.start_offset}:{row.end_offset} · "
                f"revisión textual {row.object_revision_number}"
            )
            st.write(f"…{row.context_before}**{row.exact_text}**{row.context_after}…")
            if row.effective_text != row.exact_text or row.effective_family != row.semantic_family:
                st.caption(
                    "Propuesta original: "
                    f"{row.exact_text} · {row.family_label}/{row.suggested_subtype}"
                )
            if row.is_stale:
                st.warning("El objeto cambió después de esta corrida; el candidato está obsoleto.")
            _render_decision_history(st, decisions_by.get(row.candidate_id, []))
            _render_candidate_review(
                st,
                db_path=db_path,
                project_id=project_id,
                actor=actor,
                row=row,
                decisions=decisions_by.get(row.candidate_id, []),
                authorities=authorities,
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
    _render_grouping_and_continuity(
        st,
        db_path=db_path,
        project_id=project_id,
        actor=actor,
    )
    st.caption(
        "Las decisiones son append-only. Aceptar una referencia nunca crea relaciones. "
        "Las autoridades nuevas quedan con estado Sin revisar."
    )
