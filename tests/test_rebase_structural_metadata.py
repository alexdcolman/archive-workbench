from __future__ import annotations

from sqlalchemy import select

from archive_workbench.db import session_scope
from archive_workbench.db.models import (
    DocumentPart,
    EditableObject,
    EditableObjectComment,
    EditableObjectTag,
    EditablePage,
    EditablePageAction,
    EditablePageRevision,
    ExtractedObject,
)
from archive_workbench.editable_rebase import apply_editable_rebase, preview_editable_rebase
from archive_workbench.editing import bootstrap_editable_layer
from archive_workbench.identity import new_id
from archive_workbench.page_actions import capture_page_snapshot
from tests.test_candidate_review import _project


def test_structural_action_history_is_absorbed_from_current_snapshot(tmp_path) -> None:
    _root, decisions, engine, _old_run_id, new_run_id = _project(tmp_path)
    try:
        with session_scope(engine) as session:
            bootstrap_editable_layer(
                session,
                decisions=decisions,
                created_by="Alex",
                source_keys={"doc_candidates"},
            )
            page = session.scalar(select(EditablePage))
            assert page is not None
            snapshot = capture_page_snapshot(session, page.id)
            session.add(
                EditablePageAction(
                    id=new_id(),
                    editable_page_id=page.id,
                    sequence_number=1,
                    action_type="split",
                    status="active",
                    before_snapshot_json=snapshot,
                    after_snapshot_json=snapshot,
                    selected_object_id=None,
                    note="Acción histórica ya materializada",
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
            assert preview.structural_action_count == 1
            assert preview.conflicts == []
            assert preview.can_apply is True
            result = apply_editable_rebase(
                session,
                decisions=decisions,
                source_key="doc_candidates",
                page=1,
                candidate_run_id=new_run_id,
                expected_page_revision=preview.expected_page_revision,
                rebased_by="Alex",
            )
            assert result.structural_actions_absorbed == 1

        with session_scope(engine) as session:
            revision = session.scalar(
                select(EditablePageRevision).where(EditablePageRevision.operation == "rebase")
            )
            assert revision is not None
            assert revision.details_json["structural_actions_absorbed"] == 1
    finally:
        engine.dispose()


def test_metadata_conflicts_are_resolved_and_duplicate_tags_are_preserved_in_history(tmp_path) -> None:
    _root, decisions, engine, _old_run_id, new_run_id = _project(tmp_path)
    try:
        with session_scope(engine) as session:
            candidate = session.scalar(
                select(ExtractedObject).where(ExtractedObject.extraction_run_id == new_run_id)
            )
            assert candidate is not None
            candidate.original_text = "Título viejo\n\nTexto viejo"
            candidate.object_type = "paragraph"
            bootstrap_editable_layer(
                session,
                decisions=decisions,
                created_by="Alex",
                source_keys={"doc_candidates"},
            )
            rows = session.scalars(
                select(EditableObject)
                .where(EditableObject.lifecycle_status == "active")
                .order_by(EditableObject.current_order_index)
            ).all()
            assert len(rows) == 2
            part_a = DocumentPart(
                id=new_id(),
                digital_object_id=rows[0].digital_object_id,
                part_key="parte_a",
                title="Parte A",
                part_type="document",
                page_start=1,
                page_end=1,
                page_sequence_json=[1],
                status="provisional",
                created_by="Alex",
            )
            part_b = DocumentPart(
                id=new_id(),
                digital_object_id=rows[0].digital_object_id,
                part_key="parte_b",
                title="Parte B",
                part_type="document",
                page_start=1,
                page_end=1,
                page_sequence_json=[1],
                status="provisional",
                created_by="Alex",
            )
            session.add_all([part_a, part_b])
            session.flush()
            rows[0].document_part_id = part_a.id
            rows[1].document_part_id = part_b.id
            rows[0].review_status = "reviewed"
            rows[1].review_status = "in_review"
            rows[0].current_object_type = "section_heading"
            for row in rows:
                session.add(
                    EditableObjectTag(
                        id=new_id(),
                        editable_object_id=row.id,
                        tag="relevante",
                        normalized_tag="relevante",
                        tag_kind="unclassified",
                        created_by="Alex",
                    )
                )
            part_a_id = part_a.id

        with session_scope(engine) as session:
            preview = preview_editable_rebase(
                session,
                source_key="doc_candidates",
                page=1,
                candidate_run_id=new_run_id,
            )
            assert preview.can_apply is False
            assert {item.kind for item in preview.metadata_conflicts} == {
                "document_part",
                "review_status",
                "object_type",
            }
            resolutions = {}
            for conflict in preview.metadata_conflicts:
                chosen = {
                    "document_part": part_a_id,
                    "review_status": "reviewed",
                    "object_type": "section_heading",
                }[conflict.kind]
                resolutions[conflict.conflict_id] = {
                    "action": "select",
                    "value": chosen,
                    "expected_values": [item.value for item in conflict.options],
                    "method": "manual_metadata_selection",
                }
            resolved = preview_editable_rebase(
                session,
                source_key="doc_candidates",
                page=1,
                candidate_run_id=new_run_id,
                metadata_resolutions=resolutions,
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
                metadata_resolutions=resolutions,
            )
            assert result.metadata_resolutions_applied == 3
            assert result.tags_relocated == 1
            assert result.tags_deduplicated == 1

        with session_scope(engine) as session:
            active = session.scalar(
                select(EditableObject).where(EditableObject.lifecycle_status == "active")
            )
            assert active is not None
            assert active.document_part_id == part_a_id
            assert active.review_status == "reviewed"
            assert active.current_object_type == "section_heading"
            active_tags = session.scalars(
                select(EditableObjectTag).where(EditableObjectTag.editable_object_id == active.id)
            ).all()
            assert len(active_tags) == 1
            historical_tags = session.scalars(select(EditableObjectTag)).all()
            assert len(historical_tags) == 2
            revision = session.scalar(
                select(EditablePageRevision).where(EditablePageRevision.operation == "rebase")
            )
            assert revision is not None
            assert revision.details_json["manual_metadata_resolution_count"] == 3
            assert revision.details_json["tags_deduplicated"] == 1
    finally:
        engine.dispose()


def test_low_confidence_annotated_object_requires_manual_projection(tmp_path) -> None:
    _root, decisions, engine, _old_run_id, new_run_id = _project(tmp_path)
    try:
        with session_scope(engine) as session:
            candidate = session.scalar(
                select(ExtractedObject).where(ExtractedObject.extraction_run_id == new_run_id)
            )
            assert candidate is not None
            candidate.original_text = "Contenido completamente distinto sin correspondencia textual"
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
            session.add(
                EditableObjectComment(
                    id=new_id(),
                    editable_object_id=first.id,
                    body="Comentario que debe conservarse",
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
            assert preview.can_apply is False
            assert len(preview.projection_conflicts) == 1
            conflict = preview.projection_conflicts[0]
            assert conflict.source_order_index == 0
            assert conflict.candidates
            resolution = {
                conflict.conflict_id: {
                    "action": "map",
                    "target_index": conflict.candidates[0].target_index,
                    "expected_candidate_ids": [
                        item.source_object_id for item in preview.candidate_objects
                    ],
                    "method": "manual_object_projection",
                }
            }
            resolved = preview_editable_rebase(
                session,
                source_key="doc_candidates",
                page=1,
                candidate_run_id=new_run_id,
                projection_resolutions=resolution,
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
                projection_resolutions=resolution,
            )
            assert result.projection_resolutions_applied == 1
            assert result.comments_relocated == 1

        with session_scope(engine) as session:
            active = session.scalar(
                select(EditableObject).where(EditableObject.lifecycle_status == "active")
            )
            assert active is not None
            comment = session.scalar(select(EditableObjectComment))
            assert comment is not None
            assert comment.editable_object_id == active.id
            revision = session.scalar(
                select(EditablePageRevision).where(EditablePageRevision.operation == "rebase")
            )
            assert revision is not None
            assert revision.details_json["manual_projection_resolution_count"] == 1
            assert revision.details_json["projection_resolution_methods"] == [
                "manual_object_projection"
            ]
    finally:
        engine.dispose()


def test_specialized_attributes_are_preserved_and_conflicts_are_resolved(tmp_path) -> None:
    _root, decisions, engine, _old_run_id, new_run_id = _project(tmp_path)
    try:
        with session_scope(engine) as session:
            candidate = session.scalar(
                select(ExtractedObject).where(ExtractedObject.extraction_run_id == new_run_id)
            )
            assert candidate is not None
            candidate.original_text = "Título viejo\n\nTexto viejo"
            candidate.attributes_json = {
                "classification": {"origin": "surya", "value": "candidate"},
                "layout_role": "body",
            }
            bootstrap_editable_layer(
                session,
                decisions=decisions,
                created_by="Alex",
                source_keys={"doc_candidates"},
            )
            rows = session.scalars(
                select(EditableObject)
                .where(EditableObject.lifecycle_status == "active")
                .order_by(EditableObject.current_order_index)
            ).all()
            assert len(rows) == 2
            rows[0].current_attributes_json = {
                **rows[0].current_attributes_json,
                "classification": {"origin": "human", "value": "A"},
                "shared_review": {"priority": "high"},
                "lineage_events": [{"operation": "split"}],
            }
            rows[1].current_attributes_json = {
                **rows[1].current_attributes_json,
                "classification": {"origin": "human", "value": "B"},
                "shared_review": {"priority": "high"},
            }

        with session_scope(engine) as session:
            preview = preview_editable_rebase(
                session,
                source_key="doc_candidates",
                page=1,
                candidate_run_id=new_run_id,
            )
            assert preview.can_apply is False
            assert len(preview.attribute_conflicts) == 1
            conflict = preview.attribute_conflicts[0]
            assert conflict.attribute_key == "classification"
            assert {item.option_key for item in conflict.options} >= {
                "candidate",
                "remove",
            }
            human_a = next(
                item
                for item in conflict.options
                if item.action == "set"
                and item.value == {"origin": "human", "value": "A"}
            )
            resolutions = {
                conflict.conflict_id: {
                    "action": "select",
                    "option_key": human_a.option_key,
                    "expected_option_keys": [item.option_key for item in conflict.options],
                    "method": "manual_attribute_selection",
                }
            }
            resolved = preview_editable_rebase(
                session,
                source_key="doc_candidates",
                page=1,
                candidate_run_id=new_run_id,
                attribute_resolutions=resolutions,
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
                attribute_resolutions=resolutions,
            )
            assert result.attribute_resolutions_applied == 1

        with session_scope(engine) as session:
            active = session.scalar(
                select(EditableObject).where(EditableObject.lifecycle_status == "active")
            )
            assert active is not None
            assert active.current_attributes_json["classification"] == {
                "origin": "human",
                "value": "A",
            }
            assert active.current_attributes_json["shared_review"] == {
                "priority": "high"
            }
            assert active.current_attributes_json["layout_role"] == "body"
            assert "lineage_events" not in active.current_attributes_json
            revision = session.scalar(
                select(EditablePageRevision).where(EditablePageRevision.operation == "rebase")
            )
            assert revision is not None
            assert revision.details_json["manual_attribute_resolution_count"] == 1
            assert revision.details_json["specialized_attribute_count"] == 2
    finally:
        engine.dispose()


def test_specialized_attribute_conflict_accepts_manual_json(tmp_path) -> None:
    _root, decisions, engine, _old_run_id, new_run_id = _project(tmp_path)
    try:
        with session_scope(engine) as session:
            candidate = session.scalar(
                select(ExtractedObject).where(ExtractedObject.extraction_run_id == new_run_id)
            )
            assert candidate is not None
            candidate.original_text = "Título viejo\n\nTexto viejo"
            candidate.attributes_json = {"classification": "candidate"}
            bootstrap_editable_layer(
                session,
                decisions=decisions,
                created_by="Alex",
                source_keys={"doc_candidates"},
            )
            rows = session.scalars(
                select(EditableObject)
                .where(EditableObject.lifecycle_status == "active")
                .order_by(EditableObject.current_order_index)
            ).all()
            rows[0].current_attributes_json = {
                **rows[0].current_attributes_json,
                "classification": "human",
            }

        with session_scope(engine) as session:
            preview = preview_editable_rebase(
                session,
                source_key="doc_candidates",
                page=1,
                candidate_run_id=new_run_id,
            )
            conflict = preview.attribute_conflicts[0]
            manual_value = {"scheme": "custom", "level": 3}
            resolutions = {
                conflict.conflict_id: {
                    "action": "manual_json",
                    "value": manual_value,
                    "expected_option_keys": [item.option_key for item in conflict.options],
                    "method": "manual_attribute_json",
                }
            }
            resolved = preview_editable_rebase(
                session,
                source_key="doc_candidates",
                page=1,
                candidate_run_id=new_run_id,
                attribute_resolutions=resolutions,
            )
            assert resolved.can_apply is True
            assert resolved._plan["attribute_plan"][0]["classification"] == manual_value
    finally:
        engine.dispose()
