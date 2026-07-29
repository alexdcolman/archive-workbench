from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from PIL import Image
from typer.testing import CliRunner

from archive_workbench.cli import app
from archive_workbench.db import create_sqlite_engine, database_path, session_scope, upgrade_database
from archive_workbench.db.models import (
    ArchivalUnit,
    DerivativeAsset,
    DigitalObject,
    EditableObject,
    EditablePage,
    ExtractedObject,
    ExtractionPage,
    ExtractionPageSelection,
    ExtractionRun,
    PreprocessingRun,
    Project,
    SourceRegistration,
    utc_now,
)
from archive_workbench.decisions import load_decisions
from archive_workbench.identity import new_id
from archive_workbench.review import (
    ReviewObjectRow,
    render_review_overlay,
    review_document_rows,
    review_page_view,
)
from archive_workbench.review_app import (
    _pending_selection_key,
    _project_root_from_argv,
    _run_action,
)


runner = CliRunner()


def test_edit_object_reports_placeholder_uuid_without_traceback(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "edit-object",
            str(tmp_path),
            "--object-id",
            "UUID_DEL_OBJETO",
            "--base-revision",
            "1",
            "--text-file",
            "correccion.txt",
        ],
    )
    assert result.exit_code == 2
    assert "debe ser un UUID real" in result.output
    assert "Traceback" not in result.output


def test_edit_object_reports_missing_text_file_without_traceback(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "edit-object",
            str(tmp_path),
            "--object-id",
            str(uuid4()),
            "--base-revision",
            "1",
            "--text-file",
            str(tmp_path / "no_existe.txt"),
        ],
    )
    assert result.exit_code == 2
    assert "no existe" in result.output
    assert "Traceback" not in result.output


def test_project_root_argument_parser(tmp_path: Path) -> None:
    assert _project_root_from_argv(["--project-root", str(tmp_path)]) == tmp_path.resolve()


def test_overlay_draws_normalized_geometry(tmp_path: Path) -> None:
    image_path = tmp_path / "page.webp"
    Image.new("RGB", (200, 100), "white").save(image_path)
    item = ReviewObjectRow(
        object_id=str(uuid4()),
        page=1,
        order_index=0,
        object_type="paragraph",
        lifecycle_status="active",
        revision_number=1,
        text="Texto",
        original_text="Texto",
        geometry=[
            {
                "page": 1,
                "polygon": [[0.1, 0.2], [0.9, 0.2], [0.9, 0.8], [0.1, 0.8]],
                "coordinate_space": "normalized",
            }
        ],
        attributes={},
        updated_by="tests",
        updated_at=utc_now(),
        manually_added=False,
    )
    overlay = render_review_overlay(
        image_path,
        [item],
        page=1,
        selected_object_id=item.object_id,
    )
    assert overlay.size == (200, 100)
    assert overlay.getpixel((20, 20)) != (255, 255, 255)


