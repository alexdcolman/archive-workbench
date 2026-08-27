from __future__ import annotations

from pathlib import Path

from sqlalchemy import select

from archive_workbench.ui_help import TAB_HELP
from archive_workbench.ui_navigation import (
    request_app_view,
    request_tab,
    rerun_app,
    section_heading,
    tracked_tabs,
)

from archive_workbench.analysis_audit import (
    automatic_analysis_authorization_filter_options,
    automatic_analysis_authorization_rows,
)
from archive_workbench.analysis_quality import quality_scope_caption
from archive_workbench.db import create_sqlite_engine, session_scope
from archive_workbench.db.models import Project
from archive_workbench.operational import recovery_check_rows, run_project_backup_recovery_test
from archive_workbench.project_admin import (
    check_project_health,
    create_project_backup,
    dismiss_project_health_issue,
    inspect_project_backup,
    list_project_backups,
    restore_project_health_issue,
)


_SEVERITY_LABELS = {"error": "Error", "warning": "Advertencia", "info": "Información"}
_RECOVERY_STATUS_LABELS = {"completed": "Completada", "failed": "Fallida"}
_ANALYSIS_SOURCE_LABELS = {
    "ui": "Interfaz",
    "cli": "Terminal",
    "api": "API interna",
    "script": "Script",
}


_ANALYSIS_SCOPE_LABELS = {
    "approved_only": "Sólo páginas aprobadas",
    "broader": "Incluye otros estados de revisión",
}


def _health_issue_action_label(issue) -> str | None:
    code = issue.code
    if code.startswith("graph_"):
        if issue.archival_unit_id:
            return "Abrir Productores y responsables"
        return "Abrir Entidades y menciones"
    if code == "stale_mentions":
        return "Abrir Entidades y menciones"
    if code in {"search_index_pending", "missing_search_index"}:
        return "Abrir Búsqueda textual"
    if code == "semantic_index_pending":
        return "Abrir Búsqueda semántica"
    if code in {"missing_export_file", "modified_export_file"}:
        return "Abrir Historial de exportaciones"
    if code in {"missing_local_file", "file_size_mismatch", "registered_hash_mismatch"}:
        return "Abrir Catálogo"
    if code in {"missing_database", "sqlite_quick_check", "foreign_key_check"}:
        return "Abrir Probar recuperación"
    if code == "missing_directory":
        path = str(issue.resource_path or "")
        top = path.split("/", 1)[0]
        return {
            "data": "Abrir Catálogo",
            "corpus": "Abrir Catálogo",
            "derivatives": "Abrir Procesar documentos",
            "extraction": "Abrir Procesar documentos",
            "indexes": "Abrir Búsqueda textual",
            "exports": "Abrir Exportar corpus",
            "exchange": "Abrir Intercambiar cambios",
            "backups": "Abrir Copias de seguridad",
        }.get(top, "Abrir Administrar y recuperar")
    return None


