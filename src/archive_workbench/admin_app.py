from __future__ import annotations

from pathlib import Path

from archive_workbench.db import create_sqlite_engine, session_scope
from archive_workbench.operational import recovery_check_rows, run_project_backup_recovery_test
from archive_workbench.project_admin import (
    check_project_health,
    create_project_backup,
    inspect_project_backup,
    list_project_backups,
)


_SEVERITY_LABELS = {"error": "Error", "warning": "Advertencia", "info": "Información"}


def render_admin_view(st, *, project_root: Path, db_path: Path, actor: str) -> None:
    st.header("Administración")
    st.caption(
        "Controles globales, copias verificables y pruebas no destructivas de recuperación. "
        "Los PDF y TIFF no se incluyen en estos backups: permanecen inventariados por SHA-256."
    )

    check_tab, backup_tab, recovery_tab, restore_tab = st.tabs(
        ["Validar proyecto", "Crear y verificar backups", "Probar recuperación", "Restaurar"]
    )
    with check_tab:
        if st.button("Ejecutar validación completa", type="primary"):
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
                cols = st.columns(4)
                cols[0].metric("Errores", report.error_count)
                cols[1].metric("Advertencias", report.warning_count)
                cols[2].metric("Información", report.info_count)
                cols[3].metric("Revisión DB", report.database_revision or "-")
                for issue in report.issues:
                    body = f"**{_SEVERITY_LABELS.get(issue.severity, issue.severity)} · {issue.code}**\n\n{issue.message}"
                    if issue.detail:
                        body += f"\n\n`{issue.detail}`"
                    if issue.severity == "error":
                        st.error(body)
                    elif issue.severity == "warning":
                        st.warning(body)
                    else:
                        st.info(body)

    with backup_tab:
        st.subheader("Nueva copia verificable")
        with st.form("admin_create_backup", clear_on_submit=True):
            note = st.text_input("Nota opcional")
            submit = st.form_submit_button("Crear backup", type="primary")
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
                st.success(f"Backup creado: `{info.path.relative_to(project_root)}`")
                st.code(info.backup_sha256, language=None)

        backups = list_project_backups(project_root)
        st.subheader("Backups disponibles")
        if not backups:
            st.caption("Todavía no hay backups manuales.")
        for info in backups:
            with st.expander(f"{info.path.name} · {info.created_at}"):
                st.write(f"Proyecto: **{info.project_name or info.project_id or '-'}**")
                st.write(f"Revisión DB: `{info.database_revision or '-'}`")
                st.write(f"Creado por: `{info.created_by}`")
                if info.note:
                    st.write(info.note)
                st.caption(f"SHA-256 ZIP: {info.backup_sha256}")
                if st.button("Verificar nuevamente", key=f"admin_verify_{info.backup_sha256}"):
                    try:
                        verified = inspect_project_backup(info.path)
                    except (ValueError, OSError) as exc:
                        st.error(str(exc))
                    else:
                        st.success(
                            f"Backup íntegro · base {verified.database_sha256[:16]}… · "
                            f"{verified.config_file_count} archivos de configuración"
                        )

    with recovery_tab:
        st.subheader("Prueba no destructiva")
        st.caption(
            "Extrae el backup en una carpeta temporal, comprueba claves foráneas, aplica las "
            "migraciones actuales y abre la copia. La base activa no se reemplaza."
        )
        backups = list_project_backups(project_root)
        if not backups:
            st.info("Primero creá un backup verificable.")
        else:
            selected = st.selectbox(
                "Backup a probar",
                options=backups,
                format_func=lambda row: f"{row.path.name} · {row.created_at}",
                key="admin_recovery_backup",
            )
            recovery_note = st.text_input("Nota opcional", key="admin_recovery_note")
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
        st.subheader("Historial")
        if not history:
            st.caption("Todavía no hay pruebas registradas.")
        for row in history:
            icon = "✅" if row.status == "completed" else "❌"
            with st.expander(
                f"{icon} {row.backup_relative_path} · {row.tested_at.isoformat(timespec='minutes')}"
            ):
                st.write(f"Estado: `{row.status}`")
                st.write(f"Probado por: `{row.tested_by}`")
                st.write(
                    f"Revisión: `{row.source_database_revision or '-'}` → "
                    f"`{row.upgraded_database_revision or '-'}`"
                )
                if row.note:
                    st.write(row.note)
                st.json(row.details)

    with restore_tab:
        st.warning(
            "La restauración reemplaza la base activa. Debe hacerse con Streamlit detenido. "
            "El comando crea primero un backup automático del estado actual."
        )
        backups = list_project_backups(project_root)
        if backups:
            selected = st.selectbox(
                "Backup a restaurar",
                options=backups,
                format_func=lambda row: f"{row.path.name} · {row.created_at}",
                key="admin_restore_backup",
            )
            st.code(
                "archive-workbench project-restore-backup "
                f"{project_root} {selected.path} --restored-by {actor or 'local_user'} "
                "--confirm-restore",
                language="bash",
            )
        else:
            st.caption("No hay backups disponibles para restaurar.")
