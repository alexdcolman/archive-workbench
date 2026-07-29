from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from archive_workbench.contracts.common import ContractModel, Sha256, utc_now


class DerivativeProfile(ContractModel):
    """Opciones reproducibles para generar derivados de trabajo."""

    schema_version: str = "1.0"
    profile_key: str = "default"
    preview_dpi: int = Field(default=150, ge=72, le=300)
    ocr_dpi: int = Field(default=300, ge=150, le=600)
    preview_format: Literal["webp", "jpeg", "png"] = "webp"
    ocr_format: Literal["png", "tiff"] = "png"
    preview_quality: int = Field(default=82, ge=1, le=100)
    preview_max_long_edge_px: int = Field(default=2400, ge=512, le=10000)
    preserve_native_raster_for_ocr: bool = True
    auto_rotate: bool = False
    pillow_megapixel_guard: float = Field(default=100.0, ge=10, le=1000)
    use_pyvips_when_available: bool = True


class DerivativeAssetRecord(ContractModel):
    schema_version: str = "1.0"
    asset_id: str
    preprocessing_run_id: str
    digital_object_id: str
    page: int = Field(ge=1)
    kind: Literal["preview", "ocr"]
    relative_path: str
    mime_type: str
    sha256: Sha256
    byte_size: int = Field(ge=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    dpi: int | None = Field(default=None, gt=0)
    source_width: float | None = Field(default=None, gt=0)
    source_height: float | None = Field(default=None, gt=0)
    source_dpi: float | None = Field(default=None, gt=0)
    rotation_applied: int = 0
    backend: str
    created_at: datetime = Field(default_factory=utc_now)


class PreprocessingManifest(ContractModel):
    schema_version: str = "1.0"
    run_id: str
    digital_object_id: str
    source_sha256: Sha256
    source_media_type: str
    profile: DerivativeProfile
    options_hash: Sha256
    backend: str
    backend_version: str | None = None
    status: Literal["completed", "completed_with_warnings", "failed"]
    warnings: list[str] = Field(default_factory=list)
    assets: list[DerivativeAssetRecord] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime = Field(default_factory=utc_now)
