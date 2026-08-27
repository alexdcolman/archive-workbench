from __future__ import annotations

from pathlib import Path
import zipfile

from archive_workbench.db import create_sqlite_engine, database_path, session_scope
from archive_workbench.db.models import CorpusExportRun, Project, utc_now
from archive_workbench.project_admin import (
    check_project_health,
    create_project_backup,
    dismiss_project_health_issue,
    inspect_project_backup,
    list_project_backups,
    restore_project_backup,
    restore_project_health_issue,
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


def test_project_health_can_dismiss_expected_missing_export_and_restore_it(
    tmp_path: Path,
) -> None:
    root = tmp_path / "project"
    _seed_search_project(root)
    (root / "config").mkdir(parents=True, exist_ok=True)
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            session.add(
                CorpusExportRun(
                    id="missing-export",
                    project_id="search_project",
                    profile_id=None,
                    profile_name="Prueba",
                    profile_snapshot_json={},
                    corpus_state_sha256="0" * 64,
                    output_format="jsonl",
                    output_relative_path="exports/prueba_borrada.jsonl",
                    row_count=1,
                    character_count=10,
                    byte_size=10,
                    output_sha256="1" * 64,
                    created_by="tests",
                    created_at=utc_now(),
                )
            )
        with session_scope(engine) as session:
            report = check_project_health(session, project_root=root)
            issue = next(
                item for item in report.issues if item.code == "missing_export_file"
            )
            assert issue.dismissible
            assert issue.subject_key == "missing-export"

        dismiss_project_health_issue(
            project_root=root,
            issue=issue,
            dismissed_by="tests",
        )
        with session_scope(engine) as session:
            dismissed_report = check_project_health(session, project_root=root)
        assert not any(
            item.code == "missing_export_file" for item in dismissed_report.issues
        )
        assert any(
            item.code == "missing_export_file"
            for item in dismissed_report.dismissed_issues
        )

        backup = create_project_backup(
            project_root=root,
            created_by="tests",
            note="con aviso descartado",
        )
        with zipfile.ZipFile(backup.path, "r") as archive:
            assert "config/project_health_dismissals.json" in archive.namelist()

        restore_project_health_issue(project_root=root, issue=issue)
        with session_scope(engine) as session:
            restored_report = check_project_health(session, project_root=root)
        assert any(
            item.code == "missing_export_file" for item in restored_report.issues
        )
    finally:
        engine.dispose()


def test_project_health_respects_exports_omitted_from_team_copy(
    tmp_path: Path,
) -> None:
    root = tmp_path / "project"
    _seed_search_project(root)
    (root / "exchange").mkdir(parents=True, exist_ok=True)
    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            session.add(
                CorpusExportRun(
                    id="omitted-export",
                    project_id="search_project",
                    profile_id=None,
                    profile_name="Prueba",
                    profile_snapshot_json={},
                    corpus_state_sha256="0" * 64,
                    output_format="jsonl",
                    output_relative_path="exports/omitida.jsonl",
                    row_count=1,
                    character_count=10,
                    byte_size=10,
                    output_sha256="1" * 64,
                    created_by="tests",
                    created_at=utc_now(),
                )
            )
        (root / "exchange" / "team_copy.json").write_text(
            '{"omitted_content_groups":["exports"]}\n',
            encoding="utf-8",
        )
        with session_scope(engine) as session:
            report = check_project_health(session, project_root=root)
        assert not any(item.code == "missing_export_file" for item in report.issues)
    finally:
        engine.dispose()
