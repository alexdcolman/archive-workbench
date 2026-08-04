"""Agrega agrupamiento y continuidad textual de descubrimiento abierto.

Revision ID: 0040_discovery_grouping_continuity
Revises: 0039_discovery_decisions
Create Date: 2026-08-03
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0040_discovery_grouping_continuity"
down_revision = "0039_discovery_decisions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "discovery_candidate_groups",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=128), nullable=False),
        sa.Column("preferred_label", sa.Text(), nullable=False),
        sa.Column("normalized_label", sa.Text(), nullable=False),
        sa.Column("semantic_family", sa.String(length=32), nullable=False),
        sa.Column("suggested_subtype", sa.String(length=100), nullable=True),
        sa.Column("grouping_method", sa.String(length=32), nullable=False),
        sa.Column("lifecycle_status", sa.String(length=16), nullable=False),
        sa.Column("created_by", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by", sa.String(length=200), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_discovery_candidate_groups_project_family",
        "discovery_candidate_groups",
        ["project_id", "semantic_family", "normalized_label"],
        unique=False,
    )
    op.create_index(
        "ix_discovery_candidate_groups_project_status",
        "discovery_candidate_groups",
        ["project_id", "lifecycle_status", "created_at"],
        unique=False,
    )

    op.create_table(
        "discovery_group_memberships",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=128), nullable=False),
        sa.Column("group_id", sa.String(length=36), nullable=False),
        sa.Column("candidate_id", sa.String(length=36), nullable=False),
        sa.Column("membership_status", sa.String(length=16), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("added_by", sa.String(length=200), nullable=False),
        sa.Column("added_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("removed_by", sa.String(length=200), nullable=True),
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("removal_reason", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["group_id"], ["discovery_candidate_groups.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["candidate_id"], ["discovery_candidates.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "group_id", "candidate_id", name="uq_discovery_group_membership"
        ),
    )
    op.create_index(
        "ix_discovery_group_memberships_group_status",
        "discovery_group_memberships",
        ["group_id", "membership_status"],
        unique=False,
    )
    op.create_index(
        "ix_discovery_group_memberships_candidate_status",
        "discovery_group_memberships",
        ["candidate_id", "membership_status"],
        unique=False,
    )

    op.create_table(
        "discovery_group_actions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=128), nullable=False),
        sa.Column("group_id", sa.String(length=36), nullable=False),
        sa.Column("candidate_id", sa.String(length=36), nullable=True),
        sa.Column("action_type", sa.String(length=32), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["group_id"], ["discovery_candidate_groups.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["candidate_id"], ["discovery_candidates.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_discovery_group_actions_group_created",
        "discovery_group_actions",
        ["group_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_discovery_group_actions_project_created",
        "discovery_group_actions",
        ["project_id", "created_at"],
        unique=False,
    )

    op.create_table(
        "discovery_candidate_continuities",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=128), nullable=False),
        sa.Column("source_candidate_id", sa.String(length=36), nullable=False),
        sa.Column("target_candidate_id", sa.String(length=36), nullable=False),
        sa.Column("method", sa.String(length=32), nullable=False),
        sa.Column("source_object_revision_number", sa.Integer(), nullable=False),
        sa.Column("target_object_revision_number", sa.Integer(), nullable=False),
        sa.Column("source_start_offset", sa.Integer(), nullable=False),
        sa.Column("source_end_offset", sa.Integer(), nullable=False),
        sa.Column("target_start_offset", sa.Integer(), nullable=False),
        sa.Column("target_end_offset", sa.Integer(), nullable=False),
        sa.Column("evidence_sha256", sa.String(length=64), nullable=False),
        sa.Column("created_by", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["source_candidate_id"], ["discovery_candidates.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["target_candidate_id"], ["discovery_candidates.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_candidate_id",
            "target_object_revision_number",
            name="uq_discovery_candidate_continuity_revision",
        ),
        sa.UniqueConstraint(
            "target_candidate_id", name="uq_discovery_candidate_continuity_target"
        ),
    )
    op.create_index(
        "ix_discovery_candidate_continuities_source",
        "discovery_candidate_continuities",
        ["source_candidate_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_discovery_candidate_continuities_project",
        "discovery_candidate_continuities",
        ["project_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_discovery_candidate_continuities_project",
        table_name="discovery_candidate_continuities",
    )
    op.drop_index(
        "ix_discovery_candidate_continuities_source",
        table_name="discovery_candidate_continuities",
    )
    op.drop_table("discovery_candidate_continuities")
    op.drop_index(
        "ix_discovery_group_actions_project_created",
        table_name="discovery_group_actions",
    )
    op.drop_index(
        "ix_discovery_group_actions_group_created",
        table_name="discovery_group_actions",
    )
    op.drop_table("discovery_group_actions")
    op.drop_index(
        "ix_discovery_group_memberships_candidate_status",
        table_name="discovery_group_memberships",
    )
    op.drop_index(
        "ix_discovery_group_memberships_group_status",
        table_name="discovery_group_memberships",
    )
    op.drop_table("discovery_group_memberships")
    op.drop_index(
        "ix_discovery_candidate_groups_project_status",
        table_name="discovery_candidate_groups",
    )
    op.drop_index(
        "ix_discovery_candidate_groups_project_family",
        table_name="discovery_candidate_groups",
    )
    op.drop_table("discovery_candidate_groups")
