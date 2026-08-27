from pathlib import Path

import fitz
from PIL import Image
import pytest

from archive_workbench.domain.enums import MediaType
from archive_workbench.inspection import (
    PROCESSABLE_DOCUMENT_SUFFIXES,
    detect_media_type,
    inspect_input,
    is_processable_document_path,
)


def test_inspect_tiff(tmp_path: Path) -> None:
    path = tmp_path / "sample.tiff"
    Image.new("L", (120, 80), color=255).save(path, format="TIFF")
    result = inspect_input(path)
    assert result.media_type == MediaType.TIFF
    assert result.page_count == 1
    assert result.pages[0].likely_requires_ocr is True


def test_inspect_scanned_like_pdf(tmp_path: Path) -> None:
    path = tmp_path / "sample.pdf"
    doc = fitz.open()
    doc.new_page(width=400, height=600)
    doc.save(path)
    doc.close()
    result = inspect_input(path)
    assert result.media_type == MediaType.PDF
    assert result.page_count == 1
    assert result.pages[0].likely_requires_ocr is True


def test_landscape_page_is_informational_not_warning(tmp_path: Path) -> None:
    path = tmp_path / "landscape.pdf"
    doc = fitz.open()
    doc.new_page(width=600, height=400)
    doc.save(path)
    doc.close()
    result = inspect_input(path)
    assert result.pages[0].landscape is True
    assert not any("horizont" in warning.lower() for warning in result.warnings)
    assert not any("orientación" in item.lower() for item in result.recommendations)


@pytest.mark.parametrize(
    ("suffix", "pillow_format"),
    [
        (".png", "PNG"),
        (".jpg", "JPEG"),
        (".jpeg", "JPEG"),
        (".webp", "WEBP"),
    ],
)
def test_declared_raster_formats_are_processable(
    tmp_path: Path, suffix: str, pillow_format: str
) -> None:
    path = tmp_path / f"sample{suffix}"
    Image.new("RGB", (64, 48), color="white").save(path, format=pillow_format)

    assert suffix in PROCESSABLE_DOCUMENT_SUFFIXES
    assert is_processable_document_path(path) is True
    assert detect_media_type(path) == MediaType.IMAGE
    inspection = inspect_input(path)
    assert inspection.media_type == MediaType.IMAGE
    assert inspection.page_count == 1


def test_document_processing_suffix_contract_is_explicit() -> None:
    assert PROCESSABLE_DOCUMENT_SUFFIXES == frozenset(
        {".pdf", ".tif", ".tiff", ".png", ".jpg", ".jpeg", ".webp"}
    )


def test_bmp_is_not_part_of_document_processing_contract(tmp_path: Path) -> None:
    path = tmp_path / "sample.bmp"
    Image.new("RGB", (64, 48), color="white").save(path, format="BMP")

    assert ".bmp" not in PROCESSABLE_DOCUMENT_SUFFIXES
    assert is_processable_document_path(path) is False
    assert detect_media_type(path) == MediaType.OTHER
    inspection = inspect_input(path)
    assert inspection.media_type == MediaType.OTHER
    assert "no admitido" in inspection.warnings[0].lower()
    assert "PDF, TIFF, PNG, JPEG o WebP" in inspection.recommendations[0]
