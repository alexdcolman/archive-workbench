"""Registro de cambios y checkpoints para intercambio offline.

Revision ID: 0013_offline_exchange_log
Revises: 0012_editable_search_fts
Create Date: 2026-07-23
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0013_offline_exchange_log"
down_revision = "0012_editable_search_fts"
branch_labels = None
depends_on = None


def _uuid_sql() -> str:
    return (
        "lower(hex(randomblob(4))) || '-' || lower(hex(randomblob(2))) || '-' || "
        "lower(hex(randomblob(2))) || '-' || lower(hex(randomblob(2))) || '-' || "
        "lower(hex(randomblob(6)))"
    )


def _event_insert_sql(*, entity_type: str, entity_id: str, operation: str, actor: str,
                      timestamp: str, project_id: str, base_revision: str = "NULL",
                      new_revision: str = "NULL", changed_fields: str = "'{}'") -> str:
    event_id = _uuid_sql()
    transaction_id = _uuid_sql()
    return f"""
        INSERT INTO exchange_change_events (
            id, workspace_id, project_id, sequence_number, transaction_id,
            entity_type, entity_id, operation, base_revision, new_revision,
            changed_fields_json, actor, occurred_at
        )
        SELECT
            {event_id}, w.id, {project_id},
            COALESCE((SELECT MAX(e.sequence_number) FROM exchange_change_events e
                      WHERE e.workspace_id = w.id), 0) + 1,
            {transaction_id},
            '{entity_type}', {entity_id}, {operation}, {base_revision}, {new_revision},
            {changed_fields}, {actor}, {timestamp}
        FROM exchange_workspaces w
        ORDER BY w.created_at, w.id
        LIMIT 1;
    """


def upgrade() -> None:
    op.create_table(
        "exchange_workspaces",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("project_id", sa.String(length=128), nullable=True),
        sa.Column("workspace_name", sa.String(length=200), nullable=False),
        sa.Column("created_by", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("project_id", name="uq_exchange_workspace_project"),
    )
    op.create_table(
        "exchange_change_events",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=128), nullable=True),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("transaction_id", sa.String(length=36), nullable=False),
        sa.Column("entity_type", sa.String(length=100), nullable=False),
        sa.Column("entity_id", sa.String(length=36), nullable=False),
        sa.Column("operation", sa.String(length=32), nullable=False),
        sa.Column("base_revision", sa.Integer(), nullable=True),
        sa.Column("new_revision", sa.Integer(), nullable=True),
        sa.Column("changed_fields_json", sa.JSON(), nullable=False),
        sa.Column("actor", sa.String(length=200), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["exchange_workspaces.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("workspace_id", "sequence_number", name="uq_exchange_event_sequence"),
    )
    op.create_index("ix_exchange_events_workspace_sequence", "exchange_change_events", ["workspace_id", "sequence_number"])
    op.create_index("ix_exchange_events_entity", "exchange_change_events", ["entity_type", "entity_id"])
    op.create_index("ix_exchange_events_transaction", "exchange_change_events", ["transaction_id"])

    op.create_table(
        "exchange_checkpoints",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=128), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(length=200), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("state_sha256", sa.String(length=64), nullable=False),
        sa.Column("created_by", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["exchange_workspaces.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("workspace_id", "label", name="uq_exchange_checkpoint_label"),
    )
    op.create_index("ix_exchange_checkpoints_sequence", "exchange_checkpoints", ["workspace_id", "sequence_number"])

    op.create_table(
        "exchange_bundle_records",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("bundle_id", sa.String(length=36), nullable=False),
        sa.Column("direction", sa.String(length=16), nullable=False),
        sa.Column("bundle_sha256", sa.String(length=64), nullable=False),
        sa.Column("relative_path", sa.Text(), nullable=True),
        sa.Column("base_sequence", sa.Integer(), nullable=False),
        sa.Column("last_sequence", sa.Integer(), nullable=False),
        sa.Column("event_count", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("counterpart_workspace_id", sa.String(length=36), nullable=True),
        sa.Column("created_by", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["exchange_workspaces.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("bundle_id", name="uq_exchange_bundle_id"),
    )
    op.create_index("ix_exchange_bundles_workspace_created", "exchange_bundle_records", ["workspace_id", "created_at"])

    now = "CURRENT_TIMESTAMP"
    op.execute(
        f"""
        INSERT INTO exchange_workspaces (id, project_id, workspace_name, created_by, created_at, updated_at)
        VALUES ({_uuid_sql()}, NULL, 'local_workspace', 'system', {now}, {now})
        """
    )

    # Las revisiones son la fuente append-only de las mutaciones textuales y estructurales.
    base = "(SELECT r.text FROM editable_object_revisions r WHERE r.editable_object_id = NEW.editable_object_id AND r.revision_number = NEW.base_revision_number)"
    base_type = "(SELECT r.object_type FROM editable_object_revisions r WHERE r.editable_object_id = NEW.editable_object_id AND r.revision_number = NEW.base_revision_number)"
    base_order = "(SELECT r.order_index FROM editable_object_revisions r WHERE r.editable_object_id = NEW.editable_object_id AND r.revision_number = NEW.base_revision_number)"
    base_geometry = "(SELECT json(r.geometry_json) FROM editable_object_revisions r WHERE r.editable_object_id = NEW.editable_object_id AND r.revision_number = NEW.base_revision_number)"
    base_attributes = "(SELECT json(r.attributes_json) FROM editable_object_revisions r WHERE r.editable_object_id = NEW.editable_object_id AND r.revision_number = NEW.base_revision_number)"
    base_lifecycle = "(SELECT r.lifecycle_status FROM editable_object_revisions r WHERE r.editable_object_id = NEW.editable_object_id AND r.revision_number = NEW.base_revision_number)"
    base_part = "(SELECT r.document_part_id FROM editable_object_revisions r WHERE r.editable_object_id = NEW.editable_object_id AND r.revision_number = NEW.base_revision_number)"
    changed = f"""
        json_patch(json_patch(json_patch(json_patch(json_patch(json_patch(json_patch('{{}}',
            CASE WHEN NEW.base_revision_number IS NULL OR COALESCE({base}, '') <> COALESCE(NEW.text, '')
                 THEN json_object('text', json_array({base}, NEW.text)) ELSE '{{}}' END),
            CASE WHEN NEW.base_revision_number IS NULL OR COALESCE({base_type}, '') <> COALESCE(NEW.object_type, '')
                 THEN json_object('object_type', json_array({base_type}, NEW.object_type)) ELSE '{{}}' END),
            CASE WHEN NEW.base_revision_number IS NULL OR COALESCE({base_order}, -1) <> NEW.order_index
                 THEN json_object('order_index', json_array({base_order}, NEW.order_index)) ELSE '{{}}' END),
            CASE WHEN NEW.base_revision_number IS NULL OR COALESCE({base_geometry}, 'null') <> COALESCE(json(NEW.geometry_json), 'null')
                 THEN json_object('geometry', json_array(json({base_geometry}), json(NEW.geometry_json))) ELSE '{{}}' END),
            CASE WHEN NEW.base_revision_number IS NULL OR COALESCE({base_attributes}, 'null') <> COALESCE(json(NEW.attributes_json), 'null')
                 THEN json_object('attributes', json_array(json({base_attributes}), json(NEW.attributes_json))) ELSE '{{}}' END),
            CASE WHEN NEW.base_revision_number IS NULL OR COALESCE({base_lifecycle}, '') <> COALESCE(NEW.lifecycle_status, '')
                 THEN json_object('lifecycle_status', json_array({base_lifecycle}, NEW.lifecycle_status)) ELSE '{{}}' END),
            CASE WHEN NEW.base_revision_number IS NULL OR COALESCE({base_part}, '') <> COALESCE(NEW.document_part_id, '')
                 THEN json_object('document_part_id', json_array({base_part}, NEW.document_part_id)) ELSE '{{}}' END)
    """
    op.execute(
        f"""
        CREATE TRIGGER trg_exchange_editable_revision_ai
        AFTER INSERT ON editable_object_revisions
        BEGIN
            {_event_insert_sql(
                entity_type='editable_object',
                entity_id='NEW.editable_object_id',
                operation="CASE WHEN NEW.operation IN ('create', 'import') THEN 'create' WHEN NEW.operation = 'delete' THEN 'delete' WHEN NEW.operation = 'restore' THEN 'restore' ELSE 'update' END",
                actor='NEW.created_by',
                timestamp='NEW.created_at',
                project_id="(SELECT d.project_id FROM editable_objects o JOIN digital_objects d ON d.id = o.digital_object_id WHERE o.id = NEW.editable_object_id)",
                base_revision='NEW.base_revision_number',
                new_revision='NEW.revision_number',
                changed_fields=changed,
            )}
        END
        """
    )

    op.execute(
        f"""
        CREATE TRIGGER trg_exchange_comment_ai
        AFTER INSERT ON editable_object_comments
        BEGIN
            {_event_insert_sql(
                entity_type='editable_object_comment', entity_id='NEW.id', operation="'create'",
                actor='NEW.created_by', timestamp='NEW.created_at',
                project_id="(SELECT d.project_id FROM editable_objects o JOIN digital_objects d ON d.id = o.digital_object_id WHERE o.id = NEW.editable_object_id)",
                changed_fields="json_object('editable_object_id', json_array(NULL, NEW.editable_object_id), 'body', json_array(NULL, NEW.body))",
            )}
        END
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER trg_exchange_tag_ai
        AFTER INSERT ON editable_object_tags
        BEGIN
            {_event_insert_sql(
                entity_type='editable_object_tag', entity_id='NEW.id', operation="'create'",
                actor='NEW.created_by', timestamp='NEW.created_at',
                project_id="(SELECT d.project_id FROM editable_objects o JOIN digital_objects d ON d.id = o.digital_object_id WHERE o.id = NEW.editable_object_id)",
                changed_fields="json_object('editable_object_id', json_array(NULL, NEW.editable_object_id), 'tag', json_array(NULL, NEW.tag), 'normalized_tag', json_array(NULL, NEW.normalized_tag), 'tag_kind', json_array(NULL, NEW.tag_kind))",
            )}
        END
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER trg_exchange_tag_ad
        AFTER DELETE ON editable_object_tags
        BEGIN
            {_event_insert_sql(
                entity_type='editable_object_tag', entity_id='OLD.id', operation="'delete'",
                actor="'local_user'", timestamp='CURRENT_TIMESTAMP',
                project_id="(SELECT d.project_id FROM editable_objects o JOIN digital_objects d ON d.id = o.digital_object_id WHERE o.id = OLD.editable_object_id)",
                changed_fields="json_object('editable_object_id', json_array(OLD.editable_object_id, NULL), 'tag', json_array(OLD.tag, NULL), 'normalized_tag', json_array(OLD.normalized_tag, NULL), 'tag_kind', json_array(OLD.tag_kind, NULL))",
            )}
        END
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER trg_exchange_object_review_au
        AFTER UPDATE OF review_status ON editable_objects
        WHEN OLD.review_status IS NOT NEW.review_status
        BEGIN
            {_event_insert_sql(
                entity_type='editable_object', entity_id='NEW.id', operation="'update'",
                actor='NEW.updated_by', timestamp='NEW.updated_at',
                project_id="(SELECT project_id FROM digital_objects WHERE id = NEW.digital_object_id)",
                base_revision='NEW.revision_number', new_revision='NEW.revision_number',
                changed_fields="json_object('review_status', json_array(OLD.review_status, NEW.review_status))",
            )}
        END
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER trg_exchange_page_review_au
        AFTER UPDATE OF review_status, review_note ON editable_pages
        WHEN OLD.review_status IS NOT NEW.review_status OR OLD.review_note IS NOT NEW.review_note
        BEGIN
            {_event_insert_sql(
                entity_type='editable_page', entity_id='NEW.id', operation="'update'",
                actor="COALESCE(NEW.reviewed_by, 'local_user')", timestamp="COALESCE(NEW.reviewed_at, NEW.updated_at)",
                project_id="(SELECT project_id FROM digital_objects WHERE id = NEW.digital_object_id)",
                changed_fields="json_object('review_status', json_array(OLD.review_status, NEW.review_status), 'review_note', json_array(OLD.review_note, NEW.review_note))",
            )}
        END
        """
    )


def downgrade() -> None:
    for trigger in (
        "trg_exchange_page_review_au",
        "trg_exchange_object_review_au",
        "trg_exchange_tag_ad",
        "trg_exchange_tag_ai",
        "trg_exchange_comment_ai",
        "trg_exchange_editable_revision_ai",
    ):
        op.execute(f"DROP TRIGGER IF EXISTS {trigger}")
    op.drop_table("exchange_bundle_records")
    op.drop_table("exchange_checkpoints")
    op.drop_index("ix_exchange_events_transaction", table_name="exchange_change_events")
    op.drop_index("ix_exchange_events_entity", table_name="exchange_change_events")
    op.drop_index("ix_exchange_events_workspace_sequence", table_name="exchange_change_events")
    op.drop_table("exchange_change_events")
    op.drop_table("exchange_workspaces")
