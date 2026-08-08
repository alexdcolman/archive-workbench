from __future__ import annotations

from pathlib import Path
import shutil
from types import SimpleNamespace

import pytest
import yaml
from sqlalchemy import select

from archive_workbench.audiovisual import (
    export_transcript_segments_bytes,
    register_transcription_backend,
    transcribe_audiovisual,
)
from archive_workbench.catalog import ensure_project
from archive_workbench.catalog_management import create_archival_unit
from archive_workbench.contracts.audiovisual import TranscriptSegmentInput, TranscriptionRequest
from archive_workbench.contracts.platform import PlatformImportRequest
from archive_workbench.db import create_sqlite_engine, database_path, session_scope, upgrade_database
from archive_workbench.db.models import AudiovisualMedia, DigitalObject, SourceRegistration
from archive_workbench.decisions import load_decisions
from archive_workbench.identity import sha256_file
from archive_workbench.platform_import import (
    import_platform_media,
    platform_origin_for_digital_object,
)
from archive_workbench.project_init import initialize_project


class _Backend:
    key = "platform_test_backend"

    def version(self) -> str:
        return "1"

    def transcribe(self, source: Path, *, model_name: str, device: str, language, options):
        return [TranscriptSegmentInput(start_time=0.0, end_time=1.0, text="Video incorporado")]


def _project(tmp_path: Path):
    root = tmp_path / "project"
    config_root = Path(__file__).parents[1] / "config"
    initialize_project(root, template_root=config_root)
    decisions_path = root / "config" / "decisions.yaml"
    data = yaml.safe_load(decisions_path.read_text(encoding="utf-8"))
    data["project_id"] = "av02_test_project"
    data["project_name"] = "Proyecto AV-02"
    decisions_path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    upgrade_database(root)
    decisions = load_decisions(decisions_path)
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
            title="Testimonios autorizados",
            created_by="test",
        )
    return root, decisions, engine, unit


def _metadata() -> dict:
    return {
        "id": "videoAV02",
        "extractor": "youtube",
        "extractor_key": "Youtube",
        "webpage_url": "https://www.youtube.com/watch?v=videoAV02",
        "title": "Testimonio real controlado",
        "channel": "Canal de prueba",
        "channel_id": "canal123",
        "uploader": "Canal de prueba",
        "upload_date": "20260801",
        "duration": 9.48,
        "license": None,
        "format_id": "137+140",
        "ext": "mp4",
        "requested_formats": [
            {"format_id": "137", "ext": "mp4", "vcodec": "avc1", "acodec": "none"},
            {"format_id": "140", "ext": "m4a", "vcodec": "none", "acodec": "mp4a"},
        ],
    }


def test_platform_request_requires_explicit_authorization() -> None:
    with pytest.raises(ValueError, match="autorizado"):
        PlatformImportRequest(
            url="https://www.youtube.com/watch?v=videoAV02",
            archival_unit_id="unit",
            media_kind="video",
            access_conditions="Uso de investigación autorizado",
            authorization_confirmed=False,
        )


