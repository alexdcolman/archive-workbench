from pathlib import Path

from archive_workbench.decisions import load_decisions


def test_template_is_valid() -> None:
    root = Path(__file__).parents[1]
    decisions = load_decisions(root / "config" / "decisions.template.yaml")
    assert decisions.project_id == "archivo_inteligencia"
    assert any(level.key == "legajo" for level in decisions.archival_levels)
    assert any(item.key == "handwritten_region" for item in decisions.object_types)


def test_completed_decisions_are_valid() -> None:
    root = Path(__file__).parents[1]
    decisions = load_decisions(root / "config" / "decisions.yaml")
    assert decisions.project_id == "apm_chubut"
    assert decisions.catalog.structure_profiles_by_fund is True
    assert decisions.identity.same_sha256_policy == "same_digital_object"
    assert decisions.identity.reextraction_policy == "preserve_versions_mark_current"
    assert any(field.key == "folio_number" for field in decisions.descriptive_fields)
