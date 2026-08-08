from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Callable

from archive_workbench.exchange import inspect_change_bundle, sha256_file

DRIVE_FILE_SCOPE = "https://www.googleapis.com/auth/drive.file"
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
DRIVE_FILES_URL = "https://www.googleapis.com/drive/v3/files"
DRIVE_UPLOAD_URL = "https://www.googleapis.com/upload/drive/v3/files"
DRIVE_ZIP_MIME_TYPES = ("application/zip", "application/x-zip-compressed")


@dataclass(frozen=True, slots=True)
class GoogleOAuthClient:
    client_id: str
    client_secret: str | None
    auth_uri: str
    token_uri: str


@dataclass(frozen=True, slots=True)
class GoogleDriveToken:
    access_token: str
    refresh_token: str | None
    expires_at: float
    token_type: str = "Bearer"
    scope: str = DRIVE_FILE_SCOPE

    @property
    def expired(self) -> bool:
        return time.time() >= self.expires_at - 60


@dataclass(frozen=True, slots=True)
class DriveFileMetadata:
    file_id: str
    name: str
    mime_type: str | None
    size: int | None
    web_view_link: str | None
    modified_time: str | None
    md5_checksum: str | None
    app_properties: dict[str, str]


@dataclass(frozen=True, slots=True)
class DriveUploadSummary:
    metadata: DriveFileMetadata
    local_sha256: str
    bundle_id: str
    project_id: str


@dataclass(frozen=True, slots=True)
class DriveDownloadSummary:
    metadata: DriveFileMetadata
    destination: Path
    local_sha256: str
    bundle_id: str
    project_id: str


@dataclass(frozen=True, slots=True)
class OAuthResult:
    token: GoogleDriveToken
    picked_file_ids: tuple[str, ...] = ()


def default_client_secret_path() -> Path:
    config_root = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return config_root / "archive-workbench" / "google_drive_client_secret.json"


def default_token_path() -> Path:
    config_root = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return config_root / "archive-workbench" / "google_drive_token.json"


def load_oauth_client(path: Path) -> GoogleOAuthClient:
    source = path.expanduser().resolve()
    if not source.is_file():
        raise ValueError(f"No existe el archivo de credenciales OAuth: {source}")
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"No pude leer las credenciales OAuth de Google: {exc}") from exc
    installed = payload.get("installed")
    if not isinstance(installed, dict):
        raise ValueError(
            "Las credenciales deben corresponder a un cliente OAuth de tipo aplicación de escritorio."
        )
    client_id = str(installed.get("client_id") or "").strip()
    if not client_id:
        raise ValueError("El archivo OAuth no contiene client_id.")
    client_secret = str(installed.get("client_secret") or "").strip() or None
    auth_uri = str(installed.get("auth_uri") or GOOGLE_AUTH_URL).strip()
    token_uri = str(installed.get("token_uri") or GOOGLE_TOKEN_URL).strip()
    return GoogleOAuthClient(
        client_id=client_id,
        client_secret=client_secret,
        auth_uri=auth_uri,
        token_uri=token_uri,
    )


def _token_payload(token: GoogleDriveToken) -> dict[str, Any]:
    return {
        "access_token": token.access_token,
        "refresh_token": token.refresh_token,
        "expires_at": token.expires_at,
        "token_type": token.token_type,
        "scope": token.scope,
    }


