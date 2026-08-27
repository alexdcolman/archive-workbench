from __future__ import annotations

from archive_workbench.ui_help import TAB_HELP
from pathlib import Path
import json
import re

from sqlalchemy import func, select

from archive_workbench.db import create_sqlite_engine, session_scope
from archive_workbench.db.models import EditableObject, EditablePage
from archive_workbench.candidate_review import (
    ADOPTION_ALREADY,
    ADOPTION_MANUAL,
    ADOPTION_NOT_INITIALIZED,
    adopt_candidate_page,
    add_editable_object_from_regional_candidate,
    assess_candidate_adoption,
    compare_candidate_page,
    prepare_candidate_run_for_review,
    render_candidate_overlay,
    replace_editable_object_text_from_regional_candidate,
    resolve_candidate_keep_edits,
)
from archive_workbench.editing import bootstrap_editable_layer
from archive_workbench.review import ReviewObjectRow
from archive_workbench.review_canvas import clickable_review_canvas, review_canvas_with_drawing
from archive_workbench.page_actions import execute_page_action
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
from archive_workbench.surya_engine import stop_surya_servers
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
from archive_workbench.ui_navigation import rerun_app, rerun_view, request_app_view, request_tab, section_heading, tracked_tabs
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
    "file_available": "Falta preparar imágenes",
    "pending_preparation": "Falta preparar imágenes",
    "prepared": "Imágenes listas para extraer texto",
    "pending_extraction": "Extrayendo texto",
    "incomplete_extraction": "Extracción de texto incompleta",
    "pending_selection": "Texto extraído; falta elegirlo para revisión",
    "ready_for_review": "Texto elegido; listo para revisión",
    "in_review": "En revisión",
    "completed": "Completado",
    "error": "Con errores",
}
_OPERATION_LABELS = {
    "prepare": "1. Preparar imágenes para extraer texto",
    "extract": "2. Extraer texto de las imágenes preparadas",
    "retry_failed": "Reintentar páginas con error de extracción",
    "bootstrap": "Enviar texto elegido a Revisar documentos",
}
_AUTO_QUALITY_LABELS = {
    "clear": "Sin alertas detectadas",
    "attention": "Revisar",
    "critical": "Problema probable",
}
_REGIONAL_TAB_LABEL = "Leer una zona"
_SELECTION_TAB_LABEL = "Elegir texto"
_REGIONAL_INTEGRATION_TAB_LABEL = "Corregir o agregar"
_BULK_REVIEW_TAB_LABEL = "Enviar a revisión"


_RUN_QUALITY_LABELS = {
    "unreviewed": "Sin revisar",
    "needs_review": "Requiere revisión",
    "accepted": "Aceptada",
    "approved": "Aprobada",
    "rejected": "Rechazada",
    "stale": "Desactualizada",
}


def _restore_single_widget_state(
    st,
    *,
    key: str,
    options: list[str],
    default: str,
) -> None:
    """Restaura una selección aunque Streamlit haya eliminado la clave del widget."""

    remembered_key = f"{key}__remembered"
    candidate = st.session_state.get(key)
    if candidate not in options:
        candidate = st.session_state.get(remembered_key)
    if candidate not in options:
        candidate = default
    st.session_state[key] = candidate


def _remember_single_widget_state(st, *, key: str, value: str) -> None:
    st.session_state[f"{key}__remembered"] = value


def _restore_multi_widget_state(
    st,
    *,
    key: str,
    options: list[str],
) -> None:
    """Restaura una selección múltiple y descarta opciones que ya no existen."""

    remembered_key = f"{key}__remembered"
    candidate = st.session_state.get(key)
    if not isinstance(candidate, list):
        candidate = st.session_state.get(remembered_key, [])
    selected = [value for value in candidate if value in options]
    st.session_state[key] = selected


def _remember_multi_widget_state(st, *, key: str, values: list[str]) -> None:
    st.session_state[f"{key}__remembered"] = list(values)


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


def _compact_text(text: str, limit: int = 90) -> str:
    compact = " ".join((text or "").split())
    if len(compact) <= limit:
        return compact or "[sin texto]"
    return compact[: limit - 1] + "…"


def _profile_ui_label(path: Path, profile) -> str:
    method = {
        "surya_cli": "Reconocimiento de texto y estructura (Surya)",
        "tesseract": "Reconocimiento de texto (Tesseract)",
        "docling_cli": "Extracción de texto y estructura (Docling)",
    }.get(profile.backend, "Extracción de texto")
    return f"{path.name} · {method}"


def _extraction_run_ui_label(run) -> str:
    """Nombre visible del motor que produjo una corrida guardada."""

    return {
        "surya_cli": "Surya",
        "docling_cli": "Docling",
        "tesseract_tsv": "Tesseract",
        "tesseract_regions": "Tesseract · lectura de zona",
    }.get(run.engine, run.profile_key or run.engine)


def _percentage(value) -> str:
    if value is None:
        return "—"
    return f"{float(value) * 100:.1f}%"


