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
import zipfile
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Callable

from archive_workbench.exchange import inspect_change_bundle, sha256_file
from archive_workbench.team_copy import inspect_team_copy_package
from archive_workbench.runtime_environment import managed_workspace

DRIVE_FILE_SCOPE = "https://www.googleapis.com/auth/drive.file"
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
DRIVE_FILES_URL = "https://www.googleapis.com/drive/v3/files"
DRIVE_UPLOAD_URL = "https://www.googleapis.com/upload/drive/v3/files"
DRIVE_ZIP_MIME_TYPES = ("application/zip", "application/x-zip-compressed")
GOOGLE_OAUTH_CLIENT_ID_ENV = "ARCHIVE_WORKBENCH_GOOGLE_OAUTH_CLIENT_ID"
GOOGLE_OAUTH_CLIENT_SECRET_ENV = "ARCHIVE_WORKBENCH_GOOGLE_OAUTH_CLIENT_SECRET"
GOOGLE_OAUTH_PUBLIC_URL_ENV = "ARCHIVE_WORKBENCH_PUBLIC_URL"
OAUTH_PENDING_MAX_AGE_SECONDS = 10 * 60


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
class DriveArtifactInspection:
    kind: str
    artifact_id: str
    project_id: str
    label: str


@dataclass(frozen=True, slots=True)
class DriveUploadSummary:
    metadata: DriveFileMetadata
    local_sha256: str
    artifact_kind: str
    artifact_id: str
    project_id: str
    bundle_id: str | None = None
    team_copy_id: str | None = None


@dataclass(frozen=True, slots=True)
class DriveDownloadSummary:
    metadata: DriveFileMetadata
    destination: Path
    local_sha256: str
    artifact_kind: str
    artifact_id: str
    project_id: str
    bundle_id: str | None = None
    team_copy_id: str | None = None


@dataclass(frozen=True, slots=True)
class OAuthResult:
    token: GoogleDriveToken
    picked_file_ids: tuple[str, ...] = ()


def _local_config_root() -> Path:
    config_root = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return config_root / "archive-workbench"


def default_client_secret_path() -> Path:
    return _local_config_root() / "google_drive_client_secret.json"


def default_token_path() -> Path:
    workspace = managed_workspace()
    if workspace is not None:
        return workspace.settings / "google_drive_token.json"
    return _local_config_root() / "google_drive_token.json"


def default_oauth_pending_path() -> Path:
    workspace = managed_workspace()
    if workspace is not None:
        return workspace.settings / "google_drive_oauth_pending.json"
    return _local_config_root() / "google_drive_oauth_pending.json"


def default_picker_result_path() -> Path:
    workspace = managed_workspace()
    if workspace is not None:
        return workspace.settings / "google_drive_picker_result.json"
    return _local_config_root() / "google_drive_picker_result.json"


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


def configured_oauth_client(client_secret_path: Path | None = None) -> GoogleOAuthClient:
    """Resuelve el cliente OAuth sin exigir un JSON por integrante del equipo."""

    if client_secret_path is not None:
        return load_oauth_client(client_secret_path)
    client_id = str(os.environ.get(GOOGLE_OAUTH_CLIENT_ID_ENV, "")).strip()
    if client_id:
        client_secret = str(os.environ.get(GOOGLE_OAUTH_CLIENT_SECRET_ENV, "")).strip() or None
        return GoogleOAuthClient(
            client_id=client_id,
            client_secret=client_secret,
            auth_uri=GOOGLE_AUTH_URL,
            token_uri=GOOGLE_TOKEN_URL,
        )
    fallback = default_client_secret_path()
    if fallback.is_file():
        return load_oauth_client(fallback)
    raise ValueError(
        "Esta compilación de Archive Workbench no tiene configurado el cliente OAuth de Google Drive."
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


def _pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def _pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)[:96]
    return verifier, _pkce_challenge(verifier)


