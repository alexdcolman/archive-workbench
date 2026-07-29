from __future__ import annotations

from datetime import datetime, time, timezone
from pathlib import Path

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
    st.session_state["review_pending_navigation"] = {
        "source_key": source_key,
        "page": page or 1,
    }
    st.rerun()


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
    st.header("Trabajo del equipo")
    st.caption(
        "Las asignaciones coordinan responsabilidades sin modificar automáticamente "
        "el OCR, el texto editable ni sus estados de aprobación."
    )
    assignments, workload, candidates, inventory = _load_all(
        db_path=db_path,
        project_root=project_root,
        project_id=project_id,
    )
    inventory_map = {row.source_key: row for row in inventory}
    assignment_map = {row.assignment_id: row for row in assignments}
    panel_tab, assignments_tab, mine_tab, cross_tab = st.tabs(
        ["Panel", "Asignaciones", "Mi trabajo", "Revisión cruzada"]
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
        cols = st.columns(4)
        cols[0].metric("Asignaciones activas", len(active))
        cols[1].metric("Vencidas", len(overdue))
        cols[2].metric("Enviadas", len(submitted))
        cols[3].metric("Revisiones cruzadas pendientes", len(cross_pending))

        st.subheader("Carga por responsable")
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

        st.subheader("Avance documental")
        st.dataframe(
            [
                {
                    "Documento": row.title,
                    "source_key": row.source_key,
                    "Procesamiento": row.status,
                    "Páginas": row.page_count,
                    "Seleccionadas": row.selected_pages,
                    "Editables": row.editable_pages,
                    "Revisadas": row.reviewed_pages,
                    "Aprobadas": row.approved_pages,
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
        st.subheader("Crear asignación")
        if not inventory:
            st.info("No hay documentos procesables registrados en el catálogo.")
        else:
            with st.form("create_work_assignment"):
                source_key = st.selectbox(
                    "Documento",
                    options=list(inventory_map),
                    format_func=lambda key: f"{inventory_map[key].title} · {key}",
                )
                selected_document = inventory_map[source_key]
                kind = st.selectbox(
                    "Tipo",
                    options=["processing", "primary_review"],
                    format_func=lambda value: _KIND_LABELS[value],
                )
                assignee = st.text_input("Responsable", value=actor or "")
                page_start, page_end = _scope_inputs(
                    st,
                    prefix="create_assignment",
                    page_count=selected_document.page_count,
                )
                priority = st.selectbox(
                    "Prioridad",
                    options=list(ASSIGNMENT_PRIORITIES),
                    index=list(ASSIGNMENT_PRIORITIES).index("normal"),
                    format_func=lambda value: _PRIORITY_LABELS[value],
                )
                has_due = st.checkbox("Definir fecha límite", value=False)
                due_date = st.date_input(
                    "Fecha límite",
                    help="La fecha solo se guarda cuando está marcada la opción anterior.",
                )
                note = st.text_area("Nota")
                submit = st.form_submit_button("Crear asignación")
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
                    st.rerun()

        st.divider()
        st.subheader("Asignaciones existentes")
        filter_cols = st.columns(3)
        people = sorted({row.assignee for row in assignments}, key=str.casefold)
        person_filter = filter_cols[0].multiselect("Responsable", people)
        status_filter = filter_cols[1].multiselect(
            "Estado",
            list(ASSIGNMENT_STATUSES),
            format_func=lambda value: _STATUS_LABELS[value],
        )
        kind_filter = filter_cols[2].multiselect(
            "Tipo",
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
            with st.expander(_assignment_label(row)):
                st.write(f"**Ruta:** {row.archival_path}")
                st.write(f"**Tipo:** {_KIND_LABELS[row.assignment_kind]}")
                st.write(f"**Prioridad:** {_PRIORITY_LABELS[row.priority]}")
                if row.due_at:
                    st.write(f"**Fecha límite:** {row.due_at.date().isoformat()}")
                if row.note:
                    st.write(row.note)
                if row.parent_assignee:
                    st.caption(f"Revisión primaria realizada por {row.parent_assignee}")
                with st.form(f"update_assignment_{row.assignment_id}_{row.revision}"):
                    new_assignee = st.text_input("Responsable", value=row.assignee)
                    new_status = st.selectbox(
                        "Estado",
                        options=list(ASSIGNMENT_STATUSES),
                        index=list(ASSIGNMENT_STATUSES).index(row.status),
                        format_func=lambda value: _STATUS_LABELS[value],
                    )
                    new_priority = st.selectbox(
                        "Prioridad",
                        options=list(ASSIGNMENT_PRIORITIES),
                        index=list(ASSIGNMENT_PRIORITIES).index(row.priority),
                        format_func=lambda value: _PRIORITY_LABELS[value],
                    )
                    keep_due = st.checkbox(
                        "Definir fecha límite",
                        value=row.due_at is not None,
                        key=f"assignment_has_due_{row.assignment_id}",
                    )
                    new_due_date = st.date_input(
                        "Fecha límite",
                        value=row.due_at.date() if row.due_at else datetime.now().date(),
                        key=f"assignment_due_{row.assignment_id}",
                        help="La fecha solo se guarda cuando está marcada la opción anterior.",
                    )
                    new_note = st.text_area("Nota de asignación", value=row.note or "")
                    outcome = None
                    if row.assignment_kind == "cross_review":
                        outcome_options = [None, *CROSS_REVIEW_OUTCOMES]
                        outcome = st.selectbox(
                            "Resultado",
                            options=outcome_options,
                            index=outcome_options.index(row.outcome),
                            format_func=lambda value: (
                                "Sin resultado" if value is None else _OUTCOME_LABELS[value]
                            ),
                        )
                    change_note = st.text_input("Motivo del cambio")
                    update_submit = st.form_submit_button("Guardar cambios")
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
                        st.rerun()
                if st.button(
                    "Abrir documento en Revisión",
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
                if action_col.button("Abrir", key=f"mine_open_{row.assignment_id}"):
                    _go_to_review(st, source_key=row.source_key, page=row.page_start)
                quick_cols = st.columns(4)
                transitions = [
                    ("En curso", "in_progress"),
                    ("Enviar", "submitted"),
                    ("Bloquear", "blocked"),
                    ("Completar", "completed"),
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
                            st.rerun()
                if row.assignment_kind == "cross_review":
                    with st.form(f"mine_cross_outcome_{row.assignment_id}_{row.revision}"):
                        selected_outcome = st.selectbox(
                            "Resultado de revisión cruzada",
                            options=list(CROSS_REVIEW_OUTCOMES),
                            index=(
                                list(CROSS_REVIEW_OUTCOMES).index(row.outcome)
                                if row.outcome in CROSS_REVIEW_OUTCOMES
                                else 0
                            ),
                            format_func=lambda value: _OUTCOME_LABELS[value],
                        )
                        outcome_note = st.text_area(
                            "Observaciones", value=row.note or "", height=90
                        )
                        finish_cross = st.form_submit_button(
                            "Guardar resultado y completar"
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
                            st.rerun()

    with cross_tab:
        st.subheader("Revisiones primarias enviadas")
        if not candidates:
            st.info("No hay revisiones primarias enviadas o completadas.")
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
                    "Abrir revisión primaria",
                    key=f"cross_open_{candidate.assignment_id}",
                ):
                    _go_to_review(
                        st,
                        source_key=candidate.source_key,
                        page=candidate.page_start,
                    )
                with st.form(f"create_cross_{candidate.assignment_id}"):
                    reviewer = st.text_input(
                        "Responsable de revisión cruzada",
                        value=(actor if actor.casefold() != candidate.assignee.casefold() else ""),
                    )
                    priority = st.selectbox(
                        "Prioridad",
                        options=list(ASSIGNMENT_PRIORITIES),
                        index=list(ASSIGNMENT_PRIORITIES).index("normal"),
                        format_func=lambda value: _PRIORITY_LABELS[value],
                    )
                    cross_has_due = st.checkbox(
                        "Definir fecha límite",
                        value=False,
                        key=f"cross_has_due_{candidate.assignment_id}",
                    )
                    cross_due_date = st.date_input(
                        "Fecha límite",
                        key=f"cross_due_{candidate.assignment_id}",
                        help="La fecha solo se guarda cuando está marcada la opción anterior.",
                    )
                    note = st.text_area("Indicaciones")
                    cross_submit = st.form_submit_button("Asignar revisión cruzada")
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
                        st.rerun()
