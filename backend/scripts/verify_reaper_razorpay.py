"""Does the reaper now sweep a Razorpay order — and spare a paid one?

Creates a THROWAWAY order row for a real restaurant, ages it past the TTL,
runs the REAL `reap_expired_unpaid_orders`, and deletes the row again. No
call reaches Razorpay: the provider's HTTP layer is stubbed, so this proves
the reaper's own behaviour — which orders it selects, what it asks the
gateway before cancelling, and what it does with each answer.

Two runs, because one of them is the answer to "did we just cancel an order
the customer paid for":

  unpaid  -> the order is CANCELLED and the payment link is cancelled too
  paid    -> nothing is touched, and the order is marked PAID

    python scripts/verify_reaper_razorpay.py "Radhe Dhokla"
"""

from __future__ import annotations

import sys
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest import mock

sys.path.insert(0, "F:/restaurant-rag/backend")

from sqlalchemy import select

from app.config.database import SessionLocal
from app.models.enums import (
    OrderStatus,
    PaymentGateway,
    PaymentMethod,
    PaymentStatus,
    UserRole,
)
from app.models.order import Order
from app.models.payment import PaymentTransaction
from app.models.restaurant import Restaurant
from app.models.restaurant_location import RestaurantLocation
from app.models.user import User
from app.services import payment_accounts
from app.services.payments import service
from app.services.payments.razorpay_provider import RazorpayProvider

GREEN, RED, OFF = "\033[32m", "\033[31m", "\033[0m"

#: Obviously not a credential, and deleted at the end either way.
FAKE_KEY = "rzp_test_THROWAWAY_verification"
LINK_ID = "plink_THROWAWAY"

results: list[bool] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    mark = f"{GREEN}PASS{OFF}" if ok else f"{RED}FAIL{OFF}"
    print(f"  {mark} {label}{('  — ' + detail) if detail else ''}")
    results.append(ok)


def a_stale_order(db, restaurant, location, customer) -> Order:
    """An unpaid Razorpay order, old enough that the reaper wants it."""

    order = Order(
        customer_id=customer.id,
        restaurant_id=restaurant.id,
        restaurant_location_id=location.id,
        status=OrderStatus.PAYMENT_PENDING,
        payment_status=PaymentStatus.PENDING,
        payment_method=PaymentMethod.RAZORPAY,
        subtotal=Decimal("145.00"),
        total_amount=Decimal("145.00"),
        currency=restaurant.currency,
        delivery_address="Throwaway row — scripts/verify_reaper_razorpay.py",
        placed_at=datetime.now(UTC) - timedelta(days=2),
    )
    db.add(order)
    db.flush()
    db.add(
        PaymentTransaction(
            order_id=order.id,
            provider="razorpay",
            provider_intent_id=LINK_ID,
            status=PaymentStatus.PENDING,
            amount=order.total_amount,
            currency=order.currency,
        )
    )
    db.commit()
    return order


