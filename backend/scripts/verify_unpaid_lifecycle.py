"""Against the real database: would a Razorpay order now be swept?

The unit tests prove the query names both methods. This proves the rest of
the sentence against real rows — that the reaper's own SELECT finds orders it
previously could not see, and that nothing about a COD order changed.

Read-only. It runs the reaper's query, not the reaper.

    python scripts/verify_unpaid_lifecycle.py
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta

sys.path.insert(0, "F:/restaurant-rag/backend")

from sqlalchemy import func, select

from app.config import get_settings
from app.config.database import SessionLocal
from app.models.enums import OrderStatus, PaymentMethod, PaymentStatus
from app.models.order import Order
from app.models.restaurant import Restaurant
from app.services.payments.registry import GATEWAY_FOR_METHOD

GREEN, RED, OFF = "\033[32m", "\033[31m", "\033[0m"


def main() -> int:
    settings = get_settings()
    ttl = max(1, settings.payment_intent_ttl_minutes)
    cutoff = datetime.now(UTC) - timedelta(minutes=ttl)

    with SessionLocal() as db:
        print(f"payment_intent_ttl_minutes = {ttl}  (cutoff {cutoff:%Y-%m-%d %H:%M} UTC)\n")

        print("Unpaid orders now, by method:")
        rows = db.execute(
            select(Order.payment_method, func.count())
            .where(Order.status == OrderStatus.PAYMENT_PENDING)
            .group_by(Order.payment_method)
        ).all()
        if not rows:
            print("  (none)")
        for method, count in rows:
            reaped = "swept" if method in GATEWAY_FOR_METHOD else "left alone (no gateway)"
            print(f"  {method.value:<12} {count:>4}   -> {reaped}")

        old_query = select(func.count()).where(
            Order.status == OrderStatus.PAYMENT_PENDING,
            Order.payment_method == PaymentMethod.CARD,
            Order.placed_at < cutoff,
        )
        new_query = select(func.count()).where(
            Order.status == OrderStatus.PAYMENT_PENDING,
            Order.payment_method.in_(list(GATEWAY_FOR_METHOD)),
            Order.placed_at < cutoff,
        )
        before, after = db.scalar(old_query), db.scalar(new_query)
        print(f"\nStale past the TTL:  card-only query {before}   ->   every gateway {after}")
        if after >= before:
            print(f"  {GREEN}PASS{OFF} the sweep never sees less than it used to")
        else:
            print(f"  {RED}FAIL{OFF} the new query finds FEWER orders")
            return 1

        # The rows the old query could never reach, named so they can be
        # eyeballed rather than taken on trust.
        missed = db.execute(
            select(Order.id, Order.payment_method, Order.placed_at, Order.total_amount,
                   Order.currency, Restaurant.name)
            .join(Restaurant, Restaurant.id == Order.restaurant_id)
            .where(
                Order.status == OrderStatus.PAYMENT_PENDING,
                Order.payment_method.in_(list(GATEWAY_FOR_METHOD)),
                Order.payment_method != PaymentMethod.CARD,
                Order.placed_at < cutoff,
            )
            .order_by(Order.placed_at)
            .limit(10)
        ).all()
        print(f"\nStale non-card orders the old sweep ignored: {len(missed)}")
        for order_id, method, placed, total, currency, restaurant in missed:
            print(f"  {str(order_id)[:8]}  {method.value:<9} {restaurant:<18} "
                  f"{currency} {total}  placed {placed:%Y-%m-%d %H:%M}")

        cod = db.scalar(
            select(func.count()).where(
                Order.status == OrderStatus.PAYMENT_PENDING,
                Order.payment_method == PaymentMethod.COD,
            )
        )
        print(f"\nCOD orders sitting in PAYMENT_PENDING: {cod}")
        print(f"  {GREEN}PASS{OFF} cash is outside the sweep either way"
              if PaymentMethod.COD not in GATEWAY_FOR_METHOD else f"  {RED}FAIL{OFF}")

        paid = db.scalar(
            select(func.count()).where(
                Order.status == OrderStatus.PAYMENT_PENDING,
                Order.payment_status == PaymentStatus.PAID,
            )
        )
        print(f"\nAlready-PAID orders still in PAYMENT_PENDING: {paid}"
              f"   {'(these are what reconciliation rescues)' if paid else ''}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
