"""The payout ledger: one row per order, moved only by `services/payouts`.

Built on a throwaway database from `create_all`, like every suite here. The
Razorpay side is a fake `RouteClient` recording what it was asked, so these
tests say exactly which calls a step makes, and that a repeated step makes
none.
"""

from __future__ import annotations

import sys
import unittest
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from unittest import mock

from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.config import get_settings  # noqa: E402
from app.models.base import Base  # noqa: E402
from app.models.enums import (  # noqa: E402
    OrderFulfillmentType, OrderScheduleType, OrderStatus, PaymentMethod, PaymentStatus,
    PayoutAccountStatus, PayoutStatus, UserRole,
)
from app.models.order import Order  # noqa: E402
from app.models.payment import PaymentTransaction  # noqa: E402
from app.models.restaurant import Restaurant  # noqa: E402
from app.models.restaurant_location import RestaurantLocation  # noqa: E402
from app.models.restaurant_payout import RestaurantPayout, RestaurantPayoutAccount  # noqa: E402
from app.models.user import User  # noqa: E402

settings = get_settings()
TEST_DB_NAME = "restaurant_rag_payout_ledger_test"
D = Decimal


def _url(database: str) -> str:
    return (
        f"postgresql+psycopg://{settings.postgres_user}:{settings.postgres_password}"
        f"@{settings.postgres_server}:{settings.postgres_port}/{database}"
    )


def postgres_available() -> bool:
    engine = None
    try:
        engine = create_engine(_url("postgres"), isolation_level="AUTOCOMMIT")
        with engine.connect():
            return True
    except Exception:  # noqa: BLE001
        return False
    finally:
        if engine is not None:
            engine.dispose()


class LedgerDatabase(unittest.TestCase):
    """Creates the database once per class and empties it before each test."""

    engine = None

    @classmethod
    def setUpClass(cls) -> None:
        admin = create_engine(_url("postgres"), isolation_level="AUTOCOMMIT")
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{TEST_DB_NAME}" WITH (FORCE)'))
            connection.execute(text(f'CREATE DATABASE "{TEST_DB_NAME}"'))
        admin.dispose()
        cls.engine = create_engine(_url(TEST_DB_NAME))
        with cls.engine.begin() as connection:
            connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        Base.metadata.create_all(cls.engine)
        cls.Session = sessionmaker(bind=cls.engine, expire_on_commit=False)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.engine.dispose()
        admin = create_engine(_url("postgres"), isolation_level="AUTOCOMMIT")
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{TEST_DB_NAME}" WITH (FORCE)'))
        admin.dispose()

    def setUp(self) -> None:
        with self.engine.begin() as connection:
            connection.execute(text("TRUNCATE users, restaurants CASCADE"))
        self.db = self.Session()
        self.addCleanup(self.db.close)
        # Nothing here may reach a real broker.
        patcher = mock.patch("app.config.celery.celery_app.send_task")
        self.sent = patcher.start()
        self.addCleanup(patcher.stop)
        self.owner = User(id=uuid.uuid4(), email=f"o{uuid.uuid4().hex[:6]}@x.in", full_name="Owner",
                          hashed_password="x", role=UserRole.OWNER)
        self.customer = User(id=uuid.uuid4(), email=f"c{uuid.uuid4().hex[:6]}@x.in", full_name="Cust",
                             hashed_password="x", role=UserRole.CUSTOMER)
        self.db.add_all([self.owner, self.customer])
        self.db.flush()
        self.restaurant = Restaurant(
            id=uuid.uuid4(), owner_id=self.owner.id, name="Darshan", slug=f"d-{uuid.uuid4().hex[:6]}",
            cuisine_type="Gujarati", address_line_1="1 St", city="Surat", state="Gujarat",
            postal_code="395004", is_approved=True, is_active=True, currency="INR",
        )
        self.db.add(self.restaurant)
        self.db.flush()
        self.location = RestaurantLocation(
            id=uuid.uuid4(), restaurant_id=self.restaurant.id, branch_name="Main", address_line_1="1 St",
            city="Surat", state="Gujarat", postal_code="395004", delivery_fee=D("40"), is_open=True,
        )
        self.db.add(self.location)
        self.db.commit()

    def make_order(self, *, method=PaymentMethod.RAZORPAY, status=OrderStatus.PLACED,
                   paid=True, platform=True, payment_id="pay_123", total=D("598.20")) -> Order:
        order = Order(
            id=uuid.uuid4(), customer_id=self.customer.id, restaurant_id=self.restaurant.id,
            restaurant_location_id=self.location.id, status=status,
            payment_status=PaymentStatus.PAID if paid else PaymentStatus.COD,
            payment_method=method, fulfillment_type=OrderFulfillmentType.DELIVERY,
            schedule_type=OrderScheduleType.ASAP, scheduled_at=datetime.now(UTC),
            subtotal=D("500.00"), commission_amount=D("50.00"), packaging_fee=D("20.00"),
            food_tax_amount=D("26.00"), delivery_fee=D("40.00"), delivery_tax_amount=D("7.20"),
            platform_fee=D("5.00"), tax_amount=D("33.20"), discount_amount=D("0"), total_amount=total,
            currency="INR", delivery_address="2 Lane",
        )
        self.db.add(order)
        self.db.flush()
        if method != PaymentMethod.COD:
            self.db.add(PaymentTransaction(
                order_id=order.id, provider="razorpay", provider_intent_id=f"order_{uuid.uuid4().hex[:10]}",
                provider_payment_id=payment_id or None, status=PaymentStatus.PAID, amount=total,
                currency="INR", on_platform_account=platform,
            ))
        self.db.commit()
        return order

    def make_active_account(self) -> RestaurantPayoutAccount:
        account = RestaurantPayoutAccount(
            restaurant_id=self.restaurant.id, razorpay_account_id="acc_TEST1", product_id="acc_prd_1",
            status=PayoutAccountStatus.ACTIVE.value, legal_business_name="Darshan Foods",
        )
        self.db.add(account)
        self.db.commit()
        return account


