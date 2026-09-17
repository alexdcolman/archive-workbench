from __future__ import annotations

import csv
import hashlib
import io
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from archive_workbench.db.models import utc_now
from archive_workbench.external_analysis import external_analysis_reviewed_export_rows

EXTERNAL_ANALYSIS_EXPORT_FORMATS = ("jsonl", "csv")
EXTERNAL_ANALYSIS_EXPORT_SCHEMA = "archive_workbench_reviewed_external_analysis/0.1"


@dataclass(frozen=True)
class ExternalAnalysisExportArtifact:
    output_format: str
    relative_path: str
    row_count: int
    byte_size: int
    sha256: str


def default_external_analysis_export_filename(
    output_format: str, *, now: datetime | None = None
) -> str:
    if output_format not in EXTERNAL_ANALYSIS_EXPORT_FORMATS:
        raise ValueError(f"Formato de exportación no soportado: {output_format}")
    timestamp = (now or utc_now()).strftime("%Y%m%dT%H%M%SZ")
    return f"exports/analisis_asistido_revisado_{timestamp}.{output_format}"


def _json_record(record: dict[str, Any], *, project_id: str) -> dict[str, Any]:
    return {
        "export_schema": EXTERNAL_ANALYSIS_EXPORT_SCHEMA,
        "project_id": project_id,
        **record,
    }


def _csv_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def _render_bytes(records: list[dict[str, Any]], *, project_id: str, output_format: str) -> bytes:
    normalized = [_json_record(record, project_id=project_id) for record in records]
    if output_format == "jsonl":
        text = "".join(
            json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n" for record in normalized
        )
        return text.encode("utf-8")
    if output_format != "csv":
        raise ValueError(f"Formato de exportación no soportado: {output_format}")

    fields = [
        "export_schema",
        "project_id",
        "selection_id",
        "selected_by",
        "selected_at",
        "review_id",
        "proposal_id",
        "external_proposal_id",
        "target_id",
        "digital_object_id",
        "page_number",
        "source_key",
        "navigation_source_key",
        "original_filename",
        "output_schema_id",
        "model_id",
        "producer_id",
        "producer_version",
        "review_revision",
        "reviewed_by",
        "reviewed_at",
        "review_note",
        "warnings",
        "description",
        "document_features",
        "visible_text_notes",
        "uncertainties",
        "reviewed_output_json",
    ]
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    for record in normalized:
        output = (
            record.get("reviewed_output") if isinstance(record.get("reviewed_output"), dict) else {}
        )
        row = {key: _csv_value(value) for key, value in record.items() if key != "reviewed_output"}
        row.update(
            {
                "description": _csv_value(output.get("description")),
                "document_features": _csv_value(output.get("document_features")),
                "visible_text_notes": _csv_value(output.get("visible_text_notes")),
                "uncertainties": _csv_value(output.get("uncertainties")),
                "reviewed_output_json": _csv_value(output),
            }
        )
        writer.writerow(row)
    return buffer.getvalue().encode("utf-8")


def export_reviewed_external_analysis(
    session: Session,
    *,
    project_root: str | Path,
    project_id: str,
    output_format: str,
) -> ExternalAnalysisExportArtifact:
    records = external_analysis_reviewed_export_rows(session, project_id=project_id)
    relative_path = default_external_analysis_export_filename(output_format)
    root = Path(project_root)
    output_path = root / relative_path
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = _render_bytes(records, project_id=project_id, output_format=output_format)
    temporary = output_path.with_name(f".{output_path.name}.tmp")
    temporary.write_bytes(payload)
    temporary.replace(output_path)
    return ExternalAnalysisExportArtifact(
        output_format=output_format,
        relative_path=relative_path,
        row_count=len(records),
        byte_size=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
    )
