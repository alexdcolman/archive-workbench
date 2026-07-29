from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import Field

from archive_workbench.contracts.common import ContractModel, utc_now


class ArchivalDateExpression(ContractModel):
    start: date | None = None
    end: date | None = None
    display_text: str | None = None
    approximate: bool = False


class ArchivalUnitRecord(ContractModel):
    id: str
    parent_id: str | None = None
    level_key: str
    reference_code: str | None = None
    title: str = Field(min_length=1)
    dates: ArchivalDateExpression = Field(default_factory=ArchivalDateExpression)
    extent: str | None = None
    medium: str | None = None
    scope_content: str | None = None
    archivist_note: str | None = None
    description_date: date | None = None
    extra_metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)
    created_by: str
    updated_at: datetime = Field(default_factory=utc_now)
    updated_by: str
    revision: int = Field(default=1, ge=1)
