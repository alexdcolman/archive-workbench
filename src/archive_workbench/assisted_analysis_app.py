from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from archive_workbench.ai_execution import (
    AIExecutionError,
    ai_authorization_parameters,
    inspect_ai_capabilities,
    resolve_ai_executable,
    run_ai_analysis,
)
from archive_workbench.ai_handoff import (
    AIHandoffError,
    inspect_ai_handoff_bytes,
    resolve_ai_handoff,
)
from archive_workbench.analysis_audit import record_automatic_analysis_authorization
from archive_workbench.analysis_quality import analysis_quality_scope, quality_scope_caption
from archive_workbench.corpus_export import (
    export_page_candidates,
    export_profile_rows,
    export_unit_scope_candidates,
    run_export,
)
from archive_workbench.db import create_sqlite_engine, session_scope
from archive_workbench.external_analysis import (
    ExternalAnalysisError,
    ExternalAnalysisHistoryRow,
    ExternalAnalysisProposalSummary,
    external_analysis_history_rows,
    external_analysis_package_rows,
    external_analysis_proposal_detail,
    external_analysis_proposal_summaries,
    incorporate_ai_handoff,
    read_external_analysis_proposal_asset,
    review_external_analysis_proposal,
    set_external_analysis_current_review,
)
from archive_workbench.identity import new_id
from archive_workbench.review import review_page_view
from archive_workbench.review_canvas import static_image_canvas_bytes
from archive_workbench.ui_help import TAB_HELP
from archive_workbench.visual_export import VisualExportOptions
from archive_workbench.ui_navigation import (
    request_app_view,
    request_tab,
    rerun_app,
    rerun_view,
    section_heading,
    tracked_tabs,
)

_TAB_KEY = "assisted_analysis_tabs"
_PROPOSAL_SELECTION_KEY = "assisted_analysis_proposal_id"
_PROPOSAL_PENDING_KEY = "assisted_analysis_proposal_pending"
_HISTORY_SELECTION_KEY = "assisted_analysis_history_review_id"
_HISTORY_PENDING_KEY = "assisted_analysis_history_pending"
_DOCUMENT_SELECTION_KEY = "assisted_analysis_document_review_id"
_DOCUMENT_PENDING_KEY = "assisted_analysis_document_pending"
_PAGE_SIZE = 25

_STATUS_LABELS = {
    "pending": "Pendiente",
    "accepted": "Aceptada",
    "rejected": "Rechazada",
}


_ANALYSIS_TYPE_LABELS = {
    "vision_describe/0.1": "Descripción visual",
}


_MODEL_LABELS = {
    "ggml-org/gemma-4-26B-A4B-it-GGUF:Q4_0": "Gemma 4 26B",
    "unsloth/Qwen3.5-9B-GGUF:Q4_K_M": "Qwen 3.5 9B",
}


def _model_label(value: str | None) -> str:
    if not value:
        return "Modelo no informado"
    return _MODEL_LABELS.get(value, "Otro modelo")


def _analysis_type_label(value: str | None) -> str:
    if not value:
        return "No informado"
    return _ANALYSIS_TYPE_LABELS.get(value, "Otro tipo de análisis")


def _friendly_ai_error(error: Exception) -> str:
    detail = str(error)
    lowered = detail.casefold()
    if "no está disponible" in lowered or "no existe" in lowered or "no es ejecutable" in lowered:
        return (
            "El módulo de análisis asistido no está disponible en esta computadora. "
            "Revisá su instalación antes de volver a intentar."
        )
    if any(
        token in lowered
        for token in (
            "protocolo",
            "handoff",
            "workflow",
            "salida consolidada",
            "no declara",
            "versión del resultado",
        )
    ):
        return (
            "La versión instalada del módulo de análisis no es compatible con esta "
            "versión de Archive Workbench."
        )
    if "terminó con código" in lowered or "no se pudo ejecutar" in lowered:
        return "El análisis se interrumpió antes de terminar. Podés volver a intentarlo."
    if "no produjo" in lowered:
        return "El análisis terminó sin generar un resultado que Archive Workbench pueda abrir."
    if "no puede vincularse" in lowered or "no pudo relacionarse" in lowered:
        return (
            "El resultado no pudo relacionarse de forma segura con las páginas analizadas. "
            "No se incorporó ninguna propuesta."
        )
    return "No se pudo completar el análisis. No se incorporó ninguna propuesta."


def _friendly_handoff_error() -> str:
    return (
        "No se pudo abrir este resultado. El archivo puede estar incompleto, modificado "
        "o creado con una versión no compatible."
    )


def _render_diagnostic_detail(st, detail: str) -> None:
    if not detail.strip():
        return
    with st.expander("Detalles para diagnóstico", expanded=False):
        st.caption(detail)


def _format_datetime(value) -> str:
    if value is None:
        return "-"
    try:
        return value.astimezone().strftime("%Y-%m-%d %H:%M")
    except (AttributeError, ValueError):
        return str(value)


def _join_lines(value: object) -> str:
    if not isinstance(value, list):
        return ""
    return "\n".join(str(item) for item in value if isinstance(item, str))


def _split_lines(value: str) -> list[str]:
    return [line.strip() for line in value.splitlines() if line.strip()]


def _output_text_blob(output: dict[str, Any] | None) -> str:
    if not isinstance(output, dict):
        return ""
    values: list[str] = []
    for value in output.values():
        if isinstance(value, str):
            values.append(value)
        elif isinstance(value, list):
            values.extend(str(item) for item in value if isinstance(item, str))
    return " ".join(values)


def _render_output(st, output: dict[str, Any] | None, *, title: str | None = None) -> None:
    if title:
        st.subheader(title)
    if not isinstance(output, dict):
        st.caption("No hay una versión de contenido para mostrar.")
        return
    description = output.get("description")
    if isinstance(description, str) and description.strip():
        st.write(description.strip())
    for field, label in (
        ("document_features", "Rasgos documentales"),
        ("visible_text_notes", "Notas visuales sobre texto"),
    ):
        values = output.get(field)
        if isinstance(values, list) and values:
            st.write(f"**{label}**")
            for value in values:
                if isinstance(value, str) and value.strip():
                    st.write(f"• {value.strip()}")
    uncertainties = output.get("uncertainties")
    if isinstance(uncertainties, list) and uncertainties:
        text = "\n".join(f"• {value}" for value in uncertainties if isinstance(value, str))
        if text:
            st.warning("Incertidumbres declaradas por el análisis:\n\n" + text)


