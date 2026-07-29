from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

Sha256 = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ContractModel(BaseModel):
    """Base estricta para todos los contratos persistidos o intercambiados."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)
