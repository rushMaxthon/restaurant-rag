from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import Connection, create_engine, text
from sqlalchemy.exc import ProgrammingError
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
    """Ensure pgvector exists before any migration references a Vector column.

    The existence check is not an optimisation, it is the managed-Postgres path.
    pgvector's control file carries no `trusted = true`, so on a provider that
    hands out a plain database owner rather than a superuser — Render, and most
    others — `CREATE EXTENSION vector` answers:

        ERROR: permission denied to create extension "vector"
        HINT:  Must be superuser to create this extension.

    Measured behaviour: once the extension is present, `CREATE EXTENSION IF NOT
    EXISTS` succeeds for that same unprivileged role (Postgres short-circuits on
    the name before it checks privileges). So a one-off enable by the provider
    is enough forever, and looking first means the ordinary redeploy needs no
    privilege at all.

    When it is genuinely absent and uncreatable, the raw error names neither the
    database nor the fix, and it surfaces inside a deploy log where it reads as
    a broken migration. Replacing it with the one command that resolves it is
    the difference between a five-minute fix and an afternoon.
    """

    already_installed = connection.execute(
        text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
    ).scalar()
    if already_installed:
        return

    try:
        connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    except ProgrammingError as exc:
        connection.rollback()
        raise RuntimeError(
            "pgvector is not installed on this database and this role may not "
            "create it. Connect as a superuser (on Render: the database's psql "
            "shell, or a dashboard SQL console) and run once:\n"
            "    CREATE EXTENSION vector;\n"
            "Then redeploy — migrations need no elevated privilege afterwards."
        ) from exc

    connection.commit()


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