def _render_exact_asset(st, *, asset, page: int, key: str) -> None:
    shown = static_image_canvas_bytes(
        asset.payload,
        mime_type=asset.mime_type,
        page=page,
        key=key,
    )
    if not shown:
        st.image(asset.payload, use_container_width=True)
    st.caption("Imagen utilizada para generar esta propuesta.")


def _load_surface_rows(db_path: Path, *, project_id: str):
    engine = create_sqlite_engine(db_path)
    try:
        with session_scope(engine) as session:
            packages = external_analysis_package_rows(session, project_id=project_id)
            proposals = external_analysis_proposal_summaries(session, project_id=project_id)
            history = external_analysis_history_rows(session, project_id=project_id)
    finally:
        engine.dispose()
    return packages, proposals, history


def _proposal_label(row: ExternalAnalysisProposalSummary) -> str:
    name = row.original_filename or row.source_key or row.digital_object_id
    model = _model_label(row.model_id or row.producer_id)
    return f"{name} · página {row.page_number} · {_STATUS_LABELS.get(row.status, row.status)} · {model}"


def _history_label(row: ExternalAnalysisHistoryRow) -> str:
    name = row.original_filename or row.source_key or row.digital_object_id
    current = " · vigente" if row.is_current else ""
    return (
        f"{name} · página {row.page_number} · "
        f"{_STATUS_LABELS.get(row.decision, row.decision)} · revisión {row.revision}{current}"
    )


def _apply_pending_selection(st, *, state_key: str, pending_key: str, valid_ids: set[str]) -> None:
    pending = st.session_state.pop(pending_key, None)
    if pending in valid_ids:
        st.session_state[state_key] = pending


def _paginate(st, rows: list[Any], *, key: str) -> list[Any]:
    if len(rows) <= _PAGE_SIZE:
        return rows
    page_count = (len(rows) + _PAGE_SIZE - 1) // _PAGE_SIZE
    page = st.selectbox(
        "Página de resultados",
        options=list(range(1, page_count + 1)),
        format_func=lambda value: f"{value} de {page_count}",
        key=key,
    )
    start = (int(page) - 1) * _PAGE_SIZE
    return rows[start : start + _PAGE_SIZE]


def _navigate_to_document(st, row, *, mode: str) -> None:
    source_key = row.navigation_source_key
    if not source_key:
        st.error("No se pudo resolver una ruta de navegación documental para esta página.")
        return
    request_app_view(
        st,
        mode=mode,
        source_key=source_key,
        page=row.page_number,
    )
    rerun_app(st)


def request_assisted_analysis_document(st, *, review_id: str) -> None:
    """Abre la revisión vigente pedida sin convertir la pestaña visual en estado semántico."""

    st.session_state[_DOCUMENT_PENDING_KEY] = str(review_id)
    request_tab(st, key=_TAB_KEY, label="Documentos con análisis")
    request_app_view(st, mode="assisted_analysis")
    rerun_app(st)


def _current_page_preview_path(
    session,
    *,
    project_root: Path,
    source_key: str | None,
    page_number: int,
) -> Path | None:
    if not source_key:
        return None
    try:
        view = review_page_view(
            session,
            project_root=project_root,
            source_key=source_key,
            page=page_number,
            include_deleted=False,
        )
    except (OSError, ValueError):
        return None
    return view.preview_path if view.preview_path and view.preview_path.is_file() else None


def _render_current_page_fallback(st, *, preview_path: Path | None) -> None:
    if preview_path is None:
        return
    st.image(str(preview_path), use_container_width=True)
    st.caption(
        "Página actual del proyecto. No se pudo comprobar automáticamente que sea "
        "exactamente la misma imagen utilizada durante el análisis."
    )


def _inspect_uploaded_handoff_cached(
    st,
    *,
    payload: bytes,
    project_root: Path,
    db_path: Path,
    project_id: str,
):
    digest = hashlib.sha256(payload).hexdigest()
    cache = st.session_state.get("assisted_analysis_upload_cache")
    if isinstance(cache, dict) and cache.get("sha256") == digest:
        return cache["preview"], cache["resolution"]
    preview = inspect_ai_handoff_bytes(payload)
    engine = create_sqlite_engine(db_path)
    try:
        with session_scope(engine) as session:
            resolution = resolve_ai_handoff(
                session,
                project_root=project_root,
                project_id=project_id,
                preview=preview,
            )
    finally:
        engine.dispose()
    st.session_state["assisted_analysis_upload_cache"] = {
        "sha256": digest,
        "preview": preview,
        "resolution": resolution,
    }
    return preview, resolution


def _render_handoff_preview(
    st,
    *,
    payload: bytes,
    cache_key: str,
    project_root: Path,
    db_path: Path,
    project_id: str,
    actor: str,
) -> None:
    try:
        preview, resolution = _inspect_uploaded_handoff_cached(
            st,
            payload=payload,
            project_root=project_root,
            db_path=db_path,
            project_id=project_id,
        )
    except (AIHandoffError, OSError, ValueError) as exc:
        st.error(_friendly_handoff_error())
        _render_diagnostic_detail(st, str(exc))
        return

    resolved = sum(item.acceptance_ready for item in resolution.proposal_resolutions)
    unresolved = preview.proposal_count - resolved
    source_matches = len(resolution.source_matches)
    summary = st.columns(3)
    summary[0].metric("Propuestas recibidas", preview.proposal_count)
    summary[1].metric("Páginas verificadas", resolved)
    summary[2].metric("Propuestas sin página", unresolved)
    warning_count = sum(bool(item.warnings) for item in preview.proposals)
    if warning_count:
        st.warning(
            f"{warning_count} propuesta(s) contienen advertencias del modelo que deben "
            "revisarse individualmente."
        )
    if resolution.blocking_reasons:
        st.warning(
            "Algunas propuestas no pueden incorporarse porque Archive Workbench no pudo "
            "relacionarlas con las páginas de origen."
        )
    elif source_matches > 1:
        st.info(
            "Se encontró más de una copia de los mismos materiales. Archive Workbench "
            "comprobó las coincidencias y puede continuar."
        )
    with st.expander("Detalles técnicos", expanded=False):
        st.write(f"Modelo: `{preview.model_id or 'No informado'}`")
        st.write(
            f"Origen: `{preview.producer_id or 'No informado'} "
            f"{preview.producer_version or ''}`".rstrip()
        )
        if preview.created_at:
            st.write(f"Fecha declarada: `{preview.created_at}`")
        st.write(f"Schema: `{preview.schema_version}`")
        st.write(f"Protocolo: `{preview.protocol}`")
        st.write(f"SHA-256 del handoff: `{preview.sha256}`")
        st.write(f"SHA-256 EXP-01: `{preview.exp01_sha256}`")
        st.write(f"SHA-256 result bundle: `{preview.result_bundle_sha256}`")
        if preview.request_id:
            st.write(f"Request: `{preview.request_id}`")
        if preview.runtime:
            st.write("Runtime")
            st.json(preview.runtime)
        if preview.prompt:
            st.write("Prompt")
            st.json(preview.prompt)
    if st.button(
        "Incorporar propuestas para revisión",
        type="primary",
        disabled=not resolution.incorporation_allowed,
        key=f"assisted_analysis_incorporate_{cache_key}",
    ):
        try:
            engine = create_sqlite_engine(db_path)
            try:
                with session_scope(engine) as session:
                    fresh_preview = inspect_ai_handoff_bytes(payload)
                    fresh_resolution = resolve_ai_handoff(
                        session,
                        project_root=project_root,
                        project_id=project_id,
                        preview=fresh_preview,
                    )
                    result = incorporate_ai_handoff(
                        session,
                        project_id=project_id,
                        preview=fresh_preview,
                        resolution=fresh_resolution,
                        imported_by=actor or "local_user",
                    )
            finally:
                engine.dispose()
        except (ExternalAnalysisError, ValueError, OSError) as exc:
            st.error("No se pudieron incorporar las propuestas. No se modificó ninguna decisión.")
            _render_diagnostic_detail(st, str(exc))
        else:
            st.session_state["assisted_analysis_notice"] = (
                "Propuestas incorporadas para revisión."
                if result.created
                else "Este resultado ya había sido incorporado; no se duplicó."
            )
            request_tab(st, key=_TAB_KEY, label="Revisar propuestas")
            rerun_view(st)


