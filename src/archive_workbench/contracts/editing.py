from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


ReviewStatus = Literal["unreviewed", "needs_review", "reviewed", "approved"]


class EditableObjectExport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.2"] = "1.2"
    editable_object_id: str
    source_key: str
    digital_object_id: str
    page: int = Field(ge=1)
    order_index: int = Field(ge=0)
    document_part_id: str | None = None
    document_part_key: str | None = None
    object_type: str
    text: str
    geometry: list[dict[str, Any]] = Field(default_factory=list)
    attributes: dict[str, Any] = Field(default_factory=dict)
    lifecycle_status: Literal["active", "deleted"]
    review_status: ReviewStatus = "unreviewed"
    revision_number: int = Field(ge=1)
    source_extracted_object_id: str | None = None
    source_origin_id: str | None = None
    updated_by: str
    updated_at: datetime


class EditableRevisionExport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.1"] = "1.1"
    revision_id: str
    editable_object_id: str
    revision_number: int = Field(ge=1)
    base_revision_number: int | None = Field(default=None, ge=1)
    operation: Literal[
        "import",
        "edit",
        "add",
        "delete",
        "restore",
        "revert",
        "reorder",
        "split",
        "merge",
        "undo",
        "redo",
        "assign_part",
    ]
    text: str
    object_type: str
    order_index: int = Field(ge=0)
    geometry: list[dict[str, Any]] = Field(default_factory=list)
    attributes: dict[str, Any] = Field(default_factory=dict)
    lifecycle_status: Literal["active", "deleted"]
    document_part_id: str | None = None
    document_part_key: str | None = None
    note: str | None = None
    created_by: str
    created_at: datetime


class EditableCommentExport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    comment_id: str
    editable_object_id: str
    body: str
    created_by: str
    created_at: datetime


class EditableTagExport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.1"] = "1.1"
    tag_id: str
    editable_object_id: str
    tag: str
    tag_kind: Literal["thematic", "conceptual", "workflow", "unclassified"]
    created_by: str
    created_at: datetime


class EditableExportManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.2"] = "1.2"
    source_key: str
    digital_object_id: str
    exported_at: datetime
    object_count: int = Field(ge=0)
    active_count: int = Field(ge=0)
    deleted_count: int = Field(ge=0)
    revision_count: int = Field(ge=0)
    comment_count: int = Field(ge=0)
    tag_count: int = Field(ge=0)
    objects_path: str
    revisions_path: str
    comments_path: str
    tags_path: str
