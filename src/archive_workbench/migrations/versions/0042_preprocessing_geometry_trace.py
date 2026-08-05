"""Trazabilidad estructurada del preprocesamiento geométrico por página.

Revision ID: 0042_preprocessing_geometry_trace
Revises: 0041_catalog_authority_roles_graph_layers
Create Date: 2026-08-05
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0042_preprocessing_geometry_trace"
down_revision = "0041_catalog_authority_roles_graph_layers"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Columnas aditivas: no se reconstruye la tabla poblada ni se alteran derivados previos.
    op.add_column(
        "derivative_assets",
        sa.Column(
            "analysis_json",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )
    op.add_column(
        "derivative_assets",
        sa.Column(
            "transformations_json",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )


def downgrade() -> None:
    op.drop_column("derivative_assets", "transformations_json")
    op.drop_column("derivative_assets", "analysis_json")
