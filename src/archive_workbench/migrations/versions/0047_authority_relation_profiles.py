"""Add structured descriptive profiles to authorities and relations.

Revision ID: 0047_authority_relation_profiles
Revises: 0046_audiovisual_timeline_annotations
Create Date: 2026-08-21
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0047_authority_relation_profiles"
down_revision = "0046_audiovisual_timeline_annotations"
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
    base_revision: str,
    new_revision: str,
    changed_fields: str,
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
            {_uuid_sql()}, '{entity_type}', {entity_id}, {operation},
            {base_revision}, {new_revision}, {changed_fields}, {actor}, {timestamp}
        FROM exchange_workspaces w
        ORDER BY w.created_at, w.id
        LIMIT 1;
    """


def _revision_changed_fields(*, table: str, id_field: str, fields: tuple[str, ...]) -> str:
    previous = (
        f"(SELECT r.snapshot_json FROM {table} r "
        f"WHERE r.{id_field} = NEW.{id_field} "
        "AND r.revision_number = NEW.revision_number - 1)"
    )
    create_parts = ", ".join(
        f"'{field}', json_array(NULL, json_extract(NEW.snapshot_json, '$.{field}'))"
        for field in fields
    )
    expression = "'{}'"
    for field in fields:
        old_value = f"json_extract({previous}, '$.{field}')"
        new_value = f"json_extract(NEW.snapshot_json, '$.{field}')"
        patch = (
            f"CASE WHEN json_quote({old_value}) <> json_quote({new_value}) "
            f"THEN json_object('{field}', json_array({old_value}, {new_value})) "
            "ELSE '{}' END"
        )
        expression = f"json_patch({expression}, {patch})"
    return (
        f"CASE WHEN NEW.operation = 'create' THEN json_object({create_parts}) "
        f"ELSE {expression} END"
    )


def _create_exchange_trigger(
    *,
    trigger_name: str,
    revision_table: str,
    id_field: str,
    entity_type: str,
    entity_id: str,
    fields: tuple[str, ...],
) -> None:
    op.execute(f"DROP TRIGGER IF EXISTS {trigger_name}")
    op.execute(
        f"""
        CREATE TRIGGER {trigger_name}
        AFTER INSERT ON {revision_table}
        BEGIN
            {_event_insert_sql(
                entity_type=entity_type,
                entity_id=entity_id,
                operation="CASE WHEN NEW.operation = 'create' THEN 'create' ELSE 'update' END",
                actor="NEW.changed_by",
                timestamp="NEW.changed_at",
                project_id="json_extract(NEW.snapshot_json, '$.project_id')",
                base_revision=(
                    "CASE WHEN NEW.operation = 'create' THEN NULL "
                    "ELSE NEW.revision_number - 1 END"
                ),
                new_revision="NEW.revision_number",
                changed_fields=_revision_changed_fields(
                    table=revision_table,
                    id_field=id_field,
                    fields=fields,
                ),
            )}
        END
        """
    )


def _authority_fields(*, include_profile: bool) -> tuple[str, ...]:
    fields = (
        "entity_type",
        "preferred_name",
        "normalized_name",
        "description",
        "temporal_expression",
        "temporal_start",
        "temporal_end",
        "temporal_precision",
        "temporal_approximate",
        "temporal_note",
        "lifecycle_status",
        "review_status",
        "aliases",
    )
    if not include_profile:
        return fields
    return fields[:10] + ("profile_json",) + fields[10:]


def _relation_fields(*, include_profile: bool) -> tuple[str, ...]:
    fields = (
        "source_authority_id",
        "relation_kind",
        "relation_label",
        "target_authority_id",
        "target_archival_unit_id",
        "target_document_part_id",
        "evidence_note",
        "provenance_note",
        "temporal_expression",
        "temporal_start",
        "temporal_end",
        "temporal_precision",
        "temporal_approximate",
        "temporal_note",
        "lifecycle_status",
        "review_status",
    )
    if not include_profile:
        return fields
    return fields[:14] + ("profile_json",) + fields[14:]


def _recreate_exchange_triggers(*, include_profile: bool) -> None:
    _create_exchange_trigger(
        trigger_name="trg_exchange_authority_revision_ai",
        revision_table="authority_revisions",
        id_field="authority_id",
        entity_type="authority_record",
        entity_id="NEW.authority_id",
        fields=_authority_fields(include_profile=include_profile),
    )
    _create_exchange_trigger(
        trigger_name="trg_exchange_entity_relation_revision_ai",
        revision_table="entity_relation_revisions",
        id_field="relation_id",
        entity_type="entity_relation",
        entity_id="NEW.relation_id",
        fields=_relation_fields(include_profile=include_profile),
    )


def upgrade() -> None:
    # ALTER TABLE directo evita reconstruir tablas pobladas y activar acciones
    # ON DELETE de claves foráneas durante la migración.
    op.add_column("authority_records", sa.Column("profile_json", sa.JSON(), nullable=True))
    op.add_column("entity_relations", sa.Column("profile_json", sa.JSON(), nullable=True))
    _recreate_exchange_triggers(include_profile=True)


def downgrade() -> None:
    # Los triggers vigentes consultan profile_json dentro del snapshot. Se
    # reemplazan antes de retirar las columnas y se restaura el contrato 0046.
    op.execute("DROP TRIGGER IF EXISTS trg_exchange_entity_relation_revision_ai")
    op.execute("DROP TRIGGER IF EXISTS trg_exchange_authority_revision_ai")
    op.drop_column("entity_relations", "profile_json")
    op.drop_column("authority_records", "profile_json")
    _recreate_exchange_triggers(include_profile=False)
