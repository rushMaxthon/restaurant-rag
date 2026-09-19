"""Does a Razorpay restaurant get offered Razorpay, and a link to pay on?

Saves a THROWAWAY account for the restaurant, walks the path a real order
takes, and deletes the account again. No real credentials, and no call to
Razorpay: the HTTP layer is stubbed, so this proves the wiring above it —
which method is offered, which provider is chosen, what gets stored — and
nothing about the gateway itself.

    python scripts/verify_razorpay_wiring.py "Radhe Dhokla"
"""

from __future__ import annotations

import sys
import uuid
from decimal import Decimal
from unittest import mock

sys.path.insert(0, "F:/restaurant-rag/backend")

from sqlalchemy import select

from app.config.database import SessionLocal
from app.models.enums import PaymentGateway, PaymentMethod
from app.models.restaurant import Restaurant
from app.models.restaurant_location import RestaurantLocation
from app.services import payment_accounts
from app.services.payments.razorpay_provider import RazorpayProvider
from app.services.payments.registry import available_payment_methods, provider_for

GREEN, RED, OFF = "\033[32m", "\033[31m", "\033[0m"

#: Obviously not a credential. Deleted at the end either way.
FAKE_KEY = "rzp_test_THROWAWAY_verification"


def check(label: str, ok: bool, detail: str = "") -> bool:
    mark = f"{GREEN}PASS{OFF}" if ok else f"{RED}FAIL{OFF}"
    print(f"  {mark} {label}{('  — ' + detail) if detail else ''}")
    return ok


def main() -> int:
    wanted = sys.argv[1] if len(sys.argv) > 1 else "Radhe Dhokla"
    results: list[bool] = []

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
        print(f"{restaurant.name} · {location.branch_name} · {restaurant.currency}\n")

        before = available_payment_methods(
            db, restaurant_id=restaurant.id, location=location
        )
        print(f"  before: {[m.value for m in before]}")
        results.append(check(
            "Razorpay is not offered without an account",
            PaymentMethod.RAZORPAY not in before,
        ))

        had_one = any(
            a.gateway == PaymentGateway.RAZORPAY
            for a in payment_accounts.list_accounts(db, restaurant_id=restaurant.id)
        )
        if had_one:
            print(f"\n  {RED}a Razorpay account already exists — not touching it{OFF}")
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
        # `save_account` documents "the caller commits", and the session is
        # autoflush=False — without this the row is invisible even to the
        # session that added it, which is what this script got wrong first.
        db.commit()
        try:
            after = available_payment_methods(
                db, restaurant_id=restaurant.id, location=location
            )
            print(f"\n  after:  {[m.value for m in after]}")
            results.append(check(
                "Razorpay is offered once an account is saved",
                PaymentMethod.RAZORPAY in after,
            ))

            provider = provider_for(
                db, restaurant_id=restaurant.id, method=PaymentMethod.RAZORPAY
            )
            results.append(check(
                "the restaurant's own Razorpay provider is chosen",
                isinstance(provider, RazorpayProvider) and provider.is_configured(),
                type(provider).__name__,
            ))
            results.append(check(
                "it can make a hosted payment link",
                hasattr(provider, "create_checkout_session"),
            ))

            sent: dict = {}

            def fake_request(method, path, **kwargs):
                sent["path"] = path
                sent["json"] = kwargs.get("json")
                return {
                    "id": "plink_VERIFY",
                    "short_url": "https://rzp.io/i/VERIFY",
                    "amount": kwargs["json"]["amount"],
                    "currency": kwargs["json"]["currency"],
                }

            with mock.patch.object(provider, "_request", fake_request):
                result = provider.create_checkout_session(
                    order_id=uuid.uuid4(),
                    customer_id=uuid.uuid4(),
                    restaurant_id=restaurant.id,
                    amount=Decimal("145.00"),
                    currency=restaurant.currency,
                    description="Order VERIFY",
                    customer_email=None,
                    success_url="https://example.test/orders/1",
                    cancel_url="https://example.test/orders/1",
                    idempotency_key="verify",
                )
            results.append(check(
                "the link is asked for in the restaurant's currency",
                sent["json"]["currency"] == restaurant.currency,
                f"{sent['json']['currency']} {sent['json']['amount']} minor units",
            ))
            results.append(check(
                "the link's id is what gets stored as the intent",
                result.intent_id == "plink_VERIFY",
            ))

            card = provider_for(db, restaurant_id=restaurant.id, method=PaymentMethod.CARD)
            results.append(check(
                "card still settles through its own provider",
                card is not None,
                type(card).__name__,
            ))
        finally:
            payment_accounts.delete_account(
                db, restaurant_id=restaurant.id, gateway=PaymentGateway.RAZORPAY
            )
            db.commit()
            # Confirmed from a session that never saw the row, so a stale
            # identity map cannot report success. A throwaway credential left
            # behind is the worst thing a verification script can do.
            with SessionLocal() as fresh:
                still = any(
                    a.gateway == PaymentGateway.RAZORPAY
                    for a in payment_accounts.list_accounts(
                        fresh, restaurant_id=restaurant.id
                    )
                )
            print(
                "\n  throwaway account removed: "
                + ("NO — REMOVE IT BY HAND" if still else "yes")
            )

    print()
    passed = sum(1 for r in results if r)
    print(f"{passed}/{len(results)} checks pass")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
