from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import select

from archive_workbench.catalog import register_test_corpus
from archive_workbench.db import create_sqlite_engine, database_path, session_scope, upgrade_database
from archive_workbench.db.models import EditableObject, EditablePage
from archive_workbench.decisions import load_decisions
from archive_workbench.editing import add_editable_object, bootstrap_editable_layer, export_editable_layer
from archive_workbench.layout_structure import (
    apply_layout_proposal,
    assign_object_to_column,
    create_layout_column_for_object,
    ensure_layout_column,
    layout_proposal,
    layout_structure,
    layout_structure_history,
    propose_layout,
    rename_layout_column,
)
from archive_workbench.page_actions import execute_page_action, redo_page_action, undo_page_action
from tests.test_editing import _corpus, _seed_selected_extraction, _write_pdf


def _geometry(left: float, top: float, right: float, bottom: float) -> list[dict]:
    return [
        {
            "page": 1,
            "coordinate_space": "normalized",
            "polygon": [[left, top], [right, top], [right, bottom], [left, bottom]],
        }
    ]


def _prepare(tmp_path: Path):
    root = tmp_path / "project"
    _write_pdf(root / "corpus/doc.pdf")
    decisions = load_decisions(Path(__file__).parents[1] / "config/decisions.yaml")
    upgrade_database(root)
    engine = create_sqlite_engine(database_path(root))
    with session_scope(engine) as session:
        register_test_corpus(session, project_root=root, decisions=decisions, corpus=_corpus())
        _seed_selected_extraction(session)
    with session_scope(engine) as session:
        bootstrap_editable_layer(session, decisions=decisions, created_by="tests")
        page = session.scalar(select(EditablePage))
        assert page is not None
        for item in session.scalars(select(EditableObject)).all():
            item.lifecycle_status = "deleted"
        specs = [
            ("r1", "Derecha arriba", 0.62, 0.10, 0.92, 0.17),
            ("l1", "Izquierda arriba", 0.08, 0.11, 0.40, 0.18),
            ("r2", "Derecha abajo", 0.62, 0.30, 0.92, 0.37),
            ("l2", "Izquierda abajo", 0.08, 0.31, 0.40, 0.38),
        ]
        ids: dict[str, str] = {"page": page.id}
        for key, text, left, top, right, bottom in specs:
            obj = add_editable_object(
                session,
                decisions=decisions,
                source_key="doc_editable",
                page=1,
                object_type="paragraph",
                text=text,
                created_by="tests",
            )
            obj.current_geometry_json = _geometry(left, top, right, bottom)
            ids[key] = obj.id
    return root, engine, decisions, ids


def test_proposal_detects_columns_and_does_not_change_canonical_order(tmp_path: Path) -> None:
    _root, engine, _decisions, ids = _prepare(tmp_path)
    try:
        with session_scope(engine) as session:
            before = [item.id for item in session.scalars(
                select(EditableObject).where(EditableObject.lifecycle_status == "active").order_by(EditableObject.current_order_index)
            ).all()]
            proposal = layout_proposal(session, editable_page_id=ids["page"])
            after = [item.id for item in session.scalars(
                select(EditableObject).where(EditableObject.lifecycle_status == "active").order_by(EditableObject.current_order_index)
            ).all()]
            assert len(proposal.columns) == 2
            assert proposal.proposed_order == (ids["l1"], ids["l2"], ids["r1"], ids["r2"])
            assert proposal.changed_positions == 4
            assert before == after
            page = session.get(EditablePage, ids["page"])
            assert page is not None
            assert page.layout_structure_json in ({}, {"schema_version": "1.0", "columns": []})
    finally:
        engine.dispose()


