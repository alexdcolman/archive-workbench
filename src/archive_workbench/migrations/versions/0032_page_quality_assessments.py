"""Agrega evaluaciones automáticas y auditables de calidad por página.

Revision ID: 0032_page_quality_assessments
Revises: 0031_page_action_exchange
Create Date: 2026-07-29
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0032_page_quality_assessments"
down_revision = "0031_page_action_exchange"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "extraction_page_quality_assessments",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("extraction_page_id", sa.String(length=36), nullable=False),
        sa.Column("algorithm_version", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("metrics_json", sa.JSON(), nullable=False),
        sa.Column("flags_json", sa.JSON(), nullable=False),
        sa.Column("suggestions_json", sa.JSON(), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("assessed_by", sa.String(length=200), nullable=False),
        sa.Column("assessed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["extraction_page_id"], ["extraction_pages.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_page_quality_extraction_page",
        "extraction_page_quality_assessments",
        ["extraction_page_id", "assessed_at"],
        unique=False,
    )
    op.create_index(
        "ix_page_quality_current",
        "extraction_page_quality_assessments",
        ["extraction_page_id", "is_current"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_page_quality_current", table_name="extraction_page_quality_assessments")
    op.drop_index(
        "ix_page_quality_extraction_page",
        table_name="extraction_page_quality_assessments",
    )
    op.drop_table("extraction_page_quality_assessments")
