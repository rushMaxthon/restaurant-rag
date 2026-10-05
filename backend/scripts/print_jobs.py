"""Look at the print queue, and drain it by hand.

A stand-in for the agent while the agent is being written, and a diagnostic
afterwards. Three things:

    # what is waiting
    ./.venv/Scripts/python.exe scripts/print_jobs.py

    # what one ticket actually says
    ./.venv/Scripts/python.exe scripts/print_jobs.py --show <job-id-prefix>

    # pair this machine as a printer, once
    ./.venv/Scripts/python.exe scripts/print_jobs.py --pair 192.168.29.39 --width 48

    # print everything queued, and keep printing as orders arrive
    ./.venv/Scripts/python.exe scripts/print_jobs.py --drain --watch

`--drain` does what the agent will do: claim, send, acknowledge. It talks to
the database directly rather than over the agent API, because the API does not
exist yet — but the queue semantics it exercises are the real ones, including
the lease and the idempotency index.
"""

from __future__ import annotations

import argparse
import socket
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import selectinload  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.config.database import SessionLocal  # noqa: E402
from app.models.enums import (  # noqa: E402
    PrinterTransport,
    PrintJobKind,
    PrintJobStatus,
)
from app.models.print_agent import PrintAgent, Printer, PrintJob  # noqa: E402
from app.models.restaurant_location import RestaurantLocation  # noqa: E402
from app.services.print.document import Document, Line  # noqa: E402
from app.services.print.layout import lay_out  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from print_probe import escpos_bytes  # noqa: E402


def document_from(payload: dict) -> Document:
    """A stored job's JSONB back into a Document.

    The agent does this too. Kept simple and forgiving: a line whose kind this
    build does not recognise becomes a plain text line rather than an error,
    because a ticket printing imperfectly beats a ticket not printing.
    """

    return Document(
        width=int(payload.get("width") or 48),
        kind=payload.get("kind"),
        lines=[
            Line(
                t=str(entry.get("t") or "text"),
                v=entry.get("v"),
                k=entry.get("k"),
                qty=entry.get("qty"),
                mods=list(entry.get("mods") or []),
                align=entry.get("align") or "left",
                bold=bool(entry.get("bold")),
                size=entry.get("size") or "normal",
            )
            for entry in payload.get("lines") or []
        ],
    )


def cmd_list(db) -> int:
    jobs = db.scalars(
        select(PrintJob)
        .options(selectinload(PrintJob.printer).selectinload(Printer.agent))
        .order_by(PrintJob.created_at.desc())
        .limit(40)
    ).all()
    if not jobs:
        print("No print jobs yet.")
        print("\nIf you expected some:")
        print("  * is a printer paired for the order's branch?  --pair <ip>")
        print("  * was the order PLACED, not PAYMENT_PENDING?  an unpaid order prints nothing")
        return 0

    settings = get_settings()
    print(f"{'id':10} {'kind':15} {'status':9} {'try':4} {'printer':18} created")
    print("-" * 78)
    for job in jobs:
        print(
            f"{str(job.id)[:8]:10} {job.kind.value:15} {job.status.value:9} "
            f"{job.attempts:<4} {(job.printer.name if job.printer else '?')[:18]:18} "
            f"{job.created_at:%d %b %H:%M}"
        )
        if job.last_error:
            print(f"           ! {job.last_error[:70]}")
    if not settings.enable_auto_print:
        print(
            "\nENABLE_AUTO_PRINT is off, so these are a dry run: the rows are written and "
            "no agent is served them.\nSet ENABLE_AUTO_PRINT=true in backend/.env and "
            "restart the API to print for real."
        )
    return 0


def cmd_show(db, prefix: str) -> int:
    job = db.scalars(
        select(PrintJob).where(PrintJob.id.cast(__import__("sqlalchemy").String).like(f"{prefix}%"))
    ).first()
    if job is None:
        print(f"No job starts with {prefix!r}", file=sys.stderr)
        return 1
    document = document_from(job.document)
    print(f"{job.kind.value}  {job.status.value}  {job.created_at:%d %b %H:%M}")
    print(f"{' ' + (job.printer.name if job.printer else '?') + ' ':~^{document.width}}")
    print(lay_out(document))
    return 0


