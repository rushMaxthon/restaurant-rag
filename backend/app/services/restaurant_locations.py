from __future__ import annotations

import uuid
from collections.abc import Iterable
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from fastapi import HTTPException, status
from sqlalchemy import Select, and_, or_, select
from sqlalchemy.orm import Session, selectinload

from app.config import get_settings
from app.models.enums import (
    LocationDayOfWeek,
    OrderFulfillmentType,
    OrderScheduleType,
    PaymentMethod,
    UserRole,
)
from app.models.location_fulfillment_slot import LocationFulfillmentSlot
from app.models.restaurant import Restaurant
from app.models.restaurant_location import RestaurantLocation
from app.models.user import User
from app.schemas.restaurant import (
    LocationScheduleDayGroup,
    LocationScheduleOption,
    LocationScheduleOptionsResponse,
    LocationFulfillmentSlotCreate,
    LocationFulfillmentSlotResponse,
    LocationFulfillmentSlotUpdate,
    RestaurantLocationResponse,
)

DEFAULT_BRANCH_NAME = "Main Branch"
DEFAULT_SLOT_START_TIME = time(10, 30)
DEFAULT_SLOT_END_TIME = time(22, 0)
DEFAULT_FULFILLMENT_TYPES: tuple[OrderFulfillmentType, ...] = (
    OrderFulfillmentType.PICKUP,
    OrderFulfillmentType.DELIVERY,
)
settings = get_settings()
BUSINESS_TIMEZONE: ZoneInfo = settings.business_timezone_info
DAY_SEQUENCE: tuple[LocationDayOfWeek, ...] = (
    LocationDayOfWeek.MONDAY,
    LocationDayOfWeek.TUESDAY,
    LocationDayOfWeek.WEDNESDAY,
    LocationDayOfWeek.THURSDAY,
    LocationDayOfWeek.FRIDAY,
    LocationDayOfWeek.SATURDAY,
    LocationDayOfWeek.SUNDAY,
)


def build_default_location_for_restaurant(restaurant: Restaurant) -> RestaurantLocation:
    return RestaurantLocation(
        restaurant_id=restaurant.id,
        branch_name=DEFAULT_BRANCH_NAME,
        address_line_1=restaurant.address_line_1,
        address_line_2=restaurant.address_line_2,
        city=restaurant.city,
        state=restaurant.state,
        postal_code=restaurant.postal_code,
        phone_number=restaurant.phone_number,
        delivery_fee=restaurant.delivery_fee,
        minimum_order_amount=restaurant.minimum_order_amount,
        estimated_delivery_time=30,
        estimated_pickup_time=20,
        delivery_enabled=True,
        pickup_enabled=True,
        google_pay_enabled=True,
        razorpay_enabled=True,
        card_payment_enabled=True,
        cash_on_delivery_enabled=True,
        is_open=restaurant.is_open,
        is_active=restaurant.is_active,
        future_order_enabled=True,
        max_future_days=7,
        slot_interval_minutes=15,
    )


def _base_location_query(restaurant_id: uuid.UUID) -> Select[tuple[RestaurantLocation]]:
    return (
        select(RestaurantLocation)
        .options(selectinload(RestaurantLocation.fulfillment_slots))
        .where(RestaurantLocation.restaurant_id == restaurant_id)
    )


def _slot_query(location_id: uuid.UUID) -> Select[tuple[LocationFulfillmentSlot]]:
    return select(LocationFulfillmentSlot).where(LocationFulfillmentSlot.location_id == location_id)


def _weekday_for_datetime(reference_dt: datetime) -> LocationDayOfWeek:
    return DAY_SEQUENCE[reference_dt.astimezone(BUSINESS_TIMEZONE).weekday()]


def _time_in_slot(current_time: time, start_time: time, end_time: time) -> bool:
    return start_time <= current_time <= end_time


def _localize_reference_datetime(reference_dt: datetime | None = None) -> datetime:
    current_dt = reference_dt or datetime.now(BUSINESS_TIMEZONE)
    if current_dt.tzinfo is None:
        return current_dt.replace(tzinfo=BUSINESS_TIMEZONE)
    return current_dt.astimezone(BUSINESS_TIMEZONE)


