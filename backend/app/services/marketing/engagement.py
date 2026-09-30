"""What a customer did with a campaign after it reached their phone.

Delivery is what the server observed; engagement is what the person did, and
only the device can report it. Until this existed, `opened_count` and
`clicked_count` were read by the campaign report and written by nothing — so
the funnel showed every campaign losing its whole audience between "delivered"
and "opened", which is the one place an owner looks to judge the copy.

Two rules shape everything here:

* **Counted once per person per kind.** A customer who opens a notification,
  dismisses it and opens it again has opened it once. The events table is the
  record of what happened; the counters on the campaign are a summary of
  distinct people, and a summary that double-counts is worse than none.
* **Only a real recipient may report.** The caller is authenticated, and the
  event is refused unless that user actually has a recipient row for that
  campaign. Otherwise any signed-in customer could inflate any campaign's
  numbers by posting ids at this endpoint.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import PushNotificationEventType
from app.models.push_notification_campaign import PushNotificationCampaign
from app.models.push_notification_campaign_recipient import (
    PushNotificationCampaignRecipient,
)
from app.models.push_notification_event import PushNotificationEvent
from app.models.user import User

logger = logging.getLogger(__name__)

#: The kinds a device may report. SENT, DELIVERED and FAILED are the server's
#: own observations and are deliberately not reportable from a client.
REPORTABLE = frozenset(
    {
        PushNotificationEventType.OPENED,
        PushNotificationEventType.CLICKED,
        PushNotificationEventType.UNSUBSCRIBED,
    }
)

#: Which campaign counter each kind summarises. UNSUBSCRIBED has none: the
#: opt-out itself lives on the user, and the event row is the attribution.
_COUNTER = {
    PushNotificationEventType.OPENED: "opened_count",
    PushNotificationEventType.CLICKED: "clicked_count",
}


class EngagementRefused(Exception):
    """The reporter is not a recipient of that campaign, or it is not theirs."""


def _already_recorded(
    db: Session,
    *,
    campaign_id: uuid.UUID,
    user_id: uuid.UUID,
    event_type: PushNotificationEventType,
) -> bool:
    return (
        db.scalar(
            select(PushNotificationEvent.id).where(
                PushNotificationEvent.campaign_id == campaign_id,
                PushNotificationEvent.user_id == user_id,
                PushNotificationEvent.event_type == event_type,
            )
        )
        is not None
    )


def record_engagement(
    db: Session,
    *,
    campaign_id: uuid.UUID,
    user: User,
    event_type: PushNotificationEventType,
) -> bool:
    """Record one engagement. Returns whether it counted as a new one.

    A repeat is not an error — a phone may report the same open twice, and a
    client that had to distinguish "recorded" from "already recorded" would be
    a client that retries into a double count. It is written once and reported
    honestly.
    """

    if event_type not in REPORTABLE:
        raise EngagementRefused("That event cannot be reported by a device.")

    recipient = db.scalar(
        select(PushNotificationCampaignRecipient).where(
            PushNotificationCampaignRecipient.campaign_id == campaign_id,
            PushNotificationCampaignRecipient.user_id == user.id,
        )
    )
    if recipient is None:
        # Deliberately the same refusal whether the campaign does not exist or
        # simply never went to this person: the reply must not tell a customer
        # which campaigns a restaurant has run.
        raise EngagementRefused("No campaign was sent to you with that id.")

    if _already_recorded(
        db, campaign_id=campaign_id, user_id=user.id, event_type=event_type
    ):
        return False

    db.add(
        PushNotificationEvent(
            campaign_id=campaign_id,
            user_id=user.id,
            event_type=event_type,
            payload={"source": "device", "at": datetime.now(UTC).isoformat()},
        )
    )

    counter = _COUNTER.get(event_type)
    if counter is not None:
        campaign = db.get(PushNotificationCampaign, campaign_id)
        if campaign is not None:
            setattr(campaign, counter, (getattr(campaign, counter) or 0) + 1)
            db.add(campaign)

    db.commit()
    logger.info(
        "Marketing engagement recorded campaign=%s user=%s event=%s",
        campaign_id,
        user.id,
        event_type.value,
    )
    return True