def cmd_pair(
    db,
    host: str,
    width: int,
    port: int,
    name: str,
    branch: str | None,
    api_base: str,
    host_header: str,
) -> int:
    """Pair this machine as a printer for the first branch that has none.

    A shortcut for testing only. The real pairing is a six-digit code typed
    into the agent's installer, which does not exist yet; this writes the rows
    that flow would write so the queue can be exercised today.
    """

    # Resolved through the storefront's own host, not by branch name.
    #
    # Two mistakes here cost a debugging round each. Pairing to the first
    # location by `created_at` chose a restaurant the storefront does not
    # serve, so an order queued nothing. Then matching `--branch "Main Branch"`
    # matched the wrong restaurant's branch, because more than one restaurant
    # on this platform has a branch by that name - the order went to
    # 811b2f34 and the printer was paired to 695ad941, both called "Main
    # Branch".
    #
    # So the host decides, exactly as it does for every other request: the
    # backend resolves which restaurant a request belongs to from the address
    # it arrived on, and that is the restaurant being tested by definition.
    import json
    import urllib.request

    try:
        request = urllib.request.Request(f"{api_base}/app-config")
        request.add_header("X-Forwarded-Host", host_header)
        with urllib.request.urlopen(request, timeout=10) as reply:
            restaurant_id = json.loads(reply.read())["restaurant_id"]
    except Exception as error:  # noqa: BLE001 - a helper, and the hint matters more
        print(
            f"Could not ask {api_base}/app-config which restaurant {host_header!r} "
            f"serves ({error}). Is the backend running?",
            file=sys.stderr,
        )
        return 1

    candidates = db.scalars(
        select(RestaurantLocation)
        .where(RestaurantLocation.restaurant_id == restaurant_id)
        .order_by(RestaurantLocation.created_at)
    ).all()
    if branch:
        candidates = [row for row in candidates if branch.lower() in (row.branch_name or "").lower()]
    location = candidates[0] if candidates else None
    if location is not None and len(candidates) > 1:
        print(f"{len(candidates)} branches match; using {location.branch_name!r}. Others:")
        for row in candidates[1:]:
            print(f"  --branch {row.branch_name!r}")
    if location is None:
        print("No restaurant locations exist. Run seed.py first.", file=sys.stderr)
        return 1

    agent = db.scalars(
        select(PrintAgent).where(PrintAgent.restaurant_location_id == location.id)
    ).first()
    if agent is None:
        import hashlib

        raw = uuid.uuid4().hex
        agent = PrintAgent(
            restaurant_id=location.restaurant_id,
            restaurant_location_id=location.id,
            name=f"Dev agent ({socket.gethostname()})",
            token_hash=hashlib.sha256(raw.encode()).hexdigest(),
            hostname=socket.gethostname(),
            agent_version="dev",
        )
        db.add(agent)
        db.flush()
        print(f"Paired agent {str(agent.id)[:8]} to {location.branch_name}")

    printer = db.scalars(
        select(Printer).where(Printer.print_agent_id == agent.id, Printer.name == name)
    ).first()
    if printer is not None:
        printer.host, printer.port, printer.paper_width_chars = host, port, width
        print(f"Updated printer {name!r} -> {host}:{port} at {width} columns")
    else:
        printer = Printer(
            print_agent_id=agent.id,
            name=name,
            transport=PrinterTransport.TCP,
            host=host,
            port=port,
            paper_width_chars=width,
            # Everything, so one printer proves the whole feature. A real
            # kitchen printer would take dockets and voids only.
            docket_kinds=[kind.value for kind in PrintJobKind],
        )
        db.add(printer)
        print(f"Added printer {name!r} -> {host}:{port} at {width} columns")
    db.commit()
    print(f"\nBranch: {location.branch_name}  ({location.id})")
    print("Now place an order, then run with --drain.")
    return 0


def cmd_drain(db, *, watch: bool, interval: float) -> int:
    """Claim, print and acknowledge — what the agent will do.

    Goes through the real `claim_jobs` and `ack_job`, so the lease and the
    scoping are exercised rather than bypassed. The one thing it does not do
    is keep a local ledger of printed ids; the agent will, because it is the
    half of exactly-once that the server cannot provide.
    """

    from app.services.print.queue import ack_job, claim_jobs

    settings = get_settings()
    if not settings.enable_auto_print:
        print(
            "ENABLE_AUTO_PRINT is off, so nothing will be served.\n"
            "Set ENABLE_AUTO_PRINT=true in backend/.env and restart nothing — "
            "this script reads it directly.",
            file=sys.stderr,
        )
        return 1

    agents = db.scalars(select(PrintAgent).where(PrintAgent.is_enabled.is_(True))).all()
    if not agents:
        print("No agents paired. Run with --pair <printer-ip> first.", file=sys.stderr)
        return 1

    while True:
        printed = 0
        for agent in agents:
            for job in claim_jobs(db, agent):
                document = document_from(job.document)
                printer = job.printer
                try:
                    payload = escpos_bytes(document, charset="cp437")
                    with socket.create_connection(
                        (printer.host, printer.port or 9100), timeout=5
                    ) as connection:
                        connection.sendall(payload)
                    ack_job(db, agent, job.id, printed=True)
                    print(
                        f"{datetime.now(UTC):%H:%M:%S}  printed {job.kind.value} "
                        f"{str(job.id)[:8]} -> {printer.host}:{printer.port}"
                    )
                    printed += 1
                except OSError as error:
                    # The sentence the owner reads on the admin screen.
                    ack_job(
                        db,
                        agent,
                        job.id,
                        printed=False,
                        error=(
                            f"The printer at {printer.host}:{printer.port} did not answer "
                            f"({error}). Check it is switched on, has paper, and is on the "
                            f"same network as the agent."
                        ),
                    )
                    print(f"  failed {str(job.id)[:8]}: {error}", file=sys.stderr)
        if not watch:
            if printed == 0:
                print("Nothing queued.")
            return 0
        time.sleep(interval)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--show", metavar="JOB_ID_PREFIX")
    parser.add_argument("--pair", metavar="PRINTER_IP")
    parser.add_argument("--port", type=int, default=9100)
    parser.add_argument("--width", type=int, default=48, choices=(32, 42, 48))
    parser.add_argument("--printer-name", default="Kitchen")
    parser.add_argument("--branch", help="Narrow to a branch of that restaurant by name")
    parser.add_argument("--api", default="http://127.0.0.1:8000/api")
    parser.add_argument(
        "--storefront-host",
        default="localhost",
        help="The host whose restaurant to pair to - the same value the storefront is served on",
    )
    parser.add_argument("--drain", action="store_true")
    parser.add_argument("--watch", action="store_true", help="With --drain: keep polling")
    parser.add_argument("--interval", type=float, default=3.0)
    args = parser.parse_args()

    db = SessionLocal()
    try:
        if args.show:
            return cmd_show(db, args.show)
        if args.pair:
            return cmd_pair(
                db,
                args.pair,
                args.width,
                args.port,
                args.printer_name,
                args.branch,
                args.api,
                args.storefront_host,
            )
        if args.drain:
            return cmd_drain(db, watch=args.watch, interval=args.interval)
        return cmd_list(db)
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
