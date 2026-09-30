"""The Socket.IO server: who may connect, which room they sit in, and when they leave.

Mounted inside FastAPI at `{api_v1_prefix}/socket.io` (see `app.main`), so
`app.main:app` stays the FastAPI object that gunicorn runs and every
`TestClient(app)` test imports — nothing about deployment changes.

Three decisions shape this file, each settled by the Phase 0 spike rather than
assumed:

* **WebSocket transport only.** Socket.IO's default long-polling transport
  needs every request of a session to reach the same process, and gunicorn has
  no sticky routing between its workers. With polling off there is one
  long-lived connection per client and nothing to be sticky about — which also
  holds the day Render runs more than one instance.
* **Fan-out through Redis.** `AsyncRedisManager` here, and the write-only
  `RedisManager` in `outbox` for sync code and Celery. Verified: 4 clients
  spread across 2 workers all received one emit made from a separate process.
* **The Origin check is engine.io's, with this backend's CORS rule.** It takes
  a callable, so the socket and `CORSMiddleware` answer from the same list and
  regex rather than two copies that drift. A foreign origin never reaches
  `connect`; a missing one (the mobile app, which is not a browser) is allowed,
  because a token is required either way.

Authentication happens in the handshake's `auth` payload — never the URL, which
lands in access logs. The payload carries the same identity the REST headers
do (`app_host` for a storefront, `bundle_id`/`platform` for a mobile build),
because a token is only valid for the app it was issued to and the handshake
cannot set those headers from a browser.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid
from dataclasses import dataclass
from typing import Any

import anyio
import socketio
from fastapi import HTTPException, status
from jose import jwt
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.config.database import SessionLocal
from app.models.enums import AppClientStatus, UserRole
from app.models.user import User
from app.services.app_clients import resolve_app_scope
from app.services.auth import _get_user_from_token, resolve_order_board_scope
from app.services.realtime.outbox import control_channel
from app.services.realtime.rooms import is_staff_role, staff_room, user_room

logger = logging.getLogger(__name__)
settings = get_settings()


class RealtimeRefused(Exception):
    """A handshake or subscription that must be refused, with a machine reason.

    The reason is what the client receives as `connect_error.message`, and the
    clients branch on it: `auth` signs the user out, `realtime_disabled` stops
    retrying, anything else backs off and retries.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True, slots=True)
class Principal:
    """What an open socket is, as of its handshake (or its last `subscribe`)."""

    user_id: uuid.UUID
    role: UserRole
    token_version: int
    expires_at: int
    staff_room: str | None


def origin_allowed(origin: str | None) -> bool:
    """The same answer `CORSMiddleware` gives, for the WebSocket handshake."""

    if origin is None:
        return True
    if origin in settings.backend_cors_origins_list:
        return True
    pattern = settings.cors_origin_regex
    return bool(pattern) and re.fullmatch(pattern, origin) is not None


def _optional_uuid(value: Any, field: str) -> uuid.UUID | None:
    if value in (None, ""):
        return None
    try:
        return uuid.UUID(str(value))
    except ValueError as exc:
        raise RealtimeRefused(f"invalid_{field}") from exc


def _refusal_for(exc: HTTPException) -> RealtimeRefused:
    if exc.status_code == status.HTTP_401_UNAUTHORIZED:
        return RealtimeRefused("auth")
    if exc.status_code == status.HTTP_403_FORBIDDEN:
        return RealtimeRefused("forbidden")
    return RealtimeRefused("unavailable")


def _staff_room_for(db: Session, user: User, requested: dict[str, Any]) -> str | None:
    """The one room this account may watch, via the board's own scope rule.

    `resolve_order_board_scope` is the ONLY thing that decides it. A requested
    restaurant or branch may only narrow the account's scope; anything outside
    it comes back 403 from there and is refused here.
    """

    if not is_staff_role(user.role):
        return None
    try:
        scope = resolve_order_board_scope(
            db,
            user,
            requested_restaurant_id=_optional_uuid(requested.get("restaurant_id"), "restaurant_id"),
            requested_restaurant_location_id=_optional_uuid(
                requested.get("restaurant_location_id"), "restaurant_location_id"
            ),
        )
    except HTTPException as exc:
        raise _refusal_for(exc) from exc
    return staff_room(scope)


