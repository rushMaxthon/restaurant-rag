"""The deployment must not ask for more connections than the pooler allows.

The second deploy to Render failed in the API's pre-deploy, before alembic
opened a single connection:

    FATAL: (EMAXCONNSESSION) max clients reached in session mode
           - max clients are limited to pool_size: 15

The ceiling is not Postgres `max_connections`. This deployment reaches
Supabase through its SESSION POOLER, which caps client connections per
project at 15. The blueprint had been sized by a comment reasoning about "100
connections on every Render Postgres plan under 8GB" — correct arithmetic for
the managed database in the commented-out `databases:` block, which is
deliberately not provisioned. So the numbers were right about a server that
does not exist in this topology, and (2 + 2 + 1) x 5 = 25 went straight past a
limit of 15.

This test is the arithmetic, kept somewhere that runs. It is deliberately
blunt: it re-derives the worst case from the blueprint itself rather than
trusting the comment beside the values, because the comment is exactly what
was wrong last time. Raise a gunicorn worker count, a celery concurrency or
either pool value without raising the pooler, and this fails here rather than
in a pre-deploy at the end of a six-minute build.

Parsed as text rather than with PyYAML, which is not in `requirements.txt` —
a test that silently skips because an import failed would be worse than no
test.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

BLUEPRINT = Path(__file__).resolve().parents[2] / "render.yaml"

#: What Supabase's session pooler allows this project, as its own error states
#: it. Raise this ONLY after raising it in the Supabase dashboard, under
#: Database -> Connection pooling.
POOLER_MAX_CLIENTS = 15

#: Celery's parent process holds a connection of its own alongside its
#: children, and beat is a single process. Counted explicitly so the sum below
#: is readable rather than a magic number.
CELERY_PARENT_PROCESSES = 1
BEAT_PROCESSES = 1


def blueprint() -> str:
    return BLUEPRINT.read_text(encoding="utf-8")


def group_value(key: str) -> int:
    """An integer literal from the shared env group."""

    match = re.search(
        rf"- key:\s*{re.escape(key)}\s*\n\s*value:\s*\"?(\d+)\"?",
        blueprint(),
    )
    if match is None:
        raise AssertionError(f"{key} is not set to a literal in render.yaml")
    return int(match.group(1))


def celery_concurrency() -> int:
    match = re.search(r"--concurrency=(\d+)", blueprint())
    if match is None:
        raise AssertionError("the worker declares no --concurrency")
    return int(match.group(1))


class TheConnectionBudget(unittest.TestCase):
    def test_the_worst_case_fits_under_the_pooler_cap(self) -> None:
        per_process = group_value("DB_POOL_SIZE") + group_value("DB_MAX_OVERFLOW")
        processes = (
            group_value("GUNICORN_WORKERS")
            + celery_concurrency()
            + CELERY_PARENT_PROCESSES
            + BEAT_PROCESSES
        )
        worst_case = processes * per_process

        self.assertLessEqual(
            worst_case,
            POOLER_MAX_CLIENTS,
            f"{processes} processes x {per_process} connections = {worst_case}, "
            f"against a pooler limit of {POOLER_MAX_CLIENTS}. Lower "
            f"DB_POOL_SIZE/DB_MAX_OVERFLOW, lower a process count, or raise the "
            f"pooler's own pool size in the Supabase dashboard first.",
        )

    def test_there_is_headroom_for_a_deploy(self) -> None:
        # During a deploy the OLD api instance is still connected while the new
        # one starts, so its share is paid twice for a few seconds. A budget
        # that only fits when nothing is deploying is a budget that fails every
        # time anything changes — which is precisely when someone is watching.
        per_process = group_value("DB_POOL_SIZE") + group_value("DB_MAX_OVERFLOW")
        api = group_value("GUNICORN_WORKERS") * per_process
        steady = (
            group_value("GUNICORN_WORKERS")
            + celery_concurrency()
            + CELERY_PARENT_PROCESSES
            + BEAT_PROCESSES
        ) * per_process

        self.assertLessEqual(
            steady + api,
            POOLER_MAX_CLIENTS,
            f"{steady} steady + {api} for the overlapping old api instance "
            f"exceeds the pooler limit of {POOLER_MAX_CLIENTS}.",
        )

    def test_the_unprovisioned_render_database_stays_unprovisioned(self) -> None:
        # The budget above is only correct while DATABASE_URL points at the
        # Supabase pooler. Uncommenting the `databases:` block changes the
        # ceiling from 15 to ~100 and makes every number here wrong in the
        # safe direction — but silently, and this test would keep passing
        # while the pool stayed needlessly tiny. Fail instead, so whoever
        # restores it reads this file.
        self.assertNotRegex(
            blueprint(),
            r"(?m)^databases:",
            "render.yaml now provisions a database; re-derive the connection "
            "budget in this test against its limit rather than the pooler's.",
        )


if __name__ == "__main__":
    unittest.main()
