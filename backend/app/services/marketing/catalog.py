"""The fixed reference data a campaign is assembled from.

Goals and message templates are constants rather than rows. They are product
copy — the wording an owner reads when choosing what a campaign is for — and
putting them in a table would mean a migration to fix a typo and a seed script
that every environment has to have run. Nothing in the send path branches on a
goal, so they can move at the speed of a deploy.

Branches and offers are real data, read from the tables that already own them.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import time

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.enums import (
    MarketingCampaignGoal,
    MarketingChannel,
    MarketingSegmentKey,
    OrderFulfillmentType,
    PersonalizedOfferDiscountType,
    PersonalizedOfferState,
)
from app.models.location_fulfillment_slot import LocationFulfillmentSlot
from app.models.personalized_offer import GeneratedOffer
from app.models.restaurant_location import RestaurantLocation

logger = logging.getLogger(__name__)
settings = get_settings()


#: Below this an audience is too small to send to. A campaign to nine people is
#: not a campaign, and the per-person variance makes its report meaningless.
MINIMUM_SEGMENT_SIZE = 10

#: Marketing messages one customer may receive in a rolling week, across all
#: campaigns from one restaurant. Enforced server-side at dispatch, and
#: counted from recipient rows — see `reach.recently_messaged_user_ids`.
#:
#: Read from settings rather than fixed here so a deployment can tune it
#: without a release. Re-exported under the old name because `reach.py`, the
#: reference endpoint and the admin all import this symbol.
FREQUENCY_CAP_PER_WEEK = get_settings().marketing_frequency_cap_per_week

#: Marketing sends are confined to these hours, in the business timezone.
QUIET_HOURS_START = 8
QUIET_HOURS_END = 22

# Channel availability used to be a constant here — a map from channel to the
# sentence explaining that it was not connected yet. It could only ever say
# "no", so a channel that HAD been connected still rendered as unavailable.
# It now comes from `services/marketing/connections.py`, per restaurant,
# because availability is a fact about a restaurant and not about the build.

@dataclass(frozen=True, slots=True)
class GoalDefinition:
    key: MarketingCampaignGoal
    label: str
    description: str
    default_segment: MarketingSegmentKey
    default_channels: tuple[MarketingChannel, ...]
    success_metric: str
    suggests_offer: bool


GOALS: tuple[GoalDefinition, ...] = (
    GoalDefinition(
        key=MarketingCampaignGoal.WINBACK,
        label="Bring back customers who stopped ordering",
        description="People who used to order regularly and have gone quiet.",
        default_segment=MarketingSegmentKey.LAPSED_REGULARS,
        default_channels=(MarketingChannel.PUSH,),
        success_metric="Orders from people who had gone quiet",
        suggests_offer=True,
    ),
    GoalDefinition(
        key=MarketingCampaignGoal.PROMOTE_DISH,
        label="Push one dish",
        description="Put a single dish in front of the people most likely to want it.",
        default_segment=MarketingSegmentKey.DISH_FANS,
        default_channels=(MarketingChannel.PUSH,),
        success_metric="Orders containing that dish",
        suggests_offer=True,
    ),
    GoalDefinition(
        key=MarketingCampaignGoal.NEW_ITEM,
        label="Announce something new on the menu",
        description="Tell your regulars about a dish they have never seen.",
        default_segment=MarketingSegmentKey.BRANCH_CUSTOMERS,
        default_channels=(MarketingChannel.PUSH,),
        success_metric="Orders containing the new dish",
        # News, not a discount. A new dish that launches at a discount is hard
        # to ever sell at full price.
        suggests_offer=False,
    ),
    GoalDefinition(
        key=MarketingCampaignGoal.QUIET_DAY,
        label="Fill a quiet day",
        description="Move demand into a session that is running below its usual trade.",
        default_segment=MarketingSegmentKey.BRANCH_CUSTOMERS,
        default_channels=(MarketingChannel.PUSH,),
        success_metric="Orders on the day you were trying to fill",
        suggests_offer=True,
    ),
    GoalDefinition(
        key=MarketingCampaignGoal.REWARD_VIPS,
        label="Reward your best customers",
        description="The people who spend the most, thanked before they are asked for anything.",
        default_segment=MarketingSegmentKey.VIPS,
        default_channels=(MarketingChannel.PUSH,),
        success_metric="Repeat orders from your top customers",
        suggests_offer=True,
    ),
    GoalDefinition(
        key=MarketingCampaignGoal.FIRST_TO_REGULAR,
        label="Turn a first order into a second",
        description="People who ordered once. The second order is what makes a customer.",
        default_segment=MarketingSegmentKey.FIRST_TIME_BUYERS,
        default_channels=(MarketingChannel.PUSH,),
        success_metric="Second orders from first-time buyers",
        suggests_offer=True,
    ),
    GoalDefinition(
        key=MarketingCampaignGoal.ANNOUNCEMENT,
        label="Tell customers something",
        description="New hours, a new branch, a holiday closure. No discount attached.",
        default_segment=MarketingSegmentKey.BRANCH_CUSTOMERS,
        default_channels=(MarketingChannel.PUSH,),
        success_metric="How many people read it",
        suggests_offer=False,
    ),
    GoalDefinition(
        key=MarketingCampaignGoal.CUSTOM,
        label="Something else",
        description="Choose the audience and write the message yourself.",
        default_segment=MarketingSegmentKey.BRANCH_CUSTOMERS,
        default_channels=(MarketingChannel.PUSH,),
        success_metric="Orders attributed to this campaign",
        suggests_offer=False,
    ),
)

GOALS_BY_KEY = {goal.key: goal for goal in GOALS}


@dataclass(frozen=True, slots=True)
class TemplateDefinition:
    id: str
    name: str
    goal: MarketingCampaignGoal
    channel: MarketingChannel
    title: str
    body: str


#: Starting copy, not finished copy. `{first_name}` is the only merge field the
#: P1 UI knows how to preview and fall back on, so it is the only one used here
#: — a template offering a field the preview cannot render is a template that
#: ships "Hi null" to somebody.
TEMPLATES: tuple[TemplateDefinition, ...] = (
    TemplateDefinition(
        id="winback-we-miss-you",
        name="We miss you",
        goal=MarketingCampaignGoal.WINBACK,
        channel=MarketingChannel.PUSH,
        title="We miss you, {first_name}",
        body="It has been a while. Here is something to bring you back.",
    ),
    TemplateDefinition(
        id="promote-dish-favourite",
        name="Your favourite, today",
        goal=MarketingCampaignGoal.PROMOTE_DISH,
        channel=MarketingChannel.PUSH,
        title="Craving your usual?",
        body="Your favourite is ready when you are.",
    ),
    TemplateDefinition(
        id="new-item-just-landed",
        name="Just landed",
        goal=MarketingCampaignGoal.NEW_ITEM,
        channel=MarketingChannel.PUSH,
        title="Something new on the menu",
        body="We have added something we think you will like. Take a look.",
    ),
    TemplateDefinition(
        id="quiet-day-tonight",
        name="Tonight only",
        goal=MarketingCampaignGoal.QUIET_DAY,
        channel=MarketingChannel.PUSH,
        title="Dinner sorted, {first_name}?",
        body="Order in the next few hours and we will take care of the rest.",
    ),
    TemplateDefinition(
        id="reward-vips-thank-you",
        name="Thank you",
        goal=MarketingCampaignGoal.REWARD_VIPS,
        channel=MarketingChannel.PUSH,
        title="Thank you, {first_name}",
        body="You are one of our best customers. This one is on us.",
    ),
    TemplateDefinition(
        id="first-to-regular-second-order",
        name="Come back for a second",
        goal=MarketingCampaignGoal.FIRST_TO_REGULAR,
        channel=MarketingChannel.PUSH,
        title="How was your first order?",
        body="Here is a reason to make it a habit.",
    ),
    TemplateDefinition(
        id="announcement-plain",
        name="Plain announcement",
        goal=MarketingCampaignGoal.ANNOUNCEMENT,
        channel=MarketingChannel.PUSH,
        title="A quick update",
        body="We have some news to share with you.",
    ),
)


# --- branches --------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BranchHours:
    """One branch's opening window on an ordinary week, as "HH:MM" strings.

    A projection, and lossy by design. The real schedule is
    `location_fulfillment_slot` — per weekday, per fulfillment type, and able
    to hold split shifts. Flattening it to one open and one close is what the
    frontend contract asks for, and it is adequate for the `warn`-tone "this
    branch will be closed then" notice it feeds.

    Where it is wrong, it is wrong in a knowable direction: a branch serving
    lunch 11-15 and dinner 19-23 reports 11:00-23:00, so the 16:00 gap looks
    open. That is why nothing that *blocks* a send reads these values.
    """

    opens_at: str
    closes_at: str


DEFAULT_HOURS = BranchHours(opens_at="09:00", closes_at="22:00")


def _format(value: time) -> str:
    return f"{value.hour:02d}:{value.minute:02d}"


def branch_hours(db: Session, location_ids: list[uuid.UUID]) -> dict[uuid.UUID, BranchHours]:
    """Earliest opening and latest closing across each branch's active slots."""

    if not location_ids:
        return {}

    rows = db.execute(
        select(
            LocationFulfillmentSlot.location_id,
            LocationFulfillmentSlot.start_time,
            LocationFulfillmentSlot.end_time,
        ).where(
            LocationFulfillmentSlot.location_id.in_(location_ids),
            LocationFulfillmentSlot.is_active.is_(True),
            # Delivery windows, not pickup: a customer tapping a push lands in
            # the ordering flow, and delivery is the wider of the two for
            # nearly every branch.
            LocationFulfillmentSlot.fulfillment_type == OrderFulfillmentType.DELIVERY,
        )
    ).all()

    spans: dict[uuid.UUID, tuple[time, time]] = {}
    for location_id, start_time, end_time in rows:
        current = spans.get(location_id)
        if current is None:
            spans[location_id] = (start_time, end_time)
            continue
        spans[location_id] = (min(current[0], start_time), max(current[1], end_time))

    # A branch with no active delivery slots falls back to a plain default
    # rather than being reported as closed all day, which would fire the
    # "will be closed" warning on every campaign a young restaurant sends.
    return {
        location_id: (
            BranchHours(opens_at=_format(span[0]), closes_at=_format(span[1]))
            if (span := spans.get(location_id)) is not None
            else DEFAULT_HOURS
        )
        for location_id in location_ids
    }


