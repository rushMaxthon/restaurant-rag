from __future__ import annotations

import logging
import uuid
from time import perf_counter
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.deps import AppScopeDep, ensure_restaurant_writable
from app.config.database import get_db
from app.models.user import User
from app.schemas.chat import ChatClearResponse, ChatHistoryItemResponse, ChatMessageRequest, ChatMessageResponse
from app.services.auth import get_current_user
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



@router.post("/message", response_model=ChatMessageResponse)
def send_chat_message(
    payload: ChatMessageRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    app_scope: AppScopeDep,
) -> ChatMessageResponse:
    started_at = perf_counter()
    scoped_restaurant_id = _resolve_chat_restaurant_id(app_scope, payload.restaurant_id)
    logger.info(
        "Chat API request: user_id=%s restaurant_id=%s restaurant_location_id=%s session_id=%s message=%s",
        current_user.id,
        scoped_restaurant_id,
        payload.restaurant_location_id,
        payload.session_id,
        payload.message,
    )
    response = handle_chat_message(
        db,
        user=current_user,
        message=payload.message,
        session_id=payload.session_id,
        restaurant_id=scoped_restaurant_id,
        restaurant_location_id=payload.restaurant_location_id,
    )
    logger.info(
        "Chat API response: user_id=%s session_id=%s suggestions=%d total=%.2fms",
        current_user.id,
        response.session_id,
        len(response.suggestions),
        (perf_counter() - started_at) * 1000,
    )
    return response


@router.post("/message/stream")
def stream_chat_message_route(
    payload: ChatMessageRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    app_scope: AppScopeDep,
) -> StreamingResponse:
    scoped_restaurant_id = _resolve_chat_restaurant_id(app_scope, payload.restaurant_id)
    logger.info(
        "Chat stream request: user_id=%s restaurant_id=%s restaurant_location_id=%s session_id=%s message=%s",
        current_user.id,
        scoped_restaurant_id,
        payload.restaurant_location_id,
        payload.session_id,
        payload.message,
    )
    return StreamingResponse(
        stream_chat_message(
            db,
            user=current_user,
            message=payload.message,
            session_id=payload.session_id,
            restaurant_id=scoped_restaurant_id,
            restaurant_location_id=payload.restaurant_location_id,
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
) -> list[ChatHistoryItemResponse]:
    return get_chat_history(
        db,
        current_user,
        session_id=session_id,
        restaurant_id=app_scope.restaurant_filter_id,
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
