from __future__ import annotations

from archive_workbench.ui_dates import DATE_INPUT_MIN, DATE_INPUT_MAX
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

from pydantic import ValidationError
from sqlalchemy import select

from archive_workbench.audiovisual import (
    AUDIO_EXTENSIONS,
    VIDEO_EXTENSIONS,
    REVIEW_STATUSES,
    TRANSCRIPTION_DISCARDED_STATUS,
    discard_transcription_run,
    restore_transcription_run,
    archive_timeline_annotation,
    assign_speaker_from_time,
    assign_speaker_to_segment,
    audiovisual_media_rows,
    create_segment_mention,
    create_timeline_annotation,
    ensure_playback_asset,
    export_transcript_segments_bytes,
    format_timestamp,
    resolve_playback_path,
    segment_mention_rows,
    segment_revision_rows,
    timeline_annotation_rows,
    transcript_document_text,
    transcript_with_timeline_marks,
    transcript_segment_rows,
    transcribe_audiovisual,
    update_transcript_document,
    transcription_backend_keys,
    transcription_compute_types,
    transcription_model_names,
    update_audiovisual_description,
    update_transcript_segment,
)
from archive_workbench.contracts.audiovisual import AudiovisualDescription, TranscriptionRequest
from archive_workbench.db import create_sqlite_engine, session_scope
from archive_workbench.db.models import ArchivalUnit, AudiovisualMedia, AuthorityRecord, TranscriptionRun
from archive_workbench.catalog_management import register_external_file
from archive_workbench.domain.enums import MediaType
from archive_workbench.inspection import detect_media_type
from archive_workbench.local_picker import choose_local_files
from archive_workbench.runtime_environment import (
    managed_runtime_variant,
    managed_workspace,
    workspace_display_path,
)
from archive_workbench.platform_import import (
    import_platform_media,
    platform_origin_for_digital_object,
    platform_runtime_status,
)
from archive_workbench.contracts.platform import PlatformImportRequest
from archive_workbench.transcription_evaluation import (
    compare_transcription_to_reviewed_reference,
    evaluate_transcription_run,
    original_transcript_text,
    reviewed_reference_run_id,
)
from archive_workbench.audiovisual_review_component import synchronized_media_review
from archive_workbench.ui_help import TAB_HELP, TASK_HELP
from archive_workbench.ui_navigation import (
    mount_choice_help,
    request_tab,
    rerun_view,
    section_heading,
    tracked_tabs,
)

_REVIEW_LABELS = {
    "unreviewed": "Sin revisar",
    "reviewed": "Revisado",
    "approved": "Aprobado",
}
_SPEEDS = (0.5, 0.75, 1.0, 1.25, 1.5, 2.0)
_RUN_STATUS_LABELS = {
    "registered": "Registrada",
    "running": "En curso",
    "completed": "Completada",
    "failed": "Fallida",
    TRANSCRIPTION_DISCARDED_STATUS: "Descartada",
}

def _format_supported_extensions(extensions: set[str]) -> str:
    return ", ".join(extension.removeprefix(".").upper() for extension in sorted(extensions))



