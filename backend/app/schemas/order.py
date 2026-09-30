from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.config import get_settings
from app.models.enums import (
    MenuItemPortion,
    OrderFulfillmentType,
    OrderScheduleType,
    OrderStatus,
    PaymentMethod,
    PaymentStatus,
)


class OrderRestaurantSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
    cuisine_type: str
    city: str
    address_line_1: str


class OrderRestaurantLocationSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    branch_name: str
    city: str
    address_line_1: str
    delivery_fee: Decimal
    minimum_order_amount: Decimal
    estimated_delivery_time: int
    estimated_pickup_time: int
    delivery_enabled: bool
    pickup_enabled: bool
    enabled_payment_methods: list[PaymentMethod]
    is_open: bool
    is_active: bool


class OrderCustomerSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    full_name: str
    email: str
    phone_number: str | None


class OrderCreateItemCustomizationOption(BaseModel):
    option_id: uuid.UUID
    quantity: int = Field(default=1, ge=1, le=99)
    # Which half this topping goes on. WHOLE unless the customer split a group
    # the owner marked splittable; the server refuses LEFT/RIGHT otherwise.
    portion: MenuItemPortion = MenuItemPortion.WHOLE


class OrderCreateItem(BaseModel):
    menu_item_id: uuid.UUID
    menu_item_size_id: uuid.UUID | None = None
    selected_options: list[OrderCreateItemCustomizationOption] = Field(default_factory=list)
    quantity: int = Field(ge=1, le=99)


class OrderCreateRequest(BaseModel):
    restaurant_id: uuid.UUID
    restaurant_location_id: uuid.UUID | None = None
    personalized_offer_id: uuid.UUID | None = None
    generated_offer_id: uuid.UUID | None = None
    generated_offer_user_match_id: uuid.UUID | None = None
    fulfillment_type: OrderFulfillmentType = OrderFulfillmentType.DELIVERY
    schedule_type: OrderScheduleType = OrderScheduleType.ASAP
    scheduled_at: datetime | None = None
    items: list[OrderCreateItem] = Field(min_length=1, max_length=50)
    delivery_address: str = Field(min_length=5, max_length=2000)
    # Who to ring about this delivery. Optional so the mobile client, which
    # does not send them yet, keeps working; the web checkout requires them.
    contact_name: str | None = Field(default=None, max_length=255)
    contact_phone: str | None = Field(default=None, max_length=32)
    special_instructions: str | None = Field(default=None, max_length=2000)

    @field_validator("contact_name")
    @classmethod
    def clean_contact_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @field_validator("contact_phone")
    @classmethod
    def normalize_contact_phone(cls, value: str | None) -> str | None:
        """One number, one shape.

        The same phone typed as "(415) 555-0132", "415-555-0132" and
        "+1 415 555 0132" must reach the kitchen identically, or two identical
        numbers look like two different people and nobody can search for one.

        Country code and national length come from settings rather than being
        written in here, so a deployment outside North America changes a
        setting instead of editing a validator.
        """

        if value is None:
            return None
        raw = value.strip()
        if not raw:
            return None

        had_plus = raw.startswith("+")
        digits = "".join(character for character in raw if character.isdigit())
        if not digits:
            raise ValueError("Enter a phone number using digits.")

        settings = get_settings()
        national_length = int(settings.default_phone_national_digits)
        country_code = settings.default_phone_country_code.lstrip("+")

        if had_plus:
            if len(digits) < 8 or len(digits) > 15:
                raise ValueError("Enter a valid phone number, including the country code.")
            return f"+{digits}"

        # A leading zero is how a great many people write their own national
        # number — "09825012345" — and refusing it taught the customer nothing
        # except that the form did not like them.
        if len(digits) == national_length + 1 and digits.startswith("0"):
            digits = digits[1:]

        if len(digits) == national_length:
            return f"+{country_code}{digits}"
        # Typed with the country code but no plus, e.g. "1 415 555 0132".
        if len(digits) == national_length + len(country_code) and digits.startswith(country_code):
            return f"+{digits}"
        raise ValueError(
            f"Enter a {national_length}-digit phone number, or include the country code."
        )
    payment_method: PaymentMethod = PaymentMethod.COD
    # Accepted for backwards compatibility with older clients and IGNORED. The
    # provider is derived from the method, and the reference is written only by
    # the payment service once a real provider intent exists. A client can never
    # describe its own payment.
    payment_provider: str | None = Field(
        default=None, max_length=50, deprecated=True
    )
    payment_reference: str | None = Field(
        default=None, max_length=255, deprecated=True
    )


