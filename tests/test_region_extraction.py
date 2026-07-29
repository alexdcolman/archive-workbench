from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import fitz
from sqlalchemy import select

from archive_workbench.catalog import register_test_corpus
from archive_workbench.contracts.regions import RegionTemplate
from archive_workbench.contracts.test_corpus import TestCorpus as CorpusDefinition
from archive_workbench.db import create_sqlite_engine, database_path, session_scope, upgrade_database
from archive_workbench.db.models import (
    ExtractedObject,
    ExtractionPageSelection,
    ExtractionRegion,
    ExtractionRun,
)
from archive_workbench.decisions import load_decisions
from archive_workbench.preprocessing import prepare_derivatives
from archive_workbench.region_extraction import (
    extract_regions,
    region_status_rows,
    render_region_template,
    validate_region_template,
)
from archive_workbench.tesseract_engine import TesseractLine, TesseractPageResult


def _write_pdf(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    document = fitz.open()
    page = document.new_page(width=600, height=800)
    page.insert_text((80, 100), "FORMULARIO DE PRUEBA")
    page.insert_text((80, 320), "Mensaje mecanografiado de prueba")
    page.insert_text((80, 700), "Pie del formulario")
    document.save(path)
    document.close()


def _corpus() -> CorpusDefinition:
    return CorpusDefinition.model_validate(
        {
            "corpus_name": "Prueba regional",
            "created_by": "tests",
            "created_at": datetime.now(timezone.utc),
            "documents": [
                {
                    "test_id": "ficha",
                    "local_path": "corpus/caja/ficha.pdf",
                    "short_description": "Ficha",
                    "archival_location": {
                        "fondo": "SiCH",
                        "caja": "Caja 1",
                        "documento": "Ficha",
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
                        "text_orientation": "upright",
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
            "template_key": "form_test_v1",
            "profile_key": "tesseract_form_test_v1",
            "source_key": "ficha",
            "regions": [
                {
                    "region_key": "typed_body",
                    "label": "Texto mecanografiado",
                    "page": 1,
                    "reading_order": 10,
                    "bbox": {"x0": 0.1, "y0": 0.2, "x1": 0.9, "y1": 0.6},
                    "mode": "ocr",
                    "object_type": "paragraph",
                    "ocr": {
                        "image_variant": "grayscale_autocontrast",
                        "psm": 6,
                        "languages": ["spa"],
                        "object_granularity": "paragraph",
                    },
                },
                {
                    "region_key": "stamp",
                    "label": "Sello",
                    "page": 1,
                    "reading_order": 20,
                    "bbox": {"x0": 0.15, "y0": 0.6, "x1": 0.45, "y1": 0.8},
                    "mode": "manual",
                    "object_type": "stamp",
                },
            ],
        }
    )


def _prepare(root: Path):
    _write_pdf(root / "corpus/caja/ficha.pdf")
    decisions = load_decisions(Path(__file__).parents[1] / "config/decisions.yaml")
    upgrade_database(root)
    engine = create_sqlite_engine(database_path(root))
    with session_scope(engine) as session:
        register_test_corpus(
            session,
            project_root=root,
            decisions=decisions,
            corpus=_corpus(),
        )
    with session_scope(engine) as session:
        prepare_derivatives(session, project_root=root, decisions=decisions)
    return engine, decisions


def _fake_tesseract(image_path: Path, **kwargs) -> TesseractPageResult:
    from PIL import Image

    with Image.open(image_path) as image:
        width, height = image.size
    line = TesseractLine(
        block_num=1,
        paragraph_num=1,
        line_num=1,
        text="Mensaje mecanografiado reconocido",
        left=5,
        top=5,
        right=max(6, width - 5),
        bottom=min(height, 35),
        confidence=92.0,
        word_count=3,
    )
    return TesseractPageResult(
        page_number=kwargs["page_number"],
        width=width,
        height=height,
        psm=kwargs["psm"],
        image_variant=kwargs["image_variant"],
        lines=[line],
        full_text=line.text,
        tsv_text="level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n",
        command=["tesseract", str(image_path), "stdout"],
        stderr="",
    )


def test_region_template_validation_rejects_unknown_object_type() -> None:
    import pytest

    decisions = load_decisions(Path(__file__).parents[1] / "config/decisions.yaml")
    template = _template().model_copy(deep=True)
    template.regions[0].object_type = "not_defined"
    with pytest.raises(ValueError, match="not_defined"):
        validate_region_template(template, decisions)


def test_render_and_extract_regions(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "project"
    engine, decisions = _prepare(root)
    template = _template()
    monkeypatch.setattr(
        "archive_workbench.region_extraction._tesseract_version", lambda _cmd: "5.test"
    )
    try:
        with session_scope(engine) as session:
            previews = render_region_template(
                session, project_root=root, template=template
            )
        with session_scope(engine) as session:
            summary = extract_regions(
                session,
                project_root=root,
                decisions=decisions,
                template=template,
                created_by="Alex",
                runner=_fake_tesseract,
            )
        with session_scope(engine) as session:
            runs = session.scalars(select(ExtractionRun)).all()
            regions = session.scalars(select(ExtractionRegion)).all()
            objects = session.scalars(
                select(ExtractedObject).order_by(ExtractedObject.order_index)
            ).all()
            selections = session.scalars(select(ExtractionPageSelection)).all()
            status = region_status_rows(session, source_key="ficha")
    finally:
        engine.dispose()

    assert len(previews) == 1
    assert (root / previews[0].path).is_file()
    assert summary.runs_created == 1
    assert summary.pages_processed == 1
    assert len(runs) == 1
    assert runs[0].engine == "tesseract_regions"
    assert runs[0].regions_path is not None
    assert (root / runs[0].regions_path).is_file()
    assert len(regions) == 2
    assert len(objects) == 2
    assert objects[0].original_text == "Mensaje mecanografiado reconocido"
    assert objects[0].object_type == "paragraph"
    assert objects[1].object_type == "stamp"
    assert objects[1].original_text == ""
    assert objects[1].attributes_json["manual_transcription_required"] is True
    assert len(selections) == 1
    assert len(status) == 2
    assert any(row.mode == "manual" and row.warning for row in status)


def test_region_extraction_reuses_equivalent_run(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "project"
    engine, decisions = _prepare(root)
    template = _template()
    monkeypatch.setattr(
        "archive_workbench.region_extraction._tesseract_version", lambda _cmd: "5.test"
    )
    try:
        with session_scope(engine) as session:
            first = extract_regions(
                session,
                project_root=root,
                decisions=decisions,
                template=template,
                runner=_fake_tesseract,
            )
        with session_scope(engine) as session:
            second = extract_regions(
                session,
                project_root=root,
                decisions=decisions,
                template=template,
                runner=_fake_tesseract,
            )
        with session_scope(engine) as session:
            count = len(session.scalars(select(ExtractionRun)).all())
    finally:
        engine.dispose()

    assert first.runs_created == 1
    assert second.runs_reused == 1
    assert count == 1
