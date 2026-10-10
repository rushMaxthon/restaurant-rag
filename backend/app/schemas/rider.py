"""Request and response shapes for the rider app and the admin's rider roster."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.models.enums import ApplicationStatus, RiderOnboarding, RiderStatus, VehicleType

# --- admin -------------------------------------------------------------------


class RiderCreate(BaseModel):
    full_name: str = Field(min_length=1, max_length=120)
    phone_number: str = Field(min_length=6, max_length=20)
    password: str = Field(min_length=8, max_length=128)
    vehicle_type: VehicleType
    vehicle_number: str = Field(default="", max_length=32)
    city: str = Field(default="", max_length=80)
    notes: str = Field(default="", max_length=2000)


class RiderUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=120)
    password: str | None = Field(default=None, min_length=8, max_length=128)
    vehicle_type: VehicleType | None = None
    vehicle_number: str | None = Field(default=None, max_length=32)
    city: str | None = Field(default=None, max_length=80)
    notes: str | None = Field(default=None, max_length=2000)
    is_active: bool | None = None


class RiderResponse(BaseModel):
    user_id: uuid.UUID
    full_name: str
    phone_number: str | None
    is_active: bool
    vehicle_type: VehicleType
    vehicle_number: str
    city: str
    status: RiderStatus
    last_latitude: float | None
    last_longitude: float | None
    last_location_at: datetime | None
    active_order_id: uuid.UUID | None = None
    notes: str = ""


# --- the rider app ------------------------------------------------------------


class RiderMe(BaseModel):
    user_id: uuid.UUID
    full_name: str
    phone_number: str | None
    vehicle_type: VehicleType
    vehicle_number: str
    city: str
    status: RiderStatus
    today_trips: int
    today_earnings: Decimal
    fleet_enabled: bool
    #: What a delivery pays right now, so the app can say it (admin-set).
    #: The admin's rate card, so the app can show what a delivery pays.
    pay: "RiderPayIn"
    #: APPROVED riders get the app; anyone else gets their application.
    onboarding: RiderOnboarding = RiderOnboarding.APPROVED
    #: None for a rider an admin made (they never applied).
    application_status: ApplicationStatus | None = None


class StatusUpdate(BaseModel):
    online: bool


class LocationFixIn(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    accuracy_m: float | None = Field(default=None, ge=0, le=5000)
    at: datetime


class LocationBatch(BaseModel):
    fixes: list[LocationFixIn] = Field(min_length=1, max_length=20)


class DeviceToken(BaseModel):
    token: str = Field(min_length=10, max_length=4096)
    app_version: str = Field(default="", max_length=32)


class OfferView(BaseModel):
    id: uuid.UUID
    expires_at: datetime
    seconds_left: int
    total_seconds: int
    restaurant_name: str
    branch: str
    pickup_address: str
    pickup_distance_m: float | None
    trip_distance_km: float
    #: None past the rate card: the admin prices that trip by hand.
    earning_estimate: Decimal | None
    drop_area: str
    item_count: int
    #: When the kitchen expects the food to be ready (the branch's preparation
    #: time after it accepted); None when the branch has none set.
    ready_at: datetime | None = None


class OpenOrderView(BaseModel):
    """An order a free rider may take from the list (`offers.open_orders`)."""

    order_id: uuid.UUID
    restaurant_name: str
    branch: str
    pickup_address: str
    pickup_distance_m: float | None
    trip_distance_km: float
    #: None past the rate card: the admin prices that trip by hand.
    earning_estimate: Decimal | None
    drop_area: str
    item_count: int
    #: Until the courier is booked instead.
    minutes_left: int
    #: Offered to this rider first, and they let it run out or declined it.
    missed: bool = False
    #: When the kitchen expects the food to be ready; None when the branch
    #: has no preparation time set.
    ready_at: datetime | None = None


class TripStop(BaseModel):
    name: str
    address: str
    phone: str
    lat: float | None
    lng: float | None
    branch: str | None = None
    instructions: str | None = None


class TripItem(BaseModel):
    name: str
    quantity: int


class TripView(BaseModel):
    id: uuid.UUID
    order_id: uuid.UUID
    order_code: str
    #: to_pickup | at_pickup | to_drop | at_drop | done
    step: str
    accepted_at: datetime
    arrived_pickup_at: datetime | None
    picked_up_at: datetime | None
    arrived_drop_at: datetime | None
    delivered_at: datetime | None
    ended_at: datetime | None
    end_reason: str | None
    call_attempts: int
    distance_km: float
    #: None for a trip past the rate card until the admin prices it.
    earning: Decimal | None
    otp_locked: bool
    otp_attempts_left: int
    pickup: TripStop
    drop: TripStop
    items: list[TripItem]
    item_count: int
    #: When the kitchen expects the food to be ready (the branch's preparation
    #: time after it accepted); None when the branch has none set.
    ready_at: datetime | None = None


class TripAction(BaseModel):
    #: Generated by the app per tap and reused on retry, so a retried request
    #: changes nothing twice.
    action_id: str = Field(min_length=8, max_length=64)
    otp: str | None = Field(default=None, max_length=8)


class EarningDay(BaseModel):
    date: str
    trips: int
    amount: Decimal


class Earnings(BaseModel):
    today: Decimal
    today_trips: int
    period_total: Decimal
    period_trips: int
    unpaid: Decimal
    paid_total: Decimal
    days: list[EarningDay]


# --- admin operations -----------------------------------------------------------


class PaySlabIn(BaseModel):
    up_to_km: float = Field(gt=0, le=50)
    amount: Decimal = Field(ge=0, le=1000)


class RiderPayIn(BaseModel):
    """The rate card (`fleet/config.RiderPay`): slabs, the per-delivery incentive,
    and what a ride to the restaurant pays when the order is then cancelled."""

    slabs: list[PaySlabIn] = Field(min_length=1, max_length=40)
    incentive: Decimal = Field(ge=0, le=1000)
    minimum: Decimal = Field(ge=0, le=1000)


class FleetConfigIn(BaseModel):
    offer_seconds: int = Field(default=30, ge=10, le=120)
    max_offers: int = Field(default=5, ge=1, le=20)
    window_minutes: int = Field(default=5, ge=1, le=30)
    radius_km: float = Field(default=6.0, ge=0.5, le=25)
    silent_minutes: int = Field(default=3, ge=1, le=30)
    push_minutes: int = Field(default=15, ge=0, le=60)
    wave_minutes: int = Field(default=2, ge=1, le=10)
    first_wave_km: float = Field(default=2.0, ge=0.5, le=25)
    ready_lead_minutes: int = Field(default=10, ge=0, le=60)
    location_ids: list[str] = Field(default_factory=list, max_length=500)


class FleetBranch(BaseModel):
    """A branch `location_ids` can name, so the admin picks by name, not by id."""

    id: uuid.UUID
    restaurant_name: str
    branch_name: str
    city: str
    delivery_enabled: bool


class MapBranch(BaseModel):
    """A restaurant branch as a pin on the live map."""

    id: uuid.UUID
    restaurant_name: str
    branch_name: str
    lat: float
    lng: float
    #: Our riders serve it (`location_ids` empty, or naming it); otherwise
    #: its orders go straight to the courier.
    on_fleet: bool


class FleetSettings(BaseModel):
    #: `enable_own_fleet` on this server - read-only here, set by deployment.
    enabled: bool
    pay: RiderPayIn
    fleet: FleetConfigIn
    #: Every active branch of a real (non-demo) restaurant, for the allowlist.
    branches: list[FleetBranch] = Field(default_factory=list)


class FleetOfferRow(BaseModel):
    rider_user_id: uuid.UUID
    rider_name: str
    outcome: str
    offered_at: datetime
    responded_at: datetime | None
    metres: float | None


class FleetDeliveryView(BaseModel):
    provider: str
    state: str
    attempt: int
    otp_locked: bool
    fallback_reason: str | None
    offers: list[FleetOfferRow]
    trip: TripView | None


class WaitingOrder(BaseModel):
    """An order our fleet holds with no rider on it: a pin on the admin's map."""

    order_id: uuid.UUID
    order_code: str
    restaurant_name: str
    provider: str
    pickup_lat: float | None
    pickup_lng: float | None
    drop_lat: float | None
    drop_lng: float | None
    ordered_at: datetime
    #: The rider being asked right now, if any - assigning someone else withdraws it.
    offered_to: str | None = None
    #: How far from the branch riders see it right now (the current wave);
    #: None for an order no rider is offered (unassigned, or no branch pin).
    reach_km: float | None = None
    #: When the food should be ready, and - while still in the future - when
    #: riders will hear of it (`fleet.ready`).
    ready_at: datetime | None = None
    opens_at: datetime | None = None


