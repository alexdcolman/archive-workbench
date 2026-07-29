from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import fitz
import pytest

from archive_workbench.catalog import register_test_corpus
from archive_workbench.contracts.plans import DocumentProcessingPlan
from archive_workbench.contracts.test_corpus import TestCorpus as CorpusDefinition
from archive_workbench.db import create_sqlite_engine, database_path, session_scope, upgrade_database
from archive_workbench.decisions import load_decisions
from archive_workbench.document_plans import (
    create_document_plan_template,
    execute_document_plan,
    import_document_plan,
    plan_status_rows,
    render_contact_sheets,
    representative_pages,
)
from archive_workbench.extraction import ExtractionSummary, ToolCheck
from archive_workbench.preprocessing import prepare_derivatives


def _write_pdf(path: Path, pages: int = 3) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    document = fitz.open()
    for page_number in range(1, pages + 1):
        page = document.new_page(width=500 + page_number * 10, height=700)
        page.insert_text((72, 72), f"Página {page_number}")
    document.save(path)
    document.close()


def _corpus(pages: int = 3) -> CorpusDefinition:
    return CorpusDefinition.model_validate(
        {
            "corpus_name": "Planes",
            "created_by": "Alex",
            "created_at": datetime.now(timezone.utc),
            "documents": [
                {
                    "test_id": "doc_multi",
                    "local_path": "corpus/doc_multi.pdf",
                    "short_description": "Documento multipágina",
                    "archival_location": {
                        "fondo": "SiCH",
                        "caja": "Caja 1",
                        "documento": "Documento multipágina",
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
                        "multiple_internal_documents": True,
                    },
                    "expected_extraction": {"minimum_page_coverage_percent": 95},
                }
            ],
        }
    )


def _registered_project(tmp_path: Path, pages: int = 3):
    root = tmp_path / "project"
    _write_pdf(root / "corpus/doc_multi.pdf", pages=pages)
    decisions = load_decisions(Path(__file__).parents[1] / "config/decisions.yaml")
    upgrade_database(root)
    engine = create_sqlite_engine(database_path(root))
    with session_scope(engine) as session:
        register_test_corpus(
            session,
            project_root=root,
            decisions=decisions,
            corpus=_corpus(pages),
        )
    return root, engine, decisions


def test_representative_pages_are_distributed() -> None:
    assert representative_pages(1) == [1]
    assert representative_pages(9, 5) == [1, 3, 5, 7, 9]
    assert representative_pages(34, 5) == [1, 9, 18, 26, 34]


def test_ready_plan_rejects_gaps_and_overlaps() -> None:
    with pytest.raises(ValueError, match="sin asignar"):
        DocumentProcessingPlan.model_validate(
            {
                "plan_key": "gap",
                "source_key": "doc_multi",
                "expected_page_count": 3,
                "status": "ready",
                "assignments": [
                    {
                        "assignment_key": "p1",
                        "pages": [1],
                        "mode": "manual",
                    }
                ],
            }
        )
    with pytest.raises(ValueError, match="superponen"):
        DocumentProcessingPlan.model_validate(
            {
                "plan_key": "overlap",
                "source_key": "doc_multi",
                "expected_page_count": 3,
                "status": "draft",
                "assignments": [
                    {"assignment_key": "a", "page_start": 1, "page_end": 2, "mode": "manual"},
                    {"assignment_key": "b", "pages": [2, 3], "mode": "skip"},
                ],
            }
        )


def test_template_import_is_idempotent_and_persists_parts(tmp_path: Path) -> None:
    root, engine, _decisions = _registered_project(tmp_path, pages=3)
    try:
        with session_scope(engine) as session:
            draft = create_document_plan_template(
                session, source_key="doc_multi", created_by="Alex", sample_count=3
            )
            payload = draft.model_dump(mode="json")
            payload["parts"] = [
                {
                    "part_key": "doc_1",
                    "title": "Primer documento",
                    "page_start": 1,
                    "page_end": 2,
                    "status": "provisional",
                },
                {
                    "part_key": "doc_2",
                    "title": "Segundo documento",
                    "page_start": 3,
                    "page_end": 3,
                    "status": "provisional",
                },
            ]
            plan = DocumentProcessingPlan.model_validate(payload)
            first = import_document_plan(session, project_root=root, plan=plan)
        with session_scope(engine) as session:
            second = import_document_plan(session, project_root=root, plan=plan)
            rows = plan_status_rows(session)
    finally:
        engine.dispose()
    assert first.reused is False
    assert second.reused is True
    assert rows[0].assigned_pages == 3
    assert rows[0].pending_pages == 3
    assert rows[0].parts == 2


