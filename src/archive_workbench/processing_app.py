from __future__ import annotations

from pathlib import Path
import json
import re

from sqlalchemy import func, select

from archive_workbench.db import create_sqlite_engine, session_scope
from archive_workbench.db.models import EditablePage
from archive_workbench.candidate_review import (
    ADOPTION_ALREADY,
    ADOPTION_MANUAL,
    ADOPTION_NOT_INITIALIZED,
    adopt_candidate_page,
    assess_candidate_adoption,
    compare_candidate_page,
    render_candidate_overlay,
    resolve_candidate_keep_edits,
)
from archive_workbench.editing import bootstrap_editable_layer
from archive_workbench.editable_rebase import (
    apply_editable_rebase,
    preview_editable_rebase,
)
from archive_workbench.extraction import (
    extract_documents_preferred,
    extraction_doctor,
    load_extraction_profile,
    select_extraction_pages,
    resolve_extraction_profile,
)
from archive_workbench.contracts.regions import RegionOcrOptions
from archive_workbench.region_canvas import regional_region_canvas
from archive_workbench.region_extraction import extract_regions, load_region_template
from archive_workbench.regional_workflow import (
    REGION_ROLE_DEFAULT_MODE,
    REGION_ROLE_LABELS,
    available_region_templates,
    draft_from_region,
    region_role_label,
    regional_page_assets,
    template_from_drafts,
)
from archive_workbench.preprocessing import (
    GEOMETRY_MODE_LABELS,
    OCR_TREATMENT_LABELS,
    prepare_derivatives,
    profile_for_preprocessing,
)
from archive_workbench.ui_navigation import rerun_app, rerun_view, request_app_view, request_tab, tracked_tabs
from archive_workbench.page_quality import (
    QUALITY_ATTENTION,
    QUALITY_CLEAR,
    assess_extraction_page_quality,
)
from archive_workbench.processing import (
    create_processing_job,
    extraction_candidate_runs,
    failed_extraction_pages,
    finish_processing_job,
    processing_geometry_rows,
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
_AUTO_QUALITY_LABELS = {
    "clear": "Sin alertas detectadas",
    "attention": "Revisar",
    "critical": "Problema probable",
}
_RUN_QUALITY_LABELS = {
    "unreviewed": "Sin revisar",
    "needs_review": "Requiere revisión",
    "accepted": "Aceptada",
    "approved": "Aprobada",
    "rejected": "Rechazada",
    "stale": "Desactualizada",
}


def _rebase_text_occurrences(text: str, fragment: str) -> list[tuple[int, int]]:
    if not fragment:
        return []
    matches = [(match.start(), match.end()) for match in re.finditer(re.escape(fragment), text)]
    if matches:
        return matches
    return [
        (match.start(), match.end())
        for match in re.finditer(re.escape(fragment), text, flags=re.IGNORECASE)
    ]


def _percentage(value) -> str:
    if value is None:
        return "—"
    return f"{float(value) * 100:.1f}%"


def _render_automatic_quality(st, assessment) -> None:
    if assessment is None:
        st.caption("Control automático: todavía no evaluado.")
        return
    label = _AUTO_QUALITY_LABELS.get(assessment.status, assessment.status)
    alert_count = len(assessment.flags)
    suffix = "" if not alert_count else f" · {alert_count} alerta{'s' if alert_count != 1 else ''}"
    message = f"Control automático: **{label}**{suffix}"
    if assessment.status == QUALITY_CLEAR:
        st.success(message)
    elif assessment.status == QUALITY_ATTENTION:
        st.warning(message)
    else:
        st.error(message)

    with st.expander(
        "Ver indicadores del control automático",
        expanded=assessment.status != QUALITY_CLEAR,
    ):
        st.caption(
            "Estos indicadores señalan riesgos observables; no miden la exactitud del OCR "
            "ni reemplazan la revisión humana."
        )
        metrics = assessment.metrics
        image_rows = [
            {"Indicador": "Brillo medio", "Valor": _percentage(metrics.get("mean_brightness"))},
            {"Indicador": "Contraste relativo", "Valor": _percentage(metrics.get("contrast"))},
            {"Indicador": "Bordes", "Valor": _percentage(metrics.get("edge_variance"))},
            {"Indicador": "Ruido", "Valor": _percentage(metrics.get("noise_ratio"))},
        ]
        extraction_rows = [
            {"Indicador": "Objetos", "Valor": str(metrics.get("object_count", "—"))},
            {"Indicador": "Caracteres", "Valor": str(metrics.get("character_count", "—"))},
            {"Indicador": "Objetos mínimos", "Valor": _percentage(metrics.get("tiny_object_ratio"))},
            {"Indicador": "Bboxes solapados", "Valor": _percentage(metrics.get("overlapping_bbox_ratio"))},
        ]
        image_col, extraction_col = st.columns(2)
        with image_col:
            st.write("**Imagen usada por el OCR**")
            st.dataframe(image_rows, hide_index=True, use_container_width=True)
        with extraction_col:
            st.write("**Salida OCR**")
            st.dataframe(extraction_rows, hide_index=True, use_container_width=True)

        ordinal_candidates = list(metrics.get("legal_ordinal_candidates") or [])
        checkbox_candidates = list(metrics.get("checkbox_candidates") or [])
        if ordinal_candidates or checkbox_candidates:
            st.write("**Estructuras que requieren revisión visual**")
            st.caption(
                "Estas reglas no corrigen ni adoptan valores automáticamente. Señalan lugares "
                "donde el texto plano puede perder información jurídica o de formulario."
            )
        if ordinal_candidates:
            st.write("Ordinales legales dudosos")
            st.dataframe(
                [
                    {
                        "Texto OCR": item.get("text", "—"),
                        "Lectura posible": item.get("possible_ordinal", "—"),
                        "Motivo": item.get("reason", "—"),
                    }
                    for item in ordinal_candidates
                ],
                hide_index=True,
                use_container_width=True,
            )
        if checkbox_candidates:
            state_labels = {
                "marked": "Marcado (candidato)",
                "unmarked": "No marcado (candidato)",
                "indeterminate": "Indeterminado",
            }
            method_labels = {
                "html_control": "control conservado en el HTML de Surya",
                "explicit_text": "símbolo y rótulo en el mismo bloque",
                "spatial": "marca próxima al rótulo",
                "reading_order": "asociación por orden de lectura",
                "unlinked": "sin rótulo asociado",
            }
            st.write("Casilleros o marcas detectadas")
            st.dataframe(
                [
                    {
                        "Estado candidato": state_labels.get(item.get("state"), item.get("state", "—")),
                        "Rótulo asociado": item.get("label") or "Sin rótulo",
                        "Marca": item.get("marker", "—"),
                        "Detección": method_labels.get(item.get("method"), item.get("method", "—")),
                    }
                    for item in checkbox_candidates
                ],
                hide_index=True,
                use_container_width=True,
            )
            st.caption(
                "Los casilleros vacíos que no produzcan ningún bloque OCR no pueden inferirse "
                "con seguridad y deben revisarse directamente sobre la imagen."
            )

        if assessment.flags:
            st.write("**Alertas**")
            for item in assessment.flag_messages:
                st.write(f"• {item}")
        else:
            st.write(
                "No se activó ninguna regla automática. Esto no demuestra que el texto "
                "reconocido sea correcto."
            )
        if assessment.suggestions:
            st.write("**Sugerencias conservadoras**")
            for item in assessment.suggestions:
                st.write(f"• {item}")
        assessed_at = (
            assessment.assessed_at.isoformat(timespec="minutes")
            if assessment.assessed_at is not None
            else "—"
        )
        st.caption(
            f"Algoritmo {assessment.algorithm_version} · evaluación {assessed_at} · "
            f"responsable {assessment.assessed_by}"
        )


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
            "failed_source_keys": list(getattr(summary, "failed_source_keys", [])),
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
    ocr_treatment: str,
    geometry_mode: str,
    force: bool,
) -> None:
    profile = None
    derivative_profile = None
    parameters: dict = {"force": force}
    if operation == "prepare":
        derivative_profile = profile_for_preprocessing(
            decisions, ocr_treatment, geometry_mode
        )
        parameters.update(
            ocr_treatment=ocr_treatment,
            geometry_mode=geometry_mode,
            preprocessing_profile=derivative_profile.profile_key,
        )
    if operation in {"extract", "retry_failed"}:
        if profile_path is None:
            st.error("Debe elegir un perfil de extracción.")
            return
        profile = load_extraction_profile(profile_path)
        resolution = resolve_extraction_profile(project_root, profile)
        if not resolution.ready:
            st.error("El entorno requerido por el perfil y su fallback no está listo.")
            for check in resolution.effective_report.checks:
                if check.required and not check.ok:
                    st.write(f"**{check.name}:** {check.detail}")
            return
        parameters.update(
            profile_path=profile_path.relative_to(project_root).as_posix(),
            profile_key=profile.profile_key,
            backend=profile.backend,
            device=profile.device,
            effective_profile_key=resolution.effective.profile_key,
            effective_backend=resolution.effective.backend,
            automatic_fallback=resolution.fallback_used,
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
                            profile=derivative_profile,
                        )
                    elif operation == "extract":
                        assert profile is not None
                        summary = extract_documents_preferred(
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
                        summary = extract_documents_preferred(
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
    rerun_view(st)


def _open_review(st, *, source_key: str, page: int) -> None:
    request_app_view(st, mode="review", source_key=source_key, page=page)
    rerun_app(st)



def _render_geometry_diagnostics(
    st,
    *,
    project_root: Path,
    db_path: Path,
    source_keys: list[str],
) -> None:
    if not source_keys:
        return
    engine = create_sqlite_engine(db_path)
    try:
        with session_scope(engine) as session:
            rows = processing_geometry_rows(session, source_keys=set(source_keys))
    finally:
        engine.dispose()
    if not rows:
        return
    panel_open = st.toggle(
        "Mostrar diagnóstico geométrico vigente",
        value=False,
        key="processing_geometry_diagnostic_panel",
        help="El panel permanece abierto mientras cambiás la página diagnóstica.",
    )
    if not panel_open:
        return
    with st.container(border=True):
        st.caption(
            "Muestra qué detectó y qué aplicó la preparación por página. "
            "Una confianza insuficiente conserva la geometría original."
        )
        st.dataframe(
            [
                {
                    "Documento": row.title,
                    "Página": row.page,
                    "Orientación detectada": (
                        f"{row.orientation_detected}°"
                        if row.orientation_detected is not None
                        else "—"
                    ),
                    "Confianza orientación": (
                        f"{row.orientation_confidence:.3f}"
                        if row.orientation_confidence is not None
                        else "—"
                    ),
                    "Rotación aplicada": f"{row.rotation_applied}°",
                    "Deskew detectado": (
                        f"{row.deskew_detected_angle:.1f}°"
                        if row.deskew_detected_angle is not None
                        else "—"
                    ),
                    "Deskew aplicado": (
                        f"{row.deskew_angle:.1f}°"
                        if row.deskew_angle is not None
                        else "—"
                    ),
                    "Confianza deskew": (
                        f"{row.deskew_confidence:.3f}"
                        if row.deskew_confidence is not None
                        else "—"
                    ),
                    "Líneas detectadas": row.lines_detected,
                    "Líneas eliminadas": row.lines_removed,
                }
                for row in rows
            ],
            hide_index=True,
            use_container_width=True,
        )
        options = list(range(len(rows)))
        selected = st.selectbox(
            "Página diagnóstica",
            options=options,
            format_func=lambda index: (
                f"{rows[index].title} · página {rows[index].page}"
            ),
            key="processing_geometry_diagnostic_page",
        )
        row = rows[selected]
        preview_col, image_col, mask_col = st.columns(3)
        with preview_col:
            st.write("**Previsualización sin cambios**")
            if row.preview_relative_path:
                st.image(
                    str(project_root / row.preview_relative_path),
                    use_container_width=True,
                )
            else:
                st.caption("No hay una previsualización disponible para esta página.")
        with image_col:
            st.write("**Derivado OCR**")
            st.image(str(project_root / row.ocr_relative_path), use_container_width=True)
        with mask_col:
            st.write("**Máscara de líneas eliminadas**")
            if row.mask_relative_path:
                st.image(str(project_root / row.mask_relative_path), use_container_width=True)
            else:
                st.caption("Esta preparación no generó una máscara diagnóstica.")
        st.json(row.transformations, expanded=False)


def _render_regional_extraction_builder(
    st,
    *,
    project_root: Path,
    db_path: Path,
    decisions,
    inventory,
    actor: str,
) -> None:
    st.caption(
        "Definí zonas sobre una página visible y creá una extracción candidata. "
        "La corrida no cambia la selección canónica ni la capa editable."
    )
    prepared = [
        row
        for row in inventory
        if row.preprocessing_status in {"completed", "completed_with_warnings"}
    ]
    if not prepared:
        st.info(
            "Primero prepará al menos un documento en la pestaña Ejecutar. "
            "El OCR regional necesita una imagen derivada por página."
        )
        return

    st.subheader("1. Documento")
    source_key = st.selectbox(
        "Documento para OCR regional",
        options=[row.source_key for row in prepared],
        format_func=lambda value: next(
            f"{row.title} · {value}" for row in prepared if row.source_key == value
        ),
        key="regional_source_key",
    )

    engine = create_sqlite_engine(db_path)
    try:
        with session_scope(engine) as session:
            assets = regional_page_assets(session, source_key=source_key)
    except (ValueError, RuntimeError) as exc:
        st.error(str(exc))
        return
    finally:
        engine.dispose()

    if not assets:
        st.warning("El documento no tiene páginas preparadas para OCR regional.")
        return

    st.subheader("2. Página")
    page = st.selectbox(
        "Página visible",
        options=[item.page for item in assets],
        key=f"regional_page_{source_key}",
    )
    asset = next(item for item in assets if item.page == page)
    image_path = project_root / asset.preview_relative_path

    drafts_key = f"regional_drafts_{source_key}"
    pending_key = f"regional_pending_box_{source_key}_{page}"
    drafts = list(st.session_state.get(drafts_key, []))

    st.subheader("3. Dibujar o revisar las zonas")
    st.caption(
        "La página se muestra aquí. Azul: zona OCR. Naranja: zona manual. "
        "Rojo: zona recién dibujada todavía no agregada."
    )
    templates = available_region_templates(project_root, source_key=source_key)
    with st.expander("Cargar zonas desde una plantilla guardada", expanded=False):
        if not templates:
            st.caption("No hay plantillas guardadas para este documento.")
        else:
            selected_template = st.selectbox(
                "Plantilla",
                options=[str(path) for path in templates],
                format_func=lambda value: Path(value).name,
                key=f"regional_template_{source_key}",
            )
            if st.button(
                "Cargar esta plantilla",
                key=f"regional_load_template_{source_key}",
            ):
                template = load_region_template(selected_template)
                st.session_state[drafts_key] = [
                    draft_from_region(region) for region in template.regions
                ]
                st.session_state.pop(pending_key, None)
                request_tab(st, key="processing_tabs", label="OCR regional")
                rerun_view(st)

    pending_box = st.session_state.get(pending_key)
    visible_drafts = [item for item in drafts if int(item.get("page", page)) == page]
    drawn = regional_region_canvas(
        image_path,
        visible_drafts,
        page=page,
        pending_box=pending_box,
        key=f"regional_canvas_{source_key}_{page}_{len(visible_drafts)}",
    )
    if drawn is not None and drawn != pending_box:
        st.session_state[pending_key] = drawn
        pending_box = drawn

    st.subheader("4. Describir la zona recién dibujada")
    if pending_box is None:
        st.info(
            "Para agregar una zona nueva, pulsá Dibujar una zona sobre la imagen y "
            "arrastrá un rectángulo."
        )
    else:
        roles = list(REGION_ROLE_LABELS)
        role = st.selectbox(
            "Qué contiene esta zona",
            options=roles,
            format_func=region_role_label,
            key=f"regional_role_{source_key}_{page}",
        )
        default_mode = REGION_ROLE_DEFAULT_MODE[role]
        mode = st.selectbox(
            "Cómo tratarla",
            options=["ocr", "manual"],
            index=0 if default_mode == "ocr" else 1,
            format_func=lambda value: (
                "Intentar OCR" if value == "ocr" else "Conservar para transcripción manual"
            ),
            key=f"regional_mode_{source_key}_{page}_{role}",
        )
        label = st.text_input(
            "Nombre visible de la zona",
            value=region_role_label(role),
            key=f"regional_label_{source_key}_{page}_{role}",
        )
        note = st.text_input(
            "Nota opcional",
            key=f"regional_note_{source_key}_{page}_{role}",
        )
        ocr_payload = None
        if mode == "ocr":
            with st.expander("Opciones avanzadas de OCR para esta zona", expanded=False):
                variant = st.selectbox(
                    "Tratamiento de imagen",
                    options=["original", "grayscale_autocontrast", "otsu"],
                    key=f"regional_variant_{source_key}_{page}_{role}",
                )
                psm = st.selectbox(
                    "Modo Tesseract (PSM)",
                    options=[3, 4, 6, 7, 11, 13],
                    index=2,
                    key=f"regional_psm_{source_key}_{page}_{role}",
                )
                granularity = st.selectbox(
                    "Unidad de salida",
                    options=["paragraph", "line"],
                    format_func=lambda value: "Párrafo" if value == "paragraph" else "Línea",
                    key=f"regional_granularity_{source_key}_{page}_{role}",
                )
                languages_text = st.text_input(
                    "Idiomas Tesseract",
                    value="spa",
                    key=f"regional_languages_{source_key}_{page}_{role}",
                )
            ocr_payload = RegionOcrOptions(
                image_variant=variant,
                psm=psm,
                languages=[item.strip() for item in languages_text.split(",") if item.strip()],
                object_granularity=granularity,
                minimum_characters_warning=1,
            ).model_dump(mode="json")
        if st.button(
            "Agregar esta zona",
            type="primary",
            disabled=not label.strip(),
            key=f"regional_add_zone_{source_key}_{page}",
        ):
            index = len(drafts) + 1
            used_orders = {
                int(item.get("reading_order", 0))
                for item in drafts
                if int(item.get("page", page)) == page
            }
            reading_order = 10
            while reading_order in used_orders:
                reading_order += 10
            drafts.append(
                {
                    "region_key": f"visual_{page}_{index:03d}",
                    "label": label.strip(),
                    "page": page,
                    "reading_order": reading_order,
                    "bbox": pending_box,
                    "mode": mode,
                    "semantic_role": role,
                    "ocr": ocr_payload,
                    "initial_text": "",
                    "note": note.strip() or None,
                }
            )
            st.session_state[drafts_key] = drafts
            st.session_state.pop(pending_key, None)
            request_tab(st, key="processing_tabs", label="OCR regional")
            rerun_view(st)

    drafts = list(st.session_state.get(drafts_key, drafts))
    st.subheader("5. Zonas que formarán la candidata")
    if not drafts:
        st.caption("Todavía no hay zonas agregadas.")
    else:
        st.dataframe(
            [
                {
                    "Orden": item.get("reading_order"),
                    "Página": item.get("page"),
                    "Zona": item.get("label"),
                    "Contenido": region_role_label(str(item.get("semantic_role") or "")),
                    "Tratamiento": "OCR" if item.get("mode") == "ocr" else "Manual",
                }
                for item in sorted(drafts, key=lambda row: (row.get("page", 0), row.get("reading_order", 0)))
            ],
            hide_index=True,
            use_container_width=True,
        )
        remove_options = list(range(len(drafts)))
        remove_index = st.selectbox(
            "Zona a quitar",
            options=remove_options,
            format_func=lambda index: str(drafts[index].get("label") or f"Zona {index + 1}"),
            key=f"regional_remove_select_{source_key}",
        )
        if st.button("Quitar la zona seleccionada", key=f"regional_remove_{source_key}"):
            drafts.pop(remove_index)
            st.session_state[drafts_key] = drafts
            request_tab(st, key="processing_tabs", label="OCR regional")
            rerun_view(st)

    st.subheader("6. Crear la extracción candidata")
    template_key = st.text_input(
        "Identificador de la candidata",
        value=f"regional_{source_key}",
        key=f"regional_template_key_{source_key}",
    )
    st.caption(
        "La corrida se registra como candidata. No se seleccionará ninguna página "
        "ni se inicializará la capa editable."
    )
    if st.button(
        "Crear extracción candidata",
        type="primary",
        disabled=not drafts or not template_key.strip(),
        key=f"regional_execute_{source_key}",
    ):
        try:
            template = template_from_drafts(
                source_key=source_key,
                drafts=drafts,
                template_key=template_key.strip(),
            )
            engine = create_sqlite_engine(db_path)
            try:
                with session_scope(engine) as session:
                    summary = extract_regions(
                        session,
                        project_root=project_root,
                        decisions=decisions,
                        template=template,
                        created_by=actor or "local_user",
                        selection_policy="never",
                    )
            finally:
                engine.dispose()
        except (ValueError, RuntimeError, OSError) as exc:
            st.error(str(exc))
        else:
            st.success(
                "Candidata creada: "
                f"{summary.runs_created} corrida nueva, "
                f"{summary.pages_processed} página(s), "
                f"{summary.objects_created} objeto(s). "
                "La selección canónica no cambió."
            )
            for warning in summary.warnings:
                st.warning(warning)


def render_processing_view(
    st,
    *,
    project_root: Path,
    db_path: Path,
    decisions,
    project_id: str,
    actor: str,
) -> None:
    st.header("Procesar documentos")
    st.caption(
        "Prepará los archivos, generá versiones de texto y elegí manualmente cuál usar en "
        "cada página. Ninguna extracción reemplaza por sí sola una decisión humana."
    )
    flash = st.session_state.pop("processing_flash", None)
    if flash:
        st.success(flash)

    inventory = _load_inventory(
        db_path=db_path, project_root=project_root, project_id=project_id
    )
    counts = {key: sum(row.status == key for row in inventory) for key in _STATUS_LABELS}
    with st.expander("Resumen de avance", expanded=False):
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

    processing_tabs = ["Inventario", "Ejecutar", "OCR regional", "Selección canónica", "Historial"]
    inventory_tab, execute_tab, regional_tab, selection_tab, history_tab = tracked_tabs(
        st,
        processing_tabs,
        key="processing_tabs",
    )

    with inventory_tab:
        st.caption("Consultá qué necesita cada documento antes de ejecutar una tarea.")
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
                    "Preparación OCR": OCR_TREATMENT_LABELS.get(
                        row.preprocessing_ocr_treatment or "",
                        row.preprocessing_ocr_treatment or "—",
                    ),
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
        st.caption(
            "Elegí qué hacer y sobre qué documentos. Las opciones técnicas aparecen "
            "solamente cuando corresponden."
        )
        if not inventory:
            st.info("No hay fuentes procesables registradas en el catálogo.")
        else:
            operation = st.radio(
                "Qué querés hacer",
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
            selected_extraction_profile = None
            ocr_treatment = "original"
            geometry_mode = "none"
            if operation == "prepare":
                ocr_treatment = st.selectbox(
                    "Tratamiento del derivado para OCR",
                    options=list(OCR_TREATMENT_LABELS),
                    format_func=lambda value: OCR_TREATMENT_LABELS[value],
                    key="processing_ocr_treatment",
                    help=(
                        "Solo modifica una copia derivada para OCR. El original y la "
                        "previsualización permanecen intactos."
                    ),
                )
                geometry_mode = st.selectbox(
                    "Corrección geométrica",
                    options=list(GEOMETRY_MODE_LABELS),
                    format_func=lambda value: GEOMETRY_MODE_LABELS[value],
                    key="processing_geometry_mode",
                    help=(
                        "Analiza orientación, inclinación y líneas largas sobre el "
                        "derivado OCR. Solo aplica cambios cuando la confianza supera "
                        "los umbrales conservadores."
                    ),
                )
                st.caption(
                    "La preparación crea una versión reproducible. El original, la "
                    "previsualización y las selecciones canónicas permanecen intactos."
                )
                _render_geometry_diagnostics(
                    st,
                    project_root=project_root,
                    db_path=db_path,
                    source_keys=source_keys,
                )
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
                    selected_extraction_profile = next(
                        profile
                        for path, profile in profile_rows
                        if str(path) == selected_profile
                    )
                    if selected_extraction_profile.backend == "surya_cli":
                        backend_label = {
                            "auto": "automático (vLLM con NVIDIA o llama.cpp en CPU)",
                            "cuda": "vLLM con NVIDIA/Docker",
                            "cpu": "llama.cpp en CPU",
                        }[selected_extraction_profile.device]
                        st.caption(
                            "Surya realizará OCR, clasificación de bloques y orden de lectura. "
                            f"Backend solicitado: {backend_label}. La corrida seguirá siendo una "
                            "candidata y no reemplazará la selección canónica."
                        )
                        if selected_extraction_profile.surya_torch_device == "cpu":
                            st.caption(
                                "Configuración híbrida: el VLM usa vLLM/NVIDIA y los modelos "
                                "auxiliares de Surya usan CPU."
                            )
                        if selected_extraction_profile.surya_keep_server:
                            st.info(
                                "El servidor vLLM quedará activo para reutilizarse en las próximas "
                                "corridas. Libere la VRAM al terminar con "
                                "`archive-workbench surya-server-stop`."
                            )
                        if selected_extraction_profile.fallback_profile:
                            st.caption(
                                "Fallback automático si Surya no está disponible o falla: "
                                f"`{selected_extraction_profile.fallback_profile}`."
                            )
                    selected_inventory = [
                        row for row in inventory if row.source_key in source_keys
                    ]
                    if selected_inventory:
                        st.write("**Imagen que recibirá el OCR**")
                        image_rows = []
                        for row in selected_inventory:
                            treatment = row.preprocessing_ocr_treatment or "original"
                            treatment_label = OCR_TREATMENT_LABELS.get(treatment, treatment)
                            geometry = row.preprocessing_geometry_mode or "none"
                            geometry_label = GEOMETRY_MODE_LABELS.get(geometry, geometry)
                            profile_variant = selected_extraction_profile.image_variant
                            image_rows.append(
                                {
                                    "Documento": row.title,
                                    "Tratamiento del derivado vigente": treatment_label,
                                    "Corrección geométrica vigente": geometry_label,
                                    "Transformación adicional del perfil": (
                                        "Ninguna (`original`)"
                                        if profile_variant == "original"
                                        else profile_variant
                                    ),
                                }
                            )
                        st.dataframe(image_rows, hide_index=True, use_container_width=True)
                        if selected_extraction_profile.image_variant == "original":
                            st.caption(
                                "`original` no significa que se use el archivo original sin "
                                "preparación. Significa que el perfil no agrega otra transformación: "
                                "el OCR recibe el derivado vigente tal como fue preparado."
                            )
                    else:
                        st.caption(
                            "Elegí uno o más documentos para ver el tratamiento del derivado "
                            "vigente que recibirá el OCR."
                        )
                    combined = [
                        row.source_key
                        for row in inventory
                        if row.source_key in source_keys
                        and row.preprocessing_ocr_treatment not in {None, "original"}
                    ]
                    if combined and selected_extraction_profile.image_variant != "original":
                        st.warning(
                            "Los documentos seleccionados ya tienen un tratamiento en su "
                            "derivado OCR y el perfil aplicará otro durante la extracción: "
                            + ", ".join(combined)
                            + ". Revise que esa combinación sea intencional."
                        )
                st.info(
                    "La corrida producirá candidatos. Después deberá elegir manualmente "
                    "las páginas en la pestaña Selección canónica."
                )
            force = False
            with st.expander("Opciones avanzadas", expanded=False):
                force = st.checkbox(
                    "Crear una nueva versión aunque exista una equivalente",
                    value=False,
                    key="processing_force",
                    disabled=operation in {"retry_failed", "bootstrap"},
                )
                st.caption(
                    "Usá esta opción solamente cuando necesites repetir deliberadamente una "
                    "preparación o extracción ya registrada."
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
                "Ejecutar tarea",
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
                    ocr_treatment=ocr_treatment,
                    geometry_mode=geometry_mode,
                    force=force,
                )

    with regional_tab:
        _render_regional_extraction_builder(
            st,
            project_root=project_root,
            db_path=db_path,
            decisions=decisions,
            inventory=inventory,
            actor=actor,
        )

    with selection_tab:
        st.caption(
            "Compará versiones por página y elegí cuál debe quedar como referencia de trabajo."
        )
        candidates = [row for row in inventory if row.extracted_pages or row.extraction_status]
        if not candidates:
            st.info("Todavía no hay corridas de extracción para comparar.")
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
            engine = create_sqlite_engine(db_path)
            try:
                with session_scope(engine) as session:
                    runs = extraction_candidate_runs(session, source_key=source_key)
            finally:
                engine.dispose()
            selectable_runs = [row for row in runs if row.pages]
            available_pages = sorted({page for row in selectable_runs for page in row.pages})
            if not available_pages:
                st.warning(
                    "Las corridas registradas no contienen páginas completadas para comparar."
                )
            else:
                control_cols = st.columns([1, 2])
                page = control_cols[0].selectbox(
                    "Página",
                    options=available_pages,
                    key="processing_candidate_page",
                )
                page_runs = [row for row in selectable_runs if page in row.pages]
                run_id = control_cols[1].selectbox(
                    "Versión candidata",
                    options=[row.run_id for row in page_runs],
                    format_func=lambda value: next(
                        (
                            f"{row.profile_key or '-'} · {row.status} · "
                            f"calidad {row.quality_status} · {row.created_at:%Y-%m-%d %H:%M}"
                        )
                        for row in page_runs
                        if row.run_id == value
                    ),
                    key=f"processing_candidate_run_{source_key}_{page}",
                )
                engine = create_sqlite_engine(db_path)
                try:
                    with session_scope(engine) as session:
                        comparison = compare_candidate_page(
                            session,
                            project_root=project_root,
                            source_key=source_key,
                            page=page,
                            candidate_run_id=run_id,
                        )
                        assessment = assess_candidate_adoption(
                            session,
                            source_key=source_key,
                            page=page,
                            candidate_run_id=run_id,
                        )
                except (ValueError, RuntimeError, OSError) as exc:
                    st.error(str(exc))
                    comparison = None
                    assessment = None
                finally:
                    engine.dispose()

                if comparison is not None and assessment is not None:
                    quality_targets = [comparison.candidate.page_id]
                    if comparison.current is not None:
                        quality_targets.append(comparison.current.page_id)
                    if st.button(
                        "Evaluar calidad de las versiones visibles",
                        key=f"processing_quality_{source_key}_{page}_{run_id}",
                        help=(
                            "Calcula indicadores de imagen, fragmentación y solapamiento. "
                            "No selecciona, adopta ni aprueba ninguna versión."
                        ),
                    ):
                        engine = create_sqlite_engine(db_path)
                        try:
                            with session_scope(engine) as session:
                                for target_page_id in dict.fromkeys(quality_targets):
                                    assess_extraction_page_quality(
                                        session,
                                        project_root=project_root,
                                        extraction_page_id=target_page_id,
                                        assessed_by=actor or "local_user",
                                    )
                        except (ValueError, OSError) as exc:
                            st.error(str(exc))
                        else:
                            request_tab(st, key="processing_tabs", label="Selección canónica")
                            st.session_state["processing_flash"] = (
                                f"Página {page}: control automático actualizado. "
                                "La selección y la edición no cambiaron."
                            )
                            rerun_view(st)
                        finally:
                            engine.dispose()

                    st.caption(
                        "Primero compare la página. Cambiar la selección no borra correcciones; "
                        "actualizar la base editable solo se habilita cuando es seguro."
                    )
                    current = comparison.current
                    candidate = comparison.candidate
                    metric_cols = st.columns(4)
                    metric_cols[0].metric(
                        "Objetos",
                        candidate.object_count,
                        comparison.object_delta if comparison.object_delta is not None else None,
                    )
                    metric_cols[1].metric(
                        "Caracteres",
                        candidate.character_count,
                        comparison.character_delta
                        if comparison.character_delta is not None
                        else None,
                    )
                    metric_cols[2].metric(
                        "Similitud textual",
                        (
                            f"{comparison.text_similarity * 100:.1f}%"
                            if comparison.text_similarity is not None
                            else "Sin selección previa"
                        ),
                    )
                    metric_cols[3].metric(
                        "Estado de la corrida",
                        _RUN_QUALITY_LABELS.get(
                            candidate.quality_status, candidate.quality_status
                        ),
                    )
                    st.caption(
                        "El estado de la corrida lo asigna el equipo. El control automático "
                        "es independiente: señala riesgos, pero no aprueba ni mide la exactitud "
                        "del OCR."
                    )

                    left, right = st.columns(2)
                    with left:
                        st.subheader("Selección vigente")
                        if current is None:
                            st.info("Esta página todavía no tiene una extracción seleccionada.")
                        else:
                            badges = []
                            if current.is_editable_source:
                                badges.append("base de edición")
                            badges.append(current.profile_key or current.engine)
                            st.caption(" · ".join(badges))
                            _render_automatic_quality(st, current.automatic_quality)
                            if current.preview_path is not None:
                                st.image(
                                    render_candidate_overlay(
                                        current.preview_path, current.objects, page=page
                                    ),
                                    use_container_width=True,
                                )
                            st.text_area(
                                "Texto vigente",
                                value=current.text,
                                height=260,
                                disabled=True,
                                key=f"processing_current_text_{source_key}_{page}_{current.run_id}",
                            )
                    with right:
                        st.subheader("Candidata")
                        candidate_badges = [candidate.profile_key or candidate.engine]
                        if candidate.is_selected:
                            candidate_badges.append("ya seleccionada")
                        if candidate.is_editable_source:
                            candidate_badges.append("base de edición")
                        st.caption(" · ".join(candidate_badges))
                        _render_automatic_quality(st, candidate.automatic_quality)
                        if candidate.preview_path is not None:
                            st.image(
                                render_candidate_overlay(
                                    candidate.preview_path, candidate.objects, page=page
                                ),
                                use_container_width=True,
                            )
                        st.text_area(
                            "Texto candidato",
                            value=candidate.text,
                            height=260,
                            disabled=True,
                            key=f"processing_candidate_text_{source_key}_{page}_{candidate.run_id}",
                        )

                    if comparison.unified_text_diff:
                        with st.expander("Ver diferencias línea por línea"):
                            st.code(comparison.unified_text_diff, language="diff")

                    if assessment.code == ADOPTION_MANUAL:
                        st.warning(f"**{assessment.title}.** {assessment.explanation}")
                        st.write("Se detectó: " + "; ".join(assessment.blocking_reasons) + ".")
                    elif assessment.code == ADOPTION_ALREADY:
                        st.success(f"**{assessment.title}.** {assessment.explanation}")
                    else:
                        st.info(f"**{assessment.title}.** {assessment.explanation}")

                    note = st.text_input(
                        "Nota",
                        placeholder="Motivo de la elección (opcional)",
                        key=f"processing_candidate_note_{source_key}_{page}_{run_id}",
                    )
                    action_cols = st.columns(2)
                    select_disabled = candidate.is_selected
                    if action_cols[0].button(
                        "Cambiar solo la selección",
                        disabled=select_disabled,
                        use_container_width=True,
                        help=(
                            "La edición existente se conserva. Si proviene de otra extracción, "
                            "quedará señalada como desactualizada."
                        ),
                    ):
                        engine = create_sqlite_engine(db_path)
                        try:
                            with session_scope(engine) as session:
                                _run, changed = select_extraction_pages(
                                    session,
                                    source_key=source_key,
                                    selected_by=actor or "local_user",
                                    run_id=run_id,
                                    pages={page},
                                    note=note,
                                )
                        except (ValueError, RuntimeError, OSError) as exc:
                            st.error(str(exc))
                        else:
                            st.session_state["processing_flash"] = (
                                f"Página {page}: selección actualizada ({changed} cambio). "
                                "La edición existente se conservó."
                            )
                            request_tab(st, key="processing_tabs", label="Selección canónica")
                            rerun_view(st)
                        finally:
                            engine.dispose()

                    if assessment.code == ADOPTION_NOT_INITIALIZED:
                        adopt_label = "Seleccionar e inicializar esta página"
                    else:
                        adopt_label = "Cambiar selección y base editable"
                    if action_cols[1].button(
                        adopt_label,
                        type="primary",
                        disabled=not assessment.can_adopt,
                        use_container_width=True,
                        help=(
                            assessment.explanation
                            if assessment.can_adopt
                            else "La aplicación no reemplazará automáticamente trabajo humano."
                        ),
                    ):
                        engine = create_sqlite_engine(db_path)
                        try:
                            with session_scope(engine) as session:
                                result = adopt_candidate_page(
                                    session,
                                    decisions=decisions,
                                    source_key=source_key,
                                    page=page,
                                    candidate_run_id=run_id,
                                    adopted_by=actor or "local_user",
                                    note=note,
                                )
                        except (ValueError, RuntimeError, OSError) as exc:
                            st.error(str(exc))
                        else:
                            st.session_state["processing_flash"] = (
                                f"Página {page}: candidata adoptada. "
                                f"Objetos activos: {result.objects_activated}; "
                                f"anteriores conservados: {result.objects_retired}."
                            )
                            request_tab(st, key="processing_tabs", label="Selección canónica")
                            rerun_view(st)
                        finally:
                            engine.dispose()

                    if assessment.code == ADOPTION_MANUAL:
                        with st.expander("Resolver conservando la edición actual"):
                            st.write(
                                "Esta opción no importa ni mezcla los bloques de la candidata. "
                                "Mantiene exactamente los textos, el orden, las anotaciones y "
                                "los estados actuales; solo registra que esa edición continuará "
                                "sobre la candidata elegida."
                            )
                            st.text_area(
                                "Edición que se conservará",
                                value=comparison.editable_text or "",
                                height=220,
                                disabled=True,
                                key=(
                                    f"processing_editable_text_{source_key}_{page}_"
                                    f"{comparison.editable_status}"
                                ),
                            )
                            with st.form(
                                f"processing_keep_edits_commit_{source_key}_{page}_{run_id}",
                                enter_to_submit=False,
                            ):
                                keep_confirmed = st.checkbox(
                                    "Confirmo que deseo conservar íntegramente la edición actual",
                                    key=f"processing_keep_edits_confirm_{source_key}_{page}_{run_id}",
                                )
                                keep_submitted = st.form_submit_button(
                                    "Conservar edición y vincular esta candidata",
                                    type="primary",
                                    disabled=not keep_confirmed,
                                    use_container_width=True,
                                )
                            if keep_submitted:
                                engine = create_sqlite_engine(db_path)
                                try:
                                    with session_scope(engine) as session:
                                        result = resolve_candidate_keep_edits(
                                            session,
                                            source_key=source_key,
                                            page=page,
                                            candidate_run_id=run_id,
                                            resolved_by=actor or "local_user",
                                            note=note,
                                        )
                                except (ValueError, RuntimeError, OSError) as exc:
                                    st.error(str(exc))
                                else:
                                    st.session_state["processing_flash"] = (
                                        f"Página {page}: se conservaron "
                                        f"{result.retained_objects} objetos editables. "
                                        "La decisión quedó registrada en el historial."
                                    )
                                    request_tab(st, key="processing_tabs", label="Selección canónica")
                                    rerun_view(st)
                                finally:
                                    engine.dispose()

                        with st.expander("Rebasar la edición sobre esta candidata", expanded=True):
                            st.write(
                                "Compara la extracción anterior, la edición humana y la candidata. "
                                "Solo habilita la aplicación cuando puede trasladar texto, menciones, "
                                "comentarios, etiquetas, partes documentales y atributos especializados "
                                "sin ambigüedad."
                            )
                            engine = create_sqlite_engine(db_path)
                            try:
                                with session_scope(engine) as session:
                                    rebase_preview = preview_editable_rebase(
                                        session,
                                        source_key=source_key,
                                        page=page,
                                        candidate_run_id=run_id,
                                    )
                            except (ValueError, RuntimeError, OSError) as exc:
                                st.error(str(exc))
                                rebase_preview = None
                            finally:
                                engine.dispose()

                            if rebase_preview is not None:
                                text_resolutions: dict[str, dict] = {}
                                if rebase_preview.text_conflicts:
                                    st.warning(
                                        "Hay correcciones humanas que se superponen con cambios "
                                        "distintos de la candidata. Cada tramo debe resolverse "
                                        "explícitamente antes de aplicar el rebase."
                                    )
                                    for conflict in rebase_preview.text_conflicts:
                                        key_base = (
                                            f"processing_rebase_text_{source_key}_{page}_"
                                            f"{run_id}_{conflict.conflict_id}"
                                        )
                                        with st.container(border=True):
                                            st.write(f"**Conflicto textual** · `{conflict.conflict_id}`")
                                            st.caption(conflict.reason)
                                            columns = st.columns(3)
                                            columns[0].write("**Base anterior**")
                                            columns[0].code(conflict.base_text or "[vacío]")
                                            columns[1].write("**Corrección humana**")
                                            columns[1].code(conflict.human_text or "[vacío]")
                                            columns[2].write("**Nueva candidata**")
                                            columns[2].code(conflict.candidate_text or "[vacío]")
                                            st.caption(f"Contexto: {conflict.context}")
                                            choice = st.radio(
                                                "Texto que debe quedar",
                                                options=[
                                                    "pending",
                                                    "candidate",
                                                    "human",
                                                    "manual",
                                                ],
                                                format_func=lambda value: {
                                                    "pending": "Pendiente de resolución",
                                                    "candidate": "Conservar la lectura de la candidata",
                                                    "human": "Reaplicar la corrección humana",
                                                    "manual": "Escribir manualmente el resultado",
                                                }[value],
                                                key=f"{key_base}_choice",
                                            )
                                            common = {
                                                "expected_candidate_text": conflict.candidate_text,
                                                "expected_human_text": conflict.human_text,
                                            }
                                            manual_state_key = f"{key_base}_manual_resolution"
                                            if choice == "candidate":
                                                st.session_state.pop(manual_state_key, None)
                                                text_resolutions[conflict.conflict_id] = {
                                                    **common,
                                                    "action": "keep_candidate",
                                                    "method": "manual_keep_candidate",
                                                }
                                            elif choice == "human":
                                                st.session_state.pop(manual_state_key, None)
                                                text_resolutions[conflict.conflict_id] = {
                                                    **common,
                                                    "action": "apply_human",
                                                    "method": "manual_apply_human",
                                                }
                                            elif choice == "manual":
                                                st.caption(
                                                    "El texto manual reemplaza solamente el tramo "
                                                    "mostrado en la columna Nueva candidata."
                                                )
                                                with st.form(
                                                    f"{key_base}_manual_form",
                                                    enter_to_submit=False,
                                                ):
                                                    manual_text = st.text_area(
                                                        "Texto resultante exacto para este tramo",
                                                        value=conflict.human_text,
                                                        key=f"{key_base}_manual_text",
                                                    )
                                                    manual_confirmed = st.checkbox(
                                                        "Confirmo este texto resultante",
                                                        key=f"{key_base}_manual_confirm",
                                                    )
                                                    manual_submitted = st.form_submit_button(
                                                        "Confirmar texto manual"
                                                    )
                                                if manual_submitted:
                                                    st.session_state.pop(manual_state_key, None)
                                                    if not manual_confirmed:
                                                        st.error(
                                                            "Marcá la confirmación antes de guardar "
                                                            "el texto manual."
                                                        )
                                                    else:
                                                        st.session_state[manual_state_key] = {
                                                            **common,
                                                            "action": "manual_text",
                                                            "manual_text": manual_text,
                                                            "method": "manual_custom_text",
                                                        }
                                                committed_resolution = st.session_state.get(
                                                    manual_state_key
                                                )
                                                if committed_resolution:
                                                    text_resolutions[conflict.conflict_id] = dict(
                                                        committed_resolution
                                                    )
                                                    st.success(
                                                        "Texto manual confirmado para la vista previa."
                                                    )
                                                else:
                                                    st.info(
                                                        "El texto manual no se incorporará hasta pulsar "
                                                        "Confirmar texto manual."
                                                    )
                                            else:
                                                st.session_state.pop(manual_state_key, None)

                                    if text_resolutions:
                                        engine = create_sqlite_engine(db_path)
                                        try:
                                            with session_scope(engine) as session:
                                                rebase_preview = preview_editable_rebase(
                                                    session,
                                                    source_key=source_key,
                                                    page=page,
                                                    candidate_run_id=run_id,
                                                    text_resolutions=text_resolutions,
                                                )
                                        except (ValueError, RuntimeError, OSError) as exc:
                                            st.error(str(exc))
                                            rebase_preview = None
                                        finally:
                                            engine.dispose()

                                projection_resolutions: dict[str, dict] = {}
                                if (
                                    rebase_preview is not None
                                    and not rebase_preview.text_conflicts
                                    and rebase_preview.projection_conflicts
                                ):
                                    st.warning(
                                        "Hay objetos con anotaciones o metadatos cuya correspondencia "
                                        "con los bloques candidatos no es suficientemente segura. "
                                        "Elegí explícitamente el bloque de destino."
                                    )
                                    for conflict in rebase_preview.projection_conflicts:
                                        key_base = (
                                            f"processing_rebase_projection_{source_key}_{page}_"
                                            f"{run_id}_{conflict.conflict_id}"
                                        )
                                        with st.container(border=True):
                                            st.write(
                                                f"**Proyección del objeto editable "
                                                f"{conflict.source_order_index + 1}**"
                                            )
                                            st.caption(conflict.reason)
                                            st.code(conflict.source_text[:700] or "[objeto vacío]")
                                            options = ["pending", *range(len(conflict.candidates))]
                                            selected_projection = st.selectbox(
                                                "Bloque candidato que recibirá sus anotaciones y metadatos",
                                                options=options,
                                                format_func=lambda value, candidates=conflict.candidates: (
                                                    "Pendiente de resolución"
                                                    if value == "pending"
                                                    else (
                                                        f"Bloque {candidates[value].order_index + 1} · "
                                                        f"similitud textual "
                                                        f"{candidates[value].text_score:.0%} · "
                                                        f"solapamiento posicional "
                                                        f"{candidates[value].overlap_score:.0%} · "
                                                        f"{candidates[value].text[:140]}"
                                                    )
                                                ),
                                                key=f"{key_base}_choice",
                                            )
                                            if selected_projection != "pending":
                                                candidate_option = conflict.candidates[
                                                    selected_projection
                                                ]
                                                projection_resolutions[
                                                    conflict.conflict_id
                                                ] = {
                                                    "action": "map",
                                                    "target_index": candidate_option.target_index,
                                                    "expected_candidate_ids": [
                                                        item.source_object_id
                                                        for item in rebase_preview.candidate_objects
                                                    ],
                                                    "method": "manual_object_projection",
                                                }
                                                st.success(
                                                    "Este destino se incorporará a la vista previa recalculada."
                                                )

                                    if projection_resolutions:
                                        engine = create_sqlite_engine(db_path)
                                        try:
                                            with session_scope(engine) as session:
                                                rebase_preview = preview_editable_rebase(
                                                    session,
                                                    source_key=source_key,
                                                    page=page,
                                                    candidate_run_id=run_id,
                                                    text_resolutions=text_resolutions,
                                                    projection_resolutions=(
                                                        projection_resolutions
                                                    ),
                                                )
                                        except (ValueError, RuntimeError, OSError) as exc:
                                            st.error(str(exc))
                                            rebase_preview = None
                                        finally:
                                            engine.dispose()

                                mention_resolutions: dict[str, dict] = {}
                                if (
                                    rebase_preview is not None
                                    and not rebase_preview.text_conflicts
                                    and not rebase_preview.projection_conflicts
                                    and rebase_preview.mention_conflicts
                                ):
                                    st.warning(
                                        "Hay conflictos de menciones que pueden resolverse aquí. "
                                        "La autoridad canónica y sus relaciones no se modifican: "
                                        "solo se decide el nuevo anclaje textual o el rechazo de un duplicado."
                                    )
                                    for conflict in rebase_preview.mention_conflicts:
                                        key_base = (
                                            f"processing_rebase_mention_{source_key}_{page}_"
                                            f"{run_id}_{conflict.mention_id}"
                                        )
                                        with st.container(border=True):
                                            authority_label = (
                                                conflict.authority_name
                                                or conflict.authority_id
                                                or "sin autoridad canónica"
                                            )
                                            st.write(
                                                f"**{conflict.mention_text}** · {authority_label} · "
                                                f"estado `{conflict.status}`"
                                            )
                                            st.caption(conflict.reason)
                                            st.caption(
                                                f"Contexto anterior: {conflict.source_context}"
                                            )

                                            option_values = ["pending"]
                                            option_labels = {
                                                "pending": "Pendiente de resolución",
                                                "manual": "Elegir otro fragmento manualmente",
                                                "reject": "Rechazar esta mención o duplicado",
                                            }
                                            for index, candidate_option in enumerate(
                                                conflict.candidates
                                            ):
                                                option = f"candidate:{index}"
                                                option_values.append(option)
                                                block_order = rebase_preview.candidate_objects[
                                                    candidate_option.target_index
                                                ].order_index + 1
                                                option_labels[option] = (
                                                    f"Bloque {block_order} · "
                                                    f"{candidate_option.method} · "
                                                    f"«{candidate_option.matched_text}» · "
                                                    f"{candidate_option.context}"
                                                )
                                            option_values.extend(["manual", "reject"])
                                            choice = st.selectbox(
                                                "Resolución",
                                                options=option_values,
                                                format_func=lambda value, labels=option_labels: labels[
                                                    value
                                                ],
                                                key=f"{key_base}_choice",
                                            )

                                            if choice.startswith("candidate:"):
                                                st.session_state.pop(
                                                    f"{key_base}_manual_resolution", None
                                                )
                                                candidate_index = int(choice.split(":", 1)[1])
                                                candidate_option = conflict.candidates[
                                                    candidate_index
                                                ]
                                                mention_resolutions[conflict.mention_id] = {
                                                    "action": "relocate",
                                                    "target_index": candidate_option.target_index,
                                                    "start_offset": candidate_option.start_offset,
                                                    "end_offset": candidate_option.end_offset,
                                                    "matched_text": candidate_option.matched_text,
                                                    "method": "manual_suggestion",
                                                }
                                                st.success(
                                                    "Este destino se incorporará a la nueva vista previa."
                                                )
                                            elif choice == "manual":
                                                manual_state_key = f"{key_base}_manual_resolution"
                                                block_options = list(
                                                    range(len(rebase_preview.candidate_objects))
                                                )
                                                default_block = (
                                                    conflict.predicted_target_index
                                                    if conflict.predicted_target_index
                                                    in block_options
                                                    else 0
                                                )
                                                with st.form(
                                                    f"{key_base}_manual_form",
                                                    enter_to_submit=False,
                                                ):
                                                    target_index = st.selectbox(
                                                        "Bloque candidato",
                                                        options=block_options,
                                                        index=block_options.index(default_block),
                                                        format_func=lambda value: (
                                                            f"Bloque "
                                                            f"{rebase_preview.candidate_objects[value].order_index + 1} · "
                                                            f"{rebase_preview.candidate_objects[value].rebased_text[:120]}"
                                                        ),
                                                        key=f"{key_base}_manual_block",
                                                    )
                                                    manual_text = st.text_input(
                                                        "Fragmento exacto dentro del bloque",
                                                        value=conflict.mention_text,
                                                        key=f"{key_base}_manual_text",
                                                    )
                                                    manual_occurrence = st.number_input(
                                                        "Aparición",
                                                        min_value=1,
                                                        value=1,
                                                        step=1,
                                                        help=(
                                                            "Usá 2, 3, etc. cuando el mismo fragmento "
                                                            "aparece varias veces en el bloque."
                                                        ),
                                                        key=f"{key_base}_manual_occurrence",
                                                    )
                                                    manual_submitted = st.form_submit_button(
                                                        "Confirmar fragmento manual"
                                                    )
                                                if manual_submitted:
                                                    st.session_state.pop(manual_state_key, None)
                                                    target_text = rebase_preview.candidate_objects[
                                                        target_index
                                                    ].rebased_text
                                                    occurrences = _rebase_text_occurrences(
                                                        target_text, manual_text
                                                    )
                                                    occurrence_index = int(manual_occurrence) - 1
                                                    if not occurrences:
                                                        st.error(
                                                            "Ese fragmento no aparece en el bloque elegido. "
                                                            "Copialo exactamente desde el texto resultante."
                                                        )
                                                    elif occurrence_index >= len(occurrences):
                                                        st.error(
                                                            f"El fragmento aparece {len(occurrences)} vez/veces; "
                                                            "elegí una aparición disponible."
                                                        )
                                                    else:
                                                        start_offset, end_offset = occurrences[
                                                            occurrence_index
                                                        ]
                                                        st.session_state[manual_state_key] = {
                                                            "action": "relocate",
                                                            "target_index": target_index,
                                                            "start_offset": start_offset,
                                                            "end_offset": end_offset,
                                                            "matched_text": target_text[
                                                                start_offset:end_offset
                                                            ],
                                                            "method": "manual_exact_fragment",
                                                        }
                                                committed_resolution = st.session_state.get(
                                                    manual_state_key
                                                )
                                                if committed_resolution:
                                                    mention_resolutions[conflict.mention_id] = dict(
                                                        committed_resolution
                                                    )
                                                    st.success(
                                                        "Fragmento manual confirmado para la vista previa."
                                                    )
                                                else:
                                                    st.info(
                                                        "La relocalización no se incorporará hasta pulsar "
                                                        "Confirmar fragmento manual."
                                                    )
                                            elif choice == "reject":
                                                st.session_state.pop(
                                                    f"{key_base}_manual_resolution", None
                                                )
                                                reject_confirmed = st.checkbox(
                                                    "Confirmo que esta mención debe quedar rechazada; "
                                                    "la autoridad canónica y sus relaciones se conservarán",
                                                    key=f"{key_base}_reject_confirm",
                                                )
                                                if reject_confirmed:
                                                    mention_resolutions[conflict.mention_id] = {
                                                        "action": "reject",
                                                        "method": "manual_duplicate_rejection",
                                                    }
                                                else:
                                                    st.info(
                                                        "La mención no se rechazará hasta confirmar esta decisión."
                                                    )
                                            else:
                                                st.session_state.pop(
                                                    f"{key_base}_manual_resolution", None
                                                )

                                    if mention_resolutions:
                                        engine = create_sqlite_engine(db_path)
                                        try:
                                            with session_scope(engine) as session:
                                                rebase_preview = preview_editable_rebase(
                                                    session,
                                                    source_key=source_key,
                                                    page=page,
                                                    candidate_run_id=run_id,
                                                    mention_resolutions=mention_resolutions,
                                                    text_resolutions=text_resolutions,
                                                    projection_resolutions=projection_resolutions,
                                                )
                                        except (ValueError, RuntimeError, OSError) as exc:
                                            st.error(str(exc))
                                            rebase_preview = None
                                        finally:
                                            engine.dispose()

                                metadata_resolutions: dict[str, dict] = {}
                                if (
                                    rebase_preview is not None
                                    and not rebase_preview.text_conflicts
                                    and not rebase_preview.projection_conflicts
                                    and not rebase_preview.mention_conflicts
                                    and rebase_preview.metadata_conflicts
                                ):
                                    st.warning(
                                        "Hay metadatos incompatibles entre objetos que convergen en "
                                        "un mismo bloque candidato. Elegí explícitamente el valor resultante."
                                    )
                                    for conflict in rebase_preview.metadata_conflicts:
                                        key_base = (
                                            f"processing_rebase_metadata_{source_key}_{page}_"
                                            f"{run_id}_{conflict.conflict_id}"
                                        )
                                        block = rebase_preview.candidate_objects[conflict.target_index]
                                        with st.container(border=True):
                                            kind_label = {
                                                "document_part": "Parte documental",
                                                "review_status": "Estado de revisión",
                                                "object_type": "Tipo de bloque",
                                            }.get(conflict.kind, conflict.kind)
                                            st.write(
                                                f"**{kind_label}** · bloque {block.order_index + 1}"
                                            )
                                            st.caption(conflict.reason)
                                            st.code(block.rebased_text[:600] or "[bloque vacío]")
                                            option_values = ["pending", *range(len(conflict.options))]
                                            selected = st.selectbox(
                                                "Valor que debe quedar",
                                                options=option_values,
                                                format_func=lambda value, options=conflict.options: (
                                                    "Pendiente de resolución"
                                                    if value == "pending"
                                                    else options[value].label
                                                ),
                                                key=f"{key_base}_choice",
                                            )
                                            if selected != "pending":
                                                option = conflict.options[selected]
                                                metadata_resolutions[conflict.conflict_id] = {
                                                    "action": "select",
                                                    "value": option.value,
                                                    "expected_values": [
                                                        item.value for item in conflict.options
                                                    ],
                                                    "method": "manual_metadata_selection",
                                                }
                                                st.success(
                                                    "Este valor se incorporará a la vista previa recalculada."
                                                )

                                    if metadata_resolutions:
                                        engine = create_sqlite_engine(db_path)
                                        try:
                                            with session_scope(engine) as session:
                                                rebase_preview = preview_editable_rebase(
                                                    session,
                                                    source_key=source_key,
                                                    page=page,
                                                    candidate_run_id=run_id,
                                                    mention_resolutions=mention_resolutions,
                                                    text_resolutions=text_resolutions,
                                                    projection_resolutions=projection_resolutions,
                                                    metadata_resolutions=metadata_resolutions,
                                                )
                                        except (ValueError, RuntimeError, OSError) as exc:
                                            st.error(str(exc))
                                            rebase_preview = None
                                        finally:
                                            engine.dispose()

                                attribute_resolutions: dict[str, dict] = {}
                                if (
                                    rebase_preview is not None
                                    and not rebase_preview.text_conflicts
                                    and not rebase_preview.projection_conflicts
                                    and not rebase_preview.mention_conflicts
                                    and not rebase_preview.metadata_conflicts
                                    and rebase_preview.attribute_conflicts
                                ):
                                    st.warning(
                                        "Hay atributos especializados incompatibles. Elegí un valor "
                                        "existente, eliminá el atributo o escribí un valor JSON manual."
                                    )
                                    for conflict in rebase_preview.attribute_conflicts:
                                        key_base = (
                                            f"processing_rebase_attribute_{source_key}_{page}_"
                                            f"{run_id}_{conflict.conflict_id}"
                                        )
                                        block = rebase_preview.candidate_objects[
                                            conflict.target_index
                                        ]
                                        with st.container(border=True):
                                            st.write(
                                                f"**Atributo `{conflict.attribute_key}`** · "
                                                f"bloque {block.order_index + 1}"
                                            )
                                            st.caption(conflict.reason)
                                            st.code(block.rebased_text[:600] or "[bloque vacío]")
                                            option_values = [
                                                "pending",
                                                *range(len(conflict.options)),
                                                "manual",
                                            ]
                                            selected = st.selectbox(
                                                "Valor que debe quedar",
                                                options=option_values,
                                                format_func=lambda value, options=conflict.options: (
                                                    "Pendiente de resolución"
                                                    if value == "pending"
                                                    else (
                                                        "Escribir un valor JSON manual"
                                                        if value == "manual"
                                                        else options[value].label
                                                    )
                                                ),
                                                key=f"{key_base}_choice",
                                            )
                                            manual_state_key = f"{key_base}_manual_resolution"
                                            if isinstance(selected, int):
                                                st.session_state.pop(manual_state_key, None)
                                                option = conflict.options[selected]
                                                attribute_resolutions[conflict.conflict_id] = {
                                                    "action": "select",
                                                    "option_key": option.option_key,
                                                    "expected_option_keys": [
                                                        item.option_key
                                                        for item in conflict.options
                                                    ],
                                                    "method": "manual_attribute_selection",
                                                }
                                                st.success(
                                                    "Este valor se incorporará a la vista previa recalculada."
                                                )
                                            elif selected == "manual":
                                                default_value = (
                                                    conflict.options[0].value
                                                    if conflict.options
                                                    and conflict.options[0].action == "set"
                                                    else None
                                                )
                                                with st.form(
                                                    f"{key_base}_manual_form",
                                                    enter_to_submit=False,
                                                ):
                                                    manual_json = st.text_area(
                                                        "Valor JSON exacto",
                                                        value=json.dumps(
                                                            default_value,
                                                            ensure_ascii=False,
                                                            indent=2,
                                                        ),
                                                        key=f"{key_base}_manual_json",
                                                    )
                                                    manual_confirmed = st.checkbox(
                                                        "Confirmo este valor JSON",
                                                        key=f"{key_base}_manual_confirm",
                                                    )
                                                    manual_submitted = st.form_submit_button(
                                                        "Confirmar valor JSON"
                                                    )
                                                if manual_submitted:
                                                    st.session_state.pop(manual_state_key, None)
                                                    if not manual_confirmed:
                                                        st.error(
                                                            "Marcá la confirmación antes de guardar "
                                                            "el valor JSON."
                                                        )
                                                    else:
                                                        try:
                                                            parsed_value = json.loads(manual_json)
                                                        except json.JSONDecodeError as exc:
                                                            st.error(
                                                                "JSON inválido: "
                                                                f"línea {exc.lineno}, columna {exc.colno}."
                                                            )
                                                        else:
                                                            st.session_state[manual_state_key] = {
                                                                "action": "manual_json",
                                                                "value": parsed_value,
                                                                "expected_option_keys": [
                                                                    item.option_key
                                                                    for item in conflict.options
                                                                ],
                                                                "method": "manual_attribute_json",
                                                            }
                                                committed_resolution = st.session_state.get(
                                                    manual_state_key
                                                )
                                                if committed_resolution:
                                                    attribute_resolutions[
                                                        conflict.conflict_id
                                                    ] = dict(committed_resolution)
                                                    st.success(
                                                        "Valor JSON confirmado para la vista previa."
                                                    )
                                                else:
                                                    st.info(
                                                        "El valor manual no se incorporará hasta pulsar "
                                                        "Confirmar valor JSON."
                                                    )
                                            else:
                                                st.session_state.pop(manual_state_key, None)

                                    if attribute_resolutions:
                                        engine = create_sqlite_engine(db_path)
                                        try:
                                            with session_scope(engine) as session:
                                                rebase_preview = preview_editable_rebase(
                                                    session,
                                                    source_key=source_key,
                                                    page=page,
                                                    candidate_run_id=run_id,
                                                    mention_resolutions=mention_resolutions,
                                                    text_resolutions=text_resolutions,
                                                    projection_resolutions=projection_resolutions,
                                                    metadata_resolutions=metadata_resolutions,
                                                    attribute_resolutions=attribute_resolutions,
                                                )
                                        except (ValueError, RuntimeError, OSError) as exc:
                                            st.error(str(exc))
                                            rebase_preview = None
                                        finally:
                                            engine.dispose()

                            if rebase_preview is not None:
                                rebase_metrics = st.columns(4)
                                rebase_metrics[0].metric(
                                    "Bloques editables", rebase_preview.old_object_count
                                )
                                rebase_metrics[1].metric(
                                    "Bloques candidatos", rebase_preview.new_object_count
                                )
                                rebase_metrics[2].metric(
                                    "Cambios humanos", rebase_preview.human_change_count
                                )
                                rebase_metrics[3].metric(
                                    "Menciones", rebase_preview.mention_count
                                )
                                st.caption(
                                    f"También se trasladarán {rebase_preview.comment_count} comentarios, "
                                    f"{rebase_preview.tag_count} etiquetas y "
                                    f"{rebase_preview.document_part_count} asignaciones a partes documentales."
                                )
                                if rebase_preview.structural_action_count:
                                    st.info(
                                        f"La página tiene {rebase_preview.structural_action_count} acciones "
                                        "estructurales históricas. El rebase usa el estado activo actual como "
                                        "fuente de verdad; el historial se conserva y ya no bloquea por sí solo."
                                    )
                                if rebase_preview.conflicts:
                                    st.error(
                                        "El rebase continúa bloqueado por incompatibilidades estructurales reales:"
                                    )
                                    for conflict in rebase_preview.conflicts:
                                        st.write(f"• {conflict}")
                                if rebase_preview.text_conflicts:
                                    st.error(
                                        "Todavía quedan conflictos textuales sin una resolución confirmada:"
                                    )
                                    for conflict in rebase_preview.text_conflicts:
                                        st.write(f"• {conflict.reason}")
                                if rebase_preview.projection_conflicts:
                                    st.error(
                                        "Todavía quedan objetos anotados sin una proyección estructural confirmada:"
                                    )
                                    for conflict in rebase_preview.projection_conflicts:
                                        st.write(
                                            f"• Objeto {conflict.source_order_index + 1}: "
                                            f"{conflict.reason}"
                                        )
                                if rebase_preview.mention_conflicts:
                                    st.error(
                                        "Todavía quedan conflictos de menciones sin una resolución válida:"
                                    )
                                    for conflict in rebase_preview.mention_conflicts:
                                        st.write(
                                            f"• «{conflict.mention_text}»: {conflict.reason}"
                                        )
                                if rebase_preview.metadata_conflicts:
                                    st.error(
                                        "Todavía quedan conflictos de metadatos sin una resolución válida:"
                                    )
                                    for conflict in rebase_preview.metadata_conflicts:
                                        st.write(
                                            f"• Bloque {rebase_preview.candidate_objects[conflict.target_index].order_index + 1}: "
                                            f"{conflict.reason}"
                                        )
                                if rebase_preview.attribute_conflicts:
                                    st.error(
                                        "Todavía quedan atributos especializados sin una resolución válida:"
                                    )
                                    for conflict in rebase_preview.attribute_conflicts:
                                        st.write(
                                            f"• Bloque {rebase_preview.candidate_objects[conflict.target_index].order_index + 1}, "
                                            f"`{conflict.attribute_key}`: {conflict.reason}"
                                        )
                                if rebase_preview.can_apply:
                                    st.success(
                                        "La vista previa no detectó pérdidas ni ambigüedades pendientes. "
                                        "La operación será transaccional y conservará el historial anterior."
                                    )
                                if rebase_preview.unified_text_diff:
                                    with st.expander("Ver correcciones humanas trasladadas"):
                                        st.code(
                                            rebase_preview.unified_text_diff, language="diff"
                                        )
                                st.dataframe(
                                    [
                                        {
                                            "Orden": item.order_index + 1,
                                            "Tipo": item.object_type,
                                            "Anotaciones trasladadas": item.carried_annotations,
                                            "Texto resultante": item.rebased_text,
                                        }
                                        for item in rebase_preview.candidate_objects
                                    ],
                                    hide_index=True,
                                    use_container_width=True,
                                )
                                with st.form(
                                    f"processing_rebase_commit_{source_key}_{page}_{run_id}",
                                    enter_to_submit=False,
                                ):
                                    rebase_confirmed = st.checkbox(
                                        "Confirmo que revisé la vista previa y deseo aplicar el rebase",
                                        disabled=not rebase_preview.can_apply,
                                        key=f"processing_rebase_confirm_{source_key}_{page}_{run_id}",
                                    )
                                    rebase_submitted = st.form_submit_button(
                                        "Aplicar rebase y adoptar la candidata",
                                        type="primary",
                                        disabled=not rebase_preview.can_apply,
                                        use_container_width=True,
                                    )
                                if rebase_submitted and not rebase_confirmed:
                                    st.error(
                                        "Marcá la confirmación dentro del formulario antes de aplicar el rebase."
                                    )
                                elif rebase_submitted:
                                    engine = create_sqlite_engine(db_path)
                                    try:
                                        with session_scope(engine) as session:
                                            result = apply_editable_rebase(
                                                session,
                                                decisions=decisions,
                                                source_key=source_key,
                                                page=page,
                                                candidate_run_id=run_id,
                                                expected_page_revision=(
                                                    rebase_preview.expected_page_revision
                                                ),
                                                rebased_by=actor or "local_user",
                                                note=note,
                                                mention_resolutions=mention_resolutions,
                                                text_resolutions=text_resolutions,
                                                projection_resolutions=projection_resolutions,
                                                metadata_resolutions=metadata_resolutions,
                                                attribute_resolutions=attribute_resolutions,
                                            )
                                    except (ValueError, RuntimeError, OSError) as exc:
                                        st.error(str(exc))
                                    else:
                                        rejected_suffix = (
                                            f" y se rechazaron {result.mentions_rejected} duplicadas"
                                            if result.mentions_rejected
                                            else ""
                                        )
                                        st.session_state["processing_flash"] = (
                                            f"Página {page}: rebase aplicado. "
                                            f"Se crearon {result.new_objects_created} bloques, "
                                            f"se retiraron {result.old_objects_retired} anteriores, "
                                            f"se relocalizaron {result.mentions_relocated} menciones"
                                            f"{rejected_suffix}; se absorbieron "
                                            f"{result.structural_actions_absorbed} acciones estructurales históricas "
                                            f"y se resolvieron {result.projection_resolutions_applied} "
                                            "proyecciones manuales."
                                        )
                                        request_tab(
                                            st,
                                            key="processing_tabs",
                                            label="Selección canónica",
                                        )
                                        rerun_view(st)
                                    finally:
                                        engine.dispose()

                    if assessment.editable_page_id is not None:
                        if st.button(
                            "Abrir esta página en Revisión",
                            use_container_width=True,
                        ):
                            _open_review(st, source_key=source_key, page=page)

            st.caption(
                f"Documento: {current_row.selected_pages}/{current_row.page_count or '?'} "
                f"páginas seleccionadas · {current_row.editable_pages} editables · "
                f"estado {_STATUS_LABELS[current_row.status]}."
            )

    with history_tab:
        st.caption("Consultá las tareas ejecutadas, su estado y los errores registrados.")
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
