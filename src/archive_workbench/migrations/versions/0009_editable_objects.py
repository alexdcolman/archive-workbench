"""Objetos editables e historial append-only.

Revision ID: 0009_editable_objects
Revises: 0008_document_part_logical_order
Create Date: 2026-07-23
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0009_editable_objects"
down_revision = "0008_document_part_logical_order"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "editable_pages",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "digital_object_id",
            sa.String(length=36),
            sa.ForeignKey("digital_objects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column(
            "source_extraction_run_id",
            sa.String(length=36),
            sa.ForeignKey("extraction_runs.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "source_extraction_page_id",
            sa.String(length=36),
            sa.ForeignKey("extraction_pages.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "source_selection_id",
            sa.String(length=36),
            sa.ForeignKey("extraction_page_selections.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("bootstrapped_by", sa.String(length=200), nullable=False),
        sa.Column("bootstrapped_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "digital_object_id", "page_number", name="uq_editable_page_object_page"
        ),
    )
    op.create_index("ix_editable_pages_object", "editable_pages", ["digital_object_id"])
    op.create_index(
        "ix_editable_pages_source_run", "editable_pages", ["source_extraction_run_id"]
    )

    op.create_table(
        "editable_objects",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "editable_page_id",
            sa.String(length=36),
            sa.ForeignKey("editable_pages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "digital_object_id",
            sa.String(length=36),
            sa.ForeignKey("digital_objects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column(
            "source_extracted_object_id",
            sa.String(length=36),
            sa.ForeignKey("extracted_objects.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("source_origin_id", sa.String(length=36), nullable=True),
        sa.Column("current_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("current_object_type", sa.String(length=100), nullable=False),
        sa.Column("current_order_index", sa.Integer(), nullable=False),
        sa.Column("current_geometry_json", sa.JSON(), nullable=False),
        sa.Column("current_attributes_json", sa.JSON(), nullable=False),
        sa.Column(
            "lifecycle_status", sa.String(length=32), nullable=False, server_default="active"
        ),
        sa.Column("revision_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_by", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by", sa.String(length=200), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "editable_page_id", "source_extracted_object_id", name="uq_editable_object_source"
        ),
    )
    op.create_index(
        "ix_editable_objects_page_order",
        "editable_objects",
        ["editable_page_id", "current_order_index"],
    )
    op.create_index(
        "ix_editable_objects_digital_page",
        "editable_objects",
        ["digital_object_id", "page_number"],
    )
    op.create_index(
        "ix_editable_objects_status", "editable_objects", ["lifecycle_status"]
    )

    op.create_table(
        "editable_object_revisions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "editable_object_id",
            sa.String(length=36),
            sa.ForeignKey("editable_objects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("base_revision_number", sa.Integer(), nullable=True),
        sa.Column("operation", sa.String(length=32), nullable=False),
        sa.Column("text", sa.Text(), nullable=False, server_default=""),
        sa.Column("object_type", sa.String(length=100), nullable=False),
        sa.Column("order_index", sa.Integer(), nullable=False),
        sa.Column("geometry_json", sa.JSON(), nullable=False),
        sa.Column("attributes_json", sa.JSON(), nullable=False),
        sa.Column(
            "lifecycle_status", sa.String(length=32), nullable=False, server_default="active"
        ),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "editable_object_id",
            "revision_number",
            name="uq_editable_object_revision_number",
        ),
    )
    op.create_index(
        "ix_editable_object_revisions_object",
        "editable_object_revisions",
        ["editable_object_id"],
    )
    op.create_index(
        "ix_editable_object_revisions_created",
        "editable_object_revisions",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_editable_object_revisions_created", table_name="editable_object_revisions"
    )
    op.drop_index(
        "ix_editable_object_revisions_object", table_name="editable_object_revisions"
    )
    op.drop_table("editable_object_revisions")
    op.drop_index("ix_editable_objects_status", table_name="editable_objects")
    op.drop_index("ix_editable_objects_digital_page", table_name="editable_objects")
    op.drop_index("ix_editable_objects_page_order", table_name="editable_objects")
    op.drop_table("editable_objects")
    op.drop_index("ix_editable_pages_source_run", table_name="editable_pages")
    op.drop_index("ix_editable_pages_object", table_name="editable_pages")
    op.drop_table("editable_pages")