def _interval_ceil(reference_dt: datetime, *, interval_minutes: int) -> datetime:
    if interval_minutes <= 0:
        return reference_dt.replace(second=0, microsecond=0)
    normalized = reference_dt.replace(second=0, microsecond=0)
    remainder = normalized.minute % interval_minutes
    if remainder == 0 and normalized == reference_dt.replace(second=0, microsecond=0):
        return normalized
    delta_minutes = 0 if remainder == 0 else interval_minutes - remainder
    if reference_dt.second or reference_dt.microsecond:
        if delta_minutes == 0:
            delta_minutes = interval_minutes
    return normalized + timedelta(minutes=delta_minutes)


def _combine_local_datetime(target_date: date, target_time: time) -> datetime:
    return datetime.combine(target_date, target_time, tzinfo=BUSINESS_TIMEZONE)


def _get_prep_buffer_minutes(
    location: RestaurantLocation,
    fulfillment_type: OrderFulfillmentType,
) -> int:
    eta_minutes = (
        int(location.estimated_delivery_time)
        if fulfillment_type == OrderFulfillmentType.DELIVERY
        else int(location.estimated_pickup_time)
    )
    preparation_minutes = int(location.preparation_time_minutes or 0)
    return max(preparation_minutes, eta_minutes)


def _active_slots_for_fulfillment(
    location: RestaurantLocation,
    fulfillment_type: OrderFulfillmentType,
) -> list[LocationFulfillmentSlot]:
    return [
        slot
        for slot in location.fulfillment_slots
        if slot.is_active and slot.fulfillment_type == fulfillment_type
    ]


def _slot_schedule_enabled(
    location: RestaurantLocation,
    fulfillment_type: OrderFulfillmentType,
) -> bool:
    return bool(_active_slots_for_fulfillment(location, fulfillment_type))


def _get_current_window_end_for_fulfillment(
    location: RestaurantLocation,
    *,
    fulfillment_type: OrderFulfillmentType,
    reference_dt: datetime,
) -> tuple[datetime | None, str | None]:
    current_local = _localize_reference_datetime(reference_dt)
    current_time = current_local.time().replace(second=0, microsecond=0)

    if _slot_schedule_enabled(location, fulfillment_type):
        current_day = _weekday_for_datetime(current_local)
        todays_slots = [
            slot
            for slot in _active_slots_for_fulfillment(location, fulfillment_type)
            if slot.day_of_week == current_day
        ]
        if not todays_slots:
            label = "delivery" if fulfillment_type == OrderFulfillmentType.DELIVERY else "pickup"
            return None, f"No active {label} slots are configured for today."
        for slot in todays_slots:
            if _time_in_slot(current_time, slot.start_time, slot.end_time):
                return _combine_local_datetime(current_local.date(), slot.end_time), None
        label = "delivery" if fulfillment_type == OrderFulfillmentType.DELIVERY else "pickup"
        return None, f"{label.capitalize()} is outside the current branch schedule."

    if location.opening_time is not None and location.closing_time is not None:
        if not _time_in_slot(current_time, location.opening_time, location.closing_time):
            return None, "This branch is outside its operating hours."
        return _combine_local_datetime(current_local.date(), location.closing_time), None

    return None, None


def _serialize_slot(slot: LocationFulfillmentSlot) -> LocationFulfillmentSlotResponse:
    return LocationFulfillmentSlotResponse.model_validate(slot)


def get_enabled_payment_methods(location: RestaurantLocation) -> list[PaymentMethod]:
    methods: list[PaymentMethod] = []
    if location.google_pay_enabled:
        methods.append(PaymentMethod.GOOGLE_PAY)
    if location.razorpay_enabled:
        methods.append(PaymentMethod.RAZORPAY)
    if location.card_payment_enabled:
        methods.append(PaymentMethod.CARD)
    if location.cash_on_delivery_enabled:
        methods.append(PaymentMethod.COD)
    return methods


def ensure_default_location_slots(
    db: Session,
    *,
    location_id: uuid.UUID,
) -> list[LocationFulfillmentSlot]:
    existing_windows = {
        (
            slot.day_of_week,
            slot.fulfillment_type,
            slot.start_time,
            slot.end_time,
        )
        for slot in db.scalars(_slot_query(location_id)).all()
    }
    created_slots: list[LocationFulfillmentSlot] = []
    for day_of_week in DAY_SEQUENCE:
        for fulfillment_type in DEFAULT_FULFILLMENT_TYPES:
            window_key = (
                day_of_week,
                fulfillment_type,
                DEFAULT_SLOT_START_TIME,
                DEFAULT_SLOT_END_TIME,
            )
            if window_key in existing_windows:
                continue
            slot = LocationFulfillmentSlot(
                location_id=location_id,
                day_of_week=day_of_week,
                fulfillment_type=fulfillment_type,
                start_time=DEFAULT_SLOT_START_TIME,
                end_time=DEFAULT_SLOT_END_TIME,
                is_active=True,
            )
            db.add(slot)
            created_slots.append(slot)
            existing_windows.add(window_key)
    if created_slots:
        db.flush()
    return created_slots