def _load_ai_export_scope(db_path: Path, *, project_id: str, profile_id: str, scope_kind: str):
    engine = create_sqlite_engine(db_path)
    try:
        with session_scope(engine) as session:
            profiles = export_profile_rows(session, project_id=project_id)
            profile = next((row for row in profiles if row.id == profile_id), None)
            if profile is None:
                return None, [], []
            units = (
                export_unit_scope_candidates(session, project_id=project_id, profile=profile)
                if scope_kind == "archival_units"
                else []
            )
            pages = (
                export_page_candidates(session, project_id=project_id, profile=profile)
                if scope_kind == "explicit_pages"
                else []
            )
            return profile, units, pages
    finally:
        engine.dispose()


def _render_ai_execution(
    st,
    *,
    project_root: Path,
    db_path: Path,
    project_id: str,
    actor: str,
) -> None:
    st.subheader("Analizar documentos con inteligencia artificial")
    st.caption(
        "Elegí qué páginas querés analizar. El resultado se mostrará como una propuesta "
        "para revisar antes de incorporarla al proyecto."
    )
    try:
        executable = resolve_ai_executable()
    except AIExecutionError as exc:
        st.info(_friendly_ai_error(exc))
        _render_diagnostic_detail(st, str(exc))
        return

    engine = create_sqlite_engine(db_path)
    try:
        with session_scope(engine) as session:
            profiles = export_profile_rows(session, project_id=project_id)
            profile_options = [(row.id, row.name, row.revision) for row in profiles]
    finally:
        engine.dispose()
    if not profile_options:
        st.info("Creá primero una configuración activa en Exportar corpus.")
        return

    profile_ids = [row[0] for row in profile_options]
    profile_labels = {row[0]: row[1] for row in profile_options}
    profile_id = st.selectbox(
        "Configuración de exportación",
        options=profile_ids,
        format_func=lambda value: profile_labels[value],
        key="assisted_analysis_ai01_export_profile",
    )
    scope_kind = st.radio(
        "Qué querés analizar",
        options=("profile_scope", "archival_units", "explicit_pages"),
        format_func=lambda value: {
            "profile_scope": "Todo lo incluido en la configuración",
            "archival_units": "Fondos, legajos o documentos seleccionados",
            "explicit_pages": "Páginas específicas",
        }[value],
        key="assisted_analysis_ai01_scope_kind",
    )
    profile, units, pages = _load_ai_export_scope(
        db_path,
        project_id=project_id,
        profile_id=profile_id,
        scope_kind=scope_kind,
    )
    if profile is None:
        st.warning("La configuración elegida ya no está disponible.")
        return

    selected_unit_ids: list[str] = []
    selected_page_keys: list[tuple[str, int]] = []
    if scope_kind == "archival_units":
        by_id = {row.archival_unit_id: row for row in units}
        selected_unit_ids = st.multiselect(
            "Fondos, legajos o documentos",
            options=list(by_id),
            format_func=lambda value: by_id[value].label,
            key="assisted_analysis_ai01_unit_ids",
        )
        if not units:
            st.info("No hay unidades archivísticas elegibles dentro de esta configuración.")
    elif scope_kind == "explicit_pages":
        by_key = {(row.digital_object_id, row.page_number): row for row in pages}
        selected_page_keys = st.multiselect(
            "Páginas",
            options=list(by_key),
            format_func=lambda value: by_key[value].label,
            key="assisted_analysis_ai01_page_keys",
        )
        if not pages:
            st.info("No hay páginas elegibles dentro de esta configuración.")

    quality_statuses = tuple(profile.include_page_review_statuses_json or [])
    quality_scope = analysis_quality_scope(quality_statuses)
    if quality_scope.is_default:
        st.info(quality_scope_caption(quality_statuses))
    else:
        st.warning(quality_scope_caption(quality_statuses))

    with st.form("assisted_analysis_ai01_execute_form", enter_to_submit=False):
        hardware_profile = st.radio(
            "Tipo de equipo",
            options=("H24", "L12"),
            format_func=lambda value: {
                "H24": "GPU NVIDIA con 24 GB de memoria",
                "L12": "GPU NVIDIA con 12 GB de memoria",
            }[value],
            horizontal=True,
        )
        broader_confirmed = False
        quality_reason = None
        if quality_scope.is_broader_than_default:
            broader_confirmed = st.checkbox(
                "Confirmo que este análisis puede incluir páginas que todavía no están aprobadas"
            )
            quality_reason = st.text_area(
                "Motivo para incluir estas páginas",
                help="El motivo queda registrado junto con esta ejecución.",
            )
        submitted = st.form_submit_button(
            "Iniciar análisis",
            type="primary",
        )
    if not submitted:
        return
    if scope_kind == "archival_units" and not selected_unit_ids:
        st.error("Elegí al menos un fondo, legajo o documento.")
        return
    if scope_kind == "explicit_pages" and not selected_page_keys:
        st.error("Elegí al menos una página.")
        return

    planned_run_id = new_id()
    exp01_relative = f"exports/ai01/{planned_run_id}_EXP01.zip"
    handoff_relative = f"exports/ai01/{planned_run_id}_HANDOFF.zip"
    result_relative = f"exports/ai01/{planned_run_id}_RESULT.zip"
    try:
        capabilities = inspect_ai_capabilities(executable)
        model_id = capabilities.model_for_profile(hardware_profile)
        parameters = ai_authorization_parameters(
            capabilities=capabilities,
            hardware_profile=hardware_profile,
            model_id=model_id,
            export_profile_id=profile.id,
            export_profile_revision=profile.revision,
            scope_kind=scope_kind,
            selected_unit_ids=tuple(sorted(selected_unit_ids)),
            selected_page_keys=tuple(sorted(selected_page_keys)),
        )
        engine = create_sqlite_engine(db_path)
        try:
            with session_scope(engine) as session:
                fresh_profiles = export_profile_rows(session, project_id=project_id)
                fresh_profile = next((row for row in fresh_profiles if row.id == profile.id), None)
                if fresh_profile is None:
                    raise ValueError("La configuración elegida ya no está activa.")
                if fresh_profile.revision != profile.revision:
                    raise ValueError(
                        "La configuración cambió desde que se abrió esta vista. "
                        "Revisala antes de iniciar el análisis."
                    )
                record_automatic_analysis_authorization(
                    session,
                    project_id=project_id,
                    analysis_kind="llm_tool",
                    page_review_statuses=quality_statuses,
                    broader_scope_confirmed=broader_confirmed,
                    confirmed_by=actor or "local_user",
                    confirmation_reason=quality_reason,
                    source="ui",
                    target_type="corpus_export_run",
                    target_id=planned_run_id,
                    parameters=parameters,
                )
                export_result = run_export(
                    session,
                    project_root=project_root,
                    project_id=project_id,
                    profile=fresh_profile,
                    output_relative_path=exp01_relative,
                    output_format="visual_zip",
                    created_by=actor or "local_user",
                    selected_page_keys=(
                        set(selected_page_keys) if scope_kind == "explicit_pages" else None
                    ),
                    selected_unit_ids=(
                        set(selected_unit_ids) if scope_kind == "archival_units" else None
                    ),
                    visual_options=VisualExportOptions(
                        include_pages=True,
                        include_regions=False,
                        include_figures=False,
                        include_context=True,
                    ),
                    run_id=planned_run_id,
                )
        finally:
            engine.dispose()

        with st.spinner("Analizando las páginas seleccionadas…"):
            execution = run_ai_analysis(
                capabilities=capabilities,
                input_path=export_result.output_path,
                handoff_output_path=project_root / handoff_relative,
                result_output_path=project_root / result_relative,
                hardware_profile=hardware_profile,
                model_id=model_id,
            )
        handoff_payload = execution.handoff_path.read_bytes()
        generated_preview = inspect_ai_handoff_bytes(handoff_payload)
        engine = create_sqlite_engine(db_path)
        try:
            with session_scope(engine) as session:
                generated_resolution = resolve_ai_handoff(
                    session,
                    project_root=project_root,
                    project_id=project_id,
                    preview=generated_preview,
                )
        finally:
            engine.dispose()
        if generated_resolution.blocking_reasons:
            raise AIExecutionError(
                "El resultado no pudo relacionarse de forma segura con las páginas analizadas."
            )
    except (AIExecutionError, AIHandoffError, ValueError, OSError) as exc:
        if isinstance(exc, AIExecutionError):
            st.error(_friendly_ai_error(exc))
        elif isinstance(exc, ValueError) and any(
            phrase in str(exc)
            for phrase in (
                "La configuración elegida ya no está activa.",
                "La configuración cambió desde que se abrió esta vista.",
                "alcance ampliado",
                "fundamento",
            )
        ):
            st.error(str(exc))
        else:
            st.error("No se pudo completar el análisis. No se incorporó ninguna propuesta.")
        _render_diagnostic_detail(st, str(exc))
        st.caption(
            "Si la preparación del análisis ya había terminado, los archivos creados se "
            "conservaron en el proyecto para poder revisar el problema."
        )
        return

    st.session_state["assisted_analysis_generated_handoff"] = handoff_relative
    st.session_state["assisted_analysis_notice"] = (
        f"El análisis terminó: se generaron {execution.proposal_count} propuesta(s). "
        "Revisalas antes de incorporarlas al proyecto."
    )
    rerun_view(st)


