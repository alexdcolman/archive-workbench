from __future__ import annotations

from datetime import date
from pathlib import Path
from urllib.parse import urlparse

from pydantic import ValidationError
from sqlalchemy import select

from archive_workbench.audiovisual import (
    REVIEW_STATUSES,
    audiovisual_media_rows,
    create_segment_mention,
    ensure_playback_asset,
    export_transcript_segments_bytes,
    format_timestamp,
    resolve_playback_path,
    segment_mention_rows,
    segment_revision_rows,
    transcript_segment_rows,
    transcribe_audiovisual,
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


def _control_media_element(*, rate: float, seek_to: float | None = None) -> None:
    """Controla el elemento HTML5 ya renderizado por st.audio/st.video."""
    try:
        from streamlit.components.v1 import html as component_html
    except ImportError:  # pragma: no cover - la vista solo existe con el extra streamlit
        return
    component_html(
        _media_control_script(rate=rate, seek_to=seek_to),
        height=0,
        width=0,
    )


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
    _control_media_element(rate=speed, seek_to=seek_to)


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
            latest_run = None
            if media is not None:
                latest_run = session.scalar(
                    select(TranscriptionRun)
                    .where(TranscriptionRun.audiovisual_media_id == media.id)
                    .order_by(TranscriptionRun.created_at.desc())
                )
            segments = transcript_segment_rows(session, run_id=latest_run.id) if latest_run else []
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

    selected_segment = None
    if segments:
        segment_by_id = {row.segment_id: row for row in segments}
        pending_segment = st.session_state.pop("av_pending_segment_id", None)
        if pending_segment in segment_by_id:
            st.session_state["av_segment_id"] = pending_segment
        current_segment = st.session_state.get("av_segment_id")
        if current_segment not in segment_by_id:
            st.session_state["av_segment_id"] = segments[0].segment_id
        segment_id = st.selectbox(
            "Segmento",
            options=list(segment_by_id),
            format_func=lambda value: _segment_label(segment_by_id[value]),
            key="av_segment_id",
        )
        selected_segment = segment_by_id[segment_id]

    start_time = selected_segment.start_time if selected_segment else 0.0
    speed = st.selectbox(
        "Velocidad de reproducción",
        options=_SPEEDS,
        index=_SPEEDS.index(float(st.session_state.get("av_playback_speed", 1.0)))
        if float(st.session_state.get("av_playback_speed", 1.0)) in _SPEEDS
        else 2,
        format_func=lambda value: f"{value:g}×",
        key="av_playback_speed",
    )

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
    else:
        jump_requested = bool(
            selected_segment and st.button("Ir al inicio del segmento")
        )
        _render_player(
            st,
            path=playback_path,
            media_type=media_row.media_type,
            start_time=start_time,
            speed=float(speed),
            seek_to=start_time if jump_requested else None,
        )
        if jump_requested:
            st.caption(f"Posición del reproductor: {format_timestamp(start_time)}")

    if latest_run is None:
        st.info("Este medio todavía no tiene una transcripción.")
    elif latest_run.status == "failed":
        st.error("La última transcripción falló: " + (latest_run.error_text or "sin diagnóstico"))
    elif not segments:
        st.warning("La última corrida terminó sin segmentos.")

    if selected_segment is not None:
        st.subheader("Corrección del segmento")
        corrected = st.text_area(
            "Texto corregido",
            value=selected_segment.text,
            height=150,
            key=f"av_corrected_{selected_segment.segment_id}_{selected_segment.revision_number}",
        )
        review_status = st.selectbox(
            "Estado de revisión",
            options=REVIEW_STATUSES,
            index=REVIEW_STATUSES.index(selected_segment.review_status),
            format_func=lambda value: _REVIEW_LABELS[value],
            key=f"av_review_status_{selected_segment.segment_id}_{selected_segment.revision_number}",
        )
        correction_note = st.text_input(
            "Nota de revisión (opcional)",
            key=f"av_correction_note_{selected_segment.segment_id}_{selected_segment.revision_number}",
        )
        if st.button("Guardar corrección", type="primary"):
            result = _run_db_action(
                st,
                db_path=db_path,
                callback=lambda session: update_transcript_segment(
                    session,
                    segment_id=selected_segment.segment_id,
                    corrected_text=corrected,
                    review_status=review_status,
                    actor=actor,
                    note=correction_note or None,
                ),
            )
            if result is not None:
                st.session_state["av_pending_segment_id"] = selected_segment.segment_id
                st.session_state["av_flash"] = "Corrección guardada como una nueva revisión del segmento."
                rerun_view(st)

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
                if result.status == "completed":
                    st.session_state["av_flash"] = "Transcripción completada y segmentada."
                else:
                    st.session_state["av_flash"] = (
                        "La corrida quedó registrada con error; revisá el diagnóstico técnico."
                    )
                rerun_view(st)

    if selected_segment is not None:
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
        if latest_run is not None:
            st.write(
                {
                    "corrida": latest_run.id,
                    "estado": latest_run.status,
                    "backend": latest_run.backend,
                    "versión_backend": latest_run.backend_version,
                    "modelo": latest_run.model_name,
                    "dispositivo": latest_run.device,
                    "idioma": latest_run.language,
                    "opciones": latest_run.options_json,
                    "error": latest_run.error_text,
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
