"""How many people a campaign can actually reach, and what would stop it.

This module exists separately from `campaigns.py` for one reason: **the same
checks run twice.** Once while the owner is building a draft, to show them the
numbers, and again at dispatch against data that may have moved in between — a
customer opts out, a branch closes, an offer expires, the scheduled hour
arrives late. The UI only surfaces what this returns; it never decides.

The descending numbers the Hub shows are three different facts and are kept
distinct on purpose:

    segment_members   everyone matching the segment, all branches
    audience_size     after branch filtering
    reachable         after consent, device and frequency capping, per channel

Every person lost between `audience_size` and `reachable` is itemised in
`blockers`. An owner watching their audience shrink from 418 to 390 with no
explanation will assume the product is broken, and they will be right to.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import distinct, func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.enums import (
    CampaignRecipientState,
    MarketingChannel,
    MarketingChannelFamily,
    MarketingNoticeTone,
    MarketingSegmentKey,
    PushNotificationCampaignKind,
    PushNotificationCampaignStatus,
    channel_family,
)
from app.models.push_notification_campaign import PushNotificationCampaign
from app.models.push_notification_campaign_recipient import (
    PushNotificationCampaignRecipient,
)
from app.models.restaurant_location import RestaurantLocation
from app.models.user import User
from app.models.user_device_token import UserDeviceToken
from app.services.marketing.catalog import (
    FREQUENCY_CAP_PER_WEEK,
    MINIMUM_SEGMENT_SIZE,
    QUIET_HOURS_END,
    QUIET_HOURS_START,
    branch_hours,
)
from app.services.marketing.connections import list_connections, live_channels
from app.services.marketing.providers.sms import parts as sms_parts
from app.services.marketing.consent import opted_in_condition
from app.services.marketing.segments import (
    SegmentUnavailable,
    list_segment_member_ids,
    segment_member_query,
)

logger = logging.getLogger(__name__)
settings = get_settings()


@dataclass(frozen=True, slots=True)
class Notice:
    id: str
    tone: MarketingNoticeTone
    title: str
    description: str


@dataclass(frozen=True, slots=True)
class ChannelReach:
    channel: MarketingChannel
    available: bool
    reachable: int
    blockers: list[dict]
    estimated_cost: float
    unavailable_reason: str | None = None


@dataclass(slots=True)
class ReachResult:
    segment_members: int
    audience_size: int
    channels: list[ChannelReach]
    notices: list[Notice] = field(default_factory=list)
    minimum_segment_size: int = MINIMUM_SEGMENT_SIZE
    #: The user ids a send would actually go to. Not serialised to the client —
    #: the owner gets counts, never a list of their customers' identities.
    reachable_user_ids: list[uuid.UUID] = field(default_factory=list)

    def blocked(self) -> bool:
        return any(notice.tone == MarketingNoticeTone.BLOCK for notice in self.notices)

    def blocking_reason(self) -> str | None:
        for notice in self.notices:
            if notice.tone == MarketingNoticeTone.BLOCK:
                return notice.title
        return None


# --- frequency capping -----------------------------------------------------


def recently_messaged_user_ids(
    db: Session,
    *,
    restaurant_id: uuid.UUID,
    user_ids: list[uuid.UUID],
    now: datetime,
) -> set[uuid.UUID]:
    """Who has already had their weekly allowance of marketing from this restaurant.

    **Counted from recipient rows, which is what makes the cap real.** It used
    to count `push_notification_events` of type SENT or DELIVERED — and
    nothing has ever written those. The only writer of that table is
    `engagement.py`, whose request schema restricts the event to OPENED,
    CLICKED or UNSUBSCRIBED, so the query matched zero rows and the cap
    suppressed nobody. Every owner was told on the schedule screen that
    "anyone who already heard from you this week is left out automatically",
    and it was not true. Migration `0069`'s docstring predicted exactly this
    fix: recipients are what turn the cap from an inference into a fact.

    A row counts when it reached the customer — SENT — and not when it was
    skipped or failed. Somebody the last campaign could not reach has not had
    their allowance used up, and holding a message back from them because of a
    delivery we never made would be the wrong way round.

    Only MARKETING campaigns count. An order-status update is not a marketing
    message, and letting a busy week of order updates suppress a campaign
    would penalise exactly the customers who order most.

    The cap is deliberately counted across every channel rather than per
    channel. Three pushes, three texts and three emails in a week is nine
    messages from one restaurant, and the person on the receiving end does not
    experience them as three separate allowances.
    """

    if not user_ids:
        return set()

    since = now - timedelta(days=7)
    rows = db.execute(
        select(
            PushNotificationCampaignRecipient.user_id,
            func.count(distinct(PushNotificationCampaignRecipient.campaign_id)).label(
                "sends"
            ),
        )
        .join(
            PushNotificationCampaign,
            PushNotificationCampaign.id
            == PushNotificationCampaignRecipient.campaign_id,
        )
        .where(
            PushNotificationCampaignRecipient.user_id.in_(user_ids),
            PushNotificationCampaignRecipient.state == CampaignRecipientState.SENT,
            # `sent_at`, not `created_at`: a row is written when the send
            # starts and stamped when it actually goes, and a campaign that
            # sat in SENDING overnight must not count against yesterday.
            PushNotificationCampaignRecipient.sent_at.is_not(None),
            PushNotificationCampaignRecipient.sent_at >= since,
            PushNotificationCampaign.kind == PushNotificationCampaignKind.MARKETING,
            PushNotificationCampaign.restaurant_id == restaurant_id,
        )
        .group_by(PushNotificationCampaignRecipient.user_id)
        .having(
            func.count(distinct(PushNotificationCampaignRecipient.campaign_id))
            >= FREQUENCY_CAP_PER_WEEK
        )
    ).all()

    return {row[0] for row in rows if row[0] is not None}


# --- per-channel reach -----------------------------------------------------


@dataclass(frozen=True, slots=True)
class _AddressRule:
    """How to tell whether a customer is reachable on one channel.

    `condition` is a SQL predicate rather than a Python check so the count is
    one query over the audience instead of one row per customer — an audience
    of ten thousand is normal and fetching all of it to look at a column is
    not.

    `blocker` is what the owner reads when somebody fails it, and it is
    written to be actionable: "No mobile number on file" tells them to collect
    phone numbers, where "ineligible" tells them nothing.
    """

    condition: object
    blocker: str
    cost_per_message: float = 0.0


def _address_rule(channel: MarketingChannel) -> _AddressRule | None:
    """What this channel needs on the user row, or None for push.

    Push is the exception: its address is a device token in another table, so
    it is counted with a join rather than a column predicate.
    """

    if channel is MarketingChannel.SMS:
        return _AddressRule(
            condition=User.phone_number.is_not(None),
            blocker="No mobile number on file",
            cost_per_message=settings.marketing_sms_cost_per_message,
        )
    if channel is MarketingChannel.WHATSAPP:
        return _AddressRule(
            # The same predicate as SMS, and deliberately not narrower. This
            # cannot know whether a number is registered on WhatsApp without
            # asking Meta per number, so the honest estimate is "everyone we
            # could try" and the send reports the ones that were not.
            condition=User.phone_number.is_not(None),
            blocker="No mobile number on file",
            cost_per_message=settings.marketing_whatsapp_cost_per_message,
        )
    if channel is MarketingChannel.EMAIL:
        return _AddressRule(
            condition=User.email.is_not(None),
            blocker="No email address on file",
        )
    return None


def _direct_reach(
    db: Session,
    *,
    channel: MarketingChannel,
    restaurant_id: uuid.UUID,
    audience_ids: list[uuid.UUID],
    now: datetime,
    message_parts: int = 1,
) -> tuple[ChannelReach, list[uuid.UUID]]:
    """Reachability on one addressed channel, itemised.

    Three losses, counted in order and never double-counted: no consent, then
    no usable address, then the weekly cap. A customer who opted out *and* has
    no device is reported once, under consent, because that is the one the
    owner can do nothing about and the one that matters legally.

    The order is the same for every direct channel, which is the point of
    generalising it — a per-channel copy of this would be four chances for the
    consent check to be dropped.
    """

    audience = set(audience_ids)
    if not audience:
        return (
            ChannelReach(
                channel=channel,
                available=True,
                reachable=0,
                blockers=[],
                estimated_cost=0.0,
            ),
            [],
        )

    consenting = set(
        db.scalars(
            select(User.id).where(User.id.in_(audience_ids), opted_in_condition())
        ).all()
    )
    opted_out = audience - consenting

    rule = _address_rule(channel)
    if rule is None:
        # Push: the address lives in `user_device_tokens`, not on the user.
        addressable = set(
            db.scalars(
                select(distinct(UserDeviceToken.user_id)).where(
                    UserDeviceToken.user_id.in_(consenting or {uuid.uuid4()}),
                    UserDeviceToken.is_active.is_(True),
                )
            ).all()
        )
        # One bucket, because the backend cannot tell the two apart: an
        # uninstalled app and notifications switched off both present as the
        # absence of an active token. Claiming otherwise would be a guess
        # printed as a number.
        address_blocker = "No app with notifications on"
        cost_per_message = 0.0
    else:
        addressable = set(
            db.scalars(
                select(User.id).where(
                    User.id.in_(consenting or {uuid.uuid4()}), rule.condition
                )
            ).all()
        )
        address_blocker = rule.blocker
        cost_per_message = rule.cost_per_message

    unaddressable = consenting - addressable

    capped = recently_messaged_user_ids(
        db,
        restaurant_id=restaurant_id,
        user_ids=list(addressable),
        now=now,
    )
    reachable_ids = sorted(addressable - capped, key=str)

    blockers = [
        {"reason": "Not opted in to marketing", "count": len(opted_out)},
        {"reason": address_blocker, "count": len(unaddressable)},
        {
            "reason": f"Already had {FREQUENCY_CAP_PER_WEEK} messages this week",
            "count": len(capped),
        },
    ]

    return (
        ChannelReach(
            channel=channel,
            available=True,
            reachable=len(reachable_ids),
            blockers=[blocker for blocker in blockers if blocker["count"] > 0],
            # Parts matter: a long SMS is billed as two, and quoting the
            # one-part price for a two-part message halves the bill the owner
            # was shown against the one they are charged.
            estimated_cost=round(
                cost_per_message * len(reachable_ids) * max(1, message_parts), 2
            ),
        ),
        reachable_ids,
    )


def _social_reach(
    channel: MarketingChannel,
    connection,
) -> ChannelReach:
    """A follower count, which is not a reach estimate and is not labelled one.

    `reachable` carries the followers the owner told us about at connect time,
    because the picker needs a number to show and this is the only one that
    exists. It is not filtered by consent, it is not filtered by the cap, and
    there are no blockers to itemise — none of those concepts apply to a
    public post. The admin renders social cards as "everyone who follows you"
    rather than as a count for exactly this reason.
    """

    followers = 0
    if connection is not None:
        try:
            followers = int(str((connection.config or {}).get("follower_count") or 0))
        except (TypeError, ValueError):
            followers = 0
    return ChannelReach(
        channel=channel,
        available=True,
        reachable=followers,
        blockers=[],
        estimated_cost=0.0,
    )


# --- spend ------------------------------------------------------------------


def _rate_for(channel: MarketingChannel) -> float:
    rule = _address_rule(channel)
    return rule.cost_per_message if rule is not None else 0.0


def campaign_spend(campaign: PushNotificationCampaign) -> float:
    """What one campaign actually cost, derived rather than stored.

    Recomputed from the channel, the people it reached and the length of the
    copy, because all three are already on the row and a stored total would
    be one more thing that can drift from what happened. `sent_count` is the
    count of customers actually reached, so a send that half failed is
    charged for half.
    """

    channels = campaign.channels or []
    if not channels:
        return 0.0
    try:
        channel = MarketingChannel(channels[0])
    except ValueError:
        return 0.0
    rate = _rate_for(channel)
    if rate <= 0:
        return 0.0
    parts = sms_parts(campaign.message or "") if channel is MarketingChannel.SMS else 1
    return round(rate * (campaign.sent_count or 0) * parts, 2)


def spend_this_month(
    db: Session, *, restaurant_id: uuid.UUID, now: datetime
) -> float:
    """What this restaurant has already spent on messages this calendar month.

    Calendar month rather than a rolling 30 days, because that is how an
    owner thinks about a budget and how the invoice they are checking it
    against is cut.
    """

    start = now.astimezone(UTC).replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    )
    campaigns = db.scalars(
        select(PushNotificationCampaign).where(
            PushNotificationCampaign.restaurant_id == restaurant_id,
            PushNotificationCampaign.kind == PushNotificationCampaignKind.MARKETING,
            PushNotificationCampaign.dispatched_at.is_not(None),
            PushNotificationCampaign.dispatched_at >= start,
        )
    ).all()
    return round(sum(campaign_spend(campaign) for campaign in campaigns), 2)


def _spend_notices(
    db: Session,
    *,
    restaurant_id: uuid.UUID,
    projected: float,
    now: datetime,
) -> list[Notice]:
    """Block a send that would cost more than the owner has agreed to.

    Both caps are checked here rather than in the UI, so the same rule
    decides what the builder shows and what the dispatcher allows — the
    dispatcher re-runs this estimate at send time and refuses on any blocking
    notice, which is what catches a draft that was under the cap when it was
    written and over it by the time it fires.
    """

    notices: list[Notice] = []
    if projected <= 0:
        return notices

    per_campaign = settings.marketing_campaign_spend_cap
    if per_campaign > 0 and projected > per_campaign:
        notices.append(
            Notice(
                id="over-campaign-spend-cap",
                tone=MarketingNoticeTone.BLOCK,
                title="This campaign costs more than one campaign is allowed to",
                description=(
                    f"Sending it would cost about {projected:,.0f}, and the limit for a "
                    f"single campaign is {per_campaign:,.0f}. Narrow the audience, "
                    "shorten the message, or raise the limit."
                ),
            )
        )

    monthly = settings.marketing_monthly_spend_cap
    if monthly > 0:
        already = spend_this_month(db, restaurant_id=restaurant_id, now=now)
        if already + projected > monthly:
            notices.append(
                Notice(
                    id="over-monthly-spend-cap",
                    tone=MarketingNoticeTone.BLOCK,
                    title="This would take you over your budget for the month",
                    description=(
                        f"You have spent about {already:,.0f} on messages this month and "
                        f"this campaign would add {projected:,.0f}, against a limit of "
                        f"{monthly:,.0f}."
                    ),
                )
            )
        elif already + projected > monthly * 0.8:
            notices.append(
                Notice(
                    id="near-monthly-spend-cap",
                    tone=MarketingNoticeTone.WARN,
                    title="This uses most of your budget for the month",
                    description=(
                        f"{already + projected:,.0f} of {monthly:,.0f} once this goes out."
                    ),
                )
            )
    return notices


# --- timing ----------------------------------------------------------------


def _timing_notices(
    db: Session,
    *,
    send_at: datetime | None,
    branch_ids: list[uuid.UUID],
    timezone_name: str,
    now: datetime,
) -> list[Notice]:
    if send_at is None:
        return []

    tzinfo = ZoneInfo(timezone_name)
    local = send_at.astimezone(tzinfo)

    if send_at <= now:
        return [
            Notice(
                id="schedule-past",
                tone=MarketingNoticeTone.BLOCK,
                title="That time has already passed",
                description="Choose a future time, or send now instead.",
            )
        ]

    notices: list[Notice] = []

    if local.hour < QUIET_HOURS_START or local.hour >= QUIET_HOURS_END:
        notices.append(
            Notice(
                id="quiet-hours",
                tone=MarketingNoticeTone.BLOCK,
                title="That lands inside quiet hours",
                description=(
                    f"Marketing messages can only go out between "
                    f"{QUIET_HOURS_START:02d}:00 and {QUIET_HOURS_END:02d}:00. "
                    "A notification at that hour loses customers for good."
                ),
            )
        )

    if branch_ids:
        branches = {
            branch.id: branch
            for branch in db.scalars(
                select(RestaurantLocation).where(RestaurantLocation.id.in_(branch_ids))
            ).all()
        }
        hours = branch_hours(db, list(branches))
        closed = [
            branches[branch_id].branch_name
            for branch_id in branch_ids
            if branch_id in branches
            and not _within(local, hours.get(branch_id))
        ]
        if closed:
            notices.append(
                Notice(
                    id="branch-closed",
                    tone=MarketingNoticeTone.WARN,
                    title=f"{', '.join(closed)} will be closed",
                    description=(
                        "Customers who tap through will not be able to order. "
                        "Consider a time inside opening hours."
                    ),
                )
            )

    return notices


def _within(local: datetime, hours) -> bool:
    if hours is None:
        return True
    open_hour = int(hours.opens_at.split(":")[0])
    close_hour = int(hours.closes_at.split(":")[0])
    return open_hour <= local.hour < close_hour


# --- the estimate ----------------------------------------------------------


def estimate_reach(
    db: Session,
    *,
    restaurant_id: uuid.UUID,
    app_client_id: uuid.UUID,
    segment_key: MarketingSegmentKey,
    branch_ids: list[uuid.UUID],
    channels: list[MarketingChannel],
    send_at: datetime | None = None,
    timezone_name: str | None = None,
    now: datetime | None = None,
    #: How many billable parts the copy is, for the channels charged by
    #: length. One for everything else, so callers that do not care ignore it.
    message_parts: int = 1,
) -> ReachResult:
    """Everything the reach step shows, and everything dispatch re-checks."""

    now = now or datetime.now(UTC)
    timezone_name = timezone_name or settings.business_timezone

    # Segment members ignore branch filtering; audience applies it. Two
    # queries rather than one because the UI shows both numbers and the
    # difference is what tells the owner their branch choice did something.
    segment_members = (
        db.scalar(
            select(func.count()).select_from(
                segment_member_query(
                    db,
                    key=segment_key,
                    restaurant_id=restaurant_id,
                    app_client_id=app_client_id,
                    branch_ids=None,
                    now=now,
                ).subquery()
            )
        )
        or 0
    )

    audience_ids = list_segment_member_ids(
        db,
        key=segment_key,
        restaurant_id=restaurant_id,
        app_client_id=app_client_id,
        branch_ids=branch_ids or None,
        now=now,
    )

    notices: list[Notice] = []
    channel_results: list[ChannelReach] = []
    reachable_ids: list[uuid.UUID] = []

    # Which channels this restaurant has actually switched on. One query for
    # all of them, and the single source of truth for availability — the old
    # hardcoded `PHASE_TWO_CHANNELS` map could only ever say "no", so a
    # channel that had been connected still rendered as unavailable.
    connections = list_connections(db, restaurant_id=restaurant_id)
    live = live_channels(db, restaurant_id=restaurant_id)

    for channel in channels:
        if channel not in live:
            channel_results.append(
                ChannelReach(
                    channel=channel,
                    available=False,
                    reachable=0,
                    blockers=[],
                    estimated_cost=0.0,
                    unavailable_reason=(
                        f"{channel.value.title()} is not connected yet"
                    ),
                )
            )
            continue

        if channel_family(channel) is MarketingChannelFamily.SOCIAL:
            channel_results.append(_social_reach(channel, connections.get(channel)))
            continue

        result, ids = _direct_reach(
            db,
            channel=channel,
            restaurant_id=restaurant_id,
            audience_ids=audience_ids,
            now=now,
            message_parts=message_parts,
        )
        channel_results.append(result)
        # The ids a send would go to. With one channel per campaign there is
        # exactly one direct channel in this list; if a caller ever passes
        # several, the last one wins and dispatch would send to the wrong
        # list — which is why `dispatch` passes exactly the campaign's own
        # channel and nothing else.
        reachable_ids = ids

    # Money, before anything else: a campaign that cannot be afforded should
    # say so whatever else is also wrong with it.
    notices.extend(
        _spend_notices(
            db,
            restaurant_id=restaurant_id,
            projected=round(
                sum(
                    channel.estimated_cost
                    for channel in channel_results
                    if channel.available
                ),
                2,
            ),
            now=now,
        )
    )

    if not branch_ids:
        notices.append(
            Notice(
                id="no-branch",
                tone=MarketingNoticeTone.BLOCK,
                title="Pick at least one branch",
                description="A campaign always goes to the customers of specific branches.",
            )
        )

    if not any(channel.available for channel in channel_results):
        notices.append(
            Notice(
                id="no-channel",
                tone=MarketingNoticeTone.BLOCK,
                title="This channel is not connected yet",
                description=(
                    "Connect it from Marketing → Channels, or switch this campaign to "
                    "push notifications, which are always on."
                ),
            )
        )

    audience_size = len(audience_ids)
    if 0 < audience_size < MINIMUM_SEGMENT_SIZE:
        notices.append(
            Notice(
                id="segment-too-small",
                tone=MarketingNoticeTone.BLOCK,
                title="This audience is too small to send to",
                description=(
                    f"Campaigns need at least {MINIMUM_SEGMENT_SIZE} people. "
                    "Widen the branches or choose another audience."
                ),
            )
        )

    if audience_size == 0:
        notices.append(
            Notice(
                id="segment-empty",
                tone=MarketingNoticeTone.BLOCK,
                title="Nobody matches this audience yet",
                description="Try another audience, or widen the branches you selected.",
            )
        )

    reachable_total = sum(
        channel.reachable for channel in channel_results if channel.available
    )
    if branch_ids and audience_size >= MINIMUM_SEGMENT_SIZE and reachable_total == 0:
        notices.append(
            Notice(
                id="nobody-reachable",
                tone=MarketingNoticeTone.BLOCK,
                title="Nobody in this audience can be reached",
                description=(
                    "None of these customers have the app installed with "
                    "notifications on. Try a wider audience."
                ),
            )
        )

    inactive = db.scalars(
        select(RestaurantLocation.branch_name).where(
            RestaurantLocation.id.in_(branch_ids or []),
            RestaurantLocation.is_active.is_(False),
        )
    ).all()
    if inactive:
        notices.append(
            Notice(
                id="branch-inactive",
                tone=MarketingNoticeTone.WARN,
                title=f"{', '.join(inactive)} is not currently active",
                description="Customers of an inactive branch cannot place an order right now.",
            )
        )

    unavailable = [channel for channel in channel_results if not channel.available]
    if unavailable:
        names = ", ".join(channel.channel.value.title() for channel in unavailable)
        notices.append(
            Notice(
                id="channels-unavailable",
                tone=MarketingNoticeTone.INFO,
                title="Some channels are not connected yet",
                description=f"{names} will be available once set up. Push works today.",
            )
        )

    notices.extend(
        _timing_notices(
            db,
            send_at=send_at,
            branch_ids=branch_ids or [],
            timezone_name=timezone_name,
            now=now,
        )
    )

    return ReachResult(
        segment_members=segment_members,
        audience_size=audience_size,
        channels=channel_results,
        notices=notices,
        reachable_user_ids=reachable_ids,
    )


def unavailable_result(reason: str) -> ReachResult:
    """The estimate for a restaurant that cannot run campaigns at all.

    Used when `SegmentUnavailable` is raised — most often a restaurant with no
    app of its own. Returned as a normal blocked estimate rather than an error
    response so the wizard renders the reason in place instead of showing a
    failure screen with nothing actionable on it.
    """

    return ReachResult(
        segment_members=0,
        audience_size=0,
        channels=[],
        notices=[
            Notice(
                id="no-app-client",
                tone=MarketingNoticeTone.BLOCK,
                title="This restaurant has no app yet",
                description=reason,
            )
        ],
    )


__all__ = [
    "ChannelReach",
    "Notice",
    "ReachResult",
    "SegmentUnavailable",
    "estimate_reach",
    "recently_messaged_user_ids",
    "unavailable_result",
]
