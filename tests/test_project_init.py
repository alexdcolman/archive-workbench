from pathlib import Path

from archive_workbench.project_init import initialize_project


def test_init_prefers_completed_config(tmp_path: Path) -> None:
    templates = tmp_path / "templates"
    templates.mkdir()
    (templates / "decisions.yaml").write_text("project_name: completed\n", encoding="utf-8")
    (templates / "decisions.template.yaml").write_text("project_name: generic\n", encoding="utf-8")
    (templates / "test_corpus.yaml").write_text("corpus_name: completed\n", encoding="utf-8")
    root = initialize_project(tmp_path / "project", templates)
    assert (root / "corpus").is_dir()
    assert "completed" in (root / "config" / "decisions.yaml").read_text(encoding="utf-8")
