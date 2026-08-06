from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import fitz
from sqlalchemy import inspect, select

from archive_workbench.catalog import register_test_corpus
from archive_workbench.contracts.test_corpus import TestCorpus as CorpusDefinition
from archive_workbench.db import (
    create_sqlite_engine,
    current_revision,
    database_path,
    session_scope,
    upgrade_database,
)
from archive_workbench.db.models import (
    DigitalObject,
    EditablePage,
    ExtractedObject,
    ExtractionPage,
    ExtractionRun,
    SourceRegistration,
)
from archive_workbench.decisions import load_decisions
from archive_workbench.editing import bootstrap_editable_layer
from archive_workbench.extraction import select_extraction_pages
from archive_workbench.identity import new_id
from archive_workbench.preprocessing import prepare_derivatives
from archive_workbench.processing import (
    create_processing_job,
    failed_extraction_pages,
    finish_processing_job,
    processing_inventory_rows,
    processing_job_item_rows,
    processing_job_rows,
    start_processing_job,
    update_processing_job_item,
)


def _write_pdf(path: Path, pages: int = 1) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = fitz.open()
    for number in range(1, pages + 1):
        page = doc.new_page(width=600, height=400)
        page.insert_text((50, 80), f"Documento página {number}")
    doc.save(path)
    doc.close()


