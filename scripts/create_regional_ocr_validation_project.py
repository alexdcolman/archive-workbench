#!/usr/bin/env python3
"""Crea una base descartable para validar OCR-01D sin tocar project_data."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

import fitz
from sqlalchemy import func, select
import yaml

from archive_workbench.catalog import register_test_corpus
from archive_workbench.contracts.regions import RegionTemplate
from archive_workbench.contracts.test_corpus import TestCorpus
from archive_workbench.db import (
    create_sqlite_engine,
    current_revision,
    database_path,
    session_scope,
    upgrade_database,
)
from archive_workbench.db.models import ExtractionPageSelection, ExtractionRun
from archive_workbench.decisions import load_decisions
from archive_workbench.identity import sha256_file
from archive_workbench.preprocessing import prepare_derivatives
from archive_workbench.project_init import initialize_project
from archive_workbench.regional_workflow import write_region_template
from archive_workbench.version import __version__


def _write_pdf(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    document = fitz.open()
    page = document.new_page(width=595, height=842)
    page.insert_text((52, 48), "ARCHIVO PROVINCIAL — FICHA REGIONAL", fontsize=14)
    page.draw_line((45, 62), (550, 62), color=(0.2, 0.2, 0.2), width=1)
    page.insert_text((55, 115), "Texto principal de validación para OCR regional.", fontsize=12)
    page.insert_text((55, 140), "La extracción debe limitarse a las zonas confirmadas.", fontsize=11)
    page.insert_text((55, 165), "Archivo, documento, procedencia y revisión humana.", fontsize=11)
    page.draw_circle((455, 215), 42, color=(0.45, 0.15, 0.15), width=2)
    page.insert_text((426, 215), "SELLO", fontsize=12, color=(0.45, 0.15, 0.15))
    page.draw_line((330, 320), (515, 320), color=(0.1, 0.1, 0.1), width=1)
    page.insert_text((360, 310), "Firma manuscrita", fontsize=12)
    # Ilustración que el usuario debe dibujar manualmente en la validación.
    page.draw_rect((60, 420, 260, 585), color=(0.1, 0.35, 0.75), fill=(0.92, 0.96, 1.0), width=2)
    page.draw_circle((160, 490), 45, color=(0.1, 0.35, 0.75), width=3)
    page.draw_line((95, 555), (225, 445), color=(0.1, 0.35, 0.75), width=3)
    page.insert_text((105, 575), "ILUSTRACIÓN", fontsize=13, color=(0.1, 0.35, 0.75))
    page.insert_text((520, 805), "17", fontsize=12)
    document.save(path)
    document.close()


def _corpus() -> TestCorpus:
    return TestCorpus.model_validate(
        {
            "corpus_name": "Validación OCR-01D",
            "created_by": "validation_script",
            "created_at": datetime.now(timezone.utc),
            "documents": [
                {
                    "test_id": "ficha_regional",
                    "local_path": "corpus/regional/ficha_regional.pdf",
                    "short_description": "Ficha controlada con texto, sello, firma, página e ilustración",
                    "archival_location": {
                        "fondo": "Validación OCR-01D",
                        "serie": "OCR regional",
                        "documento": "Ficha regional controlada",
                    },
                    "input_characteristics": {
                        "format": "pdf",
                        "scanned": True,
                        "digital_text_layer": False,
                        "multipage_tiff": False,
                        "poor_contrast": False,
                        "skewed_pages": False,
                        "landscape_pages": False,
                        "mixed_orientations": False,
                        "typewritten": True,
                        "handwritten_notes": True,
                        "stamps": True,
                        "tables_or_forms": True,
                        "multiple_internal_documents": False,
                    },
                    "expected_extraction": {"minimum_page_coverage_percent": 95},
                }
            ],
        }
    )


def _template() -> RegionTemplate:
    return RegionTemplate.model_validate(
        {
            "schema_version": "1.1",
            "template_key": "ocr01d_controlada",
            "profile_key": "regional_visual_v1",
            "source_key": "ficha_regional",
            "description": "Cinco zonas precargadas para validar el recorrido visual OCR-01D.",
            "regions": [
                {
                    "region_key": "encabezado",
                    "label": "Encabezado institucional",
                    "page": 1,
                    "reading_order": 10,
                    "bbox": {"x0": 0.07, "y0": 0.03, "x1": 0.93, "y1": 0.085},
                    "mode": "ocr",
                    "object_type": "page_header",
                    "semantic_role": "page_header",
                    "ocr": {"image_variant": "original", "psm": 7, "languages": ["spa"], "object_granularity": "paragraph", "minimum_characters_warning": 1},
                },
                {
                    "region_key": "texto_principal",
                    "label": "Texto principal",
                    "page": 1,
                    "reading_order": 20,
                    "bbox": {"x0": 0.075, "y0": 0.105, "x1": 0.91, "y1": 0.215},
                    "mode": "ocr",
                    "object_type": "paragraph",
                    "semantic_role": "body_text",
                    "ocr": {"image_variant": "original", "psm": 6, "languages": ["spa"], "object_granularity": "paragraph", "minimum_characters_warning": 1},
                },
                {
                    "region_key": "sello",
                    "label": "Sello circular",
                    "page": 1,
                    "reading_order": 30,
                    "bbox": {"x0": 0.68, "y0": 0.19, "x1": 0.84, "y1": 0.31},
                    "mode": "manual",
                    "object_type": "stamp",
                    "semantic_role": "stamp",
                    "initial_text": "",
                    "note": "Conservar el recorte para revisión humana.",
                },
                {
                    "region_key": "firma",
                    "label": "Firma manuscrita",
                    "page": 1,
                    "reading_order": 40,
                    "bbox": {"x0": 0.54, "y0": 0.34, "x1": 0.89, "y1": 0.40},
                    "mode": "manual",
                    "object_type": "handwritten_region",
                    "semantic_role": "signature",
                    "initial_text": "",
                    "note": "No inventar transcripción.",
                },
                {
                    "region_key": "numero_pagina",
                    "label": "Número de página",
                    "page": 1,
                    "reading_order": 60,
                    "bbox": {"x0": 0.86, "y0": 0.94, "x1": 0.95, "y1": 0.985},
                    "mode": "ocr",
                    "object_type": "page_footer",
                    "semantic_role": "page_number",
                    "ocr": {"image_variant": "original", "psm": 7, "languages": ["spa"], "object_granularity": "line", "minimum_characters_warning": 1},
                },
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
    payload = yaml.safe_load(decisions_path.read_text(encoding="utf-8"))
    payload["project_name"] = "Proyecto de validación OCR-01D"
    payload["project_id"] = "ocr01d_regional_validation"
    decisions_path.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    original_path = destination / "corpus" / "regional" / "ficha_regional.pdf"
    _write_pdf(original_path)
    original_sha256 = sha256_file(original_path)

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
        with session_scope(engine) as session:
            candidate_runs = session.scalar(select(func.count(ExtractionRun.id))) or 0
            canonical = session.scalar(select(func.count(ExtractionPageSelection.id))) or 0
    finally:
        engine.dispose()

    template_path = destination / "config" / "regions" / "ocr01d_controlada.yaml"
    write_region_template(template_path, _template())

    if preparation.failed:
        raise RuntimeError("La preparación de la ficha regional falló.")
    if sha256_file(original_path) != original_sha256:
        raise RuntimeError("El PDF original cambió durante la preparación.")

    result: dict[str, object] = {
        "version": __version__,
        "revision": current_revision(destination),
        "destination": str(destination),
        "source_key": "ficha_regional",
        "pages": 1,
        "template_regions": 5,
        "template_roles": [
            "page_header",
            "body_text",
            "stamp",
            "signature",
            "page_number",
        ],
        "manual_region_to_add": "illustration",
        "candidate_runs": candidate_runs,
        "canonical_selections": canonical,
        "original_sha256": original_sha256,
        "originals_unchanged": True,
        "project_data_touched": False,
    }
    (destination / "validation_summary.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--destination", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(create_validation_project(args.destination), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
