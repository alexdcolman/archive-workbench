"""Aplicación transaccional de bundles recibidos.

Revision ID: 0015_exchange_transactional_apply
Revises: 0014_exchange_dry_run
Create Date: 2026-07-23
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0015_exchange_transactional_apply"
down_revision = "0014_exchange_dry_run"
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
    return f"""
        INSERT INTO exchange_change_events (
            id, workspace_id, project_id, sequence_number, transaction_id,
            entity_type, entity_id, operation, base_revision, new_revision,
            changed_fields_json, actor, occurred_at
        )
        SELECT
            {_uuid_sql()}, w.id, {project_id},
            COALESCE((SELECT MAX(e.sequence_number) FROM exchange_change_events e
                      WHERE e.workspace_id = w.id), 0) + 1,
            {_uuid_sql()},
            '{entity_type}', {entity_id}, {operation}, {base_revision}, {new_revision},
            {changed_fields}, {actor}, {timestamp}
        FROM exchange_workspaces w
        ORDER BY w.created_at, w.id
        LIMIT 1;
    """


def upgrade() -> None:
    op.create_table(
        "exchange_bundle_applications",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("dry_run_id", sa.String(length=36), nullable=False),
        sa.Column("bundle_record_id", sa.String(length=36), nullable=False),
        sa.Column("bundle_id", sa.String(length=36), nullable=False),
        sa.Column("source_workspace_id", sa.String(length=36), nullable=False),
        sa.Column("backup_relative_path", sa.Text(), nullable=False),
        sa.Column("backup_sha256", sa.String(length=64), nullable=False),
        sa.Column("applied_event_count", sa.Integer(), nullable=False),
        sa.Column("duplicate_event_count", sa.Integer(), nullable=False),
        sa.Column("local_sequence_start", sa.Integer(), nullable=False),
        sa.Column("local_sequence_end", sa.Integer(), nullable=False),
        sa.Column("checkpoint_id", sa.String(length=36), nullable=True),
        sa.Column("checkpoint_label", sa.String(length=200), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("applied_by", sa.String(length=200), nullable=False),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["exchange_workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["dry_run_id"], ["exchange_dry_runs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["bundle_record_id"], ["exchange_bundle_records.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["checkpoint_id"], ["exchange_checkpoints.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("bundle_id", name="uq_exchange_application_bundle"),
    )
    op.create_index(
        "ix_exchange_applications_workspace_applied",
        "exchange_bundle_applications",
        ["workspace_id", "applied_at"],
    )
    with op.batch_alter_table("exchange_incoming_event_assessments") as batch:
        batch.add_column(sa.Column("application_id", sa.String(length=36), nullable=True))
        batch.add_column(sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True))
        batch.create_foreign_key(
            "fk_exchange_assessment_application",
            "exchange_bundle_applications",
            ["application_id"],
            ["id"],
            ondelete="SET NULL",
        )

    # Enriquece los futuros eventos de creación de objetos con su contexto de página.
    op.execute("DROP TRIGGER IF EXISTS trg_exchange_editable_revision_ai")
    base = "(SELECT r.text FROM editable_object_revisions r WHERE r.editable_object_id = NEW.editable_object_id AND r.revision_number = NEW.base_revision_number)"
    base_type = "(SELECT r.object_type FROM editable_object_revisions r WHERE r.editable_object_id = NEW.editable_object_id AND r.revision_number = NEW.base_revision_number)"
    base_order = "(SELECT r.order_index FROM editable_object_revisions r WHERE r.editable_object_id = NEW.editable_object_id AND r.revision_number = NEW.base_revision_number)"
    base_geometry = "(SELECT json(r.geometry_json) FROM editable_object_revisions r WHERE r.editable_object_id = NEW.editable_object_id AND r.revision_number = NEW.base_revision_number)"
    base_attributes = "(SELECT json(r.attributes_json) FROM editable_object_revisions r WHERE r.editable_object_id = NEW.editable_object_id AND r.revision_number = NEW.base_revision_number)"
    base_lifecycle = "(SELECT r.lifecycle_status FROM editable_object_revisions r WHERE r.editable_object_id = NEW.editable_object_id AND r.revision_number = NEW.base_revision_number)"
    base_part = "(SELECT r.document_part_id FROM editable_object_revisions r WHERE r.editable_object_id = NEW.editable_object_id AND r.revision_number = NEW.base_revision_number)"
    changed = f"""
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
    op.execute(
        f"""
        CREATE TRIGGER trg_exchange_editable_revision_ai
        AFTER INSERT ON editable_object_revisions
        BEGIN
            {_event_insert_sql(
                entity_type='editable_object',
                entity_id='NEW.editable_object_id',
                operation="CASE WHEN NEW.base_revision_number IS NULL THEN 'create' WHEN NEW.operation = 'delete' THEN 'delete' WHEN NEW.operation = 'restore' THEN 'restore' ELSE 'update' END",
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


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_exchange_editable_revision_ai")
    with op.batch_alter_table("exchange_incoming_event_assessments") as batch:
        batch.drop_constraint("fk_exchange_assessment_application", type_="foreignkey")
        batch.drop_column("applied_at")
        batch.drop_column("application_id")
    op.drop_index("ix_exchange_applications_workspace_applied", table_name="exchange_bundle_applications")
    op.drop_table("exchange_bundle_applications")
