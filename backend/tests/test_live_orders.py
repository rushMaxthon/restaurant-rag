"""The live orders board: everything in flight, and what went out today.

`GET /orders/live` is one request for the screen an operator keeps open. The
platform's admin sees every restaurant on it; an owner sees their own. What is
pinned here is the part that is easy to get quietly wrong.

**It is the order list, asked five times, not a second set of scope rules.**
Each stage is `list_orders` with a status, so the board can never show a row
the Orders page would not. A second query written for this screen would be a
second place for "which restaurant may this account see" to live.

**Done is "delivered since", from the event log.** `orders` has no completion
column and `updated_at` moves on a later refund, so the delivered stage asks
with `completed_from` — and the caller supplies the instant, because "today"
is the operator's midnight and the server does not know their timezone.

**A stage reports its true total beside a capped list.** On a busy night the
platform has more open orders than a screen should load. The count on a
column's header is the count, not the number of cards that came back.

**The courier is read once for the whole board.** One query for every order
on it. A card per order calling `/orders/{id}/delivery` is forty requests on
every refresh, and the board refreshes whenever any order moves.
"""

from __future__ import annotations

import sys
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.main import app  # noqa: E402 - imported first to settle import order
from app.models.enums import OrderStatus  # noqa: E402
from app.services import live_orders  # noqa: E402

SINCE = datetime(2026, 10, 5, 0, 0, tzinfo=timezone.utc)
NOW = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)


def an_order(status: OrderStatus):
    """Only what `build_live_board` touches; the real response has forty fields."""
    return SimpleNamespace(id=uuid.uuid4(), status=status)


def a_delivery(order_id, **over):
    fields = dict(
        order_id=order_id,
        provider="pidge",
        provider_order_id="P-1",
        state="ASSIGNED",
        provider_status="RIDER_ASSIGNED",
        rider_name="Ramesh",
        rider_mobile="9000000000",
        tracking_url="https://track.example/abc",
        distance_metres=2100.0,
        picked_up_at=None,
        delivered_at=None,
        last_error="",
        created_at=NOW,
        updated_at=NOW,
    )
    fields.update(over)
    return SimpleNamespace(**fields)


