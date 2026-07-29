from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import fitz
from sqlalchemy import select

from archive_workbench.catalog import register_test_corpus
from archive_workbench.contracts.extraction import ExtractionProfile
from archive_workbench.contracts.test_corpus import TestCorpus as CorpusDefinition
from archive_workbench.db import create_sqlite_engine, database_path, session_scope, upgrade_database
from archive_workbench.db.models import ExtractedObject, ExtractionPage, ExtractionRun
from archive_workbench.decisions import load_decisions
from archive_workbench.extraction import extract_documents, extraction_status_rows, normalize_docling_page
from archive_workbench.preprocessing import prepare_derivatives


def _write_pdf(path: Path, pages: int = 1) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    document = fitz.open()
    for number in range(1, pages + 1):
        page = document.new_page(width=600, height=400)
        page.insert_text((60, 80), f"Documento de prueba {number}")
    document.save(path)
    document.close()


def _corpus() -> CorpusDefinition:
    return CorpusDefinition.model_validate(
        {
            "corpus_name": "Prueba de extracción",
            "created_by": "tests",
            "created_at": datetime.now(timezone.utc),
            "documents": [
                {
                    "test_id": "documento_ocr",
                    "local_path": "corpus/caja/documento.pdf",
                    "short_description": "Documento OCR",
                    "archival_location": {
                        "fondo": "SiCH",
                        "caja": "Caja 1",
                        "documento": "Documento OCR",
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
                        "tables_or_forms": True,
                        "multiple_internal_documents": False,
                    },
                    "expected_extraction": {"minimum_page_coverage_percent": 95},
                }
            ],
        }
    )


def _docling_payload() -> dict:
    return {
        "schema_name": "DoclingDocument",
        "version": "1.0.0",
        "body": {
            "self_ref": "#/body",
            "children": [
                {"$ref": "#/texts/0"},
                {"$ref": "#/texts/1"},
                {"$ref": "#/tables/0"},
            ],
        },
        "texts": [
            {
                "self_ref": "#/texts/0",
                "label": "title",
                "text": "INFORME CONFIDENCIAL",
                "prov": [
                    {
                        "page_no": 1,
                        "bbox": {"l": 60, "t": 40, "r": 540, "b": 90, "coord_origin": "TOPLEFT"},
                    }
                ],
            },
            {
                "self_ref": "#/texts/1",
                "parent": {"$ref": "#/texts/0"},
                "label": "paragraph",
                "text": "Texto mecanografiado reconocido por OCR.",
                "confidence": 0.91,
                "prov": [
                    {
                        "page_no": 1,
                        "bbox": {"l": 60, "t": 110, "r": 540, "b": 180, "coord_origin": "TOPLEFT"},
                    }
                ],
            },
        ],
        "tables": [
            {
                "self_ref": "#/tables/0",
                "label": "table",
                "data": {
                    "grid": [
                        [{"text": "Nombre"}, {"text": "Cargo"}],
                        [{"text": "Ana"}, {"text": "Secretaria"}],
                    ]
                },
                "prov": [
                    {
                        "page_no": 1,
                        "bbox": {"l": 60, "t": 210, "r": 540, "b": 340, "coord_origin": "TOPLEFT"},
                    }
                ],
            }
        ],
        "pictures": [],
    }


def test_normalization_preserves_order_geometry_parent_and_table() -> None:
    decisions = load_decisions(Path(__file__).parents[1] / "config/decisions.yaml")
    records = normalize_docling_page(
        _docling_payload(),
        digital_object_id="digital-1",
        extraction_run_id="run-1",
        page_number=1,
        width=600,
        height=400,
        decisions=decisions,
    )

    assert [item.object_type for item in records] == ["title", "paragraph", "table"]
    assert [item.order_index for item in records] == [0, 1, 2]
    assert records[1].parent_object_id == records[0].object_id
    assert records[1].confidence == 0.91
    assert records[2].hidden_by_default is True
    assert "| Nombre | Cargo |" in records[2].original_text
    assert records[0].geometry[0].polygon[0] == (0.1, 0.1)
    assert records[0].geometry[0].polygon[2] == (0.9, 0.225)


