from __future__ import annotations

from collections import Counter
from datetime import datetime
from pathlib import PurePosixPath
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from archive_workbench.contracts.common import ContractModel


class InputCharacteristics(ContractModel):
    format: Literal["pdf", "tiff", "image"]
    scanned: bool
    digital_text_layer: bool
    multipage_tiff: bool
    poor_contrast: bool
    skewed_pages: bool
    landscape_pages: bool
    mixed_orientations: bool
    text_orientation: Literal["upright", "rotated", "mixed", "unknown"] = "unknown"
    typewritten: bool
    handwritten_notes: bool
    stamps: bool
    tables_or_forms: bool
    multiple_internal_documents: bool
    unknown: bool = False


class ExpectedExtraction(ContractModel):
    minimum_page_coverage_percent: int = Field(ge=0, le=100)
    reading_order_should_be_correct: bool = True
    preserve_stamps_as_regions: bool = True
    preserve_handwriting_as_regions: bool = True
    transcribe_handwriting_automatically: bool = False
    expected_object_types: list[str] = Field(default_factory=list)
    objects_that_may_be_hidden_by_default: list[str] = Field(default_factory=list)
    critical_text_examples: list[str] = Field(default_factory=list)
    known_difficulties: list[str] = Field(default_factory=list)


class ManualGroundTruth(ContractModel):
    pages_reviewed: list[int] = Field(default_factory=list)
    expected_internal_parts: list[Any] = Field(default_factory=list)
    expected_tables: list[Any] = Field(default_factory=list)
    expected_notes: list[Any] = Field(default_factory=list)


class TestDocument(ContractModel):
    test_id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    local_path: str
    short_description: str = Field(min_length=1)
    archival_location: dict[str, str | int | None] = Field(default_factory=dict)
    input_characteristics: InputCharacteristics
    expected_extraction: ExpectedExtraction
    manual_ground_truth: ManualGroundTruth = Field(default_factory=ManualGroundTruth)
    acceptance_notes: str = ""

    @field_validator("local_path")
    @classmethod
    def validate_local_path(cls, value: str) -> str:
        path = PurePosixPath(value.replace("\\", "/"))
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("local_path debe ser relativa y no puede contener '..'")
        return str(path)


class TestCorpus(ContractModel):
    corpus_name: str = Field(min_length=1)
    created_by: str = Field(min_length=1)
    created_at: datetime
    documents: list[TestDocument] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_ids(self) -> "TestCorpus":
        ids = [item.test_id for item in self.documents]
        duplicate_ids = [key for key, count in Counter(ids).items() if count > 1]
        if duplicate_ids:
            raise ValueError(f"test_id duplicados: {duplicate_ids}")
        return self
