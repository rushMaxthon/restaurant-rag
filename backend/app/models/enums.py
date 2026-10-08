from __future__ import annotations

from enum import StrEnum


class UserRole(StrEnum):
    ADMIN = "ADMIN"
    OWNER = "OWNER"
    CUSTOMER = "CUSTOMER"
    # Someone who works in one kitchen, and whose whole job is the order board.
    #
    # Platform staff like ADMIN and OWNER, so `app_client_id` is NULL and the
    # CHECK constraint needs no change. What is different is that a KITCHEN
    # account carries no implicit restaurant the way an OWNER does (via
    # `Restaurant.owner_id`) and cannot name one the way an ADMIN does: it is
    # pinned to a restaurant, and optionally to a single branch, by
    # `users.staff_restaurant_id` / `users.staff_restaurant_location_id`.
    #
    # The role exists because the alternative was handing a kitchen tablet the
    # owner's own credentials — the same token that edits the menu, spends
    # money on marketing campaigns and reads revenue.
    KITCHEN = "KITCHEN"
    # A delivery rider in the platform's own fleet (2026-10-08). Platform staff
    # like KITCHEN: `app_client_id` NULL and NOT pinned to a restaurant - one
    # fleet serves every restaurant in a city, and only an ADMIN creates or
    # manages riders. Their only surface is the rider app.
    RIDER = "RIDER"


class RiderStatus(StrEnum):
    OFFLINE = "OFFLINE"
    ONLINE = "ONLINE"
    ON_TRIP = "ON_TRIP"


class VehicleType(StrEnum):
    BIKE = "BIKE"
    SCOOTER = "SCOOTER"
    CYCLE = "CYCLE"