def test_platform_import_enters_av01_and_preserves_remote_provenance(tmp_path: Path, monkeypatch) -> None:
    root, decisions, engine, unit = _project(tmp_path)
    fixture = Path(__file__).parents[1] / "examples" / "av01_validation" / "testimonio_controlado.mp4"
    metadata = _metadata()
    fake_yt_dlp = SimpleNamespace(version=SimpleNamespace(__version__="2026.7.4"))

    def fake_extract_info(*, url: str, download: bool, outtmpl: str | None = None, media_kind: str = "video"):
        assert url == "https://www.youtube.com/watch?v=videoAV02"
        assert media_kind == "video"
        if download:
            assert outtmpl is not None
            destination = Path(outtmpl).parent
            destination.mkdir(parents=True, exist_ok=True)
            shutil.copy2(fixture, destination / "videoAV02.mp4")
        return fake_yt_dlp, dict(metadata)

    monkeypatch.setattr("archive_workbench.platform_import._extract_info", fake_extract_info)
    request = PlatformImportRequest(
        url="https://www.youtube.com/watch?v=videoAV02",
        archival_unit_id=unit.id,
        media_kind="video",
        access_conditions="Material autorizado para investigación y preservación local.",
        authorization_confirmed=True,
    )
    register_transcription_backend(_Backend())
    try:
        with session_scope(engine) as session:
            result = import_platform_media(
                session,
                project_root=root,
                project_id=decisions.project_id,
                request=request,
                actor="alex",
            )
            assert result.platform == "youtube"
            assert result.platform_id == "videoAV02"
            assert result.relative_path == "corpus/importados/plataformas/youtube/videoAV02.mp4"
            local_path = root / result.relative_path
            assert local_path.is_file()
            assert result.sha256 == sha256_file(local_path)

            digital = session.get(DigitalObject, result.digital_object_id)
            assert digital is not None
            assert digital.media_type == "video"
            assert digital.sha256 == result.sha256

            registration = session.scalar(
                select(SourceRegistration).where(
                    SourceRegistration.project_id == decisions.project_id,
                    SourceRegistration.digital_object_id == digital.id,
                )
            )
            assert registration is not None
            assert registration.source_type == "catalog"
            assert registration.source_payload_json["origin"] == "platform_import"
            origin = registration.source_payload_json["platform_import"]
            assert origin["platform"] == "youtube"
            assert origin["platform_id"] == "videoAV02"
            assert origin["webpage_url"] == metadata["webpage_url"]
            assert origin["access_conditions"].startswith("Material autorizado")
            assert origin["authorization_confirmed"] is True
            assert origin["incorporated_sha256"] == result.sha256
            assert origin["yt_dlp_version"] == "2026.7.4"

            media = session.scalar(
                select(AudiovisualMedia).where(AudiovisualMedia.digital_object_id == digital.id)
            )
            assert media is not None
            assert media.title == "Testimonio real controlado"
            assert media.channel == "Canal de prueba"
            assert media.provenance == metadata["webpage_url"]
            assert media.rights.startswith("Material autorizado")
            assert platform_origin_for_digital_object(
                session,
                project_id=decisions.project_id,
                digital_object_id=digital.id,
            )["platform_id"] == "videoAV02"

            run = transcribe_audiovisual(
                session,
                project_root=root,
                media_id=media.id,
                request=TranscriptionRequest(
                    backend="platform_test_backend",
                    model_name="fixture",
                    device="cpu",
                    language="es",
                    options={"compute_type": "int8"},
                ),
                actor="alex",
            )
            assert run.status == "completed"
            payload, count = export_transcript_segments_bytes(
                session,
                project_id=decisions.project_id,
                output_format="jsonl",
            )
            assert count == 1
            exported = payload.decode("utf-8")
            assert '"source_origin": "platform_import"' in exported
            assert '"platform": "youtube"' in exported
            assert '"platform_id": "videoAV02"' in exported
            assert metadata["webpage_url"] in exported
            assert "Material autorizado para investigación" in exported
    finally:
        engine.dispose()


def test_platform_ui_is_optional_closed_and_does_not_auto_transcribe() -> None:
    root = Path(__file__).parents[1]
    source = (root / "src" / "archive_workbench" / "audiovisual_app.py").read_text(
        encoding="utf-8"
    )
    for literal in (
        "Incorporar desde plataforma",
        "URL del audio o video",
        "Unidad archivística",
        "Tipo de incorporación",
        "Condiciones de acceso / autorización",
        "Confirmo que el proyecto está autorizado a incorporar este material",
    ):
        assert literal in source
    assert '"Incorporar desde plataforma",\n        value=False,' in source
    assert "No inicia ninguna transcripción automáticamente." in source
    assert "import_platform_media(" in source


