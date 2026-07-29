"""Catálogo, objetos digitales y trazabilidad inicial.

Revision ID: 0001_initial_catalog
Revises: None
Create Date: 2026-07-23
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0001_initial_catalog"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column("id", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=500), nullable=False),
        sa.Column("decisions_schema_version", sa.String(length=32), nullable=False),
        sa.Column("decisions_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "archival_units",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=128), nullable=False),
        sa.Column("parent_id", sa.String(length=36), nullable=True),
        sa.Column("level_key", sa.String(length=100), nullable=False),
        sa.Column("reference_code", sa.String(length=500), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("registration_status", sa.String(length=32), nullable=False),
        sa.Column("completion_confirmed", sa.Boolean(), nullable=False),
        sa.Column("completion_confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completion_confirmed_by", sa.String(length=200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String(length=200), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by", sa.String(length=200), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["parent_id"], ["archival_units.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_archival_units_project_level", "archival_units", ["project_id", "level_key"]
    )
    op.create_index(
        "ix_archival_units_project_parent", "archival_units", ["project_id", "parent_id"]
    )
    op.create_table(
        "archival_field_values",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("archival_unit_id", sa.String(length=36), nullable=False),
        sa.Column("field_key", sa.String(length=100), nullable=False),
        sa.Column("value_state", sa.String(length=32), nullable=False),
        sa.Column("value_json", sa.JSON(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("source_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["archival_unit_id"], ["archival_units.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "archival_unit_id", "field_key", "sort_order", name="uq_archival_field_value_position"
        ),
    )
    op.create_index(
        "ix_archival_field_values_unit_field",
        "archival_field_values",
        ["archival_unit_id", "field_key"],
    )
    op.create_table(
        "digital_objects",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=128), nullable=False),
        sa.Column("media_type", sa.String(length=32), nullable=False),
        sa.Column("original_filename", sa.Text(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "sha256", name="uq_digital_object_project_sha256"),
    )
    op.create_index(
        "ix_digital_objects_project_media", "digital_objects", ["project_id", "media_type"]
    )
    op.create_table(
        "file_instances",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("digital_object_id", sa.String(length=36), nullable=False),
        sa.Column("storage_root", sa.String(length=100), nullable=False),
        sa.Column("relative_path", sa.Text(), nullable=False),
        sa.Column("presence", sa.String(length=32), nullable=False),
        sa.Column("byte_size_seen", sa.Integer(), nullable=True),
        sa.Column("mtime_ns", sa.Integer(), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("verified_sha256", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(["digital_object_id"], ["digital_objects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("storage_root", "relative_path", name="uq_file_instance_path"),
    )
    op.create_index(
        "ix_file_instances_digital_object", "file_instances", ["digital_object_id"]
    )
    op.create_index("ix_file_instances_presence", "file_instances", ["presence"])
    op.create_table(
        "digital_object_unit_links",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("digital_object_id", sa.String(length=36), nullable=False),
        sa.Column("archival_unit_id", sa.String(length=36), nullable=False),
        sa.Column("relation_type", sa.String(length=64), nullable=False),
        sa.Column("page_start", sa.Integer(), nullable=True),
        sa.Column("page_end", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["archival_unit_id"], ["archival_units.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["digital_object_id"], ["digital_objects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "digital_object_id",
            "archival_unit_id",
            "relation_type",
            "page_start",
            "page_end",
            name="uq_digital_object_unit_link",
        ),
    )
    op.create_index(
        "ix_digital_object_unit_links_unit", "digital_object_unit_links", ["archival_unit_id"]
    )
    op.create_table(
        "source_registrations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=128), nullable=False),
        sa.Column("source_type", sa.String(length=64), nullable=False),
        sa.Column("source_key", sa.String(length=500), nullable=False),
        sa.Column("digital_object_id", sa.String(length=36), nullable=True),
        sa.Column("archival_unit_id", sa.String(length=36), nullable=True),
        sa.Column("source_payload_json", sa.JSON(), nullable=False),
        sa.Column("registered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("registered_by", sa.String(length=200), nullable=False),
        sa.ForeignKeyConstraint(["archival_unit_id"], ["archival_units.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["digital_object_id"], ["digital_objects.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "source_type", "source_key", name="uq_source_registration"),
    )
    op.create_index(
        "ix_source_registrations_digital_object", "source_registrations", ["digital_object_id"]
    )
    op.create_table(
        "extraction_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("digital_object_id", sa.String(length=36), nullable=False),
        sa.Column("engine", sa.String(length=100), nullable=False),
        sa.Column("engine_version", sa.String(length=100), nullable=True),
        sa.Column("source_sha256", sa.String(length=64), nullable=False),
        sa.Column("options_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False),
        sa.Column("warnings_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["digital_object_id"], ["digital_objects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_extraction_runs_current", "extraction_runs", ["digital_object_id", "is_current"]
    )
    op.create_index(
        "ix_extraction_runs_digital_object", "extraction_runs", ["digital_object_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_extraction_runs_digital_object", table_name="extraction_runs")
    op.drop_index("ix_extraction_runs_current", table_name="extraction_runs")
    op.drop_table("extraction_runs")
    op.drop_index("ix_source_registrations_digital_object", table_name="source_registrations")
    op.drop_table("source_registrations")
    op.drop_index("ix_digital_object_unit_links_unit", table_name="digital_object_unit_links")
    op.drop_table("digital_object_unit_links")
    op.drop_index("ix_file_instances_presence", table_name="file_instances")
    op.drop_index("ix_file_instances_digital_object", table_name="file_instances")
    op.drop_table("file_instances")
    op.drop_index("ix_digital_objects_project_media", table_name="digital_objects")
    op.drop_table("digital_objects")
    op.drop_index("ix_archival_field_values_unit_field", table_name="archival_field_values")
    op.drop_table("archival_field_values")
    op.drop_index("ix_archival_units_project_parent", table_name="archival_units")
    op.drop_index("ix_archival_units_project_level", table_name="archival_units")
    op.drop_table("archival_units")
    op.drop_table("projects")