class ReassignIn(BaseModel):
    rider_user_id: uuid.UUID


class ConfirmDeliveredIn(BaseModel):
    reason: str = Field(min_length=5, max_length=500)


class TripToPrice(BaseModel):
    """A trip past the rate card, waiting for the admin's price."""

    trip_id: uuid.UUID
    rider_user_id: uuid.UUID
    rider_name: str
    order_id: uuid.UUID
    order_code: str
    distance_km: float | None
    over_km: float | None
    #: Added on top of the admin's amount; 0 when the trip was not delivered.
    incentive: Decimal
    delivered: bool
    end_reason: str | None
    ended_at: datetime


class ManualPayIn(BaseModel):
    amount: Decimal = Field(ge=0, le=5000)


class ManualPayOut(BaseModel):
    trip_id: uuid.UUID
    earning_amount: Decimal


class UnpaidRow(BaseModel):
    rider_user_id: uuid.UUID
    full_name: str
    trips: int
    amount: Decimal
    oldest: datetime | None


class PayoutIn(BaseModel):
    period_to: datetime
    reference: str = Field(default="", max_length=120)


class PayoutOut(BaseModel):
    id: uuid.UUID
    rider_user_id: uuid.UUID
    period_from: datetime
    period_to: datetime
    amount: Decimal
    trips: int
    reference: str
    paid_at: datetime
