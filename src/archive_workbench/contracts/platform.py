from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, HttpUrl, field_validator


class PlatformImportRequest(BaseModel):
    url: HttpUrl
    archival_unit_id: str = Field(min_length=1)
    media_kind: Literal["video", "audio"] = "video"
    access_conditions: str = Field(min_length=3, max_length=2000)
    authorization_confirmed: bool

    @field_validator("access_conditions")
    @classmethod
    def _clean_access_conditions(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Indicá las condiciones de acceso o autorización")
        return cleaned

    @field_validator("authorization_confirmed")
    @classmethod
    def _require_authorization(cls, value: bool) -> bool:
        if not value:
            raise ValueError("La incorporación requiere confirmar que el uso está autorizado")
        return value
