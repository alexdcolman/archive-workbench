from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from typer.testing import CliRunner

from archive_workbench.db import (
    create_sqlite_engine,
    current_revision,
    database_path,
    session_scope,
    upgrade_database,
)
from archive_workbench.cli import app
from archive_workbench.operational import (
    operational_readiness,
    recovery_check_rows,
    run_project_backup_recovery_test,
)
import archive_workbench.project_admin as project_admin
from archive_workbench.project_admin import create_project_backup, list_project_backups
from archive_workbench.db.models import Project
from tests.test_search import _seed_search_project


class _FixedDateTime(datetime):
    current = datetime(2026, 1, 1, tzinfo=timezone.utc)

    @classmethod
    def now(cls, tz=None):
        value = cls.current
        return value if tz is None else value.astimezone(tz)


def test_backup_order_and_readiness_use_manifest_creation_time(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "project"
    _seed_search_project(root)
    (root / "config").mkdir(parents=True, exist_ok=True)
    (root / "config" / "decisions.yaml").write_text(
        "project_id: search_project\n", encoding="utf-8"
    )

    monkeypatch.setattr(project_admin, "datetime", _FixedDateTime)

    _FixedDateTime.current = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
    older = create_project_backup(
        project_root=root,
        created_by="tests",
        output_path=root / "backups" / "project" / "z_older.zip",
    )
    _FixedDateTime.current = datetime(2026, 1, 2, 12, tzinfo=timezone.utc)
    newer = create_project_backup(
        project_root=root,
        created_by="tests",
        output_path=root / "backups" / "project" / "a_newer.zip",
    )

    assert [row.path.name for row in list_project_backups(root)] == [
        "a_newer.zip",
        "z_older.zip",
    ]

    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            result = run_project_backup_recovery_test(
                session,
                project_root=root,
                backup_path=older.path,
                tested_by="tests",
            )
            assert result.status == "completed"

        with session_scope(engine) as session:
            report = operational_readiness(session, project_root=root)
            recovery = next(item for item in report.items if item.key == "recovery")
            assert recovery.status == "attention"
            assert recovery.summary == "El backup más reciente todavía no fue probado."

        with session_scope(engine) as session:
            result = run_project_backup_recovery_test(
                session,
                project_root=root,
                backup_path=newer.path,
                tested_by="tests",
            )
            assert result.status == "completed"

        with session_scope(engine) as session:
            report = operational_readiness(session, project_root=root)
            recovery = next(item for item in report.items if item.key == "recovery")
            assert recovery.status == "ready"
    finally:
        engine.dispose()


def test_readiness_marks_recovery_until_latest_backup_is_tested(tmp_path: Path) -> None:
    root = tmp_path / "project"
    _seed_search_project(root)
    (root / "config").mkdir(parents=True, exist_ok=True)
    (root / "config" / "decisions.yaml").write_text(
        "project_id: search_project\n", encoding="utf-8"
    )

    engine = create_sqlite_engine(database_path(root))
    try:
        with session_scope(engine) as session:
            initial = operational_readiness(session, project_root=root)
            recovery = next(item for item in initial.items if item.key == "recovery")
            assert recovery.status == "attention"

        backup = create_project_backup(project_root=root, created_by="tests")
        with session_scope(engine) as session:
            result = run_project_backup_recovery_test(
                session,
                project_root=root,
                backup_path=backup.path,
                tested_by="tests",
            )
            assert result.status == "completed"
            assert result.upgraded_database_revision == "0043_form_structure_review"

        with session_scope(engine) as session:
            report = operational_readiness(session, project_root=root)
            recovery = next(item for item in report.items if item.key == "recovery")
            assert recovery.status == "ready"
            rows = recovery_check_rows(session)
            assert len(rows) == 1
            assert rows[0].backup_sha256 == backup.backup_sha256
    finally:
        engine.dispose()


def test_recovery_test_rejects_backup_from_another_project_without_touching_active(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    _seed_search_project(first)
    (first / "config").mkdir(parents=True, exist_ok=True)
    (first / "config" / "decisions.yaml").write_text("project_id: search_project\n", encoding="utf-8")
    backup = create_project_backup(project_root=first, created_by="tests")

    upgrade_database(second)
    engine = create_sqlite_engine(database_path(second))
    try:
        with session_scope(engine) as session:
            session.add(
                Project(
                    id="other_project",
                    name="Otro",
                    decisions_schema_version="1.0",
                    decisions_json={"project_id": "other_project"},
                )
            )
        with session_scope(engine) as session:
            result = run_project_backup_recovery_test(
                session,
                project_root=second,
                backup_path=backup.path,
                tested_by="tests",
            )
            assert result.status == "failed"
            assert "pertenece al proyecto" in result.details["error"]
        with session_scope(engine) as session:
            rows = recovery_check_rows(session)
            assert rows[0].status == "failed"
    finally:
        engine.dispose()


def test_project_backup_create_does_not_upgrade_database(tmp_path: Path) -> None:
    root = tmp_path / "project"
    upgrade_database(root, revision="0030_source_replaced_exchange")
    assert current_revision(root) == "0030_source_replaced_exchange"

    result = CliRunner().invoke(
        app,
        [
            "project-backup-create",
            str(root),
            "--created-by",
            "tests",
            "--note",
            "Backup anterior a 0031",
        ],
    )

    assert result.exit_code == 0, result.output
    assert current_revision(root) == "0030_source_replaced_exchange"
    assert "Revisión: 0030_source_replaced_exchange" in result.output


def test_exchange_status_does_not_upgrade_outdated_database(tmp_path: Path) -> None:
    root = tmp_path / "project"
    upgrade_database(root, revision="0030_source_replaced_exchange")

    result = CliRunner().invoke(app, ["exchange-status", str(root)])

    assert result.exit_code != 0
    assert "No se aplicó ninguna" in result.output
    assert "migración." in result.output
    assert "db-upgrade" in result.output
    assert current_revision(root) == "0030_source_replaced_exchange"


def test_only_db_upgrade_command_invokes_upgrade_database() -> None:
    import ast
    import inspect
    import archive_workbench.cli as cli_module

    tree = ast.parse(inspect.getsource(cli_module))
    callers: set[str] = set()
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if any(
            isinstance(item, ast.Call)
            and isinstance(item.func, ast.Name)
            and item.func.id == "upgrade_database"
            for item in ast.walk(node)
        ):
            callers.add(node.name)

    assert callers == {"db_upgrade"}
