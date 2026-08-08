from pathlib import Path

import pytest
from pydantic import ValidationError

from archive_workbench.contracts.digital import FileInstanceRecord
from archive_workbench.contracts.extraction import ImageManifestRecord, PageGeometry


HASH = "a" * 64


def test_absolute_file_path_is_rejected() -> None:
    with pytest.raises(ValidationError):
        FileInstanceRecord(
            id="instance",
            digital_object_id="object",
            storage_root="project",
            relative_path=str(Path.cwd() / "outside-project-file.pdf"),
        )


def test_image_uses_reference_or_base64_but_not_both() -> None:
    ImageManifestRecord(
        page_id="p1",
        digital_object_id="d1",
        extraction_run_id="r1",
        page=1,
        sha256=HASH,
        width=100,
        height=200,
        path="pages/0001.webp",
    )
    with pytest.raises(ValidationError):
        ImageManifestRecord(
            page_id="p1",
            digital_object_id="d1",
            extraction_run_id="r1",
            page=1,
            sha256=HASH,
            width=100,
            height=200,
            path="pages/0001.webp",
            data_b64="abc",
        )


def test_normalized_geometry_range() -> None:
    with pytest.raises(ValidationError):
        PageGeometry(page=1, polygon=[(0, 0), (2, 0), (2, 1), (0, 1)])
