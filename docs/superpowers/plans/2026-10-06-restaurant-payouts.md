# Restaurant Payouts (Razorpay Route) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every paid online order writes a payout ledger row holding the restaurant's share. A restaurant with an active Razorpay linked account is paid through Route: the share is held on payment, released on delivery, and reversed on cancel. Admin and owner can both see where every rupee is.

**Architecture:**
- A pure split function decides the two shares.
- A ledger table holds one row per order.
- Only a service moves a row. It calls Razorpay through a small Route client, always from Celery after commit and always under a row lock.
- The platform's Razorpay account collects a restaurant's payments only when that restaurant can be paid out.
- One admin page serves both roles.

**Tech Stack:**
- Backend: FastAPI, SQLAlchemy 2.0, Alembic, Celery, httpx; tests are `unittest`.
- frontend-admin: React 19 + Vite, tests in vitest, no new dependencies.

**Spec:** `docs/superpowers/specs/2026-10-05-restaurant-payouts-design.md`

## Global Constraints

- `ENABLE_RESTAURANT_PAYOUTS` defaults **off**. Off: the ledger is still written, and no Razorpay call is made.
- `restaurant_share + platform_keeps` must equal `total_amount` to the paisa. If not, the row is `BLOCKED`; a figure that does not reconcile is never transferred.
- `split.py` is the only place the split arithmetic lives.
- COD, Stripe and payments on a restaurant's own keys are never transferred. They are recorded as `NOT_APPLICABLE`.
- A payout failure must never cost a sale. Nothing on the order path may raise because of payouts.
- A row that already holds a `transfer_id` is never transferred again.
- Every Razorpay call runs in Celery after commit.
- Only the platform admin creates or edits a linked account. The owner sees its status read-only, and never sees the commission rate or `platform_keeps`.
- Bank account numbers are encrypted with `services/secrets.py`. Only the last four digits are ever returned.
- New tables enable RLS in their migration (CLAUDE.md).
- `frontend-admin` gets no new runtime dependency. A new CSS class family needs a zero entry in `styleBudget.test.ts`.
- Comments explain *why*, matching the surrounding lab-notebook density.
- Tests are `unittest`. Run them as `backend/.venv/Scripts/python.exe -m unittest ...` from `backend/`.
- **Commit only when the user asks** (a standing rule in this session). Each task ends with a verified working tree, not a commit.
- Migrations are not hand-applied to Supabase. Render's `alembic upgrade head` applies `0083` on deploy.

## Review Focus

1. **Two workers transfer the same order at once.** Expect exactly one transfer, guaranteed by the row lock (`with_for_update`) plus the `transfer_id` check. Test: `TransferTests.test_a_second_call_never_transfers_again`.
2. **An order is delivered before its transfer was made** (the account activated late, or the flag was turned on late). Expect the transfer to be created already released (`on_hold` false). Test: `TransferTests.test_an_order_already_delivered_is_transferred_released`.
3. **A paid order has no Razorpay payment id** (paid through the browser before this change). Expect it to stay `WAITING_ACCOUNT` with a readable `last_error`, not to crash. Test: `TransferTests.test_no_payment_id_waits_and_says_why`.
4. **The flag is turned off after a payment was taken on the platform account.** Expect confirmation, webhooks and reconciliation to keep using the platform account. Test: `PlatformCollectionTests.test_a_platform_payment_still_confirms_with_the_flag_off`.
5. **An owner asks for another restaurant's payouts or account.** Expect 403. Test: `PayoutApiTests.test_an_owner_cannot_name_another_restaurant`.

---

## File Structure

**Backend, new:**
- `backend/app/services/payouts/__init__.py`: the package.
- `backend/app/services/payouts/split.py`: the pure split.
- `backend/app/services/payouts/route_client.py`: Razorpay Route and Accounts v2 HTTP calls.
- `backend/app/services/payouts/accounts.py`: linked-account draft, validation, onboarding and status.
- `backend/app/services/payouts/service.py`: ledger moves (record, transfer, release, reverse, refresh, flush, retry) and the after-commit queue.
- `backend/app/services/payouts/webhooks.py`: transfer, settlement and product events from the platform webhook.
- `backend/app/models/restaurant_payout.py`: `RestaurantPayoutAccount` and `RestaurantPayout`.
- `backend/alembic/versions/0083_restaurant_payouts.py`
- `backend/app/tasks/payouts.py`
- `backend/app/api/payouts.py`
- `backend/app/schemas/payout.py`

**Backend, modified:**
- `app/models/enums.py`, `app/models/__init__.py`, `app/models/payment.py`
- `app/config/settings.py`, `app/config/celery.py`
- `app/api/__init__.py`, `app/api/payments.py`
- `app/services/payments/razorpay_provider.py`, `app/services/payments/registry.py`, `app/services/payments/service.py`
- `app/services/order_events.py`

**Backend, tests:**
- `tests/test_payout_split.py`
- `tests/test_payout_route_client.py`
- `tests/test_payout_platform_collection.py`
- `tests/test_payout_ledger.py`
- `tests/test_payout_accounts.py`
- `tests/test_payout_api.py`

**Admin:**
- New: `frontend-admin/src/services/payouts.ts` and `payouts.test.ts`, `frontend-admin/src/pages/PayoutsPage.tsx`, `frontend-admin/src/components/PayoutAccountPanel.tsx`.
- Modified: `src/types/app.ts`, `src/services/api.ts`, `src/routes.tsx`.

**Docs:** `backend/docs/payouts.md` (new), plus updates to `CLAUDE.md` and `.claude/worklog.md`.

---

### Task 1: The split

**Files:**
- Create: `backend/app/services/payouts/__init__.py`, `backend/app/services/payouts/split.py`
- Test: `backend/tests/test_payout_split.py`

**Interfaces:**
- Produces:
  - `Split(restaurant_share: Decimal, platform_keeps: Decimal, blocked_reason: str)`
  - `split_order(order) -> Split`, where `order` is any object with the money attributes and `None` counts as 0.

- [ ] **Step 1: Write the failing test**

```python
"""How one paid order divides between the restaurant and the platform.

The restaurant is owed its food at its own price (the menu price less the
commission folded into it), less the discounts it chose to run, plus packaging
and the GST on its food, which it files. The platform keeps the commission,
the delivery fee and its GST (it paid the rider), and the platform fee.
Razorpay's own fee is the platform's cost and is not in either figure.
"""

from __future__ import annotations

import sys
import unittest
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.payouts.split import split_order  # noqa: E402

D = Decimal


def order(**money):
    base = dict(
        subtotal=D("0"), commission_amount=D("0"), discount_amount=D("0"),
        packaging_fee=D("0"), food_tax_amount=D("0"), delivery_fee=D("0"),
        delivery_tax_amount=D("0"), platform_fee=D("0"), total_amount=D("0"),
    )
    base.update(money)
    return SimpleNamespace(**base)


class SplitTests(unittest.TestCase):
    def test_a_delivery_order_divides_and_reconciles(self) -> None:
        o = order(subtotal=D("500.00"), commission_amount=D("50.00"), packaging_fee=D("20.00"),
                  food_tax_amount=D("26.00"), delivery_fee=D("40.00"), delivery_tax_amount=D("7.20"),
                  platform_fee=D("5.00"), total_amount=D("598.20"))
        s = split_order(o)
        self.assertEqual(s.restaurant_share, D("496.00"))
        self.assertEqual(s.platform_keeps, D("102.20"))
        self.assertEqual(s.blocked_reason, "")

    def test_a_pickup_order_has_no_delivery_in_it(self) -> None:
        s = split_order(order(subtotal=D("200.00"), commission_amount=D("20.00"),
                              food_tax_amount=D("10.00"), total_amount=D("210.00")))
        self.assertEqual((s.restaurant_share, s.platform_keeps), (D("190.00"), D("20.00")))

    def test_a_discount_comes_out_of_the_restaurants_share(self) -> None:
        s = split_order(order(subtotal=D("300.00"), commission_amount=D("30.00"), discount_amount=D("60.00"),
                              food_tax_amount=D("12.00"), total_amount=D("252.00")))
        self.assertEqual(s.restaurant_share, D("222.00"))
        self.assertEqual(s.platform_keeps, D("30.00"))

    def test_no_recorded_commission_is_zero_commission(self) -> None:
        s = split_order(order(subtotal=D("100.00"), commission_amount=None, total_amount=D("100.00")))
        self.assertEqual((s.restaurant_share, s.platform_keeps, s.blocked_reason), (D("100.00"), D("0.00"), ""))

    def test_figures_that_do_not_add_up_are_blocked_not_guessed(self) -> None:
        # An order from before food and delivery GST were stored apart: only
        # the old combined tax column was filled, so nothing reconciles.
        s = split_order(order(subtotal=D("100.00"), total_amount=D("105.00")))
        self.assertIn("105.00", s.blocked_reason)
        self.assertIn("100.00", s.blocked_reason)

    def test_a_discount_bigger_than_the_food_is_blocked(self) -> None:
        s = split_order(order(subtotal=D("100.00"), commission_amount=D("10.00"), discount_amount=D("120.00"),
                              delivery_fee=D("40.00"), total_amount=D("20.00")))
        self.assertEqual(s.restaurant_share, D("-30.00"))
        self.assertTrue(s.blocked_reason)

    def test_paise_are_kept_exactly(self) -> None:
        s = split_order(order(subtotal=D("99.99"), commission_amount=D("9.99"), food_tax_amount=D("4.50"),
                              platform_fee=D("0.01"), total_amount=D("104.50")))
        self.assertEqual((s.restaurant_share, s.platform_keeps), (D("94.50"), D("10.00")))


if __name__ == "__main__":
    unittest.main()
```

The first test's figures: share 500 − 50 + 20 + 26 = 496; platform 50 + 40 + 7.20 + 5 = 102.20; paid 598.20.

- [ ] **Step 2: Run the test and watch it fail**

Run: `cd backend && ./.venv/Scripts/python.exe -m unittest tests.test_payout_split -v`
Expected: ERROR, `ModuleNotFoundError: No module named 'app.services.payouts'`

- [ ] **Step 3: Write the implementation**

`backend/app/services/payouts/__init__.py`:

```python
"""Paying restaurants their share through Razorpay Route.

See `backend/docs/payouts.md` and the spec in
`docs/superpowers/specs/2026-10-05-restaurant-payouts-design.md`.
"""
```

`backend/app/services/payouts/split.py`:

```python
"""How one order's money divides between the restaurant and the platform.

The only place this arithmetic lives. The ledger, the transfer and both
screens read the result; none of them adds the columns up again.

    restaurant_share = subtotal - commission - discount + packaging + food GST
    platform_keeps   = commission + delivery fee + delivery GST + platform fee

`subtotal` already carries the commission (the menu price is the restaurant's
price with the platform's percentage folded in), which is why it comes back
out of the restaurant's half. Discounts are the restaurant's: an owner runs
offers for their own kitchen. Delivery and its GST are the platform's, because
the platform pays the rider. Razorpay's own fee is not in either figure: the
platform absorbs it, so a restaurant's share never shrinks with the gateway's.

A split that does not add back up to what the customer paid is BLOCKED rather
than rounded or guessed. That happens to orders from before food and delivery
GST were stored apart, and to anything a later price change adds without
teaching this function; in both cases the right number is unknown, and
transferring a wrong one is real money in the wrong bank.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

_PAISA = Decimal("0.01")


@dataclass(frozen=True)
class Split:
    restaurant_share: Decimal
    platform_keeps: Decimal
    #: Empty when the split can be paid; otherwise the sentence an admin reads.
    blocked_reason: str


def _money(order: Any, name: str) -> Decimal:
    value = getattr(order, name, None)
    return Decimal(value or 0).quantize(_PAISA)


def split_order(order: Any) -> Split:
    share = (
        _money(order, "subtotal")
        - _money(order, "commission_amount")
        - _money(order, "discount_amount")
        + _money(order, "packaging_fee")
        + _money(order, "food_tax_amount")
    )
    keeps = (
        _money(order, "commission_amount")
        + _money(order, "delivery_fee")
        + _money(order, "delivery_tax_amount")
        + _money(order, "platform_fee")
    )
    total = _money(order, "total_amount")

    reason = ""
    if share + keeps != total:
        reason = (
            f"The shares add up to {share + keeps} but the customer paid {total}; "
            "this order's figures do not reconcile, so nothing is transferred."
        )
    elif share < 0:
        reason = "The discount is larger than the food, so the restaurant's share is below zero."
    return Split(restaurant_share=share, platform_keeps=keeps, blocked_reason=reason)
```

- [ ] **Step 4: Run the test and watch it pass**

Run: `cd backend && ./.venv/Scripts/python.exe -m unittest tests.test_payout_split -v`
Expected: `Ran 7 tests ... OK`

---

### Task 2: Schema — tables, enums, settings

**Files:**
- Create: `backend/app/models/restaurant_payout.py`, `backend/alembic/versions/0083_restaurant_payouts.py`
- Modify: `backend/app/models/enums.py`, `backend/app/models/__init__.py`, `backend/app/models/payment.py`, `backend/app/config/settings.py`
- Test: `backend/tests/test_payout_ledger.py` (the schema class only, for now)

**Interfaces:**
- Produces:
  - `PayoutStatus` (StrEnum): `WAITING_ACCOUNT`, `HELD`, `RELEASED`, `SETTLED`, `REVERSED`, `FAILED`, `BLOCKED`, `NOT_APPLICABLE`.
  - `PayoutAccountStatus` (StrEnum): `DRAFT`, `SUBMITTED`, `UNDER_REVIEW`, `NEEDS_CLARIFICATION`, `ACTIVE`, `SUSPENDED`.
  - Models `RestaurantPayoutAccount` (primary key `restaurant_id`) and `RestaurantPayout` (unique `order_id`), with the columns in Step 3.
  - `PaymentTransaction.on_platform_account: bool`.
  - Settings: `enable_restaurant_payouts: bool = False`, `razorpay_webhook_secret: str = ""`, `payouts_retry_limit: int = 5`.
  - The test fixture `LedgerDatabase`, with `make_order(...)` and `make_active_account()`, which Tasks 4 to 7 import.

- [ ] **Step 1: Write the failing test.** Create `backend/tests/test_payout_ledger.py`. It holds the shared throwaway-database fixture that Tasks 4 to 7 extend.

```python
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
        self.restaurant = Restaurant(id=uuid.uuid4(), name="Darshan", slug=f"d-{uuid.uuid4().hex[:6]}",
                                     owner_id=self.owner.id)
        self.db.add(self.restaurant)
        self.db.flush()
        self.location = RestaurantLocation(id=uuid.uuid4(), restaurant_id=self.restaurant.id, name="Main",
                                           address_line1="1 Road", city="Surat")
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
            platform_fee=D("5.00"), total_amount=total, currency="INR", delivery_address="2 Lane",
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


if __name__ == "__main__":
    unittest.main()
```

The `User`, `Restaurant` and `RestaurantLocation` constructor fields above must match the models. Copy the required columns from `tests/test_demo_restaurants.py`, which builds the same three. Record any difference as a ruling.

- [ ] **Step 2: Run the test and watch it fail**

Run: `cd backend && ./.venv/Scripts/python.exe -m unittest tests.test_payout_ledger -v`
Expected: ERROR, `ImportError: cannot import name 'PayoutAccountStatus'`

- [ ] **Step 3: Write the implementation**

Append to `app/models/enums.py`:

