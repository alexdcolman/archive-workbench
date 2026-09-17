"""Integrate reviewed external analysis with project continuity.

Revision ID: 0050_external_analysis_continuity
Revises: 0049_external_analysis_layer
Create Date: 2026-09-16
"""

from __future__ import annotations

from alembic import op

revision = "0050_external_analysis_continuity"
down_revision = "0049_external_analysis_layer"
branch_labels = None
depends_on = None


def _uuid_sql() -> str:
    return (
        "lower(hex(randomblob(4))) || '-' || lower(hex(randomblob(2))) || '-' || "
        "lower(hex(randomblob(2))) || '-' || lower(hex(randomblob(2))) || '-' || "
        "lower(hex(randomblob(6)))"
    )


def _pair(expr: str, *, json_value: bool = False) -> str:
    value = f"json({expr})" if json_value else expr
    return f"json_array(NULL, {value})"


def _json_object(fields: list[tuple[str, str, bool]]) -> str:
    parts: list[str] = []
    for name, expr, json_value in fields:
        parts.extend((f"'{name}'", _pair(expr, json_value=json_value)))
    return "json_object(" + ", ".join(parts) + ")"


def _event_insert_sql(
    *,
    entity_type: str,
    source_table: str,
    project_expr: str,
    actor_expr: str,
    timestamp_expr: str,
    changed_fields: str,
) -> str:
    return f"""
        INSERT INTO exchange_change_events (
            id, workspace_id, project_id, sequence_number, transaction_id,
            entity_type, entity_id, operation, base_revision, new_revision,
            changed_fields_json, actor, occurred_at
        )
        SELECT
            {_uuid_sql()}, w.id, {project_expr},
            COALESCE((SELECT MAX(e.sequence_number) FROM exchange_change_events e
                      WHERE e.workspace_id = w.id), 0) + 1,
            {_uuid_sql()}, '{entity_type}', NEW.id, 'create', NULL, NULL,
            {changed_fields}, {actor_expr}, {timestamp_expr}
        FROM exchange_workspaces w
        WHERE w.project_id = {project_expr}
        ORDER BY w.created_at, w.id
        LIMIT 1;
    """


def _package_fields(prefix: str = "NEW") -> str:
    return _json_object(
        [
            ("project_id", f"{prefix}.project_id", False),
            ("package_sha256", f"{prefix}.package_sha256", False),
            ("package_type", f"{prefix}.package_type", False),
            ("schema_version", f"{prefix}.schema_version", False),
            ("protocol", f"{prefix}.protocol", False),
            ("producer_id", f"{prefix}.producer_id", False),
            ("producer_version", f"{prefix}.producer_version", False),
            ("request_id", f"{prefix}.request_id", False),
            ("exp01_sha256", f"{prefix}.exp01_sha256", False),
            ("result_bundle_sha256", f"{prefix}.result_bundle_sha256", False),
            ("model_json", f"{prefix}.model_json", True),
            ("runtime_json", f"{prefix}.runtime_json", True),
            ("prompt_json", f"{prefix}.prompt_json", True),
            ("source_scope_json", f"{prefix}.source_scope_json", True),
            ("proposal_count", f"{prefix}.proposal_count", False),
            ("manifest_json", f"{prefix}.manifest_json", True),
            ("imported_by", f"{prefix}.imported_by", False),
            ("imported_at", f"{prefix}.imported_at", False),
        ]
    )


def _proposal_fields(prefix: str = "NEW") -> str:
    package_sha = (
        f"(SELECT p.package_sha256 FROM external_analysis_packages p "
        f"WHERE p.id = {prefix}.package_id)"
    )
    return _json_object(
        [
            ("package_id", f"{prefix}.package_id", False),
            ("package_sha256", package_sha, False),
            ("external_proposal_id", f"{prefix}.external_proposal_id", False),
            ("result_id", f"{prefix}.result_id", False),
            ("output_schema_id", f"{prefix}.output_schema_id", False),
            ("target_type", f"{prefix}.target_type", False),
            ("target_id", f"{prefix}.target_id", False),
            ("digital_object_id", f"{prefix}.digital_object_id", False),
            ("page_number", f"{prefix}.page_number", False),
            ("source_key", f"{prefix}.source_key", False),
            ("original_filename", f"{prefix}.original_filename", False),
            ("asset_path", f"{prefix}.asset_path", False),
            ("source_asset_sha256", f"{prefix}.source_asset_sha256", False),
            ("output_json", f"{prefix}.output_json", True),
            ("output_sha256", f"{prefix}.output_sha256", False),
            ("provenance_json", f"{prefix}.provenance_json", True),
            ("warnings_json", f"{prefix}.warnings_json", True),
            ("created_at", f"{prefix}.created_at", False),
        ]
    )


