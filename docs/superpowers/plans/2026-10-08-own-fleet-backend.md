# Own Fleet (Rider) — Plan 1 of 4: Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The platform can create riders, offer each delivery to the nearest online rider, let them accept, move through the trip with a customer OTP, pay them per km, and hand the order to Pidge automatically when no rider takes it.

**Architecture:** The fleet is a second courier behind the existing `services/delivery` contract (`own_fleet_provider.py`), so `order_deliveries`, `advance_order`, the admin Delivery panel and the storefront tracking keep one source of truth. Rider-specific state lives in four new tables and a new `services/fleet/` package (settings, offers, trips, earnings, liveness). Everything is behind `enable_own_fleet`, default off.

**Tech Stack:** FastAPI 0.115, SQLAlchemy 2.0, Alembic, Postgres, Celery + Redis, Firebase Admin (FCM), python-socketio (existing realtime), `unittest`.

**Spec:** `docs/superpowers/specs/2026-10-08-rider-app-design.md`

## The four plans (roadmap)

| Plan | What | Depends on | Written |
|---|---|---|---|
| **1 — Backend fleet (this file)** | roles, tables, dispatch, trips, OTP, earnings, admin + rider APIs, realtime, push | — | now |
| 2 — Rider Android app (`rider/`) | RN 0.85 CLI app: login, permissions, online, offer alert, trip, OTP, earnings | Plan 1 API frozen | after Plan 1 Task 9 is merged |
| 3 — Admin panel | Riders page, settings, payouts, Delivery panel own-fleet view | Plan 1 | after Plan 1 |
| 4 — Storefront | OTP card + rider on map on the order page | Plan 1 Task 10 | after Plan 1 |

Plan 2 is written against the real OpenAPI of Plan 1, not guessed, which is why it waits.

## Global Constraints

- Tests are `unittest`, run with `cd backend && ./.venv/Scripts/python.exe -m unittest discover -s tests`. Each DB test creates and drops its own database (copy the harness in `tests/test_delivery_pricing_admin.py`).
- New migration is `0089_own_fleet`, `down_revision = "0088_rls_on_every_table"`; RLS enabled on every new table inside the migration; new enum value added inside `op.get_context().autocommit_block()`; platform-uniqueness indexes widened to `'ADMIN', 'OWNER', 'KITCHEN', 'RIDER'` (see `0071_kitchen_staff.py`).
- Every model change is mirrored in `__table_args__`, because tests build from `create_all`.
- `enable_own_fleet` defaults **False**; with it off, behaviour for every existing order is byte-identical.
- Riders: platform-wide, ADMIN-only management; RIDER is platform staff (`app_client_id` NULL, no `staff_restaurant_*`).
- No cash: an order whose `payment_method` is `CASH_ON_DELIVERY` is never offered to a rider (goes straight to Pidge).
- Out-of-scope rows are 404, not 403 (house rule from the kitchen board).
- A realtime push is a hint (ids only); clients refetch over REST.
- Comments explain *why*, lab-notebook style (see `app/config/settings.py`).
- The user runs migrations against Supabase themselves; never run `alembic upgrade` against Supabase.
- Commit only when the user asks. Commit trailer:
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` and
  `Claude-Session: https://claude.ai/code/session_01JFJkFSMqqK5aVpJZytBUDN`.

## Review Focus

1. Two riders tap Accept within the same 50 ms → exactly one trip; the other gets 409 `offer_taken`. (Task 5 `test_two_accepts_one_wins`, real Postgres, two sessions.)
2. A rider repeats an action after a network retry (same `action_id`) → 200 with the same trip, no double earning, no second status event. (Task 7 `test_retry_is_idempotent`.)
3. Restaurant cancels while an offer is open or a trip is running → offer WITHDRAWN, trip ended, pay rule applied, rider told. (Task 7 `test_cancel_during_trip_pays_after_arrival`.)
4. Fleet flag on but Pidge not configured and no rider online → row stays PENDING with a readable `last_error` and a Platform watch alert, never an exception loop. (Task 6 `test_no_rider_and_no_pidge_is_visible`.)
5. A rider who was deactivated mid-shift keeps sending location → 401, status set OFFLINE, open offers withdrawn. (Task 3 `test_deactivation_ends_shift`.)

---

## Task 0: Machine setup (the user does this; nothing to commit)

Needed for Plans 2+; listed first so installs run while Plan 1 is built.

- [ ] Install **JDK 17** (Microsoft OpenJDK 17 or Temurin 17). Set `JAVA_HOME`, add `%JAVA_HOME%\bin` to PATH. Check: `java -version` → `17.x`.
- [ ] Install **Android Studio** (latest). In SDK Manager install: Android SDK Platform **36**, Android SDK Build-Tools **36.0.0**, NDK **27.1.12297006**, Android SDK Platform-Tools, Android Emulator, CMake.
- [ ] Set `ANDROID_HOME=%LOCALAPPDATA%\Android\Sdk`; add `%ANDROID_HOME%\platform-tools` and `%ANDROID_HOME%\emulator` to PATH. Check: `adb --version`.
- [ ] A real Android phone (Android 10+), Developer options → USB debugging on. Check: `adb devices` lists it. (An emulator is fine for UI; background location and push must be tested on a real phone.)
- [ ] Firebase: in the existing Firebase project add an Android app with package `com.foodie.rider`, download `google-services.json` (goes to `rider/android/app/` in Plan 2; do not paste into chat).
- [ ] Google Cloud: billing fixed (valid card), then enable **Maps SDK for Android** and create a key restricted to Android apps with package `com.foodie.rider` + the debug SHA-1 (printed by `cd rider/android && ./gradlew signingReport` in Plan 2).

---

## File map (Plan 1)

| File | Responsibility |
|---|---|
| `backend/alembic/versions/0089_own_fleet.py` | enum value, 4 tables, OTP columns, index widening, RLS |
| `backend/app/models/enums.py` | `UserRole.RIDER`, `RiderStatus`, `VehicleType`, `OfferOutcome`, `TripEndReason` |
| `backend/app/models/rider.py` | `Rider`, `RiderOffer`, `RiderTrip`, `RiderPayout` |
| `backend/app/models/order_delivery.py` | `delivery_otp_hash`, `otp_attempts`, `otp_locked` |
| `backend/app/config/settings.py` | `enable_own_fleet`, `rider_otp_secret` |
| `backend/app/services/fleet/__init__.py` | package |
| `backend/app/services/fleet/config.py` | `FleetConfig`, `RiderPay`, load/save/validate from `platform_settings` |
| `backend/app/services/fleet/earnings.py` | pure pay formula |
| `backend/app/services/fleet/riders.py` | create/update/deactivate riders, shift status, location |
| `backend/app/services/fleet/offers.py` | candidates, offer, accept, decline, expire, advance loop |
| `backend/app/services/fleet/trips.py` | trip actions, OTP, cancellation, unavailable |
| `backend/app/services/fleet/otp.py` | derive / hash / verify the 4-digit code |
| `backend/app/services/fleet/notify.py` | FCM data message + realtime emits to `rider:{id}` |
| `backend/app/services/delivery/own_fleet_provider.py` | courier contract adapter |
| `backend/app/services/delivery/registry.py` | choose own fleet first when on |
| `backend/app/services/delivery/service.py` | `fallback_to_pidge`, cancel hook |
| `backend/app/tasks/fleet.py` | `advance_offers_task`, `sweep_riders_task` |
| `backend/app/config/celery.py` | include tasks, beat every 10 s / 60 s |
| `backend/app/api/rider.py` | rider endpoints |
| `backend/app/api/admin_riders.py` | admin endpoints |
| `backend/app/schemas/rider.py` | request/response models |
| `backend/app/services/auth.py` | `require_rider` |
| `backend/app/services/realtime/rooms.py`, `server.py` | `rider_room`, rider sockets join it |
| `backend/app/api/orders.py` (+ schema) | customer sees `delivery.otp` |
| `backend/app/services/platform_watch.py` | fleet alerts |
| `backend/tests/fleet_harness.py` | shared throwaway-DB fixture for fleet tests |
| `backend/tests/test_fleet_*.py` | one file per task |
| `backend/docs/delivery-integration.md`, `CLAUDE.md` | the fleet section |

---

## Task 1: Schema — role, tables, OTP columns, flag

**Files:**
- Create: `backend/alembic/versions/0089_own_fleet.py`, `backend/app/models/rider.py`, `backend/tests/fleet_harness.py`, `backend/tests/test_fleet_schema.py`
- Modify: `backend/app/models/enums.py`, `backend/app/models/order_delivery.py`, `backend/app/models/__init__.py`, `backend/app/config/settings.py`

**Interfaces:**
- Produces: `UserRole.RIDER`; enums `RiderStatus{OFFLINE,ONLINE,ON_TRIP}`, `VehicleType{BIKE,SCOOTER,CYCLE}`, `OfferOutcome{PENDING,ACCEPTED,DECLINED,EXPIRED,WITHDRAWN}`, `TripEndReason{DELIVERED,CANCELLED_BEFORE_PICKUP,CANCELLED_AFTER_PICKUP,CUSTOMER_UNAVAILABLE,REASSIGNED}`; models `Rider`, `RiderOffer`, `RiderTrip`, `RiderPayout`; `OrderDelivery.delivery_otp_hash: str`, `.otp_attempts: int`, `.otp_locked: bool`; settings `enable_own_fleet: bool = False`, `rider_otp_secret: str = ""`; harness `FleetDB` with `.session()`, `.make_admin()`, `.make_rider(**kw)`, `.make_order(**kw)`.

- [ ] **Step 1: Write the harness** `backend/tests/fleet_harness.py`

```python
"""A throwaway Postgres database for the fleet tests, built from create_all.

Copied from the harness in test_delivery_pricing_admin.py rather than imported,
because every other suite here owns its own; this one is shared by the
test_fleet_* files only, so each does not repeat sixty lines of setup.
"""

from __future__ import annotations

import sys
import uuid
from decimal import Decimal
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.config import get_settings  # noqa: E402
from app.models.base import Base  # noqa: E402
import app.models  # noqa: E402,F401  - registers every table
from app.models.enums import (  # noqa: E402
    OrderFulfillmentType, OrderStatus, PaymentMethod, RiderStatus, UserRole, VehicleType,
)
from app.models.order import Order  # noqa: E402
from app.models.restaurant import Restaurant  # noqa: E402
from app.models.restaurant_location import RestaurantLocation  # noqa: E402
from app.models.rider import Rider  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services.auth import hash_password  # noqa: E402

settings = get_settings()


def _url(database: str) -> str:
    return (
        f"postgresql+psycopg://{settings.postgres_user}:{settings.postgres_password}"
        f"@{settings.postgres_server}:{settings.postgres_port}/{database}"
    )


def postgres_available() -> bool:
    try:
        engine = create_engine(_url("postgres"), isolation_level="AUTOCOMMIT")
        with engine.connect():
            pass
        engine.dispose()
        return True
    except Exception:  # noqa: BLE001
        return False


class FleetDB:
    def __init__(self, name: str) -> None:
        self.name = name
        admin = create_engine(_url("postgres"), isolation_level="AUTOCOMMIT")
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
            conn.execute(text(f'CREATE DATABASE "{name}"'))
        admin.dispose()
        self.engine = create_engine(_url(name))
        with self.engine.begin() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)

    def drop(self) -> None:
        self.engine.dispose()
        admin = create_engine(_url("postgres"), isolation_level="AUTOCOMMIT")
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{self.name}" WITH (FORCE)'))
        admin.dispose()

    def session(self):
        return self.Session()

    def make_admin(self, db) -> User:
        user = User(
            email=f"admin-{uuid.uuid4().hex[:6]}@example.com", full_name="Admin",
            hashed_password=hash_password("password123"), role=UserRole.ADMIN, is_active=True,
        )
        db.add(user)
        db.flush()
        return user

    def make_rider(self, db, *, lat=21.17, lng=72.83, status=RiderStatus.ONLINE, phone=None) -> User:
        from datetime import UTC, datetime

        user = User(
            email=None, phone_number=phone or f"+9198{uuid.uuid4().int % 10**8:08d}",
            full_name="Ravi Rider", hashed_password=hash_password("password123"),
            role=UserRole.RIDER, is_active=True,
        )
        db.add(user)
        db.flush()
        db.add(Rider(
            user_id=user.id, vehicle_type=VehicleType.BIKE, vehicle_number="GJ05AB1234",
            city="Surat", status=status, last_latitude=lat, last_longitude=lng,
            last_location_at=datetime.now(UTC),
        ))
        db.flush()
        return user

    def make_order(self, db, *, lat=21.18, lng=72.84, payment=PaymentMethod.CARD,
                   status=OrderStatus.ACCEPTED) -> Order:
        owner = User(email=f"o-{uuid.uuid4().hex[:6]}@x.com", full_name="Owner",
                     hashed_password="x", role=UserRole.OWNER, is_active=True)
        db.add(owner)
        db.flush()
        restaurant = Restaurant(name="Bhagwati Bakery", slug=f"b-{uuid.uuid4().hex[:6]}",
                                owner_id=owner.id)
        db.add(restaurant)
        db.flush()
        location = RestaurantLocation(
            restaurant_id=restaurant.id, branch_name="Main", address_line_1="Rander Road",
            city="Surat", state="Gujarat", postal_code="395009", phone_number="9876500000",
            latitude=Decimal(str(lat)), longitude=Decimal(str(lng)),
        )
        db.add(location)
        db.flush()
        order = Order(
            restaurant_id=restaurant.id, restaurant_location_id=location.id,
            status=status, fulfillment_type=OrderFulfillmentType.DELIVERY,
            payment_method=payment, delivery_address="12 Adajan, Surat",
            delivery_latitude=21.20, delivery_longitude=72.80,
            contact_name="Customer", contact_phone="9876511111",
            subtotal_amount=Decimal("200"), total_amount=Decimal("268"), currency="INR",
        )
        db.add(order)
        db.flush()
        return order
```

