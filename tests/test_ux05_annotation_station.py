from pathlib import Path

import pytest

pytestmark = pytest.mark.fast

ROOT = Path(__file__).resolve().parents[1]


def test_ux05_annotation_station_has_no_block_type_selectors() -> None:
    source = (ROOT / "src/archive_workbench/annotation_station.py").read_text()
    assert "<select" not in source.casefold()
    assert "Guardar y siguiente" in source
    assert "Menciones" in source
    assert "Etiquetas" in source
    assert "Comentarios" in source
    assert "aw-mention-mark" in source
    assert "remove_tag" in source
    assert "update_mention" in source
    assert "scan_mentions" in source
    assert "font-size:12px" in source
    assert "Anotaciones del bloque" in source


def test_ux05_navigation_separates_structural_review_and_annotation() -> None:
    source = (ROOT / "src/archive_workbench/review_app.py").read_text()
    assert '"review": "Revisión estructural"' in source
    assert '"annotation": "Edición y anotación"' in source
    assert 'if app_mode == "annotation"' in source
    assert 'st.subheader("Revisar estructura de la página")' in source
    structural = source[source.index('key="review_object_tabs"') - 700 : source.index('key="review_object_tabs"') + 400]
    assert '"Estado y anotaciones"' not in structural
    assert '"Menciones de entidades"' not in structural
    assert '"Editar texto"' not in structural


def test_ux05_routes_from_work_and_semantic_open_annotation() -> None:
    work = (ROOT / "src/archive_workbench/work_app.py").read_text()
    semantic = (ROOT / "src/archive_workbench/semantic_app.py").read_text()
    authority = (ROOT / "src/archive_workbench/authority_app.py").read_text()
    graph = (ROOT / "src/archive_workbench/graph_app.py").read_text()
    assert 'mode="annotation"' in work
    assert 'mode="annotation"' in semantic
    assert 'mode="annotation"' in authority
    assert 'mode="annotation"' in graph


def test_ux05_annotation_station_exposes_shared_page_review_state() -> None:
    station = (ROOT / "src/archive_workbench/annotation_station.py").read_text()
    review = (ROOT / "src/archive_workbench/review_app.py").read_text()
    assert '"editable_page_id": view.editable_page_id' in station
    assert '"page_review_status": view.page_review_status' in station
    assert '"page_review_note": view.page_review_note or ""' in station
    assert "save_page_review" in station
    assert 'if kind == "save_page_review"' in review
    assert "set_page_review_status(" in review


def test_ux05_dictionary_quality_error_uses_human_page_status_label() -> None:
    source = (ROOT / "src/archive_workbench/authorities.py").read_text()
    assert '"unreviewed": "Sin revisar"' in source
    assert "current_label = _PAGE_REVIEW_LABELS.get(current, current)" in source


def test_ux05_candidate_version_is_visible() -> None:
    version = (ROOT / "src/archive_workbench/version.py").read_text()
    review = (ROOT / "src/archive_workbench/review_app.py").read_text()
    assert '__version__ = "1.1.0"' in version
    assert 'Versión {__version__' in review
