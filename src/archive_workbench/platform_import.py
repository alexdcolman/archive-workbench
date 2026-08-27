from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import shutil
from typing import Any
from urllib.parse import parse_qs, urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from archive_workbench.audiovisual import update_audiovisual_description
from archive_workbench.catalog_management import register_local_file
from archive_workbench.contracts.audiovisual import AudiovisualDescription
from archive_workbench.contracts.platform import PlatformImportRequest
from archive_workbench.db.models import AudiovisualMedia, SourceRegistration
from archive_workbench.inspection import MediaType, inspect_input


@dataclass(frozen=True)
class PlatformRuntimeStatus:
    yt_dlp_available: bool
    yt_dlp_version: str | None
    ffmpeg_available: bool
    ffprobe_available: bool
    deno_available: bool
    node_available: bool


@dataclass(frozen=True)
class PlatformImportResult:
    media_id: str
    digital_object_id: str
    source_key: str
    relative_path: str
    sha256: str
    platform: str
    platform_id: str
    title: str
    canonical_url: str
    reused_existing_path: bool


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_yt_dlp():
    try:
        import yt_dlp
    except ImportError as exc:  # pragma: no cover - depende del extra opcional
        raise RuntimeError(
            "La incorporación desde plataformas no está instalada. "
            "Instalá Archive Workbench con el extra 'platform'."
        ) from exc
    return yt_dlp


def platform_runtime_status() -> PlatformRuntimeStatus:
    try:
        yt_dlp = _load_yt_dlp()
        version = getattr(getattr(yt_dlp, "version", None), "__version__", None)
        available = True
    except RuntimeError:
        version = None
        available = False
    return PlatformRuntimeStatus(
        yt_dlp_available=available,
        yt_dlp_version=version,
        ffmpeg_available=shutil.which("ffmpeg") is not None,
        ffprobe_available=shutil.which("ffprobe") is not None,
        deno_available=shutil.which("deno") is not None,
        node_available=shutil.which("node") is not None,
    )


def _platform_name(info: dict[str, Any]) -> str:
    extractor_key = str(info.get("extractor_key") or info.get("extractor") or "platform").strip()
    cleaned = "".join(ch.lower() if ch.isalnum() else "_" for ch in extractor_key).strip("_")
    return cleaned or "platform"


def _legacy_platform_grouping(metadata: dict[str, Any]) -> dict[str, Any] | None:
    if metadata.get("platform_grouping") is not None:
        grouping = metadata.get("platform_grouping")
        return dict(grouping) if isinstance(grouping, dict) else None
    requested_url = str(metadata.get("requested_url") or "").strip()
    if not requested_url or "youtube" not in str(metadata.get("platform") or "").lower():
        return None
    playlist_ids = parse_qs(urlparse(requested_url).query).get("list") or []
    if not playlist_ids:
        return None
    playlist_id = str(playlist_ids[0]).strip()
    if not playlist_id:
        return None
    return {
        "kind": "platform_grouping",
        "title": None,
        "platform_id": playlist_id,
        "webpage_url": f"https://www.youtube.com/playlist?list={playlist_id}",
        "index": None,
        "item_count": None,
    }


def _platform_grouping_snapshot(info: dict[str, Any]) -> dict[str, Any] | None:
    title = info.get("playlist_title") or info.get("playlist")
    grouping_id = info.get("playlist_id")
    webpage_url = info.get("playlist_webpage_url")
    index = info.get("playlist_index")
    count = info.get("playlist_count")
    if not any(value is not None for value in (title, grouping_id, webpage_url, index, count)):
        return None
    return {
        "kind": "platform_grouping",
        "title": title,
        "platform_id": str(grouping_id) if grouping_id is not None else None,
        "webpage_url": webpage_url,
        "index": index,
        "item_count": count,
    }


