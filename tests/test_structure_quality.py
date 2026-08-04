from __future__ import annotations

from types import SimpleNamespace

from PIL import Image

from archive_workbench.page_quality import ALGORITHM_VERSION, evaluate_page_quality
from archive_workbench.structure_quality import (
    checkbox_candidates,
    legal_ordinal_candidates,
    structural_quality_metrics,
)


def _geometry(left: float, top: float, right: float, bottom: float) -> list[dict]:
    return [
        {
            "page": 1,
            "coordinate_space": "normalized",
            "polygon": [
                [left, top],
                [right, top],
                [right, bottom],
                [left, bottom],
            ],
        }
    ]


def _object(
    object_id: str,
    order_index: int,
    text: str,
    *,
    geometry: list[dict] | None = None,
    object_type: str = "paragraph",
    source_label: str | None = None,
    attributes: dict | None = None,
):
    return SimpleNamespace(
        id=object_id,
        order_index=order_index,
        object_type=object_type,
        original_text=text,
        geometry_json=geometry or [],
        source_label=source_label,
        attributes_json=attributes or {},
        confidence=None,
    )


def test_legal_ordinal_candidates_detect_surya_sequence_without_correcting() -> None:
    objects = [
        _object("a4", 0, "Artículo 49.- Sin perjuicio de lo expuesto."),
        _object("a5", 1, "Artículo 50.- El Ministro de Defensa."),
        _object("a6", 2, "Artículo 62.- La autoridad competente."),
        _object("a7", 3, "Artículo 72.- Promulgado el decreto."),
        _object("a8", 4, "Artículo 82.- Será refrendado."),
        _object("a9", 5, "Artículo 92.- Comuníquese y archívese."),
    ]

    candidates = legal_ordinal_candidates(objects)

    assert [item["possible_ordinal"] for item in candidates] == [
        "4º",
        "5º",
        "6º",
        "7º",
        "8º",
        "9º",
    ]
    assert objects[0].original_text.startswith("Artículo 49")


def test_legal_ordinal_candidates_do_not_flag_normal_consecutive_articles() -> None:
    objects = [
        _object("a49", 0, "Artículo 49.- Texto."),
        _object("a50", 1, "Artículo 50.- Texto."),
        _object("a51", 2, "Artículo 51.- Texto."),
    ]

    assert legal_ordinal_candidates(objects) == []


def test_checkbox_candidates_preserve_reviewable_state_and_label() -> None:
    objects = [
        _object(
            "html",
            0,
            "",
            object_type="form_field",
            source_label="Form",
            attributes={
                "html": (
                    '<label><input type="checkbox" checked> Secreto</label>'
                    '<label><input type="checkbox"> Confidencial</label>'
                )
            },
        ),
        _object("explicit", 1, "☐ Reservado", object_type="form_field", source_label="Form"),
        _object(
            "mark",
            2,
            "X",
            geometry=_geometry(0.10, 0.20, 0.13, 0.24),
            object_type="form_field",
            source_label="Form",
        ),
        _object(
            "label",
            3,
            "Urgente",
            geometry=_geometry(0.14, 0.20, 0.28, 0.24),
            object_type="form_field",
            source_label="Form",
        ),
        _object("ordinary", 4, "X marca un lugar en el texto"),
    ]

    candidates = checkbox_candidates(objects, page_number=1)

    assert [(item["state"], item["label"], item["method"]) for item in candidates[:2]] == [
        ("marked", "Secreto", "html_control"),
        ("unmarked", "Confidencial", "html_control"),
    ]
    assert candidates[2]["state"] == "unmarked"
    assert candidates[2]["label"] == "Reservado"
    assert candidates[2]["method"] == "explicit_text"
    assert candidates[3]["state"] == "marked"
    assert candidates[3]["label"] == "Urgente"
    assert candidates[3]["method"] == "spatial"
    assert all(item["marker_object_id"] != "ordinary" for item in candidates)


def test_page_quality_v2_adds_structural_alerts_without_silent_changes(tmp_path) -> None:
    image_path = tmp_path / "page.png"
    Image.new("L", (800, 1000), 240).save(image_path)
    objects = [
        _object("a4", 0, "Artículo 49.- Sin perjuicio de lo expuesto."),
        _object("a5", 1, "Artículo 50.- El Ministro de Defensa."),
        _object("a6", 2, "Artículo 62.- La autoridad competente."),
        _object(
            "mark",
            3,
            "X",
            geometry=_geometry(0.10, 0.70, 0.13, 0.74),
            object_type="form_field",
            source_label="Form",
        ),
        _object(
            "label",
            4,
            "Urgente",
            geometry=_geometry(0.14, 0.70, 0.28, 0.74),
            object_type="form_field",
            source_label="Form",
        ),
    ]

    _status, _score, metrics, flags, suggestions = evaluate_page_quality(
        image_path=image_path,
        objects=objects,
        page_number=1,
    )

    assert ALGORITHM_VERSION == "page_quality_v2"
    assert "legal_ordinal_review" in flags
    assert "checkbox_state_review" in flags
    assert metrics["legal_ordinal_candidate_count"] == 3
    assert metrics["checkbox_marked_count"] == 1
    assert any("no corregirlos automáticamente" in item for item in suggestions)
    assert structural_quality_metrics(objects, page_number=1)["checkbox_candidates"][0][
        "label"
    ] == "Urgente"
