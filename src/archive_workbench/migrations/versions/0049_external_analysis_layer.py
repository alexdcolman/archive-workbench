"""Add reviewed external-analysis persistence.

Revision ID: 0049_external_analysis_layer
Revises: 0048_catalog_document_components
Create Date: 2026-09-16
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0049_external_analysis_layer"
down_revision = "0048_catalog_document_components"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "external_analysis_packages",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=128), nullable=False),
        sa.Column("package_sha256", sa.String(length=64), nullable=False),
        sa.Column("package_type", sa.String(length=120), nullable=False),
        sa.Column("schema_version", sa.String(length=32), nullable=False),
        sa.Column("protocol", sa.String(length=120), nullable=False),
        sa.Column("producer_id", sa.String(length=200), nullable=True),
        sa.Column("producer_version", sa.String(length=120), nullable=True),
        sa.Column("request_id", sa.String(length=200), nullable=True),
        sa.Column("exp01_sha256", sa.String(length=64), nullable=False),
        sa.Column("result_bundle_sha256", sa.String(length=64), nullable=False),
        sa.Column("model_json", sa.JSON(), nullable=False),
        sa.Column("runtime_json", sa.JSON(), nullable=False),
        sa.Column("prompt_json", sa.JSON(), nullable=False),
        sa.Column("source_scope_json", sa.JSON(), nullable=False),
        sa.Column("proposal_count", sa.Integer(), nullable=False),
        sa.Column("manifest_json", sa.JSON(), nullable=False),
        sa.Column("imported_by", sa.String(length=200), nullable=False),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("proposal_count >= 1", name="ck_external_analysis_package_count"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id", "package_sha256", name="uq_external_analysis_package_sha256"
        ),
    )
    op.create_index(
        "ix_external_analysis_packages_project_imported",
        "external_analysis_packages",
        ["project_id", "imported_at"],
    )
    op.create_index(
        "ix_external_analysis_packages_exp01",
        "external_analysis_packages",
        ["project_id", "exp01_sha256"],
    )

    op.create_table(
        "external_analysis_package_sources",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("package_id", sa.String(length=36), nullable=False),
        sa.Column("export_run_id", sa.String(length=36), nullable=False),
        sa.Column("match_kind", sa.String(length=32), nullable=False),
        sa.Column("linked_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["package_id"], ["external_analysis_packages.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["export_run_id"], ["corpus_export_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "package_id", "export_run_id", name="uq_external_analysis_package_source"
        ),
    )
    op.create_index(
        "ix_external_analysis_package_sources_package",
        "external_analysis_package_sources",
        ["package_id", "export_run_id"],
    )

    op.create_table(
        "external_analysis_proposals",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("package_id", sa.String(length=36), nullable=False),
        sa.Column("external_proposal_id", sa.String(length=200), nullable=False),
        sa.Column("result_id", sa.String(length=200), nullable=False),
        sa.Column("output_schema_id", sa.String(length=120), nullable=False),
        sa.Column("target_type", sa.String(length=32), nullable=False),
        sa.Column("target_id", sa.String(length=500), nullable=False),
        sa.Column("digital_object_id", sa.String(length=36), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("source_key", sa.Text(), nullable=True),
        sa.Column("original_filename", sa.Text(), nullable=True),
        sa.Column("asset_path", sa.Text(), nullable=False),
        sa.Column("source_asset_sha256", sa.String(length=64), nullable=False),
        sa.Column("output_json", sa.JSON(), nullable=False),
        sa.Column("output_sha256", sa.String(length=64), nullable=False),
        sa.Column("provenance_json", sa.JSON(), nullable=False),
        sa.Column("warnings_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("page_number >= 1", name="ck_external_analysis_proposal_page"),
        sa.ForeignKeyConstraint(
            ["package_id"], ["external_analysis_packages.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["digital_object_id"], ["digital_objects.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "package_id",
            "external_proposal_id",
            name="uq_external_analysis_proposal_external_id",
        ),
        sa.UniqueConstraint(
            "package_id", "result_id", name="uq_external_analysis_proposal_result_id"
        ),
    )
    op.create_index(
        "ix_external_analysis_proposals_package",
        "external_analysis_proposals",
        ["package_id", "created_at"],
    )
    op.create_index(
        "ix_external_analysis_proposals_target",
        "external_analysis_proposals",
        ["digital_object_id", "page_number", "output_schema_id"],
    )

    op.create_table(
        "external_analysis_reviews",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("proposal_id", sa.String(length=36), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("decision", sa.String(length=16), nullable=False),
        sa.Column("reviewed_output_json", sa.JSON(none_as_null=True), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("reviewed_by", sa.String(length=200), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_proposal_sha256", sa.String(length=64), nullable=False),
        sa.CheckConstraint("revision >= 1", name="ck_external_analysis_review_revision"),
        sa.CheckConstraint(
            "decision IN ('accepted', 'rejected')",
            name="ck_external_analysis_review_decision",
        ),
        sa.CheckConstraint(
            "(decision = 'accepted' AND reviewed_output_json IS NOT NULL) OR "
            "(decision = 'rejected' AND reviewed_output_json IS NULL)",
            name="ck_external_analysis_review_output",
        ),
        sa.ForeignKeyConstraint(
            ["proposal_id"], ["external_analysis_proposals.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("proposal_id", "revision", name="uq_external_analysis_review_revision"),
    )
    op.create_index(
        "ix_external_analysis_reviews_proposal",
        "external_analysis_reviews",
        ["proposal_id", "revision"],
    )
    op.create_index(
        "ix_external_analysis_reviews_decision",
        "external_analysis_reviews",
        ["decision", "reviewed_at"],
    )

    op.create_table(
        "external_analysis_selections",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=128), nullable=False),
        sa.Column("target_type", sa.String(length=32), nullable=False),
        sa.Column("target_id", sa.String(length=500), nullable=False),
        sa.Column("digital_object_id", sa.String(length=36), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("output_schema_id", sa.String(length=120), nullable=False),
        sa.Column("review_id", sa.String(length=36), nullable=True),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("supersedes_selection_id", sa.String(length=36), nullable=True),
        sa.Column("selected_by", sa.String(length=200), nullable=False),
        sa.Column("selected_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("page_number >= 1", name="ck_external_analysis_selection_page"),
        sa.CheckConstraint(
            "action IN ('set', 'clear')", name="ck_external_analysis_selection_action"
        ),
        sa.CheckConstraint(
            "(action = 'set' AND review_id IS NOT NULL) OR "
            "(action = 'clear' AND review_id IS NULL)",
            name="ck_external_analysis_selection_review",
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["digital_object_id"], ["digital_objects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["review_id"], ["external_analysis_reviews.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_selection_id"],
            ["external_analysis_selections.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_external_analysis_selections_target",
        "external_analysis_selections",
        ["project_id", "target_type", "target_id", "output_schema_id", "selected_at"],
    )
    op.create_index(
        "ix_external_analysis_selections_review",
        "external_analysis_selections",
        ["review_id"],
    )

    # Raw machine output and human decision history are never rewritten in place.
    for table in (
        "external_analysis_packages",
        "external_analysis_proposals",
        "external_analysis_reviews",
        "external_analysis_selections",
    ):
        op.execute(
            f"""
            CREATE TRIGGER trg_{table}_immutable_update
            BEFORE UPDATE ON {table}
            BEGIN
                SELECT RAISE(ABORT, '{table} is append-only');
            END
            """
        )


def downgrade() -> None:
    for table in (
        "external_analysis_selections",
        "external_analysis_reviews",
        "external_analysis_proposals",
        "external_analysis_packages",
    ):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_immutable_update")

    op.drop_index(
        "ix_external_analysis_selections_review", table_name="external_analysis_selections"
    )
    op.drop_index(
        "ix_external_analysis_selections_target", table_name="external_analysis_selections"
    )
    op.drop_table("external_analysis_selections")
    op.drop_index("ix_external_analysis_reviews_decision", table_name="external_analysis_reviews")
    op.drop_index("ix_external_analysis_reviews_proposal", table_name="external_analysis_reviews")
    op.drop_table("external_analysis_reviews")
    op.drop_index("ix_external_analysis_proposals_target", table_name="external_analysis_proposals")
    op.drop_index(
        "ix_external_analysis_proposals_package", table_name="external_analysis_proposals"
    )
    op.drop_table("external_analysis_proposals")
    op.drop_index(
        "ix_external_analysis_package_sources_package",
        table_name="external_analysis_package_sources",
    )
    op.drop_table("external_analysis_package_sources")
    op.drop_index("ix_external_analysis_packages_exp01", table_name="external_analysis_packages")
    op.drop_index(
        "ix_external_analysis_packages_project_imported",
        table_name="external_analysis_packages",
    )
    op.drop_table("external_analysis_packages")
