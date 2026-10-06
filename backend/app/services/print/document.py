"""The ticket, as a document rather than as printer bytes.

A print job stores one of these, and the agent turns it into whatever its own
printer speaks. The split is the point:

* **The server decides what the ticket SAYS.** Half-and-half portions, chosen
  options, currency, the branch's timezone, whether this is a delivery or a
  collection — all of it is business fact, and all of it already exists here.
  Re-deriving any of it in the agent would be a second implementation of rules
  that `CLAUDE.md` says already live in three places that must agree, "because
  a disagreement means the customer sees one price and is charged another". A
  docket that gets half-and-half wrong is a kitchen making the wrong pizza.

* **The agent decides what the ticket IS.** ESC/POS escape codes, code pages,
  cut commands, how a Windows spooler wants its text. None of that belongs in
  a Python service that has never seen the printer.

One more reason for a document rather than a string: the same one drives a
58mm thermal printer at 32 columns, an 80mm at 48, and the Windows spooler as
plain text, without the server knowing which.

**Times are rendered here, in the branch's timezone.** An agent formatting
`created_at` with the PC's clock prints wrong times the moment that clock
drifts, and nobody notices for weeks.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Literal

#: Column counts this renderer lays out for, by paper width.
#:
#: 32 is 58mm and 48 is 80mm, which is what the `paper_width_is_known` CHECK on
#: `printers` allows. 42 is the other common 80mm font. Anything else wraps
#: every line and turns a docket into mush, which is why the column is
#: constrained rather than free.
PAPER_WIDTHS = (32, 42, 48)

Align = Literal["left", "center", "right"]
Size = Literal["normal", "double"]


@dataclass(slots=True)
class Line:
    """One instruction in a ticket.

    Deliberately a small, closed vocabulary. Every kind here maps onto
    something every thermal printer and every spooler can do; nothing here
    needs a font, an image or a measurement. A richer document would print
    beautifully on the printer it was developed against and badly on the next
    one.
    """

    t: str
    v: str | None = None
    #: `kv` only: the label on the left, value flush right on the same line.
    k: str | None = None
    #: `item` only.
    qty: int | None = None
    mods: list[str] = field(default_factory=list)
    align: Align = "left"
    bold: bool = False
    size: Size = "normal"

    def to_dict(self) -> dict[str, Any]:
        """Only what is set, so a stored document stays readable.

        The JSONB column is read by a human about as often as by the agent —
        when a ticket came out wrong, this is the evidence — so a line that is
        just `{"t": "rule"}` should not arrive as eleven nulls.
        """

        out: dict[str, Any] = {"t": self.t}
        if self.v is not None:
            out["v"] = self.v
        if self.k is not None:
            out["k"] = self.k
        if self.qty is not None:
            out["qty"] = self.qty
        if self.mods:
            out["mods"] = list(self.mods)
        if self.align != "left":
            out["align"] = self.align
        if self.bold:
            out["bold"] = True
        if self.size != "normal":
            out["size"] = self.size
        return out


def text(
    value: str, *, align: Align = "left", bold: bool = False, size: Size = "normal"
) -> Line:
    return Line(t="text", v=value, align=align, bold=bold, size=size)


def kv(label: str, value: str, *, bold: bool = False) -> Line:
    """A label and a value on one line, value flush right.

    The agent does the padding, because only it knows the column count. The
    server choosing the spacing would mean a document that is correct at 48
    columns and broken at 32.
    """

    return Line(t="kv", k=label, v=value, bold=bold)


def item(quantity: int, name: str, *, mods: list[str] | None = None) -> Line:
    """One line of food, with whatever was chosen on it underneath."""

    return Line(t="item", qty=quantity, v=name, mods=list(mods or []))


def rule(char: str = "-") -> Line:
    """A full-width divider, in whatever character.

    `char` exists for the void slip. "*** CANCELLED ***" at double size needs
    17 of the 16 columns 58mm paper gives a double-width line, so it wrapped
    mid-banner on exactly the ticket that has to be read correctly from across
    a room. A row of asterisks drawn to the paper's width cannot wrap, and the
    word itself then fits at any size.
    """

    return Line(t="rule", v=char if char != "-" else None)


def blank() -> Line:
    return Line(t="blank")


def cut() -> Line:
    """End of ticket. The agent cuts, or feeds if it has no cutter."""

    return Line(t="cut")


@dataclass(slots=True)
class Document:
    """A whole ticket, ready to be stored on a job.

    `width` is baked in at render time rather than left to the agent, because
    the server lays out money columns and truncates long dish names to fit —
    both of which need to know how wide the paper is. It comes from the printer
    row, which the enqueue already has in hand.
    """

    width: int
    lines: list[Line]
    #: Carried for the agent's logs and for a human reading the stored row.
    #: Never used to make a decision; the job's own `kind` column is the truth.
    kind: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "width": self.width,
            **({"kind": self.kind} if self.kind else {}),
            "lines": [line.to_dict() for line in self.lines],
        }


#: Currency symbols a thermal printer cannot render, and what to print instead.
#:
#: CP437 and CP850 - what most TM-series printers boot into - predate the rupee
#: sign, so it arrives as a box or is dropped, and a total with no currency on
#: it is worse than "Rs.120.25".
#:
#: The substitution happens HERE, not in the agent, and that is the whole
#: point. It was in the agent first, after layout had already padded the line
#: for a one-character symbol: `Subtotal ... Rs.100.00` came out 50 characters
#: wide on 48-column paper and the printer wrapped the money column. The
#: currency symbol is part of what a ticket SAYS, so it is decided where
#: everything else a ticket says is decided, before anything counts columns.
PRINTER_SAFE_SYMBOLS = {
    "₹": "Rs.",  # rupee
    "€": "EUR ",  # euro
    "£": "GBP ",  # pound - cp437 has it, many clones do not
    "¥": "JPY ",  # yen
    "₦": "NGN ",  # naira
    "₱": "PHP ",  # peso
}


def printer_safe_symbol(symbol: str) -> str:
    """What to print where a tenant's currency symbol will not render.

    Anything still outside ASCII after the table above falls back to the
    symbol stripped of what a printer cannot draw, and then to nothing - a
    bare number beats a row of boxes.
    """

    if symbol in PRINTER_SAFE_SYMBOLS:
        return PRINTER_SAFE_SYMBOLS[symbol]
    if symbol.isascii():
        return symbol
    return symbol.encode("ascii", "ignore").decode("ascii")


def money_str(amount: Decimal | float | int | str, symbol: str) -> str:
    """Two decimal places, with a symbol this printer can actually draw.

    Formatted here rather than in the agent for the same reason as the times:
    a tenant charging in dollars and one charging in rupees are both correct at
    once, and the agent has no idea which restaurant it is printing for.
    """

    value = Decimal(str(amount)).quantize(Decimal("0.01"))
    return f"{printer_safe_symbol(symbol)}{value}"
