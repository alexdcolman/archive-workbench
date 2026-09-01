from __future__ import annotations

from pathlib import Path

from sqlalchemy import select

from archive_workbench.decisions import load_decisions
from archive_workbench.db import create_sqlite_engine, database_path, session_scope
from archive_workbench.db.models import Project
from archive_workbench.project_setup import (
    add_standard_collection_level,
    create_ready_project,
    project_is_ready,
    suggested_project_id,
    update_archival_parent_keys,
)
from archive_workbench.user_preferences import (
    UserPreferences,
    load_user_preferences,
    save_user_preferences,
)


def test_suggested_project_id_is_stable_and_plain() -> None:
    assert suggested_project_id("Corpus de archivos de la represión") == "corpus_de_archivos_de_la_represion"


def test_create_ready_project_builds_config_and_current_database(tmp_path: Path) -> None:
    root = create_ready_project(
        tmp_path / "pilot",
        project_name="Corpus piloto",
        project_id="corpus_piloto",
    )
    decisions = load_decisions(root / "config" / "decisions.yaml")
    assert decisions.project_name == "Corpus piloto"
    assert decisions.project_id == "corpus_piloto"
    assert (root / "config" / "extraction.yaml").is_file()
    assert (root / "data" / "archive_workbench.sqlite3").is_file()
    assert project_is_ready(root)
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            project = session.scalar(select(Project))
            assert project is not None
            assert project.id == "corpus_piloto"
            assert project.name == "Corpus piloto"
    finally:
        engine.dispose()


def test_update_archival_parent_keys_preserves_identity_and_changes_only_rules(tmp_path: Path) -> None:
    source = Path(__file__).parents[1] / "config" / "decisions.template.yaml"
    target = tmp_path / "decisions.yaml"
    target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    before = load_decisions(target)

    update_archival_parent_keys(
        target,
        {
            "caja": ["fondo", "serie"],
            "documento": ["fondo", "caja", "legajo", "tomo"],
        },
    )
    after = load_decisions(target)
    assert after.project_name == before.project_name
    assert after.project_id == before.project_id
    levels = {item.key: item for item in after.archival_levels}
    assert levels["caja"].parent_keys == ["fondo", "serie"]
    assert levels["documento"].parent_keys == ["fondo", "caja", "legajo", "tomo"]


def test_user_preferences_roundtrip_and_invalid_palette_falls_back(tmp_path: Path) -> None:
    path = tmp_path / "preferences.json"
    save_user_preferences(UserPreferences(actor=" Alex ", palette="forest"), path)
    loaded = load_user_preferences(path)
    assert loaded.actor == "Alex"
    assert loaded.palette == "forest"

    path.write_text('{"actor": "Alex", "palette": "unknown"}\n', encoding="utf-8")
    assert load_user_preferences(path).palette == "system"



def test_add_standard_collection_level_updates_existing_project_without_changing_identity(tmp_path: Path) -> None:
    source = Path(__file__).parents[1] / "config" / "decisions.template.yaml"
    target = tmp_path / "decisions.yaml"
    original = source.read_text(encoding="utf-8")
    # Simula un proyecto anterior a 0.89 RC4 quitando Colección del YAML actual.
    import yaml
    raw = yaml.safe_load(original)
    raw["archival_levels"] = [item for item in raw["archival_levels"] if item["key"] != "coleccion"]
    for index, item in enumerate(raw["archival_levels"]):
        item["display_order"] = index
        if item["key"] == "documento":
            item["parent_keys"] = [value for value in item["parent_keys"] if value != "coleccion"]
    for field in raw["descriptive_fields"]:
        field["applies_to_levels"] = [
            value for value in field["applies_to_levels"] if value != "coleccion"
        ]
    target.write_text(yaml.safe_dump(raw, allow_unicode=True, sort_keys=False), encoding="utf-8")
    before = load_decisions(target)

    assert add_standard_collection_level(target) is True
    assert add_standard_collection_level(target) is False
    after = load_decisions(target)
    assert after.project_name == before.project_name
    assert after.project_id == before.project_id
    levels = {item.key: item for item in after.archival_levels}
    assert levels["coleccion"].label == "Colección"
    assert levels["coleccion"].parent_keys == ["archivo"]
    assert levels["coleccion"].resolved_semantic_kind == "record_set"
    assert levels["coleccion"].resolved_record_set_type == "collection"
    assert "coleccion" in levels["documento"].parent_keys
    fields = {item.key: item for item in after.descriptive_fields}
    assert "coleccion" in fields["scope_content"].applies_to_levels
