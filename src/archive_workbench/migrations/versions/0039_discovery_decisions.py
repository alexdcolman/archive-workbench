"""Agrega decisiones y registros propios de descubrimiento abierto.

Revision ID: 0039_discovery_decisions
Revises: 0038_open_discovery
Create Date: 2026-08-03
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0039_discovery_decisions"
down_revision = "0038_open_discovery"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "discovery_decisions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=128), nullable=False),
        sa.Column("candidate_id", sa.String(length=36), nullable=False),
        sa.Column("decision_number", sa.Integer(), nullable=False),
        sa.Column("decision_type", sa.String(length=32), nullable=False),
        sa.Column("reviewed_text", sa.Text(), nullable=False),
        sa.Column("semantic_family", sa.String(length=32), nullable=False),
        sa.Column("reviewed_subtype", sa.String(length=100), nullable=False),
        sa.Column("acceptance_mode", sa.String(length=32), nullable=True),
        sa.Column("target_authority_id", sa.String(length=36), nullable=True),
        sa.Column("created_mention_id", sa.String(length=36), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("candidate_state_sha256", sa.String(length=64), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("decided_by", sa.String(length=200), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["candidate_id"], ["discovery_candidates.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["target_authority_id"], ["authority_records.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["created_mention_id"], ["entity_mentions.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "candidate_id", "decision_number", name="uq_discovery_decision_number"
        ),
    )
    op.create_index(
        "ix_discovery_decisions_project_decided",
        "discovery_decisions",
        ["project_id", "decided_at"],
        unique=False,
    )
    op.create_index(
        "ix_discovery_decisions_candidate",
        "discovery_decisions",
        ["candidate_id", "decision_number"],
        unique=False,
    )

    op.create_table(
        "discovery_context_records",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=128), nullable=False),
        sa.Column("candidate_id", sa.String(length=36), nullable=False),
        sa.Column("decision_id", sa.String(length=36), nullable=False),
        sa.Column("semantic_family", sa.String(length=32), nullable=False),
        sa.Column("subtype", sa.String(length=100), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("normalized_label", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("temporal_expression", sa.Text(), nullable=True),
        sa.Column("temporal_start", sa.Date(), nullable=True),
        sa.Column("temporal_end", sa.Date(), nullable=True),
        sa.Column("temporal_precision", sa.String(length=32), nullable=True),
        sa.Column("temporal_approximate", sa.Boolean(), nullable=False),
        sa.Column("editable_object_id", sa.String(length=36), nullable=False),
        sa.Column("editable_page_id", sa.String(length=36), nullable=False),
        sa.Column("digital_object_id", sa.String(length=36), nullable=False),
        sa.Column("document_part_id", sa.String(length=36), nullable=True),
        sa.Column("object_revision_number", sa.Integer(), nullable=False),
        sa.Column("start_offset", sa.Integer(), nullable=False),
        sa.Column("end_offset", sa.Integer(), nullable=False),
        sa.Column("target_authority_id", sa.String(length=36), nullable=True),
        sa.Column("data_json", sa.JSON(), nullable=False),
        sa.Column("lifecycle_status", sa.String(length=16), nullable=False),
        sa.Column("created_by", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["candidate_id"], ["discovery_candidates.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["decision_id"], ["discovery_decisions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["editable_object_id"], ["editable_objects.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["editable_page_id"], ["editable_pages.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["digital_object_id"], ["digital_objects.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["document_part_id"], ["document_parts.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["target_authority_id"], ["authority_records.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("decision_id", name="uq_discovery_context_record_decision"),
    )
    op.create_index(
        "ix_discovery_context_records_project_family",
        "discovery_context_records",
        ["project_id", "semantic_family", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_discovery_context_records_object",
        "discovery_context_records",
        ["editable_object_id", "start_offset"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_discovery_context_records_object",
        table_name="discovery_context_records",
    )
    op.drop_index(
        "ix_discovery_context_records_project_family",
        table_name="discovery_context_records",
    )
    op.drop_table("discovery_context_records")
    op.drop_index(
        "ix_discovery_decisions_candidate", table_name="discovery_decisions"
    )
    op.drop_index(
        "ix_discovery_decisions_project_decided", table_name="discovery_decisions"
    )
    op.drop_table("discovery_decisions")
