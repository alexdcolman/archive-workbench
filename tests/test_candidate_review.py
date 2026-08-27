from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import fitz
import pytest
from sqlalchemy import select

from archive_workbench.candidate_review import (
    ADOPTION_MANUAL,
    ADOPTION_NOT_INITIALIZED,
    ADOPTION_SAFE,
    adopt_candidate_page,
    assess_candidate_adoption,
    compare_candidate_page,
    page_history_rows,
    resolve_candidate_keep_edits,
)
from archive_workbench.catalog import register_test_corpus
from archive_workbench.contracts.test_corpus import TestCorpus as CorpusDefinition
from archive_workbench.db import create_sqlite_engine, database_path, session_scope, upgrade_database
from archive_workbench.db.models import (
    DigitalObject,
    EditableObject,
    EditablePage,
    EditablePageRevision,
    ExchangeChangeEvent,
    ExtractionPage,
    ExtractionPageSelection,
    ExtractionPageSelectionRevision,
    ExtractionRun,
    SourceRegistration,
)
from archive_workbench.decisions import load_decisions
from archive_workbench.editing import bootstrap_editable_layer, update_editable_object
from archive_workbench.extraction import select_extraction_pages
from archive_workbench.identity import new_id
from archive_workbench.db.models import ExtractedObject


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
            "corpus_name": "Candidatas",
            "created_by": "tests",
            "created_at": datetime.now(timezone.utc),
            "documents": [
                {
                    "test_id": "doc_candidates",
                    "local_path": "corpus/doc.pdf",
                    "short_description": "Documento con candidatas OCR",
                    "archival_location": {
                        "fondo": "Fondo",
                        "legajo": "Legajo 1",
                        "documento": "Documento",
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


def _seed_run(session, *, profile: str, text_rows: list[tuple[str, str]], options_hash: str):
    registration = session.scalar(
        select(SourceRegistration).where(SourceRegistration.source_key == "doc_candidates")
    )
    assert registration and registration.digital_object_id
    digital = session.get(DigitalObject, registration.digital_object_id)
    assert digital
    run = ExtractionRun(
        id=new_id(),
        digital_object_id=digital.id,
        profile_key=profile,
        engine="tesseract_tsv",
        engine_version="5",
        source_sha256=digital.sha256,
        options_json={},
        options_hash=options_hash,
        status="completed",
        is_current=False,
        created_by="tests",
        total_pages=1,
        total_objects=len(text_rows),
        total_paragraphs=len(text_rows),
        total_characters=sum(len(text) for _kind, text in text_rows),
        warnings_json=[],
        quality_status="needs_review",
    )
    session.add(run)
    session.flush()
    page = ExtractionPage(
        id=new_id(),
        extraction_run_id=run.id,
        page_number=1,
        object_count=len(text_rows),
        character_count=sum(len(text) for _kind, text in text_rows),
        status="completed",
    )
    session.add(page)
    session.flush()
    for order, (kind, text) in enumerate(text_rows):
        session.add(
            ExtractedObject(
                id=new_id(),
                origin_id=new_id(),
                extraction_run_id=run.id,
                digital_object_id=digital.id,
                page_number=1,
                order_index=order,
                object_type=kind,
                original_text=text,
                geometry_json=[],
                attributes_json={},
            )
        )
    session.flush()
    return run


def _project(tmp_path: Path):
    root = tmp_path / "project"
    _write_pdf(root / "corpus/doc.pdf")
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
        old_run = _seed_run(
            session,
            profile="old",
            text_rows=[("title", "Título viejo"), ("paragraph", "Texto viejo")],
            options_hash="a" * 64,
        )
        new_run = _seed_run(
            session,
            profile="new",
            text_rows=[("paragraph", "Texto nuevo y más completo")],
            options_hash="b" * 64,
        )
        select_extraction_pages(
            session,
            source_key="doc_candidates",
            selected_by="tests",
            run_id=old_run.id,
            pages={1},
            note="Selección inicial",
        )
        old_id, new_id_value = old_run.id, new_run.id
    return root, decisions, engine, old_id, new_id_value


def test_compare_and_initialize_candidate_page(tmp_path: Path) -> None:
    root, decisions, engine, _old_run_id, new_run_id = _project(tmp_path)
    try:
        with session_scope(engine) as session:
            comparison = compare_candidate_page(
                session,
                project_root=root,
                source_key="doc_candidates",
                page=1,
                candidate_run_id=new_run_id,
            )
            assert comparison.current is not None
            assert comparison.current.text == "Título viejo\n\nTexto viejo"
            assert comparison.candidate.text == "Texto nuevo y más completo"
            assert comparison.object_delta == -1
            assessment = assess_candidate_adoption(
                session,
                source_key="doc_candidates",
                page=1,
                candidate_run_id=new_run_id,
            )
            assert assessment.code == ADOPTION_NOT_INITIALIZED
            result = adopt_candidate_page(
                session,
                decisions=decisions,
                source_key="doc_candidates",
                page=1,
                candidate_run_id=new_run_id,
                adopted_by="Alex",
            )
            assert result.objects_activated == 1
        with session_scope(engine) as session:
            page = session.scalar(select(EditablePage))
            selection = session.scalar(select(ExtractionPageSelection))
            assert page and selection
            assert page.source_extraction_run_id == new_run_id
            assert selection.extraction_run_id == new_run_id
            assert session.scalar(select(ExtractionPageSelectionRevision).where(
                ExtractionPageSelectionRevision.selection_id == selection.id
            ).order_by(ExtractionPageSelectionRevision.revision_number.desc())).revision_number == 2
            timeline = page_history_rows(session, source_key="doc_candidates", page=1)
            assert any(item.category == "Selección OCR" for item in timeline)
            assert any(item.operation == "bootstrap" for item in timeline)
    finally:
        engine.dispose()


def test_safe_adoption_preserves_previous_ocr_objects(tmp_path: Path) -> None:
    root, decisions, engine, _old_run_id, new_run_id = _project(tmp_path)
    try:
        with session_scope(engine) as session:
            bootstrap_editable_layer(
                session,
                decisions=decisions,
                created_by="Alex",
                source_keys={"doc_candidates"},
            )
        with session_scope(engine) as session:
            assessment = assess_candidate_adoption(
                session,
                source_key="doc_candidates",
                page=1,
                candidate_run_id=new_run_id,
            )
            assert assessment.code == ADOPTION_SAFE
            result = adopt_candidate_page(
                session,
                decisions=decisions,
                source_key="doc_candidates",
                page=1,
                candidate_run_id=new_run_id,
                adopted_by="Alex",
            )
            assert result.objects_activated == 1
            assert result.objects_retired == 2
        with session_scope(engine) as session:
            objects = session.scalars(select(EditableObject)).all()
            assert sum(item.lifecycle_status == "active" for item in objects) == 1
            assert sum(item.lifecycle_status == "deleted" for item in objects) == 2
            assert any(
                item.operation == "candidate_adopted"
                for item in page_history_rows(session, source_key="doc_candidates", page=1)
            )
    finally:
        engine.dispose()


def test_human_edit_blocks_automatic_adoption(tmp_path: Path) -> None:
    _root, decisions, engine, old_run_id, new_run_id = _project(tmp_path)
    try:
        with session_scope(engine) as session:
            bootstrap_editable_layer(
                session,
                decisions=decisions,
                created_by="Alex",
                source_keys={"doc_candidates"},
            )
        with session_scope(engine) as session:
            obj = session.scalar(
                select(EditableObject)
                .where(EditableObject.lifecycle_status == "active")
                .order_by(EditableObject.current_order_index)
            )
            assert obj
            update_editable_object(
                session,
                decisions=decisions,
                object_id=obj.id,
                expected_revision=obj.revision_number,
                edited_by="Alex",
                text="Corrección humana",
            )
        with session_scope(engine) as session:
            assessment = assess_candidate_adoption(
                session,
                source_key="doc_candidates",
                page=1,
                candidate_run_id=new_run_id,
            )
            assert assessment.code == ADOPTION_MANUAL
            assert any("correcciones" in reason for reason in assessment.blocking_reasons)
            with pytest.raises(ValueError, match="no reemplazará"):
                adopt_candidate_page(
                    session,
                    decisions=decisions,
                    source_key="doc_candidates",
                    page=1,
                    candidate_run_id=new_run_id,
                    adopted_by="Alex",
                )
            selection = session.scalar(select(ExtractionPageSelection))
            assert selection and selection.extraction_run_id == old_run_id
    finally:
        engine.dispose()


def test_manual_resolution_keeps_human_edits_and_records_decision(tmp_path: Path) -> None:
    _root, decisions, engine, _old_run_id, new_run_id = _project(tmp_path)
    try:
        with session_scope(engine) as session:
            bootstrap_editable_layer(
                session,
                decisions=decisions,
                created_by="Alex",
                source_keys={"doc_candidates"},
            )
        with session_scope(engine) as session:
            obj = session.scalar(
                select(EditableObject)
                .where(EditableObject.lifecycle_status == "active")
                .order_by(EditableObject.current_order_index)
            )
            assert obj is not None
            update_editable_object(
                session,
                decisions=decisions,
                object_id=obj.id,
                expected_revision=obj.revision_number,
                edited_by="Alex",
                text="Corrección humana preservada",
            )
            original_object_count = len(session.scalars(select(EditableObject)).all())

        with session_scope(engine) as session:
            result = resolve_candidate_keep_edits(
                session,
                source_key="doc_candidates",
                page=1,
                candidate_run_id=new_run_id,
                resolved_by="Alex",
                note="Comparada visualmente",
            )
            assert result.retained_objects == original_object_count
            assert result.candidate_objects_not_imported == 1

        with session_scope(engine) as session:
            page = session.scalar(select(EditablePage))
            selection = session.scalar(select(ExtractionPageSelection))
            objects = session.scalars(select(EditableObject)).all()
            assert page is not None and selection is not None
            assert page.source_extraction_run_id == new_run_id
            assert page.status == "active"
            assert selection.extraction_run_id == new_run_id
            assert len(objects) == original_object_count
            assert any(item.current_text == "Corrección humana preservada" for item in objects)
            revision = session.scalar(
                select(EditablePageRevision)
                .where(EditablePageRevision.operation == "manual_keep_edits")
            )
            assert revision is not None
            baseline_event = session.scalar(
                select(ExchangeChangeEvent).where(
                    ExchangeChangeEvent.entity_type == "editable_page_baseline"
                )
            )
            assert baseline_event is not None
            assert revision.details_json["strategy"] == "keep_existing_editable_objects"
            timeline = page_history_rows(session, source_key="doc_candidates", page=1)
            assert any(item.operation == "manual_keep_edits" for item in timeline)
    finally:
        engine.dispose()


def test_rebase_preserves_annotations_across_fragmentation(tmp_path: Path) -> None:
    from archive_workbench.db.models import (
        EditableObjectComment,
        EditableObjectTag,
        EntityMention,
        EntityMentionRevision,
    )
    from archive_workbench.editable_rebase import apply_editable_rebase, preview_editable_rebase

    _root, decisions, engine, _old_run_id, new_run_id = _project(tmp_path)
    try:
        with session_scope(engine) as session:
            candidate = session.scalar(
                select(ExtractedObject).where(ExtractedObject.extraction_run_id == new_run_id)
            )
            assert candidate is not None
            candidate.original_text = "Título viejo\n\nTexto viejo"
            bootstrap_editable_layer(
                session,
                decisions=decisions,
                created_by="Alex",
                source_keys={"doc_candidates"},
            )
            old_objects = session.scalars(
                select(EditableObject)
                .where(EditableObject.lifecycle_status == "active")
                .order_by(EditableObject.current_order_index)
            ).all()
            assert len(old_objects) == 2
            target = old_objects[1]
            session.add(
                EntityMention(
                    id=new_id(),
                    editable_object_id=target.id,
                    authority_id=None,
                    mention_text="Texto",
                    normalized_text="texto",
                    start_offset=0,
                    end_offset=5,
                    object_revision_number=target.revision_number,
                    status="pending",
                    source="manual",
                    confidence=None,
                    note=None,
                    created_by="Alex",
                    updated_by="Alex",
                    revision=1,
                )
            )
            session.add(
                EditableObjectComment(
                    id=new_id(), editable_object_id=target.id, body="Comentario", created_by="Alex"
                )
            )
            session.add(
                EditableObjectTag(
                    id=new_id(),
                    editable_object_id=target.id,
                    tag="relevante",
                    normalized_tag="relevante",
                    tag_kind="unclassified",
                    created_by="Alex",
                )
            )

        with session_scope(engine) as session:
            preview = preview_editable_rebase(
                session,
                source_key="doc_candidates",
                page=1,
                candidate_run_id=new_run_id,
            )
            assert preview.can_apply is True
            assert preview.old_object_count == 2
            assert preview.new_object_count == 1
            assert preview.mention_count == 1
            result = apply_editable_rebase(
                session,
                decisions=decisions,
                source_key="doc_candidates",
                page=1,
                candidate_run_id=new_run_id,
                expected_page_revision=preview.expected_page_revision,
                rebased_by="Alex",
            )
            assert result.new_objects_created == 1
            assert result.old_objects_retired == 2
            assert result.mentions_relocated == 1
            assert result.comments_relocated == 1
            assert result.tags_relocated == 1

        with session_scope(engine) as session:
            active = session.scalars(
                select(EditableObject).where(EditableObject.lifecycle_status == "active")
            ).all()
            assert len(active) == 1
            assert active[0].current_text == "Título viejo\n\nTexto viejo"
            mention = session.scalar(select(EntityMention))
            assert mention is not None
            assert mention.editable_object_id == active[0].id
            assert active[0].current_text[mention.start_offset : mention.end_offset] == "Texto"
            assert mention.object_revision_number == active[0].revision_number
            assert session.scalar(
                select(EntityMentionRevision).where(
                    EntityMentionRevision.operation == "rebase_relocate"
                )
            ) is not None
            page_revision = session.scalar(
                select(EditablePageRevision).where(EditablePageRevision.operation == "rebase")
            )
            assert page_revision is not None
            assert page_revision.details_json["strategy"] == "three_way_text_rebase"
    finally:
        engine.dispose()


def test_rebase_reapplies_human_correction_over_better_candidate(tmp_path: Path) -> None:
    from archive_workbench.editable_rebase import apply_editable_rebase, preview_editable_rebase

    _root, decisions, engine, _old_run_id, new_run_id = _project(tmp_path)
    try:
        with session_scope(engine) as session:
            candidate = session.scalar(
                select(ExtractedObject).where(ExtractedObject.extraction_run_id == new_run_id)
            )
            assert candidate is not None
            candidate.original_text = "Título viejo\n\nTexto viejo ampliado"
            bootstrap_editable_layer(
                session,
                decisions=decisions,
                created_by="Alex",
                source_keys={"doc_candidates"},
            )
            first = session.scalar(
                select(EditableObject)
                .where(EditableObject.lifecycle_status == "active")
                .order_by(EditableObject.current_order_index)
            )
            assert first is not None
            update_editable_object(
                session,
                decisions=decisions,
                object_id=first.id,
                expected_revision=first.revision_number,
                edited_by="Alex",
                text="Título corregido",
            )

        with session_scope(engine) as session:
            preview = preview_editable_rebase(
                session,
                source_key="doc_candidates",
                page=1,
                candidate_run_id=new_run_id,
            )
            assert preview.can_apply is True
            assert "Título corregido" in preview.rebased_text
            assert "ampliado" in preview.rebased_text
            apply_editable_rebase(
                session,
                decisions=decisions,
                source_key="doc_candidates",
                page=1,
                candidate_run_id=new_run_id,
                expected_page_revision=preview.expected_page_revision,
                rebased_by="Alex",
            )

        with session_scope(engine) as session:
            active = session.scalar(
                select(EditableObject).where(EditableObject.lifecycle_status == "active")
            )
            assert active is not None
            assert active.current_text == "Título corregido\n\nTexto viejo ampliado"
    finally:
        engine.dispose()


def test_rebase_conflict_blocks_all_changes(tmp_path: Path) -> None:
    from archive_workbench.editable_rebase import apply_editable_rebase, preview_editable_rebase

    _root, decisions, engine, old_run_id, new_run_id = _project(tmp_path)
    try:
        with session_scope(engine) as session:
            candidate = session.scalar(
                select(ExtractedObject).where(ExtractedObject.extraction_run_id == new_run_id)
            )
            assert candidate is not None
            candidate.original_text = "Encabezado completamente distinto\n\nTexto viejo"
            bootstrap_editable_layer(
                session,
                decisions=decisions,
                created_by="Alex",
                source_keys={"doc_candidates"},
            )
            first = session.scalar(
                select(EditableObject)
                .where(EditableObject.lifecycle_status == "active")
                .order_by(EditableObject.current_order_index)
            )
            assert first is not None
            update_editable_object(
                session,
                decisions=decisions,
                object_id=first.id,
                expected_revision=first.revision_number,
                edited_by="Alex",
                text="Título corregido por una persona",
            )

        with session_scope(engine) as session:
            preview = preview_editable_rebase(
                session,
                source_key="doc_candidates",
                page=1,
                candidate_run_id=new_run_id,
            )
            assert preview.can_apply is False
            assert preview.text_conflicts
            with pytest.raises(ValueError, match="conflictos"):
                apply_editable_rebase(
                    session,
                    decisions=decisions,
                    source_key="doc_candidates",
                    page=1,
                    candidate_run_id=new_run_id,
                    expected_page_revision=preview.expected_page_revision,
                    rebased_by="Alex",
                )

        with session_scope(engine) as session:
            selection = session.scalar(select(ExtractionPageSelection))
            assert selection is not None
            assert selection.extraction_run_id == old_run_id
            assert session.scalar(
                select(EditablePageRevision).where(EditablePageRevision.operation == "rebase")
            ) is None
    finally:
        engine.dispose()


def test_rebase_duplicate_mentions_can_be_resolved_by_rejecting_one(tmp_path: Path) -> None:
    from archive_workbench.db.models import EntityMention, EntityMentionRevision
    from archive_workbench.editable_rebase import apply_editable_rebase, preview_editable_rebase

    _root, decisions, engine, _old_run_id, new_run_id = _project(tmp_path)
    try:
        with session_scope(engine) as session:
            candidate = session.scalar(
                select(ExtractedObject).where(ExtractedObject.extraction_run_id == new_run_id)
            )
            assert candidate is not None
            candidate.original_text = "Texto nuevo y más completo"
            bootstrap_editable_layer(
                session,
                decisions=decisions,
                created_by="Alex",
                source_keys={"doc_candidates"},
            )
            target = session.scalar(
                select(EditableObject)
                .where(
                    EditableObject.lifecycle_status == "active",
                    EditableObject.current_text == "Texto viejo",
                )
            )
            assert target is not None
            mention_ids: list[str] = []
            for _ in range(2):
                mention_id = new_id()
                mention_ids.append(mention_id)
                session.add(
                    EntityMention(
                        id=mention_id,
                        editable_object_id=target.id,
                        authority_id=None,
                        mention_text="Texto",
                        normalized_text="texto",
                        start_offset=0,
                        end_offset=5,
                        object_revision_number=target.revision_number,
                        status="pending",
                        source="manual",
                        confidence=None,
                        note=None,
                        created_by="Alex",
                        updated_by="Alex",
                        revision=1,
                    )
                )

        with session_scope(engine) as session:
            preview = preview_editable_rebase(
                session,
                source_key="doc_candidates",
                page=1,
                candidate_run_id=new_run_id,
            )
            assert preview.can_apply is False
            assert {item.reason_code for item in preview.mention_conflicts} == {
                "duplicate_target"
            }
            assert {item.mention_id for item in preview.mention_conflicts} == set(mention_ids)

            resolutions = {
                mention_ids[0]: {
                    "action": "reject",
                    "method": "manual_duplicate_rejection",
                }
            }
            resolved = preview_editable_rebase(
                session,
                source_key="doc_candidates",
                page=1,
                candidate_run_id=new_run_id,
                mention_resolutions=resolutions,
            )
            assert resolved.can_apply is True
            result = apply_editable_rebase(
                session,
                decisions=decisions,
                source_key="doc_candidates",
                page=1,
                candidate_run_id=new_run_id,
                expected_page_revision=resolved.expected_page_revision,
                rebased_by="Alex",
                mention_resolutions=resolutions,
            )
            assert result.mentions_relocated == 1
            assert result.mentions_rejected == 1

        with session_scope(engine) as session:
            mentions = session.scalars(select(EntityMention).order_by(EntityMention.id)).all()
            assert sorted(item.status for item in mentions) == ["pending", "rejected"]
            relocated = next(item for item in mentions if item.status != "rejected")
            active_object = session.get(EditableObject, relocated.editable_object_id)
            assert active_object is not None
            assert active_object.lifecycle_status == "active"
            assert active_object.current_text[relocated.start_offset : relocated.end_offset] == "Texto"
            operations = set(
                session.scalars(select(EntityMentionRevision.operation)).all()
            )
            assert "rebase_relocate" in operations
            assert "rebase_reject_conflict" in operations
    finally:
        engine.dispose()


def test_rebase_manual_mention_resolution_can_change_anchor_text(tmp_path: Path) -> None:
    from archive_workbench.db.models import EntityMention, EntityMentionRevision
    from archive_workbench.editable_rebase import apply_editable_rebase, preview_editable_rebase

    _root, decisions, engine, old_run_id, new_run_id = _project(tmp_path)
    try:
        with session_scope(engine) as session:
            old_objects = session.scalars(
                select(ExtractedObject)
                .where(ExtractedObject.extraction_run_id == old_run_id)
                .order_by(ExtractedObject.order_index)
            ).all()
            assert len(old_objects) == 2
            old_objects[1].original_text = "SI. CHUBUT"
            candidate = session.scalar(
                select(ExtractedObject).where(ExtractedObject.extraction_run_id == new_run_id)
            )
            assert candidate is not None
            candidate.original_text = "Destinatario: S.I. CHUBUT"
            bootstrap_editable_layer(
                session,
                decisions=decisions,
                created_by="Alex",
                source_keys={"doc_candidates"},
            )
            target = session.scalar(
                select(EditableObject).where(
                    EditableObject.lifecycle_status == "active",
                    EditableObject.current_text == "SI. CHUBUT",
                )
            )
            assert target is not None
            mention_id = new_id()
            session.add(
                EntityMention(
                    id=mention_id,
                    editable_object_id=target.id,
                    authority_id=None,
                    mention_text="SI. CHUBUT",
                    normalized_text="si. chubut",
                    start_offset=0,
                    end_offset=10,
                    object_revision_number=target.revision_number,
                    status="pending",
                    source="manual",
                    confidence=None,
                    note=None,
                    created_by="Alex",
                    updated_by="Alex",
                    revision=1,
                )
            )

        with session_scope(engine) as session:
            preview = preview_editable_rebase(
                session,
                source_key="doc_candidates",
                page=1,
                candidate_run_id=new_run_id,
            )
            assert preview.can_apply is False
            assert len(preview.mention_conflicts) == 1
            assert preview.mention_conflicts[0].reason_code == "missing_exact"
            target_text = preview.candidate_objects[0].rebased_text
            start = target_text.index("S.I. CHUBUT")
            end = start + len("S.I. CHUBUT")
            resolutions = {
                mention_id: {
                    "action": "relocate",
                    "target_index": 0,
                    "start_offset": start,
                    "end_offset": end,
                    "matched_text": "S.I. CHUBUT",
                    "method": "manual_exact_fragment",
                }
            }
            resolved = preview_editable_rebase(
                session,
                source_key="doc_candidates",
                page=1,
                candidate_run_id=new_run_id,
                mention_resolutions=resolutions,
            )
            assert resolved.can_apply is True
            result = apply_editable_rebase(
                session,
                decisions=decisions,
                source_key="doc_candidates",
                page=1,
                candidate_run_id=new_run_id,
                expected_page_revision=resolved.expected_page_revision,
                rebased_by="Alex",
                mention_resolutions=resolutions,
            )
            assert result.mentions_relocated == 1
            assert result.mentions_rejected == 0

        with session_scope(engine) as session:
            mention = session.get(EntityMention, mention_id)
            assert mention is not None
            assert mention.mention_text == "S.I. CHUBUT"
            assert mention.normalized_text == "s.i. chubut"
            target = session.get(EditableObject, mention.editable_object_id)
            assert target is not None
            assert target.current_text[mention.start_offset : mention.end_offset] == "S.I. CHUBUT"
            revision = session.scalar(
                select(EntityMentionRevision).where(
                    EntityMentionRevision.operation == "rebase_relocate_manual"
                )
            )
            assert revision is not None
    finally:
        engine.dispose()


def _text_conflict_project(tmp_path: Path):
    root, decisions, engine, old_run_id, new_run_id = _project(tmp_path)
    with session_scope(engine) as session:
        candidate = session.scalar(
            select(ExtractedObject).where(ExtractedObject.extraction_run_id == new_run_id)
        )
        assert candidate is not None
        candidate.original_text = "Encabezado completamente distinto\n\nTexto viejo"
        bootstrap_editable_layer(
            session,
            decisions=decisions,
            created_by="Alex",
            source_keys={"doc_candidates"},
        )
        first = session.scalar(
            select(EditableObject)
            .where(EditableObject.lifecycle_status == "active")
            .order_by(EditableObject.current_order_index)
        )
        assert first is not None
        update_editable_object(
            session,
            decisions=decisions,
            object_id=first.id,
            expected_revision=first.revision_number,
            edited_by="Alex",
            text="Título corregido por una persona",
        )
    return root, decisions, engine, old_run_id, new_run_id


def test_rebase_text_conflict_can_reapply_human_correction(tmp_path: Path) -> None:
    from archive_workbench.editable_rebase import apply_editable_rebase, preview_editable_rebase

    _root, decisions, engine, _old_run_id, new_run_id = _text_conflict_project(tmp_path)
    try:
        with session_scope(engine) as session:
            preview = preview_editable_rebase(
                session,
                source_key="doc_candidates",
                page=1,
                candidate_run_id=new_run_id,
            )
            assert preview.can_apply is False
            assert len(preview.text_conflicts) == 1
            conflict = preview.text_conflicts[0]
            assert conflict.base_text == "viejo"
            assert conflict.human_text == "corregido por una persona"
            assert conflict.candidate_text == "completamente distinto"
            resolutions = {
                conflict.conflict_id: {
                    "action": "apply_human",
                    "expected_candidate_text": conflict.candidate_text,
                    "expected_human_text": conflict.human_text,
                    "method": "manual_apply_human",
                }
            }
            resolved = preview_editable_rebase(
                session,
                source_key="doc_candidates",
                page=1,
                candidate_run_id=new_run_id,
                text_resolutions=resolutions,
            )
            assert resolved.can_apply is True
            assert resolved.text_conflicts == []
            assert resolved.rebased_text.startswith("Encabezado corregido por una persona")
            apply_editable_rebase(
                session,
                decisions=decisions,
                source_key="doc_candidates",
                page=1,
                candidate_run_id=new_run_id,
                expected_page_revision=resolved.expected_page_revision,
                rebased_by="Alex",
                text_resolutions=resolutions,
            )

        with session_scope(engine) as session:
            active = session.scalar(
                select(EditableObject)
                .where(EditableObject.lifecycle_status == "active")
                .order_by(EditableObject.current_order_index)
            )
            assert active is not None
            assert active.current_text.startswith("Encabezado corregido por una persona")
            revision = session.scalar(
                select(EditablePageRevision).where(EditablePageRevision.operation == "rebase")
            )
            assert revision is not None
            assert revision.details_json["manual_text_resolution_count"] == 1
            assert revision.details_json["text_resolution_methods"] == [
                "manual_apply_human"
            ]
    finally:
        engine.dispose()


def test_rebase_text_conflict_can_keep_candidate_or_use_manual_text(tmp_path: Path) -> None:
    from archive_workbench.editable_rebase import preview_editable_rebase

    _root, _decisions, engine, _old_run_id, new_run_id = _text_conflict_project(tmp_path)
    try:
        with session_scope(engine) as session:
            preview = preview_editable_rebase(
                session,
                source_key="doc_candidates",
                page=1,
                candidate_run_id=new_run_id,
            )
            conflict = preview.text_conflicts[0]
            common = {
                "expected_candidate_text": conflict.candidate_text,
                "expected_human_text": conflict.human_text,
            }
            kept = preview_editable_rebase(
                session,
                source_key="doc_candidates",
                page=1,
                candidate_run_id=new_run_id,
                text_resolutions={
                    conflict.conflict_id: {
                        **common,
                        "action": "keep_candidate",
                    }
                },
            )
            assert kept.can_apply is True
            assert kept.rebased_text.startswith("Encabezado completamente distinto")

            manual = preview_editable_rebase(
                session,
                source_key="doc_candidates",
                page=1,
                candidate_run_id=new_run_id,
                text_resolutions={
                    conflict.conflict_id: {
                        **common,
                        "action": "manual_text",
                        "manual_text": "Título conciliado",
                    }
                },
            )
            assert manual.can_apply is True
            assert "Título conciliado" in manual.rebased_text
    finally:
        engine.dispose()


def test_rebase_rejects_stale_text_resolution(tmp_path: Path) -> None:
    from archive_workbench.editable_rebase import preview_editable_rebase

    _root, _decisions, engine, _old_run_id, new_run_id = _text_conflict_project(tmp_path)
    try:
        with session_scope(engine) as session:
            preview = preview_editable_rebase(
                session,
                source_key="doc_candidates",
                page=1,
                candidate_run_id=new_run_id,
            )
            conflict = preview.text_conflicts[0]
            stale = preview_editable_rebase(
                session,
                source_key="doc_candidates",
                page=1,
                candidate_run_id=new_run_id,
                text_resolutions={
                    conflict.conflict_id: {
                        "action": "apply_human",
                        "expected_candidate_text": "otra candidata",
                        "expected_human_text": conflict.human_text,
                    }
                },
            )
            assert stale.can_apply is False
            assert stale.text_conflicts[0].reason_code == "invalid_resolution"
    finally:
        engine.dispose()


def test_rebase_can_return_to_a_previously_used_candidate(tmp_path: Path) -> None:
    """A → B → A → B must preserve history without violating source uniqueness."""
    from archive_workbench.editable_rebase import apply_editable_rebase, preview_editable_rebase

    _root, decisions, engine, old_run_id, new_run_id = _project(tmp_path)
    try:
        with session_scope(engine) as session:
            bootstrap_editable_layer(
                session,
                decisions=decisions,
                created_by="Alex",
                source_keys={"doc_candidates"},
            )

        for candidate_run_id in (new_run_id, old_run_id, new_run_id):
            with session_scope(engine) as session:
                preview = preview_editable_rebase(
                    session,
                    source_key="doc_candidates",
                    page=1,
                    candidate_run_id=candidate_run_id,
                )
                assert preview.can_apply is True
                apply_editable_rebase(
                    session,
                    decisions=decisions,
                    source_key="doc_candidates",
                    page=1,
                    candidate_run_id=candidate_run_id,
                    expected_page_revision=preview.expected_page_revision,
                    rebased_by="Alex",
                )

        with session_scope(engine) as session:
            active = session.scalars(
                select(EditableObject)
                .where(EditableObject.lifecycle_status == "active")
                .order_by(EditableObject.current_order_index)
            ).all()
            expected_sources = {
                row.id
                for row in session.scalars(
                    select(ExtractedObject).where(
                        ExtractedObject.extraction_run_id == new_run_id
                    )
                ).all()
            }
            assert {row.source_extracted_object_id for row in active} == expected_sources

            historical = session.scalars(
                select(EditableObject).where(EditableObject.lifecycle_status == "deleted")
            ).all()
            assert historical
            released = [
                source_id
                for row in historical
                for source_id in row.current_attributes_json.get(
                    "historical_source_extracted_object_ids", []
                )
            ]
            assert released

            page_revisions = session.scalars(
                select(EditablePageRevision)
                .where(EditablePageRevision.operation == "rebase")
                .order_by(EditablePageRevision.revision_number)
            ).all()
            assert len(page_revisions) == 3
            assert any(
                row.details_json.get("source_links_released", 0) > 0
                for row in page_revisions[1:]
            )
    finally:
        engine.dispose()


def test_bulk_prepare_candidate_run_initializes_only_pending_page(tmp_path: Path) -> None:
    root, decisions, engine, _old_run_id, new_run_id = _project(tmp_path)
    from archive_workbench.candidate_review import prepare_candidate_run_for_review

    try:
        with session_scope(engine) as session:
            result = prepare_candidate_run_for_review(
                session,
                decisions=decisions,
                source_key="doc_candidates",
                run_id=new_run_id,
                created_by="Alex",
            )
            assert result.pages_available == 1
            assert result.pages_initialized == 1
            assert result.pages_already_initialized == 0
            assert result.selections_changed == 1
            assert result.objects_created == 1

        with session_scope(engine) as session:
            page = session.scalar(select(EditablePage))
            selection = session.scalar(select(ExtractionPageSelection))
            assert page is not None
            assert selection is not None
            assert page.source_extraction_run_id == new_run_id
            assert selection.extraction_run_id == new_run_id
            repeated = prepare_candidate_run_for_review(
                session,
                decisions=decisions,
                source_key="doc_candidates",
                run_id=new_run_id,
                created_by="Alex",
            )
            assert repeated.pages_initialized == 0
            assert repeated.pages_already_initialized == 1
            assert repeated.selections_changed == 0
    finally:
        engine.dispose()


def test_regional_text_replacement_changes_one_editable_object_and_keeps_page_source(
    tmp_path: Path,
) -> None:
    root, decisions, engine, old_run_id, _new_run_id = _project(tmp_path)
    from archive_workbench.candidate_review import (
        replace_editable_object_text_from_regional_candidate,
    )

    try:
        with session_scope(engine) as session:
            bootstrap_editable_layer(
                session,
                decisions=decisions,
                created_by="Alex",
                source_keys={"doc_candidates"},
            )
            regional_run = _seed_run(
                session,
                profile="regional_test",
                text_rows=[("paragraph", "DR. GUILLERMO A. BELGRANO RAWSON")],
                options_hash="c" * 64,
            )
            regional_run.engine = "tesseract_regions"
            regional_object = session.scalar(
                select(ExtractedObject).where(
                    ExtractedObject.extraction_run_id == regional_run.id
                )
            )
            assert regional_object is not None
            editable_page = session.scalar(select(EditablePage))
            editable_objects = session.scalars(
                select(EditableObject)
                .where(EditableObject.editable_page_id == editable_page.id)
                .order_by(EditableObject.current_order_index)
            ).all()
            target = editable_objects[1]
            untouched = editable_objects[0]
            untouched_text = untouched.current_text
            result = replace_editable_object_text_from_regional_candidate(
                session,
                source_key="doc_candidates",
                page=1,
                candidate_run_id=regional_run.id,
                editable_object_id=target.id,
                regional_object_id=regional_object.id,
                changed_by="Alex",
            )
            assert result.previous_text == "Texto viejo"
            assert result.replacement_text == "DR. GUILLERMO A. BELGRANO RAWSON"
            assert editable_page.source_extraction_run_id == old_run_id
            assert target.current_text == "DR. GUILLERMO A. BELGRANO RAWSON"
            assert untouched.current_text == untouched_text
            assert target.current_attributes_json["regional_ocr_text_replacements"][-1][
                "regional_run_id"
            ] == regional_run.id

        with session_scope(engine) as session:
            timeline = page_history_rows(session, source_key="doc_candidates", page=1)
            assert any(item.operation == "regional_ocr_replace" for item in timeline)
    finally:
        engine.dispose()


def test_regional_text_can_be_added_as_new_editable_object_with_provenance(
    tmp_path: Path,
) -> None:
    root, decisions, engine, old_run_id, _new_run_id = _project(tmp_path)
    from archive_workbench.candidate_review import (
        add_editable_object_from_regional_candidate,
    )

    try:
        with session_scope(engine) as session:
            bootstrap_editable_layer(
                session,
                decisions=decisions,
                created_by="Alex",
                source_keys={"doc_candidates"},
            )
            regional_run = _seed_run(
                session,
                profile="regional_add_test",
                text_rows=[("paragraph", "SUBSECRETARIO DEL INTERIOR")],
                options_hash="d" * 64,
            )
            regional_run.engine = "tesseract_regions"
            regional_object = session.scalar(
                select(ExtractedObject).where(
                    ExtractedObject.extraction_run_id == regional_run.id
                )
            )
            assert regional_object is not None
            editable_page = session.scalar(select(EditablePage))
            before = session.scalars(
                select(EditableObject)
                .where(
                    EditableObject.editable_page_id == editable_page.id,
                    EditableObject.lifecycle_status == "active",
                )
                .order_by(EditableObject.current_order_index)
            ).all()
            anchor = before[0]
            placement_geometry = [
                {
                    "page": 1,
                    "coordinate_space": "normalized",
                    "polygon": [[0.10, 0.10], [0.35, 0.10], [0.35, 0.18], [0.10, 0.18]],
                }
            ]
            result = add_editable_object_from_regional_candidate(
                session,
                decisions=decisions,
                source_key="doc_candidates",
                page=1,
                candidate_run_id=regional_run.id,
                regional_object_id=regional_object.id,
                object_type="paragraph",
                changed_by="Alex",
                after_object_id=anchor.id,
                geometry=placement_geometry,
            )
            added = session.get(EditableObject, result.editable_object_id)
            assert added is not None
            assert added.current_text == "SUBSECRETARIO DEL INTERIOR"
            assert added.source_extracted_object_id is None
            assert added.current_attributes_json["regional_ocr_added"] is True
            assert added.current_attributes_json["regional_ocr_source"][
                "regional_run_id"
            ] == regional_run.id
            assert added.current_geometry_json == placement_geometry
            assert added.current_attributes_json["regional_ocr_source"]["source_geometry"] == regional_object.geometry_json
            assert added.current_attributes_json["regional_ocr_source"]["placement_geometry_defined_by_user"] is True
            assert editable_page.source_extraction_run_id == old_run_id
            active = session.scalars(
                select(EditableObject).where(
                    EditableObject.editable_page_id == editable_page.id,
                    EditableObject.lifecycle_status == "active",
                )
            ).all()
            assert len(active) == len(before) + 1

        with session_scope(engine) as session:
            timeline = page_history_rows(session, source_key="doc_candidates", page=1)
            assert any(item.operation == "regional_ocr_add" for item in timeline)
    finally:
        engine.dispose()