def _review_fields(prefix: str = "NEW") -> str:
    package_sha = (
        "(SELECT p.package_sha256 FROM external_analysis_packages p "
        "JOIN external_analysis_proposals q ON q.package_id = p.id "
        f"WHERE q.id = {prefix}.proposal_id)"
    )
    external_proposal_id = (
        f"(SELECT q.external_proposal_id FROM external_analysis_proposals q "
        f"WHERE q.id = {prefix}.proposal_id)"
    )
    result_id = (
        f"(SELECT q.result_id FROM external_analysis_proposals q WHERE q.id = {prefix}.proposal_id)"
    )
    return _json_object(
        [
            ("proposal_id", f"{prefix}.proposal_id", False),
            ("package_sha256", package_sha, False),
            ("external_proposal_id", external_proposal_id, False),
            ("result_id", result_id, False),
            ("revision", f"{prefix}.revision", False),
            ("decision", f"{prefix}.decision", False),
            ("reviewed_output_json", f"{prefix}.reviewed_output_json", True),
            ("review_note", f"{prefix}.review_note", False),
            ("reviewed_by", f"{prefix}.reviewed_by", False),
            ("reviewed_at", f"{prefix}.reviewed_at", False),
            ("source_proposal_sha256", f"{prefix}.source_proposal_sha256", False),
        ]
    )


def _selection_fields(prefix: str = "NEW") -> str:
    review_package_sha = (
        "(SELECT p.package_sha256 FROM external_analysis_packages p "
        "JOIN external_analysis_proposals q ON q.package_id = p.id "
        "JOIN external_analysis_reviews r ON r.proposal_id = q.id "
        f"WHERE r.id = {prefix}.review_id)"
    )
    review_external_proposal_id = (
        "(SELECT q.external_proposal_id FROM external_analysis_proposals q "
        "JOIN external_analysis_reviews r ON r.proposal_id = q.id "
        f"WHERE r.id = {prefix}.review_id)"
    )
    review_revision = (
        f"(SELECT r.revision FROM external_analysis_reviews r WHERE r.id = {prefix}.review_id)"
    )
    superseded_review_package_sha = (
        "(SELECT p.package_sha256 FROM external_analysis_selections s "
        "JOIN external_analysis_reviews r ON r.id = s.review_id "
        "JOIN external_analysis_proposals q ON q.id = r.proposal_id "
        "JOIN external_analysis_packages p ON p.id = q.package_id "
        f"WHERE s.id = {prefix}.supersedes_selection_id)"
    )
    superseded_review_external_proposal_id = (
        "(SELECT q.external_proposal_id FROM external_analysis_selections s "
        "JOIN external_analysis_reviews r ON r.id = s.review_id "
        "JOIN external_analysis_proposals q ON q.id = r.proposal_id "
        f"WHERE s.id = {prefix}.supersedes_selection_id)"
    )
    superseded_review_revision = (
        "(SELECT r.revision FROM external_analysis_selections s "
        "JOIN external_analysis_reviews r ON r.id = s.review_id "
        f"WHERE s.id = {prefix}.supersedes_selection_id)"
    )
    return _json_object(
        [
            ("project_id", f"{prefix}.project_id", False),
            ("target_type", f"{prefix}.target_type", False),
            ("target_id", f"{prefix}.target_id", False),
            ("digital_object_id", f"{prefix}.digital_object_id", False),
            ("page_number", f"{prefix}.page_number", False),
            ("output_schema_id", f"{prefix}.output_schema_id", False),
            ("review_id", f"{prefix}.review_id", False),
            ("review_package_sha256", review_package_sha, False),
            ("review_external_proposal_id", review_external_proposal_id, False),
            ("review_revision", review_revision, False),
            ("action", f"{prefix}.action", False),
            ("supersedes_selection_id", f"{prefix}.supersedes_selection_id", False),
            ("supersedes_review_package_sha256", superseded_review_package_sha, False),
            (
                "supersedes_review_external_proposal_id",
                superseded_review_external_proposal_id,
                False,
            ),
            ("supersedes_review_revision", superseded_review_revision, False),
            ("selected_by", f"{prefix}.selected_by", False),
            ("selected_at", f"{prefix}.selected_at", False),
        ]
    )


