from __future__ import annotations

from datetime import date
from pathlib import Path
from urllib.parse import urlparse

from pydantic import ValidationError
from sqlalchemy import select

from archive_workbench.audiovisual import (
    REVIEW_STATUSES,
    archive_timeline_annotation,
    assign_speaker_from_time,
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
    update_audiovisual_description,
    update_transcript_segment,
)
from archive_workbench.contracts.audiovisual import AudiovisualDescription, TranscriptionRequest
from archive_workbench.db import create_sqlite_engine, session_scope
from archive_workbench.db.models import ArchivalUnit, AudiovisualMedia, AuthorityRecord, TranscriptionRun
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
from archive_workbench.ui_navigation import rerun_view

_REVIEW_LABELS = {
    "unreviewed": "Sin revisar",
    "reviewed": "Revisado",
    "approved": "Aprobado",
}
_SPEEDS = (0.5, 0.75, 1.0, 1.25, 1.5, 2.0)


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
    return f"{row['model_name']} · {device} · {row['status']} · {stamp}"


def _format_seconds(value: float | None) -> str:
    if value is None:
        return "—"
    if value < 60:
        return f"{value:.1f} s"
    minutes, seconds = divmod(value, 60)
    return f"{int(minutes)} min {seconds:.1f} s"


def _format_memory(value: float | None) -> str:
    return "—" if value is None else f"{value:.0f} MiB"


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