def _metadata_snapshot(info: dict[str, Any], *, request_url: str, media_kind: str) -> dict[str, Any]:
    requested_formats = info.get("requested_formats") or []
    if not requested_formats and info.get("format_id"):
        requested_formats = [info]
    formats = [
        {
            "format_id": row.get("format_id"),
            "ext": row.get("ext"),
            "format_note": row.get("format_note"),
            "resolution": row.get("resolution"),
            "vcodec": row.get("vcodec"),
            "acodec": row.get("acodec"),
            "filesize": row.get("filesize") or row.get("filesize_approx"),
        }
        for row in requested_formats
    ]
    webpage_url = info.get("webpage_url") or info.get("original_url") or request_url
    platform = _platform_name(info)
    platform_id = str(info.get("id") or "")
    publication = {
        "kind": "platform_publication",
        "platform": platform,
        "platform_id": platform_id,
        "webpage_url": webpage_url,
        "title": info.get("title"),
        "channel": info.get("channel") or info.get("uploader"),
        "upload_date": info.get("upload_date"),
    }
    return {
        "requested_url": request_url,
        "webpage_url": webpage_url,
        "platform": platform,
        "platform_id": platform_id,
        "extractor": info.get("extractor"),
        "extractor_key": info.get("extractor_key"),
        "title": info.get("title"),
        "uploader": info.get("uploader"),
        "uploader_id": info.get("uploader_id"),
        "channel": info.get("channel"),
        "channel_id": info.get("channel_id"),
        "upload_date": info.get("upload_date"),
        "timestamp": info.get("timestamp"),
        "duration": info.get("duration"),
        "license": info.get("license"),
        "live_status": info.get("live_status"),
        "description": info.get("description"),
        "media_kind_requested": media_kind,
        "formats": formats,
        "publication": publication,
        "platform_grouping": _platform_grouping_snapshot(info),
    }


def _extract_info(*, url: str, download: bool, outtmpl: str | None = None, media_kind: str = "video") -> tuple[Any, dict[str, Any]]:
    yt_dlp = _load_yt_dlp()
    options: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "skip_download": not download,
    }
    if download:
        if outtmpl is None:
            raise ValueError("Falta la ruta de descarga")
        options.update(
            {
                "outtmpl": outtmpl,
                "overwrites": False,
                "continuedl": True,
                "format": "ba/b" if media_kind == "audio" else "bv*+ba/b",
            }
        )
        if media_kind == "video":
            options["merge_output_format"] = "mp4"
    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=download)
    except Exception as exc:
        download_error = getattr(getattr(yt_dlp, "utils", None), "DownloadError", ())
        extractor_error = getattr(getattr(yt_dlp, "utils", None), "ExtractorError", ())
        known = tuple(
            cls for cls in (download_error, extractor_error) if isinstance(cls, type)
        )
        if known and isinstance(exc, known):
            raise RuntimeError(f"La plataforma rechazó o no pudo resolver el material: {exc}") from exc
        raise
    if not isinstance(info, dict):
        raise RuntimeError("La plataforma no devolvió metadatos utilizables")
    if info.get("_type") in {"playlist", "multi_video"} or info.get("entries"):
        raise ValueError(
            "Esta URL corresponde a una agrupación de plataforma, no a un audio o video individual. "
            "Archive Workbench no la convierte automáticamente en una Colección o Serie: abrí el material concreto que querés incorporar."
        )
    if not info.get("id"):
        raise RuntimeError("La plataforma no devolvió un identificador estable")
    return yt_dlp, info


def inspect_platform_url(url: str) -> dict[str, Any]:
    _, info = _extract_info(url=url.strip(), download=False)
    return _metadata_snapshot(info, request_url=url.strip(), media_kind="video")


def _downloaded_media_path(destination: Path, *, platform_id: str, expected_kind: str) -> Path:
    candidates = [
        path
        for path in destination.glob(f"{platform_id}.*")
        if path.is_file() and not path.name.endswith((".part", ".ytdl", ".temp"))
    ]
    valid: list[Path] = []
    expected = MediaType.VIDEO if expected_kind == "video" else MediaType.AUDIO
    for path in candidates:
        try:
            inspection = inspect_input(path)
        except (OSError, ValueError):
            continue
        if inspection.media_type == expected:
            valid.append(path)
    if not valid:
        raise RuntimeError("yt-dlp terminó sin dejar un archivo audiovisual utilizable")
    return max(valid, key=lambda path: path.stat().st_size)