def _render_received_results(
    st,
    *,
    project_root: Path,
    db_path: Path,
    project_id: str,
    actor: str,
    packages,
) -> None:
    _render_ai_execution(
        st,
        project_root=project_root,
        db_path=db_path,
        project_id=project_id,
        actor=actor,
    )

    generated_relative = st.session_state.get("assisted_analysis_generated_handoff")
    if isinstance(generated_relative, str) and generated_relative:
        generated_path = project_root / generated_relative
        st.subheader("Resultado del análisis")
        if generated_path.is_file():
            _render_handoff_preview(
                st,
                payload=generated_path.read_bytes(),
                cache_key="generated",
                project_root=project_root,
                db_path=db_path,
                project_id=project_id,
                actor=actor,
            )
        else:
            st.warning("El resultado generado ya no está disponible.")

    st.subheader("Cargar resultados externos")
    st.caption(
        "Podés cargar un archivo de resultados creado fuera de este proyecto. Archive "
        "Workbench comprobará que corresponda a materiales del proyecto antes de permitir "
        "incorporarlo."
    )
    uploaded = st.file_uploader(
        "Archivo de resultados",
        type=["zip"],
        accept_multiple_files=False,
        key="assisted_analysis_upload",
    )
    if uploaded is not None:
        _render_handoff_preview(
            st,
            payload=uploaded.getvalue(),
            cache_key="uploaded",
            project_root=project_root,
            db_path=db_path,
            project_id=project_id,
            actor=actor,
        )

    st.subheader("Resultados incorporados")
    if not packages:
        st.caption("Todavía no se incorporaron resultados de análisis asistido.")
        return
    st.dataframe(
        [
            {
                "Fecha": _format_datetime(row.imported_at),
                "Propuestas": row.proposal_count,
                "Modelo": _model_label(row.model_id),
                "Responsable": row.imported_by,
            }
            for row in packages[:50]
        ],
        hide_index=True,
        use_container_width=True,
    )