def run(db, restaurant, location, customer, *, razorpay_says: str) -> None:
    """One sweep, with Razorpay answering `razorpay_says` about the link."""

    print(f"\n  Razorpay reports the link as {razorpay_says!r}:")
    order = a_stale_order(db, restaurant, location, customer)
    calls: list[tuple[str, str]] = []

    def fake_request(_provider, method, path, **kwargs):
        # Patched on the CLASS, because the reaper builds its own provider
        # per order — so `self` arrives as the first argument here.
        calls.append((method, path))
        if path.endswith("/cancel"):
            return {"id": LINK_ID, "status": "cancelled"}
        return {
            "id": LINK_ID,
            "status": razorpay_says,
            "amount": 14500,
            "amount_paid": 14500 if razorpay_says == "paid" else 0,
            "currency": restaurant.currency,
            "short_url": "https://rzp.io/i/THROWAWAY",
        }

    try:
        with mock.patch.object(RazorpayProvider, "_request", fake_request):
            swept = service.reap_expired_unpaid_orders(db)
        db.expire_all()
        fresh = db.get(Order, order.id)
        paths = [path for _, path in calls]

        check(
            "the order is in the sweep at all",
            any("payment_links" in path for path in paths),
            f"asked Razorpay: {paths or '(nothing)'}",
        )
        if razorpay_says == "paid":
            check("a paid order is NOT cancelled", fresh.status != OrderStatus.CANCELLED,
                  fresh.status.value)
            check("it is marked paid instead", fresh.payment_status == PaymentStatus.PAID,
                  fresh.payment_status.value)
            check("and its link is left alone",
                  not any(path.endswith("/cancel") for path in paths))
        else:
            check("an unpaid order is cancelled", fresh.status == OrderStatus.CANCELLED,
                  f"{fresh.status.value}, swept={swept}")
            check(
                "and the link is cancelled at Razorpay, so it stops being payable",
                any(path.endswith("/cancel") for path in paths),
            )
            check(
                "the gateway was asked BEFORE anything was cancelled",
                paths and not paths[0].endswith("/cancel"),
                " then ".join(paths),
            )
    finally:
        db.execute(
            PaymentTransaction.__table__.delete().where(
                PaymentTransaction.order_id == order.id
            )
        )
        db.execute(Order.__table__.delete().where(Order.id == order.id))
        db.commit()


def main() -> int:
    wanted = sys.argv[1] if len(sys.argv) > 1 else "Radhe Dhokla"

    with SessionLocal() as db:
        restaurant = db.scalar(select(Restaurant).where(Restaurant.name == wanted))
        if restaurant is None:
            print(f"no restaurant called {wanted!r}")
            return 1
        location = db.scalar(
            select(RestaurantLocation)
            .where(RestaurantLocation.restaurant_id == restaurant.id)
            .order_by(RestaurantLocation.branch_name)
            .limit(1)
        )
        customer = db.scalar(select(User).where(User.role == UserRole.CUSTOMER).limit(1))
        if location is None or customer is None:
            print("need a branch and any customer to hang a throwaway order off")
            return 1
        print(f"{restaurant.name} · {location.branch_name} · {restaurant.currency}")

        held = [
            a.gateway
            for a in payment_accounts.list_accounts(db, restaurant_id=restaurant.id)
        ]
        if PaymentGateway.RAZORPAY in held:
            print(f"  {RED}a Razorpay account already exists — not touching it{OFF}")
            return 1

        payment_accounts.save_account(
            db,
            restaurant_id=restaurant.id,
            gateway=PaymentGateway.RAZORPAY,
            public_key=FAKE_KEY,
            secret_key="throwaway-secret",
            webhook_secret="throwaway-webhook-secret",
            is_enabled=True,
            updated_by_user_id=None,
        )
        db.commit()
        try:
            run(db, restaurant, location, customer, razorpay_says="created")
            run(db, restaurant, location, customer, razorpay_says="paid")
        finally:
            payment_accounts.delete_account(
                db, restaurant_id=restaurant.id, gateway=PaymentGateway.RAZORPAY
            )
            db.commit()
            # Confirmed from a session that never saw the row, so a stale
            # identity map cannot report success.
            with SessionLocal() as fresh:
                left = any(
                    a.gateway == PaymentGateway.RAZORPAY
                    for a in payment_accounts.list_accounts(fresh, restaurant_id=restaurant.id)
                )
                orders = fresh.scalars(
                    select(Order).where(
                        Order.delivery_address.like("Throwaway row%")
                    )
                ).all()
            print(
                "\n  throwaway account removed: "
                + ("NO — REMOVE IT BY HAND" if left else "yes")
                + f"   throwaway orders left: {len(orders)}"
            )

    print()
    passed = sum(1 for r in results if r)
    print(f"{passed}/{len(results)} checks pass")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
