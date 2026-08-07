from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageDraw, ImageChops
from sqlalchemy import select

from archive_workbench.contracts.test_corpus import TestCorpus as CorpusDefinition
from archive_workbench.catalog import register_test_corpus
from archive_workbench.db import (
    create_sqlite_engine,
    database_path,
    session_scope,
    upgrade_database,
)
from archive_workbench.db.models import DerivativeAsset, PreprocessingRun
from archive_workbench.decisions import load_decisions
from archive_workbench.preprocessing import prepare_derivatives, profile_for_preprocessing
from archive_workbench.preprocessing_dewarp import (
    apply_estimated_dewarp,
    estimate_vertical_dewarp,
    warp_vertical,
)
from archive_workbench.processing import processing_geometry_rows


def _synthetic_page() -> Image.Image:
    image = Image.new("RGB", (900, 1200), "white")
    draw = ImageDraw.Draw(image)
    for row in range(14):
        y = 70 + row * 70
        x = 60
        for word, width in enumerate((120, 85, 160, 95, 130)):
            draw.rectangle((x, y, x + width, y + 20), fill="black")
            for offset in range(12, width, 22):
                draw.rectangle((x + offset, y + 5, x + offset + 6, y + 20), fill="white")
            x += width + 24 + (word % 2) * 8
    return image


def _curved_page() -> Image.Image:
    flat = _synthetic_page()
    return warp_vertical(flat, lambda x: -18.0 * ((2.0 * x - 1.0) ** 2))


def _row_alignment_energy(image: Image.Image) -> float:
    gray = image.convert("L")
    getter = getattr(gray, "get_flattened_data", None)
    values = list(getter()) if getter is not None else list(gray.getdata())
    width, height = gray.size
    rows = [sum(255 - values[y * width + x] for x in range(width)) for y in range(height)]
    total = sum(rows)
    return sum(value * value for value in rows) / (total * total + 1.0)


def _manifest() -> CorpusDefinition:
    return CorpusDefinition.model_validate(
        {
            "corpus_name": "Validación de dewarp conservador",
            "created_by": "validation_script",
            "created_at": datetime.now(timezone.utc),
            "documents": [
                {
                    "test_id": "curved",
                    "local_path": "corpus/dewarp/curved.tiff",
                    "short_description": "Página curva controlada",
                    "archival_location": {
                        "fondo": "Validación",
                        "caja": "OCR-01E",
                        "documento": "Curva",
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
                    "expected_extraction": {"minimum_page_coverage_percent": 95},
                },
                {
                    "test_id": "flat",
                    "local_path": "corpus/dewarp/flat.tiff",
                    "short_description": "Página plana controlada",
                    "archival_location": {
                        "fondo": "Validación",
                        "caja": "OCR-01E",
                        "documento": "Plana",
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
                    "expected_extraction": {"minimum_page_coverage_percent": 95},
                },
            ],
        }
    )


def test_dewarp_corrects_synthetic_curve_and_skips_flat_page() -> None:
    curved = _curved_page()
    estimate = estimate_vertical_dewarp(curved)
    corrected = apply_estimated_dewarp(curved, estimate)

    assert estimate.detected is True
    assert estimate.applied is True
    assert estimate.confidence >= 0.45
    assert 10.0 <= estimate.max_displacement_px <= 28.0
    assert estimate.support_strips >= 10
    assert estimate.fit_quality >= 0.7
    assert _row_alignment_energy(corrected) > _row_alignment_energy(curved) * 1.25

    flat = _synthetic_page()
    flat_estimate = estimate_vertical_dewarp(flat)
    assert flat_estimate.detected is False
    assert flat_estimate.applied is False
    assert ImageChops.difference(
        flat,
        apply_estimated_dewarp(flat, flat_estimate),
    ).getbbox() is None


def test_dewarp_is_traced_and_creates_separate_diagnostic(tmp_path: Path) -> None:
    root = tmp_path / "project"
    source_root = root / "corpus" / "dewarp"
    source_root.mkdir(parents=True)
    curved = _curved_page()
    flat = _synthetic_page()
    curved.save(source_root / "curved.tiff", format="TIFF", dpi=(300, 300))
    flat.save(source_root / "flat.tiff", format="TIFF", dpi=(300, 300))

    decisions = load_decisions(Path(__file__).parents[1] / "config" / "decisions.yaml")
    decisions.tiff.use_pyvips_when_available = False
    upgrade_database(root)
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            register_test_corpus(
                session,
                project_root=root,
                decisions=decisions,
                corpus=_manifest(),
            )
        profile = profile_for_preprocessing(
            decisions,
            "original",
            "conservative_dewarp",
        )
        with session_scope(engine) as session:
            summary = prepare_derivatives(
                session,
                project_root=root,
                decisions=decisions,
                profile=profile,
            )
        with session_scope(engine) as session:
            runs = list(session.scalars(select(PreprocessingRun)))
            assets = list(session.scalars(select(DerivativeAsset)))
            rows = processing_geometry_rows(session)
    finally:
        engine.dispose()

    assert summary.runs_created == 2
    assert summary.assets_created == 8
    assert len(runs) == 2
    assert all(run.options_json["geometry_mode"] == "conservative_dewarp" for run in runs)
    assert all(run.options_json["dewarp_min_confidence"] == 0.45 for run in runs)

    by_title = {row.title: row for row in rows}
    curved_row = by_title["Página curva controlada"]
    flat_row = by_title["Página plana controlada"]
    assert curved_row.dewarp_detected is True
    assert curved_row.dewarp_applied is True
    assert curved_row.dewarp_diagnostic_relative_path is not None
    assert flat_row.dewarp_detected is False
    assert flat_row.dewarp_applied is False
    assert flat_row.dewarp_diagnostic_relative_path is not None

    grouped: dict[str, set[str]] = {}
    for asset in assets:
        grouped.setdefault(asset.digital_object_id, set()).add(asset.kind)
        assert (root / asset.relative_path).is_file()
    assert all(
        kinds == {"ocr", "preview", "diagnostic_mask", "dewarp_diagnostic"}
        for kinds in grouped.values()
    )
    curved_ocr = next(
        asset
        for asset in assets
        if asset.kind == "ocr" and asset.analysis_json.get("dewarp_applied") is True
    )
    assert curved_ocr.analysis_json["algorithm_version"] == "geometry_conservative_v2"
    assert curved_ocr.transformations_json["dewarp"]["reason"] == "confidence_above_threshold"