def import_platform_media(
    session: Session,
    *,
    project_root: str | Path,
    project_id: str,
    request: PlatformImportRequest,
    actor: str,
) -> PlatformImportResult:
    root = Path(project_root).resolve()
    url = str(request.url)
    _, preview = _extract_info(url=url, download=False, media_kind=request.media_kind)
    platform = _platform_name(preview)
    platform_id = str(preview["id"])
    destination = root / "corpus" / "importados" / "plataformas" / platform
    destination.mkdir(parents=True, exist_ok=True)
    outtmpl = str(destination / f"{platform_id}.%(ext)s")

    yt_dlp, info = _extract_info(
        url=url,
        download=True,
        outtmpl=outtmpl,
        media_kind=request.media_kind,
    )
    path = _downloaded_media_path(
        destination,
        platform_id=platform_id,
        expected_kind=request.media_kind,
    )
    relative_path = path.relative_to(root).as_posix()
    digest = _sha256_file(path)

    registration_result = register_local_file(
        session,
        project_root=root,
        project_id=project_id,
        archival_unit_id=request.archival_unit_id,
        relative_path=relative_path,
        registered_by=actor or "local_user",
    )
    registration = session.scalar(
        select(SourceRegistration).where(
            SourceRegistration.project_id == project_id,
            SourceRegistration.digital_object_id == registration_result.digital_object_id,
            SourceRegistration.source_key == registration_result.source_key,
        )
    )
    if registration is None:
        raise RuntimeError("No se pudo recuperar el registro de procedencia del archivo incorporado")

    metadata = _metadata_snapshot(info, request_url=url, media_kind=request.media_kind)
    yt_version = getattr(getattr(yt_dlp, "version", None), "__version__", None)
    metadata.update(
        {
            "downloaded_at": _utc_now().isoformat(),
            "yt_dlp_version": yt_version,
            "access_conditions": request.access_conditions,
            "authorization_confirmed": True,
            "incorporated_relative_path": relative_path,
            "incorporated_sha256": digest,
            "incorporated_byte_size": path.stat().st_size,
            "incorporated_extension": path.suffix.lower().lstrip("."),
            "local_copy": {
                "kind": "incorporated_copy",
                "relative_path": relative_path,
                "sha256": digest,
                "byte_size": path.stat().st_size,
                "extension": path.suffix.lower().lstrip("."),
            },
        }
    )
    payload = dict(registration.source_payload_json or {})
    payload["origin"] = "platform_import"
    payload["platform_import"] = metadata
    registration.source_payload_json = payload
    registration.registered_at = _utc_now()
    registration.registered_by = actor or "local_user"

    media = session.scalar(
        select(AudiovisualMedia).where(
            AudiovisualMedia.digital_object_id == registration_result.digital_object_id
        )
    )
    if media is None:
        raise RuntimeError("El archivo descargado no ingresó al circuito audiovisual")
    canonical_url = str(metadata.get("webpage_url") or url)
    update_audiovisual_description(
        session,
        media_id=media.id,
        description=AudiovisualDescription(
            title=str(info.get("title") or path.stem),
            producer=None,
            channel=(str(info.get("channel") or info.get("uploader")) if (info.get("channel") or info.get("uploader")) else None),
            responsible=None,
            provenance=canonical_url,
            recorded_date=None,
            rights=request.access_conditions,
            description=None,
        ),
        actor=actor or "local_user",
    )
    session.flush()
    return PlatformImportResult(
        media_id=media.id,
        digital_object_id=registration_result.digital_object_id,
        source_key=registration.source_key,
        relative_path=relative_path,
        sha256=digest,
        platform=platform,
        platform_id=platform_id,
        title=str(info.get("title") or path.stem),
        canonical_url=canonical_url,
        reused_existing_path=not registration_result.file_instance_created,
    )


def platform_origin_for_digital_object(
    session: Session,
    *,
    project_id: str,
    digital_object_id: str,
) -> dict[str, Any] | None:
    registrations = session.scalars(
        select(SourceRegistration)
        .where(
            SourceRegistration.project_id == project_id,
            SourceRegistration.digital_object_id == digital_object_id,
        )
        .order_by(SourceRegistration.registered_at.desc(), SourceRegistration.id)
    ).all()
    for registration in registrations:
        payload = registration.source_payload_json or {}
        platform = payload.get("platform_import")
        if isinstance(platform, dict):
            normalized = dict(platform)
            if normalized.get("platform_grouping") is None:
                normalized["platform_grouping"] = _legacy_platform_grouping(normalized)
            return normalized
    return None
