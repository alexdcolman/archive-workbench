"""Temporalidad transversal para entidades, relaciones y exportaciones.

Revision ID: 0027_temporal_authorities_relations
Revises: 0026_team_workflow
Create Date: 2026-07-24
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0027_temporal_authorities_relations"
down_revision = "0026_team_workflow"
branch_labels = None
depends_on = None


def _uuid_sql() -> str:
    return (
        "lower(hex(randomblob(4))) || '-' || lower(hex(randomblob(2))) || '-' || "
        "lower(hex(randomblob(2))) || '-' || lower(hex(randomblob(2))) || '-' || "
        "lower(hex(randomblob(6)))"
    )


def _event_insert_sql(*, entity_type: str, entity_id: str, operation: str, actor: str,
                      timestamp: str, project_id: str, base_revision: str,
                      new_revision: str, changed_fields: str) -> str:
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


def _add_temporal_columns(table: str) -> None:
    # Todas estas columnas pueden agregarse directamente en SQLite. Evitar
    # batch_alter_table es crítico: el modo batch recrea la tabla y activa las
    # acciones ON DELETE de las claves foráneas que apuntan a authority_records.
    op.add_column(table, sa.Column("temporal_expression", sa.Text(), nullable=True))
    op.add_column(table, sa.Column("temporal_start", sa.Date(), nullable=True))
    op.add_column(table, sa.Column("temporal_end", sa.Date(), nullable=True))
    op.add_column(table, sa.Column("temporal_precision", sa.String(length=32), nullable=True))
    op.add_column(
        table,
        sa.Column(
            "temporal_approximate",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(table, sa.Column("temporal_note", sa.Text(), nullable=True))


def _drop_temporal_columns(table: str) -> None:
    # SQLite >= 3.35 soporta DROP COLUMN directo. Al igual que en upgrade, no
    # debe recrearse authority_records porque eso alteraría sus dependencias.
    op.drop_column(table, "temporal_note")
    op.drop_column(table, "temporal_approximate")
    op.drop_column(table, "temporal_precision")
    op.drop_column(table, "temporal_end")
    op.drop_column(table, "temporal_start")
    op.drop_column(table, "temporal_expression")


def upgrade() -> None:
    for table in ("authority_records", "entity_relations"):
        _add_temporal_columns(table)

    op.create_index(
        "ix_authority_records_temporal", "authority_records",
        ["project_id", "temporal_start", "temporal_end"],
    )
    op.create_index(
        "ix_entity_relations_temporal", "entity_relations",
        ["project_id", "temporal_start", "temporal_end"],
    )

    op.add_column(
        "corpus_export_profiles",
        sa.Column("temporal_start", sa.Date(), nullable=True),
    )
    op.add_column(
        "corpus_export_profiles",
        sa.Column("temporal_end", sa.Date(), nullable=True),
    )
    op.add_column(
        "corpus_export_profiles",
        sa.Column(
            "temporal_include_undated",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )

    op.execute("DROP TRIGGER IF EXISTS trg_exchange_authority_revision_ai")
    authority_fields = (
        "entity_type", "preferred_name", "normalized_name", "description",
        "temporal_expression", "temporal_start", "temporal_end",
        "temporal_precision", "temporal_approximate", "temporal_note",
        "lifecycle_status", "review_status", "aliases",
    )
    op.execute(
        f"""
        CREATE TRIGGER trg_exchange_authority_revision_ai
        AFTER INSERT ON authority_revisions
        BEGIN
            {_event_insert_sql(
                entity_type='authority_record', entity_id='NEW.authority_id',
                operation="CASE WHEN NEW.operation = 'create' THEN 'create' ELSE 'update' END",
                actor='NEW.changed_by', timestamp='NEW.changed_at',
                project_id="json_extract(NEW.snapshot_json, '$.project_id')",
                base_revision="CASE WHEN NEW.operation = 'create' THEN NULL ELSE NEW.revision_number - 1 END",
                new_revision='NEW.revision_number',
                changed_fields=_revision_changed_fields(
                    table='authority_revisions', id_field='authority_id', fields=authority_fields,
                ),
            )}
        END
        """
    )

    op.execute("DROP TRIGGER IF EXISTS trg_exchange_entity_relation_revision_ai")
    relation_fields = (
        "source_authority_id", "relation_label", "target_authority_id",
        "target_archival_unit_id", "target_document_part_id", "evidence_note",
        "temporal_expression", "temporal_start", "temporal_end",
        "temporal_precision", "temporal_approximate", "temporal_note",
        "lifecycle_status", "review_status",
    )
    op.execute(
        f"""
        CREATE TRIGGER trg_exchange_entity_relation_revision_ai
        AFTER INSERT ON entity_relation_revisions
        BEGIN
            {_event_insert_sql(
                entity_type='entity_relation', entity_id='NEW.relation_id',
                operation="CASE WHEN NEW.operation = 'create' THEN 'create' ELSE 'update' END",
                actor='NEW.changed_by', timestamp='NEW.changed_at',
                project_id="json_extract(NEW.snapshot_json, '$.project_id')",
                base_revision="CASE WHEN NEW.operation = 'create' THEN NULL ELSE NEW.revision_number - 1 END",
                new_revision='NEW.revision_number',
                changed_fields=_revision_changed_fields(
                    table='entity_relation_revisions', id_field='relation_id', fields=relation_fields,
                ),
            )}
        END
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_exchange_entity_relation_revision_ai")
    op.execute("DROP TRIGGER IF EXISTS trg_exchange_authority_revision_ai")

    op.drop_column("corpus_export_profiles", "temporal_include_undated")
    op.drop_column("corpus_export_profiles", "temporal_end")
    op.drop_column("corpus_export_profiles", "temporal_start")

    op.drop_index("ix_entity_relations_temporal", table_name="entity_relations")
    op.drop_index("ix_authority_records_temporal", table_name="authority_records")
    for table in ("entity_relations", "authority_records"):
        _drop_temporal_columns(table)

    # Restaura los triggers de 0.31 con el conjunto de campos anterior.
    authority_fields = (
        "entity_type", "preferred_name", "normalized_name", "description",
        "lifecycle_status", "review_status", "aliases",
    )
    op.execute(
        f"""
        CREATE TRIGGER trg_exchange_authority_revision_ai
        AFTER INSERT ON authority_revisions
        BEGIN
            {_event_insert_sql(
                entity_type='authority_record', entity_id='NEW.authority_id',
                operation="CASE WHEN NEW.operation = 'create' THEN 'create' ELSE 'update' END",
                actor='NEW.changed_by', timestamp='NEW.changed_at',
                project_id="json_extract(NEW.snapshot_json, '$.project_id')",
                base_revision="CASE WHEN NEW.operation = 'create' THEN NULL ELSE NEW.revision_number - 1 END",
                new_revision='NEW.revision_number',
                changed_fields=_revision_changed_fields(
                    table='authority_revisions', id_field='authority_id', fields=authority_fields,
                ),
            )}
        END
        """
    )
    relation_fields = (
        "source_authority_id", "relation_label", "target_authority_id",
        "target_archival_unit_id", "target_document_part_id", "evidence_note",
        "lifecycle_status", "review_status",
    )
    op.execute(
        f"""
        CREATE TRIGGER trg_exchange_entity_relation_revision_ai
        AFTER INSERT ON entity_relation_revisions
        BEGIN
            {_event_insert_sql(
                entity_type='entity_relation', entity_id='NEW.relation_id',
                operation="CASE WHEN NEW.operation = 'create' THEN 'create' ELSE 'update' END",
                actor='NEW.changed_by', timestamp='NEW.changed_at',
                project_id="json_extract(NEW.snapshot_json, '$.project_id')",
                base_revision="CASE WHEN NEW.operation = 'create' THEN NULL ELSE NEW.revision_number - 1 END",
                new_revision='NEW.revision_number',
                changed_fields=_revision_changed_fields(
                    table='entity_relation_revisions', id_field='relation_id', fields=relation_fields,
                ),
            )}
        END
        """
    )
