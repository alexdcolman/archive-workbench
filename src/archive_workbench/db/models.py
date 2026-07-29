from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Float,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    decisions_schema_version: Mapped[str] = mapped_column(String(32), nullable=False, default="1.0")
    decisions_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class ArchivalUnit(Base):
    __tablename__ = "archival_units"
    __table_args__ = (
        Index("ix_archival_units_project_parent", "project_id", "parent_id"),
        Index("ix_archival_units_project_level", "project_id", "level_key"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    parent_id: Mapped[str | None] = mapped_column(
        ForeignKey("archival_units.id", ondelete="RESTRICT"), nullable=True
    )
    level_key: Mapped[str] = mapped_column(String(100), nullable=False)
    reference_code: Mapped[str | None] = mapped_column(String(500), nullable=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    registration_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="incomplete"
    )
    completion_confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    completion_confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completion_confirmed_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )
    updated_by: Mapped[str] = mapped_column(String(200), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    parent: Mapped[ArchivalUnit | None] = relationship(
        remote_side="ArchivalUnit.id", back_populates="children"
    )
    children: Mapped[list[ArchivalUnit]] = relationship(back_populates="parent")


class ArchivalFieldValue(Base):
    __tablename__ = "archival_field_values"
    __table_args__ = (
        UniqueConstraint(
            "archival_unit_id", "field_key", "sort_order", name="uq_archival_field_value_position"
        ),
        Index("ix_archival_field_values_unit_field", "archival_unit_id", "field_key"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    archival_unit_id: Mapped[str] = mapped_column(
        ForeignKey("archival_units.id", ondelete="CASCADE"), nullable=False
    )
    field_key: Mapped[str] = mapped_column(String(100), nullable=False)
    value_state: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    value_json: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class ArchivalUnitRevision(Base):
    """Snapshot append-only de una unidad archivística después de cada cambio."""

    __tablename__ = "archival_unit_revisions"
    __table_args__ = (
        UniqueConstraint(
            "archival_unit_id", "revision_number", name="uq_archival_unit_revision_number"
        ),
        Index("ix_archival_unit_revisions_unit", "archival_unit_id", "revision_number"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    archival_unit_id: Mapped[str] = mapped_column(
        ForeignKey("archival_units.id", ondelete="CASCADE"), nullable=False
    )
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    operation: Mapped[str] = mapped_column(String(32), nullable=False)
    snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    changed_by: Mapped[str] = mapped_column(String(200), nullable=False)
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


class DigitalObject(Base):
    __tablename__ = "digital_objects"
    __table_args__ = (
        UniqueConstraint("project_id", "sha256", name="uq_digital_object_project_sha256"),
        Index("ix_digital_objects_project_media", "project_id", "media_type"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    media_type: Mapped[str] = mapped_column(String(32), nullable=False)
    original_filename: Mapped[str] = mapped_column(Text, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class FileInstance(Base):
    __tablename__ = "file_instances"
    __table_args__ = (
        UniqueConstraint("storage_root", "relative_path", name="uq_file_instance_path"),
        Index("ix_file_instances_digital_object", "digital_object_id"),
        Index("ix_file_instances_presence", "presence"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    digital_object_id: Mapped[str] = mapped_column(
        ForeignKey("digital_objects.id", ondelete="CASCADE"), nullable=False
    )
    storage_root: Mapped[str] = mapped_column(String(100), nullable=False, default="project")
    relative_path: Mapped[str] = mapped_column(Text, nullable=False)
    presence: Mapped[str] = mapped_column(String(32), nullable=False, default="unverified")
    byte_size_seen: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mtime_ns: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    verified_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)


class DigitalObjectUnitLink(Base):
    __tablename__ = "digital_object_unit_links"
    __table_args__ = (
        UniqueConstraint(
            "digital_object_id",
            "archival_unit_id",
            "relation_type",
            "page_start",
            "page_end",
            name="uq_digital_object_unit_link",
        ),
        Index("ix_digital_object_unit_links_unit", "archival_unit_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    digital_object_id: Mapped[str] = mapped_column(
        ForeignKey("digital_objects.id", ondelete="CASCADE"), nullable=False
    )
    archival_unit_id: Mapped[str] = mapped_column(
        ForeignKey("archival_units.id", ondelete="CASCADE"), nullable=False
    )
    relation_type: Mapped[str] = mapped_column(String(64), nullable=False, default="represents")
    page_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_end: Mapped[int | None] = mapped_column(Integer, nullable=True)


class SourceRegistration(Base):
    __tablename__ = "source_registrations"
    __table_args__ = (
        UniqueConstraint("project_id", "source_type", "source_key", name="uq_source_registration"),
        Index("ix_source_registrations_digital_object", "digital_object_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    source_type: Mapped[str] = mapped_column(String(64), nullable=False)
    source_key: Mapped[str] = mapped_column(String(500), nullable=False)
    digital_object_id: Mapped[str | None] = mapped_column(
        ForeignKey("digital_objects.id", ondelete="SET NULL"), nullable=True
    )
    archival_unit_id: Mapped[str | None] = mapped_column(
        ForeignKey("archival_units.id", ondelete="SET NULL"), nullable=True
    )
    source_payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    registered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    registered_by: Mapped[str] = mapped_column(String(200), nullable=False)


class ExtractionRun(Base):
    __tablename__ = "extraction_runs"
    __table_args__ = (
        Index("ix_extraction_runs_digital_object", "digital_object_id"),
        Index("ix_extraction_runs_current", "digital_object_id", "is_current"),
        Index(
            "ix_extraction_runs_options",
            "digital_object_id",
            "source_sha256",
            "options_hash",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    digital_object_id: Mapped[str] = mapped_column(
        ForeignKey("digital_objects.id", ondelete="CASCADE"), nullable=False
    )
    preprocessing_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("preprocessing_runs.id", ondelete="SET NULL"), nullable=True
    )
    profile_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    engine: Mapped[str] = mapped_column(String(100), nullable=False)
    engine_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    options_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    options_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False, default="registered")
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    output_root: Mapped[str | None] = mapped_column(Text, nullable=True)
    manifest_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_pages_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    objects_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    paragraphs_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    images_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    regions_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    total_pages: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_objects: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_paragraphs: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_characters: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    warnings_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    error_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    quality_status: Mapped[str] = mapped_column(String(32), nullable=False, default="unreviewed")
    quality_score: Mapped[float | None] = mapped_column(nullable=True)
    quality_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ExtractionPage(Base):
    __tablename__ = "extraction_pages"
    __table_args__ = (
        UniqueConstraint("extraction_run_id", "page_number", name="uq_extraction_page"),
        Index("ix_extraction_pages_run", "extraction_run_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    extraction_run_id: Mapped[str] = mapped_column(
        ForeignKey("extraction_runs.id", ondelete="CASCADE"), nullable=False
    )
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    source_asset_id: Mapped[str | None] = mapped_column(
        ForeignKey("derivative_assets.id", ondelete="SET NULL"), nullable=True
    )
    raw_json_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    object_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    character_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(64), nullable=False, default="completed")
    warning_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class ExtractedObject(Base):
    __tablename__ = "extracted_objects"
    __table_args__ = (
        UniqueConstraint(
            "extraction_run_id", "origin_id", name="uq_extracted_object_run_origin"
        ),
        Index("ix_extracted_objects_run_order", "extraction_run_id", "order_index"),
        Index("ix_extracted_objects_page", "extraction_run_id", "page_number"),
        Index("ix_extracted_objects_type", "object_type"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    origin_id: Mapped[str] = mapped_column(String(36), nullable=False)
    extraction_run_id: Mapped[str] = mapped_column(
        ForeignKey("extraction_runs.id", ondelete="CASCADE"), nullable=False
    )
    digital_object_id: Mapped[str] = mapped_column(
        ForeignKey("digital_objects.id", ondelete="CASCADE"), nullable=False
    )
    parent_origin_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False)
    object_type: Mapped[str] = mapped_column(String(100), nullable=False)
    original_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    geometry_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    source_label: Mapped[str | None] = mapped_column(String(100), nullable=True)
    confidence: Mapped[float | None] = mapped_column(nullable=True)
    language: Mapped[str | None] = mapped_column(String(32), nullable=True)
    hidden_by_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    attributes_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class ExtractionRegion(Base):
    """Región declarada y procesada dentro de una corrida compuesta."""

    __tablename__ = "extraction_regions"
    __table_args__ = (
        UniqueConstraint(
            "extraction_run_id", "region_key", name="uq_extraction_region_run_key"
        ),
        Index("ix_extraction_regions_run", "extraction_run_id"),
        Index("ix_extraction_regions_page", "extraction_run_id", "page_number"),
        Index("ix_extraction_regions_type", "object_type"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    extraction_run_id: Mapped[str] = mapped_column(
        ForeignKey("extraction_runs.id", ondelete="CASCADE"), nullable=False
    )
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    region_key: Mapped[str] = mapped_column(String(120), nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    mode: Mapped[str] = mapped_column(String(32), nullable=False)
    object_type: Mapped[str] = mapped_column(String(100), nullable=False)
    reading_order: Mapped[int] = mapped_column(Integer, nullable=False)
    bbox_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    profile_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    crop_path: Mapped[str] = mapped_column(Text, nullable=False)
    raw_json_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_tsv_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_text_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    object_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    character_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(64), nullable=False, default="completed")
    warning_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


class PreprocessingRun(Base):
    __tablename__ = "preprocessing_runs"
    __table_args__ = (
        Index("ix_preprocessing_runs_digital_object", "digital_object_id"),
        Index("ix_preprocessing_runs_current", "digital_object_id", "is_current"),
        Index("ix_preprocessing_runs_options", "digital_object_id", "source_sha256", "options_hash"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    digital_object_id: Mapped[str] = mapped_column(
        ForeignKey("digital_objects.id", ondelete="CASCADE"), nullable=False
    )
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    profile_key: Mapped[str] = mapped_column(String(100), nullable=False, default="default")
    options_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    options_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    backend: Mapped[str] = mapped_column(String(100), nullable=False)
    backend_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(String(64), nullable=False, default="registered")
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    output_root: Mapped[str] = mapped_column(Text, nullable=False)
    manifest_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    warnings_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DerivativeAsset(Base):
    __tablename__ = "derivative_assets"
    __table_args__ = (
        UniqueConstraint(
            "preprocessing_run_id", "page_number", "kind", name="uq_derivative_asset_page_kind"
        ),
        UniqueConstraint("relative_path", name="uq_derivative_asset_relative_path"),
        Index("ix_derivative_assets_digital_object", "digital_object_id"),
        Index("ix_derivative_assets_run", "preprocessing_run_id"),
        Index("ix_derivative_assets_kind", "kind"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    preprocessing_run_id: Mapped[str] = mapped_column(
        ForeignKey("preprocessing_runs.id", ondelete="CASCADE"), nullable=False
    )
    digital_object_id: Mapped[str] = mapped_column(
        ForeignKey("digital_objects.id", ondelete="CASCADE"), nullable=False
    )
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    relative_path: Mapped[str] = mapped_column(Text, nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    dpi: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_width: Mapped[float | None] = mapped_column(nullable=True)
    source_height: Mapped[float | None] = mapped_column(nullable=True)
    source_dpi: Mapped[float | None] = mapped_column(nullable=True)
    rotation_applied: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    backend: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class ExtractionPageSelection(Base):
    """Selección canónica de una extracción concreta para una página."""

    __tablename__ = "extraction_page_selections"
    __table_args__ = (
        UniqueConstraint(
            "digital_object_id", "page_number", name="uq_extraction_page_selection_page"
        ),
        Index("ix_extraction_page_selections_object", "digital_object_id"),
        Index("ix_extraction_page_selections_run", "extraction_run_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    digital_object_id: Mapped[str] = mapped_column(
        ForeignKey("digital_objects.id", ondelete="CASCADE"), nullable=False
    )
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    extraction_run_id: Mapped[str] = mapped_column(
        ForeignKey("extraction_runs.id", ondelete="CASCADE"), nullable=False
    )
    extraction_page_id: Mapped[str] = mapped_column(
        ForeignKey("extraction_pages.id", ondelete="CASCADE"), nullable=False
    )
    selected_by: Mapped[str] = mapped_column(String(200), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    selected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


class DocumentPart(Base):
    """Documento o sección interna provisional dentro de un objeto multipágina."""

    __tablename__ = "document_parts"
    __table_args__ = (
        UniqueConstraint("digital_object_id", "part_key", name="uq_document_part_key"),
        Index("ix_document_parts_object_pages", "digital_object_id", "page_start", "page_end"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    digital_object_id: Mapped[str] = mapped_column(
        ForeignKey("digital_objects.id", ondelete="CASCADE"), nullable=False
    )
    part_key: Mapped[str] = mapped_column(String(120), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    part_type: Mapped[str] = mapped_column(String(100), nullable=False, default="document")
    page_start: Mapped[int] = mapped_column(Integer, nullable=False)
    page_end: Mapped[int] = mapped_column(Integer, nullable=False)
    page_sequence_json: Mapped[list[int]] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="provisional")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class DocumentProcessingPlanRecord(Base):
    """Versión importada de un plan reproducible de procesamiento por página."""

    __tablename__ = "document_processing_plans"
    __table_args__ = (
        UniqueConstraint(
            "digital_object_id", "plan_key", "plan_hash", name="uq_document_processing_plan"
        ),
        Index("ix_document_processing_plans_object", "digital_object_id"),
        Index("ix_document_processing_plans_current", "digital_object_id", "is_current"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    digital_object_id: Mapped[str] = mapped_column(
        ForeignKey("digital_objects.id", ondelete="CASCADE"), nullable=False
    )
    plan_key: Mapped[str] = mapped_column(String(120), nullable=False)
    plan_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(32), nullable=False, default="1.0")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    source_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    plan_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PageProcessingAssignmentRecord(Base):
    __tablename__ = "page_processing_assignments"
    __table_args__ = (
        UniqueConstraint("processing_plan_id", "page_number", name="uq_page_processing_assignment"),
        Index("ix_page_processing_assignments_plan", "processing_plan_id"),
        Index("ix_page_processing_assignments_mode", "mode"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    processing_plan_id: Mapped[str] = mapped_column(
        ForeignKey("document_processing_plans.id", ondelete="CASCADE"), nullable=False
    )
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    assignment_key: Mapped[str] = mapped_column(String(120), nullable=False)
    mode: Mapped[str] = mapped_column(String(32), nullable=False)
    profile_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    region_template_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    part_key: Mapped[str | None] = mapped_column(String(120), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class EditablePage(Base):
    """Página abierta para edición, anclada a una selección OCR concreta."""

    __tablename__ = "editable_pages"
    __table_args__ = (
        UniqueConstraint("digital_object_id", "page_number", name="uq_editable_page_object_page"),
        Index("ix_editable_pages_object", "digital_object_id"),
        Index("ix_editable_pages_source_run", "source_extraction_run_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    digital_object_id: Mapped[str] = mapped_column(
        ForeignKey("digital_objects.id", ondelete="CASCADE"), nullable=False
    )
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    source_extraction_run_id: Mapped[str] = mapped_column(
        ForeignKey("extraction_runs.id", ondelete="RESTRICT"), nullable=False
    )
    source_extraction_page_id: Mapped[str] = mapped_column(
        ForeignKey("extraction_pages.id", ondelete="RESTRICT"), nullable=False
    )
    source_selection_id: Mapped[str | None] = mapped_column(
        ForeignKey("extraction_page_selections.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    review_status: Mapped[str] = mapped_column(String(32), nullable=False, default="unreviewed")
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    bootstrapped_by: Mapped[str] = mapped_column(String(200), nullable=False)
    bootstrapped_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class EditableObject(Base):
    """Estado editable actual. El OCR de origen permanece inmutable en extracted_objects."""

    __tablename__ = "editable_objects"
    __table_args__ = (
        UniqueConstraint(
            "editable_page_id", "source_extracted_object_id", name="uq_editable_object_source"
        ),
        Index("ix_editable_objects_page_order", "editable_page_id", "current_order_index"),
        Index("ix_editable_objects_digital_page", "digital_object_id", "page_number"),
        Index("ix_editable_objects_status", "lifecycle_status"),
        Index("ix_editable_objects_document_part", "document_part_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    editable_page_id: Mapped[str] = mapped_column(
        ForeignKey("editable_pages.id", ondelete="CASCADE"), nullable=False
    )
    digital_object_id: Mapped[str] = mapped_column(
        ForeignKey("digital_objects.id", ondelete="CASCADE"), nullable=False
    )
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    document_part_id: Mapped[str | None] = mapped_column(
        ForeignKey("document_parts.id", ondelete="SET NULL"), nullable=True
    )
    source_extracted_object_id: Mapped[str | None] = mapped_column(
        ForeignKey("extracted_objects.id", ondelete="SET NULL"), nullable=True
    )
    source_origin_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    current_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    current_object_type: Mapped[str] = mapped_column(String(100), nullable=False)
    current_order_index: Mapped[int] = mapped_column(Integer, nullable=False)
    current_geometry_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    current_attributes_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    lifecycle_status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    review_status: Mapped[str] = mapped_column(String(32), nullable=False, default="unreviewed")
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_by: Mapped[str] = mapped_column(String(200), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class EditableObjectRevision(Base):
    """Historial append-only de cada objeto editable."""

    __tablename__ = "editable_object_revisions"
    __table_args__ = (
        UniqueConstraint(
            "editable_object_id", "revision_number", name="uq_editable_object_revision_number"
        ),
        Index("ix_editable_object_revisions_object", "editable_object_id"),
        Index("ix_editable_object_revisions_created", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    editable_object_id: Mapped[str] = mapped_column(
        ForeignKey("editable_objects.id", ondelete="CASCADE"), nullable=False
    )
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    base_revision_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    operation: Mapped[str] = mapped_column(String(32), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    object_type: Mapped[str] = mapped_column(String(100), nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False)
    geometry_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    attributes_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    lifecycle_status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    document_part_id: Mapped[str | None] = mapped_column(
        ForeignKey("document_parts.id", ondelete="SET NULL"), nullable=True
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


class EditablePageAction(Base):
    """Acción versionada sobre una página; permite deshacer y rehacer de forma segura."""

    __tablename__ = "editable_page_actions"
    __table_args__ = (
        UniqueConstraint("editable_page_id", "sequence_number", name="uq_editable_page_action_sequence"),
        Index("ix_editable_page_actions_page_status", "editable_page_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    editable_page_id: Mapped[str] = mapped_column(
        ForeignKey("editable_pages.id", ondelete="CASCADE"), nullable=False
    )
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    action_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    before_snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    after_snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    selected_object_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    undone_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    undone_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    redone_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    redone_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class EditableObjectComment(Base):
    __tablename__ = "editable_object_comments"
    __table_args__ = (Index("ix_editable_object_comments_object", "editable_object_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    editable_object_id: Mapped[str] = mapped_column(
        ForeignKey("editable_objects.id", ondelete="CASCADE"), nullable=False
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


class EditableObjectTag(Base):
    __tablename__ = "editable_object_tags"
    __table_args__ = (
        UniqueConstraint(
            "editable_object_id",
            "tag_kind",
            "normalized_tag",
            name="uq_editable_object_tag_kind",
        ),
        Index("ix_editable_object_tags_object", "editable_object_id"),
        Index("ix_editable_object_tags_normalized", "normalized_tag"),
        Index("ix_editable_object_tags_kind", "tag_kind"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    editable_object_id: Mapped[str] = mapped_column(
        ForeignKey("editable_objects.id", ondelete="CASCADE"), nullable=False
    )
    tag: Mapped[str] = mapped_column(String(200), nullable=False)
    normalized_tag: Mapped[str] = mapped_column(String(200), nullable=False)
    tag_kind: Mapped[str] = mapped_column(String(32), nullable=False, default="unclassified")
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


class AuthorityRecord(Base):
    """Registro canónico de una persona, organismo, lugar u otra entidad."""

    __tablename__ = "authority_records"
    __table_args__ = (
        Index("ix_authority_records_project_type", "project_id", "entity_type"),
        Index("ix_authority_records_project_name", "project_id", "normalized_name"),
        Index("ix_authority_records_review", "review_status"),
        Index("ix_authority_records_temporal", "project_id", "temporal_start", "temporal_end"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    preferred_name: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    temporal_expression: Mapped[str | None] = mapped_column(Text, nullable=True)
    temporal_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    temporal_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    temporal_precision: Mapped[str | None] = mapped_column(String(32), nullable=True)
    temporal_approximate: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    temporal_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    lifecycle_status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    review_status: Mapped[str] = mapped_column(String(32), nullable=False, default="unreviewed")
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_by: Mapped[str] = mapped_column(String(200), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class AuthorityAlias(Base):
    __tablename__ = "authority_aliases"
    __table_args__ = (
        UniqueConstraint(
            "authority_id", "normalized_alias", name="uq_authority_alias_normalized"
        ),
        Index("ix_authority_aliases_authority", "authority_id"),
        Index("ix_authority_aliases_normalized", "normalized_alias"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    authority_id: Mapped[str] = mapped_column(
        ForeignKey("authority_records.id", ondelete="CASCADE"), nullable=False
    )
    alias: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_alias: Mapped[str] = mapped_column(Text, nullable=False)
    alias_type: Mapped[str] = mapped_column(String(32), nullable=False, default="variant")
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


class AuthorityRevision(Base):
    __tablename__ = "authority_revisions"
    __table_args__ = (
        UniqueConstraint(
            "authority_id", "revision_number", name="uq_authority_revision_number"
        ),
        Index("ix_authority_revisions_authority", "authority_id", "revision_number"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    authority_id: Mapped[str] = mapped_column(
        ForeignKey("authority_records.id", ondelete="CASCADE"), nullable=False
    )
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    operation: Mapped[str] = mapped_column(String(32), nullable=False)
    snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    changed_by: Mapped[str] = mapped_column(String(200), nullable=False)
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


class EntityMention(Base):
    """Aparición textual vinculada —o todavía no vinculada— a una autoridad."""

    __tablename__ = "entity_mentions"
    __table_args__ = (
        Index("ix_entity_mentions_object", "editable_object_id", "start_offset"),
        Index("ix_entity_mentions_authority", "authority_id"),
        Index("ix_entity_mentions_status", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    editable_object_id: Mapped[str] = mapped_column(
        ForeignKey("editable_objects.id", ondelete="CASCADE"), nullable=False
    )
    authority_id: Mapped[str | None] = mapped_column(
        ForeignKey("authority_records.id", ondelete="SET NULL"), nullable=True
    )
    mention_text: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_text: Mapped[str] = mapped_column(Text, nullable=False)
    start_offset: Mapped[int | None] = mapped_column(Integer, nullable=True)
    end_offset: Mapped[int | None] = mapped_column(Integer, nullable=True)
    object_revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="manual")
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_by: Mapped[str] = mapped_column(String(200), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class EntityMentionRevision(Base):
    __tablename__ = "entity_mention_revisions"
    __table_args__ = (
        UniqueConstraint(
            "mention_id", "revision_number", name="uq_entity_mention_revision_number"
        ),
        Index("ix_entity_mention_revisions_mention", "mention_id", "revision_number"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    mention_id: Mapped[str] = mapped_column(
        ForeignKey("entity_mentions.id", ondelete="CASCADE"), nullable=False
    )
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    operation: Mapped[str] = mapped_column(String(32), nullable=False)
    snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    changed_by: Mapped[str] = mapped_column(String(200), nullable=False)
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


class EntityRelation(Base):
    """Relación analítica explícita creada por el equipo de investigación."""

    __tablename__ = "entity_relations"
    __table_args__ = (
        CheckConstraint(
            "((target_authority_id IS NOT NULL) + "
            "(target_archival_unit_id IS NOT NULL) + "
            "(target_document_part_id IS NOT NULL)) = 1",
            name="ck_entity_relation_one_target",
        ),
        Index("ix_entity_relations_project", "project_id"),
        Index("ix_entity_relations_source", "source_authority_id"),
        Index("ix_entity_relations_target_authority", "target_authority_id"),
        Index("ix_entity_relations_target_unit", "target_archival_unit_id"),
        Index("ix_entity_relations_target_part", "target_document_part_id"),
        Index("ix_entity_relations_temporal", "project_id", "temporal_start", "temporal_end"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    source_authority_id: Mapped[str] = mapped_column(
        ForeignKey("authority_records.id", ondelete="CASCADE"), nullable=False
    )
    relation_label: Mapped[str] = mapped_column(Text, nullable=False)
    target_authority_id: Mapped[str | None] = mapped_column(
        ForeignKey("authority_records.id", ondelete="CASCADE"), nullable=True
    )
    target_archival_unit_id: Mapped[str | None] = mapped_column(
        ForeignKey("archival_units.id", ondelete="CASCADE"), nullable=True
    )
    target_document_part_id: Mapped[str | None] = mapped_column(
        ForeignKey("document_parts.id", ondelete="CASCADE"), nullable=True
    )
    evidence_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    temporal_expression: Mapped[str | None] = mapped_column(Text, nullable=True)
    temporal_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    temporal_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    temporal_precision: Mapped[str | None] = mapped_column(String(32), nullable=True)
    temporal_approximate: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    temporal_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    lifecycle_status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    review_status: Mapped[str] = mapped_column(String(32), nullable=False, default="unreviewed")
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_by: Mapped[str] = mapped_column(String(200), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class EntityRelationRevision(Base):
    __tablename__ = "entity_relation_revisions"
    __table_args__ = (
        UniqueConstraint(
            "relation_id", "revision_number", name="uq_entity_relation_revision_number"
        ),
        Index("ix_entity_relation_revisions_relation", "relation_id", "revision_number"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    relation_id: Mapped[str] = mapped_column(
        ForeignKey("entity_relations.id", ondelete="CASCADE"), nullable=False
    )
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    operation: Mapped[str] = mapped_column(String(32), nullable=False)
    snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    changed_by: Mapped[str] = mapped_column(String(200), nullable=False)
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


class ExchangeWorkspace(Base):
    """Identidad estable de una copia local que intercambia bundles."""

    __tablename__ = "exchange_workspaces"
    __table_args__ = (UniqueConstraint("project_id", name="uq_exchange_workspace_project"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    workspace_name: Mapped[str] = mapped_column(String(200), nullable=False)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)


class ExchangeChangeEvent(Base):
    """Evento append-only producido por las mutaciones revisables."""

    __tablename__ = "exchange_change_events"
    __table_args__ = (
        UniqueConstraint("workspace_id", "sequence_number", name="uq_exchange_event_sequence"),
        Index("ix_exchange_events_workspace_sequence", "workspace_id", "sequence_number"),
        Index("ix_exchange_events_entity", "entity_type", "entity_id"),
        Index("ix_exchange_events_transaction", "transaction_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("exchange_workspaces.id", ondelete="CASCADE"), nullable=False)
    project_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    transaction_id: Mapped[str] = mapped_column(String(36), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(36), nullable=False)
    operation: Mapped[str] = mapped_column(String(32), nullable=False)
    base_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    new_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    changed_fields_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    actor: Mapped[str] = mapped_column(String(200), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class ExchangeCheckpoint(Base):
    __tablename__ = "exchange_checkpoints"
    __table_args__ = (
        UniqueConstraint("workspace_id", "label", name="uq_exchange_checkpoint_label"),
        Index("ix_exchange_checkpoints_sequence", "workspace_id", "sequence_number"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("exchange_workspaces.id", ondelete="CASCADE"), nullable=False)
    project_id: Mapped[str] = mapped_column(String(128), nullable=False)
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    state_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class ExchangeBundleRecord(Base):
    __tablename__ = "exchange_bundle_records"
    __table_args__ = (
        UniqueConstraint("bundle_id", name="uq_exchange_bundle_id"),
        Index("ix_exchange_bundles_workspace_created", "workspace_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("exchange_workspaces.id", ondelete="CASCADE"), nullable=False)
    bundle_id: Mapped[str] = mapped_column(String(36), nullable=False)
    direction: Mapped[str] = mapped_column(String(16), nullable=False)
    bundle_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    relative_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    base_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    last_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_count: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    counterpart_workspace_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class ExchangeDryRun(Base):
    """Evaluación persistida de un bundle recibido, sin aplicar cambios canónicos."""

    __tablename__ = "exchange_dry_runs"
    __table_args__ = (
        UniqueConstraint("bundle_id", name="uq_exchange_dry_run_bundle"),
        Index("ix_exchange_dry_runs_workspace_assessed", "workspace_id", "assessed_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("exchange_workspaces.id", ondelete="CASCADE"), nullable=False
    )
    bundle_record_id: Mapped[str] = mapped_column(
        ForeignKey("exchange_bundle_records.id", ondelete="CASCADE"), nullable=False
    )
    bundle_id: Mapped[str] = mapped_column(String(36), nullable=False)
    source_workspace_id: Mapped[str] = mapped_column(String(36), nullable=False)
    source_workspace_name: Mapped[str] = mapped_column(String(200), nullable=False)
    common_checkpoint_id: Mapped[str | None] = mapped_column(
        ForeignKey("exchange_checkpoints.id", ondelete="SET NULL"), nullable=True
    )
    common_checkpoint_label: Mapped[str | None] = mapped_column(String(200), nullable=True)
    common_checkpoint_sequence: Mapped[int | None] = mapped_column(Integer, nullable=True)
    base_match_status: Mapped[str] = mapped_column(String(32), nullable=False)
    overall_status: Mapped[str] = mapped_column(String(32), nullable=False)
    counts_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    warnings_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    report_json_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    report_markdown_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    assessed_state_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    assessed_sequence_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    assessed_by: Mapped[str] = mapped_column(String(200), nullable=False)
    assessed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )




class ExchangeConflictResolution(Base):
    """Decisión humana explícita para un campo conflictivo o revisable."""

    __tablename__ = "exchange_conflict_resolutions"
    __table_args__ = (
        UniqueConstraint(
            "dry_run_id", "incoming_event_id", "field_name",
            name="uq_exchange_resolution_event_field",
        ),
        Index("ix_exchange_resolutions_dry_run", "dry_run_id", "incoming_event_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    dry_run_id: Mapped[str] = mapped_column(
        ForeignKey("exchange_dry_runs.id", ondelete="CASCADE"), nullable=False
    )
    incoming_event_id: Mapped[str] = mapped_column(String(36), nullable=False)
    field_name: Mapped[str] = mapped_column(String(100), nullable=False)
    choice: Mapped[str] = mapped_column(String(32), nullable=False)
    base_value_json: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    local_value_json: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    incoming_value_json: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    resolved_value_json: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_by: Mapped[str] = mapped_column(String(200), nullable=False)
    resolved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


class ExchangeBundleApplication(Base):
    """Aplicación transaccional y auditable de un bundle recibido."""

    __tablename__ = "exchange_bundle_applications"
    __table_args__ = (
        UniqueConstraint("bundle_id", name="uq_exchange_application_bundle"),
        Index("ix_exchange_applications_workspace_applied", "workspace_id", "applied_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("exchange_workspaces.id", ondelete="CASCADE"), nullable=False
    )
    dry_run_id: Mapped[str] = mapped_column(
        ForeignKey("exchange_dry_runs.id", ondelete="RESTRICT"), nullable=False
    )
    bundle_record_id: Mapped[str] = mapped_column(
        ForeignKey("exchange_bundle_records.id", ondelete="RESTRICT"), nullable=False
    )
    bundle_id: Mapped[str] = mapped_column(String(36), nullable=False)
    source_workspace_id: Mapped[str] = mapped_column(String(36), nullable=False)
    backup_relative_path: Mapped[str] = mapped_column(Text, nullable=False)
    backup_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    applied_event_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duplicate_event_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    kept_local_event_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    local_sequence_start: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    local_sequence_end: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    checkpoint_id: Mapped[str | None] = mapped_column(
        ForeignKey("exchange_checkpoints.id", ondelete="SET NULL"), nullable=True
    )
    checkpoint_label: Mapped[str | None] = mapped_column(String(200), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="applied")
    applied_by: Mapped[str] = mapped_column(String(200), nullable=False)
    applied_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


class ExchangeIncomingEventAssessment(Base):
    """Clasificación de un evento recibido durante un dry-run."""

    __tablename__ = "exchange_incoming_event_assessments"
    __table_args__ = (
        UniqueConstraint(
            "dry_run_id", "incoming_event_id", name="uq_exchange_incoming_assessment_event"
        ),
        Index("ix_exchange_incoming_assessment_disposition", "dry_run_id", "disposition"),
        Index("ix_exchange_incoming_assessment_entity", "entity_type", "entity_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    dry_run_id: Mapped[str] = mapped_column(
        ForeignKey("exchange_dry_runs.id", ondelete="CASCADE"), nullable=False
    )
    incoming_event_id: Mapped[str] = mapped_column(String(36), nullable=False)
    source_sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    entity_type: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(36), nullable=False)
    operation: Mapped[str] = mapped_column(String(32), nullable=False)
    disposition: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    local_event_ids_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    overlapping_fields_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    incoming_event_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    application_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="not_applied"
    )
    application_id: Mapped[str | None] = mapped_column(
        ForeignKey("exchange_bundle_applications.id", ondelete="SET NULL"), nullable=True
    )
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    assessed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


class CorpusExportProfile(Base):
    """Perfil reproducible para exportar la capa textual revisada."""

    __tablename__ = "corpus_export_profiles"
    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_corpus_export_profile_name"),
        Index("ix_corpus_export_profiles_project", "project_id", "updated_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    aggregation_level: Mapped[str] = mapped_column(String(32), nullable=False)
    text_policy: Mapped[str] = mapped_column(String(32), nullable=False)
    output_format: Mapped[str] = mapped_column(String(16), nullable=False, default="jsonl")
    include_object_types_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    include_review_statuses_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    include_page_review_statuses_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    temporal_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    temporal_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    temporal_include_undated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    object_separator: Mapped[str] = mapped_column(Text, nullable=False, default="\n\n")
    page_separator: Mapped[str] = mapped_column(Text, nullable=False, default="\n\n")
    include_page_markers: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_by: Mapped[str] = mapped_column(String(200), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class CorpusExportRun(Base):
    """Registro inmutable de una exportación materializada."""

    __tablename__ = "corpus_export_runs"
    __table_args__ = (
        Index("ix_corpus_export_runs_project_created", "project_id", "created_at"),
        Index("ix_corpus_export_runs_profile", "profile_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    profile_id: Mapped[str | None] = mapped_column(
        ForeignKey("corpus_export_profiles.id", ondelete="SET NULL"), nullable=True
    )
    profile_name: Mapped[str] = mapped_column(String(200), nullable=False)
    profile_snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    corpus_state_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    output_format: Mapped[str] = mapped_column(String(16), nullable=False)
    output_relative_path: Mapped[str] = mapped_column(Text, nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    character_count: Mapped[int] = mapped_column(Integer, nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    output_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


class ProcessingJob(Base):
    """Ejecución coordinada desde la vista Procesamiento."""

    __tablename__ = "processing_jobs"
    __table_args__ = (
        Index("ix_processing_jobs_project_created", "project_id", "created_at"),
        Index("ix_processing_jobs_status", "project_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    operation: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    source_keys_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    parameters_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    total_items: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completed_items: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_items: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    warning_items: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ProcessingJobItem(Base):
    """Resultado persistente por documento dentro de un trabajo de procesamiento."""

    __tablename__ = "processing_job_items"
    __table_args__ = (
        UniqueConstraint(
            "processing_job_id", "source_key", name="uq_processing_job_item_source"
        ),
        Index("ix_processing_job_items_job", "processing_job_id", "status"),
        Index("ix_processing_job_items_source", "source_key", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    processing_job_id: Mapped[str] = mapped_column(
        ForeignKey("processing_jobs.id", ondelete="CASCADE"), nullable=False
    )
    digital_object_id: Mapped[str | None] = mapped_column(
        ForeignKey("digital_objects.id", ondelete="SET NULL"), nullable=True
    )
    source_key: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    pages_json: Mapped[list[int]] = mapped_column(JSON, nullable=False, default=list)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    detail_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class WorkAssignment(Base):
    """Asignación de procesamiento o revisión para una persona del equipo."""

    __tablename__ = "work_assignments"
    __table_args__ = (
        Index("ix_work_assignments_project_status", "project_id", "status"),
        Index("ix_work_assignments_assignee", "project_id", "assignee", "status"),
        Index("ix_work_assignments_source", "project_id", "source_type", "source_key"),
        Index("ix_work_assignments_parent", "parent_assignment_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    source_type: Mapped[str] = mapped_column(String(64), nullable=False)
    source_key: Mapped[str] = mapped_column(String(500), nullable=False)
    page_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    assignment_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    assignee: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="planned")
    priority: Mapped[str] = mapped_column(String(16), nullable=False, default="normal")
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    parent_assignment_id: Mapped[str | None] = mapped_column(
        ForeignKey("work_assignments.id", ondelete="SET NULL"), nullable=True
    )
    outcome: Mapped[str | None] = mapped_column(String(32), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_by: Mapped[str] = mapped_column(String(200), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class WorkAssignmentRevision(Base):
    __tablename__ = "work_assignment_revisions"
    __table_args__ = (
        UniqueConstraint(
            "assignment_id", "revision_number", name="uq_work_assignment_revision_number"
        ),
        Index("ix_work_assignment_revisions_assignment", "assignment_id", "revision_number"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    assignment_id: Mapped[str] = mapped_column(
        ForeignKey("work_assignments.id", ondelete="CASCADE"), nullable=False
    )
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    operation: Mapped[str] = mapped_column(String(32), nullable=False)
    snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    changed_by: Mapped[str] = mapped_column(String(200), nullable=False)
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


class SemanticSearchProfile(Base):
    """Perfil reproducible para construir un índice semántico local."""

    __tablename__ = "semantic_search_profiles"
    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_semantic_search_profile_name"),
        Index("ix_semantic_search_profiles_project", "project_id", "updated_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    model_name: Mapped[str] = mapped_column(String(500), nullable=False)
    model_revision: Mapped[str | None] = mapped_column(String(100), nullable=True)
    aggregation_level: Mapped[str] = mapped_column(String(32), nullable=False, default="object")
    include_object_types_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    include_review_statuses_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    include_page_review_statuses_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    chunk_size: Mapped[int] = mapped_column(Integer, nullable=False, default=1800)
    chunk_overlap: Mapped[int] = mapped_column(Integer, nullable=False, default=200)
    query_prefix: Mapped[str] = mapped_column(Text, nullable=False, default="query: ")
    document_prefix: Mapped[str] = mapped_column(Text, nullable=False, default="passage: ")
    normalize_embeddings: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_by: Mapped[str] = mapped_column(String(200), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class SemanticIndexRun(Base):
    """Índice semántico derivado; los vectores viven fuera de SQLite."""

    __tablename__ = "semantic_index_runs"
    __table_args__ = (
        Index("ix_semantic_index_runs_profile_created", "profile_id", "created_at"),
        Index("ix_semantic_index_runs_project_created", "project_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    profile_id: Mapped[str] = mapped_column(
        ForeignKey("semantic_search_profiles.id", ondelete="CASCADE"), nullable=False
    )
    profile_snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    corpus_state_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    model_name: Mapped[str] = mapped_column(String(500), nullable=False)
    model_revision: Mapped[str | None] = mapped_column(String(100), nullable=True)
    vectors_relative_path: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_relative_path: Mapped[str] = mapped_column(Text, nullable=False)
    manifest_relative_path: Mapped[str] = mapped_column(Text, nullable=False)
    vector_count: Mapped[int] = mapped_column(Integer, nullable=False)
    dimensions: Mapped[int] = mapped_column(Integer, nullable=False)
    vectors_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    metadata_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="completed")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


class ProjectRecoveryCheck(Base):
    """Prueba no destructiva de que un backup puede verificarse y migrarse."""

    __tablename__ = "project_recovery_checks"
    __table_args__ = (
        Index("ix_project_recovery_checks_project_tested", "project_id", "tested_at"),
        Index("ix_project_recovery_checks_backup", "project_id", "backup_sha256"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    backup_relative_path: Mapped[str] = mapped_column(Text, nullable=False)
    backup_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_database_revision: Mapped[str | None] = mapped_column(String(128), nullable=True)
    upgraded_database_revision: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    details_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    tested_by: Mapped[str] = mapped_column(String(200), nullable=False)
    tested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
