"""Courier status, pushed.

**This endpoint does not trust its own payload, and that is the whole design.**

Pidge documents no signature, no shared secret and no verification of any kind
on its webhook — I looked, and there is nothing. An endpoint that moves an
order to DELIVERED on the strength of an unauthenticated POST is an endpoint
where anyone who learns the URL can mark every order delivered, close the
kitchen's tickets and strand the food.

So the push is treated as a *nudge*, never as news: it is read only for which
delivery it concerns, and the state is then fetched from the courier over our
own authenticated connection. A forged POST costs one API call and changes
nothing. When Pidge adds signing, `delivery_webhook_secret` below can become a
real check and this fetch becomes an optimisation rather than the guarantee.

The optional shared secret is defence in depth and not the guarantee either —
it travels in a URL, and URLs end up in logs and proxies.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.config import get_settings
from app.models.order_delivery import OrderDelivery
from app.services.delivery.base import DeliveryProviderError
from app.services.delivery.registry import delivery_provider
from app.services.delivery.service import record

logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter(prefix="/delivery", tags=["Delivery"])

#: Always 200. A courier that reads anything else retries, and a retry storm
#: over a payload we have deliberately ignored helps nobody.
ACCEPTED: dict[str, str] = {"status": "accepted"}


def _provider_order_id(body: Any) -> str:
    """The courier's own id for the delivery, wherever they put it.

    The only field read out of an untrusted payload, and it is used solely to
    look up a row we already have — never to create one, and never as a value
    that reaches the database.
    """

    if not isinstance(body, dict):
        return ""
    data = body.get("data")
    if isinstance(data, dict):
        found = data.get("id")
        if found:
            return str(found)
    found = body.get("id")
    return str(found) if found else ""


@router.post("/webhook", include_in_schema=False)
async def receive(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    secret: str | None = Header(default=None, alias="X-Delivery-Secret"),
) -> dict[str, str]:
    """Take a status push, confirm it with the courier, and record the truth."""

    if settings.delivery_webhook_secret and secret != settings.delivery_webhook_secret:
        logger.warning("Delivery webhook refused: wrong secret")
        return Response(status_code=status.HTTP_403_FORBIDDEN)  # type: ignore[return-value]

    try:
        body = await request.json()
    except ValueError:
        logger.warning("Delivery webhook was not JSON")
        return ACCEPTED

    provider_order_id = _provider_order_id(body)
    if not provider_order_id:
        logger.warning("Delivery webhook named no delivery")
        return ACCEPTED

    row = db.scalar(
        select(OrderDelivery).where(OrderDelivery.provider_order_id == provider_order_id)
    )
    if row is None:
        # Not ours, or ours and not yet stored. Either way there is nothing to
        # update, and saying so loudly would let anyone probe which ids exist.
        logger.info("Delivery webhook for an unknown delivery %s", provider_order_id)
        return ACCEPTED

    provider = delivery_provider()
    if provider is None:
        logger.warning("Delivery webhook arrived with no courier configured")
        return ACCEPTED

    try:
        # The payload said something happened. THIS is what actually happened.
        result = provider.fetch(provider_order_id)
    except DeliveryProviderError as error:
        # Their API is unreachable, so the push cannot be confirmed and is not
        # acted on. The courier will push again, and the admin can refresh by
        # hand in the meantime.
        logger.warning("Could not confirm delivery %s: %s", provider_order_id, error)
        return ACCEPTED

    before = row.state
    record(db, row, result)
    db.commit()
    if before != row.state:
        logger.info(
            "Delivery %s moved %s -> %s (order %s now %s)",
            provider_order_id,
            before,
            row.state,
            row.order_id,
            getattr(row.order, "status", "?"),
        )
    return ACCEPTED