```python
class PayoutStatus(StrEnum):
    """Where one order's share for the restaurant is. See `services/payouts`."""

    # Paid, but nothing has gone to the restaurant yet: no active linked
    # account, payouts switched off, or the payment id not known yet.
    WAITING_ACCOUNT = "WAITING_ACCOUNT"
    HELD = "HELD"  # transferred, on hold until the order is delivered
    RELEASED = "RELEASED"  # hold lifted; Razorpay settles it on its schedule
    SETTLED = "SETTLED"  # in the restaurant's bank
    REVERSED = "REVERSED"  # taken back: cancelled or refunded
    FAILED = "FAILED"  # Razorpay refused; Retry once the cause is fixed
    BLOCKED = "BLOCKED"  # the split did not reconcile, nothing is transferred
    # COD, Stripe, or the restaurant's own keys: the money never passed
    # through the platform, so there is nothing to send. Recorded anyway so
    # the screen shows every order's split.
    NOT_APPLICABLE = "NOT_APPLICABLE"


class PayoutAccountStatus(StrEnum):
    """A restaurant's Razorpay linked account, as Razorpay last described it."""

    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
```

Create `app/models/restaurant_payout.py`:

```python
"""A restaurant's Razorpay linked account, and one payout row per order.

Statuses are stored as strings rather than Postgres enums. Adding a value to a
Postgres enum inside an Alembic upgrade is the trap `0071` documents (unsafe
use of a new value in the same transaction), and these vocabularies are
Razorpay's to extend.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin
from app.models.enums import PayoutAccountStatus


class RestaurantPayoutAccount(Base):
    __tablename__ = "restaurant_payout_accounts"

    restaurant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("restaurants.id", ondelete="CASCADE"), primary_key=True
    )
    razorpay_account_id: Mapped[str] = mapped_column(String(64), nullable=False, default="", server_default="")
    stakeholder_id: Mapped[str] = mapped_column(String(64), nullable=False, default="", server_default="")
    product_id: Mapped[str] = mapped_column(String(64), nullable=False, default="", server_default="")
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=PayoutAccountStatus.DRAFT.value,
        server_default=PayoutAccountStatus.DRAFT.value,
    )
    legal_business_name: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    business_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default="proprietorship", server_default="proprietorship"
    )
    pan: Mapped[str] = mapped_column(String(10), nullable=False, default="", server_default="")
    contact_name: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    email: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    phone: Mapped[str] = mapped_column(String(32), nullable=False, default="", server_default="")
    street: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    city: Mapped[str] = mapped_column(String(120), nullable=False, default="", server_default="")
    state: Mapped[str] = mapped_column(String(120), nullable=False, default="", server_default="")
    postal_code: Mapped[str] = mapped_column(String(10), nullable=False, default="", server_default="")
    # Encrypted like a gateway secret; only the last four are ever returned.
    bank_account_number_encrypted: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    bank_account_last4: Mapped[str] = mapped_column(String(4), nullable=False, default="", server_default="")
    ifsc: Mapped[str] = mapped_column(String(11), nullable=False, default="", server_default="")
    beneficiary_name: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    # What Razorpay still needs, as it phrased it, for the screen.
    requirements: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class RestaurantPayout(TimestampMixin, Base):
    __tablename__ = "restaurant_payouts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # Unique: one row per order is what makes every step idempotent.
    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    restaurant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    payment_id: Mapped[str] = mapped_column(String(64), nullable=False, default="", server_default="")
    restaurant_share: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    platform_keeps: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="INR", server_default="INR")
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    transfer_id: Mapped[str] = mapped_column(String(64), nullable=False, default="", server_default="", index=True)
    settlement_id: Mapped[str] = mapped_column(String(64), nullable=False, default="", server_default="")
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reversed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
```

In `app/models/__init__.py`, import and export both classes beside the other models, following the file's existing pattern.

In `app/models/payment.py`, add to `PaymentTransaction` after `provider_payment_id`. Add `Boolean` to that file's sqlalchemy import.

```python
    # Which Razorpay account took this payment: the platform's (Route, paid
    # out to the restaurant) or the restaurant's own. Confirming, reconciling
    # and cancelling use THIS, not what the restaurant is set to now, so
    # moving a restaurant onto Route cannot strand its earlier orders.
    on_platform_account: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
```

In `app/config/settings.py`, beside `razorpay_key_secret`:

```python
    # The platform's own Razorpay webhook secret, for payments it collects for
    # restaurants on Route, and for transfer, settlement and linked-account
    # events. Different from each restaurant's own webhook secret.
    razorpay_webhook_secret: str = ""
    # Pay restaurants their share through Razorpay Route. Off: the payout
    # ledger is still written, so the admin can see exactly what would be
    # paid, and Razorpay is never called. Also gates the platform collecting
    # a restaurant's payments at all: without payouts there is no way to pass
    # the money on.
    enable_restaurant_payouts: bool = False
    # How many times a refused or unreachable transfer is retried by the
    # hourly sweep before it waits for a person.
    payouts_retry_limit: int = 5
```

Create `backend/alembic/versions/0083_restaurant_payouts.py`:

```python
"""Restaurant payouts through Razorpay Route.

Two tables, `restaurant_payout_accounts` (a restaurant's linked account) and
`restaurant_payouts` (one row per order), plus
`payment_transactions.on_platform_account`. Additive, and guarded like
`0075`-`0082` so a schema created by hand is not created twice. RLS is enabled
here, not by hand, so a fresh environment comes up closed (CLAUDE.md).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0083_restaurant_payouts"
down_revision = "0082_restaurant_is_demo"
branch_labels = None
depends_on = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    tables = _tables()
    if "restaurant_payout_accounts" not in tables:
        op.create_table(
            "restaurant_payout_accounts",
            sa.Column("restaurant_id", postgresql.UUID(as_uuid=True),
                      sa.ForeignKey("restaurants.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("razorpay_account_id", sa.String(64), nullable=False, server_default=""),
            sa.Column("stakeholder_id", sa.String(64), nullable=False, server_default=""),
            sa.Column("product_id", sa.String(64), nullable=False, server_default=""),
            sa.Column("status", sa.String(32), nullable=False, server_default="DRAFT"),
            sa.Column("legal_business_name", sa.String(255), nullable=False, server_default=""),
            sa.Column("business_type", sa.String(32), nullable=False, server_default="proprietorship"),
            sa.Column("pan", sa.String(10), nullable=False, server_default=""),
            sa.Column("contact_name", sa.String(255), nullable=False, server_default=""),
            sa.Column("email", sa.String(255), nullable=False, server_default=""),
            sa.Column("phone", sa.String(32), nullable=False, server_default=""),
            sa.Column("street", sa.String(255), nullable=False, server_default=""),
            sa.Column("city", sa.String(120), nullable=False, server_default=""),
            sa.Column("state", sa.String(120), nullable=False, server_default=""),
            sa.Column("postal_code", sa.String(10), nullable=False, server_default=""),
            sa.Column("bank_account_number_encrypted", sa.String(1024), nullable=True),
            sa.Column("bank_account_last4", sa.String(4), nullable=False, server_default=""),
            sa.Column("ifsc", sa.String(11), nullable=False, server_default=""),
            sa.Column("beneficiary_name", sa.String(255), nullable=False, server_default=""),
            sa.Column("requirements", postgresql.JSONB(), nullable=False, server_default="[]"),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column("updated_by_user_id", postgresql.UUID(as_uuid=True),
                      sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
    if "restaurant_payouts" not in tables:
        op.create_table(
            "restaurant_payouts",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("order_id", postgresql.UUID(as_uuid=True),
                      sa.ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, unique=True),
            sa.Column("restaurant_id", postgresql.UUID(as_uuid=True),
                      sa.ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False),
            sa.Column("payment_id", sa.String(64), nullable=False, server_default=""),
            sa.Column("restaurant_share", sa.Numeric(10, 2), nullable=False),
            sa.Column("platform_keeps", sa.Numeric(10, 2), nullable=False),
            sa.Column("currency", sa.String(10), nullable=False, server_default="INR"),
            sa.Column("status", sa.String(32), nullable=False),
            sa.Column("transfer_id", sa.String(64), nullable=False, server_default=""),
            sa.Column("settlement_id", sa.String(64), nullable=False, server_default=""),
            sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("reversed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
        op.create_index("ix_restaurant_payouts_restaurant_id", "restaurant_payouts", ["restaurant_id"])
        op.create_index("ix_restaurant_payouts_status", "restaurant_payouts", ["status"])
        op.create_index("ix_restaurant_payouts_transfer_id", "restaurant_payouts", ["transfer_id"])
    if "on_platform_account" not in _columns("payment_transactions"):
        op.add_column(
            "payment_transactions",
            sa.Column("on_platform_account", sa.Boolean(), nullable=False, server_default=sa.false()),
        )
    op.execute("ALTER TABLE public.restaurant_payout_accounts ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE public.restaurant_payouts ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    if "on_platform_account" in _columns("payment_transactions"):
        op.drop_column("payment_transactions", "on_platform_account")
    tables = _tables()
    if "restaurant_payouts" in tables:
        op.drop_table("restaurant_payouts")
    if "restaurant_payout_accounts" in tables:
        op.drop_table("restaurant_payout_accounts")
```

Check `TimestampMixin` in `app/models/base.py`. If its column definitions differ from the two timestamp columns written in the migration, copy its definitions into the migration and record a ruling.

- [ ] **Step 4: Run the test and watch it pass, then round-trip the migration**

Run: `cd backend && ./.venv/Scripts/python.exe -m unittest tests.test_payout_ledger -v`
Expected: `Ran 3 tests ... OK`

Then run a migration round-trip on a LOCAL throwaway database only. Adapt the scratchpad `stamp_check.py`:
1. Create `rr_payouts_mig`.
2. Run `upgrade head`, then `downgrade -1`, then `upgrade head`.
3. Drop the database.

The script must refuse any URL that is not `127.0.0.1`.
Expected: all three steps succeed, and `alembic heads` prints one head, `0083_restaurant_payouts`.

---

### Task 3: The Route client

**Files:**
- Modify: `backend/app/services/payments/razorpay_provider.py`. `_request` gains `base`; the constructor gains `is_platform`.
- Create: `backend/app/services/payouts/route_client.py`
- Test: `backend/tests/test_payout_route_client.py`

**Interfaces:**
- Consumes: `RazorpayProvider._request(method, path, *, base=API_BASE, **kwargs)` and `_to_minor_units`.
- Produces:
  - `TransferState(transfer_id, status, on_hold, settlement_status, settlement_id, error)`.
  - `ProductState(product_id, activation_status, requirements: list[str])`.
  - `RouteClient(provider)`, with these methods:
    - `create_transfer(*, payment_id, account_id, amount, currency, order_id, on_hold) -> TransferState`
    - `release(transfer_id) -> TransferState`
    - `reverse(transfer_id) -> None`
    - `fetch_transfer(transfer_id) -> TransferState`
    - `create_account(account) -> str`
    - `create_stakeholder(account_id, account) -> str`
    - `request_route(account_id) -> ProductState`
    - `submit_bank(account_id, product_id, *, account_number, ifsc, beneficiary_name) -> ProductState`
    - `fetch_product(account_id, product_id) -> ProductState`
  - `ACCOUNT_STATUS_FOR_ACTIVATION: dict[str, PayoutAccountStatus]`.

- [ ] **Step 1: Write the failing test**