def _write_private_json(path: Path, payload: dict[str, Any]) -> Path:
    destination = path.expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp = destination.with_suffix(destination.suffix + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.chmod(temp, 0o600)
    temp.replace(destination)
    os.chmod(destination, 0o600)
    return destination


def _read_json_object(path: Path) -> dict[str, Any] | None:
    source = path.expanduser().resolve()
    if not source.is_file():
        return None
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def public_oauth_redirect_uri() -> str:
    value = str(os.environ.get(GOOGLE_OAUTH_PUBLIC_URL_ENV, "")).strip().rstrip("/")
    if not value:
        raise ValueError(
            "La distribución administrada no informó la URL local necesaria para volver desde Google Drive."
        )
    parsed = urllib.parse.urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("La URL local configurada para Google Drive no es válida.")
    return value


def prepare_google_drive_authorization(
    client_secret_path: Path | None = None,
    *,
    picker: bool = False,
    pending_path: Path | None = None,
    redirect_uri: str | None = None,
) -> str:
    """Prepara OAuth/PKCE para abrir Google en el navegador del equipo anfitrión."""

    client = configured_oauth_client(client_secret_path)
    redirect = (redirect_uri or public_oauth_redirect_uri()).rstrip("/")
    destination = pending_path or default_oauth_pending_path()
    existing = _read_json_object(destination)
    now = time.time()
    verifier = ""
    state_value = ""
    if existing:
        created_at = float(existing.get("created_at") or 0)
        if (
            now - created_at < OAUTH_PENDING_MAX_AGE_SECONDS
            and bool(existing.get("picker")) is picker
            and str(existing.get("redirect_uri") or "") == redirect
            and str(existing.get("client_id") or "") == client.client_id
        ):
            verifier = str(existing.get("code_verifier") or "")
            state_value = str(existing.get("state") or "")
    if not verifier or not state_value:
        state_value = secrets.token_urlsafe(24)
        verifier, _ = _pkce_pair()
        _write_private_json(
            destination,
            {
                "state": state_value,
                "code_verifier": verifier,
                "redirect_uri": redirect,
                "client_id": client.client_id,
                "picker": bool(picker),
                "created_at": now,
            },
        )
    return build_authorization_url(
        client,
        redirect_uri=redirect,
        state=state_value,
        code_challenge=_pkce_challenge(verifier),
        picker=picker,
    )


def complete_google_drive_authorization(
    *,
    code: str,
    state: str,
    picked_file_ids: str = "",
    client_secret_path: Path | None = None,
    token_path: Path | None = None,
    pending_path: Path | None = None,
    picker_result_path: Path | None = None,
) -> OAuthResult:
    pending = _read_json_object(pending_path or default_oauth_pending_path())
    if not pending:
        raise RuntimeError("No encontré una autorización de Google Drive pendiente en esta instalación.")
    if time.time() - float(pending.get("created_at") or 0) >= OAUTH_PENDING_MAX_AGE_SECONDS:
        raise RuntimeError("La autorización de Google Drive venció. Iniciá la conexión nuevamente.")
    if not state or state != str(pending.get("state") or ""):
        raise RuntimeError("La respuesta OAuth de Google no coincide con la solicitud iniciada.")
    clean_code = code.strip()
    if not clean_code:
        raise RuntimeError("Google no devolvió el código de autorización.")
    verifier = str(pending.get("code_verifier") or "")
    redirect_uri = str(pending.get("redirect_uri") or "")
    if not verifier or not redirect_uri:
        raise RuntimeError("La autorización pendiente de Google Drive está incompleta.")

    client = configured_oauth_client(client_secret_path)
    if client.client_id != str(pending.get("client_id") or ""):
        raise RuntimeError("El cliente OAuth cambió desde que se inició la autorización.")
    token_request = {
        "client_id": client.client_id,
        "code": clean_code,
        "code_verifier": verifier,
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri,
    }
    if client.client_secret:
        token_request["client_secret"] = client.client_secret
    previous = load_token(token_path)
    token = _token_from_response(_post_form(client.token_uri, token_request), previous=previous)
    save_token(token, token_path)
    picked = tuple(item.strip() for item in picked_file_ids.split(",") if item.strip())
    if bool(pending.get("picker")):
        if not picked:
            raise RuntimeError("Google Picker no devolvió ningún archivo seleccionado.")
        _write_private_json(
            picker_result_path or default_picker_result_path(),
            {"file_ids": list(picked), "created_at": time.time()},
        )
    return OAuthResult(token=token, picked_file_ids=picked)


def load_picker_result(path: Path | None = None, *, max_age_seconds: float = 3600) -> tuple[str, ...]:
    payload = _read_json_object(path or default_picker_result_path())
    if not payload:
        return ()
    if time.time() - float(payload.get("created_at") or 0) > max_age_seconds:
        return ()
    raw = payload.get("file_ids")
    if not isinstance(raw, list):
        return ()
    return tuple(str(item).strip() for item in raw if str(item).strip())


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
    client_secret_path: Path | None = None,
    *,
    picker: bool = False,
    token_path: Path | None = None,
    open_browser: Callable[[str], bool] | None = None,
    timeout_seconds: float = 300,
) -> OAuthResult:
    client = configured_oauth_client(client_secret_path)
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
    client_secret_path: Path | None = None,
    *,
    token_path: Path | None = None,
) -> GoogleDriveToken:
    client = configured_oauth_client(client_secret_path)
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
    client_secret_path: Path | None = None,
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


