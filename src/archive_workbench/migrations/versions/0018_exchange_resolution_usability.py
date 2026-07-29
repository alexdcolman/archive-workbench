"""Usabilidad de resoluciones y contabilidad de decisiones locales.

Revision ID: 0018_exchange_resolution_usability
Revises: 0017_exchange_conflict_resolutions
Create Date: 2026-07-24
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0018_exchange_resolution_usability"
down_revision = "0017_exchange_conflict_resolutions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("exchange_bundle_applications") as batch:
        batch.add_column(
            sa.Column(
                "kept_local_event_count",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("exchange_bundle_applications") as batch:
        batch.drop_column("kept_local_event_count")
