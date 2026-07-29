"""Extracción OCR compuesta por regiones.

Revision ID: 0006_region_extraction
Revises: 0005_page_extraction_selection
Create Date: 2026-07-23
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0006_region_extraction"
down_revision = "0005_page_extraction_selection"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("extraction_runs") as batch:
        batch.add_column(sa.Column("regions_path", sa.Text(), nullable=True))

    op.create_table(
        "extraction_regions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "extraction_run_id",
            sa.String(length=36),
            sa.ForeignKey("extraction_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("region_key", sa.String(length=120), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("mode", sa.String(length=32), nullable=False),
        sa.Column("object_type", sa.String(length=100), nullable=False),
        sa.Column("reading_order", sa.Integer(), nullable=False),
        sa.Column("bbox_json", sa.JSON(), nullable=False),
        sa.Column("profile_json", sa.JSON(), nullable=True),
        sa.Column("crop_path", sa.Text(), nullable=False),
        sa.Column("raw_json_path", sa.Text(), nullable=True),
        sa.Column("raw_tsv_path", sa.Text(), nullable=True),
        sa.Column("raw_text_path", sa.Text(), nullable=True),
        sa.Column("object_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("character_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("warning_text", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "extraction_run_id", "region_key", name="uq_extraction_region_run_key"
        ),
    )
    op.create_index("ix_extraction_regions_run", "extraction_regions", ["extraction_run_id"])
    op.create_index(
        "ix_extraction_regions_page",
        "extraction_regions",
        ["extraction_run_id", "page_number"],
    )
    op.create_index("ix_extraction_regions_type", "extraction_regions", ["object_type"])


def downgrade() -> None:
    op.drop_index("ix_extraction_regions_type", table_name="extraction_regions")
    op.drop_index("ix_extraction_regions_page", table_name="extraction_regions")
    op.drop_index("ix_extraction_regions_run", table_name="extraction_regions")
    op.drop_table("extraction_regions")
    with op.batch_alter_table("extraction_runs") as batch:
        batch.drop_column("regions_path")
