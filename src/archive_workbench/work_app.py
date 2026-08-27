from __future__ import annotations

from archive_workbench.ui_dates import DATE_INPUT_MIN, DATE_INPUT_MAX
from archive_workbench.ui_help import TAB_HELP
from datetime import datetime, time, timezone
from pathlib import Path

from archive_workbench.ui_navigation import rerun_view, section_heading, tracked_tabs

from archive_workbench.ui_navigation import rerun_app, request_app_view

from archive_workbench.db import create_sqlite_engine, session_scope
from archive_workbench.processing import processing_inventory_rows
from archive_workbench.work import (
    ASSIGNMENT_KINDS,
    ASSIGNMENT_PRIORITIES,
    ASSIGNMENT_STATUSES,
    CROSS_REVIEW_OUTCOMES,
    create_cross_review_assignment,
    create_work_assignment,
    cross_review_candidate_rows,
    update_work_assignment,
    work_assignment_revision_rows,
    work_assignment_rows,
    workload_summary_rows,
)

_KIND_LABELS = {
    "processing": "Seguimiento de procesamiento",
    "primary_review": "Revisión primaria",
    "cross_review": "Revisión cruzada",
}
_STATUS_LABELS = {
    "planned": "Planificada",
    "in_progress": "En curso",
    "submitted": "Enviada a revisión",
    "completed": "Completada",
    "blocked": "Bloqueada",
    "cancelled": "Cancelada",
}
_PRIORITY_LABELS = {
    "low": "Baja",
    "normal": "Normal",
    "high": "Alta",
    "urgent": "Urgente",
}
_OUTCOME_LABELS = {
    "accepted": "Aceptada",
    "changes_requested": "Requiere cambios",
    "not_applicable": "No aplicable",
}
_ACTIVE_STATUSES = {"planned", "in_progress", "submitted", "blocked"}


def _render_summary_card(st, label: str, value: object) -> None:
    """Muestra un indicador compacto del estado del trabajo."""

    st.metric(label, value)


def _database_action(db_path: Path, callback):
    engine = create_sqlite_engine(db_path)
    try:
        with session_scope(engine) as session:
            return callback(session)
    finally:
        engine.dispose()


def _load_all(*, db_path: Path, project_root: Path, project_id: str):
    engine = create_sqlite_engine(db_path)
    try:
        with session_scope(engine) as session:
            assignments = work_assignment_rows(session, project_id=project_id)
            workload = workload_summary_rows(session, project_id=project_id)
            candidates = cross_review_candidate_rows(session, project_id=project_id)
            inventory = processing_inventory_rows(
                session, project_root=project_root, project_id=project_id
            )
    finally:
        engine.dispose()
    return assignments, workload, candidates, inventory


def _go_to_review(st, *, source_key: str, page: int | None) -> None:
    request_app_view(st, mode="review", source_key=source_key, page=page or 1)
    rerun_app(st)


def _due_datetime(enabled: bool, value) -> datetime | None:
    if not enabled:
        return None
    return datetime.combine(value, time(23, 59), tzinfo=timezone.utc)


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _scope_inputs(st, *, prefix: str, page_count: int | None):
    whole = st.checkbox("Documento completo", value=True, key=f"{prefix}_whole")
    if whole:
        return None, None
    maximum = max(1, page_count or 1)
    columns = st.columns(2)
    start = columns[0].number_input(
        "Página inicial", min_value=1, max_value=maximum, value=1, key=f"{prefix}_start"
    )
    end = columns[1].number_input(
        "Página final", min_value=1, max_value=maximum, value=maximum, key=f"{prefix}_end"
    )
    return int(start), int(end)


def _assignment_label(row) -> str:
    return (
        f"{row.title} · {row.scope_label} · {row.assignee} · "
        f"{_STATUS_LABELS.get(row.status, row.status)}"
    )


