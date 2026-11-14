"""SQLite engine and session helper."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine

BACKEND_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = BACKEND_ROOT / "data"
DEFAULT_DB_PATH = DATA_DIR / "tremorband.db"


def database_url() -> str:
    """Return the SQLite URL, or DATABASE_URL when the environment sets one."""
    configured = os.environ.get("DATABASE_URL")
    if configured:
        return configured
    return f"sqlite:///{DEFAULT_DB_PATH}"


def _is_sqlite(url: str) -> bool:
    return url.startswith("sqlite:")


ENGINE_URL = database_url()
connect_args = {"check_same_thread": False} if _is_sqlite(ENGINE_URL) else {}
engine = create_engine(ENGINE_URL, connect_args=connect_args)


@event.listens_for(Engine, "connect")
def _sqlite_pragmas(dbapi_connection, _connection_record) -> None:
    """Enable foreign keys and WAL on each SQLite connection."""
    if not _is_sqlite(ENGINE_URL):
        return
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.close()


def init_db() -> None:
    """Create the data directory and any missing tables."""
    if _is_sqlite(ENGINE_URL):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
    from app import models  # noqa: F401

    SQLModel.metadata.create_all(engine)


def get_session() -> Iterator[Session]:
    """Yield a database session and roll it back when a request fails."""
    with Session(engine) as session:
        try:
            yield session
        except Exception:
            session.rollback()
            raise