def inspect_drive_artifact(path: Path) -> DriveArtifactInspection:
    source = path.expanduser().resolve()
    if not source.is_file():
        raise ValueError(f"No existe el archivo ZIP: {source}")
    try:
        bundle = inspect_change_bundle(source)
    except (ValueError, zipfile.BadZipFile) as bundle_exc:
        try:
            team_copy = inspect_team_copy_package(source)
        except ValueError as team_exc:
            message = str(bundle_exc)
            if "ZIP válido" in message or "File is not a zip file" in message:
                raise ValueError("El archivo elegido no es un ZIP válido") from bundle_exc
            raise ValueError(
                "El ZIP elegido no es un paquete de cambios ni una copia para trabajar en equipo compatible con Archive Workbench."
            ) from team_exc
        return DriveArtifactInspection(
            kind="team_copy",
            artifact_id=team_copy.package_id,
            project_id=team_copy.project_id,
            label="Copia para trabajar en equipo",
        )
    return DriveArtifactInspection(
        kind="exchange_bundle",
        artifact_id=bundle.manifest.bundle_id,
        project_id=bundle.manifest.project_id,
        label="Paquete de cambios",
    )


def _resumable_session_url(
    *,
    metadata: dict[str, Any],
    source: Path,
    token: GoogleDriveToken,
) -> str:
    fields = "id,name,mimeType,size,webViewLink,modifiedTime,md5Checksum,appProperties"
    url = f"{DRIVE_UPLOAD_URL}?" + urllib.parse.urlencode(
        {"uploadType": "resumable", "fields": fields, "supportsAllDrives": "true"}
    )
    body = json.dumps(metadata, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    headers = _auth_headers(token)
    headers.update(
        {
            "Content-Type": "application/json; charset=UTF-8",
            "Content-Length": str(len(body)),
            "X-Upload-Content-Type": "application/zip",
            "X-Upload-Content-Length": str(source.stat().st_size),
        }
    )
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            session_url = response.headers.get("Location")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Google devolvió HTTP {exc.code}: {detail[:600]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"No pude iniciar la subida a Google Drive: {exc.reason}") from exc
    if not session_url:
        raise RuntimeError("Google Drive no devolvió la sesión necesaria para una subida reanudable.")
    return session_url


def _range_next_offset(range_header: str | None) -> int:
    if not range_header:
        return 0
    text = range_header.strip()
    if not text.startswith("bytes=0-"):
        return 0
    try:
        return int(text.split("-", 1)[1]) + 1
    except ValueError:
        return 0


def _query_resumable_upload(
    session_url: str,
    *,
    total_size: int,
    token: GoogleDriveToken,
) -> tuple[int, dict[str, Any] | None]:
    headers = _auth_headers(token)
    headers.update({"Content-Length": "0", "Content-Range": f"bytes */{total_size}"})
    request = urllib.request.Request(session_url, data=b"", headers=headers, method="PUT")
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            payload = response.read()
            decoded = json.loads(payload.decode("utf-8")) if payload else {}
            return total_size, decoded if isinstance(decoded, dict) else {}
    except urllib.error.HTTPError as exc:
        if exc.code == 308:
            return _range_next_offset(exc.headers.get("Range")), None
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Google devolvió HTTP {exc.code}: {detail[:600]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"No pude consultar el estado de la subida: {exc.reason}") from exc


def _upload_resumable_file(
    *,
    source: Path,
    session_url: str,
    token: GoogleDriveToken,
    chunk_size: int = 8 * 1024 * 1024,
    max_retries: int = 3,
) -> dict[str, Any]:
    unit = 256 * 1024
    if chunk_size < unit or chunk_size % unit:
        raise ValueError("El tamaño de bloque de Google Drive debe ser múltiplo de 256 KiB")
    total_size = source.stat().st_size
    if total_size == 0:
        headers = _auth_headers(token)
        headers.update({"Content-Length": "0", "Content-Range": "bytes */0"})
        request = urllib.request.Request(session_url, data=b"", headers=headers, method="PUT")
        return _json_request(request, timeout=180)

    offset = 0
    with source.open("rb") as handle:
        while offset < total_size:
            handle.seek(offset)
            payload = handle.read(min(chunk_size, total_size - offset))
            end = offset + len(payload) - 1
            retries = 0
            while True:
                headers = _auth_headers(token)
                headers.update(
                    {
                        "Content-Type": "application/zip",
                        "Content-Length": str(len(payload)),
                        "Content-Range": f"bytes {offset}-{end}/{total_size}",
                    }
                )
                request = urllib.request.Request(
                    session_url, data=payload, headers=headers, method="PUT"
                )
                try:
                    with urllib.request.urlopen(request, timeout=300) as response:
                        body = response.read()
                        decoded = json.loads(body.decode("utf-8")) if body else {}
                        if not isinstance(decoded, dict):
                            raise RuntimeError("Google devolvió una respuesta inesperada al completar la subida.")
                        return decoded
                except urllib.error.HTTPError as exc:
                    if exc.code == 308:
                        next_offset = _range_next_offset(exc.headers.get("Range"))
                        offset = next_offset if next_offset > offset else end + 1
                        break
                    if exc.code < 500 or retries >= max_retries:
                        detail = exc.read().decode("utf-8", errors="replace")
                        raise RuntimeError(f"Google devolvió HTTP {exc.code}: {detail[:600]}") from exc
                except urllib.error.URLError as exc:
                    if retries >= max_retries:
                        raise RuntimeError(f"La subida a Google Drive se interrumpió: {exc.reason}") from exc
                retries += 1
                time.sleep(min(2**retries, 8))
                known_offset, completed = _query_resumable_upload(
                    session_url, total_size=total_size, token=token
                )
                if completed is not None:
                    return completed
                if known_offset != offset:
                    offset = known_offset
                    break
    raise RuntimeError("La subida a Google Drive terminó sin una confirmación final.")


def upload_archive_workbench_zip_to_drive(
    archive_path: Path,
    *,
    client_secret_path: Path | None = None,
    token_path: Path | None = None,
) -> DriveUploadSummary:
    source = archive_path.expanduser().resolve()
    inspection = inspect_drive_artifact(source)
    local_sha = sha256_file(source)
    token = refresh_google_drive_token(client_secret_path, token_path=token_path)
    metadata = {
        "name": source.name,
        "mimeType": "application/zip",
        "appProperties": {
            "archive_workbench_kind": inspection.kind,
            "archive_workbench_sha256": local_sha,
            "archive_workbench_artifact_id": inspection.artifact_id,
            "archive_workbench_project_id": inspection.project_id,
        },
    }
    if inspection.kind == "exchange_bundle":
        metadata["appProperties"]["archive_workbench_bundle_id"] = inspection.artifact_id
    else:
        metadata["appProperties"]["archive_workbench_team_copy_id"] = inspection.artifact_id
    session_url = _resumable_session_url(metadata=metadata, source=source, token=token)
    uploaded = _metadata_from_payload(
        _upload_resumable_file(source=source, session_url=session_url, token=token)
    )
    return DriveUploadSummary(
        metadata=uploaded,
        local_sha256=local_sha,
        artifact_kind=inspection.kind,
        artifact_id=inspection.artifact_id,
        project_id=inspection.project_id,
        bundle_id=inspection.artifact_id if inspection.kind == "exchange_bundle" else None,
        team_copy_id=inspection.artifact_id if inspection.kind == "team_copy" else None,
    )


def upload_exchange_bundle_to_drive(
    bundle_path: Path,
    *,
    client_secret_path: Path | None = None,
    token_path: Path | None = None,
) -> DriveUploadSummary:
    """Compatibilidad: sube un paquete incremental y rechaza otros ZIP."""
    source = bundle_path.expanduser().resolve()
    inspection = inspect_drive_artifact(source)
    if inspection.kind != "exchange_bundle":
        raise ValueError("El archivo elegido es una copia para trabajar en equipo, no un paquete de cambios.")
    return upload_archive_workbench_zip_to_drive(
        source, client_secret_path=client_secret_path, token_path=token_path
    )

def _safe_download_name(name: str, file_id: str) -> str:
    base = Path(name).name.strip() or "paquete.zip"
    if not base.lower().endswith(".zip"):
        base += ".zip"
    stem = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in base)
    stem = stem[-120:] if len(stem) > 120 else stem
    return f"{file_id[:12]}_{stem}"


