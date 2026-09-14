"""How long the kitchen needs before the window shuts.

`_get_prep_buffer_minutes` returned `max(preparation_time_minutes, eta)`, so
prep time only mattered when it exceeded the ETA. It never did: measured across
all 18 branches, prep runs 15-18 minutes and the delivery ETA 21-33, so
`preparation_time_minutes` affected nothing anywhere in the product. An owner
raising it to 25 would have seen no change at all.

They are now summed. The decision is that the ETA is travel time, not
cook-plus-travel — so a branch needing 17 minutes to cook and 29 to deliver
cannot accept an order 30 minutes before it shuts.

Concretely, for Bangkok Bowl Bodakdev with a delivery window ending 21:30:

    before   buffer 29   last order 21:01
    after    buffer 46   last order 20:44

The buffer feeds three things, so this moves all of them together: the ASAP
cutoff, the minimum lead time on a scheduled order, and which slots the picker
offers at all.
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
    def test_prep_and_travel_are_added(self) -> None:
        location = FakeLocation(prep=17, delivery_eta=29, pickup_eta=19)
        self.assertEqual(
            _get_prep_buffer_minutes(location, OrderFulfillmentType.DELIVERY),
            46,
        )

    def test_pickup_adds_its_own_eta(self) -> None:
        """Pickup still has a wait — the customer travels, not the food."""

        location = FakeLocation(prep=17, delivery_eta=29, pickup_eta=19)
        self.assertEqual(
            _get_prep_buffer_minutes(location, OrderFulfillmentType.PICKUP),
            36,
        )

    def test_no_prep_time_recorded_leaves_the_eta_alone(self) -> None:
        """`preparation_time_minutes` is nullable and NULL on most rows — five
        of eight when this was written. A branch that never set one must behave
        exactly as it did before, not lose its buffer."""

        location = FakeLocation(prep=None, delivery_eta=29, pickup_eta=19)
        self.assertEqual(
            _get_prep_buffer_minutes(location, OrderFulfillmentType.DELIVERY),
            29,
        )

    def test_the_old_max_behaviour_is_gone(self) -> None:
        """The regression this file exists to prevent.

        Under `max()` these two produced 29. Summing is the whole change, and a
        revert would show up here rather than as an order the kitchen cannot
        cook.
        """

        location = FakeLocation(prep=17, delivery_eta=29, pickup_eta=19)
        self.assertNotEqual(
            _get_prep_buffer_minutes(location, OrderFulfillmentType.DELIVERY),
            29,
        )


if __name__ == "__main__":
    unittest.main()
