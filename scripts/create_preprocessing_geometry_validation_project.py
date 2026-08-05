#!/usr/bin/env python3
"""Crea una base descartable para validar OCR-01A sin tocar project_data."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from sqlalchemy import select
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
from archive_workbench.db.models import (
    DerivativeAsset,
    DigitalObject,
    PreprocessingRun,
    SourceRegistration,
)
from archive_workbench.decisions import load_decisions
from archive_workbench.identity import sha256_file
from archive_workbench.preprocessing import (
    prepare_derivatives,
    profile_for_preprocessing,
)
from archive_workbench.project_init import initialize_project
from archive_workbench.version import __version__


def _font(size: int) -> ImageFont.ImageFont:
    for candidate in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    ):
        if Path(candidate).is_file():
            return ImageFont.truetype(candidate, size=size)
    return ImageFont.load_default()


def _text_page(title: str, *, frame: bool = False) -> Image.Image:
    image = Image.new("RGB", (900, 1200), "white")
    draw = ImageDraw.Draw(image)
    title_font = _font(30)
    body_font = _font(22)
    draw.text((65, 35), title, fill="black", font=title_font)
    for row in range(12):
        y = 105 + row * 65
        draw.text(
            (70, y),
            f"Línea controlada {row + 1:02d}: archivo, documento y procedencia.",
            fill="black",
            font=body_font,
        )
    if frame:
        draw.rectangle((20, 20, 880, 1180), outline="black", width=3)
    return image


def _crossing_line_page() -> Image.Image:
    image = _text_page("Línea que cruza texto: debe conservarse")
    draw = ImageDraw.Draw(image)
    # Cruza la segunda línea de texto y debe ser rechazada por la regla conservadora.
    draw.line((25, 183, 875, 183), fill="black", width=2)
    return image


def _low_confidence_page() -> Image.Image:
    image = Image.new("RGB", (900, 1200), "white")
    draw = ImageDraw.Draw(image)
    draw.text(
        (365, 575),
        "muestra mínima",
        fill=(150, 150, 150),
        font=_font(16),
    )
    return image


def _write_tiff(path: Path, image: Image.Image) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, format="TIFF", dpi=(300, 300), compression="tiff_deflate")


def _document(test_id: str, title: str, *, skewed: bool = False, forms: bool = False) -> dict:
    return {
        "test_id": test_id,
        "local_path": f"corpus/geometria/{test_id}.tiff",
        "short_description": title,
        "archival_location": {
            "fondo": "Validación OCR-01A",
            "caja": "Geometría",
            "documento": title,
        },
        "input_characteristics": {
            "format": "tiff",
            "scanned": True,
            "digital_text_layer": False,
            "multipage_tiff": False,
            "poor_contrast": test_id == "baja_confianza",
            "skewed_pages": skewed,
            "landscape_pages": test_id == "orientacion_90",
            "mixed_orientations": test_id == "orientacion_90",
            "text_orientation": "rotated" if test_id == "orientacion_90" else "upright",
            "typewritten": True,
            "handwritten_notes": False,
            "stamps": False,
            "tables_or_forms": forms,
            "multiple_internal_documents": False,
        },
        "expected_extraction": {"minimum_page_coverage_percent": 95},
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
    decisions_payload = yaml.safe_load(decisions_path.read_text(encoding="utf-8"))
    decisions_payload["project_name"] = "Proyecto de validación OCR-01A"
    decisions_payload["project_id"] = "ocr01a_geometry_validation"
    decisions_payload["tiff"]["use_pyvips_when_available"] = False
    decisions_path.write_text(
        yaml.safe_dump(decisions_payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    pages = {
        "orientacion_90": _text_page("Orientación 90°", frame=True).rotate(
            -90, expand=True, fillcolor="white"
        ),
        "deskew_3": _text_page("Deskew 3°").rotate(3, expand=True, fillcolor="white"),
        "marcos_lineas": _text_page("Marcos y líneas largas", frame=True),
        "linea_cruza_texto": _crossing_line_page(),
        "baja_confianza": _low_confidence_page(),
    }
    originals: dict[str, str] = {}
    for key, image in pages.items():
        path = destination / "corpus" / "geometria" / f"{key}.tiff"
        _write_tiff(path, image)
        originals[key] = sha256_file(path)

    corpus = TestCorpus.model_validate(
        {
            "corpus_name": "Validación OCR-01A",
            "created_by": "validation_script",
            "created_at": datetime.now(timezone.utc),
            "documents": [
                _document("orientacion_90", "Página rotada 90°", skewed=False),
                _document("deskew_3", "Página inclinada 3°", skewed=True),
                _document("marcos_lineas", "Página con marco", forms=True),
                _document("linea_cruza_texto", "Línea que cruza texto", forms=True),
                _document("baja_confianza", "Página de baja confianza"),
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
        profile = profile_for_preprocessing(decisions, "original", "conservative")
        with session_scope(engine) as session:
            preparation = prepare_derivatives(
                session,
                project_root=destination,
                decisions=decisions,
                profile=profile,
            )
        with session_scope(engine) as session:
            rows = session.execute(
                select(SourceRegistration.source_key, DigitalObject.id)
                .join(DigitalObject, DigitalObject.id == SourceRegistration.digital_object_id)
            ).all()
            diagnostics: dict[str, dict[str, object]] = {}
            for source_key, digital_object_id in rows:
                run = session.scalar(
                    select(PreprocessingRun).where(
                        PreprocessingRun.digital_object_id == digital_object_id,
                        PreprocessingRun.is_current.is_(True),
                    )
                )
                assert run is not None
                assets = list(
                    session.scalars(
                        select(DerivativeAsset).where(
                            DerivativeAsset.preprocessing_run_id == run.id
                        )
                    )
                )
                by_kind = {asset.kind: asset for asset in assets}
                ocr = by_kind["ocr"]
                mask = by_kind["diagnostic_mask"]
                diagnostics[str(source_key)] = {
                    "rotation_applied": ocr.rotation_applied,
                    "analysis": dict(ocr.analysis_json or {}),
                    "transformations": dict(ocr.transformations_json or {}),
                    "ocr_path": ocr.relative_path,
                    "mask_path": mask.relative_path,
                    "manifest_path": run.manifest_path,
                }
    finally:
        engine.dispose()

    assert preparation.failed == 0
    assert preparation.runs_created == 5
    assert preparation.assets_created == 15
    assert diagnostics["orientacion_90"]["rotation_applied"] == 90
    assert abs(float(diagnostics["deskew_3"]["analysis"]["deskew_angle"]) + 3.0) <= 0.5
    assert int(diagnostics["marcos_lineas"]["analysis"]["lines_removed"]) >= 4
    assert int(diagnostics["linea_cruza_texto"]["analysis"]["lines_removed"]) == 0
    assert diagnostics["baja_confianza"]["rotation_applied"] == 0
    assert diagnostics["baja_confianza"]["transformations"]["orientation"]["applied"] is False
    assert diagnostics["baja_confianza"]["transformations"]["deskew"]["applied"] is False
    assert float(diagnostics["baja_confianza"]["analysis"]["deskew_angle"]) == 0.0
    assert all(
        sha256_file(destination / "corpus" / "geometria" / f"{key}.tiff") == digest
        for key, digest in originals.items()
    )
    assert all(
        (destination / str(data["ocr_path"])).is_file()
        and (destination / str(data["mask_path"])).is_file()
        and (destination / str(data["manifest_path"])).is_file()
        for data in diagnostics.values()
    )

    result: dict[str, object] = {
        "version": __version__,
        "revision": current_revision(destination),
        "destination": str(destination),
        "documents": len(diagnostics),
        "runs_created": preparation.runs_created,
        "assets_created": preparation.assets_created,
        "orientation_rotation": diagnostics["orientacion_90"]["rotation_applied"],
        "deskew_angle": diagnostics["deskew_3"]["analysis"]["deskew_angle"],
        "frame_lines_removed": diagnostics["marcos_lineas"]["analysis"]["lines_removed"],
        "crossing_line_removed": diagnostics["linea_cruza_texto"]["analysis"]["lines_removed"],
        "low_confidence_rotation": diagnostics["baja_confianza"]["rotation_applied"],
        "originals_unchanged": True,
        "project_data_touched": False,
        "diagnostics": diagnostics,
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
