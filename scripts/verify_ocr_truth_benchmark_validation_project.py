#!/usr/bin/env python3
"""Verifica el benchmark real Tesseract/Docling/Surya de OCR-01F."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3

from sqlalchemy import func, select

from archive_workbench.db import create_sqlite_engine, database_path, session_scope
from archive_workbench.db.models import DigitalObject, ExtractionPageSelection, SourceRegistration
from archive_workbench.identity import sha256_file


def _check(ok: bool, label: str, errors: list[str], detail: str | None = None) -> None:
    if ok:
        print(f"  OK: {label}")
        return
    suffix = f" · valor actual: {detail}" if detail is not None else ""
    print(f"  ERROR: {label}{suffix}")
    errors.append(label)


def verify(destination: Path) -> int:
    destination = destination.expanduser().resolve()
    db_path = database_path(destination)
    summary_path = destination / "validation_summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    errors: list[str] = []

    print("Verificación OCR-01F")
    print(f"Proyecto: {destination}")
    print(f"Base: {db_path}")

    connection = sqlite3.connect(db_path)
    try:
        quick_check = connection.execute("PRAGMA quick_check").fetchone()[0]
        revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]
    finally:
        connection.close()
    _check(quick_check == "ok", "PRAGMA quick_check: ok", errors, str(quick_check))
    _check(
        revision == "0044_layout_structure_review",
        "la revisión sigue en 0044_layout_structure_review (OCR-01F no migra la base)",
        errors,
        str(revision),
    )

    engine = create_sqlite_engine(db_path)
    try:
        with session_scope(engine) as session:
            row = session.execute(
                select(SourceRegistration, DigitalObject)
                .join(DigitalObject, SourceRegistration.digital_object_id == DigitalObject.id)
                .where(SourceRegistration.source_key == summary["source_key"])
            ).one()
            _registration, digital = row
            selection_count = session.scalar(select(func.count()).select_from(ExtractionPageSelection)) or 0
    finally:
        engine.dispose()

    benchmark_root = destination / "ocr_benchmarks" / digital.id
    candidates = sorted(benchmark_root.glob("truth_*/manifest.json"))
    _check(len(candidates) == 1, "existe exactamente un benchmark con verdad terreno", errors, str(len(candidates)))
    if not candidates:
        print("\nRESULTADO: no existe un benchmark para verificar.")
        return 1

    manifest_path = candidates[-1]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    output_root = manifest_path.parent
    engines = [item["engine_key"] for item in manifest.get("aggregates", [])]
    _check(set(engines) == {"tesseract", "docling", "surya"}, "participaron Tesseract, Docling y Surya", errors, str(engines))
    _check(len(manifest.get("references", [])) == 1, "se registró una página de verdad terreno", errors)
    _check(len(manifest.get("candidates", [])) == 3, "se registró un resultado por motor", errors, str(len(manifest.get("candidates", []))))

    truth = destination / summary["ground_truth_path"]
    _check(sha256_file(truth) == summary["ground_truth_sha256"], "la verdad terreno conserva su SHA-256", errors)
    snapshot = output_root / "ground_truth/page_0001.txt"
    _check(snapshot.is_file(), "el benchmark conserva una copia de la verdad terreno usada", errors)
    if snapshot.is_file():
        _check(sha256_file(snapshot) == summary["ground_truth_sha256"], "la copia de verdad terreno coincide por SHA-256", errors)

    for item in manifest.get("candidates", []):
        engine_key = item["engine_key"]
        _check(float(item["cer"]) >= 0, f"{engine_key} registra CER", errors)
        _check(float(item["wer"]) >= 0, f"{engine_key} registra WER", errors)
        _check(float(item["elapsed_seconds"]) >= 0, f"{engine_key} registra tiempo", errors)
        _check((destination / item["text_path"]).is_file(), f"{engine_key} conserva el texto comparado", errors)
        for raw_path in item.get("raw_paths", []):
            _check((destination / raw_path).is_file(), f"{engine_key} conserva salida cruda", errors)

    _check((output_root / "summary.md").is_file(), "existe summary.md", errors)
    _check((output_root / "summary.csv").is_file(), "existe summary.csv", errors)
    _check((output_root / "summary.json").is_file(), "existe summary.json", errors)
    _check(selection_count == 0, "la selección canónica permanece vacía", errors, str(selection_count))

    original = destination / "corpus/ocr_truth/control.tiff"
    _check(sha256_file(original) == summary["original_sha256"], "el TIFF original conserva su SHA-256", errors)
    _check(summary.get("project_data_touched") is False, "project_data_touched: false", errors)

    print("\nResultado agregado real:")
    for item in sorted(manifest.get("aggregates", []), key=lambda row: (row["cer"], row["wer"])):
        print(
            f"  - {item['engine_key']}: CER {float(item['cer']):.4f} · "
            f"WER {float(item['wer']):.4f} · {float(item['elapsed_seconds']):.2f}s"
        )

    print("\nTexto de referencia:")
    print(truth.read_text(encoding="utf-8").strip())
    print("\nTextos producidos por los motores:")
    for item in sorted(manifest.get("candidates", []), key=lambda row: row["engine_key"]):
        text_path = destination / item["text_path"]
        version = item.get("engine_version") or "versión no informada"
        print(f"\n[{item['engine_key']}] {version}")
        if text_path.is_file():
            print(text_path.read_text(encoding="utf-8").strip())
        else:
            print("<texto no disponible>")

    if errors:
        print(f"\nRESULTADO: {len(errors)} control(es) no coinciden. No avances con project_data.")
        return 1
    print("\nRESULTADO: validación OCR-01F completa y consistente.")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    raise SystemExit(verify(args.destination))


if __name__ == "__main__":
    main()
