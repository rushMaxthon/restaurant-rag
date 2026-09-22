"""Whether a feature is on for a restaurant, and why.

The only module that may decide this. `config/capabilities.py` explains at
length why that matters — an allowlist of restaurant ids lived in this
codebase before, as a module constant, and was deleted for becoming a
permanent unexplained split.

**Resolution is `global flag AND tenant capability`.** The global flag can
only subtract: a deployment that has not got the feature at all keeps it off
everywhere, including where somebody has granted it, and the screen says so
through `BUILD_FLAG_OFF` rather than showing an operator a switch that does
nothing.

**Never fall back to enabled.** If the database cannot be reached the answer
is the catalog default, not "on". A feature that switches itself on during an
outage is worse than one that switches off: nobody is watching, and it is
usually the expensive one.
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.config.capabilities import (
    CAPABILITIES,
    CAPABILITY_KEYS,
    CapabilityDecision,
    CapabilityReason,
)
from app.models.restaurant_capability import RestaurantCapability

logger = logging.getLogger(__name__)


class UnknownCapability(ValueError):
    """A key this platform does not register.

    Refused rather than stored. A capability that exists only as a row has no
    label, no owner-facing sentence and no screen — which is precisely the
    shape of the mistake this system replaced.
    """


def validate_capability_key(key: str) -> str:
    normalized = (key or "").strip().lower()
    if normalized not in CAPABILITY_KEYS:
        known = ", ".join(sorted(CAPABILITY_KEYS))
        raise UnknownCapability(f"'{key}' is not a capability. Known keys: {known}.")
    return normalized


def _global_allows(capability_key: str) -> bool:
    """The deployment-wide kill switch for this capability, if it has one."""

    flag = CAPABILITIES[capability_key].global_flag
    if flag is None:
        return True
    return bool(getattr(get_settings(), flag, False))


def resolve_capabilities(
    db: Session,
    *,
    restaurant_id: uuid.UUID | None,
) -> dict[str, CapabilityDecision]:
    """Every capability for one restaurant, each with its reason.

    One query for the whole restaurant rather than one per key, because every
    caller that wants one wants the rest a moment later — the storefront sends
    them all to the client, and the admin screen renders them all as a list.

    `restaurant_id` of None is the marketplace, which is not a restaurant and
    therefore has no grants: it gets the catalog defaults.
    """

    stored: dict[str, bool] = {}
    if restaurant_id is not None:
        rows = db.execute(
            select(
                RestaurantCapability.capability_key,
                RestaurantCapability.is_enabled,
            ).where(RestaurantCapability.restaurant_id == restaurant_id)
        ).all()
        # Keys that have left the catalog are ignored rather than surfaced.
        # Deleting a capability should not make a screen fail to render.
        stored = {key: enabled for key, enabled in rows if key in CAPABILITY_KEYS}

    decisions: dict[str, CapabilityDecision] = {}
    for key, capability in CAPABILITIES.items():
        if not _global_allows(key):
            decisions[key] = CapabilityDecision(key, False, CapabilityReason.BUILD_FLAG_OFF)
            continue

        granted = stored.get(key)
        if granted is True:
            decisions[key] = CapabilityDecision(key, True, CapabilityReason.GRANTED)
        elif granted is False:
            decisions[key] = CapabilityDecision(key, False, CapabilityReason.REVOKED)
        elif capability.default:
            decisions[key] = CapabilityDecision(key, True, CapabilityReason.DEFAULT_ON)
        else:
            decisions[key] = CapabilityDecision(key, False, CapabilityReason.DEFAULT_OFF)

    return decisions


def client_capabilities(
    db: Session,
    *,
    restaurant_id: uuid.UUID | None,
) -> dict[str, bool]:
    """What the customer-facing clients are told, already combined.

    Only the `client_visible` subset, and only the boolean — a storefront never
    learns that a global flag exists, and operator-only capabilities never
    leave the admin API.
    """

    resolved = resolve_capabilities(db, restaurant_id=restaurant_id)
    return {
        key: decision.enabled
        for key, decision in resolved.items()
        if CAPABILITIES[key].client_visible
    }


def set_capability(
    db: Session,
    *,
    restaurant_id: uuid.UUID,
    capability_key: str,
    enabled: bool,
    granted_by_user_id: uuid.UUID | None,
    note: str | None = None,
) -> CapabilityDecision:
    """Switch one capability on or off for one restaurant.

    Writes a row either way. An explicit "off" is not the same fact as no row
    at all: one says somebody decided, the other says nobody has looked, and
    the difference is what an operator needs to see when a default later
    changes under them.

    The caller commits.
    """

    key = validate_capability_key(capability_key)
    row = db.get(RestaurantCapability, (restaurant_id, key))
    if row is None:
        row = RestaurantCapability(restaurant_id=restaurant_id, capability_key=key)
        db.add(row)

    row.is_enabled = enabled
    row.granted_by_user_id = granted_by_user_id
    row.note = (note or "").strip() or None

    logger.info(
        "Capability %s restaurant_id=%s -> %s by=%s",
        key,
        restaurant_id,
        "on" if enabled else "off",
        granted_by_user_id,
    )

    if not _global_allows(key):
        return CapabilityDecision(key, False, CapabilityReason.BUILD_FLAG_OFF)
    return CapabilityDecision(
        key,
        enabled,
        CapabilityReason.GRANTED if enabled else CapabilityReason.REVOKED,
    )


def clear_capability(db: Session, *, restaurant_id: uuid.UUID, capability_key: str) -> None:
    """Forget a decision, returning this restaurant to the catalog default.

    Distinct from switching it off, and worth having: an operator who granted
    something as a one-off should be able to say "treat this like everyone
    else" rather than pinning today's default in place forever.

    The caller commits.
    """

    key = validate_capability_key(capability_key)
    row = db.get(RestaurantCapability, (restaurant_id, key))
    if row is not None:
        db.delete(row)


__all__ = [
    "UnknownCapability",
    "clear_capability",
    "client_capabilities",
    "resolve_capabilities",
    "set_capability",
    "validate_capability_key",
]
