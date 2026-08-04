from __future__ import annotations

import importlib.metadata
import json
import math
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

import fitz
from PIL import Image, ImageFilter, ImageOps
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from archive_workbench.contracts.decisions import ProjectDecisions
from archive_workbench.contracts.preprocessing import (
    DerivativeAssetRecord,
    DerivativeProfile,
    PreprocessingManifest,
)
from archive_workbench.db.models import (
    DerivativeAsset,
    DigitalObject,
    FileInstance,
    PreprocessingRun,
    SourceRegistration,
)
from archive_workbench.domain.enums import FilePresence, MediaType
from archive_workbench.identity import new_id, sha256_file, sha256_json
from archive_workbench.inspection import inspect_input
from archive_workbench.tesseract_engine import otsu_threshold



OCR_TREATMENT_LABELS = {
    "original": "Sin cambios",
    "grayscale_autocontrast": "Escala de grises y autocontraste",
    "otsu": "Binarización Otsu",
    "denoise_autocontrast": "Reducción de ruido y autocontraste",
}


def profile_for_ocr_treatment(
    decisions: ProjectDecisions, treatment: str
) -> DerivativeProfile:
    if treatment not in OCR_TREATMENT_LABELS:
        raise ValueError(f"Tratamiento OCR desconocido: {treatment}")
    base = profile_from_decisions(decisions)
    return base.model_copy(
        update={
            "profile_key": ("default" if treatment == "original" else f"ocr_{treatment}"),
            "ocr_treatment": treatment,
        }
    )


def apply_ocr_treatment(image: Image.Image, treatment: str) -> Image.Image:
    """Genera un derivado OCR conservador sin alterar el original ni la previsualización."""
    if treatment == "original":
        return image.copy()
    gray = ImageOps.grayscale(image)
    if treatment == "denoise_autocontrast":
        gray = gray.filter(ImageFilter.MedianFilter(size=3))
    gray = ImageOps.autocontrast(gray)
    if treatment in {"grayscale_autocontrast", "denoise_autocontrast"}:
        return gray
    if treatment == "otsu":
        threshold = otsu_threshold(gray)
        return gray.point(lambda value: 255 if value > threshold else 0, mode="1")
    raise ValueError(f"Tratamiento OCR desconocido: {treatment}")

@dataclass(slots=True)
class PreprocessingSummary:
    objects_seen: int = 0
    runs_created: int = 0
    runs_reused: int = 0
    failed: int = 0
    assets_created: int = 0
    warnings: list[str] = field(default_factory=list)


@dataclass(slots=True)
class PreprocessingStatusRow:
    source_key: str
    title: str
    media_type: str
    page_count: int | None
    run_status: str | None
    profile_key: str | None
    ocr_treatment: str | None
    assets: int
    output_root: str | None


def profile_from_decisions(decisions: ProjectDecisions) -> DerivativeProfile:
    return DerivativeProfile(
        preview_dpi=decisions.tiff.preview_dpi,
        ocr_dpi=decisions.tiff.target_ocr_dpi,
        preview_format=decisions.tiff.preview_format,
        ocr_format=decisions.tiff.ocr_derivative_format,
        use_pyvips_when_available=decisions.tiff.use_pyvips_when_available,
        auto_rotate=False,
    )


def _package_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def _pyvips_module():
    try:
        import pyvips  # type: ignore[import-not-found]
    except (ImportError, OSError):
        return None
    return pyvips


def _mime_type(fmt: str) -> str:
    return {
        "webp": "image/webp",
        "jpeg": "image/jpeg",
        "png": "image/png",
        "tiff": "image/tiff",
    }[fmt]


def _extension(fmt: str) -> str:
    return "jpg" if fmt == "jpeg" else ("tif" if fmt == "tiff" else fmt)


def _relative(path: Path, project_root: Path) -> str:
    return path.resolve().relative_to(project_root.resolve()).as_posix()