def schedule_slot_is_available(
    location: RestaurantLocation,
    *,
    fulfillment_type: OrderFulfillmentType,
    scheduled_at: datetime,
    reference_dt: datetime | None = None,
) -> tuple[bool, str | None]:
    scheduled_local = _localize_reference_datetime(scheduled_at)
    current_local = _localize_reference_datetime(reference_dt)

    if not location.is_active:
        return False, "This branch is inactive right now."
    if not location.is_open:
        return False, location.temporary_closed_reason or "This branch is currently closed."
    if fulfillment_type == OrderFulfillmentType.DELIVERY and not location.delivery_enabled:
        return False, "Delivery is currently unavailable for this branch."
    if fulfillment_type == OrderFulfillmentType.PICKUP and not location.pickup_enabled:
        return False, "Pickup is currently unavailable for this branch."
    if not location.future_order_enabled:
        return False, "Scheduled orders are currently unavailable for this branch."

    prep_buffer_minutes = _get_prep_buffer_minutes(location, fulfillment_type)
    earliest_allowed = current_local + timedelta(minutes=prep_buffer_minutes)
    if scheduled_local < earliest_allowed:
        return False, f"Please choose a time at least {prep_buffer_minutes} minutes from now."

    latest_allowed = current_local + timedelta(days=int(location.max_future_days))
    if scheduled_local > latest_allowed:
        return False, f"You can schedule up to {int(location.max_future_days)} days ahead."

    interval = int(location.slot_interval_minutes)
    if scheduled_local.minute % interval != 0 or scheduled_local.second != 0 or scheduled_local.microsecond != 0:
        return False, f"Please select a valid {interval}-minute time slot."

    if _slot_schedule_enabled(location, fulfillment_type):
        current_day = _weekday_for_datetime(scheduled_local)
        matching_slots = [
            slot
            for slot in _active_slots_for_fulfillment(location, fulfillment_type)
            if slot.day_of_week == current_day
            and _time_in_slot(scheduled_local.time(), slot.start_time, slot.end_time)
        ]
        if not matching_slots:
            label = "delivery" if fulfillment_type == OrderFulfillmentType.DELIVERY else "pickup"
            return False, f"{label.capitalize()} is not available for the selected time."
    elif location.opening_time is not None and location.closing_time is not None:
        if not _time_in_slot(scheduled_local.time(), location.opening_time, location.closing_time):
            return False, "The selected time is outside the branch operating hours."

    return True, None


