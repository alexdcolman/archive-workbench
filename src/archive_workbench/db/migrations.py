from __future__ import annotations

from importlib.resources import as_file, files
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from archive_workbench.db.session import create_sqlite_engine, database_path, sqlite_url


def _new_config(db_path: Path, migrations_path: Path) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(migrations_path))
    cfg.set_main_option("sqlalchemy.url", sqlite_url(db_path))
    return cfg


def upgrade_database(project_root: str | Path, revision: str = "head") -> Path:
    db_path = database_path(project_root)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    migrations_ref = files("archive_workbench").joinpath("migrations")
    with as_file(migrations_ref) as migrations_path:
        command.upgrade(_new_config(db_path, migrations_path), revision)
    return db_path


def current_revision(project_root: str | Path) -> str | None:
    db_path = database_path(project_root)
    if not db_path.exists():
        return None
    engine = create_sqlite_engine(db_path)
    try:
        inspector = inspect(engine)
        if "alembic_version" not in inspector.get_table_names():
            return None
        with engine.connect() as connection:
            row = connection.exec_driver_sql("SELECT version_num FROM alembic_version").first()
            return str(row[0]) if row else None
    finally:
        engine.dispose()