def _save_pillow(image: Image.Image, path: Path, fmt: str, *, quality: int, dpi: float | None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    save_options: dict[str, object] = {}
    if dpi is not None and math.isfinite(dpi) and dpi > 0:
        save_options["dpi"] = (float(dpi), float(dpi))
    if fmt == "webp":
        save_options.update(quality=quality, method=4)
    elif fmt == "jpeg":
        save_options.update(quality=max(quality, 85), optimize=True)
    elif fmt == "png":
        save_options.update(compress_level=6)
    elif fmt == "tiff":
        save_options.update(compression="tiff_deflate")
    image.save(path, format=fmt.upper() if fmt != "jpeg" else "JPEG", **save_options)


def _normalized_pillow_image(image: Image.Image) -> Image.Image:
    # No se aplica rotación EXIF ni detección automática: la geometría del original se conserva.
    if image.mode == "1":
        return image.convert("L")
    if image.mode in {"L", "RGB"}:
        return image.copy()
    if "A" in image.getbands():
        rgba = image.convert("RGBA")
        background = Image.new("RGB", rgba.size, "white")
        background.paste(rgba, mask=rgba.getchannel("A"))
        return background
    return image.convert("RGB")


def _source_dpi_from_pillow(image: Image.Image) -> float | None:
    value = image.info.get("dpi")
    if isinstance(value, tuple) and value:
        candidates = [
            float(item)
            for item in value[:2]
            if item and 50 <= float(item) <= 2400
        ]
        if candidates:
            return sum(candidates) / len(candidates)
    if isinstance(value, (int, float)) and 50 <= float(value) <= 2400:
        return float(value)
    return None


def _preview_size(
    width: int,
    height: int,
    *,
    source_dpi: float | None,
    profile: DerivativeProfile,
) -> tuple[int, int]:
    scale = 1.0
    if source_dpi and source_dpi > profile.preview_dpi:
        scale = min(scale, profile.preview_dpi / source_dpi)
    longest = max(width, height)
    if longest * scale > profile.preview_max_long_edge_px:
        scale = min(scale, profile.preview_max_long_edge_px / longest)
    if scale >= 0.999:
        return width, height
    return max(1, round(width * scale)), max(1, round(height * scale))


def _asset_record(
    *,
    run_id: str,
    digital_object_id: str,
    page: int,
    kind: str,
    path: Path,
    project_root: Path,
    fmt: str,
    width: int,
    height: int,
    dpi: int | None,
    source_width: float,
    source_height: float,
    source_dpi: float | None,
    backend: str,
) -> DerivativeAssetRecord:
    return DerivativeAssetRecord(
        asset_id=new_id(),
        preprocessing_run_id=run_id,
        digital_object_id=digital_object_id,
        page=page,
        kind=kind,  # type: ignore[arg-type]
        relative_path=_relative(path, project_root),
        mime_type=_mime_type(fmt),
        sha256=sha256_file(path),
        byte_size=path.stat().st_size,
        width=width,
        height=height,
        dpi=dpi,
        source_width=source_width,
        source_height=source_height,
        source_dpi=source_dpi,
        rotation_applied=0,
        backend=backend,
    )


def _render_pdf(
    source: Path,
    *,
    project_root: Path,
    output_dir: Path,
    run_id: str,
    digital_object_id: str,
    profile: DerivativeProfile,
) -> tuple[list[DerivativeAssetRecord], list[str], str, str | None]:
    assets: list[DerivativeAssetRecord] = []
    preview_fmt = profile.preview_format
    ocr_fmt = profile.ocr_format
    with fitz.open(source) as document:
        for page_number, page in enumerate(document, start=1):
            source_rect = page.rect

            ocr_pix = page.get_pixmap(dpi=profile.ocr_dpi, colorspace=fitz.csRGB, alpha=False)
            rendered_ocr = Image.frombytes("RGB", (ocr_pix.width, ocr_pix.height), ocr_pix.samples)
            ocr_image = apply_ocr_treatment(rendered_ocr, profile.ocr_treatment)
            ocr_path = output_dir / "ocr" / f"page_{page_number:04d}.{_extension(ocr_fmt)}"
            _save_pillow(
                ocr_image,
                ocr_path,
                ocr_fmt,
                quality=profile.preview_quality,
                dpi=profile.ocr_dpi,
            )
            assets.append(
                _asset_record(
                    run_id=run_id,
                    digital_object_id=digital_object_id,
                    page=page_number,
                    kind="ocr",
                    path=ocr_path,
                    project_root=project_root,
                    fmt=ocr_fmt,
                    width=ocr_image.width,
                    height=ocr_image.height,
                    dpi=profile.ocr_dpi,
                    source_width=source_rect.width,
                    source_height=source_rect.height,
                    source_dpi=72.0,
                    backend="pymupdf",
                )
            )

            preview_pix = page.get_pixmap(
                dpi=profile.preview_dpi, colorspace=fitz.csRGB, alpha=False
            )
            preview_image = Image.frombytes(
                "RGB", (preview_pix.width, preview_pix.height), preview_pix.samples
            )
            preview_path = (
                output_dir / "preview" / f"page_{page_number:04d}.{_extension(preview_fmt)}"
            )
            _save_pillow(
                preview_image,
                preview_path,
                preview_fmt,
                quality=profile.preview_quality,
                dpi=profile.preview_dpi,
            )
            assets.append(
                _asset_record(
                    run_id=run_id,
                    digital_object_id=digital_object_id,
                    page=page_number,
                    kind="preview",
                    path=preview_path,
                    project_root=project_root,
                    fmt=preview_fmt,
                    width=preview_image.width,
                    height=preview_image.height,
                    dpi=profile.preview_dpi,
                    source_width=source_rect.width,
                    source_height=source_rect.height,
                    source_dpi=72.0,
                    backend="pymupdf",
                )
            )
    return assets, [], "pymupdf", _package_version("PyMuPDF")


def _render_raster_pillow(
    source: Path,
    *,
    project_root: Path,
    output_dir: Path,
    run_id: str,
    digital_object_id: str,
    profile: DerivativeProfile,
) -> tuple[list[DerivativeAssetRecord], list[str], str, str | None]:
    inspection = inspect_input(source)
    max_megapixels = max(
        ((float(page.width) * float(page.height)) / 1_000_000 for page in inspection.pages),
        default=0.0,
    )
    if max_megapixels > profile.pillow_megapixel_guard:
        if profile.ocr_treatment != "original":
            raise RuntimeError(
                f"La imagen alcanza {max_megapixels:.1f} MP. El tratamiento "
                f"{OCR_TREATMENT_LABELS[profile.ocr_treatment]!r} requiere cargarla con "
                "Pillow y supera el límite de memoria configurado. Use 'Sin cambios' o "
                "procese una copia más pequeña; el original no fue modificado."
            )
        raise RuntimeError(
            f"La imagen alcanza {max_megapixels:.1f} MP y supera el límite seguro de Pillow "
            f"({profile.pillow_megapixel_guard:.0f} MP). Instale el extra [tiff] para usar pyvips."
        )

    assets: list[DerivativeAssetRecord] = []
    warnings_out: list[str] = []
    with Image.open(source) as opened:
        frame_count = getattr(opened, "n_frames", 1)
        for frame in range(frame_count):
            opened.seek(frame)
            source_dpi = _source_dpi_from_pillow(opened)
            image = _normalized_pillow_image(opened)
            source_width, source_height = image.size

            # Para rasteres no se inventan píxeles: el derivado OCR conserva resolución nativa.
            ocr_image = apply_ocr_treatment(image, profile.ocr_treatment)
            ocr_path = output_dir / "ocr" / f"page_{frame + 1:04d}.{_extension(profile.ocr_format)}"
            _save_pillow(
                ocr_image,
                ocr_path,
                profile.ocr_format,
                quality=profile.preview_quality,
                dpi=source_dpi,
            )
            assets.append(
                _asset_record(
                    run_id=run_id,
                    digital_object_id=digital_object_id,
                    page=frame + 1,
                    kind="ocr",
                    path=ocr_path,
                    project_root=project_root,
                    fmt=profile.ocr_format,
                    width=ocr_image.width,
                    height=ocr_image.height,
                    dpi=round(source_dpi) if source_dpi else None,
                    source_width=source_width,
                    source_height=source_height,
                    source_dpi=source_dpi,
                    backend="pillow",
                )
            )

            preview_width, preview_height = _preview_size(
                source_width,
                source_height,
                source_dpi=source_dpi,
                profile=profile,
            )
            if (preview_width, preview_height) == image.size:
                preview_image = image.copy()
            else:
                preview_image = image.resize(
                    (preview_width, preview_height), Image.Resampling.LANCZOS
                )
            preview_path = (
                output_dir
                / "preview"
                / f"page_{frame + 1:04d}.{_extension(profile.preview_format)}"
            )
            _save_pillow(
                preview_image,
                preview_path,
                profile.preview_format,
                quality=profile.preview_quality,
                dpi=min(source_dpi, profile.preview_dpi) if source_dpi else None,
            )
            assets.append(
                _asset_record(
                    run_id=run_id,
                    digital_object_id=digital_object_id,
                    page=frame + 1,
                    kind="preview",
                    path=preview_path,
                    project_root=project_root,
                    fmt=profile.preview_format,
                    width=preview_image.width,
                    height=preview_image.height,
                    dpi=(
                        round(min(source_dpi, profile.preview_dpi))
                        if source_dpi
                        else None
                    ),
                    source_width=source_width,
                    source_height=source_height,
                    source_dpi=source_dpi,
                    backend="pillow",
                )
            )
            if source_dpi is None:
                warnings_out.append(
                    f"Página {frame + 1}: el raster no declara DPI; se conservaron los píxeles nativos."
                )
    return assets, warnings_out, "pillow", _package_version("Pillow")


def _render_raster_pyvips(
    source: Path,
    *,
    page_count: int,
    project_root: Path,
    output_dir: Path,
    run_id: str,
    digital_object_id: str,
    profile: DerivativeProfile,
    pyvips,
) -> tuple[list[DerivativeAssetRecord], list[str], str, str | None]:
    assets: list[DerivativeAssetRecord] = []
    warnings_out: list[str] = []
    is_tiff = source.suffix.lower() in {".tif", ".tiff"}
    for frame in range(page_count):
        load_options: dict[str, object] = {"access": "sequential"}
        if is_tiff:
            load_options.update(page=frame, n=1, autorotate=False)
        image = pyvips.Image.new_from_file(str(source), **load_options)
        source_width = int(image.width)
        source_height = int(image.height)
        source_dpi = None
        try:
            xres = float(image.xres)
            yres = float(image.yres)
            candidate_dpi = ((xres + yres) / 2.0) * 25.4
            if 50 <= candidate_dpi <= 2400:
                source_dpi = candidate_dpi
        except (AttributeError, TypeError, ValueError):
            source_dpi = None

        if image.bands in {2, 4}:
            image = image.flatten(background=[255] * (image.bands - 1))
        if image.bands not in {1, 3}:
            image = image.colourspace("srgb")

        ocr_path = output_dir / "ocr" / f"page_{frame + 1:04d}.{_extension(profile.ocr_format)}"
        ocr_path.parent.mkdir(parents=True, exist_ok=True)
        image.write_to_file(str(ocr_path))
        assets.append(
            _asset_record(
                run_id=run_id,
                digital_object_id=digital_object_id,
                page=frame + 1,
                kind="ocr",
                path=ocr_path,
                project_root=project_root,
                fmt=profile.ocr_format,
                width=source_width,
                height=source_height,
                dpi=round(source_dpi) if source_dpi else None,
                source_width=source_width,
                source_height=source_height,
                source_dpi=source_dpi,
                backend="pyvips",
            )
        )

        preview_width, preview_height = _preview_size(
            source_width,
            source_height,
            source_dpi=source_dpi,
            profile=profile,
        )
        preview = image
        if (preview_width, preview_height) != (source_width, source_height):
            preview = image.resize(preview_width / source_width)
        preview_path = (
            output_dir / "preview" / f"page_{frame + 1:04d}.{_extension(profile.preview_format)}"
        )
        preview_path.parent.mkdir(parents=True, exist_ok=True)
        save_options = {"Q": profile.preview_quality} if profile.preview_format in {"webp", "jpeg"} else {}
        preview.write_to_file(str(preview_path), **save_options)
        assets.append(
            _asset_record(
                run_id=run_id,
                digital_object_id=digital_object_id,
                page=frame + 1,
                kind="preview",
                path=preview_path,
                project_root=project_root,
                fmt=profile.preview_format,
                width=int(preview.width),
                height=int(preview.height),
                dpi=(round(min(source_dpi, profile.preview_dpi)) if source_dpi else None),
                source_width=source_width,
                source_height=source_height,
                source_dpi=source_dpi,
                backend="pyvips",
            )
        )
        if source_dpi is None:
            warnings_out.append(
                f"Página {frame + 1}: el raster no declara DPI; se conservaron los píxeles nativos."
            )
    return assets, warnings_out, "pyvips", _package_version("pyvips")


def _iter_objects(
    session: Session,
    *,
    source_keys: set[str] | None,
) -> Iterator[tuple[DigitalObject, FileInstance, str]]:
    statement = (
        select(DigitalObject, FileInstance, SourceRegistration.source_key)
        .join(FileInstance, FileInstance.digital_object_id == DigitalObject.id)
        .join(SourceRegistration, SourceRegistration.digital_object_id == DigitalObject.id)
        .where(FileInstance.presence == FilePresence.PRESENT.value)
        .order_by(SourceRegistration.source_key, FileInstance.relative_path)
    )
    if source_keys:
        statement = statement.where(SourceRegistration.source_key.in_(source_keys))
    seen: set[str] = set()
    for digital_object, file_instance, source_key in session.execute(statement):
        if digital_object.id in seen:
            continue
        seen.add(digital_object.id)
        yield digital_object, file_instance, str(source_key)


def _reusable_run(
    session: Session,
    *,
    digital_object_id: str,
    source_sha256: str,
    options: dict[str, object],
    project_root: Path,
) -> PreprocessingRun | None:
    runs = session.scalars(
        select(PreprocessingRun)
        .where(
            PreprocessingRun.digital_object_id == digital_object_id,
            PreprocessingRun.source_sha256 == source_sha256,
            PreprocessingRun.status.in_(["completed", "completed_with_warnings"]),
        )
        .order_by(PreprocessingRun.created_at.desc())
    ).all()
    for run in runs:
        stored_options = dict(run.options_json or {})
        # Las corridas anteriores a 0.36.0 no declaraban este campo; su valor era
        # materialmente equivalente a "original".
        stored_options.setdefault("ocr_treatment", "original")
        if stored_options != options:
            continue
        if not run.manifest_path:
            continue
        assets = session.scalars(
            select(DerivativeAsset).where(DerivativeAsset.preprocessing_run_id == run.id)
        ).all()
        if not assets:
            continue
        if not (project_root / run.manifest_path).is_file():
            continue
        if any(not (project_root / asset.relative_path).is_file() for asset in assets):
            continue
        return run
    return None


def _insert_assets(session: Session, records: list[DerivativeAssetRecord]) -> None:
    for record in records:
        session.add(
            DerivativeAsset(
                id=record.asset_id,
                preprocessing_run_id=record.preprocessing_run_id,
                digital_object_id=record.digital_object_id,
                page_number=record.page,
                kind=record.kind,
                relative_path=record.relative_path,
                mime_type=record.mime_type,
                sha256=record.sha256,
                byte_size=record.byte_size,
                width=record.width,
                height=record.height,
                dpi=record.dpi,
                source_width=record.source_width,
                source_height=record.source_height,
                source_dpi=record.source_dpi,
                rotation_applied=record.rotation_applied,
                backend=record.backend,
            )
        )


def prepare_derivatives(
    session: Session,
    *,
    project_root: str | Path,
    decisions: ProjectDecisions,
    source_keys: set[str] | None = None,
    force: bool = False,
    profile: DerivativeProfile | None = None,
) -> PreprocessingSummary:
    root = Path(project_root).resolve()
    profile = profile or profile_from_decisions(decisions)
    options = profile.model_dump(mode="json")
    options_hash = sha256_json(options)
    summary = PreprocessingSummary()

    for digital_object, file_instance, source_key in _iter_objects(
        session, source_keys=source_keys
    ):
        summary.objects_seen += 1
        source = root / file_instance.relative_path
        if not source.is_file():
            summary.failed += 1
            summary.warnings.append(f"{source_key}: la copia local ya no está presente")
            continue

        stat = source.stat()
        stat_unchanged = (
            file_instance.byte_size_seen == stat.st_size
            and file_instance.mtime_ns == stat.st_mtime_ns
            and file_instance.verified_sha256 == digital_object.sha256
        )
        if not stat_unchanged:
            actual_sha256 = sha256_file(source)
            file_instance.byte_size_seen = stat.st_size
            file_instance.mtime_ns = stat.st_mtime_ns
            file_instance.verified_sha256 = actual_sha256
            file_instance.last_seen_at = datetime.now(timezone.utc)
            if actual_sha256 != digital_object.sha256:
                file_instance.presence = FilePresence.MODIFIED.value
                summary.failed += 1
                summary.warnings.append(
                    f"{source_key}: el archivo cambió desde su registro; ejecute scan-files "
                    "y vuelva a registrarlo antes de generar derivados"
                )
                continue
            file_instance.presence = FilePresence.PRESENT.value

        if not force:
            reusable = _reusable_run(
                session,
                digital_object_id=digital_object.id,
                source_sha256=digital_object.sha256,
                options=options,
                project_root=root,
            )
            if reusable is not None:
                session.execute(
                    update(PreprocessingRun)
                    .where(
                        PreprocessingRun.digital_object_id == digital_object.id,
                        PreprocessingRun.id != reusable.id,
                    )
                    .values(is_current=False)
                )
                reusable.is_current = True
                summary.runs_reused += 1
                continue

        run_id = new_id()
        relative_output_root = (
            Path("derivatives") / digital_object.id / run_id
        ).as_posix()
        final_output = root / relative_output_root
        temp_output = final_output.parent / f".{run_id}.tmp"
        if temp_output.exists():
            shutil.rmtree(temp_output)
        temp_output.mkdir(parents=True, exist_ok=False)

        run = PreprocessingRun(
            id=run_id,
            digital_object_id=digital_object.id,
            source_sha256=digital_object.sha256,
            profile_key=profile.profile_key,
            options_json=options,
            options_hash=options_hash,
            backend="pending",
            backend_version=None,
            status="running",
            is_current=False,
            output_root=relative_output_root,
            warnings_json=[],
        )
        session.add(run)
        session.flush()

        try:
            media_type = MediaType(digital_object.media_type)
            if media_type == MediaType.PDF:
                records, warnings_out, backend, backend_version = _render_pdf(
                    source,
                    project_root=root,
                    output_dir=temp_output,
                    run_id=run_id,
                    digital_object_id=digital_object.id,
                    profile=profile,
                )
            elif media_type in {MediaType.TIFF, MediaType.IMAGE}:
                inspection = inspect_input(source)
                pyvips = _pyvips_module() if profile.use_pyvips_when_available else None
                use_pyvips = pyvips is not None and profile.ocr_treatment == "original" and (
                    media_type == MediaType.TIFF
                    or any(
                        (float(page.width) * float(page.height)) / 1_000_000
                        > profile.pillow_megapixel_guard
                        for page in inspection.pages
                    )
                )
                if use_pyvips:
                    records, warnings_out, backend, backend_version = _render_raster_pyvips(
                        source,
                        page_count=inspection.page_count or 1,
                        project_root=root,
                        output_dir=temp_output,
                        run_id=run_id,
                        digital_object_id=digital_object.id,
                        profile=profile,
                        pyvips=pyvips,
                    )
                else:
                    records, warnings_out, backend, backend_version = _render_raster_pillow(
                        source,
                        project_root=root,
                        output_dir=temp_output,
                        run_id=run_id,
                        digital_object_id=digital_object.id,
                        profile=profile,
                    )
            else:
                raise RuntimeError(f"Formato no soportado para derivados: {media_type.value}")

            # Los registros se calcularon con la ruta temporal; se reemplaza por la ruta final.
            for record in records:
                temp_rel = Path(record.relative_path)
                try:
                    suffix = temp_rel.relative_to(_relative(temp_output, root))
                except ValueError:
                    suffix = Path(record.kind) / Path(record.relative_path).name
                record.relative_path = (Path(relative_output_root) / suffix).as_posix()

            completed_at = datetime.now(timezone.utc)
            manifest = PreprocessingManifest(
                run_id=run_id,
                digital_object_id=digital_object.id,
                source_sha256=digital_object.sha256,
                source_media_type=digital_object.media_type,
                profile=profile,
                options_hash=options_hash,
                backend=backend,
                backend_version=backend_version,
                status="completed_with_warnings" if warnings_out else "completed",
                warnings=warnings_out,
                assets=records,
                created_at=run.created_at,
                completed_at=completed_at,
            )
            manifest_path_temp = temp_output / "manifest.json"
            manifest_path_temp.write_text(
                json.dumps(manifest.model_dump(mode="json"), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            final_output.parent.mkdir(parents=True, exist_ok=True)
            if final_output.exists():
                shutil.rmtree(final_output)
            temp_output.rename(final_output)

            session.execute(
                update(PreprocessingRun)
                .where(
                    PreprocessingRun.digital_object_id == digital_object.id,
                    PreprocessingRun.id != run_id,
                )
                .values(is_current=False)
            )
            run.backend = backend
            run.backend_version = backend_version
            run.status = manifest.status
            run.is_current = True
            run.manifest_path = (Path(relative_output_root) / "manifest.json").as_posix()
            run.warnings_json = warnings_out
            run.completed_at = completed_at
            _insert_assets(session, records)
            summary.runs_created += 1
            summary.assets_created += len(records)
            summary.warnings.extend(f"{source_key}: {warning}" for warning in warnings_out)
            session.flush()
        except Exception as exc:
            if temp_output.exists():
                shutil.rmtree(temp_output, ignore_errors=True)
            if final_output.exists():
                shutil.rmtree(final_output, ignore_errors=True)
            run.status = "failed"
            run.backend = run.backend if run.backend != "pending" else "unknown"
            run.warnings_json = [str(exc)]
            run.completed_at = datetime.now(timezone.utc)
            summary.failed += 1
            summary.warnings.append(f"{source_key}: {exc}")
            session.flush()

    return summary


def preprocessing_status_rows(session: Session) -> list[PreprocessingStatusRow]:
    source_rows = session.execute(
        select(
            SourceRegistration.source_key,
            SourceRegistration.source_payload_json,
            DigitalObject,
        )
        .join(DigitalObject, DigitalObject.id == SourceRegistration.digital_object_id)
        .order_by(SourceRegistration.source_key)
    ).all()
    rows: list[PreprocessingStatusRow] = []
    for source_key, source_payload, digital_object in source_rows:
        current = session.scalar(
            select(PreprocessingRun)
            .where(
                PreprocessingRun.digital_object_id == digital_object.id,
                PreprocessingRun.is_current.is_(True),
            )
            .order_by(PreprocessingRun.created_at.desc())
        )
        if current is None:
            current = session.scalar(
                select(PreprocessingRun)
                .where(PreprocessingRun.digital_object_id == digital_object.id)
                .order_by(PreprocessingRun.created_at.desc())
            )
        asset_count = 0
        if current is not None:
            asset_count = len(
                session.scalars(
                    select(DerivativeAsset).where(
                        DerivativeAsset.preprocessing_run_id == current.id
                    )
                ).all()
            )
        title = str(source_payload.get("short_description") or source_key)
        rows.append(
            PreprocessingStatusRow(
                source_key=str(source_key),
                title=title,
                media_type=digital_object.media_type,
                page_count=digital_object.page_count,
                run_status=current.status if current else None,
                profile_key=current.profile_key if current else None,
                ocr_treatment=(
                    str((current.options_json or {}).get("ocr_treatment", "original"))
                    if current
                    else None
                ),
                assets=asset_count,
                output_root=current.output_root if current else None,
            )
        )
    return rows
