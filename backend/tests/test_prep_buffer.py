"""How long the kitchen needs before the window shuts.

The ordering cutoff is the window end minus PREPARATION TIME. Travel is not
subtracted.

It has been all three things. Originally `max(prep, eta)`, which meant prep
never counted — measured across all 18 branches, prep runs 15-20 minutes against
ETAs of 20-33, so the ETA always won and `preparation_time_minutes` changed
nothing an owner could observe. Then briefly `prep + eta`, which read the window
end as the moment food must be in the customer's hands.

Neither is what the window means. It is when the shop stops taking orders, and
what has to fit before then is cooking. A driver still out at 21:45 is not a
problem the ordering window exists to prevent.

For Bangkok Bowl Bodakdev, delivery window ending 21:30, prep 20:

    max(prep, eta)   buffer 20   last order 21:10
    prep + eta       buffer 40   last order 20:50
    prep only        buffer 20   last order 21:10   <- this

A NULL prep falls back to the ETA rather than to zero. Five of eight stored rows
have none, and the fallback is protection, not a claim about travel: without it
those branches would accept an order at the closing minute with nothing left to
cook it.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.main import app  # noqa: F401 - imported first to settle import order
from app.models.enums import OrderFulfillmentType
from app.services.restaurant_locations import _get_prep_buffer_minutes


class FakeLocation:
    def __init__(self, prep, delivery_eta, pickup_eta):
        self.preparation_time_minutes = prep
        self.estimated_delivery_time = delivery_eta
        self.estimated_pickup_time = pickup_eta


class PrepBufferTests(unittest.TestCase):
    def test_only_preparation_time_is_subtracted(self) -> None:
        location = FakeLocation(prep=20, delivery_eta=29, pickup_eta=19)
        self.assertEqual(
            _get_prep_buffer_minutes(location, OrderFulfillmentType.DELIVERY),
            20,
        )

    def test_pickup_uses_the_same_prep_time(self) -> None:
        """The kitchen does not cook faster because the customer collects."""

        location = FakeLocation(prep=20, delivery_eta=29, pickup_eta=19)
        self.assertEqual(
            _get_prep_buffer_minutes(location, OrderFulfillmentType.PICKUP),
            20,
        )

    def test_travel_time_does_not_shorten_the_window(self) -> None:
        """A long delivery ETA must not pull the cutoff back.

        The regression that produced "delivery until 8:30 PM" for a branch whose
        window runs to 9:30.
        """

        near = FakeLocation(prep=20, delivery_eta=10, pickup_eta=10)
        far = FakeLocation(prep=20, delivery_eta=45, pickup_eta=45)
        self.assertEqual(
            _get_prep_buffer_minutes(near, OrderFulfillmentType.DELIVERY),
            _get_prep_buffer_minutes(far, OrderFulfillmentType.DELIVERY),
        )

    def test_no_prep_time_recorded_falls_back_to_the_eta(self) -> None:
        """`preparation_time_minutes` is NULL on five of eight stored rows.

        Falling back to zero would let those branches accept an order at the
        closing minute with nothing left to cook it. The fallback is protection,
        not a claim that travel counts.
        """

        location = FakeLocation(prep=None, delivery_eta=29, pickup_eta=19)
        self.assertEqual(
            _get_prep_buffer_minutes(location, OrderFulfillmentType.DELIVERY),
            29,
        )

    def test_a_zero_prep_time_is_treated_as_unset(self) -> None:
        """Zero and NULL both mean "nobody told us", and neither should remove
        the guard entirely."""

        location = FakeLocation(prep=0, delivery_eta=29, pickup_eta=19)
        self.assertEqual(
            _get_prep_buffer_minutes(location, OrderFulfillmentType.DELIVERY),
            29,
        )


if __name__ == "__main__":
    unittest.main()
