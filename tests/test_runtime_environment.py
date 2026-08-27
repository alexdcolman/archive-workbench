from pathlib import Path

from archive_workbench.runtime_environment import (
    managed_runtime_variant,
    managed_workspace,
    workspace_display_path,
)
from archive_workbench.user_preferences import preferences_path


def _clear_workspace_env(monkeypatch) -> None:
    for name in (
        "ARCHIVE_WORKBENCH_WORKSPACE_ROOT",
        "ARCHIVE_WORKBENCH_PROJECTS_ROOT",
        "ARCHIVE_WORKBENCH_DOCUMENT_IMPORT_ROOT",
        "ARCHIVE_WORKBENCH_AUDIOVISUAL_IMPORT_ROOT",
        "ARCHIVE_WORKBENCH_SETTINGS_ROOT",
        "ARCHIVE_WORKBENCH_PREFERENCES_PATH",
        "ARCHIVE_WORKBENCH_RUNTIME_VARIANT",
    ):
        monkeypatch.delenv(name, raising=False)


def test_managed_workspace_is_disabled_without_distribution_environment(monkeypatch) -> None:
    _clear_workspace_env(monkeypatch)
    assert managed_workspace() is None


def test_managed_workspace_uses_explicit_and_default_subdirectories(tmp_path: Path, monkeypatch) -> None:
    _clear_workspace_env(monkeypatch)
    root = tmp_path / "workspace"
    projects = tmp_path / "projects-override"
    monkeypatch.setenv("ARCHIVE_WORKBENCH_WORKSPACE_ROOT", str(root))
    monkeypatch.setenv("ARCHIVE_WORKBENCH_PROJECTS_ROOT", str(projects))

    workspace = managed_workspace()

    assert workspace is not None
    assert workspace.root == root.resolve()
    assert workspace.projects == projects.resolve()
    assert workspace.document_imports == (root / "Imports" / "Documents").resolve()
    assert workspace.audiovisual_imports == (root / "Imports" / "AudioVideo").resolve()
    assert workspace.settings == (root / "Settings").resolve()


def test_workspace_display_path_uses_host_visible_distribution_name(tmp_path: Path, monkeypatch) -> None:
    _clear_workspace_env(monkeypatch)
    root = tmp_path / "workspace"
    monkeypatch.setenv("ARCHIVE_WORKBENCH_WORKSPACE_ROOT", str(root))

    assert workspace_display_path(root / "Projects" / "demo") == "ArchiveWorkbenchData/Projects/demo"
    assert workspace_display_path(tmp_path / "outside") == str((tmp_path / "outside").resolve())


def test_preferences_path_can_live_in_managed_workspace(tmp_path: Path, monkeypatch) -> None:
    _clear_workspace_env(monkeypatch)
    target = tmp_path / "workspace" / "Settings" / "preferences.json"
    monkeypatch.setenv("ARCHIVE_WORKBENCH_PREFERENCES_PATH", str(target))

    assert preferences_path() == target.resolve()


def test_managed_audiovisual_import_discovers_only_supported_media(tmp_path: Path) -> None:
    from archive_workbench.audiovisual_app import _managed_audiovisual_import_paths

    root = tmp_path / "imports"
    nested = root / "subcarpeta"
    nested.mkdir(parents=True)
    audio = root / "entrevista.mp3"
    video = nested / "registro.MP4"
    ignored = nested / "notas.txt"
    audio.write_bytes(b"audio")
    video.write_bytes(b"video")
    ignored.write_text("texto", encoding="utf-8")

    assert _managed_audiovisual_import_paths(root) == [audio.resolve(), video.resolve()]
    assert _managed_audiovisual_import_paths(tmp_path / "missing") == []


def test_managed_runtime_variant_is_explicit_and_bounded(monkeypatch) -> None:
    _clear_workspace_env(monkeypatch)
    assert managed_runtime_variant() is None

    monkeypatch.setenv("ARCHIVE_WORKBENCH_RUNTIME_VARIANT", "CPU")
    assert managed_runtime_variant() == "cpu"

    monkeypatch.setenv("ARCHIVE_WORKBENCH_RUNTIME_VARIANT", "gpu")
    assert managed_runtime_variant() == "gpu"

    monkeypatch.setenv("ARCHIVE_WORKBENCH_RUNTIME_VARIANT", "metal")
    assert managed_runtime_variant() is None
