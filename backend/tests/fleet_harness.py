"""A throwaway Postgres database for the fleet tests, built from create_all.

Shared by the test_fleet_* files only, so each does not repeat sixty lines of
setup; every other suite in this folder owns its own copy, as
test_delivery_pricing_admin.py does. Skips cleanly when Postgres is down.
"""

from __future__ import annotations

import sys
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import app.models  # noqa: E402,F401  - registers every table on Base.metadata
from app.config import get_settings  # noqa: E402
from app.models.app_client import AppClient  # noqa: E402
from app.models.base import Base  # noqa: E402
from app.models.enums import (  # noqa: E402
    AppMode,
    OrderFulfillmentType,
    OrderStatus,
    PaymentMethod,
    RiderStatus,
    UserRole,
    VehicleType,
)
from app.models.order import Order  # noqa: E402
from app.models.order_delivery import OrderDelivery  # noqa: E402
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


def _suffix() -> str:
    return uuid.uuid4().hex[:8]


class FleetDB:
    """One database per test class: create in setUpClass, drop in tearDownClass."""

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

    def ensure_marketplace(self, db) -> AppClient:
        """The default app client login falls back to when no bundle id is sent."""

        key = settings.default_app_client_key
        client = db.query(AppClient).filter(AppClient.key == key).one_or_none()
        if client is None:
            client = AppClient(key=key, display_name="Marketplace", app_mode=AppMode.MARKETPLACE)
            db.add(client)
            db.flush()
        return client

    # --- people ---------------------------------------------------------------

    def make_admin(self, db) -> User:
        user = User(
            email=f"admin-{_suffix()}@example.com",
            full_name="Platform Admin",
            hashed_password=hash_password("password123"),
            role=UserRole.ADMIN,
            is_active=True,
        )
        db.add(user)
        db.flush()
        return user

    def make_owner(self, db) -> User:
        user = User(
            email=f"owner-{_suffix()}@example.com",
            full_name="Owner",
            hashed_password=hash_password("password123"),
            role=UserRole.OWNER,
            is_active=True,
        )
        db.add(user)
        db.flush()
        return user

    def make_rider(
        self,
        db,
        *,
        lat: float | None = 21.17,
        lng: float | None = 72.83,
        status: RiderStatus = RiderStatus.ONLINE,
        phone: str | None = None,
        name: str = "Ravi Rider",
        seen_at: datetime | None = None,
    ) -> User:
        digits = phone or f"98{uuid.uuid4().int % 10**8:08d}"
        user = User(
            email=f"rider.{digits}@riders.invalid",
            phone_number=f"+91{digits[-10:]}",
            full_name=name,
            hashed_password=hash_password("password123"),
            role=UserRole.RIDER,
            is_active=True,
        )
        db.add(user)
        db.flush()
        db.add(
            Rider(
                user_id=user.id,
                vehicle_type=VehicleType.BIKE,
                vehicle_number="GJ05AB1234",
                city="Surat",
                status=status,
                last_latitude=lat,
                last_longitude=lng,
                last_location_at=seen_at or (datetime.now(UTC) if lat is not None else None),
            )
        )
        db.flush()
        return user

    # --- an order that needs delivering ---------------------------------------

    def make_order(
        self,
        db,
        *,
        lat: float = 21.18,
        lng: float = 72.84,
        payment: PaymentMethod = PaymentMethod.CARD,
        status: OrderStatus = OrderStatus.ACCEPTED,
    ) -> Order:
        client = AppClient(key=f"mkt-{_suffix()}", display_name="Marketplace", app_mode=AppMode.MARKETPLACE)
        db.add(client)
        db.flush()
        customer = User(
            email=f"cust-{_suffix()}@example.com",
            full_name="Asha Customer",
            phone_number="+919876511111",
            hashed_password=hash_password("password123"),
            role=UserRole.CUSTOMER,
            app_client_id=client.id,
            is_active=True,
        )
        owner = self.make_owner(db)
        db.add(customer)
        db.flush()
        restaurant = Restaurant(
            owner_id=owner.id,
            name="Bhagwati Bakery",
            slug=f"bhagwati-{_suffix()}",
            cuisine_type="Bakery",
            address_line_1="Rander Road",
            city="Surat",
            state="Gujarat",
            postal_code="395009",
        )
        db.add(restaurant)
        db.flush()
        location = RestaurantLocation(
            restaurant_id=restaurant.id,
            branch_name="Main",
            address_line_1="Rander Road",
            city="Surat",
            state="Gujarat",
            postal_code="395009",
            latitude=Decimal(str(lat)),
            longitude=Decimal(str(lng)),
        )
        db.add(location)
        db.flush()
        order = Order(
            customer_id=customer.id,
            restaurant_id=restaurant.id,
            restaurant_location_id=location.id,
            status=status,
            fulfillment_type=OrderFulfillmentType.DELIVERY,
            payment_method=payment,
            subtotal=Decimal("200.00"),
            total_amount=Decimal("268.00"),
            currency="INR",
            delivery_address="12 Adajan Gam, Surat, Gujarat, 395009",
            delivery_latitude=21.20,
            delivery_longitude=72.80,
            contact_name="Asha Customer",
            contact_phone="+919876511111",
        )
        db.add(order)
        db.flush()
        return order

    def make_fleet_delivery(self, db, order: Order, **over) -> OrderDelivery:
        row = OrderDelivery(
            order_id=order.id,
            provider=over.pop("provider", "own_fleet"),
            provider_order_id=over.pop("provider_order_id", f"fleet-{_suffix()}"),
            state=over.pop("state", "PENDING"),
            distance_metres=over.pop("distance_metres", 4000.0),
            **over,
        )
        db.add(row)
        db.flush()
        return row


def client_for(fdb: FleetDB, user: User | None):
    """A TestClient whose database is `fdb` and whose caller is `user`.

    `user=None` leaves authentication real (for the login test). Overrides are
    cleared by `reset_overrides()` in tearDown, because they live on the one
    shared app object.
    """

    from fastapi.testclient import TestClient

    from app.config.database import get_db
    from app.main import app
    from app.services.auth import get_current_user

    def _db():
        db = fdb.session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _db
    if user is not None:
        app.dependency_overrides[get_current_user] = lambda: user
    else:
        app.dependency_overrides.pop(get_current_user, None)
    return TestClient(app)


def reset_overrides() -> None:
    from app.main import app

    app.dependency_overrides.clear()