def list_branches(db: Session, restaurant_id: uuid.UUID) -> list[RestaurantLocation]:
    return list(
        db.scalars(
            select(RestaurantLocation)
            .where(RestaurantLocation.restaurant_id == restaurant_id)
            .order_by(RestaurantLocation.branch_name)
        ).all()
    )


# --- offers ----------------------------------------------------------------


def _discount_label(offer: GeneratedOffer) -> str:
    if offer.discount_type == PersonalizedOfferDiscountType.PERCENTAGE:
        return f"{offer.discount_value:g}% off"
    if offer.discount_type == PersonalizedOfferDiscountType.FLAT:
        return f"{offer.discount_value:g} off"
    if offer.discount_type == PersonalizedOfferDiscountType.FREE_DELIVERY:
        return "Free delivery"
    return "No discount"


def _applies_to(offer: GeneratedOffer) -> str:
    if offer.applicable_item_id is not None:
        return "One dish"
    if offer.applicable_category:
        return offer.applicable_category
    if offer.applicable_cuisine:
        return offer.applicable_cuisine
    return "Whole menu"


def list_attachable_offers(db: Session, restaurant_id: uuid.UUID) -> list[GeneratedOffer]:
    """Offers a campaign may attach.

    Shared offers only — `generated_for_user_id IS NULL`. A per-customer offer
    belongs to one person by construction and attaching it to a campaign sent to
    four hundred would either break its eligibility or leak someone else's
    discount.
    """

    return list(
        db.scalars(
            select(GeneratedOffer)
            .where(
                GeneratedOffer.restaurant_id == restaurant_id,
                GeneratedOffer.state == PersonalizedOfferState.ACTIVE,
                GeneratedOffer.generated_for_user_id.is_(None),
                GeneratedOffer.discount_type != PersonalizedOfferDiscountType.NONE,
            )
            .order_by(GeneratedOffer.created_at.desc())
        ).all()
    )


def offer_view(offer: GeneratedOffer) -> dict:
    """A `GeneratedOffer` in the shape the Hub's offer picker expects."""

    return {
        "id": offer.id,
        "name": offer.generated_title,
        "discount_label": _discount_label(offer),
        # The contract knows only PERCENTAGE and FLAT. FREE_DELIVERY is
        # reported as a flat discount of zero rather than being hidden: the
        # owner can still attach it, and the exposure maths correctly says it
        # gives away no order value. The delivery fee is not order revenue.
        "discount_type": (
            "PERCENTAGE"
            if offer.discount_type == PersonalizedOfferDiscountType.PERCENTAGE
            else "FLAT"
        ),
        "discount_value": float(offer.discount_value),
        "minimum_order_amount": float(offer.minimum_order_amount),
        "max_discount_amount": float(offer.max_discount_amount or 0),
        "valid_for_days": offer.valid_for_days,
        "applies_to": _applies_to(offer),
    }