def list_available_schedule_options(
    location: RestaurantLocation,
    *,
    restaurant_id: uuid.UUID,
    fulfillment_type: OrderFulfillmentType,
    reference_dt: datetime | None = None,
) -> LocationScheduleOptionsResponse:
    current_local = _localize_reference_datetime(reference_dt)
    asap_available, asap_unavailable_reason = get_location_fulfillment_status(
        location,
        fulfillment_type=fulfillment_type,
        reference_dt=current_local,
    )
    prep_buffer_minutes = _get_prep_buffer_minutes(location, fulfillment_type)
    groups: list[LocationScheduleDayGroup] = []
    scheduled_prerequisite_reason: str | None = None
    if not location.is_active:
        scheduled_prerequisite_reason = "This branch is inactive right now."
    elif not location.is_open:
        scheduled_prerequisite_reason = (
            location.temporary_closed_reason or "This branch is currently closed."
        )
    elif fulfillment_type == OrderFulfillmentType.DELIVERY and not location.delivery_enabled:
        scheduled_prerequisite_reason = "Delivery is currently unavailable for this branch."
    elif fulfillment_type == OrderFulfillmentType.PICKUP and not location.pickup_enabled:
        scheduled_prerequisite_reason = "Pickup is currently unavailable for this branch."
    elif not location.future_order_enabled:
        scheduled_prerequisite_reason = "Scheduled orders are currently unavailable for this branch."

    if scheduled_prerequisite_reason is None:
        interval = int(location.slot_interval_minutes)
        for day_offset in range(int(location.max_future_days) + 1):
            target_date = (current_local + timedelta(days=day_offset)).date()
            day_label = (
                "Today"
                if day_offset == 0
                else "Tomorrow"
                if day_offset == 1
                else target_date.strftime("%A")
            )
            target_day = DAY_SEQUENCE[target_date.weekday()]

            if _slot_schedule_enabled(location, fulfillment_type):
                day_slots = [
                    slot
                    for slot in _active_slots_for_fulfillment(location, fulfillment_type)
                    if slot.day_of_week == target_day
                ]
            elif location.opening_time is not None and location.closing_time is not None:
                synthetic_slot = LocationFulfillmentSlot(
                    location_id=location.id,
                    day_of_week=target_day,
                    fulfillment_type=fulfillment_type,
                    start_time=location.opening_time,
                    end_time=location.closing_time,
                    is_active=True,
                )
                day_slots = [synthetic_slot]
            else:
                day_slots = []

            option_rows: list[LocationScheduleOption] = []
            earliest_slot_dt = current_local + timedelta(minutes=prep_buffer_minutes)
            for slot in day_slots:
                slot_start = _combine_local_datetime(target_date, slot.start_time)
                slot_end = _combine_local_datetime(target_date, slot.end_time)
                candidate = slot_start
                if day_offset == 0 and candidate < earliest_slot_dt:
                    candidate = _interval_ceil(earliest_slot_dt, interval_minutes=interval)
                else:
                    candidate = _interval_ceil(candidate, interval_minutes=interval)

                while candidate <= slot_end:
                    option_rows.append(
                        LocationScheduleOption(
                            scheduled_at=candidate.astimezone(BUSINESS_TIMEZONE),
                            label=candidate.strftime("%I:%M %p").lstrip("0"),
                        )
                    )
                    candidate += timedelta(minutes=interval)

            if option_rows:
                groups.append(
                    LocationScheduleDayGroup(
                        date=target_date,
                        label=day_label,
                        slots=option_rows,
                    )
                )

    scheduled_available = bool(groups)
    scheduled_unavailable_reason = (
        None
        if scheduled_available
        else (
            scheduled_prerequisite_reason
            or "No future slots are currently available for this fulfillment type."
        )
    )

    eta_minutes = (
        int(location.estimated_delivery_time)
        if fulfillment_type == OrderFulfillmentType.DELIVERY
        else int(location.estimated_pickup_time)
    )

    return LocationScheduleOptionsResponse(
        restaurant_id=restaurant_id,
        location_id=location.id,
        fulfillment_type=fulfillment_type,
        schedule_type=OrderScheduleType.SCHEDULED,
        asap_available=asap_available,
        asap_eta_minutes=eta_minutes,
        asap_unavailable_reason=None if asap_available else asap_unavailable_reason,
        future_order_enabled=location.future_order_enabled,
        max_future_days=int(location.max_future_days),
        slot_interval_minutes=int(location.slot_interval_minutes),
        prep_buffer_minutes=prep_buffer_minutes,
        scheduled_available=scheduled_available,
        scheduled_unavailable_reason=scheduled_unavailable_reason,
        groups=groups,
    )


def validate_slot_window(start_time: time, end_time: time) -> None:
    if start_time >= end_time:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Start time must be before end time",
        )


def ensure_no_overlapping_slots(
    db: Session,
    *,
    location_id: uuid.UUID,
    day_of_week: LocationDayOfWeek,
    fulfillment_type: OrderFulfillmentType,
    start_time: time,
    end_time: time,
    exclude_slot_id: uuid.UUID | None = None,
) -> None:
    overlap_filters = [
        LocationFulfillmentSlot.location_id == location_id,
        LocationFulfillmentSlot.day_of_week == day_of_week,
        LocationFulfillmentSlot.fulfillment_type == fulfillment_type,
        LocationFulfillmentSlot.is_active.is_(True),
        LocationFulfillmentSlot.start_time < end_time,
        LocationFulfillmentSlot.end_time > start_time,
    ]
    if exclude_slot_id is not None:
        overlap_filters.append(LocationFulfillmentSlot.id != exclude_slot_id)

    overlapping_slot = db.scalar(select(LocationFulfillmentSlot).where(*overlap_filters))
    if overlapping_slot is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This slot overlaps with an existing active slot for the same day and fulfillment type",
        )


