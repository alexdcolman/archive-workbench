from pathlib import Path

import fitz
from PIL import Image

from archive_workbench.domain.enums import MediaType
from archive_workbench.inspection import inspect_input


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
