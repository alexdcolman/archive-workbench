"""Registra adopciones transaccionales de estado divergente y sus rollbacks.

Revision ID: 0037_exchange_state_adoptions
Revises: 0036_exchange_common_base_agreements
Create Date: 2026-08-03
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0037_exchange_state_adoptions"
down_revision = "0036_exchange_common_base_agreements"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "exchange_state_adoptions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("adoption_id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=128), nullable=False),
        sa.Column("local_workspace_id", sa.String(length=36), nullable=False),
        sa.Column("source_workspace_id", sa.String(length=36), nullable=False),
        sa.Column("source_workspace_name", sa.String(length=200), nullable=False),
        sa.Column("source_sequence", sa.Integer(), nullable=False),
        sa.Column("target_workspace_id", sa.String(length=36), nullable=False),
        sa.Column("target_workspace_name", sa.String(length=200), nullable=False),
        sa.Column("previous_state_sha256", sa.String(length=64), nullable=False),
        sa.Column("adopted_state_sha256", sa.String(length=64), nullable=False),
        sa.Column("foundation_sha256", sa.String(length=64), nullable=False),
        sa.Column("package_path", sa.Text(), nullable=False),
        sa.Column("package_sha256", sa.String(length=64), nullable=False),
        sa.Column("manifest_sha256", sa.String(length=64), nullable=False),
        sa.Column("manifest_version", sa.String(length=16), nullable=False),
        sa.Column("backup_path", sa.Text(), nullable=False),
        sa.Column("backup_sha256", sa.String(length=64), nullable=False),
        sa.Column("backup_database_sha256", sa.String(length=64), nullable=False),
        sa.Column("backup_database_revision", sa.String(length=128), nullable=True),
        sa.Column("impact_json", sa.JSON(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("applied_by", sa.String(length=200), nullable=False),
        sa.Column("application_reason", sa.Text(), nullable=False),
        sa.Column("parameters_sha256", sa.String(length=64), nullable=False),
        sa.Column("stale_dry_run_count", sa.Integer(), nullable=False),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["local_workspace_id"], ["exchange_workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("adoption_id", name="uq_exchange_state_adoption_id"),
        sa.UniqueConstraint("package_sha256", name="uq_exchange_state_adoption_package"),
    )
    op.create_index(
        "ix_exchange_state_adoptions_workspace_applied",
        "exchange_state_adoptions",
        ["local_workspace_id", "applied_at"],
        unique=False,
    )

    op.create_table(
        "exchange_state_adoption_rollbacks",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("adoption_record_id", sa.String(length=36), nullable=False),
        sa.Column("restored_state_sha256", sa.String(length=64), nullable=False),
        sa.Column("restored_backup_path", sa.Text(), nullable=False),
        sa.Column("restored_backup_sha256", sa.String(length=64), nullable=False),
        sa.Column("safety_backup_path", sa.Text(), nullable=False),
        sa.Column("safety_backup_sha256", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("rolled_back_by", sa.String(length=200), nullable=False),
        sa.Column("rollback_reason", sa.Text(), nullable=False),
        sa.Column("parameters_sha256", sa.String(length=64), nullable=False),
        sa.Column("stale_dry_run_count", sa.Integer(), nullable=False),
        sa.Column("rolled_back_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["adoption_record_id"], ["exchange_state_adoptions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "adoption_record_id", name="uq_exchange_state_adoption_rollback"
        ),
    )
    op.create_index(
        "ix_exchange_state_adoption_rollbacks_time",
        "exchange_state_adoption_rollbacks",
        ["rolled_back_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_exchange_state_adoption_rollbacks_time",
        table_name="exchange_state_adoption_rollbacks",
    )
    op.drop_table("exchange_state_adoption_rollbacks")
    op.drop_index(
        "ix_exchange_state_adoptions_workspace_applied",
        table_name="exchange_state_adoptions",
    )
    op.drop_table("exchange_state_adoptions")
