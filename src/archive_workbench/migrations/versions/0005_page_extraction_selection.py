"""Selección canónica de extracción por página.

Revision ID: 0005_page_extraction_selection
Revises: 0004_extraction_quality
Create Date: 2026-07-23
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0005_page_extraction_selection"
down_revision = "0004_extraction_quality"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "extraction_page_selections",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "digital_object_id",
            sa.String(length=36),
            sa.ForeignKey("digital_objects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column(
            "extraction_run_id",
            sa.String(length=36),
            sa.ForeignKey("extraction_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "extraction_page_id",
            sa.String(length=36),
            sa.ForeignKey("extraction_pages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("selected_by", sa.String(length=200), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("selected_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "digital_object_id",
            "page_number",
            name="uq_extraction_page_selection_page",
        ),
    )
    op.create_index(
        "ix_extraction_page_selections_object",
        "extraction_page_selections",
        ["digital_object_id"],
    )
    op.create_index(
        "ix_extraction_page_selections_run",
        "extraction_page_selections",
        ["extraction_run_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_extraction_page_selections_run",
        table_name="extraction_page_selections",
    )
    op.drop_index(
        "ix_extraction_page_selections_object",
        table_name="extraction_page_selections",
    )
    op.drop_table("extraction_page_selections")
