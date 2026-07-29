from __future__ import annotations

from pathlib import Path

from sqlalchemy import func, select

from archive_workbench.db import create_sqlite_engine, session_scope
from archive_workbench.db.models import EditablePage
from archive_workbench.editing import bootstrap_editable_layer
from archive_workbench.extraction import (
    extract_documents,
    extraction_doctor,
    load_extraction_profile,
    select_extraction_pages,
)
from archive_workbench.preprocessing import prepare_derivatives
from archive_workbench.processing import (
    create_processing_job,
    extraction_candidate_runs,
    failed_extraction_pages,
    finish_processing_job,
    processing_inventory_rows,
    processing_job_item_rows,
    processing_job_rows,
    start_processing_job,
    update_processing_job_item,
)

_STATUS_LABELS = {
    "missing_local_file": "Sin archivo local",
    "file_available": "Archivo disponible",
    "pending_preparation": "Pendiente de preparación",
    "prepared": "Preparado",
    "pending_extraction": "Pendiente de extracción",
    "incomplete_extraction": "Extracción incompleta",
    "pending_selection": "Pendiente de selección",
    "ready_for_review": "Listo para revisión",
    "in_review": "En revisión",
    "completed": "Completado",
    "error": "Con errores",
}
_OPERATION_LABELS = {
    "prepare": "Preparar páginas",
    "extract": "Extraer texto",
    "retry_failed": "Reintentar páginas fallidas",
    "bootstrap": "Inicializar capa editable",
}
_JOB_STATUS_LABELS = {
    "queued": "En cola",
    "running": "En ejecución",
    "completed": "Completado",
    "completed_with_warnings": "Completado con advertencias",
    "warning": "Advertencia",
    "failed": "Fallido",
}


def _profiles(project_root: Path):
    rows = []
    config_root = project_root / "config"
    for path in sorted(config_root.glob("extraction*.yaml")):
        if path.name.endswith(".template.yaml"):
            continue
        try:
            profile = load_extraction_profile(path)
        except (ValueError, OSError):
            continue
        rows.append((path, profile))
    return rows


def _load_inventory(*, db_path: Path, project_root: Path, project_id: str):
    engine = create_sqlite_engine(db_path)
    try:
        with session_scope(engine) as session:
            return processing_inventory_rows(
                session, project_root=project_root, project_id=project_id
            )
    finally:
        engine.dispose()


def _mark_item(
    *,
    db_path: Path,
    job_id: str,
    source_key: str,
    status: str,
    pages=None,
    message: str | None = None,
    detail: dict | None = None,
) -> None:
    engine = create_sqlite_engine(db_path)
    try:
        with session_scope(engine) as session:
            update_processing_job_item(
                session,
                job_id=job_id,
                source_key=source_key,
                status=status,
                pages=pages,
                message=message,
                detail=detail,
            )
    finally:
        engine.dispose()


def _finish_job(*, db_path: Path, job_id: str) -> None:
    engine = create_sqlite_engine(db_path)
    try:
        with session_scope(engine) as session:
            finish_processing_job(session, job_id=job_id)
    finally:
        engine.dispose()


def _summary_message(operation: str, summary) -> tuple[str, str, dict]:
    if operation == "prepare":
        detail = {
            "objects_seen": summary.objects_seen,
            "runs_created": summary.runs_created,
            "runs_reused": summary.runs_reused,
            "assets_created": summary.assets_created,
            "failed": summary.failed,
            "warnings": list(summary.warnings),
        }
        message = (
            f"Derivados: {summary.runs_created} corridas nuevas, "
            f"{summary.runs_reused} reutilizadas y {summary.assets_created} archivos."
        )
        if summary.failed:
            return "failed", message, detail
        if summary.warnings:
            return "warning", message, detail
        return "completed", message, detail
    if operation in {"extract", "retry_failed"}:
        detail = {
            "objects_seen": summary.objects_seen,
            "runs_created": summary.runs_created,
            "runs_reused": summary.runs_reused,
            "pages_processed": summary.pages_processed,
            "objects_created": summary.objects_created,
            "characters_created": summary.characters_created,
            "failed": summary.failed,
            "warnings": list(summary.warnings),
        }
        message = (
            f"Extracción: {summary.pages_processed} páginas, {summary.objects_created} objetos "
            f"y {summary.characters_created} caracteres."
        )
        if summary.failed:
            return "failed", message, detail
        if summary.warnings:
            return "warning", message, detail
        return "completed", message, detail
    detail = {
        "documents_seen": summary.documents_seen,
        "pages_created": summary.pages_created,
        "pages_reused": summary.pages_reused,
        "pages_stale": summary.pages_stale,
        "objects_created": summary.objects_created,
        "warnings": list(summary.warnings),
    }
    message = (
        f"Capa editable: {summary.pages_created} páginas nuevas, "
        f"{summary.pages_reused} reutilizadas y {summary.objects_created} objetos."
    )
    if summary.warnings:
        return "warning", message, detail
    return "completed", message, detail


