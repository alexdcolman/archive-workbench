from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from PIL import Image, ImageDraw
from sqlalchemy import select

from archive_workbench.catalog import register_test_corpus
from archive_workbench.contracts.extraction import ExtractionProfile
from archive_workbench.contracts.ocr_truth import OcrTruthBenchmarkProfile
from archive_workbench.contracts.preprocessing import DerivativeProfile
from archive_workbench.contracts.test_corpus import TestCorpus as CorpusDefinition
from archive_workbench.db import (
    create_sqlite_engine,
    database_path,
    session_scope,
    upgrade_database,
)
from archive_workbench.db.models import ExtractionPageSelection
from archive_workbench.decisions import load_decisions
from archive_workbench.ocr_truth_benchmark import (
    benchmark_doctor,
    edit_distance,
    error_metrics,
    load_ocr_truth_benchmark_profile,
    normalize_ocr_text,
    run_ocr_truth_benchmark,
)
from archive_workbench.preprocessing import prepare_derivatives
from archive_workbench.tesseract_engine import TesseractLine, TesseractPageResult


GROUND_TRUTH = "ARCHIVO DE PRUEBA\nTexto controlado numero uno"


def _write_tiff(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (900, 500), "white")
    draw = ImageDraw.Draw(image)
    draw.text((60, 100), "ARCHIVO DE PRUEBA", fill="black")
    draw.text((60, 180), "Texto controlado numero uno", fill="black")
    image.save(path, format="TIFF", dpi=(300, 300))


