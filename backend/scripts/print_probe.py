"""Send a real ticket to a real printer, before any of the agent exists.

The point is to answer the hardware questions early, because they are the ones
that cannot be answered by reading code:

* does the printer accept a raw socket on 9100, or does it need the spooler?
* is it 58mm or 80mm — 32 or 48 columns?
* does it cut, or just feed?
* does it have a rupee sign? (Many do not. See `--charset`.)

Everything it prints goes through the same `render.py` and `layout.py` the
agent will use, so a ticket that looks right here is the ticket that will
arrive when an order lands. It is a probe, not part of the product: no
database, no queue, no job rows.

    # safe default: nothing leaves the machine
    ./.venv/Scripts/python.exe scripts/print_probe.py

    # a network printer
    ./.venv/Scripts/python.exe scripts/print_probe.py --host 192.168.1.50 --width 80mm

    # a USB printer through the Windows spooler
    ./.venv/Scripts/python.exe scripts/print_probe.py --windows "EPSON TM-T82 Receipt"

    # every ticket type, so one run proves the lot
    ./.venv/Scripts/python.exe scripts/print_probe.py --host 192.168.1.50 --kind all
"""

from __future__ import annotations

import argparse
import socket
import subprocess
import sys
import tempfile
import unicodedata
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
from app.services.print.document import Document, Line  # noqa: E402
from app.services.print.layout import lay_out  # noqa: E402
from app.services.print.render import (  # noqa: E402
    render_customer_bill,
    render_kitchen_docket,
    render_test_page,
    render_void_slip,
)

# --- ESC/POS, the little of it a receipt needs ------------------------------
#
# Deliberately the smallest usable subset. Every one of these is in the
# original Epson command set and has been honoured by every clone for twenty
# years; anything fancier is where printer compatibility goes to die.

ESC = b"\x1b"
GS = b"\x1d"

INIT = ESC + b"@"  # reset: clears any state a previous job left behind
ALIGN = {"left": ESC + b"a\x00", "center": ESC + b"a\x01", "right": ESC + b"a\x02"}
BOLD_ON, BOLD_OFF = ESC + b"E\x01", ESC + b"E\x00"
# GS ! n, where the high nibble is width and the low nibble height.
SIZE_NORMAL, SIZE_DOUBLE = GS + b"!\x00", GS + b"!\x11"
FEED = b"\n"
# GS V 66 n: feed then partial cut. Printers with no cutter ignore it, which
# is why it is safe to send unconditionally.
CUT = GS + b"V\x42\x03"

#: Characters a thermal printer's default code page does not have.
#:
#: The rupee sign is the one that matters here and it is not cosmetic: CP437
#: and CP850, which is what most TM-series printers boot into, predate it. An
#: un-transliterated bill prints the total as a box or drops the symbol, and
#: "462.50" with no currency on a bill is worse than "Rs.462.50".
#:
#: Printers that DO have it need a code-page command and a different mapping,
#: which is why this is a flag rather than a constant: `--charset utf8` sends
#: the bytes through untouched for a printer that has been configured for it.
TRANSLITERATE = {
    "₹": "Rs.",  # rupee
    "’": "'",
    "‘": "'",
    "“": '"',
    "”": '"',
    "–": "-",
    "—": "-",
    "…": "...",
}


def to_ascii(value: str) -> str:
    for source, target in TRANSLITERATE.items():
        value = value.replace(source, target)
    # Anything still outside ASCII is stripped to its closest form rather than
    # sent as bytes the printer will render as noise.
    return unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")


def escpos_bytes(document: Document, *, charset: str) -> bytes:
    """One document as printer bytes.

    Line breaks come from `layout.py` rather than being left to the printer,
    for the reason that module documents: the printer wraps mid-word wherever
    it lands, and a delivery address is the wrong thing to let it guess at.
    So each already-wrapped row is emitted with its own styling.

    This is the reference the agent's `escpos.ts` is built against.
    """

    out = bytearray(INIT)

    for line in document.lines:
        if line.t == "cut":
            out += FEED * 3 + CUT
            continue

        rendered = lay_out(Document(width=document.width, lines=[line]))
        for row in rendered.split("\n"):
            text = row if charset == "utf8" else to_ascii(row)
            # Alignment is already baked into the padding by `layout.py`, so
            # the row is sent left-aligned and the spaces do the work. That
            # keeps this and the Windows spooler path producing the same
            # ticket, which they would not if one centred and the other
            # padded.
            out += ALIGN["left"]
            out += SIZE_DOUBLE if line.size == "double" else SIZE_NORMAL
            if line.bold:
                out += BOLD_ON
            out += text.encode("cp437", "replace") if charset != "utf8" else text.encode("utf-8")
            if line.bold:
                out += BOLD_OFF
            out += SIZE_NORMAL
            out += FEED

    return bytes(out)


