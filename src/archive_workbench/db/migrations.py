from __future__ import annotations

from importlib.resources import as_file, files
from pathlib import Path
import threading

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import inspect

from archive_workbench.db.session import create_sqlite_engine, database_path, sqlite_url


_MIGRATION_LOCK = threading.RLock()


def _new_config(db_path: Path, migrations_path: Path) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(migrations_path))
    cfg.set_main_option("sqlalchemy.url", sqlite_url(db_path))
    return cfg


def upgrade_database(project_root: str | Path, revision: str = "head") -> Path:
    """Ejecuta Alembic de forma serial dentro del proceso actual.

    Alembic mantiene proxies globales durante ``command.upgrade`` y no es seguro
    ejecutar dos migraciones simultáneas desde sesiones/reruns de Streamlit.
    Serializar este tramo evita bases parcialmente migradas y estados internos
    de Alembic corruptos sin introducir migraciones implícitas adicionales.
    """

    db_path = database_path(project_root)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    migrations_ref = files("archive_workbench").joinpath("migrations")
    with _MIGRATION_LOCK:
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

class DatabaseRevisionError(ValueError):
    """La base no está lista para operar con la versión instalada."""


def head_revision() -> str:
    migrations_ref = files("archive_workbench").joinpath("migrations")
    with as_file(migrations_ref) as migrations_path:
        script = ScriptDirectory.from_config(
            _new_config(Path(":memory:"), migrations_path)
        )
        head = script.get_current_head()
    if head is None:
        raise RuntimeError("No se pudo determinar la revisión actual de la aplicación")
    return str(head)


def require_current_database(project_root: str | Path) -> Path:
    """Comprueba la revisión sin ejecutar migraciones implícitas."""
    root = Path(project_root)
    db_path = database_path(root)
    expected = head_revision()
    actual = current_revision(root)
    if not db_path.is_file():
        raise DatabaseRevisionError(
            "La base todavía no existe. Ejecutá explícitamente: "
            f"archive-workbench db-upgrade {root}"
        )
    if actual != expected:
        shown = actual or "sin revisión Alembic"
        raise DatabaseRevisionError(
            f"La base está en {shown} y esta versión requiere {expected}. "
            "No se aplicó ninguna migración. Ejecutá explícitamente: "
            f"archive-workbench db-upgrade {root}"
        )
    return db_path
