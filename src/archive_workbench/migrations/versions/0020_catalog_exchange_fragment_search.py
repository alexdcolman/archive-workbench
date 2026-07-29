"""Intercambio de catálogo, búsqueda por fragmentos y metadatos de vínculos.

Revision ID: 0020_catalog_exchange_fragment_search
Revises: 0019_catalog_management
Create Date: 2026-07-24
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0020_catalog_exchange_fragment_search"
down_revision = "0019_catalog_management"
branch_labels = None
depends_on = None


def _uuid_sql() -> str:
    return (
        "lower(hex(randomblob(4))) || '-' || lower(hex(randomblob(2))) || '-' || "
        "lower(hex(randomblob(2))) || '-' || lower(hex(randomblob(2))) || '-' || "
        "lower(hex(randomblob(6)))"
    )


def _event_insert_sql(
    *,
    entity_type: str,
    entity_id: str,
    operation: str,
    actor: str,
    timestamp: str,
    project_id: str,
    base_revision: str = "NULL",
    new_revision: str = "NULL",
    changed_fields: str = "'{}'",
) -> str:
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


def _catalog_changed_fields_sql() -> str:
    old_snapshot = (
        "(SELECT r.snapshot_json FROM archival_unit_revisions r "
        "WHERE r.archival_unit_id = NEW.archival_unit_id "
        "AND r.revision_number = NEW.revision_number - 1)"
    )
    fields = (
        "parent_id",
        "level_key",
        "reference_code",
        "title",
        "registration_status",
        "completion_confirmed",
        "completion_confirmed_at",
        "completion_confirmed_by",
        "fields",
    )
    create_parts = ", ".join(
        f"'{field}', json_array(NULL, json_extract(NEW.snapshot_json, '$.{field}'))"
        for field in fields
    )
    expression = "'{}'"
    for field in fields:
        old_value = f"json_extract({old_snapshot}, '$.{field}')"
        new_value = f"json_extract(NEW.snapshot_json, '$.{field}')"
        patch = (
            f"CASE WHEN json_quote({old_value}) <> json_quote({new_value}) "
            f"THEN json_object('{field}', json_array({old_value}, {new_value})) "
            "ELSE '{}' END"
        )
        expression = f"json_patch({expression}, {patch})"
    return (
        "CASE WHEN NEW.operation = 'create' "
        f"THEN json_object({create_parts}) ELSE {expression} END"
    )


def upgrade() -> None:
    op.execute(
        """
        CREATE VIRTUAL TABLE editable_search_trigram_fts USING fts5(
            object_id UNINDEXED,
            source_key UNINDEXED,
            document_title UNINDEXED,
            page_number UNINDEXED,
            order_index UNINDEXED,
            object_type UNINDEXED,
            object_review_status UNINDEXED,
            page_review_status UNINDEXED,
            lifecycle_status UNINDEXED,
            document_part_key UNINDEXED,
            document_part_title UNINDEXED,
            current_text,
            original_text,
            comments,
            thematic_tags,
            conceptual_tags,
            workflow_tags,
            unclassified_tags,
            all_tags,
            tokenize = 'trigram case_sensitive 0'
        )
        """
    )
    op.execute(
        "UPDATE editable_search_state SET dirty_generation = dirty_generation + 1 WHERE id = 1"
    )

    op.execute(
        f"""
        CREATE TRIGGER trg_exchange_archival_revision_ai
        AFTER INSERT ON archival_unit_revisions
        WHEN NEW.operation <> 'baseline'
        BEGIN
            {_event_insert_sql(
                entity_type='archival_unit',
                entity_id='NEW.archival_unit_id',
                operation="CASE WHEN NEW.operation = 'create' THEN 'create' ELSE 'update' END",
                actor='NEW.changed_by',
                timestamp='NEW.changed_at',
                project_id="json_extract(NEW.snapshot_json, '$.project_id')",
                base_revision="CASE WHEN NEW.operation = 'create' THEN NULL ELSE NEW.revision_number - 1 END",
                new_revision='NEW.revision_number',
                changed_fields=_catalog_changed_fields_sql(),
            )}
        END
        """
    )

    link_changed = """
        json_object(
            'digital_object_id', json_array(NULL, NEW.digital_object_id),
            'archival_unit_id', json_array(NULL, NEW.archival_unit_id),
            'relation_type', json_array(NULL, NEW.relation_type),
            'page_start', json_array(NULL, NEW.page_start),
            'page_end', json_array(NULL, NEW.page_end),
            'digital_project_id', json_array(NULL, (SELECT project_id FROM digital_objects WHERE id = NEW.digital_object_id)),
            'media_type', json_array(NULL, (SELECT media_type FROM digital_objects WHERE id = NEW.digital_object_id)),
            'original_filename', json_array(NULL, (SELECT original_filename FROM digital_objects WHERE id = NEW.digital_object_id)),
            'sha256', json_array(NULL, (SELECT sha256 FROM digital_objects WHERE id = NEW.digital_object_id)),
            'byte_size', json_array(NULL, (SELECT byte_size FROM digital_objects WHERE id = NEW.digital_object_id)),
            'page_count', json_array(NULL, (SELECT page_count FROM digital_objects WHERE id = NEW.digital_object_id))
        )
    """
    op.execute(
        f"""
        CREATE TRIGGER trg_exchange_digital_object_unit_link_ai
        AFTER INSERT ON digital_object_unit_links
        BEGIN
            {_event_insert_sql(
                entity_type='digital_object_unit_link',
                entity_id='NEW.id',
                operation="'create'",
                actor="COALESCE((SELECT registered_by FROM source_registrations WHERE digital_object_id = NEW.digital_object_id AND archival_unit_id = NEW.archival_unit_id ORDER BY registered_at DESC, id DESC LIMIT 1), 'local_user')",
                timestamp="COALESCE((SELECT registered_at FROM source_registrations WHERE digital_object_id = NEW.digital_object_id AND archival_unit_id = NEW.archival_unit_id ORDER BY registered_at DESC, id DESC LIMIT 1), CURRENT_TIMESTAMP)",
                project_id='(SELECT project_id FROM digital_objects WHERE id = NEW.digital_object_id)',
                changed_fields=link_changed,
            )}
        END
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_exchange_digital_object_unit_link_ai")
    op.execute("DROP TRIGGER IF EXISTS trg_exchange_archival_revision_ai")
    op.execute("DROP TABLE IF EXISTS editable_search_trigram_fts")
