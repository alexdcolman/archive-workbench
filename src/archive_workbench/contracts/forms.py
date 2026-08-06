from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from archive_workbench.contracts.common import ContractModel

CheckboxState = Literal["marked", "unmarked", "indeterminate"]
LifecycleStatus = Literal["active", "archived"]
ControlSource = Literal["candidate", "manual"]


class FormGroup(ContractModel):
    group_id: str = Field(min_length=1, max_length=120)
    label: str = Field(min_length=1, max_length=300)
    note: str | None = None
    lifecycle_status: LifecycleStatus = "active"
    created_by: str = Field(min_length=1, max_length=200)
    created_at: datetime
    updated_by: str = Field(min_length=1, max_length=200)
    updated_at: datetime


class FormControl(ContractModel):
    control_id: str = Field(min_length=1, max_length=120)
    group_id: str | None = Field(default=None, max_length=120)
    marker_object_id: str | None = Field(default=None, max_length=120)
    label_object_id: str | None = Field(default=None, max_length=120)
    label: str = Field(min_length=1, max_length=500)
    state: CheckboxState
    source: ControlSource
    candidate_fingerprint: str | None = Field(default=None, max_length=128)
    candidate_method: str | None = Field(default=None, max_length=100)
    marker_text: str | None = Field(default=None, max_length=100)
    evidence_note: str | None = None
    lifecycle_status: LifecycleStatus = "active"
    confirmed_by: str = Field(min_length=1, max_length=200)
    confirmed_at: datetime
    updated_by: str = Field(min_length=1, max_length=200)
    updated_at: datetime

    @model_validator(mode="after")
    def require_object_anchor(self) -> "FormControl":
        if self.marker_object_id is None and self.label_object_id is None:
            raise ValueError("El casillero debe vincularse al menos a un objeto editable")
        return self


class FormStructure(ContractModel):
    schema_version: Literal["1.0"] = "1.0"
    groups: list[FormGroup] = Field(default_factory=list)
    controls: list[FormControl] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_references(self) -> "FormStructure":
        group_ids = [item.group_id for item in self.groups]
        if len(group_ids) != len(set(group_ids)):
            raise ValueError("Los group_id no deben repetirse")
        control_ids = [item.control_id for item in self.controls]
        if len(control_ids) != len(set(control_ids)):
            raise ValueError("Los control_id no deben repetirse")
        known_groups = set(group_ids)
        invalid = sorted(
            {
                item.group_id
                for item in self.controls
                if item.group_id is not None and item.group_id not in known_groups
            }
        )
        if invalid:
            raise ValueError(
                "Hay casilleros vinculados a grupos inexistentes: " + ", ".join(invalid)
            )
        return self
