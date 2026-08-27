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


def test_catalog_semantics_are_explicit_for_new_projects_and_inferred_for_legacy_configs(tmp_path: Path) -> None:
    import yaml

    root = Path(__file__).parents[1]
    decisions = load_decisions(root / "config" / "decisions.yaml")
    levels = {level.key: level for level in decisions.archival_levels}
    assert levels["archivo"].semantic_kind == "custody_context"
    assert levels["fondo"].resolved_semantic_kind == "record_set"
    assert levels["fondo"].resolved_record_set_type == "fonds"
    assert levels["coleccion"].resolved_record_set_type == "collection"
    assert levels["serie"].resolved_record_set_type == "series"
    assert levels["caja"].resolved_semantic_kind == "container"
    assert levels["documento"].resolved_semantic_kind == "record"

    raw = yaml.safe_load((root / "config" / "decisions.yaml").read_text(encoding="utf-8"))
    for level in raw["archival_levels"]:
        level.pop("semantic_kind", None)
        level.pop("record_set_type", None)
    legacy = tmp_path / "legacy-decisions.yaml"
    legacy.write_text(yaml.safe_dump(raw, allow_unicode=True, sort_keys=False), encoding="utf-8")

    legacy_decisions = load_decisions(legacy)
    legacy_levels = {level.key: level for level in legacy_decisions.archival_levels}
    assert legacy_levels["archivo"].resolved_semantic_kind == "custody_context"
    assert legacy_levels["fondo"].resolved_record_set_type == "fonds"
    assert legacy_levels["coleccion"].resolved_record_set_type == "collection"
    assert legacy_levels["caja"].resolved_semantic_kind == "container"
    assert legacy_levels["documento"].resolved_semantic_kind == "record"