def _navigate_health_issue(st, issue) -> None:
    code = issue.code
    if code.startswith("graph_"):
        if issue.archival_unit_id:
            st.session_state["catalog_main_task"] = "units"
            st.session_state["catalog_query"] = ""
            st.session_state["catalog_level_filter"] = ""
            st.session_state["catalog_status_filter"] = ""
            st.session_state["catalog_pending_unit_id"] = issue.archival_unit_id
            st.session_state["catalog_pending_detail_tab"] = "Productores y responsables"
            request_app_view(st, mode="catalog")
        else:
            st.session_state["authority_main_task"] = "review"
            if issue.entity_id:
                st.session_state["authority_selected"] = issue.entity_id
            tab = "Menciones" if issue.mention_id and not issue.relation_id else "Relaciones"
            request_tab(st, key="authority_tabs", label=tab)
            request_app_view(st, mode="authorities")
        rerun_app(st)
        return
    if code == "stale_mentions":
        st.session_state["authority_main_task"] = "review"
        request_tab(st, key="authority_tabs", label="Menciones")
        request_app_view(st, mode="authorities")
        rerun_app(st)
        return
    if code in {"search_index_pending", "missing_search_index"}:
        st.session_state["search_rebuild_open"] = True
        request_app_view(st, mode="search")
        rerun_app(st)
        return
    if code == "semantic_index_pending":
        if issue.semantic_profile_id:
            st.session_state["semantic_requested_profile_id"] = issue.semantic_profile_id
        request_tab(st, key="semantic_tabs", label="Configurar el índice de búsqueda")
        request_app_view(st, mode="semantic")
        rerun_app(st)
        return
    if code in {"missing_export_file", "modified_export_file"}:
        audiovisual = issue.export_material_type == "audiovisual_transcript_segments"
        st.session_state["export_surface"] = "audiovisual" if audiovisual else "documentos"
        request_tab(
            st,
            key="export_audiovisual_tabs" if audiovisual else "export_tabs",
            label="Historial de exportaciones",
        )
        request_app_view(st, mode="export")
        rerun_app(st)
        return
    if code in {"missing_local_file", "file_size_mismatch", "registered_hash_mismatch"}:
        st.session_state["catalog_main_task"] = "units"
        if issue.resource_path:
            st.session_state["catalog_query"] = Path(issue.resource_path).name
        request_app_view(st, mode="catalog")
        rerun_app(st)
        return
    if code in {"missing_database", "sqlite_quick_check", "foreign_key_check"}:
        request_tab(st, key="admin_tabs", label="Probar recuperación")
        rerun_app(st)
        return
    if code == "missing_directory":
        top = str(issue.resource_path or "").split("/", 1)[0]
        mode = {
            "data": "catalog",
            "corpus": "catalog",
            "derivatives": "processing",
            "extraction": "processing",
            "indexes": "search",
            "exports": "export",
            "exchange": "exchange",
        }.get(top)
        if mode:
            request_app_view(st, mode=mode)
        elif top == "backups":
            request_tab(st, key="admin_tabs", label="Copias de seguridad")
        else:
            request_tab(st, key="admin_tabs", label="Integridad")
        rerun_app(st)


def _render_health_issue(st, *, issue, project_root: Path, actor: str) -> None:
    action_label = _health_issue_action_label(issue)
    with st.container(border=True):
        st.caption(_SEVERITY_LABELS.get(issue.severity, issue.severity))
        st.write(issue.message)
        if issue.code == "semantic_index_pending" and issue.detail:
            st.caption(issue.detail)
        action_count = int(bool(action_label)) + int(bool(issue.dismissible))
        if action_count:
            columns = st.columns(action_count)
            index = 0
            if action_label:
                if columns[index].button(
                    action_label,
                    key=f"admin_health_open_{issue.code}_{issue.subject_key or issue.detail or index}",
                    use_container_width=True,
                ):
                    _navigate_health_issue(st, issue)
                index += 1
            if issue.dismissible:
                if columns[index].button(
                    "Descartar este aviso",
                    key=f"admin_health_dismiss_{issue.code}_{issue.subject_key}",
                    use_container_width=True,
                ):
                    try:
                        dismiss_project_health_issue(
                            project_root=project_root,
                            issue=issue,
                            dismissed_by=actor or "local_user",
                        )
                    except (ValueError, OSError) as exc:
                        st.error(str(exc))
                    else:
                        st.session_state["admin_health_notice"] = (
                            "Aviso descartado. Podés volver a mostrarlo desde Avisos descartados."
                        )
                        rerun_app(st)
        with st.expander("Detalles técnicos del diagnóstico", expanded=False):
            st.write(f"Código interno: `{issue.code}`")
            if issue.detail:
                st.write(f"Detalle: `{issue.detail}`")


def _render_dismissed_health_issues(
    st, *, issues, project_root: Path
) -> None:
    if not issues:
        return
    show = st.toggle(
        f"Ver avisos descartados ({len(issues)})",
        value=bool(st.session_state.get("admin_show_dismissed_health", False)),
        key="admin_show_dismissed_health",
    )
    if not show:
        return
    for issue in issues:
        with st.container(border=True):
            st.write(issue.message)
            if st.button(
                "Volver a mostrar este aviso",
                key=f"admin_health_restore_{issue.code}_{issue.subject_key}",
            ):
                try:
                    restore_project_health_issue(
                        project_root=project_root,
                        issue=issue,
                    )
                except (ValueError, OSError) as exc:
                    st.error(str(exc))
                else:
                    rerun_app(st)


