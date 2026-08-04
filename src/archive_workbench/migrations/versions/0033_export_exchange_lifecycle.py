"""Agrega ciclo de vida para perfiles de exportación y bundles recibidos.

Revision ID: 0033_export_exchange_lifecycle
Revises: 0032_page_quality_assessments
Create Date: 2026-08-01
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0033_export_exchange_lifecycle"
down_revision = "0032_page_quality_assessments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "corpus_export_profiles",
        sa.Column(
            "lifecycle_status",
            sa.String(length=16),
            nullable=False,
            server_default="active",
        ),
    )
    op.add_column(
        "corpus_export_profiles",
        sa.Column("archived_by", sa.String(length=200), nullable=True),
    )
    op.add_column(
        "corpus_export_profiles",
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_corpus_export_profiles_lifecycle",
        "corpus_export_profiles",
        ["project_id", "lifecycle_status", "updated_at"],
        unique=False,
    )

    op.add_column(
        "exchange_dry_runs",
        sa.Column(
            "lifecycle_status",
            sa.String(length=16),
            nullable=False,
            server_default="active",
        ),
    )
    op.add_column(
        "exchange_dry_runs",
        sa.Column("archived_by", sa.String(length=200), nullable=True),
    )
    op.add_column(
        "exchange_dry_runs",
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "exchange_dry_runs",
        sa.Column("archive_note", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_exchange_dry_runs_lifecycle",
        "exchange_dry_runs",
        ["workspace_id", "lifecycle_status", "assessed_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_exchange_dry_runs_lifecycle", table_name="exchange_dry_runs")
    op.drop_column("exchange_dry_runs", "archive_note")
    op.drop_column("exchange_dry_runs", "archived_at")
    op.drop_column("exchange_dry_runs", "archived_by")
    op.drop_column("exchange_dry_runs", "lifecycle_status")

    op.drop_index(
        "ix_corpus_export_profiles_lifecycle",
        table_name="corpus_export_profiles",
    )
    op.drop_column("corpus_export_profiles", "archived_at")
    op.drop_column("corpus_export_profiles", "archived_by")
    op.drop_column("corpus_export_profiles", "lifecycle_status")
