from __future__ import annotations

from pathlib import Path
import json
import wave
import zipfile

import yaml
from sqlalchemy import inspect, select

from archive_workbench.audiovisual import (
    TRANSCRIPTION_DISCARDED_STATUS,
    audiovisual_media_rows,
    discard_transcription_run,
    create_segment_mention,
    AudiovisualExportOptions,
    export_transcript_segments_bytes,
    preview_transcript_export,
    run_audiovisual_export,
    register_transcription_backend,
    restore_transcription_run,
    search_transcript_segments,
    transcript_segment_rows,
    transcribe_audiovisual,
    update_transcript_segment,
)
from archive_workbench.catalog import ensure_project
from archive_workbench.catalog_management import create_archival_unit, register_local_file
from archive_workbench.contracts.audiovisual import TranscriptSegmentInput, TranscriptionRequest
from archive_workbench.db import (
    create_sqlite_engine,
    current_revision,
    database_path,
    session_scope,
    upgrade_database,
)
from archive_workbench.db.models import AudiovisualMedia, DigitalObject, TranscriptSegmentRevision
from archive_workbench.corpus_export import export_run_rows
from archive_workbench.decisions import load_decisions
from archive_workbench.inspection import detect_media_type, inspect_input
from archive_workbench.processing import processing_inventory_rows
from archive_workbench.project_init import initialize_project
from archive_workbench.domain.enums import MediaType
from archive_workbench.identity import new_id, sha256_file
from archive_workbench.exchange import ensure_exchange_workspace
from archive_workbench.state_adoption import create_state_adoption_package


class _FakeBackend:
    key = "test_backend"

    def version(self) -> str:
        return "test-1"

    def transcribe(self, source: Path, *, model_name: str, device: str, language, options):
        assert source.suffix == ".wav"
        assert device == "cpu"
        return [
            TranscriptSegmentInput(start_time=0.0, end_time=0.5, text="Archivo de prueba"),
            TranscriptSegmentInput(start_time=0.5, end_time=1.0, text="Memoria y documentos"),
        ]


