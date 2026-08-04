"""Registra acuerdos bilaterales de base común verificable.

Revision ID: 0036_exchange_common_base_agreements
Revises: 0035_exchange_lineage_recovery
Create Date: 2026-08-03
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0036_exchange_common_base_agreements"
down_revision = "0035_exchange_lineage_recovery"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "exchange_common_base_agreements",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("agreement_id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=128), nullable=False),
        sa.Column("local_workspace_id", sa.String(length=36), nullable=False),
        sa.Column("counterpart_workspace_id", sa.String(length=36), nullable=False),
        sa.Column("local_role", sa.String(length=16), nullable=False),
        sa.Column("adopted_state", sa.String(length=32), nullable=False),
        sa.Column("state_sha256", sa.String(length=64), nullable=False),
        sa.Column("local_sequence", sa.Integer(), nullable=False),
        sa.Column("counterpart_sequence", sa.Integer(), nullable=False),
        sa.Column("local_checkpoint_id", sa.String(length=36), nullable=False),
        sa.Column("local_checkpoint_label", sa.String(length=200), nullable=False),
        sa.Column("proposal_sha256", sa.String(length=64), nullable=False),
        sa.Column("manifest_sha256", sa.String(length=64), nullable=False),
        sa.Column("manifest_version", sa.String(length=16), nullable=False),
        sa.Column("initiator_workspace_id", sa.String(length=36), nullable=False),
        sa.Column("initiator_workspace_name", sa.String(length=200), nullable=False),
        sa.Column("initiator_sequence", sa.Integer(), nullable=False),
        sa.Column("initiator_confirmed_by", sa.String(length=200), nullable=False),
        sa.Column("initiator_confirmation_reason", sa.Text(), nullable=False),
        sa.Column("counterpart_workspace_name", sa.String(length=200), nullable=False),
        sa.Column("counterpart_confirmed_by", sa.String(length=200), nullable=False),
        sa.Column("counterpart_confirmation_reason", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("registered_by", sa.String(length=200), nullable=False),
        sa.Column("registration_reason", sa.Text(), nullable=False),
        sa.Column("parameters_sha256", sa.String(length=64), nullable=False),
        sa.Column("result", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("registered_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["local_workspace_id"], ["exchange_workspaces.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["local_checkpoint_id"], ["exchange_checkpoints.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "agreement_id", name="uq_exchange_common_base_agreement"
        ),
    )
    op.create_index(
        "ix_exchange_common_base_workspace_registered",
        "exchange_common_base_agreements",
        ["local_workspace_id", "registered_at"],
        unique=False,
    )
    op.create_index(
        "ix_exchange_common_base_match",
        "exchange_common_base_agreements",
        [
            "local_checkpoint_id",
            "counterpart_workspace_id",
            "state_sha256",
            "result",
        ],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_exchange_common_base_match",
        table_name="exchange_common_base_agreements",
    )
    op.drop_index(
        "ix_exchange_common_base_workspace_registered",
        table_name="exchange_common_base_agreements",
    )
    op.drop_table("exchange_common_base_agreements")
