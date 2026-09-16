from __future__ import annotations

import logging
import uuid
from time import perf_counter
from collections.abc import Iterator
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.deps import AppScopeDep, ensure_restaurant_writable
from app.config.database import get_db
from app.models.user import User
from app.schemas.chat import ChatClearResponse, ChatHistoryItemResponse, ChatMessageRequest, ChatMessageResponse
from app.services.auth import get_current_user, get_current_user_optional
from app.services.chat_principal import ChatPrincipal, guest_principal_for_session
from app.services.rag import clear_chat_history, get_chat_history, handle_chat_message, stream_chat_message

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/chat", tags=["Chat"])


def _resolve_chat_restaurant_id(app_scope, requested_restaurant_id):
    """Force a scoped app's chat turns onto its own restaurant.

    The assistant answers from live menu rows, so leaving this to the client
    would let a scoped app be talked into recommending dishes it does not sell.
    A request naming a different restaurant is refused outright.
    """

    scoped_restaurant_id = app_scope.restaurant_filter_id
    if scoped_restaurant_id is None:
        return requested_restaurant_id

    if requested_restaurant_id is not None:
        ensure_restaurant_writable(app_scope, requested_restaurant_id)
    return scoped_restaurant_id



def _resolve_principal(
    current_user: User | None,
    session_id: uuid.UUID | None,
) -> tuple[ChatPrincipal, uuid.UUID | None]:
    """Signed-in customer, or a guest pinned to this conversation.

    The session id is resolved HERE for guests rather than deeper in the RAG
    pipeline, because a guest's identity is derived from it: let the pipeline
    mint its own and turn 1 writes its memory under a key turn 2 never reads.
    Signed-in users keep the existing behaviour, None and all.
    """

    if current_user is not None:
        return current_user, session_id
    resolved = session_id or uuid.uuid4()
    return guest_principal_for_session(resolved), resolved


@router.post("/message", response_model=ChatMessageResponse)
def send_chat_message(
    payload: ChatMessageRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User | None, Depends(get_current_user_optional)],
    app_scope: AppScopeDep,
) -> ChatMessageResponse:
    started_at = perf_counter()
    scoped_restaurant_id = _resolve_chat_restaurant_id(app_scope, payload.restaurant_id)
    principal, session_id = _resolve_principal(current_user, payload.session_id)
    logger.info(
        "Chat API request: user_id=%s restaurant_id=%s restaurant_location_id=%s session_id=%s message=%s",
        principal.id,
        scoped_restaurant_id,
        payload.restaurant_location_id,
        payload.session_id,
        payload.message,
    )
    response = handle_chat_message(
        db,
        user=principal,
        message=payload.message,
        session_id=session_id,
        restaurant_id=scoped_restaurant_id,
        restaurant_location_id=payload.restaurant_location_id,
        # Honoured only for a guest; ignored outright for an authenticated user.
        # See `resolve_chat_preferences`.
        guest_preferences=(
            payload.guest_preferences.model_dump() if payload.guest_preferences else None
        ),
        cart=payload.cart,
    )
    logger.info(
        "Chat API response: user_id=%s session_id=%s suggestions=%d total=%.2fms",
        principal.id,
        response.session_id,
        len(response.suggestions),
        (perf_counter() - started_at) * 1000,
    )
    return response


def _releasing(frames: Iterator[str], db: Session) -> Iterator[str]:
    """Stream frames, and hand the connection back however the stream ends.

    `StreamingResponse` closes its iterator on a client disconnect as well as
    on a normal finish, and closing a generator raises `GeneratorExit` at the
    yield it is parked on — so this `finally` runs in both cases. Without it
    an abandoned stream leaks its pooled connection until the worker dies.
    Closing a Session is safe and idempotent: `get_db`'s own cleanup closes it
    again, and SQLAlchemy reopens on next use.
    """

    try:
        yield from frames
    finally:
        db.close()


@router.post("/message/stream")
def stream_chat_message_route(
    payload: ChatMessageRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User | None, Depends(get_current_user_optional)],
    app_scope: AppScopeDep,
) -> StreamingResponse:
    scoped_restaurant_id = _resolve_chat_restaurant_id(app_scope, payload.restaurant_id)
    principal, session_id = _resolve_principal(current_user, payload.session_id)
    logger.info(
        "Chat stream request: user_id=%s restaurant_id=%s restaurant_location_id=%s session_id=%s message=%s",
        principal.id,
        scoped_restaurant_id,
        payload.restaurant_location_id,
        payload.session_id,
        payload.message,
    )
    return StreamingResponse(
        _releasing(
            stream_chat_message(
                db,
                user=principal,
                message=payload.message,
                session_id=session_id,
                restaurant_id=scoped_restaurant_id,
                restaurant_location_id=payload.restaurant_location_id,
                # The surface the customer app actually uses. Wiring only the
                # non-streaming endpoint would make this work in every curl and in
                # no browser.
                guest_preferences=(
                    payload.guest_preferences.model_dump() if payload.guest_preferences else None
                ),
                # The ordering agent reasons about THIS cart, and the cart lives in
                # the browser — there is no server-side cart to read it from. Sent
                # on the streaming route as well as the non-streaming one for the
                # same reason `guest_preferences` is: this is the route the web
                # concierge and mobile actually call.
                cart=payload.cart,
                previous_reply=payload.previous_reply,
                recent_history=[line.model_dump() for line in payload.recent_history],
            ),
            db,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/history", response_model=list[ChatHistoryItemResponse])
def list_chat_history(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    app_scope: AppScopeDep,
    session_id: uuid.UUID | None = Query(default=None),
    # Capped rather than unbounded: a thread is read from the bottom, and a
    # customer who has been chatting for months does not need all of it shipped
    # to render the part they are looking at.
    limit: int = Query(default=50, ge=1, le=200),
) -> list[ChatHistoryItemResponse]:
    return get_chat_history(
        db,
        current_user,
        session_id=session_id,
        restaurant_id=app_scope.restaurant_filter_id,
        limit=limit,
    )


@router.delete("/history", response_model=ChatClearResponse)
def delete_chat_history(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    app_scope: AppScopeDep,
    session_id: uuid.UUID | None = Query(default=None),
) -> ChatClearResponse:
    deleted_count = clear_chat_history(
        db,
        user=current_user,
        session_id=session_id,
        restaurant_id=app_scope.restaurant_filter_id,
    )
    return ChatClearResponse(
        deleted_count=deleted_count,
        cleared_session_id=session_id,
    )