class ChargeLineResponse(BaseModel):
    """One row of the breakdown behind the collapsed charges line.

    `note` is not decoration. A platform fee with no explanation reads as a
    made-up number, and a tax row that does not say the rate is the
    government's invites a complaint aimed at the wrong party.
    """

    key: str
    label: str
    amount: Decimal
    note: str = ""


class OrderChargesResponse(BaseModel):
    """What sits behind "Taxes and charges" when a customer opens it.

    One line on the summary, because four extra rows on a checkout read as
    nickel-and-diming. A breakdown behind it, because a total nobody can take
    apart is a total nobody trusts.
    """

    total: Decimal
    lines: list[ChargeLineResponse] = Field(default_factory=list)


class OrderValidationResponse(BaseModel):
    valid: bool = True
    restaurant_id: uuid.UUID
    restaurant_location_id: uuid.UUID
    fulfillment_type: OrderFulfillmentType
    schedule_type: OrderScheduleType
    scheduled_at: datetime
    subtotal: Decimal
    delivery_fee: Decimal
    #: Everything that is neither the food nor the delivery, collapsed into one
    #: figure. `charges` is the same number taken apart.
    tax_amount: Decimal
    discount_amount: Decimal
    total_amount: Decimal
    currency: str
    item_count: int
    charges: OrderChargesResponse | None = None


class DeliveryQuoteRequest(BaseModel):
    """Where to, so a courier can price the trip.

    Deliberately not the whole cart. A customer typing their address wants to
    know the delivery fee before they have finished choosing food, and making
    them assemble a valid order first to learn the price is the wrong way
    round.
    """

    restaurant_location_id: uuid.UUID
    delivery_address: str = Field(default="", max_length=500)
    #: The address in parts, when the form has them. Structured beats a single
    #: blob and it is not close: a geocoder given separate fields can refuse a
    #: house number in the wrong city, while one given a joined string silently
    #: picks whichever reading scores best. The form collects these as separate
    #: boxes already, so flattening them and asking a geocoder to take them
    #: apart again loses accuracy for nothing.
    city: str = Field(default="", max_length=120)
    state: str = Field(default="", max_length=120)
    postal_code: str = Field(default="", max_length=20)
    country: str = Field(default="", max_length=120)
    #: A saved address the customer chose. Its stored coordinates are used
    #: directly, so a repeat order is priced with no geocoder call at all.
    saved_address_id: uuid.UUID | None = None
    #: The cart's food total, so the reply can price the WHOLE bill rather than
    #: just the delivery.
    #:
    #: The client could add up the tax itself from rates on the branch, and that
    #: is exactly the arrangement to avoid: two implementations of the same
    #: arithmetic drift, and when they disagree the customer is right to believe
    #: the screen while the server charges something else. One rule, on the
    #: server, asked live.
    subtotal: Decimal | None = Field(default=None, ge=0)
    #: Any offer already applied, because food tax follows the discount.
    discount_amount: Decimal = Field(default=Decimal("0"), ge=0)
    #: The coordinates of a place the customer PICKED from the autocomplete.
    #:
    #: The whole reason a dropdown beats a text box. These come from the map
    #: provider's own record of that building, so accepting them is strictly
    #: better than geocoding the text underneath — which would be a second paid
    #: call to get a worse answer.
    #:
    #: Range-checked because they arrive from a client. A client cannot invent a
    #: DELIVERY FEE with these: the courier is still the only thing that prices
    #: the trip, and a wrong coordinate produces a wrong distance rather than a
    #: chosen number. The bounds keep a malformed pair from being sent to the
    #: courier as a real request.
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)


