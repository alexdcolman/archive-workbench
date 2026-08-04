"""Registra autorizaciones de alcance para análisis automáticos.

Revision ID: 0034_automatic_analysis_authorizations
Revises: 0033_export_exchange_lifecycle
Create Date: 2026-08-03
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0034_automatic_analysis_authorizations"
down_revision = "0033_export_exchange_lifecycle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "automatic_analysis_authorizations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=128), nullable=False),
        sa.Column("policy_version", sa.String(length=64), nullable=False),
        sa.Column("analysis_kind", sa.String(length=64), nullable=False),
        sa.Column("page_review_statuses_json", sa.JSON(), nullable=False),
        sa.Column("scope_key", sa.String(length=32), nullable=False),
        sa.Column(
            "broader_scope_confirmed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("confirmed_by", sa.String(length=200), nullable=False),
        sa.Column("confirmation_reason", sa.Text(), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("target_type", sa.String(length=100), nullable=True),
        sa.Column("target_id", sa.String(length=100), nullable=True),
        sa.Column("parameters_sha256", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_automatic_analysis_authorizations_project_created",
        "automatic_analysis_authorizations",
        ["project_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_automatic_analysis_authorizations_target",
        "automatic_analysis_authorizations",
        ["project_id", "target_type", "target_id"],
        unique=False,
    )
    op.create_index(
        "ix_automatic_analysis_authorizations_kind",
        "automatic_analysis_authorizations",
        ["project_id", "analysis_kind", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_automatic_analysis_authorizations_kind",
        table_name="automatic_analysis_authorizations",
    )
    op.drop_index(
        "ix_automatic_analysis_authorizations_target",
        table_name="automatic_analysis_authorizations",
    )
    op.drop_index(
        "ix_automatic_analysis_authorizations_project_created",
        table_name="automatic_analysis_authorizations",
    )
    op.drop_table("automatic_analysis_authorizations")
