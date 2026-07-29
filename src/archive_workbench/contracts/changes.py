from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field

from archive_workbench.contracts.common import ContractModel, Sha256, utc_now
from archive_workbench.domain.enums import ChangeOperation, MergeDisposition


class ChangeEvent(ContractModel):
    schema_version: str = "1.0"
    event_id: str
    project_id: str
    workspace_id: str
    sequence_number: int = Field(ge=1)
    transaction_id: str
    entity_type: str
    entity_id: str
    operation: ChangeOperation
    base_revision: int | None = Field(default=None, ge=0)
    new_revision: int | None = Field(default=None, ge=1)
    changed_fields: dict[str, Any] = Field(default_factory=dict)
    actor: str
    timestamp: datetime = Field(default_factory=utc_now)


class ChangeBundleManifest(ContractModel):
    schema_version: str = "1.0"
    project_id: str
    bundle_id: str
    source_workspace_id: str
    source_workspace_name: str
    app_version: str
    database_revision: str
    created_by: str
    created_at: datetime = Field(default_factory=utc_now)
    base_checkpoint_id: str
    base_checkpoint_label: str
    base_checkpoint_state_sha256: Sha256
    base_sequence: int = Field(ge=0)
    last_sequence: int = Field(ge=0)
    event_count: int = Field(ge=0)
    changes_sha256: Sha256
    attachment_checksums: dict[str, Sha256] = Field(default_factory=dict)


class BundleInspection(ContractModel):
    manifest: ChangeBundleManifest
    bundle_sha256: Sha256
    event_count: int = Field(ge=0)
    first_sequence: int | None = Field(default=None, ge=1)
    last_sequence: int | None = Field(default=None, ge=1)
    warnings: list[str] = Field(default_factory=list)


class MergeAssessment(ContractModel):
    disposition: MergeDisposition
    reason: str
    local_event_id: str | None = None
    incoming_event_id: str | None = None
    overlapping_fields: list[str] = Field(default_factory=list)


class DryRunEventAssessment(ContractModel):
    schema_version: str = "1.0"
    incoming_event: ChangeEvent
    disposition: MergeDisposition
    reason: str
    local_event_ids: list[str] = Field(default_factory=list)
    overlapping_fields: list[str] = Field(default_factory=list)


class BundleDryRunReport(ContractModel):
    schema_version: str = "1.0"
    project_id: str
    local_workspace_id: str
    local_workspace_name: str
    bundle_id: str
    bundle_sha256: Sha256
    source_workspace_id: str
    source_workspace_name: str
    base_checkpoint_state_sha256: Sha256
    common_checkpoint_id: str | None = None
    common_checkpoint_label: str | None = None
    common_checkpoint_sequence: int | None = Field(default=None, ge=0)
    base_match_status: str
    overall_status: str
    counts: dict[str, int] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    assessments: list[DryRunEventAssessment] = Field(default_factory=list)
    assessed_local_state_sha256: Sha256
    assessed_local_sequence: int = Field(ge=0)
    assessed_by: str
    assessed_at: datetime = Field(default_factory=utc_now)
