from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import select

from archive_workbench.db import create_sqlite_engine, database_path, session_scope, upgrade_database
from archive_workbench.db.models import EditableObject, EditablePage, EditablePageRevision
from archive_workbench.decisions import load_decisions
from archive_workbench.editing import add_editable_object, bootstrap_editable_layer, export_editable_layer
from archive_workbench.form_structure import (
    archive_control,
    archive_group,
    ensure_group,
    form_candidates,
    form_structure,
    form_structure_history,
    register_control,
    rename_group,
    update_control,
)
from archive_workbench.page_actions import execute_page_action, redo_page_action, undo_page_action
from archive_workbench.catalog import register_test_corpus
from tests.test_editing import _corpus, _seed_selected_extraction, _write_pdf


def _prepare(tmp_path: Path):
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
        _seed_selected_extraction(session)
    with session_scope(engine) as session:
        bootstrap_editable_layer(
            session,
            decisions=decisions,
            created_by="tests",
        )
        page = session.scalar(select(EditablePage))
        assert page is not None
        marked = add_editable_object(
            session,
            decisions=decisions,
            source_key="doc_editable",
            page=1,
            object_type="form_field",
            text="[x] Afiliado",
            created_by="tests",
        )
        unmarked = add_editable_object(
            session,
            decisions=decisions,
            source_key="doc_editable",
            page=1,
            object_type="form_field",
            text="☐ Casado",
            created_by="tests",
        )
        manual_label = add_editable_object(
            session,
            decisions=decisions,
            source_key="doc_editable",
            page=1,
            object_type="form_field",
            text="Antecedentes",
            created_by="tests",
        )
        ids = {
            "page": page.id,
            "marked": marked.id,
            "unmarked": unmarked.id,
            "manual_label": manual_label.id,
        }
    return root, engine, decisions, ids


def test_candidates_use_current_editable_state_and_are_not_canonical(tmp_path: Path) -> None:
    _root, engine, _decisions, ids = _prepare(tmp_path)
    try:
        with session_scope(engine) as session:
            candidates = form_candidates(session, editable_page_id=ids["page"])
            assert [(row.state, row.label) for row in candidates] == [
                ("marked", "Afiliado"),
                ("unmarked", "Casado"),
            ]
            assert all(not row.already_registered for row in candidates)
            page = session.get(EditablePage, ids["page"])
            assert page is not None
            assert page.form_structure_json in ({}, {"schema_version": "1.0", "groups": [], "controls": []})
    finally:
        engine.dispose()