def render_work_view(
    st,
    *,
    project_root: Path,
    db_path: Path,
    project_id: str,
    actor: str,
) -> None:
    section_heading(st, "Organizar trabajo")
    assignments, workload, candidates, inventory = _load_all(
        db_path=db_path,
        project_root=project_root,
        project_id=project_id,
    )
    inventory_map = {row.source_key: row for row in inventory}
    assignment_map = {row.assignment_id: row for row in assignments}
    panel_tab, assignments_tab, mine_tab, cross_tab = tracked_tabs(
        st,
        ["Estado de las tareas", "Crear y administrar asignaciones", "Tareas de la persona actual", "Asignar una segunda revisión"],
        key="work_tabs",
        help_by_label=TAB_HELP["work_tabs"],
    )

    with panel_tab:
        active = [row for row in assignments if row.status in _ACTIVE_STATUSES]
        overdue = [
            row
            for row in active
            if row.due_at is not None and _as_utc(row.due_at) < datetime.now(timezone.utc)
        ]
        submitted = [row for row in assignments if row.status == "submitted"]
        cross_pending = [
            row
            for row in assignments
            if row.assignment_kind == "cross_review" and row.status in _ACTIVE_STATUSES
        ]
        summary_cols = st.columns(4)
        with summary_cols[0]:
            _render_summary_card(st, "Activas", len(active))
        with summary_cols[1]:
            _render_summary_card(st, "Vencidas", len(overdue))
        with summary_cols[2]:
            _render_summary_card(st, "En revisión", len(submitted))
        with summary_cols[3]:
            _render_summary_card(st, "Segundas revisiones", len(cross_pending))

        with st.expander("Cantidad de tareas por responsable", expanded=False):
            if workload:
                st.dataframe(
                    [
                        {
                            "Responsable": row.assignee,
                            "Total": row.total,
                            "Planificadas": row.planned,
                            "En curso": row.in_progress,
                            "Enviadas": row.submitted,
                            "Bloqueadas": row.blocked,
                            "Completadas": row.completed,
                            "Vencidas": row.overdue,
                            "Revisión primaria": row.primary_review,
                            "Revisión cruzada": row.cross_review,
                            "Procesamiento": row.processing,
                        }
                        for row in workload
                    ],
                    hide_index=True,
                    use_container_width=True,
                )
            else:
                st.info("Todavía no hay asignaciones de trabajo.")

        with st.expander("Avance de procesamiento y revisión por documento", expanded=False):
            st.dataframe(
                [
                    {
                        "Documento": row.title,
                        "Identificador técnico del documento": row.source_key,
                        "Estado de procesamiento": row.status,
                        "Páginas": row.page_count,
                        "Páginas con texto elegido": row.selected_pages,
                        "Páginas disponibles en Revisar documentos": row.editable_pages,
                        "Páginas revisadas": row.reviewed_pages,
                        "Páginas aprobadas": row.approved_pages,
                        "Asignaciones activas": sum(
                            item.source_key == row.source_key
                            and item.status in _ACTIVE_STATUSES
                            for item in assignments
                        ),
                    }
                    for row in inventory
                ],
                hide_index=True,
                use_container_width=True,
            )

    with assignments_tab:
        st.subheader("Crear una asignación de trabajo")
        if not inventory:
            st.info("No hay documentos procesables registrados en el catálogo.")
        else:
            with st.form("create_work_assignment", enter_to_submit=False):
                source_key = st.selectbox(
                    "Documento sobre el que se trabajará",
                    options=list(inventory_map),
                    format_func=lambda key: f"{inventory_map[key].title} · {key}",
                )
                selected_document = inventory_map[source_key]
                kind = st.selectbox(
                    "Tarea que se asignará",
                    options=["processing", "primary_review"],
                    format_func=lambda value: _KIND_LABELS[value],
                )
                assignee = st.text_input("Persona responsable de esta asignación", value=actor or "")
                page_start, page_end = _scope_inputs(
                    st,
                    prefix="create_assignment",
                    page_count=selected_document.page_count,
                )
                priority = st.selectbox(
                    "Prioridad de esta asignación",
                    options=list(ASSIGNMENT_PRIORITIES),
                    index=list(ASSIGNMENT_PRIORITIES).index("normal"),
                    format_func=lambda value: _PRIORITY_LABELS[value],
                )
                has_due = st.checkbox("Agregar una fecha límite a esta asignación", value=False)
                due_date = st.date_input(
                    "Fecha límite de esta asignación",
                    min_value=DATE_INPUT_MIN,
                    max_value=DATE_INPUT_MAX,
                    help="La fecha sólo se guarda si activaste la opción de agregar una fecha límite.",
                )
                note = st.text_area("Indicaciones opcionales para la persona responsable")
                submit = st.form_submit_button("Crear una asignación de trabajo")
            if submit:
                try:
                    _database_action(
                        db_path,
                        lambda session: create_work_assignment(
                            session,
                            project_id=project_id,
                            source_type=selected_document.source_type,
                            source_key=source_key,
                            assignment_kind=kind,
                            assignee=assignee,
                            created_by=actor,
                            page_start=page_start,
                            page_end=page_end,
                            priority=priority,
                            due_at=_due_datetime(has_due, due_date),
                            note=note,
                        ),
                    )
                except ValueError as exc:
                    st.error(str(exc))
                else:
                    st.success("Asignación creada.")
                    rerun_view(st)

        st.divider()
        st.subheader("Asignaciones de trabajo existentes")
        people = sorted({row.assignee for row in assignments}, key=str.casefold)
        with st.popover("Filtrar asignaciones"):
            filter_cols = st.columns(3)
            person_filter = filter_cols[0].multiselect("Persona responsable", people)
            status_filter = filter_cols[1].multiselect(
                "Estado de la asignación",
                list(ASSIGNMENT_STATUSES),
                format_func=lambda value: _STATUS_LABELS[value],
            )
            kind_filter = filter_cols[2].multiselect(
                "Tarea asignada",
                list(ASSIGNMENT_KINDS),
                format_func=lambda value: _KIND_LABELS[value],
            )
        filtered = [
            row
            for row in assignments
            if (not person_filter or row.assignee in person_filter)
            and (not status_filter or row.status in status_filter)
            and (not kind_filter or row.assignment_kind in kind_filter)
        ]
        if not filtered:
            st.info("No hay asignaciones para los filtros seleccionados.")
        for row in filtered:
            assignment_panel_open = st.toggle(
                _assignment_label(row),
                value=False,
                key=f"work_assignment_panel_{row.assignment_id}",
            )
            if assignment_panel_open:
                with st.container(border=True):
                    st.write(f"**Ruta:** {row.archival_path}")
                    st.write(f"**Tipo:** {_KIND_LABELS[row.assignment_kind]}")
                    st.write(f"**Prioridad:** {_PRIORITY_LABELS[row.priority]}")
                    if row.due_at:
                        st.write(f"**Fecha límite:** {row.due_at.date().isoformat()}")
                    if row.note:
                        st.write(row.note)
                    if row.parent_assignee:
                        st.caption(f"Revisión primaria realizada por {row.parent_assignee}")
                    with st.form(f"update_assignment_{row.assignment_id}_{row.revision}", enter_to_submit=False):
                        new_assignee = st.text_input("Persona responsable de esta asignación", value=row.assignee)
                        new_status = st.selectbox(
                            "Estado de la asignación",
                            options=list(ASSIGNMENT_STATUSES),
                            index=list(ASSIGNMENT_STATUSES).index(row.status),
                            format_func=lambda value: _STATUS_LABELS[value],
                        )
                        new_priority = st.selectbox(
                            "Prioridad de esta asignación",
                            options=list(ASSIGNMENT_PRIORITIES),
                            index=list(ASSIGNMENT_PRIORITIES).index(row.priority),
                            format_func=lambda value: _PRIORITY_LABELS[value],
                        )
                        keep_due = st.checkbox(
                            "Mantener o agregar una fecha límite a esta asignación",
                            value=row.due_at is not None,
                            key=f"assignment_has_due_{row.assignment_id}",
                        )
                        new_due_date = st.date_input(
                            "Fecha límite",
                            value=row.due_at.date() if row.due_at else datetime.now().date(),
                            min_value=DATE_INPUT_MIN,
                            max_value=DATE_INPUT_MAX,
                            key=f"assignment_due_{row.assignment_id}",
                            help="La fecha solo se guarda cuando está marcada la opción anterior.",
                        )
                        new_note = st.text_area("Indicaciones de esta asignación", value=row.note or "")
                        outcome = None
                        if row.assignment_kind == "cross_review":
                            outcome_options = [None, *CROSS_REVIEW_OUTCOMES]
                            outcome = st.selectbox(
                                "Resultado de la revisión cruzada",
                                options=outcome_options,
                                index=outcome_options.index(row.outcome),
                                format_func=lambda value: (
                                    "Sin resultado" if value is None else _OUTCOME_LABELS[value]
                                ),
                            )
                        change_note = st.text_input("Motivo de los cambios en esta asignación")
                        update_submit = st.form_submit_button("Guardar cambios de esta asignación")
                    if update_submit:
                        try:
                            _database_action(
                                db_path,
                                lambda session, row=row: update_work_assignment(
                                    session,
                                    assignment_id=row.assignment_id,
                                    expected_revision=row.revision,
                                    changed_by=actor,
                                    assignee=new_assignee,
                                    status=new_status,
                                    priority=new_priority,
                                    due_at=_due_datetime(keep_due, new_due_date),
                                    outcome=outcome,
                                    assignment_note=new_note,
                                    change_note=change_note,
                                ),
                            )
                        except ValueError as exc:
                            st.error(str(exc))
                        else:
                            st.success("Asignación actualizada.")
                            rerun_view(st)
                    if st.button(
                        "Abrir este documento en Revisar documentos",
                        key=f"assignment_open_{row.assignment_id}",
                    ):
                        _go_to_review(st, source_key=row.source_key, page=row.page_start)
                    with st.expander("Historial de la asignación"):
                        history = _database_action(
                            db_path,
                            lambda session, row=row: work_assignment_revision_rows(
                                session, assignment_id=row.assignment_id
                            ),
                        )
                        for revision in history:
                            st.write(
                                f"Revisión {revision.revision_number} · {revision.operation} · "
                                f"{revision.changed_by} · "
                                f"{revision.changed_at.isoformat(timespec='minutes')}"
                            )
                            if revision.note:
                                st.caption(revision.note)

    with mine_tab:
        clean_actor = (actor or "").strip()
        if not clean_actor:
            st.info("Indicá tu nombre en el campo Responsable de la barra lateral.")
        mine = [
            row
            for row in assignments
            if row.assignee.casefold() == clean_actor.casefold()
            and row.status != "cancelled"
        ]
        if not mine:
            st.info("No hay asignaciones a tu nombre.")
        for row in mine:
            with st.container(border=True):
                title_col, action_col = st.columns([5, 1])
                title_col.write(f"**{row.title}** · {row.scope_label}")
                title_col.caption(
                    f"{_KIND_LABELS[row.assignment_kind]} · "
                    f"{_STATUS_LABELS[row.status]} · {_PRIORITY_LABELS[row.priority]}"
                )
                if row.note:
                    title_col.write(row.note)
                if action_col.button("Abrir el documento de esta tarea", key=f"mine_open_{row.assignment_id}"):
                    _go_to_review(st, source_key=row.source_key, page=row.page_start)
                quick_cols = st.columns(4)
                transitions = [
                    ("Marcar en curso", "in_progress"),
                    ("Enviar a revisión", "submitted"),
                    ("Marcar bloqueada", "blocked"),
                    ("Marcar completada", "completed"),
                ]
                for column, (label, target_status) in zip(quick_cols, transitions):
                    disabled = (
                        row.assignment_kind == "cross_review"
                        and target_status == "completed"
                        and row.outcome is None
                    )
                    if column.button(
                        label,
                        key=f"mine_{target_status}_{row.assignment_id}",
                        disabled=disabled,
                        use_container_width=True,
                    ):
                        try:
                            _database_action(
                                db_path,
                                lambda session, row=row, target_status=target_status: update_work_assignment(
                                    session,
                                    assignment_id=row.assignment_id,
                                    expected_revision=row.revision,
                                    changed_by=actor,
                                    status=target_status,
                                    change_note=f"Cambio rápido a {target_status}",
                                ),
                            )
                        except ValueError as exc:
                            st.error(str(exc))
                        else:
                            rerun_view(st)
                if row.assignment_kind == "cross_review":
                    with st.form(f"mine_cross_outcome_{row.assignment_id}_{row.revision}", enter_to_submit=False):
                        selected_outcome = st.selectbox(
                            "Conclusión de esta segunda revisión",
                            options=list(CROSS_REVIEW_OUTCOMES),
                            index=(
                                list(CROSS_REVIEW_OUTCOMES).index(row.outcome)
                                if row.outcome in CROSS_REVIEW_OUTCOMES
                                else 0
                            ),
                            format_func=lambda value: _OUTCOME_LABELS[value],
                        )
                        outcome_note = st.text_area(
                            "Observaciones de esta segunda revisión", value=row.note or "", height=90
                        )
                        finish_cross = st.form_submit_button(
                            "Guardar la conclusión y completar esta segunda revisión"
                        )
                    if finish_cross:
                        try:
                            _database_action(
                                db_path,
                                lambda session, row=row: update_work_assignment(
                                    session,
                                    assignment_id=row.assignment_id,
                                    expected_revision=row.revision,
                                    changed_by=actor,
                                    status="completed",
                                    outcome=selected_outcome,
                                    assignment_note=outcome_note,
                                    change_note="Cierre de revisión cruzada",
                                ),
                            )
                        except ValueError as exc:
                            st.error(str(exc))
                        else:
                            st.success("Revisión cruzada completada.")
                            rerun_view(st)

    with cross_tab:
        st.subheader("Revisiones primarias disponibles para una segunda revisión")
        if not candidates:
            st.info("No hay revisiones primarias enviadas o completadas que puedan recibir una segunda revisión.")
        for candidate in candidates:
            scope = (
                "Documento completo"
                if candidate.page_start is None
                else (
                    f"Página {candidate.page_start}"
                    if candidate.page_start == candidate.page_end
                    else f"Páginas {candidate.page_start}–{candidate.page_end}"
                )
            )
            with st.container(border=True):
                st.write(f"**{candidate.title}** · {scope}")
                st.caption(
                    f"Revisión primaria: {candidate.assignee} · "
                    f"cruzadas activas {candidate.active_cross_reviews} · "
                    f"completadas {candidate.completed_cross_reviews}"
                )
                if st.button(
                    "Abrir el documento de esta revisión primaria",
                    key=f"cross_open_{candidate.assignment_id}",
                ):
                    _go_to_review(
                        st,
                        source_key=candidate.source_key,
                        page=candidate.page_start,
                    )
                with st.form(f"create_cross_{candidate.assignment_id}", enter_to_submit=False):
                    reviewer = st.text_input(
                        "Persona responsable de la segunda revisión",
                        value=(actor if actor.casefold() != candidate.assignee.casefold() else ""),
                    )
                    priority = st.selectbox(
                        "Prioridad de esta asignación",
                        options=list(ASSIGNMENT_PRIORITIES),
                        index=list(ASSIGNMENT_PRIORITIES).index("normal"),
                        format_func=lambda value: _PRIORITY_LABELS[value],
                    )
                    cross_has_due = st.checkbox(
                        "Agregar una fecha límite a esta segunda revisión",
                        value=False,
                        key=f"cross_has_due_{candidate.assignment_id}",
                    )
                    cross_due_date = st.date_input(
                        "Fecha límite de esta segunda revisión",
                        min_value=DATE_INPUT_MIN,
                        max_value=DATE_INPUT_MAX,
                        key=f"cross_due_{candidate.assignment_id}",
                        help="La fecha solo se guarda cuando está marcada la opción anterior.",
                    )
                    note = st.text_area("Indicaciones para la persona que hará la segunda revisión")
                    cross_submit = st.form_submit_button("Asignar esta segunda revisión")
                if cross_submit:
                    try:
                        _database_action(
                            db_path,
                            lambda session, candidate=candidate: create_cross_review_assignment(
                                session,
                                primary_assignment_id=candidate.assignment_id,
                                assignee=reviewer,
                                created_by=actor,
                                priority=priority,
                                due_at=_due_datetime(cross_has_due, cross_due_date),
                                note=note,
                            ),
                        )
                    except ValueError as exc:
                        st.error(str(exc))
                    else:
                        st.success("Revisión cruzada asignada.")
                        rerun_view(st)
