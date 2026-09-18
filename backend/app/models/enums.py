from __future__ import annotations

from enum import StrEnum


class UserRole(StrEnum):
    ADMIN = "ADMIN"
    OWNER = "OWNER"
    CUSTOMER = "CUSTOMER"


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

    Every value here is system-derived. The platform has no human cancellation
    flow — `ORDER_STATUS_FLOW` is strictly linear and refuses anything else —
    so a cancellation is always one of these, and never a free-text guess.
    """

    # The card intent was never completed within its TTL, so the reaper closed it.
    PAYMENT_NOT_COMPLETED = "PAYMENT_NOT_COMPLETED"
    # The customer dismissed the payment sheet before paying.
    PAYMENT_ABANDONED = "PAYMENT_ABANDONED"
    # The payment provider declined or failed the charge outright.
    PAYMENT_FAILED = "PAYMENT_FAILED"
    # Recorded when history predates reason tracking and no path can be inferred.
    UNKNOWN = "UNKNOWN"


class OrderEventActor(StrEnum):
    """Who caused a change: staff, the customer, or an automated job."""

    OWNER = "OWNER"
    ADMIN = "ADMIN"
    CUSTOMER = "CUSTOMER"
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


class PushNotificationEventType(StrEnum):
    SENT = "SENT"
    DELIVERED = "DELIVERED"
    OPENED = "OPENED"
    FAILED = "FAILED"


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
