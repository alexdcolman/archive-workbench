from __future__ import annotations

from pathlib import Path
import json
import wave
import zipfile

import yaml
from sqlalchemy import inspect, select

from archive_workbench.audiovisual import (
    audiovisual_media_rows,
    create_segment_mention,
    export_transcript_segments_bytes,
    register_transcription_backend,
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
    assert current_revision(root) == "0045_audiovisual_transcription"
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


def test_audiovisual_ui_exposes_simple_review_flow_and_hidden_technical_options() -> None:
    root = Path(__file__).parents[1]
    audiovisual_ui = (root / "src" / "archive_workbench" / "audiovisual_app.py").read_text(
        encoding="utf-8"
    )
    review_ui = (root / "src" / "archive_workbench" / "review_app.py").read_text(encoding="utf-8")
    export_ui = (root / "src" / "archive_workbench" / "export_app.py").read_text(encoding="utf-8")

    for literal in (
        "Transcribir audio y video",
        "Medio",
        "Segmento",
        "Velocidad de reproducción",
        "Ir al inicio del segmento",
        "Corrección del segmento",
        "Texto corregido",
        "Estado de revisión",
        "Guardar corrección",
        "Editar datos descriptivos",
        "Opciones técnicas",
        "Anotar entidades en este segmento",
        "Guardar mención",
        "Datos técnicos e historial",
    ):
        assert literal in audiovisual_ui
    assert '"Opciones técnicas",\n        value=False,' in audiovisual_ui
    assert '"Editar datos descriptivos",\n        value=False,' in audiovisual_ui
    assert '"Anotar entidades en este segmento",\n            value=False,' in audiovisual_ui
    assert 'button_type = "primary" if selected_segment is None else "secondary"' in audiovisual_ui
    assert '"Transcribir audio y video"' in review_ui
    assert '"Transcripciones de audio y video"' in review_ui
    assert '"Segmentos de audio y video"' in export_ui
    assert '"Descargar segmentos audiovisuales"' in export_ui


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
