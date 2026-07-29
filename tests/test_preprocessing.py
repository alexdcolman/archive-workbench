from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import fitz
from PIL import Image, ImageDraw
from sqlalchemy import select

from archive_workbench.catalog import register_test_corpus
from archive_workbench.contracts.test_corpus import TestCorpus as CorpusDefinition
from archive_workbench.db import (
    create_sqlite_engine,
    current_revision,
    database_path,
    session_scope,
    upgrade_database,
)
from archive_workbench.db.models import DerivativeAsset, PreprocessingRun
from archive_workbench.decisions import load_decisions
from archive_workbench.preprocessing import prepare_derivatives, preprocessing_status_rows


def _write_pdf(path: Path, pages: int = 2) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    document = fitz.open()
    for number in range(1, pages + 1):
        page = document.new_page(width=800, height=500)
        page.insert_text((60, 80), f"Página de prueba {number}")
    document.save(path)
    document.close()


def _write_tiff(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (1200, 600), "white")
    draw = ImageDraw.Draw(image)
    draw.text((50, 50), "Texto horizontal legible", fill="black")
    image.save(path, format="TIFF", dpi=(300, 300), compression="tiff_deflate")


def _corpus(documents: list[dict]) -> CorpusDefinition:
    return CorpusDefinition.model_validate(
        {
            "corpus_name": "Prueba de derivados",
            "created_by": "tests",
            "created_at": datetime.now(timezone.utc),
            "documents": documents,
        }
    )


def _document(test_id: str, local_path: str, fmt: str, title: str) -> dict:
    return {
        "test_id": test_id,
        "local_path": local_path,
        "short_description": title,
        "archival_location": {
            "fondo": "SiCH",
            "caja": "Caja 1",
            "documento": title,
        },
        "input_characteristics": {
            "format": fmt,
            "scanned": True,
            "digital_text_layer": False,
            "multipage_tiff": False,
            "poor_contrast": False,
            "skewed_pages": False,
            "landscape_pages": True,
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


def test_pdf_derivatives_are_created_and_reused(tmp_path: Path) -> None:
    root = tmp_path / "project"
    _write_pdf(root / "corpus/caja/a.pdf", pages=2)
    decisions = load_decisions(Path(__file__).parents[1] / "config/decisions.yaml")
    corpus = _corpus([_document("pdf_a", "corpus/caja/a.pdf", "pdf", "PDF A")])

    upgrade_database(root)
    assert current_revision(root) == "0028_operational_readiness"
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            register_test_corpus(
                session,
                project_root=root,
                decisions=decisions,
                corpus=corpus,
            )
        with session_scope(engine) as session:
            first = prepare_derivatives(
                session,
                project_root=root,
                decisions=decisions,
            )
        with session_scope(engine) as session:
            second = prepare_derivatives(
                session,
                project_root=root,
                decisions=decisions,
            )
        with session_scope(engine) as session:
            runs = session.scalars(select(PreprocessingRun)).all()
            assets = session.scalars(select(DerivativeAsset)).all()
    finally:
        engine.dispose()

    assert first.runs_created == 1
    assert first.assets_created == 4
    assert first.failed == 0
    assert second.runs_reused == 1
    assert len(runs) == 1
    assert len(assets) == 4
    assert sum(asset.kind == "ocr" for asset in assets) == 2
    assert sum(asset.kind == "preview" for asset in assets) == 2
    assert all((root / asset.relative_path).is_file() for asset in assets)
    assert (root / runs[0].manifest_path).is_file()


def test_tiff_derivatives_keep_native_orientation_and_resolution(tmp_path: Path) -> None:
    root = tmp_path / "project"
    _write_tiff(root / "corpus/legajo/a.tiff")
    decisions = load_decisions(Path(__file__).parents[1] / "config/decisions.yaml")
    decisions.tiff.use_pyvips_when_available = False
    corpus = _corpus([_document("tiff_a", "corpus/legajo/a.tiff", "tiff", "TIFF A")])

    upgrade_database(root)
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            register_test_corpus(
                session,
                project_root=root,
                decisions=decisions,
                corpus=corpus,
            )
        with session_scope(engine) as session:
            summary = prepare_derivatives(
                session,
                project_root=root,
                decisions=decisions,
            )
        with session_scope(engine) as session:
            assets = session.scalars(select(DerivativeAsset)).all()
            status = preprocessing_status_rows(session)
    finally:
        engine.dispose()

    assert summary.runs_created == 1
    assert summary.failed == 0
    assert len(assets) == 2
    ocr = next(asset for asset in assets if asset.kind == "ocr")
    preview = next(asset for asset in assets if asset.kind == "preview")
    assert (ocr.width, ocr.height) == (1200, 600)
    assert ocr.rotation_applied == 0
    assert preview.width > preview.height
    assert status[0].run_status == "completed"
    assert status[0].assets == 2


def test_modified_source_is_not_preprocessed_under_old_identity(tmp_path: Path) -> None:
    root = tmp_path / "project"
    source = root / "corpus/caja/a.pdf"
    _write_pdf(source, pages=1)
    decisions = load_decisions(Path(__file__).parents[1] / "config/decisions.yaml")
    corpus = _corpus([_document("pdf_a", "corpus/caja/a.pdf", "pdf", "PDF A")])

    upgrade_database(root)
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            register_test_corpus(
                session,
                project_root=root,
                decisions=decisions,
                corpus=corpus,
            )
        _write_pdf(source, pages=2)
        with session_scope(engine) as session:
            summary = prepare_derivatives(
                session,
                project_root=root,
                decisions=decisions,
            )
        with session_scope(engine) as session:
            runs = session.scalars(select(PreprocessingRun)).all()
    finally:
        engine.dispose()

    assert summary.failed == 1
    assert summary.runs_created == 0
    assert runs == []
    assert "cambió desde su registro" in summary.warnings[0]
