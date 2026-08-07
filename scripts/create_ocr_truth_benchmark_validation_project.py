#!/usr/bin/env python3
"""Crea un proyecto descartable para validar OCR-01F sin tocar project_data."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
import yaml

from archive_workbench.catalog import register_test_corpus
from archive_workbench.contracts.test_corpus import TestCorpus
from archive_workbench.db import (
    create_sqlite_engine,
    current_revision,
    database_path,
    session_scope,
    upgrade_database,
)
from archive_workbench.decisions import load_decisions
from archive_workbench.identity import sha256_file
from archive_workbench.preprocessing import prepare_derivatives
from archive_workbench.project_init import initialize_project
from archive_workbench.version import __version__


GROUND_TRUTH = """ARCHIVO DE PRUEBA OCR
Delegación regional de documentación
Expediente número 1427
Fecha: 18 de septiembre de 1976
Se remite el presente informe para su archivo.
La segunda línea conserva acentos: investigación, sección y número.
"""


def _font(size: int) -> ImageFont.ImageFont:
    candidates = (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    )
    for candidate in candidates:
        path = Path(candidate)
        if path.is_file():
            return ImageFont.truetype(str(path), size=size)
    return ImageFont.load_default()


def _page() -> Image.Image:
    image = Image.new("RGB", (1400, 1800), "white")
    draw = ImageDraw.Draw(image)
    title = _font(44)
    body = _font(34)
    draw.text((110, 110), "ARCHIVO DE PRUEBA OCR", font=title, fill="black")
    y = 230
    for line in GROUND_TRUTH.splitlines()[1:]:
        draw.text((110, y), line, font=body, fill="black")
        y += 78
    draw.rectangle((90, 80, 1310, 760), outline="black", width=2)
    return image


def _write_tiff(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _page().save(path, format="TIFF", dpi=(300, 300), compression="tiff_deflate")


def _corpus() -> TestCorpus:
    return TestCorpus.model_validate(
        {
            "corpus_name": "Validación OCR-01F",
            "created_by": "validation_script",
            "created_at": datetime.now(timezone.utc),
            "documents": [
                {
                    "test_id": "ocr_truth_controlado",
                    "local_path": "corpus/ocr_truth/control.tiff",
                    "short_description": "Página controlada para benchmark OCR",
                    "archival_location": {
                        "fondo": "Validación OCR-01F",
                        "caja": "Benchmark",
                        "documento": "Página controlada para benchmark OCR",
                    },
                    "input_characteristics": {
                        "format": "tiff",
                        "scanned": True,
                        "digital_text_layer": False,
                        "multipage_tiff": False,
                        "poor_contrast": False,
                        "skewed_pages": False,
                        "landscape_pages": False,
                        "mixed_orientations": False,
                        "text_orientation": "upright",
                        "typewritten": True,
                        "handwritten_notes": False,
                        "stamps": False,
                        "tables_or_forms": False,
                        "multiple_internal_documents": False,
                    },
                    "expected_extraction": {
                        "minimum_page_coverage_percent": 95,
                        "known_difficulties": ["acentos y número de expediente"],
                    },
                }
            ],
        }
    )


def create_validation_project(destination: Path) -> dict[str, object]:
    destination = destination.expanduser().resolve()
    if destination.exists():
        raise SystemExit(
            f"El destino ya existe: {destination}. Elegí otra ruta; "
            "el script no elimina ni reemplaza proyectos."
        )

    repository_root = Path(__file__).resolve().parents[1]
    initialize_project(destination, template_root=repository_root / "config")

    decisions_path = destination / "config" / "decisions.yaml"
    decisions_payload = yaml.safe_load(decisions_path.read_text(encoding="utf-8"))
    decisions_payload["project_name"] = "Proyecto de validación OCR-01F"
    decisions_payload["project_id"] = "ocr01f_truth_benchmark_validation"
    decisions_payload["tiff"]["use_pyvips_when_available"] = False
    decisions_path.write_text(
        yaml.safe_dump(decisions_payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    original = destination / "corpus/ocr_truth/control.tiff"
    _write_tiff(original)
    original_sha256 = sha256_file(original)

    truth_path = destination / "ground_truth/ocr/ocr_truth_controlado/page_0001.txt"
    truth_path.parent.mkdir(parents=True, exist_ok=True)
    truth_path.write_text(GROUND_TRUTH, encoding="utf-8")
    truth_sha256 = sha256_file(truth_path)

    upgrade_database(destination)
    decisions = load_decisions(decisions_path)
    engine = create_sqlite_engine(database_path(destination))
    try:
        with session_scope(engine) as session:
            register_test_corpus(
                session,
                project_root=destination,
                decisions=decisions,
                corpus=_corpus(),
            )
        with session_scope(engine) as session:
            preparation = prepare_derivatives(
                session,
                project_root=destination,
                decisions=decisions,
            )
    finally:
        engine.dispose()

    result: dict[str, object] = {
        "version": __version__,
        "revision": current_revision(destination),
        "destination": str(destination),
        "source_key": "ocr_truth_controlado",
        "pages": 1,
        "prepared_runs": preparation.runs_created,
        "ground_truth_path": "ground_truth/ocr/ocr_truth_controlado/page_0001.txt",
        "ground_truth_sha256": truth_sha256,
        "expected_engines": ["tesseract", "docling", "surya"],
        "candidate_runs": 0,
        "canonical_selections": 0,
        "original_sha256": original_sha256,
        "originals_unchanged": True,
        "project_data_touched": False,
    }
    (destination / "validation_summary.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(create_validation_project(args.destination), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
