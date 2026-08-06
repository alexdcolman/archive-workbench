#!/usr/bin/env python3
"""Verifica la validación manual de OCR-01D con mensajes legibles."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import sqlite3

from sqlalchemy import func, select

from archive_workbench.db import create_sqlite_engine, database_path, session_scope
from archive_workbench.db.models import (
    ExtractedObject,
    ExtractionPageSelection,
    ExtractionRegion,
    ExtractionRun,
)


class Checks:
    def __init__(self) -> None:
        self.errors = 0

    def check(self, condition: bool, label: str, *, actual=None) -> None:
        if condition:
            print(f"  OK: {label}")
            return
        self.errors += 1
        suffix = "" if actual is None else f" · valor actual: {actual!r}"
        print(f"  ERROR: {label}{suffix}")


def verify(destination: Path) -> int:
    destination = destination.expanduser().resolve()
    db_path = database_path(destination)
    summary_path = destination / "validation_summary.json"
    checks = Checks()

    print("Verificación OCR-01D")
    print(f"Proyecto: {destination}")
    print(f"Base: {db_path}")

    connection = sqlite3.connect(db_path)
    try:
        quick_check = connection.execute("PRAGMA quick_check").fetchone()[0]
        revision = connection.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchone()[0]
    finally:
        connection.close()

    checks.check(quick_check == "ok", "PRAGMA quick_check: ok", actual=quick_check)
    checks.check(
        revision == "0044_layout_structure_review",
        "la revisión sigue en 0044_layout_structure_review (OCR-01D no migra la base)",
        actual=revision,
    )

    engine = create_sqlite_engine(db_path)
    try:
        with session_scope(engine) as session:
            run = session.scalar(
                select(ExtractionRun)
                .where(ExtractionRun.engine == "tesseract_regions")
                .order_by(ExtractionRun.created_at.desc())
            )
            regions = [] if run is None else list(
                session.scalars(
                    select(ExtractionRegion)
                    .where(ExtractionRegion.extraction_run_id == run.id)
                    .order_by(ExtractionRegion.reading_order)
                )
            )
            objects = [] if run is None else list(
                session.scalars(
                    select(ExtractedObject)
                    .where(ExtractedObject.extraction_run_id == run.id)
                    .order_by(ExtractedObject.order_index)
                )
            )
            canonical = session.scalar(select(func.count(ExtractionPageSelection.id))) or 0
    finally:
        engine.dispose()

    checks.check(run is not None, "existe una corrida regional candidata")
    if run is None:
        print("\nRESULTADO: no existe una candidata regional para verificar.")
        return 1

    checks.check(run.status in {"completed", "completed_with_warnings"}, "la corrida terminó", actual=run.status)
    checks.check(run.total_pages == 1, "la corrida contiene una página", actual=run.total_pages)
    checks.check(len(regions) == 6, "la candidata contiene seis zonas", actual=len(regions))

    roles = [(row.profile_json or {}).get("semantic_role") for row in regions]
    expected_roles = {
        "page_header", "body_text", "stamp", "signature", "page_number", "illustration"
    }
    checks.check(set(roles) == expected_roles, "las seis clasificaciones semánticas son correctas", actual=roles)

    mode_by_role = {
        (row.profile_json or {}).get("semantic_role"): row.mode for row in regions
    }
    checks.check(mode_by_role.get("page_header") == "ocr", "el encabezado usa OCR", actual=mode_by_role.get("page_header"))
    checks.check(mode_by_role.get("body_text") == "ocr", "el texto principal usa OCR", actual=mode_by_role.get("body_text"))
    checks.check(mode_by_role.get("page_number") == "ocr", "el número de página usa OCR", actual=mode_by_role.get("page_number"))
    for role in ("stamp", "signature", "illustration"):
        checks.check(mode_by_role.get(role) == "manual", f"{role} se conserva como zona manual", actual=mode_by_role.get(role))

    missing_crops = [row.crop_path for row in regions if not (destination / row.crop_path).is_file()]
    checks.check(not missing_crops, "existen los seis recortes", actual=missing_crops)
    checks.check(len(objects) >= 6, "la corrida generó al menos un objeto por zona", actual=len(objects))
    checks.check(canonical == 0, "la selección canónica permanece vacía", actual=canonical)

    manifest_path = destination / (run.manifest_path or "")
    regions_path = destination / (run.regions_path or "")
    checks.check(manifest_path.is_file(), "existe manifest.json", actual=str(manifest_path))
    checks.check(regions_path.is_file(), "existe regions.jsonl", actual=str(regions_path))

    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        checks.check(manifest.get("template", {}).get("schema_version") == "1.1", "el manifiesto conserva el contrato regional 1.1")
        checks.check(len(manifest.get("template", {}).get("regions", [])) == 6, "el manifiesto conserva las seis zonas")

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    original_path = destination / "corpus" / "regional" / "ficha_regional.pdf"
    digest = sha256(original_path.read_bytes()).hexdigest()
    checks.check(digest == summary["original_sha256"], "el PDF original conserva su SHA-256")
    checks.check(summary.get("project_data_touched") is False, "project_data_touched: false")

    if checks.errors:
        print(f"\nRESULTADO: {checks.errors} control(es) no coinciden. No avances con project_data.")
        return 1
    print("\nRESULTADO: validación OCR-01D completa y consistente.")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    raise SystemExit(verify(args.destination))


if __name__ == "__main__":
    main()