class OfferOutcome(StrEnum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"
    #: Taken back by the system: the order was cancelled, reassigned, sent to
    #: Pidge, or the rider went offline.
    WITHDRAWN = "WITHDRAWN"


class TripEndReason(StrEnum):
    DELIVERED = "DELIVERED"
    CANCELLED_BEFORE_PICKUP = "CANCELLED_BEFORE_PICKUP"
    CANCELLED_AFTER_PICKUP = "CANCELLED_AFTER_PICKUP"
    CUSTOMER_UNAVAILABLE = "CUSTOMER_UNAVAILABLE"
    REASSIGNED = "REASSIGNED"


class AppMode(StrEnum):
    MARKETPLACE = "MARKETPLACE"
    SINGLE_RESTAURANT = "SINGLE_RESTAURANT"


class AppClientStatus(StrEnum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    OFFBOARDED = "OFFBOARDED"


class AppClientPlatform(StrEnum):
    IOS = "IOS"
    ANDROID = "ANDROID"


class AppClientDomainKind(StrEnum):
    """Who owns the address a storefront answers on.

    A subdomain we issue is ours: it resolves the moment the row exists, and
    there is nothing to prove. A domain the restaurant already owns has to be
    verified before it is served, or anyone could claim a name that is not
    theirs and be handed that brand's storefront.
    """

    PLATFORM_SUBDOMAIN = "PLATFORM_SUBDOMAIN"
    CUSTOM = "CUSTOM"


class AppClientEnvironment(StrEnum):
    PROD = "PROD"
    STAGING = "STAGING"


class PushCredentialProvider(StrEnum):
    FCM = "FCM"


class OrderStatus(StrEnum):
    # A card order lives here until the payment provider confirms the charge.
    # The kitchen never sees it, and it is not part of ORDER_STATUS_FLOW.
    PAYMENT_PENDING = "PAYMENT_PENDING"
    PLACED = "PLACED"
    ACCEPTED = "ACCEPTED"
    PREPARING = "PREPARING"
    OUT_FOR_DELIVERY = "OUT_FOR_DELIVERY"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class OrderFulfillmentType(StrEnum):
    DELIVERY = "DELIVERY"
    PICKUP = "PICKUP"


class OrderScheduleType(StrEnum):
    ASAP = "ASAP"
    SCHEDULED = "SCHEDULED"


class LocationDayOfWeek(StrEnum):
    MONDAY = "MONDAY"
    TUESDAY = "TUESDAY"
    WEDNESDAY = "WEDNESDAY"
    THURSDAY = "THURSDAY"
    FRIDAY = "FRIDAY"
    SATURDAY = "SATURDAY"
    SUNDAY = "SUNDAY"


class PaymentStatus(StrEnum):
    PENDING = "PENDING"
    PAID = "PAID"
    FAILED = "FAILED"
    COD = "COD"
    REFUNDED = "REFUNDED"
    # Customer dismissed the payment sheet, or the intent was cancelled.
    CANCELLED = "CANCELLED"


class GeneratedComboLifecycleStatus(StrEnum):
    DRAFT = "DRAFT"
    LIVE = "LIVE"
    ARCHIVED = "ARCHIVED"


class PaymentGateway(StrEnum):
    """A gateway a restaurant can hold an account with.

    Distinct from `PaymentMethod`, which is what the customer picks on the
    checkout screen. One gateway can settle several methods — Razorpay's own
    checkout covers UPI, cards, netbanking and wallets behind one button — and
    one method can be settled by more than one gateway, which is exactly why
    these are two enums rather than one.
    """

    STRIPE = "STRIPE"
    RAZORPAY = "RAZORPAY"


class PaymentMethod(StrEnum):
    GOOGLE_PAY = "GOOGLE_PAY"
    RAZORPAY = "RAZORPAY"
    CARD = "CARD"
    COD = "COD"


class MenuItemCustomizationSelectionType(StrEnum):
    SINGLE = "SINGLE"
    MULTI = "MULTI"


class MenuItemPortion(StrEnum):
    """Which part of the item a chosen option applies to.

    Half-and-half toppings: pepperoni on one side, mushroom on the other. Only
    groups the owner marks `supports_halves` may use LEFT or RIGHT, so a client
    cannot half-price a topping on an item the kitchen cannot split.

    LEFT and RIGHT are labels for two halves, not geometry — the kitchen reads
    them off the ticket. Naming them is what lets an order say which topping
    goes where at all.
    """

    WHOLE = "WHOLE"
    LEFT = "LEFT"
    RIGHT = "RIGHT"


class ChatMessageRole(StrEnum):
    USER = "USER"
    ASSISTANT = "ASSISTANT"


class PersonalizedOfferType(StrEnum):
    WELCOME_FIRST_ORDER = "WELCOME_FIRST_ORDER"
    FAVORITE_ITEM = "FAVORITE_ITEM"
    FAVORITE_RESTAURANT = "FAVORITE_RESTAURANT"
    PREFERENCE_MATCH = "PREFERENCE_MATCH"
    ORDER_HISTORY_MATCH = "ORDER_HISTORY_MATCH"
    NEW_ITEM_MATCH = "NEW_ITEM_MATCH"
    TASTE_MATCH = "TASTE_MATCH"
    CUISINE_AFFINITY = "CUISINE_AFFINITY"
    BUDGET_BEHAVIOR = "BUDGET_BEHAVIOR"
    COMBO_AFFINITY = "COMBO_AFFINITY"
    CUSTOM = "CUSTOM"


class PersonalizedOfferAudience(StrEnum):
    ACTIVE_USERS = "ACTIVE_USERS"
    INACTIVE_USERS = "INACTIVE_USERS"
    ALL_CUSTOMERS = "ALL_CUSTOMERS"


class PersonalizedOfferState(StrEnum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    EXPIRED = "EXPIRED"
    DISABLED = "DISABLED"


class PersonalizedOfferDiscountType(StrEnum):
    NONE = "NONE"
    PERCENTAGE = "PERCENTAGE"
    FLAT = "FLAT"
    FREE_DELIVERY = "FREE_DELIVERY"


class PersonalizedOfferEventType(StrEnum):
    VIEWED = "VIEWED"
    CLICKED = "CLICKED"
    CONVERTED = "CONVERTED"


class PersonalizedOfferSource(StrEnum):
    MANUAL_TEMPLATE = "MANUAL_TEMPLATE"
    AI_GENERATED = "AI_GENERATED"


class PersonalizedOfferGenerationReason(StrEnum):
    REPEATED_ORDER = "REPEATED_ORDER"
    FAVORITE_RESTAURANT = "FAVORITE_RESTAURANT"
    FIRST_ORDER = "FIRST_ORDER"
    INACTIVE_USER = "INACTIVE_USER"
    CUISINE_AFFINITY = "CUISINE_AFFINITY"
    COMBO_AFFINITY = "COMBO_AFFINITY"
    BUDGET_BEHAVIOR = "BUDGET_BEHAVIOR"
    GLOBAL_FALLBACK = "GLOBAL_FALLBACK"


class OwnerInsightType(StrEnum):
    REVENUE_DROP = "REVENUE_DROP"
    REVENUE_SPIKE = "REVENUE_SPIKE"
    ITEM_DECLINE = "ITEM_DECLINE"
    ITEM_SURGE = "ITEM_SURGE"
    CATEGORY_DECLINE = "CATEGORY_DECLINE"
    DAYPART_WEAKNESS = "DAYPART_WEAKNESS"
    WEEKDAY_WEAKNESS = "WEEKDAY_WEAKNESS"
    RETURNING_CUSTOMER_DECLINE = "RETURNING_CUSTOMER_DECLINE"
    NEW_CUSTOMER_DECLINE = "NEW_CUSTOMER_DECLINE"
    CANCELLATION_SPIKE = "CANCELLATION_SPIKE"
    AOV_DROP = "AOV_DROP"
    ANOMALY_DAY = "ANOMALY_DAY"
    # Root-cause findings, from the operational history added in Phase 6A.
    STOCKOUT_IMPACT = "STOCKOUT_IMPACT"
    SLOW_ACCEPTANCE = "SLOW_ACCEPTANCE"
    # Branch-level movement, from the location dimension added in Phase 8A.
    LOCATION_DECLINE = "LOCATION_DECLINE"
    # Phase 8B: a finding the analyst reached itself rather than one a rule
    # matched. Its own category is carried in `ai_category`, because the whole
    # point of an analyst is that it can find something this enum does not name.
    AI_DISCOVERED = "AI_DISCOVERED"


class OwnerInsightSeverity(StrEnum):
    INFO = "INFO"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class InsightOrigin(StrEnum):
    """Who produced a finding: a deterministic rule, or the analyst.

    Recorded on every insight and proposal so a reader can always tell a
    measured conclusion from a generated one, and so AI output can be filtered
    out wholesale while it is still being evaluated.
    """

    RULES = "RULES"
    AI = "AI"


class AnalysisRunStatus(StrEnum):
    """How one analyst run ended."""

    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    REJECTED = "REJECTED"
    SKIPPED = "SKIPPED"


class AnalysisConfidence(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class OwnerInsightStatus(StrEnum):
    NEW = "NEW"
    SEEN = "SEEN"
    DISMISSED = "DISMISSED"


class InsightNarrationSource(StrEnum):
    TEMPLATE = "TEMPLATE"
    LLM = "LLM"


class OrderCancellationReason(StrEnum):
    """Why an order was cancelled.

    The first four are system-derived. The last five are a person's: since
    2026-10-06 the platform admin or the restaurant's owner may cancel an
    order the rider has not collected yet (`services/order_cancellation.py`),
    choosing one of these, never free text - a note rides beside it.
    """

    # The card intent was never completed within its TTL, so the reaper closed it.
    PAYMENT_NOT_COMPLETED = "PAYMENT_NOT_COMPLETED"
    # The customer dismissed the payment sheet before paying.
    PAYMENT_ABANDONED = "PAYMENT_ABANDONED"
    # The payment provider declined or failed the charge outright.
    PAYMENT_FAILED = "PAYMENT_FAILED"
    # Recorded when history predates reason tracking and no path can be inferred.
    UNKNOWN = "UNKNOWN"
    # Cancelled by staff (admin or owner). `STAFF_CANCELLATION_REASONS`.
    OUT_OF_STOCK = "OUT_OF_STOCK"
    KITCHEN_UNAVAILABLE = "KITCHEN_UNAVAILABLE"  # closed, or too busy to cook it
    CUSTOMER_REQUEST = "CUSTOMER_REQUEST"
    DUPLICATE_OR_TEST = "DUPLICATE_OR_TEST"
    OTHER_BY_STAFF = "OTHER_BY_STAFF"  # needs a note saying what


class OrderEventActor(StrEnum):
    """Who caused a change: staff, the customer, or an automated job."""

    OWNER = "OWNER"
    ADMIN = "ADMIN"
    CUSTOMER = "CUSTOMER"
    # Distinct from OWNER on purpose. Without it `actor_for_user` falls through
    # to SYSTEM, and every advance a cook made would be logged as something the
    # platform did by itself — which is exactly the question this table exists
    # to answer.
    KITCHEN = "KITCHEN"
    # The same reason as KITCHEN: a rider's "picked up" must not read as the
    # platform moving the order by itself.
    RIDER = "RIDER"
    SYSTEM = "SYSTEM"
    PAYMENT_PROVIDER = "PAYMENT_PROVIDER"


class ActionOutcomeVerdict(StrEnum):
    """What was observed after an action ran.

    Deliberately phrased as observation, not causation: there is no holdout
    group, so nothing here can prove the action produced the result.
    """

    NO_UPTAKE = "NO_UPTAKE"
    BELOW_ESTIMATE = "BELOW_ESTIMATE"
    MET_ESTIMATE = "MET_ESTIMATE"
    ABOVE_ESTIMATE = "ABOVE_ESTIMATE"
    NOT_MEASURABLE = "NOT_MEASURABLE"


class OwnerActionType(StrEnum):
    # Executable: approving these creates a real offer.
    PROMOTE_ITEM = "PROMOTE_ITEM"
    PROMOTE_CATEGORY = "PROMOTE_CATEGORY"
    DAYPART_OFFER = "DAYPART_OFFER"
    WINBACK_INACTIVE = "WINBACK_INACTIVE"
    WELCOME_NEW_CUSTOMERS = "WELCOME_NEW_CUSTOMERS"
    CROSS_SELL_COMBO = "CROSS_SELL_COMBO"
    # Advisory: the data supports the observation but not an automated fix.
    OPERATIONAL_REVIEW = "OPERATIONAL_REVIEW"
    PROTECT_SUPPLY = "PROTECT_SUPPLY"


class OwnerActionStatus(StrEnum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    EXECUTED = "EXECUTED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"


class PushNotificationAudience(StrEnum):
    ALL_USERS = "ALL_USERS"
    CUSTOMERS = "CUSTOMERS"
    OWNERS = "OWNERS"
    ADMINS = "ADMINS"
    SPECIFIC_USER = "SPECIFIC_USER"
    # A marketing campaign's audience: the members of one segment, narrowed to
    # the chosen branches. Unlike every value above it, the recipient list
    # cannot be derived from a role - it is computed per campaign.
    SEGMENT = "SEGMENT"


class PushNotificationDeliveryType(StrEnum):
    INSTANT = "INSTANT"
    SCHEDULED = "SCHEDULED"


class PushNotificationCampaignStatus(StrEnum):
    DRAFT = "DRAFT"
    SCHEDULED = "SCHEDULED"
    SENDING = "SENDING"
    SENT = "SENT"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class CampaignRecipientState(StrEnum):
    """What happened to one customer's copy of one campaign.

    SKIPPED is distinct from FAILED on purpose: a customer with no device token
    was never attempted and nothing went wrong, while FAILED means Firebase was
    asked and refused. Collapsing them would make a campaign to an audience
    that mostly has no app installed look broken.
    """

    PENDING = "PENDING"
    SENT = "SENT"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class PushNotificationEventType(StrEnum):
    SENT = "SENT"
    DELIVERED = "DELIVERED"
    OPENED = "OPENED"
    FAILED = "FAILED"
    # Marketing only. A tap that reached the deep link's destination, and a
    # marketing opt-out attributed to the message that prompted it - both are
    # things a transactional order update has no equivalent of.
    CLICKED = "CLICKED"
    UNSUBSCRIBED = "UNSUBSCRIBED"


class PushNotificationCampaignKind(StrEnum):
    """Why a push exists, which decides who may see it and what caps it.

    The distinction is not cosmetic. A transactional push tells someone their
    own order was accepted: it ignores marketing consent, ignores the weekly
    frequency cap and ignores quiet hours, because suppressing it would be a
    fault. A marketing push is subject to all three. Both live in
    `push_notification_campaigns`, so without this column the send path has no
    way to tell which rules apply, and the Marketing Hub's campaign list would
    show every order notification the platform has ever sent.

    Existing rows backfill to TRANSACTIONAL - the marketing routes are the only
    writer of MARKETING, so nothing sent before the Hub existed can be
    retro-attributed to a campaign nobody created.
    """

    TRANSACTIONAL = "TRANSACTIONAL"
    MARKETING = "MARKETING"


class MarketingChannel(StrEnum):
    """Delivery channels a campaign can name.

    Every value other than PUSH is declared but unsendable in Phase 1. They
    exist here because the channel picker has to render them as unavailable
    with a reason, and a UI that offers a channel the backend has never heard
    of cannot be validated server-side.
    """

    PUSH = "PUSH"
    EMAIL = "EMAIL"
    SMS = "SMS"
    WHATSAPP = "WHATSAPP"
    FACEBOOK = "FACEBOOK"
    INSTAGRAM = "INSTAGRAM"


class MarketingChannelFamily(StrEnum):
    """Whether a channel is addressed to people or broadcast to nobody.

    This is the distinction the whole Hub turns on, and it is not cosmetic.

    DIRECT (push, WhatsApp, SMS, email) names recipients: consent applies, the
    audience is countable before the send, one recipient row is written per
    customer, and attribution is measured per recipient from their own send
    instant.

    SOCIAL (Instagram, Facebook) names nobody. There is no consent to check
    and no recipient row to write, so the per-recipient attribution rule the
    rest of this product runs on has no subject. A public post is attributed
    by a promo code the customer types at checkout, which is a weaker claim
    and is reported as one.
    """

    DIRECT = "DIRECT"
    SOCIAL = "SOCIAL"


#: Which family each channel belongs to. Kept beside the enum rather than in a
#: service because it is a property of the channel itself, and both the reach
#: path and the dispatch path branch on it before any service is involved.
CHANNEL_FAMILY: dict[MarketingChannel, MarketingChannelFamily] = {
    MarketingChannel.PUSH: MarketingChannelFamily.DIRECT,
    MarketingChannel.EMAIL: MarketingChannelFamily.DIRECT,
    MarketingChannel.SMS: MarketingChannelFamily.DIRECT,
    MarketingChannel.WHATSAPP: MarketingChannelFamily.DIRECT,
    MarketingChannel.FACEBOOK: MarketingChannelFamily.SOCIAL,
    MarketingChannel.INSTAGRAM: MarketingChannelFamily.SOCIAL,
}


def channel_family(channel: MarketingChannel) -> MarketingChannelFamily:
    """DIRECT for anything not explicitly declared social.

    The default matters: a channel added to `MarketingChannel` and forgotten
    here would otherwise raise mid-dispatch. Treating it as DIRECT means it
    fails the "no provider for this channel" check instead, which is a message
    an owner can read.
    """

    return CHANNEL_FAMILY.get(channel, MarketingChannelFamily.DIRECT)


class ChannelConnectionStatus(StrEnum):
    """How far a restaurant has got with switching a channel on.

    Absence of a row means NOT_CONNECTED, so this enum never needs that value:
    a status column that can disagree with the existence of the row it sits on
    is a bug waiting to be written.

    DISABLED is distinct from deleting the row. An owner who pauses WhatsApp
    for a month should not have to re-authorise Meta afterwards, and a channel
    that failed verification should keep its configuration so the owner can
    see what was wrong with it.
    """

    CONNECTED = "CONNECTED"
    DISABLED = "DISABLED"
    ERROR = "ERROR"


class CampaignPostState(StrEnum):
    """What happened to a campaign's one public post.

    The social counterpart of `CampaignRecipientState`, and deliberately not
    the same enum: a post is published or it is not, there is no SKIPPED
    because there is no recipient to skip, and its identifiers (a platform
    post id, a permalink) have no equivalent on a push.
    """

    PENDING = "PENDING"
    PUBLISHED = "PUBLISHED"
    FAILED = "FAILED"


class MarketingCampaignGoal(StrEnum):
    """What the owner said they were trying to achieve.

    Goals are not rules - they seed defaults (a segment, a set of channels,
    whether to suggest a discount) and they label the report. Nothing in the
    send path branches on a goal, which is why a new one can be added without
    touching dispatch.
    """

    WINBACK = "WINBACK"
    PROMOTE_DISH = "PROMOTE_DISH"
    NEW_ITEM = "NEW_ITEM"
    QUIET_DAY = "QUIET_DAY"
    REWARD_VIPS = "REWARD_VIPS"
    FIRST_TO_REGULAR = "FIRST_TO_REGULAR"
    ANNOUNCEMENT = "ANNOUNCEMENT"
    CUSTOM = "CUSTOM"


class MarketingSegmentKey(StrEnum):
    """The audiences a campaign can be sent to.

    Each one resolves to a real SQL definition in
    `services/marketing/segments.py`; the owner-facing one-liner lives beside
    it. They are recency/frequency/monetary shaped, which is deliberately a
    different axis from `ai_offer_segments`' item/category/cuisine affinity -
    that module answers "what should this offer be about", this one answers
    "who should hear from us".
    """

    LAPSED_REGULARS = "LAPSED_REGULARS"
    FIRST_TIME_BUYERS = "FIRST_TIME_BUYERS"
    VIPS = "VIPS"
    BIG_SPENDERS = "BIG_SPENDERS"
    WEEKEND_DINERS = "WEEKEND_DINERS"
    DISH_FANS = "DISH_FANS"
    BRANCH_CUSTOMERS = "BRANCH_CUSTOMERS"
    NEVER_ORDERED = "NEVER_ORDERED"


class MarketingDeepLink(StrEnum):
    """Where tapping the notification lands the customer."""

    RESTAURANT_HOME = "RESTAURANT_HOME"
    MENU_ITEM = "MENU_ITEM"
    OFFERS = "OFFERS"
    CART = "CART"


class MarketingNoticeTone(StrEnum):
    """How hard a pre-send check pushes back.

    BLOCK is the only one that stops a send, and it is re-decided server-side
    at dispatch rather than trusted from the client.
    """

    BLOCK = "block"
    WARN = "warn"
    INFO = "info"


class PreferenceInputType(StrEnum):
    SINGLE_SELECT = "SINGLE_SELECT"
    MULTI_SELECT = "MULTI_SELECT"


class PreferenceSignalRole(StrEnum):
    """What the recommender is allowed to do with a question's answers.

    The questionnaire's structure is data, but its meaning is not: the scoring
    engine treats a diet answer differently from a spice answer, and it cannot
    infer that from a prompt string. This is the declaration that connects one
    to the other.

    `NONE` is the important value. A question carrying it is collected, stored
    and returned like any other, and contributes nothing to ranking - which is
    what lets an owner add a question today without anyone re-tuning the
    weights, and what a future taste vector will read from.
    """

    CUISINE = "CUISINE"
    DISLIKED_CUISINE = "DISLIKED_CUISINE"
    DIET = "DIET"
    SPICE = "SPICE"
    BUDGET = "BUDGET"
    FAVORITE_ITEM = "FAVORITE_ITEM"
    NONE = "NONE"


class PrinterTransport(StrEnum):
    """How an agent reaches one printer.

    Two, because restaurants have both and the agent is installed into whatever
    is already on the counter.

    `TCP` is ESC/POS straight to the printer's own address on port 9100. It
    needs no driver, produces identical bytes everywhere, and a Windows service
    can do it, which is the whole reason it is built first.

    `WINDOWS` goes through the print spooler, for a printer attached to the PC
    by USB. It carries a constraint that is easy to miss and expensive to
    discover: a Windows service runs in Session 0, which has no user profile
    and therefore cannot see per-user installed printers. An agent configured
    this way has to run as a logged-in user's startup task instead.
    """

    TCP = "TCP"
    WINDOWS = "WINDOWS"


class PrintJobKind(StrEnum):
    """What a ticket is for.

    The kinds are separate because they are different documents with different
    audiences, not one document with a flag: a kitchen docket omits money and
    shouts the items, a bill shows the money and is handed to a customer, and a
    void slip exists to contradict a docket somebody is already holding.

    Which printer takes which is `printers.docket_kinds` — data, so one PC can
    drive a kitchen printer and a counter printer without the agent branching
    on anything.
    """

    KITCHEN_DOCKET = "KITCHEN_DOCKET"
    CUSTOMER_BILL = "CUSTOMER_BILL"
    VOID_SLIP = "VOID_SLIP"
    TEST = "TEST"


class PrintJobSource(StrEnum):
    """Whether the platform decided to print this, or a person did.

    Load-bearing rather than descriptive: the partial unique index that makes
    automatic printing idempotent is scoped to `AUTO`, so one order yields one
    docket per printer however many times an enqueue fires. A reprint is
    `MANUAL` and deliberately unconstrained, because asking for a second copy
    is the entire point of pressing the button.
    """

    AUTO = "AUTO"
    MANUAL = "MANUAL"


class PrintJobStatus(StrEnum):
    """Where a ticket is between being decided on and being on paper.

    `CLAIMED` is not decoration. An agent takes a job under a short lease, so a
    second poll cannot serve the same ticket twice, and an agent that dies
    mid-print hands it back by doing nothing at all — the lease simply expires
    and the job is claimable again.

    `FAILED` is not terminal in the way the others are: it carries a sentence
    written for the owner, and it is excluded from the idempotency index so a
    ticket that failed can be enqueued again.
    """

    QUEUED = "QUEUED"
    CLAIMED = "CLAIMED"
    PRINTED = "PRINTED"
    FAILED = "FAILED"


class PayoutStatus(StrEnum):
    """Where one order's share for the restaurant is. See `services/payouts`."""

    # Paid, but nothing has gone to the restaurant yet: no active linked
    # account, payouts switched off, or the payment id not known yet.
    WAITING_ACCOUNT = "WAITING_ACCOUNT"
    HELD = "HELD"  # transferred, on hold until the order is delivered
    RELEASED = "RELEASED"  # hold lifted; Razorpay settles it on its schedule
    SETTLED = "SETTLED"  # in the restaurant's bank
    REVERSED = "REVERSED"  # taken back: cancelled or refunded
    FAILED = "FAILED"  # Razorpay refused; Retry once the cause is fixed
    BLOCKED = "BLOCKED"  # the split did not reconcile, nothing is transferred
    # COD, Stripe, or the restaurant's own keys: the money never passed
    # through the platform, so there is nothing to send. Recorded anyway so
    # the screen shows every order's split.
    NOT_APPLICABLE = "NOT_APPLICABLE"


class PayoutAccountStatus(StrEnum):
    """A restaurant's Razorpay linked account, as Razorpay last described it."""

    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
