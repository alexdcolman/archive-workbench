"""Registra recuperación append-only de linaje de intercambio.

Revision ID: 0035_exchange_lineage_recovery
Revises: 0034_automatic_analysis_authorizations
Create Date: 2026-08-03
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0035_exchange_lineage_recovery"
down_revision = "0034_automatic_analysis_authorizations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "exchange_dry_runs",
        sa.Column(
            "base_match_method",
            sa.String(length=64),
            nullable=False,
            server_default="unknown",
        ),
    )

    op.create_table(
        "exchange_lineage_cases",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=128), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("dry_run_id", sa.String(length=36), nullable=False),
        sa.Column("bundle_record_id", sa.String(length=36), nullable=False),
        sa.Column("bundle_id", sa.String(length=36), nullable=False),
        sa.Column("source_workspace_id", sa.String(length=36), nullable=False),
        sa.Column("diagnostic_classification", sa.String(length=32), nullable=False),
        sa.Column("candidate_fingerprint", sa.Text(), nullable=False),
        sa.Column("diagnostic_parameters_sha256", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("opened_by", sa.String(length=200), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_by", sa.String(length=200), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["exchange_workspaces.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["dry_run_id"], ["exchange_dry_runs.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["bundle_record_id"], ["exchange_bundle_records.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("bundle_id", name="uq_exchange_lineage_case_bundle"),
    )
    op.create_index(
        "ix_exchange_lineage_cases_workspace_created",
        "exchange_lineage_cases",
        ["workspace_id", "closed_at"],
        unique=False,
    )

    op.create_table(
        "exchange_lineage_evidence",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("case_id", sa.String(length=36), nullable=False),
        sa.Column("artifact_type", sa.String(length=64), nullable=False),
        sa.Column("artifact_reference", sa.Text(), nullable=False),
        sa.Column("artifact_sha256", sa.String(length=64), nullable=True),
        sa.Column("verification_status", sa.String(length=32), nullable=False),
        sa.Column("strength", sa.String(length=32), nullable=False),
        sa.Column("code", sa.String(length=100), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("observed_project_id", sa.String(length=128), nullable=True),
        sa.Column("observed_workspace_id", sa.String(length=36), nullable=True),
        sa.Column("observed_sequence_number", sa.Integer(), nullable=True),
        sa.Column("observed_checkpoint_id", sa.String(length=36), nullable=True),
        sa.Column("observed_checkpoint_label", sa.String(length=200), nullable=True),
        sa.Column("observed_state_sha256", sa.String(length=64), nullable=True),
        sa.Column(
            "selected_for_decision",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("details_json", sa.JSON(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["case_id"], ["exchange_lineage_cases.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_exchange_lineage_evidence_case",
        "exchange_lineage_evidence",
        ["case_id", "recorded_at"],
        unique=False,
    )
    op.create_index(
        "ix_exchange_lineage_evidence_artifact",
        "exchange_lineage_evidence",
        ["artifact_sha256", "artifact_type"],
        unique=False,
    )

    op.create_table(
        "exchange_lineage_decisions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("case_id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=128), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("operation", sa.String(length=32), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("target_bundle_id", sa.String(length=36), nullable=False),
        sa.Column("target_bundle_sha256", sa.String(length=64), nullable=False),
        sa.Column("source_workspace_id", sa.String(length=36), nullable=False),
        sa.Column("target_base_checkpoint_id", sa.String(length=36), nullable=False),
        sa.Column("target_base_checkpoint_label", sa.String(length=200), nullable=False),
        sa.Column("target_base_state_sha256", sa.String(length=64), nullable=False),
        sa.Column("target_base_sequence", sa.Integer(), nullable=False),
        sa.Column("candidate_fingerprint", sa.Text(), nullable=False),
        sa.Column("recovery_method", sa.String(length=64), nullable=False),
        sa.Column("local_checkpoint_id", sa.String(length=36), nullable=True),
        sa.Column("local_checkpoint_label", sa.String(length=200), nullable=True),
        sa.Column("local_checkpoint_sequence", sa.Integer(), nullable=False),
        sa.Column("local_checkpoint_state_sha256", sa.String(length=64), nullable=True),
        sa.Column("remote_workspace_id", sa.String(length=36), nullable=False),
        sa.Column("remote_sequence", sa.Integer(), nullable=False),
        sa.Column("evidence_ids_json", sa.JSON(), nullable=False),
        sa.Column("chain_bundle_ids_json", sa.JSON(), nullable=False),
        sa.Column(
            "recovery_confirmed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("confirmed_by", sa.String(length=200), nullable=False),
        sa.Column("confirmation_reason", sa.Text(), nullable=False),
        sa.Column("parameters_sha256", sa.String(length=64), nullable=False),
        sa.Column("result", sa.String(length=32), nullable=False),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["case_id"], ["exchange_lineage_cases.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["exchange_workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("case_id", name="uq_exchange_lineage_decision_case"),
        sa.UniqueConstraint(
            "target_bundle_id", name="uq_exchange_lineage_decision_bundle"
        ),
    )
    op.create_index(
        "ix_exchange_lineage_decisions_workspace_created",
        "exchange_lineage_decisions",
        ["workspace_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_exchange_lineage_decisions_match",
        "exchange_lineage_decisions",
        [
            "workspace_id",
            "source_workspace_id",
            "target_bundle_id",
            "target_base_sequence",
            "result",
        ],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_exchange_lineage_decisions_match",
        table_name="exchange_lineage_decisions",
    )
    op.drop_index(
        "ix_exchange_lineage_decisions_workspace_created",
        table_name="exchange_lineage_decisions",
    )
    op.drop_table("exchange_lineage_decisions")
    op.drop_index(
        "ix_exchange_lineage_evidence_artifact",
        table_name="exchange_lineage_evidence",
    )
    op.drop_index(
        "ix_exchange_lineage_evidence_case",
        table_name="exchange_lineage_evidence",
    )
    op.drop_table("exchange_lineage_evidence")
    op.drop_index(
        "ix_exchange_lineage_cases_workspace_created",
        table_name="exchange_lineage_cases",
    )
    op.drop_table("exchange_lineage_cases")
    op.drop_column("exchange_dry_runs", "base_match_method")
