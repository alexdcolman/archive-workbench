"""Usabilidad de catálogo, relaciones explícitas y búsqueda robusta.

Revision ID: 0022_catalog_usability_entity_relations
Revises: 0021_entity_authorities
Create Date: 2026-07-24
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0022_catalog_usability_entity_relations"
down_revision = "0021_entity_authorities"
branch_labels = None
depends_on = None


def _uuid_sql() -> str:
    return (
        "lower(hex(randomblob(4))) || '-' || lower(hex(randomblob(2))) || '-' || "
        "lower(hex(randomblob(2))) || '-' || lower(hex(randomblob(2))) || '-' || "
        "lower(hex(randomblob(6)))"
    )


def _event_insert_sql(
    *, entity_type: str, entity_id: str, operation: str, actor: str,
    timestamp: str, project_id: str, base_revision: str = "NULL",
    new_revision: str = "NULL", changed_fields: str = "'{}'",
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


def _create_fts(table: str, tokenizer: str, *, include_relations: bool) -> None:
    relation_column = ", relation_texts" if include_relations else ""
    op.execute(
        f"""
        CREATE VIRTUAL TABLE {table} USING fts5(
            object_id UNINDEXED, source_key UNINDEXED, document_title UNINDEXED,
            page_number UNINDEXED, order_index UNINDEXED, object_type UNINDEXED,
            object_review_status UNINDEXED, page_review_status UNINDEXED,
            lifecycle_status UNINDEXED, document_part_key UNINDEXED,
            document_part_title UNINDEXED, current_text, original_text, comments,
            thematic_tags, conceptual_tags, workflow_tags, unclassified_tags, all_tags,
            authority_names, authority_aliases, mention_texts{relation_column},
            tokenize = '{tokenizer}'
        )
        """
    )


def upgrade() -> None:
    op.create_table(
        "entity_relations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=128), nullable=False),
        sa.Column("source_authority_id", sa.String(length=36), nullable=False),
        sa.Column("relation_label", sa.Text(), nullable=False),
        sa.Column("target_authority_id", sa.String(length=36), nullable=True),
        sa.Column("target_archival_unit_id", sa.String(length=36), nullable=True),
        sa.Column("target_document_part_id", sa.String(length=36), nullable=True),
        sa.Column("evidence_note", sa.Text(), nullable=True),
        sa.Column("lifecycle_status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("review_status", sa.String(length=32), nullable=False, server_default="unreviewed"),
        sa.Column("created_by", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by", sa.String(length=200), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.CheckConstraint(
            "((target_authority_id IS NOT NULL) + (target_archival_unit_id IS NOT NULL) + "
            "(target_document_part_id IS NOT NULL)) = 1",
            name="ck_entity_relation_one_target",
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_authority_id"], ["authority_records.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["target_authority_id"], ["authority_records.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["target_archival_unit_id"], ["archival_units.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["target_document_part_id"], ["document_parts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    for name, columns in (
        ("ix_entity_relations_project", ["project_id"]),
        ("ix_entity_relations_source", ["source_authority_id"]),
        ("ix_entity_relations_target_authority", ["target_authority_id"]),
        ("ix_entity_relations_target_unit", ["target_archival_unit_id"]),
        ("ix_entity_relations_target_part", ["target_document_part_id"]),
    ):
        op.create_index(name, "entity_relations", columns)

    op.create_table(
        "entity_relation_revisions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("relation_id", sa.String(length=36), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("operation", sa.String(length=32), nullable=False),
        sa.Column("snapshot_json", sa.JSON(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("changed_by", sa.String(length=200), nullable=False),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["relation_id"], ["entity_relations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("relation_id", "revision_number", name="uq_entity_relation_revision_number"),
    )
    op.create_index(
        "ix_entity_relation_revisions_relation", "entity_relation_revisions",
        ["relation_id", "revision_number"]
    )

    op.execute("DROP TABLE IF EXISTS editable_search_fts")
    op.execute("DROP TABLE IF EXISTS editable_search_trigram_fts")
    _create_fts("editable_search_fts", "unicode61 remove_diacritics 2", include_relations=True)
    _create_fts("editable_search_trigram_fts", "trigram case_sensitive 0", include_relations=True)
    op.execute("UPDATE editable_search_state SET dirty_generation = dirty_generation + 1 WHERE id = 1")

    for suffix, event in (("ai", "INSERT"), ("au", "UPDATE"), ("ad", "DELETE")):
        op.execute(
            f"""
            CREATE TRIGGER trg_search_dirty_entity_relations_{suffix}
            AFTER {event} ON entity_relations
            BEGIN
                UPDATE editable_search_state
                SET dirty_generation = dirty_generation + 1 WHERE id = 1;
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
                entity_type='entity_relation',
                entity_id='NEW.relation_id',
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

    # La migración anterior registraba altas de vínculos, pero no bajas.
    link_deleted = """
        json_object(
            'digital_object_id', json_array(OLD.digital_object_id, NULL),
            'archival_unit_id', json_array(OLD.archival_unit_id, NULL),
            'relation_type', json_array(OLD.relation_type, NULL),
            'page_start', json_array(OLD.page_start, NULL),
            'page_end', json_array(OLD.page_end, NULL),
            'digital_project_id', json_array((SELECT project_id FROM digital_objects WHERE id = OLD.digital_object_id), NULL),
            'media_type', json_array((SELECT media_type FROM digital_objects WHERE id = OLD.digital_object_id), NULL),
            'original_filename', json_array((SELECT original_filename FROM digital_objects WHERE id = OLD.digital_object_id), NULL),
            'sha256', json_array((SELECT sha256 FROM digital_objects WHERE id = OLD.digital_object_id), NULL),
            'byte_size', json_array((SELECT byte_size FROM digital_objects WHERE id = OLD.digital_object_id), NULL),
            'page_count', json_array((SELECT page_count FROM digital_objects WHERE id = OLD.digital_object_id), NULL)
        )
    """
    op.execute(
        f"""
        CREATE TRIGGER trg_exchange_digital_object_unit_link_ad
        AFTER DELETE ON digital_object_unit_links
        BEGIN
            {_event_insert_sql(
                entity_type='digital_object_unit_link', entity_id='OLD.id', operation="'delete'",
                actor="COALESCE((SELECT registered_by FROM source_registrations WHERE digital_object_id = OLD.digital_object_id AND archival_unit_id = OLD.archival_unit_id ORDER BY registered_at DESC, id DESC LIMIT 1), 'local_user')",
                timestamp="COALESCE((SELECT registered_at FROM source_registrations WHERE digital_object_id = OLD.digital_object_id AND archival_unit_id = OLD.archival_unit_id ORDER BY registered_at DESC, id DESC LIMIT 1), CURRENT_TIMESTAMP)",
                project_id='(SELECT project_id FROM digital_objects WHERE id = OLD.digital_object_id)',
                changed_fields=link_deleted,
            )}
        END
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_exchange_digital_object_unit_link_ad")
    op.execute("DROP TRIGGER IF EXISTS trg_exchange_entity_relation_revision_ai")
    for suffix in ("ai", "au", "ad"):
        op.execute(f"DROP TRIGGER IF EXISTS trg_search_dirty_entity_relations_{suffix}")
    op.execute("DROP TABLE IF EXISTS editable_search_fts")
    op.execute("DROP TABLE IF EXISTS editable_search_trigram_fts")
    _create_fts("editable_search_fts", "unicode61 remove_diacritics 2", include_relations=False)
    _create_fts("editable_search_trigram_fts", "trigram case_sensitive 0", include_relations=False)
    op.execute("UPDATE editable_search_state SET dirty_generation = dirty_generation + 1 WHERE id = 1")
    op.drop_index("ix_entity_relation_revisions_relation", table_name="entity_relation_revisions")
    op.drop_table("entity_relation_revisions")
    for name in (
        "ix_entity_relations_target_part", "ix_entity_relations_target_unit",
        "ix_entity_relations_target_authority", "ix_entity_relations_source",
        "ix_entity_relations_project",
    ):
        op.drop_index(name, table_name="entity_relations")
    op.drop_table("entity_relations")
