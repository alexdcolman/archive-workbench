"""Add ordered digital components for catalog document units.

Revision ID: 0048_catalog_document_components
Revises: 0047_authority_relation_profiles
Create Date: 2026-09-11
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0048_catalog_document_components"
down_revision = "0047_authority_relation_profiles"
branch_labels = None
depends_on = None


def _uuid_sql() -> str:
    return (
        "lower(hex(randomblob(4))) || '-' || lower(hex(randomblob(2))) || '-' || "
        "lower(hex(randomblob(2))) || '-' || lower(hex(randomblob(2))) || '-' || "
        "lower(hex(randomblob(6)))"
    )


def _event_insert_sql(*, operation: str, actor: str, timestamp: str) -> str:
    source = "OLD" if operation == "delete" else "NEW"
    old = "OLD" if operation != "create" else None
    new = "NEW" if operation != "delete" else None
    def pair(field: str) -> str:
        before = f"{old}.{field}" if old else "NULL"
        after = f"{new}.{field}" if new else "NULL"
        return f"json_array({before}, {after})"
    return f"""
        INSERT INTO exchange_change_events (
            id, workspace_id, project_id, sequence_number, transaction_id,
            entity_type, entity_id, operation, base_revision, new_revision,
            changed_fields_json, actor, occurred_at
        )
        SELECT
            {_uuid_sql()}, w.id,
            COALESCE(
                (SELECT project_id FROM archival_units WHERE id = {source}.archival_unit_id),
                (SELECT project_id FROM digital_objects WHERE id = {source}.digital_object_id)
            ),
            COALESCE((SELECT MAX(e.sequence_number) FROM exchange_change_events e
                      WHERE e.workspace_id = w.id), 0) + 1,
            {_uuid_sql()}, 'archival_document_component', {source}.id, '{operation}',
            NULL, NULL,
            json_object(
                'archival_unit_id', {pair('archival_unit_id')},
                'digital_object_id', {pair('digital_object_id')},
                'sequence_position', {pair('sequence_position')},
                'page_start', {pair('page_start')},
                'page_end', {pair('page_end')}
            ),
            {actor}, {timestamp}
        FROM exchange_workspaces w
        ORDER BY w.created_at, w.id
        LIMIT 1;
    """


def upgrade() -> None:
    op.create_table(
        "archival_document_components",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("archival_unit_id", sa.String(length=36), nullable=False),
        sa.Column("digital_object_id", sa.String(length=36), nullable=False),
        sa.Column("sequence_position", sa.Integer(), nullable=False),
        sa.Column("page_start", sa.Integer(), nullable=True),
        sa.Column("page_end", sa.Integer(), nullable=True),
        sa.Column("created_by", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by", sa.String(length=200), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "sequence_position >= 1", name="ck_archival_document_component_position_positive"
        ),
        sa.CheckConstraint(
            "page_start IS NULL OR page_start >= 1",
            name="ck_archival_document_component_page_start_positive",
        ),
        sa.CheckConstraint(
            "page_end IS NULL OR page_end >= 1",
            name="ck_archival_document_component_page_end_positive",
        ),
        sa.CheckConstraint(
            "page_start IS NULL OR page_end IS NULL OR page_end >= page_start",
            name="ck_archival_document_component_page_order",
        ),
        sa.ForeignKeyConstraint(
            ["archival_unit_id"], ["archival_units.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["digital_object_id"], ["digital_objects.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "archival_unit_id",
            "sequence_position",
            name="uq_archival_document_component_position",
        ),
    )
    op.create_index(
        "ix_archival_document_components_unit",
        "archival_document_components",
        ["archival_unit_id", "sequence_position"],
    )
    op.create_index(
        "ix_archival_document_components_digital",
        "archival_document_components",
        ["digital_object_id"],
    )

    op.execute(
        f"""
        CREATE TRIGGER trg_exchange_archival_document_component_ai
        AFTER INSERT ON archival_document_components
        BEGIN
            {_event_insert_sql(operation='create', actor='NEW.created_by', timestamp='NEW.created_at')}
        END
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER trg_exchange_archival_document_component_au
        AFTER UPDATE ON archival_document_components
        BEGIN
            {_event_insert_sql(operation='update', actor='NEW.updated_by', timestamp='NEW.updated_at')}
        END
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER trg_exchange_archival_document_component_ad
        AFTER DELETE ON archival_document_components
        BEGIN
            {_event_insert_sql(operation='delete', actor='OLD.updated_by', timestamp='OLD.updated_at')}
        END
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_exchange_archival_document_component_ad")
    op.execute("DROP TRIGGER IF EXISTS trg_exchange_archival_document_component_au")
    op.execute("DROP TRIGGER IF EXISTS trg_exchange_archival_document_component_ai")
    op.drop_index(
        "ix_archival_document_components_digital", table_name="archival_document_components"
    )
    op.drop_index(
        "ix_archival_document_components_unit", table_name="archival_document_components"
    )
    op.drop_table("archival_document_components")
