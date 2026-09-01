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
    GOOGLE_OAUTH_CLIENT_ID_ENV,
    GOOGLE_OAUTH_PUBLIC_URL_ENV,
    GoogleDriveToken,
    GoogleOAuthClient,
    _safe_download_name,
    _upload_resumable_file,
    build_authorization_url,
    complete_google_drive_authorization,
    configured_oauth_client,
    connection_status,
    default_token_path,
    download_archive_workbench_zip_from_drive,
    download_exchange_bundle_from_drive,
    load_oauth_client,
    load_picker_result,
    load_token,
    prepare_google_drive_authorization,
    save_token,
    upload_archive_workbench_zip_to_drive,
    upload_exchange_bundle_to_drive,
)


class _FakeResponse:
    def __init__(self, payload: bytes, *, headers: dict[str, str] | None = None):
        self.payload = payload
        self.headers = headers or {}
        self._offset = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self, size: int = -1) -> bytes:
        if size is None or size < 0:
            data = self.payload[self._offset :]
            self._offset = len(self.payload)
            return data
        data = self.payload[self._offset : self._offset + size]
        self._offset += len(data)
        return data


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
        database_revision="0047_authority_relation_profiles",
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


def test_managed_oauth_uses_embedded_client_and_persists_token_in_settings(
    tmp_path: Path, monkeypatch
):
    workspace = tmp_path / "ArchiveWorkbenchData"
    settings = workspace / "Settings"
    monkeypatch.setenv("ARCHIVE_WORKBENCH_WORKSPACE_ROOT", str(workspace))
    monkeypatch.setenv("ARCHIVE_WORKBENCH_SETTINGS_ROOT", str(settings))
    monkeypatch.setenv(GOOGLE_OAUTH_CLIENT_ID_ENV, "managed-client.apps.googleusercontent.com")
    monkeypatch.setenv("ARCHIVE_WORKBENCH_GOOGLE_OAUTH_CLIENT_SECRET", "managed-secret")
    monkeypatch.setenv(GOOGLE_OAUTH_PUBLIC_URL_ENV, "http://127.0.0.1:8507")

    client = configured_oauth_client()
    assert client.client_id == "managed-client.apps.googleusercontent.com"
    assert client.client_secret == "managed-secret"
    assert default_token_path() == settings / "google_drive_token.json"

    authorization_url = prepare_google_drive_authorization(picker=True)
    params = urllib.parse.parse_qs(urllib.parse.urlparse(authorization_url).query)
    assert params["scope"] == [DRIVE_FILE_SCOPE]
    assert params["redirect_uri"] == ["http://127.0.0.1:8507"]
    assert params["trigger_onepick"] == ["true"]
    assert params["code_challenge_method"] == ["S256"]

    requests = []

    def fake_post_form(url, data, *, timeout=60):
        requests.append((url, data, timeout))
        return {
            "access_token": "managed-access",
            "refresh_token": "managed-refresh",
            "expires_in": 3600,
            "scope": DRIVE_FILE_SCOPE,
        }

    monkeypatch.setattr("archive_workbench.google_drive_transport._post_form", fake_post_form)
    result = complete_google_drive_authorization(
        code="authorization-code",
        state=params["state"][0],
        picked_file_ids="drive-file-1",
    )

    assert result.picked_file_ids == ("drive-file-1",)
    assert load_token(default_token_path()) is not None
    assert load_picker_result() == ("drive-file-1",)
    assert requests[0][1]["code_verifier"]
    assert requests[0][1]["redirect_uri"] == "http://127.0.0.1:8507"
    assert requests[0][1]["client_secret"] == "managed-secret"