def _create_triggers() -> None:
    triggers = (
        (
            "external_analysis_package",
            "external_analysis_packages",
            "NEW.project_id",
            "NEW.imported_by",
            "NEW.imported_at",
            _package_fields(),
        ),
        (
            "external_analysis_proposal",
            "external_analysis_proposals",
            "(SELECT p.project_id FROM external_analysis_packages p WHERE p.id = NEW.package_id)",
            "(SELECT p.imported_by FROM external_analysis_packages p WHERE p.id = NEW.package_id)",
            "NEW.created_at",
            _proposal_fields(),
        ),
        (
            "external_analysis_review",
            "external_analysis_reviews",
            "(SELECT p.project_id FROM external_analysis_packages p "
            "JOIN external_analysis_proposals q ON q.package_id = p.id "
            "WHERE q.id = NEW.proposal_id)",
            "NEW.reviewed_by",
            "NEW.reviewed_at",
            _review_fields(),
        ),
        (
            "external_analysis_selection",
            "external_analysis_selections",
            "NEW.project_id",
            "NEW.selected_by",
            "NEW.selected_at",
            _selection_fields(),
        ),
    )
    for entity_type, table, project_expr, actor_expr, timestamp_expr, fields in triggers:
        op.execute(f"DROP TRIGGER IF EXISTS trg_exchange_{entity_type}_ai")
        op.execute(
            f"""
            CREATE TRIGGER trg_exchange_{entity_type}_ai
            AFTER INSERT ON {table}
            BEGIN
                {
                _event_insert_sql(
                    entity_type=entity_type,
                    source_table=table,
                    project_expr=project_expr,
                    actor_expr=actor_expr,
                    timestamp_expr=timestamp_expr,
                    changed_fields=fields,
                )
            }
            END
            """
        )


def _backfill_entity(
    *,
    entity_type: str,
    table: str,
    project_expr: str,
    actor_expr: str,
    timestamp_expr: str,
    fields: str,
    order_by: str,
) -> None:
    op.execute(
        f"""
        INSERT INTO exchange_change_events (
            id, workspace_id, project_id, sequence_number, transaction_id,
            entity_type, entity_id, operation, base_revision, new_revision,
            changed_fields_json, actor, occurred_at
        )
        SELECT
            {_uuid_sql()}, source.workspace_id, source.project_id,
            source.base_sequence + ROW_NUMBER() OVER (
                PARTITION BY source.workspace_id ORDER BY source.sort_timestamp, source.entity_id
            ),
            {_uuid_sql()}, '{entity_type}', source.entity_id, 'create', NULL, NULL,
            source.changed_fields_json, source.actor, source.sort_timestamp
        FROM (
            SELECT
                w.id AS workspace_id,
                {project_expr} AS project_id,
                row.id AS entity_id,
                {actor_expr} AS actor,
                {timestamp_expr} AS sort_timestamp,
                {fields} AS changed_fields_json,
                COALESCE((SELECT MAX(e.sequence_number) FROM exchange_change_events e
                          WHERE e.workspace_id = w.id), 0) AS base_sequence
            FROM {table} row
            JOIN exchange_workspaces w ON w.project_id = {project_expr}
            WHERE NOT EXISTS (
                SELECT 1 FROM exchange_change_events existing
                WHERE existing.workspace_id = w.id
                  AND existing.entity_type = '{entity_type}'
                  AND existing.entity_id = row.id
            )
            ORDER BY {order_by}
        ) AS source
        """
    )


def _backfill_existing_rows() -> None:
    _backfill_entity(
        entity_type="external_analysis_package",
        table="external_analysis_packages",
        project_expr="row.project_id",
        actor_expr="row.imported_by",
        timestamp_expr="row.imported_at",
        fields=_package_fields("row"),
        order_by="row.imported_at, row.id",
    )
    _backfill_entity(
        entity_type="external_analysis_proposal",
        table="external_analysis_proposals",
        project_expr="(SELECT p.project_id FROM external_analysis_packages p WHERE p.id = row.package_id)",
        actor_expr="(SELECT p.imported_by FROM external_analysis_packages p WHERE p.id = row.package_id)",
        timestamp_expr="row.created_at",
        fields=_proposal_fields("row"),
        order_by="row.created_at, row.id",
    )
    _backfill_entity(
        entity_type="external_analysis_review",
        table="external_analysis_reviews",
        project_expr="(SELECT p.project_id FROM external_analysis_packages p "
        "JOIN external_analysis_proposals q ON q.package_id = p.id WHERE q.id = row.proposal_id)",
        actor_expr="row.reviewed_by",
        timestamp_expr="row.reviewed_at",
        fields=_review_fields("row"),
        order_by="row.reviewed_at, row.id",
    )
    _backfill_entity(
        entity_type="external_analysis_selection",
        table="external_analysis_selections",
        project_expr="row.project_id",
        actor_expr="row.selected_by",
        timestamp_expr="row.selected_at",
        fields=_selection_fields("row"),
        order_by="row.selected_at, row.id",
    )


def upgrade() -> None:
    _create_triggers()
    _backfill_existing_rows()


def downgrade() -> None:
    for entity_type in (
        "external_analysis_selection",
        "external_analysis_review",
        "external_analysis_proposal",
        "external_analysis_package",
    ):
        op.execute(f"DROP TRIGGER IF EXISTS trg_exchange_{entity_type}_ai")
    # Los eventos históricos se conservan: un downgrade de esquema no debe reescribir
    # el registro de continuidad ya generado por la copia de trabajo.
