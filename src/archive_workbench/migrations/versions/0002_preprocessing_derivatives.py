"""Preprocesamiento y derivados por página.

Revision ID: 0002_preprocessing_derivatives
Revises: 0001_initial_catalog
Create Date: 2026-07-23
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0002_preprocessing_derivatives"
down_revision = "0001_initial_catalog"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "preprocessing_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("digital_object_id", sa.String(length=36), nullable=False),
        sa.Column("source_sha256", sa.String(length=64), nullable=False),
        sa.Column("profile_key", sa.String(length=100), nullable=False),
        sa.Column("options_json", sa.JSON(), nullable=False),
        sa.Column("options_hash", sa.String(length=64), nullable=False),
        sa.Column("backend", sa.String(length=100), nullable=False),
        sa.Column("backend_version", sa.String(length=100), nullable=True),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False),
        sa.Column("output_root", sa.Text(), nullable=False),
        sa.Column("manifest_path", sa.Text(), nullable=True),
        sa.Column("warnings_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["digital_object_id"], ["digital_objects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_preprocessing_runs_digital_object",
        "preprocessing_runs",
        ["digital_object_id"],
    )
    op.create_index(
        "ix_preprocessing_runs_current",
        "preprocessing_runs",
        ["digital_object_id", "is_current"],
    )
    op.create_index(
        "ix_preprocessing_runs_options",
        "preprocessing_runs",
        ["digital_object_id", "source_sha256", "options_hash"],
    )

    op.create_table(
        "derivative_assets",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("preprocessing_run_id", sa.String(length=36), nullable=False),
        sa.Column("digital_object_id", sa.String(length=36), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("relative_path", sa.Text(), nullable=False),
        sa.Column("mime_type", sa.String(length=100), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("dpi", sa.Integer(), nullable=True),
        sa.Column("source_width", sa.Float(), nullable=True),
        sa.Column("source_height", sa.Float(), nullable=True),
        sa.Column("source_dpi", sa.Float(), nullable=True),
        sa.Column("rotation_applied", sa.Integer(), nullable=False),
        sa.Column("backend", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["preprocessing_run_id"], ["preprocessing_runs.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["digital_object_id"], ["digital_objects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "preprocessing_run_id", "page_number", "kind", name="uq_derivative_asset_page_kind"
        ),
        sa.UniqueConstraint("relative_path", name="uq_derivative_asset_relative_path"),
    )
    op.create_index(
        "ix_derivative_assets_digital_object", "derivative_assets", ["digital_object_id"]
    )
    op.create_index("ix_derivative_assets_run", "derivative_assets", ["preprocessing_run_id"])
    op.create_index("ix_derivative_assets_kind", "derivative_assets", ["kind"])


def downgrade() -> None:
    op.drop_index("ix_derivative_assets_kind", table_name="derivative_assets")
    op.drop_index("ix_derivative_assets_run", table_name="derivative_assets")
    op.drop_index("ix_derivative_assets_digital_object", table_name="derivative_assets")
    op.drop_table("derivative_assets")
    op.drop_index("ix_preprocessing_runs_options", table_name="preprocessing_runs")
    op.drop_index("ix_preprocessing_runs_current", table_name="preprocessing_runs")
    op.drop_index("ix_preprocessing_runs_digital_object", table_name="preprocessing_runs")
    op.drop_table("preprocessing_runs")
