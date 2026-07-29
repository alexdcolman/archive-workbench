"""Corrige precondiciones de borrado y caducidad del dry-run.

Revision ID: 0016_exchange_delete_preconditions
Revises: 0015_exchange_transactional_apply
Create Date: 2026-07-23
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0016_exchange_delete_preconditions"
down_revision = "0015_exchange_transactional_apply"
branch_labels = None
depends_on = None


def _uuid_sql() -> str:
    return (
        "lower(hex(randomblob(4))) || '-' || lower(hex(randomblob(2))) || '-' || "
        "lower(hex(randomblob(2))) || '-' || lower(hex(randomblob(2))) || '-' || "
        "lower(hex(randomblob(6)))"
    )


def _event_insert_sql(*, changed_fields: str) -> str:
    return f"""
        INSERT INTO exchange_change_events (
            id, workspace_id, project_id, sequence_number, transaction_id,
            entity_type, entity_id, operation, base_revision, new_revision,
            changed_fields_json, actor, occurred_at
        )
        SELECT
            {_uuid_sql()}, w.id,
            (SELECT d.project_id FROM editable_objects o
             JOIN digital_objects d ON d.id = o.digital_object_id
             WHERE o.id = NEW.editable_object_id),
            COALESCE((SELECT MAX(e.sequence_number) FROM exchange_change_events e
                      WHERE e.workspace_id = w.id), 0) + 1,
            {_uuid_sql()}, 'editable_object', NEW.editable_object_id,
            CASE WHEN NEW.base_revision_number IS NULL THEN 'create'
                 WHEN NEW.operation = 'delete' THEN 'delete'
                 WHEN NEW.operation = 'restore' THEN 'restore'
                 ELSE 'update' END,
            NEW.base_revision_number, NEW.revision_number,
            {changed_fields}, NEW.created_by, NEW.created_at
        FROM exchange_workspaces w
        ORDER BY w.created_at, w.id
        LIMIT 1;
    """


def _full_changed_fields() -> str:
    base = "(SELECT r.text FROM editable_object_revisions r WHERE r.editable_object_id = NEW.editable_object_id AND r.revision_number = NEW.base_revision_number)"
    base_type = "(SELECT r.object_type FROM editable_object_revisions r WHERE r.editable_object_id = NEW.editable_object_id AND r.revision_number = NEW.base_revision_number)"
    base_order = "(SELECT r.order_index FROM editable_object_revisions r WHERE r.editable_object_id = NEW.editable_object_id AND r.revision_number = NEW.base_revision_number)"
    base_geometry = "(SELECT json(r.geometry_json) FROM editable_object_revisions r WHERE r.editable_object_id = NEW.editable_object_id AND r.revision_number = NEW.base_revision_number)"
    base_attributes = "(SELECT json(r.attributes_json) FROM editable_object_revisions r WHERE r.editable_object_id = NEW.editable_object_id AND r.revision_number = NEW.base_revision_number)"
    base_lifecycle = "(SELECT r.lifecycle_status FROM editable_object_revisions r WHERE r.editable_object_id = NEW.editable_object_id AND r.revision_number = NEW.base_revision_number)"
    base_part = "(SELECT r.document_part_id FROM editable_object_revisions r WHERE r.editable_object_id = NEW.editable_object_id AND r.revision_number = NEW.base_revision_number)"
    return f"""
        json_patch(json_patch(json_patch(json_patch(json_patch(json_patch(json_patch(json_patch('{{}}',
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
                 THEN json_object('document_part_id', json_array({base_part}, NEW.document_part_id)) ELSE '{{}}' END),
            CASE WHEN NEW.base_revision_number IS NULL THEN json_object(
                'editable_page_id', json_array(NULL, (SELECT o.editable_page_id FROM editable_objects o WHERE o.id = NEW.editable_object_id)),
                'digital_object_id', json_array(NULL, (SELECT o.digital_object_id FROM editable_objects o WHERE o.id = NEW.editable_object_id)),
                'page_number', json_array(NULL, (SELECT o.page_number FROM editable_objects o WHERE o.id = NEW.editable_object_id)),
                'source_extracted_object_id', json_array(NULL, (SELECT o.source_extracted_object_id FROM editable_objects o WHERE o.id = NEW.editable_object_id)),
                'source_origin_id', json_array(NULL, (SELECT o.source_origin_id FROM editable_objects o WHERE o.id = NEW.editable_object_id)),
                'review_status', json_array(NULL, (SELECT o.review_status FROM editable_objects o WHERE o.id = NEW.editable_object_id))
            ) ELSE '{{}}' END)
    """


def _install_trigger(*, canonical_lifecycle: bool) -> None:
    full = _full_changed_fields()
    if canonical_lifecycle:
        changed = f"""
            CASE
                WHEN NEW.operation = 'delete' THEN json_object(
                    'lifecycle_status', json_array('active', 'deleted')
                )
                WHEN NEW.operation = 'restore' THEN json_object(
                    'lifecycle_status', json_array('deleted', 'active')
                )
                ELSE {full}
            END
        """
    else:
        changed = full
    op.execute("DROP TRIGGER IF EXISTS trg_exchange_editable_revision_ai")
    op.execute(
        f"""
        CREATE TRIGGER trg_exchange_editable_revision_ai
        AFTER INSERT ON editable_object_revisions
        BEGIN
            {_event_insert_sql(changed_fields=changed)}
        END
        """
    )


def upgrade() -> None:
    with op.batch_alter_table("exchange_dry_runs") as batch:
        batch.add_column(sa.Column("assessed_state_sha256", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("assessed_sequence_number", sa.Integer(), nullable=True))
    # Los dry-runs anteriores quedan NULL y deben repetirse antes de aplicar.
    _install_trigger(canonical_lifecycle=True)


def downgrade() -> None:
    _install_trigger(canonical_lifecycle=False)
    with op.batch_alter_table("exchange_dry_runs") as batch:
        batch.drop_column("assessed_sequence_number")
        batch.drop_column("assessed_state_sha256")
