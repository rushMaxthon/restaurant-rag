from __future__ import annotations

import sys
import unittest
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models.enums import GeneratedComboLifecycleStatus, OrderStatus, PaymentStatus
from app.models.generated_combo import GeneratedCombo
from app.services import generated_combos as generated_combo_service
from app.services.generated_combos import (
    _calculate_confidence_score,
    _combo_signature,
    _counted_order_statuses,
    _counted_payment_statuses,
    _is_combo_stale,
    _is_draft_combo_expired,
    _remaining_unique_users_to_publish,
    _suggested_price,
    list_generated_combos,
    rebuild_generated_combos,
    set_generated_combo_status,
)


class ScalarResultStub:
    def __init__(self, items: list[object]) -> None:
        self._items = list(items)

    def all(self) -> list[object]:
        return list(self._items)


class FakeSession:
    def __init__(self, scalar_results: list[list[object]]) -> None:
        self._scalar_results = [ScalarResultStub(items) for items in scalar_results]
        self.added: list[object] = []
        self.commit_count = 0

    def scalars(self, _query: object) -> ScalarResultStub:
        if not self._scalar_results:
            raise AssertionError("Unexpected db.scalars() call")
        return self._scalar_results.pop(0)

    def scalar(self, _query: object) -> object | None:
        if not self._scalar_results:
            raise AssertionError("Unexpected db.scalar() call")
        items = self._scalar_results.pop(0).all()
        return items[0] if items else None

    def add(self, obj: object) -> None:
        if obj not in self.added:
            self.added.append(obj)

    def commit(self) -> None:
        self.commit_count += 1

    def flush(self) -> None:
        return None


def make_restaurant(*, restaurant_id: uuid.UUID) -> SimpleNamespace:
    return SimpleNamespace(
        id=restaurant_id,
        name="Bangkok Bowl",
        is_active=True,
        is_approved=True,
    )


def make_menu_item(
    *,
    menu_item_id: uuid.UUID,
    restaurant_id: uuid.UUID,
    location_id: uuid.UUID,
    name: str,
    price: str,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=menu_item_id,
        restaurant_id=restaurant_id,
        restaurant_location_id=location_id,
        name=name,
        price=Decimal(price),
        is_available=True,
    )


def make_order(
    *,
    restaurant_id: uuid.UUID,
    location_id: uuid.UUID,
    customer_id: uuid.UUID,
    placed_at: datetime,
    item_ids: list[uuid.UUID],
    payment_status: PaymentStatus = PaymentStatus.PAID,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        restaurant_id=restaurant_id,
        restaurant_location_id=location_id,
        customer_id=customer_id,
        placed_at=placed_at,
        status=OrderStatus.DELIVERED,
        payment_status=payment_status,
        items=[SimpleNamespace(menu_item_id=item_id) for item_id in item_ids],
    )


def make_existing_combo(
    *,
    restaurant_id: uuid.UUID,
    location_id: uuid.UUID,
    item_ids: tuple[uuid.UUID, ...],
    created_at: datetime,
    last_seen_at: datetime,
    status: GeneratedComboLifecycleStatus,
    unique_user_count: int,
    is_active: bool | None = None,
    is_customer_visible: bool | None = None,
) -> GeneratedCombo:
    combo = GeneratedCombo(
        id=uuid.uuid4(),
        restaurant_id=restaurant_id,
        restaurant_location_id=location_id,
        signature=_combo_signature(restaurant_id, location_id, item_ids),
        combo_name="Existing Combo",
        description="Existing description",
        order_count=3,
        unique_user_count=unique_user_count,
        confidence_score=Decimal("0.00"),
        status=status.value,
        manual_status_override=None,
        is_customer_visible=is_customer_visible if is_customer_visible is not None else status == GeneratedComboLifecycleStatus.LIVE,
        original_total_price=Decimal("100.00"),
        suggested_combo_price=Decimal("93.00"),
        is_active=is_active if is_active is not None else status != GeneratedComboLifecycleStatus.ARCHIVED,
        generated_from_orders=True,
        last_seen_at=last_seen_at,
        created_at=created_at,
        updated_at=last_seen_at,
    )
    combo.combo_items = []
    return combo


def build_rebuild_session(
    *,
    orders: list[object],
    menu_items: list[object],
    restaurants: list[object],
    existing_combos: list[GeneratedCombo],
) -> FakeSession:
    return FakeSession([orders, menu_items, restaurants, existing_combos])


