from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import Field, model_validator

from archive_workbench.contracts.common import ContractModel, Sha256, utc_now
from archive_workbench.domain.enums import ExtractionStatus, MediaType


class PageGeometry(ContractModel):
    page: int = Field(ge=1)
    polygon: list[tuple[float, float]] = Field(min_length=4)
    coordinate_space: Literal["normalized", "pixels", "pdf_points"] = "normalized"

    @model_validator(mode="after")
    def validate_normalized(self) -> "PageGeometry":
        if self.coordinate_space == "normalized":
            for x, y in self.polygon:
                if not (0 <= x <= 1 and 0 <= y <= 1):
                    raise ValueError("Coordenadas normalizadas deben estar entre 0 y 1")
        return self


class ExtractionProfile(ContractModel):
    """Opciones reproducibles para una extracción OCR/layout."""

    schema_version: str = "1.0"
    profile_key: str = "docling_tesseract_es_v1"
    backend: Literal["docling_cli", "tesseract_tsv"] = "docling_cli"
    docling_command: str = "docling"
    tesseract_command: str = "tesseract"
    pipeline: Literal["standard"] = "standard"
    ocr_engine: str = "tesseract"
    ocr_languages: list[str] = Field(default_factory=lambda: ["spa"], min_length=1)
    force_ocr: bool = True
    extract_tables: bool = True
    table_mode: Literal["fast", "accurate"] = "accurate"
    psm: int | None = Field(default=3, ge=0, le=13)
    device: Literal["auto", "cpu", "cuda"] = "auto"
    fallback_device: Literal["cpu"] | None = "cpu"
    retry_on_accelerator_error: bool = True
    num_threads: int = Field(default=4, ge=1, le=64)
    page_batch_size: int = Field(default=1, ge=1, le=64)
    document_timeout_seconds: int = Field(default=900, ge=30, le=86400)
    use_ocr_derivatives: bool = True
    image_export_mode: Literal["placeholder", "referenced"] = "placeholder"
    minimum_characters_per_page_warning: int = Field(default=20, ge=0)
    artifacts_path: str | None = None
    image_variant: Literal["original", "grayscale_autocontrast", "otsu"] = "original"
    object_granularity: Literal["line", "paragraph"] = "line"
    layout_hint: Literal["automatic", "newspaper_columns", "single_block", "sparse"] = "automatic"


class OcrBenchmarkProfile(ContractModel):
    """Matriz pequeña y reproducible para comparar OCR sin declarar un ganador automático."""

    schema_version: str = "1.0"
    profile_key: str = "tesseract_es_quality_gate_v1"
    tesseract_command: str = "tesseract"
    languages: list[str] = Field(default_factory=lambda: ["spa"], min_length=1)
    psm_modes: list[int] = Field(default_factory=lambda: [3, 4, 6, 11], min_length=1)
    image_variants: list[Literal["original", "grayscale_autocontrast", "otsu"]] = Field(
        default_factory=lambda: ["original", "grayscale_autocontrast", "otsu"],
        min_length=1,
    )
    timeout_seconds: int = Field(default=900, ge=30, le=86400)

    @model_validator(mode="after")
    def validate_psm_modes(self) -> "OcrBenchmarkProfile":
        if any(psm < 0 or psm > 13 for psm in self.psm_modes):
            raise ValueError("Los PSM deben estar entre 0 y 13")
        unsupported = sorted(set(self.psm_modes) & {0, 1, 2, 12})
        if unsupported:
            raise ValueError(
                "El benchmark preserva orientación y requiere OCR; no admite PSM "
                + ", ".join(map(str, unsupported))
            )
        if len(set(self.psm_modes)) != len(self.psm_modes):
            raise ValueError("Los PSM no deben repetirse")
        if len(set(self.image_variants)) != len(self.image_variants):
            raise ValueError("Las variantes de imagen no deben repetirse")
        return self


