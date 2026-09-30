"""Marketing consent: reading it, changing it, and the one rule around it.

Consent here is opt-out. `users.marketing_opt_in` defaults true, so a customer
who has never been asked is reachable. That is the decision recorded in
migration `0063`; this module is where it is enforced rather than re-decided.

The single rule worth stating plainly: **this module is consulted by marketing
sends only.** A transactional push — "your order was accepted" — must go out to
a customer who has opted out of marketing, because it is not marketing and
withholding it would be a fault. Nothing in `notifications.py`'s order paths
imports from here, and nothing should start to.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.models.enums import UserRole
from app.models.user import User

logger = logging.getLogger(__name__)


def audience_base_conditions() -> list:
    """Who can be *in* a segment at all, before consent is considered.

    Consent is deliberately not here. The Hub shows an owner three descending
    numbers — segment members, audience after branch filtering, and reachable
    per channel — and consent belongs to the third. Folding it into segment
    membership would make people vanish between the segment card and the reach
    summary with nothing to explain the gap, which is exactly what
    `ChannelReach.blockers` exists to prevent.

    An unverified user is excluded: an unverified account can hold an address
    someone else controls, and a marketing message is the wrong thing to send
    there. The transactional path applies the same filter for the same reason.
    """

    return [
        User.role == UserRole.CUSTOMER,
        User.is_active.is_(True),
        User.is_verified.is_(True),
    ]


def opted_in_condition():
    """The consent predicate on its own, for composing into a reach query."""

    return User.marketing_opt_in.is_(True)


def marketing_reachable_conditions() -> list:
    """Everything a marketing send requires of a user: eligible *and* consenting."""

    return [*audience_base_conditions(), opted_in_condition()]


def opted_out_count_query(user_ids: list[uuid.UUID]) -> Select:
    """How many of these users have explicitly opted out.

    Used to itemise the reach breakdown. The owner is shown where their
    audience went rather than just a smaller number, and "not opted in to
    marketing" has to be a real count for that to be honest.
    """

    return select(User.id).where(
        User.id.in_(user_ids),
        User.marketing_opt_in.is_(False),
    )


def set_marketing_consent(
    db: Session,
    *,
    user: User,
    opted_in: bool,
) -> User:
    """Record a customer's marketing preference.

    `marketing_opt_in_changed_at` is stamped on every call, including one that
    re-affirms the current value. The timestamp answers "when did they last
    decide", and a customer re-confirming a preference is a decision — the
    interesting null is "never decided at all", which only the backfill leaves
    behind.
    """

    user.marketing_opt_in = opted_in
    user.marketing_opt_in_changed_at = datetime.now(UTC)
    db.add(user)
    db.commit()
    db.refresh(user)

    logger.info(
        "Marketing consent updated user_id=%s opted_in=%s",
        user.id,
        opted_in,
    )
    return user


def has_ever_decided(user: User) -> bool:
    """Whether this customer has actually expressed a preference.

    Distinguishes an assumption from a decision. Exposed so the UI can say "you
    have not set this" instead of asserting an opt-in the customer never made.
    """

    return user.marketing_opt_in_changed_at is not None
