"""Corrige el intercambio de objetos retirados al adoptar otra candidata OCR.

Revision ID: 0030_source_replaced_exchange
Revises: 0029_extraction_candidate_history
Create Date: 2026-07-29
"""
from __future__ import annotations

from alembic import op

revision = "0030_source_replaced_exchange"
down_revision = "0029_extraction_candidate_history"
branch_labels = None
depends_on = None


_BACKFILL_NOTE = (
    "Estado base reconstruido por 0030_source_replaced_exchange para completar "
    "el historial previo."
)
_BACKFILL_ACTOR = "system:migration_0030"


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


def _install_trigger(*, canonical_source_replaced: bool) -> None:
    full = _full_changed_fields()
    source_replaced = " OR NEW.operation = 'source_replaced'" if canonical_source_replaced else ""
    changed = f"""
        CASE
            WHEN NEW.operation = 'delete'{source_replaced} THEN json_object(
                'lifecycle_status', json_array('active', 'deleted')
            )
            WHEN NEW.operation = 'restore' THEN json_object(
                'lifecycle_status', json_array('deleted', 'active')
            )
            ELSE {full}
        END
    """
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


def _backfill_reconstructable_baselines() -> None:
    """Completa solo bases que pueden reconstruirse sin inventar contenido.

    Se cubren objetos intactos en revisión 1 y objetos cuya primera revisión es
    ``source_replaced``: esa operación únicamente cambia ``active`` por
    ``deleted``, por lo que el resto del estado anterior es conocido.
    """
    op.execute(
        f"""
        INSERT INTO editable_object_revisions (
            id, editable_object_id, revision_number, base_revision_number,
            operation, text, object_type, order_index, geometry_json,
            attributes_json, lifecycle_status, document_part_id, note,
            created_by, created_at
        )
        SELECT
            {_uuid_sql()}, o.id, 1, NULL, 'import',
            CASE WHEN first.operation = 'source_replaced' THEN first.text
                 ELSE o.current_text END,
            CASE WHEN first.operation = 'source_replaced' THEN first.object_type
                 ELSE o.current_object_type END,
            CASE WHEN first.operation = 'source_replaced' THEN first.order_index
                 ELSE o.current_order_index END,
            CASE WHEN first.operation = 'source_replaced' THEN first.geometry_json
                 ELSE o.current_geometry_json END,
            CASE WHEN first.operation = 'source_replaced' THEN first.attributes_json
                 ELSE o.current_attributes_json END,
            CASE WHEN first.operation = 'source_replaced' THEN 'active'
                 ELSE o.lifecycle_status END,
            CASE WHEN first.operation = 'source_replaced' THEN first.document_part_id
                 ELSE o.document_part_id END,
            '{_BACKFILL_NOTE}', '{_BACKFILL_ACTOR}', o.created_at
        FROM editable_objects o
        LEFT JOIN editable_object_revisions existing
               ON existing.editable_object_id = o.id
              AND existing.revision_number = 1
        LEFT JOIN editable_object_revisions first
               ON first.id = (
                    SELECT r.id
                    FROM editable_object_revisions r
                    WHERE r.editable_object_id = o.id
                    ORDER BY r.revision_number, r.created_at, r.id
                    LIMIT 1
               )
        WHERE existing.id IS NULL
          AND (
                o.revision_number = 1
                OR (
                    first.revision_number = 2
                    AND first.operation = 'source_replaced'
                )
          )
        """
    )


def upgrade() -> None:
    # El backfill no es un cambio de usuario y no debe generar eventos de bundle.
    op.execute("DROP TRIGGER IF EXISTS trg_exchange_editable_revision_ai")
    _backfill_reconstructable_baselines()
    _install_trigger(canonical_source_replaced=True)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_exchange_editable_revision_ai")
    op.execute(
        "DELETE FROM editable_object_revisions "
        f"WHERE created_by = '{_BACKFILL_ACTOR}' AND note = '{_BACKFILL_NOTE}'"
    )
    _install_trigger(canonical_source_replaced=False)
