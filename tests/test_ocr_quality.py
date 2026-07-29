from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import fitz
import pytest
from sqlalchemy import select

from archive_workbench.catalog import register_test_corpus
from archive_workbench.contracts.extraction import ExtractionProfile, OcrBenchmarkProfile
from archive_workbench.contracts.test_corpus import TestCorpus as CorpusDefinition
from archive_workbench.db import create_sqlite_engine, database_path, session_scope, upgrade_database
from archive_workbench.db.models import ExtractedObject, ExtractionRun
from archive_workbench.decisions import load_decisions
from archive_workbench.extraction import (
    extract_documents,
    extraction_status_rows,
    review_current_extraction,
    restore_profile_page_selections,
)
from archive_workbench.ocr_benchmark import run_ocr_benchmark
from archive_workbench.preprocessing import prepare_derivatives
from archive_workbench.tesseract_engine import (
    TesseractLine,
    TesseractPageResult,
    parse_tesseract_tsv,
)


def _write_pdf(path: Path, page_count: int = 1) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    document = fitz.open()
    for page_number in range(1, page_count + 1):
        page = document.new_page(width=600, height=400)
        page.insert_text((60, 80), f"DIARIO JORNADA {page_number}")
    document.save(path)
    document.close()


def _corpus() -> CorpusDefinition:
    return CorpusDefinition.model_validate(
        {
            "corpus_name": "Prueba OCR",
            "created_by": "tests",
            "created_at": datetime.now(timezone.utc),
            "documents": [
                {
                    "test_id": "recorte",
                    "local_path": "corpus/caja/recorte.pdf",
                    "short_description": "Recorte",
                    "archival_location": {
                        "fondo": "SiCH",
                        "caja": "Caja 1",
                        "documento": "Recorte",
                    },
                    "input_characteristics": {
                        "format": "pdf",
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
            ],
        }
    )


def _result(image_path: Path, psm: int = 3, variant: str = "original") -> TesseractPageResult:
    return TesseractPageResult(
        page_number=1,
        width=600,
        height=400,
        psm=psm,
        image_variant=variant,
        lines=[
            TesseractLine(
                block_num=1,
                paragraph_num=1,
                line_num=1,
                text="DIARIO JORNADA",
                left=60,
                top=40,
                right=300,
                bottom=80,
                confidence=91.0,
                word_count=2,
            ),
            TesseractLine(
                block_num=1,
                paragraph_num=1,
                line_num=2,
                text=f"Texto reconocido PSM {psm}",
                left=60,
                top=90,
                right=500,
                bottom=130,
                confidence=85.0,
                word_count=4,
            ),
        ],
        full_text=f"DIARIO JORNADA\nTexto reconocido PSM {psm}",
        tsv_text="level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n",
        command=["tesseract", str(image_path), "stdout"],
        stderr="",
    )


def _prepare_project(root: Path):
    _write_pdf(root / "corpus/caja/recorte.pdf")
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


def test_parse_tesseract_tsv_groups_words_into_lines() -> None:
    tsv = "\n".join(
        [
            "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext",
            "5\t1\t1\t1\t1\t1\t10\t20\t40\t10\t90\tDIARIO",
            "5\t1\t1\t1\t1\t2\t60\t20\t60\t10\t80\tJORNADA",
            "5\t1\t1\t1\t2\t1\t10\t40\t50\t10\t70\tTrelew",
        ]
    )
    lines = parse_tesseract_tsv(tsv)
    assert [line.text for line in lines] == ["DIARIO JORNADA", "Trelew"]
    assert lines[0].confidence == 85
    assert (lines[0].left, lines[0].right) == (10, 120)


def test_direct_tesseract_extraction_and_quality_review(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "project"
    engine, decisions = _prepare_project(root)

    def fake_run(image_path: Path, **kwargs):
        return _result(image_path, kwargs["psm"], kwargs["image_variant"])

    monkeypatch.setattr("archive_workbench.extraction.run_tesseract_page", fake_run)
    monkeypatch.setattr("archive_workbench.extraction._tesseract_version", lambda _cmd: "5.test")
    profile = ExtractionProfile(
        profile_key="tesseract_test",
        backend="tesseract_tsv",
        psm=3,
        image_variant="original",
        minimum_characters_per_page_warning=5,
    )
    try:
        with session_scope(engine) as session:
            summary = extract_documents(
                session,
                project_root=root,
                decisions=decisions,
                profile=profile,
                created_by="Alex",
            )
        with session_scope(engine) as session:
            reviewed = review_current_extraction(
                session,
                source_key="recorte",
                verdict="accepted",
                reviewed_by="Alex",
                note="Salida legible",
            )
        with session_scope(engine) as session:
            run = session.scalar(select(ExtractionRun))
            objects = session.scalars(select(ExtractedObject)).all()
            status = extraction_status_rows(session)
    finally:
        engine.dispose()

    assert summary.runs_created == 1
    assert summary.objects_created == 2
    assert run is not None
    assert run.engine == "tesseract_tsv"
    assert run.quality_score is not None
    assert reviewed.quality_status == "accepted"
    assert status[0].quality_status == "accepted"
    assert [item.original_text for item in objects] == [
        "DIARIO JORNADA",
        "Texto reconocido PSM 3",
    ]
    assert (root / run.raw_pages_path / "page_0001.tsv").is_file()
    assert (root / run.raw_pages_path / "page_0001.txt").is_file()


def test_ocr_benchmark_writes_ranked_candidates(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "project"
    engine, _decisions = _prepare_project(root)

    def fake_run(image_path: Path, **kwargs):
        result = _result(image_path, kwargs["psm"], kwargs["image_variant"])
        if kwargs["psm"] == 11:
            result.lines[1].confidence = 98.0
            result.full_text += "\nContenido adicional claramente reconocido"
            result.lines.append(
                TesseractLine(2, 1, 1, "Contenido adicional claramente reconocido", 60, 150, 520, 190, 98.0, 4)
            )
        return result

    monkeypatch.setattr("archive_workbench.ocr_benchmark.run_tesseract_page", fake_run)
    profile = OcrBenchmarkProfile(psm_modes=[3, 11], image_variants=["original", "otsu"])
    try:
        with session_scope(engine) as session:
            summary = run_ocr_benchmark(
                session,
                project_root=root,
                source_key="recorte",
                profile=profile,
                pages={1},
            )
    finally:
        engine.dispose()

    assert len(summary.candidates) == 4
    assert summary.candidates[0].psm == 11
    output = root / summary.output_root
    assert (output / "manifest.json").is_file()
    assert (output / "summary.md").is_file()
    assert "PSM 11" in (output / "summary.md").read_text(encoding="utf-8")


def test_benchmark_rejects_osd_psm_modes() -> None:
    import pytest

    with pytest.raises(ValueError, match="no admite PSM"):
        OcrBenchmarkProfile(psm_modes=[3, 12])


def test_tesseract_paragraph_granularity_groups_lines() -> None:
    from archive_workbench.tesseract_engine import normalize_tesseract_result

    result = TesseractPageResult(
        page_number=1,
        width=600,
        height=400,
        psm=3,
        image_variant="grayscale_autocontrast",
        lines=[
            TesseractLine(1, 1, 1, "Primera línea", 10, 20, 200, 40, 90.0, 2),
            TesseractLine(1, 1, 2, "segunda línea", 10, 45, 210, 65, 80.0, 2),
            TesseractLine(2, 1, 1, "Otra columna", 320, 20, 550, 40, 95.0, 2),
        ],
        full_text="Primera línea\nsegunda línea\nOtra columna",
        tsv_text="",
        command=["tesseract"],
        stderr="",
    )
    records = normalize_tesseract_result(
        result,
        digital_object_id="digital-1",
        extraction_run_id="run-1",
        granularity="paragraph",
    )
    assert len(records) == 2
    assert records[0].original_text == "Primera línea\nsegunda línea"
    assert records[0].attributes["line_count"] == 2
    assert records[1].original_text == "Otra columna"
    assert records[0].order_index == 0
    assert records[1].order_index == 1


def test_page_selection_policy_and_manual_replacement(tmp_path: Path, monkeypatch) -> None:
    from archive_workbench.db.models import ExtractionPageSelection
    from archive_workbench.extraction import select_extraction_pages

    root = tmp_path / "project"
    engine, decisions = _prepare_project(root)

    def fake_run(image_path: Path, **kwargs):
        return _result(image_path, kwargs["psm"], kwargs["image_variant"])

    monkeypatch.setattr("archive_workbench.extraction.run_tesseract_page", fake_run)
    monkeypatch.setattr("archive_workbench.extraction._tesseract_version", lambda _cmd: "5.test")
    profile_a = ExtractionProfile(
        profile_key="press_psm3",
        backend="tesseract_tsv",
        psm=3,
        image_variant="grayscale_autocontrast",
        object_granularity="paragraph",
    )
    profile_b = ExtractionProfile(
        profile_key="sparse_psm11",
        backend="tesseract_tsv",
        psm=11,
        image_variant="grayscale_autocontrast",
    )
    try:
        with session_scope(engine) as session:
            extract_documents(
                session,
                project_root=root,
                decisions=decisions,
                profile=profile_a,
                created_by="Alex",
                selection_policy="replace",
            )
        with session_scope(engine) as session:
            first = session.scalar(select(ExtractionPageSelection))
            assert first is not None
            first_run_id = first.extraction_run_id
        with session_scope(engine) as session:
            extract_documents(
                session,
                project_root=root,
                decisions=decisions,
                profile=profile_b,
                created_by="Alex",
                selection_policy="if_unselected",
            )
        with session_scope(engine) as session:
            unchanged = session.scalar(select(ExtractionPageSelection))
            assert unchanged is not None
            assert unchanged.extraction_run_id == first_run_id
            run, changed = select_extraction_pages(
                session,
                source_key="recorte",
                profile_key="sparse_psm11",
                selected_by="Alex",
                note="Prueba manual",
            )
            assert changed == 1
            assert run.profile_key == "sparse_psm11"
        with session_scope(engine) as session:
            selected = session.scalar(select(ExtractionPageSelection))
            assert selected is not None
            assert selected.extraction_run_id != first_run_id
            assert selected.selected_by == "Alex"
    finally:
        engine.dispose()


def test_spatial_reconstruction_option_is_rejected() -> None:
    """La estrategia retirada no puede volver a entrar silenciosamente en un perfil."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ExtractionProfile(
            profile_key="regression_guard",
            backend="tesseract_tsv",
            object_granularity="paragraph",
            paragraph_reconstruction="spatial_rows",  # type: ignore[call-arg]
        )


def test_restore_profile_pages_finds_separate_partial_runs(
    tmp_path: Path, monkeypatch
) -> None:
    from archive_workbench.db.models import ExtractionPageSelection

    root = tmp_path / "project"
    _write_pdf(root / "corpus/caja/recorte.pdf", page_count=2)
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
        prepare_derivatives(
            session,
            project_root=root,
            decisions=decisions,
        )

    def fake_run(image_path: Path, **kwargs):
        page_number = int(image_path.stem.rsplit("_", 1)[1])
        result = _result(image_path, kwargs["psm"], kwargs["image_variant"])
        result.page_number = page_number
        result.full_text = f"Página {page_number}"
        for line in result.lines:
            line.text = f"Página {page_number} {line.text}"
        return result

    monkeypatch.setattr("archive_workbench.extraction.run_tesseract_page", fake_run)
    monkeypatch.setattr("archive_workbench.extraction._tesseract_version", lambda _cmd: "5.test")

    profile_page_1 = ExtractionProfile(
        profile_key="stable_profile",
        backend="tesseract_tsv",
        psm=3,
    )
    profile_page_2 = ExtractionProfile(
        profile_key="stable_profile",
        backend="tesseract_tsv",
        psm=4,
    )
    try:
        with session_scope(engine) as session:
            extract_documents(
                session,
                project_root=root,
                decisions=decisions,
                profile=profile_page_1,
                selected_pages={1},
                created_by="Alex",
                selection_policy="replace",
            )
            extract_documents(
                session,
                project_root=root,
                decisions=decisions,
                profile=profile_page_2,
                selected_pages={2},
                created_by="Alex",
                selection_policy="replace",
            )
        with session_scope(engine) as session:
            restored = restore_profile_page_selections(
                session,
                source_key="recorte",
                profile_key="stable_profile",
                pages={1, 2},
                selected_by="Alex",
                note="rollback",
            )
            assert [page for page, _run in restored] == [1, 2]
            assert len({run for _page, run in restored}) == 2
        with session_scope(engine) as session:
            selections = session.scalars(
                select(ExtractionPageSelection).order_by(ExtractionPageSelection.page_number)
            ).all()
            assert [item.page_number for item in selections] == [1, 2]
            assert len({item.extraction_run_id for item in selections}) == 2
    finally:
        engine.dispose()
