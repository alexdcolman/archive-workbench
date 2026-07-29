from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import fitz
import pytest
from sqlalchemy import func, select

from archive_workbench.catalog import register_test_corpus
from archive_workbench.contracts.test_corpus import TestCorpus as CorpusDefinition
from archive_workbench.db import create_sqlite_engine, database_path, session_scope, upgrade_database
from archive_workbench.db.models import (
    DigitalObject,
    DocumentPart,
    EditableObject,
    EditableObjectRevision,
    EditablePage,
    ExtractedObject,
    ExtractionPage,
    ExtractionPageSelection,
    ExtractionRun,
    SourceRegistration,
)
from archive_workbench.decisions import load_decisions
from archive_workbench.editing import (
    add_editable_object,
    bootstrap_editable_layer,
    editing_status_rows,
    export_editable_layer,
    merge_editable_object,
    move_editable_object,
    object_revision_rows,
    revert_editable_object,
    set_editable_object_lifecycle,
    split_editable_object,
    update_editable_object,
)
from archive_workbench.identity import new_id


def _write_pdf(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = fitz.open()
    page = doc.new_page(width=600, height=400)
    page.insert_text((50, 80), "Documento")
    doc.save(path)
    doc.close()


def _corpus() -> CorpusDefinition:
    return CorpusDefinition.model_validate(
        {
            "corpus_name": "Edición",
            "created_by": "tests",
            "created_at": datetime.now(timezone.utc),
            "documents": [
                {
                    "test_id": "doc_editable",
                    "local_path": "corpus/doc.pdf",
                    "short_description": "Documento editable",
                    "archival_location": {
                        "fondo": "SiCH",
                        "legajo": "Legajo 1",
                        "documento": "Documento editable",
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


def _seed_selected_extraction(session) -> tuple[str, str, str]:
    registration = session.scalar(
        select(SourceRegistration).where(SourceRegistration.source_key == "doc_editable")
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
        options_json={},
        options_hash="a" * 64,
        status="completed",
        is_current=True,
        created_by="tests",
        total_pages=1,
        total_objects=2,
        total_paragraphs=2,
        total_characters=18,
        warnings_json=[],
        quality_status="needs_review",
    )
    session.add(run)
    session.flush()
    page = ExtractionPage(
        id=new_id(),
        extraction_run_id=run.id,
        page_number=1,
        object_count=2,
        character_count=18,
        status="completed",
    )
    session.add(page)
    session.flush()
    first = ExtractedObject(
        id=new_id(),
        origin_id=new_id(),
        extraction_run_id=run.id,
        digital_object_id=digital.id,
        page_number=1,
        order_index=0,
        object_type="title",
        original_text="Título OCR",
        geometry_json=[],
        attributes_json={},
    )
    second = ExtractedObject(
        id=new_id(),
        origin_id=new_id(),
        extraction_run_id=run.id,
        digital_object_id=digital.id,
        page_number=1,
        order_index=1,
        object_type="paragraph",
        original_text="Texto OCR",
        geometry_json=[],
        attributes_json={},
    )
    session.add_all([first, second])
    selection = ExtractionPageSelection(
        id=new_id(),
        digital_object_id=digital.id,
        page_number=1,
        extraction_run_id=run.id,
        extraction_page_id=page.id,
        selected_by="tests",
    )
    session.add(selection)
    session.flush()
    return digital.id, first.id, page.id


def test_editable_layer_is_versioned_and_does_not_mutate_ocr(tmp_path: Path) -> None:
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
            _seed_selected_extraction(session)
        with session_scope(engine) as session:
            summary = bootstrap_editable_layer(
                session,
                decisions=decisions,
                created_by="Alex",
                source_keys={"doc_editable"},
            )
        assert summary.pages_created == 1
        assert summary.objects_created == 2
        assert summary.revisions_created == 2

        with session_scope(engine) as session:
            objects = session.scalars(
                select(EditableObject).order_by(EditableObject.current_order_index)
            ).all()
            source = session.get(ExtractedObject, objects[0].source_extracted_object_id)
            assert source and source.original_text == "Título OCR"
            first_id = objects[0].id
            second_id = objects[1].id

        with session_scope(engine) as session:
            edited = update_editable_object(
                session,
                decisions=decisions,
                object_id=first_id,
                expected_revision=1,
                edited_by="Alex",
                text="Título corregido",
                note="Corrección manual",
            )
            assert edited.revision_number == 2
        with session_scope(engine) as session:
            with pytest.raises(ValueError, match="Conflicto de revisión"):
                update_editable_object(
                    session,
                    decisions=decisions,
                    object_id=first_id,
                    expected_revision=1,
                    edited_by="Otra persona",
                    text="Sobrescritura",
                )

        with session_scope(engine) as session:
            added = add_editable_object(
                session,
                decisions=decisions,
                source_key="doc_editable",
                page=1,
                object_type="paragraph",
                text="Texto agregado",
                created_by="Alex",
                after_object_id=first_id,
            )
            assert added.current_order_index == 1
        with session_scope(engine) as session:
            second = session.get(EditableObject, second_id)
            assert second and second.current_order_index == 2
            assert second.revision_number == 2

        with session_scope(engine) as session:
            deleted = set_editable_object_lifecycle(
                session,
                object_id=added.id,
                expected_revision=1,
                lifecycle_status="deleted",
                changed_by="Alex",
            )
            assert deleted.revision_number == 2
        with session_scope(engine) as session:
            restored = set_editable_object_lifecycle(
                session,
                object_id=added.id,
                expected_revision=2,
                lifecycle_status="active",
                changed_by="Alex",
            )
            assert restored.revision_number == 3
        with session_scope(engine) as session:
            reverted = revert_editable_object(
                session,
                object_id=first_id,
                target_revision=1,
                expected_revision=2,
                reverted_by="Alex",
            )
            assert reverted.current_text == "Título OCR"
            assert reverted.revision_number == 3

        with session_scope(engine) as session:
            history = object_revision_rows(session, object_id=first_id)
            assert [item.operation for item in history] == ["import", "edit", "revert"]
            status = editing_status_rows(session)[0]
            assert status.editable_pages == 1
            assert status.stale_pages == []
            assert status.active_objects == 3
            assert status.revisions >= 8
            exported = export_editable_layer(
                session,
                project_root=root,
                source_key="doc_editable",
            )
            assert exported.object_count == 3
            assert exported.revision_count >= 8
            assert exported.objects_path.is_file()
            assert exported.revisions_path.is_file()
            assert exported.manifest_path.is_file()
    finally:
        engine.dispose()


def test_bootstrap_marks_existing_page_stale_when_selection_changes(tmp_path: Path) -> None:
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
            digital_id, _source_id, old_page_id = _seed_selected_extraction(session)
            bootstrap_editable_layer(
                session,
                decisions=decisions,
                created_by="Alex",
                source_keys={"doc_editable"},
            )
            selection = session.scalar(
                select(ExtractionPageSelection).where(
                    ExtractionPageSelection.digital_object_id == digital_id,
                    ExtractionPageSelection.page_number == 1,
                )
            )
            assert selection
            old_run = session.get(ExtractionRun, selection.extraction_run_id)
            assert old_run
            new_run = ExtractionRun(
                id=new_id(),
                digital_object_id=digital_id,
                profile_key="new_profile",
                engine="tesseract_tsv",
                source_sha256=old_run.source_sha256,
                options_json={},
                options_hash="b" * 64,
                status="completed",
                is_current=True,
                total_pages=1,
                total_objects=0,
                total_paragraphs=0,
                total_characters=0,
                warnings_json=[],
                quality_status="unreviewed",
            )
            session.add(new_run)
            session.flush()
            new_page = ExtractionPage(
                id=new_id(),
                extraction_run_id=new_run.id,
                page_number=1,
                object_count=0,
                character_count=0,
                status="completed",
            )
            session.add(new_page)
            session.flush()
            selection.extraction_run_id = new_run.id
            selection.extraction_page_id = new_page.id
            assert selection.extraction_page_id != old_page_id
        with session_scope(engine) as session:
            summary = bootstrap_editable_layer(
                session,
                decisions=decisions,
                created_by="Alex",
                source_keys={"doc_editable"},
            )
            assert summary.pages_stale == 1
            page = session.scalar(select(EditablePage))
            assert page and page.status == "stale"
            assert editing_status_rows(session)[0].stale_pages == [1]
    finally:
        engine.dispose()


def test_structural_editing_is_versioned_and_preserves_lineage(tmp_path: Path) -> None:
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
            _seed_selected_extraction(session)
            bootstrap_editable_layer(
                session,
                decisions=decisions,
                created_by="Alex",
                source_keys={"doc_editable"},
            )
        with session_scope(engine) as session:
            objects = session.scalars(
                select(EditableObject).order_by(EditableObject.current_order_index)
            ).all()
            first_id, second_id = objects[0].id, objects[1].id

        with session_scope(engine) as session:
            moved = move_editable_object(
                session,
                object_id=second_id,
                expected_revision=1,
                direction="up",
                changed_by="Alex",
            )
            assert moved.current_order_index == 0
        with session_scope(engine) as session:
            first = session.get(EditableObject, first_id)
            second = session.get(EditableObject, second_id)
            assert first and second
            assert first.current_order_index == 1
            assert second.current_order_index == 0
            assert object_revision_rows(session, object_id=second_id)[-1].operation == "reorder"

        with session_scope(engine) as session:
            second = session.get(EditableObject, second_id)
            assert second
            left, right = split_editable_object(
                session,
                object_id=second_id,
                expected_revision=second.revision_number,
                left_text="Primera mitad",
                right_text="Segunda mitad",
                changed_by="Alex",
            )
            right_id = right.id
            assert left.current_text == "Primera mitad"
            assert right.current_order_index == 1
            assert right.current_geometry_json == []
            assert right.current_attributes_json["split_from_object_id"] == second_id

        with session_scope(engine) as session:
            right = session.get(EditableObject, right_id)
            assert right
            merged = merge_editable_object(
                session,
                object_id=right_id,
                expected_revision=right.revision_number,
                direction="previous",
                separator="\n",
                changed_by="Alex",
            )
            assert merged.current_text == "Primera mitad\nSegunda mitad"
        with session_scope(engine) as session:
            active = session.scalars(
                select(EditableObject)
                .where(EditableObject.lifecycle_status == "active")
                .order_by(EditableObject.current_order_index)
            ).all()
            deleted = session.scalars(
                select(EditableObject).where(EditableObject.lifecycle_status == "deleted")
            ).all()
            assert [item.current_order_index for item in active] == [0, 1]
            assert len(deleted) == 1
            assert deleted[0].id == second_id
            assert object_revision_rows(session, object_id=right_id)[-1].operation == "merge"
            assert object_revision_rows(session, object_id=second_id)[-1].operation == "merge"
    finally:
        engine.dispose()


def test_page_actions_undo_redo_structural_changes(tmp_path: Path) -> None:
    from archive_workbench.page_actions import (
        execute_page_action,
        page_action_availability,
        redo_page_action,
        undo_page_action,
    )

    root = tmp_path / "project_actions"
    _write_pdf(root / "corpus/doc.pdf")
    decisions = load_decisions(Path(__file__).parents[1] / "config/decisions.yaml")
    upgrade_database(root)
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            register_test_corpus(
                session, project_root=root, decisions=decisions, corpus=_corpus()
            )
            _seed_selected_extraction(session)
            bootstrap_editable_layer(
                session,
                decisions=decisions,
                created_by="Alex",
                source_keys={"doc_editable"},
            )
        with session_scope(engine) as session:
            objects = session.scalars(
                select(EditableObject).order_by(EditableObject.current_order_index)
            ).all()
            first, second = objects
            editable_page_id = first.editable_page_id
            execute_page_action(
                session,
                editable_page_id=editable_page_id,
                action_type="reorder",
                changed_by="Alex",
                selected_object_id=first.id,
                action=lambda: move_editable_object(
                    session,
                    object_id=first.id,
                    expected_revision=first.revision_number,
                    direction="down",
                    changed_by="Alex",
                ),
            )
        with session_scope(engine) as session:
            first = session.get(EditableObject, first.id)
            second = session.get(EditableObject, second.id)
            assert first and second
            assert (first.current_order_index, second.current_order_index) == (1, 0)
            availability = page_action_availability(
                session, editable_page_id=editable_page_id
            )
            assert availability.can_undo is True
            assert availability.can_redo is False
            selected = undo_page_action(
                session, editable_page_id=editable_page_id, changed_by="Alex"
            )
            assert selected == first.id
        with session_scope(engine) as session:
            first = session.get(EditableObject, first.id)
            second = session.get(EditableObject, second.id)
            assert first and second
            assert (first.current_order_index, second.current_order_index) == (0, 1)
            availability = page_action_availability(
                session, editable_page_id=editable_page_id
            )
            assert availability.can_redo is True
            redo_page_action(session, editable_page_id=editable_page_id, changed_by="Alex")
        with session_scope(engine) as session:
            first = session.get(EditableObject, first.id)
            second = session.get(EditableObject, second.id)
            assert first and second
            assert (first.current_order_index, second.current_order_index) == (1, 0)
    finally:
        engine.dispose()


def test_review_annotations_and_export(tmp_path: Path) -> None:
    from archive_workbench.review_annotations import (
        add_object_comment,
        add_object_tag,
        object_comment_rows,
        object_tag_rows,
        object_tags,
        set_object_review_status,
        set_page_review_status,
    )

    root = tmp_path / "project_annotations"
    _write_pdf(root / "corpus/doc.pdf")
    decisions = load_decisions(Path(__file__).parents[1] / "config/decisions.yaml")
    upgrade_database(root)
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            register_test_corpus(
                session, project_root=root, decisions=decisions, corpus=_corpus()
            )
            _seed_selected_extraction(session)
            bootstrap_editable_layer(
                session,
                decisions=decisions,
                created_by="Alex",
                source_keys={"doc_editable"},
            )
        with session_scope(engine) as session:
            obj = session.scalar(
                select(EditableObject).order_by(EditableObject.current_order_index)
            )
            assert obj
            add_object_tag(
                session,
                object_id=obj.id,
                tag="Persona vigilada",
                tag_kind="thematic",
                created_by="Alex",
            )
            add_object_tag(
                session,
                object_id=obj.id,
                tag=" persona   vigilada ",
                tag_kind="thematic",
                created_by="Alex",
            )
            add_object_tag(
                session,
                object_id=obj.id,
                tag="Vigilancia",
                tag_kind="conceptual",
                created_by="Alex",
            )
            add_object_comment(
                session,
                object_id=obj.id,
                body="Revisar el apellido en la imagen.",
                created_by="Alex",
            )
            set_object_review_status(
                session, object_id=obj.id, status="needs_review", changed_by="Alex"
            )
            set_page_review_status(
                session,
                editable_page_id=obj.editable_page_id,
                status="reviewed",
                changed_by="Alex",
                note="Primera pasada completa",
            )
        with session_scope(engine) as session:
            assert object_tags(session, object_id=obj.id) == ["Vigilancia", "Persona vigilada"]
            tag_rows = object_tag_rows(session, object_id=obj.id)
            assert [(item.tag_kind, item.tag) for item in tag_rows] == [
                ("conceptual", "Vigilancia"),
                ("thematic", "Persona vigilada"),
            ]
            comments = object_comment_rows(session, object_id=obj.id)
            assert len(comments) == 1
            assert "apellido" in comments[0].body
            current = session.get(EditableObject, obj.id)
            page = session.get(EditablePage, obj.editable_page_id)
            assert current and current.review_status == "needs_review"
            assert page and page.review_status == "reviewed"
            summary = export_editable_layer(
                session, project_root=root, source_key="doc_editable"
            )
        assert summary.comment_count == 1
        assert summary.tag_count == 2
        assert summary.comments_path.is_file()
        assert summary.tags_path.is_file()
        exported_tags = summary.tags_path.read_text(encoding="utf-8")
        assert "Persona vigilada" in exported_tags
        assert '"tag_kind":"thematic"' in exported_tags
        assert '"tag_kind":"conceptual"' in exported_tags
    finally:
        engine.dispose()


def test_assign_internal_part_is_versioned_and_undoable(tmp_path: Path) -> None:
    from archive_workbench.page_actions import execute_page_action, undo_page_action
    from archive_workbench.review_parts import assign_editable_object_part

    root = tmp_path / "project_parts"
    _write_pdf(root / "corpus/doc.pdf")
    decisions = load_decisions(Path(__file__).parents[1] / "config/decisions.yaml")
    upgrade_database(root)
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            register_test_corpus(
                session, project_root=root, decisions=decisions, corpus=_corpus()
            )
            digital_id, _source_id, _page_id = _seed_selected_extraction(session)
            part = DocumentPart(
                id=new_id(),
                digital_object_id=digital_id,
                part_key="informe_principal",
                title="Informe principal",
                part_type="report",
                page_start=1,
                page_end=1,
                page_sequence_json=[1],
                status="confirmed",
                created_by="tests",
            )
            session.add(part)
            bootstrap_editable_layer(
                session,
                decisions=decisions,
                created_by="Alex",
                source_keys={"doc_editable"},
            )
            session.flush()
            obj = session.scalar(
                select(EditableObject).order_by(EditableObject.current_order_index)
            )
            assert obj
            object_id = obj.id
            editable_page_id = obj.editable_page_id
            part_id = part.id
            execute_page_action(
                session,
                editable_page_id=editable_page_id,
                action_type="assign_part",
                changed_by="Alex",
                selected_object_id=object_id,
                action=lambda: assign_editable_object_part(
                    session,
                    object_id=object_id,
                    part_id=part_id,
                    expected_revision=obj.revision_number,
                    changed_by="Alex",
                ),
            )
        with session_scope(engine) as session:
            obj = session.get(EditableObject, object_id)
            assert obj and obj.document_part_id == part_id
            assert object_revision_rows(session, object_id=object_id)[-1].operation == "assign_part"
            undo_page_action(
                session, editable_page_id=editable_page_id, changed_by="Alex"
            )
        with session_scope(engine) as session:
            obj = session.get(EditableObject, object_id)
            assert obj and obj.document_part_id is None
            summary = export_editable_layer(
                session, project_root=root, source_key="doc_editable"
            )
        assert summary.objects_path.is_file()
    finally:
        engine.dispose()
