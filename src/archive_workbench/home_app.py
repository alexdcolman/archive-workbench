from __future__ import annotations

from pathlib import Path

from archive_workbench.ui_navigation import rerun_app, request_app_view

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
    st.header("Inicio del proyecto")
    st.caption(
        "Estado operativo del proyecto y recorrido guiado. Los indicadores se derivan de SQLite "
        "y de los archivos verificables; no modifican el corpus."
    )

    engine = create_sqlite_engine(db_path)
    try:
        with session_scope(engine) as session:
            report = operational_readiness(session, project_root=project_root)
    finally:
        engine.dispose()

    metrics = st.columns(4)
    metrics[0].metric("Listos", report.ready_count)
    metrics[1].metric("Requieren atención", report.attention_count)
    metrics[2].metric("Pendientes", report.pending_count)
    metrics[3].metric("Versión de la base", report.database_revision or "-")

    if report.overall_status == "attention":
        st.warning("Hay cuestiones operativas que conviene resolver antes de ampliar el trabajo.")
    elif report.overall_status == "in_progress":
        st.info("El proyecto es utilizable, pero todavía tiene etapas pendientes.")
    else:
        st.success("Los controles operativos principales están listos.")

    st.subheader("Recorrido del proyecto")
    for item in report.items:
        label = _STATUS_LABELS.get(item.status, item.status)
        with st.container(border=True):
            left, right = st.columns([5, 1])
            with left:
                st.write(f"**{item.label}** · {label}")
                st.write(item.summary)
                if item.detail:
                    st.caption(item.detail)
            with right:
                if item.app_mode and st.button(
                    "Abrir",
                    key=f"home_open_{item.key}",
                    use_container_width=True,
                ):
                    _navigate(st, item.app_mode)

    st.subheader("Secuencia recomendada")
    st.code(
        "Catálogo documental\n"
        "→ Procesar documentos\n"
        "→ Organizar trabajo\n"
        "→ Revisar documentos\n"
        "→ Buscar y registrar entidades\n"
        "→ Explorar relaciones y preparar corpus\n"
        "→ Intercambiar cambios y recuperar",
        language=None,
    )
    st.caption(
        "La barra lateral describe cada sección. Podés volver a Inicio en cualquier momento "
        "sin perder la selección del documento ni el estado guardado."
    )
    st.caption(
        "La comparación OCR/Surya, la optimización de extracción y la estabilización CUDA "
        "siguen diferidas hasta contar con una muestra real suficiente."
    )
