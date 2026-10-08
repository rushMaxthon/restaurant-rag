"""Fleet background work: the offer loop and the silent-rider sweep.

Both run on the `notifications` queue - an offer reaching a rider is as
time-critical as an order update reaching a customer, and both talk to
Firebase.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from app.config.celery import celery_app
from app.config.database import SessionLocal

logger = logging.getLogger(__name__)


@celery_app.task(name="app.tasks.fleet.sweep_riders_task")
def sweep_riders_task() -> dict[str, Any]:
    from app.services.fleet.riders import sweep_silent

    with SessionLocal() as db:
        return sweep_silent(db)


@celery_app.task(name="app.tasks.fleet.advance_delivery_task")
def advance_delivery_task(delivery_id: str) -> str:
    from app.services.fleet.offers import advance

    with SessionLocal() as db:
        return advance(db, uuid.UUID(delivery_id))


@celery_app.task(name="app.tasks.fleet.advance_offers_task")
def advance_offers_task() -> dict[str, int]:
    """Safety net: every own-fleet delivery still waiting for a rider gets one step.

    The API and the expiry countdown drive the loop on their own; this catches
    whatever a lost task or a worker restart left behind.
    """

    from sqlalchemy import select

    from app.models.order_delivery import OrderDelivery
    from app.services.fleet.offers import PROVIDER, advance

    with SessionLocal() as db:
        ids = db.scalars(
            select(OrderDelivery.id).where(OrderDelivery.provider == PROVIDER, OrderDelivery.state == "PENDING")
        ).all()
    counts: dict[str, int] = {}
    for delivery_id in ids:
        try:
            with SessionLocal() as db:
                result = advance(db, delivery_id)
        except Exception:  # noqa: BLE001 - one bad row must not stop the rest
            logger.exception("Offer loop failed for delivery %s", delivery_id)
            result = "error"
        counts[result] = counts.get(result, 0) + 1
    return counts
