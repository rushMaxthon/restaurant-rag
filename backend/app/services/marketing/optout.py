"""Someone replied STOP. Make it stop.

Every SMS this product sends carries "Reply STOP to opt out" and every
WhatsApp template carries the same line, because both are required to. Until
now nothing read the replies — the footer was a promise the system could not
keep, which is worse than not offering it: a customer who does the one thing
they were told to do and keeps receiving messages has been actively misled,
and in most jurisdictions the restaurant is the one who answers for it.

Three decisions worth stating.

**A phone number identifies a person, not an account.** `AppClient` scoping
means the same phone can be two customer rows — one in the Marketplace app,
one in a single-restaurant app — and they are deliberately separate accounts
everywhere else in this product. Not here. Somebody texting STOP is telling us
to stop, and answering "you are still opted in on your other account" would be
a technicality used against them. Every matching customer is opted out.

**Opting out is global, not per restaurant.** The reply arrives on a channel,
not on a campaign: an SMS "STOP" carries no way to know which of several
restaurants prompted it, and guessing wrong leaves them still receiving the
messages they objected to. `marketing_opt_in` is a single flag and this sets
it false.

**Transactional messages are untouched.** Order updates are not marketing and
are not suppressed by consent — this module only writes `marketing_opt_in`,
and `notifications.py` never reads it.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.enums import (
    CampaignRecipientState,
    PushNotificationEventType,
    UserRole,
)
from app.models.push_notification_campaign_recipient import (
    PushNotificationCampaignRecipient,
)
from app.models.push_notification_event import PushNotificationEvent
from app.models.user import User
from app.services.auth import normalize_phone_number

logger = logging.getLogger(__name__)


#: What counts as "stop".
#:
#: The first four are the words carriers themselves recognise and are obliged
#: to honour, so a customer has every reason to expect them to work. The rest
#: are what people actually type. Matching is on the whole message, trimmed
#: and case-folded, with punctuation removed — "Stop." and "STOP!" are the
#: same instruction, but "stop sending me the chicken one" is a sentence and
#: is left for a human or the assistant to read.
STOP_WORDS = frozenset(
    {
        "stop",
        "stopall",
        "unsubscribe",
        "cancel",
        "end",
        "quit",
        "optout",
        "opt out",
        "stop all",
        "remove me",
    }
)

#: What counts as "start again", for the same reason the carriers require it:
#: an opt-out a customer cannot reverse from the same place is a trap.
START_WORDS = frozenset({"start", "unstop", "subscribe", "optin", "opt in", "resume"})


def _canonical(text: str) -> str:
    stripped = "".join(
        character for character in (text or "") if character.isalnum() or character.isspace()
    )
    return " ".join(stripped.lower().split())


def is_stop_word(text: str) -> bool:
    return _canonical(text) in STOP_WORDS


def is_start_word(text: str) -> bool:
    return _canonical(text) in START_WORDS


@dataclass(slots=True)
class OptOutResult:
    #: How many customer rows this phone resolved to. Zero is normal and not
    #: an error: someone can text STOP from a number we have never held.
    matched: int
    changed: int
    opted_in: bool


def _customers_for_phone(db: Session, phone_number: str) -> list[User]:
    """Every customer row holding this number, in any app.

    Matched on both the normalised form and the raw digits, because the
    column has been written by several paths over the product's life and
    holds both "+919876543210" and "9876543210".
    """

    normalized = normalize_phone_number(phone_number)
    if not normalized:
        return []
    digits = "".join(character for character in normalized if character.isdigit())
    if not digits:
        return []

    candidates = {normalized, digits, f"+{digits}"}
    return list(
        db.scalars(
            select(User).where(
                User.role == UserRole.CUSTOMER,
                or_(*[User.phone_number == value for value in candidates]),
            )
        ).all()
    )


def _attribute_to_recent_campaign(
    db: Session, user: User, *, now: datetime
) -> uuid.UUID | None:
    """The campaign this person most recently received, if any.

    An opt-out rate per campaign is how an owner learns that a piece of copy
    cost them their list, so the reply is credited to the message that most
    plausibly prompted it. "Most recent send to this person" is a guess and is
    the best one available — the reply itself carries no campaign id.
    """

    return db.scalars(
        select(PushNotificationCampaignRecipient.campaign_id)
        .where(
            PushNotificationCampaignRecipient.user_id == user.id,
            PushNotificationCampaignRecipient.state == CampaignRecipientState.SENT,
            PushNotificationCampaignRecipient.sent_at.is_not(None),
        )
        .order_by(PushNotificationCampaignRecipient.sent_at.desc())
        .limit(1)
    ).first()


def apply_reply(
    db: Session,
    *,
    phone_number: str,
    text: str,
    source: str,
    now: datetime | None = None,
) -> OptOutResult | None:
    """Honour a STOP or a START. Returns None when the text was neither.

    `source` is only for the log line — "whatsapp" or "sms" — because when an
    owner asks why a customer stopped receiving things, which channel they
    replied on is the first question.
    """

    now = now or datetime.now(UTC)
    stopping = is_stop_word(text)
    starting = is_start_word(text)
    if not stopping and not starting:
        return None

    customers = _customers_for_phone(db, phone_number)
    changed = 0
    for user in customers:
        if user.marketing_opt_in is not stopping:
            # Already in the state they are asking for. Recorded as matched
            # but not changed, so a customer texting STOP twice does not
            # produce two opt-out events and double-count against a campaign.
            continue
        user.marketing_opt_in = not stopping
        user.marketing_opt_in_changed_at = now
        db.add(user)
        changed += 1

        if stopping:
            campaign_id = _attribute_to_recent_campaign(db, user, now=now)
            if campaign_id is not None:
                db.add(
                    PushNotificationEvent(
                        campaign_id=campaign_id,
                        user_id=user.id,
                        event_type=PushNotificationEventType.UNSUBSCRIBED,
                        payload={"source": source, "at": now.isoformat()},
                    )
                )

    if changed:
        db.commit()
    else:
        db.rollback()

    logger.info(
        "Marketing %s reply from %s via %s matched=%s changed=%s",
        "STOP" if stopping else "START",
        phone_number[-4:] if phone_number else "?",
        source,
        len(customers),
        changed,
    )
    return OptOutResult(matched=len(customers), changed=changed, opted_in=not stopping)
