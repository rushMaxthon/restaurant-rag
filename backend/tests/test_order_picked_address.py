"""An order is priced from the building the customer chose, not the line typed.

`DeliveryQuoteRequest` has carried `latitude`/`longitude` since the
autocomplete was built, and argues there that accepting them is "strictly
better than geocoding the text underneath — which would be a second paid call
to get a worse answer".

`OrderCreateRequest` did not carry them. The storefront's checkout sent them
anyway and pydantic dropped them, silently, because an unknown field is
ignored rather than rejected. So:

- the quote the customer was SHOWN was priced from the rooftop they picked
- the order they PLACED was priced by re-geocoding the typed line

Those are two different points and two potentially different numbers for one
address. The live log shows the second half of it on nearly every attempt:

    Address only resolved to LOCALITY (Jahangir Pura, Surat, Gujarat, India);
    pricing from it but not trusting it

A customer seeing one delivery charge and being charged another is the exact
failure the half-and-half rules are written in three places to prevent. It
also sends the rider to a neighbourhood rather than a door.

The second half of this change is a refusal: a delivery order from a checkout
that carries no coordinates never had an address picked, so there is nothing
to price accurately and nothing to drive to. It is refused rather than
quietly priced from a locality.

That refusal is scoped to clients that can actually offer a picker. The
WhatsApp agent and the mobile app collect an address as text and have no
dropdown; `require_payment_validation` is already how `create_order`
distinguishes a checkout the customer is standing in front of from those
paths, so it is what gates this too.
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.schemas.order import DeliveryQuoteRequest, OrderCreateRequest  # noqa: E402


class TheOrderAcceptsThePointTheQuoteWasGiven(unittest.TestCase):
    def test_order_creation_accepts_coordinates(self) -> None:
        # The bug: it did not, so every pair the checkout sent was dropped.
        self.assertIn("latitude", OrderCreateRequest.model_fields)
        self.assertIn("longitude", OrderCreateRequest.model_fields)

    def test_the_two_requests_agree_on_the_bounds(self) -> None:
        # If one accepted a coordinate the other refused, the quote and the
        # order could still be priced from different points — which is the
        # whole failure, rebuilt out of validators instead of missing fields.
        for name in ("latitude", "longitude"):
            with self.subTest(field=name):
                order = OrderCreateRequest.model_fields[name]
                quote = DeliveryQuoteRequest.model_fields[name]
                self.assertEqual(
                    [str(m) for m in order.metadata],
                    [str(m) for m in quote.metadata],
                )

    def test_a_coordinate_outside_the_world_is_refused(self) -> None:
        # They arrive from a client. The bounds are what stop a malformed pair
        # reaching the courier as a real request.
        for lat, lng in ((91.0, 72.8), (-91.0, 72.8), (21.2, 181.0), (21.2, -181.0)):
            with self.subTest(lat=lat, lng=lng):
                with self.assertRaises(Exception):
                    OrderCreateRequest(
                        restaurant_id="00000000-0000-0000-0000-000000000001",
                        items=[{"menu_item_id": "00000000-0000-0000-0000-000000000002", "quantity": 1}],
                        delivery_address="Somewhere in Surat",
                        latitude=lat,
                        longitude=lng,
                    )

    def test_coordinates_remain_optional_on_the_schema(self) -> None:
        # The REFUSAL lives in create_order, not here, because it depends on
        # which client is calling. A required field would break the WhatsApp
        # agent and the mobile app, neither of which has a picker.
        self.assertFalse(OrderCreateRequest.model_fields["latitude"].is_required())
        self.assertFalse(OrderCreateRequest.model_fields["longitude"].is_required())


class TheRulesAreInTheSource(unittest.TestCase):
    def setUp(self) -> None:
        from pathlib import Path

        self.source = (
            Path(__file__).resolve().parents[1] / "app" / "services" / "orders.py"
        ).read_text(encoding="utf-8")

    def test_the_picked_point_is_passed_to_the_courier(self) -> None:
        # Accepting the field and then not using it would be the same bug with
        # an extra step.
        self.assertIn("known_drop=known_drop", self.source)
        self.assertIn("GeocodeConfidence.ROOFTOP.value", self.source)

    def test_the_picked_point_is_kept_on_the_order(self) -> None:
        # Priced from it and then dropped: the courier was sent the text alone
        # and geocoded it itself. The order now keeps the point it was priced
        # from, which is what `delivery.build_request` sends the rider to.
        self.assertIn("delivery_latitude=draft.drop_point[0] if draft.drop_point else None", self.source)
        self.assertIn("drop_point=", self.source)

    def test_a_typed_address_is_refused_at_a_checkout(self) -> None:
        # Written as a check on `known_drop` rather than an `elif` on the
        # coordinates, because a coordinate is no longer the only way to be
        # located: an address chosen from the customer's own saved list
        # carries one on its row. This used to read
        # `elif require_payment_validation:`, hanging off the coordinate test,
        # and so refused a saved address the customer had plainly chosen —
        # "Please choose your address from the suggestions", shown to somebody
        # who had. See test_saved_address_is_saved_once.
        #
        # The rule being guarded is unchanged and slightly stronger: a
        # checkout that produced no point at all, by any route, is refused.
        self.assertIn("if known_drop is None and require_payment_validation:", self.source)
        self.assertIn("choose your address from the suggestions", self.source)

    def test_a_saved_address_is_a_located_address(self) -> None:
        # The other route to a point, and the reason the refusal above had to
        # move. The quote endpoint has read it since the autocomplete was
        # built; the order path did not, so the two disagreed about the same
        # address.
        self.assertIn("payload.saved_address_id", self.source)
        self.assertIn("saved.user_id == customer.id", self.source)

    def test_an_unpriced_delivery_is_still_refused(self) -> None:
        # The companion rule from test_delivery_fee_required. Both must hold:
        # a picked address with no quote and no flat fee is still no price.
        self.assertIn("elif delivery_fee <= 0:", self.source)


if __name__ == "__main__":
    unittest.main()
