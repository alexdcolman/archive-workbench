"""Panel coordinado de procesamiento y logs persistentes.

Revision ID: 0025_processing_dashboard
Revises: 0024_semantic_search
Create Date: 2026-07-24
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0025_processing_dashboard"
down_revision = "0024_semantic_search"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "processing_jobs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=128), nullable=False),
        sa.Column("operation", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="queued"),
        sa.Column("source_keys_json", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("parameters_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("total_items", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completed_items", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_items", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("warning_items", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_by", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_processing_jobs_project_created",
        "processing_jobs",
        ["project_id", "created_at"],
    )
    op.create_index(
        "ix_processing_jobs_status", "processing_jobs", ["project_id", "status"]
    )
    op.create_table(
        "processing_job_items",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("processing_job_id", sa.String(length=36), nullable=False),
        sa.Column("digital_object_id", sa.String(length=36), nullable=True),
        sa.Column("source_key", sa.String(length=500), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="queued"),
        sa.Column("pages_json", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("detail_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["processing_job_id"], ["processing_jobs.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["digital_object_id"], ["digital_objects.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "processing_job_id", "source_key", name="uq_processing_job_item_source"
        ),
    )
    op.create_index(
        "ix_processing_job_items_job",
        "processing_job_items",
        ["processing_job_id", "status"],
    )
    op.create_index(
        "ix_processing_job_items_source",
        "processing_job_items",
        ["source_key", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_processing_job_items_source", table_name="processing_job_items")
    op.drop_index("ix_processing_job_items_job", table_name="processing_job_items")
    op.drop_table("processing_job_items")
    op.drop_index("ix_processing_jobs_status", table_name="processing_jobs")
    op.drop_index("ix_processing_jobs_project_created", table_name="processing_jobs")
    op.drop_table("processing_jobs")
