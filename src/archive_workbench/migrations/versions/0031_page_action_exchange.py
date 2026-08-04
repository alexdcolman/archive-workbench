"""Transporta acciones de página y sus estados de deshacer/rehacer.

Revision ID: 0031_page_action_exchange
Revises: 0030_source_replaced_exchange
Create Date: 2026-07-29
"""
from __future__ import annotations

from alembic import op

revision = "0031_page_action_exchange"
down_revision = "0030_source_replaced_exchange"
branch_labels = None
depends_on = None


def _uuid_sql() -> str:
    return (
        "lower(hex(randomblob(4))) || '-' || lower(hex(randomblob(2))) || '-' || "
        "lower(hex(randomblob(2))) || '-' || lower(hex(randomblob(2))) || '-' || "
        "lower(hex(randomblob(6)))"
    )


def _workspace_id() -> str:
    return "(SELECT id FROM exchange_workspaces ORDER BY created_at, id LIMIT 1)"


def _project_id(action_alias: str) -> str:
    return (
        "(SELECT d.project_id FROM editable_pages p "
        "JOIN digital_objects d ON d.id = p.digital_object_id "
        f"WHERE p.id = {action_alias}.editable_page_id)"
    )


def _next_sequence() -> str:
    wid = _workspace_id()
    return (
        "COALESCE((SELECT MAX(e.sequence_number) FROM exchange_change_events e "
        f"WHERE e.workspace_id = {wid}), 0) + 1"
    )


def _create_changed(alias: str) -> str:
    return f"""
        json_object(
            'editable_page_id', json_array(NULL, {alias}.editable_page_id),
            'sequence_number', json_array(NULL, {alias}.sequence_number),
            'action_type', json_array(NULL, {alias}.action_type),
            'status', json_array(NULL, {alias}.status),
            'before_snapshot', json_array(NULL, json({alias}.before_snapshot_json)),
            'after_snapshot', json_array(NULL, json({alias}.after_snapshot_json)),
            'selected_object_id', json_array(NULL, {alias}.selected_object_id),
            'note', json_array(NULL, {alias}.note),
            'created_by', json_array(NULL, {alias}.created_by),
            'created_at', json_array(NULL, {alias}.created_at),
            'undone_by', json_array(NULL, {alias}.undone_by),
            'undone_at', json_array(NULL, {alias}.undone_at),
            'redone_by', json_array(NULL, {alias}.redone_by),
            'redone_at', json_array(NULL, {alias}.redone_at)
        )
    """


def _update_changed() -> str:
    fields = []
    for field in ("status", "undone_by", "undone_at", "redone_by", "redone_at"):
        fields.append(
            f"CASE WHEN OLD.{field} IS NOT NEW.{field} "
            f"THEN json_object('{field}', json_array(OLD.{field}, NEW.{field})) "
            "ELSE '{}' END"
        )
    value = fields[0]
    for field in fields[1:]:
        value = f"json_patch({value}, {field})"
    return value


def _backfill_existing_actions() -> None:
    wid = _workspace_id()
    base = (
        "COALESCE((SELECT MAX(e.sequence_number) FROM exchange_change_events e "
        f"WHERE e.workspace_id = {wid}), 0)"
    )
    op.execute(
        f"""
        INSERT INTO exchange_change_events (
            id, workspace_id, project_id, sequence_number, transaction_id,
            entity_type, entity_id, operation, base_revision, new_revision,
            changed_fields_json, actor, occurred_at
        )
        SELECT
            {_uuid_sql()}, {wid}, {_project_id('a')},
            {base} + ROW_NUMBER() OVER (ORDER BY a.created_at, a.editable_page_id, a.sequence_number, a.id),
            {_uuid_sql()}, 'editable_page_action', a.id, 'create', NULL, 1,
            {_create_changed('a')}, a.created_by, a.created_at
        FROM editable_page_actions a
        WHERE {wid} IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM exchange_change_events e
              WHERE e.entity_type = 'editable_page_action'
                AND e.entity_id = a.id
          )
        ORDER BY a.created_at, a.editable_page_id, a.sequence_number, a.id
        """
    )


def _install_triggers() -> None:
    wid = _workspace_id()
    op.execute("DROP TRIGGER IF EXISTS trg_exchange_page_action_ai")
    op.execute("DROP TRIGGER IF EXISTS trg_exchange_page_action_au")
    op.execute(
        f"""
        CREATE TRIGGER trg_exchange_page_action_ai
        AFTER INSERT ON editable_page_actions
        WHEN {wid} IS NOT NULL
        BEGIN
            INSERT INTO exchange_change_events (
                id, workspace_id, project_id, sequence_number, transaction_id,
                entity_type, entity_id, operation, base_revision, new_revision,
                changed_fields_json, actor, occurred_at
            ) VALUES (
                {_uuid_sql()}, {wid}, {_project_id('NEW')}, {_next_sequence()}, {_uuid_sql()},
                'editable_page_action', NEW.id, 'create', NULL, 1,
                {_create_changed('NEW')}, NEW.created_by, NEW.created_at
            );
        END
        """
    )
    changed = _update_changed()
    op.execute(
        f"""
        CREATE TRIGGER trg_exchange_page_action_au
        AFTER UPDATE OF status, undone_by, undone_at, redone_by, redone_at
        ON editable_page_actions
        WHEN {wid} IS NOT NULL AND (
            OLD.status IS NOT NEW.status OR
            OLD.undone_by IS NOT NEW.undone_by OR
            OLD.undone_at IS NOT NEW.undone_at OR
            OLD.redone_by IS NOT NEW.redone_by OR
            OLD.redone_at IS NOT NEW.redone_at
        )
        BEGIN
            INSERT INTO exchange_change_events (
                id, workspace_id, project_id, sequence_number, transaction_id,
                entity_type, entity_id, operation, base_revision, new_revision,
                changed_fields_json, actor, occurred_at
            ) VALUES (
                {_uuid_sql()}, {wid}, {_project_id('NEW')}, {_next_sequence()}, {_uuid_sql()},
                'editable_page_action', NEW.id, 'update', NULL, NULL,
                {changed}, COALESCE(NEW.redone_by, NEW.undone_by, NEW.created_by), CURRENT_TIMESTAMP
            );
        END
        """
    )


def upgrade() -> None:
    _backfill_existing_actions()
    _install_triggers()


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_exchange_page_action_au")
    op.execute("DROP TRIGGER IF EXISTS trg_exchange_page_action_ai")
    op.execute("DELETE FROM exchange_change_events WHERE entity_type = 'editable_page_action'")