def save_token(token: GoogleDriveToken, path: Path | None = None) -> Path:
    destination = (path or default_token_path()).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp = destination.with_suffix(destination.suffix + ".tmp")
    temp.write_text(
        json.dumps(_token_payload(token), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.chmod(temp, 0o600)
    temp.replace(destination)
    os.chmod(destination, 0o600)
    return destination


def load_token(path: Path | None = None) -> GoogleDriveToken | None:
    source = (path or default_token_path()).expanduser().resolve()
    if not source.is_file():
        return None
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
        access_token = str(payload.get("access_token") or "").strip()
        if not access_token:
            return None
        refresh = str(payload.get("refresh_token") or "").strip() or None
        return GoogleDriveToken(
            access_token=access_token,
            refresh_token=refresh,
            expires_at=float(payload.get("expires_at") or 0),
            token_type=str(payload.get("token_type") or "Bearer"),
            scope=str(payload.get("scope") or DRIVE_FILE_SCOPE),
        )
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None


def _pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)[:96]
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return verifier, challenge


def build_authorization_url(
    client: GoogleOAuthClient,
    *,
    redirect_uri: str,
    state: str,
    code_challenge: str,
    picker: bool,
) -> str:
    params: dict[str, str] = {
        "client_id": client.client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": DRIVE_FILE_SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    if picker:
        params.update(
            {
                "trigger_onepick": "true",
                "allow_multiple": "false",
                "mimetypes": ",".join(DRIVE_ZIP_MIME_TYPES),
            }
        )
    return f"{client.auth_uri}?{urllib.parse.urlencode(params)}"


class _CallbackState:
    def __init__(self) -> None:
        self.params: dict[str, list[str]] | None = None


class _OAuthCallbackHandler(BaseHTTPRequestHandler):
    callback_state: _CallbackState

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        self.callback_state.params = urllib.parse.parse_qs(parsed.query)
        error = (self.callback_state.params.get("error") or [None])[0]
        if error:
            title = "Autorización cancelada"
            body = "Google Drive no fue conectado. Podés cerrar esta pestaña."
        else:
            title = "Archive Workbench"
            body = "La autorización terminó. Podés cerrar esta pestaña y volver a Archive Workbench."
        payload = (
            "<!doctype html><html><head><meta charset='utf-8'><title>"
            + title
            + "</title></head><body><h2>"
            + title
            + "</h2><p>"
            + body
            + "</p></body></html>"
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args: object) -> None:
        return


def _post_form(url: str, data: dict[str, str], *, timeout: float = 60) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=urllib.parse.urlencode(data).encode("utf-8"),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    return _json_request(request, timeout=timeout)


def _json_request(request: urllib.request.Request, *, timeout: float = 120) -> dict[str, Any]:
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Google devolvió HTTP {exc.code}: {detail[:600]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"No pude conectar con Google: {exc.reason}") from exc
    try:
        decoded = json.loads(payload.decode("utf-8")) if payload else {}
    except json.JSONDecodeError as exc:
        raise RuntimeError("Google devolvió una respuesta JSON inválida.") from exc
    if not isinstance(decoded, dict):
        raise RuntimeError("Google devolvió una respuesta inesperada.")
    return decoded


def _token_from_response(
    payload: dict[str, Any], *, previous: GoogleDriveToken | None = None
) -> GoogleDriveToken:
    access_token = str(payload.get("access_token") or "").strip()
    if not access_token:
        raise RuntimeError("Google no devolvió un access_token.")
    refresh = str(payload.get("refresh_token") or "").strip() or (
        previous.refresh_token if previous else None
    )
    expires_in = float(payload.get("expires_in") or 3600)
    return GoogleDriveToken(
        access_token=access_token,
        refresh_token=refresh,
        expires_at=time.time() + expires_in,
        token_type=str(payload.get("token_type") or "Bearer"),
        scope=str(payload.get("scope") or DRIVE_FILE_SCOPE),
    )


def authorize_google_drive(
    client_secret_path: Path,
    *,
    picker: bool = False,
    token_path: Path | None = None,
    open_browser: Callable[[str], bool] | None = None,
    timeout_seconds: float = 300,
) -> OAuthResult:
    client = load_oauth_client(client_secret_path)
    state_value = secrets.token_urlsafe(24)
    verifier, challenge = _pkce_pair()
    callback_state = _CallbackState()

    handler_type = type(
        "ArchiveWorkbenchOAuthCallback",
        (_OAuthCallbackHandler,),
        {"callback_state": callback_state},
    )
    server = HTTPServer(("127.0.0.1", 0), handler_type)
    server.timeout = timeout_seconds
    redirect_uri = f"http://127.0.0.1:{server.server_port}/oauth2callback"
    authorization_url = build_authorization_url(
        client,
        redirect_uri=redirect_uri,
        state=state_value,
        code_challenge=challenge,
        picker=picker,
    )

    opener = open_browser or (lambda url: webbrowser.open(url, new=2))
    if not opener(authorization_url):
        server.server_close()
        raise RuntimeError(
            "No pude abrir el navegador para autorizar Google Drive. Abrí manualmente la URL de autorización."
        )
    try:
        server.handle_request()
    finally:
        server.server_close()

    params = callback_state.params
    if params is None:
        raise RuntimeError("La autorización de Google Drive agotó el tiempo de espera.")
    error = (params.get("error") or [None])[0]
    if error:
        raise RuntimeError(f"Google Drive no fue autorizado: {error}")
    returned_state = (params.get("state") or [None])[0]
    if returned_state != state_value:
        raise RuntimeError("La respuesta OAuth de Google no coincide con la solicitud iniciada.")
    code = (params.get("code") or [None])[0]
    if not code:
        raise RuntimeError("Google no devolvió el código de autorización.")

    token_request = {
        "client_id": client.client_id,
        "code": code,
        "code_verifier": verifier,
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri,
    }
    if client.client_secret:
        token_request["client_secret"] = client.client_secret
    previous = load_token(token_path)
    token = _token_from_response(
        _post_form(client.token_uri, token_request),
        previous=previous,
    )
    save_token(token, token_path)
    raw_ids = (params.get("picked_file_ids") or [""])[0]
    picked = tuple(item.strip() for item in raw_ids.split(",") if item.strip())
    if picker and not picked:
        raise RuntimeError("Google Picker no devolvió ningún archivo seleccionado.")
    return OAuthResult(token=token, picked_file_ids=picked)


def refresh_google_drive_token(
    client_secret_path: Path,
    *,
    token_path: Path | None = None,
) -> GoogleDriveToken:
    client = load_oauth_client(client_secret_path)
    current = load_token(token_path)
    if current is None:
        raise RuntimeError("Google Drive todavía no está conectado.")
    if not current.expired:
        return current
    if not current.refresh_token:
        raise RuntimeError("La autorización guardada no contiene refresh_token; conectá Google Drive nuevamente.")
    data = {
        "client_id": client.client_id,
        "refresh_token": current.refresh_token,
        "grant_type": "refresh_token",
    }
    if client.client_secret:
        data["client_secret"] = client.client_secret
    refreshed = _token_from_response(_post_form(client.token_uri, data), previous=current)
    save_token(refreshed, token_path)
    return refreshed


def _auth_headers(token: GoogleDriveToken) -> dict[str, str]:
    return {"Authorization": f"Bearer {token.access_token}"}


def _metadata_from_payload(payload: dict[str, Any]) -> DriveFileMetadata:
    return DriveFileMetadata(
        file_id=str(payload.get("id") or ""),
        name=str(payload.get("name") or ""),
        mime_type=str(payload.get("mimeType") or "") or None,
        size=int(payload["size"]) if str(payload.get("size") or "").isdigit() else None,
        web_view_link=str(payload.get("webViewLink") or "") or None,
        modified_time=str(payload.get("modifiedTime") or "") or None,
        md5_checksum=str(payload.get("md5Checksum") or "") or None,
        app_properties={str(k): str(v) for k, v in (payload.get("appProperties") or {}).items()},
    )


def get_drive_file_metadata(
    file_id: str,
    *,
    client_secret_path: Path,
    token_path: Path | None = None,
) -> DriveFileMetadata:
    clean_id = file_id.strip()
    if not clean_id:
        raise ValueError("El identificador de Google Drive está vacío.")
    token = refresh_google_drive_token(client_secret_path, token_path=token_path)
    fields = "id,name,mimeType,size,webViewLink,modifiedTime,md5Checksum,appProperties"
    url = f"{DRIVE_FILES_URL}/{urllib.parse.quote(clean_id)}?" + urllib.parse.urlencode(
        {"fields": fields, "supportsAllDrives": "true"}
    )
    request = urllib.request.Request(url, headers=_auth_headers(token), method="GET")
    return _metadata_from_payload(_json_request(request))


def _multipart_related(metadata: dict[str, Any], payload: bytes, mime_type: str) -> tuple[str, bytes]:
    boundary = "awb_" + secrets.token_hex(20)
    json_part = json.dumps(metadata, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    body = b"\r\n".join(
        [
            f"--{boundary}".encode("ascii"),
            b"Content-Type: application/json; charset=UTF-8",
            b"",
            json_part,
            f"--{boundary}".encode("ascii"),
            f"Content-Type: {mime_type}".encode("ascii"),
            b"",
            payload,
            f"--{boundary}--".encode("ascii"),
            b"",
        ]
    )
    return f"multipart/related; boundary={boundary}", body


def upload_exchange_bundle_to_drive(
    bundle_path: Path,
    *,
    client_secret_path: Path,
    token_path: Path | None = None,
) -> DriveUploadSummary:
    source = bundle_path.expanduser().resolve()
    inspection = inspect_change_bundle(source)
    local_sha = sha256_file(source)
    token = refresh_google_drive_token(client_secret_path, token_path=token_path)
    metadata = {
        "name": source.name,
        "mimeType": "application/zip",
        "appProperties": {
            "archive_workbench_kind": "exchange_bundle",
            "archive_workbench_sha256": local_sha,
            "archive_workbench_bundle_id": inspection.manifest.bundle_id,
            "archive_workbench_project_id": inspection.manifest.project_id,
        },
    }
    content_type, body = _multipart_related(metadata, source.read_bytes(), "application/zip")
    fields = "id,name,mimeType,size,webViewLink,modifiedTime,md5Checksum,appProperties"
    url = f"{DRIVE_UPLOAD_URL}?" + urllib.parse.urlencode(
        {"uploadType": "multipart", "fields": fields, "supportsAllDrives": "true"}
    )
    headers = _auth_headers(token)
    headers["Content-Type"] = content_type
    headers["Content-Length"] = str(len(body))
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    uploaded = _metadata_from_payload(_json_request(request, timeout=180))
    return DriveUploadSummary(
        metadata=uploaded,
        local_sha256=local_sha,
        bundle_id=inspection.manifest.bundle_id,
        project_id=inspection.manifest.project_id,
    )


def _safe_download_name(name: str, file_id: str) -> str:
    base = Path(name).name.strip() or "paquete.zip"
    if not base.lower().endswith(".zip"):
        base += ".zip"
    stem = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in base)
    stem = stem[-120:] if len(stem) > 120 else stem
    return f"{file_id[:12]}_{stem}"


def download_exchange_bundle_from_drive(
    file_id: str,
    *,
    project_root: Path,
    client_secret_path: Path,
    token_path: Path | None = None,
) -> DriveDownloadSummary:
    metadata = get_drive_file_metadata(
        file_id,
        client_secret_path=client_secret_path,
        token_path=token_path,
    )
    if metadata.mime_type not in DRIVE_ZIP_MIME_TYPES and not metadata.name.lower().endswith(".zip"):
        raise ValueError("El archivo elegido en Google Drive no parece ser un ZIP.")
    token = refresh_google_drive_token(client_secret_path, token_path=token_path)
    url = f"{DRIVE_FILES_URL}/{urllib.parse.quote(file_id.strip())}?" + urllib.parse.urlencode(
        {"alt": "media", "supportsAllDrives": "true"}
    )
    request = urllib.request.Request(url, headers=_auth_headers(token), method="GET")
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            data = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Google devolvió HTTP {exc.code}: {detail[:600]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"No pude descargar desde Google Drive: {exc.reason}") from exc

    destination_dir = project_root.expanduser().resolve() / "exchange" / "drive_downloads"
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / _safe_download_name(metadata.name, file_id.strip())
    temp = destination.with_suffix(destination.suffix + ".tmp")
    temp.write_bytes(data)
    temp.replace(destination)
    inspection = inspect_change_bundle(destination)
    local_sha = sha256_file(destination)
    declared_sha = metadata.app_properties.get("archive_workbench_sha256")
    if declared_sha and declared_sha != local_sha:
        destination.unlink(missing_ok=True)
        raise ValueError("El SHA-256 descargado no coincide con el registrado por Archive Workbench en Drive.")
    return DriveDownloadSummary(
        metadata=metadata,
        destination=destination,
        local_sha256=local_sha,
        bundle_id=inspection.manifest.bundle_id,
        project_id=inspection.manifest.project_id,
    )


def pick_drive_exchange_bundle(
    client_secret_path: Path,
    *,
    token_path: Path | None = None,
    open_browser: Callable[[str], bool] | None = None,
) -> tuple[str, DriveFileMetadata]:
    result = authorize_google_drive(
        client_secret_path,
        picker=True,
        token_path=token_path,
        open_browser=open_browser,
    )
    file_id = result.picked_file_ids[0]
    metadata = get_drive_file_metadata(
        file_id,
        client_secret_path=client_secret_path,
        token_path=token_path,
    )
    return file_id, metadata


def connection_status(token_path: Path | None = None) -> str:
    token = load_token(token_path)
    if token is None:
        return "not_connected"
    return "expired" if token.expired else "connected"