def _render_proposal_review(
    st,
    *,
    project_root: Path,
    db_path: Path,
    project_id: str,
    actor: str,
    proposals: list[ExternalAnalysisProposalSummary],
) -> None:
    st.subheader("Revisar propuestas")
    if not proposals:
        st.info("Todavía no hay propuestas incorporadas para revisar.")
        return
    filter_cols = st.columns([1, 1, 1.6])
    status_filter = filter_cols[0].selectbox(
        "Estado de la propuesta",
        options=["pending", "accepted", "rejected", "all"],
        format_func=lambda value: {
            "pending": "Pendientes",
            "accepted": "Aceptadas",
            "rejected": "Rechazadas",
            "all": "Todos los estados",
        }[value],
        key="assisted_analysis_review_status",
    )
    models = sorted({row.model_id for row in proposals if row.model_id})
    model_filter = filter_cols[1].selectbox(
        "Modelo",
        options=[""] + models,
        format_func=lambda value: "Todos" if not value else _model_label(value),
        key="assisted_analysis_review_model",
    )
    search_text = (
        filter_cols[2]
        .text_input(
            "Documento o archivo",
            key="assisted_analysis_review_search",
        )
        .strip()
        .casefold()
    )
    filtered = [
        row
        for row in proposals
        if (status_filter == "all" or row.status == status_filter)
        and (not model_filter or row.model_id == model_filter)
        and (
            not search_text
            or search_text
            in " ".join(
                part
                for part in (
                    row.original_filename or "",
                    row.source_key or "",
                    row.digital_object_id,
                )
                if part
            ).casefold()
        )
    ]
    st.caption(f"{len(filtered)} propuesta(s) en esta vista.")
    if not filtered:
        st.info("No hay propuestas que coincidan con estos filtros.")
        return
    page_rows = _paginate(st, filtered, key="assisted_analysis_review_page")
    valid_ids = {row.proposal_id for row in page_rows}
    _apply_pending_selection(
        st,
        state_key=_PROPOSAL_SELECTION_KEY,
        pending_key=_PROPOSAL_PENDING_KEY,
        valid_ids=valid_ids,
    )
    current = st.session_state.get(_PROPOSAL_SELECTION_KEY)
    if current not in valid_ids:
        st.session_state[_PROPOSAL_SELECTION_KEY] = page_rows[0].proposal_id
    selected_id = st.selectbox(
        "Propuesta",
        options=[row.proposal_id for row in page_rows],
        format_func=lambda value: _proposal_label(
            next(row for row in page_rows if row.proposal_id == value)
        ),
        key=_PROPOSAL_SELECTION_KEY,
    )
    selected = next(row for row in page_rows if row.proposal_id == selected_id)
    selected_index = page_rows.index(selected)
    previous_col, next_col = st.columns(2)
    if previous_col.button(
        "← Propuesta anterior",
        disabled=selected_index == 0,
        use_container_width=True,
        key=f"assisted_analysis_previous_{selected.proposal_id}",
    ):
        st.session_state[_PROPOSAL_PENDING_KEY] = page_rows[selected_index - 1].proposal_id
        rerun_view(st)
    if next_col.button(
        "Propuesta siguiente →",
        disabled=selected_index >= len(page_rows) - 1,
        use_container_width=True,
        key=f"assisted_analysis_next_{selected.proposal_id}",
    ):
        st.session_state[_PROPOSAL_PENDING_KEY] = page_rows[selected_index + 1].proposal_id
        rerun_view(st)

    engine = create_sqlite_engine(db_path)
    try:
        with session_scope(engine) as session:
            detail = external_analysis_proposal_detail(
                session,
                project_id=project_id,
                proposal_id=selected_id,
            )
            try:
                asset = read_external_analysis_proposal_asset(
                    session,
                    project_root=project_root,
                    project_id=project_id,
                    proposal_id=selected_id,
                )
                asset_error = None
            except (ExternalAnalysisError, AIHandoffError, OSError, ValueError) as exc:
                asset = None
                asset_error = str(exc)
            fallback_preview = (
                _current_page_preview_path(
                    session,
                    project_root=project_root,
                    source_key=selected.navigation_source_key,
                    page_number=selected.page_number,
                )
                if asset is None
                else None
            )
    finally:
        engine.dispose()

    status_text = _STATUS_LABELS.get(selected.status, selected.status)
    current_text = " · vigente" if selected.current_review_id == selected.latest_review_id else ""
    st.caption(
        f"{selected.original_filename or selected.source_key or selected.digital_object_id} · "
        f"página {selected.page_number} · {status_text}{current_text} · "
        f"{_model_label(selected.model_id)}"
    )
    image_col, proposal_col = st.columns([1.15, 1], gap="large")
    with image_col:
        st.subheader("Imagen de origen")
        if asset is None:
            st.error("No se pudo comprobar la imagen utilizada para esta propuesta.")
            if asset_error:
                _render_diagnostic_detail(st, asset_error)
            _render_current_page_fallback(st, preview_path=fallback_preview)
        else:
            _render_exact_asset(
                st,
                asset=asset,
                page=selected.page_number,
                key=f"assisted_analysis_asset_{selected.proposal_id}",
            )
    with proposal_col:
        _render_output(st, detail.raw_output, title="Propuesta automática")
        if selected.warnings:
            st.warning("Advertencias del modelo: " + " · ".join(selected.warnings))
        if selected.latest_review_id:
            with st.expander("Última decisión registrada", expanded=False):
                st.write(
                    f"{_STATUS_LABELS.get(selected.latest_decision or '', selected.latest_decision or '')}"
                    f" · revisión {selected.latest_revision} · "
                    f"{selected.latest_reviewed_by or '-'} · "
                    f"{_format_datetime(selected.latest_reviewed_at)}"
                )
                if detail.latest_reviewed_output:
                    _render_output(st, detail.latest_reviewed_output)
                if detail.latest_review_note:
                    st.caption(detail.latest_review_note)
        with st.expander("Procedencia técnica", expanded=False):
            st.write(f"proposal_id: `{selected.external_proposal_id}`")
            st.write(f"target_id: `{selected.target_id}`")
            st.write(f"digital_object_id: `{selected.digital_object_id}`")
            st.write(f"schema: `{selected.output_schema_id}`")
            st.json(detail.provenance)

    _render_proposal_comparison(
        st,
        db_path=db_path,
        project_id=project_id,
        selected=selected,
        selected_output=detail.raw_output,
        proposals=proposals,
    )

    if asset is None:
        st.info(
            "No se habilitan decisiones hasta que Archive Workbench pueda comprobar la imagen utilizada para generar esta propuesta."
        )
        return

    if selected.current_review_id and selected.current_review_id != selected.latest_review_id:
        st.warning(
            "Esta página ya tiene otra revisión vigente. Aceptar esta propuesta no la reemplaza salvo que lo confirmes explícitamente."
        )
    raw = detail.raw_output
    with st.form(f"assisted_analysis_review_form_{selected.proposal_id}", enter_to_submit=False):
        st.subheader("Decisión")
        description = st.text_area(
            "Descripción revisada",
            value=str(raw.get("description") or ""),
            key=f"assisted_analysis_description_{selected.proposal_id}",
        )
        document_features = st.text_area(
            "Rasgos documentales · uno por línea",
            value=_join_lines(raw.get("document_features")),
            key=f"assisted_analysis_features_{selected.proposal_id}",
        )
        visible_text_notes = st.text_area(
            "Notas visuales sobre texto · una por línea",
            value=_join_lines(raw.get("visible_text_notes")),
            key=f"assisted_analysis_text_notes_{selected.proposal_id}",
        )
        uncertainties = st.text_area(
            "Incertidumbres que deben conservarse como advertencias · una por línea",
            value=_join_lines(raw.get("uncertainties")),
            key=f"assisted_analysis_uncertainties_{selected.proposal_id}",
        )
        note = st.text_input(
            "Nota de revisión (opcional)",
            key=f"assisted_analysis_review_note_{selected.proposal_id}",
        )
        replace_current = False
        if selected.current_review_id:
            replace_current = st.checkbox(
                "Si acepto, usar esta nueva revisión como vigente para esta página",
                value=False,
                key=f"assisted_analysis_replace_current_{selected.proposal_id}",
            )
        action_cols = st.columns(3)
        accept_raw = action_cols[0].form_submit_button(
            "Aceptar tal como está",
            type="primary",
            use_container_width=True,
        )
        accept_edit = action_cols[1].form_submit_button(
            "Editar y aceptar",
            use_container_width=True,
        )
        reject = action_cols[2].form_submit_button(
            "Rechazar",
            use_container_width=True,
        )
    if not (accept_raw or accept_edit or reject):
        return
    try:
        engine = create_sqlite_engine(db_path)
        try:
            with session_scope(engine) as session:
                if reject:
                    review = review_external_analysis_proposal(
                        session,
                        proposal_id=selected.proposal_id,
                        decision="rejected",
                        reviewed_by=actor or "local_user",
                        review_note=note or None,
                    )
                    made_current = False
                else:
                    reviewed_output = None
                    if accept_edit:
                        reviewed_output = {
                            "description": description,
                            "document_features": _split_lines(document_features),
                            "visible_text_notes": _split_lines(visible_text_notes),
                            "uncertainties": _split_lines(uncertainties),
                        }
                    review = review_external_analysis_proposal(
                        session,
                        proposal_id=selected.proposal_id,
                        decision="accepted",
                        reviewed_by=actor or "local_user",
                        reviewed_output=reviewed_output,
                        review_note=note or None,
                    )
                    made_current = review.initial_selection_id is not None
                    if replace_current and not made_current:
                        selection = set_external_analysis_current_review(
                            session,
                            review_id=review.review_id,
                            selected_by=actor or "local_user",
                        )
                        made_current = selection.created or selection.selection_id is not None
        finally:
            engine.dispose()
    except (ExternalAnalysisError, ValueError, OSError) as exc:
        st.error("No se pudo guardar la decisión. La propuesta quedó sin cambios.")
        _render_diagnostic_detail(st, str(exc))
        return
    if reject:
        notice = "Propuesta rechazada. El resultado automático original se conservó sin cambios."
    elif made_current:
        notice = "Propuesta aceptada y vinculada como análisis vigente de esta página."
    else:
        notice = "Propuesta aceptada. La revisión vigente anterior se conservó."
    st.session_state["assisted_analysis_notice"] = notice
    rerun_view(st)


