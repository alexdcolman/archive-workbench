"""Planes multipágina y partes documentales.

Revision ID: 0007_document_processing_plans
Revises: 0006_region_extraction
Create Date: 2026-07-23
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0007_document_processing_plans"
down_revision = "0006_region_extraction"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "document_parts",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "digital_object_id",
            sa.String(length=36),
            sa.ForeignKey("digital_objects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("part_key", sa.String(length=120), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("part_type", sa.String(length=100), nullable=False),
        sa.Column("page_start", sa.Integer(), nullable=False),
        sa.Column("page_end", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("digital_object_id", "part_key", name="uq_document_part_key"),
    )
    op.create_index(
        "ix_document_parts_object_pages",
        "document_parts",
        ["digital_object_id", "page_start", "page_end"],
    )

    op.create_table(
        "document_processing_plans",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "digital_object_id",
            sa.String(length=36),
            sa.ForeignKey("digital_objects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("plan_key", sa.String(length=120), nullable=False),
        sa.Column("plan_hash", sa.String(length=64), nullable=False),
        sa.Column("schema_version", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("source_path", sa.Text(), nullable=True),
        sa.Column("plan_json", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "digital_object_id", "plan_key", "plan_hash", name="uq_document_processing_plan"
        ),
    )
    op.create_index(
        "ix_document_processing_plans_object", "document_processing_plans", ["digital_object_id"]
    )
    op.create_index(
        "ix_document_processing_plans_current",
        "document_processing_plans",
        ["digital_object_id", "is_current"],
    )

    op.create_table(
        "page_processing_assignments",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "processing_plan_id",
            sa.String(length=36),
            sa.ForeignKey("document_processing_plans.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("assignment_key", sa.String(length=120), nullable=False),
        sa.Column("mode", sa.String(length=32), nullable=False),
        sa.Column("profile_path", sa.Text(), nullable=True),
        sa.Column("region_template_path", sa.Text(), nullable=True),
        sa.Column("part_key", sa.String(length=120), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.UniqueConstraint(
            "processing_plan_id", "page_number", name="uq_page_processing_assignment"
        ),
    )
    op.create_index(
        "ix_page_processing_assignments_plan",
        "page_processing_assignments",
        ["processing_plan_id"],
    )
    op.create_index(
        "ix_page_processing_assignments_mode", "page_processing_assignments", ["mode"]
    )


def downgrade() -> None:
    op.drop_index("ix_page_processing_assignments_mode", table_name="page_processing_assignments")
    op.drop_index("ix_page_processing_assignments_plan", table_name="page_processing_assignments")
    op.drop_table("page_processing_assignments")
    op.drop_index("ix_document_processing_plans_current", table_name="document_processing_plans")
    op.drop_index("ix_document_processing_plans_object", table_name="document_processing_plans")
    op.drop_table("document_processing_plans")
    op.drop_index("ix_document_parts_object_pages", table_name="document_parts")
    op.drop_table("document_parts")