class DeliveryQuoteResponse(BaseModel):
    """What delivery costs, and where the figure came from.

    `source` is the point of this response. A checkout showing a number the
    customer will pay should be able to say whether a courier priced this
    particular trip or whether it is the restaurant's own flat rate — and a
    support call six weeks later is unanswerable without it.
    """

    delivery_fee: Decimal
    currency: str
    #: "courier" when a courier priced this trip, "branch" for the flat fee.
    source: str
    #: WHY it is the branch's flat fee, when it is. The field that stops a
    #: checkout printing "Free" because a lookup quietly failed — which is
    #: exactly what happened to a real order: the branch was located, the
    #: customer's address was not, the fee fell back to a flat ₹0.00 and the
    #: page announced free delivery.
    #:
    #: * `""` — a courier priced it.
    #: * `"no_courier"` — none configured, or quoting is off. The flat fee is
    #:   the restaurant's own policy and is correct.
    #: * `"address_unknown"` — the customer's address could not be placed on a
    #:   map. Fixable by them: correct it, or pick it from the suggestions.
    #: * `"branch_unknown"` — the RESTAURANT has no usable coordinates. Nothing
    #:   the customer can do; the operator has to locate the branch.
    #: * `"unserviceable"` — the courier will not drive there.
    #: * `"currency_mismatch"` — the courier quoted a currency this order is not
    #:   charged in, so the quote was discarded rather than converted.
    fallback_reason: str = ""
    #: False when the courier will not serve the address at all. The fee then
    #: falls back to the branch's, because refusing an order on a courier's
    #: say-so is the restaurant's decision to make, not this endpoint's.
    serviceable: bool = True
    #: Straight-line-ish distance as the courier measured it, when it said.
    distance_metres: float | None = None
    #: Seconds the courier expects to need to find a rider at all. Often
    #: larger than the drive, and the difference between an honest ETA and an
    #: optimistic one.
    assign_seconds: int | None = None
    #: Seconds from the branch to the door, as the courier reckons the drive.
    #:
    #: NOT an ETA on its own and must never be shown as one: it excludes the
    #: time the kitchen spends cooking, which is most of the wait. The
    #: restaurant's own `estimated_delivery_time` is the figure that covers the
    #: whole journey.
    travel_seconds: int | None = None
    #: False when either end of the trip was a stand-in coordinate rather than
    #: a located address. The price is real; the trip it prices may not be.
    #:
    #: A geocoder never refuses — ask it for a street that does not exist and
    #: it hands back a city centroid without complaint. So this is not "did
    #: something answer" but "is the point precise enough to price": a
    #: locality-level match is a coordinate, not an address.
    exact_location: bool = True
    #: Where the drop coordinate came from: "row", "geocoder" or "stand-in".
    #: The field that makes a wrong quote diagnosable instead of mysterious.
    located_by: str = ""
    #: The address as the geocoder understood it. Shown when it disagrees with
    #: what the customer typed, which is the failure that otherwise looks
    #: exactly like success.
    matched_address: str = ""
    #: The rest of the bill, when a subtotal was sent: everything that is
    #: neither the food nor the delivery, with the parts behind it.
    charges: "OrderChargesResponse | None" = None
    #: What the customer will actually pay, worked out by the same code that
    #: charges them. Null when no subtotal was sent.
    total_amount: Decimal | None = None


class OrderStatusUpdateRequest(BaseModel):
    status: OrderStatus


class OrderItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    menu_item_id: uuid.UUID
    menu_item_size_id: uuid.UUID | None = None
    item_name_snapshot: str
    size_name_snapshot: str | None = None
    quantity: int
    base_unit_price: Decimal
    customization_total_price: Decimal
    unit_price: Decimal
    total_price: Decimal
    selected_options_snapshot: list[dict[str, object]] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class OrderResponse(BaseModel):
    id: uuid.UUID
    customer_id: uuid.UUID
    restaurant_id: uuid.UUID
    restaurant_location_id: uuid.UUID
    restaurant: OrderRestaurantSummary
    restaurant_location: OrderRestaurantLocationSummary
    customer: OrderCustomerSummary
    status: OrderStatus
    payment_status: PaymentStatus
    payment_method: PaymentMethod
    payment_provider: str
    payment_reference: str | None
    fulfillment_type: OrderFulfillmentType
    schedule_type: OrderScheduleType
    scheduled_at: datetime
    subtotal: Decimal
    delivery_fee: Decimal
    tax_amount: Decimal
    discount_amount: Decimal
    total_amount: Decimal
    currency: str
    #: The itemised bill, rebuilt from what this order STORED rather than from
    #: today's rates, so a receipt reads the same a year later.
    charges: OrderChargesResponse | None = None
    special_instructions: str | None
    delivery_address: str
    contact_name: str | None = None
    contact_phone: str | None = None
    placed_at: datetime
    created_at: datetime
    updated_at: datetime
    items: list[OrderItemResponse]


class OrderDeliveryResponse(BaseModel):
    """What the courier is doing with this order, for the admin.

    `state` is ours; `provider_status` is the courier's own word, kept so a
    status nobody has seen before is diagnosable from the screen rather than
    from the logs. `raw` is deliberately NOT here — it can carry a customer's
    address and phone in a shape nothing validates, and the panel has no use
    for it.
    """

    model_config = ConfigDict(from_attributes=True)

    provider: str
    provider_order_id: str
    state: str
    provider_status: str
    rider_name: str
    rider_mobile: str
    tracking_url: str
    distance_metres: float | None
    picked_up_at: datetime | None
    delivered_at: datetime | None
    last_error: str
    created_at: datetime
    updated_at: datetime
