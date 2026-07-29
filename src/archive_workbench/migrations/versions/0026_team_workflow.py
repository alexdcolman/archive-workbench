"""Asignaciones de trabajo, avance del equipo y revisión cruzada.

Revision ID: 0026_team_workflow
Revises: 0025_processing_dashboard
Create Date: 2026-07-24
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0026_team_workflow"
down_revision = "0025_processing_dashboard"
branch_labels = None
depends_on = None


def _uuid_sql() -> str:
    return (
        "lower(hex(randomblob(4))) || '-' || lower(hex(randomblob(2))) || '-' || "
        "lower(hex(randomblob(2))) || '-' || lower(hex(randomblob(2))) || '-' || "
        "lower(hex(randomblob(6)))"
    )


def _revision_changed_fields(fields: tuple[str, ...]) -> str:
    previous = (
        "(SELECT r.snapshot_json FROM work_assignment_revisions r "
        "WHERE r.assignment_id = NEW.assignment_id "
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


def upgrade() -> None:
    op.create_table(
        "work_assignments",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=128), nullable=False),
        sa.Column("source_type", sa.String(length=64), nullable=False),
        sa.Column("source_key", sa.String(length=500), nullable=False),
        sa.Column("page_start", sa.Integer(), nullable=True),
        sa.Column("page_end", sa.Integer(), nullable=True),
        sa.Column("assignment_kind", sa.String(length=32), nullable=False),
        sa.Column("assignee", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="planned"),
        sa.Column("priority", sa.String(length=16), nullable=False, server_default="normal"),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("parent_assignment_id", sa.String(length=36), nullable=True),
        sa.Column("outcome", sa.String(length=32), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by", sa.String(length=200), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["parent_assignment_id"], ["work_assignments.id"], ondelete="SET NULL"
        ),
        sa.CheckConstraint(
            "((page_start IS NULL AND page_end IS NULL) OR "
            "(page_start IS NOT NULL AND page_end IS NOT NULL AND "
            "page_start >= 1 AND page_end >= page_start))",
            name="ck_work_assignment_page_scope",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_work_assignments_project_status", "work_assignments", ["project_id", "status"]
    )
    op.create_index(
        "ix_work_assignments_assignee",
        "work_assignments",
        ["project_id", "assignee", "status"],
    )
    op.create_index(
        "ix_work_assignments_source",
        "work_assignments",
        ["project_id", "source_type", "source_key"],
    )
    op.create_index(
        "ix_work_assignments_parent", "work_assignments", ["parent_assignment_id"]
    )

    op.create_table(
        "work_assignment_revisions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("assignment_id", sa.String(length=36), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("operation", sa.String(length=32), nullable=False),
        sa.Column("snapshot_json", sa.JSON(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("changed_by", sa.String(length=200), nullable=False),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["assignment_id"], ["work_assignments.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "assignment_id", "revision_number", name="uq_work_assignment_revision_number"
        ),
    )
    op.create_index(
        "ix_work_assignment_revisions_assignment",
        "work_assignment_revisions",
        ["assignment_id", "revision_number"],
    )

    fields = (
        "project_id",
        "source_type",
        "source_key",
        "page_start",
        "page_end",
        "assignment_kind",
        "assignee",
        "status",
        "priority",
        "due_at",
        "parent_assignment_id",
        "outcome",
        "note",
        "submitted_at",
        "completed_at",
    )
    changed = _revision_changed_fields(fields)
    op.execute(
        f"""
        CREATE TRIGGER trg_exchange_work_assignment_revision_ai
        AFTER INSERT ON work_assignment_revisions
        BEGIN
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
                {_uuid_sql()},
                'work_assignment', NEW.assignment_id,
                CASE WHEN NEW.operation = 'create' THEN 'create' ELSE 'update' END,
                CASE WHEN NEW.operation = 'create' THEN NULL ELSE NEW.revision_number - 1 END,
                NEW.revision_number,
                {changed}, NEW.changed_by, NEW.changed_at
            FROM exchange_workspaces w
            ORDER BY w.created_at, w.id
            LIMIT 1;
        END
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_exchange_work_assignment_revision_ai")
    op.drop_index(
        "ix_work_assignment_revisions_assignment", table_name="work_assignment_revisions"
    )
    op.drop_table("work_assignment_revisions")
    op.drop_index("ix_work_assignments_parent", table_name="work_assignments")
    op.drop_index("ix_work_assignments_source", table_name="work_assignments")
    op.drop_index("ix_work_assignments_assignee", table_name="work_assignments")
    op.drop_index("ix_work_assignments_project_status", table_name="work_assignments")
    op.drop_table("work_assignments")
