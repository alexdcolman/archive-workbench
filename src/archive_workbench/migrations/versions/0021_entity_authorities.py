"""Registros de autoridad, alias, menciones y búsqueda de entidades.

Revision ID: 0021_entity_authorities
Revises: 0020_catalog_exchange_fragment_search
Create Date: 2026-07-24
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0021_entity_authorities"
down_revision = "0020_catalog_exchange_fragment_search"
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
    return f"CASE WHEN NEW.operation = 'create' THEN json_object({create_parts}) ELSE {expression} END"


def _create_fts(table: str, tokenizer: str) -> None:
    op.execute(
        f"""
        CREATE VIRTUAL TABLE {table} USING fts5(
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
            authority_names,
            authority_aliases,
            mention_texts,
            tokenize = '{tokenizer}'
        )
        """
    )


def upgrade() -> None:
    op.create_table(
        "authority_records",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=128), nullable=False),
        sa.Column("entity_type", sa.String(length=32), nullable=False),
        sa.Column("preferred_name", sa.Text(), nullable=False),
        sa.Column("normalized_name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("lifecycle_status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("review_status", sa.String(length=32), nullable=False, server_default="unreviewed"),
        sa.Column("created_by", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by", sa.String(length=200), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_authority_records_project_type", "authority_records", ["project_id", "entity_type"])
    op.create_index("ix_authority_records_project_name", "authority_records", ["project_id", "normalized_name"])
    op.create_index("ix_authority_records_review", "authority_records", ["review_status"])

    op.create_table(
        "authority_aliases",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("authority_id", sa.String(length=36), nullable=False),
        sa.Column("alias", sa.Text(), nullable=False),
        sa.Column("normalized_alias", sa.Text(), nullable=False),
        sa.Column("alias_type", sa.String(length=32), nullable=False, server_default="variant"),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["authority_id"], ["authority_records.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("authority_id", "normalized_alias", name="uq_authority_alias_normalized"),
    )
    op.create_index("ix_authority_aliases_authority", "authority_aliases", ["authority_id"])
    op.create_index("ix_authority_aliases_normalized", "authority_aliases", ["normalized_alias"])

    op.create_table(
        "authority_revisions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("authority_id", sa.String(length=36), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("operation", sa.String(length=32), nullable=False),
        sa.Column("snapshot_json", sa.JSON(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("changed_by", sa.String(length=200), nullable=False),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["authority_id"], ["authority_records.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("authority_id", "revision_number", name="uq_authority_revision_number"),
    )
    op.create_index("ix_authority_revisions_authority", "authority_revisions", ["authority_id", "revision_number"])

    op.create_table(
        "entity_mentions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("editable_object_id", sa.String(length=36), nullable=False),
        sa.Column("authority_id", sa.String(length=36), nullable=True),
        sa.Column("mention_text", sa.Text(), nullable=False),
        sa.Column("normalized_text", sa.Text(), nullable=False),
        sa.Column("start_offset", sa.Integer(), nullable=True),
        sa.Column("end_offset", sa.Integer(), nullable=True),
        sa.Column("object_revision_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("source", sa.String(length=32), nullable=False, server_default="manual"),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by", sa.String(length=200), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.ForeignKeyConstraint(["editable_object_id"], ["editable_objects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["authority_id"], ["authority_records.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_entity_mentions_object", "entity_mentions", ["editable_object_id", "start_offset"])
    op.create_index("ix_entity_mentions_authority", "entity_mentions", ["authority_id"])
    op.create_index("ix_entity_mentions_status", "entity_mentions", ["status"])

    op.create_table(
        "entity_mention_revisions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("mention_id", sa.String(length=36), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("operation", sa.String(length=32), nullable=False),
        sa.Column("snapshot_json", sa.JSON(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("changed_by", sa.String(length=200), nullable=False),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["mention_id"], ["entity_mentions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("mention_id", "revision_number", name="uq_entity_mention_revision_number"),
    )
    op.create_index("ix_entity_mention_revisions_mention", "entity_mention_revisions", ["mention_id", "revision_number"])

    # Los índices de búsqueda son derivados: se recrean con las columnas de entidades.
    op.execute("DROP TABLE IF EXISTS editable_search_fts")
    op.execute("DROP TABLE IF EXISTS editable_search_trigram_fts")
    _create_fts("editable_search_fts", "unicode61 remove_diacritics 2")
    _create_fts("editable_search_trigram_fts", "trigram case_sensitive 0")
    op.execute("UPDATE editable_search_state SET dirty_generation = dirty_generation + 1 WHERE id = 1")

    for table in ("authority_records", "authority_aliases", "entity_mentions"):
        for suffix, event in (("ai", "INSERT"), ("au", "UPDATE"), ("ad", "DELETE")):
            op.execute(
                f"""
                CREATE TRIGGER trg_search_dirty_{table}_{suffix}
                AFTER {event} ON {table}
                BEGIN
                    UPDATE editable_search_state
                    SET dirty_generation = dirty_generation + 1
                    WHERE id = 1;
                END
                """
            )


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
                entity_type='authority_record',
                entity_id='NEW.authority_id',
                operation="CASE WHEN NEW.operation = 'create' THEN 'create' ELSE 'update' END",
                actor='NEW.changed_by',
                timestamp='NEW.changed_at',
                project_id="json_extract(NEW.snapshot_json, '$.project_id')",
                base_revision="CASE WHEN NEW.operation = 'create' THEN NULL ELSE NEW.revision_number - 1 END",
                new_revision='NEW.revision_number',
                changed_fields=_revision_changed_fields(
                    table='authority_revisions',
                    id_field='authority_id',
                    fields=authority_fields,
                ),
            )}
        END
        """
    )

    mention_fields = (
        "editable_object_id", "authority_id", "mention_text", "normalized_text",
        "start_offset", "end_offset", "object_revision_number", "status",
        "source", "confidence", "note",
    )
    op.execute(
        f"""
        CREATE TRIGGER trg_exchange_entity_mention_revision_ai
        AFTER INSERT ON entity_mention_revisions
        BEGIN
            {_event_insert_sql(
                entity_type='entity_mention',
                entity_id='NEW.mention_id',
                operation="CASE WHEN NEW.operation = 'create' THEN 'create' ELSE 'update' END",
                actor='NEW.changed_by',
                timestamp='NEW.changed_at',
                project_id="(SELECT d.project_id FROM entity_mentions m JOIN editable_objects o ON o.id = m.editable_object_id JOIN digital_objects d ON d.id = o.digital_object_id WHERE m.id = NEW.mention_id)",
                base_revision="CASE WHEN NEW.operation = 'create' THEN NULL ELSE NEW.revision_number - 1 END",
                new_revision='NEW.revision_number',
                changed_fields=_revision_changed_fields(
                    table='entity_mention_revisions',
                    id_field='mention_id',
                    fields=mention_fields,
                ),
            )}
        END
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_exchange_entity_mention_revision_ai")
    op.execute("DROP TRIGGER IF EXISTS trg_exchange_authority_revision_ai")
    for table in ("entity_mentions", "authority_aliases", "authority_records"):
        for suffix in ("ai", "au", "ad"):
            op.execute(f"DROP TRIGGER IF EXISTS trg_search_dirty_{table}_{suffix}")
    op.execute("DROP TABLE IF EXISTS editable_search_fts")
    op.execute("DROP TABLE IF EXISTS editable_search_trigram_fts")
    # Restaura el esquema anterior de búsqueda.
    op.execute(
        """
        CREATE VIRTUAL TABLE editable_search_fts USING fts5(
            object_id UNINDEXED, source_key UNINDEXED, document_title UNINDEXED,
            page_number UNINDEXED, order_index UNINDEXED, object_type UNINDEXED,
            object_review_status UNINDEXED, page_review_status UNINDEXED,
            lifecycle_status UNINDEXED, document_part_key UNINDEXED,
            document_part_title UNINDEXED, current_text, original_text, comments,
            thematic_tags, conceptual_tags, workflow_tags, unclassified_tags, all_tags,
            tokenize = 'unicode61 remove_diacritics 2'
        )
        """
    )
    op.execute(
        """
        CREATE VIRTUAL TABLE editable_search_trigram_fts USING fts5(
            object_id UNINDEXED, source_key UNINDEXED, document_title UNINDEXED,
            page_number UNINDEXED, order_index UNINDEXED, object_type UNINDEXED,
            object_review_status UNINDEXED, page_review_status UNINDEXED,
            lifecycle_status UNINDEXED, document_part_key UNINDEXED,
            document_part_title UNINDEXED, current_text, original_text, comments,
            thematic_tags, conceptual_tags, workflow_tags, unclassified_tags, all_tags,
            tokenize = 'trigram case_sensitive 0'
        )
        """
    )
    op.execute("UPDATE editable_search_state SET dirty_generation = dirty_generation + 1 WHERE id = 1")
    op.drop_index("ix_entity_mention_revisions_mention", table_name="entity_mention_revisions")
    op.drop_table("entity_mention_revisions")
    op.drop_index("ix_entity_mentions_status", table_name="entity_mentions")
    op.drop_index("ix_entity_mentions_authority", table_name="entity_mentions")
    op.drop_index("ix_entity_mentions_object", table_name="entity_mentions")
    op.drop_table("entity_mentions")
    op.drop_index("ix_authority_revisions_authority", table_name="authority_revisions")
    op.drop_table("authority_revisions")
    op.drop_index("ix_authority_aliases_normalized", table_name="authority_aliases")
    op.drop_index("ix_authority_aliases_authority", table_name="authority_aliases")
    op.drop_table("authority_aliases")
    op.drop_index("ix_authority_records_review", table_name="authority_records")
    op.drop_index("ix_authority_records_project_name", table_name="authority_records")
    op.drop_index("ix_authority_records_project_type", table_name="authority_records")
    op.drop_table("authority_records")
