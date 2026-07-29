"""Índice FTS5 para búsqueda transversal sobre la capa editable.

Revision ID: 0012_editable_search_fts
Revises: 0011_editor_parts_tag_kinds
Create Date: 2026-07-23
"""
from __future__ import annotations

from alembic import op

revision = "0012_editable_search_fts"
down_revision = "0011_editor_parts_tag_kinds"
branch_labels = None
depends_on = None


_DIRTY_TABLES = (
    "editable_objects",
    "editable_pages",
    "editable_object_comments",
    "editable_object_tags",
    "document_parts",
    "archival_units",
    "source_registrations",
)


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE editable_search_state (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            dirty_generation INTEGER NOT NULL DEFAULT 1,
            indexed_generation INTEGER NOT NULL DEFAULT 0,
            indexed_at TEXT NULL
        )
        """
    )
    op.execute(
        "INSERT INTO editable_search_state (id, dirty_generation, indexed_generation) "
        "VALUES (1, 1, 0)"
    )
    op.execute(
        """
        CREATE VIRTUAL TABLE editable_search_fts USING fts5(
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
            tokenize = 'unicode61 remove_diacritics 2'
        )
        """
    )
    for table in _DIRTY_TABLES:
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


def downgrade() -> None:
    for table in reversed(_DIRTY_TABLES):
        for suffix in ("ai", "au", "ad"):
            op.execute(f"DROP TRIGGER IF EXISTS trg_search_dirty_{table}_{suffix}")
    op.execute("DROP TABLE IF EXISTS editable_search_fts")
    op.execute("DROP TABLE IF EXISTS editable_search_state")
