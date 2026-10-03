"""Print a ticket to the terminal, laid out exactly as the paper will be.

`dryrun_whatsapp.py` established this idiom here as "the fastest way to see
what a customer actually gets". Same argument: a renderer with thirty passing
tests can still produce a docket a cook cannot read, and the only way to know
is to look at one.

This is also the layout reference for the agent. The column arithmetic below —
how a `kv` pads, how an `item` indents its modifiers, how `double` is
simulated — is what `agent/src/render/escpos.ts` has to reproduce in ESC/POS,
so the two can be compared side by side rather than guessed at.

    # a made-up order, no database needed
    ./.venv/Scripts/python.exe scripts/dryrun_print.py

    # a real one, at 58mm
    ./.venv/Scripts/python.exe scripts/dryrun_print.py --order 6373b312 --width 32
"""

from __future__ import annotations

import argparse
import sys
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models.enums import (  # noqa: E402
    MenuItemPortion,
    OrderFulfillmentType,
    OrderScheduleType,
    PaymentMethod,
    PaymentStatus,
)
from app.services.print.layout import lay_out  # noqa: E402
from app.services.print.render import (  # noqa: E402
    render_customer_bill,
    render_kitchen_docket,
    render_test_page,
    render_void_slip,
)


def _sample_order():
    """An order with the parts that break tickets.

    Half-and-half on one line, a size on another, a countable extra, an
    allergy note, and a delivery address long enough to wrap. A sample that
    prints cleanly tells you nothing.
    """

    now = datetime(2026, 10, 3, 19, 30, tzinfo=timezone.utc)

    def opt(name, portion=MenuItemPortion.WHOLE, quantity=1, countable=False):
        return {
            "option_name": name,
            "portion": portion.value,
            "quantity": quantity,
            "is_countable": countable,
            "group_title": "Toppings",
        }

    return SimpleNamespace(
        id=uuid.UUID("6373b312-6d34-4c3f-8742-0b27b6336061"),
        created_at=now,
        scheduled_at=now,
        schedule_type=OrderScheduleType.ASAP,
        fulfillment_type=OrderFulfillmentType.DELIVERY,
        status="PLACED",
        payment_method=PaymentMethod.COD,
        payment_status=PaymentStatus.PENDING,
        currency="INR",
        subtotal=Decimal("450.00"),
        discount_amount=Decimal("50.00"),
        tax_amount=Decimal("22.50"),
        delivery_fee=Decimal("40.00"),
        total_amount=Decimal("462.50"),
        special_instructions="NO PEANUTS - severe allergy. Ring the bell twice.",
        delivery_address="A-31 Rangdarshan Society, Near Dhanmora, Katargam, Surat, Gujarat, 395004",
        contact_name="Asha Patel",
        contact_phone="9825322860",
        items=[
            SimpleNamespace(
                item_name_snapshot="Build Your Own Pizza",
                size_name_snapshot="Large",
                quantity=1,
                selected_options_snapshot=[
                    opt("Thin crust"),
                    opt("Olives", MenuItemPortion.LEFT),
                    opt("Jalapeno", MenuItemPortion.LEFT),
                    opt("Paneer", MenuItemPortion.RIGHT, quantity=2, countable=True),
                    opt("Mushroom", MenuItemPortion.RIGHT),
                ],
            ),
            SimpleNamespace(
                item_name_snapshot="Masala Chai",
                size_name_snapshot=None,
                quantity=2,
                selected_options_snapshot=[],
            ),
        ],
    )


def main() -> int:
    # The Windows console is cp1252, which has no rupee sign, so printing a
    # bill crashed with UnicodeEncodeError. The ticket is not wrong; the
    # terminal is narrower than the world.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--order", help="First 8 characters of a real order id")
    parser.add_argument("--width", type=int, default=48, choices=(32, 42, 48))
    parser.add_argument("--tz", default="Asia/Kolkata")
    args = parser.parse_args()

    tz = ZoneInfo(args.tz)
    name, branch = "Bhagwati Bakery", "Main Branch"

    if args.order:
        from sqlalchemy.orm import selectinload

        from app.config.database import SessionLocal
        from app.models.order import Order

        db = SessionLocal()
        try:
            order = (
                db.query(Order)
                .options(selectinload(Order.items))
                .filter(Order.id.cast(__import__("sqlalchemy").String).like(f"{args.order}%"))
                .first()
            )
            if order is None:
                print(f"No order starts with {args.order!r}", file=sys.stderr)
                return 1
            documents = [
                ("KITCHEN DOCKET", render_kitchen_docket(order, restaurant_name=name, branch_name=branch, width=args.width, tz=tz)),
                ("CUSTOMER BILL", render_customer_bill(order, restaurant_name=name, branch_name=branch, width=args.width, tz=tz)),
                ("VOID SLIP", render_void_slip(order, restaurant_name=name, branch_name=branch, width=args.width, tz=tz, reason="Payment expired")),
            ]
        finally:
            db.close()
    else:
        order = _sample_order()
        documents = [
            ("KITCHEN DOCKET", render_kitchen_docket(order, restaurant_name=name, branch_name=branch, width=args.width, tz=tz)),
            ("CUSTOMER BILL", render_customer_bill(order, restaurant_name=name, branch_name=branch, width=args.width, tz=tz)),
            ("VOID SLIP", render_void_slip(order, restaurant_name=name, branch_name=branch, width=args.width, tz=tz, reason="Payment expired")),
            ("TEST PAGE", render_test_page(restaurant_name=name, printer_name="Kitchen", width=args.width, tz=tz)),
        ]

    for title, document in documents:
        print()
        print(f"{' ' + title + ' ':~^{args.width}}")
        print(lay_out(document))
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