def test_managed_google_drive_ui_uses_host_browser_callback_without_per_user_json():
    source = (Path(__file__).parents[1] / "src" / "archive_workbench" / "review_app.py").read_text(
        encoding="utf-8"
    )
    managed_start = source.index("if workspace is not None:", source.index("def _render_google_drive_connection"))
    native_start = source.index("panel_key =", managed_start)
    managed_branch = source[managed_start:native_start]

    assert "prepare_google_drive_authorization()" in managed_branch
    assert 'st.link_button(' in managed_branch
    assert "ArchiveWorkbenchData/Settings" in managed_branch
    assert "client_secret_path" not in managed_branch
    assert "google_drive_client_secret.json" not in managed_branch
    assert "_handle_google_drive_oauth_callback(st)" in source
    assert source.index("_handle_google_drive_oauth_callback(st)", source.index("def main()")) < source.index(
        "_render_global_input_policy(st)", source.index("def main()")
    )


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
    responses = [
        _FakeResponse(b"", headers={"Location": "https://upload.example/session"}),
        _FakeResponse(json.dumps(response).encode("utf-8")),
    ]

    def fake_urlopen(request, timeout=0):
        calls.append(request)
        return responses.pop(0)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    summary = upload_exchange_bundle_to_drive(
        bundle,
        client_secret_path=secret,
        token_path=token_path,
    )
    assert summary.metadata.file_id == "drive-file-1"
    assert summary.local_sha256 == local_sha
    assert summary.bundle_id == "bundle-1"
    assert summary.artifact_kind == "exchange_bundle"
    assert len(calls) == 2
    assert "uploadType=resumable" in calls[0].full_url
    assert calls[0].headers["X-upload-content-length"] == str(bundle.stat().st_size)
    assert calls[1].headers["Content-range"].startswith("bytes 0-")
    assert calls[1].data == bundle.read_bytes()


def test_resumable_upload_streams_multiple_chunks(tmp_path: Path, monkeypatch):
    source = tmp_path / "large.zip"
    source.write_bytes(b"x" * (512 * 1024 + 17))
    token = GoogleDriveToken(
        access_token="access",
        refresh_token=None,
        expires_at=time.time() + 3600,
    )
    calls = []

    def fake_urlopen(request, timeout=0):
        calls.append(request)
        if len(calls) == 1:
            import urllib.error
            raise urllib.error.HTTPError(
                request.full_url,
                308,
                "Resume Incomplete",
                {"Range": "bytes=0-262143"},
                None,
            )
        return _FakeResponse(json.dumps({"id": "done"}).encode("utf-8"))

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    result = _upload_resumable_file(
        source=source,
        session_url="https://upload.example/session",
        token=token,
        chunk_size=256 * 1024,
    )
    assert result["id"] == "done"
    assert len(calls) == 2
    assert len(calls[0].data) == 256 * 1024
    assert calls[1].headers["Content-range"].startswith("bytes 262144-")

def test_upload_non_zip_fails_before_network_with_plain_error(tmp_path: Path, monkeypatch):
    secret = _client_secret(tmp_path / "client.json")
    token_path = _token(tmp_path / "token.json")
    invalid = tmp_path / "not-a-bundle.zip"
    invalid.write_text("esto no es un ZIP", encoding="utf-8")

    def fail_urlopen(*_args, **_kwargs):
        raise AssertionError("No debe intentar acceder a Google Drive")

    monkeypatch.setattr("urllib.request.urlopen", fail_urlopen)
    try:
        upload_exchange_bundle_to_drive(
            invalid,
            client_secret_path=secret,
            token_path=token_path,
        )
    except ValueError as exc:
        message = str(exc)
    else:
        raise AssertionError("Se esperaba ValueError para un archivo que no es ZIP")

    assert "no es un ZIP válido" in message


