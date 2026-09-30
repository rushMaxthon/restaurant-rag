"""Request and response shapes for the Marketing Hub.

These mirror `frontend-admin/src/services/marketing/types.ts` field for field,
because that file is the contract: the whole P1 UI was built against it while
the backend was a mock, and every component already speaks it. Where a name
here looks redundant (`segment_members` beside `audience_size`) it is because
the UI renders both and the difference is the point — one is the segment, the
other is what is left after branch filtering.

Money is a plain number and carries no currency code, matching the contract.
Push is the only channel with a cost in P1 and its cost is always zero, so
there is nothing yet for a currency to qualify.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import (
    ChannelConnectionStatus,
    MarketingCampaignGoal,
    MarketingChannel,
    MarketingChannelFamily,
    MarketingDeepLink,
    MarketingSegmentKey,
    PushNotificationCampaignStatus,
)

# --- consent ---------------------------------------------------------------


class MarketingConsentResponse(BaseModel):
    """A customer's own marketing preference."""

    marketing_opt_in: bool
    # Null means the customer has never expressed a preference, which the UI
    # should present differently from a deliberate opt-in.
    marketing_opt_in_changed_at: datetime | None


class MarketingConsentUpdateRequest(BaseModel):
    marketing_opt_in: bool


# --- reference data --------------------------------------------------------


class CampaignGoalResponse(BaseModel):
    key: MarketingCampaignGoal
    label: str
    description: str
    default_segment: MarketingSegmentKey
    default_channels: list[MarketingChannel]
    success_metric: str
    suggests_offer: bool


class MarketingSegmentResponse(BaseModel):
    key: MarketingSegmentKey
    name: str
    definition: str
    total_members: int
    # Keyed by branch id as a string, because JSON object keys are strings and
    # the UI indexes this map directly with the branch ids it already holds.
    members_by_branch: dict[str, int]
    computed_at: datetime


class MarketingBranchResponse(BaseModel):
    id: uuid.UUID
    branch_name: str
    city: str
    state: str
    is_active: bool
    # "HH:MM" in the restaurant's business timezone, projected from the
    # branch's weekly fulfillment slots. See `catalog.branch_hours`.
    opens_at: str
    closes_at: str


class MarketingOfferResponse(BaseModel):
    id: uuid.UUID
    name: str
    discount_label: str
    discount_type: Literal["PERCENTAGE", "FLAT"]
    discount_value: float
    minimum_order_amount: float
    max_discount_amount: float
    valid_for_days: int
    applies_to: str


class MessageTemplateResponse(BaseModel):
    id: str
    name: str
    goal: MarketingCampaignGoal
    channel: MarketingChannel
    title: str
    body: str


class MarketingReferenceResponse(BaseModel):
    """Everything the wizard needs to render before a draft exists."""

    goals: list[CampaignGoalResponse]
    segments: list[MarketingSegmentResponse]
    branches: list[MarketingBranchResponse]
    offers: list[MarketingOfferResponse]
    templates: list[MessageTemplateResponse]
    minimum_segment_size: int
    frequency_cap_per_week: int
    timezone: str


# --- reach estimation ------------------------------------------------------


class ReachBlocker(BaseModel):
    reason: str
    count: int


class ChannelReachResponse(BaseModel):
    channel: MarketingChannel
    available: bool
    unavailable_reason: str | None = None
    reachable: int
    blockers: list[ReachBlocker]
    estimated_cost: float


class CampaignNoticeResponse(BaseModel):
    id: str
    tone: Literal["block", "warn", "info"]
    title: str
    description: str


class ReachEstimateResponse(BaseModel):
    segment_members: int
    audience_size: int
    channels: list[ChannelReachResponse]
    notices: list[CampaignNoticeResponse]
    minimum_segment_size: int


class ReachEstimateRequest(BaseModel):
    goal: MarketingCampaignGoal
    segment_key: MarketingSegmentKey
    branch_ids: list[uuid.UUID] = Field(default_factory=list)
    channels: list[MarketingChannel] = Field(default_factory=list)
    offer_id: uuid.UUID | None = None
    send_at: datetime | None = None


# --- channel connections ---------------------------------------------------


class ConnectionFieldResponse(BaseModel):
    """One thing the owner has to supply before a channel can send.

    `secret` is here so the form can render a password input and, more
    importantly, so it can show an existing connection's non-secret values
    while leaving the secret blank — a stored token cannot be displayed, and
    re-saving without retyping it must not blank it.
    """

    key: str
    label: str
    example: str
    secret: bool
    required: bool
    help: str