```python
"""The calls that move a restaurant's share, and that open its linked account.

Every request body is asserted exactly, because these are the calls that move
money: an amount in rupees where paise were meant is a hundredfold error, and
`on_hold` missing means the restaurant is paid for food nobody has delivered.
"""

from __future__ import annotations

import sys
import unittest
import uuid
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models.enums import PayoutAccountStatus  # noqa: E402
from app.services.payments.razorpay_provider import V2_API_BASE, RazorpayProvider  # noqa: E402
from app.services.payouts.route_client import ACCOUNT_STATUS_FOR_ACTIVATION, RouteClient  # noqa: E402

TRANSFER = {"id": "trf_1", "status": "pending", "on_hold": True, "settlement_status": "on_hold",
            "recipient_settlement_id": None}


class RouteClientTests(unittest.TestCase):
    def setUp(self) -> None:
        self.provider = RazorpayProvider(key_id="rzp_test_x", key_secret="s", is_platform=True)
        self.client = RouteClient(self.provider)

    def _run(self, reply, call):
        with mock.patch.object(self.provider, "_request", return_value=reply) as request:
            result = call()
        return result, request.call_args

    def test_a_transfer_is_made_from_the_payment_in_paise_and_on_hold(self) -> None:
        order_id = uuid.uuid4()
        state, call = self._run({"items": [TRANSFER]}, lambda: self.client.create_transfer(
            payment_id="pay_9", account_id="acc_1", amount=Decimal("496.55"), currency="INR",
            order_id=order_id, on_hold=True))
        self.assertEqual(call.args, ("POST", "/payments/pay_9/transfers"))
        self.assertEqual(call.kwargs["json"], {"transfers": [{
            "account": "acc_1", "amount": 49655, "currency": "INR", "on_hold": 1,
            "notes": {"order_id": str(order_id)},
        }]})
        self.assertEqual((state.transfer_id, state.on_hold), ("trf_1", True))

    def test_a_delivered_order_is_transferred_without_a_hold(self) -> None:
        _, call = self._run({"items": [dict(TRANSFER, on_hold=False)]}, lambda: self.client.create_transfer(
            payment_id="pay_9", account_id="acc_1", amount=Decimal("1"), currency="INR",
            order_id=uuid.uuid4(), on_hold=False))
        self.assertEqual(call.kwargs["json"]["transfers"][0]["on_hold"], 0)

    def test_release_lifts_the_hold(self) -> None:
        state, call = self._run(dict(TRANSFER, on_hold=False), lambda: self.client.release("trf_1"))
        self.assertEqual(call.args, ("PATCH", "/transfers/trf_1"))
        self.assertEqual(call.kwargs["json"], {"on_hold": 0})
        self.assertFalse(state.on_hold)

    def test_reverse_takes_the_whole_transfer_back(self) -> None:
        _, call = self._run({"id": "rvrsl_1"}, lambda: self.client.reverse("trf_1"))
        self.assertEqual(call.args, ("POST", "/transfers/trf_1/reversals"))

    def test_a_settled_transfer_carries_its_settlement(self) -> None:
        state, _ = self._run(dict(TRANSFER, status="processed", on_hold=False, settlement_status="settled",
                                  recipient_settlement_id="setl_7"), lambda: self.client.fetch_transfer("trf_1"))
        self.assertEqual((state.settlement_status, state.settlement_id), ("settled", "setl_7"))

    def test_opening_a_linked_account_uses_v2(self) -> None:
        account = SimpleNamespace(
            restaurant_id=uuid.uuid4(), email="a@b.in", phone="9876543210", legal_business_name="Darshan Foods",
            business_type="proprietorship", contact_name="Darshan", pan="ABCDE1234F", street="1 Road",
            city="Surat", state="Gujarat", postal_code="395007")
        account_id, call = self._run({"id": "acc_1"}, lambda: self.client.create_account(account))
        self.assertEqual(call.args, ("POST", "/accounts"))
        self.assertEqual(call.kwargs["base"], V2_API_BASE)
        body = call.kwargs["json"]
        self.assertEqual(body["type"], "route")
        self.assertEqual(body["reference_id"], str(account.restaurant_id)[:20])
        self.assertEqual(body["legal_info"], {"pan": "ABCDE1234F"})
        self.assertEqual(body["profile"]["addresses"]["registered"]["postal_code"], "395007")
        self.assertEqual(account_id, "acc_1")

    def test_the_bank_account_goes_on_the_route_product(self) -> None:
        state, call = self._run({"id": "acc_prd_1", "activation_status": "under_review", "requirements": []},
                                lambda: self.client.submit_bank("acc_1", "acc_prd_1", account_number="123456789",
                                                                ifsc="HDFC0000001", beneficiary_name="Darshan Foods"))
        self.assertEqual(call.args, ("PATCH", "/accounts/acc_1/products/acc_prd_1"))
        self.assertEqual(call.kwargs["json"], {"settlements": {"account_number": "123456789",
                                                               "ifsc_code": "HDFC0000001",
                                                               "beneficiary_name": "Darshan Foods"},
                                               "tnc_accepted": True})
        self.assertEqual(state.activation_status, "under_review")

    def test_requirements_are_kept_as_razorpay_said_them(self) -> None:
        state, _ = self._run({"id": "acc_prd_1", "activation_status": "needs_clarification",
                              "requirements": [{"field_reference": "settlements.ifsc_code",
                                                "reason_code": "field_missing"}]},
                             lambda: self.client.fetch_product("acc_1", "acc_prd_1"))
        self.assertEqual(state.requirements, ["settlements.ifsc_code: field_missing"])

    def test_every_activation_status_has_a_meaning_here(self) -> None:
        self.assertEqual(ACCOUNT_STATUS_FOR_ACTIVATION["activated"], PayoutAccountStatus.ACTIVE)
        self.assertEqual(ACCOUNT_STATUS_FOR_ACTIVATION["needs_clarification"],
                         PayoutAccountStatus.NEEDS_CLARIFICATION)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test and watch it fail**

Run: `cd backend && ./.venv/Scripts/python.exe -m unittest tests.test_payout_route_client -v`
Expected: ERROR, `ImportError: cannot import name 'V2_API_BASE'`

- [ ] **Step 3: Write the implementation**

Make three changes in `razorpay_provider.py`:
- Add `V2_API_BASE = "https://api.razorpay.com/v2"` under `API_BASE`.
- Give the constructor a keyword argument `is_platform: bool = False` and store it as `self.is_platform = is_platform`. Comment it: True only for the platform's own account (Route); the flag is read when an attempt is recorded, so the attempt remembers which account took it.
- Make `_request` `def _request(self, method: str, path: str, *, base: str = API_BASE, **kwargs: Any)` and change its URL to `f"{base}{path}"`.

Create `app/services/payouts/route_client.py`:

```python
"""Razorpay Route and linked-account calls, on the platform's own account.

Built on `RazorpayProvider._request` so the error handling is the one already
proven on checkout: a 4xx is our request being wrong and is not retried, a
5xx or a network failure is. Amounts go through `_to_minor_units`, the one
place rupees become paise.

Linked accounts use Razorpay's v2 Accounts API (`/v2/accounts`, then a
stakeholder, then the `route` product, then the settlement bank account on
the product). Transfers use v1. The v2 bodies follow Razorpay's published
Route onboarding docs; the first test-mode run is where a field name is
confirmed (see `backend/docs/payouts.md`).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from app.models.enums import PayoutAccountStatus
from app.services.payments.razorpay_provider import V2_API_BASE, RazorpayProvider, _to_minor_units

#: Razorpay's `activation_status` on the route product, in this app's words.
ACCOUNT_STATUS_FOR_ACTIVATION: dict[str, PayoutAccountStatus] = {
    "requested": PayoutAccountStatus.SUBMITTED,
    "under_review": PayoutAccountStatus.UNDER_REVIEW,
    "needs_clarification": PayoutAccountStatus.NEEDS_CLARIFICATION,
    "activated": PayoutAccountStatus.ACTIVE,
    "suspended": PayoutAccountStatus.SUSPENDED,
}


@dataclass(frozen=True)
class TransferState:
    transfer_id: str
    status: str
    on_hold: bool
    settlement_status: str
    settlement_id: str
    error: str = ""


@dataclass(frozen=True)
class ProductState:
    product_id: str
    activation_status: str
    requirements: list[str] = field(default_factory=list)


def _transfer(body: dict[str, Any]) -> TransferState:
    error = body.get("error") or {}
    return TransferState(
        transfer_id=str(body.get("id") or ""),
        status=str(body.get("status") or ""),
        on_hold=bool(body.get("on_hold")),
        settlement_status=str(body.get("settlement_status") or ""),
        settlement_id=str(body.get("recipient_settlement_id") or ""),
        error=str(error.get("description") or "") if isinstance(error, dict) else "",
    )


def _product(body: dict[str, Any]) -> ProductState:
    needs = []
    for item in body.get("requirements") or []:
        if isinstance(item, dict):
            needs.append(f"{item.get('field_reference', '')}: {item.get('reason_code', '')}".strip(": "))
    return ProductState(
        product_id=str(body.get("id") or ""),
        activation_status=str(body.get("activation_status") or ""),
        requirements=needs,
    )


class RouteClient:
    def __init__(self, provider: RazorpayProvider) -> None:
        self._provider = provider

    # --- transfers -------------------------------------------------------

    def create_transfer(self, *, payment_id: str, account_id: str, amount: Decimal, currency: str,
                        order_id: uuid.UUID, on_hold: bool) -> TransferState:
        body = self._provider._request("POST", f"/payments/{payment_id}/transfers", json={"transfers": [{
            "account": account_id,
            "amount": _to_minor_units(amount),
            "currency": (currency or "INR").upper(),
            "on_hold": 1 if on_hold else 0,
            "notes": {"order_id": str(order_id)},
        }]})
        items = body.get("items") or []
        return _transfer(items[0] if items else body)

    def release(self, transfer_id: str) -> TransferState:
        return _transfer(self._provider._request("PATCH", f"/transfers/{transfer_id}", json={"on_hold": 0}))

    def reverse(self, transfer_id: str) -> None:
        # No amount: the whole transfer comes back to the platform's balance.
        self._provider._request("POST", f"/transfers/{transfer_id}/reversals", json={})

    def fetch_transfer(self, transfer_id: str) -> TransferState:
        return _transfer(self._provider._request("GET", f"/transfers/{transfer_id}"))

    # --- linked accounts ------------------------------------------------

    def create_account(self, account: Any) -> str:
        body = self._provider._request("POST", "/accounts", base=V2_API_BASE, json={
            "email": account.email,
            "phone": account.phone,
            "type": "route",
            # Razorpay caps reference_id at 20 characters.
            "reference_id": str(account.restaurant_id)[:20],
            "legal_business_name": account.legal_business_name,
            "business_type": account.business_type,
            "contact_name": account.contact_name,
            "profile": {
                "category": "food",
                "subcategory": "restaurant",
                "addresses": {"registered": {
                    "street1": account.street, "street2": account.street, "city": account.city,
                    "state": account.state, "postal_code": account.postal_code, "country": "IN",
                }},
            },
            "legal_info": {"pan": account.pan},
        })
        return str(body.get("id") or "")

    def create_stakeholder(self, account_id: str, account: Any) -> str:
        body = self._provider._request("POST", f"/accounts/{account_id}/stakeholders", base=V2_API_BASE,
                                       json={"name": account.contact_name, "email": account.email})
        return str(body.get("id") or "")

    def request_route(self, account_id: str) -> ProductState:
        return _product(self._provider._request("POST", f"/accounts/{account_id}/products", base=V2_API_BASE,
                                                json={"product_name": "route", "tnc_accepted": True}))

    def submit_bank(self, account_id: str, product_id: str, *, account_number: str, ifsc: str,
                    beneficiary_name: str) -> ProductState:
        return _product(self._provider._request(
            "PATCH", f"/accounts/{account_id}/products/{product_id}", base=V2_API_BASE,
            json={"settlements": {"account_number": account_number, "ifsc_code": ifsc,
                                  "beneficiary_name": beneficiary_name},
                  "tnc_accepted": True},
        ))

    def fetch_product(self, account_id: str, product_id: str) -> ProductState:
        return _product(self._provider._request("GET", f"/accounts/{account_id}/products/{product_id}",
                                                base=V2_API_BASE))
```

- [ ] **Step 4: Run the tests and watch them pass**

Run: `cd backend && ./.venv/Scripts/python.exe -m unittest tests.test_payout_route_client tests.test_razorpay tests.test_razorpay_payment_links -v`
Expected: all OK. The existing Razorpay suites must still pass with the new `_request` signature.

---

### Task 4: The platform collects, and remembers that it did

**Files:**
- Modify: `app/services/payments/registry.py`, `app/services/payments/service.py`, `app/api/payments.py`
- Create: `app/services/payouts/accounts.py` (only `get_account` and `payout_account_active` for now; Task 7 adds the rest)
- Create: `app/services/payouts/webhooks.py` (a no-op `handle_route_event`; Task 6 fills it in)
- Test: `backend/tests/test_payout_platform_collection.py`

**Interfaces:**
- Consumes: `RazorpayProvider(is_platform=True)`, `RestaurantPayoutAccount`, and settings.
- Produces:
  - `platform_razorpay_provider(*, require_enabled: bool = True) -> RazorpayProvider | None`
  - `platform_collects(db, restaurant_id) -> bool`
  - `provider_for_transaction(db, *, order, transaction) -> PaymentProvider | None`
  - `payout_account_active(db, restaurant_id) -> bool`
  - `handle_platform_razorpay_webhook(db, *, payload, signature) -> dict[str, str]`
  - The route `POST /payments/razorpay/webhook`.
  - `on_platform_account` set on every transaction created.

- [ ] **Step 1: Write the failing test.** The test files import the shared fixture as `from test_payout_ledger import ...`. `unittest discover -s tests` puts `tests/` on `sys.path`, so a bare module import works under discovery. When a file is run as `-m unittest tests.x`, add `sys.path.insert(0, str(Path(__file__).parent))` at the top as well, as below.

```python
"""The platform's Razorpay account takes a restaurant's payment only when it
can pay that restaurant out, and every attempt remembers whose account it was.

Before this, `registry.platform_provider_for` was Stripe only, so a restaurant
without its own Razorpay keys was simply not offered Razorpay — six of the
seven real kitchens. Route needs the platform to collect; the rule here is
that it collects only for a restaurant it can pay.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_payout_ledger import LedgerDatabase, postgres_available  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.models.enums import PaymentMethod, PaymentStatus, PayoutAccountStatus  # noqa: E402
from app.models.payment import PaymentTransaction  # noqa: E402
from app.services.payments import registry  # noqa: E402
from app.services.payments import service as payments  # noqa: E402

PLATFORM = dict(enable_restaurant_payouts=True, razorpay_key_id="rzp_test_platform",
                razorpay_key_secret="platform_secret", razorpay_webhook_secret="whsec_platform")


def settings_with(**overrides):
    return mock.patch("app.services.payments.registry.get_settings",
                      return_value=get_settings().model_copy(update=overrides))


@unittest.skipUnless(postgres_available(), "Postgres is not reachable")
class PlatformCollectionTests(LedgerDatabase):
    def provider(self):
        return registry.provider_for(self.db, restaurant_id=self.restaurant.id, method=PaymentMethod.RAZORPAY)

    def test_no_linked_account_means_no_platform_razorpay(self) -> None:
        with settings_with(**PLATFORM):
            self.assertIsNone(self.provider())

    def test_an_active_linked_account_lets_the_platform_collect(self) -> None:
        self.make_active_account()
        with settings_with(**PLATFORM):
            provider = self.provider()
        self.assertTrue(provider.is_platform)
        self.assertEqual(provider.public_key, "rzp_test_platform")

    def test_payouts_off_means_the_platform_never_collects(self) -> None:
        self.make_active_account()
        with settings_with(**dict(PLATFORM, enable_restaurant_payouts=False)):
            self.assertIsNone(self.provider())

    def test_the_mock_default_key_is_not_an_account(self) -> None:
        self.make_active_account()
        with settings_with(**dict(PLATFORM, razorpay_key_id="rzp_test_mock")):
            self.assertIsNone(self.provider())

    def test_an_account_under_review_cannot_collect_yet(self) -> None:
        account = self.make_active_account()
        account.status = PayoutAccountStatus.UNDER_REVIEW.value
        self.db.commit()
        with settings_with(**PLATFORM):
            self.assertIsNone(self.provider())

    def test_a_platform_payment_still_confirms_with_the_flag_off(self) -> None:
        order = self.make_order(platform=True)
        transaction = self.db.query(PaymentTransaction).filter_by(order_id=order.id).one()
        with settings_with(**dict(PLATFORM, enable_restaurant_payouts=False)):
            provider = registry.provider_for_transaction(self.db, order=order, transaction=transaction)
        self.assertTrue(provider.is_platform)

    def test_the_browsers_confirmation_records_the_payment_id(self) -> None:
        order = self.make_order(platform=True, payment_id="")
        order.payment_status = PaymentStatus.PENDING
        transaction = self.db.query(PaymentTransaction).filter_by(order_id=order.id).one()
        transaction.status = PaymentStatus.PENDING
        self.db.commit()
        signature = hmac.new(b"platform_secret", f"{transaction.provider_intent_id}|pay_777".encode(),
                             hashlib.sha256).hexdigest()
        with settings_with(**PLATFORM), mock.patch.object(payments, "_confirm_in_chat"), \
                mock.patch("app.services.orders.run_order_placed_side_effects"):
            payments.confirm_razorpay_checkout(self.db, order=order,
                                               razorpay_order_id=transaction.provider_intent_id,
                                               razorpay_payment_id="pay_777", razorpay_signature=signature)
        self.db.refresh(transaction)
        self.assertEqual(transaction.provider_payment_id, "pay_777")

    def test_the_platform_webhook_is_verified_with_the_platform_secret(self) -> None:
        body = json.dumps({"id": "evt_1", "event": "transfer.processed", "payload": {}}).encode()
        good = hmac.new(b"whsec_platform", body, hashlib.sha256).hexdigest()
        with settings_with(**PLATFORM):
            self.assertEqual(payments.handle_platform_razorpay_webhook(
                self.db, payload=body, signature=good)["event_id"], "evt_1")
            with self.assertRaises(Exception):
                payments.handle_platform_razorpay_webhook(self.db, payload=body, signature="0" * 64)


if __name__ == "__main__":
    unittest.main()
```

Add the same `sys.path.insert(0, str(Path(__file__).resolve().parent))` line to every later test file that imports `test_payout_ledger`.

- [ ] **Step 2: Run the test and watch it fail**

Run: `cd backend && ./.venv/Scripts/python.exe -m unittest tests.test_payout_platform_collection -v`
Expected: failures and errors. `provider_for` returns None where a provider is expected, and `provider_for_transaction` and `handle_platform_razorpay_webhook` do not exist.

- [ ] **Step 3: Write the implementation**

Create `app/services/payouts/accounts.py` with its first two functions:

```python
"""A restaurant's Razorpay linked account: whether it can be paid, and how it
is opened. Only the platform admin opens or edits one (`api/payouts.py`)."""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.models.enums import PayoutAccountStatus
from app.models.restaurant_payout import RestaurantPayoutAccount


def get_account(db: Session, restaurant_id: uuid.UUID) -> RestaurantPayoutAccount | None:
    return db.get(RestaurantPayoutAccount, restaurant_id)


def payout_account_active(db: Session, restaurant_id: uuid.UUID | None) -> bool:
    if restaurant_id is None:
        return False
    account = get_account(db, restaurant_id)
    return bool(account and account.razorpay_account_id and account.status == PayoutAccountStatus.ACTIVE.value)