> If `create_all` fails because `Order`/`Restaurant`/`RestaurantLocation` require more columns than above, read the model, add the missing NOT NULL columns with harmless values, and record the change in the ledger. The shape above matches the fields used by `test_delivery_dispatch.py`.

- [ ] **Step 2: Write the failing schema test** `backend/tests/test_fleet_schema.py`

```python
"""The fleet's tables exist, a rider is platform staff, and the flag is off.

Platform staff is the important part: `ck_users_app_client_scope_matches_role`
and the platform uniqueness indexes both name roles explicitly, and 0071
showed that forgetting one leaves a role with no uniqueness at all.
"""

from __future__ import annotations

import unittest

from sqlalchemy.exc import IntegrityError

from fleet_harness import FleetDB, postgres_available
from app.config import get_settings
from app.models.enums import UserRole
from app.models.order_delivery import OrderDelivery
from app.models.user import User


@unittest.skipUnless(postgres_available(), "local Postgres is not running")
class FleetSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fdb = FleetDB("restaurant_rag_fleet_schema_test")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.fdb.drop()

    def test_a_rider_is_created_with_no_app_client(self) -> None:
        with self.fdb.session() as db:
            rider = self.fdb.make_rider(db)
            db.commit()
            self.assertEqual(rider.role, UserRole.RIDER)
            self.assertIsNone(rider.app_client_id)

    def test_order_delivery_has_otp_columns(self) -> None:
        cols = OrderDelivery.__table__.columns
        self.assertIn("delivery_otp_hash", cols)
        self.assertIn("otp_attempts", cols)
        self.assertIn("otp_locked", cols)

    def test_flag_defaults_off(self) -> None:
        self.assertFalse(get_settings().enable_own_fleet)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run it — expect FAIL**

Run: `cd backend && ./.venv/Scripts/python.exe -m unittest tests.test_fleet_schema -v` (run from `backend/tests` on sys.path: `cd backend/tests && ../.venv/Scripts/python.exe -m unittest test_fleet_schema -v`)
Expected: ImportError `cannot import name 'RiderStatus'`.

- [ ] **Step 4: Enums** — append to `backend/app/models/enums.py` inside `UserRole` after `KITCHEN`:

```python
    # A delivery rider in the platform's own fleet (2026-10-08). Platform staff
    # like KITCHEN: `app_client_id` NULL, and NOT pinned to a restaurant -
    # the fleet is shared by every restaurant in a city, and only an ADMIN
    # creates or manages riders. Their only surface is the rider app.
    RIDER = "RIDER"
```

and at module level:

```python
class RiderStatus(StrEnum):
    OFFLINE = "OFFLINE"
    ONLINE = "ONLINE"
    ON_TRIP = "ON_TRIP"


class VehicleType(StrEnum):
    BIKE = "BIKE"
    SCOOTER = "SCOOTER"
    CYCLE = "CYCLE"


