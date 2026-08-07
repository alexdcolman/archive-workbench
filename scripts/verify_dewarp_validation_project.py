#!/usr/bin/env python3
"""Verifica la validación manual de OCR-01E con mensajes legibles."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3

from sqlalchemy import func, select

from archive_workbench.db import create_sqlite_engine, database_path, session_scope
from archive_workbench.db.models import (
    DerivativeAsset,
    ExtractionPageSelection,
    PreprocessingRun,
    SourceRegistration,
    DigitalObject,
)
from archive_workbench.identity import sha256_file


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
    summary = json.loads(
        (destination / "validation_summary.json").read_text(encoding="utf-8")
    )
    checks = Checks()

    print("Verificación OCR-01E")
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
        "la revisión sigue en 0044_layout_structure_review (OCR-01E no migra la base)",
        actual=revision,
    )

    engine = create_sqlite_engine(db_path)
    try:
        with session_scope(engine) as session:
            rows = session.execute(
                select(SourceRegistration.source_key, DigitalObject.id)
                .join(DigitalObject, DigitalObject.id == SourceRegistration.digital_object_id)
                .order_by(SourceRegistration.source_key)
            ).all()
            diagnostics: dict[str, dict[str, object]] = {}
            for source_key, digital_object_id in rows:
                run = session.scalar(
                    select(PreprocessingRun)
                    .where(
                        PreprocessingRun.digital_object_id == digital_object_id,
                        PreprocessingRun.is_current.is_(True),
                    )
                    .order_by(PreprocessingRun.created_at.desc())
                )
                if run is None:
                    diagnostics[str(source_key)] = {"run": None}
                    continue
                assets = list(
                    session.scalars(
                        select(DerivativeAsset).where(
                            DerivativeAsset.preprocessing_run_id == run.id
                        )
                    )
                )
                by_kind = {asset.kind: asset for asset in assets}
                ocr = by_kind.get("ocr")
                diagnostics[str(source_key)] = {
                    "run": run,
                    "assets": by_kind,
                    "analysis": dict(ocr.analysis_json or {}) if ocr else {},
                    "transformations": (
                        dict(ocr.transformations_json or {}) if ocr else {}
                    ),
                }
            canonical = session.scalar(
                select(func.count(ExtractionPageSelection.id))
            ) or 0
    finally:
        engine.dispose()

    checks.check(
        set(diagnostics) == {"curved", "flat"},
        "existen los dos documentos controlados",
        actual=list(diagnostics),
    )
    for key in ("curved", "flat"):
        checks.check(
            diagnostics.get(key, {}).get("run") is not None,
            f"{key} tiene una preparación vigente",
        )

    if any(diagnostics.get(key, {}).get("run") is None for key in ("curved", "flat")):
        print("\nRESULTADO: faltan preparaciones. No avances con project_data.")
        return 1

    curved = diagnostics["curved"]
    flat = diagnostics["flat"]
    curved_run = curved["run"]
    flat_run = flat["run"]
    checks.check(
        curved_run.status in {"completed", "completed_with_warnings"},
        "la preparación curva terminó",
        actual=curved_run.status,
    )
    checks.check(
        flat_run.status in {"completed", "completed_with_warnings"},
        "la preparación plana terminó",
        actual=flat_run.status,
    )
    checks.check(
        curved_run.options_json.get("geometry_mode") == "conservative_dewarp",
        "la página curva usó el modo dewarp conservador",
        actual=curved_run.options_json.get("geometry_mode"),
    )
    checks.check(
        flat_run.options_json.get("geometry_mode") == "conservative_dewarp",
        "la página plana usó el modo dewarp conservador",
        actual=flat_run.options_json.get("geometry_mode"),
    )

    curved_analysis = curved["analysis"]
    flat_analysis = flat["analysis"]
    checks.check(
        curved_analysis.get("dewarp_detected") is True,
        "la curvatura controlada fue detectada",
        actual=curved_analysis.get("dewarp_detected"),
    )
    checks.check(
        curved_analysis.get("dewarp_applied") is True,
        "el dewarp se aplicó a la página curva",
        actual=curved_analysis.get("dewarp_applied"),
    )
    checks.check(
        float(curved_analysis.get("dewarp_confidence") or 0.0) >= 0.45,
        "la página curva supera el umbral de confianza",
        actual=curved_analysis.get("dewarp_confidence"),
    )
    displacement = float(
        curved_analysis.get("dewarp_max_displacement_px") or 0.0
    )
    checks.check(
        8.0 <= displacement <= 30.0,
        "el desplazamiento de la página curva está dentro del rango controlado",
        actual=curved_analysis.get("dewarp_max_displacement_px"),
    )
    checks.check(
        flat_analysis.get("dewarp_detected") is False,
        "la página plana no produce un candidato de curvatura",
        actual=flat_analysis.get("dewarp_detected"),
    )
    checks.check(
        flat_analysis.get("dewarp_applied") is False,
        "la página plana conserva su geometría",
        actual=flat_analysis.get("dewarp_applied"),
    )

    expected_kinds = {"ocr", "preview", "diagnostic_mask", "dewarp_diagnostic"}
    for key, data in diagnostics.items():
        assets = data.get("assets", {})
        checks.check(
            set(assets) == expected_kinds,
            f"{key} conserva cuatro derivados trazables",
            actual=sorted(assets),
        )
        missing = [
            kind
            for kind, asset in assets.items()
            if not (destination / asset.relative_path).is_file()
        ]
        checks.check(not missing, f"los derivados de {key} existen", actual=missing)

    for key, digest in summary["original_sha256"].items():
        source_path = destination / "corpus" / "dewarp" / f"{key}.tiff"
        checks.check(
            sha256_file(source_path) == digest,
            f"el original {key}.tiff conserva su SHA-256",
        )

    checks.check(canonical == 0, "la selección canónica permanece vacía", actual=canonical)
    checks.check(summary.get("project_data_touched") is False, "project_data_touched: false")

    if checks.errors:
        print(
            f"\nRESULTADO: {checks.errors} control(es) no coinciden. "
            "No avances con project_data."
        )
        return 1
    print("\nRESULTADO: validación OCR-01E completa y consistente.")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    raise SystemExit(verify(args.destination))


if __name__ == "__main__":
    main()
