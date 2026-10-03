"""The print queue: deciding a ticket exists, handing it out, and closing it.

Three operations and nothing else. Everything difficult about auto-printing
lives in the gaps between them.

**Why a queue rather than an event.** An agent that printed straight off
`order:updated` would reprint its whole history on every reconnect — the
clients report a reconnect as "anything may have changed" and refetch — lose a
ticket outright whenever the printer was out of paper, and have no way to tell
a redelivery from a second order. A row per ticket answers all three: it
survives a restart, it waits for a printer that is switched off, and it has an
id the agent can remember having printed.

**Why the enqueue runs inside the order's own transaction.** The realtime
outbox exists because Redis is an external side effect that must not precede
a commit. A database row has no such problem: it becomes visible exactly when
the transaction commits, which is the semantics wanted here, for free. So
there is no after-commit listener and no second session — a rolled-back order
takes its tickets with it, and a committed one cannot be missing them.

What that buys has to be paid for in one place: this module must never raise
into the caller. The caller is placing an order. A renderer bug, a printer
row with impossible configuration, a database hiccup on an index — none of
those may cost a customer their order. So `enqueue_for_order` catches
everything and logs.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, selectinload

from app.config import get_settings
from app.models.enums import PrintJobKind, PrintJobSource, PrintJobStatus
from app.models.order import Order
from app.models.print_agent import PrintAgent, Printer, PrintJob
from app.services.print.document import Document
from app.services.print.render import (
    render_customer_bill,
    render_kitchen_docket,
    render_test_page,
    render_void_slip,
)

logger = logging.getLogger(__name__)


def _branch_timezone(order: Order) -> ZoneInfo:
    """The timezone the ticket's times are printed in.

    The platform's business timezone today, because that is what the rest of
    the ordering code uses — slots, scheduling and the order board all read
    `settings.business_timezone_info`. Per-branch timezones are a real future
    need for a platform selling to more than one country, and when they exist
    this is the one place a ticket reads them from.
    """

    return get_settings().business_timezone_info


def printers_for(
    db: Session,
    *,
    restaurant_location_id: uuid.UUID,
    kind: PrintJobKind,
) -> list[Printer]:
    """Every printer at this branch that takes this kind of ticket.

    Three conditions, and all three are the owner's switches rather than the
    platform's: the agent is enabled, the printer is enabled, and the printer
    subscribes to this kind. That last one is what lets one PC drive a kitchen
    printer that takes dockets and a counter printer that takes bills, without
    anything in the agent knowing which is which.

    An empty list is a normal answer, not an error. A branch with no printer
    paired yet simply queues nothing.
    """

    statement = (
        select(Printer)
        .join(PrintAgent, Printer.print_agent_id == PrintAgent.id)
        .where(
            PrintAgent.restaurant_location_id == restaurant_location_id,
            PrintAgent.is_enabled.is_(True),
            Printer.is_enabled.is_(True),
        )
    )
    # Filtered in Python rather than with an ARRAY containment operator so the
    # same code works against SQLite, where `docket_kinds` is JSON. The list
    # is one branch's printers; there is no scale question here.
    return [
        printer
        for printer in db.scalars(statement).all()
        if kind.value in (printer.docket_kinds or [])
    ]


def _render(
    order: Order,
    *,
    kind: PrintJobKind,
    printer: Printer,
    reason: str | None = None,
) -> Document:
    restaurant = order.restaurant_location.restaurant if order.restaurant_location else None
    name = restaurant.name if restaurant is not None else "Order"
    branch = order.restaurant_location.branch_name if order.restaurant_location else None
    common = dict(
        restaurant_name=name,
        branch_name=branch,
        width=printer.paper_width_chars,
        tz=_branch_timezone(order),
    )
    if kind == PrintJobKind.KITCHEN_DOCKET:
        return render_kitchen_docket(order, **common)
    if kind == PrintJobKind.CUSTOMER_BILL:
        return render_customer_bill(order, **common)
    if kind == PrintJobKind.VOID_SLIP:
        return render_void_slip(order, reason=reason, **common)
    raise ValueError(f"{kind} is not rendered from an order")


def enqueue_for_order(
    db: Session,
    order: Order,
    *,
    kind: PrintJobKind,
    source: PrintJobSource = PrintJobSource.AUTO,
    reason: str | None = None,
) -> list[PrintJob]:
    """Queue this ticket on every printer at the branch that wants it.

    Returns the jobs created, which may be none — no printer paired, none
    subscribing to this kind, or one already queued.

    **Never raises.** The caller is in the middle of placing an order and a
    ticket is not worth one. Everything here is caught and logged, including
    the renderer, because a bug in how a docket is laid out must not be able
    to refuse a customer's money.

    **Runs with the flag OFF as well.** The rows are written and visible to
    the owner — a dry run of exactly what would have printed — and the agent
    endpoints refuse to serve them. Same posture as marketing dispatch: the
    inspectable rehearsal is the point, because paper is not recallable.
    """

    if order.restaurant_location_id is None:
        return []

    created: list[PrintJob] = []
    try:
        printers = printers_for(
            db, restaurant_location_id=order.restaurant_location_id, kind=kind
        )
        for printer in printers:
            document = _render(order, kind=kind, printer=printer, reason=reason)
            job = PrintJob(
                printer_id=printer.id,
                order_id=order.id,
                kind=kind,
                source=source,
                status=PrintJobStatus.QUEUED,
                document=document.to_dict(),
            )
            try:
                # Added INSIDE the savepoint, not before it, and that ordering
                # is the entire fix for a bug this caught in testing.
                #
                # `db.add` outside the block leaves the object pending on the
                # OUTER session, so rolling the savepoint back undoes the
                # INSERT without discarding the object — and the next flush
                # retries exactly the insert the index just refused. The
                # session ends up in `PendingRollbackError`, which means the
                # ORDER's commit fails. A duplicate ticket would have cost a
                # customer their order, which is the one thing this module
                # promises cannot happen.
                #
                # Flushed per job so the index answers now, for this job,
                # rather than failing the whole batch at commit.
                with db.begin_nested():
                    db.add(job)
                    db.flush()
            except IntegrityError:
                # `uq_print_jobs_auto_once`: this order already has this
                # ticket on this printer. The correct outcome, and the whole
                # reason the index exists — a replayed webhook or a retried
                # task reaches here and changes nothing.
                logger.debug(
                    "Print job already queued order=%s printer=%s kind=%s",
                    order.id,
                    printer.id,
                    kind.value,
                )
                continue
            created.append(job)
    except (SQLAlchemyError, Exception):  # noqa: B014 - deliberate catch-all
        # See the docstring. A ticket is never worth an order.
        logger.exception(
            "Could not queue %s for order %s; the order is unaffected",
            kind.value,
            order.id,
        )
        return created

    if created:
        logger.info(
            "Queued %d %s ticket(s) for order %s%s",
            len(created),
            kind.value,
            order.id,
            "" if get_settings().enable_auto_print else " (dry run: auto-print is off)",
        )
    return created


def enqueue_test_print(db: Session, printer: Printer) -> PrintJob:
    """A ticket proving this printer works, from the admin screen.

    Unlike the others this one raises on failure, because its caller is a
    person who pressed Test and is waiting for an answer. Silence would be the
    wrong report.

    Always MANUAL, so the idempotency index does not apply: pressing Test
    twice should print twice, which is how somebody checks whether the first
    one was a fluke.
    """

    agent = printer.agent
    restaurant = agent.restaurant if agent is not None else None
    document = render_test_page(
        restaurant_name=restaurant.name if restaurant is not None else "Test",
        printer_name=printer.name,
        width=printer.paper_width_chars,
        tz=get_settings().business_timezone_info,
    )
    job = PrintJob(
        printer_id=printer.id,
        order_id=None,
        kind=PrintJobKind.TEST,
        source=PrintJobSource.MANUAL,
        status=PrintJobStatus.QUEUED,
        document=document.to_dict(),
    )
    db.add(job)
    db.flush()
    return job


def claim_jobs(db: Session, agent: PrintAgent, *, limit: int | None = None) -> list[PrintJob]:
    """Hand this agent its next tickets, under a lease.

    Takes QUEUED jobs and jobs whose CLAIMED lease has expired. The second
    half is the crash recovery, and it needs no sweeper: an agent that died
    between claiming a ticket and printing it hands it back by doing nothing,
    because the lease simply runs out and the next poll is allowed to take it.

    Ordered oldest first so a kitchen receives tickets in the order the
    orders arrived. `with_for_update(skip_locked=True)` so two agents on one
    branch — or one agent polling twice because a reply was slow — cannot be
    served the same row.

    Refuses everything while `enable_auto_print` is off. The jobs stay QUEUED
    and visible: that is the inspectable dry run, not a broken queue.
    """

    settings = get_settings()
    if not settings.enable_auto_print:
        return []
    if not agent.is_enabled:
        return []

    lease_cutoff = datetime.now(UTC) - timedelta(
        seconds=settings.print_job_claim_lease_seconds
    )
    batch = limit or settings.print_job_poll_batch

    statement = (
        select(PrintJob)
        .join(Printer, PrintJob.printer_id == Printer.id)
        .where(
            Printer.print_agent_id == agent.id,
            Printer.is_enabled.is_(True),
            or_(
                PrintJob.status == PrintJobStatus.QUEUED,
                (PrintJob.status == PrintJobStatus.CLAIMED)
                & (PrintJob.claimed_at < lease_cutoff),
            ),
        )
        .order_by(PrintJob.created_at)
        .limit(batch)
        .with_for_update(skip_locked=True)
        .options(selectinload(PrintJob.printer))
    )

    jobs = list(db.scalars(statement).all())
    now = datetime.now(UTC)
    for job in jobs:
        job.status = PrintJobStatus.CLAIMED
        job.claimed_at = now
        job.attempts = (job.attempts or 0) + 1
        db.add(job)
    if jobs:
        agent.last_seen_at = now
        db.add(agent)
    db.commit()
    return jobs


def ack_job(
    db: Session,
    agent: PrintAgent,
    job_id: uuid.UUID,
    *,
    printed: bool,
    error: str | None = None,
) -> PrintJob | None:
    """Close a ticket the agent has finished with.

    Idempotent: acking an already-PRINTED job changes nothing and still
    answers. The agent keeps its own ledger of printed job ids and re-acks a
    redelivery, so this is a normal path rather than a client bug.

    Scoped to the agent's own printers, and returns None rather than raising
    for anything else — the route turns that into a 404, for the reason the
    order board gives: a client learns nothing about work that is not its own,
    including whether it exists.
    """

    job = db.scalars(
        select(PrintJob)
        .join(Printer, PrintJob.printer_id == Printer.id)
        .where(PrintJob.id == job_id, Printer.print_agent_id == agent.id)
    ).first()
    if job is None:
        return None

    now = datetime.now(UTC)
    if printed:
        job.status = PrintJobStatus.PRINTED
        job.printed_at = job.printed_at or now
        job.last_error = None
        job.printer.last_printed_at = now
        job.printer.last_error = None
    else:
        job.status = PrintJobStatus.FAILED
        # The sentence an owner reads. The Marketing Hub's argument, for the
        # same reason: "that string lands in `campaign.last_error` and then on
        # their screen". It is stored on the printer as well as the job so the
        # admin can say "this printer is unreachable" without scanning jobs.
        job.last_error = (error or "The agent could not print this ticket.")[:2000]
        job.printer.last_error = job.last_error

    agent.last_seen_at = now
    db.add_all([job, job.printer, agent])
    db.commit()
    return job