```

Create `app/services/payouts/webhooks.py` as a placeholder that Task 6 replaces:

```python
"""Route's own events from the platform webhook."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session


def handle_route_event(db: Session, body: dict[str, Any]) -> None:
    return None
```

In `registry.py`, add after `platform_provider_for`:

```python
#: The Razorpay key `settings.py` ships with so a fresh checkout boots. It is
#: not an account, and treating it as one would put a Razorpay button on a
#: checkout that cannot take a payment.
_MOCK_RAZORPAY_KEY = "rzp_test_mock"


def platform_razorpay_provider(*, require_enabled: bool = True) -> RazorpayProvider | None:
    """The platform's own Razorpay account, used for Route.

    `require_enabled=False` is for money ALREADY taken on it: confirming,
    reconciling and webhooks must keep working after payouts are switched off,
    or a paid order would sit unpaid here.
    """

    settings = get_settings()
    if require_enabled and not settings.enable_restaurant_payouts:
        return None
    key_id = (settings.razorpay_key_id or "").strip()
    if not key_id or key_id == _MOCK_RAZORPAY_KEY:
        return None
    provider = RazorpayProvider(
        key_id=key_id,
        key_secret=settings.razorpay_key_secret,
        webhook_secret=settings.razorpay_webhook_secret,
        is_platform=True,
    )
    return provider if provider.is_configured() else None


def platform_collects(db: Session, restaurant_id: uuid.UUID | None) -> bool:
    """Whether the platform may take this restaurant's Razorpay payments.

    Only when it can pay them out: payouts on, platform keys real, and the
    restaurant's linked account ACTIVE. Anything less and the money would
    land with the platform with no way to pass it on.
    `payments_require_restaurant_account` is deliberately not consulted: it
    guards against the platform silently keeping a restaurant's money, and
    Route is the opposite of that.
    """

    from app.services.payouts.accounts import payout_account_active

    return platform_razorpay_provider() is not None and payout_account_active(db, restaurant_id)


def provider_for_transaction(db: Session, *, order, transaction) -> PaymentProvider | None:
    """The account that took THIS attempt, whatever the restaurant uses now."""

    if transaction is not None and getattr(transaction, "on_platform_account", False):
        return platform_razorpay_provider(require_enabled=False)
    return provider_for(db, restaurant_id=order.restaurant_id, method=order.payment_method)
```

In `provider_for`, inside `if restaurant_id is not None:` and after the own-credentials block (still inside that `if`), add:

```python
        # No keys of its own: the platform collects, if it can pay this
        # restaurant out. See `platform_collects`.
        if method == PaymentMethod.RAZORPAY and platform_collects(db, restaurant_id):
            return platform_razorpay_provider()
```

Add `"platform_collects"`, `"platform_razorpay_provider"` and `"provider_for_transaction"` to `__all__`.

In `payments/service.py`:
1. Import `provider_for_transaction` and `platform_razorpay_provider` from the registry.
2. In `create_payment_intent` and `create_payment_link`, add `on_platform_account=bool(getattr(provider, "is_platform", False)),` to every `PaymentTransaction(...)` construction.
3. In `cancel_payment` and `_reconcile_with_provider`, replace `provider_for(db, restaurant_id=order.restaurant_id, method=order.payment_method)` with `provider_for_transaction(db, order=order, transaction=transaction)`. The transaction is already read in both functions; in `cancel_payment`, move the provider lookup inside the `if transaction is not None` block. In `reap_expired_unpaid_orders`, read `transaction = _latest_transaction(db, order.id)` before resolving the provider, then resolve it with `provider_for_transaction`.
4. Reorder the top of `confirm_razorpay_checkout`. Read the transaction first, resolve the provider from it, then verify the signature exactly as now. Delete the later duplicate transaction check.

```python
    transaction = _latest_transaction(db, order.id)
    if transaction is None or transaction.provider_intent_id != razorpay_order_id:
        # The signature may be genuine but name an order that is not this one.
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail="That payment belongs to a different order.",
        )

    # The account that created this attempt, which since Route may be the
    # platform's rather than the restaurant's.
    provider = provider_for_transaction(db, order=order, transaction=transaction)
    if provider is None or not hasattr(provider, "verify_checkout_signature"):
        raise HTTPException(
            status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Razorpay is not available for this restaurant.",
        )
```

Then add `payment_id=razorpay_payment_id,` to the `WebhookEvent(...)` passed to `_mark_paid`. A transfer is made from a payment id, and this path never recorded one. Record a ruling: the 409 now comes before signature verification. That costs nothing, because the endpoint already requires the order's own customer.

5. Add:

```python
def handle_platform_razorpay_webhook(
    db: Session, *, payload: bytes, signature: str | None
) -> dict[str, str]:
    """Events for the platform's own Razorpay account.

    Payments the platform collected for a restaurant on Route, and Route's own
    events: transfers, settlements, linked accounts. Verified with the
    platform's webhook secret before anything in the body is believed.
    """

    provider = platform_razorpay_provider(require_enabled=False)
    if provider is None:
        raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST,
                            detail="The platform has no Razorpay account configured.")
    try:
        event = provider.parse_webhook(payload=payload, signature=signature)
    except WebhookVerificationError as error:
        raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail=str(error)) from error

    result = _apply_webhook_event(db, provider_name="razorpay_platform", event=event)
    if result.get("status") != "duplicate":
        # Imported lazily: payouts imports this module's registry.
        from app.services.payouts.webhooks import handle_route_event

        handle_route_event(db, event.payload)
    return result
```

In `app/api/payments.py`, import `handle_platform_razorpay_webhook` and add this before `gateway_webhook`:

```python
@router.post("/razorpay/webhook", include_in_schema=False)
async def platform_razorpay_webhook(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    razorpay_signature: Annotated[str | None, Header(alias="X-Razorpay-Signature")] = None,
) -> dict[str, str]:
    """Event sink for the platform's own Razorpay account (Route).

    Unauthenticated, like the other sinks: the signature is the
    authentication, and the raw body is required for it.
    """

    payload = await request.body()
    return handle_platform_razorpay_webhook(db, payload=payload, signature=razorpay_signature)
```

- [ ] **Step 4: Run the tests and watch them pass**

Run: `cd backend && ./.venv/Scripts/python.exe -m unittest tests.test_payout_platform_collection tests.test_payments tests.test_razorpay tests.test_razorpay_payment_links tests.test_payment_accounts tests.test_payment_webhook_url tests.test_refundable_payment_id -v`
Expected: all OK. If an existing test asserted the old confirm order, read its docstring before changing it, and record a ruling.

---

### Task 5: The ledger service

**Files:**
- Create: `backend/app/services/payouts/service.py`
- Test: extend `backend/tests/test_payout_ledger.py`

**Interfaces:**
- Consumes: `split_order`, `RouteClient`, `TransferState`, `payout_account_active`, `get_account` and `platform_razorpay_provider`.
- Produces:
  - `record_paid_order(db, order, transaction) -> RestaurantPayout` (does not commit)
  - `queue_payout_step(db, step: str, order_id) -> None`, where `step` is `"transfer"`, `"release"` or `"reverse"`
  - `transfer(db, order_id, *, client=None) -> RestaurantPayout | None`
  - `release(db, order_id, *, client=None)`
  - `reverse(db, order_id, *, client=None)`
  - `refresh_transfer(db, transfer_id, *, client=None)`
  - `flush_waiting(db, restaurant_id, *, client=None) -> int`
  - `retry_stuck(db, *, client=None) -> int`
  - `retry(db, payout_id) -> RestaurantPayout`
  - `default_client() -> RouteClient | None`

- [ ] **Step 1: Write the failing tests.** Append to `tests/test_payout_ledger.py`, above `if __name__`:

```python
from app.services.payouts import service as payouts  # noqa: E402
from app.services.payouts.route_client import TransferState  # noqa: E402


class FakeClient:
    """Records what it was asked; answers like Razorpay would."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def create_transfer(self, **kwargs):
        self.calls.append(("create", kwargs))
        return TransferState("trf_1", "pending", kwargs["on_hold"], "on_hold" if kwargs["on_hold"] else "pending", "")

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
            payouts.reverse(self.db, order.id, client=client)
        self.assertEqual(client.calls[-1], ("reverse", "trf_1"))
        self.assertEqual(self.row(order).status, PayoutStatus.REVERSED.value)

    def test_cancelling_before_any_transfer_moves_no_money(self) -> None:
        order = self.make_order()
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
```

The `FakeClient` returns `trf_1` for every create. In `test_activation_flushes_what_was_waiting`, the second create therefore writes the same `transfer_id` to a second row. That is harmless here: `transfer_id` is indexed but not unique.

- [ ] **Step 2: Run the tests and watch them fail**

Run: `cd backend && ./.venv/Scripts/python.exe -m unittest tests.test_payout_ledger -v`
Expected: ERROR, `ImportError: cannot import name 'service' from 'app.services.payouts'`

- [ ] **Step 3: Write the implementation.** Create `app/services/payouts/service.py`:

```python
"""Moving one order's share to its restaurant, and recording every step.

Every function here is safe to call twice. Three things make it so:

- **One row per order** (`restaurant_payouts.order_id` is unique).
- **A row lock around every Razorpay call** (`with_for_update`). Two workers
  handed the same order serialise on the row, and the second one finds the
  `transfer_id` the first one wrote.
- **A row that holds a `transfer_id` is never transferred again.** Razorpay
  would accept a second transfer from the same payment as long as the total
  stays under the payment, so this check is the only thing between a retry
  and paying a restaurant twice.

Razorpay is only called from Celery, after the order's own transaction has
committed (`queue_payout_step`), and only with `ENABLE_RESTAURANT_PAYOUTS`
on. With it off, every row is still written and computed, so the screen
shows what would be paid.

Nothing here may cost a sale. The order path calls `record_paid_order` and
`queue_payout_step` inside try/except, and a refusal from Razorpay becomes
`FAILED` on the row, never an error on the order.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, event, or_, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.enums import OrderStatus, PaymentMethod, PayoutStatus
from app.models.order import Order
from app.models.payment import PaymentTransaction
from app.models.restaurant_payout import RestaurantPayout
from app.services.payments.base import PaymentProviderError
from app.services.payouts.accounts import get_account, payout_account_active
from app.services.payouts.split import split_order

logger = logging.getLogger(__name__)

_STEPS = {"transfer", "release", "reverse"}


def default_client():
    """The Route client on the platform's account, or None when it has none."""

    from app.services.payments.registry import platform_razorpay_provider
    from app.services.payouts.route_client import RouteClient

    provider = platform_razorpay_provider(require_enabled=False)
    return RouteClient(provider) if provider is not None else None


def _latest_transaction(db: Session, order_id: uuid.UUID) -> PaymentTransaction | None:
    return db.scalar(
        select(PaymentTransaction)
        .where(PaymentTransaction.order_id == order_id)
        .order_by(PaymentTransaction.created_at.desc())
        .limit(1)
    )


def record_paid_order(db: Session, order: Order, transaction: PaymentTransaction | None) -> RestaurantPayout:
    """Write this order's ledger row, once. Inside the caller's transaction."""

    existing = db.scalar(select(RestaurantPayout).where(RestaurantPayout.order_id == order.id))
    if existing is not None:
        return existing

    split = split_order(order)
    on_platform = bool(transaction is not None and transaction.on_platform_account)
    if order.payment_method == PaymentMethod.COD or not on_platform:
        status, error = PayoutStatus.NOT_APPLICABLE, None
    elif split.blocked_reason:
        status, error = PayoutStatus.BLOCKED, split.blocked_reason
    else:
        status, error = PayoutStatus.WAITING_ACCOUNT, None

    row = RestaurantPayout(
        order_id=order.id,
        restaurant_id=order.restaurant_id,
        payment_id=(transaction.provider_payment_id or "") if transaction is not None else "",
        restaurant_share=split.restaurant_share,
        platform_keeps=split.platform_keeps,
        currency=order.currency or "INR",
        status=status.value,
        last_error=error,
    )
    db.add(row)
    db.flush()
    return row


def queue_payout_step(db: Session, step: str, order_id: uuid.UUID) -> None:
    """Run a step in Celery once the caller's transaction commits. Never raises."""

    if step not in _STEPS:
        raise ValueError(step)
    task = f"app.tasks.payouts.{step}_payout_task"
    kwargs = {"order_id": str(order_id)}

    def _send(_session: Session) -> None:
        try:
            from app.config.celery import celery_app

            celery_app.send_task(task, kwargs=kwargs)
        except Exception:  # noqa: BLE001 - a broker that is down must not undo an order
            logger.warning("Could not queue payout step %s for order %s", step, order_id, exc_info=True)

    event.listen(db, "after_commit", _send, once=True)


def _locked_row(db: Session, order_id: uuid.UUID) -> RestaurantPayout | None:
    return db.scalar(
        select(RestaurantPayout).where(RestaurantPayout.order_id == order_id).with_for_update()
        .execution_options(populate_existing=True)
    )


def _ensure_row(db: Session, order: Order) -> RestaurantPayout:
    row = _locked_row(db, order.id)
    if row is None:
        record_paid_order(db, order, _latest_transaction(db, order.id))
        db.commit()
        row = _locked_row(db, order.id)
    return row


def _fail(db: Session, row: RestaurantPayout, error: PaymentProviderError) -> None:
    row.attempts += 1
    row.last_error = str(error)
    if not error.retryable:
        row.status = PayoutStatus.FAILED.value
    db.commit()


def transfer(db: Session, order_id: uuid.UUID, *, client: Any = None) -> RestaurantPayout | None:
    order = db.get(Order, order_id, populate_existing=True)
    if order is None:
        return None
    row = _ensure_row(db, order)
    if row.status != PayoutStatus.WAITING_ACCOUNT.value or row.transfer_id:
        db.commit()
        return row
    if not get_settings().enable_restaurant_payouts or not payout_account_active(db, order.restaurant_id):
        db.commit()
        return row
    if not row.payment_id:
        # Paid through the browser before the confirmation recorded payment
        # ids, or the webhook carrying it has not arrived yet.
        transaction = _latest_transaction(db, order.id)
        row.payment_id = (transaction.provider_payment_id or "") if transaction is not None else ""
    if not row.payment_id:
        row.last_error = "Waiting for Razorpay's payment id for this order; the webhook will bring it."
        db.commit()
        return row

    client = client or default_client()
    if client is None:
        row.last_error = "The platform has no Razorpay account configured."
        db.commit()
        return row
    account = get_account(db, order.restaurant_id)
    delivered = order.status == OrderStatus.DELIVERED
    try:
        state = client.create_transfer(
            payment_id=row.payment_id, account_id=account.razorpay_account_id,
            amount=row.restaurant_share, currency=row.currency, order_id=order.id, on_hold=not delivered,
        )
    except PaymentProviderError as error:
        _fail(db, row, error)
        if error.retryable:
            raise
        return row

    row.transfer_id = state.transfer_id
    row.attempts += 1
    row.last_error = None
    if delivered:
        row.status = PayoutStatus.RELEASED.value
        row.released_at = datetime.now(UTC)
    else:
        row.status = PayoutStatus.HELD.value
    db.commit()
    return row


def release(db: Session, order_id: uuid.UUID, *, client: Any = None) -> RestaurantPayout | None:
    order = db.get(Order, order_id, populate_existing=True)
    if order is None:
        return None
    row = _ensure_row(db, order)
    if row.status == PayoutStatus.WAITING_ACCOUNT.value:
        db.commit()
        return transfer(db, order_id, client=client)
    if row.status != PayoutStatus.HELD.value or not row.transfer_id or not get_settings().enable_restaurant_payouts:
        db.commit()
        return row
    client = client or default_client()
    if client is None:
        db.commit()
        return row
    try:
        client.release(row.transfer_id)
    except PaymentProviderError as error:
        _fail(db, row, error)
        if error.retryable:
            raise
        return row
    row.status = PayoutStatus.RELEASED.value
    row.released_at = datetime.now(UTC)
    row.last_error = None
    db.commit()
    return row


def reverse(db: Session, order_id: uuid.UUID, *, client: Any = None) -> RestaurantPayout | None:
    order = db.get(Order, order_id, populate_existing=True)
    if order is None:
        return None
    row = _ensure_row(db, order)
    if row.status in {PayoutStatus.WAITING_ACCOUNT.value, PayoutStatus.BLOCKED.value}:
        row.status = PayoutStatus.NOT_APPLICABLE.value
        row.last_error = "Cancelled or refunded before anything was paid out."
        db.commit()
        return row
    if row.status == PayoutStatus.SETTLED.value:
        # Already in the restaurant's bank. Razorpay can claw it back from
        # the linked account's balance, but that is a decision for a person.
        row.last_error = "Cancelled or refunded after the share reached the restaurant's bank; recover it by hand."
        db.commit()
        return row
    if row.status not in {PayoutStatus.HELD.value, PayoutStatus.RELEASED.value} or not row.transfer_id:
        db.commit()
        return row
    if not get_settings().enable_restaurant_payouts:
        row.last_error = "Cancelled while payouts are switched off; reverse this transfer by hand."
        db.commit()
        return row
    client = client or default_client()
    if client is None:
        db.commit()
        return row
    try:
        client.reverse(row.transfer_id)
    except PaymentProviderError as error:
        _fail(db, row, error)
        if error.retryable:
            raise
        return row
    row.status = PayoutStatus.REVERSED.value
    row.reversed_at = datetime.now(UTC)
    row.last_error = None
    db.commit()
    return row