def _execute_batch(
    st,
    *,
    project_root: Path,
    db_path: Path,
    decisions,
    project_id: str,
    actor: str,
    operation: str,
    source_keys: list[str],
    profile_path: Path | None,
    force: bool,
) -> None:
    profile = None
    parameters: dict = {"force": force}
    if operation in {"extract", "retry_failed"}:
        if profile_path is None:
            st.error("Debe elegir un perfil de extracción.")
            return
        profile = load_extraction_profile(profile_path)
        doctor = extraction_doctor(profile)
        if not doctor.ready:
            st.error("El entorno requerido por el perfil no está listo.")
            for check in doctor.checks:
                if check.required and not check.ok:
                    st.write(f"**{check.name}:** {check.detail}")
            return
        parameters.update(
            profile_path=profile_path.relative_to(project_root).as_posix(),
            profile_key=profile.profile_key,
            backend=profile.backend,
            device=profile.device,
            selection_policy="never",
        )

    engine = create_sqlite_engine(db_path)
    try:
        with session_scope(engine) as session:
            job = create_processing_job(
                session,
                project_id=project_id,
                operation=operation,
                source_keys=source_keys,
                created_by=actor or "local_user",
                parameters=parameters,
            )
            start_processing_job(session, job_id=job.id)
            job_id = job.id
    finally:
        engine.dispose()

    progress = st.progress(0.0)
    status_box = st.empty()
    for index, source_key in enumerate(source_keys, start=1):
        status_box.write(f"Procesando **{source_key}** ({index}/{len(source_keys)})")
        _mark_item(
            db_path=db_path,
            job_id=job_id,
            source_key=source_key,
            status="running",
        )
        pages: list[int] = []
        try:
            engine = create_sqlite_engine(db_path)
            try:
                with session_scope(engine) as session:
                    if operation == "prepare":
                        summary = prepare_derivatives(
                            session,
                            project_root=project_root,
                            decisions=decisions,
                            source_keys={source_key},
                            force=force,
                        )
                    elif operation == "extract":
                        assert profile is not None
                        summary = extract_documents(
                            session,
                            project_root=project_root,
                            decisions=decisions,
                            profile=profile,
                            source_keys={source_key},
                            force=force,
                            created_by=actor or "local_user",
                            selection_policy="never",
                        )
                    elif operation == "retry_failed":
                        assert profile is not None
                        pages = failed_extraction_pages(session, source_key=source_key)
                        if not pages:
                            raise ValueError("No hay páginas fallidas registradas para reintentar")
                        summary = extract_documents(
                            session,
                            project_root=project_root,
                            decisions=decisions,
                            profile=profile,
                            source_keys={source_key},
                            selected_pages=set(pages),
                            force=True,
                            created_by=actor or "local_user",
                            selection_policy="never",
                        )
                    else:
                        summary = bootstrap_editable_layer(
                            session,
                            decisions=decisions,
                            created_by=actor or "local_user",
                            source_keys={source_key},
                        )
            finally:
                engine.dispose()
            item_status, message, detail = _summary_message(operation, summary)
            _mark_item(
                db_path=db_path,
                job_id=job_id,
                source_key=source_key,
                status=item_status,
                pages=pages,
                message=message,
                detail=detail,
            )
        except (ValueError, RuntimeError, OSError, FileNotFoundError) as exc:
            _mark_item(
                db_path=db_path,
                job_id=job_id,
                source_key=source_key,
                status="failed",
                pages=pages,
                message=str(exc),
                detail={"exception_type": type(exc).__name__},
            )
        progress.progress(index / len(source_keys))
    _finish_job(db_path=db_path, job_id=job_id)
    st.session_state["processing_flash"] = (
        f"Trabajo {_OPERATION_LABELS[operation].lower()} finalizado. "
        "La selección canónica no fue modificada automáticamente."
    )
    st.rerun()


