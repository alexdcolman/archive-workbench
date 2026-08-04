"""Comparación, adopción segura e historial de candidatas OCR.

Revision ID: 0029_extraction_candidate_history
Revises: 0028_operational_readiness
Create Date: 2026-07-29
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0029_extraction_candidate_history"
down_revision = "0028_operational_readiness"
branch_labels = None
depends_on = None


def _uuid_sql() -> str:
    return (
        "lower(hex(randomblob(4))) || '-' || lower(hex(randomblob(2))) || '-' || "
        "lower(hex(randomblob(2))) || '-' || lower(hex(randomblob(2))) || '-' || "
        "lower(hex(randomblob(6)))"
    )


def _baseline_event_sql(
    *, entity_type: str, entity_id: str, project_id: str, actor: str, occurred_at: str,
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
            {_uuid_sql()}, '{entity_type}', {entity_id}, 'update', NULL, NULL,
            {changed_fields}, {actor}, {occurred_at}
        FROM exchange_workspaces w
        ORDER BY w.created_at, w.id
        LIMIT 1;
    """


def upgrade() -> None:
    with op.batch_alter_table("editable_pages") as batch:
        batch.add_column(
            sa.Column("revision_number", sa.Integer(), nullable=False, server_default="1")
        )

    op.create_table(
        "extraction_page_selection_revisions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "selection_id",
            sa.String(length=36),
            sa.ForeignKey("extraction_page_selections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "digital_object_id",
            sa.String(length=36),
            sa.ForeignKey("digital_objects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("operation", sa.String(length=32), nullable=False),
        sa.Column(
            "previous_extraction_run_id",
            sa.String(length=36),
            sa.ForeignKey("extraction_runs.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "previous_extraction_page_id",
            sa.String(length=36),
            sa.ForeignKey("extraction_pages.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "extraction_run_id",
            sa.String(length=36),
            sa.ForeignKey("extraction_runs.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "extraction_page_id",
            sa.String(length=36),
            sa.ForeignKey("extraction_pages.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("selected_by", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "selection_id",
            "revision_number",
            name="uq_extraction_page_selection_revision_number",
        ),
    )
    op.create_index(
        "ix_extraction_page_selection_revisions_page",
        "extraction_page_selection_revisions",
        ["digital_object_id", "page_number", "created_at"],
    )
    op.create_index(
        "ix_extraction_page_selection_revisions_selection",
        "extraction_page_selection_revisions",
        ["selection_id", "revision_number"],
    )

    op.create_table(
        "editable_page_revisions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "editable_page_id",
            sa.String(length=36),
            sa.ForeignKey("editable_pages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("base_revision_number", sa.Integer(), nullable=True),
        sa.Column("operation", sa.String(length=32), nullable=False),
        sa.Column(
            "source_extraction_run_id",
            sa.String(length=36),
            sa.ForeignKey("extraction_runs.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "source_extraction_page_id",
            sa.String(length=36),
            sa.ForeignKey("extraction_pages.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "source_selection_id",
            sa.String(length=36),
            sa.ForeignKey("extraction_page_selections.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("review_status", sa.String(length=32), nullable=False),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("details_json", sa.JSON(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "editable_page_id", "revision_number", name="uq_editable_page_revision_number"
        ),
    )
    op.create_index(
        "ix_editable_page_revisions_page",
        "editable_page_revisions",
        ["editable_page_id", "revision_number"],
    )
    op.create_index(
        "ix_editable_page_revisions_created",
        "editable_page_revisions",
        ["created_at"],
    )

    # Las selecciones y páginas existentes adquieren un punto de partida explícito.
    op.execute(
        f"""
        INSERT INTO extraction_page_selection_revisions (
            id, selection_id, digital_object_id, page_number, revision_number,
            operation, previous_extraction_run_id, previous_extraction_page_id,
            extraction_run_id, extraction_page_id, note, selected_by, created_at
        )
        SELECT
            {_uuid_sql()}, id, digital_object_id, page_number, 1,
            'import', NULL, NULL, extraction_run_id, extraction_page_id,
            note, selected_by, selected_at
        FROM extraction_page_selections
        """
    )
    op.execute(
        f"""
        INSERT INTO editable_page_revisions (
            id, editable_page_id, revision_number, base_revision_number, operation,
            source_extraction_run_id, source_extraction_page_id, source_selection_id,
            status, review_status, review_note, details_json, note, created_by, created_at
        )
        SELECT
            {_uuid_sql()}, id, 1, NULL, 'import',
            source_extraction_run_id, source_extraction_page_id, source_selection_id,
            status, review_status, review_note, '{{}}',
            'Estado existente al migrar a 0.34.0', bootstrapped_by, bootstrapped_at
        FROM editable_pages
        """
    )

    # Cambiar la selección o la base OCR altera el punto de partida compartido.
    # Se registra como evento bloqueante: un bundle de ediciones no transporta corridas OCR.
    selection_changed_fields = (
        "json_object("
        "'digital_object_id', json_array(NEW.digital_object_id, NEW.digital_object_id), "
        "'page_number', json_array(NEW.page_number, NEW.page_number), "
        "'extraction_run_id', json_array(NEW.previous_extraction_run_id, NEW.extraction_run_id), "
        "'extraction_page_id', json_array(NEW.previous_extraction_page_id, NEW.extraction_page_id)"
        ")"
    )
    op.execute(
        f"""
        CREATE TRIGGER trg_exchange_selection_baseline_ai
        AFTER INSERT ON extraction_page_selection_revisions
        WHEN NEW.operation <> 'import'
        BEGIN
            {_baseline_event_sql(
                entity_type='extraction_selection_baseline',
                entity_id='NEW.selection_id',
                project_id='(SELECT project_id FROM digital_objects WHERE id = NEW.digital_object_id)',
                actor='NEW.selected_by',
                occurred_at='NEW.created_at',
                changed_fields=selection_changed_fields,
            )}
        END
        """
    )

    editable_changed_fields = (
        "json_object("
        "'digital_object_id', json_array("
        "(SELECT digital_object_id FROM editable_pages WHERE id = NEW.editable_page_id), "
        "(SELECT digital_object_id FROM editable_pages WHERE id = NEW.editable_page_id)), "
        "'page_number', json_array("
        "(SELECT page_number FROM editable_pages WHERE id = NEW.editable_page_id), "
        "(SELECT page_number FROM editable_pages WHERE id = NEW.editable_page_id)), "
        "'source_extraction_run_id', "
        "json_array(json_extract(NEW.details_json, '$.previous_extraction_run_id'), "
        "NEW.source_extraction_run_id), "
        "'source_extraction_page_id', "
        "json_array(json_extract(NEW.details_json, '$.previous_extraction_page_id'), "
        "NEW.source_extraction_page_id)"
        ")"
    )
    op.execute(
        f"""
        CREATE TRIGGER trg_exchange_editable_baseline_ai
        AFTER INSERT ON editable_page_revisions
        WHEN NEW.operation IN ('candidate_adopted', 'manual_keep_edits')
        BEGIN
            {_baseline_event_sql(
                entity_type='editable_page_baseline',
                entity_id='NEW.editable_page_id',
                project_id='(SELECT d.project_id FROM editable_pages p JOIN digital_objects d ON d.id = p.digital_object_id WHERE p.id = NEW.editable_page_id)',
                actor='NEW.created_by',
                occurred_at='NEW.created_at',
                changed_fields=editable_changed_fields,
            )}
        END
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_exchange_editable_baseline_ai")
    op.execute("DROP TRIGGER IF EXISTS trg_exchange_selection_baseline_ai")
    op.drop_index("ix_editable_page_revisions_created", table_name="editable_page_revisions")
    op.drop_index("ix_editable_page_revisions_page", table_name="editable_page_revisions")
    op.drop_table("editable_page_revisions")
    op.drop_index(
        "ix_extraction_page_selection_revisions_selection",
        table_name="extraction_page_selection_revisions",
    )
    op.drop_index(
        "ix_extraction_page_selection_revisions_page",
        table_name="extraction_page_selection_revisions",
    )
    op.drop_table("extraction_page_selection_revisions")
    with op.batch_alter_table("editable_pages") as batch:
        batch.drop_column("revision_number")
