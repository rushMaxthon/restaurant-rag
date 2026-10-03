"""The owner's side of printing: pair an agent, configure printers, reprint.

Separate from `print_agents.py` because the two have nothing in common but a
subject. That one authenticates a device with a bearer token and lets it read
its own queue; this one authenticates a person and lets them decide what the
queue is for. Putting both behind one router would mean one file where it
matters most which caller is which.

Scoping is `resolve_insights_scope`, the same rule every other tenant-scoped
screen uses: "an ADMIN has no implicit restaurant; an OWNER may not name one."
So an admin must say which restaurant, and an owner cannot ask about anybody
else's — enforced here rather than hidden by the UI.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.config.database import get_db
from app.models.enums import PrinterTransport, PrintJobKind, PrintJobSource, PrintJobStatus
from app.models.order import Order
from app.models.print_agent import PrintAgent, Printer, PrintJob
from app.models.restaurant_location import RestaurantLocation
from app.models.user import User
from app.services.auth import get_current_user
from app.services.insights.scope import resolve_insights_scope
from app.services.print.queue import enqueue_for_order, enqueue_test_print
from app.api.print_agents import issue_pairing_code

router = APIRouter(prefix="/printing", tags=["Printing"])

StaffDep = Annotated[User, Depends(get_current_user)]
DbDep = Annotated[Session, Depends(get_db)]


def _scoped_restaurant_id(
    db: Session, current_user: User, restaurant_id: uuid.UUID | None
) -> uuid.UUID:
    scope = resolve_insights_scope(db, current_user=current_user, restaurant_id=restaurant_id)
    return scope.restaurant_id


def _agent_in_scope(db: Session, restaurant_id: uuid.UUID, agent_id: uuid.UUID) -> PrintAgent:
    agent = db.scalars(
        select(PrintAgent)
        .where(PrintAgent.id == agent_id, PrintAgent.restaurant_id == restaurant_id)
        .options(selectinload(PrintAgent.printers))
    ).first()
    if agent is None:
        # 404 rather than 403, as everywhere else: a caller learns nothing
        # about an agent that is not theirs, including whether it exists.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such agent.")
    return agent


def _printer_in_scope(db: Session, restaurant_id: uuid.UUID, printer_id: uuid.UUID) -> Printer:
    printer = db.scalars(
        select(Printer)
        .join(PrintAgent, Printer.print_agent_id == PrintAgent.id)
        .where(Printer.id == printer_id, PrintAgent.restaurant_id == restaurant_id)
        .options(selectinload(Printer.agent))
    ).first()
    if printer is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such printer.")
    return printer


def _refuse_duplicate_address(
    db: Session,
    *,
    restaurant_location_id: uuid.UUID,
    body: PrinterIn,
    printer_id: uuid.UUID | None = None,
) -> None:
    """Two printer rows must not point at the same physical printer.

    Found live, and it is not a cosmetic duplicate: two rows at one branch
    both subscribed to KITCHEN_DOCKET and both addressed to 192.168.29.39:9100
    means every order queues two dockets and both are sent to the same print
    head. A kitchen gets two of every ticket and nothing in the system looks
    wrong — the idempotency index is per PRINTER, and as far as it is
    concerned these are two printers.

    Several printers per branch is the supported case (kitchen, counter, expo),
    and several agents per branch is too. What cannot be right is two rows with
    one address.
    """

    if body.transport == PrinterTransport.TCP:
        target = (body.host or "").strip().lower(), body.port or 9100
    else:
        target = ((body.windows_printer_name or "").strip().lower(), None)

    siblings = db.scalars(
        select(Printer)
        .join(PrintAgent, Printer.print_agent_id == PrintAgent.id)
        .where(PrintAgent.restaurant_location_id == restaurant_location_id)
    ).all()

    for other in siblings:
        if printer_id is not None and other.id == printer_id:
            continue
        if other.transport != body.transport:
            continue
        if body.transport == PrinterTransport.TCP:
            existing = ((other.host or "").strip().lower(), other.port or 9100)
        else:
            existing = ((other.windows_printer_name or "").strip().lower(), None)
        if existing != target:
            continue
        where = (
            f"{body.host}:{body.port or 9100}"
            if body.transport == PrinterTransport.TCP
            else body.windows_printer_name
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"'{other.name}' at this branch already prints to {where}. "
                "Two printers on one address means every ticket prints twice. "
                "Point this one somewhere else, or edit the existing printer instead."
            ),
        )


# --- schemas ---------------------------------------------------------------


class PrinterOut(BaseModel):
    id: uuid.UUID
    name: str
    transport: str
    host: str | None
    port: int | None
    windows_printer_name: str | None
    paper_width_chars: int
    copies: int
    docket_kinds: list[str]
    is_enabled: bool
    last_error: str | None
    last_printed_at: datetime | None


class AgentOut(BaseModel):
    id: uuid.UUID
    name: str
    restaurant_location_id: uuid.UUID
    branch_name: str | None
    hostname: str | None
    agent_version: str | None
    last_seen_at: datetime | None
    is_enabled: bool
    printers: list[PrinterOut]


class PairingCodeRequest(BaseModel):
    restaurant_location_id: uuid.UUID
    name: str = Field(min_length=1, max_length=120)
    restaurant_id: uuid.UUID | None = None


class PairingCodeResponse(BaseModel):
    code: str
    expires_at: datetime
    #: Repeated back so the admin screen can say what the code is FOR. An
    #: owner with two branches pairing the wrong one is a silent failure:
    #: every order prints somewhere nobody is standing.
    branch_name: str


class PrinterIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    transport: PrinterTransport
    host: str | None = Field(default=None, max_length=255)
    port: int | None = Field(default=9100, ge=1, le=65535)
    windows_printer_name: str | None = Field(default=None, max_length=255)
    paper_width_chars: int = 48
    copies: int = Field(default=1, ge=1, le=5)
    docket_kinds: list[PrintJobKind] = Field(
        default_factory=lambda: [PrintJobKind.KITCHEN_DOCKET, PrintJobKind.VOID_SLIP]
    )

    @field_validator("paper_width_chars")
    @classmethod
    def _known_width(cls, value: int) -> int:
        # The database CHECK says the same thing; saying it here too means the
        # owner gets a sentence instead of a 500 from a constraint.
        if value not in (32, 42, 48):
            raise ValueError(
                "Paper width must be 32 (58mm), 42 or 48 (80mm) characters. "
                "A wrong column count makes every line wrap."
            )
        return value

    def validated(self) -> PrinterIn:
        """The transport's own requirements, as a sentence rather than a 500.

        The `transport_is_exhaustive` CHECK on `printers` is the real
        guarantee. This exists so saving the form is refused with something an
        owner can act on.
        """

        if self.transport == PrinterTransport.TCP:
            if not self.host:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="A network printer needs its IP address.",
                )
            self.windows_printer_name = None
            self.port = self.port or 9100
        else:
            if not self.windows_printer_name:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=(
                        "A Windows printer needs its queue name, exactly as it appears in "
                        "Settings > Printers & scanners."
                    ),
                )
            self.host = None
            self.port = None
        return self


class JobOut(BaseModel):
    id: uuid.UUID
    order_id: uuid.UUID | None
    printer_id: uuid.UUID
    printer_name: str | None
    kind: str
    source: str
    status: str
    attempts: int
    last_error: str | None
    created_at: datetime
    printed_at: datetime | None


# --- endpoints -------------------------------------------------------------


@router.get("/agents", response_model=list[AgentOut])
def list_agents(
    current_user: StaffDep,
    db: DbDep,
    restaurant_id: uuid.UUID | None = None,
) -> list[AgentOut]:
    """Every agent for this restaurant, with its printers.

    `restaurant_id` is an optional query parameter for the reason every other
    insights and marketing route takes one: this panel serves both roles, an
    ADMIN has no implicit restaurant, and omitting it is answered with a
    sentence rather than somebody else's data.
    """

    scoped = _scoped_restaurant_id(db, current_user, restaurant_id)
    agents = db.scalars(
        select(PrintAgent)
        .where(PrintAgent.restaurant_id == scoped)
        .options(selectinload(PrintAgent.printers))
        .order_by(PrintAgent.created_at)
    ).all()
    branches = {
        row.id: row.branch_name
        for row in db.scalars(
            select(RestaurantLocation).where(RestaurantLocation.restaurant_id == scoped)
        ).all()
    }
    return [
        AgentOut(
            id=agent.id,
            name=agent.name,
            restaurant_location_id=agent.restaurant_location_id,
            branch_name=branches.get(agent.restaurant_location_id),
            hostname=agent.hostname,
            agent_version=agent.agent_version,
            last_seen_at=agent.last_seen_at,
            is_enabled=agent.is_enabled,
            printers=[PrinterOut.model_validate(p, from_attributes=True) for p in agent.printers],
        )
        for agent in agents
    ]


@router.post("/pairing-code", response_model=PairingCodeResponse)
def create_pairing_code(
    payload: PairingCodeRequest,
    current_user: StaffDep,
    db: DbDep,
) -> PairingCodeResponse:
    """A six-digit code for somebody standing at the kitchen PC.

    This is the only moment a long-lived credential comes into existence, so
    it is the moment worth constraining: the code lasts ten minutes, is used
    once, and can only ever create an agent for the branch named here.
    """

    scoped = _scoped_restaurant_id(db, current_user, payload.restaurant_id)
    location = db.scalars(
        select(RestaurantLocation).where(
            RestaurantLocation.id == payload.restaurant_location_id,
            RestaurantLocation.restaurant_id == scoped,
        )
    ).first()
    if location is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such branch.")

    issued = issue_pairing_code(
        restaurant_id=scoped,
        restaurant_location_id=location.id,
        name=payload.name.strip(),
    )
    return PairingCodeResponse(
        code=issued["code"],
        expires_at=issued["expires_at"],
        branch_name=location.branch_name,
    )


@router.post("/agents/{agent_id}/printers", response_model=PrinterOut, status_code=201)
def add_printer(
    agent_id: uuid.UUID,
    payload: PrinterIn,
    current_user: StaffDep,
    db: DbDep,
    restaurant_id: uuid.UUID | None = None,
) -> PrinterOut:
    scoped = _scoped_restaurant_id(db, current_user, restaurant_id)
    agent = _agent_in_scope(db, scoped, agent_id)
    body = payload.validated()
    _refuse_duplicate_address(
        db, restaurant_location_id=agent.restaurant_location_id, body=body
    )
    printer = Printer(
        print_agent_id=agent.id,
        name=body.name.strip(),
        transport=body.transport,
        host=body.host,
        port=body.port,
        windows_printer_name=body.windows_printer_name,
        paper_width_chars=body.paper_width_chars,
        copies=body.copies,
        docket_kinds=[kind.value for kind in body.docket_kinds],
    )
    db.add(printer)
    db.commit()
    db.refresh(printer)
    return PrinterOut.model_validate(printer, from_attributes=True)


@router.patch("/printers/{printer_id}", response_model=PrinterOut)
def update_printer(
    printer_id: uuid.UUID,
    payload: PrinterIn,
    current_user: StaffDep,
    db: DbDep,
    restaurant_id: uuid.UUID | None = None,
) -> PrinterOut:
    scoped = _scoped_restaurant_id(db, current_user, restaurant_id)
    printer = _printer_in_scope(db, scoped, printer_id)
    body = payload.validated()
    _refuse_duplicate_address(
        db,
        restaurant_location_id=printer.agent.restaurant_location_id,
        body=body,
        printer_id=printer.id,
    )
    printer.name = body.name.strip()
    printer.transport = body.transport
    printer.host = body.host
    printer.port = body.port
    printer.windows_printer_name = body.windows_printer_name
    printer.paper_width_chars = body.paper_width_chars
    printer.copies = body.copies
    printer.docket_kinds = [kind.value for kind in body.docket_kinds]
    # Cleared on a save, because the error described the OLD configuration.
    # Leaving it would tell an owner their corrected address is still wrong.
    printer.last_error = None
    db.add(printer)
    db.commit()
    db.refresh(printer)
    return PrinterOut.model_validate(printer, from_attributes=True)


@router.post("/printers/{printer_id}/test", response_model=JobOut, status_code=201)
def test_print(
    printer_id: uuid.UUID,
    current_user: StaffDep,
    db: DbDep,
    restaurant_id: uuid.UUID | None = None,
) -> JobOut:
    """Queue a page that proves this printer works.

    Always MANUAL, so the idempotency index does not apply: pressing Test
    twice should print twice, which is how somebody checks whether the first
    one was a fluke.
    """

    scoped = _scoped_restaurant_id(db, current_user, restaurant_id)
    printer = _printer_in_scope(db, scoped, printer_id)
    job = enqueue_test_print(db, printer)
    db.commit()
    db.refresh(job)
    return JobOut(
        id=job.id,
        order_id=None,
        printer_id=job.printer_id,
        printer_name=printer.name,
        kind=job.kind.value,
        source=job.source.value,
        status=job.status.value,
        attempts=job.attempts,
        last_error=job.last_error,
        created_at=job.created_at,
        printed_at=job.printed_at,
    )


@router.post("/orders/{order_id}/reprint", response_model=list[JobOut], status_code=201)
def reprint_order(
    order_id: uuid.UUID,
    current_user: StaffDep,
    db: DbDep,
    kind: PrintJobKind = PrintJobKind.KITCHEN_DOCKET,
    restaurant_id: uuid.UUID | None = None,
) -> list[JobOut]:
    """Print this order's ticket again.

    MANUAL, so it is not blocked by the index that makes automatic printing
    idempotent — a second copy is the entire point. Re-rendered rather than
    replayed from the first job's stored document, because a reprint an hour
    later should show the order as it is now; the original job keeps its own
    snapshot of what the kitchen first saw.
    """

    scoped = _scoped_restaurant_id(db, current_user, restaurant_id)
    order = db.scalars(
        select(Order)
        .where(Order.id == order_id, Order.restaurant_id == scoped)
        .options(selectinload(Order.items), selectinload(Order.restaurant_location))
    ).first()
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such order.")

    jobs = enqueue_for_order(db, order, kind=kind, source=PrintJobSource.MANUAL)
    db.commit()
    if not jobs:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "No printer at this branch is set up to take that kind of ticket. "
                "Check the Printers page."
            ),
        )
    names = {p.id: p.name for p in db.scalars(select(Printer)).all()}
    return [
        JobOut(
            id=job.id,
            order_id=job.order_id,
            printer_id=job.printer_id,
            printer_name=names.get(job.printer_id),
            kind=job.kind.value,
            source=job.source.value,
            status=job.status.value,
            attempts=job.attempts,
            last_error=job.last_error,
            created_at=job.created_at,
            printed_at=job.printed_at,
        )
        for job in jobs
    ]


@router.get("/jobs", response_model=list[JobOut])
def list_jobs(
    current_user: StaffDep,
    db: DbDep,
    restaurant_id: uuid.UUID | None = None,
    limit: int = 50,
) -> list[JobOut]:
    """Recent tickets, newest first — including the ones that failed.

    This is where an owner finds out why nothing printed. `last_error` carries
    a sentence written for them, which is why every provider failure in this
    feature is phrased as advice rather than as an exception.
    """

    scoped = _scoped_restaurant_id(db, current_user, restaurant_id)
    jobs = db.scalars(
        select(PrintJob)
        .join(Printer, PrintJob.printer_id == Printer.id)
        .join(PrintAgent, Printer.print_agent_id == PrintAgent.id)
        .where(PrintAgent.restaurant_id == scoped)
        .options(selectinload(PrintJob.printer))
        .order_by(PrintJob.created_at.desc())
        .limit(min(max(limit, 1), 200))
    ).all()
    return [
        JobOut(
            id=job.id,
            order_id=job.order_id,
            printer_id=job.printer_id,
            printer_name=job.printer.name if job.printer else None,
            kind=job.kind.value,
            source=job.source.value,
            status=job.status.value,
            attempts=job.attempts,
            last_error=job.last_error,
            created_at=job.created_at,
            printed_at=job.printed_at,
        )
        for job in jobs
    ]


@router.patch("/agents/{agent_id}", response_model=AgentOut)
def update_agent(
    agent_id: uuid.UUID,
    current_user: StaffDep,
    db: DbDep,
    is_enabled: bool | None = None,
    name: str | None = None,
    restaurant_id: uuid.UUID | None = None,
) -> AgentOut:
    """Rename or switch off an agent.

    Switching off bumps `token_version` as well as the flag, so the PC stops
    on its next poll rather than whenever its token would have expired — the
    same reason deactivating a kitchen account bumps it. There is no delete:
    `print_jobs` points at these rows, and removing one would take the record
    of what was printed with it.
    """

    scoped = _scoped_restaurant_id(db, current_user, restaurant_id)
    agent = _agent_in_scope(db, scoped, agent_id)
    if name is not None:
        agent.name = name.strip()[:120]
    if is_enabled is not None and is_enabled != agent.is_enabled:
        agent.is_enabled = is_enabled
        agent.token_version = (agent.token_version or 1) + 1
    db.add(agent)
    db.commit()
    db.refresh(agent)
    location = agent.location
    return AgentOut(
        id=agent.id,
        name=agent.name,
        restaurant_location_id=agent.restaurant_location_id,
        branch_name=location.branch_name if location is not None else None,
        hostname=agent.hostname,
        agent_version=agent.agent_version,
        last_seen_at=agent.last_seen_at,
        is_enabled=agent.is_enabled,
        printers=[PrinterOut.model_validate(p, from_attributes=True) for p in agent.printers],
    )


__all__ = ["router"]
