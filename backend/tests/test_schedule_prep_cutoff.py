"""Prep time has to fit before the kitchen closes.

Reported from the product side, with the example that makes it obvious: if a
branch closes at 11pm and needs 15 minutes to cook, nobody should be able to
book 10:50pm — or 11pm, which is what the picker actually offered.

ASAP ordering already got this right: `get_location_fulfillment_status` refuses
once `now + prep` passes the window end. SCHEDULED ordering did not. Both the
generator and the validator used `<= slot_end`, so the last bookable slot was
the closing minute itself, with no time left to cook it.

No database: a RestaurantLocation is built in memory with the windows each test
needs, so the boundary is pinned to exact clock times rather than to whatever
the seed happens to hold that day.
"""

from __future__ import annotations

import unittest
import uuid
from datetime import datetime, time, timedelta

from app.main import app  # noqa: F401 - imported first to settle import order
from app.models.enums import LocationDayOfWeek, OrderFulfillmentType
from app.models.location_fulfillment_slot import LocationFulfillmentSlot
from app.models.restaurant_location import RestaurantLocation
from app.services.restaurant_locations import (
    BUSINESS_TIMEZONE,
    list_available_schedule_options,
    schedule_slot_is_available,
)

DAYS = [
    LocationDayOfWeek.MONDAY,
    LocationDayOfWeek.TUESDAY,
    LocationDayOfWeek.WEDNESDAY,
    LocationDayOfWeek.THURSDAY,
    LocationDayOfWeek.FRIDAY,
    LocationDayOfWeek.SATURDAY,
    LocationDayOfWeek.SUNDAY,
]


def build_location(
    *,
    prep_minutes: int = 15,
    eta_minutes: int = 15,
    interval: int = 15,
    opens: time = time(9, 0),
    closes: time = time(23, 0),
) -> RestaurantLocation:
    """A branch open the same window every day, so the weekday never matters."""

    location = RestaurantLocation(
        id=uuid.uuid4(),
        restaurant_id=uuid.uuid4(),
        branch_name="Test Branch",
        address_line_1="1 Test Street",
        city="Ahmedabad",
        state="Gujarat",
        postal_code="380015",
        phone_number="9876543210",
        delivery_enabled=True,
        pickup_enabled=True,
        delivery_fee=0,
        minimum_order_amount=0,
        estimated_delivery_time=eta_minutes,
        estimated_pickup_time=eta_minutes,
        preparation_time_minutes=prep_minutes,
        is_open=True,
        is_active=True,
        future_order_enabled=True,
        max_future_days=7,
        slot_interval_minutes=interval,
    )
    location.fulfillment_slots = [
        LocationFulfillmentSlot(
            id=uuid.uuid4(),
            location_id=location.id,
            day_of_week=day,
            fulfillment_type=fulfillment,
            start_time=opens,
            end_time=closes,
            is_active=True,
        )
        for day in DAYS
        for fulfillment in (OrderFulfillmentType.DELIVERY, OrderFulfillmentType.PICKUP)
    ]
    return location


def at(hour: int, minute: int = 0, *, days_ahead: int = 0) -> datetime:
    base = datetime.now(BUSINESS_TIMEZONE).replace(
        hour=hour, minute=minute, second=0, microsecond=0
    )
    return base + timedelta(days=days_ahead)


