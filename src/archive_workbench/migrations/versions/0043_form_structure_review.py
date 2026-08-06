"""Estructura revisable de formularios y casilleros por página.

Revision ID: 0043_form_structure_review
Revises: 0042_preprocessing_geometry_trace
Create Date: 2026-08-05
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0043_form_structure_review"
down_revision = "0042_preprocessing_geometry_trace"
branch_labels = None
depends_on = None


def _uuid_sql() -> str:
    return (
        "lower(hex(randomblob(4))) || '-' || lower(hex(randomblob(2))) || '-' || "
        "lower(hex(randomblob(2))) || '-' || lower(hex(randomblob(2))) || '-' || "
        "lower(hex(randomblob(6)))"
    )


def upgrade() -> None:
    op.add_column(
        "editable_pages",
        sa.Column(
            "form_structure_json",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )
    op.add_column(
        "editable_page_revisions",
        sa.Column(
            "form_structure_json",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )
    event_id = _uuid_sql()
    transaction_id = _uuid_sql()
    op.execute(
        f"""
        CREATE TRIGGER trg_exchange_page_form_structure_au
        AFTER UPDATE OF form_structure_json ON editable_pages
        WHEN OLD.form_structure_json IS NOT NEW.form_structure_json
        BEGIN
            INSERT INTO exchange_change_events (
                id, workspace_id, project_id, sequence_number, transaction_id,
                entity_type, entity_id, operation, base_revision, new_revision,
                changed_fields_json, actor, occurred_at
            )
            SELECT
                {event_id}, w.id,
                (SELECT project_id FROM digital_objects WHERE id = NEW.digital_object_id),
                COALESCE((SELECT MAX(e.sequence_number) FROM exchange_change_events e
                          WHERE e.workspace_id = w.id), 0) + 1,
                {transaction_id},
                'editable_page', NEW.id, 'update', OLD.revision_number, NEW.revision_number,
                json_object(
                    'form_structure',
                    json_array(json(OLD.form_structure_json), json(NEW.form_structure_json))
                ),
                'local_user', NEW.updated_at
            FROM exchange_workspaces w
            ORDER BY w.created_at, w.id
            LIMIT 1;
        END
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_exchange_page_form_structure_au")
    op.drop_column("editable_page_revisions", "form_structure_json")
    op.drop_column("editable_pages", "form_structure_json")
