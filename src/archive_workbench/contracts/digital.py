from __future__ import annotations

from datetime import datetime
from pathlib import PurePosixPath

from pydantic import Field, field_validator

from archive_workbench.contracts.common import ContractModel, Sha256, utc_now
from archive_workbench.domain.enums import FilePresence, MediaType


class DigitalObjectRecord(ContractModel):
    id: str
    media_type: MediaType
    original_filename: str = Field(min_length=1)
    sha256: Sha256
    byte_size: int = Field(ge=0)
    page_count: int | None = Field(default=None, ge=1)
    created_at: datetime = Field(default_factory=utc_now)


class DigitalObjectUnitLink(ContractModel):
    id: str
    digital_object_id: str
    archival_unit_id: str
    relation_type: str = "represents"
    page_start: int | None = Field(default=None, ge=1)
    page_end: int | None = Field(default=None, ge=1)


class FileInstanceRecord(ContractModel):
    id: str
    digital_object_id: str
    storage_root: str
    relative_path: str
    presence: FilePresence = FilePresence.UNVERIFIED
    last_seen_at: datetime | None = None
    verified_sha256: Sha256 | None = None

    @field_validator("relative_path")
    @classmethod
    def validate_relative_path(cls, value: str) -> str:
        path = PurePosixPath(value.replace("\\", "/"))
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("relative_path debe ser relativa y no puede contener '..'")
        if str(path) in {"", "."}:
            raise ValueError("relative_path no puede estar vacía")
        return str(path)


class RemoteLocationRecord(ContractModel):
    id: str
    digital_object_id: str
    provider: str
    url: str
    remote_path: str | None = None
    notes: str | None = None