def test_av02_validation_scripts_accept_one_authorized_youtube_import(tmp_path: Path, monkeypatch) -> None:
    import importlib.util

    root_dir = Path(__file__).parents[1]
    create_path = root_dir / "scripts" / "create_platform_import_validation_project.py"
    verify_path = root_dir / "scripts" / "verify_platform_import_validation_project.py"

    create_spec = importlib.util.spec_from_file_location("av02_create", create_path)
    assert create_spec and create_spec.loader
    create_module = importlib.util.module_from_spec(create_spec)
    create_spec.loader.exec_module(create_module)

    project_root = tmp_path / "av02_validation"
    summary = create_module.create_validation_project(project_root)
    assert summary["version"] == "0.87.0"
    assert summary["revision"] == "0046_audiovisual_timeline_annotations"
    assert summary["platform_import_count"] == 0
    assert summary["project_data_touched"] is False

    fixture = root_dir / "examples" / "av01_validation" / "testimonio_controlado.mp4"
    metadata = _metadata()
    metadata["channel_id"] = "UCsZG_7l0cYIEtJNhajrFPYg"
    fake_yt_dlp = SimpleNamespace(version=SimpleNamespace(__version__="2026.7.4"))

    def fake_extract_info(*, url: str, download: bool, outtmpl: str | None = None, media_kind: str = "video"):
        if download:
            assert outtmpl is not None
            destination = Path(outtmpl).parent
            destination.mkdir(parents=True, exist_ok=True)
            shutil.copy2(fixture, destination / "videoAV02.mp4")
        return fake_yt_dlp, dict(metadata)

    monkeypatch.setattr("archive_workbench.platform_import._extract_info", fake_extract_info)
    engine = create_sqlite_engine(database_path(project_root))
    try:
        with session_scope(engine) as session:
            import_platform_media(
                session,
                project_root=project_root,
                project_id="av02_platform_validation",
                request=PlatformImportRequest(
                    url="https://www.youtube.com/watch?v=videoAV02",
                    archival_unit_id=str(summary["archival_unit_id"]),
                    media_kind="video",
                    access_conditions="Material autorizado para prueba AV-02.",
                    authorization_confirmed=True,
                ),
                actor="alex",
            )
    finally:
        engine.dispose()

    verify_spec = importlib.util.spec_from_file_location("av02_verify", verify_path)
    assert verify_spec and verify_spec.loader
    verify_module = importlib.util.module_from_spec(verify_spec)
    verify_spec.loader.exec_module(verify_module)
    ok, details = verify_module.verify(project_root)
    assert ok is True, details
    assert details["channel_id"] == "UCsZG_7l0cYIEtJNhajrFPYg"
    assert details["transcription_run_count"] == 0


def test_platform_import_form_errors_are_human_readable() -> None:
    from archive_workbench.audiovisual_app import _platform_import_form_error

    assert _platform_import_form_error(
        url="",
        access_conditions="Material autorizado",
        authorization_confirmed=True,
    ) == "Pegá la dirección (URL) del audio o video que querés incorporar."

    assert _platform_import_form_error(
        url="youtube.com/watch?v=abc",
        access_conditions="Material autorizado",
        authorization_confirmed=True,
    ) == (
        "La dirección del material no parece válida. Copiá y pegá la URL completa, "
        "por ejemplo https://www.youtube.com/watch?v=…"
    )

    assert _platform_import_form_error(
        url="https://www.youtube.com/watch?v=abc",
        access_conditions="",
        authorization_confirmed=True,
    ) == "Completá las condiciones de acceso o autorización antes de incorporar el material."

    assert _platform_import_form_error(
        url="https://www.youtube.com/watch?v=abc",
        access_conditions="Material autorizado",
        authorization_confirmed=False,
    ) == (
        "Marcá la casilla de confirmación para indicar que el proyecto está autorizado "
        "a incorporar este material."
    )

    assert _platform_import_form_error(
        url="https://www.youtube.com/watch?v=abc",
        access_conditions="Material autorizado",
        authorization_confirmed=True,
    ) is None


def test_platform_request_validation_error_never_exposes_pydantic_details() -> None:
    from pydantic import ValidationError
    from archive_workbench.audiovisual_app import _platform_request_validation_message

    with pytest.raises(ValidationError) as captured:
        PlatformImportRequest(
            url="https://www.youtube.com/watch?v=abc",
            archival_unit_id="unit",
            media_kind="video",
            access_conditions="",
            authorization_confirmed=True,
        )

    message = _platform_request_validation_message(captured.value)
    assert message == "Completá las condiciones de acceso o autorización antes de incorporar el material."
    assert "validation error" not in message.lower()
    assert "string_too_short" not in message
    assert "pydantic" not in message.lower()