def latest_combo_from_session(db: FakeSession) -> GeneratedCombo:
    combos = [entry for entry in db.added if isinstance(entry, GeneratedCombo)]
    if not combos:
        raise AssertionError("Expected a generated combo to be added")
    return combos[-1]


class GeneratedComboLifecycleTests(unittest.TestCase):
    def test_counted_order_statuses_ignore_unknown_values(self) -> None:
        with patch.object(
            generated_combo_service.settings,
            "generated_combo_counted_statuses",
            "DELIVERED,COMPLETED,CANCELLED",
        ):
            self.assertEqual(_counted_order_statuses(), (OrderStatus.DELIVERED,))

    def test_counted_payment_statuses_include_cod_and_ignore_unknown_values(self) -> None:
        with patch.object(
            generated_combo_service.settings,
            "generated_combo_counted_payment_statuses",
            "PAID,COD,REFUND_PENDING",
        ):
            self.assertEqual(_counted_payment_statuses(), (PaymentStatus.PAID, PaymentStatus.COD))

    def test_confidence_score_rewards_multi_user_adoption(self) -> None:
        now = datetime(2026, 6, 18, tzinfo=UTC)
        score = _calculate_confidence_score(4, 3, now - timedelta(days=2), now=now)
        self.assertEqual(score, Decimal("12.00"))

    def test_discount_boost_requires_visible_unique_user_threshold(self) -> None:
        original_total = Decimal("100.00")
        with patch.object(generated_combo_service.settings, "generated_combo_min_visible_unique_users", 3):
            boosted = _suggested_price(original_total, Decimal("11.00"), 3)
            not_boosted = _suggested_price(original_total, Decimal("11.00"), 1)
        self.assertEqual(boosted, Decimal("91.00"))
        self.assertEqual(not_boosted, Decimal("93.00"))

    def test_expiry_helpers_cover_draft_and_live_rules(self) -> None:
        now = datetime(2026, 6, 18, tzinfo=UTC)
        with (
            patch.object(generated_combo_service.settings, "generated_combo_expiry_days", 90),
            patch.object(generated_combo_service.settings, "generated_combo_draft_expiry_days", 30),
        ):
            self.assertTrue(_is_combo_stale(now - timedelta(days=91), now=now))
            self.assertFalse(_is_combo_stale(now - timedelta(days=45), now=now))
            self.assertTrue(_is_draft_combo_expired(now - timedelta(days=31), now=now))
            self.assertFalse(_is_draft_combo_expired(now - timedelta(days=10), now=now))

    def test_single_user_repeated_orders_create_draft_combo(self) -> None:
        restaurant_id = uuid.uuid4()
        location_id = uuid.uuid4()
        item_a = uuid.uuid4()
        item_b = uuid.uuid4()
        now = datetime(2026, 6, 18, tzinfo=UTC)
        customer_id = uuid.uuid4()
        orders = [
            make_order(
                restaurant_id=restaurant_id,
                location_id=location_id,
                customer_id=customer_id,
                placed_at=now - timedelta(days=offset + 1),
                item_ids=[item_a, item_b],
            )
            for offset in range(6)
        ]
        menu_items = [
            make_menu_item(menu_item_id=item_a, restaurant_id=restaurant_id, location_id=location_id, name="Pad Thai Veg", price="60.00"),
            make_menu_item(menu_item_id=item_b, restaurant_id=restaurant_id, location_id=location_id, name="Thai Iced Tea", price="40.00"),
        ]
        db = build_rebuild_session(
            orders=orders,
            menu_items=menu_items,
            restaurants=[make_restaurant(restaurant_id=restaurant_id)],
            existing_combos=[],
        )

        with patch("app.services.generated_combos._invalidate_combo_related_caches"):
            result = rebuild_generated_combos(db, lookback_days=120)

        combo = latest_combo_from_session(db)
        self.assertEqual(result.created_count, 1)
        self.assertEqual(combo.status, GeneratedComboLifecycleStatus.DRAFT.value)
        self.assertFalse(combo.is_customer_visible)
        self.assertTrue(combo.is_active)
        self.assertEqual(combo.unique_user_count, 1)
        self.assertEqual(_remaining_unique_users_to_publish(combo.unique_user_count), 2)

    def test_draft_combos_are_hidden_from_customers_but_visible_to_admin(self) -> None:
        restaurant_id = uuid.uuid4()
        location_id = uuid.uuid4()
        now = datetime(2026, 6, 18, tzinfo=UTC)
        combo = make_existing_combo(
            restaurant_id=restaurant_id,
            location_id=location_id,
            item_ids=(uuid.uuid4(), uuid.uuid4()),
            created_at=now - timedelta(days=5),
            last_seen_at=now - timedelta(days=1),
            status=GeneratedComboLifecycleStatus.DRAFT,
            unique_user_count=1,
        )
        combo.__dict__["restaurant"] = SimpleNamespace(name="Bangkok Bowl")
        combo.__dict__["restaurant_location"] = SimpleNamespace(branch_name="Ellisbridge")
        combo.__dict__["combo_items"] = []

        customer_db = FakeSession([[combo]])
        admin_db = FakeSession([[combo]])

        customer_rows = list_generated_combos(customer_db, limit=12)
        admin_rows = list_generated_combos(admin_db, limit=12, active_only=False, customer_visible_only=False)

        self.assertEqual(customer_rows, [])
        self.assertEqual(len(admin_rows), 1)
        self.assertEqual(admin_rows[0].status, GeneratedComboLifecycleStatus.DRAFT.value)
        self.assertEqual(admin_rows[0].remaining_unique_users_to_publish, 2)

    def test_draft_combo_becomes_live_once_threshold_is_reached(self) -> None:
        restaurant_id = uuid.uuid4()
        location_id = uuid.uuid4()
        item_a = uuid.uuid4()
        item_b = uuid.uuid4()
        now = datetime(2026, 6, 18, tzinfo=UTC)
        created_at = now - timedelta(days=7)
        existing_combo = make_existing_combo(
            restaurant_id=restaurant_id,
            location_id=location_id,
            item_ids=(item_a, item_b),
            created_at=created_at,
            last_seen_at=now - timedelta(days=6),
            status=GeneratedComboLifecycleStatus.DRAFT,
            unique_user_count=1,
        )
        orders = [
            make_order(
                restaurant_id=restaurant_id,
                location_id=location_id,
                customer_id=uuid.uuid4(),
                placed_at=now - timedelta(days=index + 1),
                item_ids=[item_a, item_b],
            )
            for index in range(3)
        ]
        menu_items = [
            make_menu_item(menu_item_id=item_a, restaurant_id=restaurant_id, location_id=location_id, name="Pad Thai Veg", price="60.00"),
            make_menu_item(menu_item_id=item_b, restaurant_id=restaurant_id, location_id=location_id, name="Thai Iced Tea", price="40.00"),
        ]
        db = build_rebuild_session(
            orders=orders,
            menu_items=menu_items,
            restaurants=[make_restaurant(restaurant_id=restaurant_id)],
            existing_combos=[existing_combo],
        )

        with patch("app.services.generated_combos._invalidate_combo_related_caches"):
            result = rebuild_generated_combos(db, lookback_days=120)

        self.assertEqual(result.created_count, 0)
        self.assertEqual(result.updated_count, 1)
        self.assertEqual(existing_combo.status, GeneratedComboLifecycleStatus.LIVE.value)
        self.assertTrue(existing_combo.is_customer_visible)
        self.assertTrue(existing_combo.is_active)

    def test_live_combos_appear_to_customers(self) -> None:
        restaurant_id = uuid.uuid4()
        location_id = uuid.uuid4()
        now = datetime(2026, 6, 18, tzinfo=UTC)
        combo = make_existing_combo(
            restaurant_id=restaurant_id,
            location_id=location_id,
            item_ids=(uuid.uuid4(), uuid.uuid4()),
            created_at=now - timedelta(days=5),
            last_seen_at=now - timedelta(days=1),
            status=GeneratedComboLifecycleStatus.LIVE,
            unique_user_count=3,
        )
        combo.__dict__["restaurant"] = SimpleNamespace(name="Bangkok Bowl")
        combo.__dict__["restaurant_location"] = SimpleNamespace(branch_name="Ellisbridge")
        combo.__dict__["combo_items"] = []

        customer_db = FakeSession([[combo]])
        rows = list_generated_combos(customer_db, limit=12)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].status, GeneratedComboLifecycleStatus.LIVE.value)
        self.assertTrue(rows[0].is_customer_visible)

    def test_draft_combo_archives_after_draft_expiry(self) -> None:
        restaurant_id = uuid.uuid4()
        location_id = uuid.uuid4()
        item_a = uuid.uuid4()
        item_b = uuid.uuid4()
        now = datetime(2026, 6, 18, tzinfo=UTC)
        created_at = now - timedelta(days=40)
        existing_combo = make_existing_combo(
            restaurant_id=restaurant_id,
            location_id=location_id,
            item_ids=(item_a, item_b),
            created_at=created_at,
            last_seen_at=now - timedelta(days=1),
            status=GeneratedComboLifecycleStatus.DRAFT,
            unique_user_count=1,
        )
        customer_id = uuid.uuid4()
        orders = [
            make_order(
                restaurant_id=restaurant_id,
                location_id=location_id,
                customer_id=customer_id,
                placed_at=now - timedelta(days=index + 1),
                item_ids=[item_a, item_b],
            )
            for index in range(6)
        ]
        menu_items = [
            make_menu_item(menu_item_id=item_a, restaurant_id=restaurant_id, location_id=location_id, name="Pad Thai Veg", price="60.00"),
            make_menu_item(menu_item_id=item_b, restaurant_id=restaurant_id, location_id=location_id, name="Thai Iced Tea", price="40.00"),
        ]
        db = build_rebuild_session(
            orders=orders,
            menu_items=menu_items,
            restaurants=[make_restaurant(restaurant_id=restaurant_id)],
            existing_combos=[existing_combo],
        )

        with (
            patch.object(generated_combo_service.settings, "generated_combo_draft_expiry_days", 30),
            patch("app.services.generated_combos._invalidate_combo_related_caches"),
        ):
            rebuild_generated_combos(db, lookback_days=120)

        self.assertEqual(existing_combo.status, GeneratedComboLifecycleStatus.ARCHIVED.value)
        self.assertFalse(existing_combo.is_active)
        self.assertFalse(existing_combo.is_customer_visible)

    def test_live_combo_archives_after_inactivity_expiry(self) -> None:
        restaurant_id = uuid.uuid4()
        location_id = uuid.uuid4()
        item_a = uuid.uuid4()
        item_b = uuid.uuid4()
        now = datetime(2026, 6, 18, tzinfo=UTC)
        created_at = now - timedelta(days=120)
        existing_combo = make_existing_combo(
            restaurant_id=restaurant_id,
            location_id=location_id,
            item_ids=(item_a, item_b),
            created_at=created_at,
            last_seen_at=now - timedelta(days=95),
            status=GeneratedComboLifecycleStatus.LIVE,
            unique_user_count=3,
        )
        orders = [
            make_order(
                restaurant_id=restaurant_id,
                location_id=location_id,
                customer_id=uuid.UUID(int=index + 1),
                placed_at=now - timedelta(days=95),
                item_ids=[item_a, item_b],
            )
            for index in range(3)
        ]
        menu_items = [
            make_menu_item(menu_item_id=item_a, restaurant_id=restaurant_id, location_id=location_id, name="Pad Thai Veg", price="60.00"),
            make_menu_item(menu_item_id=item_b, restaurant_id=restaurant_id, location_id=location_id, name="Thai Iced Tea", price="40.00"),
        ]
        db = build_rebuild_session(
            orders=orders,
            menu_items=menu_items,
            restaurants=[make_restaurant(restaurant_id=restaurant_id)],
            existing_combos=[existing_combo],
        )

        with (
            patch.object(generated_combo_service.settings, "generated_combo_expiry_days", 90),
            patch("app.services.generated_combos._invalidate_combo_related_caches"),
        ):
            rebuild_generated_combos(db, lookback_days=120)

        self.assertEqual(existing_combo.status, GeneratedComboLifecycleStatus.ARCHIVED.value)
        self.assertFalse(existing_combo.is_active)
        self.assertFalse(existing_combo.is_customer_visible)

    def test_rebuild_status_transition_and_upsert_prevent_duplicates(self) -> None:
        restaurant_id = uuid.uuid4()
        location_id = uuid.uuid4()
        item_a = uuid.uuid4()
        item_b = uuid.uuid4()
        now = datetime(2026, 6, 18, tzinfo=UTC)
        existing_combo = make_existing_combo(
            restaurant_id=restaurant_id,
            location_id=location_id,
            item_ids=(item_a, item_b),
            created_at=now - timedelta(days=8),
            last_seen_at=now - timedelta(days=7),
            status=GeneratedComboLifecycleStatus.DRAFT,
            unique_user_count=1,
        )
        orders = [
            make_order(
                restaurant_id=restaurant_id,
                location_id=location_id,
                customer_id=uuid.uuid4(),
                placed_at=now - timedelta(days=index + 1),
                item_ids=[item_a, item_b],
            )
            for index in range(3)
        ]
        menu_items = [
            make_menu_item(menu_item_id=item_a, restaurant_id=restaurant_id, location_id=location_id, name="Pad Thai Veg", price="60.00"),
            make_menu_item(menu_item_id=item_b, restaurant_id=restaurant_id, location_id=location_id, name="Thai Iced Tea", price="40.00"),
        ]
        db = build_rebuild_session(
            orders=orders,
            menu_items=menu_items,
            restaurants=[make_restaurant(restaurant_id=restaurant_id)],
            existing_combos=[existing_combo],
        )

        with patch("app.services.generated_combos._invalidate_combo_related_caches"):
            result = rebuild_generated_combos(db, lookback_days=120)

        combo_entries = [entry for entry in db.added if isinstance(entry, GeneratedCombo)]
        self.assertEqual(result.created_count, 0)
        self.assertEqual(result.updated_count, 1)
        self.assertEqual(len(combo_entries), 1)
        self.assertIs(combo_entries[0], existing_combo)
        self.assertEqual(existing_combo.status, GeneratedComboLifecycleStatus.LIVE.value)

    def test_manual_status_update_promotes_combo_to_live(self) -> None:
        restaurant_id = uuid.uuid4()
        location_id = uuid.uuid4()
        now = datetime(2026, 6, 18, tzinfo=UTC)
        combo = make_existing_combo(
            restaurant_id=restaurant_id,
            location_id=location_id,
            item_ids=(uuid.uuid4(), uuid.uuid4()),
            created_at=now - timedelta(days=5),
            last_seen_at=now - timedelta(days=1),
            status=GeneratedComboLifecycleStatus.DRAFT,
            unique_user_count=1,
        )
        combo.__dict__["restaurant"] = SimpleNamespace(name="Bangkok Bowl")
        combo.__dict__["restaurant_location"] = SimpleNamespace(branch_name="Ellisbridge")
        combo.__dict__["combo_items"] = []
        db = FakeSession([[combo], [combo]])

        with patch("app.services.generated_combos._invalidate_combo_related_caches"):
            updated = set_generated_combo_status(
                db,
                combo_id=combo.id,
                status_value=GeneratedComboLifecycleStatus.LIVE.value,
            )

        self.assertEqual(combo.manual_status_override, GeneratedComboLifecycleStatus.LIVE.value)
        self.assertEqual(combo.status, GeneratedComboLifecycleStatus.LIVE.value)
        self.assertTrue(combo.is_customer_visible)
        self.assertTrue(combo.is_active)
        self.assertEqual(updated.status, GeneratedComboLifecycleStatus.LIVE.value)

    def test_delivered_cod_orders_also_contribute_to_draft_generation(self) -> None:
        restaurant_id = uuid.uuid4()
        location_id = uuid.uuid4()
        item_a = uuid.uuid4()
        item_b = uuid.uuid4()
        now = datetime(2026, 6, 18, tzinfo=UTC)
        customer_id = uuid.uuid4()
        orders = [
            make_order(
                restaurant_id=restaurant_id,
                location_id=location_id,
                customer_id=customer_id,
                placed_at=now - timedelta(days=offset + 1),
                item_ids=[item_a, item_b],
                payment_status=PaymentStatus.COD,
            )
            for offset in range(4)
        ]
        menu_items = [
            make_menu_item(menu_item_id=item_a, restaurant_id=restaurant_id, location_id=location_id, name="Thai Mango Salad", price="8.99"),
            make_menu_item(menu_item_id=item_b, restaurant_id=restaurant_id, location_id=location_id, name="Coconut Cooler", price="3.29"),
        ]
        db = build_rebuild_session(
            orders=orders,
            menu_items=menu_items,
            restaurants=[make_restaurant(restaurant_id=restaurant_id)],
            existing_combos=[],
        )

        with patch("app.services.generated_combos._invalidate_combo_related_caches"):
            result = rebuild_generated_combos(db, lookback_days=120)

        combo = latest_combo_from_session(db)
        self.assertEqual(result.created_count, 1)
        self.assertEqual(combo.status, GeneratedComboLifecycleStatus.DRAFT.value)
        self.assertFalse(combo.is_customer_visible)


if __name__ == "__main__":
    unittest.main()
