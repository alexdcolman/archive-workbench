#!/usr/bin/env python3
"""Crea una base descartable para validar OCR-01E sin tocar project_data."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from PIL import Image, ImageDraw
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
from archive_workbench.preprocessing_dewarp import estimate_vertical_dewarp, warp_vertical
from archive_workbench.project_init import initialize_project
from archive_workbench.version import __version__


def _flat_page() -> Image.Image:
    image = Image.new("RGB", (900, 1200), "white")
    draw = ImageDraw.Draw(image)
    draw.text((60, 28), "VALIDACIÓN OCR-01E: DEWARP CONSERVADOR", fill="black")
    for row in range(14):
        y = 80 + row * 68
        x = 60
        for word, width in enumerate((120, 85, 160, 95, 130)):
            draw.rectangle((x, y, x + width, y + 20), fill="black")
            for offset in range(12, width, 22):
                draw.rectangle((x + offset, y + 5, x + offset + 6, y + 20), fill="white")
            x += width + 24 + (word % 2) * 8
    draw.text((60, 1080), "La previsualización debe conservar esta geometría.", fill="black")
    return image


def _curved_page() -> Image.Image:
    return warp_vertical(
        _flat_page(),
        lambda x: -18.0 * ((2.0 * x - 1.0) ** 2),
    )


def _write_tiff(path: Path, image: Image.Image) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, format="TIFF", dpi=(300, 300), compression="tiff_deflate")


def _document(test_id: str, title: str, *, curved: bool) -> dict[str, object]:
    return {
        "test_id": test_id,
        "local_path": f"corpus/dewarp/{test_id}.tiff",
        "short_description": title,
        "archival_location": {
            "fondo": "Validación OCR-01E",
            "caja": "Dewarp",
            "documento": title,
        },
        "input_characteristics": {
            "format": "tiff",
            "scanned": True,
            "digital_text_layer": False,
            "multipage_tiff": False,
            "poor_contrast": False,
            "skewed_pages": curved,
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
            "known_difficulties": [
                "curvatura vertical sintética controlada"
            ] if curved else [],
        },
    }


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
    payload = yaml.safe_load(decisions_path.read_text(encoding="utf-8"))
    payload["project_name"] = "Proyecto de validación OCR-01E"
    payload["project_id"] = "ocr01e_dewarp_validation"
    payload["tiff"]["use_pyvips_when_available"] = False
    decisions_path.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    pages = {
        "curved": _curved_page(),
        "flat": _flat_page(),
    }
    originals: dict[str, str] = {}
    for key, image in pages.items():
        path = destination / "corpus" / "dewarp" / f"{key}.tiff"
        _write_tiff(path, image)
        originals[key] = sha256_file(path)

    corpus = TestCorpus.model_validate(
        {
            "corpus_name": "Validación OCR-01E",
            "created_by": "validation_script",
            "created_at": datetime.now(timezone.utc),
            "documents": [
                _document("curved", "Página curva controlada", curved=True),
                _document("flat", "Página plana controlada", curved=False),
            ],
        }
    )

    upgrade_database(destination)
    decisions = load_decisions(decisions_path)
    engine = create_sqlite_engine(database_path(destination))
    try:
        with session_scope(engine) as session:
            register_test_corpus(
                session,
                project_root=destination,
                decisions=decisions,
                corpus=corpus,
            )
    finally:
        engine.dispose()

    curved_estimate = estimate_vertical_dewarp(pages["curved"])
    flat_estimate = estimate_vertical_dewarp(pages["flat"])
    assert curved_estimate.applied is True
    assert flat_estimate.applied is False

    result: dict[str, object] = {
        "version": __version__,
        "revision": current_revision(destination),
        "destination": str(destination),
        "documents": 2,
        "candidate_runs": 0,
        "expected_curved_applied": True,
        "expected_flat_applied": False,
        "expected_curved_displacement_px": round(
            curved_estimate.max_displacement_px,
            3,
        ),
        "original_sha256": originals,
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