def render_audiovisual_view(
    st,
    *,
    project_root: Path,
    db_path: Path,
    project_id: str,
    actor: str,
) -> None:
    st.header("Transcribir audio y video")
    st.caption(
        "Reproducí un medio, saltá al segmento vigente y corregí la transcripción sin alterar el original."
    )

    flash = st.session_state.pop("av_flash", None)
    if flash:
        st.success(flash)

    platform_open = st.toggle(
        "Incorporar desde plataforma",
        value=False,
        key="av_platform_import_open",
    )
    if platform_open:
        platform_engine = create_sqlite_engine(db_path)
        try:
            with session_scope(platform_engine) as session:
                units = session.scalars(
                    select(ArchivalUnit)
                    .where(ArchivalUnit.project_id == project_id)
                    .order_by(ArchivalUnit.title, ArchivalUnit.id)
                ).all()
        finally:
            platform_engine.dispose()
        unit_by_id = {row.id: row for row in units}
        runtime = platform_runtime_status()
        if not runtime.yt_dlp_available:
            st.error(
                "La extensión de incorporación desde plataformas no está instalada. "
                "Instalá el extra `platform`."
            )
        elif not runtime.ffmpeg_available or not runtime.ffprobe_available:
            st.error("AV-02 requiere FFmpeg y FFprobe disponibles en PATH.")
        elif not (runtime.deno_available or runtime.node_available):
            st.error(
                "YouTube requiere un runtime JavaScript compatible. "
                "El extra `platform` instala Deno; verificá que quede disponible en PATH."
            )
        elif not unit_by_id:
            st.warning("El proyecto todavía no tiene una unidad archivística de destino.")
        else:
            st.caption(
                "Incorpora un material autorizado y lo registra como archivo local de AV-01. "
                "No inicia ninguna transcripción automáticamente."
            )
            with st.form("av_platform_import_form", enter_to_submit=False):
                platform_url = st.text_input(
                    "URL del audio o video",
                    placeholder="https://www.youtube.com/watch?v=…",
                )
                platform_unit = st.selectbox(
                    "Unidad archivística",
                    options=list(unit_by_id),
                    format_func=lambda value: unit_by_id[value].title,
                )
                platform_kind = st.radio(
                    "Tipo de incorporación",
                    options=("video", "audio"),
                    format_func=lambda value: "Video" if value == "video" else "Solo audio",
                    horizontal=True,
                )
                access_conditions = st.text_area(
                    "Condiciones de acceso / autorización",
                    placeholder="Indicá por qué este material puede incorporarse al proyecto.",
                    height=90,
                )
                authorization = st.checkbox(
                    "Confirmo que el proyecto está autorizado a incorporar este material"
                )
                submitted = st.form_submit_button("Incorporar desde plataforma", type="primary")
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
                            result = _run_db_action(
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
                        if result is not None:
                            st.session_state["av_pending_media_id"] = result.media_id
                            st.session_state["av_flash"] = (
                                f"Material incorporado desde {result.platform}: {result.title}. "
                                "El archivo quedó registrado en el circuito local de AV-01."
                            )
                            rerun_view(st)

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
            "Todavía no hay audio o video registrado. Incorporalo primero en "
            "Catálogo documental como archivo local."
        )
        return

    by_id = {row.media_id: row for row in media_rows}
    pending_media = st.session_state.pop("av_pending_media_id", None)
    if pending_media in by_id:
        st.session_state["av_media_id"] = pending_media
    current_media = st.session_state.get("av_media_id")
    if current_media not in by_id:
        st.session_state["av_media_id"] = media_rows[0].media_id
    media_id = st.selectbox(
        "Medio",
        options=list(by_id),
        format_func=lambda value: _media_label(by_id[value]),
        key="av_media_id",
    )
    media_row = by_id[media_id]

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
            run_summaries: list[dict[str, object]] = []
            if media is not None:
                run_rows = session.scalars(
                    select(TranscriptionRun)
                    .where(TranscriptionRun.audiovisual_media_id == media.id)
                    .order_by(TranscriptionRun.created_at.desc(), TranscriptionRun.id.desc())
                ).all()
                run_summaries = [
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

    run_by_id = {str(row["id"]): row for row in run_summaries}
    latest_run = run_summaries[0] if run_summaries else None
    selected_run = None
    selected_run_id = None
    if run_summaries:
        pending_run = st.session_state.pop("av_pending_run_id", None)
        run_state_key = f"av_run_id_{media_id}"
        if pending_run in run_by_id:
            st.session_state[run_state_key] = pending_run
        current_run = st.session_state.get(run_state_key)
        if current_run not in run_by_id:
            st.session_state[run_state_key] = str(run_summaries[0]["id"])
        if len(run_summaries) > 1:
            selected_run_id = st.selectbox(
                "Corrida",
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
        navigation_key = f"av_navigation_open_{selected_run_id}"
        if pending_segment in segment_by_id:
            st.session_state[segment_state_key] = pending_segment
            st.session_state[navigation_key] = True
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
                st.session_state["av_flash"] = "Copia de reproducción preparada; el original permanece intacto."
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
            st.caption(
                "Reproducí o pausá normalmente. La transcripción de la derecha acompaña el tiempo actual."
            )
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
            result = _run_db_action(
                st,
                db_path=db_path,
                callback=lambda session: assign_speaker_from_time(
                    session,
                    media_id=media_id,
                    time_seconds=action_time,
                    label=action_label,
                    authority_id=(
                        str(sync_action["authority_id"])
                        if sync_action.get("authority_id")
                        else None
                    ),
                    actor=actor,
                ),
            )
            if result is not None:
                st.session_state["av_flash"] = (
                    f"Hablante asignado desde {format_timestamp(action_time)}."
                )
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
        st.info("Este medio todavía no tiene una transcripción.")
    elif selected_run and selected_run["status"] == "failed":
        st.error(
            "La corrida seleccionada falló: "
            + (str(selected_run.get("error_text") or "sin diagnóstico"))
        )
    elif selected_run and not segments:
        st.warning("La corrida seleccionada terminó sin segmentos.")

    if selected_run is not None and selected_run["status"] == "completed" and segments:
        transcript_engine = create_sqlite_engine(db_path)
        try:
            with session_scope(transcript_engine) as session:
                current_transcript = transcript_document_text(
                    session, run_id=str(selected_run_id)
                )
        finally:
            transcript_engine.dispose()

        st.subheader("Transcripción")
        st.caption(
            "Revisá y corregí el texto completo en un solo lugar. "
            "Los tiempos siguen conservados por debajo para navegación, búsqueda y exportación."
        )
        editor_key = f"av_transcript_editor_{selected_run_id}"
        if editor_key not in st.session_state:
            st.session_state[editor_key] = current_transcript
        with st.form(f"av_transcript_form_{selected_run_id}", enter_to_submit=False):
            transcript_text = st.text_area(
                "Transcripción completa",
                key=editor_key,
                height=520,
            )
            save_transcript = st.form_submit_button(
                "Guardar transcripción", type="primary"
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

    navigation_open = False
    if segments:
        navigation_key = f"av_navigation_open_{selected_run_id}"
        if navigation_key not in st.session_state:
            st.session_state[navigation_key] = False
        navigation_open = st.toggle(
            "Navegar por tiempos y segmentos",
            key=navigation_key,
        )
        if navigation_open:
            segment_state_key = f"av_segment_id_{selected_run_id}"
            segment_id = st.selectbox(
                "Segmento temporal",
                options=list(segment_by_id),
                format_func=lambda value: _segment_label(segment_by_id[value]),
                key=segment_state_key,
            )
            selected_segment = segment_by_id[segment_id]
            st.caption(
                f"{format_timestamp(selected_segment.start_time)}–"
                f"{format_timestamp(selected_segment.end_time)}"
            )
            if st.button("Ir al inicio del segmento"):
                st.session_state["av_pending_seek_seconds"] = float(
                    selected_segment.start_time
                )
                rerun_view(st)
            st.text_area(
                "Texto alineado en este tramo",
                value=selected_segment.text,
                height=100,
                disabled=True,
                key=f"av_segment_preview_{selected_segment.segment_id}_{selected_segment.revision_number}",
            )

    if selected_run_id is not None and segments:
        manage_key = f"av_manage_annotations_{media_id}"
        if manage_key not in st.session_state:
            st.session_state[manage_key] = False
        if st.toggle("Gestionar anotaciones y hablantes", key=manage_key):
            st.caption(
                "La creación cotidiana se hace junto al reproductor. "
                "Acá podés revisar o archivar las marcas ya registradas."
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
                            "autoridad": row.authority_name or "—",
                        }
                        for row in current_annotations
                    ],
                    hide_index=True,
                    use_container_width=True,
                )
                annotation_by_id = {row.annotation_id: row for row in current_annotations}
                annotation_id = st.selectbox(
                    "Marca existente",
                    options=list(annotation_by_id),
                    format_func=lambda value: _timeline_annotation_label(annotation_by_id[value]),
                    key=f"av_annotation_existing_{media_id}",
                )
                if st.button("Archivar marca", key=f"av_archive_annotation_{media_id}"):
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
        "Editar datos descriptivos",
        value=False,
        key=f"av_metadata_open_{media_id}",
    )
    if metadata_open:
        st.write("**Datos descriptivos**")
        title = st.text_input("Título", value=(media.title if media else None) or "")
        producer = st.text_input("Productor", value=(media.producer if media else None) or "")
        channel = st.text_input("Canal", value=(media.channel if media else None) or "")
        responsible = st.text_input("Responsable", value=(media.responsible if media else None) or "")
        provenance = st.text_input("Procedencia", value=(media.provenance if media else None) or "")
        recorded_date = st.date_input(
            "Fecha",
            value=media.recorded_date if media and media.recorded_date else None,
        )
        rights = st.text_input("Derechos", value=(media.rights if media else None) or "")
        description = st.text_area("Descripción", value=(media.description if media else None) or "")
        if st.button("Guardar datos descriptivos"):
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
                st.session_state["av_flash"] = "Datos descriptivos guardados."
                rerun_view(st)

    technical_open = st.toggle(
        "Opciones técnicas",
        value=False,
        key=f"av_technical_open_{media_id}",
    )
    backend = "faster_whisper"
    model_name = "small"
    device = "cpu"
    language = "es"
    compute_type = "int8"
    if technical_open:
        st.caption("Estos parámetros solo afectan una nueva corrida; el original no se modifica.")
        backend = st.selectbox(
            "Backend",
            options=transcription_backend_keys(),
            index=0,
            key=f"av_backend_{media_id}",
        )
        model_name = st.text_input("Modelo", value="small", key=f"av_model_{media_id}")
        device = st.selectbox(
            "Dispositivo",
            options=("cpu", "cuda"),
            index=0,
            format_func=lambda value: "Procesador (CPU)" if value == "cpu" else "Placa NVIDIA (CUDA)",
            key=f"av_device_{media_id}",
        )
        language = st.text_input("Idioma (código, opcional)", value="es", key=f"av_language_{media_id}")
        compute_type = st.text_input(
            "Tipo de cálculo",
            value="int8" if device == "cpu" else "float16",
            key=f"av_compute_type_{media_id}",
        )

    show_default_transcription = latest_run is None and not technical_open
    show_advanced_transcription = technical_open
    if show_default_transcription or show_advanced_transcription:
        button_label = "Transcribir en CPU" if show_default_transcription else "Iniciar nueva transcripción"
        button_type = "primary" if selected_segment is None else "secondary"
        if st.button(button_label, type=button_type):
            effective_device = device if technical_open else "cpu"
            effective_compute = compute_type if technical_open else "int8"
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
                        device=effective_device,
                        language=(language.strip() or None),
                        options={"compute_type": effective_compute, "vad_filter": True},
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
                        "La corrida quedó registrada con error; revisá el diagnóstico técnico."
                    )
                rerun_view(st)

    if selected_run is not None and selected_run["status"] == "completed":
        evaluation_key = f"av_evaluation_open_{selected_run_id}"
        if evaluation_key not in st.session_state:
            st.session_state[evaluation_key] = False
        evaluation_open = st.toggle(
            "Evaluar transcripción",
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

            st.write("**Rendimiento de la corrida**")
            perf_a, perf_b, perf_c = st.columns(3)
            perf_a.metric("Tiempo de transcripción", _format_seconds(evaluation.wall_seconds))
            perf_b.metric(
                "Factor tiempo-real",
                "—" if evaluation.realtime_factor is None else f"{evaluation.realtime_factor:.3f}×",
            )
            perf_c.metric("Memoria máxima observada", _format_memory(evaluation.peak_rss_mib))
            if evaluation.device == "cuda":
                st.caption(
                    "Memoria máxima GPU observada: "
                    + _format_memory(evaluation.peak_gpu_memory_mib)
                )
            elif evaluation.average_cpu_cores is not None:
                st.caption(
                    f"Trabajo CPU medio durante la corrida: {evaluation.average_cpu_cores:.2f} núcleos equivalentes."
                )

            st.write("**Segmentación**")
            seg_a, seg_b, seg_c = st.columns(3)
            seg_a.metric("Segmentos", evaluation.segment_count)
            seg_b.metric(
                "Duración mediana",
                _format_seconds(evaluation.median_segment_seconds),
            )
            seg_c.metric("Huecos entre segmentos", _format_seconds(evaluation.total_gap_seconds))
            st.caption(
                f"Segmentos muy cortos (<0,75 s): {evaluation.short_segment_count} · "
                f"segmentos largos (>15 s): {evaluation.long_segment_count} · "
                f"segmentos sin texto: {evaluation.empty_segment_count}."
            )

            st.write("**Muestra reproducible de corrección humana**")
            st.caption(
                "La muestra conserva cinco anclajes repartidos de forma determinista a lo largo de la corrida. "
                "Sirve para comparar calidad sin convertir cada segmento en una tarea de edición."
            )
            st.progress(
                (evaluation.reviewed_sample_count / evaluation.sample_size)
                if evaluation.sample_size
                else 0.0,
                text=(
                    f"Revisados {evaluation.reviewed_sample_count} de {evaluation.sample_size} segmentos de muestra"
                ),
            )
            if evaluation.sample:
                st.dataframe(
                    [
                        {
                            "Muestra": item.ordinal,
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
                    "CER/WER de corrección comparan la salida automática con tu corrección humana "
                    "solo sobre los segmentos de muestra revisados; no son una verdad terreno externa."
                )
                qual_a, qual_b = st.columns(2)
                qual_a.metric(
                    "CER de corrección",
                    "—" if evaluation.sample_cer is None else f"{evaluation.sample_cer:.3f}",
                )
                qual_b.metric(
                    "WER de corrección",
                    "—" if evaluation.sample_wer is None else f"{evaluation.sample_wer:.3f}",
                )
            st.download_button(
                "Descargar evaluación AV-03",
                data=evaluation.to_json_bytes(),
                file_name=f"evaluacion_transcripcion_{selected_run_id}.json",
                mime="application/json",
                key=f"av_evaluation_download_{selected_run_id}",
            )

            st.write("**Comparar reconocimiento**")
            st.caption(
                "La comparación reutiliza exactamente las cinco referencias humanas ya revisadas. "
                "No requiere volver a corregir la muestra."
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

            if quality_run is None or quality_run.get("status") == "failed":
                if quality_run is not None and quality_run.get("error_text"):
                    st.warning(
                        "La prueba anterior de mayor calidad no pudo completarse: "
                        + str(quality_run["error_text"])
                    )
                if st.button(
                    "Probar reconocimiento de mayor calidad (GPU)",
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
                                    "Prueba de reconocimiento de mayor calidad completada."
                                )
                            else:
                                st.session_state["av_flash"] = (
                                    "La prueba de mayor calidad quedó registrada con error; "
                                    "revisá el mensaje de la corrida."
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
                            "Corrida": "Línea de base",
                            "Modelo": baseline_eval.model_name,
                            "Dispositivo": baseline_eval.device,
                            "Tiempo": _format_seconds(baseline_eval.wall_seconds),
                            "RTF": (
                                "—"
                                if baseline_eval.realtime_factor is None
                                else f"{baseline_eval.realtime_factor:.3f}×"
                            ),
                            "CER muestra": (
                                "—" if baseline_cmp.cer is None else f"{baseline_cmp.cer:.3f}"
                            ),
                            "WER muestra": (
                                "—" if baseline_cmp.wer is None else f"{baseline_cmp.wer:.3f}"
                            ),
                        },
                        {
                            "Corrida": "Mayor calidad",
                            "Modelo": quality_eval.model_name,
                            "Dispositivo": quality_eval.device,
                            "Tiempo": _format_seconds(quality_eval.wall_seconds),
                            "RTF": (
                                "—"
                                if quality_eval.realtime_factor is None
                                else f"{quality_eval.realtime_factor:.3f}×"
                            ),
                            "CER muestra": "—",
                            "WER muestra": "—",
                        },
                    ],
                    hide_index=True,
                    use_container_width=True,
                )
                if quality_eval.peak_gpu_memory_mib is not None:
                    st.caption(
                        "Memoria máxima GPU observada en la corrida de mayor calidad: "
                        + _format_memory(quality_eval.peak_gpu_memory_mib)
                    )
                st.caption(
                    "La línea de base conserva CER/WER exactos sobre los cinco segmentos humanos revisados. "
                    "large-v3 usa fronteras temporales distintas y estas corridas no guardan timestamps por "
                    "palabra: por eso no se publica un CER/WER artificial recortando el texto con ayuda de la "
                    "propia referencia humana. Para large-v3 se muestra el contexto automático que realmente "
                    "solapa cada ventana y la transcripción original completa."
                )

                with st.expander("Ver comparación de las cinco referencias humanas", expanded=False):
                    rows_for_display = []
                    for baseline_window, quality_window in zip(
                        baseline_cmp.windows, quality_cmp.windows, strict=True
                    ):
                        rows_for_display.append(
                            {
                                "Muestra": baseline_window.ordinal,
                                "Inicio": format_timestamp(baseline_window.start_time),
                                "Fin": format_timestamp(baseline_window.end_time),
                                "Referencia humana": baseline_window.reference_text,
                                "small original": baseline_window.candidate_text,
                                "large-v3 · contexto temporal": quality_window.candidate_context_text,
                                "WER small": (
                                    None
                                    if baseline_window.wer is None
                                    else round(baseline_window.wer, 3)
                                ),
                            }
                        )
                    st.dataframe(
                        rows_for_display,
                        hide_index=True,
                        use_container_width=True,
                    )
                    st.caption(
                        "El texto de large-v3 es el contexto original de todos los segmentos que se solapan "
                        "con cada ventana humana. No se recorta usando el contenido de la referencia."
                    )

                with st.expander("Ver transcripciones automáticas completas", expanded=False):
                    left, right = st.columns(2)
                    with left:
                        st.write("**Línea de base · small · salida original**")
                        st.text_area(
                            "Transcripción automática original de small",
                            value=baseline_original_text,
                            height=420,
                            disabled=True,
                            key=f"av_cmp_baseline_original_{reference_run_id}",
                            label_visibility="collapsed",
                        )
                        st.download_button(
                            "Descargar small original",
                            data=(baseline_original_text + "\n").encode("utf-8"),
                            file_name="transcripcion_small_original.txt",
                            mime="text/plain",
                            key=f"av_cmp_baseline_download_{reference_run_id}",
                        )
                    with right:
                        st.write("**Mayor calidad · large-v3 · salida original**")
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

    if selected_segment is not None and navigation_open:
        mentions_open = st.toggle(
            "Anotar entidades en este segmento",
            value=False,
            key=f"av_mentions_open_{selected_segment.segment_id}",
        )
        if mentions_open:
            authority_by_id = {row.id: row for row in authorities}
            authority_options = [None, *authority_by_id]
            mention_text = st.text_input(
                "Texto de la mención",
                key=f"av_mention_text_{selected_segment.segment_id}",
            )
            authority_id = st.selectbox(
                "Autoridad existente (opcional)",
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
                "Nota de la mención (opcional)",
                key=f"av_mention_note_{selected_segment.segment_id}",
            )
            if st.button("Guardar mención"):
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
                            "autoridad": item.authority_name or "Sin vincular",
                            "estado": item.status,
                            "revisión_segmento": item.segment_revision_number,
                            "desactualizada": item.is_stale,
                        }
                        for item in mentions
                    ],
                    hide_index=True,
                    use_container_width=True,
                )

    with st.expander("Datos técnicos e historial", expanded=False):
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
            st.write("**Procedencia de plataforma**")
            st.write(
                {
                    "plataforma": platform_origin.get("platform"),
                    "id": platform_origin.get("platform_id"),
                    "url": platform_origin.get("webpage_url"),
                    "canal": platform_origin.get("channel") or platform_origin.get("uploader"),
                    "fecha_publicación": platform_origin.get("upload_date"),
                    "formato_incorporado": platform_origin.get("incorporated_extension"),
                    "sha256": platform_origin.get("incorporated_sha256"),
                    "condiciones_acceso": platform_origin.get("access_conditions"),
                    "yt_dlp": platform_origin.get("yt_dlp_version"),
                }
            )
        if selected_run is not None:
            st.write(
                {
                    "corrida": selected_run["id"],
                    "estado": selected_run["status"],
                    "backend": selected_run["backend"],
                    "versión_backend": selected_run["backend_version"],
                    "modelo": selected_run["model_name"],
                    "dispositivo": selected_run["device"],
                    "idioma": selected_run["language"],
                    "opciones": selected_run["options_json"],
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
