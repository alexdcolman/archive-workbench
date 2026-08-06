from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from archive_workbench.contracts.common import ContractModel



RegionSemanticRole = Literal[
    "body_text",
    "cover",
    "page_header",
    "page_footer",
    "page_number",
    "stamp",
    "signature",
    "handwriting",
    "illustration",
    "preprinted",
]

REGION_SEMANTIC_OBJECT_TYPES: dict[str, str] = {
    "body_text": "paragraph",
    "cover": "title",
    "page_header": "page_header",
    "page_footer": "page_footer",
    "page_number": "page_footer",
    "stamp": "stamp",
    "signature": "handwritten_region",
    "handwriting": "handwritten_region",
    "illustration": "figure",
    "preprinted": "form_field",
}

class NormalizedRegionBox(ContractModel):
    x0: float = Field(ge=0, le=1)
    y0: float = Field(ge=0, le=1)
    x1: float = Field(ge=0, le=1)
    y1: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def validate_order(self) -> "NormalizedRegionBox":
        if self.x1 <= self.x0 or self.y1 <= self.y0:
            raise ValueError("La caja regional debe tener ancho y alto positivos")
        return self

    def polygon(self) -> list[tuple[float, float]]:
        return [
            (self.x0, self.y0),
            (self.x1, self.y0),
            (self.x1, self.y1),
            (self.x0, self.y1),
        ]


class RegionOcrOptions(ContractModel):
    image_variant: Literal["original", "grayscale_autocontrast", "otsu"] = "original"
    psm: int = Field(default=6, ge=0, le=13)
    languages: list[str] = Field(default_factory=lambda: ["spa"], min_length=1)
    object_granularity: Literal["line", "paragraph"] = "paragraph"
    minimum_characters_warning: int = Field(default=5, ge=0)

    @model_validator(mode="after")
    def reject_osd_modes(self) -> "RegionOcrOptions":
        if self.psm in {0, 1, 2, 12}:
            raise ValueError(
                "La extracción regional preserva la orientación y no admite PSM con OSD"
            )
        return self


class RegionDefinition(ContractModel):
    region_key: str = Field(min_length=1, max_length=120)
    label: str = Field(min_length=1, max_length=300)
    page: int = Field(ge=1)
    reading_order: int = Field(ge=0)
    bbox: NormalizedRegionBox
    mode: Literal["ocr", "manual"]
    object_type: str = Field(min_length=1, max_length=100)
    semantic_role: RegionSemanticRole | None = None
    hidden_by_default: bool = False
    ocr: RegionOcrOptions | None = None
    initial_text: str = ""
    note: str | None = None

    @model_validator(mode="after")
    def validate_mode(self) -> "RegionDefinition":
        if self.mode == "ocr" and self.ocr is None:
            raise ValueError(f"La región OCR '{self.region_key}' requiere opciones ocr")
        if self.mode == "manual" and self.ocr is not None:
            raise ValueError(f"La región manual '{self.region_key}' no debe declarar opciones ocr")
        if self.semantic_role is not None:
            expected = REGION_SEMANTIC_OBJECT_TYPES[self.semantic_role]
            if self.object_type != expected:
                raise ValueError(
                    f"La clasificación '{self.semantic_role}' requiere object_type '{expected}'"
                )
        return self


class RegionTemplate(ContractModel):
    schema_version: str = "1.0"
    template_key: str = Field(min_length=1, max_length=120)
    profile_key: str = Field(min_length=1, max_length=120)
    source_key: str = Field(min_length=1, max_length=500)
    description: str = ""
    tesseract_command: str = "tesseract"
    timeout_seconds: int = Field(default=900, ge=30, le=86400)
    regions: list[RegionDefinition] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_regions(self) -> "RegionTemplate":
        keys = [item.region_key for item in self.regions]
        if len(keys) != len(set(keys)):
            raise ValueError("Los region_key no deben repetirse")
        positions = [(item.page, item.reading_order) for item in self.regions]
        if len(positions) != len(set(positions)):
            raise ValueError("El reading_order debe ser único dentro de cada página")
        return self


class RegionExportRecord(ContractModel):
    schema_version: str = "1.0"
    extraction_run_id: str
    digital_object_id: str
    source_key: str
    template_key: str
    region_key: str
    label: str
    page: int = Field(ge=1)
    reading_order: int = Field(ge=0)
    mode: Literal["ocr", "manual"]
    object_type: str
    semantic_role: RegionSemanticRole | None = None
    bbox: NormalizedRegionBox
    crop_path: str
    raw_json_path: str | None = None
    raw_tsv_path: str | None = None
    raw_text_path: str | None = None
    object_count: int = Field(default=0, ge=0)
    character_count: int = Field(default=0, ge=0)
    status: str
    warning: str | None = None
    note: str | None = None

class RegionExtractionManifest(ContractModel):
    schema_version: str = "1.0"
    run_id: str
    digital_object_id: str
    preprocessing_run_id: str
    source_key: str
    source_sha256: str
    template: RegionTemplate
    engine: str = "tesseract_regions"
    engine_version: str | None = None
    options_hash: str
    created_by: str
    created_at: str
    completed_at: str
    status: str
    warnings: list[str] = Field(default_factory=list)
    pages_processed: list[int] = Field(default_factory=list)
    object_count: int = Field(default=0, ge=0)
    paragraph_count: int = Field(default=0, ge=0)
    character_count: int = Field(default=0, ge=0)
    output_root: str
    objects_path: str
    paragraphs_path: str
    images_path: str
    regions_path: str
