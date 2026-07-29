"""Resoluciones humanas campo por campo para bundles conflictivos.

Revision ID: 0017_exchange_conflict_resolutions
Revises: 0016_exchange_delete_preconditions
Create Date: 2026-07-24
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0017_exchange_conflict_resolutions"
down_revision = "0016_exchange_delete_preconditions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "exchange_conflict_resolutions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("dry_run_id", sa.String(length=36), nullable=False),
        sa.Column("incoming_event_id", sa.String(length=36), nullable=False),
        sa.Column("field_name", sa.String(length=100), nullable=False),
        sa.Column("choice", sa.String(length=32), nullable=False),
        sa.Column("base_value_json", sa.JSON(), nullable=True),
        sa.Column("local_value_json", sa.JSON(), nullable=True),
        sa.Column("incoming_value_json", sa.JSON(), nullable=True),
        sa.Column("resolved_value_json", sa.JSON(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("resolved_by", sa.String(length=200), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["dry_run_id"], ["exchange_dry_runs.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "dry_run_id", "incoming_event_id", "field_name",
            name="uq_exchange_resolution_event_field",
        ),
    )
    op.create_index(
        "ix_exchange_resolutions_dry_run",
        "exchange_conflict_resolutions",
        ["dry_run_id", "incoming_event_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_exchange_resolutions_dry_run",
        table_name="exchange_conflict_resolutions",
    )
    op.drop_table("exchange_conflict_resolutions")
