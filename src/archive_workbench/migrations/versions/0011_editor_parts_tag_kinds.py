"""Partes internas en objetos editables y categorías de etiquetas.

Revision ID: 0011_editor_parts_tag_kinds
Revises: 0010_review_actions_annotations
Create Date: 2026-07-23
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0011_editor_parts_tag_kinds"
down_revision = "0010_review_actions_annotations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("editable_objects") as batch:
        batch.add_column(sa.Column("document_part_id", sa.String(length=36), nullable=True))
        batch.create_foreign_key(
            "fk_editable_objects_document_part",
            "document_parts",
            ["document_part_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_index("ix_editable_objects_document_part", ["document_part_id"])

    with op.batch_alter_table("editable_object_revisions") as batch:
        batch.add_column(sa.Column("document_part_id", sa.String(length=36), nullable=True))
        batch.create_foreign_key(
            "fk_editable_object_revisions_document_part",
            "document_parts",
            ["document_part_id"],
            ["id"],
            ondelete="SET NULL",
        )

    with op.batch_alter_table("editable_object_tags") as batch:
        batch.add_column(
            sa.Column(
                "tag_kind",
                sa.String(length=32),
                nullable=False,
                server_default="unclassified",
            )
        )
        batch.drop_constraint("uq_editable_object_tag", type_="unique")
        batch.create_unique_constraint(
            "uq_editable_object_tag_kind",
            ["editable_object_id", "tag_kind", "normalized_tag"],
        )
        batch.create_index("ix_editable_object_tags_kind", ["tag_kind"])


def downgrade() -> None:
    with op.batch_alter_table("editable_object_tags") as batch:
        batch.drop_index("ix_editable_object_tags_kind")
        batch.drop_constraint("uq_editable_object_tag_kind", type_="unique")
        batch.create_unique_constraint(
            "uq_editable_object_tag", ["editable_object_id", "normalized_tag"]
        )
        batch.drop_column("tag_kind")

    with op.batch_alter_table("editable_object_revisions") as batch:
        batch.drop_constraint("fk_editable_object_revisions_document_part", type_="foreignkey")
        batch.drop_column("document_part_id")

    with op.batch_alter_table("editable_objects") as batch:
        batch.drop_index("ix_editable_objects_document_part")
        batch.drop_constraint("fk_editable_objects_document_part", type_="foreignkey")
        batch.drop_column("document_part_id")
