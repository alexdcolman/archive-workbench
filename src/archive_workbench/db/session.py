from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker


def database_path(project_root: str | Path) -> Path:
    return Path(project_root) / "data" / "archive_workbench.sqlite3"


def sqlite_url(path: str | Path) -> str:
    return f"sqlite:///{Path(path).resolve().as_posix()}"


def create_sqlite_engine(path: str | Path, *, echo: bool = False) -> Engine:
    db_path = Path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(sqlite_url(db_path), echo=echo, future=True)

    @event.listens_for(engine, "connect")
    def configure_sqlite(dbapi_connection, _connection_record) -> None:  # type: ignore[no-untyped-def]
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()

    return engine


@contextmanager
def session_scope(engine: Engine) -> Iterator[Session]:
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
