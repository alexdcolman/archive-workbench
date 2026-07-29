"""Perfiles y ejecuciones reproducibles de exportación.

Revision ID: 0023_reproducible_corpus_exports
Revises: 0022_catalog_usability_entity_relations
Create Date: 2026-07-24
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0023_reproducible_corpus_exports"
down_revision = "0022_catalog_usability_entity_relations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "corpus_export_profiles",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("aggregation_level", sa.String(length=32), nullable=False),
        sa.Column("text_policy", sa.String(length=32), nullable=False),
        sa.Column("output_format", sa.String(length=16), nullable=False, server_default="jsonl"),
        sa.Column("include_object_types_json", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("include_review_statuses_json", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("include_page_review_statuses_json", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("object_separator", sa.Text(), nullable=False, server_default="\n\n"),
        sa.Column("page_separator", sa.Text(), nullable=False, server_default="\n\n"),
        sa.Column("include_page_markers", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_by", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by", sa.String(length=200), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "name", name="uq_corpus_export_profile_name"),
    )
    op.create_index(
        "ix_corpus_export_profiles_project",
        "corpus_export_profiles",
        ["project_id", "updated_at"],
    )

    op.create_table(
        "corpus_export_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=128), nullable=False),
        sa.Column("profile_id", sa.String(length=36), nullable=True),
        sa.Column("profile_name", sa.String(length=200), nullable=False),
        sa.Column("profile_snapshot_json", sa.JSON(), nullable=False),
        sa.Column("corpus_state_sha256", sa.String(length=64), nullable=False),
        sa.Column("output_format", sa.String(length=16), nullable=False),
        sa.Column("output_relative_path", sa.Text(), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("character_count", sa.Integer(), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("output_sha256", sa.String(length=64), nullable=False),
        sa.Column("created_by", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["profile_id"], ["corpus_export_profiles.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_corpus_export_runs_project_created",
        "corpus_export_runs",
        ["project_id", "created_at"],
    )
    op.create_index(
        "ix_corpus_export_runs_profile",
        "corpus_export_runs",
        ["profile_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_corpus_export_runs_profile", table_name="corpus_export_runs")
    op.drop_index("ix_corpus_export_runs_project_created", table_name="corpus_export_runs")
    op.drop_table("corpus_export_runs")
    op.drop_index("ix_corpus_export_profiles_project", table_name="corpus_export_profiles")
    op.drop_table("corpus_export_profiles")
