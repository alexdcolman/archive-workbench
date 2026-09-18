from __future__ import annotations

from pathlib import Path


def test_p3c_assisted_analysis_is_top_level_after_export_with_passive_tabs() -> None:
    root = Path(__file__).parents[1] / "src" / "archive_workbench"
    review_source = (root / "review_app.py").read_text(encoding="utf-8")
    app_source = (root / "assisted_analysis_app.py").read_text(encoding="utf-8")

    labels_window = review_source[
        review_source.index("_VIEW_LABELS = {") : review_source.index("_WORKFLOW_STEPS = (")
    ]
    assert (
        labels_window.index('"export": "Exportar corpus"')
        < labels_window.index('"assisted_analysis": "Análisis asistido"')
        < labels_window.index('"exchange": "Intercambiar cambios"')
    )
    assert 'section_heading(st, "Análisis asistido")' in app_source
    assert (
        '["Resultados recibidos", "Revisar propuestas", "Documentos con análisis", "Historial"]'
        in app_source
    )
    assert "rerun_on_change=False" in app_source
    assert "@st.fragment" not in app_source


def test_p3c_review_requires_exact_asset_and_explicit_human_actions() -> None:
    source = (
        Path(__file__).parents[1] / "src" / "archive_workbench" / "assisted_analysis_app.py"
    ).read_text(encoding="utf-8")

    assert "read_external_analysis_proposal_asset" in source
    assert "Aceptar tal como está" in source
    assert "Editar y aceptar" in source
    assert "Rechazar" in source
    assert "enter_to_submit=False" in source
    assert "automatic_apply" not in source
    assert "set_external_analysis_current_review" in source
    assert "Confirmo que quiero usar esta revisión como vigente" in source


def test_p3c_documents_surface_links_back_to_same_page_without_rewriting_canonical_layers() -> None:
    source = (
        Path(__file__).parents[1] / "src" / "archive_workbench" / "assisted_analysis_app.py"
    ).read_text(encoding="utf-8")

    assert "Abrir en Edición y anotación" in source
    assert "Abrir en Revisión estructural" in source
    assert 'mode="annotation"' in source
    assert 'mode="review"' in source
    assert "update_editable_object" not in source
    assert "set_page_review_status" not in source
    assert "create_mention" not in source
    assert "create_relationship" not in source


def test_ai_execution_is_explicit_governed_external_and_returns_through_p3() -> None:
    root = Path(__file__).parents[1] / "src" / "archive_workbench"
    app_source = (root / "assisted_analysis_app.py").read_text(encoding="utf-8")
    execution_source = (root / "ai_execution.py").read_text(encoding="utf-8")

    assert "run_ai_analysis" in app_source
    assert 'analysis_kind="llm_tool"' in app_source
    assert 'target_type="corpus_export_run"' in app_source
    assert "run_id=planned_run_id" in app_source
    assert "inspect_ai_handoff_bytes" in app_source
    assert "Incorporar propuestas para revisión" in app_source
    assert "subprocess" not in app_source
    assert "capabilities.executable," in execution_source
    assert '"analyze",' in execution_source
    assert '"--input"' in execution_source
    assert '"--output"' in execution_source
    assert '"--result-output"' in execution_source
    assert "shell=True" not in execution_source
