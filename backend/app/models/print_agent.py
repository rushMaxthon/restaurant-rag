from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.models.enums import (
    PrinterTransport,
    PrintJobKind,
    PrintJobSource,
    PrintJobStatus,
)

if TYPE_CHECKING:
    from app.models.order import Order
    from app.models.restaurant import Restaurant
    from app.models.restaurant_location import RestaurantLocation


#: A paired agent may hold a token for a long time, so the pairing code it was
#: swapped for must be short-lived. Ten minutes is long enough to walk to the
#: kitchen PC and type six digits, and short enough that a code left on an
#: owner's screen is worthless by the time anyone else reads it.
PAIRING_CODE_TTL_SECONDS = 600

#: How long a claimed job stays claimed before another poll may take it.
#:
#: This is the whole of the crash-recovery design. An agent that dies between
#: claiming a ticket and printing it hands the ticket back by doing nothing:
#: the lease expires and the next poll is allowed to serve it again. No
#: sweeper, no background task, nothing to forget to run.
#:
#: Two minutes rather than ten seconds because a printer can legitimately take
#: a while — a long docket on a slow thermal head, or a TCP connect timing out
#: against an unplugged printer — and re-serving a job that is still printing
#: is how a kitchen gets two of the same ticket.
JOB_CLAIM_LEASE_SECONDS = 120


class PrintAgent(TimestampMixin, Base):
    """One installed copy of the Windows print agent.

    A device, not a person, and that distinction is the reason this table
    exists at all. `UserRole.KITCHEN` was added because advancing an order was
    `require_owner`, so "the only way to put a board in a kitchen was to leave
    the owner signed in on it - one token that also edits the menu, spends
    marketing budget and reads revenue, on a tablet on a wall". An agent is
    that argument one step further: its credential sits unattended on a PC in a
    restaurant for years, and it must be revocable without ending any cook's
    session.

    So it holds its own hashed token and its own `token_version`, and it can do
    exactly two things over the API: read the jobs queued for its own printers,
    and say whether they printed.

    **The branch is not nullable, unlike a KITCHEN account's.** A NULL location
    on `users` means "every branch of that restaurant" and is a real answer for
    a cook who covers two kitchens. A printer is a physical object in one room,
    so there is no such reading here, and the composite foreign key below ties
    the branch to the restaurant rather than trusting them to agree.
    """

    __tablename__ = "print_agents"
    __table_args__ = (
        # The branch belongs to the restaurant, enforced by the database.
        #
        # A composite FK onto `(id, restaurant_id)` rather than a plain one
        # onto `id`, for the reason `ck_users_kitchen_assignment` gives: an
        # agent pinned to somebody else's branch becomes unrepresentable
        # rather than merely unlikely. Without this, two correct-looking
        # foreign keys still permit a printer in Surat queued with Ahmedabad's
        # orders.
        ForeignKeyConstraint(
            ["restaurant_location_id", "restaurant_id"],
            ["restaurant_locations.id", "restaurant_locations.restaurant_id"],
            name="fk_print_agents_location_matches_restaurant",
            # RESTRICT, not CASCADE: deleting a branch that still has a printer
            # paired to it should fail loudly rather than silently leave an
            # agent holding a valid token for a scope that no longer exists.
            ondelete="RESTRICT",
        ),
        Index("ix_print_agents_restaurant_id", "restaurant_id"),
        Index("ix_print_agents_restaurant_location_id", "restaurant_location_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    restaurant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("restaurants.id", ondelete="RESTRICT"),
        nullable=False,
    )
    restaurant_location_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )

    #: What the owner calls this machine. "Kitchen PC", "Counter laptop".
    name: Mapped[str] = mapped_column(String(120), nullable=False)

    #: SHA-256 of the agent's bearer token. The raw token is shown once, at
    #: pairing, and never stored - the same posture as any other credential
    #: here, and the reason a leaked database row cannot be used to print.
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)

    #: Bumped to revoke. Every authenticated call checks it, so disabling an
    #: agent stops it on its next poll rather than whenever a token expires -
    #: mirroring `users.token_version`, which exists because "the tablet keeps
    #: working until its token expires" was the bug.
    token_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    #: Reported by the agent on every heartbeat. Support reads this first: half
    #: of "the printer stopped working" is an agent three versions behind.
    agent_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    hostname: Mapped[str | None] = mapped_column(String(120), nullable=True)

    #: Null until the agent has ever connected. The admin screen reads this to
    #: say online or offline, so a paired-but-never-started agent is visibly
    #: different from one that has stopped.
    last_seen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    restaurant: Mapped[Restaurant] = relationship("Restaurant")
    location: Mapped[RestaurantLocation] = relationship(
        "RestaurantLocation",
        primaryjoin="PrintAgent.restaurant_location_id == RestaurantLocation.id",
        foreign_keys="PrintAgent.restaurant_location_id",
        viewonly=True,
    )
    printers: Mapped[list[Printer]] = relationship(
        "Printer", back_populates="agent", cascade="all, delete-orphan"
    )