def authenticate(db: Session, auth: Any) -> Principal:
    """Validate a handshake exactly as a REST request would be validated.

    Same app scope resolution as `get_app_scope`, same token checks as
    `get_current_user` (it IS that function — `_get_user_from_token` — so a
    token a REST call would refuse cannot open a socket), then the staff room
    from the board scope.
    """

    if not isinstance(auth, dict):
        raise RealtimeRefused("auth")
    token = auth.get("token")
    if not isinstance(token, str) or not token:
        raise RealtimeRefused("auth")

    host = str(auth.get("app_host") or "").split(",")[0]
    app_scope = resolve_app_scope(
        db,
        bundle_id=auth.get("bundle_id") or None,
        platform_value=auth.get("platform") or None,
        host=host or None,
    )
    if app_scope.status is not None and app_scope.status != AppClientStatus.ACTIVE:
        raise RealtimeRefused("forbidden")

    try:
        user = _get_user_from_token(db, token, app_scope)
    except HTTPException as exc:
        raise _refusal_for(exc) from exc

    # Already verified above; read only for the expiry the sweep enforces.
    expires_at = int(jwt.get_unverified_claims(token).get("exp") or 0)
    return Principal(
        user_id=user.id,
        role=user.role,
        token_version=user.token_version,
        expires_at=expires_at,
        staff_room=_staff_room_for(db, user, auth),
    )


def resubscribe(db: Session, principal: Principal, requested: Any) -> Principal:
    """Move a staff socket to another restaurant or branch it may watch.

    The account is re-read rather than trusted from the handshake: it may have
    been deactivated or re-branched since, and a subscription is a fresh claim.
    """

    if not isinstance(requested, dict):
        raise RealtimeRefused("invalid_subscription")
    user = db.get(User, principal.user_id)
    if user is None or not user.is_active or user.token_version != principal.token_version:
        raise RealtimeRefused("auth")
    if not is_staff_role(user.role):
        raise RealtimeRefused("forbidden")
    return Principal(
        user_id=principal.user_id,
        role=principal.role,
        token_version=principal.token_version,
        expires_at=principal.expires_at,
        staff_room=_staff_room_for(db, user, requested),
    )


def stale_principals(
    db: Session, principals: dict[str, Principal], *, now: float
) -> list[str]:
    """Which open sockets no longer stand on a valid session.

    Expired tokens need no query. For the rest, one query per sweep for every
    account with a socket on this process, not one per socket.
    """

    stale = [sid for sid, p in principals.items() if p.expires_at and p.expires_at <= now]
    live = {sid: p for sid, p in principals.items() if sid not in stale}
    if not live:
        return stale
    user_ids = {p.user_id for p in live.values()}
    rows = db.execute(
        select(User.id, User.token_version, User.is_active).where(User.id.in_(user_ids))
    ).all()
    current = {row.id: (row.token_version, row.is_active) for row in rows}
    for sid, principal in live.items():
        version, active = current.get(principal.user_id, (None, False))
        if not active or version != principal.token_version:
            stale.append(sid)
    return stale


# --- the server --------------------------------------------------------------

_client_manager = (
    socketio.AsyncRedisManager(settings.redis_url, channel=settings.realtime_redis_channel)
    if settings.enable_realtime
    else None
)

sio = socketio.AsyncServer(
    async_mode="asgi",
    client_manager=_client_manager,
    transports=["websocket"],
    cors_allowed_origins=origin_allowed,
    ping_interval=settings.realtime_ping_interval_seconds,
    ping_timeout=settings.realtime_ping_timeout_seconds,
    logger=False,
    engineio_logger=False,
)

# Sockets held by THIS process. A room says who hears an event; this says who
# a socket is, for `subscribe`, revocation and the sweep.
_principals: dict[str, Principal] = {}


def _with_session(fn: Any, *args: Any) -> Any:
    with SessionLocal() as db:
        return fn(db, *args)