def list_restaurant_locations(
    db: Session,
    *,
    restaurant_id: uuid.UUID,
    include_inactive: bool = False,
) -> list[RestaurantLocation]:
    query = _base_location_query(restaurant_id)
    if not include_inactive:
        query = query.where(RestaurantLocation.is_active.is_(True))
    return db.scalars(
        query.order_by(
            RestaurantLocation.is_open.desc(),
            RestaurantLocation.is_active.desc(),
            RestaurantLocation.created_at.asc(),
            RestaurantLocation.branch_name.asc(),
        )
    ).all()


def get_location_for_restaurant(
    db: Session,
    *,
    restaurant_id: uuid.UUID,
    location_id: uuid.UUID,
    include_inactive: bool = False,
) -> RestaurantLocation | None:
    query = _base_location_query(restaurant_id).where(RestaurantLocation.id == location_id)
    if not include_inactive:
        query = query.where(RestaurantLocation.is_active.is_(True))
    return db.scalar(query)


def require_location_for_restaurant(
    db: Session,
    *,
    restaurant_id: uuid.UUID,
    location_id: uuid.UUID,
    include_inactive: bool = False,
) -> RestaurantLocation:
    location = get_location_for_restaurant(
        db,
        restaurant_id=restaurant_id,
        location_id=location_id,
        include_inactive=include_inactive,
    )
    if location is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Restaurant location not found")
    return location


def get_default_location_for_restaurant(
    db: Session,
    *,
    restaurant_id: uuid.UUID,
    include_inactive: bool = False,
) -> RestaurantLocation | None:
    locations = list_restaurant_locations(
        db,
        restaurant_id=restaurant_id,
        include_inactive=include_inactive,
    )
    if not locations:
        return None
    open_locations = [location for location in locations if location.is_open and location.is_active]
    if open_locations:
        return open_locations[0]
    if include_inactive:
        return locations[0]
    active_locations = [location for location in locations if location.is_active]
    return active_locations[0] if active_locations else None


def resolve_location_for_restaurant(
    db: Session,
    *,
    restaurant_id: uuid.UUID,
    location_id: uuid.UUID | None,
    include_inactive: bool = False,
) -> RestaurantLocation | None:
    if location_id is not None:
        return get_location_for_restaurant(
            db,
            restaurant_id=restaurant_id,
            location_id=location_id,
            include_inactive=include_inactive,
        )
    return get_default_location_for_restaurant(
        db,
        restaurant_id=restaurant_id,
        include_inactive=include_inactive,
    )


def ensure_location_access(
    db: Session,
    *,
    restaurant: Restaurant,
    current_user: User | None,
    location_id: uuid.UUID | None,
) -> RestaurantLocation | None:
    include_inactive = bool(
        current_user is not None and current_user.role in {UserRole.ADMIN, UserRole.OWNER}
    )
    location = resolve_location_for_restaurant(
        db,
        restaurant_id=restaurant.id,
        location_id=location_id,
        include_inactive=include_inactive,
    )
    if location is None:
        return None
    if current_user is None or current_user.role == UserRole.CUSTOMER:
        if not restaurant.is_active or not restaurant.is_approved or not location.is_active:
            return None
    return location


def list_location_fulfillment_slots(
    db: Session,
    *,
    location_id: uuid.UUID,
    include_inactive: bool = True,
) -> list[LocationFulfillmentSlot]:
    query = _slot_query(location_id)
    if not include_inactive:
        query = query.where(LocationFulfillmentSlot.is_active.is_(True))
    return db.scalars(
        query.order_by(
            LocationFulfillmentSlot.day_of_week.asc(),
            LocationFulfillmentSlot.fulfillment_type.asc(),
            LocationFulfillmentSlot.start_time.asc(),
        )
    ).all()


def require_location_slot(
    db: Session,
    *,
    location_id: uuid.UUID,
    slot_id: uuid.UUID,
) -> LocationFulfillmentSlot:
    slot = db.scalar(_slot_query(location_id).where(LocationFulfillmentSlot.id == slot_id))
    if slot is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Location slot not found")
    return slot