def test_contact_sheets_and_plan_execution_manifest(tmp_path: Path, monkeypatch) -> None:
    root, engine, decisions = _registered_project(tmp_path, pages=3)
    profile_source = Path(__file__).parents[1] / "config/extraction_tesseract.yaml"
    profile_destination = root / "config/extraction_tesseract.yaml"
    profile_destination.parent.mkdir(parents=True, exist_ok=True)
    profile_destination.write_text(profile_source.read_text(encoding="utf-8"), encoding="utf-8")
    try:
        with session_scope(engine) as session:
            prepare_derivatives(session, project_root=root, decisions=decisions)
        with session_scope(engine) as session:
            sheets = render_contact_sheets(
                session,
                project_root=root,
                source_key="doc_multi",
                pages_per_sheet=2,
                columns=2,
                thumb_width=200,
            )
        assert len(sheets) == 2
        assert all((root / item.path).is_file() for item in sheets)

        plan = DocumentProcessingPlan.model_validate(
            {
                "plan_key": "doc_multi_ready_v1",
                "source_key": "doc_multi",
                "expected_page_count": 3,
                "status": "ready",
                "benchmark_pages": [1, 2, 3],
                "parts": [
                    {
                        "part_key": "documento",
                        "title": "Documento completo",
                        "page_start": 1,
                        "page_end": 3,
                    }
                ],
                "assignments": [
                    {
                        "assignment_key": "ocr_all",
                        "page_start": 1,
                        "page_end": 3,
                        "mode": "ocr",
                        "profile": "config/extraction_tesseract.yaml",
                        "part_key": "documento",
                    }
                ],
                "created_by": "Alex",
            }
        )

        import archive_workbench.document_plans as module

        monkeypatch.setattr(
            module,
            "extraction_doctor",
            lambda profile: type("Report", (), {"checks": [ToolCheck("Tesseract", True, "ok")]})(),
        )
        monkeypatch.setattr(
            module,
            "extract_documents",
            lambda *args, **kwargs: ExtractionSummary(
                objects_seen=1,
                runs_created=1,
                pages_processed=3,
                objects_created=9,
                paragraphs_created=3,
                characters_created=120,
            ),
        )
        with session_scope(engine) as session:
            summary = execute_document_plan(
                session,
                project_root=root,
                decisions=decisions,
                plan=plan,
                created_by="Alex",
            )
        assert summary.failed == 0
        assert summary.pages_processed == 3
        assert summary.manifest_path is not None
        assert (root / summary.manifest_path).is_file()
    finally:
        engine.dispose()


def test_part_page_sequence_preserves_logical_order() -> None:
    plan = DocumentProcessingPlan.model_validate(
        {
            "plan_key": "logical_order",
            "source_key": "doc_multi",
            "expected_page_count": 3,
            "status": "ready",
            "parts": [
                {
                    "part_key": "reordered",
                    "title": "Documento reordenado",
                    "page_start": 1,
                    "page_end": 2,
                    "page_sequence": [2, 1],
                    "status": "confirmed",
                },
                {
                    "part_key": "third",
                    "title": "Tercera página",
                    "page_start": 3,
                    "page_end": 3,
                },
            ],
            "assignments": [
                {
                    "assignment_key": "first_part",
                    "pages": [1, 2],
                    "mode": "manual",
                    "part_key": "reordered",
                },
                {
                    "assignment_key": "second_part",
                    "pages": [3],
                    "mode": "manual",
                    "part_key": "third",
                },
            ],
        }
    )
    assert plan.parts[0].pages == {1, 2}
    assert plan.parts[0].logical_pages == [2, 1]
    assert plan.parts[0].physical_page_start == 1
    assert plan.parts[0].physical_page_end == 2


def test_part_sequence_and_assignment_must_match_part_pages() -> None:
    with pytest.raises(ValueError, match="exactamente las páginas"):
        DocumentProcessingPlan.model_validate(
            {
                "plan_key": "bad_sequence",
                "source_key": "doc_multi",
                "expected_page_count": 3,
                "parts": [
                    {
                        "part_key": "bad",
                        "title": "Mala secuencia",
                        "page_start": 1,
                        "page_end": 2,
                        "page_sequence": [2],
                    }
                ],
                "assignments": [
                    {"assignment_key": "all", "pages": [1, 2, 3], "mode": "manual"}
                ],
            }
        )
    with pytest.raises(ValueError, match="fuera de la parte"):
        DocumentProcessingPlan.model_validate(
            {
                "plan_key": "bad_assignment_part",
                "source_key": "doc_multi",
                "expected_page_count": 3,
                "parts": [
                    {
                        "part_key": "part",
                        "title": "Una página",
                        "page_start": 1,
                        "page_end": 1,
                    }
                ],
                "assignments": [
                    {
                        "assignment_key": "outside",
                        "pages": [1, 2],
                        "mode": "manual",
                        "part_key": "part",
                    },
                    {"assignment_key": "remaining", "pages": [3], "mode": "manual"},
                ],
            }
        )


def test_import_persists_logical_page_sequence(tmp_path: Path) -> None:
    from sqlalchemy import select
    from archive_workbench.db.models import DocumentPart
    from archive_workbench.document_plans import document_part_status_rows

    root, engine, _decisions = _registered_project(tmp_path, pages=3)
    plan = DocumentProcessingPlan.model_validate(
        {
            "schema_version": "1.1",
            "plan_key": "logical_import",
            "source_key": "doc_multi",
            "expected_page_count": 3,
            "status": "ready",
            "parts": [
                {
                    "part_key": "reordered",
                    "title": "Documento reordenado",
                    "page_start": 1,
                    "page_end": 2,
                    "page_sequence": [2, 1],
                    "status": "confirmed",
                },
                {
                    "part_key": "last",
                    "title": "Último documento",
                    "page_start": 3,
                    "page_end": 3,
                },
            ],
            "assignments": [
                {
                    "assignment_key": "p12",
                    "pages": [1, 2],
                    "mode": "manual",
                    "part_key": "reordered",
                },
                {
                    "assignment_key": "p3",
                    "pages": [3],
                    "mode": "manual",
                    "part_key": "last",
                },
            ],
        }
    )
    try:
        with session_scope(engine) as session:
            import_document_plan(session, project_root=root, plan=plan)
        with session_scope(engine) as session:
            persisted = session.scalar(
                select(DocumentPart).where(DocumentPart.part_key == "reordered")
            )
            rows = document_part_status_rows(session, source_key="doc_multi")
            assert persisted is not None
            assert persisted.page_sequence_json == [2, 1]
            assert rows[0].physical_pages == [1, 2]
            assert rows[0].logical_pages == [2, 1]
    finally:
        engine.dispose()