@sio.event
async def connect(sid: str, environ: dict[str, Any], auth: Any = None) -> None:
    if not get_settings().enable_realtime:
        raise socketio.exceptions.ConnectionRefusedError("realtime_disabled")
    try:
        # Sync SQLAlchemy, so off the event loop: one slow database round trip
        # must not stall every other socket this process holds.
        principal = await anyio.to_thread.run_sync(_with_session, authenticate, auth)
    except RealtimeRefused as exc:
        raise socketio.exceptions.ConnectionRefusedError(exc.reason) from exc
    except Exception as exc:  # noqa: BLE001 - a refused socket, never a crashed handler
        logger.exception("Realtime handshake failed sid=%s", sid)
        raise socketio.exceptions.ConnectionRefusedError("unavailable") from exc

    _principals[sid] = principal
    await sio.enter_room(sid, user_room(principal.user_id))
    if principal.staff_room is not None:
        await sio.enter_room(sid, principal.staff_room)
    logger.info(
        "Realtime connected sid=%s user_id=%s role=%s room=%s",
        sid,
        principal.user_id,
        principal.role.value,
        principal.staff_room,
    )


@sio.event
async def subscribe(sid: str, data: Any = None) -> dict[str, Any]:
    """Change which restaurant or branch a staff socket watches.

    Answered through the acknowledgement, never silently: a board that asked
    for one branch and quietly kept another is worse than one told "no".
    """

    principal = _principals.get(sid)
    if principal is None:
        return {"ok": False, "error": "auth"}
    try:
        updated = await anyio.to_thread.run_sync(_with_session, resubscribe, principal, data)
    except RealtimeRefused as exc:
        if exc.reason == "auth":
            await sio.disconnect(sid)
        return {"ok": False, "error": exc.reason}
    except Exception:  # noqa: BLE001
        logger.exception("Realtime subscribe failed sid=%s", sid)
        return {"ok": False, "error": "unavailable"}

    if principal.staff_room is not None and principal.staff_room != updated.staff_room:
        await sio.leave_room(sid, principal.staff_room)
    if updated.staff_room is not None:
        await sio.enter_room(sid, updated.staff_room)
    _principals[sid] = updated
    return {"ok": True}


@sio.event
async def disconnect(sid: str, reason: Any = None) -> None:
    _principals.pop(sid, None)


async def _disconnect_user(user_id: str) -> None:
    for sid, principal in list(_principals.items()):
        if str(principal.user_id) == user_id:
            await sio.disconnect(sid)


async def _control_loop() -> None:
    """Act on revocations announced by any process (see `outbox`)."""

    import redis.asyncio as aioredis

    while True:
        client = None
        try:
            client = aioredis.from_url(settings.redis_url, decode_responses=True)
            pubsub = client.pubsub()
            await pubsub.subscribe(control_channel())
            async for message in pubsub.listen():
                if message.get("type") != "message":
                    continue
                try:
                    data = json.loads(message["data"])
                except (TypeError, ValueError):
                    continue
                if data.get("type") == "revoke" and data.get("user_id"):
                    await _disconnect_user(str(data["user_id"]))
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - the sweep covers the gap
            logger.warning("Realtime control listener lost Redis; retrying", exc_info=True)
            await asyncio.sleep(5)
        finally:
            if client is not None:
                try:
                    await client.aclose()
                except Exception:  # noqa: BLE001
                    pass


async def _sweep_loop() -> None:
    interval = max(5, settings.realtime_session_sweep_seconds)
    while True:
        await asyncio.sleep(interval)
        snapshot = dict(_principals)
        if not snapshot:
            continue
        try:
            stale = await anyio.to_thread.run_sync(
                _with_session, lambda db: stale_principals(db, snapshot, now=time.time())
            )
        except Exception:  # noqa: BLE001
            logger.warning("Realtime session sweep failed", exc_info=True)
            continue
        for sid in stale:
            await sio.disconnect(sid)


_background: list[asyncio.Task[None]] = []


async def start_background_tasks() -> None:
    if not settings.enable_realtime or _background:
        return
    _background.append(asyncio.create_task(_control_loop(), name="realtime-control"))
    _background.append(asyncio.create_task(_sweep_loop(), name="realtime-sweep"))


async def stop_background_tasks() -> None:
    while _background:
        task = _background.pop()
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass


asgi_app = socketio.ASGIApp(sio, socketio_path=None)
