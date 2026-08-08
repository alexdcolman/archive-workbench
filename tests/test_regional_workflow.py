from __future__ import annotations

from pathlib import Path

import pytest

from archive_workbench.contracts.regions import RegionDefinition
from archive_workbench.region_canvas import build_region_canvas_payload
from archive_workbench.regional_workflow import (
    REGION_ROLE_DEFAULT_MODE,
    draft_from_region,
    object_type_for_role,
    region_from_draft,
    region_role_label,
    template_from_drafts,
)
from scripts.create_regional_ocr_validation_project import create_validation_project
from scripts.prepare_regional_ocr_validation_resume import prepare as prepare_resume


def _draft(*, role: str = "body_text", mode: str = "ocr", page: int = 1) -> dict:
    return {
        "region_key": "r1",
        "label": "Zona uno",
        "page": page,
        "reading_order": 10,
        "bbox": {"x0": 0.1, "y0": 0.2, "x1": 0.5, "y1": 0.4},
        "mode": mode,
        "semantic_role": role,
        "object_type": object_type_for_role(role),
        "ocr": ({"image_variant": "original", "psm": 6, "languages": ["spa"], "object_granularity": "paragraph", "minimum_characters_warning": 1} if mode == "ocr" else None),
    }


def test_region_role_mapping_and_defaults() -> None:
    assert region_role_label("illustration") == "Ilustración o imagen"
    assert object_type_for_role("signature") == "handwritten_region"
    assert REGION_ROLE_DEFAULT_MODE["body_text"] == "ocr"
    assert REGION_ROLE_DEFAULT_MODE["illustration"] == "manual"


def test_template_from_drafts_preserves_semantic_contract() -> None:
    template = template_from_drafts(
        source_key="doc",
        drafts=[_draft()],
        template_key="visual",
    )
    assert template.schema_version == "1.1"
    assert template.regions[0].semantic_role == "body_text"
    assert template.regions[0].object_type == "paragraph"


def test_draft_roundtrip() -> None:
    region = region_from_draft(_draft(role="stamp", mode="manual"), fallback_index=1)
    restored = region_from_draft(draft_from_region(region), fallback_index=2)
    assert restored == region
    assert restored.ocr is None


def test_canvas_payload_filters_other_pages(tmp_path: Path) -> None:
    from PIL import Image

    image = tmp_path / "page.png"
    Image.new("RGB", (200, 300), "white").save(image)
    regions = [
        RegionDefinition.model_validate(_draft(page=1)),
        RegionDefinition.model_validate({**_draft(page=2), "region_key": "r2"}),
    ]
    payload = build_region_canvas_payload(image, regions, page=1)
    assert payload["page"] == 1
    assert len(payload["boxes"]) == 1
    assert payload["boxes"][0]["region_key"] == "r1"


def test_semantic_role_rejects_mismatched_object_type() -> None:
    payload = _draft()
    payload["object_type"] = "figure"
    with pytest.raises(ValueError, match="requiere object_type"):
        RegionDefinition.model_validate(payload)


def test_template_from_drafts_uses_free_order_gap_for_duplicate_page_position() -> None:
    drafts = []
    for index, order in enumerate((10, 20, 30, 40, 60), start=1):
        item = _draft(mode="manual", role="illustration")
        item.update(
            {
                "region_key": f"r{index}",
                "label": f"Zona {index}",
                "reading_order": order,
            }
        )
        drafts.append(item)

    manual = _draft(mode="manual", role="illustration")
    manual.update(
        {
            "region_key": "manual",
            "label": "Ilustración controlada",
            "reading_order": 60,
        }
    )
    drafts.append(manual)

    template = template_from_drafts(
        source_key="doc",
        drafts=drafts,
        template_key="visual",
    )

    assert [row.reading_order for row in template.regions] == [10, 20, 30, 40, 50, 60]
    assert template.regions[4].region_key == "manual"


def test_regional_ui_assigns_first_free_reading_order() -> None:
    source = (
        Path(__file__).parents[1]
        / "src"
        / "archive_workbench"
        / "processing_app.py"
    ).read_text(encoding="utf-8")

    assert "while reading_order in used_orders" in source
    assert '"reading_order": reading_order' in source


def test_resume_template_adds_manual_illustration_in_free_position(tmp_path: Path) -> None:
    root = tmp_path / "regional"
    create_validation_project(root)
    path = prepare_resume(root)
    from archive_workbench.region_extraction import load_region_template

    template = load_region_template(path)
    assert [row.reading_order for row in template.regions] == [10, 20, 30, 40, 50, 60]
    assert template.regions[4].semantic_role == "illustration"
    assert prepare_resume(root) == path


def test_validation_project_starts_without_candidate_or_selection(tmp_path: Path) -> None:
    result = create_validation_project(tmp_path / "regional")
    assert result["version"] == "0.88.2"
    assert result["revision"] == "0046_audiovisual_timeline_annotations"
    assert result["template_regions"] == 5
    assert result["candidate_runs"] == 0
    assert result["canonical_selections"] == 0
    assert result["originals_unchanged"] is True
    assert result["project_data_touched"] is False
