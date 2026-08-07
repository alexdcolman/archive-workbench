from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import Field, model_validator

from archive_workbench.contracts.common import ContractModel, Sha256
from archive_workbench.domain.enums import MediaType


class AudiovisualTechnicalMetadata(ContractModel):
    media_type: MediaType
    container_format: str | None = None
    duration_seconds: float | None = Field(default=None, ge=0)
    audio_codec: str | None = None
    video_codec: str | None = None
    channels: int | None = Field(default=None, ge=1)
    sample_rate_hz: int | None = Field(default=None, ge=1)
    width: int | None = Field(default=None, ge=1)
    height: int | None = Field(default=None, ge=1)
    frame_rate: float | None = Field(default=None, ge=0)
    raw_probe: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_media_type(self) -> "AudiovisualTechnicalMetadata":
        if self.media_type not in {MediaType.AUDIO, MediaType.VIDEO}:
            raise ValueError("Los metadatos audiovisuales requieren audio o video")
        return self


class AudiovisualDescription(ContractModel):
    title: str | None = None
    producer: str | None = None
    channel: str | None = None
    responsible: str | None = None
    provenance: str | None = None
    recorded_date: date | None = None
    rights: str | None = None
    description: str | None = None


class AudiovisualAssetRecord(ContractModel):
    relative_path: str
    sha256: Sha256
    byte_size: int = Field(ge=0)
    mime_type: str | None = None
    container_format: str | None = None
    codec: str | None = None
    source_sha256: Sha256
    ffmpeg_version: str | None = None
    command: list[str] = Field(default_factory=list)


class TranscriptSegmentInput(ContractModel):
    start_time: float = Field(ge=0)
    end_time: float = Field(ge=0)
    text: str

    @model_validator(mode="after")
    def validate_time_order(self) -> "TranscriptSegmentInput":
        if self.end_time < self.start_time:
            raise ValueError("end_time no puede ser menor que start_time")
        return self


class TranscriptionRequest(ContractModel):
    backend: str = "faster_whisper"
    model_name: str = "small"
    device: str = "cpu"
    language: str | None = None
    options: dict[str, Any] = Field(default_factory=dict)
