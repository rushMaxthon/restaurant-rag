"""Wait for the schema, then become Celery.

This exists because of how Render runs `dockerCommand`, and the failure it
prevents is not subtle - it is both Celery services crash-looping from the
first second of the first deploy, with this in the log:

    sh: 1: python -m app.scripts.wait_for_schema && exec celery -A
    app.config.celery:celery_app worker --loglevel=info --queues=... : not found

Read that carefully: `sh` is naming the WHOLE command as the program it could
not find. The blueprint asked for `sh -c "python -m ... && exec celery ..."`,
which is correct Docker and correct shell. Render consumes the `sh -c ` itself
and passes the remainder to its own shell with the double quotes still in it,
so that shell strips them and is left with a single enormous word. The `&&`
is never parsed as an operator, and nothing runs.

So the command Render is given must survive being split on whitespace by
something that does not understand quoting: one program, no quotes, no `&&`,
no `exec`. That is this module. The two steps that used to be joined by `&&`
are joined here instead, where they are ordinary Python.

`os.execvp` and not `subprocess`: it REPLACES this process, so Celery keeps
PID 1 and receives the SIGTERM Render sends at shutdown directly. Wrapping it
in a parent would swallow that signal and turn every deploy into a 30-second
kill timeout with tasks cut off mid-flight.

Why the wait is still here at all, unchanged: Render deploys the API, the
worker and beat from one commit with nothing ordering them, and only the API
has a `preDeployCommand` running the migration. Without the wait the workers
start new code against the old schema. They deliberately do not migrate
themselves - two processes racing the same `alembic_version` row is the
failure the API's pre-deploy exists to avoid. See `wait_for_schema`.

Used as:

    python -m app.scripts.start_celery -A app.config.celery:celery_app worker ...
    python -m app.scripts.start_celery -A app.config.celery:celery_app beat ...

Everything after the module name is passed to `celery` untouched, so the flags
stay readable in `render.yaml` and mean exactly what they mean to Celery.
"""

from __future__ import annotations

import os
import sys

from app.scripts.wait_for_schema import main as wait_for_schema


def main(argv: list[str] | None = None) -> int:
    """Wait, then exec. Returns only on failure - success never comes back."""

    arguments = list(sys.argv[1:] if argv is None else argv)
    if not arguments:
        # A dockerCommand that lost its arguments would otherwise start a bare
        # `celery` with no app and fail in a way that reads like a Celery
        # problem rather than a configuration one.
        print(
            "start_celery needs the celery arguments, e.g. "
            "-A app.config.celery:celery_app worker --loglevel=info",
            file=sys.stderr,
        )
        return 2

    waited = wait_for_schema()
    if waited != 0:
        # The schema never arrived. Exiting non-zero fails the deploy loudly
        # instead of leaving a worker erroring on every task it picks up.
        return waited

    os.execvp("celery", ["celery", *arguments])
    # Unreachable: execvp either replaces this process or raises OSError.
    return 1  # pragma: no cover


if __name__ == "__main__":
    raise SystemExit(main())
