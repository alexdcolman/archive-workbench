from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from archive_workbench.contracts.common import ContractModel, Sha256, utc_now


class OcrTruthEngineSpec(ContractModel):
    """Motor que participa en una comparación contra verdad terreno."""

    engine_key: Literal["tesseract", "docling", "surya"]
    profile_path: str
    enabled: bool = True


class OcrTruthBenchmarkProfile(ContractModel):
    """Configuración reproducible del benchmark con verdad terreno."""

    schema_version: str = "1.0"
    benchmark_key: str = "ocr_truth_es_v1"
    engines: list[OcrTruthEngineSpec] = Field(
        default_factory=lambda: [
            OcrTruthEngineSpec(
                engine_key="tesseract",
                profile_path="config/extraction_tesseract.yaml",
            ),
            OcrTruthEngineSpec(
                engine_key="docling",
                profile_path="config/extraction_docling_es.yaml",
            ),
            OcrTruthEngineSpec(
                engine_key="surya",
                profile_path="config/extraction_surya_es.yaml",
            ),
        ],
        min_length=1,
    )
    ground_truth_root: str = "ground_truth/ocr"
    unicode_form: Literal["NFC", "NFKC"] = "NFC"
    collapse_whitespace: bool = True
    case_sensitive: bool = True

    @model_validator(mode="after")
    def validate_engines(self) -> "OcrTruthBenchmarkProfile":
        keys = [item.engine_key for item in self.engines if item.enabled]
        if not keys:
            raise ValueError("El benchmark requiere al menos un motor habilitado")
        if len(keys) != len(set(keys)):
            raise ValueError("Cada motor puede aparecer una sola vez")
        return self


class OcrTruthReference(ContractModel):
    source_key: str
    page: int = Field(ge=1)
    path: str
    sha256: Sha256
    character_count: int = Field(ge=0)
    word_count: int = Field(ge=0)


class OcrTruthCandidateMetrics(ContractModel):
    engine_key: Literal["tesseract", "docling", "surya"]
    profile_key: str
    backend: str
    engine_version: str | None = None
    page: int = Field(ge=1)
    reference_sha256: Sha256
    reference_character_count: int = Field(ge=0)
    candidate_character_count: int = Field(ge=0)
    reference_word_count: int = Field(ge=0)
    candidate_word_count: int = Field(ge=0)
    character_edit_distance: int = Field(ge=0)
    word_edit_distance: int = Field(ge=0)
    cer: float = Field(ge=0)
    wer: float = Field(ge=0)
    elapsed_seconds: float = Field(ge=0)
    text_path: str
    raw_paths: list[str] = Field(default_factory=list)
    log_path: str | None = None


class OcrTruthEngineAggregate(ContractModel):
    engine_key: Literal["tesseract", "docling", "surya"]
    profile_key: str
    pages: int = Field(ge=1)
    reference_character_count: int = Field(ge=0)
    candidate_character_count: int = Field(ge=0)
    reference_word_count: int = Field(ge=0)
    candidate_word_count: int = Field(ge=0)
    character_edit_distance: int = Field(ge=0)
    word_edit_distance: int = Field(ge=0)
    cer: float = Field(ge=0)
    wer: float = Field(ge=0)
    elapsed_seconds: float = Field(ge=0)


class OcrTruthBenchmarkManifest(ContractModel):
    schema_version: str = "1.0"
    benchmark_id: str
    digital_object_id: str
    source_key: str
    preprocessing_run_id: str
    source_sha256: Sha256
    profile: OcrTruthBenchmarkProfile
    created_at: datetime = Field(default_factory=utc_now)
    references: list[OcrTruthReference] = Field(default_factory=list)
    candidates: list[OcrTruthCandidateMetrics] = Field(default_factory=list)
    aggregates: list[OcrTruthEngineAggregate] = Field(default_factory=list)
    output_root: str
