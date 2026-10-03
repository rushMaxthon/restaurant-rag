"""What a print agent is allowed to ask this server.

Four endpoints and a deliberately small amount of authority. An agent is a
device sitting unattended on a PC in a restaurant, so it can do exactly two
things: read the tickets queued for its own printers, and say whether they
printed. It cannot advance an order, read revenue, see another branch, or
learn that another branch exists.

**Why the agent polls instead of being pushed to.** It holds an outbound
connection, so a restaurant needs no port forwarding, no static address and
nothing configured on its router. The Socket.IO channel the other clients use
is an accelerator on top of this — it tells the agent to poll now — and the
poll is what makes a ticket arrive at all. Same division as the kitchen
board's socket and its 30-second refetch.

**Authentication is a bearer token, not a login.** `Authorization: Bearer
<agent token>`, hashed in the database, with a `token_version` that revokes
instantly. Deliberately not a `users` row: `UserRole.KITCHEN` exists because
leaving an owner signed in on a wall tablet gave a cook a token that also
edited the menu and spent marketing budget, and an agent's credential lives
longer and is watched less.

**Out of scope is 404, never 403**, for the reason the order board gives: a
client learns nothing about work that is not its own, including whether it
exists.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.config import get_settings
from app.config.database import get_db
from app.models.enums import PrintJobStatus
from app.models.print_agent import PrintAgent, Printer
from app.services.print.queue import ack_job, claim_jobs

router = APIRouter(prefix="/print-agents", tags=["Printing"])


#: How long a pairing code is worth anything.
#:
#: Ten minutes: long enough to walk to the kitchen PC and type six digits,
#: short enough that a code still on an owner's screen after a break is
#: already useless. The code is the only moment a long-lived credential is
#: created, so it is the moment worth constraining.
PAIRING_CODE_TTL = timedelta(minutes=10)

#: Codes handed out and not yet used, in memory on purpose.
#:
#: A pairing code has a ten-minute life and exists to be used once, in the
#: same sitting, by somebody standing at the PC. Persisting it would mean a
#: table, a migration and a sweeper for a value whose entire purpose is to
#: stop mattering. A process restart invalidating outstanding codes is
#: acceptable: the owner presses the button again.
#:
#: The trade-off this accepts: with more than one API process, the code must
#: be redeemed by the process that issued it. Behind a load balancer that
#: means a retry may be needed. When that becomes real, this moves to Redis
#: with the same TTL - not to a table.
_pending_codes: dict[str, dict[str, Any]] = {}


def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _prune_codes() -> None:
    now = datetime.now(UTC)
    for code in [c for c, entry in _pending_codes.items() if entry["expires_at"] < now]:
        _pending_codes.pop(code, None)


def issue_pairing_code(
    *, restaurant_id: uuid.UUID, restaurant_location_id: uuid.UUID, name: str
) -> dict[str, Any]:
    """Mint a code for an owner to read off their screen.

    Called by the owner-facing route, not by the agent. Six digits because it
    is typed by a person on a keyboard they may be using for the first time;
    the secrecy that matters is in the token it becomes, not in the code.
    """

    _prune_codes()
    # `secrets`, not `random`: this is short-lived but it still authorises
    # the creation of a long-lived credential.
    code = f"{secrets.randbelow(1_000_000):06d}"
    expires_at = datetime.now(UTC) + PAIRING_CODE_TTL
    _pending_codes[code] = {
        "restaurant_id": restaurant_id,
        "restaurant_location_id": restaurant_location_id,
        "name": name,
        "expires_at": expires_at,
    }
    return {"code": code, "expires_at": expires_at}


def current_agent(
    db: Annotated[Session, Depends(get_db)],
    authorization: Annotated[str | None, Header()] = None,
) -> PrintAgent:
    """The agent this request is from, or 401.

    The token is compared by hash, and `token_version` is checked on every
    call rather than at pairing — so disabling an agent stops it on its next
    poll instead of whenever a token would have expired. `users.token_version`
    exists for the same reason, after "the tablet keeps working until its
    token expires" turned out to be the bug.
    """

    scheme, _, raw = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not raw.strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="This endpoint needs an agent token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    agent = db.scalars(
        select(PrintAgent)
        .where(PrintAgent.token_hash == _hash_token(raw.strip()))
        .options(selectinload(PrintAgent.printers))
    ).first()
    if agent is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="That agent token is not recognised. Pair this agent again.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not agent.is_enabled:
        # 403 rather than 401, and the difference is a contract the agent
        # branches on: 401 means "re-pair", 403 means "stop and wait for a
        # human". An agent that retried a disabled pairing forever would fill
        # a log and never recover.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This agent has been switched off in the admin panel.",
        )
    return agent


AgentDep = Annotated[PrintAgent, Depends(current_agent)]


# --- schemas ---------------------------------------------------------------


class PairRequest(BaseModel):
    code: str = Field(min_length=4, max_length=12)
    hostname: str | None = Field(default=None, max_length=120)
    agent_version: str | None = Field(default=None, max_length=40)


class PrinterConfig(BaseModel):
    id: uuid.UUID
    name: str
    transport: str
    host: str | None
    port: int | None
    windows_printer_name: str | None
    paper_width_chars: int
    copies: int
    docket_kinds: list[str]

    @classmethod
    def of(cls, printer: Printer) -> PrinterConfig:
        return cls(
            id=printer.id,
            name=printer.name,
            transport=printer.transport.value,
            host=printer.host,
            port=printer.port,
            windows_printer_name=printer.windows_printer_name,
            paper_width_chars=printer.paper_width_chars,
            copies=printer.copies,
            docket_kinds=list(printer.docket_kinds or []),
        )


class PairResponse(BaseModel):
    agent_id: uuid.UUID
    agent_token: str
    restaurant_name: str
    branch_name: str
    printers: list[PrinterConfig]


class JobPayload(BaseModel):
    id: uuid.UUID
    printer_id: uuid.UUID
    kind: str
    document: dict[str, Any]
    copies: int


class PollResponse(BaseModel):
    jobs: list[JobPayload]
    #: Sent on every poll so a change in the admin reaches the agent without
    #: anybody reinstalling anything. Paper width, a new printer, a changed
    #: address: all of it arrives with the next ticket.
    printers: list[PrinterConfig]
    #: What the agent should wait before polling again. Server-controlled so a
    #: deployment can slow every agent down at once, and so a disabled feature
    #: can tell them to back off rather than hammer.
    poll_after_seconds: int


class AckRequest(BaseModel):
    printed: bool
    error: str | None = Field(default=None, max_length=2000)


class HeartbeatRequest(BaseModel):
    agent_version: str | None = Field(default=None, max_length=40)
    printer_errors: dict[uuid.UUID, str | None] = Field(default_factory=dict)


# --- endpoints -------------------------------------------------------------


@router.post("/pair", response_model=PairResponse, status_code=status.HTTP_201_CREATED)
def pair_agent(
    payload: PairRequest,
    db: Annotated[Session, Depends(get_db)],
) -> PairResponse:
    """Exchange a six-digit code for a long-lived token.

    Unauthenticated by necessity — the agent has no credential yet, which is
    the whole point of the code. The code is single-use and short-lived, and
    it only ever authorises creating an agent for the branch the owner chose
    when they pressed the button.
    """

    _prune_codes()
    entry = _pending_codes.pop(payload.code.strip(), None)
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "That pairing code is not valid, or it has expired. "
                "Generate a new one from the Printers page and try again."
            ),
        )

    raw = secrets.token_urlsafe(32)
    agent = PrintAgent(
        restaurant_id=entry["restaurant_id"],
        restaurant_location_id=entry["restaurant_location_id"],
        name=entry["name"],
        token_hash=_hash_token(raw),
        hostname=payload.hostname,
        agent_version=payload.agent_version,
        last_seen_at=datetime.now(UTC),
    )
    db.add(agent)
    db.commit()
    db.refresh(agent)

    location = agent.location
    return PairResponse(
        agent_id=agent.id,
        # The only time this is ever returned. Everything else works from the
        # hash, so a leaked database row cannot be used to print.
        agent_token=raw,
        restaurant_name=agent.restaurant.name if agent.restaurant else "",
        branch_name=location.branch_name if location is not None else "",
        printers=[PrinterConfig.of(p) for p in agent.printers],
    )


@router.get("/me/jobs", response_model=PollResponse)
def poll_jobs(agent: AgentDep, db: Annotated[Session, Depends(get_db)]) -> PollResponse:
    """The agent's next tickets, claimed under a lease.

    An empty list is the normal answer and is not an error. The printer
    configuration comes back either way, so the agent is always working from
    what the admin currently says.
    """

    settings = get_settings()
    jobs = claim_jobs(db, agent)
    printers = {printer.id: printer for printer in agent.printers}
    return PollResponse(
        jobs=[
            JobPayload(
                id=job.id,
                printer_id=job.printer_id,
                kind=job.kind.value,
                document=job.document,
                copies=printers[job.printer_id].copies if job.printer_id in printers else 1,
            )
            for job in jobs
        ],
        printers=[PrinterConfig.of(p) for p in agent.printers],
        # Back off when there is nothing to do, and come straight back when
        # there was — a burst of orders drains without waiting out an idle
        # interval. The socket covers the latency between the two.
        poll_after_seconds=1 if jobs else settings.print_agent_poll_seconds,
    )


# `response_class=Response` because FastAPI refuses a 204 that declares a
# body, and the default class declares one.
@router.post(
    "/me/jobs/{job_id}/ack",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def acknowledge_job(
    job_id: uuid.UUID,
    payload: AckRequest,
    agent: AgentDep,
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    """Close a ticket. Idempotent, and scoped to this agent's own printers.

    Acking an already-printed job is a normal path, not a client bug: the
    agent keeps a local ledger of printed ids and re-acks a redelivery, which
    is the half of exactly-once that the server cannot provide.
    """

    job = ack_job(db, agent, job_id, printed=payload.printed, error=payload.error)
    if job is None:
        # Not this agent's, or gone. 404 either way — see the module
        # docstring.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such job.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/me/heartbeat", status_code=status.HTTP_200_OK)
def heartbeat(
    payload: HeartbeatRequest,
    agent: AgentDep,
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """"I am still here, and this is what I can reach."

    Separate from polling because an agent with nothing to print is still
    worth knowing about: the admin screen says online or offline from
    `last_seen_at`, and an agent that has stopped is the failure nobody
    notices until an order does not print.

    `printer_errors` lets the agent report a printer it cannot reach BEFORE a
    ticket needs it, so the owner can be told at four in the afternoon rather
    than during the evening rush.
    """

    agent.last_seen_at = datetime.now(UTC)
    if payload.agent_version:
        agent.agent_version = payload.agent_version
    for printer in agent.printers:
        if printer.id in payload.printer_errors:
            printer.last_error = payload.printer_errors[printer.id]
            db.add(printer)
    db.add(agent)
    db.commit()

    settings = get_settings()
    return {
        # So an agent can say "printing is switched off for this restaurant"
        # rather than looking broken while it polls an empty queue forever.
        "auto_print_enabled": settings.enable_auto_print,
        "poll_after_seconds": settings.print_agent_poll_seconds,
    }


__all__ = ["router", "issue_pairing_code"]
