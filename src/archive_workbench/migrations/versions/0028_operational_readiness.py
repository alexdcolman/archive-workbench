"""Estabilización operativa y pruebas de recuperación.

Revision ID: 0028_operational_readiness
Revises: 0027_temporal_authorities_relations
Create Date: 2026-07-24
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0028_operational_readiness"
down_revision = "0027_temporal_authorities_relations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "project_recovery_checks",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(length=128),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("backup_relative_path", sa.Text(), nullable=False),
        sa.Column("backup_sha256", sa.String(length=64), nullable=False),
        sa.Column("source_database_revision", sa.String(length=128), nullable=True),
        sa.Column("upgraded_database_revision", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("details_json", sa.JSON(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("tested_by", sa.String(length=200), nullable=False),
        sa.Column("tested_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_project_recovery_checks_project_tested",
        "project_recovery_checks",
        ["project_id", "tested_at"],
    )
    op.create_index(
        "ix_project_recovery_checks_backup",
        "project_recovery_checks",
        ["project_id", "backup_sha256"],
    )


def downgrade() -> None:
    op.drop_index("ix_project_recovery_checks_backup", table_name="project_recovery_checks")
    op.drop_index(
        "ix_project_recovery_checks_project_tested", table_name="project_recovery_checks"
    )
    op.drop_table("project_recovery_checks")