def _render_proposal_comparison(
    st,
    *,
    db_path: Path,
    project_id: str,
    selected: ExternalAnalysisProposalSummary,
    selected_output: dict[str, Any],
    proposals: list[ExternalAnalysisProposalSummary],
) -> None:
    comparable = [
        row
        for row in proposals
        if row.proposal_id != selected.proposal_id
        and row.digital_object_id == selected.digital_object_id
        and row.page_number == selected.page_number
        and row.output_schema_id == selected.output_schema_id
    ]
    if not comparable:
        return
    st.subheader("Comparar propuestas")
    compare_id = st.selectbox(
        "Comparar con",
        options=[None] + [row.proposal_id for row in comparable],
        format_func=lambda value: (
            "Elegir otra propuesta"
            if value is None
            else _proposal_label(next(row for row in comparable if row.proposal_id == value))
        ),
        key=f"assisted_analysis_compare_{selected.proposal_id}",
    )
    if compare_id is None:
        st.caption("Elegí otra propuesta para verla junto a la seleccionada.")
        return
    compared = next(row for row in comparable if row.proposal_id == compare_id)
    engine = create_sqlite_engine(db_path)
    try:
        with session_scope(engine) as session:
            detail = external_analysis_proposal_detail(
                session,
                project_id=project_id,
                proposal_id=compared.proposal_id,
            )
    finally:
        engine.dispose()
    left, right = st.columns(2, gap="large")
    with left:
        st.write(f"**Seleccionada · {_model_label(selected.model_id or selected.producer_id)}**")
        st.caption(_STATUS_LABELS.get(selected.status, selected.status))
        _render_output(st, selected_output)
        if selected.warnings:
            st.warning("Advertencias del modelo: " + " · ".join(selected.warnings))
    with right:
        st.write(f"**Comparación · {_model_label(compared.model_id or compared.producer_id)}**")
        st.caption(_STATUS_LABELS.get(compared.status, compared.status))
        _render_output(st, detail.raw_output)
        if compared.warnings:
            st.warning("Advertencias del modelo: " + " · ".join(compared.warnings))