def test_confirm_group_update_archive_history_and_export(tmp_path: Path) -> None:
    root, engine, _decisions, ids = _prepare(tmp_path)
    try:
        with session_scope(engine) as session:
            candidates = form_candidates(session, editable_page_id=ids["page"])
            marked = candidates[0]
            group_id = ensure_group(
                session,
                editable_page_id=ids["page"],
                label="Datos personales",
                changed_by="Alex",
            )
            control = register_control(
                session,
                editable_page_id=ids["page"],
                state="marked",
                label="Afiliado",
                changed_by="Alex",
                marker_object_id=marked.marker_object_id,
                label_object_id=marked.label_object_id,
                group_id=group_id,
                source="candidate",
                candidate_fingerprint=marked.fingerprint,
                candidate_method=marked.method,
                marker_text=marked.marker,
                evidence_note="Revisión sobre la imagen",
            )
            manual = register_control(
                session,
                editable_page_id=ids["page"],
                state="unmarked",
                label="Antecedentes",
                changed_by="Alex",
                label_object_id=ids["manual_label"],
                group_id=group_id,
                source="manual",
                evidence_note="Casillero vacío visible, sin símbolo OCR",
            )
            update_control(
                session,
                editable_page_id=ids["page"],
                control_id=control.control_id,
                changed_by="Alex",
                state="indeterminate",
                label="Afiliación",
                group_id=group_id,
                evidence_note="Marca ambigua",
            )
            rename_group(
                session,
                editable_page_id=ids["page"],
                group_id=group_id,
                label="Identificación personal",
                changed_by="Alex",
            )
            archive_control(
                session,
                editable_page_id=ids["page"],
                control_id=manual.control_id,
                changed_by="Alex",
                note="No corresponde a esta ficha",
            )

        with session_scope(engine) as session:
            structure = form_structure(session, editable_page_id=ids["page"])
            active_group = next(item for item in structure.groups if item.lifecycle_status == "active")
            assert active_group.label == "Identificación personal"
            active_control = next(item for item in structure.controls if item.lifecycle_status == "active")
            assert active_control.state == "indeterminate"
            assert active_control.label == "Afiliación"
            assert active_control.evidence_note == "Marca ambigua"
            assert sum(item.lifecycle_status == "archived" for item in structure.controls) == 1
            candidates = form_candidates(session, editable_page_id=ids["page"])
            marked = next(item for item in candidates if item.label == "Afiliado")
            assert marked.already_registered is True
            history = form_structure_history(session, editable_page_id=ids["page"])
            assert [row.details["action"] for row in history] == [
                "create_group",
                "register_control",
                "register_control",
                "update_control",
                "rename_group",
                "archive_control",
            ]
            summary = export_editable_layer(
                session,
                project_root=root,
                source_key="doc_editable",
            )
        exported = [
            json.loads(line)
            for line in summary.form_structures_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        assert summary.form_structure_count == 1
        assert exported[0]["structure"]["groups"][0]["label"] == "Identificación personal"
        manifest = json.loads(summary.manifest_path.read_text(encoding="utf-8"))
        assert manifest["schema_version"] == "1.4"
        assert manifest["form_structure_count"] == 1
        assert manifest["form_structures_path"] == "form_structures.jsonl"
    finally:
        engine.dispose()



def test_confirmed_candidate_stays_registered_after_editable_label_change(
    tmp_path: Path,
) -> None:
    _root, engine, decisions, ids = _prepare(tmp_path)
    try:
        with session_scope(engine) as session:
            candidate = form_candidates(session, editable_page_id=ids["page"])[0]
            register_control(
                session,
                editable_page_id=ids["page"],
                state=candidate.state,
                label=candidate.label or "Sin rótulo",
                changed_by="Alex",
                marker_object_id=candidate.marker_object_id,
                label_object_id=candidate.label_object_id,
                source="candidate",
                candidate_fingerprint=candidate.fingerprint,
                candidate_method=candidate.method,
                marker_text=candidate.marker,
            )
        with session_scope(engine) as session:
            obj = session.get(EditableObject, ids["marked"])
            assert obj is not None
            from archive_workbench.editing import update_editable_object

            update_editable_object(
                session,
                decisions=decisions,
                object_id=obj.id,
                expected_revision=obj.revision_number,
                edited_by="Alex",
                text="[x] Afiliación sindical",
            )
        with session_scope(engine) as session:
            candidate = next(
                item
                for item in form_candidates(session, editable_page_id=ids["page"])
                if item.label == "Afiliación sindical"
            )
            assert candidate.already_registered is True
    finally:
        engine.dispose()


def test_archiving_group_detaches_active_controls_and_keeps_history(tmp_path: Path) -> None:
    _root, engine, _decisions, ids = _prepare(tmp_path)
    try:
        with session_scope(engine) as session:
            candidate = form_candidates(session, editable_page_id=ids["page"])[0]
            group_id = ensure_group(
                session,
                editable_page_id=ids["page"],
                label="Estado civil",
                changed_by="Alex",
            )
            control = register_control(
                session,
                editable_page_id=ids["page"],
                state=candidate.state,
                label=candidate.label or "Sin rótulo",
                changed_by="Alex",
                marker_object_id=candidate.marker_object_id,
                label_object_id=candidate.label_object_id,
                group_id=group_id,
                source="candidate",
                candidate_fingerprint=candidate.fingerprint,
                candidate_method=candidate.method,
                marker_text=candidate.marker,
            )
            archive_group(
                session,
                editable_page_id=ids["page"],
                group_id=group_id,
                changed_by="Alex",
                note="Agrupación incorrecta",
            )
        with session_scope(engine) as session:
            structure = form_structure(session, editable_page_id=ids["page"])
            group = next(item for item in structure.groups if item.group_id == group_id)
            current = next(
                item for item in structure.controls if item.control_id == control.control_id
            )
            assert group.lifecycle_status == "archived"
            assert current.lifecycle_status == "active"
            assert current.group_id is None
            assert form_structure_history(session, editable_page_id=ids["page"])[-1].details == {
                "action": "archive_group",
                "group_id": group_id,
            }
    finally:
        engine.dispose()

def test_form_structure_page_action_can_be_undone_and_redone(tmp_path: Path) -> None:
    _root, engine, _decisions, ids = _prepare(tmp_path)
    try:
        with session_scope(engine) as session:
            candidate = form_candidates(session, editable_page_id=ids["page"])[0]

            def action():
                return register_control(
                    session,
                    editable_page_id=ids["page"],
                    state=candidate.state,
                    label=candidate.label or "Sin rótulo",
                    changed_by="Alex",
                    marker_object_id=candidate.marker_object_id,
                    label_object_id=candidate.label_object_id,
                    source="candidate",
                    candidate_fingerprint=candidate.fingerprint,
                    candidate_method=candidate.method,
                    marker_text=candidate.marker,
                )

            execute_page_action(
                session,
                editable_page_id=ids["page"],
                action_type="form_structure",
                changed_by="Alex",
                selected_object_id=ids["marked"],
                action=action,
            )
        with session_scope(engine) as session:
            assert len(form_structure(session, editable_page_id=ids["page"]).controls) == 1
            undo_page_action(session, editable_page_id=ids["page"], changed_by="Alex")
        with session_scope(engine) as session:
            assert len(form_structure(session, editable_page_id=ids["page"]).controls) == 0
            redo_page_action(session, editable_page_id=ids["page"], changed_by="Alex")
        with session_scope(engine) as session:
            assert len(form_structure(session, editable_page_id=ids["page"]).controls) == 1
            revisions = session.scalars(
                select(EditablePageRevision)
                .where(EditablePageRevision.editable_page_id == ids["page"])
                .order_by(EditablePageRevision.revision_number)
            ).all()
            assert {row.operation for row in revisions} >= {"form_structure", "undo", "redo"}
    finally:
        engine.dispose()


def test_form_structure_validation_project_is_controlled_and_noncanonical(
    tmp_path: Path,
) -> None:
    import importlib.util

    script_path = (
        Path(__file__).parents[1]
        / "scripts"
        / "create_form_structure_validation_project.py"
    )
    spec = importlib.util.spec_from_file_location(
        "form_structure_validation_script", script_path
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    destination = tmp_path / "ocr01b_validation"
    result = module.create_validation_project(destination)

    assert result["revision"] == "0045_audiovisual_transcription"
    assert result["documents"] == 1
    assert result["candidate_count"] == 3
    assert result["candidate_states"] == ["marked", "unmarked", "marked"]
    assert result["candidate_labels"] == ["Soltero", "Casado", "Afiliado"]
    assert result["confirmed_groups"] == 0
    assert result["confirmed_controls"] == 0
    assert result["manual_only_label"] == "Beneficiario"
    assert result["originals_unchanged"] is True
    assert result["project_data_touched"] is False
    assert (destination / "validation_summary.json").is_file()
