"""Agrega perfiles, corridas y candidatos de descubrimiento abierto.

Revision ID: 0038_open_discovery
Revises: 0037_exchange_state_adoptions
Create Date: 2026-08-03
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0038_open_discovery"
down_revision = "0037_exchange_state_adoptions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "discovery_profiles",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("provider_key", sa.String(length=100), nullable=False),
        sa.Column("provider_version", sa.String(length=100), nullable=False),
        sa.Column("families_json", sa.JSON(), nullable=False),
        sa.Column("include_object_types_json", sa.JSON(), nullable=False),
        sa.Column("include_object_review_statuses_json", sa.JSON(), nullable=False),
        sa.Column("include_page_review_statuses_json", sa.JSON(), nullable=False),
        sa.Column("minimum_confidence", sa.Float(), nullable=False),
        sa.Column("lifecycle_status", sa.String(length=16), nullable=False),
        sa.Column("created_by", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by", sa.String(length=200), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "name", name="uq_discovery_profile_name"),
    )
    op.create_index(
        "ix_discovery_profiles_project",
        "discovery_profiles",
        ["project_id", "updated_at"],
        unique=False,
    )

    op.create_table(
        "discovery_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=128), nullable=False),
        sa.Column("profile_id", sa.String(length=36), nullable=False),
        sa.Column("authorization_id", sa.String(length=36), nullable=False),
        sa.Column("profile_name", sa.String(length=200), nullable=False),
        sa.Column("profile_snapshot_json", sa.JSON(), nullable=False),
        sa.Column("provider_key", sa.String(length=100), nullable=False),
        sa.Column("provider_version", sa.String(length=100), nullable=False),
        sa.Column("method", sa.String(length=100), nullable=False),
        sa.Column("parameters_sha256", sa.String(length=64), nullable=False),
        sa.Column("corpus_state_sha256", sa.String(length=64), nullable=False),
        sa.Column("page_review_statuses_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("object_count", sa.Integer(), nullable=False),
        sa.Column("candidate_count", sa.Integer(), nullable=False),
        sa.Column("family_counts_json", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(length=200), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["profile_id"], ["discovery_profiles.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["authorization_id"],
            ["automatic_analysis_authorizations.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_discovery_runs_project_started",
        "discovery_runs",
        ["project_id", "started_at"],
        unique=False,
    )
    op.create_index(
        "ix_discovery_runs_profile_started",
        "discovery_runs",
        ["profile_id", "started_at"],
        unique=False,
    )

    op.create_table(
        "discovery_candidates",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=128), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("profile_id", sa.String(length=36), nullable=False),
        sa.Column("editable_object_id", sa.String(length=36), nullable=False),
        sa.Column("editable_page_id", sa.String(length=36), nullable=False),
        sa.Column("digital_object_id", sa.String(length=36), nullable=False),
        sa.Column("document_part_id", sa.String(length=36), nullable=True),
        sa.Column("source_key", sa.String(length=500), nullable=True),
        sa.Column("original_filename", sa.Text(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("object_revision_number", sa.Integer(), nullable=False),
        sa.Column("page_revision_number", sa.Integer(), nullable=False),
        sa.Column("start_offset", sa.Integer(), nullable=False),
        sa.Column("end_offset", sa.Integer(), nullable=False),
        sa.Column("exact_text", sa.Text(), nullable=False),
        sa.Column("context_before", sa.Text(), nullable=False),
        sa.Column("context_after", sa.Text(), nullable=False),
        sa.Column("semantic_family", sa.String(length=32), nullable=False),
        sa.Column("suggested_subtype", sa.String(length=100), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("method", sa.String(length=100), nullable=False),
        sa.Column("provider_key", sa.String(length=100), nullable=False),
        sa.Column("provider_version", sa.String(length=100), nullable=False),
        sa.Column("model_name", sa.String(length=500), nullable=True),
        sa.Column("model_version", sa.String(length=200), nullable=True),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("parameters_sha256", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("start_offset >= 0", name="ck_discovery_candidate_start"),
        sa.CheckConstraint("end_offset > start_offset", name="ck_discovery_candidate_end"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["discovery_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["profile_id"], ["discovery_profiles.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["editable_object_id"], ["editable_objects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["editable_page_id"], ["editable_pages.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["digital_object_id"], ["digital_objects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["document_part_id"], ["document_parts.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "run_id",
            "editable_object_id",
            "start_offset",
            "end_offset",
            "semantic_family",
            "suggested_subtype",
            name="uq_discovery_candidate_location",
        ),
    )
    op.create_index(
        "ix_discovery_candidates_run",
        "discovery_candidates",
        ["run_id", "semantic_family"],
        unique=False,
    )
    op.create_index(
        "ix_discovery_candidates_object",
        "discovery_candidates",
        ["editable_object_id", "start_offset"],
        unique=False,
    )
    op.create_index(
        "ix_discovery_candidates_project_created",
        "discovery_candidates",
        ["project_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_discovery_candidates_project_created", table_name="discovery_candidates"
    )
    op.drop_index("ix_discovery_candidates_object", table_name="discovery_candidates")
    op.drop_index("ix_discovery_candidates_run", table_name="discovery_candidates")
    op.drop_table("discovery_candidates")
    op.drop_index("ix_discovery_runs_profile_started", table_name="discovery_runs")
    op.drop_index("ix_discovery_runs_project_started", table_name="discovery_runs")
    op.drop_table("discovery_runs")
    op.drop_index("ix_discovery_profiles_project", table_name="discovery_profiles")
    op.drop_table("discovery_profiles")
