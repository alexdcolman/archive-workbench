"""Extracciones OCR versionadas y objetos normalizados.

Revision ID: 0003_extraction_objects
Revises: 0002_preprocessing_derivatives
Create Date: 2026-07-23
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0003_extraction_objects"
down_revision = "0002_preprocessing_derivatives"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("extraction_runs") as batch:
        batch.add_column(sa.Column("preprocessing_run_id", sa.String(length=36), nullable=True))
        batch.add_column(sa.Column("profile_key", sa.String(length=100), nullable=True))
        batch.add_column(sa.Column("options_json", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("output_root", sa.Text(), nullable=True))
        batch.add_column(sa.Column("manifest_path", sa.Text(), nullable=True))
        batch.add_column(sa.Column("raw_pages_path", sa.Text(), nullable=True))
        batch.add_column(sa.Column("objects_path", sa.Text(), nullable=True))
        batch.add_column(sa.Column("paragraphs_path", sa.Text(), nullable=True))
        batch.add_column(sa.Column("images_path", sa.Text(), nullable=True))
        batch.add_column(sa.Column("created_by", sa.String(length=200), nullable=True))
        batch.add_column(
            sa.Column("total_pages", sa.Integer(), nullable=False, server_default="0")
        )
        batch.add_column(
            sa.Column("total_objects", sa.Integer(), nullable=False, server_default="0")
        )
        batch.add_column(
            sa.Column("total_paragraphs", sa.Integer(), nullable=False, server_default="0")
        )
        batch.add_column(
            sa.Column("total_characters", sa.Integer(), nullable=False, server_default="0")
        )
        batch.add_column(sa.Column("error_text", sa.Text(), nullable=True))
        batch.create_foreign_key(
            "fk_extraction_runs_preprocessing_run",
            "preprocessing_runs",
            ["preprocessing_run_id"],
            ["id"],
            ondelete="SET NULL",
        )

    op.create_index(
        "ix_extraction_runs_options",
        "extraction_runs",
        ["digital_object_id", "source_sha256", "options_hash"],
    )

    op.create_table(
        "extraction_pages",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("extraction_run_id", sa.String(length=36), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("source_asset_id", sa.String(length=36), nullable=True),
        sa.Column("raw_json_path", sa.Text(), nullable=True),
        sa.Column("object_count", sa.Integer(), nullable=False),
        sa.Column("character_count", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("warning_text", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["extraction_run_id"], ["extraction_runs.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["source_asset_id"], ["derivative_assets.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("extraction_run_id", "page_number", name="uq_extraction_page"),
    )
    op.create_index("ix_extraction_pages_run", "extraction_pages", ["extraction_run_id"])

    op.create_table(
        "extracted_objects",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("origin_id", sa.String(length=36), nullable=False),
        sa.Column("extraction_run_id", sa.String(length=36), nullable=False),
        sa.Column("digital_object_id", sa.String(length=36), nullable=False),
        sa.Column("parent_origin_id", sa.String(length=36), nullable=True),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("order_index", sa.Integer(), nullable=False),
        sa.Column("object_type", sa.String(length=100), nullable=False),
        sa.Column("original_text", sa.Text(), nullable=False),
        sa.Column("geometry_json", sa.JSON(), nullable=False),
        sa.Column("source_label", sa.String(length=100), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("language", sa.String(length=32), nullable=True),
        sa.Column("hidden_by_default", sa.Boolean(), nullable=False),
        sa.Column("attributes_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["digital_object_id"], ["digital_objects.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["extraction_run_id"], ["extraction_runs.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "extraction_run_id", "origin_id", name="uq_extracted_object_run_origin"
        ),
    )
    op.create_index(
        "ix_extracted_objects_run_order",
        "extracted_objects",
        ["extraction_run_id", "order_index"],
    )
    op.create_index(
        "ix_extracted_objects_page",
        "extracted_objects",
        ["extraction_run_id", "page_number"],
    )
    op.create_index("ix_extracted_objects_type", "extracted_objects", ["object_type"])


def downgrade() -> None:
    op.drop_index("ix_extracted_objects_type", table_name="extracted_objects")
    op.drop_index("ix_extracted_objects_page", table_name="extracted_objects")
    op.drop_index("ix_extracted_objects_run_order", table_name="extracted_objects")
    op.drop_table("extracted_objects")
    op.drop_index("ix_extraction_pages_run", table_name="extraction_pages")
    op.drop_table("extraction_pages")
    op.drop_index("ix_extraction_runs_options", table_name="extraction_runs")
    with op.batch_alter_table("extraction_runs") as batch:
        batch.drop_constraint("fk_extraction_runs_preprocessing_run", type_="foreignkey")
        for column in (
            "error_text",
            "total_characters",
            "total_paragraphs",
            "total_objects",
            "total_pages",
            "created_by",
            "images_path",
            "paragraphs_path",
            "objects_path",
            "raw_pages_path",
            "manifest_path",
            "output_root",
            "options_json",
            "profile_key",
            "preprocessing_run_id",
        ):
            batch.drop_column(column)
