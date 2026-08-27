"""Estado de calidad y revisión manual de las extracciones.

Revision ID: 0004_extraction_quality
Revises: 0003_extraction_objects
Create Date: 2026-07-23
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0004_extraction_quality"
down_revision = "0003_extraction_objects"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("extraction_runs") as batch:
        batch.add_column(
            sa.Column(
                "quality_status",
                sa.String(length=32),
                nullable=False,
                server_default="unreviewed",
            )
        )
        batch.add_column(sa.Column("quality_score", sa.Float(), nullable=True))
        batch.add_column(sa.Column("quality_note", sa.Text(), nullable=True))
        batch.add_column(sa.Column("reviewed_by", sa.String(length=200), nullable=True))
        batch.add_column(sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("extraction_runs") as batch:
        for column in (
            "reviewed_at",
            "reviewed_by",
            "quality_note",
            "quality_score",
            "quality_status",
        ):
            batch.drop_column(column)
