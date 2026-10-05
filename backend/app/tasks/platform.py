"""A pulse, so the admin can tell whether scheduled work is happening.

Beat sends this every minute and a worker runs it, so a fresh timestamp
proves both are alive. Without it the only sign that beat had stopped was
the absence of things - unpaid orders not cleaned up, the morning stock
refill not happening - which nobody notices until a customer does.
Read by `services.platform_watch`.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.config.celery import celery_app
from app.services.cache import get_redis_client
from app.services.platform_watch import HEARTBEAT_KEY


@celery_app.task(name="app.tasks.platform.heartbeat_task")
def heartbeat_task() -> str:
    stamp = datetime.now(UTC).isoformat()
    # An hour, so a long-dead scheduler reads as "stopped N minutes ago"
    # rather than "never seen" for a while, then as never seen.
    get_redis_client().set(HEARTBEAT_KEY, stamp, ex=3600)
    return stamp
