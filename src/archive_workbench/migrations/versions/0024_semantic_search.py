"""Búsqueda semántica opcional y reconstruible.

Revision ID: 0024_semantic_search
Revises: 0023_reproducible_corpus_exports
Create Date: 2026-07-24
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0024_semantic_search"
down_revision = "0023_reproducible_corpus_exports"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "semantic_search_profiles",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("model_name", sa.String(length=500), nullable=False),
        sa.Column("model_revision", sa.String(length=100), nullable=True),
        sa.Column("aggregation_level", sa.String(length=32), nullable=False, server_default="object"),
        sa.Column("include_object_types_json", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("include_review_statuses_json", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("include_page_review_statuses_json", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("chunk_size", sa.Integer(), nullable=False, server_default="1800"),
        sa.Column("chunk_overlap", sa.Integer(), nullable=False, server_default="200"),
        sa.Column("query_prefix", sa.Text(), nullable=False, server_default="query: "),
        sa.Column("document_prefix", sa.Text(), nullable=False, server_default="passage: "),
        sa.Column("normalize_embeddings", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by", sa.String(length=200), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "name", name="uq_semantic_search_profile_name"),
    )
    op.create_index(
        "ix_semantic_search_profiles_project",
        "semantic_search_profiles",
        ["project_id", "updated_at"],
    )
    op.create_table(
        "semantic_index_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=128), nullable=False),
        sa.Column("profile_id", sa.String(length=36), nullable=False),
        sa.Column("profile_snapshot_json", sa.JSON(), nullable=False),
        sa.Column("corpus_state_sha256", sa.String(length=64), nullable=False),
        sa.Column("model_name", sa.String(length=500), nullable=False),
        sa.Column("model_revision", sa.String(length=100), nullable=True),
        sa.Column("vectors_relative_path", sa.Text(), nullable=False),
        sa.Column("metadata_relative_path", sa.Text(), nullable=False),
        sa.Column("manifest_relative_path", sa.Text(), nullable=False),
        sa.Column("vector_count", sa.Integer(), nullable=False),
        sa.Column("dimensions", sa.Integer(), nullable=False),
        sa.Column("vectors_sha256", sa.String(length=64), nullable=False),
        sa.Column("metadata_sha256", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="completed"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["profile_id"], ["semantic_search_profiles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_semantic_index_runs_profile_created",
        "semantic_index_runs",
        ["profile_id", "created_at"],
    )
    op.create_index(
        "ix_semantic_index_runs_project_created",
        "semantic_index_runs",
        ["project_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_semantic_index_runs_project_created", table_name="semantic_index_runs")
    op.drop_index("ix_semantic_index_runs_profile_created", table_name="semantic_index_runs")
    op.drop_table("semantic_index_runs")
    op.drop_index("ix_semantic_search_profiles_project", table_name="semantic_search_profiles")
    op.drop_table("semantic_search_profiles")
