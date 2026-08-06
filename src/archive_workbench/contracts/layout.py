from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from archive_workbench.contracts.common import ContractModel

LifecycleStatus = Literal["active", "archived"]
ColumnSource = Literal["candidate", "manual"]


class LayoutColumn(ContractModel):
    column_id: str = Field(min_length=1, max_length=120)
    label: str = Field(min_length=1, max_length=300)
    order_index: int = Field(ge=0)
    object_ids: list[str] = Field(default_factory=list)
    source: ColumnSource
    evidence_note: str | None = None
    lifecycle_status: LifecycleStatus = "active"
    created_by: str = Field(min_length=1, max_length=200)
    created_at: datetime
    updated_by: str = Field(min_length=1, max_length=200)
    updated_at: datetime


class LayoutStructure(ContractModel):
    schema_version: Literal["1.0"] = "1.0"
    columns: list[LayoutColumn] = Field(default_factory=list)
    candidate_fingerprint: str | None = Field(default=None, max_length=128)
    candidate_algorithm: str | None = Field(default=None, max_length=100)
    candidate_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    applied_by: str | None = Field(default=None, max_length=200)
    applied_at: datetime | None = None
    evidence_note: str | None = None

    @model_validator(mode="after")
    def validate_columns(self) -> "LayoutStructure":
        column_ids = [item.column_id for item in self.columns]
        if len(column_ids) != len(set(column_ids)):
            raise ValueError("Los column_id no deben repetirse")
        active = [item for item in self.columns if item.lifecycle_status == "active"]
        orders = [item.order_index for item in active]
        if len(orders) != len(set(orders)):
            raise ValueError("El orden de las columnas activas no debe repetirse")
        assigned: list[str] = []
        for column in active:
            if len(column.object_ids) != len(set(column.object_ids)):
                raise ValueError("Una columna no puede repetir objetos")
            assigned.extend(column.object_ids)
        if len(assigned) != len(set(assigned)):
            raise ValueError("Un objeto no puede pertenecer a dos columnas activas")
        return self