def test_extraction_is_versioned_persisted_and_reused(tmp_path: Path) -> None:
    root = tmp_path / "project"
    _write_pdf(root / "corpus/caja/documento.pdf", pages=2)
    decisions = load_decisions(Path(__file__).parents[1] / "config/decisions.yaml")
    profile = ExtractionProfile(minimum_characters_per_page_warning=5)

    calls: list[int] = []

    def fake_runner(
        source_images: list[tuple[int, Path]],
        output_dir: Path,
        _profile: ExtractionProfile,
    ):
        calls.append(len(source_images))
        output_dir.mkdir(parents=True, exist_ok=True)
        outputs: dict[int, Path] = {}
        for page_number, source_image in source_images:
            assert source_image.is_file()
            json_path = output_dir / f"page_{page_number:04d}.json"
            json_path.write_text(json.dumps(_docling_payload()), encoding="utf-8")
            outputs[page_number] = json_path
        return outputs, "test-docling", "fake runner"

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
            preprocessing = prepare_derivatives(
                session,
                project_root=root,
                decisions=decisions,
            )
        with session_scope(engine) as session:
            first = extract_documents(
                session,
                project_root=root,
                decisions=decisions,
                profile=profile,
                created_by="Alex",
                runner=fake_runner,
            )
        with session_scope(engine) as session:
            second = extract_documents(
                session,
                project_root=root,
                decisions=decisions,
                profile=profile,
                created_by="Alex",
                runner=fake_runner,
            )
        with session_scope(engine) as session:
            runs = session.scalars(select(ExtractionRun)).all()
            pages = session.scalars(select(ExtractionPage)).all()
            objects = session.scalars(select(ExtractedObject).order_by(ExtractedObject.order_index)).all()
            status = extraction_status_rows(session)
    finally:
        engine.dispose()

    assert preprocessing.runs_created == 1
    assert first.runs_created == 1
    assert first.pages_processed == 2
    assert first.objects_created == 6
    assert first.characters_created > 20
    assert first.failed == 0
    assert second.runs_reused == 1
    assert calls == [2]
    assert len(runs) == 1
    assert len(pages) == 2
    assert len(objects) == 6
    assert runs[0].is_current is True
    assert runs[0].engine_version == "test-docling"
    assert objects[1].parent_origin_id == objects[0].origin_id
    assert objects[4].parent_origin_id == objects[3].origin_id
    assert status[0].run_status == "completed"
    assert status[0].objects == 6
    for relative_path in (
        runs[0].manifest_path,
        runs[0].raw_pages_path,
        runs[0].objects_path,
        runs[0].paragraphs_path,
        runs[0].images_path,
    ):
        assert relative_path is not None
        assert (root / relative_path).exists()


def test_docling_runner_retries_cpu_after_cudnn_error(tmp_path: Path, monkeypatch) -> None:
    import subprocess

    import archive_workbench.extraction as extraction_module

    source = tmp_path / "page_0001.png"
    source.write_bytes(b"fake-png")
    profile = ExtractionProfile(
        device="auto",
        fallback_device="cpu",
        retry_on_accelerator_error=True,
    )
    calls: list[list[str]] = []

    def fake_run(command, **_kwargs):
        calls.append(list(command))
        device = command[command.index("--device") + 1]
        if device == "auto":
            return subprocess.CompletedProcess(
                command,
                1,
                stdout="",
                stderr="CUDNN_STATUS_SUBLIBRARY_VERSION_MISMATCH",
            )
        output_dir = Path(command[command.index("--output") + 1])
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "page_0001.json").write_text(
            json.dumps(_docling_payload()), encoding="utf-8"
        )
        return subprocess.CompletedProcess(command, 0, stdout="converted", stderr="")

    monkeypatch.setattr(extraction_module.subprocess, "run", fake_run)
    monkeypatch.setattr(extraction_module, "_docling_version", lambda _command: "test")

    outputs, version, log_text = extraction_module.run_docling_cli_batch(
        [(1, source)], tmp_path / "work", profile
    )

    assert version == "test"
    assert outputs[1].is_file()
    assert [call[call.index("--device") + 1] for call in calls] == ["auto", "cpu"]
    assert all("--abort-on-error" in call for call in calls)
    assert "ARCHIVE_WORKBENCH_FALLBACK_DEVICE=cpu" in log_text
    assert "CUDNN_STATUS_SUBLIBRARY_VERSION_MISMATCH" in log_text


def test_failed_docling_run_persists_diagnostic_log(tmp_path: Path) -> None:
    from archive_workbench.extraction import DoclingExecutionError

    root = tmp_path / "project"
    _write_pdf(root / "corpus/caja/documento.pdf", pages=1)
    decisions = load_decisions(Path(__file__).parents[1] / "config/decisions.yaml")
    profile = ExtractionProfile()

    def failing_runner(_source_images, _output_dir, _profile):
        raise DoclingExecutionError(
            "falló layout CUDA",
            log_text="$ docling convert --device auto\nCUDNN_STATUS_SUBLIBRARY_VERSION_MISMATCH",
        )

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
            prepare_derivatives(session, project_root=root, decisions=decisions)
        with session_scope(engine) as session:
            summary = extract_documents(
                session,
                project_root=root,
                decisions=decisions,
                profile=profile,
                created_by="Alex",
                runner=failing_runner,
            )
        with session_scope(engine) as session:
            run = session.scalar(select(ExtractionRun))
    finally:
        engine.dispose()

    assert summary.failed == 1
    assert run is not None
    assert run.status == "failed"
    assert run.raw_pages_path is not None
    log_path = root / run.raw_pages_path / "docling.log"
    assert log_path.is_file()
    assert "CUDNN_STATUS_SUBLIBRARY_VERSION_MISMATCH" in log_path.read_text(encoding="utf-8")