def _corpus() -> CorpusDefinition:
    return CorpusDefinition.model_validate(
        {
            "corpus_name": "Benchmark OCR verdad terreno",
            "created_by": "tests",
            "created_at": datetime.now(timezone.utc),
            "documents": [
                {
                    "test_id": "benchmark_controlado",
                    "local_path": "corpus/benchmark/control.tiff",
                    "short_description": "Benchmark controlado",
                    "archival_location": {
                        "fondo": "Validación",
                        "caja": "OCR",
                        "documento": "Benchmark controlado",
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
                }
            ],
        }
    )


def _prepare_project(root: Path):
    _write_tiff(root / "corpus/benchmark/control.tiff")
    config_root = Path(__file__).parents[1] / "config"
    (root / "config").mkdir(parents=True, exist_ok=True)
    for name in (
        "decisions.yaml",
        "extraction_tesseract.yaml",
        "extraction_docling_es.yaml",
        "extraction_surya_es.yaml",
        "ocr_benchmark_truth.yaml",
    ):
        (root / "config" / name).write_text(
            (config_root / name).read_text(encoding="utf-8"), encoding="utf-8"
        )
    upgrade_database(root)
    decisions = load_decisions(root / "config/decisions.yaml")
    engine = create_sqlite_engine(database_path(root))
    with session_scope(engine) as session:
        register_test_corpus(
            session,
            project_root=root,
            decisions=decisions,
            corpus=_corpus(),
        )
    with session_scope(engine) as session:
        summary = prepare_derivatives(
            session,
            project_root=root,
            decisions=decisions,
            profile=DerivativeProfile(
                profile_key="ocr-truth-test",
                use_pyvips_when_available=False,
            ),
        )
        assert summary.failed == 0, summary.warnings
        assert summary.runs_created == 1
        assert summary.assets_created >= 2
    truth = root / "ground_truth/ocr/benchmark_controlado/page_0001.txt"
    truth.parent.mkdir(parents=True, exist_ok=True)
    truth.write_text(GROUND_TRUTH + "\n", encoding="utf-8")
    return engine


def _fake_doctor(_profile):
    return SimpleNamespace(ready=True, checks=[])


def _tesseract_result(image_path: Path, **kwargs) -> TesseractPageResult:
    return TesseractPageResult(
        page_number=kwargs["page_number"],
        width=900,
        height=500,
        psm=kwargs["psm"],
        image_variant=kwargs["image_variant"],
        lines=[
            TesseractLine(1, 1, 1, "ARCHIVO DE PRUEBA", 60, 100, 400, 130, 96.0, 3),
            TesseractLine(1, 1, 2, "Texto controlado numero uno", 60, 180, 500, 215, 94.0, 4),
        ],
        full_text=GROUND_TRUTH,
        tsv_text="header\n",
        command=["tesseract", str(image_path), "stdout"],
        stderr="",
    )


def _docling_runner(source_images, work_dir: Path, _profile: ExtractionProfile):
    work_dir.mkdir(parents=True)
    outputs = {}
    for page, _path in source_images:
        output = work_dir / f"page_{page:04d}.json"
        output.write_text(
            json.dumps(
                {
                    "texts": [
                        {"label": "text", "text": "ARCHIVO DE PRUEBA"},
                        {"label": "text", "text": "Texto controlado numero uno"},
                    ]
                }
            ),
            encoding="utf-8",
        )
        outputs[page] = output
    return outputs, "2.test", "docling fake"


def _surya_runner(source_images, work_dir: Path, _profile: ExtractionProfile):
    work_dir.mkdir(parents=True)
    outputs = {}
    for page, _path in source_images:
        output = work_dir / f"page_{page:04d}.json"
        output.write_text(
            json.dumps(
                {
                    "blocks": [
                        {
                            "label": "Text",
                            "raw_label": "Text",
                            "reading_order": 0,
                            "html": "<p>ARCHIVO DE PRUEBA</p>",
                            "bbox": [60, 100, 400, 130],
                            "polygon": [[60, 100], [400, 100], [400, 130], [60, 130]],
                            "confidence": 0.99,
                            "skipped": False,
                            "error": False,
                        },
                        {
                            "label": "Text",
                            "raw_label": "Text",
                            "reading_order": 1,
                            "html": "<p>Texto controlado numero uno</p>",
                            "bbox": [60, 180, 500, 215],
                            "polygon": [[60, 180], [500, 180], [500, 215], [60, 215]],
                            "confidence": 0.98,
                            "skipped": False,
                            "error": False,
                        },
                    ],
                    "image_bbox": [0, 0, 900, 500],
                }
            ),
            encoding="utf-8",
        )
        outputs[page] = output
    return outputs, "0.22.test", "surya fake"


def test_edit_distance_and_metrics_are_explicit() -> None:
    profile = OcrTruthBenchmarkProfile()
    assert edit_distance("gato", "pato") == 1
    assert edit_distance(["uno", "dos"], ["uno", "tres"]) == 1
    assert normalize_ocr_text("uno\n  dos", profile) == "uno dos"
    metrics = error_metrics("uno dos", "uno tres", profile)
    assert metrics["word_edit_distance"] == 1
    assert metrics["wer"] == 0.5
    assert metrics["cer"] > 0


def test_truth_profile_requires_unique_engines() -> None:
    import pytest

    with pytest.raises(ValueError, match="una sola vez"):
        OcrTruthBenchmarkProfile.model_validate(
            {
                "engines": [
                    {"engine_key": "tesseract", "profile_path": "a.yaml"},
                    {"engine_key": "tesseract", "profile_path": "b.yaml"},
                ]
            }
        )


def test_load_truth_profile_from_yaml(tmp_path: Path) -> None:
    path = tmp_path / "profile.yaml"
    path.write_text(
        "schema_version: '1.0'\n"
        "benchmark_key: test\n"
        "engines:\n"
        "  - engine_key: tesseract\n"
        "    profile_path: config/extraction_tesseract.yaml\n",
        encoding="utf-8",
    )
    profile = load_ocr_truth_benchmark_profile(path)
    assert profile.benchmark_key == "test"
    assert profile.engines[0].engine_key == "tesseract"


def test_truth_benchmark_runs_three_engines_without_selecting_pages(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "project"
    engine = _prepare_project(root)
    monkeypatch.setattr("archive_workbench.ocr_truth_benchmark.extraction_doctor", _fake_doctor)
    monkeypatch.setattr("archive_workbench.ocr_truth_benchmark._engine_version", lambda *_: "test")
    profile = load_ocr_truth_benchmark_profile(root / "config/ocr_benchmark_truth.yaml")
    try:
        with session_scope(engine) as session:
            summary = run_ocr_truth_benchmark(
                session,
                project_root=root,
                source_key="benchmark_controlado",
                profile=profile,
                pages={1},
                tesseract_runner=_tesseract_result,
                docling_runner=_docling_runner,
                surya_runner=_surya_runner,
            )
        with session_scope(engine) as session:
            selections = session.scalars(select(ExtractionPageSelection)).all()
    finally:
        engine.dispose()

    assert selections == []
    assert {item.engine_key for item in summary.candidates} == {
        "tesseract",
        "docling",
        "surya",
    }
    assert all(item.cer == 0 for item in summary.candidates)
    assert all(item.wer == 0 for item in summary.candidates)
    assert len(summary.aggregates) == 3
    output = root / summary.output_root
    assert (output / "manifest.json").is_file()
    assert (output / "summary.md").is_file()
    assert (output / "summary.csv").is_file()
    assert (output / "ground_truth/page_0001.txt").read_text(encoding="utf-8") == GROUND_TRUTH + "\n"
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["profile"]["benchmark_key"] == "ocr_truth_es_v1"
    assert len(manifest["candidates"]) == 3


def test_benchmark_doctor_checks_requested_engines(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path
    config = root / "config"
    config.mkdir()
    repo_config = Path(__file__).parents[1] / "config"
    for name in (
        "extraction_tesseract.yaml",
        "extraction_docling_es.yaml",
        "extraction_surya_es.yaml",
    ):
        (config / name).write_text((repo_config / name).read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr("archive_workbench.ocr_truth_benchmark.extraction_doctor", _fake_doctor)
    rows = benchmark_doctor(project_root=root, profile=OcrTruthBenchmarkProfile())
    assert [row.engine_key for row in rows] == ["tesseract", "docling", "surya"]
    assert all(row.ready for row in rows)


def test_truth_benchmark_preflights_all_engines_before_creating_output(
    tmp_path: Path, monkeypatch
) -> None:
    import pytest

    root = tmp_path / "project"
    engine = _prepare_project(root)

    def selective_doctor(profile):
        if profile.backend == "docling_cli":
            return SimpleNamespace(
                ready=False,
                checks=[
                    SimpleNamespace(
                        name="Docling CLI",
                        ok=False,
                        detail="no encontrado",
                        required=True,
                    )
                ],
            )
        return SimpleNamespace(ready=True, checks=[])

    monkeypatch.setattr(
        "archive_workbench.ocr_truth_benchmark.extraction_doctor",
        selective_doctor,
    )
    profile = load_ocr_truth_benchmark_profile(root / "config/ocr_benchmark_truth.yaml")
    try:
        with session_scope(engine) as session:
            with pytest.raises(RuntimeError, match="Motor docling no disponible"):
                run_ocr_truth_benchmark(
                    session,
                    project_root=root,
                    source_key="benchmark_controlado",
                    profile=profile,
                    pages={1},
                    tesseract_runner=_tesseract_result,
                    docling_runner=_docling_runner,
                    surya_runner=_surya_runner,
                )
    finally:
        engine.dispose()

    benchmark_root = root / "ocr_benchmarks"
    assert not list(benchmark_root.glob("*/truth_*"))
