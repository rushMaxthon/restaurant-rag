"""A document as characters on paper of a known width.

This exists because the first dry run of a real-looking order printed this:

    NOTE
    NO PEANUTS - severe allergy. Ring the bell twice
    ...
    A-31 Rangdarshan Society, Near Dhanmora, Katarga

The note lost its last character and the address lost "Surat, Gujarat,
395004" — the part a rider needs. Both because the layout truncated at the
paper's width instead of wrapping. Thirty-two renderer tests passed through
it, because they assert what the DOCUMENT says and the document was correct;
nothing asserted what the paper shows.

So the rule has a home and tests of its own: **a ticket never silently drops
text.** It wraps. The only thing allowed to be shortened is a `kv` label, and
never its value.

Two readers depend on this:

* `scripts/dryrun_print.py`, so a human can see a docket before a printer does;
* the WINDOWS transport, where the spooler wants plain text and this *is* the
  output.

The ESC/POS transport in the agent reimplements it against the printer's own
double-width and wrap behaviour, and `agent/src/render/escpos.test.ts` compares
its line breaks to this module's for the same documents — so the two cannot
drift into disagreeing about where a long address breaks.
"""

from __future__ import annotations

from app.services.print.document import Document, Line


def _wrap(value: str, width: int) -> list[str]:
    """Break a string to fit, on word boundaries where it can.

    A word longer than the paper is split rather than left to overflow — a
    45-character street name on 32-column paper has to break somewhere, and
    breaking it is better than losing its tail.

    Returns at least one line, so an empty string still occupies the row the
    document asked for rather than collapsing it.
    """

    if width <= 0:
        return [value]

    out: list[str] = []
    for paragraph in value.split("\n"):
        words = paragraph.split()
        if not words:
            out.append("")
            continue
        current = ""
        for word in words:
            while len(word) > width:
                # Longer than the paper on its own. Flush what we have, then
                # take a full line of it and carry on with the rest.
                if current:
                    out.append(current)
                    current = ""
                out.append(word[:width])
                word = word[width:]
            if not current:
                current = word
            elif len(current) + 1 + len(word) <= width:
                current = f"{current} {word}"
            else:
                out.append(current)
                current = word
        if current:
            out.append(current)
    return out or [""]


def _effective_width(line: Line, width: int) -> int:
    """How many characters of THIS line fit on the paper.

    Half, for a double-size line. Not a detail: ESC/POS double height is also
    double WIDTH, so "*** CANCELLED ***" at 48 columns occupies 34 of a
    24-column budget and the printer wraps it itself — mid-word, wherever it
    lands. Wrapping it here means we choose the break.
    """

    return width // 2 if line.size == "double" else width


def lay_out(document: Document) -> str:
    """The whole ticket, as the paper will show it."""

    width = document.width
    out: list[str] = []

    for line in document.lines:
        if line.t == "rule":
            out.append((line.v or "-") * width)
        elif line.t == "blank":
            out.append("")
        elif line.t == "cut":
            out.append("")
        elif line.t == "kv":
            out.extend(_lay_out_kv(line, width))
        elif line.t == "item":
            out.extend(_lay_out_item(line, width))
        else:
            out.extend(_lay_out_text(line, width))

    return "\n".join(out)


def _lay_out_kv(line: Line, width: int) -> list[str]:
    """Label left, value flush right, on one row.

    The value is never shortened and never wrapped onto a second row: these
    are phone numbers, order codes and totals, and half of any of them is
    worse than useless. If the pair cannot fit, the LABEL gives way — "Phone"
    cut to "Pho" is still obvious, a phone number missing two digits is a
    rider who cannot call.
    """

    label = line.k or ""
    value = line.v or ""
    gap = width - len(label) - len(value)
    if gap < 1:
        label = label[: max(0, width - len(value) - 1)]
        gap = max(1, width - len(label) - len(value))
    return [f"{label}{' ' * gap}{value}"]


def _lay_out_item(line: Line, width: int) -> list[str]:
    """A quantity and a dish, with what was chosen indented beneath.

    The dish name wraps with a hanging indent so a long name stays visibly one
    item rather than looking like two. Modifiers are indented further again,
    because a cook scanning the left edge is counting dishes.
    """

    head = f"{line.qty} x {line.v or ''}"
    out = _wrap(head, width)
    # Continuation of a wrapped dish name, aligned under the name rather than
    # the quantity.
    out = [out[0]] + [f"    {rest}"[:width] for rest in out[1:]]

    for mod in line.mods:
        wrapped = _wrap(mod, max(1, width - 4))
        out.append(f"    {wrapped[0]}")
        out.extend(f"      {rest}" for rest in wrapped[1:])
    return out


def _lay_out_text(line: Line, width: int) -> list[str]:
    effective = _effective_width(line, width)
    rows = _wrap(line.v or "", effective)
    if line.align == "center":
        return [row.center(width) for row in rows]
    if line.align == "right":
        return [row.rjust(width) for row in rows]
    return rows