def refresh_transfer(db: Session, transfer_id: str, *, client: Any = None) -> RestaurantPayout | None:
    """A webhook said something happened; ask Razorpay what."""

    if not transfer_id:
        return None
    row = db.scalar(
        select(RestaurantPayout).where(RestaurantPayout.transfer_id == transfer_id).with_for_update()
        .execution_options(populate_existing=True)
    )
    if row is None:
        return None
    client = client or default_client()
    if client is None:
        db.commit()
        return row
    try:
        state = client.fetch_transfer(transfer_id)
    except PaymentProviderError:
        db.commit()
        return row
    now = datetime.now(UTC)
    if state.status in {"reversed", "partially_reversed"}:
        row.status, row.reversed_at = PayoutStatus.REVERSED.value, row.reversed_at or now
    elif state.status == "failed":
        row.status = PayoutStatus.FAILED.value
        row.last_error = state.error or "Razorpay reports the transfer failed."
    elif state.settlement_status == "settled":
        row.status = PayoutStatus.SETTLED.value
        row.settled_at = row.settled_at or now
        row.settlement_id = state.settlement_id
    elif not state.on_hold and row.status == PayoutStatus.HELD.value:
        row.status, row.released_at = PayoutStatus.RELEASED.value, row.released_at or now
    db.commit()
    return row


def flush_waiting(db: Session, restaurant_id: uuid.UUID, *, client: Any = None) -> int:
    """A linked account just became ACTIVE: transfer what was waiting for it."""

    order_ids = db.scalars(
        select(RestaurantPayout.order_id).where(
            RestaurantPayout.restaurant_id == restaurant_id,
            RestaurantPayout.status == PayoutStatus.WAITING_ACCOUNT.value,
        )
    ).all()
    moved = 0
    for order_id in order_ids:
        try:
            row = transfer(db, order_id, client=client)
        except PaymentProviderError:
            continue
        if row is not None and row.transfer_id:
            moved += 1
    return moved


def retry_stuck(db: Session, *, client: Any = None) -> int:
    """The hourly sweep: whatever a lost task or webhook left behind."""

    limit = get_settings().payouts_retry_limit
    cutoff = datetime.now(UTC) - timedelta(minutes=10)
    rows = db.execute(
        select(RestaurantPayout.order_id, RestaurantPayout.status)
        .join(Order, Order.id == RestaurantPayout.order_id)
        .where(RestaurantPayout.attempts < limit)
        .where(or_(
            and_(RestaurantPayout.status == PayoutStatus.WAITING_ACCOUNT.value, RestaurantPayout.created_at < cutoff),
            and_(RestaurantPayout.status == PayoutStatus.HELD.value, Order.status == OrderStatus.DELIVERED),
        ))
    ).all()
    touched = 0
    for order_id, payout_status in rows:
        try:
            if payout_status == PayoutStatus.HELD.value:
                release(db, order_id, client=client)
            else:
                transfer(db, order_id, client=client)
            touched += 1
        except PaymentProviderError:
            continue
    return touched


def retry(db: Session, payout_id: uuid.UUID) -> RestaurantPayout:
    """An admin's Retry on a FAILED or BLOCKED row, once the cause is fixed."""

    row = db.get(RestaurantPayout, payout_id, with_for_update=True, populate_existing=True)
    if row is None:
        raise LookupError("payout not found")
    order = db.get(Order, row.order_id, populate_existing=True)
    if row.status == PayoutStatus.BLOCKED.value:
        split = split_order(order)
        row.restaurant_share, row.platform_keeps = split.restaurant_share, split.platform_keeps
        if split.blocked_reason:
            row.last_error = split.blocked_reason
            db.commit()
            return row
    if row.status in {PayoutStatus.BLOCKED.value, PayoutStatus.FAILED.value} and not row.transfer_id:
        row.status = PayoutStatus.WAITING_ACCOUNT.value
        row.attempts = 0
        row.last_error = None
        queue_payout_step(db, "release" if order.status == OrderStatus.DELIVERED else "transfer", row.order_id)
    db.commit()
    return row
```

- [ ] **Step 4: Run the tests and watch them pass**

Run: `cd backend && ./.venv/Scripts/python.exe -m unittest tests.test_payout_ledger -v`
Expected: all OK.

---

### Task 6: Wiring — the order path, Celery, and the webhook

**Files:**
- Modify: `app/services/payments/service.py` (`_mark_paid`, `_mark_refunded`), `app/services/order_events.py`, `app/config/celery.py`
- Create: `app/tasks/payouts.py`
- Replace: `app/services/payouts/webhooks.py`
- Test: add `WiringTests` to `tests/test_payout_ledger.py`

**Interfaces:**
- Consumes: everything Task 5 produces.
- Produces:
  - Celery tasks `app.tasks.payouts.{transfer,release,reverse}_payout_task(order_id)`, `refresh_transfer_task(transfer_id)`, `flush_waiting_task(restaurant_id)` and `retry_payouts_task()`.
  - `handle_route_event(db, body)`.
  - `after_commit_task(db, task, **kwargs)` in `webhooks.py`, reused by `accounts.py`.

- [ ] **Step 1: Write the failing tests.** Append:

```python
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
```

`record_order_status_event` also queues the realtime push and the print jobs, so the test session may write `print_jobs` rows. That is fine on a throwaway database.

- [ ] **Step 2: Run the tests and watch them fail**

Run: `cd backend && ./.venv/Scripts/python.exe -m unittest tests.test_payout_ledger.WiringTests -v`
Expected: 4 failures. No row is written, nothing is queued, and the account status is unchanged.

- [ ] **Step 3: Write the implementation**

In `_mark_paid`, insert this immediately before the existing `db.add_all([order, transaction])` that follows `order.status = OrderStatus.PLACED`:

```python
    # The restaurant's share, written in the same transaction as PAID so the
    # two cannot disagree, and the transfer queued for after the commit. In a
    # try: a payout problem must never cost a sale.
    try:
        from app.services.payouts.service import queue_payout_step, record_paid_order

        record_paid_order(db, order, transaction)
        queue_payout_step(db, "transfer", order.id)
    except Exception:  # noqa: BLE001
        logger.exception("Could not record the payout for order %s", order.id)
```

Record a ruling here. `record_paid_order` runs a flush inside `_mark_paid`'s transaction. If it raised partway, the session could be left dirty, so wrap only the call in a SAVEPOINT (`with db.begin_nested():`). A failure then rolls back just the payout row and never the payment.

In `_mark_refunded`, before `db.commit()`:

```python
    try:
        from app.services.payouts.service import queue_payout_step

        queue_payout_step(db, "reverse", order.id)
    except Exception:  # noqa: BLE001
        logger.exception("Could not queue the payout reversal for order %s", order.id)
```

In `order_events.record_order_status_event`, after `_queue_print_jobs(...)`:

```python
    # And the restaurant's share: released when the food is handed over,
    # taken back when the order is called off. Queued after commit like the
    # push, and never raising: history and payouts must not break an order.
    if to_status in (OrderStatus.DELIVERED, OrderStatus.CANCELLED):
        try:
            from app.services.payouts.service import queue_payout_step

            queue_payout_step(db, "release" if to_status == OrderStatus.DELIVERED else "reverse", order.id)
        except Exception:  # noqa: BLE001
            logger.exception("Could not queue the payout step for order %s", getattr(order, "id", None))
```

Import `OrderStatus` there if it is not already imported.

Replace `app/services/payouts/webhooks.py`:

```python
"""Route's own events, from the platform webhook.

The same rule as the delivery webhook: an event is a nudge. A transfer event
queues a fetch of the transfer, and the row is moved by what Razorpay says
when asked, never by the body. An account event is the exception, because
the activation status IS the fact and fetching it would return the same
word. It is still applied only to an account id this database already holds.

`settlement.processed` carries a settlement rather than a transfer, so it is
not matched here; the transfer's own event and the hourly sweep record the
settlement instead.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import event as sa_event
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import PayoutAccountStatus
from app.models.restaurant_payout import RestaurantPayoutAccount
from app.services.payouts.route_client import ACCOUNT_STATUS_FOR_ACTIVATION

logger = logging.getLogger(__name__)


def after_commit_task(db: Session, task: str, **kwargs: str) -> None:
    """Queue a Celery task once `db` commits. Never raises."""

    def _send(_session: Session) -> None:
        try:
            from app.config.celery import celery_app

            celery_app.send_task(task, kwargs=kwargs)
        except Exception:  # noqa: BLE001
            logger.warning("Could not queue %s", task, exc_info=True)

    sa_event.listen(db, "after_commit", _send, once=True)


def handle_route_event(db: Session, body: dict[str, Any]) -> None:
    name = str(body.get("event") or "")
    entities = body.get("payload") or {}
    if name.startswith("transfer."):
        transfer = (entities.get("transfer") or {}).get("entity") or {}
        if transfer.get("id"):
            after_commit_task(db, "app.tasks.payouts.refresh_transfer_task", transfer_id=str(transfer["id"]))
            db.commit()
        return
    if name.startswith("product.route.") or name.startswith("account."):
        account_id = str(body.get("account_id") or "")
        product = (entities.get("merchant_product") or {}).get("entity") or {}
        status = ACCOUNT_STATUS_FOR_ACTIVATION.get(str(product.get("activation_status") or ""))
        if not account_id or status is None:
            return
        account = db.scalar(
            select(RestaurantPayoutAccount).where(RestaurantPayoutAccount.razorpay_account_id == account_id)
        )
        if account is None:
            return
        became_active = status == PayoutAccountStatus.ACTIVE and account.status != status.value
        account.status = status.value
        if became_active:
            after_commit_task(db, "app.tasks.payouts.flush_waiting_task", restaurant_id=str(account.restaurant_id))
        db.commit()
```

`handle_route_event` commits so that its after-commit listener fires. The test's own `self.db.commit()` afterwards is then a no-op.

Create `app/tasks/payouts.py`, using the same session factory as `app/tasks/delivery.py`. Check that file and use its import and its with-pattern:

```python
"""Payout steps, run after the order's own transaction has committed.

A retryable Razorpay error (network, 5xx) is retried a few times with
backoff; a refusal is written onto the row as FAILED by the service and not
retried here. The hourly sweep is the backstop for both.
"""

from __future__ import annotations

import uuid

from app.config.celery import celery_app
from app.config.database import SessionLocal
from app.services.payments.base import PaymentProviderError
from app.services.payouts import service

_RETRY = dict(autoretry_for=(PaymentProviderError,), retry_backoff=30, retry_kwargs={"max_retries": 3})


@celery_app.task(name="app.tasks.payouts.transfer_payout_task", **_RETRY)
def transfer_payout_task(order_id: str) -> str:
    with SessionLocal() as db:
        row = service.transfer(db, uuid.UUID(order_id))
        return row.status if row else "missing"


@celery_app.task(name="app.tasks.payouts.release_payout_task", **_RETRY)
def release_payout_task(order_id: str) -> str:
    with SessionLocal() as db:
        row = service.release(db, uuid.UUID(order_id))
        return row.status if row else "missing"


@celery_app.task(name="app.tasks.payouts.reverse_payout_task", **_RETRY)
def reverse_payout_task(order_id: str) -> str:
    with SessionLocal() as db:
        row = service.reverse(db, uuid.UUID(order_id))
        return row.status if row else "missing"


@celery_app.task(name="app.tasks.payouts.refresh_transfer_task")
def refresh_transfer_task(transfer_id: str) -> str:
    with SessionLocal() as db:
        row = service.refresh_transfer(db, transfer_id)
        return row.status if row else "missing"


@celery_app.task(name="app.tasks.payouts.flush_waiting_task")
def flush_waiting_task(restaurant_id: str) -> int:
    with SessionLocal() as db:
        return service.flush_waiting(db, uuid.UUID(restaurant_id))


@celery_app.task(name="app.tasks.payouts.retry_payouts_task")
def retry_payouts_task() -> int:
    with SessionLocal() as db:
        return service.retry_stuck(db)
```

In `app/config/celery.py`, add `"app.tasks.payouts"` to `include`, plus this beat entry:

```python
        # The payout backstop: a transfer whose task was lost, a hold whose
        # release was lost. Hourly rather than daily, because it is a
        # restaurant's money waiting, and the sweep calls Razorpay only for a
        # row that needs it.
        "retry-payouts": {
            "task": "app.tasks.payouts.retry_payouts_task",
            "schedule": crontab(minute="17"),
        },
```

Record a ruling: the sweep runs hourly, where the spec said daily.

- [ ] **Step 4: Run the tests and watch them pass**

Run: `cd backend && ./.venv/Scripts/python.exe -m unittest tests.test_payout_ledger tests.test_payout_platform_collection tests.test_payments tests.test_delivery_tracking -v`
Expected: all OK.

---

### Task 7: Linked-account onboarding and the payouts API

**Files:**
- Modify: `app/services/payouts/accounts.py` (add onboarding)
- Create: `app/schemas/payout.py`, `app/api/payouts.py`
- Modify: `app/api/__init__.py`
- Test: `tests/test_payout_accounts.py`, `tests/test_payout_api.py`

**Interfaces:**
- Produces in the service:
  - `PayoutAccountInput` (pydantic, defined in schemas)
  - `save_draft(db, restaurant_id, data, actor_id) -> RestaurantPayoutAccount`
  - `submit(db, restaurant_id, client) -> RestaurantPayoutAccount`
  - `refresh_status(db, restaurant_id, client) -> RestaurantPayoutAccount`
  - `describe(account) -> dict`
- Produces over HTTP:
  - `GET /payouts?restaurant_id=&date_from=&date_to=&status=` returns a `PayoutListResponse`.
  - `POST /payouts/{payout_id}/retry` (admin only).
  - `GET /payouts/account?restaurant_id=` returns a `PayoutAccountResponse` or null.
  - `PUT /payouts/account?restaurant_id=`, `POST /payouts/account/submit?restaurant_id=` and `POST /payouts/account/refresh?restaurant_id=` (all admin only).

- [ ] **Step 1: Write the failing tests**

`tests/test_payout_accounts.py`:

```python
"""Opening a restaurant's linked account: validation, encryption, and the
four Razorpay calls, each made once."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_payout_ledger import LedgerDatabase, postgres_available  # noqa: E402

from app.models.enums import PayoutAccountStatus  # noqa: E402
from app.schemas.payout import PayoutAccountInput  # noqa: E402
from app.services.payouts import accounts  # noqa: E402
from app.services.payouts.route_client import ProductState  # noqa: E402

GOOD = dict(legal_business_name="Darshan Foods", business_type="proprietorship", pan="ABCDE1234F",
            contact_name="Darshan Patel", email="d@x.in", phone="9876543210", street="1 Ring Road",
            city="Surat", state="Gujarat", postal_code="395007", bank_account_number="123456789012",
            ifsc="HDFC0000123", beneficiary_name="Darshan Foods")


class InputTests(unittest.TestCase):
    def test_a_bad_pan_ifsc_pin_or_account_number_is_refused(self) -> None:
        for field, value in (("pan", "ABC123"), ("ifsc", "HDFC123"), ("postal_code", "39"),
                             ("bank_account_number", "12ab")):
            with self.assertRaises(ValueError, msg=field):
                PayoutAccountInput(**dict(GOOD, **{field: value}))

    def test_a_lowercase_pan_is_the_same_pan(self) -> None:
        self.assertEqual(PayoutAccountInput(**dict(GOOD, pan="abcde1234f")).pan, "ABCDE1234F")