def test_apply_manual_assignment_undo_redo_history_and_export(tmp_path: Path) -> None:
    root, engine, _decisions, ids = _prepare(tmp_path)
    try:
        with session_scope(engine) as session:
            execute_page_action(
                session,
                editable_page_id=ids["page"],
                action_type="layout",
                changed_by="Alex",
                action=lambda: apply_layout_proposal(
                    session,
                    editable_page_id=ids["page"],
                    changed_by="Alex",
                    note="Comparado con la página",
                ),
            )
        with session_scope(engine) as session:
            structure = layout_structure(session, editable_page_id=ids["page"])
            assert [item.label for item in structure.columns if item.lifecycle_status == "active"] == [
                "Columna 1",
                "Columna 2",
            ]
            active = session.scalars(
                select(EditableObject).where(EditableObject.lifecycle_status == "active").order_by(EditableObject.current_order_index)
            ).all()
            assert [item.id for item in active] == [ids["l1"], ids["l2"], ids["r1"], ids["r2"]]
            manual_id = ensure_layout_column(
                session,
                editable_page_id=ids["page"],
                label="Marginal",
                changed_by="Alex",
            )
            execute_page_action(
                session,
                editable_page_id=ids["page"],
                action_type="layout",
                changed_by="Alex",
                action=lambda: assign_object_to_column(
                    session,
                    editable_page_id=ids["page"],
                    object_id=ids["r2"],
                    column_id=manual_id,
                    changed_by="Alex",
                ),
            )
        with session_scope(engine) as session:
            undo_page_action(session, editable_page_id=ids["page"], changed_by="Alex")
        with session_scope(engine) as session:
            structure = layout_structure(session, editable_page_id=ids["page"])
            marginal = next(item for item in structure.columns if item.label == "Marginal")
            assert marginal.object_ids == []
            redo_page_action(session, editable_page_id=ids["page"], changed_by="Alex")
        with session_scope(engine) as session:
            structure = layout_structure(session, editable_page_id=ids["page"])
            marginal = next(item for item in structure.columns if item.label == "Marginal")
            assert marginal.object_ids == [ids["r2"]]
            history = layout_structure_history(session, editable_page_id=ids["page"])
            assert any(row.operation == "undo" for row in history)
            assert any(row.operation == "redo" for row in history)
            summary = export_editable_layer(session, project_root=root, source_key="doc_editable")
        exported = [
            json.loads(line)
            for line in summary.layout_structures_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        assert summary.layout_structure_count == 1
        assert len(exported[0]["structure"]["columns"]) == 3
        manifest = json.loads(summary.manifest_path.read_text(encoding="utf-8"))
        assert manifest["schema_version"] == "1.4"
        assert manifest["layout_structure_count"] == 1
        assert manifest["layout_structures_path"] == "layout_structures.jsonl"
    finally:
        engine.dispose()


def test_fragmentation_and_duplicate_candidates_are_only_diagnostics() -> None:
    from types import SimpleNamespace

    objects = [
        SimpleNamespace(id="a", order_index=0, object_type="paragraph", text="Primera línea", geometry_json=_geometry(0.1, 0.1, 0.45, 0.14), lifecycle_status="active"),
        SimpleNamespace(id="b", order_index=1, object_type="paragraph", text="continúa aquí.", geometry_json=_geometry(0.1, 0.145, 0.45, 0.185), lifecycle_status="active"),
        SimpleNamespace(id="c", order_index=2, object_type="paragraph", text="Duplicado", geometry_json=_geometry(0.6, 0.2, 0.9, 0.26), lifecycle_status="active"),
        SimpleNamespace(id="d", order_index=3, object_type="paragraph", text="Duplicado", geometry_json=_geometry(0.605, 0.202, 0.895, 0.258), lifecycle_status="active"),
    ]
    proposal = propose_layout(objects, page_number=1)
    assert proposal.fragment_candidates[0].object_ids == ("a", "b")
    assert proposal.duplicate_candidates[0].keep_object_id == "c"
    assert proposal.duplicate_candidates[0].duplicate_object_id == "d"
    assert [item.order_index for item in objects] == [0, 1, 2, 3]


def test_layout_validation_project_is_controlled_and_noncanonical(tmp_path: Path) -> None:
    import importlib.util

    script_path = (
        Path(__file__).parents[1]
        / "scripts"
        / "create_layout_structure_validation_project.py"
    )
    spec = importlib.util.spec_from_file_location("layout_validation_script", script_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    result = module.create_validation_project(tmp_path / "ocr01c_validation")

    assert result["version"] == "0.88.0"
    assert result["revision"] == "0046_audiovisual_timeline_annotations"
    assert result["proposed_columns"] == 2
    assert result["fragment_candidates"] == 1
    assert result["duplicate_candidates"] == 1
    assert result["confirmed_columns"] == 0
    assert result["review_image_available"] is True
    assert (tmp_path / "ocr01c_validation" / result["review_image_path"]).is_file()
    assert result["originals_unchanged"] is True
    assert result["project_data_touched"] is False


def test_confirmed_fragment_and_duplicate_actions_are_reversible(tmp_path: Path) -> None:
    import importlib.util

    script_path = (
        Path(__file__).parents[1]
        / "scripts"
        / "create_layout_structure_validation_project.py"
    )
    spec = importlib.util.spec_from_file_location("layout_validation_actions", script_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    root = tmp_path / "layout_actions"
    module.create_validation_project(root)
    engine = create_sqlite_engine(database_path(root))
    try:
        from archive_workbench.layout_structure import (
            archive_duplicate_candidate,
            merge_fragment_candidate,
        )

        with session_scope(engine) as session:
            page = session.scalar(select(EditablePage))
            assert page is not None
            execute_page_action(
                session,
                editable_page_id=page.id,
                action_type="layout",
                changed_by="Alex",
                action=lambda: apply_layout_proposal(
                    session,
                    editable_page_id=page.id,
                    changed_by="Alex",
                ),
            )
        with session_scope(engine) as session:
            page = session.scalar(select(EditablePage))
            assert page is not None
            proposal = layout_proposal(session, editable_page_id=page.id)
            fragment = proposal.fragment_candidates[0]
            execute_page_action(
                session,
                editable_page_id=page.id,
                action_type="merge",
                changed_by="Alex",
                action=lambda: merge_fragment_candidate(
                    session,
                    editable_page_id=page.id,
                    fingerprint=fragment.fingerprint,
                    changed_by="Alex",
                ),
            )
        with session_scope(engine) as session:
            page = session.scalar(select(EditablePage))
            assert page is not None
            proposal = layout_proposal(session, editable_page_id=page.id)
            duplicate = proposal.duplicate_candidates[0]
            execute_page_action(
                session,
                editable_page_id=page.id,
                action_type="delete",
                changed_by="Alex",
                action=lambda: archive_duplicate_candidate(
                    session,
                    editable_page_id=page.id,
                    fingerprint=duplicate.fingerprint,
                    changed_by="Alex",
                ),
            )
        with session_scope(engine) as session:
            active_count = len(
                session.scalars(
                    select(EditableObject).where(
                        EditableObject.lifecycle_status == "active"
                    )
                ).all()
            )
            assert active_count == 5
            page = session.scalar(select(EditablePage))
            assert page is not None
            undo_page_action(session, editable_page_id=page.id, changed_by="Alex")
        with session_scope(engine) as session:
            active_count = len(
                session.scalars(
                    select(EditableObject).where(
                        EditableObject.lifecycle_status == "active"
                    )
                ).all()
            )
            assert active_count == 6
    finally:
        engine.dispose()


def test_create_manual_column_and_assign_object_is_one_layout_revision(tmp_path: Path) -> None:
    _root, engine, _decisions, ids = _prepare(tmp_path)
    try:
        with session_scope(engine) as session:
            execute_page_action(
                session,
                editable_page_id=ids["page"],
                action_type="layout",
                changed_by="Alex",
                action=lambda: apply_layout_proposal(
                    session,
                    editable_page_id=ids["page"],
                    changed_by="Alex",
                ),
            )
        with session_scope(engine) as session:
            before = layout_structure_history(session, editable_page_id=ids["page"])
            column_id = execute_page_action(
                session,
                editable_page_id=ids["page"],
                action_type="layout",
                changed_by="Alex",
                selected_object_id=ids["r2"],
                action=lambda: create_layout_column_for_object(
                    session,
                    editable_page_id=ids["page"],
                    object_id=ids["r2"],
                    label="Marginal",
                    changed_by="Alex",
                ),
            )
            after = layout_structure_history(session, editable_page_id=ids["page"])
            assert len(after) == len(before) + 1
            assert after[-1].details["action"] == "create_and_assign_layout_column"
            structure = layout_structure(session, editable_page_id=ids["page"])
            column = next(item for item in structure.columns if item.column_id == column_id)
            assert column.object_ids == [ids["r2"]]
        with session_scope(engine) as session:
            undo_page_action(session, editable_page_id=ids["page"], changed_by="Alex")
        with session_scope(engine) as session:
            structure = layout_structure(session, editable_page_id=ids["page"])
            assert all(item.label != "Marginal" for item in structure.columns)
            redo_page_action(session, editable_page_id=ids["page"], changed_by="Alex")
        with session_scope(engine) as session:
            structure = layout_structure(session, editable_page_id=ids["page"])
            column = next(item for item in structure.columns if item.label == "Marginal")
            assert column.object_ids == [ids["r2"]]
    finally:
        engine.dispose()


def test_diagnostic_verifier_reports_complete_manual_validation(tmp_path: Path) -> None:
    import importlib.util

    root = tmp_path / "layout_verified"
    create_path = (
        Path(__file__).parents[1]
        / "scripts"
        / "create_layout_structure_validation_project.py"
    )
    create_spec = importlib.util.spec_from_file_location("layout_create_verified", create_path)
    assert create_spec and create_spec.loader
    create_module = importlib.util.module_from_spec(create_spec)
    create_spec.loader.exec_module(create_module)
    create_module.create_validation_project(root)

    engine = create_sqlite_engine(database_path(root))
    try:
        from archive_workbench.layout_structure import (
            archive_duplicate_candidate,
            merge_fragment_candidate,
        )

        with session_scope(engine) as session:
            page = session.scalar(select(EditablePage))
            assert page is not None
            execute_page_action(
                session,
                editable_page_id=page.id,
                action_type="layout",
                changed_by="Alex",
                action=lambda: apply_layout_proposal(
                    session,
                    editable_page_id=page.id,
                    changed_by="Alex",
                ),
            )

        with session_scope(engine) as session:
            page = session.scalar(select(EditablePage))
            assert page is not None
            right_bottom = session.scalar(
                select(EditableObject).where(
                    EditableObject.current_attributes_json["validation_key"].as_string()
                    == "right_bottom"
                )
            )
            assert right_bottom is not None
            column_id = create_layout_column_for_object(
                session,
                editable_page_id=page.id,
                object_id=right_bottom.id,
                label="Marginal",
                changed_by="Alex",
            )
            rename_layout_column(
                session,
                editable_page_id=page.id,
                column_id=column_id,
                label="Margen derecho",
                changed_by="Alex",
            )

        with session_scope(engine) as session:
            page = session.scalar(select(EditablePage))
            assert page is not None
            fragment = layout_proposal(session, editable_page_id=page.id).fragment_candidates[0]
            execute_page_action(
                session,
                editable_page_id=page.id,
                action_type="merge",
                changed_by="Alex",
                action=lambda: merge_fragment_candidate(
                    session,
                    editable_page_id=page.id,
                    fingerprint=fragment.fingerprint,
                    changed_by="Alex",
                ),
            )

        with session_scope(engine) as session:
            page = session.scalar(select(EditablePage))
            assert page is not None
            duplicate = layout_proposal(session, editable_page_id=page.id).duplicate_candidates[0]
            execute_page_action(
                session,
                editable_page_id=page.id,
                action_type="delete",
                changed_by="Alex",
                action=lambda: archive_duplicate_candidate(
                    session,
                    editable_page_id=page.id,
                    fingerprint=duplicate.fingerprint,
                    changed_by="Alex",
                ),
            )

        with session_scope(engine) as session:
            page = session.scalar(select(EditablePage))
            assert page is not None
            undo_page_action(session, editable_page_id=page.id, changed_by="Alex")
        with session_scope(engine) as session:
            page = session.scalar(select(EditablePage))
            assert page is not None
            redo_page_action(session, editable_page_id=page.id, changed_by="Alex")
            export_editable_layer(
                session,
                project_root=root,
                source_key="layout_dos_columnas",
            )
    finally:
        engine.dispose()

    verify_path = (
        Path(__file__).parents[1]
        / "scripts"
        / "verify_layout_structure_validation_project.py"
    )
    verify_spec = importlib.util.spec_from_file_location("layout_verify", verify_path)
    assert verify_spec and verify_spec.loader
    verify_module = importlib.util.module_from_spec(verify_spec)
    verify_spec.loader.exec_module(verify_module)
    assert verify_module.verify(root) == 0
