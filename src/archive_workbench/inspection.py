from __future__ import annotations

import warnings
from pathlib import Path

import fitz
from PIL import Image, UnidentifiedImageError

from archive_workbench.contracts.extraction import InputInspection, PageInspection
from archive_workbench.domain.enums import MediaType
from archive_workbench.identity import sha256_file
from archive_workbench.audiovisual import AUDIO_EXTENSIONS, VIDEO_EXTENSIONS

_TIFF_SIGNATURES = (b"II*\x00", b"MM\x00*", b"II+\x00", b"MM\x00+")
_PDF_SIGNATURE = b"%PDF-"


def detect_media_type(path: str | Path) -> MediaType:
    source = Path(path)
    with source.open("rb") as handle:
        signature = handle.read(8)
    if signature.startswith(_PDF_SIGNATURE):
        return MediaType.PDF
    if any(signature.startswith(candidate) for candidate in _TIFF_SIGNATURES):
        return MediaType.TIFF
    suffix = source.suffix.lower()
    if suffix in {".png", ".jpg", ".jpeg", ".bmp", ".webp"}:
        return MediaType.IMAGE
    if suffix in AUDIO_EXTENSIONS:
        return MediaType.AUDIO
    if suffix in VIDEO_EXTENSIONS:
        return MediaType.VIDEO
    return MediaType.OTHER


def inspect_input(path: str | Path) -> InputInspection:
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(source)
    media_type = detect_media_type(source)
    common = {
        "path": str(source),
        "media_type": media_type,
        "sha256": sha256_file(source),
        "byte_size": source.stat().st_size,
    }
    if media_type == MediaType.PDF:
        return _inspect_pdf(source, common)
    if media_type in {MediaType.TIFF, MediaType.IMAGE}:
        return _inspect_image(source, common)
    if media_type in {MediaType.AUDIO, MediaType.VIDEO}:
        return InputInspection(
            **common,
            warnings=[],
            recommendations=[
                "Registrar el original y completar su inspección técnica audiovisual con FFprobe."
            ],
        )
    return InputInspection(
        **common,
        warnings=["Formato todavía no inspeccionable por el módulo inicial."],
        recommendations=["Registrar el archivo, pero no enviarlo todavía a extracción."],
    )


def _inspect_pdf(source: Path, common: dict[str, object]) -> InputInspection:
    pages: list[PageInspection] = []
    warnings_out: list[str] = []
    recommendations: list[str] = []
    with fitz.open(source) as document:
        for index, page in enumerate(document, start=1):
            rect = page.rect
            text = page.get_text("text") or ""
            images = page.get_images(full=True)
            text_characters = len(text.strip())
            requires_ocr = text_characters < 40
            pages.append(
                PageInspection(
                    page=index,
                    width=rect.width,
                    height=rect.height,
                    rotation=page.rotation,
                    landscape=rect.width > rect.height,
                    text_characters=text_characters,
                    embedded_images=len(images),
                    likely_requires_ocr=requires_ocr,
                )
            )
    ocr_pages = [page.page for page in pages if page.likely_requires_ocr]
    if ocr_pages:
        warnings_out.append(f"{len(ocr_pages)} página(s) tienen muy poco texto digital.")
        recommendations.append("Usar modo OCR automático o completo y revisar una muestra.")
    return InputInspection(
        **common,
        page_count=len(pages),
        pages=pages,
        warnings=warnings_out,
        recommendations=recommendations,
    )


def _inspect_image(source: Path, common: dict[str, object]) -> InputInspection:
    pages: list[PageInspection] = []
    warnings_out: list[str] = []
    recommendations = [
        "Preservar el TIFF o la imagen original sin modificaciones.",
        "Crear derivados de trabajo por página para OCR y previsualización.",
    ]
    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            with Image.open(source) as image:
                frame_count = getattr(image, "n_frames", 1)
                for frame in range(frame_count):
                    image.seek(frame)
                    width, height = image.size
                    pages.append(
                        PageInspection(
                            page=frame + 1,
                            width=width,
                            height=height,
                            rotation=0,
                            landscape=width > height,
                            text_characters=None,
                            embedded_images=1,
                            likely_requires_ocr=True,
                        )
                    )
            for warning in caught:
                warnings_out.append(str(warning.message))
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError(f"No se pudo inspeccionar la imagen {source}: {exc}") from exc

    megapixels = [page.width * page.height / 1_000_000 for page in pages]
    if megapixels and max(megapixels) > 100:
        warnings_out.append("Hay al menos una página de más de 100 megapíxeles.")
        recommendations.append("Usar libvips/pyvips para generar derivados sin cargar todo en RAM.")
    if len(pages) > 1:
        recommendations.append("Separar el TIFF multipágina en derivados por página para procesarlo.")
    return InputInspection(
        **common,
        page_count=len(pages),
        pages=pages,
        warnings=warnings_out,
        recommendations=recommendations,
    )
