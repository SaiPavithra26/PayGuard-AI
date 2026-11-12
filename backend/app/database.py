"""Database session management and engine initialization for PayLater Shield."""

import os
from pathlib import Path
from sqlite3 import Connection as SQLite3Connection
from typing import Generator
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.models.base import Base


def _enable_sqlite_foreign_keys(dbapi_connection: object, connection_record: object) -> None:
    """Enforce foreign key constraints on SQLite connections."""
    if isinstance(dbapi_connection, SQLite3Connection):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON;")
        cursor.close()


# Register listener globally on all Engine instances
event.listen(Engine, "connect", _enable_sqlite_foreign_keys)


def get_engine(db_url: str | None = None, echo: bool | None = None) -> Engine:
    """Create and return a configured SQLAlchemy engine."""
    url = db_url or settings.DATABASE_URL
    is_echo = echo if echo is not None else settings.DB_ECHO

    connect_args = {}
    if url.startswith("sqlite"):
        connect_args["check_same_thread"] = False

        # If a file path is provided in sqlite:///path, ensure directory exists
        if not url.startswith("sqlite:///:memory:"):
            db_path_str = url.replace("sqlite:///", "")
            db_path = Path(db_path_str)
            db_path.parent.mkdir(parents=True, exist_ok=True)

    return create_engine(
        url,
        echo=is_echo,
        connect_args=connect_args,
    )


# Default application engine and session factory
engine = get_engine()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db(target_engine: Engine | None = None) -> None:
    """Initialize database schema by creating all registered tables."""
    eng = target_engine or engine
    Base.metadata.create_all(bind=eng)


def drop_db(target_engine: Engine | None = None) -> None:
    """Drop all tables in the database (useful for test resets)."""
    eng = target_engine or engine
    Base.metadata.drop_all(bind=eng)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency for yielding transactional database sessions."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