def _render_documents_with_analysis(
    st,
    *,
    project_root: Path,
    db_path: Path,
    project_id: str,
    history: list[ExternalAnalysisHistoryRow],
) -> None:
    st.subheader("Documentos con análisis")
    current_rows = [row for row in history if row.is_current and row.decision == "accepted"]
    if not current_rows:
        st.info("Todavía no hay páginas con una revisión de análisis asistido vigente.")
        return
    filter_cols = st.columns([1, 1.5])
    models = sorted({row.model_id for row in current_rows if row.model_id})
    model_filter = filter_cols[0].selectbox(
        "Modelo",
        options=[""] + models,
        format_func=lambda value: "Todos" if not value else _model_label(value),
        key="assisted_analysis_documents_model",
    )
    search_text = (
        filter_cols[1]
        .text_input(
            "Documento o archivo",
            key="assisted_analysis_documents_search",
        )
        .strip()
        .casefold()
    )
    filtered = [
        row
        for row in current_rows
        if (not model_filter or row.model_id == model_filter)
        and (
            not search_text
            or search_text
            in " ".join(
                part
                for part in (
                    row.original_filename or "",
                    row.source_key or "",
                    row.digital_object_id,
                )
                if part
            ).casefold()
        )
    ]
    if not filtered:
        st.info("No hay páginas con análisis que coincidan con estos filtros.")
        return
    pending_review_id = st.session_state.get(_DOCUMENT_PENDING_KEY)
    if pending_review_id:
        pending_index = next(
            (index for index, row in enumerate(filtered) if row.review_id == pending_review_id),
            None,
        )
        if pending_index is not None:
            st.session_state["assisted_analysis_documents_page"] = pending_index // _PAGE_SIZE + 1
    page_rows = _paginate(st, filtered, key="assisted_analysis_documents_page")
    valid_ids = {row.review_id for row in page_rows}
    _apply_pending_selection(
        st,
        state_key=_DOCUMENT_SELECTION_KEY,
        pending_key=_DOCUMENT_PENDING_KEY,
        valid_ids=valid_ids,
    )
    if st.session_state.get(_DOCUMENT_SELECTION_KEY) not in valid_ids:
        st.session_state[_DOCUMENT_SELECTION_KEY] = page_rows[0].review_id
    selected_review_id = st.selectbox(
        "Página con análisis",
        options=[row.review_id for row in page_rows],
        format_func=lambda value: _history_label(
            next(row for row in page_rows if row.review_id == value)
        ),
        key=_DOCUMENT_SELECTION_KEY,
    )
    selected = next(row for row in page_rows if row.review_id == selected_review_id)
    engine = create_sqlite_engine(db_path)
    try:
        with session_scope(engine) as session:
            try:
                asset = read_external_analysis_proposal_asset(
                    session,
                    project_root=project_root,
                    project_id=project_id,
                    proposal_id=selected.proposal_id,
                )
                asset_error = None
            except (ExternalAnalysisError, AIHandoffError, OSError, ValueError) as exc:
                asset = None
                asset_error = str(exc)
            fallback_preview = (
                _current_page_preview_path(
                    session,
                    project_root=project_root,
                    source_key=selected.navigation_source_key,
                    page_number=selected.page_number,
                )
                if asset is None
                else None
            )
            detail = external_analysis_proposal_detail(
                session,
                project_id=project_id,
                proposal_id=selected.proposal_id,
            )
    finally:
        engine.dispose()
    image_col, analysis_col = st.columns([1.15, 1], gap="large")
    with image_col:
        st.subheader(
            f"{selected.original_filename or selected.source_key or selected.digital_object_id} · página {selected.page_number}"
        )
        if asset is None:
            st.error("No se pudo comprobar la imagen utilizada para este análisis.")
            if asset_error:
                _render_diagnostic_detail(st, asset_error)
            _render_current_page_fallback(st, preview_path=fallback_preview)
        else:
            _render_exact_asset(
                st,
                asset=asset,
                page=selected.page_number,
                key=f"assisted_analysis_current_asset_{selected.review_id}",
            )
    with analysis_col:
        _render_output(st, selected.reviewed_output, title="Análisis revisado vigente")
        st.caption(
            f"Revisado por {selected.reviewed_by} · {_format_datetime(selected.reviewed_at)} · "
            f"{_model_label(selected.model_id)}"
        )
        if selected.review_note:
            st.write(f"**Nota de revisión:** {selected.review_note}")
        with st.expander("Comparar con la propuesta automática original", expanded=False):
            _render_output(st, detail.raw_output)
        nav_cols = st.columns(2)
        if nav_cols[0].button(
            "Abrir en Edición y anotación",
            use_container_width=True,
            key=f"assisted_analysis_open_annotation_{selected.review_id}",
        ):
            _navigate_to_document(st, selected, mode="annotation")
        if nav_cols[1].button(
            "Abrir en Revisión estructural",
            use_container_width=True,
            key=f"assisted_analysis_open_review_{selected.review_id}",
        ):
            _navigate_to_document(st, selected, mode="review")