def _platform_import_form_error(
    *,
    url: str,
    access_conditions: str,
    authorization_confirmed: bool,
) -> str | None:
    cleaned_url = url.strip()
    if not cleaned_url:
        return "Pegá la dirección (URL) del audio o video que querés incorporar."
    parsed = urlparse(cleaned_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return (
            "La dirección del material no parece válida. Copiá y pegá la URL completa, "
            "por ejemplo https://www.youtube.com/watch?v=…"
        )
    if len(access_conditions.strip()) < 3:
        return "Completá las condiciones de acceso o autorización antes de incorporar el material."
    if not authorization_confirmed:
        return (
            "Marcá la casilla de confirmación para indicar que el proyecto está autorizado "
            "a incorporar este material."
        )
    return None


def _platform_request_validation_message(exc: ValidationError) -> str:
    fields = {str(part) for error in exc.errors(include_url=False) for part in error.get("loc", ())}
    if "url" in fields:
        return (
            "La dirección del material no parece válida. Copiá y pegá la URL completa, "
            "por ejemplo https://www.youtube.com/watch?v=…"
        )
    if "access_conditions" in fields:
        return "Completá las condiciones de acceso o autorización antes de incorporar el material."
    if "authorization_confirmed" in fields:
        return (
            "Marcá la casilla de confirmación para indicar que el proyecto está autorizado "
            "a incorporar este material."
        )
    return "Revisá los datos del formulario antes de incorporar el material."


def _run_db_action(st, *, db_path: Path, callback) -> object | None:
    engine = create_sqlite_engine(db_path)
    try:
        with session_scope(engine) as session:
            result = callback(session)
    except (ValueError, RuntimeError, OSError, FileNotFoundError) as exc:
        st.error(str(exc))
        return None
    finally:
        engine.dispose()
    return result


def _render_segment_mentions(st, *, db_path: Path, selected_segment, authorities, actor: str) -> None:
    st.write("**Registrar una mención en el segmento seleccionado**")
    authority_by_id = {row.id: row for row in authorities}
    authority_options = [None, *authority_by_id]
    mention_text = st.text_input(
        "Texto exacto de la mención en este segmento",
        key=f"av_mention_text_{selected_segment.segment_id}",
    )
    authority_id = st.selectbox(
        "Entidad existente vinculada a esta mención (opcional)",
        options=authority_options,
        format_func=lambda value: (
            "Sin vincular"
            if value is None
            else authority_by_id[value].preferred_name
        ),
        key=f"av_mention_authority_{selected_segment.segment_id}",
    )
    mention_status = st.selectbox(
        "Estado de la mención",
        options=("pending", "accepted", "modified", "rejected"),
        format_func=lambda value: {
            "pending": "Pendiente",
            "accepted": "Aceptada",
            "modified": "Modificada",
            "rejected": "Rechazada",
        }[value],
        key=f"av_mention_status_{selected_segment.segment_id}",
    )
    mention_note = st.text_input(
        "Nota sobre esta mención (opcional)",
        key=f"av_mention_note_{selected_segment.segment_id}",
    )
    if st.button("Guardar esta mención en el segmento"):
        result = _run_db_action(
            st,
            db_path=db_path,
            callback=lambda session: create_segment_mention(
                session,
                segment_id=selected_segment.segment_id,
                mention_text=mention_text,
                authority_id=authority_id,
                status=mention_status,
                actor=actor,
                note=mention_note or None,
            ),
        )
        if result is not None:
            st.session_state["av_pending_segment_id"] = selected_segment.segment_id
            st.session_state["av_flash"] = "Mención audiovisual guardada."
            rerun_view(st)

    mention_engine = create_sqlite_engine(db_path)
    try:
        with session_scope(mention_engine) as session:
            mentions = segment_mention_rows(
                session, segment_id=selected_segment.segment_id
            )
    finally:
        mention_engine.dispose()
    if mentions:
        st.dataframe(
            [
                {
                    "mención": item.mention_text,
                    "entidad vinculada": item.authority_name or "Sin vincular",
                    "estado": item.status,
                    "revisión_segmento": item.segment_revision_number,
                    "desactualizada": item.is_stale,
                }
                for item in mentions
            ],
            hide_index=True,
            use_container_width=True,
        )



def _media_control_script(*, rate: float, seek_to: float | None = None) -> str:
    """JavaScript mínimo para velocidad y salto del reproductor HTML5 de Streamlit."""

    seek_value = "null" if seek_to is None else repr(max(0.0, float(seek_to)))
    return f"""
    <script>
    const rate = {float(rate)!r};
    const seekTo = {seek_value};
    let seekApplied = false;
    function applyControls() {{
      try {{
        const media = window.parent.document.querySelectorAll('audio, video');
        if (!media.length) return;
        const element = media[media.length - 1];
        element.playbackRate = rate;
        element.defaultPlaybackRate = rate;
        if (seekTo !== null && !seekApplied) {{
          const seek = () => {{
            try {{
              element.currentTime = seekTo;
              seekApplied = true;
            }} catch (e) {{}}
          }};
          if (element.readyState >= 1) {{
            seek();
          }} else {{
            element.addEventListener('loadedmetadata', seek, {{once: true}});
          }}
        }}
      }} catch (e) {{}}
    }}
    applyControls();
    setTimeout(applyControls, 100);
    setTimeout(applyControls, 500);
    </script>
    """


def _control_media_element(st, *, rate: float, seek_to: float | None = None) -> None:
    """Controla el elemento HTML5 ya renderizado por st.audio/st.video."""
    script = _media_control_script(rate=rate, seek_to=seek_to)
    iframe = getattr(st, "iframe", None)
    if iframe is not None:
        iframe(script, height=1, width=1)
        return
    # Compatibilidad con Streamlit 1.55, antes de la API pública st.iframe.
    from streamlit.components.v1 import html as component_html

    component_html(script, height=1, width=1)


def _media_label(row) -> str:
    title = row.title or row.original_filename
    duration = f" · {format_timestamp(row.duration_seconds)}" if row.duration_seconds else ""
    return f"{title} · {row.media_type}{duration}"


def _segment_label(row) -> str:
    text = " ".join(row.text.split())
    snippet = text if len(text) <= 72 else text[:71] + "…"
    return (
        f"{row.segment_index + 1}. {format_timestamp(row.start_time)}–"
        f"{format_timestamp(row.end_time)} · {snippet or '[sin texto]'}"
    )


def _segment_for_time(rows, time_seconds: float):
    if not rows:
        return None
    current = max(0.0, float(time_seconds))
    for row in rows:
        if float(row.start_time) <= current < float(row.end_time):
            return row
    return min(
        rows,
        key=lambda row: (
            float(row.start_time) - current
            if current < float(row.start_time)
            else current - float(row.end_time)
        ),
    )


def _timeline_annotation_label(row) -> str:
    kind = "Hablante" if row.annotation_type == "speaker" else "Anotación"
    linked = f" · {row.authority_name}" if row.authority_name else ""
    return (
        f"{format_timestamp(row.start_time)}–{format_timestamp(row.end_time)} · "
        f"{kind} · {row.label}{linked}"
    )


def _run_label(row: dict[str, object]) -> str:
    device = "CPU" if row["device"] == "cpu" else "CUDA"
    created = row.get("created_at")
    stamp = created.strftime("%Y-%m-%d %H:%M") if hasattr(created, "strftime") else str(created)
    status = _RUN_STATUS_LABELS.get(str(row.get("status") or ""), str(row.get("status") or ""))
    return f"{row['model_name']} · {device} · {status} · {stamp}"


def _format_seconds(value: float | None) -> str:
    if value is None:
        return "No disponible"
    if value < 60:
        return f"{value:.1f} s"
    minutes, seconds = divmod(value, 60)
    return f"{int(minutes)} min {seconds:.1f} s"


def _format_memory(value: float | None) -> str:
    return "No disponible" if value is None else f"{value:.0f} MiB"


def _format_duration_share(value: float | None) -> str:
    """Expresa cuánto tiempo de cómputo usó la corrida respecto de la duración del audio."""

    return "No disponible" if value is None else f"{value * 100:.1f} %"


def _render_player(
    st,
    *,
    path: Path,
    media_type: str,
    start_time: float,
    speed: float,
    seek_to: float | None = None,
) -> None:
    start = max(0, int(start_time))
    if media_type == "video":
        st.video(str(path), start_time=start)
    else:
        st.audio(str(path), start_time=start)
    _control_media_element(st, rate=speed, seek_to=seek_to)


def _archival_unit_labels(units) -> dict[str, str]:
    base_labels: dict[str, str] = {}
    counts: dict[str, int] = {}
    for unit in units:
        base = unit.title.strip() or "Unidad sin título"
        if unit.reference_code:
            base = f"{base} · {unit.reference_code}"
        base_labels[unit.id] = base
        counts[base] = counts.get(base, 0) + 1

    seen: dict[str, int] = {}
    labels: dict[str, str] = {}
    for unit in units:
        base = base_labels[unit.id]
        if counts[base] == 1:
            labels[unit.id] = base
            continue
        seen[base] = seen.get(base, 0) + 1
        labels[unit.id] = f"{base} · unidad {seen[base]}"
    return labels


def _local_media_type_label(media_type: MediaType) -> str:
    return "Audio" if media_type == MediaType.AUDIO else "Video"


def _validate_local_media_paths(paths: list[Path]) -> tuple[list[tuple[Path, MediaType]], list[str]]:
    valid: list[tuple[Path, MediaType]] = []
    errors: list[str] = []
    for source in paths:
        if not source.is_file():
            errors.append(f"No se encontró el archivo: {source}")
            continue
        try:
            media_type = detect_media_type(source)
        except OSError as exc:
            errors.append(f"No se pudo revisar {source.name}: {exc}")
            continue
        if media_type not in {MediaType.AUDIO, MediaType.VIDEO}:
            errors.append(f"{source.name} no es un archivo de audio o video admitido.")
            continue
        valid.append((source, media_type))
    return valid, errors



def _managed_audiovisual_import_paths(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    supported = AUDIO_EXTENSIONS | VIDEO_EXTENSIONS
    return sorted(
        path.resolve()
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in supported
    )

def _register_selected_local_media(
    session,
    *,
    project_root: Path,
    project_id: str,
    archival_unit_id: str,
    paths: list[Path],
    actor: str,
) -> dict[str, object]:
    successes: list[dict[str, str]] = []
    failures: list[str] = []
    for source in paths:
        try:
            with session.begin_nested():
                result = register_external_file(
                    session,
                    project_root=project_root,
                    project_id=project_id,
                    archival_unit_id=archival_unit_id,
                    source_path=source,
                    destination_dir="corpus/importados",
                    registered_by=actor or "local_user",
                )
                media = session.scalar(
                    select(AudiovisualMedia).where(
                        AudiovisualMedia.digital_object_id
                        == result.registration.digital_object_id
                    )
                )
                if media is None:
                    raise RuntimeError("El archivo no ingresó al circuito de audio y video")
                successes.append(
                    {
                        "media_id": str(media.id),
                        "label": str(media.title or source.stem),
                        "filename": source.name,
                    }
                )
        except (ValueError, RuntimeError, OSError, FileNotFoundError) as exc:
            failures.append(f"{source.name}: {exc}")
    return {"successes": successes, "failures": failures}


def _render_last_import_result(st) -> None:
    result = st.session_state.get("av_last_import_result")
    if not isinstance(result, dict):
        return
    successes = list(result.get("successes") or [])
    failures = list(result.get("failures") or [])
    if successes:
        count = len(successes)
        st.success(
            "Se incorporó 1 archivo de audio o video."
            if count == 1
            else f"Se incorporaron {count} archivos de audio o video."
        )
        open_options = {str(item["media_id"]): str(item["label"]) for item in successes}
        if len(open_options) == 1:
            selected_media_id = next(iter(open_options))
        else:
            selected_media_id = st.selectbox(
                "Audio o video incorporado que querés abrir",
                options=list(open_options),
                format_func=lambda value: open_options[value],
                key="av_import_result_media_id",
            )
        if st.button(
            "Abrir este audio o video para transcribirlo",
            key="av_open_imported_media",
            type="primary",
        ):
            st.session_state["av_pending_media_id"] = selected_media_id
            st.session_state.pop("av_last_import_result", None)
            request_tab(st, key="audiovisual_tabs", label="Transcribir y revisar")
            rerun_view(st)
    if failures:
        st.warning(
            "No se pudieron incorporar algunos archivos. Abrí los detalles para revisar cuáles."
        )
        with st.expander("Ver archivos que no se pudieron incorporar", expanded=False):
            for failure in failures:
                st.write(f"- {failure}")


def _render_audiovisual_import(
    st,
    *,
    project_root: Path,
    db_path: Path,
    project_id: str,
    actor: str,
) -> None:
    engine = create_sqlite_engine(db_path)
    try:
        with session_scope(engine) as session:
            units = session.scalars(
                select(ArchivalUnit)
                .where(ArchivalUnit.project_id == project_id)
                .order_by(ArchivalUnit.title, ArchivalUnit.id)
            ).all()
    finally:
        engine.dispose()

    if not units:
        st.warning(
            "El proyecto todavía no tiene una unidad del catálogo donde vincular el audio o video."
        )
        return

    unit_by_id = {row.id: row for row in units}
    unit_labels = _archival_unit_labels(units)
    method = st.radio(
        "Cómo querés incorporar el audio o video",
        options=("local", "platform"),
        format_func=lambda value: (
            "Desde esta computadora" if value == "local" else "Desde una plataforma web"
        ),
        horizontal=True,
        key="audiovisual_import_method",
    )
    active_method_label = (
        "Desde esta computadora" if method == "local" else "Desde una plataforma web"
    )
    mount_choice_help(
        st,
        key="audiovisual_import_method",
        label=active_method_label,
        help_text=TASK_HELP["audiovisual_import_method"][active_method_label],
    )

    if method == "local":
        st.caption(
            "Formatos admitidos desde esta computadora. "
            f"Audio: {_format_supported_extensions(AUDIO_EXTENSIONS)}. "
            f"Video: {_format_supported_extensions(VIDEO_EXTENSIONS)}."
        )
        local_unit = st.selectbox(
            "Unidad del catálogo a la que pertenece este material",
            options=list(unit_by_id),
            format_func=lambda value: unit_labels[value],
            key="av_local_import_unit",
        )
        workspace = managed_workspace()
        if workspace is not None:
            available_paths = _managed_audiovisual_import_paths(workspace.audiovisual_imports)
            available_by_label = {
                path.relative_to(workspace.audiovisual_imports).as_posix(): path
                for path in available_paths
            }
            st.caption(
                "Copiá los archivos de audio o video a "
                "`ArchiveWorkbenchData/Imports/AudioVideo`. Esta lista muestra los archivos "
                "compatibles que están en esa carpeta y sus subcarpetas."
            )
            selected_labels = st.multiselect(
                "Archivos de audio o video que querés incorporar",
                options=list(available_by_label),
                key="av_managed_import_selection",
            )
            current_paths = [available_by_label[label] for label in selected_labels]
            if not available_paths:
                st.info(
                    "Todavía no hay archivos compatibles en "
                    "`ArchiveWorkbenchData/Imports/AudioVideo`."
                )
            st.button(
                "Actualizar la lista de archivos",
                key="av_refresh_managed_imports",
                help=(
                    "Usalo después de copiar nuevos archivos a "
                    "ArchiveWorkbenchData/Imports/AudioVideo."
                ),
            )
        else:
            current_paths = [
                Path(value).expanduser().resolve()
                for value in st.session_state.get("av_local_import_paths", [])
            ]
            initial_path = current_paths[0].parent if current_paths else Path.home()
            picker_label = (
                "Cambiar archivos seleccionados"
                if current_paths
                else "Elegir archivos de audio o video"
            )
            if st.button(picker_label, key="av_choose_local_media"):
                selected, picker_error = choose_local_files(
                    initial_path,
                    title="Elegir archivos de audio o video",
                    extensions=sorted(AUDIO_EXTENSIONS | VIDEO_EXTENSIONS),
                )
                if picker_error:
                    st.error(picker_error)
                elif selected is not None:
                    st.session_state["av_local_import_paths"] = [str(path) for path in selected]
                    st.session_state.pop("av_last_import_result", None)
                    current_paths = selected

        valid_paths, selection_errors = _validate_local_media_paths(current_paths)
        if current_paths:
            rows = [
                {
                    "Archivo": source.name,
                    "Tipo": _local_media_type_label(media_type),
                    "Carpeta de origen": workspace_display_path(source.parent),
                }
                for source, media_type in valid_paths
            ]
            if rows:
                st.dataframe(rows, hide_index=True, use_container_width=True)
            for error in selection_errors:
                st.error(error)
            if st.button(
                "Incorporar los archivos seleccionados",
                type="primary",
                key="av_register_local_media",
            ):
                if selection_errors or not valid_paths:
                    st.error("Elegí solamente archivos de audio o video válidos antes de continuar.")
                else:
                    result = _run_db_action(
                        st,
                        db_path=db_path,
                        callback=lambda session: _register_selected_local_media(
                            session,
                            project_root=project_root,
                            project_id=project_id,
                            archival_unit_id=local_unit,
                            paths=[source for source, _media_type in valid_paths],
                            actor=actor,
                        ),
                    )
                    if isinstance(result, dict):
                        st.session_state["av_last_import_result"] = result
        else:
            if workspace is not None:
                st.caption(
                    "Elegí uno o más archivos de la lista para incorporarlos al proyecto. "
                    "La incorporación copia cada archivo seleccionado dentro del proyecto y conserva "
                    "sin cambios el archivo ubicado en ArchiveWorkbenchData/Imports/AudioVideo."
                )
            else:
                st.caption(
                    "Los archivos elegidos se copian dentro del proyecto si todavía están fuera de su carpeta. "
                    "Si ya pertenecen al proyecto, Archive Workbench los registra sin crear otra copia."
                )
    else:
        runtime = platform_runtime_status()
        if not runtime.yt_dlp_available:
            st.error(
                "La extensión de incorporación desde plataformas no está instalada. "
                "Instalá el extra `platform`."
            )
        elif not runtime.ffmpeg_available or not runtime.ffprobe_available:
            st.error(
                "La incorporación desde plataformas requiere FFmpeg y FFprobe instalados y disponibles para Archive Workbench."
            )
        elif not (runtime.deno_available or runtime.node_available):
            st.error(
                "YouTube requiere un runtime JavaScript compatible. "
                "El extra `platform` instala Deno; verificá que quede disponible en PATH."
            )
        else:
            with st.form("av_platform_import_form", enter_to_submit=False):
                platform_url = st.text_input(
                    "URL del audio o video",
                    placeholder="https://www.youtube.com/watch?v=…",
                )
                platform_unit = st.selectbox(
                    "Unidad del catálogo a la que pertenece este material",
                    options=list(unit_by_id),
                    format_func=lambda value: unit_labels[value],
                )
                platform_kind = st.radio(
                    "Qué parte del material querés incorporar",
                    options=("video", "audio"),
                    format_func=lambda value: "Video" if value == "video" else "Solo audio",
                    horizontal=True,
                )
                access_conditions = st.text_area(
                    "Motivo o condiciones que autorizan incorporar este material",
                    placeholder="Indicá por qué este material puede incorporarse al proyecto.",
                    height=90,
                )
                authorization = st.checkbox(
                    "Confirmo que este proyecto está autorizado a conservar una copia de este audio o video"
                )
                submitted = st.form_submit_button(
                    "Incorporar este audio o video desde la plataforma",
                    type="primary",
                )
            if submitted:
                form_error = _platform_import_form_error(
                    url=platform_url,
                    access_conditions=access_conditions,
                    authorization_confirmed=authorization,
                )
                if form_error is not None:
                    st.error(form_error)
                else:
                    try:
                        request = PlatformImportRequest(
                            url=platform_url.strip(),
                            archival_unit_id=platform_unit,
                            media_kind=platform_kind,
                            access_conditions=access_conditions,
                            authorization_confirmed=authorization,
                        )
                    except ValidationError as exc:
                        st.error(_platform_request_validation_message(exc))
                    else:
                        with st.spinner("Descargando y registrando el material…"):
                            imported = _run_db_action(
                                st,
                                db_path=db_path,
                                callback=lambda session: import_platform_media(
                                    session,
                                    project_root=project_root,
                                    project_id=project_id,
                                    request=request,
                                    actor=actor,
                                ),
                            )
                        if imported is not None:
                            st.session_state["av_last_import_result"] = {
                                "successes": [
                                    {
                                        "media_id": imported.media_id,
                                        "label": imported.title,
                                        "filename": Path(imported.relative_path).name,
                                    }
                                ],
                                "failures": [],
                            }

    _render_last_import_result(st)


def _render_transcription_workspace(
    st,
    *,
    project_root: Path,
    db_path: Path,
    project_id: str,
    actor: str,
) -> None:
    engine = create_sqlite_engine(db_path)
    try:
        with session_scope(engine) as session:
            media_rows = audiovisual_media_rows(
                session, project_root=project_root, project_id=project_id
            )
    finally:
        engine.dispose()

    if not media_rows:
        st.info(
            "Todavía no hay audio o video incorporado en este proyecto. "
            "Podés agregarlo desde la pestaña Incorporar audio o video."
        )
        if st.button("Ir a Incorporar audio o video", key="av_go_to_import"):
            request_tab(st, key="audiovisual_tabs", label="Incorporar audio o video")
            rerun_view(st)
        return

    by_id = {row.media_id: row for row in media_rows}
    pending_media = st.session_state.pop("av_pending_media_id", None)
    if pending_media in by_id:
        st.session_state["av_media_id"] = pending_media
    current_media = st.session_state.get("av_media_id")
    if current_media not in by_id:
        st.session_state["av_media_id"] = media_rows[0].media_id
    if len(media_rows) > 1:
        media_id = st.selectbox(
            "Audio o video que querés transcribir o revisar",
            options=list(by_id),
            format_func=lambda value: _media_label(by_id[value]),
            key="av_media_id",
            label_visibility="collapsed",
        )
    else:
        media_id = media_rows[0].media_id
        st.session_state["av_media_id"] = media_id
    media_row = by_id[media_id]
    st.markdown(f"### {media_row.title or media_row.original_filename}")
    media_meta = [media_row.media_type]
    if media_row.duration_seconds:
        media_meta.append(format_timestamp(media_row.duration_seconds))
    if media_row.archival_title:
        media_meta.append(media_row.archival_title)
    st.caption(" · ".join(media_meta))

    engine = create_sqlite_engine(db_path)
    try:
        with session_scope(engine) as session:
            media = session.get(AudiovisualMedia, media_id)
            playback_path = resolve_playback_path(
                session, project_root=project_root, media_id=media_id
            )
            platform_origin = None
            if media is not None:
                platform_origin = platform_origin_for_digital_object(
                    session,
                    project_id=project_id,
                    digital_object_id=media.digital_object_id,
                )
            all_run_summaries: list[dict[str, object]] = []
            if media is not None:
                run_rows = session.scalars(
                    select(TranscriptionRun)
                    .where(TranscriptionRun.audiovisual_media_id == media.id)
                    .order_by(TranscriptionRun.created_at.desc(), TranscriptionRun.id.desc())
                ).all()
                all_run_summaries = [
                    {
                        "id": row.id,
                        "status": row.status,
                        "backend": row.backend,
                        "backend_version": row.backend_version,
                        "model_name": row.model_name,
                        "device": row.device,
                        "language": row.language,
                        "options_json": dict(row.options_json or {}),
                        "error_text": row.error_text,
                        "created_at": row.created_at,
                        "completed_at": row.completed_at,
                    }
                    for row in run_rows
                ]
            current_annotations = (
                timeline_annotation_rows(session, media_id=media_id)
                if media is not None
                else []
            )
            authorities = session.scalars(
                select(AuthorityRecord)
                .where(
                    AuthorityRecord.project_id == project_id,
                    AuthorityRecord.lifecycle_status == "active",
                )
                .order_by(AuthorityRecord.preferred_name, AuthorityRecord.id)
            ).all()
    finally:
        engine.dispose()

    discarded_run_summaries = [
        row for row in all_run_summaries if row.get("status") == TRANSCRIPTION_DISCARDED_STATUS
    ]
    run_summaries = [
        row for row in all_run_summaries if row.get("status") != TRANSCRIPTION_DISCARDED_STATUS
    ]

    run_by_id = {str(row["id"]): row for row in run_summaries}
    latest_run = run_summaries[0] if run_summaries else None
    selected_run = None
    selected_run_id = None
    run_state_key = f"av_run_id_{media_id}"
    if run_summaries:
        pending_run = st.session_state.pop("av_pending_run_id", None)
        if pending_run in run_by_id:
            st.session_state[run_state_key] = pending_run
        current_run = st.session_state.get(run_state_key)
        if current_run not in run_by_id:
            st.session_state[run_state_key] = str(run_summaries[0]["id"])
        if len(run_summaries) > 1:
            selected_run_id = st.selectbox(
                "Versión de transcripción que querés revisar",
                options=list(run_by_id),
                format_func=lambda value: _run_label(run_by_id[value]),
                key=run_state_key,
            )
        else:
            selected_run_id = str(run_summaries[0]["id"])
            st.session_state[run_state_key] = selected_run_id
        selected_run = run_by_id[selected_run_id]

    segments = []
    if selected_run_id is not None:
        segment_engine = create_sqlite_engine(db_path)
        try:
            with session_scope(segment_engine) as session:
                segments = transcript_segment_rows(session, run_id=selected_run_id)
        finally:
            segment_engine.dispose()

    segment_by_id = {row.segment_id: row for row in segments}
    selected_segment = None
    if segments:
        pending_segment = st.session_state.pop("av_pending_segment_id", None)
        segment_state_key = f"av_segment_id_{selected_run_id}"
        if pending_segment in segment_by_id:
            st.session_state[segment_state_key] = pending_segment
            st.session_state["av_pending_seek_seconds"] = float(
                segment_by_id[pending_segment].start_time
            )
        current_segment = st.session_state.get(segment_state_key)
        if current_segment not in segment_by_id:
            st.session_state[segment_state_key] = segments[0].segment_id
        selected_segment = segment_by_id[st.session_state[segment_state_key]]

    speed = st.selectbox(
        "Velocidad de reproducción",
        options=_SPEEDS,
        index=_SPEEDS.index(float(st.session_state.get("av_playback_speed", 1.0)))
        if float(st.session_state.get("av_playback_speed", 1.0)) in _SPEEDS
        else 2,
        format_func=lambda value: f"{value:g}×",
        key="av_playback_speed",
    )

    seek_to = st.session_state.pop("av_pending_seek_seconds", None)
    sync_action = None
    if playback_path is None:
        if media_row.local_path is None:
            st.warning(
                "El archivo audiovisual original no está disponible en esta copia del proyecto. "
                "La transcripción, las anotaciones y los metadatos guardados siguen disponibles; "
                "la reproducción y las operaciones que requieren el medio original quedan deshabilitadas."
            )
        else:
            st.warning(
                "Este formato está registrado, pero necesita una copia técnica para reproducción en el navegador."
            )
            if st.button("Preparar copia para reproducción", type="primary"):
                result = _run_db_action(
                    st,
                    db_path=db_path,
                    callback=lambda session: ensure_playback_asset(
                        session,
                        project_root=project_root,
                        media_id=media_id,
                        actor=actor,
                    ),
                )
                if result is not None:
                    st.session_state["av_flash"] = "Copia de reproducción preparada."
                    rerun_view(st)
    elif selected_run is not None and selected_run["status"] == "completed" and segments:
        player_col, review_col = st.columns([1.02, 0.98], gap="large")
        with player_col:
            _render_player(
                st,
                path=playback_path,
                media_type=media_row.media_type,
                start_time=float(seek_to or 0.0),
                speed=float(speed),
                seek_to=float(seek_to) if seek_to is not None else None,
            )
            if seek_to is not None:
                st.caption(f"Posición del reproductor: {format_timestamp(float(seek_to))}")
        with review_col:
            sync_action = synchronized_media_review(
                segments,
                current_annotations,
                authorities,
                key=f"av_sync_review_{selected_run_id}",
            )
    else:
        _render_player(
            st,
            path=playback_path,
            media_type=media_row.media_type,
            start_time=float(seek_to or 0.0),
            speed=float(speed),
            seek_to=float(seek_to) if seek_to is not None else None,
        )
        if seek_to is not None:
            st.caption(f"Posición del reproductor: {format_timestamp(float(seek_to))}")

    if sync_action is not None:
        action_kind = str(sync_action.get("kind") or "")
        action_time = max(0.0, float(sync_action.get("time") or 0.0))
        action_label = str(sync_action.get("label") or "").strip()
        st.session_state["av_pending_seek_seconds"] = action_time
        if action_kind == "speaker":
            authority_id = (
                str(sync_action["authority_id"])
                if sync_action.get("authority_id")
                else None
            )
            speaker_scope = str(sync_action.get("scope") or "segment")
            target_segment = _segment_for_time(segments, action_time)
            if speaker_scope == "segment":
                if target_segment is None:
                    st.error("No pude asociar el hablante con el segmento seleccionado.")
                    result = None
                else:
                    result = _run_db_action(
                        st,
                        db_path=db_path,
                        callback=lambda session: assign_speaker_to_segment(
                            session,
                            media_id=media_id,
                            start_time=float(target_segment.start_time),
                            end_time=float(target_segment.end_time),
                            label=action_label,
                            authority_id=authority_id,
                            actor=actor,
                        ),
                    )
                success_message = "Hablante asignado sólo al segmento seleccionado."
            else:
                result = _run_db_action(
                    st,
                    db_path=db_path,
                    callback=lambda session: assign_speaker_from_time(
                        session,
                        media_id=media_id,
                        time_seconds=action_time,
                        label=action_label,
                        authority_id=authority_id,
                        actor=actor,
                    ),
                )
                success_message = (
                    "Hablante asignado desde este punto hasta la próxima marca de hablante."
                )
            if result is not None:
                st.session_state["av_flash"] = success_message
                rerun_view(st)
        elif action_kind == "annotation":
            target_segment = _segment_for_time(segments, action_time)
            if target_segment is None:
                st.error("No pude asociar la anotación con un tramo de la transcripción.")
            else:
                result = _run_db_action(
                    st,
                    db_path=db_path,
                    callback=lambda session: create_timeline_annotation(
                        session,
                        media_id=media_id,
                        annotation_type="annotation",
                        start_time=float(target_segment.start_time),
                        end_time=float(target_segment.end_time),
                        label=action_label,
                        authority_id=None,
                        actor=actor,
                    ),
                )
                if result is not None:
                    st.session_state["av_flash"] = (
                        f"Anotación agregada en {format_timestamp(action_time)}."
                    )
                    rerun_view(st)

    if latest_run is None:
        st.info("Este audio o video todavía no tiene una transcripción.")
    elif selected_run and selected_run["status"] == "failed":
        st.error(
            "La versión de transcripción seleccionada no pudo completarse: "
            + (str(selected_run.get("error_text") or "sin diagnóstico"))
        )
    elif selected_run and not segments:
        st.warning("La versión de transcripción seleccionada terminó sin fragmentos de texto.")

    if selected_run is not None and selected_run["status"] == "completed" and segments:
        transcript_engine = create_sqlite_engine(db_path)
        try:
            with session_scope(transcript_engine) as session:
                current_transcript = transcript_document_text(
                    session, run_id=str(selected_run_id)
                )
        finally:
            transcript_engine.dispose()

        st.subheader("Texto completo de la transcripción")
        editor_key = f"av_transcript_editor_{selected_run_id}"
        if editor_key not in st.session_state:
            st.session_state[editor_key] = current_transcript
        with st.form(f"av_transcript_form_{selected_run_id}", enter_to_submit=False):
            transcript_text = st.text_area(
                "Texto completo de esta transcripción",
                key=editor_key,
                height=520,
            )
            save_transcript = st.form_submit_button(
                "Guardar las correcciones de esta transcripción", type="primary"
            )
        if save_transcript:
            result = _run_db_action(
                st,
                db_path=db_path,
                callback=lambda session: update_transcript_document(
                    session,
                    run_id=str(selected_run_id),
                    corrected_text=transcript_text,
                    actor=actor,
                ),
            )
            if result is not None:
                st.session_state["av_flash"] = (
                    "Transcripción guardada. "
                    f"Se actualizaron {result.changed_segment_count} de "
                    f"{result.total_segment_count} anclajes temporales."
                )
                rerun_view(st)

    segment_annotation_open = False
    if segments:
        segment_annotation_key = f"av_segment_annotation_open_{selected_run_id}"
        if segment_annotation_key not in st.session_state:
            st.session_state[segment_annotation_key] = False
        segment_annotation_open = st.toggle(
            "Registrar entidades mencionadas en un fragmento de la transcripción",
            key=segment_annotation_key,
        )
        if segment_annotation_open:
            st.caption(
                "Usá este panel para elegir un fragmento concreto de la transcripción y registrar qué persona, organización, lugar u otra entidad se menciona allí. "
                "La reproducción y el salto al momento correspondiente se manejan en el panel principal."
            )
            segment_state_key = f"av_segment_id_{selected_run_id}"
            segment_id = st.selectbox(
                "Fragmento de la transcripción que querés anotar",
                options=list(segment_by_id),
                format_func=lambda value: _segment_label(segment_by_id[value]),
                key=segment_state_key,
            )
            selected_segment = segment_by_id[segment_id]
            st.text_area(
                "Texto del segmento seleccionado",
                value=selected_segment.text,
                height=100,
                disabled=True,
                key=f"av_segment_preview_{selected_segment.segment_id}_{selected_segment.revision_number}",
            )
            _render_segment_mentions(
                st,
                db_path=db_path,
                selected_segment=selected_segment,
                authorities=authorities,
                actor=actor,
            )

    if selected_run_id is not None and segments:
        manage_key = f"av_manage_annotations_{media_id}"
        if manage_key not in st.session_state:
            st.session_state[manage_key] = False
        if st.toggle("Revisar marcas temporales, hablantes y anotaciones ya registradas", key=manage_key):
            st.caption(
                "Las nuevas marcas temporales se crean junto al reproductor. "
                "Este panel permite revisar o archivar las marcas, hablantes y anotaciones que ya fueron registrados para este audio o video."
            )
            annotation_engine = create_sqlite_engine(db_path)
            try:
                with session_scope(annotation_engine) as session:
                    current_annotations = timeline_annotation_rows(session, media_id=media_id)
                    marked_transcript = transcript_with_timeline_marks(
                        session, run_id=str(selected_run_id)
                    )
            finally:
                annotation_engine.dispose()

            if current_annotations:
                st.write("**Marcas registradas**")
                st.dataframe(
                    [
                        {
                            "tipo": "Hablante" if row.annotation_type == "speaker" else "Anotación",
                            "inicio": format_timestamp(row.start_time),
                            "fin": format_timestamp(row.end_time),
                            "texto": row.label,
                            "entidad vinculada": row.authority_name or "Sin entidad vinculada",
                        }
                        for row in current_annotations
                    ],
                    hide_index=True,
                    use_container_width=True,
                )
                annotation_by_id = {row.annotation_id: row for row in current_annotations}
                annotation_id = st.selectbox(
                    "Marca temporal que querés revisar",
                    options=list(annotation_by_id),
                    format_func=lambda value: _timeline_annotation_label(annotation_by_id[value]),
                    key=f"av_annotation_existing_{media_id}",
                )
                if st.button("Archivar esta marca temporal", key=f"av_archive_annotation_{media_id}"):
                    result = _run_db_action(
                        st,
                        db_path=db_path,
                        callback=lambda session: archive_timeline_annotation(
                            session,
                            annotation_id=annotation_id,
                            actor=actor,
                        ),
                    )
                    if result is not None:
                        st.session_state["av_flash"] = "Marca temporal archivada."
                        rerun_view(st)
                st.text_area(
                    "Transcripción con hablantes y anotaciones",
                    value=marked_transcript,
                    height=320,
                    disabled=True,
                    key=f"av_marked_transcript_{selected_run_id}_{len(current_annotations)}",
                )
            else:
                st.info(
                    "Todavía no hay marcas. Pausá el medio y agregalas desde Revisión sincronizada."
                )

    metadata_open = st.toggle(
        "Editar la descripción de este audio o video",
        value=False,
        key=f"av_metadata_open_{media_id}",
    )
    if metadata_open:
        st.write("**Descripción registrada para este audio o video**")
        title = st.text_input("Título del audio o video", value=(media.title if media else None) or "")
        producer = st.text_input("Productor o creador del audio o video", value=(media.producer if media else None) or "")
        channel = st.text_input("Canal o cuenta de publicación", value=(media.channel if media else None) or "")
        responsible = st.text_input("Responsable del registro de este material", value=(media.responsible if media else None) or "")
        provenance = st.text_input("Procedencia del audio o video", value=(media.provenance if media else None) or "")
        recorded_date = st.date_input(
            "Fecha de registro, producción o publicación",
            value=media.recorded_date if media and media.recorded_date else None,
            min_value=DATE_INPUT_MIN,
            max_value=DATE_INPUT_MAX,
            format="DD/MM/YYYY",
            help="Fecha de registro, producción o publicación cuando sea conocida.",
        )
        rights = st.text_input("Derechos o condiciones de uso", value=(media.rights if media else None) or "")
        description = st.text_area("Descripción del contenido del audio o video", value=(media.description if media else None) or "")
        if st.button("Guardar la descripción de este audio o video"):
            result = _run_db_action(
                st,
                db_path=db_path,
                callback=lambda session: update_audiovisual_description(
                    session,
                    media_id=media_id,
                    description=AudiovisualDescription(
                        title=title,
                        producer=producer,
                        channel=channel,
                        responsible=responsible,
                        provenance=provenance,
                        recorded_date=recorded_date if isinstance(recorded_date, date) else None,
                        rights=rights,
                        description=description,
                    ),
                    actor=actor,
                ),
            )
            if result is not None:
                st.session_state["av_flash"] = "Descripción del audio o video guardada."
                rerun_view(st)

    backend_options = transcription_backend_keys()
    backend = backend_options[0] if backend_options else "faster_whisper"

    if latest_run is None:
        button_type = "primary" if selected_segment is None else "secondary"
        if st.button("Transcribir en CPU", type=button_type):
            result = _run_db_action(
                st,
                db_path=db_path,
                callback=lambda session: transcribe_audiovisual(
                    session,
                    project_root=project_root,
                    media_id=media_id,
                    request=TranscriptionRequest(
                        backend=backend,
                        model_name="small",
                        device="cpu",
                        language="es",
                        options={
                            "compute_type": "int8",
                            "vad_filter": True,
                            "beam_size": 5,
                            "hotwords": "",
                        },
                    ),
                    actor=actor,
                ),
            )
            if result is not None:
                st.session_state["av_pending_run_id"] = result.id
                if result.status == "completed":
                    st.session_state["av_flash"] = "Transcripción completada y segmentada."
                else:
                    st.session_state["av_flash"] = (
                        "La nueva versión de la transcripción quedó registrada con un error; revisá el diagnóstico técnico."
                    )
                rerun_view(st)

    with st.popover(
        "Opciones avanzadas para crear otra transcripción",
        use_container_width=True,
        on_change="ignore",
    ):
        model_name = "small"
        device = "cpu"
        language = "es"
        compute_type = "int8"
        beam_size = 5
        vad_filter = True
        hotwords = ""
        st.caption(
            "Estas opciones sólo son necesarias si querés generar otra versión de la transcripción con un modelo o una configuración diferente. "
            "La transcripción y las marcas de revisión quedan vinculadas al audio o video incorporado al proyecto."
        )
        if len(backend_options) > 1:
            backend = st.selectbox(
                "Método de reconocimiento de voz",
                options=backend_options,
                index=0,
                key=f"av_backend_{media_id}",
            )
        else:
            st.caption(f"Método técnico disponible para el reconocimiento de voz: {backend}")

        model_options = transcription_model_names(backend) or ("small",)
        model_key = f"av_model_{media_id}"
        if st.session_state.get(model_key) not in model_options:
            st.session_state[model_key] = "small" if "small" in model_options else model_options[0]
        model_name = st.selectbox(
            "Modelo de reconocimiento de voz",
            options=model_options,
            key=model_key,
            help="Elegí uno de los modelos admitidos por el motor de transcripción.",
        )
        runtime_variant = managed_runtime_variant()
        if runtime_variant == "cpu":
            device_options = ("cpu",)
        elif runtime_variant == "gpu":
            device_options = ("cuda", "cpu")
        else:
            device_options = ("cpu", "cuda")

        device_help = None
        if runtime_variant == "cpu":
            device_help = (
                "Esta instalación se ejecuta con la imagen CPU; "
                "el reconocimiento de voz usa el procesador."
            )
        elif runtime_variant == "gpu":
            device_help = (
                "Esta instalación se ejecuta con la imagen GPU; CUDA aparece primero "
                "y CPU queda disponible como alternativa."
            )
        device = st.selectbox(
            "Equipo que realizará el reconocimiento",
            options=device_options,
            index=0,
            format_func=lambda value: "Procesador (CPU)" if value == "cpu" else "Placa NVIDIA (CUDA)",
            key=f"av_device_{media_id}",
            help=device_help,
        )
        language = st.text_input("Idioma (código, opcional)", value="es", key=f"av_language_{media_id}")

        compute_options = transcription_compute_types(device)
        preferred_compute = (
            "float16" if device == "cuda" and "float16" in compute_options
            else "int8" if "int8" in compute_options
            else compute_options[0]
        )
        compute_key = f"av_compute_type_{media_id}"
        if st.session_state.get(compute_key) not in compute_options:
            st.session_state[compute_key] = preferred_compute
        compute_labels = {
            "float16": "float16 - recomendado para GPU NVIDIA compatible",
            "int8_float16": "int8_float16 - menor uso de memoria en GPU",
            "int8": "int8 - menor uso de memoria",
            "float32": "float32 - mayor precisión numérica, mayor uso de memoria",
            "int8_float32": "int8_float32 - INT8 con cálculo FP32",
            "int16": "int16",
            "bfloat16": "bfloat16",
        }
        compute_type = st.selectbox(
            "Precisión de cálculo del modelo",
            options=compute_options,
            format_func=lambda value: compute_labels.get(value, value),
            key=compute_key,
            help="Las opciones se obtienen del dispositivo y de CTranslate2 cuando está disponible.",
        )
        hotwords = st.text_input(
            "Vocabulario esperado (opcional)",
            key=f"av_hotwords_{media_id}",
            help=(
                "Nombres propios o expresiones que esperás escuchar. Se usan como pistas para "
                "el reconocimiento y quedan registrados con esta versión de la transcripción."
            ),
        )
        advanced_key = f"av_recognition_advanced_{media_id}"
        if st.toggle("Ajustes avanzados del reconocimiento", value=False, key=advanced_key):
            beam_size = int(
                st.number_input(
                    "Cantidad de alternativas que compara el decodificador",
                    min_value=1,
                    max_value=20,
                    value=5,
                    step=1,
                    key=f"av_beam_size_{media_id}",
                    help="Corresponde a beam_size. El valor histórico usado en el piloto es 5.",
                )
            )
            vad_filter = st.checkbox(
                "Detectar automáticamente los tramos con voz (VAD)",
                value=True,
                key=f"av_vad_filter_{media_id}",
            )
        st.caption(
            "La configuración usada para crear cada versión de la transcripción queda registrada para poder comparar después sus resultados sobre el mismo audio."
        )
        button_type = "primary" if selected_segment is None else "secondary"
        if st.button("Iniciar nueva transcripción", type=button_type):
            result = _run_db_action(
                st,
                db_path=db_path,
                callback=lambda session: transcribe_audiovisual(
                    session,
                    project_root=project_root,
                    media_id=media_id,
                    request=TranscriptionRequest(
                        backend=backend,
                        model_name=model_name,
                        device=device,
                        language=(language.strip() or None),
                        options={
                            "compute_type": compute_type,
                            "vad_filter": bool(vad_filter),
                            "beam_size": int(beam_size),
                            "hotwords": hotwords.strip(),
                        },
                    ),
                    actor=actor,
                ),
            )
            if result is not None:
                st.session_state["av_pending_run_id"] = result.id
                if result.status == "completed":
                    st.session_state["av_flash"] = "Transcripción completada y segmentada."
                else:
                    st.session_state["av_flash"] = (
                        "La nueva versión de la transcripción quedó registrada con un error; revisá el diagnóstico técnico."
                    )
                rerun_view(st)

    if selected_run is not None and selected_run["status"] == "completed":
        evaluation_key = f"av_evaluation_open_{selected_run_id}"
        if evaluation_key not in st.session_state:
            st.session_state[evaluation_key] = False
        evaluation_open = st.toggle(
            "Evaluar la calidad de esta versión de la transcripción",
            key=evaluation_key,
        )
        if evaluation_open:
            evaluation_engine = create_sqlite_engine(db_path)
            try:
                with session_scope(evaluation_engine) as session:
                    evaluation = evaluate_transcription_run(
                        session, run_id=str(selected_run_id), sample_size=5
                    )
            finally:
                evaluation_engine.dispose()

            st.write("**Tiempo y uso de memoria de esta transcripción automática**")
            if evaluation.device == "cuda":
                perf_a, perf_b, perf_c, perf_d = st.columns(4)
            else:
                perf_a, perf_b, perf_c = st.columns(3)
                perf_d = None
            perf_a.metric("Tiempo de transcripción", _format_seconds(evaluation.wall_seconds))
            perf_b.metric(
                "Tiempo de procesamiento respecto de la duración del audio",
                _format_duration_share(evaluation.realtime_factor),
            )
            perf_c.metric(
                "Pico de memoria RAM durante la transcripción",
                _format_memory(evaluation.peak_rss_mib),
            )
            if evaluation.device == "cuda" and perf_d is not None:
                perf_d.metric(
                    "Pico de memoria GPU durante la transcripción",
                    _format_memory(evaluation.peak_gpu_memory_mib),
                )
            elif evaluation.average_cpu_cores is not None:
                st.caption(
                    f"Uso medio de CPU durante la transcripción: {evaluation.average_cpu_cores:.2f} núcleos equivalentes."
                )
            st.caption(
                "El porcentaje de tiempo compara cuánto tardó el procesamiento con la duración del audio: "
                "100 % significa que tardó lo mismo que dura el audio; 50 % significa que tardó la mitad."
            )

            st.write("**Cómo quedó dividida la transcripción**")
            seg_a, seg_b, seg_c = st.columns(3)
            seg_a.metric("Segmentos de texto", evaluation.segment_count)
            seg_b.metric(
                "Duración típica de un segmento",
                _format_seconds(evaluation.median_segment_seconds),
            )
            seg_c.metric("Tiempo sin texto entre segmentos", _format_seconds(evaluation.total_gap_seconds))
            st.caption(
                f"Segmentos muy cortos (<0,75 s): {evaluation.short_segment_count} · "
                f"segmentos largos (>15 s): {evaluation.long_segment_count} · "
                f"segmentos sin texto: {evaluation.empty_segment_count}."
            )

            st.write("**Cinco fragmentos revisados para comparar transcripciones**")
            st.caption(
                "La aplicación conserva cinco fragmentos distribuidos a lo largo de esta transcripción. "
                "Las correcciones guardadas en esos fragmentos se usan como referencia para comparar "
                "la calidad de distintas transcripciones del mismo audio sin volver a revisar todo el audio."
            )
            st.progress(
                (evaluation.reviewed_sample_count / evaluation.sample_size)
                if evaluation.sample_size
                else 0.0,
                text=(
                    f"Fragmentos revisados: {evaluation.reviewed_sample_count} de {evaluation.sample_size}"
                ),
            )
            if evaluation.sample:
                st.dataframe(
                    [
                        {
                            "Fragmento": item.ordinal,
                            "Inicio": format_timestamp(item.start_time),
                            "Fin": format_timestamp(item.end_time),
                            "Estado": "Revisada" if item.reviewed else "Pendiente",
                        }
                        for item in evaluation.sample
                    ],
                    hide_index=True,
                    use_container_width=True,
                )

            if evaluation.reviewed_sample_count:
                st.caption(
                    "Estos porcentajes comparan la salida automática con la referencia revisada sólo en estos cinco fragmentos. "
                    "Un valor menor indica menos diferencias; 0 % significa coincidencia exacta en la muestra. "
                    "No se comparan aquí transcripciones externas completas."
                )
                qual_a, qual_b = st.columns(2)
                qual_a.metric(
                    "Caracteres diferentes respecto de la referencia",
                    "No disponible" if evaluation.sample_cer is None else f"{evaluation.sample_cer * 100:.1f} %",
                )
                qual_b.metric(
                    "Palabras diferentes respecto de la referencia",
                    "No disponible" if evaluation.sample_wer is None else f"{evaluation.sample_wer * 100:.1f} %",
                )
            st.download_button(
                "Descargar evaluación de transcripción",
                data=evaluation.to_json_bytes(),
                file_name=f"evaluacion_transcripcion_{selected_run_id}.json",
                mime="application/json",
                key=f"av_evaluation_download_{selected_run_id}",
            )

            comparison_open = st.toggle(
                "Comparar esta versión con otra transcripción del mismo audio",
                value=False,
                key=f"av_compare_open_{selected_run_id}",
            )
            if comparison_open:
                st.caption(
                    "La comparación reutiliza exactamente las cinco referencias revisadas que ya existen "
                    "para este audio. No requiere volver a corregir esa muestra."
                )
                reference_engine = create_sqlite_engine(db_path)
                try:
                    with session_scope(reference_engine) as session:
                        reference_run_id = reviewed_reference_run_id(
                            session, media_id=media_id, sample_size=5
                        )
                finally:
                    reference_engine.dispose()

                quality_profile = "av03_quality_gpu_large_v3_v1"
                quality_runs = [
                    row
                    for row in run_summaries
                    if (row.get("options_json") or {}).get("_av03_profile") == quality_profile
                ]
                quality_run = quality_runs[0] if quality_runs else None

                default_hotwords: list[str] = []
                for authority in authorities[:8]:
                    name = str(authority.preferred_name).strip()
                    if name and name not in default_hotwords:
                        default_hotwords.append(name)
                if platform_origin:
                    channel = str(platform_origin.get("channel") or "").strip()
                    if channel and channel not in default_hotwords:
                        default_hotwords.append(channel)
                hotwords_value = st.text_input(
                    "Vocabulario esperado (opcional)",
                    value=", ".join(default_hotwords),
                    help=(
                        "Nombres propios y expresiones esperables que pueden ayudar al modelo. "
                        "No se insertan automáticamente en el texto."
                    ),
                    key=f"av_quality_hotwords_{media_id}",
                )

                selected_is_large_gpu = (
                    str(selected_run.get("model_name") or "") == "large-v3"
                    and str(selected_run.get("device") or "") == "cuda"
                )
                if selected_is_large_gpu:
                    st.info(
                        "La versión seleccionada ya fue creada con large-v3 en GPU. Si querés comparar una configuración diferente, generá otra transcripción desde las opciones avanzadas."
                    )
                elif quality_run is None or quality_run.get("status") == "failed":
                    if quality_run is not None and quality_run.get("error_text"):
                        st.warning(
                            "La transcripción anterior creada para comparar con large-v3 en GPU no pudo completarse: "
                            + str(quality_run["error_text"])
                        )
                    if st.button(
                        "Generar comparación con large-v3 en GPU",
                        key=f"av_quality_run_{media_id}",
                    ):
                        try:
                            import ctranslate2

                            cuda_devices = int(ctranslate2.get_cuda_device_count())
                        except Exception as exc:
                            st.error(
                                "No pude comprobar el acceso de faster-whisper a la GPU. "
                                f"Detalle: {exc}"
                            )
                            cuda_devices = 0
                        if cuda_devices < 1:
                            st.error(
                                "faster-whisper no detecta una GPU CUDA disponible en este entorno. "
                                "La línea de base CPU permanece válida."
                            )
                        else:
                            with st.spinner(
                                "Transcribiendo con large-v3 en GPU. La primera vez puede descargar el modelo…"
                            ):
                                result = _run_db_action(
                                    st,
                                    db_path=db_path,
                                    callback=lambda session: transcribe_audiovisual(
                                        session,
                                        project_root=project_root,
                                        media_id=media_id,
                                        request=TranscriptionRequest(
                                            backend="faster_whisper",
                                            model_name="large-v3",
                                            device="cuda",
                                            language="es",
                                            options={
                                                "compute_type": "float16",
                                                "vad_filter": True,
                                                "beam_size": 5,
                                                "hotwords": hotwords_value.strip(),
                                                "_av03_profile": quality_profile,
                                            },
                                        ),
                                        actor=actor,
                                    ),
                                )
                            if result is not None:
                                st.session_state["av_pending_run_id"] = result.id
                                st.session_state[f"av_evaluation_open_{result.id}"] = True
                                if result.status == "completed":
                                    st.session_state["av_flash"] = (
                                        "Transcripción para comparar con large-v3 en GPU completada."
                                    )
                                else:
                                    st.session_state["av_flash"] = (
                                        "La transcripción para comparar con large-v3 en GPU quedó registrada con un error; revisá su mensaje de diagnóstico."
                                    )
                                rerun_view(st)
                elif reference_run_id is not None:
                    quality_run_id = str(quality_run["id"])
                    comparison_engine = create_sqlite_engine(db_path)
                    try:
                        with session_scope(comparison_engine) as session:
                            baseline_eval = evaluate_transcription_run(
                                session, run_id=reference_run_id, sample_size=5
                            )
                            quality_eval = evaluate_transcription_run(
                                session, run_id=quality_run_id, sample_size=5
                            )
                            baseline_cmp = compare_transcription_to_reviewed_reference(
                                session,
                                reference_run_id=reference_run_id,
                                candidate_run_id=reference_run_id,
                                sample_size=5,
                            )
                            quality_cmp = compare_transcription_to_reviewed_reference(
                                session,
                                reference_run_id=reference_run_id,
                                candidate_run_id=quality_run_id,
                                sample_size=5,
                            )
                            baseline_original_text = original_transcript_text(
                                session, run_id=reference_run_id
                            )
                            quality_original_text = original_transcript_text(
                                session, run_id=quality_run_id
                            )
                    finally:
                        comparison_engine.dispose()

                    st.dataframe(
                        [
                            {
                                "Versión de transcripción": "Referencia revisada",
                                "Modelo de reconocimiento de voz": baseline_eval.model_name,
                                "Equipo que realizará el reconocimiento": baseline_eval.device,
                                "Tiempo": _format_seconds(baseline_eval.wall_seconds),
                                "Tiempo de procesamiento / duración del audio": (
                                    _format_duration_share(baseline_eval.realtime_factor)
                                ),
                                "Caracteres diferentes en los cinco fragmentos revisados": (
                                    "No disponible" if baseline_cmp.cer is None else f"{baseline_cmp.cer * 100:.1f} %"
                                ),
                                "Palabras diferentes en los cinco fragmentos revisados": (
                                    "No disponible" if baseline_cmp.wer is None else f"{baseline_cmp.wer * 100:.1f} %"
                                ),
                            },
                            {
                                "Versión de transcripción": "large-v3 en GPU",
                                "Modelo de reconocimiento de voz": quality_eval.model_name,
                                "Equipo que realizará el reconocimiento": quality_eval.device,
                                "Tiempo": _format_seconds(quality_eval.wall_seconds),
                                "Tiempo de procesamiento / duración del audio": (
                                    _format_duration_share(quality_eval.realtime_factor)
                                ),
                                "Caracteres diferentes en los cinco fragmentos revisados": "No disponible",
                                "Palabras diferentes en los cinco fragmentos revisados": "No disponible",
                            },
                        ],
                        hide_index=True,
                        use_container_width=True,
                    )
                    if quality_eval.peak_gpu_memory_mib is not None:
                        st.caption(
                            "Pico de memoria de GPU al crear la transcripción con large-v3: "
                            + _format_memory(quality_eval.peak_gpu_memory_mib)
                        )
                    st.caption(
                        "La transcripción usada como referencia permite calcular diferencias exactas en los cinco fragmentos revisados. "
                        "La versión creada con large-v3 divide el audio en fragmentos temporales diferentes y ninguna de estas versiones guarda tiempos por palabra; "
                        "por eso no se calcula un porcentaje artificial recortando el texto con ayuda de la referencia revisada. "
                        "Para large-v3 se muestra el contexto automático que realmente se superpone con cada fragmento y la "
                        "transcripción original completa."
                    )

                    with st.expander("Ver comparación de los cinco fragmentos revisados", expanded=False):
                        rows_for_display = []
                        for baseline_window, quality_window in zip(
                            baseline_cmp.windows, quality_cmp.windows, strict=True
                        ):
                            rows_for_display.append(
                                {
                                    "Fragmento": baseline_window.ordinal,
                                    "Inicio": format_timestamp(baseline_window.start_time),
                                    "Fin": format_timestamp(baseline_window.end_time),
                                    "Referencia revisada": baseline_window.reference_text,
                                    f"Salida automática de {baseline_eval.model_name}": baseline_window.candidate_text,
                                    "Salida large-v3 en el mismo tramo temporal": quality_window.candidate_context_text,
                                    "Palabras diferentes respecto de la referencia": (
                                        "No disponible"
                                        if baseline_window.wer is None
                                        else f"{baseline_window.wer * 100:.1f} %"
                                    ),
                                }
                            )
                        st.dataframe(
                            rows_for_display,
                            hide_index=True,
                            use_container_width=True,
                        )
                        st.caption(
                            "El texto de large-v3 es el contexto original de todos los segmentos que se superponen "
                            "con cada fragmento revisado. No se recorta usando el contenido de la referencia revisada."
                        )

                    full_transcripts_open = st.toggle(
                        "Ver transcripciones automáticas completas",
                        value=False,
                        key=f"av_full_transcripts_{reference_run_id}_{quality_run_id}",
                    )
                    if full_transcripts_open:
                        left, right = st.columns(2)
                        with left:
                            st.write(f"**Versión de referencia · {baseline_eval.model_name} · transcripción automática original**")
                            st.text_area(
                                f"Transcripción automática original de {baseline_eval.model_name}",
                                value=baseline_original_text,
                                height=420,
                                disabled=True,
                                key=f"av_cmp_baseline_original_{reference_run_id}",
                                label_visibility="collapsed",
                            )
                            st.download_button(
                                f"Descargar {baseline_eval.model_name} original",
                                data=(baseline_original_text + "\n").encode("utf-8"),
                                file_name=f"transcripcion_{baseline_eval.model_name}_original.txt",
                                mime="text/plain",
                                key=f"av_cmp_baseline_download_{reference_run_id}",
                            )
                        with right:
                            st.write("**large-v3 en GPU · salida original**")
                            st.text_area(
                                "Transcripción automática original de large-v3",
                                value=quality_original_text,
                                height=420,
                                disabled=True,
                                key=f"av_cmp_quality_original_{quality_run_id}",
                                label_visibility="collapsed",
                            )
                            st.download_button(
                                "Descargar large-v3 original",
                                data=(quality_original_text + "\n").encode("utf-8"),
                                file_name="transcripcion_large_v3_original.txt",
                                mime="text/plain",
                                key=f"av_cmp_quality_download_{quality_run_id}",
                            )

    if selected_run is not None and selected_run.get("status") == "completed":
        discard_run_open = st.toggle(
            "Descartar esta versión de la transcripción",
            value=False,
            key=f"av_discard_run_open_{selected_run_id}",
        )
        if discard_run_open:
            st.caption(
                "Usá esta acción sólo si esta versión se creó por error o no debe seguir participando del trabajo. "
                "El audio o video original y las demás versiones de la transcripción se conservan."
            )
            with st.form(f"av_discard_run_{selected_run_id}", enter_to_submit=False):
                discard_note = st.text_input(
                    "Motivo del descarte (opcional)",
                    placeholder="Por ejemplo: transcripción duplicada",
                )
                discard_confirmed = st.checkbox(
                    "Confirmo que quiero descartar esta versión de la transcripción"
                )
                discard_submit = st.form_submit_button("Descartar esta versión de la transcripción")
            if discard_submit:
                if not discard_confirmed:
                    st.error("Confirmá el descarte antes de continuar.")
                else:
                    result = _run_db_action(
                        st,
                        db_path=db_path,
                        callback=lambda session: discard_transcription_run(
                            session,
                            run_id=str(selected_run_id),
                            actor=actor,
                            note=discard_note or None,
                        ),
                    )
                    if result is not None:
                        st.session_state.pop(run_state_key, None)
                        st.session_state["av_flash"] = (
                            "Transcripción descartada. Se conserva en el historial y puede restaurarse."
                        )
                        rerun_view(st)

    if discarded_run_summaries:
        discarded_runs_open = st.toggle(
            f"Transcripciones descartadas ({len(discarded_run_summaries)})",
            value=False,
            key=f"av_discarded_runs_open_{media_id}",
        )
        if discarded_runs_open:
            st.caption(
                "Estas versiones se conservan como historial y no participan en la búsqueda ni en las exportaciones. "
                "Podés restaurar una versión si el descarte fue un error."
            )
            for discarded in discarded_run_summaries:
                with st.container(border=True):
                    info_col, restore_col = st.columns([4, 1])
                    with info_col:
                        st.write(_run_label(discarded))
                    with restore_col:
                        if st.button(
                            "Restaurar esta versión de la transcripción",
                            key=f"av_restore_run_{discarded['id']}",
                            use_container_width=True,
                        ):
                            result = _run_db_action(
                                st,
                                db_path=db_path,
                                callback=lambda session, run_id=str(discarded["id"]): restore_transcription_run(
                                    session, run_id=run_id, actor=actor
                                ),
                            )
                            if result is not None:
                                st.session_state["av_pending_run_id"] = str(discarded["id"])
                                st.session_state["av_flash"] = "Transcripción restaurada."
                                rerun_view(st)

    with st.expander("Datos técnicos e historial de este audio o video", expanded=False):
        if media is not None:
            st.write(
                {
                    "formato": media.container_format,
                    "duración_s": media.duration_seconds,
                    "audio_codec": media.audio_codec,
                    "video_codec": media.video_codec,
                    "canales": media.channels,
                    "frecuencia_hz": media.sample_rate_hz,
                    "resolución": (
                        f"{media.width}×{media.height}" if media.width and media.height else None
                    ),
                    "fps": media.frame_rate,
                }
            )
        if platform_origin:
            publication = platform_origin.get("publication")
            if not isinstance(publication, dict):
                publication = {
                    "platform": platform_origin.get("platform"),
                    "platform_id": platform_origin.get("platform_id"),
                    "webpage_url": platform_origin.get("webpage_url"),
                    "title": platform_origin.get("title"),
                    "channel": platform_origin.get("channel") or platform_origin.get("uploader"),
                    "upload_date": platform_origin.get("upload_date"),
                }
            st.write("**Publicación en la plataforma**")
            st.write(
                {
                    "plataforma": publication.get("platform"),
                    "id": publication.get("platform_id"),
                    "url": publication.get("webpage_url"),
                    "título": publication.get("title"),
                    "canal": publication.get("channel"),
                    "fecha_publicación": publication.get("upload_date"),
                }
            )
            grouping = platform_origin.get("platform_grouping")
            if isinstance(grouping, dict):
                st.write("**Agrupación en la plataforma**")
                st.caption(
                    "Se conserva como contexto externo de publicación y no se transforma automáticamente "
                    "en una Colección, Serie u otra unidad del catálogo."
                )
                st.write(
                    {
                        "título": grouping.get("title"),
                        "id": grouping.get("platform_id"),
                        "url": grouping.get("webpage_url"),
                        "posición": grouping.get("index"),
                        "cantidad_elementos": grouping.get("item_count"),
                    }
                )
            local_copy = platform_origin.get("local_copy")
            if not isinstance(local_copy, dict):
                local_copy = {
                    "relative_path": platform_origin.get("incorporated_relative_path"),
                    "extension": platform_origin.get("incorporated_extension"),
                    "sha256": platform_origin.get("incorporated_sha256"),
                    "byte_size": platform_origin.get("incorporated_byte_size"),
                }
            st.write("**Copia incorporada al proyecto**")
            st.write(
                {
                    "ruta": local_copy.get("relative_path"),
                    "formato": local_copy.get("extension"),
                    "sha256": local_copy.get("sha256"),
                    "bytes": local_copy.get("byte_size"),
                    "condiciones_acceso": platform_origin.get("access_conditions"),
                    "yt_dlp": platform_origin.get("yt_dlp_version"),
                }
            )
        if selected_run is not None:
            run_options = dict(selected_run["options_json"] or {})
            st.write("**Configuración usada para la versión de transcripción seleccionada**")
            st.write(
                {
                    "identificador_transcripción": selected_run["id"],
                    "estado": selected_run["status"],
                    "motor": selected_run["backend"],
                    "versión_motor": selected_run["backend_version"],
                    "modelo": selected_run["model_name"],
                    "dispositivo": selected_run["device"],
                    "tipo_cálculo": run_options.get("compute_type"),
                    "idioma": selected_run["language"],
                    "beam_size": run_options.get("beam_size", 5),
                    "detección_voz_vad": run_options.get("vad_filter", True),
                    "vocabulario_esperado": run_options.get("hotwords") or None,
                    "error": selected_run["error_text"],
                }
            )
        if selected_segment is not None:
            history_engine = create_sqlite_engine(db_path)
            try:
                with session_scope(history_engine) as session:
                    history = segment_revision_rows(
                        session, segment_id=selected_segment.segment_id
                    )
            finally:
                history_engine.dispose()
            if history:
                st.write("**Historial del segmento**")
                st.dataframe(
                    [
                        {
                            "revisión": item.revision_number,
                            "acción": "Estado inicial" if item.operation == "baseline" else "Corrección",
                            "responsable": item.changed_by,
                            "nota": item.note or "",
                            "fecha": item.changed_at,
                        }
                        for item in history
                    ],
                    hide_index=True,
                    use_container_width=True,
                )


def render_audiovisual_view(
    st,
    *,
    project_root: Path,
    db_path: Path,
    project_id: str,
    actor: str,
) -> None:
    section_heading(st, "Audio y video")

    flash = st.session_state.pop("av_flash", None)
    if flash:
        st.success(flash)

    incorporate_tab, review_tab = tracked_tabs(
        st,
        ["Incorporar audio o video", "Transcribir y revisar"],
        key="audiovisual_tabs",
        default="Transcribir y revisar",
        rerun_on_change=False,
        help_by_label=TAB_HELP["audiovisual_tabs"],
    )
    with incorporate_tab:
        _render_audiovisual_import(
            st,
            project_root=project_root,
            db_path=db_path,
            project_id=project_id,
            actor=actor,
        )
    with review_tab:
        _render_transcription_workspace(
            st,
            project_root=project_root,
            db_path=db_path,
            project_id=project_id,
            actor=actor,
        )