def test_review_queries_resolve_preview_and_original(tmp_path: Path) -> None:
    root = tmp_path / "project"
    (root / "config").mkdir(parents=True)
    decisions_path = Path(__file__).parents[1] / "config" / "decisions.yaml"
    decisions = load_decisions(decisions_path)
    (root / "config" / "decisions.yaml").write_text(
        decisions_path.read_text(encoding="utf-8"), encoding="utf-8"
    )
    preview_rel = Path("derivatives/test/run/preview/page_0001.webp")
    preview_path = root / preview_rel
    preview_path.parent.mkdir(parents=True)
    Image.new("RGB", (120, 160), "white").save(preview_path)
    upgrade_database(root)
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            session.add(
                Project(
                    id=decisions.project_id,
                    name=decisions.project_name,
                    decisions_json=decisions.model_dump(mode="json"),
                )
            )
            session.flush()
            unit = ArchivalUnit(
                id=new_id(),
                project_id=decisions.project_id,
                level_key="documento",
                title="Documento de prueba",
                created_by="tests",
                updated_by="tests",
            )
            digital = DigitalObject(
                id=new_id(),
                project_id=decisions.project_id,
                media_type="pdf",
                original_filename="doc.pdf",
                sha256="a" * 64,
                byte_size=1,
                page_count=1,
            )
            session.add_all([unit, digital])
            session.flush()
            session.add(
                SourceRegistration(
                    id=new_id(),
                    project_id=decisions.project_id,
                    source_type="test_corpus",
                    source_key="doc_review",
                    digital_object_id=digital.id,
                    archival_unit_id=unit.id,
                    source_payload_json={},
                    registered_by="tests",
                )
            )
            preprocessing = PreprocessingRun(
                id=new_id(),
                digital_object_id=digital.id,
                source_sha256=digital.sha256,
                profile_key="default",
                options_json={},
                options_hash="b" * 64,
                backend="pymupdf",
                status="completed",
                is_current=True,
                output_root="derivatives/test/run",
            )
            session.add(preprocessing)
            session.flush()
            session.add(
                DerivativeAsset(
                    id=new_id(),
                    preprocessing_run_id=preprocessing.id,
                    digital_object_id=digital.id,
                    page_number=1,
                    kind="preview",
                    relative_path=preview_rel.as_posix(),
                    mime_type="image/webp",
                    sha256="c" * 64,
                    byte_size=preview_path.stat().st_size,
                    width=120,
                    height=160,
                    dpi=150,
                    backend="pymupdf",
                )
            )
            run = ExtractionRun(
                id=new_id(),
                digital_object_id=digital.id,
                profile_key="test",
                engine="tesseract_tsv",
                source_sha256=digital.sha256,
                options_json={},
                options_hash="d" * 64,
                status="completed",
                is_current=True,
                total_pages=1,
                total_objects=1,
                total_paragraphs=1,
                total_characters=8,
                warnings_json=[],
                quality_status="needs_review",
                created_by="tests",
            )
            session.add(run)
            session.flush()
            extraction_page = ExtractionPage(
                id=new_id(),
                extraction_run_id=run.id,
                page_number=1,
                object_count=1,
                character_count=8,
                status="completed",
            )
            session.add(extraction_page)
            session.flush()
            source = ExtractedObject(
                id=new_id(),
                origin_id=new_id(),
                extraction_run_id=run.id,
                digital_object_id=digital.id,
                page_number=1,
                order_index=0,
                object_type="paragraph",
                original_text="OCR base",
                geometry_json=[
                    {
                        "page": 1,
                        "polygon": [[0.1, 0.1], [0.9, 0.1], [0.9, 0.2], [0.1, 0.2]],
                        "coordinate_space": "normalized",
                    }
                ],
                attributes_json={},
            )
            session.add(source)
            session.flush()
            selection = ExtractionPageSelection(
                id=new_id(),
                digital_object_id=digital.id,
                page_number=1,
                extraction_run_id=run.id,
                extraction_page_id=extraction_page.id,
                selected_by="tests",
            )
            session.add(selection)
            session.flush()
            editable_page = EditablePage(
                id=new_id(),
                digital_object_id=digital.id,
                page_number=1,
                source_extraction_run_id=run.id,
                source_extraction_page_id=extraction_page.id,
                source_selection_id=selection.id,
                status="active",
                bootstrapped_by="tests",
            )
            session.add(editable_page)
            session.flush()
            session.add(
                EditableObject(
                    id=new_id(),
                    editable_page_id=editable_page.id,
                    digital_object_id=digital.id,
                    page_number=1,
                    source_extracted_object_id=source.id,
                    source_origin_id=source.origin_id,
                    current_text="Texto editado",
                    current_object_type="paragraph",
                    current_order_index=0,
                    current_geometry_json=source.geometry_json,
                    current_attributes_json={},
                    lifecycle_status="active",
                    revision_number=2,
                    created_by="tests",
                    updated_by="tests",
                )
            )
        with session_scope(engine) as session:
            documents = review_document_rows(session)
            assert len(documents) == 1
            assert documents[0].editable_pages == [1]
            view = review_page_view(
                session,
                project_root=root,
                source_key="doc_review",
                page=1,
            )
            assert view.preview_path == preview_path
            assert view.is_stale is False
            assert view.objects[0].original_text == "OCR base"
            assert view.objects[0].text == "Texto editado"
    finally:
        engine.dispose()


def test_clickable_canvas_payload_contains_only_valid_boxes(tmp_path: Path) -> None:
    from archive_workbench.review_canvas import build_review_canvas_payload

    image_path = tmp_path / "page.webp"
    Image.new("RGB", (100, 200), "white").save(image_path)
    valid_id = str(uuid4())
    objects = [
        ReviewObjectRow(
            object_id=valid_id,
            page=1,
            order_index=0,
            object_type="paragraph",
            lifecycle_status="active",
            revision_number=1,
            text="Texto",
            original_text="Texto",
            geometry=[
                {
                    "page": 1,
                    "polygon": [[0.1, 0.2], [0.9, 0.2], [0.9, 0.3], [0.1, 0.3]],
                    "coordinate_space": "normalized",
                }
            ],
            attributes={},
            updated_by="tests",
            updated_at=utc_now(),
            manually_added=False,
        ),
        ReviewObjectRow(
            object_id=str(uuid4()),
            page=1,
            order_index=1,
            object_type="paragraph",
            lifecycle_status="active",
            revision_number=1,
            text="Sin caja",
            original_text=None,
            geometry=[],
            attributes={},
            updated_by="tests",
            updated_at=utc_now(),
            manually_added=True,
        ),
    ]
    payload = build_review_canvas_payload(
        image_path,
        objects,
        page=1,
        selected_object_id=valid_id,
    )
    assert payload["image_data_url"].startswith("data:image/webp;base64,")
    assert len(payload["boxes"]) == 1
    assert payload["boxes"][0]["object_id"] == valid_id
    assert payload["boxes"][0]["selected"] is True


def test_run_action_queues_selection_without_mutating_widget_key() -> None:
    class FakeStreamlit:
        def __init__(self) -> None:
            self.session_state: dict[str, str] = {"widget": "old"}
            self.rerun_called = False

        def error(self, _message: str) -> None:
            raise AssertionError("No debía informar error")

        def rerun(self) -> None:
            self.rerun_called = True

    st = FakeStreamlit()
    _run_action(
        st,
        lambda: "new-object",
        selection_key="widget",
        fallback_selection="fallback",
    )
    assert st.session_state["widget"] == "old"
    assert st.session_state[_pending_selection_key("widget")] == "new-object"
    assert st.rerun_called is True
