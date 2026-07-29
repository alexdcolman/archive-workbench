"""Historial versionado para administración del catálogo.

Revision ID: 0019_catalog_management
Revises: 0018_exchange_resolution_usability
"""

from alembic import op
import sqlalchemy as sa

revision = "0019_catalog_management"
down_revision = "0018_exchange_resolution_usability"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "archival_unit_revisions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("archival_unit_id", sa.String(length=36), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("operation", sa.String(length=32), nullable=False),
        sa.Column("snapshot_json", sa.JSON(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("changed_by", sa.String(length=200), nullable=False),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["archival_unit_id"], ["archival_units.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "archival_unit_id",
            "revision_number",
            name="uq_archival_unit_revision_number",
        ),
    )
    op.create_index(
        "ix_archival_unit_revisions_unit",
        "archival_unit_revisions",
        ["archival_unit_id", "revision_number"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_archival_unit_revisions_unit", table_name="archival_unit_revisions"
    )
    op.drop_table("archival_unit_revisions")
