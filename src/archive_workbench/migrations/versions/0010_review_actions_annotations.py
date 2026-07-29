"""Acciones de página, estados de revisión, comentarios y etiquetas.

Revision ID: 0010_review_actions_annotations
Revises: 0009_editable_objects
Create Date: 2026-07-23
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0010_review_actions_annotations"
down_revision = "0009_editable_objects"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "editable_pages",
        sa.Column("review_status", sa.String(length=32), nullable=False, server_default="unreviewed"),
    )
    op.add_column("editable_pages", sa.Column("review_note", sa.Text(), nullable=True))
    op.add_column("editable_pages", sa.Column("reviewed_by", sa.String(length=200), nullable=True))
    op.add_column("editable_pages", sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "editable_objects",
        sa.Column("review_status", sa.String(length=32), nullable=False, server_default="unreviewed"),
    )

    op.create_table(
        "editable_page_actions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "editable_page_id",
            sa.String(length=36),
            sa.ForeignKey("editable_pages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("action_type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("before_snapshot_json", sa.JSON(), nullable=False),
        sa.Column("after_snapshot_json", sa.JSON(), nullable=False),
        sa.Column("selected_object_id", sa.String(length=36), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("undone_by", sa.String(length=200), nullable=True),
        sa.Column("undone_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("redone_by", sa.String(length=200), nullable=True),
        sa.Column("redone_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "editable_page_id", "sequence_number", name="uq_editable_page_action_sequence"
        ),
    )
    op.create_index(
        "ix_editable_page_actions_page_status",
        "editable_page_actions",
        ["editable_page_id", "status"],
    )

    op.create_table(
        "editable_object_comments",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "editable_object_id",
            sa.String(length=36),
            sa.ForeignKey("editable_objects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_by", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_editable_object_comments_object",
        "editable_object_comments",
        ["editable_object_id"],
    )

    op.create_table(
        "editable_object_tags",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "editable_object_id",
            sa.String(length=36),
            sa.ForeignKey("editable_objects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tag", sa.String(length=200), nullable=False),
        sa.Column("normalized_tag", sa.String(length=200), nullable=False),
        sa.Column("created_by", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("editable_object_id", "normalized_tag", name="uq_editable_object_tag"),
    )
    op.create_index(
        "ix_editable_object_tags_object", "editable_object_tags", ["editable_object_id"]
    )
    op.create_index(
        "ix_editable_object_tags_normalized", "editable_object_tags", ["normalized_tag"]
    )


def downgrade() -> None:
    op.drop_index("ix_editable_object_tags_normalized", table_name="editable_object_tags")
    op.drop_index("ix_editable_object_tags_object", table_name="editable_object_tags")
    op.drop_table("editable_object_tags")
    op.drop_index("ix_editable_object_comments_object", table_name="editable_object_comments")
    op.drop_table("editable_object_comments")
    op.drop_index("ix_editable_page_actions_page_status", table_name="editable_page_actions")
    op.drop_table("editable_page_actions")
    op.drop_column("editable_objects", "review_status")
    op.drop_column("editable_pages", "reviewed_at")
    op.drop_column("editable_pages", "reviewed_by")
    op.drop_column("editable_pages", "review_note")
    op.drop_column("editable_pages", "review_status")