def _write_wav(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rate = 16000
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(rate)
        output.writeframes(b"\x00\x00" * rate)


def _project(tmp_path: Path):
    root = tmp_path / "project"
    config_root = Path(__file__).parents[1] / "config"
    initialize_project(root, template_root=config_root)
    decisions_path = root / "config" / "decisions.yaml"
    data = yaml.safe_load(decisions_path.read_text(encoding="utf-8"))
    data["project_id"] = "av01_test_project"
    data["project_name"] = "Proyecto AV-01"
    decisions_path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    upgrade_database(root)
    decisions = load_decisions(decisions_path)
    audio = root / "corpus" / "audiovisual" / "control.wav"
    _write_wav(audio)
    engine = create_sqlite_engine(database_path(root))
    with session_scope(engine) as session:
        ensure_project(session, decisions)
        root_level = next(
            level
            for level in sorted(decisions.archival_levels, key=lambda item: item.display_order)
            if level.enabled and not level.parent_keys
        )
        unit = create_archival_unit(
            session,
            decisions=decisions,
            project_id=decisions.project_id,
            parent_id=None,
            level_key=root_level.key,
            title="Audiovisual",
            created_by="test",
        )
        result = register_local_file(
            session,
            project_root=root,
            project_id=decisions.project_id,
            archival_unit_id=unit.id,
            relative_path=audio.relative_to(root).as_posix(),
            registered_by="test",
        )
    return root, decisions, engine, result, audio


def test_media_detection_supports_audio_and_video_extensions(tmp_path: Path) -> None:
    audio = tmp_path / "sample.wav"
    _write_wav(audio)
    video = tmp_path / "sample.mkv"
    video.write_bytes(b"not-a-real-video")
    assert detect_media_type(audio) == MediaType.AUDIO
    assert detect_media_type(video) == MediaType.VIDEO
    inspection = inspect_input(audio)
    assert inspection.media_type == MediaType.AUDIO
    assert inspection.page_count is None


def test_audiovisual_migration_adds_temporal_tables(tmp_path: Path) -> None:
    root = tmp_path / "project"
    upgrade_database(root, revision="0044_layout_structure_review")
    assert current_revision(root) == "0044_layout_structure_review"
    upgrade_database(root)
    assert current_revision(root) == "0047_authority_relation_profiles"
    engine = create_sqlite_engine(database_path(root))
    try:
        tables = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()
    assert {
        "audiovisual_media",
        "audiovisual_derivative_assets",
        "transcription_runs",
        "transcript_segments",
        "transcript_segment_revisions",
        "segment_entity_mentions",
        "audiovisual_timeline_annotations",
        "audiovisual_timeline_annotation_revisions",
    } <= tables


def test_audio_registration_transcription_review_search_export_and_ocr_exclusion(tmp_path: Path) -> None:
    root, decisions, engine, result, audio = _project(tmp_path)
    original_hash = sha256_file(audio)
    register_transcription_backend(_FakeBackend())
    try:
        with session_scope(engine) as session:
            digital = session.get(DigitalObject, result.digital_object_id)
            assert digital is not None
            assert digital.media_type == "audio"
            media = session.scalar(
                select(AudiovisualMedia).where(AudiovisualMedia.digital_object_id == digital.id)
            )
            assert media is not None
            assert media.duration_seconds is not None
            assert media.audio_codec == "pcm_s16le"
            assert processing_inventory_rows(
                session, project_root=root, project_id=decisions.project_id
            ) == []
            run = transcribe_audiovisual(
                session,
                project_root=root,
                media_id=media.id,
                request=TranscriptionRequest(
                    backend="test_backend",
                    model_name="fixture",
                    device="cpu",
                    language="es",
                    options={"compute_type": "int8"},
                ),
                actor="test",
            )
            assert run.status == "completed"
            assert run.options_json["compute_type"] == "int8"
            assert run.options_json["beam_size"] == 5
            assert run.options_json["vad_filter"] is True
            segments = transcript_segment_rows(session, run_id=run.id)
            assert len(segments) == 2
            edited = update_transcript_segment(
                session,
                segment_id=segments[1].segment_id,
                corrected_text="Memoria, voces y documentos",
                review_status="reviewed",
                actor="alex",
                note="Corrección controlada",
            )
            assert edited.revision_number == 2
            create_segment_mention(
                session,
                segment_id=edited.id,
                mention_text="Memoria",
                authority_id=None,
                status="pending",
                actor="alex",
            )
            revisions = session.scalars(
                select(TranscriptSegmentRevision)
                .where(TranscriptSegmentRevision.segment_id == edited.id)
                .order_by(TranscriptSegmentRevision.revision_number)
            ).all()
            assert [row.revision_number for row in revisions] == [1, 2]
            hits = search_transcript_segments(
                session,
                project_id=decisions.project_id,
                query="voces",
            )
            assert len(hits) == 1
            assert hits[0].segment_id == edited.id
            payload, count = export_transcript_segments_bytes(
                session,
                project_id=decisions.project_id,
                output_format="jsonl",
            )
            assert count == 2
            text = payload.decode("utf-8")
            assert "Memoria, voces y documentos" in text
            assert original_hash in text
            rows = audiovisual_media_rows(
                session, project_root=root, project_id=decisions.project_id
            )
            assert len(rows) == 1
            assert rows[0].segment_count == 2

            ensure_exchange_workspace(
                session, workspace_name="copia-av-origen", changed_by="test"
            )
            package = create_state_adoption_package(
                session,
                project_root=root,
                target_workspace_id=new_id(),
                target_workspace_name="copia-av-destino",
                created_by="test",
                creation_reason="Validar transporte del estado audiovisual",
                package_confirmed=True,
                destination=root / "exchange" / "av_state_test.zip",
            )
            with zipfile.ZipFile(package.output_path) as archive:
                manifest = json.loads(archive.read("manifest.json"))
                state = json.loads(archive.read("state.json"))
            assert manifest["schema_version"] == "1.1"
            assert len(state["audiovisual_media"]) == 1
            assert len(state["transcription_runs"]) == 1
            assert len(state["transcript_segments"]) == 2
            assert len(state["transcript_segment_revisions"]) == 3
            assert len(state["segment_entity_mentions"]) == 1
    finally:
        engine.dispose()
    assert sha256_file(audio) == original_hash



def test_discarded_transcription_is_removed_from_normal_use_and_can_be_restored(tmp_path: Path) -> None:
    root, decisions, engine, result, _audio = _project(tmp_path)
    register_transcription_backend(_FakeBackend())
    try:
        with session_scope(engine) as session:
            media = session.scalar(
                select(AudiovisualMedia).where(
                    AudiovisualMedia.digital_object_id == result.digital_object_id
                )
            )
            assert media is not None
            run = transcribe_audiovisual(
                session,
                project_root=root,
                media_id=media.id,
                request=TranscriptionRequest(
                    backend="test_backend",
                    model_name="fixture",
                    device="cpu",
                    language="es",
                    options={"compute_type": "int8"},
                ),
                actor="alex",
            )
            assert len(
                search_transcript_segments(
                    session, project_id=decisions.project_id, query="Memoria"
                )
            ) == 1

            discarded = discard_transcription_run(
                session, run_id=run.id, actor="alex", note="Versión duplicada"
            )
            assert discarded.status == TRANSCRIPTION_DISCARDED_STATUS
            history = discarded.options_json["_lifecycle_history"]
            assert history[-1]["action"] == "discard"
            assert history[-1]["note"] == "Versión duplicada"
            assert search_transcript_segments(
                session, project_id=decisions.project_id, query="Memoria"
            ) == []
            _payload, count = export_transcript_segments_bytes(
                session, project_id=decisions.project_id, output_format="jsonl"
            )
            assert count == 0
            media_rows = audiovisual_media_rows(
                session, project_root=root, project_id=decisions.project_id
            )
            assert media_rows[0].latest_run_id is None
            assert media_rows[0].segment_count == 0

            restored = restore_transcription_run(session, run_id=run.id, actor="alex")
            assert restored.status == "completed"
            assert restored.options_json["_lifecycle_history"][-1]["action"] == "restore"
            assert len(
                search_transcript_segments(
                    session, project_id=decisions.project_id, query="Memoria"
                )
            ) == 1
            _payload, count = export_transcript_segments_bytes(
                session, project_id=decisions.project_id, output_format="jsonl"
            )
            assert count == 2
    finally:
        engine.dispose()

def test_audiovisual_ui_separates_incorporation_from_transcription_and_keeps_secondary_tools_progressive() -> None:
    root = Path(__file__).parents[1]
    audiovisual_ui = (root / "src" / "archive_workbench" / "audiovisual_app.py").read_text(
        encoding="utf-8"
    )
    review_ui = (root / "src" / "archive_workbench" / "review_app.py").read_text(encoding="utf-8")
    export_ui = (root / "src" / "archive_workbench" / "export_app.py").read_text(encoding="utf-8")

    for literal in (
        'section_heading(st, "Audio y video")',
        '"Incorporar audio o video", "Transcribir y revisar"',
        'key="audiovisual_tabs"',
        'rerun_on_change=False',
        '"Desde esta computadora"',
        '"Desde una plataforma web"',
        '"Formatos admitidos desde esta computadora. "',
        '"Elegir archivos de audio o video"',
        '"Incorporar los archivos seleccionados"',
        'register_external_file(',
        'import_platform_media(',
        '"Abrir este audio o video para transcribirlo"',
        "Audio o video que querés transcribir o revisar",
        "Velocidad de reproducción",
        "Transcripción completa",
        "Guardar las correcciones de esta transcripción",
        "Revisión sincronizada",
        "Editar la descripción de este audio o video",
        "Opciones avanzadas para crear otra transcripción",
        "Registrar entidades mencionadas en un fragmento de la transcripción",
        "Datos técnicos e historial",
        "Comparar esta versión con otra transcripción del mismo audio",
        "Descartar esta versión de la transcripción",
        "Transcripciones descartadas",
        "Restaurar esta versión de la transcripción",
    ):
        assert literal in audiovisual_ui

    assert 'with st.popover(\n        "Opciones avanzadas para crear otra transcripción"' in audiovisual_ui
    assert 'on_change="ignore"' in audiovisual_ui
    assert 'technical_open = st.toggle(' not in audiovisual_ui
    assert 'av_platform_import_open' not in audiovisual_ui
    assert 'Incorporalo primero en Catálogo documental como archivo local' not in audiovisual_ui
    assert 'with st.expander("Descartar esta versión de la transcripción"' not in audiovisual_ui
    assert 'with st.expander(\n            f"Transcripciones descartadas' not in audiovisual_ui
    assert 'with st.expander("Ver transcripciones automáticas completas"' not in audiovisual_ui
    assert 'discard_run_open = st.toggle(' in audiovisual_ui
    assert 'discarded_runs_open = st.toggle(' in audiovisual_ui
    assert 'full_transcripts_open = st.toggle(' in audiovisual_ui
    assert '"Audio y video"' in review_ui
    assert '"Transcripciones de audio y video"' in review_ui
    assert '"Segmentos de audio y video"' in export_ui
    assert '"Descargar esta exportación"' in export_ui


def test_audiovisual_supported_format_caption_uses_canonical_extension_sets() -> None:
    from archive_workbench.audiovisual import AUDIO_EXTENSIONS, VIDEO_EXTENSIONS
    from archive_workbench.audiovisual_app import _format_supported_extensions

    audio = _format_supported_extensions(AUDIO_EXTENSIONS)
    video = _format_supported_extensions(VIDEO_EXTENSIONS)

    assert audio == "AAC, AIF, AIFF, ALAC, FLAC, M4A, MP3, OGG, OPUS, WAV, WMA"
    assert video == "AVI, M2TS, M4V, MKV, MOV, MP4, MPEG, MPG, MTS, TS, WEBM, WMV"


def test_audiovisual_player_control_script_seeks_and_preserves_speed() -> None:
    from archive_workbench.audiovisual_app import _media_control_script

    script = _media_control_script(rate=1.5, seek_to=2.4)

    assert "const rate = 1.5" in script
    assert "const seekTo = 2.4" in script
    assert "element.currentTime = seekTo" in script
    assert "element.playbackRate = rate" in script


def test_pending_app_mode_accepts_audiovisual_navigation() -> None:
    from types import SimpleNamespace

    from archive_workbench.review_app import _apply_pending_app_mode

    st = SimpleNamespace(
        session_state={"review_pending_app_mode": "audiovisual", "review_app_mode": "search"}
    )
    _apply_pending_app_mode(st)

    assert st.session_state["review_app_mode"] == "audiovisual"
    assert "review_pending_app_mode" not in st.session_state


def test_faster_whisper_ui_uses_known_models_and_supported_compute_types() -> None:
    from archive_workbench.audiovisual import (
        transcription_compute_types,
        transcription_model_names,
    )

    models = transcription_model_names("faster_whisper")
    assert models == (
        "tiny",
        "base",
        "small",
        "medium",
        "large-v1",
        "large-v2",
        "large-v3",
        "turbo",
    )
    assert "int8" in transcription_compute_types("cpu")
    assert "float16" in transcription_compute_types("cuda")

    source = (
        Path(__file__).parents[1] / "src" / "archive_workbench" / "audiovisual_app.py"
    ).read_text(encoding="utf-8")
    assert 'model_name = st.selectbox(' in source
    assert 'compute_type = st.selectbox(' in source
    assert 'compute_type = st.text_input(' not in source
    assert 'model_name = st.text_input(' not in source
    assert '"tipo_cálculo": run_options.get("compute_type")' in source
    assert '"beam_size": run_options.get("beam_size", 5)' in source
    assert '"detección_voz_vad": run_options.get("vad_filter", True)' in source
    assert '"Vocabulario esperado (opcional)"' in source
    assert '"Cantidad de alternativas que compara el decodificador"' in source
    assert '"Detectar automáticamente los tramos con voz (VAD)"' in source
    assert '"hotwords": hotwords_value' in source
    assert '"beam_size": int(beam_size)' in source
    assert '"vad_filter": bool(vad_filter)' in source


def test_audiovisual_visible_copy_hides_internal_block_codes_and_supports_historical_dates() -> None:
    source = (
        Path(__file__).parents[1] / "src" / "archive_workbench" / "audiovisual_app.py"
    ).read_text(encoding="utf-8")
    assert "circuito local de AV-01" not in source
    assert "AV-02 requiere" not in source
    assert "Descargar evaluación AV-03" not in source
    assert "Estas opciones sólo son necesarias si querés generar otra versión de la transcripción" in source
    assert "min_value=DATE_INPUT_MIN" in source
    assert "max_value=DATE_INPUT_MAX" in source
    assert 'format="DD/MM/YYYY"' in source


def test_audiovisual_evaluation_copy_is_explicit_and_avoids_ambiguous_labels() -> None:
    source = (
        Path(__file__).parents[1] / "src" / "archive_workbench" / "audiovisual_app.py"
    ).read_text(encoding="utf-8")
    assert "Cinco fragmentos revisados para comparar transcripciones" in source
    assert "calidad de distintas transcripciones del mismo audio" in source
    assert "Tiempo de procesamiento respecto de la duración del audio" in source
    assert "Pico de memoria RAM durante la transcripción" in source
    assert "Caracteres diferentes respecto de la referencia" in source
    assert "Palabras diferentes respecto de la referencia" in source
    assert "Factor tiempo-real" not in source
    assert "Memoria máxima observada" not in source
    assert "Muestra reproducible de corrección humana" not in source
    assert "referencias humanas" not in source
    assert "Probar reconocimiento de mayor calidad (GPU)" not in source
    assert "Generar comparación con large-v3 en GPU" in source


def test_current_user_facing_python_copy_does_not_use_humana_as_review_shorthand() -> None:
    source_root = Path(__file__).parents[1] / "src" / "archive_workbench"
    offenders = []
    for path in source_root.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "humana" in text.casefold() or "humanas" in text.casefold():
            offenders.append(path.name)
    assert offenders == []


def test_audiovisual_export_is_materialized_in_project_and_registered_in_history(tmp_path: Path) -> None:
    root, decisions, engine, _result, _audio = _project(tmp_path)
    register_transcription_backend(_FakeBackend())
    try:
        with session_scope(engine) as session:
            media = session.scalar(select(AudiovisualMedia))
            assert media is not None
            run = transcribe_audiovisual(
                session,
                project_root=root,
                media_id=media.id,
                request=TranscriptionRequest(
                    backend="test_backend",
                    model_name="fixture",
                    device="cpu",
                    language="es",
                    options={"compute_type": "int8"},
                ),
                actor="test",
            )
            segments = transcript_segment_rows(session, run_id=run.id)
            update_transcript_segment(
                session,
                segment_id=segments[1].segment_id,
                corrected_text="Memoria revisada para exportación",
                review_status="reviewed",
                actor="alex",
            )
            options = AudiovisualExportOptions(
                text_policy="corrected_fallback_original",
                include_review_statuses=("unreviewed", "reviewed"),
                run_scope="latest_completed_per_media",
                media_ids=(media.id,),
                include_timeline_annotations=True,
            )
            preview = preview_transcript_export(
                session, project_id=decisions.project_id, options=options
            )
            assert preview.total_records == 2
            result = run_audiovisual_export(
                session,
                project_root=root,
                project_id=decisions.project_id,
                options=options,
                output_relative_path="exports/transcripciones_control.jsonl",
                output_format="jsonl",
                created_by="alex",
            )
            history = export_run_rows(session, project_id=decisions.project_id)
    finally:
        engine.dispose()
    assert result.output_path == root / "exports" / "transcripciones_control.jsonl"
    rows = [json.loads(line) for line in result.output_path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 2
    assert rows[0]["export_schema_version"] == "1.1"
    assert rows[0]["record_type"] == "archive_workbench.audiovisual_transcript_segment"
    assert rows[0]["project_id"] == decisions.project_id
    assert rows[0]["export_run_id"] == result.run_id
    assert rows[0]["exported_at"]
    assert rows[0]["corpus_state_sha256"] == result.corpus_state_sha256
    assert rows[0]["export_configuration"]["run_scope"] == "latest_completed_per_media"
    assert rows[0]["source_type"]
    assert rows[0]["original_filename"] == "control.wav"
    assert rows[1]["text"] == "Memoria revisada para exportación"
    assert rows[1]["text_source"] == "corrected_transcription"
    av_history = [
        row
        for row in history
        if row.profile_snapshot.get("material_type") == "audiovisual_transcript_segments"
    ]
    assert len(av_history) == 1
    assert av_history[0].output_relative_path == "exports/transcripciones_control.jsonl"
    assert av_history[0].profile_snapshot["options"]["run_scope"] == "latest_completed_per_media"
