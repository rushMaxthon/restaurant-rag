"""Which courier answers, and whether one is configured at all.

Platform-level rather than per-restaurant, which is the opposite of payments
and deliberate. A restaurant's payment account is its own money and must be
its own credentials; a courier account is the PLATFORM's commercial
relationship — Pidge distinguishes our tenants by `brand.code` and
`location_code` inside one account, not by separate logins. Per-restaurant
courier credentials would mean one Pidge contract per restaurant, which is
not how the product is sold.

`None` means "no courier", and callers treat that as delivery being
unavailable rather than as an error — exactly as `payments.registry` treats a
restaurant with no gateway.
"""

from __future__ import annotations

import logging
import threading

from app.config import get_settings
from app.services.delivery.base import DeliveryProvider
from app.services.delivery.pidge_provider import PROVIDER_NAME, PidgeProvider

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_provider: DeliveryProvider | None = None
_built = False


def delivery_provider() -> DeliveryProvider | None:
    """The configured courier, or None.

    Built once and held: the provider caches an auth token, and a fresh
    instance per call would log in on every order.
    """

    global _provider, _built
    with _lock:
        if _built:
            return _provider
        _built = True
        settings = get_settings()
        if not settings.enable_delivery_dispatch:
            logger.info("Delivery dispatch is switched off; no courier will be called")
            _provider = None
            return None
        candidate = PidgeProvider(
            base_url=settings.pidge_base_url,
            username=settings.pidge_username,
            password=settings.pidge_password,
            brand_code=settings.pidge_brand_code,
            brand_location_code=settings.pidge_brand_location_code,
            brand_name=settings.pidge_brand_name,
        )
        if not candidate.is_configured():
            logger.warning("Delivery dispatch is on but %s has no credentials", PROVIDER_NAME)
            _provider = None
            return None
        _provider = candidate
        return _provider


def reset_delivery_provider() -> None:
    """Forget the cached provider. For tests, and for a settings reload."""

    global _provider, _built
    with _lock:
        _provider = None
        _built = False


__all__ = ["delivery_provider", "reset_delivery_provider"]
