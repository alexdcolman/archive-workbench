"""Roles archivísticos controlados y capas documentales del grafo.

Revision ID: 0041_catalog_authority_roles_graph_layers
Revises: 0040_discovery_grouping_continuity
Create Date: 2026-08-04
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0041_catalog_authority_roles_graph_layers"
down_revision = "0040_discovery_grouping_continuity"
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
            json_extract(NEW.snapshot_json, '$.project_id'),
            COALESCE((SELECT MAX(e.sequence_number) FROM exchange_change_events e
                      WHERE e.workspace_id = w.id), 0) + 1,
            {_uuid_sql()}, 'entity_relation', NEW.relation_id,
            CASE WHEN NEW.operation = 'create' THEN 'create' ELSE 'update' END,
            CASE WHEN NEW.operation = 'create' THEN NULL ELSE NEW.revision_number - 1 END,
            NEW.revision_number, {changed_fields}, NEW.changed_by, NEW.changed_at
        FROM exchange_workspaces w
        ORDER BY w.created_at, w.id
        LIMIT 1;
    """


def _revision_changed_fields(fields: tuple[str, ...]) -> str:
    previous = (
        "(SELECT r.snapshot_json FROM entity_relation_revisions r "
        "WHERE r.relation_id = NEW.relation_id "
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


def _create_exchange_trigger(fields: tuple[str, ...]) -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_exchange_entity_relation_revision_ai")
    op.execute(
        f"""
        CREATE TRIGGER trg_exchange_entity_relation_revision_ai
        AFTER INSERT ON entity_relation_revisions
        BEGIN
            {_event_insert_sql(changed_fields=_revision_changed_fields(fields))}
        END
        """
    )


def _create_contract_triggers() -> None:
    invalid = """
        NEW.relation_kind NOT IN ('analytical', 'producer', 'manager')
        OR (
            NEW.relation_kind IN ('producer', 'manager')
            AND (
                NEW.target_archival_unit_id IS NULL
                OR NEW.target_authority_id IS NOT NULL
                OR NEW.target_document_part_id IS NOT NULL
                OR length(trim(coalesce(NEW.evidence_note, ''))) = 0
                OR length(trim(coalesce(NEW.provenance_note, ''))) = 0
            )
        )
        OR (NEW.relation_kind = 'producer' AND NEW.relation_label <> 'produjo')
        OR (NEW.relation_kind = 'manager' AND NEW.relation_label <> 'gestionó')
    """
    for suffix, event in (("bi", "INSERT"), ("bu", "UPDATE")):
        op.execute(
            f"""
            CREATE TRIGGER trg_entity_relation_contract_{suffix}
            BEFORE {event} ON entity_relations
            WHEN {invalid}
            BEGIN
                SELECT RAISE(
                    ABORT,
                    'Contrato inválido de relación analítica, productora o gestora'
                );
            END
            """
        )


def upgrade() -> None:
    # ALTER TABLE directo evita reconstruir una tabla poblada y activar acciones
    # ON DELETE de sus claves foráneas.
    op.add_column(
        "entity_relations",
        sa.Column(
            "relation_kind",
            sa.String(length=32),
            nullable=False,
            server_default="analytical",
        ),
    )
    op.add_column(
        "entity_relations",
        sa.Column("provenance_note", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_entity_relations_project_kind_target_unit",
        "entity_relations",
        ["project_id", "relation_kind", "target_archival_unit_id"],
        unique=False,
    )
    _create_contract_triggers()

    relation_fields = (
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
    _create_exchange_trigger(relation_fields)
    op.execute(
        "UPDATE editable_search_state SET dirty_generation = dirty_generation + 1 WHERE id = 1"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_entity_relation_contract_bu")
    op.execute("DROP TRIGGER IF EXISTS trg_entity_relation_contract_bi")
    op.drop_index(
        "ix_entity_relations_project_kind_target_unit",
        table_name="entity_relations",
    )
    op.execute("DROP TRIGGER IF EXISTS trg_exchange_entity_relation_revision_ai")
    op.drop_column("entity_relations", "provenance_note")
    op.drop_column("entity_relations", "relation_kind")

    previous_fields = (
        "source_authority_id",
        "relation_label",
        "target_authority_id",
        "target_archival_unit_id",
        "target_document_part_id",
        "evidence_note",
        "temporal_expression",
        "temporal_start",
        "temporal_end",
        "temporal_precision",
        "temporal_approximate",
        "temporal_note",
        "lifecycle_status",
        "review_status",
    )
    _create_exchange_trigger(previous_fields)
    op.execute(
        "UPDATE editable_search_state SET dirty_generation = dirty_generation + 1 WHERE id = 1"
    )