class ChannelConnectionResponse(BaseModel):
    """One channel's state for one restaurant.

    Carries `config` and never `credentials`. That split is the whole reason
    the model has two JSONB columns: an owner needs to see which number they
    are sending from, and nobody needs the token that sends from it.
    """

    channel: MarketingChannel
    family: MarketingChannelFamily
    #: Whether a campaign on this channel can actually leave the building.
    connected: bool
    status: ChannelConnectionStatus | None
    config: dict[str, Any] = Field(default_factory=dict)
    #: "@spiceroute", "+91 80 4718 2203" — who the customer sees it from.
    identity: str | None = None
    connected_at: datetime | None = None
    verified_at: datetime | None = None
    last_error: str | None = None
    requirements: list[ConnectionFieldResponse] = Field(default_factory=list)


class ChannelConnectRequest(BaseModel):
    """What the owner typed into the connect form.

    An open map rather than a field per channel: the fields differ per
    channel and are declared in `connections.REQUIREMENTS`, which is also
    what validates this. A schema per channel would be five schemas that have
    to be kept in step with that map.
    """

    values: dict[str, str] = Field(default_factory=dict)

    @field_validator("values")
    @classmethod
    def _bounded(cls, value: dict[str, str]) -> dict[str, str]:
        if len(value) > 20:
            raise ValueError("Too many fields for one connection")
        for key, entry in value.items():
            if len(key) > 64 or len(entry) > 2000:
                raise ValueError("That value is too long")
        return value


class ChannelEnableRequest(BaseModel):
    enabled: bool


# --- campaigns -------------------------------------------------------------


class CampaignContentSchema(BaseModel):
    """What the customer sees, in the shape the chosen channel needs.

    `title` and `body` are the two fields every channel has some version of -
    a push title and body, an email subject and message, a WhatsApp header and
    text - so they stay columns. `extra` is everything that belongs to one or
    two channels only: the photo a post cannot exist without, a hashtag block,
    a boost budget, the promo code a public post is attributed by.

    It is carried, not interpreted. The backend stores it and hands it back
    unchanged, which is what lets a new channel ship as a frontend change plus
    a dispatcher, with no migration and no schema edit here. Push - the only
    channel that sends today - reads nothing from it.

    Size-capped rather than typed per key, because the alternative is this
    schema growing a branch per channel and every addition becoming a backend
    release. The cap is what stops it being used as a document store.
    """

    title: str = Field(min_length=1, max_length=120)
    body: str = Field(min_length=1, max_length=1000)
    deep_link: MarketingDeepLink
    template_id: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)

    @field_validator("extra")
    @classmethod
    def _bounded(cls, value: dict[str, Any]) -> dict[str, Any]:
        if len(value) > 32:
            raise ValueError("Too many channel fields on one campaign")
        return value


class CampaignScheduleSchema(BaseModel):
    mode: Literal["NOW", "SCHEDULED"]
    send_at: datetime | None = None
    timezone: str


class CampaignDraftRequest(BaseModel):
    """A save from any step of the wizard.

    Deliberately permissive: a draft is saved continuously as the owner moves
    through six steps, and refusing to persist a half-finished one would mean
    losing their work every time they stepped away. Everything that makes a
    campaign *sendable* is validated at send time instead, where it can be
    re-checked against data that may have moved since the draft was written.
    """

    # Absent on the first save, present on every later one.
    id: uuid.UUID | None = None
    name: str = Field(min_length=1, max_length=255)
    goal: MarketingCampaignGoal
    segment_key: MarketingSegmentKey
    branch_ids: list[uuid.UUID] = Field(default_factory=list)
    offer_id: uuid.UUID | None = None
    channels: list[MarketingChannel] = Field(default_factory=list)
    content: CampaignContentSchema
    schedule: CampaignScheduleSchema
    # Six screens now: where, why, who, words, when, ready. The channel screen
    # is step 1, which is why the ceiling moved - a draft saved from the review
    # screen of the redesigned wizard reports 6.
    last_step: int = Field(default=1, ge=1, le=6)


class DeliveryBreakdownResponse(BaseModel):
    sent: int
    delivered: int
    opened: int
    clicked: int
    failed: int
    unsubscribed: int


class FailureReasonResponse(BaseModel):
    reason: str
    count: int