class Printer(TimestampMixin, Base):
    """One printer an agent can reach.

    Separate from the agent because one PC commonly drives two: a docket
    printer bolted to the kitchen wall and a bill printer at the counter.
    Making that two agents would mean two installs and two tokens on one
    machine; making it one agent with one printer would mean the second
    printer needs a second PC.

    **`docket_kinds` is the routing rule, and it is data.** The kitchen printer
    subscribes to dockets and voids, the counter printer to bills. Nothing in
    the agent branches on which printer it is talking to, which is what keeps
    the agent a dumb pipe and the decision somewhere the owner can change it.
    """

    __tablename__ = "printers"
    __table_args__ = (
        # The transport is exhaustive, so a half-configured printer cannot be
        # stored. Without this a row could claim TCP and carry no host, and the
        # failure would surface as a confusing error on the agent at the moment
        # an order arrived rather than when somebody saved the form.
        CheckConstraint(
            "(transport = 'TCP' AND host IS NOT NULL AND port IS NOT NULL"
            " AND windows_printer_name IS NULL)"
            " OR (transport = 'WINDOWS' AND windows_printer_name IS NOT NULL"
            " AND host IS NULL AND port IS NULL)",
            name="transport_is_exhaustive",
        ),
        # 32 columns is 58mm paper and 48 is 80mm. Anything else is a typo, and
        # a wrong column count is not a subtle failure: every line wraps and
        # the docket becomes unreadable mush.
        CheckConstraint(
            "paper_width_chars IN (32, 42, 48)", name="paper_width_is_known"
        ),
        CheckConstraint("copies BETWEEN 1 AND 5", name="copies_are_sane"),
        Index("ix_printers_print_agent_id", "print_agent_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    print_agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("print_agents.id", ondelete="CASCADE"),
        nullable=False,
    )

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    transport: Mapped[PrinterTransport] = mapped_column(
        Enum(PrinterTransport, name="printer_transport"), nullable=False
    )

    #: TCP only. The printer's own address on the restaurant's LAN; 9100 is the
    #: raw-print port essentially every thermal printer answers on.
    host: Mapped[str | None] = mapped_column(String(255), nullable=True)
    port: Mapped[int | None] = mapped_column(Integer, nullable=True)

    #: WINDOWS only. The queue name as the spooler knows it.
    windows_printer_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    paper_width_chars: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=48
    )
    copies: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)

    #: Which kinds of ticket this printer takes. See the class docstring.
    docket_kinds: Mapped[list[str]] = mapped_column(
        ARRAY(String(32)), nullable=False, default=list
    )

    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    #: The last failure, in a sentence written for the owner.
    #:
    #: The same device the Marketing Hub uses for a provider error, for the
    #: same reason: "that string lands in `campaign.last_error` and then on
    #: their screen". "Connection refused" is not an answer; "the printer at
    #: 192.168.1.50 did not answer - check it is switched on and on the same
    #: network" is.
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_printed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    agent: Mapped[PrintAgent] = relationship("PrintAgent", back_populates="printers")


class PrintJob(TimestampMixin, Base):
    """One ticket, from the moment it is decided on to the moment it is paper.

    The queue is the feature. An agent that printed straight off a realtime
    event would reprint its whole history on reconnect (the client reports a
    reconnect as "anything may have changed"), lose a ticket outright whenever
    the printer was out of paper, and have no way to tell a redelivery from a
    second order. A row per ticket answers all three: it survives a restart, it
    waits for a printer that is switched off, and it has an id the agent can
    remember having printed.
    """

    __tablename__ = "print_jobs"
    __table_args__ = (
        # One automatic ticket per order per printer, enforced by Postgres.
        #
        # This is the idempotency guarantee, and it is here rather than in the
        # service on purpose: a double-firing enqueue, a replayed webhook or a
        # retried Celery task physically cannot write a second docket. Scoped
        # to AUTO so a reprint - whose entire purpose is a second copy - is
        # unconstrained, and excluding FAILED so a ticket that did not print
        # can be queued again.
        Index(
            "uq_print_jobs_auto_once",
            "printer_id",
            "order_id",
            "kind",
            unique=True,
            postgresql_where=text("source = 'AUTO' AND status <> 'FAILED'"),
        ),
        # The poll orders by this: oldest queued first, per printer.
        Index("ix_print_jobs_printer_status", "printer_id", "status", "created_at"),
        Index("ix_print_jobs_order_id", "order_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    printer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("printers.id", ondelete="CASCADE"),
        nullable=False,
    )

    #: Null for a TEST print, which belongs to no order. Every other kind has
    #: one, and the index above depends on it.
    order_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id", ondelete="CASCADE"), nullable=True
    )

    kind: Mapped[PrintJobKind] = mapped_column(
        Enum(PrintJobKind, name="print_job_kind"), nullable=False
    )
    source: Mapped[PrintJobSource] = mapped_column(
        Enum(PrintJobSource, name="print_job_source"),
        nullable=False,
        default=PrintJobSource.AUTO,
    )
    status: Mapped[PrintJobStatus] = mapped_column(
        Enum(PrintJobStatus, name="print_job_status"),
        nullable=False,
        default=PrintJobStatus.QUEUED,
    )

    #: The rendered ticket, as a structured document rather than printer bytes.
    #:
    #: Stored rather than re-derived, and that is a deliberate audit property:
    #: a reprint reproduces exactly what the kitchen saw at the time, even if
    #: the order, the menu or the branch's prices have changed since. Rendering
    #: again on reprint would quietly produce a different ticket for the same
    #: order and nobody would know which one the cook worked from.
    document: Mapped[dict] = mapped_column(JSONB, nullable=False)

    attempts: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    claimed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    printed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    printer: Mapped[Printer] = relationship("Printer")
    order: Mapped[Order | None] = relationship("Order")