def _corpus(*, pages: int = 1) -> CorpusDefinition:
    return CorpusDefinition.model_validate(
        {
            "corpus_name": "Procesamiento",
            "created_by": "tests",
            "created_at": datetime.now(timezone.utc),
            "documents": [
                {
                    "test_id": "doc_processing",
                    "local_path": "corpus/doc.pdf",
                    "short_description": "Documento de procesamiento",
                    "archival_location": {
                        "fondo": "Fondo de prueba",
                        "legajo": "Legajo 1",
                        "documento": "Documento de procesamiento",
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


def _seed_completed_extraction(session, *, pages: int = 1) -> ExtractionRun:
    registration = session.scalar(
        select(SourceRegistration).where(SourceRegistration.source_key == "doc_processing")
    )
    assert registration and registration.digital_object_id
    digital = session.get(DigitalObject, registration.digital_object_id)
    assert digital
    run = ExtractionRun(
        id=new_id(),
        digital_object_id=digital.id,
        profile_key="test_profile",
        engine="tesseract_tsv",
        engine_version="5",
        source_sha256=digital.sha256,
        options_json={"selected_pages": list(range(1, pages + 1))},
        options_hash="a" * 64,
        status="completed",
        is_current=True,
        created_by="tests",
        total_pages=pages,
        total_objects=pages,
        total_paragraphs=pages,
        total_characters=20 * pages,
        warnings_json=[],
        quality_status="needs_review",
    )
    session.add(run)
    session.flush()
    for page_number in range(1, pages + 1):
        page = ExtractionPage(
            id=new_id(),
            extraction_run_id=run.id,
            page_number=page_number,
            object_count=1,
            character_count=20,
            status="completed",
        )
        session.add(page)
        session.flush()
        session.add(
            ExtractedObject(
                id=new_id(),
                origin_id=new_id(),
                extraction_run_id=run.id,
                digital_object_id=digital.id,
                page_number=page_number,
                order_index=page_number - 1,
                object_type="paragraph",
                original_text=f"Texto OCR página {page_number}",
                geometry_json=[],
                attributes_json={},
            )
        )
    session.flush()
    return run


def test_processing_inventory_follows_manual_canonical_flow(tmp_path: Path) -> None:
    root = tmp_path / "project"
    _write_pdf(root / "corpus/doc.pdf")
    decisions = load_decisions(Path(__file__).parents[1] / "config/decisions.yaml")
    upgrade_database(root)
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            register_test_corpus(
                session,
                project_root=root,
                decisions=decisions,
                corpus=_corpus(),
            )
        with session_scope(engine) as session:
            initial = processing_inventory_rows(
                session, project_root=root, project_id=decisions.project_id
            )[0]
        assert initial.status in {"pending_preparation", "file_available"}

        with session_scope(engine) as session:
            prepared = prepare_derivatives(
                session, project_root=root, decisions=decisions
            )
        assert prepared.runs_created == 1
        with session_scope(engine) as session:
            row = processing_inventory_rows(
                session, project_root=root, project_id=decisions.project_id
            )[0]
        assert row.status == "prepared"
        assert row.preprocessing_ocr_treatment == "original"

        with session_scope(engine) as session:
            run = _seed_completed_extraction(session)
        with session_scope(engine) as session:
            row = processing_inventory_rows(
                session, project_root=root, project_id=decisions.project_id
            )[0]
        assert row.status == "pending_selection"
        assert row.selected_pages == 0

        with session_scope(engine) as session:
            _run, changed = select_extraction_pages(
                session,
                source_key="doc_processing",
                selected_by="Alex",
                run_id=run.id,
                pages={1},
            )
        assert changed == 1
        with session_scope(engine) as session:
            row = processing_inventory_rows(
                session, project_root=root, project_id=decisions.project_id
            )[0]
        assert row.status == "ready_for_review"

        with session_scope(engine) as session:
            summary = bootstrap_editable_layer(
                session,
                decisions=decisions,
                created_by="Alex",
                source_keys={"doc_processing"},
            )
        assert summary.pages_created == 1
        with session_scope(engine) as session:
            row = processing_inventory_rows(
                session, project_root=root, project_id=decisions.project_id
            )[0]
        assert row.status == "in_review"

        with session_scope(engine) as session:
            page = session.scalar(select(EditablePage))
            assert page
            page.review_status = "approved"
        with session_scope(engine) as session:
            row = processing_inventory_rows(
                session, project_root=root, project_id=decisions.project_id
            )[0]
        assert row.status == "completed"
    finally:
        engine.dispose()


def test_failed_page_retry_uses_missing_pages_from_latest_failed_run(tmp_path: Path) -> None:
    root = tmp_path / "project"
    _write_pdf(root / "corpus/doc.pdf", pages=2)
    decisions = load_decisions(Path(__file__).parents[1] / "config/decisions.yaml")
    upgrade_database(root)
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            register_test_corpus(
                session,
                project_root=root,
                decisions=decisions,
                corpus=_corpus(pages=2),
            )
            registration = session.scalar(
                select(SourceRegistration).where(
                    SourceRegistration.source_key == "doc_processing"
                )
            )
            assert registration and registration.digital_object_id
            digital = session.get(DigitalObject, registration.digital_object_id)
            assert digital
            run = ExtractionRun(
                id=new_id(),
                digital_object_id=digital.id,
                profile_key="test_profile",
                engine="tesseract_tsv",
                source_sha256=digital.sha256,
                options_json={"selected_pages": [1, 2]},
                options_hash="b" * 64,
                status="failed",
                is_current=False,
                created_by="tests",
                total_pages=0,
                total_objects=0,
                total_paragraphs=0,
                total_characters=0,
                warnings_json=[],
                error_text="Falló página 2",
            )
            session.add(run)
            session.flush()
            session.add(
                ExtractionPage(
                    id=new_id(),
                    extraction_run_id=run.id,
                    page_number=1,
                    object_count=1,
                    character_count=20,
                    status="completed",
                )
            )
        with session_scope(engine) as session:
            assert failed_extraction_pages(session, source_key="doc_processing") == [2]
    finally:
        engine.dispose()


def test_processing_jobs_persist_batch_results(tmp_path: Path) -> None:
    root = tmp_path / "project"
    _write_pdf(root / "corpus/doc.pdf")
    decisions = load_decisions(Path(__file__).parents[1] / "config/decisions.yaml")
    upgrade_database(root)
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            register_test_corpus(
                session,
                project_root=root,
                decisions=decisions,
                corpus=_corpus(),
            )
            job = create_processing_job(
                session,
                project_id=decisions.project_id,
                operation="prepare",
                source_keys=["doc_processing"],
                created_by="Alex",
                parameters={"force": False},
            )
            start_processing_job(session, job_id=job.id)
            update_processing_job_item(
                session,
                job_id=job.id,
                source_key="doc_processing",
                status="running",
            )
            update_processing_job_item(
                session,
                job_id=job.id,
                source_key="doc_processing",
                status="warning",
                message="Derivados creados con una advertencia",
                detail={"warnings": ["bajo contraste"]},
            )
            finish_processing_job(session, job_id=job.id)
            job_id = job.id
        with session_scope(engine) as session:
            jobs = processing_job_rows(session, project_id=decisions.project_id)
            items = processing_job_item_rows(session, job_id=job_id)
        assert jobs[0].status == "completed_with_warnings"
        assert jobs[0].warning_items == 1
        assert items[0].status == "warning"
        assert items[0].detail == {"warnings": ["bajo contraste"]}
    finally:
        engine.dispose()


def test_processing_migration_upgrades_an_existing_029_database(tmp_path: Path) -> None:
    root = tmp_path / "project"
    upgrade_database(root, revision="0024_semantic_search")
    assert current_revision(root) == "0024_semantic_search"

    upgrade_database(root)
    assert current_revision(root) == "0043_form_structure_review"
    engine = create_sqlite_engine(database_path(root))
    try:
        tables = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()
    assert {"processing_jobs", "processing_job_items"}.issubset(tables)


def test_quality_panel_explains_indicators_without_presenting_accuracy_percentage() -> None:
    from archive_workbench.page_quality import PageQualityResult
    from archive_workbench.processing_app import _render_automatic_quality

    class Context:
        def __init__(self, st):
            self.st = st

        def __enter__(self):
            return self.st

        def __exit__(self, exc_type, exc, traceback):
            return False

    class FakeStreamlit:
        def __init__(self):
            self.messages: list[str] = []
            self.tables: list[list[dict[str, str]]] = []

        def success(self, message):
            self.messages.append(str(message))

        def warning(self, message):
            self.messages.append(str(message))

        def error(self, message):
            self.messages.append(str(message))

        def caption(self, message):
            self.messages.append(str(message))

        def write(self, message):
            self.messages.append(str(message))

        def expander(self, label, **_kwargs):
            self.messages.append(str(label))
            return Context(self)

        def columns(self, count):
            return [Context(self) for _ in range(count)]

        def dataframe(self, rows, **_kwargs):
            self.tables.append(rows)

    st = FakeStreamlit()
    assessment = PageQualityResult(
        assessment_id="assessment",
        extraction_page_id="page",
        status="clear",
        score=1.0,
        metrics={
            "mean_brightness": 0.75,
            "contrast": 0.32,
            "edge_variance": 0.01,
            "noise_ratio": 0.005,
            "object_count": 4,
            "character_count": 300,
            "tiny_object_ratio": 0.0,
            "overlapping_bbox_ratio": 0.0,
        },
    )

    _render_automatic_quality(st, assessment)

    joined = "\n".join(st.messages)
    assert "Sin alertas detectadas" in joined
    assert "100%" not in joined
    assert "no miden la exactitud del OCR" in joined
    assert "no demuestra que el texto reconocido sea correcto" in joined
    assert len(st.tables) == 2


def test_processing_ui_distinguishes_derivative_treatment_from_profile_variant() -> None:
    source = (
        Path(__file__).parents[1]
        / "src"
        / "archive_workbench"
        / "processing_app.py"
    ).read_text(encoding="utf-8")

    assert "Tratamiento del derivado vigente" in source
    assert "Transformación adicional del perfil" in source
    assert "`original` no significa que se use el archivo original sin " in source
    assert "preparación. Significa que el perfil no agrega otra transformación" in source
