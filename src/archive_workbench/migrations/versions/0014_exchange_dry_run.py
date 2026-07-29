"""Dry-run persistido para bundles recibidos.

Revision ID: 0014_exchange_dry_run
Revises: 0013_offline_exchange_log
Create Date: 2026-07-23
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0014_exchange_dry_run"
down_revision = "0013_offline_exchange_log"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "exchange_dry_runs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("bundle_record_id", sa.String(length=36), nullable=False),
        sa.Column("bundle_id", sa.String(length=36), nullable=False),
        sa.Column("source_workspace_id", sa.String(length=36), nullable=False),
        sa.Column("source_workspace_name", sa.String(length=200), nullable=False),
        sa.Column("common_checkpoint_id", sa.String(length=36), nullable=True),
        sa.Column("common_checkpoint_label", sa.String(length=200), nullable=True),
        sa.Column("common_checkpoint_sequence", sa.Integer(), nullable=True),
        sa.Column("base_match_status", sa.String(length=32), nullable=False),
        sa.Column("overall_status", sa.String(length=32), nullable=False),
        sa.Column("counts_json", sa.JSON(), nullable=False),
        sa.Column("warnings_json", sa.JSON(), nullable=False),
        sa.Column("report_json_path", sa.Text(), nullable=True),
        sa.Column("report_markdown_path", sa.Text(), nullable=True),
        sa.Column("assessed_by", sa.String(length=200), nullable=False),
        sa.Column("assessed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["exchange_workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["bundle_record_id"], ["exchange_bundle_records.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["common_checkpoint_id"], ["exchange_checkpoints.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("bundle_id", name="uq_exchange_dry_run_bundle"),
    )
    op.create_index(
        "ix_exchange_dry_runs_workspace_assessed",
        "exchange_dry_runs",
        ["workspace_id", "assessed_at"],
    )
    op.create_table(
        "exchange_incoming_event_assessments",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("dry_run_id", sa.String(length=36), nullable=False),
        sa.Column("incoming_event_id", sa.String(length=36), nullable=False),
        sa.Column("source_sequence_number", sa.Integer(), nullable=False),
        sa.Column("entity_type", sa.String(length=100), nullable=False),
        sa.Column("entity_id", sa.String(length=36), nullable=False),
        sa.Column("operation", sa.String(length=32), nullable=False),
        sa.Column("disposition", sa.String(length=32), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("local_event_ids_json", sa.JSON(), nullable=False),
        sa.Column("overlapping_fields_json", sa.JSON(), nullable=False),
        sa.Column("incoming_event_json", sa.JSON(), nullable=False),
        sa.Column("application_status", sa.String(length=32), nullable=False),
        sa.Column("assessed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["dry_run_id"], ["exchange_dry_runs.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "dry_run_id", "incoming_event_id", name="uq_exchange_incoming_assessment_event"
        ),
    )
    op.create_index(
        "ix_exchange_incoming_assessment_disposition",
        "exchange_incoming_event_assessments",
        ["dry_run_id", "disposition"],
    )
    op.create_index(
        "ix_exchange_incoming_assessment_entity",
        "exchange_incoming_event_assessments",
        ["entity_type", "entity_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_exchange_incoming_assessment_entity",
        table_name="exchange_incoming_event_assessments",
    )
    op.drop_index(
        "ix_exchange_incoming_assessment_disposition",
        table_name="exchange_incoming_event_assessments",
    )
    op.drop_table("exchange_incoming_event_assessments")
    op.drop_index("ix_exchange_dry_runs_workspace_assessed", table_name="exchange_dry_runs")
    op.drop_table("exchange_dry_runs")
