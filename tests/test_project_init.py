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


def test_init_copies_preferred_surya_and_docling_fallback(tmp_path: Path) -> None:
    templates = tmp_path / "templates"
    templates.mkdir()
    (templates / "extraction.template.yaml").write_text(
        "profile_key: surya_preferred\nbackend: surya_cli\n",
        encoding="utf-8",
    )
    (templates / "extraction_docling_es.template.yaml").write_text(
        "profile_key: docling_fallback\nbackend: docling_cli\n",
        encoding="utf-8",
    )
    (templates / "extraction_surya_es.template.yaml").write_text(
        "profile_key: surya_explicit\nbackend: surya_cli\n",
        encoding="utf-8",
    )

    root = initialize_project(tmp_path / "project", templates)

    assert (root / "config/extraction.yaml").is_file()
    assert (root / "config/extraction_docling_es.yaml").is_file()
    assert (root / "config/extraction_surya_es.yaml").is_file()


def test_init_refuses_existing_destination_unless_explicitly_allowed(tmp_path: Path) -> None:
    destination = tmp_path / "existing"
    destination.mkdir()

    try:
        initialize_project(destination)
    except FileExistsError as exc:
        assert "ya existe" in str(exc)
    else:
        raise AssertionError("initialize_project debía rechazar una carpeta existente")

    root = initialize_project(destination, allow_existing=True)
    assert root == destination
    assert (root / "config").is_dir()
    assert (root / "corpus").is_dir()