def _open_review(st, *, source_key: str, page: int) -> None:
    st.session_state["review_pending_navigation"] = {
        "source_key": source_key,
        "page": page,
    }
    st.rerun()


def render_processing_view(
    st,
    *,
    project_root: Path,
    db_path: Path,
    decisions,
    project_id: str,
    actor: str,
) -> None:
    st.header("Procesamiento")
    st.caption(
        "Coordina archivos, preparación, extracción, selección e inicialización editable. "
        "Cada OCR queda como una versión candidata: ninguna corrida reemplaza por sí sola "
        "la selección canónica ni una edición ya iniciada."
    )
    flash = st.session_state.pop("processing_flash", None)
    if flash:
        st.success(flash)

    inventory = _load_inventory(
        db_path=db_path, project_root=project_root, project_id=project_id
    )
    counts = {key: sum(row.status == key for row in inventory) for key in _STATUS_LABELS}
    metrics = st.columns(6)
    metrics[0].metric("Documentos", len(inventory))
    metrics[1].metric("Sin archivo", counts["missing_local_file"])
    metrics[2].metric("Por preparar", counts["pending_preparation"] + counts["file_available"])
    metrics[3].metric(
        "Por seleccionar",
        counts["pending_selection"] + counts["incomplete_extraction"],
    )
    metrics[4].metric("En revisión", counts["ready_for_review"] + counts["in_review"])
    metrics[5].metric("Completados", counts["completed"])

    inventory_tab, execute_tab, selection_tab, history_tab = st.tabs(
        ["Inventario", "Ejecutar", "Selección canónica", "Historial"]
    )

    with inventory_tab:
        filter_cols = st.columns([2, 1.2])
        query = filter_cols[0].text_input(
            "Buscar documento",
            placeholder="Título, source_key, ruta archivística o archivo",
            key="processing_inventory_query",
        )
        status_filter = filter_cols[1].multiselect(
            "Estado",
            options=list(_STATUS_LABELS),
            format_func=lambda value: _STATUS_LABELS[value],
            key="processing_inventory_status",
        )
        needle = query.strip().casefold()
        visible = [
            row
            for row in inventory
            if (not status_filter or row.status in status_filter)
            and (
                not needle
                or needle
                in " ".join(
                    [
                        row.source_key,
                        row.title,
                        row.archival_path,
                        row.original_filename,
                    ]
                ).casefold()
            )
        ]
        st.dataframe(
            [
                {
                    "Estado": _STATUS_LABELS[row.status],
                    "Documento": row.title,
                    "Clave": row.source_key,
                    "Ruta archivística": row.archival_path,
                    "Archivo": row.original_filename,
                    "Páginas": row.page_count,
                    "Extraídas": row.extracted_pages,
                    "Seleccionadas": row.selected_pages,
                    "Editables": row.editable_pages,
                    "Aprobadas": row.approved_pages,
                    "Perfil OCR": row.extraction_profile,
                    "Error": row.last_error,
                }
                for row in visible
            ],
            use_container_width=True,
            hide_index=True,
        )
        st.caption(
            "‘Archivo disponible’ indica que existe una copia local todavía no verificada por "
            "el preprocesamiento. ‘Completado’ exige que todas las páginas conocidas "
            "estén aprobadas."
        )

    with execute_tab:
        if not inventory:
            st.info("No hay fuentes procesables registradas en el catálogo.")
        else:
            operation = st.radio(
                "Operación",
                options=["prepare", "extract", "retry_failed", "bootstrap"],
                format_func=lambda value: _OPERATION_LABELS[value],
                horizontal=True,
                key="processing_operation",
            )
            source_keys = st.multiselect(
                "Documentos",
                options=[row.source_key for row in inventory],
                format_func=lambda value: next(
                    f"{row.title} · {_STATUS_LABELS[row.status]} · {value}"
                    for row in inventory
                    if row.source_key == value
                ),
                key="processing_source_keys",
            )
            profile_rows = _profiles(project_root)
            profile_path = None
            if operation in {"extract", "retry_failed"}:
                if not profile_rows:
                    st.error("No se encontraron perfiles extraction*.yaml válidos en config/.")
                else:
                    selected_profile = st.selectbox(
                        "Perfil OCR/extracción",
                        options=[str(path) for path, _profile in profile_rows],
                        format_func=lambda value: next(
                            f"{path.name} · {profile.profile_key} · {profile.backend} · "
                            f"{profile.device}"
                            for path, profile in profile_rows
                            if str(path) == value
                        ),
                        key="processing_profile_path",
                    )
                    profile_path = Path(selected_profile)
                st.info(
                    "La corrida producirá candidatos. Después deberá elegir manualmente "
                    "las páginas "
                    "en la pestaña Selección canónica."
                )
            force = st.checkbox(
                "Crear una nueva versión aunque exista una equivalente",
                value=False,
                key="processing_force",
                disabled=operation in {"retry_failed", "bootstrap"},
            )
            if operation == "retry_failed" and source_keys:
                engine = create_sqlite_engine(db_path)
                try:
                    with session_scope(engine) as session:
                        retry_map = {
                            key: failed_extraction_pages(session, source_key=key)
                            for key in source_keys
                        }
                finally:
                    engine.dispose()
                for key, pages in retry_map.items():
                    page_label = ", ".join(map(str, pages)) if pages else "sin páginas fallidas"
                    st.write(f"`{key}`: {page_label}")
            if st.button(
                "Ejecutar operación",
                type="primary",
                disabled=not source_keys
                or (operation in {"extract", "retry_failed"} and profile_path is None),
            ):
                _execute_batch(
                    st,
                    project_root=project_root,
                    db_path=db_path,
                    decisions=decisions,
                    project_id=project_id,
                    actor=actor,
                    operation=operation,
                    source_keys=source_keys,
                    profile_path=profile_path,
                    force=force,
                )

    with selection_tab:
        candidates = [row for row in inventory if row.extracted_pages or row.extraction_status]
        if not candidates:
            st.info("Todavía no hay corridas de extracción para seleccionar.")
        else:
            source_key = st.selectbox(
                "Documento",
                options=[row.source_key for row in candidates],
                format_func=lambda value: next(
                    f"{row.title} · {value}" for row in candidates if row.source_key == value
                ),
                key="processing_selection_source",
            )
            current_row = next(row for row in candidates if row.source_key == source_key)
            st.write(
                f"Seleccionadas: **{current_row.selected_pages}/"
                f"{current_row.page_count or '?'}** · "
                f"editables: **{current_row.editable_pages}** · "
                f"estado: **{_STATUS_LABELS[current_row.status]}**"
            )
            engine = create_sqlite_engine(db_path)
            try:
                with session_scope(engine) as session:
                    runs = extraction_candidate_runs(session, source_key=source_key)
            finally:
                engine.dispose()
            selectable_runs = [row for row in runs if row.pages]
            if not selectable_runs:
                st.warning(
                    "Las corridas registradas no contienen páginas completadas seleccionables."
                )
            else:
                run_id = st.selectbox(
                    "Corrida candidata",
                    options=[row.run_id for row in selectable_runs],
                    format_func=lambda value: next(
                        (
                            f"{row.profile_key or '-'} · {row.status} · "
                            f"calidad {row.quality_status} · "
                            f"{len(row.pages)} pág. · {row.created_at:%Y-%m-%d %H:%M}"
                        )
                        for row in selectable_runs
                        if row.run_id == value
                    ),
                    key="processing_selection_run",
                )
                selected_run = next(row for row in selectable_runs if row.run_id == run_id)
                pages = st.multiselect(
                    "Páginas que pasarán a ser canónicas",
                    options=selected_run.pages,
                    default=selected_run.pages,
                    key=f"processing_selection_pages_{run_id}",
                )
                note = st.text_input(
                    "Nota de selección",
                    placeholder="Por qué se elige esta corrida o estas páginas",
                    key="processing_selection_note",
                )
                if selected_run.quality_status == "rejected":
                    st.warning("Esta corrida está marcada como rechazada.")
                if st.button(
                    "Confirmar selección canónica",
                    type="primary",
                    disabled=not pages,
                ):
                    engine = create_sqlite_engine(db_path)
                    try:
                        with session_scope(engine) as session:
                            _run, changed = select_extraction_pages(
                                session,
                                source_key=source_key,
                                selected_by=actor or "local_user",
                                run_id=run_id,
                                pages=set(pages),
                                note=note,
                            )
                    except (ValueError, RuntimeError, OSError) as exc:
                        st.error(str(exc))
                    else:
                        st.session_state["processing_flash"] = (
                            f"Selección actualizada: {changed} página(s). "
                            "La capa editable no fue reemplazada automáticamente."
                        )
                        st.rerun()
                    finally:
                        engine.dispose()

            action_cols = st.columns(2)
            if action_cols[0].button(
                "Inicializar páginas seleccionadas",
                disabled=current_row.selected_pages == 0,
                use_container_width=True,
            ):
                _execute_batch(
                    st,
                    project_root=project_root,
                    db_path=db_path,
                    decisions=decisions,
                    project_id=project_id,
                    actor=actor,
                    operation="bootstrap",
                    source_keys=[source_key],
                    profile_path=None,
                    force=False,
                )
            if action_cols[1].button(
                "Abrir en Revisión",
                disabled=current_row.editable_pages == 0,
                use_container_width=True,
            ):
                engine = create_sqlite_engine(db_path)
                try:
                    with session_scope(engine) as session:
                        first_page = session.scalar(
                            select(func.min(EditablePage.page_number)).where(
                                EditablePage.digital_object_id == current_row.digital_object_id
                            )
                        )
                finally:
                    engine.dispose()
                if first_page is not None:
                    _open_review(st, source_key=source_key, page=int(first_page))

    with history_tab:
        engine = create_sqlite_engine(db_path)
        try:
            with session_scope(engine) as session:
                jobs = processing_job_rows(session, project_id=project_id, limit=100)
        finally:
            engine.dispose()
        if not jobs:
            st.caption("Todavía no hay trabajos ejecutados desde esta vista.")
        for job in jobs:
            label = (
                f"{_OPERATION_LABELS.get(job.operation, job.operation)} · "
                f"{_JOB_STATUS_LABELS.get(job.status, job.status)} · "
                f"{job.created_at:%Y-%m-%d %H:%M} · {job.created_by}"
            )
            with st.expander(label):
                cols = st.columns(4)
                cols[0].metric("Documentos", job.total_items)
                cols[1].metric("Completados", job.completed_items)
                cols[2].metric("Advertencias", job.warning_items)
                cols[3].metric("Fallidos", job.failed_items)
                if job.parameters:
                    st.json(job.parameters)
                engine = create_sqlite_engine(db_path)
                try:
                    with session_scope(engine) as session:
                        items = processing_job_item_rows(session, job_id=job.job_id)
                finally:
                    engine.dispose()
                st.dataframe(
                    [
                        {
                            "Documento": item.source_key,
                            "Estado": _JOB_STATUS_LABELS.get(item.status, item.status),
                            "Páginas": ", ".join(map(str, item.pages)),
                            "Mensaje": item.message,
                        }
                        for item in items
                    ],
                    use_container_width=True,
                    hide_index=True,
                )
                for item in items:
                    if item.detail:
                        with st.expander(f"Detalle · {item.source_key}"):
                            st.json(item.detail)