def create_location_slot(
    db: Session,
    *,
    location: RestaurantLocation,
    payload: LocationFulfillmentSlotCreate,
) -> LocationFulfillmentSlot:
    validate_slot_window(payload.start_time, payload.end_time)
    if payload.is_active:
        ensure_no_overlapping_slots(
            db,
            location_id=location.id,
            day_of_week=payload.day_of_week,
            fulfillment_type=payload.fulfillment_type,
            start_time=payload.start_time,
            end_time=payload.end_time,
        )

    slot = LocationFulfillmentSlot(location_id=location.id, **payload.model_dump())
    db.add(slot)
    db.flush()
    db.refresh(slot)
    return slot


def update_location_slot(
    db: Session,
    *,
    slot: LocationFulfillmentSlot,
    payload: LocationFulfillmentSlotUpdate,
) -> LocationFulfillmentSlot:
    next_day = payload.day_of_week or slot.day_of_week
    next_fulfillment_type = payload.fulfillment_type or slot.fulfillment_type
    next_start_time = payload.start_time or slot.start_time
    next_end_time = payload.end_time or slot.end_time
    next_active = slot.is_active if payload.is_active is None else payload.is_active

    validate_slot_window(next_start_time, next_end_time)
    if next_active:
        ensure_no_overlapping_slots(
            db,
            location_id=slot.location_id,
            day_of_week=next_day,
            fulfillment_type=next_fulfillment_type,
            start_time=next_start_time,
            end_time=next_end_time,
            exclude_slot_id=slot.id,
        )

    for field_name, value in payload.model_dump(exclude_unset=True).items():
        setattr(slot, field_name, value)
    db.add(slot)
    db.flush()
    db.refresh(slot)
    return slot


def get_location_fulfillment_status(
    location: RestaurantLocation,
    *,
    fulfillment_type: OrderFulfillmentType,
    reference_dt: datetime | None = None,
) -> tuple[bool, str | None]:
    current_dt = _localize_reference_datetime(reference_dt)

    if not location.is_active:
        return False, "This branch is inactive right now."
    if not location.is_open:
        return False, location.temporary_closed_reason or "This branch is currently closed."
    if fulfillment_type == OrderFulfillmentType.DELIVERY and not location.delivery_enabled:
        return False, "Delivery is currently unavailable for this branch."
    if fulfillment_type == OrderFulfillmentType.PICKUP and not location.pickup_enabled:
        return False, "Pickup is currently unavailable for this branch."

    current_window_end, unavailable_reason = _get_current_window_end_for_fulfillment(
        location,
        fulfillment_type=fulfillment_type,
        reference_dt=current_dt,
    )
    if unavailable_reason:
        return False, unavailable_reason
    if current_window_end is None:
        return True, None

    prep_buffer_minutes = _get_prep_buffer_minutes(location, fulfillment_type)
    earliest_ready = current_dt + timedelta(minutes=prep_buffer_minutes)
    if earliest_ready > current_window_end:
        return False, "ASAP ordering is unavailable because the kitchen is closing soon."

    return True, None


def build_location_response(
    location: RestaurantLocation,
    *,
    include_slots: bool = True,
    reference_dt: datetime | None = None,
) -> RestaurantLocationResponse:
    delivery_available_now, delivery_reason = get_location_fulfillment_status(
        location,
        fulfillment_type=OrderFulfillmentType.DELIVERY,
        reference_dt=reference_dt,
    )
    pickup_available_now, pickup_reason = get_location_fulfillment_status(
        location,
        fulfillment_type=OrderFulfillmentType.PICKUP,
        reference_dt=reference_dt,
    )
    payload = RestaurantLocationResponse.model_validate(location).model_copy(
        update={
            "delivery_available_now": delivery_available_now,
            "pickup_available_now": pickup_available_now,
            "delivery_unavailable_reason": None if delivery_available_now else delivery_reason,
            "pickup_unavailable_reason": None if pickup_available_now else pickup_reason,
            "enabled_payment_methods": get_enabled_payment_methods(location),
            "fulfillment_slots": (
                [_serialize_slot(slot) for slot in sorted_slots(location.fulfillment_slots)]
                if include_slots
                else []
            ),
        }
    )
    return payload


def sorted_slots(slots: Iterable[LocationFulfillmentSlot]) -> list[LocationFulfillmentSlot]:
    day_index = {day: index for index, day in enumerate(DAY_SEQUENCE)}
    return sorted(
        slots,
        key=lambda slot: (
            day_index.get(slot.day_of_week, 99),
            slot.fulfillment_type.value,
            slot.start_time,
            slot.end_time,
        ),
    )