def render_admin_view(st, *, project_root: Path, db_path: Path, actor: str) -> None:
    section_heading(st, "Administrar y recuperar")

    check_tab, backup_tab, recovery_tab, restore_tab, analysis_tab = tracked_tabs(
        st,
        [
            "Integridad",
            "Copias de seguridad",
            "Probar recuperación",
            "Restaurar",
            "Autorizaciones de análisis",
        ],
        key="admin_tabs",
        help_by_label=TAB_HELP["admin_tabs"],
    )
    with check_tab:
        notice = st.session_state.pop("admin_health_notice", None)
        if notice:
            st.success(notice)
        if st.button("Comprobar ahora la integridad del proyecto", type="primary"):
            st.session_state["admin_run_health"] = True
        if st.session_state.get("admin_run_health"):
            engine = create_sqlite_engine(db_path)
            try:
                with session_scope(engine) as session:
                    report = check_project_health(session, project_root=project_root)
            except (ValueError, RuntimeError, OSError) as exc:
                st.error(str(exc))
                report = None
            finally:
                engine.dispose()
            if report is not None:
                cols = st.columns(3)
                cols[0].metric("Problemas que impiden continuar", report.error_count)
                cols[1].metric("Problemas que conviene revisar", report.warning_count)
                cols[2].metric("Comprobaciones informativas", report.info_count)

                active_attention = [
                    issue for issue in report.issues if issue.severity in {"error", "warning"}
                ]
                information = [
                    issue for issue in report.issues if issue.severity == "info"
                ]
                if active_attention:
                    st.subheader("Problemas que requieren atención")
                    for issue in active_attention:
                        _render_health_issue(
                            st, issue=issue, project_root=project_root, actor=actor
                        )
                else:
                    st.success("No hay problemas activos que impidan continuar ni advertencias pendientes.")

                if information:
                    show_info = st.toggle(
                        f"Ver comprobaciones informativas ({len(information)})",
                        value=bool(st.session_state.get("admin_show_health_info", False)),
                        key="admin_show_health_info",
                    )
                    if show_info:
                        for issue in information:
                            _render_health_issue(
                                st, issue=issue, project_root=project_root, actor=actor
                            )

                _render_dismissed_health_issues(
                    st, issues=report.dismissed_issues, project_root=project_root
                )

                with st.expander("Detalles técnicos de la comprobación", expanded=False):
                    st.write(
                        "Revisión de la base de datos del proyecto: "
                        f"`{report.database_revision or '-'}`"
                    )
                    st.write(f"Comprobación ejecutada: `{report.checked_at}`")

    with backup_tab:
        st.subheader("Crear una nueva copia de seguridad")
        with st.form("admin_create_backup", clear_on_submit=True, enter_to_submit=False):
            note = st.text_input("Nota opcional sobre esta copia de seguridad")
            submit = st.form_submit_button("Crear copia de seguridad", type="primary")
        if submit:
            try:
                info = create_project_backup(
                    project_root=project_root,
                    created_by=actor or "local_user",
                    note=note,
                )
            except (ValueError, OSError) as exc:
                st.error(str(exc))
            else:
                st.success("Copia de seguridad creada correctamente.")
                with st.expander("Detalles técnicos de la copia de seguridad", expanded=False):
                    st.write(f"Ruta dentro del proyecto: `{info.path.relative_to(project_root)}`")
                    st.write(f"Huella SHA-256: `{info.backup_sha256}`")

        backups = list_project_backups(project_root)
        st.subheader("Copias de seguridad disponibles")
        if not backups:
            st.caption("Todavía no hay copias de seguridad manuales.")
        for info in backups:
            backup_panel_open = st.toggle(
                f"{info.path.name} · {info.created_at}",
                value=False,
                key=f"admin_backup_panel_{info.backup_sha256}",
            )
            if backup_panel_open:
                with st.container(border=True):
                    st.write(f"Proyecto: **{info.project_name or info.project_id or '-'}**")
                    st.write(f"Versión de la base: `{info.database_revision or '-'}`")
                    st.write(f"Creado por: `{info.created_by}`")
                    if info.note:
                        st.write(info.note)
                    st.caption(f"SHA-256 ZIP: {info.backup_sha256}")
                    if st.button("Volver a comprobar esta copia de seguridad", key=f"admin_verify_{info.backup_sha256}"):
                        try:
                            verified = inspect_project_backup(info.path)
                        except (ValueError, OSError) as exc:
                            st.error(str(exc))
                        else:
                            st.success("La copia de seguridad está íntegra y puede usarse para una recuperación.")
                            with st.expander("Detalles técnicos de esta comprobación", expanded=False):
                                st.write(f"Huella de la base incluida: `{verified.database_sha256}`")
                                st.write(
                                    f"Archivos de configuración incluidos: {verified.config_file_count}"
                                )

    with recovery_tab:
        backups = list_project_backups(project_root)
        if not backups:
            st.info("Primero creá una copia de seguridad verificable.")
        else:
            selected = st.selectbox(
                "Copia de seguridad a probar",
                options=backups,
                format_func=lambda row: f"{row.path.name} · {row.created_at}",
                key="admin_recovery_backup",
            )
            recovery_note = st.text_input("Nota opcional sobre esta prueba de recuperación", key="admin_recovery_note")
            if st.button("Ejecutar prueba de recuperación", type="primary"):
                engine = create_sqlite_engine(db_path)
                try:
                    with session_scope(engine) as session:
                        result = run_project_backup_recovery_test(
                            session,
                            project_root=project_root,
                            backup_path=selected.path,
                            tested_by=actor or "local_user",
                            note=recovery_note or None,
                        )
                except (ValueError, RuntimeError, OSError) as exc:
                    st.error(str(exc))
                else:
                    if result.status == "completed":
                        st.success(
                            "La copia pudo verificarse, migrarse y abrirse sin modificar el proyecto activo."
                        )
                    else:
                        st.error(str(result.details.get("error") or "La prueba falló"))

        engine = create_sqlite_engine(db_path)
        try:
            with session_scope(engine) as session:
                history = recovery_check_rows(session, limit=20)
        finally:
            engine.dispose()
        st.subheader("Pruebas de recuperación realizadas")
        if not history:
            st.caption("Todavía no hay pruebas registradas.")
        for row in history:
            icon = "✅" if row.status == "completed" else "❌"
            with st.expander(
                f"{icon} {row.backup_relative_path} · {row.tested_at.isoformat(timespec='minutes')}"
            ):
                st.write(f"Estado de la prueba de recuperación: **{_RECOVERY_STATUS_LABELS.get(row.status, row.status)}**")
                st.write(f"Prueba ejecutada por: `{row.tested_by}`")
                st.write(
                    f"Revisión de la base: `{row.source_database_revision or '-'}` → "
                    f"`{row.upgraded_database_revision or '-'}`"
                )
                if row.note:
                    st.write(row.note)
                st.json(row.details)

    with restore_tab:
        st.warning(
            "Restaurar una copia de seguridad reemplaza la base de datos que usa actualmente este proyecto. "
            "Por seguridad, la restauración sólo se realiza con la aplicación detenida y crea antes una copia del estado actual."
        )
        backups = list_project_backups(project_root)
        if backups:
            selected = st.selectbox(
                "Copia de seguridad a restaurar",
                options=backups,
                format_func=lambda row: f"{row.path.name} · {row.created_at}",
                key="admin_restore_backup",
            )
            with st.expander("Ver comando técnico de restauración"):
                st.code(
                    "archive-workbench project-restore-backup "
                    f"{project_root} {selected.path} --restored-by {actor or 'local_user'} "
                    "--confirm-restore",
                    language="bash",
                )
        else:
            st.caption("No hay copias de seguridad disponibles para restaurar.")

    with analysis_tab:
        engine = create_sqlite_engine(db_path)
        try:
            with session_scope(engine) as session:
                project_id = session.execute(select(Project.id)).scalar_one()
                filter_options = automatic_analysis_authorization_filter_options(
                    session, project_id=project_id
                )
        finally:
            engine.dispose()

        kind_labels = {kind: label for kind, label in filter_options.analysis_kinds}
        filter_row_1 = st.columns([2.2, 1.4, 1.2])
        with filter_row_1[0]:
            query = st.text_input(
                "Buscar autorizaciones",
                placeholder="Buscar por responsable, fundamento o destino",
                key="admin_analysis_query",
            )
        with filter_row_1[1]:
            analysis_kind = st.selectbox(
                "Tipo de análisis",
                options=[""] + list(kind_labels),
                format_func=lambda value: "Todos los análisis" if not value else kind_labels[value],
                key="admin_analysis_kind",
            )
        with filter_row_1[2]:
            confirmed_by = st.selectbox(
                "Responsable",
                options=[""] + list(filter_options.confirmed_by),
                format_func=lambda value: "Todas las personas" if not value else value,
                key="admin_analysis_confirmed_by",
            )

        filter_row_2 = st.columns([1.4, 1.6, 1])
        with filter_row_2[0]:
            source = st.selectbox(
                "Origen de la autorización",
                options=[""] + list(filter_options.sources),
                format_func=lambda value: (
                    "Todos los orígenes"
                    if not value
                    else _ANALYSIS_SOURCE_LABELS.get(value, value)
                ),
                key="admin_analysis_source",
            )
        with filter_row_2[1]:
            scope_key = st.selectbox(
                "Alcance de páginas",
                options=[""] + list(filter_options.scope_keys),
                format_func=lambda value: (
                    "Todos los alcances"
                    if not value
                    else _ANALYSIS_SCOPE_LABELS.get(value, value)
                ),
                key="admin_analysis_scope",
            )
        with filter_row_2[2]:
            limit = st.selectbox(
                "Cantidad a mostrar",
                options=[25, 50, 100, 250],
                index=1,
                key="admin_analysis_limit",
            )

        engine = create_sqlite_engine(db_path)
        try:
            with session_scope(engine) as session:
                analysis_rows = automatic_analysis_authorization_rows(
                    session,
                    project_id=project_id,
                    analysis_kind=analysis_kind or None,
                    confirmed_by=confirmed_by or None,
                    source=source or None,
                    scope_key=scope_key or None,
                    query=query or None,
                    limit=int(limit),
                )
        finally:
            engine.dispose()

        if not analysis_rows:
            st.caption("No hay autorizaciones que coincidan con los filtros actuales.")
            return
        st.caption(f"Mostrando {len(analysis_rows)} autorizaciones, de la más reciente a la más antigua.")
        for row in analysis_rows:
            scope_label = quality_scope_caption(row.page_review_statuses)
            title = (
                f"{row.analysis_label} · {row.confirmed_by} · "
                f"{row.created_at.isoformat(timespec='minutes')}"
            )
            with st.expander(title):
                if row.scope_key == "approved_only":
                    st.info(scope_label)
                else:
                    st.warning(scope_label)
                st.write(f"Origen: **{_ANALYSIS_SOURCE_LABELS.get(row.source, row.source)}**")
                if row.confirmation_reason:
                    st.write(f"Fundamento: {row.confirmation_reason}")
                if row.target_type or row.target_id:
                    st.write(
                        "Destino: "
                        f"`{row.target_type or '-'}` · `{row.target_id or '-'}`"
                    )
                with st.expander("Datos técnicos de esta autorización"):
                    st.code(
                        "\n".join(
                            [
                                f"autorizacion={row.authorization_id}",
                                f"tipo={row.analysis_kind}",
                                f"alcance={row.scope_key}",
                                "estados=" + ",".join(row.page_review_statuses),
                                f"parametros_sha256={row.parameters_sha256 or '-'}",
                            ]
                        ),
                        language=None,
                    )