@unittest.skipUnless(postgres_available(), "Postgres is not reachable")
class AccountTests(LedgerDatabase):
    def test_a_draft_keeps_only_the_last_four_in_the_clear(self) -> None:
        row = accounts.save_draft(self.db, self.restaurant.id, PayoutAccountInput(**GOOD), self.owner.id)
        self.assertEqual(row.bank_account_last4, "9012")
        self.assertNotIn("123456789012", row.bank_account_number_encrypted)
        self.assertNotIn("bank_account_number", accounts.describe(row))

    def test_an_active_account_cannot_be_edited(self) -> None:
        account = self.make_active_account()
        with self.assertRaises(ValueError):
            accounts.save_draft(self.db, account.restaurant_id, PayoutAccountInput(**GOOD), self.owner.id)

    def test_submitting_makes_each_call_once(self) -> None:
        accounts.save_draft(self.db, self.restaurant.id, PayoutAccountInput(**GOOD), self.owner.id)
        client = mock.Mock()
        client.create_account.return_value = "acc_1"
        client.create_stakeholder.return_value = "sth_1"
        client.request_route.return_value = ProductState("acc_prd_1", "requested", [])
        client.submit_bank.return_value = ProductState("acc_prd_1", "needs_clarification", ["ifsc: field_missing"])
        row = accounts.submit(self.db, self.restaurant.id, client)
        self.assertEqual((row.razorpay_account_id, row.product_id, row.status),
                         ("acc_1", "acc_prd_1", PayoutAccountStatus.NEEDS_CLARIFICATION.value))
        client.submit_bank.assert_called_once_with("acc_1", "acc_prd_1", account_number="123456789012",
                                                   ifsc="HDFC0000123", beneficiary_name="Darshan Foods")
        # Submitting again after a correction does not open a second account.
        accounts.submit(self.db, self.restaurant.id, client)
        client.create_account.assert_called_once()
        client.request_route.assert_called_once()

    def test_a_refusal_is_kept_on_the_row(self) -> None:
        from app.services.payments.base import PaymentProviderError
        accounts.save_draft(self.db, self.restaurant.id, PayoutAccountInput(**GOOD), self.owner.id)
        client = mock.Mock()
        client.create_account.side_effect = PaymentProviderError("Razorpay refused this request: invalid PAN",
                                                                 retryable=False)
        with self.assertRaises(PaymentProviderError):
            accounts.submit(self.db, self.restaurant.id, client)
        self.db.expire_all()
        self.assertIn("invalid PAN", accounts.get_account(self.db, self.restaurant.id).last_error)

    def test_refresh_that_finds_it_active_flushes_the_waiting(self) -> None:
        account = self.make_active_account()
        account.status = PayoutAccountStatus.UNDER_REVIEW.value
        self.db.commit()
        client = mock.Mock()
        client.fetch_product.return_value = ProductState("acc_prd_1", "activated", [])
        accounts.refresh_status(self.db, self.restaurant.id, client)
        self.assertIn("app.tasks.payouts.flush_waiting_task", [c.args[0] for c in self.sent.call_args_list])


if __name__ == "__main__":
    unittest.main()
```

`tests/test_payout_api.py`:

```python
"""Who may see and change which payouts. Owners see their own, without the
platform's half; only an admin touches a linked account."""

from __future__ import annotations

import sys
import unittest
import uuid
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_payout_ledger import D, LedgerDatabase, postgres_available  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.config.database import get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models.enums import PayoutStatus, UserRole  # noqa: E402
from app.models.restaurant_payout import RestaurantPayout  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services.auth import get_current_user  # noqa: E402

PREFIX = get_settings().api_v1_prefix.rstrip("/")


@unittest.skipUnless(postgres_available(), "Postgres is not reachable")
class PayoutApiTests(LedgerDatabase):
    def setUp(self) -> None:
        super().setUp()
        self.admin = User(id=uuid.uuid4(), email=f"a{uuid.uuid4().hex[:6]}@x.in", full_name="Admin",
                          hashed_password="x", role=UserRole.ADMIN)
        self.db.add(self.admin)
        self.db.commit()
        order = self.make_order()
        self.payout = RestaurantPayout(order_id=order.id, restaurant_id=self.restaurant.id,
                                       restaurant_share=D("496.00"), platform_keeps=D("102.20"), currency="INR",
                                       status=PayoutStatus.FAILED.value, last_error="nope")
        self.db.add(self.payout)
        self.db.commit()
        app.dependency_overrides[get_db] = lambda: self.db
        self.addCleanup(app.dependency_overrides.clear)
        self.http = TestClient(app)

    def as_user(self, user) -> None:
        app.dependency_overrides[get_current_user] = lambda: user

    def test_an_owner_sees_their_share_and_not_the_platforms(self) -> None:
        self.as_user(self.owner)
        body = self.http.get(f"{PREFIX}/payouts").json()
        self.assertEqual(body["rows"][0]["restaurant_share"], "496.00")
        self.assertIsNone(body["rows"][0]["platform_keeps"])

    def test_an_owner_cannot_name_another_restaurant(self) -> None:
        self.as_user(self.owner)
        self.assertEqual(self.http.get(f"{PREFIX}/payouts?restaurant_id={uuid.uuid4()}").status_code, 403)
        self.assertEqual(self.http.get(f"{PREFIX}/payouts/account?restaurant_id={uuid.uuid4()}").status_code, 403)

    def test_an_owner_cannot_retry_or_edit(self) -> None:
        self.as_user(self.owner)
        self.assertEqual(self.http.post(f"{PREFIX}/payouts/{self.payout.id}/retry").status_code, 403)
        self.assertIn(self.http.put(f"{PREFIX}/payouts/account", json={}).status_code, (403, 422))

    def test_an_admin_sees_both_halves_and_a_summary(self) -> None:
        self.as_user(self.admin)
        body = self.http.get(f"{PREFIX}/payouts?restaurant_id={self.restaurant.id}").json()
        self.assertEqual(body["rows"][0]["platform_keeps"], "102.20")
        self.assertEqual(body["summary"]["problems"]["count"], 1)
        self.assertFalse(body["payouts_enabled"])

    def test_an_admin_must_name_a_restaurant_for_its_account(self) -> None:
        self.as_user(self.admin)
        self.assertEqual(self.http.get(f"{PREFIX}/payouts/account").status_code, 400)


if __name__ == "__main__":
    unittest.main()
```

Check how `resolve_owner_restaurant_id` finds an owner's restaurant (`Restaurant.owner_id`). The fixture sets `owner_id`, so it resolves.

- [ ] **Step 2: Run the tests and watch them fail**

Run: `cd backend && ./.venv/Scripts/python.exe -m unittest tests.test_payout_accounts tests.test_payout_api -v`
Expected: ERROR, `ModuleNotFoundError: No module named 'app.schemas.payout'`

- [ ] **Step 3: Write the implementation**

`app/schemas/payout.py`:

```python
"""Payouts and linked accounts on the wire. See `api/payouts.py`."""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, field_validator

_PAN = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")
_IFSC = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")
BUSINESS_TYPES = {"proprietorship", "partnership", "private_limited", "public_limited", "llp", "individual"}


class PayoutAccountInput(BaseModel):
    """What the admin types to open a restaurant's linked account.

    Checked here in the shape Razorpay checks it, so a typo is caught on this
    screen rather than coming back from Razorpay a day later as
    NEEDS_CLARIFICATION.
    """

    legal_business_name: str
    business_type: str = "proprietorship"
    pan: str
    contact_name: str
    email: str
    phone: str
    street: str
    city: str
    state: str
    postal_code: str
    bank_account_number: str
    ifsc: str
    beneficiary_name: str

    @field_validator("pan", "ifsc", mode="before")
    @classmethod
    def _upper(cls, value: str) -> str:
        return str(value or "").strip().upper()

    @field_validator("pan")
    @classmethod
    def _pan(cls, value: str) -> str:
        if not _PAN.match(value):
            raise ValueError("A PAN is five letters, four digits and a letter, like ABCDE1234F.")
        return value

    @field_validator("ifsc")
    @classmethod
    def _ifsc(cls, value: str) -> str:
        if not _IFSC.match(value):
            raise ValueError("An IFSC is four letters, a zero, then six letters or digits, like HDFC0001234.")
        return value

    @field_validator("postal_code")
    @classmethod
    def _postal(cls, value: str) -> str:
        value = str(value or "").strip()
        if not re.fullmatch(r"[1-9][0-9]{5}", value):
            raise ValueError("A PIN code is six digits.")
        return value

    @field_validator("bank_account_number")
    @classmethod
    def _account(cls, value: str) -> str:
        value = re.sub(r"\s", "", str(value or ""))
        if not re.fullmatch(r"[0-9]{9,18}", value):
            raise ValueError("A bank account number is 9 to 18 digits.")
        return value

    @field_validator("business_type")
    @classmethod
    def _type(cls, value: str) -> str:
        if value not in BUSINESS_TYPES:
            raise ValueError(f"Business type must be one of: {', '.join(sorted(BUSINESS_TYPES))}.")
        return value

    @field_validator("legal_business_name", "contact_name", "email", "phone", "street", "city", "state",
                     "beneficiary_name")
    @classmethod
    def _required(cls, value: str) -> str:
        value = str(value or "").strip()
        if not value:
            raise ValueError("This is required.")
        return value


class PayoutAccountResponse(BaseModel):
    restaurant_id: uuid.UUID
    status: str
    razorpay_account_id: str
    legal_business_name: str
    business_type: str
    pan: str
    contact_name: str
    email: str
    phone: str
    street: str
    city: str
    state: str
    postal_code: str
    bank_account_last4: str
    ifsc: str
    beneficiary_name: str
    requirements: list[str]
    last_error: str | None
    updated_at: datetime | None


class PayoutRow(BaseModel):
    id: uuid.UUID
    order_id: uuid.UUID
    order_placed_at: datetime | None
    restaurant_id: uuid.UUID
    restaurant_name: str
    restaurant_share: Decimal
    #: None for an owner: with the share and the total, it would give away
    #: the commission.
    platform_keeps: Decimal | None
    currency: str
    status: str
    transfer_id: str
    last_error: str | None
    released_at: datetime | None
    settled_at: datetime | None


class PayoutBucket(BaseModel):
    count: int
    amount: Decimal


class PayoutSummary(BaseModel):
    held: PayoutBucket
    released: PayoutBucket
    settled: PayoutBucket
    waiting: PayoutBucket
    problems: PayoutBucket
    not_applicable: PayoutBucket


class PayoutListResponse(BaseModel):
    currency: str
    payouts_enabled: bool
    summary: PayoutSummary
    rows: list[PayoutRow]
```

Pydantic's `ValidationError` subclasses `ValueError`, so `assertRaises(ValueError)` holds. Confirm that `Decimal` serialises as the string `"496.00"`; that is how this repo's other responses do it. If it does not, compare the value with `Decimal(...)` in the test and record a ruling.

Add to `app/services/payouts/accounts.py`, merging the imports with the existing ones:

```python
from app.services.payments.base import PaymentProviderError
from app.services.payouts.route_client import ACCOUNT_STATUS_FOR_ACTIVATION
from app.services.secrets import decrypt_secret, encrypt_secret

#: Statuses in which the admin may still change what Razorpay will be sent.
_EDITABLE = {PayoutAccountStatus.DRAFT.value, PayoutAccountStatus.NEEDS_CLARIFICATION.value}


def save_draft(db, restaurant_id, data, actor_id) -> RestaurantPayoutAccount:
    account = get_account(db, restaurant_id)
    if account is None:
        account = RestaurantPayoutAccount(restaurant_id=restaurant_id)
        db.add(account)
    elif account.status not in _EDITABLE:
        raise ValueError(
            "This account is with Razorpay already; it can be changed only if Razorpay asks for a correction."
        )
    for name in ("legal_business_name", "business_type", "pan", "contact_name", "email", "phone",
                 "street", "city", "state", "postal_code", "ifsc", "beneficiary_name"):
        setattr(account, name, getattr(data, name))
    account.bank_account_number_encrypted = encrypt_secret(data.bank_account_number)
    account.bank_account_last4 = data.bank_account_number[-4:]
    account.updated_by_user_id = actor_id
    db.commit()
    return account


def _apply_product(account, product) -> bool:
    """Write Razorpay's word onto the row; True when it just became ACTIVE."""

    status = ACCOUNT_STATUS_FOR_ACTIVATION.get(product.activation_status)
    if product.product_id:
        account.product_id = product.product_id
    account.requirements = list(product.requirements)
    if status is None:
        return False
    became_active = status == PayoutAccountStatus.ACTIVE and account.status != status.value
    account.status = status.value
    return became_active


def _flush_after_commit(db, restaurant_id) -> None:
    from app.services.payouts.webhooks import after_commit_task

    after_commit_task(db, "app.tasks.payouts.flush_waiting_task", restaurant_id=str(restaurant_id))


def submit(db, restaurant_id, client) -> RestaurantPayoutAccount:
    """Open (or correct) the linked account with Razorpay. Each step once.

    Every id is written to the row as soon as Razorpay returns it, so a
    failure halfway resumes from where it stopped rather than opening a
    second account for the same restaurant.
    """

    account = get_account(db, restaurant_id)
    if account is None or not account.bank_account_number_encrypted:
        raise ValueError("Save the restaurant's details and bank account first.")
    try:
        if not account.razorpay_account_id:
            account.razorpay_account_id = client.create_account(account)
            db.commit()
        if not account.stakeholder_id:
            account.stakeholder_id = client.create_stakeholder(account.razorpay_account_id, account)
            db.commit()
        if not account.product_id:
            _apply_product(account, client.request_route(account.razorpay_account_id))
            db.commit()
        product = client.submit_bank(
            account.razorpay_account_id, account.product_id,
            account_number=decrypt_secret(account.bank_account_number_encrypted),
            ifsc=account.ifsc, beneficiary_name=account.beneficiary_name,
        )
    except PaymentProviderError as error:
        account.last_error = str(error)
        db.commit()
        raise
    account.last_error = None
    if _apply_product(account, product):
        _flush_after_commit(db, restaurant_id)
    db.commit()
    return account


def refresh_status(db, restaurant_id, client) -> RestaurantPayoutAccount:
    account = get_account(db, restaurant_id)
    if account is None or not account.razorpay_account_id or not account.product_id:
        raise ValueError("This restaurant's account has not been sent to Razorpay yet.")
    if _apply_product(account, client.fetch_product(account.razorpay_account_id, account.product_id)):
        _flush_after_commit(db, restaurant_id)
    db.commit()
    return account


def describe(account) -> dict:
    """What a screen may know. Never the bank account number."""

    return {
        "restaurant_id": account.restaurant_id, "status": account.status,
        "razorpay_account_id": account.razorpay_account_id,
        "legal_business_name": account.legal_business_name, "business_type": account.business_type,
        "pan": account.pan, "contact_name": account.contact_name, "email": account.email,
        "phone": account.phone, "street": account.street, "city": account.city, "state": account.state,
        "postal_code": account.postal_code, "bank_account_last4": account.bank_account_last4,
        "ifsc": account.ifsc, "beneficiary_name": account.beneficiary_name,
        "requirements": list(account.requirements or []), "last_error": account.last_error,
        "updated_at": account.updated_at,
    }