def download_archive_workbench_zip_from_drive(
    file_id: str,
    *,
    project_root: Path,
    client_secret_path: Path | None = None,
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

    destination_dir = project_root.expanduser().resolve() / "exchange" / "drive_downloads"
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / _safe_download_name(metadata.name, file_id.strip())
    temp = destination.with_suffix(destination.suffix + ".tmp")
    temp.unlink(missing_ok=True)
    try:
        with urllib.request.urlopen(request, timeout=300) as response, temp.open("wb") as target:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                target.write(chunk)
        temp.replace(destination)
    except urllib.error.HTTPError as exc:
        temp.unlink(missing_ok=True)
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Google devolvió HTTP {exc.code}: {detail[:600]}") from exc
    except urllib.error.URLError as exc:
        temp.unlink(missing_ok=True)
        raise RuntimeError(f"No pude descargar desde Google Drive: {exc.reason}") from exc
    except Exception:
        temp.unlink(missing_ok=True)
        raise

    try:
        inspection = inspect_drive_artifact(destination)
    except ValueError:
        destination.unlink(missing_ok=True)
        raise
    local_sha = sha256_file(destination)
    declared_sha = metadata.app_properties.get("archive_workbench_sha256")
    if declared_sha and declared_sha != local_sha:
        destination.unlink(missing_ok=True)
        raise ValueError("El SHA-256 descargado no coincide con el registrado por Archive Workbench en Drive.")
    declared_kind = metadata.app_properties.get("archive_workbench_kind")
    if declared_kind and declared_kind != inspection.kind:
        destination.unlink(missing_ok=True)
        raise ValueError("El tipo de archivo descargado no coincide con el registrado por Archive Workbench en Drive.")
    return DriveDownloadSummary(
        metadata=metadata,
        destination=destination,
        local_sha256=local_sha,
        artifact_kind=inspection.kind,
        artifact_id=inspection.artifact_id,
        project_id=inspection.project_id,
        bundle_id=inspection.artifact_id if inspection.kind == "exchange_bundle" else None,
        team_copy_id=inspection.artifact_id if inspection.kind == "team_copy" else None,
    )


def download_exchange_bundle_from_drive(
    file_id: str,
    *,
    project_root: Path,
    client_secret_path: Path | None = None,
    token_path: Path | None = None,
) -> DriveDownloadSummary:
    """Compatibilidad: descarga y exige un paquete incremental."""
    result = download_archive_workbench_zip_from_drive(
        file_id,
        project_root=project_root,
        client_secret_path=client_secret_path,
        token_path=token_path,
    )
    if result.artifact_kind != "exchange_bundle":
        result.destination.unlink(missing_ok=True)
        raise ValueError("El archivo elegido es una copia para trabajar en equipo, no un paquete de cambios.")
    return result

def pick_drive_exchange_bundle(
    client_secret_path: Path | None = None,
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