class OcrCandidateMetrics(ContractModel):
    candidate_id: str
    page: int = Field(ge=1)
    psm: int = Field(ge=0, le=13)
    image_variant: str
    character_count: int = Field(ge=0)
    word_count: int = Field(ge=0)
    line_count: int = Field(ge=0)
    mean_confidence: float | None = Field(default=None, ge=0, le=100)
    high_confidence_ratio: float | None = Field(default=None, ge=0, le=1)
    alphanumeric_ratio: float = Field(ge=0, le=1)
    suspicious_symbol_ratio: float = Field(ge=0, le=1)
    heuristic_score: float = Field(ge=0, le=1)
    text_path: str
    tsv_path: str
    image_path: str


class OcrBenchmarkManifest(ContractModel):
    schema_version: str = "1.0"
    benchmark_id: str
    digital_object_id: str
    source_key: str
    preprocessing_run_id: str
    source_sha256: Sha256
    profile: OcrBenchmarkProfile
    created_at: datetime = Field(default_factory=utc_now)
    candidates: list[OcrCandidateMetrics] = Field(default_factory=list)
    output_root: str


class ExtractedObjectRecord(ContractModel):
    schema_version: str = "1.0"
    object_id: str
    digital_object_id: str
    extraction_run_id: str
    part_id: str | None = None
    parent_object_id: str | None = None
    order_index: int = Field(ge=0)
    object_type: str
    original_text: str = ""
    geometry: list[PageGeometry] = Field(default_factory=list)
    source_label: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    language: str | None = None
    hidden_by_default: bool = False
    attributes: dict[str, Any] = Field(default_factory=dict)


class ParagraphExportRecord(ContractModel):
    schema_version: str = "1.0"
    paragraph_id: str
    digital_object_id: str
    extraction_run_id: str
    page: int | None = Field(default=None, ge=1)
    order_index: int = Field(ge=0)
    object_type: str
    text: str
    bboxes: list[list[float]] = Field(default_factory=list)
    origin_object_ids: list[str] = Field(default_factory=list)


class ImageManifestRecord(ContractModel):
    schema_version: str = "1.0"
    page_id: str
    digital_object_id: str
    extraction_run_id: str
    page: int = Field(ge=1)
    sha256: Sha256
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    dpi: int | None = Field(default=None, gt=0)
    path: str | None = None
    data_b64: str | None = None
    mime_type: str = "image/webp"

    @model_validator(mode="after")
    def validate_storage(self) -> "ImageManifestRecord":
        if bool(self.path) == bool(self.data_b64):
            raise ValueError("Debe existir exactamente uno entre path y data_b64")
        return self


class ExtractionManifest(ContractModel):
    schema_version: str = "1.0"
    run_id: str
    digital_object_id: str
    preprocessing_run_id: str
    source_sha256: Sha256
    source_media_type: MediaType
    profile: ExtractionProfile
    engine: str
    engine_version: str | None = None
    model_versions: dict[str, str] = Field(default_factory=dict)
    options: dict[str, Any] = Field(default_factory=dict)
    options_hash: Sha256
    created_by: str
    created_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = None
    status: ExtractionStatus
    warnings: list[str] = Field(default_factory=list)
    pages_processed: list[int] = Field(default_factory=list)
    object_count: int = Field(default=0, ge=0)
    paragraph_count: int = Field(default=0, ge=0)
    character_count: int = Field(default=0, ge=0)
    output_root: str | None = None
    raw_pages_path: str | None = None
    objects_path: str | None = None
    paragraphs_path: str | None = None
    images_path: str | None = None


class PageInspection(ContractModel):
    page: int = Field(ge=1)
    width: int | float = Field(gt=0)
    height: int | float = Field(gt=0)
    rotation: int = 0
    landscape: bool = False
    text_characters: int | None = Field(default=None, ge=0)
    embedded_images: int | None = Field(default=None, ge=0)
    likely_requires_ocr: bool | None = None


class InputInspection(ContractModel):
    path: str
    media_type: MediaType
    sha256: Sha256
    byte_size: int = Field(ge=0)
    page_count: int | None = Field(default=None, ge=1)
    pages: list[PageInspection] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
