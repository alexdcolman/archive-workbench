from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.parse
import zipfile
from pathlib import Path

from archive_workbench.contracts.changes import ChangeBundleManifest
from archive_workbench.db import (
    create_sqlite_engine,
    current_revision,
    database_path,
    session_scope,
    upgrade_database,
)
from archive_workbench.db.models import ExchangeCheckpoint, ExchangeWorkspace, Project, utc_now
from archive_workbench.exchange import compare_change_bundle_manifest, ensure_exchange_workspace
from archive_workbench.decisions import load_decisions
from archive_workbench.google_drive_transport import (
    DRIVE_FILE_SCOPE,
    GoogleDriveToken,
    GoogleOAuthClient,
    _safe_download_name,
    build_authorization_url,
    connection_status,
    download_exchange_bundle_from_drive,
    load_oauth_client,
    load_token,
    save_token,
    upload_exchange_bundle_to_drive,
)


class _FakeResponse:
    def __init__(self, payload: bytes):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self) -> bytes:
        return self.payload


def _client_secret(path: Path) -> Path:
    path.write_text(
        json.dumps(
            {
                "installed": {
                    "client_id": "client.apps.googleusercontent.com",
                    "client_secret": "secret",
                    "auth_uri": "https://accounts.google.com/o/oauth2/v2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                }
            }
        ),
        encoding="utf-8",
    )
    return path


def _token(path: Path) -> Path:
    save_token(
        GoogleDriveToken(
            access_token="access-token",
            refresh_token="refresh-token",
            expires_at=time.time() + 3600,
        ),
        path,
    )
    return path


def _bundle(path: Path, *, project_id: str = "project-1", source_workspace_id: str = "remote") -> Path:
    changes = b""
    manifest = ChangeBundleManifest(
        project_id=project_id,
        bundle_id="bundle-1",
        source_workspace_id=source_workspace_id,
        source_workspace_name="Remota",
        app_version="0.87.0",
        database_revision="0046_audiovisual_timeline_annotations",
        created_by="tests",
        base_checkpoint_id="remote-base",
        base_checkpoint_label="base",
        base_checkpoint_state_sha256="a" * 64,
        base_sequence=0,
        last_sequence=0,
        event_count=0,
        changes_sha256=hashlib.sha256(changes).hexdigest(),
        attachment_checksums={},
    )
    manifest_bytes = manifest.model_dump_json(exclude_none=True).encode("utf-8") + b"\n"
    checksums = (
        f"{hashlib.sha256(manifest_bytes).hexdigest()}  manifest.json\n"
        f"{hashlib.sha256(changes).hexdigest()}  changes.jsonl\n"
    ).encode("utf-8")
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", manifest_bytes)
        archive.writestr("changes.jsonl", changes)
        archive.writestr("checksums.sha256", checksums)
    return path


def test_load_desktop_oauth_client_and_token_permissions(tmp_path: Path):
    secret = _client_secret(tmp_path / "client.json")
    client = load_oauth_client(secret)
    assert client.client_id == "client.apps.googleusercontent.com"
    assert client.client_secret == "secret"

    token_path = _token(tmp_path / "token.json")
    assert load_token(token_path) is not None
    assert oct(os.stat(token_path).st_mode & 0o777) == "0o600"
    assert connection_status(token_path) == "connected"


def test_picker_authorization_url_uses_only_drive_file_scope():
    client = GoogleOAuthClient(
        client_id="client",
        client_secret=None,
        auth_uri="https://accounts.google.com/o/oauth2/v2/auth",
        token_uri="https://oauth2.googleapis.com/token",
    )
    url = build_authorization_url(
        client,
        redirect_uri="http://127.0.0.1:9999/oauth2callback",
        state="state",
        code_challenge="challenge",
        picker=True,
    )
    params = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    assert params["scope"] == [DRIVE_FILE_SCOPE]
    assert params["trigger_onepick"] == ["true"]
    assert params["allow_multiple"] == ["false"]
    assert "application/zip" in params["mimetypes"][0]
    assert params["code_challenge_method"] == ["S256"]


def test_upload_valid_bundle_sets_archive_workbench_properties(tmp_path: Path, monkeypatch):
    secret = _client_secret(tmp_path / "client.json")
    token_path = _token(tmp_path / "token.json")
    bundle = _bundle(tmp_path / "exchange.zip")
    local_sha = hashlib.sha256(bundle.read_bytes()).hexdigest()
    calls = []

    def fake_urlopen(request, timeout=0):
        calls.append(request)
        response = {
            "id": "drive-file-1",
            "name": "exchange.zip",
            "mimeType": "application/zip",
            "size": str(bundle.stat().st_size),
            "webViewLink": "https://drive.google.com/file/d/drive-file-1/view",
            "appProperties": {
                "archive_workbench_kind": "exchange_bundle",
                "archive_workbench_sha256": local_sha,
                "archive_workbench_bundle_id": "bundle-1",
                "archive_workbench_project_id": "project-1",
            },
        }
        return _FakeResponse(json.dumps(response).encode("utf-8"))

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    summary = upload_exchange_bundle_to_drive(
        bundle,
        client_secret_path=secret,
        token_path=token_path,
    )
    assert summary.metadata.file_id == "drive-file-1"
    assert summary.local_sha256 == local_sha
    assert summary.bundle_id == "bundle-1"
    assert len(calls) == 1
    body = calls[0].data
    assert body is not None
    assert b"archive_workbench_sha256" in body
    assert local_sha.encode("ascii") in body
    assert bundle.read_bytes() in body


def test_download_valid_bundle_is_atomic_and_verified(tmp_path: Path, monkeypatch):
    secret = _client_secret(tmp_path / "client.json")
    token_path = _token(tmp_path / "token.json")
    source = _bundle(tmp_path / "source.zip")
    payload = source.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    responses = [
        _FakeResponse(
            json.dumps(
                {
                    "id": "drive-file-2",
                    "name": "../paquete recibido.zip",
                    "mimeType": "application/zip",
                    "size": str(len(payload)),
                    "webViewLink": "https://drive.google.com/file/d/drive-file-2/view",
                    "appProperties": {"archive_workbench_sha256": digest},
                }
            ).encode("utf-8")
        ),
        _FakeResponse(payload),
    ]

    def fake_urlopen(request, timeout=0):
        return responses.pop(0)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    root = tmp_path / "project"
    summary = download_exchange_bundle_from_drive(
        "drive-file-2",
        project_root=root,
        client_secret_path=secret,
        token_path=token_path,
    )
    assert summary.destination.is_file()
    assert summary.destination.parent == root / "exchange" / "drive_downloads"
    assert ".." not in summary.destination.name
    assert summary.local_sha256 == digest
    assert not summary.destination.with_suffix(summary.destination.suffix + ".tmp").exists()


def test_download_rejects_declared_sha_mismatch_and_removes_file(tmp_path: Path, monkeypatch):
    secret = _client_secret(tmp_path / "client.json")
    token_path = _token(tmp_path / "token.json")
    source = _bundle(tmp_path / "source.zip")
    payload = source.read_bytes()
    responses = [
        _FakeResponse(
            json.dumps(
                {
                    "id": "drive-file-mismatch",
                    "name": "paquete.zip",
                    "mimeType": "application/zip",
                    "size": str(len(payload)),
                    "appProperties": {"archive_workbench_sha256": "0" * 64},
                }
            ).encode("utf-8")
        ),
        _FakeResponse(payload),
    ]

    monkeypatch.setattr("urllib.request.urlopen", lambda request, timeout=0: responses.pop(0))
    root = tmp_path / "project"
    try:
        download_exchange_bundle_from_drive(
            "drive-file-mismatch",
            project_root=root,
            client_secret_path=secret,
            token_path=token_path,
        )
    except ValueError as exc:
        assert "SHA-256" in str(exc)
    else:
        raise AssertionError("La descarga con SHA declarado incorrecto debía rechazarse")
    assert not list((root / "exchange" / "drive_downloads").glob("*.zip"))


def test_safe_download_name_removes_directory_components():
    value = _safe_download_name("../../afuera.zip", "abcdefghijklmnop")
    assert value == "abcdefghijkl_afuera.zip"
    assert "/" not in value


def test_manifest_comparison_is_informative_and_does_not_apply_bundle(tmp_path: Path):
    root = tmp_path / "project"
    upgrade_database(root)
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            session.add(
                Project(
                    id="project-1",
                    name="Proyecto",
                    decisions_schema_version="1.0",
                    decisions_json={},
                    created_at=utc_now(),
                    updated_at=utc_now(),
                )
            )
            session.flush()
            workspace = ensure_exchange_workspace(
                session, workspace_name="Local", changed_by="tests"
            )
            session.add(
                ExchangeCheckpoint(
                    id="local-base",
                    workspace_id=workspace.id,
                    project_id="project-1",
                    sequence_number=0,
                    label="base-local",
                    note=None,
                    state_sha256="a" * 64,
                    created_by="tests",
                    created_at=utc_now(),
                )
            )
        bundle = _bundle(tmp_path / "incoming.zip")
        with session_scope(engine) as session:
            comparison = compare_change_bundle_manifest(
                session,
                project_root=root,
                bundle_path=bundle,
            )
            assert comparison.project_matches is True
            assert comparison.source_is_local_workspace is False
            assert comparison.base_checkpoint_known is True
            assert comparison.database_revision_known is True
            assert {row.field for row in comparison.rows} >= {
                "Proyecto",
                "Copia de origen",
                "Revisión de base",
                "Base del paquete",
                "Secuencias",
            }
            sequence_row = next(row for row in comparison.rows if row.field == "Secuencias")
            assert sequence_row.incoming_value == "sin eventos · base 0"
    finally:
        engine.dispose()


def test_exchange_ui_keeps_google_drive_secondary_and_persistent():
    source = (Path(__file__).parents[1] / "src" / "archive_workbench" / "review_app.py").read_text(
        encoding="utf-8"
    )
    assert 'st.toggle(\n        "Google Drive (opcional)"' in source
    assert 'with st.expander("Google Drive' not in source
    assert "Drive sólo transporta paquetes ZIP" in source
    assert "Simular evaluación del paquete descargado" in source


def test_validation_generator_creates_review_app_compatible_projects(tmp_path: Path):
    import importlib.util

    script_path = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "create_google_drive_transport_validation_projects.py"
    )
    spec = importlib.util.spec_from_file_location("int01_validation_generator", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    sender = tmp_path / "sender"
    receiver = tmp_path / "receiver"
    result = module.create_validation_projects(sender, receiver, force=False)

    assert result["project_id"] == "int01-google-drive-validation"
    for root in (sender, receiver):
        decisions_path = root / "config" / "decisions.yaml"
        assert decisions_path.is_file()
        decisions = load_decisions(decisions_path)
        assert decisions.project_id == "int01-google-drive-validation"
        assert decisions.project_name == "Validación INT-01 Google Drive"
        assert database_path(root).is_file()
        assert current_revision(root) == "0046_audiovisual_timeline_annotations"