class TheBoardTests(unittest.TestCase):
    def build(self, by_status, deliveries=(), totals=None, loads=()):
        """Run the board with `list_orders` and the delivery read stubbed.

        The response models are stood in for as well: the rows here carry two
        fields, not the forty a real order does, and what is under test is
        which questions get asked and what is attached to what.
        """
        calls = []
        self.count_calls = []

        def fake_counts(db, user, **kwargs):
            self.count_calls.append(kwargs)
            return list(loads)

        def fake_list_orders(db, user, **kwargs):
            calls.append(kwargs)
            status = kwargs["status_filter"]
            rows = list(by_status.get(status, []))
            total = (totals or {}).get(status, len(rows))
            return rows, total

        db = mock.Mock()
        db.scalars.return_value.all.return_value = list(deliveries)
        with mock.patch.object(live_orders, "list_orders", side_effect=fake_list_orders),                 mock.patch.object(live_orders, "count_live_orders_by_restaurant", side_effect=fake_counts), \
                mock.patch.object(live_orders, "_as_card", side_effect=lambda order, delivery, viewer=None: SimpleNamespace(order=order, delivery=delivery)),                 mock.patch.object(live_orders, "LiveOrdersStage", side_effect=lambda **fields: SimpleNamespace(**fields)),                 mock.patch.object(live_orders, "LiveOrdersResponse", side_effect=lambda **fields: SimpleNamespace(**fields)):
            board = live_orders.build_live_board(
                db,
                mock.Mock(),
                owner_restaurant_id=None,
                restaurant_id=None,
                restaurant_location_id=None,
                app_scope_restaurant_id=None,
                completed_from=SINCE,
            )
        return board, calls, db

    def test_every_stage_is_asked_for_and_in_the_order_food_moves(self) -> None:
        board, calls, _ = self.build({})
        self.assertEqual(
            [stage.status for stage in board.stages],
            [
                OrderStatus.PLACED,
                OrderStatus.ACCEPTED,
                OrderStatus.PREPARING,
                OrderStatus.OUT_FOR_DELIVERY,
                OrderStatus.DELIVERED,
            ],
        )
        self.assertEqual([c["status_filter"] for c in calls], [s.status for s in board.stages])

    def test_an_unpaid_or_cancelled_order_is_not_on_the_board(self) -> None:
        # PAYMENT_PENDING is a checkout somebody may still abandon, and
        # CANCELLED is nothing to do. Neither is work.
        _, calls, _ = self.build({})
        asked = {c["status_filter"] for c in calls}
        self.assertNotIn(OrderStatus.PAYMENT_PENDING, asked)
        self.assertNotIn(OrderStatus.CANCELLED, asked)

    def test_open_orders_are_newest_first_and_have_no_date_window(self) -> None:
        # Newest, because the list is capped: with 208 orders nobody will ever
        # accept sitting at PLACED, oldest-first sent a hundred of those and
        # left tonight's order off the board. An order still open from
        # yesterday is still open, so there is no date window either.
        _, calls, _ = self.build({})
        for call in calls[:4]:
            with self.subTest(status=call["status_filter"]):
                self.assertEqual(call["sort"], "placed_at:desc")
                self.assertIsNone(call["completed_from"])

    def test_done_is_delivered_since_the_callers_midnight_newest_first(self) -> None:
        _, calls, _ = self.build({})
        done = calls[4]
        self.assertEqual(done["completed_from"], SINCE)
        self.assertEqual(done["sort"], "completed_at:desc")

    def test_the_scope_it_was_given_reaches_every_stage_untouched(self) -> None:
        owner, branch = uuid.uuid4(), uuid.uuid4()
        calls = []

        def fake(db, user, **kwargs):
            calls.append(kwargs)
            return [], 0

        counted = []

        def fake_counts(db, user, **kwargs):
            counted.append(kwargs)
            return []

        with mock.patch.object(live_orders, "list_orders", side_effect=fake),                 mock.patch.object(live_orders, "count_live_orders_by_restaurant", side_effect=fake_counts):
            live_orders.build_live_board(
                mock.Mock(),
                mock.Mock(),
                owner_restaurant_id=owner,
                restaurant_id=None,
                restaurant_location_id=branch,
                app_scope_restaurant_id=None,
                completed_from=SINCE,
            )
        self.assertEqual(len(calls), 5)
        # The per-restaurant count is a sixth reader, and gets the same scope.
        self.assertEqual(len(counted), 1)
        for call in calls + counted:
            self.assertEqual(call["owner_restaurant_id"], owner)
            self.assertEqual(call["restaurant_location_id"], branch)

    def test_a_stage_keeps_its_true_total_beside_a_capped_list(self) -> None:
        rows = [an_order(OrderStatus.PLACED) for _ in range(3)]
        board, calls, _ = self.build(
            {OrderStatus.PLACED: rows}, totals={OrderStatus.PLACED: 240}
        )
        placed = board.stages[0]
        self.assertEqual(placed.total, 240)
        self.assertEqual(len(placed.orders), 3)
        self.assertEqual(calls[0]["limit"], live_orders.STAGE_LIMIT)

    def test_each_order_carries_its_own_courier_and_the_rest_carry_none(self) -> None:
        with_rider = an_order(OrderStatus.OUT_FOR_DELIVERY)
        pickup = an_order(OrderStatus.PREPARING)
        board, _, db = self.build(
            {
                OrderStatus.OUT_FOR_DELIVERY: [with_rider],
                OrderStatus.PREPARING: [pickup],
            },
            deliveries=[a_delivery(with_rider.id)],
        )
        cards = {card.order.id: card for stage in board.stages for card in stage.orders}
        self.assertEqual(cards[with_rider.id].delivery.tracking_url, "https://track.example/abc")
        self.assertIsNone(cards[pickup.id].delivery)
        # One read for the whole board, not one per card.
        self.assertEqual(db.scalars.call_count, 1)

    def test_an_empty_board_asks_the_courier_table_nothing(self) -> None:
        _, _, db = self.build({})
        db.scalars.assert_not_called()

    def test_who_has_what_is_the_databases_count_not_the_cards(self) -> None:
        # 213 new orders, 100 cards sent. The restaurant's figure is 213.
        bakery, wok = uuid.uuid4(), uuid.uuid4()
        board, _, _ = self.build(
            {OrderStatus.PLACED: [an_order(OrderStatus.PLACED)]},
            totals={OrderStatus.PLACED: 213},
            loads=[
                (bakery, "Bhagwati Bakery", "Surat", OrderStatus.PLACED, 213, 208),
                (bakery, "Bhagwati Bakery", "Surat", OrderStatus.DELIVERED, 4, 4),
                (wok, "Dragon Wok", "Surat", OrderStatus.PREPARING, 2, 0),
            ],
        )
        by_id = {load.restaurant_id: load for load in board.restaurants}
        self.assertEqual(
            by_id[bakery].counts, {OrderStatus.PLACED: 213, OrderStatus.DELIVERED: 4}
        )
        self.assertEqual(by_id[bakery].name, "Bhagwati Bakery")
        self.assertEqual(by_id[wok].counts, {OrderStatus.PREPARING: 2})
        # Backlog is counted apart, and a delivered order is never backlog.
        self.assertEqual(by_id[bakery].stale, {OrderStatus.PLACED: 208})
        self.assertEqual(by_id[wok].stale, {})
        self.assertEqual(board.stages[0].stale_total, 208)
        self.assertEqual(board.stages[4].stale_total, 0)

    def test_picking_a_restaurant_narrows_the_cards_and_not_the_picker(self) -> None:
        # An admin chose one restaurant. The columns are that restaurant's; the
        # strip they chose it from still lists everybody, or choosing one
        # would empty the list it was chosen from.
        picked = uuid.uuid4()
        calls, counted = [], []

        def fake(db, user, **kwargs):
            calls.append(kwargs)
            return [], 0

        def fake_counts(db, user, **kwargs):
            counted.append(kwargs)
            return []

        with mock.patch.object(live_orders, "list_orders", side_effect=fake),                 mock.patch.object(live_orders, "count_live_orders_by_restaurant", side_effect=fake_counts):
            live_orders.build_live_board(
                mock.Mock(),
                mock.Mock(),
                owner_restaurant_id=None,
                restaurant_id=picked,
                restaurant_location_id=None,
                app_scope_restaurant_id=None,
                completed_from=SINCE,
            )
        self.assertTrue(all(call["restaurant_id"] == picked for call in calls))
        self.assertIsNone(counted[0]["restaurant_id"])

    def test_a_picked_restaurants_columns_carry_only_its_own_backlog(self) -> None:
        # The strip lists everybody; the columns are the picked restaurant's,
        # so the backlog figure on them must be too.
        picked, other = uuid.uuid4(), uuid.uuid4()
        rows = [
            (picked, "Bhagwati Bakery", "Surat", OrderStatus.PLACED, 4, 3),
            (other, "Bangkok Bowl", "Bangkok", OrderStatus.PLACED, 208, 205),
        ]
        with mock.patch.object(live_orders, "list_orders", return_value=([], 4)),                 mock.patch.object(live_orders, "count_live_orders_by_restaurant", return_value=rows):
            board = live_orders.build_live_board(
                mock.Mock(),
                mock.Mock(),
                owner_restaurant_id=None,
                restaurant_id=picked,
                restaurant_location_id=None,
                app_scope_restaurant_id=None,
                completed_from=SINCE,
            )
        self.assertEqual(board.stages[0].stale_total, 3)
        self.assertEqual(len(board.restaurants), 2)
        self.assertEqual(board.stale_after_minutes, 24 * 60)

    def test_the_count_covers_the_same_statuses_and_the_same_day(self) -> None:
        self.build({})
        (call,) = self.count_calls
        self.assertEqual(call["open_statuses"], live_orders.OPEN_STATUSES)
        self.assertEqual(call["completed_from"], SINCE)
        # The backlog line is a day back from now, whatever the caller's midnight.
        age = datetime.now(timezone.utc) - call["stale_before"]
        self.assertAlmostEqual(age.total_seconds(), 24 * 3600, delta=60)


class TheRouteTests(unittest.TestCase):
    def test_live_is_not_swallowed_by_the_order_id_route(self) -> None:
        # `/orders/{order_id}` is declared in the same router. Registered
        # first, it would read "live" as an id and answer 422.
        paths = [route.path for route in app.routes if getattr(route, "path", "").startswith("/api/orders")]
        self.assertIn("/api/orders/live", paths)
        self.assertLess(paths.index("/api/orders/live"), paths.index("/api/orders/{order_id}"))

    def test_a_customer_is_refused(self) -> None:
        from fastapi import HTTPException

        from app.api import orders as orders_api
        from app.models.enums import UserRole

        with self.assertRaises(HTTPException) as refused:
            orders_api.get_live_orders(
                db=mock.Mock(),
                current_user=SimpleNamespace(role=UserRole.CUSTOMER),
                app_scope=mock.Mock(),
                restaurant_id=None,
                restaurant_location_id=None,
                completed_from=None,
            )
        self.assertEqual(refused.exception.status_code, 403)


if __name__ == "__main__":
    unittest.main()