```

`app/api/payouts.py`:

```python
"""Payouts: what each restaurant is owed and where it is, and its linked
account.

One screen for both roles, like the rest of the panel. An OWNER is pinned to
their restaurant and may not name another (403). An ADMIN may list across
restaurants, leaving out demo kitchens unless one is named, and must name one
for anything about a single account (400). Only an admin changes anything.
An owner never sees `platform_keeps`, which with their share and the order
total would give the commission away.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.config.database import get_db
from app.models.enums import PayoutStatus, UserRole
from app.models.order import Order
from app.models.restaurant import Restaurant
from app.models.restaurant_payout import RestaurantPayout
from app.models.user import User
from app.schemas.payout import (
    PayoutAccountInput, PayoutAccountResponse, PayoutBucket, PayoutListResponse, PayoutRow, PayoutSummary,
)
from app.services.auth import get_current_user, resolve_owner_restaurant_id
from app.services.payments.base import PaymentProviderError
from app.services.payouts import accounts, service

router = APIRouter(prefix="/payouts", tags=["payouts"])

_BUCKETS = {
    "held": {PayoutStatus.HELD.value},
    "released": {PayoutStatus.RELEASED.value},
    "settled": {PayoutStatus.SETTLED.value},
    "waiting": {PayoutStatus.WAITING_ACCOUNT.value},
    "problems": {PayoutStatus.FAILED.value, PayoutStatus.BLOCKED.value},
    "not_applicable": {PayoutStatus.NOT_APPLICABLE.value, PayoutStatus.REVERSED.value},
}


def _staff(user: Annotated[User, Depends(get_current_user)]) -> User:
    if user.role not in (UserRole.ADMIN, UserRole.OWNER):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not allowed")
    return user


def _admin(user: Annotated[User, Depends(get_current_user)]) -> User:
    if user.role != UserRole.ADMIN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the platform admin can do this.")
    return user


def _scope(db: Session, user: User, restaurant_id: uuid.UUID | None, *, required: bool) -> uuid.UUID | None:
    if user.role == UserRole.OWNER:
        own = resolve_owner_restaurant_id(db, user)
        if restaurant_id is not None and restaurant_id != own:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="That is not your restaurant.")
        return own
    if required and restaurant_id is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="restaurant_id is required.")
    return restaurant_id


def _client():
    client = service.default_client()
    if client is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail="The platform's Razorpay keys are not configured.")
    return client


@router.get("", response_model=PayoutListResponse)
def list_payouts(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(_staff)],
    restaurant_id: uuid.UUID | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
) -> PayoutListResponse:
    scoped = _scope(db, user, restaurant_id, required=False)
    query = (
        select(RestaurantPayout, Order.placed_at, Restaurant.name)
        .join(Order, Order.id == RestaurantPayout.order_id)
        .join(Restaurant, Restaurant.id == RestaurantPayout.restaurant_id)
    )
    if scoped is not None:
        query = query.where(RestaurantPayout.restaurant_id == scoped)
    else:
        query = query.where(Restaurant.is_demo.is_(False))
    if date_from is not None:
        query = query.where(Order.placed_at >= datetime.combine(date_from, time.min))
    if date_to is not None:
        query = query.where(Order.placed_at < datetime.combine(date_to + timedelta(days=1), time.min))
    if status_filter:
        query = query.where(RestaurantPayout.status == status_filter)
    found = db.execute(query.order_by(Order.placed_at.desc()).limit(1000)).all()

    owner = user.role == UserRole.OWNER
    rows = [
        PayoutRow(
            id=p.id, order_id=p.order_id, order_placed_at=placed_at, restaurant_id=p.restaurant_id,
            restaurant_name=name, restaurant_share=p.restaurant_share,
            platform_keeps=None if owner else p.platform_keeps, currency=p.currency, status=p.status,
            transfer_id=p.transfer_id, last_error=p.last_error, released_at=p.released_at,
            settled_at=p.settled_at,
        )
        for p, placed_at, name in found
    ]
    summary = {
        key: PayoutBucket(
            count=sum(1 for r in rows if r.status in statuses),
            amount=sum((r.restaurant_share for r in rows if r.status in statuses), Decimal("0.00")),
        )
        for key, statuses in _BUCKETS.items()
    }
    return PayoutListResponse(
        currency=rows[0].currency if rows else "INR",
        payouts_enabled=get_settings().enable_restaurant_payouts,
        summary=PayoutSummary(**summary),
        rows=rows,
    )


@router.post("/{payout_id}/retry", response_model=dict)
def retry_payout(payout_id: uuid.UUID, db: Annotated[Session, Depends(get_db)],
                 _user: Annotated[User, Depends(_admin)]) -> dict:
    try:
        row = service.retry(db, payout_id)
    except LookupError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Payout not found") from error
    return {"status": row.status, "last_error": row.last_error}


@router.get("/account", response_model=PayoutAccountResponse | None)
def get_payout_account(db: Annotated[Session, Depends(get_db)], user: Annotated[User, Depends(_staff)],
                       restaurant_id: uuid.UUID | None = None):
    account = accounts.get_account(db, _scope(db, user, restaurant_id, required=True))
    return accounts.describe(account) if account is not None else None


@router.put("/account", response_model=PayoutAccountResponse)
def save_payout_account(payload: PayoutAccountInput, db: Annotated[Session, Depends(get_db)],
                        user: Annotated[User, Depends(_admin)], restaurant_id: uuid.UUID | None = None):
    scoped = _scope(db, user, restaurant_id, required=True)
    try:
        return accounts.describe(accounts.save_draft(db, scoped, payload, user.id))
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error


@router.post("/account/submit", response_model=PayoutAccountResponse)
def submit_payout_account(db: Annotated[Session, Depends(get_db)], user: Annotated[User, Depends(_admin)],
                          restaurant_id: uuid.UUID | None = None):
    scoped = _scope(db, user, restaurant_id, required=True)
    try:
        return accounts.describe(accounts.submit(db, scoped, _client()))
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    except PaymentProviderError as error:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(error)) from error


@router.post("/account/refresh", response_model=PayoutAccountResponse)
def refresh_payout_account(db: Annotated[Session, Depends(get_db)], user: Annotated[User, Depends(_admin)],
                           restaurant_id: uuid.UUID | None = None):
    scoped = _scope(db, user, restaurant_id, required=True)
    try:
        return accounts.describe(accounts.refresh_status(db, scoped, _client()))
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    except PaymentProviderError as error:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(error)) from error
```

Register `payouts_router` in `app/api/__init__.py`, beside `payments_router`, following that file's import pattern.

- [ ] **Step 4: Run the tests and watch them pass**

Run: `cd backend && ./.venv/Scripts/python.exe -m unittest tests.test_payout_accounts tests.test_payout_api -v`
Expected: all OK.

---

### Task 8: The Payouts screen

**Files:**
- Create: `frontend-admin/src/services/payouts.ts`, `frontend-admin/src/services/payouts.test.ts`, `frontend-admin/src/pages/PayoutsPage.tsx`, `frontend-admin/src/components/PayoutAccountPanel.tsx`
- Modify: `frontend-admin/src/types/app.ts`, `frontend-admin/src/services/api.ts`, `frontend-admin/src/routes.tsx`

**Interfaces:**
- Consumes: the HTTP contract from Task 7.
- Produces:
  - `PAYOUT_STATUS_META`
  - `ACCOUNT_STATUS_META`
  - `payoutsCsv(rows, isAdmin) -> string`
  - `accountInputErrors(input)`
  - `periodQuery(range) -> {date_from, date_to}`

- [ ] **Step 1: Write the failing test** `src/services/payouts.test.ts`:

```ts
import { describe, expect, it } from "vitest";

import { ACCOUNT_STATUS_META, PAYOUT_STATUS_META, accountInputErrors, payoutsCsv, periodQuery } from "./payouts";
import type { PayoutAccountInput, PayoutRow, PayoutStatus } from "../types/app";

const row: PayoutRow = {
  id: "p1", order_id: "o1", order_placed_at: "2026-10-05T10:00:00Z", restaurant_id: "r1",
  restaurant_name: "Darshan, Surat", restaurant_share: "496.00", platform_keeps: "102.20", currency: "INR",
  status: "HELD", transfer_id: "trf_1", last_error: null, released_at: null, settled_at: null,
};

const good: PayoutAccountInput = {
  legal_business_name: "Darshan Foods", business_type: "proprietorship", pan: "ABCDE1234F",
  contact_name: "Darshan", email: "d@x.in", phone: "9876543210", street: "1 Road", city: "Surat",
  state: "Gujarat", postal_code: "395007", bank_account_number: "123456789012", ifsc: "HDFC0000123",
  beneficiary_name: "Darshan Foods",
};

const STATUSES: PayoutStatus[] = [
  "WAITING_ACCOUNT", "HELD", "RELEASED", "SETTLED", "REVERSED", "FAILED", "BLOCKED", "NOT_APPLICABLE",
];

describe("payout statuses", () => {
  it("names every status for both readers", () => {
    for (const status of STATUSES) {
      expect(PAYOUT_STATUS_META[status].label).toBeTruthy();
      expect(PAYOUT_STATUS_META[status].ownerLabel).toBeTruthy();
    }
    expect(PAYOUT_STATUS_META.SETTLED.ownerLabel).toBe("In your bank");
    expect(ACCOUNT_STATUS_META.ACTIVE.label).toBe("Active");
  });
});

describe("payoutsCsv", () => {
  it("quotes a comma and gives the admin both halves", () => {
    const csv = payoutsCsv([row], true);
    expect(csv.split("\n")[0]).toContain("Platform keeps");
    expect(csv).toContain('"Darshan, Surat"');
    expect(csv).toContain("102.20");
  });

  it("never gives the owner the platform's half", () => {
    const csv = payoutsCsv([row], false);
    expect(csv).not.toContain("Platform keeps");
    expect(csv).not.toContain("102.20");
  });
});

describe("accountInputErrors", () => {
  it("accepts a good form", () => {
    expect(accountInputErrors(good)).toEqual({});
  });

  it("says what is wrong with a PAN, an IFSC, a PIN and an account number", () => {
    const errors = accountInputErrors({ ...good, pan: "ABC", ifsc: "HDFC123", postal_code: "39", bank_account_number: "12ab" });
    expect(Object.keys(errors).sort()).toEqual(["bank_account_number", "ifsc", "pan", "postal_code"]);
  });

  it("treats a lowercase PAN as the same PAN", () => {
    expect(accountInputErrors({ ...good, pan: "abcde1234f" })).toEqual({});
  });
});

describe("periodQuery", () => {
  it("sends whole days, the end day included", () => {
    const query = periodQuery({ start: new Date(2026, 9, 1), end: new Date(2026, 9, 6) });
    expect(query).toEqual({ date_from: "2026-10-01", date_to: "2026-10-05" });
  });
});
```

- [ ] **Step 2: Run the test and watch it fail**

Run: `cd frontend-admin && npx vitest run src/services/payouts.test.ts`
Expected: FAIL, with `Failed to resolve import "./payouts"`

- [ ] **Step 3: Write the implementation**

Add to `src/types/app.ts`:

```ts
export type PayoutStatus =
  | "WAITING_ACCOUNT" | "HELD" | "RELEASED" | "SETTLED" | "REVERSED" | "FAILED" | "BLOCKED" | "NOT_APPLICABLE";
export type PayoutAccountStatus =
  | "DRAFT" | "SUBMITTED" | "UNDER_REVIEW" | "NEEDS_CLARIFICATION" | "ACTIVE" | "SUSPENDED";

export interface PayoutRow {
  id: string;
  order_id: string;
  order_placed_at: string | null;
  restaurant_id: string;
  restaurant_name: string;
  restaurant_share: string;
  /** Null for an owner: with the share and the total it would give the commission away. */
  platform_keeps: string | null;
  currency: string;
  status: PayoutStatus;
  transfer_id: string;
  last_error: string | null;
  released_at: string | null;
  settled_at: string | null;
}

export interface PayoutBucket {
  count: number;
  amount: string;
}

export interface PayoutList {
  currency: string;
  payouts_enabled: boolean;
  summary: Record<"held" | "released" | "settled" | "waiting" | "problems" | "not_applicable", PayoutBucket>;
  rows: PayoutRow[];
}

export interface PayoutAccountInput {
  legal_business_name: string;
  business_type: string;
  pan: string;
  contact_name: string;
  email: string;
  phone: string;
  street: string;
  city: string;
  state: string;
  postal_code: string;
  bank_account_number: string;
  ifsc: string;
  beneficiary_name: string;
}

export interface PayoutAccount extends Omit<PayoutAccountInput, "bank_account_number"> {
  restaurant_id: string;
  status: PayoutAccountStatus;
  razorpay_account_id: string;
  bank_account_last4: string;
  requirements: string[];
  last_error: string | null;
  updated_at: string | null;
}
```

Add to the `api` object in `src/services/api.ts`, beside `getCommissionReport`, and add the four types to the file's type import:

```ts
  getPayouts(token: string, query: { restaurant_id?: string; date_from?: string; date_to?: string }): Promise<PayoutList> {
    const params = new URLSearchParams();
    for (const [key, value] of Object.entries(query)) {
      if (value) params.set(key, value);
    }
    return request<PayoutList>(`/payouts?${params.toString()}`, { token });
  },
  retryPayout(token: string, payoutId: string): Promise<{ status: string; last_error: string | null }> {
    return request(`/payouts/${payoutId}/retry`, { method: "POST", token });
  },
  /** An owner passes no restaurant: the server pins them to their own. */
  getPayoutAccount(token: string, restaurantId?: string): Promise<PayoutAccount | null> {
    const query = restaurantId ? `?restaurant_id=${restaurantId}` : "";
    return request<PayoutAccount | null>(`/payouts/account${query}`, { token });
  },
  savePayoutAccount(token: string, restaurantId: string, body: PayoutAccountInput): Promise<PayoutAccount> {
    return request<PayoutAccount>(`/payouts/account?restaurant_id=${restaurantId}`, { method: "PUT", token, body });
  },
  submitPayoutAccount(token: string, restaurantId: string): Promise<PayoutAccount> {
    return request<PayoutAccount>(`/payouts/account/submit?restaurant_id=${restaurantId}`, { method: "POST", token });
  },
  refreshPayoutAccount(token: string, restaurantId: string): Promise<PayoutAccount> {
    return request<PayoutAccount>(`/payouts/account/refresh?restaurant_id=${restaurantId}`, { method: "POST", token });
  },
```

`_scope(required=True)` gives an owner their own restaurant whether or not they name one, so the owner's call needs no id.

`src/services/payouts.ts`:

```ts
/**
 * Rules for the Payouts screen, kept out of the component so they can be
 * tested without rendering it. The server is still the authority: it pins
 * an owner to their restaurant and never sends them the platform's half.
 */
import { isoDay, type PeriodRange } from "./dashboardPeriod";
import type { PayoutAccountInput, PayoutAccountStatus, PayoutRow, PayoutStatus } from "../types/app";

/** `pill` is a status word `StatusPill` already colours. */
export const PAYOUT_STATUS_META: Record<PayoutStatus, { label: string; ownerLabel: string; pill: string }> = {
  WAITING_ACCOUNT: { label: "Waiting", ownerLabel: "Waiting for your account", pill: "PENDING" },
  HELD: { label: "Held", ownerLabel: "Held until delivered", pill: "PREPARING" },
  RELEASED: { label: "Released", ownerLabel: "On its way", pill: "OUT_FOR_DELIVERY" },
  SETTLED: { label: "Settled", ownerLabel: "In your bank", pill: "DELIVERED" },
  REVERSED: { label: "Reversed", ownerLabel: "Taken back", pill: "CANCELLED" },
  FAILED: { label: "Failed", ownerLabel: "Being looked into", pill: "FAILED" },
  BLOCKED: { label: "Blocked", ownerLabel: "Being looked into", pill: "FAILED" },
  NOT_APPLICABLE: { label: "Not via platform", ownerLabel: "Paid to you directly", pill: "COD" },
};

export const ACCOUNT_STATUS_META: Record<PayoutAccountStatus, { label: string; pill: string; hint: string }> = {
  DRAFT: { label: "Draft", pill: "PENDING", hint: "Saved here, not sent to Razorpay yet." },
  SUBMITTED: { label: "Submitted", pill: "PLACED", hint: "Sent to Razorpay." },
  UNDER_REVIEW: { label: "Under review", pill: "PREPARING", hint: "Razorpay is checking the details, usually 1-3 working days." },
  NEEDS_CLARIFICATION: { label: "Needs a correction", pill: "FAILED", hint: "Razorpay asked for the changes listed below." },
  ACTIVE: { label: "Active", pill: "DELIVERED", hint: "Payments are passed on to this bank account." },
  SUSPENDED: { label: "Suspended", pill: "CANCELLED", hint: "Razorpay has stopped payouts to this account." },
};

function cell(value: string | number | null | undefined): string {
  const text = value === null || value === undefined ? "" : String(value);
  return /[",\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

export function payoutsCsv(rows: PayoutRow[], isAdmin: boolean): string {
  const header = [
    "Order placed", "Order", "Restaurant", "Restaurant share", ...(isAdmin ? ["Platform keeps"] : []),
    "Currency", "Status", "Razorpay transfer", "Released", "Settled", "Note",
  ];
  const lines = rows.map((row) =>
    [
      row.order_placed_at, row.order_id, row.restaurant_name, row.restaurant_share,
      ...(isAdmin ? [row.platform_keeps] : []), row.currency,
      isAdmin ? PAYOUT_STATUS_META[row.status].label : PAYOUT_STATUS_META[row.status].ownerLabel,
      row.transfer_id, row.released_at, row.settled_at, row.last_error,
    ].map(cell).join(","),
  );
  return [header.map(cell).join(","), ...lines].join("\n");
}

const PAN = /^[A-Z]{5}[0-9]{4}[A-Z]$/;
const IFSC = /^[A-Z]{4}0[A-Z0-9]{6}$/;
const REQUIRED = [
  "legal_business_name", "contact_name", "email", "phone", "street", "city", "state", "beneficiary_name",
] as const;

/** The same checks the server makes, so a typo is caught before Save. */
export function accountInputErrors(input: PayoutAccountInput): Partial<Record<keyof PayoutAccountInput, string>> {
  const errors: Partial<Record<keyof PayoutAccountInput, string>> = {};
  if (!PAN.test(input.pan.trim().toUpperCase())) errors.pan = "Five letters, four digits, a letter - like ABCDE1234F.";
  if (!IFSC.test(input.ifsc.trim().toUpperCase())) errors.ifsc = "Four letters, a zero, then six letters or digits.";
  if (!/^[1-9][0-9]{5}$/.test(input.postal_code.trim())) errors.postal_code = "Six digits.";
  if (!/^[0-9]{9,18}$/.test(input.bank_account_number.replace(/\s/g, ""))) {
    errors.bank_account_number = "9 to 18 digits.";
  }
  for (const key of REQUIRED) {
    if (!input[key].trim()) errors[key] = "Required.";
  }
  return errors;
}

/** The server takes whole days, both included; a range's `end` is exclusive. */
export function periodQuery(range: Pick<PeriodRange, "start" | "end">): { date_from: string; date_to: string } {
  return { date_from: isoDay(range.start), date_to: isoDay(new Date(range.end.getTime() - 1)) };
}
```

Check that every `pill` word above is one `StatusPill` colours. Read its tone resolver, imported in `components/StatusPill.tsx`. If a word falls through to a neutral tone, choose a better-known word and record a ruling.

`src/components/PayoutAccountPanel.tsx`:

```tsx
import { Landmark, RefreshCw, Send } from "lucide-react";
import { useEffect, useState } from "react";

import { StatusPill } from "./StatusPill";
import { ApiError, api } from "../services/api";
import { ACCOUNT_STATUS_META, accountInputErrors } from "../services/payouts";
import type { PayoutAccount, PayoutAccountInput, ToastMessage } from "../types/app";

const EMPTY: PayoutAccountInput = {
  legal_business_name: "", business_type: "proprietorship", pan: "", contact_name: "", email: "", phone: "",
  street: "", city: "", state: "", postal_code: "", bank_account_number: "", ifsc: "", beneficiary_name: "",
};

const FIELDS: Array<{ key: keyof PayoutAccountInput; label: string; hint?: string }> = [
  { key: "legal_business_name", label: "Legal business name", hint: "As on the PAN." },
  { key: "pan", label: "PAN" },
  { key: "contact_name", label: "Contact name" },
  { key: "email", label: "Email" },
  { key: "phone", label: "Phone" },
  { key: "street", label: "Registered address" },
  { key: "city", label: "City" },
  { key: "state", label: "State" },
  { key: "postal_code", label: "PIN code" },
  { key: "beneficiary_name", label: "Account holder's name" },
  { key: "bank_account_number", label: "Bank account number", hint: "Stored encrypted; only the last four are shown again." },
  { key: "ifsc", label: "IFSC" },
];

/**
 * A restaurant's Razorpay linked account. Only the platform admin fills it
 * in (the server refuses an owner); the owner sees where it stands and what
 * Razorpay still needs.
 */
export function PayoutAccountPanel({ token, restaurantId, isAdmin, onToast }: {
  token: string;
  /** Empty for an owner: the server answers with their own restaurant. */
  restaurantId: string;
  isAdmin: boolean;
  onToast: (title: string, description: string, tone?: ToastMessage["tone"]) => void;
}) {
  const [account, setAccount] = useState<PayoutAccount | null>(null);
  const [form, setForm] = useState<PayoutAccountInput>(EMPTY);
  const [busy, setBusy] = useState(false);
  const [touched, setTouched] = useState(false);

  useEffect(() => {
    let current = true;
    api
      .getPayoutAccount(token, restaurantId || undefined)
      .then((next) => {
        if (!current) return;
        setAccount(next);
        setForm(next ? { ...EMPTY, ...next, bank_account_number: "" } : EMPTY);
      })
      .catch((error: unknown) => {
        if (!current) return;
        onToast("Could not load the payout account", error instanceof ApiError ? error.message : "Please try again.", "error");
      });
    return () => {
      current = false;
    };
  }, [token, restaurantId, onToast]);

  const editable = isAdmin && (!account || account.status === "DRAFT" || account.status === "NEEDS_CLARIFICATION");
  const errors = accountInputErrors(form);
  const canSave = Object.keys(errors).length === 0;

  async function run(action: () => Promise<PayoutAccount>, done: string) {
    setBusy(true);
    try {
      const next = await action();
      setAccount(next);
      onToast(done, ACCOUNT_STATUS_META[next.status].hint, "success");
    } catch (error) {
      onToast("That did not work", error instanceof ApiError ? error.message : "Please try again.", "error");
    } finally {
      setBusy(false);
    }
  }

  const meta = account ? ACCOUNT_STATUS_META[account.status] : null;
  return (
    <section aria-labelledby="payout-account-title" className="elevated-panel">
      <h2 id="payout-account-title">
        <Landmark aria-hidden="true" size={18} /> Bank account for payouts
      </h2>
      {meta ? (
        <p>
          <StatusPill status={meta.pill} /> {meta.label}. {meta.hint}
          {account?.bank_account_last4 ? ` Account ending ${account.bank_account_last4}.` : ""}
        </p>
      ) : (
        <p>
          {isAdmin
            ? "Not set up yet. Fill this in to start passing payments on to this restaurant."
            : "Your platform admin has not set up payouts for you yet."}
        </p>
      )}
      {account?.requirements.length ? (
        <ul>
          {account.requirements.map((need) => (
            <li key={need}>{need}</li>
          ))}
        </ul>
      ) : null}
      {account?.last_error ? <p role="alert">{account.last_error}</p> : null}

      {editable ? (
        <form
          className="form-grid"
          onSubmit={(event) => {
            event.preventDefault();
            setTouched(true);
            if (canSave) void run(() => api.savePayoutAccount(token, restaurantId, form), "Saved");
          }}
        >
          {FIELDS.map(({ key, label, hint }) => (
            <label className="field" key={key}>
              <span>{label}</span>
              <input
                aria-invalid={touched && Boolean(errors[key])}
                autoComplete="off"
                onChange={(event) => setForm({ ...form, [key]: event.target.value })}
                value={form[key]}
              />
              {touched && errors[key] ? <small role="alert">{errors[key]}</small> : hint ? <small>{hint}</small> : null}
            </label>
          ))}
          <div>
            <button className="secondary-button" disabled={busy} type="submit">
              Save
            </button>
            <button
              className="primary-button"
              disabled={busy || !account}
              onClick={() => void run(() => api.submitPayoutAccount(token, restaurantId), "Sent to Razorpay")}
              title={account ? "Open the linked account with Razorpay." : "Save the details first."}
              type="button"
            >
              <Send size={15} /> Send to Razorpay
            </button>
            {!account ? <small>Save the details first.</small> : null}
          </div>
        </form>
      ) : null}

      {isAdmin && account?.razorpay_account_id ? (
        <button
          className="secondary-button"
          disabled={busy}
          onClick={() => void run(() => api.refreshPayoutAccount(token, restaurantId), "Status refreshed")}
          type="button"
        >
          <RefreshCw size={15} /> Refresh status
        </button>
      ) : null}
    </section>
  );
}
```

Before writing `src/pages/PayoutsPage.tsx`, read `CommissionPage.tsx` and `DashboardPage.tsx` for their load/failed/attempt shape and how they store the period. The page:
- `useMarketingScope()` provides the admin's restaurant picker. An empty selection means all restaurants: the list shows every restaurant's rows, and the account panel says "Pick a restaurant to see its bank account". An owner sees neither the picker nor the restaurant column.
- `DashboardPeriodPicker` sits in `PageIntro.actions`. Store the period with `parsePeriod`/`JSON.stringify` under the localStorage key `restaurant-rag-payouts-period`, with try/catch, the same way `DashboardPage` does. Derive `years` the same way too.
- `StatTiles` shows held, on its way (released), in the bank (settled), waiting, and problems. Each tile's `value` is `money.format(bucket.amount)` and its hint is `pluralize(count, "order")` (from `services/format`).
- When `payouts_enabled` is false, show a notice with `role="status"`: "Payouts are switched off. These are the amounts that would be paid; nothing has been sent to Razorpay."
- `ResponsiveTable` columns:
  - placed (date and time);
  - restaurant (admin only);
  - share;
  - platform keeps (admin only);
  - status: `StatusPill` with `PAYOUT_STATUS_META[s].pill`, then the label for the role;
  - note (`last_error`).

  `mobileTitle` is the share; `mobileSubtitle` is the placed time. The admin gets a "Retry" table action on FAILED and BLOCKED rows. It calls `api.retryPayout`, toasts the result, and reloads.
- An "Export CSV" button builds a `Blob` from `payoutsCsv(rows, isAdmin)`, makes a URL with `URL.createObjectURL`, and clicks a temporary `<a download="payouts.csv">`. When there are no rows it is disabled, with the title "Nothing to export for this period".
- `PayoutAccountPanel` sits below the table: `restaurantId` is `selectedRestaurantId` for an admin, or `""` for an owner.
- State is set only from an answer, never on the way in, because the lint baseline counts set-state-in-effect. Use the `current` flag pattern from `CommissionPage`.

Add to `routes.tsx` after the `commission` route, importing `Wallet` and `PayoutsPage`, and mirror the `commission` route's `render` context field names:

```tsx
  {
    // Both roles: an admin sees every restaurant and both halves; an owner
    // their own share only. The server enforces both.
    id: "payouts",
    pattern: "/payouts",
    roles: BOTH,
    nav: { section: "Orders", label: "Payouts", icon: Wallet, keywords: ["settlement", "bank", "razorpay", "transfer", "money"] },
    render: (ctx) => <PayoutsPage onToast={ctx.pushToast} token={ctx.token} />,
  },
```

- [ ] **Step 4: Run the tests, the build and lint**

Run: `cd frontend-admin && npx vitest run src/services/payouts.test.ts && npm run test && npm run build && npm run lint`
Expected:
- The payouts tests pass, and so does the whole suite, including `styleBudget.test.ts` (no new CSS family was added).
- The build is clean.
- Lint reports the 68-problem baseline and nothing new from these files.

- [ ] **Step 5: Check it in the browser**

The dev servers must be running (API on 8000, admin on 5174). In the signed-in admin tab, open `/payouts` and check:
- the tiles render;
- the switched-off notice shows;
- the table loads;
- the restaurant picker narrows the list;
- the account form shows field errors for a bad PAN.

Do NOT press "Send to Razorpay". The local `.env` holds real keys, and that call opens a real linked account. Take a screenshot for the user.

---

### Task 9: Documentation, full suites, and the Razorpay test-mode checklist

**Files:**
- Create: `backend/docs/payouts.md`
- Modify: `CLAUDE.md` (a "Payouts" section, the docs table, the migration note), `.claude/worklog.md`

- [ ] **Step 1: Write `backend/docs/payouts.md`**, covering:
- the split, and why each line sits on its side;
- the statuses and what moves each one;
- the platform-collection rule;
- the flag;
- the webhook URL `https://<api>/api/payments/razorpay/webhook`;
- the env vars `ENABLE_RESTAURANT_PAYOUTS`, `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET`, `RAZORPAY_WEBHOOK_SECRET`.

The events to tick on the webhook are:
- `payment.captured`, `payment.failed`, `order.paid`
- `refund.created`, `refund.processed`
- `transfer.processed`, `transfer.failed`, `settlement.processed`
- `product.route.activated`, `product.route.needs_clarification`, `product.route.under_review`
- `account.suspended`

Then the test-mode checklist, to run before the flag goes on in production:
1. Enable Route in test mode.
2. Run locally with test keys and `ENABLE_RESTAURANT_PAYOUTS=true`.
3. Fill one restaurant's account with Razorpay's test PAN and bank details, then Send.
4. Activate it from the Razorpay test dashboard.
5. Place a Razorpay test order. The row should show HELD, and the Razorpay dashboard should show a transfer on hold.
6. Mark the order Delivered. The row should show RELEASED.
7. Place another order and cancel it. The row should show REVERSED.
8. Correct any v2 field name the run disproves.

- [ ] **Step 2: Update `CLAUDE.md`.** Add a short "Payouts (Razorpay Route)" section in the house voice, covering the rules that fail silently:
- the split lives only in `split.py`;
- `on_platform_account` decides which account an attempt belongs to;
- the row lock plus the `transfer_id` rule;
- with the flag off, the ledger is still written;
- an owner never gets `platform_keeps`;
- the platform collects only for a restaurant it can pay.

Also add `backend/docs/payouts.md` to the docs table, and note that `0083` is the new head.

- [ ] **Step 3: Run every suite**

Run:
```bash
cd backend && ./.venv/Scripts/python.exe -m compileall -q app alembic && ./.venv/Scripts/python.exe -m unittest discover -s tests > "$SCRATCH/payouts-backend.log" 2>&1; tail -5 "$SCRATCH/payouts-backend.log"
cd ../frontend-admin && npm run test && npm run build && npm run lint
cd ../frontend-customer && npm run test
```
`$SCRATCH` is the session scratchpad. Expected:
- backend: `OK`, with 3147 plus the new tests and no new failures;
- admin: tests and build green, lint at its baseline;
- storefront: green. Nothing there changes, but its Razorpay checkout ends at the reordered `confirm_razorpay_checkout`.

- [ ] **Step 4: Append the worklog entry** to `.claude/worklog.md`. Record what was built, every ruling, and what the user must do outside the code:
- Enable Route on the Razorpay account.
- Collect each restaurant's PAN and bank details.
- Set `RAZORPAY_WEBHOOK_SECRET` and add the webhook on Razorpay.
- Run the test-mode checklist.
- Deploy `redesign` so `0083` runs.
- Only then set `ENABLE_RESTAURANT_PAYOUTS=true` on Render.