def _render_automatic_quality(st, assessment) -> None:
    if assessment is None:
        st.badge("Control automático sin evaluar", color="gray")
        return
    label = _AUTO_QUALITY_LABELS.get(assessment.status, assessment.status)
    alert_count = len(assessment.flags)
    suffix = "" if not alert_count else f" · {alert_count} alerta{'s' if alert_count != 1 else ''}"
    color = {QUALITY_CLEAR: "green", QUALITY_ATTENTION: "orange"}.get(assessment.status, "red")
    st.badge(f"Control automático: {label}{suffix}", color=color)

    with st.expander(
        "Indicadores del control automático",
        expanded=False,
    ):
        st.caption(
            "Estos indicadores señalan riesgos observables; no miden la exactitud del OCR "
            "ni reemplazan la revisión manual."
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
            {"Indicador": "Caracteres del texto", "Valor": str(metrics.get("character_count", "—"))},
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
                "marked": "Posible marcado",
                "unmarked": "Posible no marcado",
                "indeterminate": "Indeterminado",
            }
            method_labels = {
                "html_control": "control conservado en el HTML de Surya",
                "explicit_text": "símbolo y rótulo en el mismo fragmento de texto",
                "spatial": "marca próxima al rótulo",
                "reading_order": "asociación por orden de lectura",
                "unlinked": "sin rótulo asociado",
            }
            st.write("Casilleros o marcas detectadas")
            st.dataframe(
                [
                    {
                        "Estado detectado": state_labels.get(item.get("state"), item.get("state", "—")),
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
                "Los casilleros vacíos que no produzcan ningún texto reconocido no pueden inferirse "
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
            st.write("**Sugerencias conservadoras sobre la extracción**")
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
            f"Preparación: {summary.runs_created} versiones nuevas, "
            f"{summary.runs_reused} preparaciones ya existentes reutilizadas y {summary.assets_created} archivos derivados creados."
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
            f"Extracción de texto: {summary.pages_processed} páginas, {summary.objects_created} fragmentos de texto "
            f"y {summary.characters_created} caracteres."
        )
        if summary.failed:
            warnings = list(summary.warnings)
            if warnings:
                first = str(warnings[0])
                if "no tiene una corrida de preprocesamiento vigente" in first:
                    message = "No se pudo extraer texto porque el documento todavía no tenía imágenes preparadas."
                else:
                    reason = first.split(": ", 1)[-1].strip()
                    message = f"No se pudo extraer texto: {reason}"
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
        f"Envío a Revisar documentos: {summary.pages_created} páginas nuevas, "
        f"{summary.pages_reused} ya disponibles reutilizadas y {summary.objects_created} fragmentos de texto disponibles para revisar."
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
    source_labels: dict[str, str] | None,
    profile_path: Path | None,
    ocr_treatment: str,
    geometry_mode: str,
    force: bool,
) -> None:
    profile = None
    runtime_profile = None
    derivative_profile = None
    cleanup_surya = False
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
            st.error("Elegí un método de extracción.")
            return
        profile = load_extraction_profile(profile_path)
        resolution = resolve_extraction_profile(project_root, profile)
        if not resolution.ready:
            st.error("El método de extracción elegido no está disponible en este equipo y tampoco está disponible su alternativa configurada.")
            for check in resolution.effective_report.checks:
                if check.required and not check.ok:
                    st.write(f"**{check.name}:** {check.detail}")
            return
        runtime_profile = profile
        if profile.backend == "surya_cli" and not resolution.fallback_used:
            # La interfaz es dueña del ciclo de vida del servidor: se conserva sólo
            # durante un lote y se libera al finalizar la tarea completa.
            runtime_profile = profile.model_copy(
                update={"surya_keep_server": len(source_keys) > 1}
            )
            cleanup_surya = True
        parameters.update(
            profile_path=profile_path.relative_to(project_root).as_posix(),
            profile_key=profile.profile_key,
            backend=profile.backend,
            device=profile.device,
            effective_profile_key=resolution.effective.profile_key,
            effective_backend=resolution.effective.backend,
            automatic_fallback=resolution.fallback_used,
            selection_policy="never",
            resource_cleanup="automatic_after_job",
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
    try:
        for index, source_key in enumerate(source_keys, start=1):
            status_box.write(
                f"Procesando **{(source_labels or {}).get(source_key, 'documento seleccionado')}** "
                f"({index}/{len(source_keys)})"
            )
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
                            assert runtime_profile is not None
                            summary = extract_documents_preferred(
                                session,
                                project_root=project_root,
                                decisions=decisions,
                                profile=runtime_profile,
                                source_keys={source_key},
                                force=force,
                                created_by=actor or "local_user",
                                selection_policy="never",
                            )
                        elif operation == "retry_failed":
                            assert runtime_profile is not None
                            pages = failed_extraction_pages(session, source_key=source_key)
                            if not pages:
                                raise ValueError("No hay páginas fallidas registradas para reintentar")
                            summary = extract_documents_preferred(
                                session,
                                project_root=project_root,
                                decisions=decisions,
                                profile=runtime_profile,
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
    finally:
        if cleanup_surya:
            stop_surya_servers()
    _finish_job(db_path=db_path, job_id=job_id)
    st.session_state["processing_flash"] = (
        f"Trabajo {_OPERATION_LABELS[operation].lower()} finalizado. "
        "El texto elegido para revisar no fue modificado automáticamente."
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
                    "Dewarp detectado": "sí" if row.dewarp_detected else "no",
                    "Dewarp aplicado": "sí" if row.dewarp_applied else "no",
                    "Confianza dewarp": f"{row.dewarp_confidence:.3f}",
                    "Desplazamiento máximo": (
                        f"{row.dewarp_max_displacement_px:.1f}px"
                        if row.dewarp_detected
                        else "—"
                    ),
                    "Franjas con soporte": row.dewarp_support_strips,
                    "Líneas detectadas": row.lines_detected,
                    "Líneas eliminadas": row.lines_removed,
                }
                for row in rows
            ],
            hide_index=True,
            use_container_width=True,
        )
        base_page_labels = [f"{row.title} · página {row.page}" for row in rows]
        label_counts: dict[str, int] = {}
        for label in base_page_labels:
            label_counts[label.casefold()] = label_counts.get(label.casefold(), 0) + 1
        page_positions: dict[str, int] = {}
        page_labels = []
        for label in base_page_labels:
            key = label.casefold()
            if label_counts[key] > 1:
                page_positions[key] = page_positions.get(key, 0) + 1
                page_labels.append(f"{label} · documento {page_positions[key]}")
            else:
                page_labels.append(label)
        options = list(range(len(rows)))
        selected = st.selectbox(
            "Página diagnóstica",
            options=options,
            format_func=lambda index: page_labels[index],
            key="processing_geometry_diagnostic_page",
        )
        row = rows[selected]
        preview_col, image_col, mask_col, dewarp_col = st.columns(4)
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
        with dewarp_col:
            st.write("**Diagnóstico de curvatura**")
            if row.dewarp_diagnostic_relative_path:
                st.image(
                    str(project_root / row.dewarp_diagnostic_relative_path),
                    use_container_width=True,
                )
            else:
                st.caption("Esta preparación no evaluó dewarp.")
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
    prepared = _unique_processing_rows([
        row
        for row in inventory
        if row.preprocessing_status in {"completed", "completed_with_warnings"}
    ])
    if not prepared:
        st.info("No hay documentos con imágenes preparadas para trabajar una zona.")
        return

    prepared_by_id = {_processing_row_identity(row): row for row in prepared}
    prepared_labels = _processing_document_labels(prepared)
    st.markdown("**1. Elegir el documento y la página**")
    selector_cols = st.columns([2, 1])
    selected_document_id = selector_cols[0].selectbox(
        "Documento",
        options=list(prepared_by_id),
        format_func=lambda value: prepared_labels[value],
        key="regional_document_id",
    )
    source_key = prepared_by_id[selected_document_id].source_key

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
        st.warning("Este documento no tiene imágenes preparadas para trabajar una zona.")
        return

    page = selector_cols[1].selectbox(
        "Página",
        options=[item.page for item in assets],
        key=f"regional_page_{selected_document_id}",
    )
    asset = next(item for item in assets if item.page == page)
    image_path = project_root / asset.preview_relative_path

    drafts_key = f"regional_drafts_{selected_document_id}"
    pending_key = f"regional_pending_box_{selected_document_id}_{page}"
    drafts = list(st.session_state.get(drafts_key, []))
    templates = available_region_templates(project_root, source_key=source_key)

    if templates:
        reuse_open = st.toggle(
            "Usar zonas guardadas",
            value=False,
            key=f"regional_saved_layouts_open_{selected_document_id}",
        )
        if reuse_open:
            reuse_cols = st.columns([3, 1])
            selected_template = reuse_cols[0].selectbox(
                "Zonas guardadas",
                options=[str(path) for path in templates],
                format_func=lambda value: Path(value).name,
                key=f"regional_template_{selected_document_id}",
                label_visibility="collapsed",
            )
            if reuse_cols[1].button(
                "Cargar zonas",
                key=f"regional_load_template_{selected_document_id}",
                use_container_width=True,
            ):
                template = load_region_template(selected_template)
                st.session_state[drafts_key] = [
                    draft_from_region(region) for region in template.regions
                ]
                st.session_state.pop(pending_key, None)
                request_tab(st, key="processing_tabs", label=_REGIONAL_TAB_LABEL)
                rerun_view(st)

    pending_box = st.session_state.get(pending_key)
    visible_drafts = [item for item in drafts if int(item.get("page", page)) == page]
    st.markdown("**2. Marcar una zona en la imagen**")
    drawn = regional_region_canvas(
        image_path,
        visible_drafts,
        page=page,
        pending_box=pending_box,
        key=f"regional_canvas_{selected_document_id}_{page}_{len(visible_drafts)}",
    )
    if drawn is not None and drawn != pending_box:
        st.session_state[pending_key] = drawn
        pending_box = drawn

    if pending_box is not None:
        st.markdown("**3. Describir la zona marcada**")
        roles = list(REGION_ROLE_LABELS)
        decision_cols = st.columns(2)
        role = decision_cols[0].selectbox(
            "Qué contiene",
            options=roles,
            format_func=region_role_label,
            key=f"regional_role_{selected_document_id}_{page}",
        )
        default_mode = REGION_ROLE_DEFAULT_MODE[role]
        mode = decision_cols[1].selectbox(
            "Qué hacer",
            options=["ocr", "manual"],
            index=0 if default_mode == "ocr" else 1,
            format_func=lambda value: (
                "Reconocer texto" if value == "ocr" else "Reservar para transcripción manual"
            ),
            key=f"regional_mode_{selected_document_id}_{page}_{role}",
        )
        text_cols = st.columns(2)
        label = text_cols[0].text_input(
            "Nombre de la zona",
            value=region_role_label(role),
            key=f"regional_label_{selected_document_id}_{page}_{role}",
        )
        note = text_cols[1].text_input(
            "Nota opcional",
            key=f"regional_note_{selected_document_id}_{page}_{role}",
        )

        ocr_payload = None
        if mode == "ocr":
            variant = "original"
            psm = 6
            granularity = "paragraph"
            languages_text = "spa"
            ocr_options_open = st.toggle(
                "Opciones del reconocimiento",
                value=False,
                key=f"regional_ocr_options_open_{selected_document_id}_{page}_{role}",
            )
            if ocr_options_open:
                ocr_cols = st.columns(2)
                variant = ocr_cols[0].selectbox(
                    "Tratamiento de imagen",
                    options=["original", "grayscale_autocontrast", "otsu"],
                    key=f"regional_variant_{selected_document_id}_{page}_{role}",
                )
                psm = ocr_cols[1].selectbox(
                    "Modo de lectura (PSM)",
                    options=[3, 4, 6, 7, 11, 13],
                    index=2,
                    key=f"regional_psm_{selected_document_id}_{page}_{role}",
                    help="Parámetro técnico de Tesseract.",
                )
                granularity = ocr_cols[0].selectbox(
                    "Dividir el texto en",
                    options=["paragraph", "line"],
                    format_func=lambda value: "Párrafos" if value == "paragraph" else "Líneas",
                    key=f"regional_granularity_{selected_document_id}_{page}_{role}",
                )
                languages_text = ocr_cols[1].text_input(
                    "Idiomas",
                    value="spa",
                    key=f"regional_languages_{selected_document_id}_{page}_{role}",
                )
            ocr_payload = RegionOcrOptions(
                image_variant=variant,
                psm=psm,
                languages=[item.strip() for item in languages_text.split(",") if item.strip()],
                object_granularity=granularity,
                minimum_characters_warning=1,
            ).model_dump(mode="json")

        st.markdown("**4. Agregar la zona a la lista**")
        if st.button(
            "Agregar esta zona a la lista",
            type="primary",
            disabled=not label.strip(),
            key=f"regional_add_zone_{selected_document_id}_{page}",
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
            request_tab(st, key="processing_tabs", label=_REGIONAL_TAB_LABEL)
            rerun_view(st)

    drafts = list(st.session_state.get(drafts_key, drafts))
    if drafts:
        st.markdown("**5. Revisar las zonas marcadas**")
        st.caption(f"Zonas marcadas: {len(drafts)}")
        st.dataframe(
            [
                {
                    "Página": item.get("page"),
                    "Zona": item.get("label"),
                    "Contenido": region_role_label(str(item.get("semantic_role") or "")),
                    "Acción": "Reconocer texto" if item.get("mode") == "ocr" else "Transcribir manualmente",
                }
                for item in sorted(
                    drafts,
                    key=lambda row: (row.get("page", 0), row.get("reading_order", 0)),
                )
            ],
            hide_index=True,
            use_container_width=True,
        )
        remove_cols = st.columns([3, 1])
        remove_options = list(range(len(drafts)))
        remove_index = remove_cols[0].selectbox(
            "Zona que querés quitar",
            options=remove_options,
            format_func=lambda index: str(drafts[index].get("label") or f"Zona {index + 1}"),
            key=f"regional_remove_select_{selected_document_id}",
            label_visibility="collapsed",
        )
        if remove_cols[1].button(
            "Quitar zona",
            key=f"regional_remove_{selected_document_id}",
            use_container_width=True,
        ):
            drafts.pop(remove_index)
            st.session_state[drafts_key] = drafts
            request_tab(st, key="processing_tabs", label=_REGIONAL_TAB_LABEL)
            rerun_view(st)

    template_key = f"regional_{source_key}"
    technical_open = st.toggle(
        "Cambiar el identificador de esta lectura",
        value=False,
        key=f"regional_technical_open_{selected_document_id}",
    )
    if technical_open:
        template_key = st.text_input(
            "Identificador de este procesamiento",
            value=template_key,
            key=f"regional_template_key_{selected_document_id}",
            help="Se usa para distinguir esta lectura en el historial.",
        )

    st.markdown("**6. Procesar las zonas marcadas**")
    if st.button(
        "Procesar las zonas marcadas",
        type="primary",
        disabled=not drafts or not template_key.strip(),
        key=f"regional_execute_{selected_document_id}",
        help="Guarda esta lectura parcial para decidir después si corrige o agrega texto en la página.",
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
                f"Zonas procesadas: {summary.pages_processed} página(s), "
                f"{summary.objects_created} texto(s) reconocido(s) o reservado(s)."
            )
            for warning in summary.warnings:
                st.warning(warning)


def _processing_row_identity(row) -> str:
    """Identidad estable del documento para controles de Procesar documentos."""

    return str(row.digital_object_id)


def _unique_processing_rows(rows):
    """Procesamiento opera por objeto digital aunque existan varios registros de origen."""
    chosen = {}
    for row in rows:
        current = chosen.get(row.digital_object_id)
        if current is None or (current.source_type != "catalog" and row.source_type == "catalog"):
            chosen[row.digital_object_id] = row
    return list(chosen.values())


def _processing_row_label(row) -> str:
    filename = row.original_filename or "sin nombre de archivo"
    if filename.casefold() == (row.title or "").casefold():
        return row.title
    return f"{row.title} · {filename}"


def _processing_document_labels(rows, *, include_status: bool = False) -> dict[str, str]:
    """Crea rótulos únicos y legibles sin usar el nombre visible como identidad.

    Los nombres de documento y de archivo pueden repetirse legítimamente. Sólo se
    agrega contexto adicional cuando hace falta distinguir dos opciones visibles.
    """

    unique_rows = _unique_processing_rows(rows)
    labels = {
        _processing_row_identity(row): _processing_row_label(row)
        for row in unique_rows
    }

    def duplicate_ids(current: dict[str, str]) -> set[str]:
        grouped: dict[str, list[str]] = {}
        for row_id, label in current.items():
            grouped.setdefault(label.casefold(), []).append(row_id)
        return {row_id for ids in grouped.values() if len(ids) > 1 for row_id in ids}

    duplicated = duplicate_ids(labels)
    if duplicated:
        by_id = {_processing_row_identity(row): row for row in unique_rows}
        for row_id in duplicated:
            row = by_id[row_id]
            path = (row.archival_path or "").strip()
            if path:
                labels[row_id] = f"{labels[row_id]} · {path}"

    duplicated = duplicate_ids(labels)
    if duplicated:
        grouped: dict[str, list[str]] = {}
        for row_id in duplicated:
            grouped.setdefault(labels[row_id].casefold(), []).append(row_id)
        for row_ids in grouped.values():
            ordered_ids = sorted(row_ids)
            for position, row_id in enumerate(ordered_ids, start=1):
                labels[row_id] = f"{labels[row_id]} · documento {position}"

    if include_status:
        by_id = {_processing_row_identity(row): row for row in unique_rows}
        labels = {
            row_id: f"{label} · {_STATUS_LABELS[by_id[row_id].status]}"
            for row_id, label in labels.items()
        }
    return labels


def _bbox_geometry(*, page: int, box: dict[str, float]) -> list[dict]:
    x0, y0, x1, y1 = (float(box[name]) for name in ("x0", "y0", "x1", "y1"))
    return [
        {
            "page": page,
            "coordinate_space": "normalized",
            "polygon": [[x0, y0], [x1, y0], [x1, y1], [x0, y1]],
        }
    ]


def _editable_rows_for_page(session, *, editable_page_id: str):
    return session.scalars(
        select(EditableObject)
        .where(
            EditableObject.editable_page_id == editable_page_id,
            EditableObject.lifecycle_status == "active",
        )
        .order_by(EditableObject.current_order_index, EditableObject.id)
    ).all()


def _review_canvas_rows(editable_rows):
    return [
        ReviewObjectRow(
            object_id=item.id,
            page=item.page_number,
            order_index=item.current_order_index,
            object_type=item.current_object_type,
            lifecycle_status=item.lifecycle_status,
            revision_number=item.revision_number,
            text=item.current_text,
            original_text=None,
            geometry=list(item.current_geometry_json or []),
            attributes=dict(item.current_attributes_json or {}),
            updated_by=item.updated_by or "",
            updated_at=item.updated_at,
            manually_added=item.source_extracted_object_id is None,
            review_status=item.review_status,
            document_part_id=item.document_part_id,
        )
        for item in editable_rows
    ]


def _render_bulk_review_sender(
    st,
    *,
    db_path: Path,
    decisions,
    inventory,
    actor: str,
) -> None:
    candidates = _unique_processing_rows(
        [row for row in inventory if row.extracted_pages or row.extraction_status]
    )
    if not candidates:
        st.info("No hay documentos con extracciones completas disponibles.")
        return

    by_id = {_processing_row_identity(row): row for row in candidates}
    document_labels = _processing_document_labels(candidates)
    mode = st.radio(
        "Enviar",
        options=["single", "multiple"],
        format_func=lambda value: "Un documento" if value == "single" else "Varios documentos",
        horizontal=True,
        key="processing_bulk_mode",
    )

    if mode == "single":
        control_cols = st.columns([2, 1.5])
        selected_id = control_cols[0].selectbox(
            "Documento",
            options=list(by_id),
            format_func=lambda value: document_labels[value],
            key="processing_bulk_single_document",
        )
        current_row = by_id[selected_id]
        engine = create_sqlite_engine(db_path)
        try:
            with session_scope(engine) as session:
                runs = extraction_candidate_runs(
                    session,
                    source_key=current_row.source_key,
                    digital_object_id=current_row.digital_object_id,
                )
                initialized_pages = set(
                    session.scalars(
                        select(EditablePage.page_number).where(
                            EditablePage.digital_object_id == current_row.digital_object_id
                        )
                    ).all()
                )
        finally:
            engine.dispose()
        general_runs = [row for row in runs if row.pages and row.engine != "tesseract_regions"]
        if not general_runs:
            control_cols[1].selectbox(
                "Extracción",
                options=["No disponible"],
                disabled=True,
                key=f"processing_bulk_single_unavailable_{current_row.digital_object_id}",
            )
            st.info("Este documento todavía no tiene una extracción completa disponible.")
            return

        run_id = control_cols[1].selectbox(
            "Extracción",
            options=[row.run_id for row in general_runs],
            format_func=lambda value: next(
                f"{len(row.pages)} pág. · {row.created_at:%Y-%m-%d %H:%M}"
                for row in general_runs if row.run_id == value
            ),
            key=f"processing_bulk_single_run_{current_row.digital_object_id}",
        )
        run = next(row for row in general_runs if row.run_id == run_id)
        pending_pages = sorted(set(run.pages) - initialized_pages)
        existing_pages = len(set(run.pages) & initialized_pages)
        st.caption(
            f"{len(pending_pages)} página(s) nuevas · {existing_pages} ya están en Revisar documentos"
        )
        if st.button(
            "Enviar páginas pendientes",
            type="primary",
            disabled=not pending_pages,
            key=f"processing_bulk_single_apply_{current_row.digital_object_id}_{run_id}",
        ):
            engine = create_sqlite_engine(db_path)
            try:
                with session_scope(engine) as session:
                    result = prepare_candidate_run_for_review(
                        session,
                        decisions=decisions,
                        source_key=current_row.source_key,
                        digital_object_id=current_row.digital_object_id,
                        run_id=run_id,
                        created_by=actor or "local_user",
                    )
            except (ValueError, RuntimeError, OSError) as exc:
                st.error(str(exc))
            else:
                st.session_state["processing_flash"] = (
                    f"{result.pages_initialized} página(s) de {current_row.title} fueron enviadas a Revisar documentos; "
                    f"{result.pages_already_initialized} ya estaban allí."
                )
                request_tab(st, key="processing_tabs", label=_BULK_REVIEW_TAB_LABEL)
                rerun_view(st)
            finally:
                engine.dispose()
        return

    multi_ids = st.multiselect(
        "Documentos",
        options=list(by_id),
        format_func=lambda value: document_labels[value],
        key="processing_bulk_multi_documents",
        placeholder="Elegir documentos",
    )
    multi_plan: list[tuple[object, str]] = []
    multi_rows: list[dict] = []
    engine = create_sqlite_engine(db_path)
    try:
        with session_scope(engine) as session:
            for row_id in multi_ids:
                row = by_id[row_id]
                runs = extraction_candidate_runs(
                    session,
                    source_key=row.source_key,
                    digital_object_id=row.digital_object_id,
                )
                general = [item for item in runs if item.pages and item.engine != "tesseract_regions"]
                initialized = set(
                    session.scalars(
                        select(EditablePage.page_number).where(
                            EditablePage.digital_object_id == row.digital_object_id
                        )
                    ).all()
                )
                if not general:
                    multi_rows.append(
                        {
                            "Documento": document_labels[_processing_row_identity(row)],
                            "Extracción": "No disponible",
                            "Nuevas": 0,
                            "Ya en revisión": len(initialized),
                        }
                    )
                    continue
                chosen = st.selectbox(
                    f"Extracción para {row.title}",
                    options=[item.run_id for item in general],
                    format_func=lambda value, choices=general: next(
                        f"{len(item.pages)} pág. · {item.created_at:%Y-%m-%d %H:%M}"
                        for item in choices if item.run_id == value
                    ),
                    key=f"processing_bulk_multi_run_{row.digital_object_id}",
                )
                chosen_row = next(item for item in general if item.run_id == chosen)
                pending = len(set(chosen_row.pages) - initialized)
                multi_plan.append((row, chosen))
                multi_rows.append(
                    {
                        "Documento": document_labels[_processing_row_identity(row)],
                        "Extracción": f"{len(chosen_row.pages)} pág.",
                        "Nuevas": pending,
                        "Ya en revisión": len(set(chosen_row.pages) & initialized),
                    }
                )
    finally:
        engine.dispose()

    if multi_rows:
        st.dataframe(multi_rows, hide_index=True, use_container_width=True)
    if st.button(
        "Enviar páginas pendientes",
        type="primary",
        disabled=not multi_plan,
        key="processing_bulk_multi_apply",
    ):
        totals = {"pages": 0, "existing": 0}
        engine = create_sqlite_engine(db_path)
        try:
            with session_scope(engine) as session:
                for row, planned_run in multi_plan:
                    result = prepare_candidate_run_for_review(
                        session,
                        decisions=decisions,
                        source_key=row.source_key,
                        digital_object_id=row.digital_object_id,
                        run_id=planned_run,
                        created_by=actor or "local_user",
                    )
                    totals["pages"] += result.pages_initialized
                    totals["existing"] += result.pages_already_initialized
        except (ValueError, RuntimeError, OSError) as exc:
            st.error(str(exc))
        else:
            st.session_state["processing_flash"] = (
                f"Envío completado: {totals['pages']} página(s) nuevas en Revisar documentos; "
                f"{totals['existing']} ya estaban allí."
            )
            request_tab(st, key="processing_tabs", label=_BULK_REVIEW_TAB_LABEL)
            rerun_view(st)
        finally:
            engine.dispose()


def _render_regional_review_integration(
    st,
    *,
    project_root: Path,
    db_path: Path,
    decisions,
    inventory,
    actor: str,
) -> None:
    candidates = _unique_processing_rows(
        [row for row in inventory if row.extraction_status or row.extracted_pages]
    )
    if not candidates:
        st.info("No hay documentos con texto extraído.")
        return

    available: dict[str, tuple[object, list]] = {}
    engine = create_sqlite_engine(db_path)
    try:
        with session_scope(engine) as session:
            for row in candidates:
                runs = extraction_candidate_runs(
                    session,
                    source_key=row.source_key,
                    digital_object_id=row.digital_object_id,
                )
                regional = [item for item in runs if item.pages and item.engine == "tesseract_regions"]
                if regional:
                    available[_processing_row_identity(row)] = (row, regional)
    finally:
        engine.dispose()
    if not available:
        st.info("No hay lecturas de zonas disponibles para incorporar.")
        return

    available_labels = _processing_document_labels([item[0] for item in available.values()])
    context_cols = st.columns([2.2, 0.7, 1.4])
    selected_id = context_cols[0].selectbox(
        "Documento",
        options=list(available),
        format_func=lambda value: available_labels[value],
        key="processing_regional_integrate_document",
        help="Documento cuya página ya está disponible en Revisar documentos y tiene al menos una lectura de zona guardada.",
    )
    row, regional_runs = available[selected_id]
    pages = sorted({page for run in regional_runs for page in run.pages})
    page = context_cols[1].selectbox(
        "Página",
        options=pages,
        key=f"processing_regional_integrate_page_{row.digital_object_id}",
        help="Página en la que querés corregir o agregar texto.",
    )
    page_runs = [run for run in regional_runs if page in run.pages]
    run_id = context_cols[2].selectbox(
        "Lectura de zona",
        options=[run.run_id for run in page_runs],
        format_func=lambda value: next(
            f"{run.created_at:%Y-%m-%d %H:%M}"
            for run in page_runs if run.run_id == value
        ),
        key=f"processing_regional_integrate_run_{row.digital_object_id}_{page}",
        help="Lectura parcial guardada para esa página. Elegí la que contiene el texto que querés incorporar.",
    )

    engine = create_sqlite_engine(db_path)
    try:
        with session_scope(engine) as session:
            comparison = compare_candidate_page(
                session,
                project_root=project_root,
                source_key=row.source_key,
                digital_object_id=row.digital_object_id,
                page=page,
                candidate_run_id=run_id,
            )
            assessment = assess_candidate_adoption(
                session,
                source_key=row.source_key,
                digital_object_id=row.digital_object_id,
                page=page,
                candidate_run_id=run_id,
            )
            editable_rows = (
                _editable_rows_for_page(session, editable_page_id=assessment.editable_page_id)
                if assessment.editable_page_id is not None else []
            )
    except (ValueError, RuntimeError, OSError) as exc:
        st.error(str(exc))
        return
    finally:
        engine.dispose()

    if assessment.editable_page_id is None:
        st.warning(
            f"La página {page} todavía no está en Revisar documentos. Elegí primero una extracción completa en «{_SELECTION_TAB_LABEL}»."
        )
        return
    partial_texts = [item for item in comparison.candidate.objects if item.text.strip()]
    if not partial_texts:
        st.warning("La lectura elegida no recuperó texto para incorporar.")
        return

    text_cols = st.columns([1.1, 1.4])
    partial_id = text_cols[0].selectbox(
        "Texto recuperado",
        options=[item.object_id for item in partial_texts],
        format_func=lambda value: next(
            _compact_text(item.text) for item in partial_texts if item.object_id == value
        ),
        key=f"processing_regional_integrate_text_{row.digital_object_id}_{page}_{run_id}",
        help="Fragmento de texto recuperado dentro de la lectura de zona elegida.",
    )
    partial = next(item for item in partial_texts if item.object_id == partial_id)
    text_cols[1].text_area(
        "Texto de la zona",
        value=partial.text,
        height=100,
        disabled=True,
        key=f"processing_regional_integrate_preview_{row.digital_object_id}_{page}_{run_id}_{partial_id}",
        help="Vista completa del fragmento recuperado antes de decidir si corrige un texto existente o agrega texto faltante.",
    )
    action = st.radio(
        "Acción",
        options=["replace", "add"],
        format_func=lambda value: (
            "Corregir texto existente" if value == "replace" else "Agregar texto faltante"
        ),
        horizontal=True,
        key=f"processing_regional_integrate_action_{row.digital_object_id}_{page}_{run_id}",
    )

    active_ids = [item.id for item in editable_rows]
    target_key = f"processing_regional_integrate_target_{row.digital_object_id}_{page}"
    selected_target = st.session_state.get(target_key)
    if selected_target not in active_ids:
        selected_target = active_ids[0] if active_ids else None
        if selected_target is not None:
            st.session_state[target_key] = selected_target
    canvas_rows = _review_canvas_rows(editable_rows)
    preview_path = (
        comparison.current.preview_path
        if comparison.current is not None and comparison.current.preview_path is not None
        else comparison.candidate.preview_path
    )
    drawn_key = f"processing_regional_new_text_bbox_{row.digital_object_id}_{page}_{run_id}"
    drawn_box = st.session_state.get(drawn_key)

    if action == "replace":
        if not editable_rows:
            st.warning("Esta página no tiene texto existente que pueda corregirse.")
            return
        if preview_path is not None:
            clicked = clickable_review_canvas(
                preview_path,
                canvas_rows,
                page=page,
                selected_object_id=selected_target,
                show_deleted=False,
                key=f"processing_regional_replace_canvas_{row.digital_object_id}_{page}_{run_id}",
            )
            if clicked in active_ids:
                selected_target = clicked
                st.session_state[target_key] = clicked
        selected_target = st.selectbox(
            "Texto que querés corregir",
            options=active_ids,
            format_func=lambda value: next(
                f"{item.current_order_index + 1}. {_compact_text(item.current_text)}"
                for item in editable_rows if item.id == value
            ),
            key=target_key,
        )
        insertion_mode = "end"
        object_type = None
    else:
        if preview_path is not None:
            clicked, newly_drawn = review_canvas_with_drawing(
                preview_path,
                canvas_rows,
                page=page,
                selected_object_id=selected_target,
                show_deleted=False,
                key=f"processing_regional_add_canvas_{row.digital_object_id}_{page}_{run_id}",
                confirmed_box=drawn_box,
            )
            if clicked in active_ids:
                selected_target = clicked
                st.session_state[target_key] = clicked
            if newly_drawn is not None:
                drawn_box = newly_drawn
                st.session_state[drawn_key] = newly_drawn
        if drawn_box is None:
            st.info("Dibujá en la página dónde irá el texto nuevo.")
        else:
            st.success("Ubicación marcada.")
        object_type_options = [item.key for item in decisions.object_types if item.editable]
        default_type = partial.object_type if partial.object_type in object_type_options else (
            "paragraph" if "paragraph" in object_type_options else object_type_options[0]
        )
        add_cols = st.columns(2)
        object_type = add_cols[0].selectbox(
            "Tipo de texto",
            options=object_type_options,
            index=object_type_options.index(default_type),
            format_func=lambda value: next(item.label for item in decisions.object_types if item.key == value),
            key=f"processing_regional_add_type_{row.digital_object_id}_{page}_{run_id}",
        )
        position_options = ["end"] + (["after", "before"] if editable_rows else [])
        insertion_mode = add_cols[1].selectbox(
            "Orden de lectura",
            options=position_options,
            format_func=lambda value: {
                "end": "Al final",
                "after": "Después de un texto existente",
                "before": "Antes de un texto existente",
            }[value],
            key=f"processing_regional_add_position_{row.digital_object_id}_{page}_{run_id}",
        )
        if insertion_mode in {"after", "before"} and editable_rows:
            selected_target = st.selectbox(
                "Texto de referencia",
                options=active_ids,
                format_func=lambda value: next(
                    f"{item.current_order_index + 1}. {_compact_text(item.current_text)}"
                    for item in editable_rows if item.id == value
                ),
                key=target_key,
            )

    note = st.text_input(
        "Nota opcional",
        key=f"processing_regional_integrate_note_{row.digital_object_id}_{page}_{run_id}_{action}",
    )
    if action == "replace":
        confirm_label = "Confirmo el reemplazo del texto seleccionado"
        button_label = "Corregir texto"
        disabled = selected_target is None
    else:
        confirm_label = "Confirmo la incorporación en la ubicación marcada"
        button_label = "Agregar texto"
        disabled = drawn_box is None
    confirmed = st.checkbox(
        confirm_label,
        key=f"processing_regional_integrate_confirm_{row.digital_object_id}_{page}_{run_id}_{action}",
    )
    if st.button(
        button_label,
        type="primary",
        disabled=disabled or not confirmed,
        key=f"processing_regional_integrate_apply_{row.digital_object_id}_{page}_{run_id}_{action}",
    ):
        engine = create_sqlite_engine(db_path)
        try:
            with session_scope(engine) as session:
                editable_page = session.get(EditablePage, assessment.editable_page_id)
                if editable_page is None:
                    raise ValueError("La página dejó de estar disponible en Revisar documentos.")
                if action == "replace":
                    if selected_target is None:
                        raise ValueError("Elegí el texto que querés corregir.")
                    execute_page_action(
                        session,
                        editable_page_id=editable_page.id,
                        action_type="regional_ocr_replace",
                        changed_by=actor or "local_user",
                        selected_object_id=selected_target,
                        note=note or None,
                        action=lambda: replace_editable_object_text_from_regional_candidate(
                            session,
                            source_key=row.source_key,
                            digital_object_id=row.digital_object_id,
                            page=page,
                            candidate_run_id=run_id,
                            editable_object_id=selected_target,
                            regional_object_id=partial_id,
                            changed_by=actor or "local_user",
                            note=note or None,
                        ),
                    )
                    flash = f"Página {page}: se corrigió el texto seleccionado."
                else:
                    after_id = selected_target if insertion_mode == "after" else None
                    before_id = selected_target if insertion_mode == "before" else None
                    execute_page_action(
                        session,
                        editable_page_id=editable_page.id,
                        action_type="regional_ocr_add",
                        changed_by=actor or "local_user",
                        selected_object_id=selected_target,
                        note=note or None,
                        action=lambda: add_editable_object_from_regional_candidate(
                            session,
                            decisions=decisions,
                            source_key=row.source_key,
                            digital_object_id=row.digital_object_id,
                            page=page,
                            candidate_run_id=run_id,
                            regional_object_id=partial_id,
                            object_type=object_type,
                            changed_by=actor or "local_user",
                            after_object_id=after_id,
                            before_object_id=before_id,
                            geometry=_bbox_geometry(page=page, box=drawn_box),
                            note=note or None,
                        ),
                    )
                    st.session_state.pop(drawn_key, None)
                    flash = f"Página {page}: se agregó el texto en la ubicación dibujada."
        except (ValueError, RuntimeError, OSError) as exc:
            st.error(str(exc))
        else:
            st.session_state["processing_flash"] = flash
            request_tab(st, key="processing_tabs", label=_REGIONAL_INTEGRATION_TAB_LABEL)
            rerun_view(st)
        finally:
            engine.dispose()


def render_processing_view(
    st,
    *,
    project_root: Path,
    db_path: Path,
    decisions,
    project_id: str,
    actor: str,
) -> None:
    section_heading(st, "Procesar documentos")
    flash = st.session_state.pop("processing_flash", None)
    if flash:
        st.success(flash)

    inventory = _load_inventory(
        db_path=db_path, project_root=project_root, project_id=project_id
    )
    counts = {key: sum(row.status == key for row in inventory) for key in _STATUS_LABELS}

    processing_tabs = [
        "Estado",
        "Preparar / extraer",
        _REGIONAL_TAB_LABEL,
        _SELECTION_TAB_LABEL,
        _REGIONAL_INTEGRATION_TAB_LABEL,
        _BULK_REVIEW_TAB_LABEL,
        "Historial",
    ]
    (
        inventory_tab,
        execute_tab,
        regional_tab,
        selection_tab,
        regional_integration_tab,
        bulk_review_tab,
        history_tab,
    ) = tracked_tabs(
        st,
        processing_tabs,
        key="processing_tabs",
        help_by_label=TAB_HELP["processing_tabs"],
        rerun_on_change=False,
    )

    with inventory_tab:
        filter_cols = st.columns([2, 1.2])
        query = filter_cols[0].text_input(
            "Buscar documento",
            placeholder="Buscar por título, ruta archivística o archivo",
            key="processing_inventory_query",
            label_visibility="collapsed",
        )
        status_filter = filter_cols[1].multiselect(
            "Estado del procesamiento del documento",
            options=list(_STATUS_LABELS),
            format_func=lambda value: _STATUS_LABELS[value],
            key="processing_inventory_status",
            placeholder="Todos los estados",
            label_visibility="collapsed",
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
        if query.strip() or status_filter:
            st.caption(f"{len(visible)} documento(s) encontrados")

        detailed_inventory = st.toggle(
            "Ver más datos",
            value=False,
            key="processing_inventory_details",
        )
        table_rows = []
        for row in visible:
            item = {
                "Estado": _STATUS_LABELS[row.status],
                "Documento": row.title,
                "Ruta archivística": row.archival_path,
                "Páginas": row.page_count,
                "Texto elegido": row.selected_pages,
                "En Revisar documentos": row.editable_pages,
            }
            if detailed_inventory:
                item.update(
                    {
                        "Archivo": row.original_filename,
                        "Texto extraído": row.extracted_pages,
                        "Páginas aprobadas": row.approved_pages,
                        "Último problema": row.last_error,
                    }
                )
            table_rows.append(item)
        st.dataframe(
            table_rows,
            use_container_width=True,
            hide_index=True,
        )

    with execute_tab:
        if not inventory:
            st.info("No hay documentos procesables registrados en el catálogo.")
        else:
            operation_options = ["prepare", "extract"]
            _restore_single_widget_state(
                st,
                key="processing_operation",
                options=operation_options,
                default="prepare",
            )
            operation = st.radio(
                "Paso",
                options=operation_options,
                format_func=lambda value: _OPERATION_LABELS[value],
                horizontal=True,
                key="processing_operation",
                help=(
                    "Primero se preparan las imágenes de página. Después se extrae el texto de esas imágenes."
                ),
            )
            _remember_single_widget_state(
                st, key="processing_operation", value=operation
            )

            if operation == "prepare":
                eligible_rows = _unique_processing_rows([
                    row for row in inventory
                    if row.file_presence not in {"missing", "modified"}
                ])
            else:
                eligible_rows = _unique_processing_rows(
                    [row for row in inventory if row.preprocessing_ready]
                )

            eligible_by_id = {_processing_row_identity(row): row for row in eligible_rows}
            document_options = list(eligible_by_id)
            document_labels = _processing_document_labels(eligible_rows, include_status=True)
            _restore_multi_widget_state(
                st, key="processing_document_ids", options=document_options
            )
            selected_document_ids = st.multiselect(
                "Documentos",
                options=document_options,
                format_func=lambda value: document_labels[value],
                key="processing_document_ids",
                placeholder="Elegir documentos",
            )
            _remember_multi_widget_state(
                st, key="processing_document_ids", values=selected_document_ids
            )
            selected_rows = [eligible_by_id[row_id] for row_id in selected_document_ids]
            source_keys = [row.source_key for row in selected_rows]
            source_labels = {
                row.source_key: document_labels[_processing_row_identity(row)]
                for row in selected_rows
            }
            if not document_options:
                if operation == "extract":
                    st.warning(
                        "Todavía no hay documentos con imágenes preparadas. Elegí el paso 1 y prepará al menos un documento antes de extraer texto."
                    )
                else:
                    st.warning("No hay documentos con una copia local utilizable para preparar imágenes.")

            profile_rows = _profiles(project_root)
            profile_path = None
            selected_extraction_profile = None
            ocr_treatment = "original"
            geometry_mode = "none"
            if operation == "prepare":
                treatment_options = list(OCR_TREATMENT_LABELS)
                _restore_single_widget_state(
                    st,
                    key="processing_ocr_treatment",
                    options=treatment_options,
                    default="original",
                )
                prepare_cols = st.columns(2)
                ocr_treatment = prepare_cols[0].selectbox(
                    "Tratamiento de imagen",
                    options=treatment_options,
                    format_func=lambda value: OCR_TREATMENT_LABELS[value],
                    key="processing_ocr_treatment",
                    help="Se aplica a la imagen de trabajo, no al archivo original.",
                )
                _remember_single_widget_state(
                    st, key="processing_ocr_treatment", value=ocr_treatment
                )

                geometry_options = list(GEOMETRY_MODE_LABELS)
                _restore_single_widget_state(
                    st,
                    key="processing_geometry_mode",
                    options=geometry_options,
                    default="none",
                )
                geometry_mode = prepare_cols[1].selectbox(
                    "Orientación y geometría",
                    options=geometry_options,
                    format_func=lambda value: GEOMETRY_MODE_LABELS[value],
                    key="processing_geometry_mode",
                    help="Corrige orientación, inclinación, curvatura o líneas largas antes de extraer texto.",
                )
                _remember_single_widget_state(
                    st, key="processing_geometry_mode", value=geometry_mode
                )
                _render_geometry_diagnostics(
                    st,
                    project_root=project_root,
                    db_path=db_path,
                    source_keys=source_keys,
                )
            else:
                if not profile_rows:
                    st.error("No se encontraron métodos de extracción de texto configurados para este proyecto.")
                else:
                    selected_profile = st.selectbox(
                        "Método de extracción",
                        options=[str(path) for path, _profile in profile_rows],
                        format_func=lambda value: next(
                            _profile_ui_label(path, profile)
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
                    selected_inventory = list(selected_rows)
                    with st.expander("Detalles técnicos", expanded=False):
                        st.write(f"**Configuración:** `{selected_extraction_profile.profile_key}`")
                        st.write(f"**Motor:** `{selected_extraction_profile.backend}`")
                        st.write(f"**Equipo solicitado:** `{selected_extraction_profile.device}`")
                        if selected_extraction_profile.surya_torch_device == "cpu":
                            st.caption("Los modelos auxiliares de Surya se ejecutan en CPU.")
                        if selected_extraction_profile.fallback_profile:
                            st.caption(
                                "Método alternativo configurado: "
                                f"`{selected_extraction_profile.fallback_profile}`."
                            )
                        if selected_inventory:
                            image_rows = []
                            for row in selected_inventory:
                                treatment = row.preprocessing_ocr_treatment or "original"
                                geometry = row.preprocessing_geometry_mode or "none"
                                profile_variant = selected_extraction_profile.image_variant
                                image_rows.append(
                                    {
                                        "Documento": row.title,
                                        "Tratamiento": OCR_TREATMENT_LABELS.get(treatment, treatment),
                                        "Geometría": GEOMETRY_MODE_LABELS.get(geometry, geometry),
                                        "Transformación del método": (
                                            "Ninguna" if profile_variant == "original" else profile_variant
                                        ),
                                    }
                                )
                            st.dataframe(image_rows, hide_index=True, use_container_width=True)
                    combined = [
                        document_labels[_processing_row_identity(row)]
                        for row in selected_rows
                        if row.preprocessing_ocr_treatment not in {None, "original"}
                    ]
                    if combined and selected_extraction_profile.image_variant != "original":
                        st.warning(
                            "Estos documentos ya recibieron un tratamiento al preparar sus imágenes y el método elegido aplicará otra transformación durante la extracción: "
                            + ", ".join(combined)
                            + ". Verificá que esa combinación sea intencional."
                        )

            force = st.toggle(
                "Crear una nueva versión aunque ya exista una equivalente",
                value=False,
                key="processing_force",
                help=(
                    "Usalo sólo cuando necesites conservar otra corrida con la misma configuración "
                    "en lugar de reutilizar una extracción equivalente ya existente."
                ),
            )

            action_label = (
                "Preparar las imágenes de los documentos seleccionados"
                if operation == "prepare"
                else "Extraer texto de los documentos seleccionados"
            )
            if st.button(
                action_label,
                type="primary",
                disabled=not source_keys or (operation == "extract" and profile_path is None),
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
                    source_labels=source_labels,
                    profile_path=profile_path,
                    ocr_treatment=ocr_treatment,
                    geometry_mode=geometry_mode,
                    force=force,
                )

            if operation == "extract" and source_keys:
                engine = create_sqlite_engine(db_path)
                try:
                    with session_scope(engine) as session:
                        retry_map = {
                            key: failed_extraction_pages(session, source_key=key)
                            for key in source_keys
                        }
                finally:
                    engine.dispose()
                retry_sources = [key for key, pages in retry_map.items() if pages]
                if retry_sources:
                    retry_open = st.toggle(
                        "Reintentar páginas con error",
                        value=False,
                        key="processing_retry_failed_open",
                    )
                    if retry_open:
                        for key in retry_sources:
                            st.caption(
                                f"{source_labels.get(key, 'Documento seleccionado')}: páginas "
                                + ", ".join(map(str, retry_map[key]))
                            )
                        if st.button(
                            "Reintentar páginas con error",
                            disabled=profile_path is None,
                            key="processing_retry_failed_pages",
                        ):
                            _execute_batch(
                                st,
                                project_root=project_root,
                                db_path=db_path,
                                decisions=decisions,
                                project_id=project_id,
                                actor=actor,
                                operation="retry_failed",
                                source_keys=retry_sources,
                                source_labels=source_labels,
                                profile_path=profile_path,
                                ocr_treatment=ocr_treatment,
                                geometry_mode=geometry_mode,
                                force=False,
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
        candidates = _unique_processing_rows(
            [row for row in inventory if row.extracted_pages or row.extraction_status]
        )
        if not candidates:
            st.info("Todavía no hay extracciones completas para comparar.")
        else:
            by_id = {_processing_row_identity(row): row for row in candidates}
            document_labels = _processing_document_labels(candidates)
            selected_document_id = st.selectbox(
                "Documento",
                options=list(by_id),
                format_func=lambda value: document_labels[value],
                key="processing_selection_source",
            )
            current_row = by_id[selected_document_id]
            source_key = current_row.source_key
            engine = create_sqlite_engine(db_path)
            try:
                with session_scope(engine) as session:
                    runs = extraction_candidate_runs(session, source_key=source_key, digital_object_id=current_row.digital_object_id)
            finally:
                engine.dispose()
            general_runs = [row for row in runs if row.pages and row.engine != "tesseract_regions"]
            selectable_runs = general_runs

            available_pages = sorted({page for row in selectable_runs for page in row.pages})
            if not available_pages:
                st.warning(
                    "Las extracciones registradas no contienen páginas completadas para comparar."
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
                    "Extracción",
                    options=[row.run_id for row in page_runs],
                    format_func=lambda value: next(
                        (
                            f"{row.created_at:%Y-%m-%d %H:%M} · "
                            f"{len(row.pages)} pág. · {_extraction_run_ui_label(row)}"
                        )
                        for row in page_runs
                        if row.run_id == value
                    ),
                    key=f"processing_candidate_run_{current_row.digital_object_id}_{page}",
                )
                engine = create_sqlite_engine(db_path)
                try:
                    with session_scope(engine) as session:
                        comparison = compare_candidate_page(
                            session,
                            project_root=project_root,
                            source_key=source_key,
                                    digital_object_id=current_row.digital_object_id,
                            page=page,
                            candidate_run_id=run_id,
                        )
                        assessment = assess_candidate_adoption(
                            session,
                            source_key=source_key,
                                    digital_object_id=current_row.digital_object_id,
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
                    quality_open = st.toggle(
                        "Actualizar control automático",
                        value=False,
                        key=f"processing_quality_open_{current_row.digital_object_id}_{page}_{run_id}",
                    )
                    if quality_open and st.button(
                        "Calcular indicadores",
                        key=f"processing_quality_{current_row.digital_object_id}_{page}_{run_id}",
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
                            request_tab(st, key="processing_tabs", label=_SELECTION_TAB_LABEL)
                            st.session_state["processing_flash"] = f"Página {page}: control automático actualizado."
                            rerun_view(st)
                        finally:
                            engine.dispose()

                    current = comparison.current
                    candidate = comparison.candidate
                    similarity = (
                        f"{comparison.text_similarity * 100:.1f}% parecido"
                        if comparison.text_similarity is not None
                        else "sin selección previa"
                    )
                    st.caption(
                        f"{candidate.object_count} fragmentos · {candidate.character_count} caracteres · "
                        f"{similarity} · {_RUN_QUALITY_LABELS.get(candidate.quality_status, candidate.quality_status)}"
                    )

                    left, right = st.columns(2)
                    with left:
                        st.write("**Elegida actualmente**")
                        if current is None:
                            st.info("Esta página todavía no tiene una extracción elegida para Revisar documentos.")
                        else:
                            st.caption(_extraction_run_ui_label(current))
                            _render_automatic_quality(st, current.automatic_quality)
                            with st.expander("Detalles técnicos de esta extracción", expanded=False):
                                st.write(f"Motor: {_extraction_run_ui_label(current)}")
                                st.write(f"Perfil: `{current.profile_key or current.engine}`")
                            if current.preview_path is not None:
                                st.image(
                                    render_candidate_overlay(
                                        current.preview_path, current.objects, page=page
                                    ),
                                    use_container_width=True,
                                )
                            st.text_area(
                                "Texto de la extracción elegida",
                                value=current.text,
                                height=180,
                                disabled=True,
                                key=f"processing_current_text_{current_row.digital_object_id}_{page}_{current.run_id}",
                            )
                    with right:
                        st.write("**Comparada**")
                        st.caption(_extraction_run_ui_label(candidate))
                        _render_automatic_quality(st, candidate.automatic_quality)
                        with st.expander("Detalles técnicos de esta extracción", expanded=False):
                            st.write(f"Motor: {_extraction_run_ui_label(candidate)}")
                            st.write(f"Perfil: `{candidate.profile_key or candidate.engine}`")
                        if candidate.preview_path is not None:
                            st.image(
                                render_candidate_overlay(
                                    candidate.preview_path, candidate.objects, page=page
                                ),
                                use_container_width=True,
                            )
                        st.text_area(
                            "Texto de la extracción comparada",
                            value=candidate.text,
                            height=180,
                            disabled=True,
                            key=f"processing_candidate_text_{current_row.digital_object_id}_{page}_{candidate.run_id}",
                        )

                    if comparison.unified_text_diff:
                        with st.expander("Ver diferencias línea por línea"):
                            st.code(comparison.unified_text_diff, language="diff")

                    if assessment.code == ADOPTION_MANUAL:
                        st.warning(assessment.title)
                        st.caption(" · ".join(assessment.blocking_reasons))
                    elif assessment.code == ADOPTION_ALREADY:
                        st.success(assessment.title)
                    else:
                        st.info(assessment.title)

                    note = st.text_input(
                        "Nota opcional",
                        placeholder="Motivo de la decisión",
                        key=f"processing_candidate_note_{current_row.digital_object_id}_{page}_{run_id}",
                    )
                    action_cols = st.columns(2)
                    select_disabled = candidate.is_selected
                    if action_cols[0].button(
                        "Elegir esta extracción",
                        disabled=select_disabled,
                        use_container_width=True,
                        help=(
                            "La edición existente se conserva. Si fue creada desde otra extracción, "
                            "quedará señalada como desactualizada."
                        ),
                    ):
                        engine = create_sqlite_engine(db_path)
                        try:
                            with session_scope(engine) as session:
                                _run, changed = select_extraction_pages(
                                    session,
                                    source_key=source_key,
                                    digital_object_id=current_row.digital_object_id,
                                    selected_by=actor or "local_user",
                                    run_id=run_id,
                                    pages={page},
                                    note=note,
                                )
                        except (ValueError, RuntimeError, OSError) as exc:
                            st.error(str(exc))
                        else:
                            st.session_state["processing_flash"] = (
                                f"Página {page}: extracción elegida actualizada ({changed} cambio). "
                                "La edición existente se conservó."
                            )
                            request_tab(
                                st, key="processing_tabs", label=_SELECTION_TAB_LABEL
                            )
                            rerun_view(st)
                        finally:
                            engine.dispose()

                    if assessment.code == ADOPTION_NOT_INITIALIZED:
                        adopt_label = "Enviar a Revisar documentos"
                    else:
                        adopt_label = "Actualizar en Revisar documentos"
                    if action_cols[1].button(
                        adopt_label,
                        type="primary",
                        disabled=not assessment.can_adopt,
                        use_container_width=True,
                        help=(
                            assessment.explanation
                            if assessment.can_adopt
                            else "La aplicación no reemplazará automáticamente trabajo revisado."
                        ),
                    ):
                        engine = create_sqlite_engine(db_path)
                        try:
                            with session_scope(engine) as session:
                                result = adopt_candidate_page(
                                    session,
                                    decisions=decisions,
                                    source_key=source_key,
                                    digital_object_id=current_row.digital_object_id,
                                    page=page,
                                    candidate_run_id=run_id,
                                    adopted_by=actor or "local_user",
                                    note=note,
                                )
                        except (ValueError, RuntimeError, OSError) as exc:
                            st.error(str(exc))
                        else:
                            st.session_state["processing_flash"] = (
                                f"Página {page}: extracción aplicada. "
                                f"Textos activos: {result.objects_activated}; "
                                f"textos anteriores conservados en el historial: {result.objects_retired}."
                            )
                            request_tab(
                                st, key="processing_tabs", label=_SELECTION_TAB_LABEL
                            )
                            rerun_view(st)
                        finally:
                            engine.dispose()

                    if assessment.code == ADOPTION_MANUAL:
                        manual_path = st.radio(
                            "Edición existente",
                            options=["none", "keep", "rebase"],
                            format_func=lambda value: {
                                "none": "Elegir cómo continuar",
                                "keep": "Mantener la edición actual",
                                "rebase": "Trasladar la edición a la extracción comparada",
                            }[value],
                            horizontal=True,
                            key=f"processing_manual_path_{current_row.digital_object_id}_{page}_{run_id}",
                        )
                        if manual_path == "keep":
                            st.text_area(
                                "Edición que se conservará",
                                value=comparison.editable_text or "",
                                height=220,
                                disabled=True,
                                key=(
                                    f"processing_editable_text_{current_row.digital_object_id}_{page}_"
                                    f"{comparison.editable_status}"
                                ),
                            )
                            with st.form(
                                f"processing_keep_edits_commit_{current_row.digital_object_id}_{page}_{run_id}",
                                enter_to_submit=False,
                            ):
                                keep_confirmed = st.checkbox(
                                    "Confirmo que deseo conservar íntegramente la edición actual",
                                    key=f"processing_keep_edits_confirm_{current_row.digital_object_id}_{page}_{run_id}",
                                )
                                keep_submitted = st.form_submit_button(
                                    "Conservar la edición y vincularla con esta extracción",
                                    type="primary",
                                    use_container_width=True,
                                )
                            if keep_submitted and not keep_confirmed:
                                st.error(
                                    "Marcá la confirmación dentro del formulario antes de conservar la edición."
                                )
                            elif keep_submitted:
                                engine = create_sqlite_engine(db_path)
                                try:
                                    with session_scope(engine) as session:
                                        result = resolve_candidate_keep_edits(
                                            session,
                                            source_key=source_key,
                                            digital_object_id=current_row.digital_object_id,
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
                                        f"{result.retained_objects} fragmentos de texto editables. "
                                        "La decisión quedó registrada en el historial."
                                    )
                                    request_tab(st, key="processing_tabs", label=_SELECTION_TAB_LABEL)
                                    rerun_view(st)
                                finally:
                                    engine.dispose()

                        if manual_path == "rebase":
                            engine = create_sqlite_engine(db_path)
                            try:
                                with session_scope(engine) as session:
                                    rebase_preview = preview_editable_rebase(
                                        session,
                                        source_key=source_key,
                                        digital_object_id=current_row.digital_object_id,
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
                                        "Hay correcciones revisadas que se superponen con cambios "
                                        "distintos de la extracción nueva. Cada tramo debe resolverse "
                                        "explícitamente antes de trasladar la edición."
                                    )
                                    for conflict in rebase_preview.text_conflicts:
                                        key_base = (
                                            f"processing_rebase_text_{current_row.digital_object_id}_{page}_"
                                            f"{run_id}_{conflict.conflict_id}"
                                        )
                                        with st.container(border=True):
                                            st.write(f"**Conflicto textual** · `{conflict.conflict_id}`")
                                            st.caption(conflict.reason)
                                            columns = st.columns(3)
                                            columns[0].write("**Base anterior**")
                                            columns[0].code(conflict.base_text or "[vacío]")
                                            columns[1].write("**Corrección revisada**")
                                            columns[1].code(conflict.human_text or "[vacío]")
                                            columns[2].write("**Extracción nueva**")
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
                                                    "candidate": "Conservar la lectura de la extracción nueva",
                                                    "human": "Reaplicar la corrección revisada",
                                                    "manual": "Escribir manualmente el texto",
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
                                                    "mostrado en la columna Extracción nueva."
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
                                                digital_object_id=current_row.digital_object_id,
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
                                        "Hay fragmentos de texto con anotaciones o datos adicionales cuya correspondencia con el texto de la extracción nueva no es suficientemente segura. Elegí explícitamente qué fragmento nuevo debe recibir esa información."
                                    )
                                    for conflict in rebase_preview.projection_conflicts:
                                        key_base = (
                                            f"processing_rebase_projection_{current_row.digital_object_id}_{page}_"
                                            f"{run_id}_{conflict.conflict_id}"
                                        )
                                        with st.container(border=True):
                                            st.write(
                                                f"**Destino para las anotaciones del fragmento de texto "
                                                f"{conflict.source_order_index + 1}**"
                                            )
                                            st.caption(conflict.reason)
                                            st.code(conflict.source_text[:700] or "[fragmento de texto vacío]")
                                            options = ["pending", *range(len(conflict.candidates))]
                                            selected_projection = st.selectbox(
                                                "Fragmento del texto nuevo que recibirá sus anotaciones y datos adicionales",
                                                options=options,
                                                format_func=lambda value, candidates=conflict.candidates: (
                                                    "Pendiente de resolución"
                                                    if value == "pending"
                                                    else (
                                                        f"Fragmento {candidates[value].order_index + 1} · "
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
                                                digital_object_id=current_row.digital_object_id,
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
                                        "Algunas menciones de entidades no pueden trasladarse automáticamente al texto nuevo. Acá decidís a qué fragmento deben quedar vinculadas o si una mención duplicada debe rechazarse. La ficha de la entidad y sus relaciones no cambian."
                                    )
                                    for conflict in rebase_preview.mention_conflicts:
                                        key_base = (
                                            f"processing_rebase_mention_{current_row.digital_object_id}_{page}_"
                                            f"{run_id}_{conflict.mention_id}"
                                        )
                                        with st.container(border=True):
                                            authority_label = (
                                                conflict.authority_name
                                                or conflict.authority_id
                                                or "sin entidad vinculada"
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
                                                    f"Fragmento {block_order} · "
                                                    f"{candidate_option.method} · "
                                                    f"«{candidate_option.matched_text}» · "
                                                    f"{candidate_option.context}"
                                                )
                                            option_values.extend(["manual", "reject"])
                                            choice = st.selectbox(
                                                "Cómo trasladar este dato al texto nuevo",
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
                                                        "Fragmento del texto nuevo",
                                                        options=block_options,
                                                        index=block_options.index(default_block),
                                                        format_func=lambda value: (
                                                            f"Fragmento "
                                                            f"{rebase_preview.candidate_objects[value].order_index + 1} · "
                                                            f"{rebase_preview.candidate_objects[value].rebased_text[:120]}"
                                                        ),
                                                        key=f"{key_base}_manual_block",
                                                    )
                                                    manual_text = st.text_input(
                                                        "Fragmento exacto dentro del texto",
                                                        value=conflict.mention_text,
                                                        key=f"{key_base}_manual_text",
                                                    )
                                                    manual_occurrence = st.number_input(
                                                        "Qué aparición del fragmento querés usar",
                                                        min_value=1,
                                                        value=1,
                                                        step=1,
                                                        help=(
                                                            "Usá 2, 3, etc. cuando el mismo fragmento "
                                                            "aparece varias veces en ese texto."
                                                        ),
                                                        key=f"{key_base}_manual_occurrence",
                                                    )
                                                    manual_submitted = st.form_submit_button(
                                                        "Confirmar este fragmento como nueva ubicación"
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
                                                            "Ese fragmento no aparece en el texto elegido. "
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
                                                    "Confirmo que esta mención duplicada debe quedar rechazada; "
                                                    "la ficha de la entidad y sus relaciones se conservarán",
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
                                                digital_object_id=current_row.digital_object_id,
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
                                        "Hay datos adicionales incompatibles porque varios fragmentos anteriores convergen en un mismo fragmento del texto nuevo. Elegí explícitamente qué valor debe conservarse."
                                    )
                                    for conflict in rebase_preview.metadata_conflicts:
                                        key_base = (
                                            f"processing_rebase_metadata_{current_row.digital_object_id}_{page}_"
                                            f"{run_id}_{conflict.conflict_id}"
                                        )
                                        block = rebase_preview.candidate_objects[conflict.target_index]
                                        with st.container(border=True):
                                            kind_label = {
                                                "document_part": "Parte documental",
                                                "review_status": "Estado de revisión",
                                                "object_type": "Tipo de fragmento de texto",
                                            }.get(conflict.kind, conflict.kind)
                                            st.write(
                                                f"**{kind_label}** · fragmento {block.order_index + 1}"
                                            )
                                            st.caption(conflict.reason)
                                            st.code(block.rebased_text[:600] or "[fragmento vacío]")
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
                                                digital_object_id=current_row.digital_object_id,
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
                                            f"processing_rebase_attribute_{current_row.digital_object_id}_{page}_"
                                            f"{run_id}_{conflict.conflict_id}"
                                        )
                                        block = rebase_preview.candidate_objects[
                                            conflict.target_index
                                        ]
                                        with st.container(border=True):
                                            st.write(
                                                f"**Atributo `{conflict.attribute_key}`** · "
                                                f"fragmento {block.order_index + 1}"
                                            )
                                            st.caption(conflict.reason)
                                            st.code(block.rebased_text[:600] or "[fragmento vacío]")
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
                                                        "Valor técnico exacto que querés conservar (JSON)",
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
                                                        "Confirmar este valor técnico"
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
                                                digital_object_id=current_row.digital_object_id,
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
                                    "Fragmentos de texto editables", rebase_preview.old_object_count
                                )
                                rebase_metrics[1].metric(
                                    "Fragmentos del texto nuevo", rebase_preview.new_object_count
                                )
                                rebase_metrics[2].metric(
                                    "Cambios manuales", rebase_preview.human_change_count
                                )
                                rebase_metrics[3].metric(
                                    "Menciones de entidades", rebase_preview.mention_count
                                )
                                st.caption(
                                    f"También se trasladarán {rebase_preview.comment_count} comentarios, "
                                    f"{rebase_preview.tag_count} etiquetas y "
                                    f"{rebase_preview.document_part_count} asignaciones a partes documentales."
                                )
                                if rebase_preview.structural_action_count:
                                    st.info(
                                        f"La página tiene {rebase_preview.structural_action_count} acciones "
                                        "estructurales históricas. El traslado usa el estado activo actual como "
                                        "fuente de verdad; el historial se conserva y ya no bloquea por sí solo."
                                    )
                                if rebase_preview.conflicts:
                                    st.error(
                                        "El traslado de la edición sigue bloqueado por incompatibilidades estructurales:"
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
                                        "Todavía quedan fragmentos de texto con anotaciones cuyo destino en el texto nuevo no fue confirmado:"
                                    )
                                    for conflict in rebase_preview.projection_conflicts:
                                        st.write(
                                            f"• Fragmento de texto {conflict.source_order_index + 1}: "
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
                                            f"• Fragmento {rebase_preview.candidate_objects[conflict.target_index].order_index + 1}: "
                                            f"{conflict.reason}"
                                        )
                                if rebase_preview.attribute_conflicts:
                                    st.error(
                                        "Todavía quedan atributos especializados sin una resolución válida:"
                                    )
                                    for conflict in rebase_preview.attribute_conflicts:
                                        st.write(
                                            f"• Fragmento {rebase_preview.candidate_objects[conflict.target_index].order_index + 1}, "
                                            f"`{conflict.attribute_key}`: {conflict.reason}"
                                        )
                                if rebase_preview.can_apply:
                                    st.success(
                                        "La vista previa no detectó pérdidas ni ambigüedades pendientes. "
                                        "La operación será transaccional y conservará el historial anterior."
                                    )
                                if rebase_preview.unified_text_diff:
                                    with st.expander("Ver correcciones revisadas trasladadas"):
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
                                    f"processing_rebase_commit_{current_row.digital_object_id}_{page}_{run_id}",
                                    enter_to_submit=False,
                                ):
                                    rebase_confirmed = st.checkbox(
                                        "Confirmo que revisé la vista previa y deseo trasladar la edición a la extracción nueva",
                                        disabled=not rebase_preview.can_apply,
                                        key=f"processing_rebase_confirm_{current_row.digital_object_id}_{page}_{run_id}",
                                    )
                                    rebase_submitted = st.form_submit_button(
                                        "Aplicar el traslado y usar la extracción nueva",
                                        type="primary",
                                        disabled=not rebase_preview.can_apply,
                                        use_container_width=True,
                                    )
                                if rebase_submitted and not rebase_confirmed:
                                    st.error(
                                        "Marcá la confirmación dentro del formulario antes de trasladar la edición."
                                    )
                                elif rebase_submitted:
                                    engine = create_sqlite_engine(db_path)
                                    try:
                                        with session_scope(engine) as session:
                                            result = apply_editable_rebase(
                                                session,
                                                decisions=decisions,
                                                source_key=source_key,
                                                digital_object_id=current_row.digital_object_id,
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
                                            f"Página {page}: edición trasladada a la extracción nueva. "
                                            f"Se crearon {result.new_objects_created} fragmentos de texto, "
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
                                            label=_SELECTION_TAB_LABEL,
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


    with regional_integration_tab:
        _render_regional_review_integration(
            st,
            project_root=project_root,
            db_path=db_path,
            decisions=decisions,
            inventory=inventory,
            actor=actor,
        )

    with bulk_review_tab:
        _render_bulk_review_sender(
            st,
            db_path=db_path,
            decisions=decisions,
            inventory=inventory,
            actor=actor,
        )

    with history_tab:
        history_document_labels = {}
        for row in inventory:
            history_document_labels.setdefault(row.source_key, row.title)
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
                st.caption(
                    f"{job.total_items} documento(s) · {job.completed_items} completados · "
                    f"{job.warning_items} con advertencias · {job.failed_items} fallidos"
                )
                engine = create_sqlite_engine(db_path)
                try:
                    with session_scope(engine) as session:
                        items = processing_job_item_rows(session, job_id=job.job_id)
                finally:
                    engine.dispose()
                st.dataframe(
                    [
                        {
                            "Documento": history_document_labels.get(item.source_key, item.source_key),
                            "Estado": _JOB_STATUS_LABELS.get(item.status, item.status),
                            "Páginas": ", ".join(map(str, item.pages)),
                            "Mensaje": (
                                "No se pudo extraer texto porque el documento todavía no tenía imágenes preparadas."
                                if item.status == "failed"
                                and any(
                                    "no tiene una corrida de preprocesamiento vigente" in str(warning)
                                    for warning in (item.detail.get("warnings") or [])
                                )
                                else item.message
                            ),
                        }
                        for item in items
                    ],
                    use_container_width=True,
                    hide_index=True,
                )
                technical = {
                    "parametros": job.parameters or {},
                    "detalles_por_documento": {
                        item.source_key: item.detail for item in items if item.detail
                    },
                }
                if technical["parametros"] or technical["detalles_por_documento"]:
                    st.json(technical, expanded=False)