def _render_history(
    st,
    *,
    db_path: Path,
    project_id: str,
    actor: str,
    history: list[ExternalAnalysisHistoryRow],
) -> None:
    st.subheader("Historial")
    if not history:
        st.info("Todavía no hay decisiones registradas sobre propuestas de análisis asistido.")
        return
    filter_a, filter_b, filter_c = st.columns(3)
    decision_filter = filter_a.selectbox(
        "Estado de la decisión",
        options=["", "accepted", "rejected"],
        format_func=lambda value: "Todos" if not value else _STATUS_LABELS[value],
        key="assisted_analysis_history_status",
    )
    model_options = sorted(
        {row.model_id or row.producer_id for row in history if row.model_id or row.producer_id}
    )
    model_filter = filter_b.selectbox(
        "Modelo de análisis",
        options=[""] + model_options,
        format_func=lambda value: "Todos" if not value else _model_label(value),
        key="assisted_analysis_history_model",
    )
    reviewer_options = sorted({row.reviewed_by for row in history if row.reviewed_by})
    reviewer_filter = filter_c.selectbox(
        "Persona revisora",
        options=[""] + reviewer_options,
        format_func=lambda value: "Todas" if not value else value,
        key="assisted_analysis_history_reviewer",
    )
    filter_d, filter_e, filter_f = st.columns([1, 1, 1.6])
    schemas = sorted({row.output_schema_id for row in history})
    schema_filter = filter_d.selectbox(
        "Tipo de análisis",
        options=[""] + schemas,
        format_func=lambda value: "Todos" if not value else _analysis_type_label(value),
        key="assisted_analysis_history_schema",
    )
    page_filter = int(
        filter_e.number_input(
            "Página (0 = todas)",
            min_value=0,
            value=0,
            step=1,
            key="assisted_analysis_history_page_number",
        )
    )
    text_filter = (
        filter_f.text_input(
            "Buscar en documento, nota o versión revisada",
            key="assisted_analysis_history_text",
        )
        .strip()
        .casefold()
    )
    dates = [row.reviewed_at.date() for row in history]
    date_cols = st.columns(2)
    date_start = date_cols[0].date_input(
        "Decisiones desde",
        value=min(dates),
        min_value=min(dates),
        max_value=max(dates),
        key="assisted_analysis_history_date_start",
    )
    date_end = date_cols[1].date_input(
        "Decisiones hasta",
        value=max(dates),
        min_value=min(dates),
        max_value=max(dates),
        key="assisted_analysis_history_date_end",
    )
    filtered = []
    for row in history:
        blob = " ".join(
            part
            for part in (
                row.original_filename or "",
                row.source_key or "",
                row.review_note or "",
                _output_text_blob(row.reviewed_output),
            )
            if part
        ).casefold()
        if decision_filter and row.decision != decision_filter:
            continue
        if model_filter and (row.model_id or row.producer_id) != model_filter:
            continue
        if reviewer_filter and row.reviewed_by != reviewer_filter:
            continue
        if schema_filter and row.output_schema_id != schema_filter:
            continue
        if page_filter and row.page_number != page_filter:
            continue
        if not (date_start <= row.reviewed_at.date() <= date_end):
            continue
        if text_filter and text_filter not in blob:
            continue
        filtered.append(row)
    st.caption(f"{len(filtered)} decisión(es) en esta vista.")
    if not filtered:
        st.info("No hay decisiones que coincidan con estos filtros.")
        return
    page_rows = _paginate(st, filtered, key="assisted_analysis_history_page")
    valid_ids = {row.review_id for row in page_rows}
    _apply_pending_selection(
        st,
        state_key=_HISTORY_SELECTION_KEY,
        pending_key=_HISTORY_PENDING_KEY,
        valid_ids=valid_ids,
    )
    if st.session_state.get(_HISTORY_SELECTION_KEY) not in valid_ids:
        st.session_state[_HISTORY_SELECTION_KEY] = page_rows[0].review_id
    selected_review_id = st.selectbox(
        "Decisión",
        options=[row.review_id for row in page_rows],
        format_func=lambda value: _history_label(
            next(row for row in page_rows if row.review_id == value)
        ),
        key=_HISTORY_SELECTION_KEY,
    )
    selected = next(row for row in page_rows if row.review_id == selected_review_id)
    st.write(
        f"**{_STATUS_LABELS.get(selected.decision, selected.decision)}** · revisión {selected.revision} · "
        f"{selected.reviewed_by} · {_format_datetime(selected.reviewed_at)}"
    )
    if selected.is_current:
        st.success("Esta revisión es la descripción vigente de esta página.")
    if selected.reviewed_output:
        _render_output(st, selected.reviewed_output)
    if selected.review_note:
        st.write(f"**Nota:** {selected.review_note}")
    with st.expander("Detalles técnicos y propuesta original", expanded=False):
        st.write(f"proposal_id: `{selected.external_proposal_id}`")
        st.write(f"schema: `{selected.output_schema_id}`")
        st.write(f"modelo: `{selected.model_id or '-'}`")
        engine = create_sqlite_engine(db_path)
        try:
            with session_scope(engine) as session:
                detail = external_analysis_proposal_detail(
                    session,
                    project_id=project_id,
                    proposal_id=selected.proposal_id,
                )
        finally:
            engine.dispose()
        _render_output(st, detail.raw_output, title="Propuesta automática original")
    if selected.decision == "accepted" and not selected.is_current:
        with st.form(f"assisted_analysis_set_current_{selected.review_id}", enter_to_submit=False):
            confirm = st.checkbox(
                "Confirmo que quiero usar esta revisión como vigente para esta página",
                value=False,
                key=f"assisted_analysis_set_current_confirm_{selected.review_id}",
            )
            submit = st.form_submit_button("Usar esta revisión como vigente", type="primary")
        if submit:
            if not confirm:
                st.error("Marcá la confirmación antes de reemplazar la revisión vigente.")
            else:
                try:
                    engine = create_sqlite_engine(db_path)
                    try:
                        with session_scope(engine) as session:
                            set_external_analysis_current_review(
                                session,
                                review_id=selected.review_id,
                                selected_by=actor or "local_user",
                            )
                    finally:
                        engine.dispose()
                except (ExternalAnalysisError, ValueError) as exc:
                    st.error("No se pudo cambiar la revisión vigente.")
                    _render_diagnostic_detail(st, str(exc))
                else:
                    st.session_state["assisted_analysis_notice"] = (
                        "La revisión seleccionada quedó vigente para esta página."
                    )
                    rerun_view(st)
    if selected.navigation_source_key:
        nav_cols = st.columns(2)
        if nav_cols[0].button(
            "Abrir página en Edición y anotación",
            key=f"assisted_analysis_history_annotation_{selected.review_id}",
            use_container_width=True,
        ):
            _navigate_to_document(st, selected, mode="annotation")
        if nav_cols[1].button(
            "Abrir página en Revisión estructural",
            key=f"assisted_analysis_history_review_{selected.review_id}",
            use_container_width=True,
        ):
            _navigate_to_document(st, selected, mode="review")


def render_assisted_analysis_view(
    st,
    *,
    project_root: Path,
    db_path: Path,
    project_id: str,
    actor: str,
) -> None:
    section_heading(st, "Análisis asistido")
    notice = st.session_state.pop("assisted_analysis_notice", None)
    if notice:
        st.success(str(notice))
    packages, proposals, history = _load_surface_rows(db_path, project_id=project_id)
    received_tab, review_tab, documents_tab, history_tab = tracked_tabs(
        st,
        ["Resultados recibidos", "Revisar propuestas", "Documentos con análisis", "Historial"],
        key=_TAB_KEY,
        default="Resultados recibidos",
        rerun_on_change=False,
        help_by_label=TAB_HELP[_TAB_KEY],
    )
    with received_tab:
        _render_received_results(
            st,
            project_root=project_root,
            db_path=db_path,
            project_id=project_id,
            actor=actor,
            packages=packages,
        )
    with review_tab:
        _render_proposal_review(
            st,
            project_root=project_root,
            db_path=db_path,
            project_id=project_id,
            actor=actor,
            proposals=proposals,
        )
    with documents_tab:
        _render_documents_with_analysis(
            st,
            project_root=project_root,
            db_path=db_path,
            project_id=project_id,
            history=history,
        )
    with history_tab:
        _render_history(
            st,
            db_path=db_path,
            project_id=project_id,
            actor=actor,
            history=history,
        )
