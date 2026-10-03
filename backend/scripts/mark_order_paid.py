"""Advance an order to PLACED the way a payment webhook would. Testing only.

Printing starts at `PLACED`, which on a card order means a gateway has
confirmed the money. That is correct and it is deliberate — a docket for an
unpaid order has a kitchen cooking food nobody has bought — but it makes
"place an order and watch it print" need a real payment every time.

So this does exactly what `_mark_paid` in `services/payments/service.py` does
when a webhook arrives: sets `payment_status`, records the
PAYMENT_PENDING -> PLACED transition through `record_order_status_event`, and
commits. That is the same function every other path goes through, so the print
hook is exercised honestly rather than bypassed.

It does NOT create a payment transaction, so an order advanced this way shows
no provider reference. Fine for watching a printer; not a substitute for
testing the payment flow.

    # the most recent unpaid order
    ./.venv/Scripts/python.exe scripts/mark_order_paid.py

    # a particular one
    ./.venv/Scripts/python.exe scripts/mark_order_paid.py --order cc354981
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import sqlalchemy as sa  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import selectinload  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.config.database import SessionLocal  # noqa: E402
from app.models.enums import (  # noqa: E402
    OrderEventActor,
    OrderStatus,
    PaymentStatus,
)
from app.models.order import Order  # noqa: E402
from app.services.order_events import record_order_status_event  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--order", help="First characters of an order id")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        statement = (
            select(Order)
            .options(selectinload(Order.items), selectinload(Order.restaurant_location))
            .order_by(Order.created_at.desc())
        )
        if args.order:
            statement = statement.where(Order.id.cast(sa.String).like(f"{args.order}%"))
        else:
            statement = statement.where(Order.status == OrderStatus.PAYMENT_PENDING)

        order = db.scalars(statement.limit(1)).first()
        if order is None:
            print(
                "No matching order. Place one first, or check the id.",
                file=sys.stderr,
            )
            return 1

        if order.status != OrderStatus.PAYMENT_PENDING:
            print(
                f"Order {str(order.id)[:8]} is already {order.status.value}; "
                "nothing to advance.",
                file=sys.stderr,
            )
            return 1

        branch = order.restaurant_location.branch_name if order.restaurant_location else "?"
        order.payment_status = PaymentStatus.PAID
        record_order_status_event(
            db,
            order=order,
            from_status=OrderStatus.PAYMENT_PENDING,
            to_status=OrderStatus.PLACED,
            actor=OrderEventActor.PAYMENT_PROVIDER,
            note="payment confirmed (mark_order_paid)",
        )
        order.status = OrderStatus.PLACED
        db.add(order)
        # The print jobs are written inside this transaction, so they become
        # visible exactly when it commits. Nothing to flush separately.
        db.commit()

        print(f"Order {str(order.id)[:8]} is now PLACED  ({branch})")
        if not get_settings().enable_auto_print:
            print(
                "\nENABLE_AUTO_PRINT is off, so the tickets were queued and will not be "
                "served to an agent.\nSet ENABLE_AUTO_PRINT=true in backend/.env and "
                "restart the API to print for real."
            )
        else:
            print("The agent should print within its poll interval (about 15 seconds).")
        print("\nWhat was queued:")
        from app.models.print_agent import PrintJob

        for job in db.scalars(
            select(PrintJob).where(PrintJob.order_id == order.id).order_by(PrintJob.created_at)
        ).all():
            print(f"  {str(job.id)[:8]}  {job.kind.value:15} {job.status.value}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