@unittest.skipUnless(postgres_available(), "Postgres is not reachable")
class SchemaTests(LedgerDatabase):
    def test_one_ledger_row_per_order(self) -> None:
        order = self.make_order()
        for _ in range(2):
            self.db.add(RestaurantPayout(order_id=order.id, restaurant_id=self.restaurant.id,
                                         restaurant_share=D("1"), platform_keeps=D("1"), currency="INR",
                                         status=PayoutStatus.WAITING_ACCOUNT.value))
        with self.assertRaises(IntegrityError):
            self.db.commit()
        self.db.rollback()

    def test_a_payment_remembers_which_account_took_it(self) -> None:
        order = self.make_order(platform=True)
        transaction = self.db.query(PaymentTransaction).filter_by(order_id=order.id).one()
        self.assertTrue(transaction.on_platform_account)

    def test_payouts_are_off_until_switched_on(self) -> None:
        self.assertFalse(type(settings).model_fields["enable_restaurant_payouts"].default)


from app.services.payouts import service as payouts  # noqa: E402
from app.services.payouts.route_client import TransferState  # noqa: E402


class FakeClient:
    """Records what it was asked; answers like Razorpay would."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def create_transfer(self, **kwargs):
        self.calls.append(("create", kwargs))
        return TransferState("trf_1", "pending", kwargs["on_hold"], "on_hold" if kwargs["on_hold"] else "pending", "")

    def find_transfer(self, *, payment_id, order_id):
        return None

    def release(self, transfer_id):
        self.calls.append(("release", transfer_id))
        return TransferState(transfer_id, "processed", False, "pending", "")

    def reverse(self, transfer_id):
        self.calls.append(("reverse", transfer_id))

    def fetch_transfer(self, transfer_id):
        self.calls.append(("fetch", transfer_id))
        return TransferState(transfer_id, "processed", False, "settled", "setl_9")


def payouts_on():
    return mock.patch("app.services.payouts.service.get_settings",
                      return_value=get_settings().model_copy(update={"enable_restaurant_payouts": True}))


class LedgerHelpers(LedgerDatabase):
    def row(self, order):
        self.db.expire_all()
        return self.db.query(RestaurantPayout).filter_by(order_id=order.id).one()

    def record(self, order):
        transaction = self.db.query(PaymentTransaction).filter_by(order_id=order.id).one_or_none()
        payouts.record_paid_order(self.db, order, transaction)
        self.db.commit()
        return self.row(order)


@unittest.skipUnless(postgres_available(), "Postgres is not reachable")
class RecordTests(LedgerHelpers):
    def test_a_platform_payment_waits_for_its_transfer_with_both_shares(self) -> None:
        row = self.record(self.make_order())
        self.assertEqual((row.status, row.restaurant_share, row.platform_keeps, row.payment_id),
                         (PayoutStatus.WAITING_ACCOUNT.value, D("496.00"), D("102.20"), "pay_123"))

    def test_the_restaurants_own_keys_are_not_applicable(self) -> None:
        row = self.record(self.make_order(platform=False))
        self.assertEqual(row.status, PayoutStatus.NOT_APPLICABLE.value)
        self.assertEqual(row.restaurant_share, D("496.00"))  # still shown

    def test_cash_is_not_applicable(self) -> None:
        row = self.record(self.make_order(method=PaymentMethod.COD, paid=False))
        self.assertEqual(row.status, PayoutStatus.NOT_APPLICABLE.value)

    def test_figures_that_do_not_reconcile_are_blocked(self) -> None:
        row = self.record(self.make_order(total=D("600.00")))
        self.assertEqual(row.status, PayoutStatus.BLOCKED.value)
        self.assertIn("600.00", row.last_error)

    def test_recording_twice_keeps_one_row(self) -> None:
        order = self.make_order()
        self.record(order)
        self.record(order)
        self.assertEqual(self.db.query(RestaurantPayout).filter_by(order_id=order.id).count(), 1)


@unittest.skipUnless(postgres_available(), "Postgres is not reachable")
class TransferTests(LedgerHelpers):
    def ready(self, **order_kwargs):
        order = self.make_order(**order_kwargs)
        self.make_active_account()
        self.record(order)
        return order

    def test_payouts_off_calls_nothing(self) -> None:
        order = self.ready()
        client = FakeClient()
        payouts.transfer(self.db, order.id, client=client)
        self.assertEqual(client.calls, [])
        self.assertEqual(self.row(order).status, PayoutStatus.WAITING_ACCOUNT.value)

    def test_no_active_account_keeps_waiting(self) -> None:
        order = self.make_order()
        self.record(order)
        client = FakeClient()
        with payouts_on():
            payouts.transfer(self.db, order.id, client=client)
        self.assertEqual(client.calls, [])

    def test_payment_transfers_the_share_on_hold(self) -> None:
        order = self.ready()
        client = FakeClient()
        with payouts_on():
            payouts.transfer(self.db, order.id, client=client)
        kind, kwargs = client.calls[0]
        self.assertEqual((kind, kwargs["account_id"], kwargs["amount"], kwargs["on_hold"]),
                         ("create", "acc_TEST1", D("496.00"), True))
        row = self.row(order)
        self.assertEqual((row.status, row.transfer_id), (PayoutStatus.HELD.value, "trf_1"))

    def test_a_second_call_never_transfers_again(self) -> None:
        order = self.ready()
        client = FakeClient()
        with payouts_on():
            payouts.transfer(self.db, order.id, client=client)
            payouts.transfer(self.db, order.id, client=client)
        self.assertEqual([c[0] for c in client.calls], ["create"])

    def test_an_order_already_delivered_is_transferred_released(self) -> None:
        order = self.ready(status=OrderStatus.DELIVERED)
        client = FakeClient()
        with payouts_on():
            payouts.transfer(self.db, order.id, client=client)
        self.assertFalse(client.calls[0][1]["on_hold"])
        self.assertEqual(self.row(order).status, PayoutStatus.RELEASED.value)

    def test_no_payment_id_waits_and_says_why(self) -> None:
        order = self.ready(payment_id="")
        client = FakeClient()
        with payouts_on():
            payouts.transfer(self.db, order.id, client=client)
        self.assertEqual(client.calls, [])
        self.assertIn("payment id", self.row(order).last_error)

    def test_a_refusal_is_failed_with_razorpays_sentence(self) -> None:
        from app.services.payments.base import PaymentProviderError
        order = self.ready()
        client = FakeClient()
        client.create_transfer = mock.Mock(side_effect=PaymentProviderError(
            "Razorpay refused this request: account not activated", retryable=False))
        with payouts_on():
            payouts.transfer(self.db, order.id, client=client)
        row = self.row(order)
        self.assertEqual(row.status, PayoutStatus.FAILED.value)
        self.assertIn("not activated", row.last_error)
        self.assertEqual(row.attempts, 1)

    def test_delivery_releases_the_hold(self) -> None:
        order = self.ready()
        client = FakeClient()
        with payouts_on():
            payouts.transfer(self.db, order.id, client=client)
            order.status = OrderStatus.DELIVERED
            self.db.commit()
            payouts.release(self.db, order.id, client=client)
        self.assertEqual(client.calls[-1], ("release", "trf_1"))
        row = self.row(order)
        self.assertEqual(row.status, PayoutStatus.RELEASED.value)
        self.assertIsNotNone(row.released_at)

    def test_cancelling_before_delivery_reverses(self) -> None:
        order = self.ready()
        client = FakeClient()
        with payouts_on():
            payouts.transfer(self.db, order.id, client=client)
            order.status = OrderStatus.CANCELLED
            self.db.commit()
            payouts.reverse(self.db, order.id, client=client)
        self.assertEqual(client.calls[-1], ("reverse", "trf_1"))
        self.assertEqual(self.row(order).status, PayoutStatus.REVERSED.value)

    def test_cancelling_before_any_transfer_moves_no_money(self) -> None:
        order = self.make_order(status=OrderStatus.CANCELLED)
        self.record(order)
        client = FakeClient()
        with payouts_on():
            payouts.reverse(self.db, order.id, client=client)
        self.assertEqual(client.calls, [])
        self.assertEqual(self.row(order).status, PayoutStatus.NOT_APPLICABLE.value)

    def test_a_delivered_cash_order_gets_a_row_too(self) -> None:
        order = self.make_order(method=PaymentMethod.COD, paid=False, status=OrderStatus.DELIVERED)
        with payouts_on():
            payouts.release(self.db, order.id, client=FakeClient())
        self.assertEqual(self.row(order).status, PayoutStatus.NOT_APPLICABLE.value)

    def test_a_settlement_is_recorded_from_a_fetch(self) -> None:
        order = self.ready()
        client = FakeClient()
        with payouts_on():
            payouts.transfer(self.db, order.id, client=client)
            payouts.refresh_transfer(self.db, "trf_1", client=client)
        row = self.row(order)
        self.assertEqual((row.status, row.settlement_id), (PayoutStatus.SETTLED.value, "setl_9"))

    def test_activation_flushes_what_was_waiting(self) -> None:
        orders = [self.make_order(), self.make_order()]
        for order in orders:
            self.record(order)
        self.make_active_account()
        client = FakeClient()
        with payouts_on():
            self.assertEqual(payouts.flush_waiting(self.db, self.restaurant.id, client=client), 2)
        self.assertEqual([c[0] for c in client.calls], ["create", "create"])

    def test_retry_unblocks_once_the_figures_reconcile(self) -> None:
        order = self.make_order(total=D("600.00"))
        row = self.record(order)
        order.total_amount = D("598.20")
        self.db.commit()
        payouts.retry(self.db, row.id)
        self.assertEqual(self.row(order).status, PayoutStatus.WAITING_ACCOUNT.value)

@unittest.skipUnless(postgres_available(), "Postgres is not reachable")
class WiringTests(LedgerHelpers):
    def queued(self):
        return [call.args[0] for call in self.sent.call_args_list]

    def test_a_confirmed_payment_writes_the_row_and_queues_the_transfer(self) -> None:
        from app.services.payments import service as payments
        from app.services.payments.base import WebhookEvent
        order = self.make_order(status=OrderStatus.PAYMENT_PENDING)
        order.payment_status = PaymentStatus.PENDING
        self.db.commit()
        transaction = self.db.query(PaymentTransaction).filter_by(order_id=order.id).one()
        with mock.patch("app.services.orders.run_order_placed_side_effects"):
            payments._mark_paid(self.db, order, transaction, WebhookEvent(
                event_id="e1", event_type="succeeded", intent_id=transaction.provider_intent_id,
                amount=order.total_amount, currency="INR", payment_id="pay_123"))
        self.assertEqual(self.row(order).status, PayoutStatus.WAITING_ACCOUNT.value)
        self.assertIn("app.tasks.payouts.transfer_payout_task", self.queued())

    def test_delivery_and_cancellation_queue_their_steps(self) -> None:
        from app.services.order_events import record_order_status_event
        order = self.make_order()
        record_order_status_event(self.db, order=order, to_status=OrderStatus.DELIVERED)
        self.db.commit()
        record_order_status_event(self.db, order=order, to_status=OrderStatus.CANCELLED)
        self.db.commit()
        self.assertIn("app.tasks.payouts.release_payout_task", self.queued())
        self.assertIn("app.tasks.payouts.reverse_payout_task", self.queued())

    def test_a_transfer_event_is_a_nudge_to_fetch(self) -> None:
        from app.services.payouts.webhooks import handle_route_event
        handle_route_event(self.db, {"event": "transfer.processed",
                                     "payload": {"transfer": {"entity": {"id": "trf_1"}}}})
        self.db.commit()
        self.assertIn("app.tasks.payouts.refresh_transfer_task", self.queued())

    def test_an_activated_account_is_recorded_and_flushed(self) -> None:
        from app.services.payouts.webhooks import handle_route_event
        account = self.make_active_account()
        account.status = PayoutAccountStatus.UNDER_REVIEW.value
        self.db.commit()
        handle_route_event(self.db, {"event": "product.route.activated", "account_id": "acc_TEST1",
                                     "payload": {"merchant_product": {"entity": {
                                         "id": "acc_prd_1", "activation_status": "activated"}}}})
        self.db.refresh(account)
        self.assertEqual(account.status, PayoutAccountStatus.ACTIVE.value)
        self.assertIn("app.tasks.payouts.flush_waiting_task", self.queued())

class TimeoutClient(FakeClient):
    """Razorpay accepts the transfer, then the answer is lost on the way back."""

    def __init__(self) -> None:
        super().__init__()
        self.accepted: dict[str, TransferState] = {}

    def create_transfer(self, **kwargs):
        from app.services.payments.base import PaymentProviderError
        self.calls.append(("create", kwargs))
        self.accepted[str(kwargs["order_id"])] = TransferState("trf_1", "pending", kwargs["on_hold"], "on_hold", "")
        raise PaymentProviderError("Could not reach Razorpay: read timed out", retryable=True)

    def find_transfer(self, *, payment_id, order_id):
        self.calls.append(("find", payment_id))
        return self.accepted.get(str(order_id))


@unittest.skipUnless(postgres_available(), "Postgres is not reachable")
class ReviewFixTests(LedgerHelpers):
    """Found by the whole-branch review: each one moved real money wrongly."""

    def ready(self, **order_kwargs):
        order = self.make_order(**order_kwargs)
        self.make_active_account()
        self.record(order)
        return order

    def test_a_transfer_accepted_before_a_timeout_is_adopted_not_made_twice(self) -> None:
        from app.services.payments.base import PaymentProviderError
        order = self.ready()
        client = TimeoutClient()
        with payouts_on():
            with self.assertRaises(PaymentProviderError):
                payouts.transfer(self.db, order.id, client=client)
            payouts.transfer(self.db, order.id, client=client)  # the Celery retry
        self.assertEqual([c[0] for c in client.calls].count("create"), 1)
        row = self.row(order)
        self.assertEqual((row.status, row.transfer_id), (PayoutStatus.HELD.value, "trf_1"))

    def test_a_cancelled_order_is_never_transferred(self) -> None:
        order = self.ready(status=OrderStatus.CANCELLED)
        client = FakeClient()
        with payouts_on():
            payouts.transfer(self.db, order.id, client=client)
        self.assertEqual(client.calls, [])

    def test_a_live_order_is_never_reversed(self) -> None:
        order = self.ready()
        client = FakeClient()
        with payouts_on():
            payouts.transfer(self.db, order.id, client=client)
            payouts.reverse(self.db, order.id, client=client)
        self.assertNotIn("reverse", [c[0] for c in client.calls])
        self.assertEqual(self.row(order).status, PayoutStatus.HELD.value)

    def test_a_rolled_back_step_is_never_queued(self) -> None:
        order = self.make_order()
        payouts.queue_payout_step(self.db, "reverse", order.id)
        self.db.rollback()
        self.db.commit()
        self.assertNotIn("app.tasks.payouts.reverse_payout_task", [c.args[0] for c in self.sent.call_args_list])

    def test_a_partial_refund_leaves_the_share_for_a_person(self) -> None:
        from app.services.payments import service as payments
        order = self.ready(status=OrderStatus.DELIVERED)
        transaction = self.db.query(PaymentTransaction).filter_by(order_id=order.id).one()
        payments._mark_refunded(self.db, order, transaction, refunded=D("30.00"))
        self.assertNotIn("app.tasks.payouts.reverse_payout_task", [c.args[0] for c in self.sent.call_args_list])
        self.assertIn("30.00", self.row(order).last_error)

    def test_a_full_refund_takes_the_share_back(self) -> None:
        from app.services.payments import service as payments
        order = self.ready()
        transaction = self.db.query(PaymentTransaction).filter_by(order_id=order.id).one()
        payments._mark_refunded(self.db, order, transaction, refunded=order.total_amount)
        self.assertIn("app.tasks.payouts.reverse_payout_task", [c.args[0] for c in self.sent.call_args_list])

    def test_the_sweep_asks_razorpay_about_money_on_its_way(self) -> None:
        from datetime import timedelta
        order = self.ready(status=OrderStatus.DELIVERED)
        client = FakeClient()
        with payouts_on():
            payouts.transfer(self.db, order.id, client=client)
            row = self.row(order)
            row.released_at = datetime.now(UTC) - timedelta(days=2)
            self.db.commit()
            payouts.retry_stuck(self.db, client=client)
        self.assertEqual(self.row(order).status, PayoutStatus.SETTLED.value)


if __name__ == "__main__":
    unittest.main()