class LastSlotLeavesTimeToCookTests(unittest.TestCase):
    def _todays_labels(self, location: RestaurantLocation, *, now: datetime) -> list[str]:
        options = list_available_schedule_options(
            location,
            restaurant_id=location.restaurant_id,
            fulfillment_type=OrderFulfillmentType.DELIVERY,
            reference_dt=now,
        )
        today = [group for group in options.groups if group.label == "Today"]
        return [option.label for option in today[0].slots] if today else []

    def test_the_last_slot_is_prep_time_before_closing(self) -> None:
        # The reported example: closes 11pm, needs 15 minutes to cook, 15 to
        # deliver. The buffer is prep + travel, so the last bookable slot is
        # 10:30 PM — cook from 10:30, out the door by 10:45, delivered by 11:00.
        location = build_location(prep_minutes=15, eta_minutes=15, interval=15, closes=time(23, 0))
        labels = self._todays_labels(location, now=at(9, 0))
        self.assertTrue(labels)
        self.assertEqual(labels[-1], "10:30 PM")
        self.assertNotIn("11:00 PM", labels)
        self.assertNotIn("10:45 PM", labels)

    def test_a_longer_delivery_eta_pulls_the_last_slot_further_back(self) -> None:
        # 15 to cook plus 45 to drive is an hour, so 10:00 PM is the last slot
        # that still lands before an 11pm close.
        location = build_location(prep_minutes=15, eta_minutes=45, interval=15, closes=time(23, 0))
        labels = self._todays_labels(location, now=at(9, 0))
        self.assertEqual(labels[-1], "10:00 PM")

    def test_the_cutoff_lands_on_the_interval_grid(self) -> None:
        # 23:00 minus a 40 minute buffer (20 to cook, 20 to travel) is 22:20,
        # which is not a 30-minute grid point. Offering it would be refused by
        # the interval check, so the last slot has to be the grid point at or
        # before the cutoff.
        location = build_location(prep_minutes=20, eta_minutes=20, interval=30, closes=time(23, 0))
        labels = self._todays_labels(location, now=at(9, 0))
        self.assertEqual(labels[-1], "10:00 PM")

    def test_a_window_shorter_than_the_prep_time_offers_nothing(self) -> None:
        # Open 10:00 to 10:10 with a 15 minute buffer: there is no honest slot
        # in there, and offering one would fail at the server after the customer
        # had filled in the whole form.
        location = build_location(
            prep_minutes=15, eta_minutes=15, interval=15, opens=time(10, 0), closes=time(10, 10)
        )
        self.assertEqual(self._todays_labels(location, now=at(9, 0)), [])


class SchedulingTooCloseToClosingTests(unittest.TestCase):
    def _check(self, location: RestaurantLocation, when: datetime, *, now: datetime):
        return schedule_slot_is_available(
            location,
            fulfillment_type=OrderFulfillmentType.DELIVERY,
            scheduled_at=when,
            reference_dt=now,
        )

    def test_the_advice_names_a_time_that_can_actually_be_picked(self) -> None:
        # 23:00 minus a 58 minute buffer (29 to cook, 29 to travel) is 22:02,
        # which is not on a 30-minute grid. Saying "the latest time is 10:02 PM"
        # names a slot the interval check would then reject, sending the
        # customer round again.
        location = build_location(prep_minutes=29, eta_minutes=29, interval=30, closes=time(23, 0))
        ok, reason = self._check(location, at(23, 0), now=at(9, 0))
        self.assertFalse(ok)
        assert reason is not None
        self.assertIn("10:00 PM", reason)
        self.assertNotIn("10:02", reason)

    def test_the_closing_minute_is_refused(self) -> None:
        location = build_location(prep_minutes=15, eta_minutes=15, interval=15, closes=time(23, 0))
        ok, reason = self._check(location, at(23, 0), now=at(9, 0))
        self.assertFalse(ok)
        self.assertIsNotNone(reason)

    def test_a_time_inside_the_prep_window_is_refused(self) -> None:
        location = build_location(prep_minutes=15, eta_minutes=15, interval=15, closes=time(23, 0))
        ok, _ = self._check(location, at(22, 50), now=at(9, 0))
        self.assertFalse(ok)

    def test_the_last_honest_slot_is_accepted(self) -> None:
        location = build_location(prep_minutes=15, eta_minutes=15, interval=15, closes=time(23, 0))
        ok, reason = self._check(location, at(22, 30), now=at(9, 0))
        self.assertTrue(ok, reason)
        # And the one after it is not: 10:45 leaves 15 minutes for a job that
        # needs 30.
        ok, _ = self._check(location, at(22, 45), now=at(9, 0))
        self.assertFalse(ok)

    def test_an_ordinary_midday_slot_is_untouched(self) -> None:
        # The cutoff must not cost anyone a slot in the middle of the day.
        location = build_location(prep_minutes=15, eta_minutes=15, interval=15, closes=time(23, 0))
        ok, reason = self._check(location, at(13, 0), now=at(9, 0))
        self.assertTrue(ok, reason)

    def test_tomorrow_is_measured_against_tomorrows_closing(self) -> None:
        location = build_location(prep_minutes=15, eta_minutes=15, interval=15, closes=time(23, 0))
        ok, _ = self._check(location, at(23, 0, days_ahead=1), now=at(9, 0))
        self.assertFalse(ok)
        ok, reason = self._check(location, at(22, 30, days_ahead=1), now=at(9, 0))
        self.assertTrue(ok, reason)


if __name__ == "__main__":
    unittest.main()
