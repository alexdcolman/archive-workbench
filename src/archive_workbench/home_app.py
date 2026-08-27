from __future__ import annotations

from pathlib import Path

from archive_workbench.ui_navigation import rerun_app, request_app_view, section_heading
from archive_workbench.db import create_sqlite_engine, session_scope
from archive_workbench.operational import operational_readiness


_STATUS_LABELS = {
    "ready": "Listo",
    "attention": "Requiere atención",
    "pending": "Pendiente",
    "optional": "Opcional",
}


def _navigate(st, mode: str) -> None:
    request_app_view(st, mode=mode)
    rerun_app(st)


def render_home_view(st, *, project_root: Path, db_path: Path, actor: str) -> None:
    section_heading(st, "Inicio")

    engine = create_sqlite_engine(db_path)
    try:
        with session_scope(engine) as session:
            report = operational_readiness(session, project_root=project_root)
    finally:
        engine.dispose()

    metrics = st.columns(3)
    metrics[0].metric("Etapas listas", report.ready_count)
    metrics[1].metric("Etapas que requieren atención", report.attention_count)
    metrics[2].metric("Etapas pendientes", report.pending_count)

    if report.overall_status == "attention":
        st.warning("Hay etapas del proyecto que requieren revisión antes de continuar con tareas que dependan de ellas.")
    elif report.overall_status == "in_progress":
        st.info("El proyecto puede continuar, aunque algunas etapas del trabajo con el corpus todavía están pendientes.")
    else:
        st.success("Las comprobaciones principales del proyecto están al día.")

    st.subheader("Estado del proyecto")
    for item in report.items:
        label = _STATUS_LABELS.get(item.status, item.status)
        left, right = st.columns([6, 1])
        with left:
            st.markdown(f"**{item.label}** · {label}")
            st.caption(item.summary)
            if item.detail and item.status != "ready":
                st.caption(item.detail)
        with right:
            if item.app_mode and st.button(
                f"Abrir {item.label}",
                key=f"home_open_{item.key}",
                help=f"Abrir {item.label}",
                use_container_width=True,
            ):
                _navigate(st, item.app_mode)
