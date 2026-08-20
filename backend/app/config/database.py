from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import Connection, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings

settings = get_settings()

engine = create_engine(
    settings.sqlalchemy_database_uri,
    echo=settings.database_echo,
    # Verifies a pooled connection is still alive before handing it out, which
    # matters behind any proxy or managed server that drops idle connections.
    pool_pre_ping=True,
    # Sized explicitly rather than left at SQLAlchemy's defaults: the pool is
    # per process, so every gunicorn worker and every Celery child multiplies
    # it, and the total has to fit inside the server's `max_connections`. See
    # the note on `db_pool_size` in settings.py for the arithmetic.
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_recycle=settings.db_pool_recycle,
    pool_timeout=settings.db_pool_timeout,
)

SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
    class_=Session,
)


def initialize_pg_extensions(connection: Connection) -> None:
    connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    connection.commit()


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
