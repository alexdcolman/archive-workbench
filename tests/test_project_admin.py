from __future__ import annotations

from pathlib import Path

from archive_workbench.db import create_sqlite_engine, database_path, session_scope
from archive_workbench.db.models import Project
from archive_workbench.project_admin import (
    check_project_health,
    create_project_backup,
    inspect_project_backup,
    list_project_backups,
    restore_project_backup,
)
from tests.test_search import _seed_search_project


def test_project_health_and_backup_are_verifiable(tmp_path: Path) -> None:
    root = tmp_path / "project"
    _seed_search_project(root)
    (root / "config").mkdir(parents=True, exist_ok=True)
    (root / "config" / "decisions.yaml").write_text("project_id: search_project\n", encoding="utf-8")
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            report = check_project_health(session, project_root=root)
    finally:
        engine.dispose()
    assert report.error_count == 0

    backup = create_project_backup(project_root=root, created_by="tests", note="primero")
    inspected = inspect_project_backup(backup.path)
    assert inspected.database_sha256 == backup.database_sha256
    assert inspected.project_id == "search_project"
    assert len(list_project_backups(root)) == 1


def test_restore_creates_safety_backup_and_restores_database(tmp_path: Path) -> None:
    root = tmp_path / "project"
    _seed_search_project(root)
    (root / "config").mkdir(parents=True, exist_ok=True)
    (root / "config" / "decisions.yaml").write_text("project_id: search_project\n", encoding="utf-8")
    backup = create_project_backup(project_root=root, created_by="tests")

    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            session.get(Project, "search_project").name = "Nombre modificado"
    finally:
        engine.dispose()

    summary = restore_project_backup(
        project_root=root,
        backup_path=backup.path,
        restored_by="tests",
    )
    assert summary.safety_backup.exists()
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            assert session.get(Project, "search_project").name == "Search"
    finally:
        engine.dispose()