class AttributionDailyPoint(BaseModel):
    label: str
    revenue: float
    orders: int


class AttributionReportResponse(BaseModel):
    window_days: int
    window_open: bool
    orders: int
    revenue: float
    discount_given: float
    net_revenue: float
    average_order_value: float
    baseline_orders: int
    returning_customers: int
    new_customers: int
    daily: list[AttributionDailyPoint]


class SocialPostResponse(BaseModel):
    """The public post a social campaign produced.

    Null for every direct campaign, and the two are never both populated: a
    campaign is a message to people or a post to nobody.
    """

    state: str | None = None
    post_id: str | None = None
    permalink: str | None = None
    published_at: datetime | None = None
    #: True when `enable_marketing_dispatch` was off, so nothing was posted.
    #: Reported rather than inferred from a null post id, which would look
    #: the same as a post whose id we failed to read back.
    dry_run: bool = False
    reason: str | None = None
    promo_code: str | None = None
    #: Whatever the platform served, unchanged. A metric it stopped serving
    #: disappears rather than reading as zero.
    insights: dict[str, int] = Field(default_factory=dict)
    insights_updated_at: datetime | None = None


class CampaignResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    goal: MarketingCampaignGoal
    segment_key: MarketingSegmentKey
    branch_ids: list[uuid.UUID]
    offer_id: uuid.UUID | None
    channels: list[MarketingChannel]
    content: CampaignContentSchema
    schedule: CampaignScheduleSchema
    status: PushNotificationCampaignStatus
    created_at: datetime
    updated_at: datetime
    sent_at: datetime | None
    created_by: str
    audience_size: int
    delivery: DeliveryBreakdownResponse | None
    failure_reasons: list[FailureReasonResponse]
    attribution: AttributionReportResponse | None
    last_error: str | None
    sending_progress: float | None
    social: SocialPostResponse | None = None


class CampaignScheduleRequest(BaseModel):
    send_at: datetime


class TestSendRequest(BaseModel):
    """Campaign copy, sent to the staff member asking for it and nobody else.

    Carries the text rather than a campaign id so the wizard can test a draft
    that has not been saved — which is the moment an owner actually wants to
    see it on a phone.

    `channel` defaults to push so a client written before the other channels
    existed keeps working. A social channel is refused rather than defaulted:
    there is no private way to test a public post, and quietly sending a push
    instead would let an owner conclude Instagram works.
    """

    title: str = Field(min_length=1, max_length=120)
    body: str = Field(min_length=1, max_length=1000)
    channel: MarketingChannel = MarketingChannel.PUSH


class TestSendResponse(BaseModel):
    delivered: bool
    device_count: int
    #: Written for the owner: says what happened, including the case where
    #: sending is switched off in this environment and nothing was delivered.
    detail: str


class MarketingDashboardResponse(BaseModel):
    """The Hub home's figures, all of them attributed rather than estimated."""

    attributed_revenue_30d: Decimal
    attributed_revenue_previous_30d: Decimal
    campaigns_sent_30d: int
    attributed_orders_30d: int
    best_campaign: BestCampaignResponse | None
    attention: list[AttentionFlagResponse]
    revenue_trend: list[RevenueTrendPoint]


class BestCampaignResponse(BaseModel):
    id: uuid.UUID
    name: str
    net_revenue: Decimal
    orders: int
    sent_at: datetime | None


class AttentionFlagResponse(BaseModel):
    """Something the owner should look at, phrased as the thing to do.

    `id` is stable per kind so the Hub can key its carousel without the flags
    reordering underneath it between refreshes.
    """

    id: str
    tone: str
    title: str
    detail: str
    campaign_id: uuid.UUID | None = None


class RevenueTrendPoint(BaseModel):
    date: date
    revenue: Decimal

# --- engagement -------------------------------------------------------------


class CampaignEngagementRequest(BaseModel):
    """What a device reports a customer did with a campaign it received."""

    campaign_id: uuid.UUID
    # Only what a device can legitimately observe. SENT, DELIVERED and FAILED
    # are the server's own record and are refused here.
    event: Literal["OPENED", "CLICKED", "UNSUBSCRIBED"]


class CampaignEngagementResponse(BaseModel):
    #: False when this person had already reported that event. Not an error —
    #: the counters summarise distinct people, so a repeat is simply not new.
    recorded: bool
    #: Echoed so a client that opted out can update its own switch without a
    #: second round trip.
    marketing_opt_in: bool