def send_tcp(payload: bytes, host: str, port: int, timeout: float) -> None:
    """Raw bytes to the printer's own address.

    No handshake and no acknowledgement: 9100 is a pipe to the print head, so
    a successful `sendall` means the bytes left this machine, not that paper
    moved. That asymmetry is why the agent reports a job as printed on a
    clean write and the owner still has eyes on the printer.
    """

    with socket.create_connection((host, port), timeout=timeout) as connection:
        connection.sendall(payload)


def send_windows(payload: bytes, printer: str) -> None:
    """Through the Windows spooler, for a USB printer.

    Text rather than ESC/POS, because a spooler queue created from a Windows
    driver expects the driver's own language and will render raw escape codes
    as literal gibberish. A queue installed as "Generic / Text Only" takes the
    text and the printer applies its own defaults — no bold, no double height,
    but legible, which is the whole requirement for this transport.

    Known limitation, and the reason TCP is built first: a Windows SERVICE
    runs in Session 0 and cannot see per-user installed printers, so an agent
    using this transport has to run as a logged-in user's startup task.
    """

    with tempfile.NamedTemporaryFile(
        "w", suffix=".txt", delete=False, encoding="utf-8"
    ) as handle:
        handle.write(payload.decode("utf-8", "replace"))
        path = handle.name
    result = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            f"Get-Content -LiteralPath '{path}' | Out-Printer -Name '{printer}'",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"The Windows spooler refused the job: {result.stderr.strip() or 'no detail'}"
        )


def _sample_order():
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
        delivery_address=(
            "A-31 Rangdarshan Society, Near Dhanmora, Katargam, Surat, Gujarat, 395004"
        ),
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
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", help="Printer IP. Omit to print nothing and only preview.")
    parser.add_argument("--port", type=int, default=9100)
    parser.add_argument("--windows", help="Windows printer queue name, instead of --host")
    parser.add_argument(
        "--width",
        default="80mm",
        choices=("58mm", "80mm", "32", "42", "48"),
        help="Paper width. 58mm is 32 columns, 80mm is 48.",
    )
    parser.add_argument(
        "--kind", default="test", choices=("test", "docket", "bill", "void", "all")
    )
    parser.add_argument(
        "--charset",
        default="cp437",
        choices=("cp437", "utf8"),
        help="cp437 transliterates the rupee sign to 'Rs.'; utf8 sends it through",
    )
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument("--tz", default="Asia/Kolkata")
    args = parser.parse_args()

    width = {"58mm": 32, "80mm": 48}.get(args.width, None) or int(args.width)
    tz = ZoneInfo(args.tz)
    order = _sample_order()
    common = dict(restaurant_name="Bhagwati Bakery", branch_name="Main Branch", width=width, tz=tz)

    chosen = ("test", "docket", "bill", "void") if args.kind == "all" else (args.kind,)
    documents = []
    for kind in chosen:
        if kind == "test":
            # No branch: a test page proves a PRINTER works, so naming a
            # branch on it would be the only untrue thing on the ticket.
            documents.append(
                (
                    "TEST PAGE",
                    render_test_page(
                        restaurant_name="Bhagwati Bakery",
                        printer_name=args.windows or args.host or "preview",
                        width=width,
                        tz=tz,
                    ),
                )
            )
        elif kind == "docket":
            documents.append(("KITCHEN DOCKET", render_kitchen_docket(order, **common)))
        elif kind == "bill":
            documents.append(("CUSTOMER BILL", render_customer_bill(order, **common)))
        else:
            documents.append(("VOID SLIP", render_void_slip(order, reason="Payment expired", **common)))

    for title, document in documents:
        print(f"\n{' ' + title + ' ':~^{width}}")
        print(lay_out(document))

    if not args.host and not args.windows:
        print(
            f"\nPreviewed {len(documents)} ticket(s) at {width} columns. "
            "Nothing was sent anywhere.\n"
            "Add --host <printer-ip> or --windows '<queue name>' to print for real."
        )
        return 0

    for title, document in documents:
        payload = escpos_bytes(document, charset=args.charset)
        try:
            if args.windows:
                send_windows(
                    lay_out(document).encode("utf-8"), args.windows
                )
                where = f"spooler queue {args.windows!r}"
            else:
                send_tcp(payload, args.host, args.port, args.timeout)
                where = f"{args.host}:{args.port}"
            print(f"sent {title} ({len(payload)} bytes) to {where}")
        except OSError as error:
            # The sentence an owner would need, not the exception's. This is
            # the wording the agent's `last_error` should carry too.
            print(
                f"\nCould not reach the printer at {args.host}:{args.port} - {error}\n"
                "  * is it switched on, with paper?\n"
                "  * is it on the same network as this PC?\n"
                f"  * does `ping {args.host}` answer?\n"
                "  * some printers use 515 (LPR) rather than 9100 - try --port 515",
                file=sys.stderr,
            )
            return 1
        except RuntimeError as error:
            print(f"\n{error}", file=sys.stderr)
            return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