def test_upload_team_copy_zip_is_supported_by_generic_drive_transport(
    tmp_path: Path, monkeypatch
):
    secret = _client_secret(tmp_path / "client.json")
    token_path = _token(tmp_path / "token.json")
    team_copy = tmp_path / "copia-trabajo.zip"
    manifest = {
        "format": "archive-workbench-team-copy-v1",
        "package_id": "team-1",
        "project_id": "project-1",
        "project_name": "Proyecto",
        "base_checkpoint_label": "team_base_1",
        "base_state_sha256": "a" * 64,
        "content_profile": "review",
        "included_content_groups": ["derivatives"],
        "omitted_content_groups": ["originals"],
    }
    with zipfile.ZipFile(team_copy, "w") as archive:
        archive.writestr("proyecto/TEAM_COPY_MANIFEST.json", json.dumps(manifest))
        archive.writestr("proyecto/exchange/team_copy.json", json.dumps(manifest))
        archive.writestr("proyecto/data/archive_workbench.sqlite3", b"sqlite")
    responses = [
        _FakeResponse(b"", headers={"Location": "https://upload.example/session"}),
        _FakeResponse(
            json.dumps(
                {
                    "id": "drive-team-1",
                    "name": team_copy.name,
                    "mimeType": "application/zip",
                    "size": str(team_copy.stat().st_size),
                    "appProperties": {
                        "archive_workbench_kind": "team_copy",
                        "archive_workbench_team_copy_id": "team-1",
                        "archive_workbench_project_id": "project-1",
                    },
                }
            ).encode("utf-8")
        ),
    ]
    monkeypatch.setattr(
        "urllib.request.urlopen", lambda request, timeout=0: responses.pop(0)
    )
    summary = upload_archive_workbench_zip_to_drive(
        team_copy,
        client_secret_path=secret,
        token_path=token_path,
    )
    assert summary.artifact_kind == "team_copy"
    assert summary.team_copy_id == "team-1"
    assert summary.project_id == "project-1"

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



def test_download_team_copy_from_drive_is_verified_without_applying_it(
    tmp_path: Path, monkeypatch
):
    secret = _client_secret(tmp_path / "client.json")
    token_path = _token(tmp_path / "token.json")
    team_copy = tmp_path / "team.zip"
    manifest = {
        "format": "archive-workbench-team-copy-v1",
        "package_id": "team-download-1",
        "project_id": "project-1",
        "project_name": "Proyecto",
        "base_checkpoint_label": "team_base_1",
        "base_state_sha256": "a" * 64,
        "content_profile": "review",
        "included_content_groups": ["derivatives"],
        "omitted_content_groups": ["originals"],
    }
    with zipfile.ZipFile(team_copy, "w") as archive:
        archive.writestr("proyecto/TEAM_COPY_MANIFEST.json", json.dumps(manifest))
        archive.writestr("proyecto/exchange/team_copy.json", json.dumps(manifest))
        archive.writestr("proyecto/data/archive_workbench.sqlite3", b"sqlite")
    payload = team_copy.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    responses = [
        _FakeResponse(
            json.dumps(
                {
                    "id": "drive-team-download",
                    "name": "team.zip",
                    "mimeType": "application/zip",
                    "size": str(len(payload)),
                    "appProperties": {
                        "archive_workbench_kind": "team_copy",
                        "archive_workbench_sha256": digest,
                    },
                }
            ).encode("utf-8")
        ),
        _FakeResponse(payload),
    ]
    monkeypatch.setattr(
        "urllib.request.urlopen", lambda request, timeout=0: responses.pop(0)
    )
    result = download_archive_workbench_zip_from_drive(
        "drive-team-download",
        project_root=tmp_path / "project",
        client_secret_path=secret,
        token_path=token_path,
    )
    assert result.artifact_kind == "team_copy"
    assert result.team_copy_id == "team-download-1"
    assert result.destination.is_file()
    assert result.local_sha256 == digest

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


def test_exchange_ui_integrates_google_drive_into_send_prepare_and_receive():
    source = (Path(__file__).parents[1] / "src" / "archive_workbench" / "review_app.py").read_text(
        encoding="utf-8"
    )
    assert '"more": "Más opciones"' not in source
    assert 'key="exchange_secondary_task"' not in source
    assert "Google Drive se usa sólo para trasladar ZIP entre copias" not in source
    assert "def _render_google_drive_receive" in source
    assert "def _render_receive_zip_source" in source
    assert "Subir a Google Drive" in source
    assert "Desde Google Drive" in source
    assert "Elegir ZIP en Google Drive" in source
    assert "Revisar los cambios de este ZIP" in source
    assert "Detalles de compatibilidad y archivo" in source


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
        assert current_revision(root) == "0047_authority_relation_profiles"
