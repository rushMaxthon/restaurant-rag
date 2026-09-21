from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import Connection, create_engine, event, text
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

# pgvector's IVFFlat index is APPROXIMATE: a query scans `probes` of the
# index's `lists` and never looks at the rest. Postgres then applies the WHERE
# clause to what came back. Every menu search in this application filters by
# restaurant and branch, so that ordering is exactly wrong for us — the index
# narrows first, on similarity across every tenant, and the tenant filter runs
# second, on the survivors.
#
# The server default is `probes = 1`, and `menu_embeddings` is built WITH
# (lists = 14). Measured on this database: asking for "tofu" at Radhe Dhokla,
# which has 136 embedded items, returned NOTHING — one list in fourteen, and
# the tofu neighbourhood belongs to another restaurant's menu. Not an error, not
# a slow answer: an empty retrieval, which downstream reads as "no evidence
# about this dish" and answers with a fuzzy-name guess instead. That is how
# "red curry tofu" became "Which size for Kaju Curry (Brown)?".
#
# Set far above any plausible `lists`, because pgvector clamps it: the effect is
# "scan every list", which makes the search exact. Matching today's 14 would
# under-probe again the first time the index was rebuilt larger, silently and
# in the same way.
#
# It is not a trade here. Platform-wide there are ~1,300 embeddings, and full
# probing measured 66.8ms against an exact scan's 67.1ms — both dominated by the
# round trip, not the search. If that corpus ever grows enough for exact search
# to hurt, the answer is a different index (HNSW, or partitioning by tenant),
# NOT fewer probes: fewer probes does not cost recall evenly, it costs whole
# tenants their own menu.
IVFFLAT_PROBES = 1000


def set_vector_probes(dbapi_connection: object, _connection_record: object) -> None:
    """Make vector search exact for this connection, once, on connect.

    Per connection rather than per query: it is a session GUC, the pool hands
    the same connections out repeatedly, and a `SET` before each search would
    add a round trip to every menu lookup — 67ms here — to configure something
    that never changes.

    Never raises. A Postgres that has never loaded pgvector does not know this
    setting, and a connect listener that throws takes down every connection in
    the pool: a search-quality fix presenting as a total outage.
    """

    try:
        cursor = dbapi_connection.cursor()
    except Exception:  # pragma: no cover - a driver with no cursor to give
        return
    try:
        cursor.execute(f"SET ivfflat.probes = {IVFFLAT_PROBES}")
    except Exception:
        pass
    finally:
        try:
            cursor.close()
        except Exception:  # pragma: no cover
            pass


event.listen(engine, "connect", set_vector_probes)


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
