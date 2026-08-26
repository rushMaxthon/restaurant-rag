"""Block until the database schema is at the revision this build expects.

Render deploys the API, the worker and beat from the same commit at the same
time, but only the API has a `preDeployCommand` running `alembic upgrade head`.
Nothing orders the three, so the worker and beat can start new code against the
old schema - which is exactly how a background job ended up selecting
`restaurants.theme` seconds before the column existed, and then crash-looping.

Adding a second `alembic upgrade head` to the workers would be worse: two or
three processes racing the same `alembic_version` row is the failure the API's
pre-deploy comment already warns about. So the workers do not migrate. They
wait, and the API's pre-deploy stays the single writer.

Exits 0 once the stamped revision matches the newest revision on disk, or
non-zero if it has not happened within the timeout - which fails the deploy
loudly instead of leaving a worker quietly erroring on every task.
"""

from __future__ import annotations

import logging
import os
import sys
import time

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text

from app.config import get_settings

logger = logging.getLogger("wait_for_schema")

# Long enough for a real migration to run, short enough that a genuinely stuck
# deploy is reported rather than hanging for ever.
DEFAULT_TIMEOUT_SECONDS = 300
POLL_SECONDS = 3


def expected_heads() -> set[str]:
    """The revisions this build's own migration files end at."""

    config = Config(os.path.join(os.path.dirname(__file__), "..", "..", "alembic.ini"))
    config.set_main_option(
        "script_location", os.path.join(os.path.dirname(__file__), "..", "..", "alembic")
    )
    return set(ScriptDirectory.from_config(config).get_heads())


def stamped_revisions(engine) -> set[str]:
    """What the database says it is at. Empty if it has never been migrated."""

    with engine.connect() as connection:
        exists = connection.execute(
            text(
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_name = 'alembic_version'"
            )
        ).scalar()
        if not exists:
            return set()
        rows = connection.execute(text("SELECT version_num FROM alembic_version")).all()
        return {row[0] for row in rows}


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    timeout = int(os.getenv("SCHEMA_WAIT_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS))
    settings = get_settings()
    engine = create_engine(settings.sqlalchemy_database_uri, pool_pre_ping=True)

    heads = expected_heads()
    logger.info("Waiting for schema revision(s) %s", ", ".join(sorted(heads)))

    deadline = time.monotonic() + timeout
    last_seen: set[str] | None = None
    while True:
        try:
            current = stamped_revisions(engine)
        except Exception as error:  # noqa: BLE001 - the database may still be starting
            current = None
            logger.info("Database not reachable yet (%s)", error)

        if current is not None:
            if current >= heads:
                logger.info("Schema is at %s; starting.", ", ".join(sorted(current)))
                return 0
            if current != last_seen:
                logger.info(
                    "Schema is at %s, waiting for %s",
                    ", ".join(sorted(current)) or "(unmigrated)",
                    ", ".join(sorted(heads - current)),
                )
                last_seen = current

        if time.monotonic() >= deadline:
            if current is None:
                where = "(unreachable)"
            elif not current:
                where = "(unmigrated)"
            else:
                where = ", ".join(sorted(current))
            logger.error(
                "Schema still at %s after %ss; expected %s. "
                "Has the API pre-deploy migration run?",
                where,
                timeout,
                ", ".join(sorted(heads)),
            )
            return 1

        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    sys.exit(main())