class OfferOutcome(StrEnum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"
    #: Taken back by the system: the order was cancelled, reassigned or sent to Pidge.
    WITHDRAWN = "WITHDRAWN"


class TripEndReason(StrEnum):
    DELIVERED = "DELIVERED"
    CANCELLED_BEFORE_PICKUP = "CANCELLED_BEFORE_PICKUP"
    CANCELLED_AFTER_PICKUP = "CANCELLED_AFTER_PICKUP"
    CUSTOMER_UNAVAILABLE = "CUSTOMER_UNAVAILABLE"
    REASSIGNED = "REASSIGNED"
```

Also add `RIDER = "RIDER"` to `OrderEventActor` (same reason `KITCHEN` was added: otherwise a rider's advance is logged as SYSTEM), and map it in `actor_for_user`.

- [ ] **Step 5: Models** — `backend/app/models/rider.py`

```python
"""The platform's own riders: who they are, what they were offered, what they carried.

One `riders` row per RIDER account (1:1 with users, keyed by user_id), so a
user is never half a rider. Offers and trips hang off `order_deliveries`, not
`orders`, because the delivery row is the one courier-neutral record of "who
is carrying this" - the same row Pidge's webhook writes.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean, DateTime, Enum, Float, ForeignKey, Index, Numeric, String, Text, text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin
from app.models.enums import OfferOutcome, RiderStatus, TripEndReason, VehicleType


def _enum(cls, name: str):
    return Enum(cls, name=name, values_callable=lambda e: [m.value for m in e])


class Rider(TimestampMixin, Base):
    __tablename__ = "riders"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    vehicle_type: Mapped[VehicleType] = mapped_column(_enum(VehicleType, "rider_vehicle_type"), nullable=False)
    vehicle_number: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    city: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    status: Mapped[RiderStatus] = mapped_column(
        _enum(RiderStatus, "rider_status"), nullable=False, default=RiderStatus.OFFLINE
    )
    status_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_location_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fcm_token: Mapped[str] = mapped_column(Text, nullable=False, default="")
    app_version: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")

    __table_args__ = (Index("ix_riders_status", "status"),)


class RiderOffer(TimestampMixin, Base):
    __tablename__ = "rider_offers"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_delivery_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("order_deliveries.id", ondelete="CASCADE"), nullable=False
    )
    rider_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("riders.user_id", ondelete="CASCADE"), nullable=False
    )
    offered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    outcome: Mapped[OfferOutcome] = mapped_column(
        _enum(OfferOutcome, "rider_offer_outcome"), nullable=False, default=OfferOutcome.PENDING
    )
    distance_to_pickup_m: Mapped[float | None] = mapped_column(Float, nullable=True)

    __table_args__ = (
        # One open offer per delivery: the loop offers to one rider at a time,
        # and two open offers would let two riders accept the same food.
        Index(
            "uq_rider_offers_one_pending", "order_delivery_id", unique=True,
            postgresql_where=text("outcome = 'PENDING'"),
        ),
        Index("ix_rider_offers_rider", "rider_user_id", "outcome"),
    )


class RiderTrip(TimestampMixin, Base):
    __tablename__ = "rider_trips"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_delivery_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("order_deliveries.id", ondelete="CASCADE"), nullable=False
    )
    rider_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("riders.user_id", ondelete="RESTRICT"), nullable=False
    )
    accepted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    arrived_pickup_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    picked_up_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    arrived_drop_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    end_reason: Mapped[TripEndReason | None] = mapped_column(
        _enum(TripEndReason, "rider_trip_end_reason"), nullable=True
    )
    call_attempts: Mapped[int] = mapped_column(nullable=False, default=0, server_default="0")
    distance_km: Mapped[float | None] = mapped_column(Float, nullable=True)
    earning_amount: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    earning_breakdown: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    #: client action ids already applied, so a retried request is a no-op.
    applied_actions: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    payout_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("rider_payouts.id", ondelete="SET NULL"), nullable=True
    )

    __table_args__ = (
        # One LIVE trip per delivery; a reassigned trip has ended_at set and
        # stays as history.
        Index(
            "uq_rider_trips_one_live", "order_delivery_id", unique=True,
            postgresql_where=text("ended_at IS NULL"),
        ),
        Index("ix_rider_trips_rider", "rider_user_id", "accepted_at"),
    )


class RiderPayout(TimestampMixin, Base):
    __tablename__ = "rider_payouts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    rider_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("riders.user_id", ondelete="RESTRICT"), nullable=False
    )
    period_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_to: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    reference: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    paid_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
```

Register in `app/models/__init__.py` (`from app.models.rider import Rider, RiderOffer, RiderPayout, RiderTrip` and in `__all__`).

In `order_delivery.py` add after `attempt`:

```python
    # Own fleet only (2026-10-08). The customer reads a 4-digit code to the
    # rider; it is derived from a server secret per order (services/fleet/otp)
    # and only its hash is stored, so a database read does not reveal it.
    delivery_otp_hash: Mapped[str] = mapped_column(String(128), nullable=False, default="", server_default="")
    otp_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    otp_locked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
```

Update `users` model `__table_args__` if it carries the role-list CHECK/partial indexes (search `KITCHEN` in `app/models/user.py`) so they name `RIDER` as well.

In `settings.py` beside `enable_delivery_dispatch`:

```python
    # The platform's own riders (2026-10-08). Off: no order is offered to a
    # rider and the registry never returns the fleet courier - Pidge behaves
    # exactly as before. Riders can still sign in and be trained while it is
    # off, which is why the rider endpoints are not behind it.
    enable_own_fleet: bool = False
    # Derives each order's delivery OTP (HMAC). Unset falls back to the JWT
    # secret, so a deployment that forgets it still has unguessable codes.
    rider_otp_secret: str = ""
```

- [ ] **Step 6: Migration** `backend/alembic/versions/0089_own_fleet.py`

```python
"""The platform's own delivery fleet: riders, offers, trips, payouts, delivery OTP.

RIDER is platform staff, so the two platform-uniqueness indexes are widened
to name it (0071's lesson: a role missing from them has no uniqueness at
all). The enum value is added in an autocommit block because Postgres will
not let a value added in this transaction be used by a later statement in it.
RLS is enabled on every new table here, in the migration, so a fresh
environment comes up closed (0088's lesson).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0089_own_fleet"
down_revision = "0088_rls_on_every_table"
branch_labels = None
depends_on = None

PLATFORM_ROLES = "'ADMIN', 'OWNER', 'KITCHEN', 'RIDER'"
OLD_PLATFORM_ROLES = "'ADMIN', 'OWNER', 'KITCHEN'"
NEW_TABLES = ("riders", "rider_offers", "rider_trips", "rider_payouts")


def _enum(name: str, *values: str) -> postgresql.ENUM:
    return postgresql.ENUM(*values, name=name, create_type=False)


def _uniqueness(roles: str) -> None:
    op.execute("DROP INDEX IF EXISTS uq_users_email_platform")
    op.execute(f"CREATE UNIQUE INDEX uq_users_email_platform ON users (lower(email)) WHERE role IN ({roles})")
    op.execute("DROP INDEX IF EXISTS uq_users_phone_number_platform")
    op.execute(
        "CREATE UNIQUE INDEX uq_users_phone_number_platform ON users (phone_number) "
        f"WHERE role IN ({roles}) AND phone_number IS NOT NULL"
    )


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE user_role ADD VALUE IF NOT EXISTS 'RIDER'")
        op.execute("ALTER TYPE order_event_actor ADD VALUE IF NOT EXISTS 'RIDER'")

    bind = op.get_bind()
    for name, values in (
        ("rider_status", ("OFFLINE", "ONLINE", "ON_TRIP")),
        ("rider_vehicle_type", ("BIKE", "SCOOTER", "CYCLE")),
        ("rider_offer_outcome", ("PENDING", "ACCEPTED", "DECLINED", "EXPIRED", "WITHDRAWN")),
        ("rider_trip_end_reason", ("DELIVERED", "CANCELLED_BEFORE_PICKUP", "CANCELLED_AFTER_PICKUP",
                                   "CUSTOMER_UNAVAILABLE", "REASSIGNED")),
    ):
        postgresql.ENUM(*values, name=name).create(bind, checkfirst=True)

    ts = dict(server_default=sa.text("now()"), nullable=False)
    uid = postgresql.UUID(as_uuid=True)

    op.create_table(
        "riders",
        sa.Column("user_id", uid, sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("vehicle_type", _enum("rider_vehicle_type"), nullable=False),
        sa.Column("vehicle_number", sa.String(32), nullable=False, server_default=""),
        sa.Column("city", sa.String(80), nullable=False, server_default=""),
        sa.Column("status", _enum("rider_status"), nullable=False, server_default="OFFLINE"),
        sa.Column("status_at", sa.DateTime(timezone=True)),
        sa.Column("last_latitude", sa.Float()),
        sa.Column("last_longitude", sa.Float()),
        sa.Column("last_location_at", sa.DateTime(timezone=True)),
        sa.Column("fcm_token", sa.Text(), nullable=False, server_default=""),
        sa.Column("app_version", sa.String(32), nullable=False, server_default=""),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), **ts),
        sa.Column("updated_at", sa.DateTime(timezone=True), **ts),
    )
    op.create_index("ix_riders_status", "riders", ["status"])

    op.create_table(
        "rider_payouts",
        sa.Column("id", uid, primary_key=True),
        sa.Column("rider_user_id", uid, sa.ForeignKey("riders.user_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("period_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_to", sa.DateTime(timezone=True), nullable=False),
        sa.Column("amount", sa.Numeric(10, 2), nullable=False),
        sa.Column("reference", sa.String(120), nullable=False, server_default=""),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by_user_id", uid, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), **ts),
        sa.Column("updated_at", sa.DateTime(timezone=True), **ts),
    )

    op.create_table(
        "rider_offers",
        sa.Column("id", uid, primary_key=True),
        sa.Column("order_delivery_id", uid, sa.ForeignKey("order_deliveries.id", ondelete="CASCADE"), nullable=False),
        sa.Column("rider_user_id", uid, sa.ForeignKey("riders.user_id", ondelete="CASCADE"), nullable=False),
        sa.Column("offered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("responded_at", sa.DateTime(timezone=True)),
        sa.Column("outcome", _enum("rider_offer_outcome"), nullable=False, server_default="PENDING"),
        sa.Column("distance_to_pickup_m", sa.Float()),
        sa.Column("created_at", sa.DateTime(timezone=True), **ts),
        sa.Column("updated_at", sa.DateTime(timezone=True), **ts),
    )
    op.create_index("uq_rider_offers_one_pending", "rider_offers", ["order_delivery_id"],
                    unique=True, postgresql_where=sa.text("outcome = 'PENDING'"))
    op.create_index("ix_rider_offers_rider", "rider_offers", ["rider_user_id", "outcome"])

    op.create_table(
        "rider_trips",
        sa.Column("id", uid, primary_key=True),
        sa.Column("order_delivery_id", uid, sa.ForeignKey("order_deliveries.id", ondelete="CASCADE"), nullable=False),
        sa.Column("rider_user_id", uid, sa.ForeignKey("riders.user_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("arrived_pickup_at", sa.DateTime(timezone=True)),
        sa.Column("picked_up_at", sa.DateTime(timezone=True)),
        sa.Column("arrived_drop_at", sa.DateTime(timezone=True)),
        sa.Column("delivered_at", sa.DateTime(timezone=True)),
        sa.Column("ended_at", sa.DateTime(timezone=True)),
        sa.Column("end_reason", _enum("rider_trip_end_reason")),
        sa.Column("call_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("distance_km", sa.Float()),
        sa.Column("earning_amount", sa.Numeric(10, 2)),
        sa.Column("earning_breakdown", postgresql.JSONB()),
        sa.Column("applied_actions", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("payout_id", uid, sa.ForeignKey("rider_payouts.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), **ts),
        sa.Column("updated_at", sa.DateTime(timezone=True), **ts),
    )
    op.create_index("uq_rider_trips_one_live", "rider_trips", ["order_delivery_id"],
                    unique=True, postgresql_where=sa.text("ended_at IS NULL"))
    op.create_index("ix_rider_trips_rider", "rider_trips", ["rider_user_id", "accepted_at"])

    op.add_column("order_deliveries", sa.Column("delivery_otp_hash", sa.String(128), nullable=False, server_default=""))
    op.add_column("order_deliveries", sa.Column("otp_attempts", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("order_deliveries", sa.Column("otp_locked", sa.Boolean(), nullable=False, server_default="false"))

    _uniqueness(PLATFORM_ROLES)

    for table in NEW_TABLES:
        op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    _uniqueness(OLD_PLATFORM_ROLES)
    for column in ("otp_locked", "otp_attempts", "delivery_otp_hash"):
        op.drop_column("order_deliveries", column)
    for table in ("rider_trips", "rider_offers", "rider_payouts", "riders"):
        op.drop_table(table)
    bind = op.get_bind()
    for name in ("rider_trip_end_reason", "rider_offer_outcome", "rider_vehicle_type", "rider_status"):
        postgresql.ENUM(name=name).drop(bind, checkfirst=True)
    # 'RIDER' stays in user_role / order_event_actor: Postgres cannot remove an
    # enum value. Delete or re-role RIDER accounts before downgrading.
```

Check the real enum type names (`user_role`, `order_event_actor`) against `0071_kitchen_staff.py` lines 88-92 before running.

- [ ] **Step 7: Run the test — expect PASS**; then round-trip the migration on a throwaway local DB (never Supabase):

```bash
cd backend
./.venv/Scripts/python.exe -m unittest discover -s tests -p "test_fleet_schema.py" -v
# migration round trip against a scratch local DB:
DATABASE_URL=postgresql+psycopg://postgres:postgres@127.0.0.1:5432/rr_mig_check ./.venv/Scripts/python.exe -m alembic upgrade head
DATABASE_URL=... ./.venv/Scripts/python.exe -m alembic downgrade -1 && DATABASE_URL=... ./.venv/Scripts/python.exe -m alembic upgrade head
```

Expected: 3 tests OK; upgrade → downgrade → upgrade with no error. (Create `rr_mig_check` first with `psql`; drop it afterwards.)

- [ ] **Step 8: Full suite** — `./.venv/Scripts/python.exe -m unittest discover -s tests > ../.superpowers/t1.log 2>&1; tail -5 ../.superpowers/t1.log`. Expected: same pass count as before + 3, no new failures (the ~24 pre-existing `test_ordering_agent_*` failures excepted — compare against the count before the task).

- [ ] **Step 9: Commit (only if the user has asked to commit)**

```bash
git add backend/alembic/versions/0089_own_fleet.py backend/app/models backend/app/config/settings.py backend/tests/fleet_harness.py backend/tests/test_fleet_schema.py
git commit -m "feat(fleet): rider role, fleet tables and delivery OTP columns"
```

---

## Task 2: Fleet settings and the pay formula

**Files:**
- Create: `backend/app/services/fleet/__init__.py` (empty docstring), `backend/app/services/fleet/config.py`, `backend/app/services/fleet/earnings.py`, `backend/tests/test_fleet_config.py`

**Interfaces:**
- Produces:
  - `RiderPay(base: Decimal, per_km: Decimal, minimum: Decimal)`; `FleetConfig(offer_seconds:int, max_offers:int, window_minutes:int, radius_km:float, silent_minutes:int, location_ids:list[str])` (empty list = every branch).
  - `load_pay(db) -> RiderPay`, `load_fleet(db) -> FleetConfig`, `save_pay(db, user, data: dict) -> RiderPay`, `save_fleet(db, user, data: dict) -> FleetConfig` (raise `HTTPException(422)` on invalid).
  - `earning_for(km: float, pay: RiderPay) -> tuple[Decimal, dict]`.

- [ ] **Step 1: Failing tests** `backend/tests/test_fleet_config.py`

```python
"""What a rider is paid, and the dispatch dials, both set by the super admin.

Defaults ship in code so nothing needs saving before the first trip:
Rs 25 + Rs 6/km, never under Rs 30. A saved value that would pay nothing or
offer for zero seconds is refused, because it applies to every trip at once.
"""

from __future__ import annotations

import unittest
from decimal import Decimal

from fastapi import HTTPException

from fleet_harness import FleetDB, postgres_available
from app.services.fleet import config, earnings


class PayFormulaTests(unittest.TestCase):
    def test_base_plus_per_km(self) -> None:
        pay = config.RiderPay(base=Decimal("25"), per_km=Decimal("6"), minimum=Decimal("30"))
        amount, parts = earnings.earning_for(4.0, pay)
        self.assertEqual(amount, Decimal("49.00"))
        self.assertEqual(parts, {"base": "25", "per_km": "6", "km": 4.0, "minimum": "30"})

    def test_short_trip_gets_the_minimum(self) -> None:
        pay = config.RiderPay(base=Decimal("10"), per_km=Decimal("2"), minimum=Decimal("30"))
        self.assertEqual(earnings.earning_for(1.0, pay)[0], Decimal("30.00"))

    def test_km_is_rounded_to_one_decimal(self) -> None:
        pay = config.default_pay()
        self.assertEqual(earnings.earning_for(3.04, pay)[0], Decimal("43.00"))


@unittest.skipUnless(postgres_available(), "local Postgres is not running")
class SavedSettingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fdb = FleetDB("restaurant_rag_fleet_config_test")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.fdb.drop()

    def test_defaults_when_nothing_saved(self) -> None:
        with self.fdb.session() as db:
            self.assertEqual(config.load_pay(db), config.default_pay())
            fleet = config.load_fleet(db)
            self.assertEqual((fleet.offer_seconds, fleet.max_offers, fleet.window_minutes), (30, 5, 4))

    def test_admin_saves_and_reads_back(self) -> None:
        with self.fdb.session() as db:
            admin = self.fdb.make_admin(db)
            config.save_pay(db, admin, {"base": "30", "per_km": "7", "minimum": "35"})
            self.assertEqual(config.load_pay(db).per_km, Decimal("7"))

    def test_nonsense_is_refused(self) -> None:
        with self.fdb.session() as db:
            admin = self.fdb.make_admin(db)
            for bad in ({"base": "0", "per_km": "0", "minimum": "0"}, {"base": "-1", "per_km": "6", "minimum": "30"}):
                with self.subTest(bad=bad), self.assertRaises(HTTPException):
                    config.save_pay(db, admin, bad)
            with self.assertRaises(HTTPException):
                config.save_fleet(db, admin, {"offer_seconds": 0})
```

- [ ] **Step 2: Run — expect FAIL** (`ModuleNotFoundError: app.services.fleet`).

- [ ] **Step 3: Implement** `config.py`

```python
"""The fleet's two admin-set records in `platform_settings`.

Same shape as `delivery/slabs.py`: defaults in code, an admin row overrides,
a savepoint read so a database without the row (or the table) costs nothing,
and validation that refuses a value which would be wrong for every trip at once.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from decimal import Decimal, InvalidOperation

from fastapi import HTTPException, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

PAY_KEY = "rider_pay"
FLEET_KEY = "own_fleet"


@dataclass(frozen=True, slots=True)
class RiderPay:
    base: Decimal
    per_km: Decimal
    minimum: Decimal


@dataclass(frozen=True, slots=True)
class FleetConfig:
    offer_seconds: int = 30
    max_offers: int = 5
    window_minutes: int = 4
    radius_km: float = 6.0
    silent_minutes: int = 3
    #: Branches the fleet serves; empty means every branch. A visible list on
    #: the admin page, never a constant in code (the deleted AI allowlist).
    location_ids: list[str] = field(default_factory=list)


def default_pay() -> RiderPay:
    return RiderPay(base=Decimal("25"), per_km=Decimal("6"), minimum=Decimal("30"))


def _read(db: Session | None, key: str) -> dict | None:
    if db is None:
        return None
    from app.models.platform_setting import PlatformSetting

    try:
        with db.begin_nested():
            row = db.get(PlatformSetting, key)
    except SQLAlchemyError:
        logger.warning("platform_settings unreadable; using fleet defaults for %s", key)
        return None
    return dict(row.value or {}) if row is not None else None


def _write(db: Session, user, key: str, value: dict) -> None:
    from app.models.platform_setting import PlatformSetting

    row = db.get(PlatformSetting, key)
    if row is None:
        db.add(PlatformSetting(key=key, value=value, updated_by_user_id=user.id))
    else:
        row.value = value
        row.updated_by_user_id = user.id
    db.commit()
    logger.info("%s changed by %s: %s", key, user.id, value)


def _refuse(message: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=message)


def _money(value, name: str) -> Decimal:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError):
        raise _refuse(f"{name} must be a number") from None
    if amount < 0 or amount > 1000:
        raise _refuse(f"{name} must be between 0 and 1000")
    return amount


def validate_pay(data: dict) -> RiderPay:
    pay = RiderPay(
        base=_money(data.get("base"), "Base pay"),
        per_km=_money(data.get("per_km"), "Pay per km"),
        minimum=_money(data.get("minimum"), "Minimum per trip"),
    )
    if pay.base == 0 and pay.per_km == 0 and pay.minimum == 0:
        raise _refuse("A trip must pay something")
    return pay


def load_pay(db: Session | None) -> RiderPay:
    raw = _read(db, PAY_KEY)
    if not raw:
        return default_pay()
    try:
        return validate_pay(raw)
    except HTTPException:
        logger.error("Saved rider pay is invalid; using defaults: %s", raw)
        return default_pay()


def save_pay(db: Session, user, data: dict) -> RiderPay:
    pay = validate_pay(data)
    _write(db, user, PAY_KEY, {"base": str(pay.base), "per_km": str(pay.per_km), "minimum": str(pay.minimum)})
    return load_pay(db)


def _int(data: dict, name: str, low: int, high: int, default: int) -> int:
    value = data.get(name, default)
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise _refuse(f"{name} must be a whole number") from None
    if not low <= number <= high:
        raise _refuse(f"{name} must be between {low} and {high}")
    return number


def validate_fleet(data: dict) -> FleetConfig:
    base = FleetConfig()
    radius = data.get("radius_km", base.radius_km)
    try:
        radius = float(radius)
    except (TypeError, ValueError):
        raise _refuse("radius_km must be a number") from None
    if not 0.5 <= radius <= 25:
        raise _refuse("radius_km must be between 0.5 and 25")
    ids = data.get("location_ids", [])
    if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
        raise _refuse("location_ids must be a list of branch ids")
    return FleetConfig(
        offer_seconds=_int(data, "offer_seconds", 10, 120, base.offer_seconds),
        max_offers=_int(data, "max_offers", 1, 20, base.max_offers),
        window_minutes=_int(data, "window_minutes", 1, 30, base.window_minutes),
        radius_km=radius,
        silent_minutes=_int(data, "silent_minutes", 1, 30, base.silent_minutes),
        location_ids=ids,
    )


def load_fleet(db: Session | None) -> FleetConfig:
    raw = _read(db, FLEET_KEY)
    if not raw:
        return FleetConfig()
    try:
        return validate_fleet(raw)
    except HTTPException:
        logger.error("Saved fleet config is invalid; using defaults: %s", raw)
        return FleetConfig()


def save_fleet(db: Session, user, data: dict) -> FleetConfig:
    fleet = validate_fleet(data)
    _write(db, user, FLEET_KEY, asdict(fleet))
    return load_fleet(db)
```

`earnings.py`

```python
"""What one trip pays the rider. Pure, so admin, app and payouts agree."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from app.services.fleet.config import RiderPay


def earning_for(km: float, pay: RiderPay) -> tuple[Decimal, dict]:
    # One decimal of a km: the distance comes from a road estimate, and
    # paying to the metre would suggest a precision nobody measured.
    rounded = round(max(km, 0.0), 1)
    amount = pay.base + pay.per_km * Decimal(str(rounded))
    amount = max(amount, pay.minimum).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return amount, {"base": str(pay.base), "per_km": str(pay.per_km), "km": rounded, "minimum": str(pay.minimum)}
```

- [ ] **Step 4: Run — expect PASS** (`test_fleet_config`: 6 OK). Note 3.04 km → 3.0 → 25 + 18 = 43.00.
- [ ] **Step 5: Full suite, then commit** `feat(fleet): rider pay and dispatch settings`.

---

## Task 3: Rider accounts (admin) and the RIDER guard

**Files:**
- Create: `backend/app/services/fleet/riders.py`, `backend/app/schemas/rider.py`, `backend/app/api/admin_riders.py`, `backend/tests/test_fleet_riders_admin.py`
- Modify: `backend/app/services/auth.py` (add `require_rider = _require_role(UserRole.RIDER)`), `backend/app/api/__init__.py` (include router), `frontend-admin/src/types` `UserRole` union gets `'RIDER'` and `AdminUsersPage` `ROLE_META` gets a RIDER entry (CLAUDE.md: a missing role takes the Users page down).

**Interfaces:**
- Produces (service): `create_rider(db, admin, *, full_name, phone_number, password, vehicle_type, vehicle_number, city, notes="") -> User`; `update_rider(db, admin, user_id, **fields) -> User` (fields: full_name, vehicle_type, vehicle_number, city, notes, is_active, password); `list_riders(db) -> list[tuple[User, Rider]]`; `go_offline(db, rider_user_id, reason: str) -> None` (sets OFFLINE, withdraws PENDING offers).
- Produces (API, all `require_admin`): `GET /admin/riders`, `POST /admin/riders`, `PATCH /admin/riders/{user_id}`, `GET /admin/riders/live`.
- Schemas: `RiderCreate`, `RiderUpdate`, `RiderResponse{user_id, full_name, phone_number, is_active, vehicle_type, vehicle_number, city, status, last_latitude, last_longitude, last_location_at, active_order_id|None, notes}`.

- [ ] **Step 1: Failing tests** — `test_fleet_riders_admin.py` (TestClient with `app.dependency_overrides[get_current_user]`, same as `test_delivery_pricing_admin.py`):

```python
"""Only the super admin hires and lets go of riders, and letting go is immediate."""

# imports and harness as in test_delivery_pricing_admin.py, plus fleet_harness.FleetDB

class RiderAdminTests(unittest.TestCase):
    # setUpClass: FleetDB("restaurant_rag_fleet_riders_admin_test"); override get_db to its Session

    def test_admin_creates_a_rider_who_can_sign_in_by_phone(self):
        r = self.client_as(self.admin).post("/api/admin/riders", json={
            "full_name": "Ravi", "phone_number": "9876543210", "password": "s3cret-pass",
            "vehicle_type": "BIKE", "vehicle_number": "GJ05AB1234", "city": "Surat"})
        self.assertEqual(r.status_code, 201, r.text)
        login = self.client.post("/api/auth/login", json={"phone_number": "9876543210", "password": "s3cret-pass"})
        self.assertEqual(login.status_code, 200, login.text)
        self.assertEqual(login.json()["user"]["role"], "RIDER")

    def test_same_phone_twice_is_409(self):
        body = {"full_name": "A", "phone_number": "9876500001", "password": "s3cret-pass",
                "vehicle_type": "BIKE", "vehicle_number": "X", "city": "Surat"}
        self.assertEqual(self.client_as(self.admin).post("/api/admin/riders", json=body).status_code, 201)
        self.assertEqual(self.client_as(self.admin).post("/api/admin/riders", json=body).status_code, 409)

    def test_owner_and_kitchen_cannot_see_riders(self):
        for user in (self.owner, self.kitchen):
            with self.subTest(role=user.role):
                self.assertEqual(self.client_as(user).get("/api/admin/riders").status_code, 403)

    def test_deactivation_ends_shift(self):
        # Review Focus 5
        rider = self.make_online_rider_with_pending_offer()
        r = self.client_as(self.admin).patch(f"/api/admin/riders/{rider.id}", json={"is_active": False})
        self.assertEqual(r.status_code, 200)
        with self.fdb.session() as db:
            row = db.get(Rider, rider.id); user = db.get(User, rider.id)
            self.assertEqual(row.status, RiderStatus.OFFLINE)
            self.assertGreater(user.token_version, rider.token_version)
            self.assertEqual(db.scalar(select(RiderOffer.outcome).where(RiderOffer.rider_user_id == rider.id)),
                             OfferOutcome.WITHDRAWN)

    def test_short_password_is_refused(self):
        r = self.client_as(self.admin).post("/api/admin/riders", json={
            "full_name": "A", "phone_number": "9876500002", "password": "123",
            "vehicle_type": "BIKE", "vehicle_number": "X", "city": "Surat"})
        self.assertEqual(r.status_code, 422)
```

Write `client_as`, `make_online_rider_with_pending_offer` (creates rider via `fdb.make_rider`, an order + `OrderDelivery(provider="own_fleet", state="PENDING")`, and a PENDING `RiderOffer` expiring in 30 s) inside the test class.

- [ ] **Step 2: Run — expect FAIL** (404 on `/api/admin/riders`).

- [ ] **Step 3: Implement** `services/fleet/riders.py`

```python
"""Hiring, editing and letting go of riders, and a rider's shift state.

Deactivation bumps `token_version` (like kitchen staff and the Users page),
so the app is signed out on its next request rather than when its token
expires, and the rider is taken offline with any open offer withdrawn so
the loop moves to the next rider immediately.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.enums import OfferOutcome, RiderStatus, UserRole, VehicleType
from app.models.rider import Rider, RiderOffer
from app.models.user import User
from app.services.auth import hash_password, normalize_phone_number

logger = logging.getLogger(__name__)
MIN_PASSWORD = 8


def _now() -> datetime:
    return datetime.now(UTC)


def create_rider(db: Session, admin: User, *, full_name: str, phone_number: str, password: str,
                 vehicle_type: VehicleType, vehicle_number: str, city: str, notes: str = "") -> User:
    phone = normalize_phone_number(phone_number)
    if not phone:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Enter a valid phone number")
    if len(password) < MIN_PASSWORD:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Password must be at least {MIN_PASSWORD} characters")
    user = User(full_name=full_name.strip(), phone_number=phone, email=None,
                hashed_password=hash_password(password), role=UserRole.RIDER, is_active=True)
    db.add(user)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "A staff account already uses this phone number") from None
    db.add(Rider(user_id=user.id, vehicle_type=vehicle_type, vehicle_number=vehicle_number.strip().upper(),
                 city=city.strip(), notes=notes, status=RiderStatus.OFFLINE, status_at=_now()))
    db.commit()
    logger.info("Rider %s created by %s", user.id, admin.id)
    return user


def get_rider(db: Session, user_id: uuid.UUID) -> tuple[User, Rider]:
    user = db.get(User, user_id)
    rider = db.get(Rider, user_id)
    if user is None or rider is None or user.role != UserRole.RIDER:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Rider not found")
    return user, rider


def withdraw_open_offers(db: Session, rider_user_id: uuid.UUID) -> list[uuid.UUID]:
    rows = db.execute(
        update(RiderOffer)
        .where(RiderOffer.rider_user_id == rider_user_id, RiderOffer.outcome == OfferOutcome.PENDING)
        .values(outcome=OfferOutcome.WITHDRAWN, responded_at=_now())
        .returning(RiderOffer.order_delivery_id)
    ).scalars().all()
    return list(rows)


def go_offline(db: Session, rider_user_id: uuid.UUID, reason: str) -> list[uuid.UUID]:
    """Take a rider off shift; returns deliveries whose offer must move on.

    Never takes a rider on a trip off it - that food is in their hands; the
    caller (sweep / deactivation) raises an alert instead.
    """

    rider = db.get(Rider, rider_user_id)
    if rider is None:
        return []
    released = withdraw_open_offers(db, rider_user_id)
    if rider.status != RiderStatus.ON_TRIP:
        rider.status = RiderStatus.OFFLINE
        rider.status_at = _now()
    logger.info("Rider %s offline: %s", rider_user_id, reason)
    return released


def update_rider(db: Session, admin: User, user_id: uuid.UUID, **fields) -> User:
    user, rider = get_rider(db, user_id)
    released: list[uuid.UUID] = []
    for name in ("vehicle_type", "vehicle_number", "city", "notes"):
        if fields.get(name) is not None:
            setattr(rider, name, fields[name])
    if fields.get("full_name"):
        user.full_name = fields["full_name"].strip()
    if fields.get("password"):
        if len(fields["password"]) < MIN_PASSWORD:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Password must be at least {MIN_PASSWORD} characters")
        user.hashed_password = hash_password(fields["password"])
        user.token_version += 1
    if fields.get("is_active") is not None and fields["is_active"] != user.is_active:
        user.is_active = fields["is_active"]
        user.token_version += 1
        if not user.is_active:
            released = go_offline(db, user.id, "deactivated by admin")
    db.commit()
    if released:
        from app.services.fleet import offers

        for delivery_id in released:
            offers.queue_advance(delivery_id)
    return user


def list_riders(db: Session) -> list[tuple[User, Rider]]:
    return list(db.execute(
        select(User, Rider).join(Rider, Rider.user_id == User.id).order_by(User.full_name)
    ).all())
```

> `offers.queue_advance` is produced in Task 5. Until then, Task 3's tests do not hit it with a released offer except `test_deactivation_ends_shift`; implement Task 3 with a local stub `def queue_advance(_id): pass` in a new `services/fleet/offers.py` and replace it in Task 5 (ledger it).

Also the `revoke_sessions` realtime queue: if `services/auth` or kitchen staff code calls a helper that queues `session:revoked` when bumping `token_version` (search `session:revoked` / `queue_session_revoked`), call it here too.

Schemas `schemas/rider.py`:

```python
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.enums import RiderStatus, VehicleType


class RiderCreate(BaseModel):
    full_name: str = Field(min_length=1, max_length=120)
    phone_number: str = Field(min_length=6, max_length=20)
    password: str = Field(min_length=8, max_length=128)
    vehicle_type: VehicleType
    vehicle_number: str = Field(default="", max_length=32)
    city: str = Field(default="", max_length=80)
    notes: str = Field(default="", max_length=2000)


class RiderUpdate(BaseModel):
    full_name: str | None = Field(default=None, max_length=120)
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
```

API `api/admin_riders.py`:

```python
"""The super admin's rider roster. ADMIN only: the fleet is the platform's,
and an owner who could see it could see every other restaurant's deliveries."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.order_delivery import OrderDelivery
from app.models.rider import RiderTrip
from app.models.user import User
from app.schemas.rider import RiderCreate, RiderResponse, RiderUpdate
from app.services.auth import require_admin
from app.services.fleet import riders as svc

router = APIRouter(prefix="/admin/riders", tags=["admin-riders"])
Admin = Annotated[User, Depends(require_admin)]
Db = Annotated[Session, Depends(get_db)]


def _active_orders(db: Session) -> dict[uuid.UUID, uuid.UUID]:
    rows = db.execute(
        select(RiderTrip.rider_user_id, OrderDelivery.order_id)
        .join(OrderDelivery, OrderDelivery.id == RiderTrip.order_delivery_id)
        .where(RiderTrip.ended_at.is_(None))
    ).all()
    return {rider_id: order_id for rider_id, order_id in rows}


def _out(user, rider, active: dict) -> RiderResponse:
    return RiderResponse(
        user_id=user.id, full_name=user.full_name, phone_number=user.phone_number, is_active=user.is_active,
        vehicle_type=rider.vehicle_type, vehicle_number=rider.vehicle_number, city=rider.city,
        status=rider.status, last_latitude=rider.last_latitude, last_longitude=rider.last_longitude,
        last_location_at=rider.last_location_at, active_order_id=active.get(user.id), notes=rider.notes,
    )


@router.get("", response_model=list[RiderResponse])
def list_riders(_: Admin, db: Db) -> list[RiderResponse]:
    active = _active_orders(db)
    return [_out(u, r, active) for u, r in svc.list_riders(db)]


@router.get("/live", response_model=list[RiderResponse])
def live_riders(_: Admin, db: Db) -> list[RiderResponse]:
    active = _active_orders(db)
    return [_out(u, r, active) for u, r in svc.list_riders(db) if u.is_active and r.status != "OFFLINE"]


@router.post("", response_model=RiderResponse, status_code=status.HTTP_201_CREATED)
def create_rider(body: RiderCreate, admin: Admin, db: Db) -> RiderResponse:
    user = svc.create_rider(db, admin, **body.model_dump())
    user, rider = svc.get_rider(db, user.id)
    return _out(user, rider, {})


@router.patch("/{user_id}", response_model=RiderResponse)
def update_rider(user_id: uuid.UUID, body: RiderUpdate, admin: Admin, db: Db) -> RiderResponse:
    svc.update_rider(db, admin, user_id, **body.model_dump(exclude_unset=True))
    user, rider = svc.get_rider(db, user_id)
    return _out(user, rider, _active_orders(db))
```

Check `require_admin` and `get_db` import paths with `grep -rn "require_admin =" app/services/auth.py` and `grep -rn "def get_db" app/` and adjust.

- [ ] **Step 4: Run — expect PASS** (5 tests). Also run `test_kitchen_staff_scope` and the admin users tests to confirm RIDER broke no role switch.
- [ ] **Step 5: Admin types** — add `'RIDER'` to `UserRole` in `frontend-admin/src/types` and a `RIDER` entry to `ROLE_META` in `AdminUsersPage.tsx` (icon `Bike` from lucide-react, label "Rider"). Run `cd frontend-admin && npm run test && npm run build`.
- [ ] **Step 6: Commit** `feat(fleet): admin creates and deactivates riders`.

---

## Task 4: Rider shift — status, location, device token, liveness sweep

**Files:**
- Create: `backend/app/api/rider.py` (first endpoints), `backend/app/tasks/fleet.py` (sweep), `backend/tests/test_fleet_shift.py`
- Modify: `backend/app/services/fleet/riders.py`, `backend/app/schemas/rider.py`, `backend/app/config/celery.py`, `backend/app/api/__init__.py`

**Interfaces:**
- Produces: `set_status(db, user, online: bool) -> Rider` (refuses going offline while ON_TRIP with 409 `on_trip`); `record_locations(db, user, fixes: list[LocationFix]) -> Rider`; `sweep_silent(db, now) -> dict` (returns `{"offline": n, "alerts": [user_ids]}`).
- API (`require_rider`): `GET /rider/me` → `RiderMe{user_id, full_name, phone_number, vehicle_type, vehicle_number, status, today_trips, today_earnings}`; `POST /rider/status {online: bool}`; `POST /rider/location {fixes:[{lat,lng,accuracy_m,at}]}` (1..20); `POST /rider/device-token {token, app_version}`.
- Celery: `app.tasks.fleet.sweep_riders_task` every 60 s.

- [ ] **Step 1: Failing tests** `test_fleet_shift.py`:

```python
class ShiftTests(unittest.TestCase):
    def test_online_then_offline(self): ...          # POST status true -> ONLINE; false -> OFFLINE
    def test_cannot_go_offline_on_a_trip(self): ...  # rider ON_TRIP -> 409 detail "on_trip"
    def test_location_batch_keeps_the_newest(self):
        # fixes out of order: newest 'at' wins, older fix never overwrites newer
        ...
    def test_fix_from_the_future_is_clamped(self): ... # at > now+60s -> stored as now
    def test_bad_coordinates_are_422(self): ...        # lat 95 -> 422
    def test_only_riders_reach_rider_routes(self): ... # ADMIN/OWNER/CUSTOMER -> 403
    def test_sweep_takes_silent_rider_offline(self):
        # last_location_at = now - 4 min, ONLINE -> OFFLINE; ON_TRIP stays, listed in alerts
        ...
    def test_location_on_a_trip_reaches_the_delivery_row(self):
        # ON_TRIP rider with live trip -> order_deliveries.rider_latitude/longitude/location_at updated
        ...
```

Write each body fully, using `fdb.make_rider`, `fdb.make_order`, an `OrderDelivery(provider="own_fleet")` and a `RiderTrip` for trip cases, and `TestClient` with `get_current_user` overridden to the rider.

- [ ] **Step 2: Run — expect FAIL.**

- [ ] **Step 3: Implement** in `riders.py`:

```python
from dataclasses import dataclass
from datetime import timedelta


@dataclass(slots=True)
class LocationFix:
    lat: float
    lng: float
    at: datetime
    accuracy_m: float | None = None


def set_status(db: Session, user: User, online: bool) -> Rider:
    rider = db.get(Rider, user.id)
    if online:
        if rider.status == RiderStatus.OFFLINE:
            rider.status, rider.status_at = RiderStatus.ONLINE, _now()
    else:
        if rider.status == RiderStatus.ON_TRIP:
            raise HTTPException(status.HTTP_409_CONFLICT, "on_trip")
        go_offline(db, user.id, "rider went offline")
    db.commit()
    return rider


def record_locations(db: Session, user: User, fixes: list[LocationFix]) -> Rider:
    from app.models.order_delivery import OrderDelivery
    from app.models.rider import RiderTrip

    rider = db.get(Rider, user.id)
    now = _now()
    newest = max(fixes, key=lambda f: f.at)
    at = min(newest.at, now)  # a phone clock ahead of ours must not pin "fresh" forever
    if rider.last_location_at and at <= rider.last_location_at:
        return rider  # a late batch never moves the rider backwards
    rider.last_latitude, rider.last_longitude, rider.last_location_at = newest.lat, newest.lng, at
    trip = db.scalar(select(RiderTrip).where(RiderTrip.rider_user_id == user.id, RiderTrip.ended_at.is_(None)))
    if trip is not None:
        delivery = db.get(OrderDelivery, trip.order_delivery_id)
        delivery.rider_latitude, delivery.rider_longitude, delivery.rider_location_at = newest.lat, newest.lng, at
        from app.services.fleet import notify

        notify.order_moved(db, delivery)  # throttled hint, Task 8
    db.commit()
    return rider


def sweep_silent(db: Session, now: datetime | None = None) -> dict:
    from app.services.fleet.config import load_fleet

    now = now or _now()
    cutoff = now - timedelta(minutes=load_fleet(db).silent_minutes)
    silent = db.scalars(select(Rider).where(
        Rider.status != RiderStatus.OFFLINE,
        (Rider.last_location_at.is_(None)) | (Rider.last_location_at < cutoff),
    )).all()
    offline, alerts, released = 0, [], []
    for rider in silent:
        if rider.status == RiderStatus.ON_TRIP:
            alerts.append(str(rider.user_id))
            continue
        released += go_offline(db, rider.user_id, "no location for too long")
        offline += 1
    db.commit()
    from app.services.fleet import offers

    for delivery_id in released:
        offers.queue_advance(delivery_id)
    return {"offline": offline, "alerts": alerts}
```

`notify.order_moved` doesn't exist until Task 8: create `services/fleet/notify.py` now with `def order_moved(db, delivery): pass` and a docstring "filled in Task 8"; ledger it.

Schemas: `StatusUpdate{online: bool}`, `LocationFixIn{lat: float = Field(ge=-90, le=90); lng: float = Field(ge=-180, le=180); accuracy_m: float | None = Field(default=None, ge=0, le=5000); at: datetime}`, `LocationBatch{fixes: list[LocationFixIn] = Field(min_length=1, max_length=20)}`, `DeviceToken{token: str = Field(min_length=10, max_length=4096); app_version: str = Field(default="", max_length=32)}`, `RiderMe`.

API `api/rider.py`:

```python
"""The rider app's API. RIDER only; every row is the caller's own, and anything
else is 404 - a rider learns nothing about another rider's work."""

router = APIRouter(prefix="/rider", tags=["rider"])
RiderUser = Annotated[User, Depends(require_rider)]

@router.get("/me", response_model=RiderMe) ...           # today = trips with accepted_at >= local midnight (Asia/Kolkata via settings tz)
@router.post("/status", response_model=RiderMe) ...
@router.post("/location", status_code=204) ...
@router.post("/device-token", status_code=204) ...       # stores fcm_token + app_version
```

Rate-limit `/rider/location` with the existing `rate_limit.per_ip` at 30/minute per user (look at how `api/traffic.py` uses it).

Task `tasks/fleet.py`:

```python
"""Fleet background work: the offer loop's safety net and the liveness sweep."""

from app.config.celery import celery_app
from app.db.session import SessionLocal


@celery_app.task(name="app.tasks.fleet.sweep_riders_task")
def sweep_riders_task() -> dict:
    from app.services.fleet.riders import sweep_silent

    with SessionLocal() as db:
        return sweep_silent(db)
```

Add `"app.tasks.fleet"` to `include` and a beat entry `"fleet-sweep-riders": {"task": "app.tasks.fleet.sweep_riders_task", "schedule": 60.0}` guarded by `if settings.enable_own_fleet` (same pattern as the delivery refresh at celery.py:110-123). Check `SessionLocal` import path in `app/tasks/delivery.py` and copy it.

- [ ] **Step 4: Run — expect PASS** (8 tests); full suite.
- [ ] **Step 5: Commit** `feat(fleet): rider shift, location and liveness sweep`.

---

## Task 5: The offer loop

**Files:**
- Create/replace: `backend/app/services/fleet/offers.py`, `backend/tests/test_fleet_offers.py`
- Modify: `backend/app/tasks/fleet.py` (`advance_offers_task`, `advance_delivery_task`), `backend/app/config/celery.py` (beat 10 s)

**Interfaces:**
- Consumes: `load_fleet`, `Rider`, `RiderOffer`, `RiderTrip`, `OrderDelivery`, `notify.offer_made(db, offer)` / `notify.offer_withdrawn(db, offer)` (stubs until Task 8), `service.fallback_to_pidge(db, delivery, reason)` (Task 6; stub raising `NotImplementedError` is NOT acceptable — implement Task 5 tests with `mock.patch` on it).
- Produces:
  - `haversine_m(lat1, lng1, lat2, lng2) -> float`
  - `candidates(db, delivery, fleet, now) -> list[tuple[Rider, float]]` nearest first
  - `advance(db, delivery_id, now=None) -> str` — one step of the loop; returns `"offered" | "waiting" | "fallback" | "assigned" | "closed"`
  - `accept(db, rider_user, offer_id, now=None) -> RiderTrip` — raises `HTTPException(409, "offer_taken"|"offer_expired")`, 404 for another rider's offer
  - `decline(db, rider_user, offer_id) -> None`
  - `queue_advance(delivery_id: uuid.UUID) -> None` — after-commit Celery enqueue of `advance_delivery_task`
  - `current_offer(db, rider_user) -> RiderOffer | None`
  - `reassign(db, admin, delivery, rider_user_id) -> RiderOffer`

- [ ] **Step 1: Failing tests** `test_fleet_offers.py`:

```python
"""Offering a delivery to riders, one at a time, nearest first.

The money question here is "two riders, one order": the partial unique
index allows one PENDING offer per delivery and one live trip per delivery,
and accept locks the delivery row, so a double tap or a race resolves to
exactly one trip.
"""

class OfferLoopTests(unittest.TestCase):
    # FleetDB("restaurant_rag_fleet_offers_test"); each test makes its own order + OrderDelivery(provider="own_fleet", state="PENDING")

    def test_nearest_online_rider_is_offered_first(self):
        # riders at 0.5 km, 2 km, 9 km (outside 6 km radius), and an OFFLINE one at 0.1 km
        # advance -> "offered"; the offer is to the 0.5 km rider, expires_at = now + 30 s
        ...

    def test_stale_location_is_not_a_candidate(self):
        # rider 0.2 km away but last_location_at 5 min ago -> not offered
        ...

    def test_expired_offer_moves_to_the_next_rider(self):
        # advance(now) offers A; advance(now + 31 s) marks A EXPIRED and offers B
        ...

    def test_decline_moves_on_and_never_reoffers_the_same_rider(self):
        ...

    def test_max_offers_then_pidge(self):
        # max_offers=2 saved; A expires, B expires -> advance returns "fallback";
        # service.fallback_to_pidge called once with reason "no rider accepted"
        ...

    def test_nobody_online_goes_straight_to_pidge(self):
        # reason "no rider online nearby"
        ...

    def test_window_elapsed_goes_to_pidge(self):
        # delivery.created_at = now - 5 min, window 4 -> fallback reason "no rider within 4 minutes"
        ...

    def test_accept_creates_trip_and_assigns(self):
        # accept -> trip row, rider ON_TRIP, delivery.state == ASSIGNED, rider_name/mobile set,
        # timeline has {"event": "assigned"}
        ...

    def test_two_accepts_one_wins(self):
        # Review Focus 1. Reassign hack: create offer to A, then mark it ACCEPTED path via a second
        # session concurrently: two threads call accept(...) for the same offer with separate sessions;
        # assert exactly one RiderTrip exists and the other raised HTTPException(409).
        ...

    def test_accept_after_expiry_is_409_expired(self): ...
    def test_another_riders_offer_is_404(self): ...
    def test_cash_order_is_never_offered(self):
        # payment_method CASH_ON_DELIVERY -> advance returns "fallback", reason "cash order"
        ...
    def test_branch_not_in_location_ids_goes_to_pidge(self):
        # fleet.location_ids = [other branch] -> fallback reason "branch not on the fleet"
        ...
    def test_admin_reassign_withdraws_and_offers_named_rider(self): ...
```

Fill each body with concrete setup and asserts as described in its comment. For the race test use `threading.Thread` + `threading.Barrier(2)` and two `fdb.session()`s.

- [ ] **Step 2: Run — expect FAIL.**

- [ ] **Step 3: Implement** `offers.py`

```python
"""Offering a delivery to the platform's riders, one at a time, nearest first.

`advance` is one step of a small state machine and is safe to call any number
of times from anywhere - the API after a decline, a Celery task after an
accept window, the 10 s beat as a safety net. It locks the delivery row, so
two callers at once take turns rather than offering twice.
"""

from __future__ import annotations

import logging
import math
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.enums import OfferOutcome, PaymentMethod, RiderStatus
from app.models.order import Order
from app.models.order_delivery import OrderDelivery
from app.models.rider import Rider, RiderOffer, RiderTrip
from app.models.user import User
from app.services.delivery.base import DeliveryState
from app.services.fleet.config import FleetConfig, load_fleet

logger = logging.getLogger(__name__)
PROVIDER = "own_fleet"


def _now() -> datetime:
    return datetime.now(UTC)


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _timeline(delivery: OrderDelivery, event: str, **data) -> None:
    entries = list(delivery.timeline or [])
    entries.append({"event": event, "at": _now().isoformat(), **data})
    delivery.timeline = entries


def candidates(db: Session, delivery: OrderDelivery, fleet: FleetConfig, now: datetime) -> list[tuple[Rider, float]]:
    order = db.get(Order, delivery.order_id)
    branch = order.restaurant_location
    if branch.latitude is None or branch.longitude is None:
        return []
    tried = set(db.scalars(select(RiderOffer.rider_user_id).where(RiderOffer.order_delivery_id == delivery.id)))
    fresh_after = now - timedelta(minutes=fleet.silent_minutes)
    rows = db.execute(
        select(Rider).join(User, User.id == Rider.user_id).where(
            Rider.status == RiderStatus.ONLINE, User.is_active.is_(True),
            Rider.last_location_at >= fresh_after,
            Rider.last_latitude.is_not(None), Rider.last_longitude.is_not(None),
        )
    ).scalars().all()
    limit = fleet.radius_km * 1000
    out = []
    for rider in rows:
        if rider.user_id in tried:
            continue
        busy = db.scalar(select(RiderOffer.id).where(
            RiderOffer.rider_user_id == rider.user_id, RiderOffer.outcome == OfferOutcome.PENDING))
        if busy:
            continue  # one open offer per rider: they can only look at one alert
        metres = haversine_m(rider.last_latitude, rider.last_longitude, float(branch.latitude), float(branch.longitude))
        if metres <= limit:
            out.append((rider, metres))
    return sorted(out, key=lambda pair: pair[1])


def _refusal(db: Session, delivery: OrderDelivery, fleet: FleetConfig, now: datetime) -> str | None:
    order = db.get(Order, delivery.order_id)
    if order.payment_method == PaymentMethod.CASH_ON_DELIVERY:
        return "cash order"
    if fleet.location_ids and str(order.restaurant_location_id) not in fleet.location_ids:
        return "branch not on the fleet"
    if delivery.created_at and now - delivery.created_at > timedelta(minutes=fleet.window_minutes):
        return f"no rider within {fleet.window_minutes} minutes"
    tried = db.scalar(select(func_count()).where(RiderOffer.order_delivery_id == delivery.id))
    if tried >= fleet.max_offers:
        return "no rider accepted"
    return None


def func_count():
    from sqlalchemy import func

    return func.count(RiderOffer.id)


def advance(db: Session, delivery_id: uuid.UUID, now: datetime | None = None) -> str:
    from app.services.delivery import service as delivery_service
    from app.services.fleet import notify

    now = now or _now()
    delivery = db.scalar(select(OrderDelivery).where(OrderDelivery.id == delivery_id).with_for_update())
    if delivery is None or delivery.provider != PROVIDER or DeliveryState(delivery.state).is_terminal:
        db.rollback()
        return "closed"
    if db.scalar(select(RiderTrip.id).where(RiderTrip.order_delivery_id == delivery.id, RiderTrip.ended_at.is_(None))):
        db.rollback()
        return "assigned"
    fleet = load_fleet(db)
    open_offer = db.scalar(select(RiderOffer).where(
        RiderOffer.order_delivery_id == delivery.id, RiderOffer.outcome == OfferOutcome.PENDING))
    if open_offer is not None:
        if open_offer.expires_at > now:
            db.rollback()
            return "waiting"
        open_offer.outcome, open_offer.responded_at = OfferOutcome.EXPIRED, now
        _timeline(delivery, "offer_expired", rider=str(open_offer.rider_user_id))
        db.flush()
        notify.offer_withdrawn(db, open_offer)

    reason = _refusal(db, delivery, fleet, now)
    pool = [] if reason else candidates(db, delivery, fleet, now)
    if not reason and not pool:
        reason = "no rider online nearby"
    if reason:
        _timeline(delivery, "fallback", reason=reason)
        delivery_service.fallback_to_pidge(db, delivery, reason)
        db.commit()
        return "fallback"

    rider, metres = pool[0]
    offer = RiderOffer(order_delivery_id=delivery.id, rider_user_id=rider.user_id, offered_at=now,
                       expires_at=now + timedelta(seconds=fleet.offer_seconds), distance_to_pickup_m=metres)
    db.add(offer)
    _timeline(delivery, "offered", rider=str(rider.user_id), metres=round(metres))
    db.commit()
    notify.offer_made(db, offer)
    schedule_expiry(delivery.id, fleet.offer_seconds)
    return "offered"


def accept(db: Session, rider_user: User, offer_id: uuid.UUID, now: datetime | None = None) -> RiderTrip:
    now = now or _now()
    offer = db.get(RiderOffer, offer_id)
    if offer is None or offer.rider_user_id != rider_user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Offer not found")
    delivery = db.scalar(select(OrderDelivery).where(OrderDelivery.id == offer.order_delivery_id).with_for_update())
    db.refresh(offer)
    if offer.outcome != OfferOutcome.PENDING:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "offer_taken")
    if offer.expires_at <= now:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "offer_expired")
    offer.outcome, offer.responded_at = OfferOutcome.ACCEPTED, now
    trip = RiderTrip(order_delivery_id=delivery.id, rider_user_id=rider_user.id, accepted_at=now)
    db.add(trip)
    rider = db.get(Rider, rider_user.id)
    rider.status, rider.status_at = RiderStatus.ON_TRIP, now
    delivery.state = DeliveryState.ASSIGNED.value
    delivery.rider_name = rider_user.full_name or "Rider"
    delivery.rider_mobile = rider_user.phone_number or ""
    delivery.allocated_at = now
    delivery.provider_order_id = delivery.provider_order_id or f"fleet-{delivery.id}"
    _timeline(delivery, "assigned", rider=str(rider_user.id))
    try:
        db.commit()
    except IntegrityError:
        # uq_rider_trips_one_live: someone else's accept committed first.
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "offer_taken") from None
    from app.services.fleet import notify

    notify.trip_changed(db, trip)
    return trip


def decline(db: Session, rider_user: User, offer_id: uuid.UUID) -> None:
    offer = db.get(RiderOffer, offer_id)
    if offer is None or offer.rider_user_id != rider_user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Offer not found")
    if offer.outcome == OfferOutcome.PENDING:
        offer.outcome, offer.responded_at = OfferOutcome.DECLINED, _now()
        db.commit()
    queue_advance(offer.order_delivery_id)


def current_offer(db: Session, rider_user: User) -> RiderOffer | None:
    return db.scalar(select(RiderOffer).where(
        RiderOffer.rider_user_id == rider_user.id, RiderOffer.outcome == OfferOutcome.PENDING,
        RiderOffer.expires_at > _now()))


def reassign(db: Session, admin: User, delivery: OrderDelivery, rider_user_id: uuid.UUID) -> RiderOffer:
    from app.services.fleet import trips

    trips.end_live_trip(db, delivery, reason="REASSIGNED")
    for offer in db.scalars(select(RiderOffer).where(
            RiderOffer.order_delivery_id == delivery.id, RiderOffer.outcome == OfferOutcome.PENDING)):
        offer.outcome, offer.responded_at = OfferOutcome.WITHDRAWN, _now()
    fleet = load_fleet(db)
    now = _now()
    offer = RiderOffer(order_delivery_id=delivery.id, rider_user_id=rider_user_id, offered_at=now,
                       expires_at=now + timedelta(seconds=fleet.offer_seconds))
    db.add(offer)
    _timeline(delivery, "reassigned", by=str(admin.id), rider=str(rider_user_id))
    db.commit()
    from app.services.fleet import notify

    notify.offer_made(db, offer)
    return offer


def queue_advance(delivery_id: uuid.UUID) -> None:
    from app.tasks.fleet import advance_delivery_task

    try:
        advance_delivery_task.delay(str(delivery_id))
    except Exception:  # noqa: BLE001 - the 10 s beat picks it up
        logger.warning("Could not queue advance for %s; the beat will", delivery_id)


def schedule_expiry(delivery_id: uuid.UUID, seconds: int) -> None:
    from app.tasks.fleet import advance_delivery_task

    try:
        advance_delivery_task.apply_async((str(delivery_id),), countdown=seconds + 1)
    except Exception:  # noqa: BLE001
        logger.warning("Could not schedule expiry for %s; the beat will", delivery_id)
```

> Note `delivery.created_at` is from `TimestampMixin` (aware datetime). `trips.end_live_trip` is produced in Task 7; until then `reassign`'s test patches it. In the race test, `with_for_update()` serialises the two accepts; the unique index is the second guard.

Tasks:

```python
@celery_app.task(name="app.tasks.fleet.advance_delivery_task")
def advance_delivery_task(delivery_id: str) -> str:
    from app.services.fleet.offers import advance

    with SessionLocal() as db:
        return advance(db, uuid.UUID(delivery_id))


@celery_app.task(name="app.tasks.fleet.advance_offers_task")
def advance_offers_task() -> dict:
    """Safety net: anything own-fleet and not yet assigned gets one step."""
    from sqlalchemy import select
    from app.models.order_delivery import OrderDelivery
    from app.services.fleet.offers import PROVIDER, advance

    counts: dict[str, int] = {}
    with SessionLocal() as db:
        ids = db.scalars(select(OrderDelivery.id).where(
            OrderDelivery.provider == PROVIDER, OrderDelivery.state == "PENDING")).all()
    for delivery_id in ids:
        with SessionLocal() as db:
            result = advance(db, delivery_id)
        counts[result] = counts.get(result, 0) + 1
    return counts
```

Beat: `"fleet-advance-offers": {"task": "app.tasks.fleet.advance_offers_task", "schedule": 10.0}` under the `enable_own_fleet` guard. Route both fleet tasks to the `notifications` queue (`task_routes` in celery.py — copy how `send_kitchen_new_order_notification` is routed).

- [ ] **Step 4: Run — expect PASS** (14 tests). Run 3 times (race test must be stable).
- [ ] **Step 5: Commit** `feat(fleet): offer loop with accept race protection`.

---

## Task 6: The fleet as a courier, and the fallback to Pidge

**Files:**
- Create: `backend/app/services/delivery/own_fleet_provider.py`, `backend/tests/test_fleet_courier.py`
- Modify: `backend/app/services/delivery/registry.py`, `backend/app/services/delivery/service.py`, `backend/app/services/platform_watch.py`

**Interfaces:**
- Produces: `OwnFleetProvider` implementing the `DeliveryProvider` protocol (`name="own_fleet"`, `is_configured()->True`, `quote(...)` → delegates to `slabs` pricing exactly as the current quote path does, `create(request)->DeliveryResult(state=PENDING, provider_order_id=f"fleet-{uuid}")`, `fetch(id)` → reads the row, `cancel(id)` → no network call, `parse_webhook` → raises `DeliveryProviderError("no webhook")`).
- `registry.dispatch_provider() -> DeliveryProvider | None` — own fleet when `enable_own_fleet`, else `delivery_provider()`. `registry.pidge_provider() -> DeliveryProvider | None` — the existing courier (what `delivery_provider()` returns today).
- `service.dispatch` uses `dispatch_provider()`; after creating an own-fleet row it calls `offers.queue_advance(row.id)` after commit.
- `service.fallback_to_pidge(db, delivery, reason) -> None`: if `pidge_provider()` is None → `delivery.last_error = f"No rider and no courier: {reason}"`, `state` stays PENDING, `platform_watch` sees it; else set `provider = pidge.name`, `attempt += 1`, `provider_order_id = ""`, then `dispatch` the order again via the Pidge provider (reuse `rebook` internals: read `rebook` lines 623-666 and call the shared part).
- Quotes are **unchanged**: `quote` keeps using whatever `delivery_provider()` returns today (customer price comes from slabs anyway).

- [ ] **Step 1: Failing tests** `test_fleet_courier.py`:

```python
class FleetCourierTests(unittest.TestCase):
    def test_flag_off_dispatch_goes_to_pidge_as_before(self):
        # ENABLE_OWN_FLEET unset -> dispatch_provider() is delivery_provider(); no own_fleet row
        ...
    def test_flag_on_dispatch_creates_pending_own_fleet_row_and_queues_offer(self):
        # patch offers.queue_advance; dispatch(order) -> row.provider == "own_fleet", state PENDING,
        # queue_advance called with row.id
        ...
    def test_fallback_repoints_the_same_row_to_pidge(self):
        # fake pidge provider (mock with create() returning DeliveryResult(provider_order_id="P1", state=PENDING))
        # fallback_to_pidge(row, "no rider accepted") -> same row id, provider "pidge", attempt 2, provider_order_id "P1"
        ...
    def test_no_rider_and_no_pidge_is_visible(self):
        # Review Focus 4: pidge_provider() None -> row PENDING, last_error mentions reason,
        # platform_watch check returns a red item naming the order; no exception
        ...
    def test_customer_cancellation_cancels_fleet_without_network(self):
        # service.cancel(order) on own_fleet row -> state CANCELLED, offers WITHDRAWN (Task 7 hook)
        ...
```

- [ ] **Step 2: Run — expect FAIL.**
- [ ] **Step 3: Implement** the provider (copy method signatures exactly from `base.py` Protocol lines 222-260 and from `rehearsal_provider.py`), the two registry functions, the `dispatch` switch, and `fallback_to_pidge`. In `platform_watch.py` add `_check_fleet(db)`: red if any `own_fleet` delivery is PENDING with `last_error` starting "No rider and no courier", or any rider ON_TRIP with no location for `silent_minutes`; label "Own delivery fleet". Follow the shape of `_check_maps`.
- [ ] **Step 4: Run — expect PASS**; then the whole delivery suite: `-p "test_delivery_*.py"` — all still green (flag off is byte-identical).
- [ ] **Step 5: Commit** `feat(fleet): own fleet is a courier; Pidge takes over when nobody accepts`.

---

## Task 7: Trips — actions, OTP, cancellation, earnings

**Files:**
- Create: `backend/app/services/fleet/trips.py`, `backend/app/services/fleet/otp.py`, `backend/tests/test_fleet_trips.py`
- Modify: `backend/app/api/rider.py`, `backend/app/schemas/rider.py`, `backend/app/services/delivery/service.py` (`cancel` hook)

**Interfaces:**
- Produces:
  - `otp.code_for(order_id: uuid.UUID) -> str` (4 digits, HMAC-SHA256 of order id with `rider_otp_secret or jwt secret`, `int(hex[:8],16) % 10000`, zero-padded); `otp.hash_code(code) -> str`; `otp.matches(delivery, code) -> bool` (constant-time).
  - `trips.act(db, rider_user, trip_id, action: str, action_id: str, otp: str | None = None) -> RiderTrip` with action in `arrived_pickup | picked_up | arrived_drop | delivered | unavailable | call_logged`. Errors: 404 not theirs; 409 `out_of_order`; 409 `otp_locked`; 422 `otp_wrong` (with `attempts_left`); 409 `too_early` for `unavailable`.
  - `trips.end_live_trip(db, delivery, reason: str) -> RiderTrip | None` (sets ended_at, end_reason, rider back ONLINE, computes pay per the cancellation rule).
  - `trips.on_order_cancelled(db, delivery) -> None` (withdraw offers + end trip with `CANCELLED_BEFORE_PICKUP`/`CANCELLED_AFTER_PICKUP`).
  - `trips.admin_confirm_delivered(db, admin, delivery, reason: str) -> RiderTrip`.
  - `trips.active_trip(db, rider_user) -> RiderTrip | None`; `trips.trip_view(db, trip) -> dict` (restaurant name/phone/address/lat/lng, customer first name/phone/address/lat/lng, items [{name, qty}], step, earning estimate, order code).
- API: `GET /rider/trip` (204 when none), `POST /rider/trip/{id}/{action}` body `{action_id: str(8..64), otp?: str}`, `GET /rider/offers/current` (204 when none) returning `OfferView{id, expires_at, seconds_left, restaurant_name, pickup_distance_m, trip_distance_km, earning_estimate, area}`, `POST /rider/offers/{id}/accept`, `POST /rider/offers/{id}/decline`, `GET /rider/earnings?from&to` → `{total, paid, unpaid, days:[{date, trips, amount}], trips:[...]}`, `GET /rider/trips?cursor&limit` (history).

State mapping (from the spec) — each action calls `service.record(db, delivery, DeliveryResult(...))` so `advance_order` moves the order exactly as Pidge does:

| action | requires | sets | DeliveryState |
|---|---|---|---|
| arrived_pickup | accepted | arrived_pickup_at | ASSIGNED |
| picked_up | arrived_pickup_at | picked_up_at | PICKED_UP |
| arrived_drop | picked_up_at | arrived_drop_at | IN_TRANSIT |
| delivered | arrived_drop_at, OTP ok | delivered_at, ended_at, end_reason DELIVERED, earning | DELIVERED |
| unavailable | arrived_drop_at + 10 min, call_attempts ≥ 2 | ended_at, CUSTOMER_UNAVAILABLE, earning | FAILED |
| call_logged | any live step | call_attempts += 1 | — |

- [ ] **Step 1: Failing tests** `test_fleet_trips.py`:

```python
class TripTests(unittest.TestCase):
    def test_happy_path_moves_the_order(self):
        # accept -> arrived_pickup -> picked_up (order OUT_FOR_DELIVERY) -> arrived_drop
        # -> delivered with otp.code_for(order.id) -> order DELIVERED, trip.earning_amount == earning_for(km)
        # rider back ONLINE
        ...
    def test_steps_cannot_be_skipped(self):        # picked_up before arrived_pickup -> 409 out_of_order
        ...
    def test_retry_is_idempotent(self):
        # Review Focus 2: picked_up twice with same action_id -> 200 both, one timeline event,
        # one order_status_event for OUT_FOR_DELIVERY
        ...
    def test_wrong_otp_counts_down_then_locks(self):
        # 5 wrong -> 6th call 409 otp_locked even with the right code
        ...
    def test_admin_confirm_unlocks_and_completes(self):
        # timeline entry has admin id + reason; trip DELIVERED
        ...
    def test_unavailable_needs_wait_and_two_calls(self):
        # immediately -> 409 too_early; after 2 call_logged and arrived_drop_at - 11 min -> FAILED
        ...
    def test_cancel_during_trip_pays_after_arrival(self):
        # Review Focus 3: (a) cancelled before arrived_pickup -> earning 0, CANCELLED_BEFORE_PICKUP
        # (b) after arrived_pickup -> earning = pay.minimum, end_reason CANCELLED_BEFORE_PICKUP
        # (c) after picked_up -> earning_for(km), CANCELLED_AFTER_PICKUP. Rider ONLINE afterwards.
        ...
    def test_another_riders_trip_is_404(self): ...
    def test_otp_is_four_digits_and_stable(self):
        # code_for(id) == code_for(id), len 4, differs across 20 ids (not all equal)
        ...
    def test_offer_view_shows_earning_estimate(self): ...
```

- [ ] **Step 2: Run — expect FAIL.**
- [ ] **Step 3: Implement** `otp.py`:

```python
"""The 4-digit code a customer reads to the rider.

Derived, not stored: HMAC of the order id under a server secret, so the
customer's order page can show it without a column holding it in clear, and
a database read alone does not let anyone complete a delivery. Four digits is
guessable in 10,000 tries, which is why the rider gets five.
"""

import hashlib
import hmac
import uuid

from app.config import get_settings

MAX_ATTEMPTS = 5


def _secret() -> bytes:
    s = get_settings()
    return (s.rider_otp_secret or s.jwt_secret_key).encode()


def code_for(order_id: uuid.UUID) -> str:
    digest = hmac.new(_secret(), f"delivery-otp:{order_id}".encode(), hashlib.sha256).hexdigest()
    return f"{int(digest[:8], 16) % 10000:04d}"


def hash_code(code: str) -> str:
    return hashlib.sha256(f"{code}".encode()).hexdigest()


def matches(order_id: uuid.UUID, code: str) -> bool:
    return hmac.compare_digest(code_for(order_id), (code or "").strip())
```

(Check the real JWT secret attribute name in settings: `grep -n "jwt" app/config/settings.py`.) Store `delivery_otp_hash = hash_code(code_for(order.id))` when the fleet row is created (Task 6 `create`) — used only to show admin "OTP issued".

`trips.py`: implement `act` with `SELECT … FOR UPDATE` on the trip, the table above, `applied_actions` for idempotency (if `action_id in trip.applied_actions` → return trip unchanged), timeline entries, `service.record(db, delivery, DeliveryResult(provider_order_id=delivery.provider_order_id, state=..., picked_up_at=..., delivered_at=..., rider_name=..., rider_mobile=...))`, earnings via `earning_for(km, load_pay(db))` where `km = (delivery.distance_metres or haversine(branch, drop) * settings.delivery_road_factor) / 1000`, rider status back to ONLINE on end, `notify.trip_changed(db, trip)` after commit. In `service.cancel`, when `row.provider == "own_fleet"`, call `trips.on_order_cancelled(db, row)` instead of a courier API call.

- [ ] **Step 4: Run — expect PASS** (10 tests); full suite.
- [ ] **Step 5: Commit** `feat(fleet): trip steps, delivery OTP and rider earnings`.

---

## Task 8: Telling the rider — realtime room and push

**Files:**
- Modify: `backend/app/services/fleet/notify.py` (replace stubs), `backend/app/services/realtime/rooms.py`, `backend/app/services/realtime/server.py`, `backend/app/services/realtime/outbox.py` (generic queued emit if not present)
- Create: `backend/tests/test_fleet_notify.py`

**Interfaces:**
- Produces: `rooms.rider_room(user_id) -> str` (`f"rider:{user_id}"`); a RIDER socket joins only that room (never a staff room — `is_staff_role` must return False for RIDER so it does not enter the staff branch). Events (payload ids only): `rider:offer {offer_id}`, `rider:offer_withdrawn {offer_id}`, `rider:trip_updated {trip_id}`, `rider:trip_cancelled {trip_id}`.
- `notify.offer_made(db, offer)`: realtime emit after commit + FCM **data-only, high priority** message to `rider.fcm_token`: `{"type": "rider_offer", "offer_id": ..., "expires_at": iso}` with `android=AndroidConfig(priority="high", ttl=offer_seconds)`; on `UnregisteredError` clear `fcm_token` (reuse `_should_deactivate_token`). Behind `enable_realtime` / Firebase availability exactly like kitchen push; never raises.
- `notify.offer_withdrawn`, `notify.trip_changed`, `notify.trip_cancelled` (realtime + data push for cancelled).
- `notify.order_moved(db, delivery)`: queue the existing `order:updated` hint for the order, at most once per 10 s per delivery (Redis `SET NX EX 10` key `fleet:moved:{delivery_id}`; Redis down → emit anyway).

- [ ] **Step 1: Failing tests** — mock the emitter and `messaging.send`:
  - offer_made emits `rider:offer` to `rider:{id}` only and sends one data message with `priority="high"` and no `notification` block (data-only so the app's handler shows the full-screen alert itself);
  - a RIDER socket connect joins `rider:{id}` and nothing else; an OWNER socket never joins a rider room;
  - `order_moved` twice within 10 s emits once;
  - an unregistered token is cleared;
  - with Firebase unconfigured nothing raises.
- [ ] **Step 2: Run — expect FAIL.**
- [ ] **Step 3: Implement**, reading `services/kitchen_push.py` for the Firebase pattern and `realtime/server.py` for where staff rooms are chosen (add the RIDER branch before the staff branch).
- [ ] **Step 4: Run — expect PASS**; run `test_realtime*` too.
- [ ] **Step 5: Commit** `feat(fleet): offers reach the rider by socket and push`.

---

## Task 9: Admin operations — reassign, confirm, settings, payouts

**Files:**
- Modify: `backend/app/api/admin_riders.py`, `backend/app/schemas/rider.py`, `backend/app/api/delivery.py` (or wherever the admin Delivery panel reads; `grep -rn "DeliveryPanel\|/delivery" app/api`)
- Create: `backend/app/services/fleet/payouts.py`, `backend/tests/test_fleet_admin_ops.py`

**Interfaces (all ADMIN only):**
- `GET /admin/riders/settings` → `{pay: {base, per_km, minimum}, fleet: FleetConfig}`; `PUT /admin/riders/settings/pay`; `PUT /admin/riders/settings/fleet`.
- `POST /admin/riders/deliveries/{order_id}/reassign {rider_user_id}` → `OfferView`.
- `POST /admin/riders/deliveries/{order_id}/confirm-delivered {reason: str(5..500)}`.
- `GET /admin/riders/deliveries/{order_id}` → `{provider, state, offers:[{rider, outcome, offered_at, responded_at, metres}], trip: {...}|None, fallback_reason|None, otp_locked}`.
- `GET /admin/riders/payouts/unpaid` → `[{rider_user_id, full_name, trips, amount, oldest}]`.
- `POST /admin/riders/{user_id}/payouts {period_to, reference}` → marks every ended, unpaid trip with `ended_at <= period_to` paid; amount = sum; 409 if nothing to pay.
- `GET /admin/riders/{user_id}/trips?from&to`.
- The existing admin delivery serializer gains `own_fleet: {...}|None` so `DeliveryPanel` can show it (Plan 3).

- [ ] **Step 1: Failing tests:** settings round trip and 403 for OWNER; reassign to an OFFLINE rider is 409 `rider_offline`; payout sums exactly the unpaid ended trips and a second payout for the same period is 409; a trip paid is never in "unpaid" again; owner cannot read `/admin/riders/deliveries/{id}` (403).
- [ ] **Step 2: Run — expect FAIL.**
- [ ] **Step 3: Implement** (`payouts.py`: `unpaid_summary(db)`, `pay_rider(db, admin, rider_user_id, period_to, reference) -> RiderPayout`, using `SELECT … FOR UPDATE` on the trips so two clicks cannot pay twice).
- [ ] **Step 4: Run — expect PASS**; full suite.
- [ ] **Step 5: Export the OpenAPI** for Plan 2: `./.venv/Scripts/python.exe -c "import json; from app.main import app; json.dump(app.openapi(), open('../docs/superpowers/plans/rider-openapi.json','w'), indent=1)"`.
- [ ] **Step 6: Commit** `feat(fleet): admin reassign, confirm, pay settings and payouts`.

---

## Task 10: Customer sees the OTP; docs

**Files:**
- Modify: the order response schema + builder (`grep -rn "class OrderResponse\|def serialize_order" app/`), `backend/docs/delivery-integration.md`, `CLAUDE.md`, `backend/docs/security.md`
- Create: `backend/tests/test_fleet_customer_otp.py`

**Interfaces:**
- `OrderResponse.delivery.otp: str | None` — set only when the viewer is the order's customer, provider is `own_fleet`, and state in `ASSIGNED, PICKED_UP, IN_TRANSIT`. Owners, kitchen, admin and other customers get `None`.

- [ ] **Step 1: Failing tests:** customer sees 4 digits during the trip; `None` before assignment and after DELIVERED; OWNER/KITCHEN/ADMIN see `None`; Pidge order → `None`.
- [ ] **Step 2: Run — expect FAIL.**  **Step 3: Implement.**  **Step 4: Run — PASS**, full suite.
- [ ] **Step 5: Docs.** In `delivery-integration.md` add "## The platform's own fleet" (courier shape, offer loop, fallback, OTP, the flag, how to test locally). In `CLAUDE.md` add a short "## Own delivery fleet" section (RIDER role, `services/fleet/`, rules that fail silently: one pending offer / one live trip indexes, fallback re-points the same row, OTP derived not stored, cash never offered, flag default off) and add `0089_own_fleet` to the migrations rough-edges list with "user applies to Supabase themselves". In `security.md` add the rider surface (404 rule, OTP, token revocation).
- [ ] **Step 6: Commit** `feat(fleet): customer sees the delivery code; fleet documented`.

---

## Local end-to-end check (after Task 10)

With `ENABLE_OWN_FLEET=true`, `ENABLE_DELIVERY_DISPATCH=true` and the rehearsal/local guard in `.env` (local only), start API + worker (`--pool=solo --logfile logs/celery.log`) + beat, then with `curl`/HTTPie as a rider: login → status online → location near a branch → place a card order on the storefront and accept it in the kitchen board → `GET /rider/offers/current` shows it → accept → walk the actions → customer order page shows the OTP → deliver with it → order DELIVERED, `GET /rider/earnings` shows the amount. Then stop the rider (offline) and repeat: the order must go to Pidge (sandbox) with the fallback reason in the admin delivery view.

## Self-review notes

- Spec coverage: role/tables (T1), pay + dispatch settings (T2), roster + deactivation (T3), shift/location/liveness (T4), offer loop + accept race + reassign (T5), courier + fallback + watch (T6), trip steps + OTP + cancellation + unavailable + earnings (T7), realtime + FCM (T8), admin ops + payouts (T9), customer OTP + docs (T10). Rider app, admin UI and storefront UI are Plans 2–4.
- Stubs introduced early and replaced later are each named in the task that introduces them (`queue_advance` T3→T5, `notify.*` T4/T5→T8, `trips.end_live_trip` patched in T5 tests, produced in T7) and must be ledgered.
