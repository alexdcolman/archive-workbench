"""Orden lógico de páginas dentro de documentos internos.

Revision ID: 0008_document_part_logical_order
Revises: 0007_document_processing_plans
Create Date: 2026-07-23
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0008_document_part_logical_order"
down_revision = "0007_document_processing_plans"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("document_parts") as batch:
        batch.add_column(
            sa.Column(
                "page_sequence_json",
                sa.JSON(),
                nullable=False,
                server_default="[]",
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("document_parts") as batch:
        batch.drop_column("page_sequence_json")
