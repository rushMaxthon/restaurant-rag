"""Storefront traffic: the heartbeat the storefront sends, and the reports.

`services/traffic.py` holds every rule; this file decides who may call what.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import AppScopeDep
from app.config import get_settings
from app.config.database import get_db
from app.models.enums import UserRole
from app.models.user import User
from app.schemas.traffic import (
    TrafficDay,
    TrafficOverviewResponse,
    TrafficOverviewRow,
    TrafficSummaryResponse,
    TrafficToday,
)
from app.services import traffic
from app.services.rate_limit import client_ip as rate_limit_client_ip
from app.services.auth import get_current_user, get_current_user_optional, require_admin
from app.services.insights.scope import resolve_insights_scope

router = APIRouter(prefix="/traffic", tags=["Traffic"])


class TrafficBeat(BaseModel):
    #: The anonymous id the storefront keeps in the browser.
    visitor_id: uuid.UUID


def _client_address(request: Request) -> str | None:
    # The address Render's proxy recorded, not the first X-Forwarded-For entry,
    # which the caller writes and could rotate to dodge the new-visitor cap.
    return rate_limit_client_ip(request)


@router.post("/beat", status_code=status.HTTP_204_NO_CONTENT)
def beat(
    payload: TrafficBeat,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    app_scope: AppScopeDep,
    current_user: Annotated[User | None, Depends(get_current_user_optional)],
) -> Response:
    """A storefront page is open and on screen. Always 204, counted or not.

    The answer never says whether the beat was counted, so a script learns
    nothing from it about which of its tricks worked.
    """

    done = Response(status_code=status.HTTP_204_NO_CONTENT)
    restaurant_id = app_scope.restaurant_filter_id
    if restaurant_id is None:
        # The marketplace browses every restaurant; it has no one to count for.
        return done
    agent = request.headers.get("user-agent")
    if traffic.is_bot(agent):
        return done
    host = request.headers.get("x-forwarded-host") or request.headers.get("host")
    if traffic.is_local_host(host) and not get_settings().traffic_count_local_hosts:
        return done

    now = datetime.now(UTC)
    if not traffic.known_today(db, restaurant_id, payload.visitor_id, now) and not traffic.allow_new_visitor(
        _client_address(request), restaurant_id, now
    ):
        return done
    # Only a customer's account says who ordered; a member of staff looking
    # at the storefront while signed in is still a visitor, but not a buyer.
    user_id = current_user.id if current_user is not None and current_user.role == UserRole.CUSTOMER else None
    traffic.record_beat(
        db,
        restaurant_id=restaurant_id,
        visitor_id=payload.visitor_id,
        user_id=user_id,
        user_agent=agent,
        now=now,
    )
    return done


@router.get("/summary", response_model=TrafficSummaryResponse)
def get_summary(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    restaurant_id: uuid.UUID | None = Query(default=None),
) -> TrafficSummaryResponse:
    """One restaurant's traffic. An owner gets their own; an admin names one."""

    scope = resolve_insights_scope(db, current_user=current_user, restaurant_id=restaurant_id)
    result = traffic.summary(db, scope.restaurant_id)
    return TrafficSummaryResponse(
        restaurant_id=result.restaurant_id,
        online_now=result.online_now,
        today=TrafficToday(**result.today.__dict__),
        daily=[TrafficDay(day=row.day, visitors=row.visitors, ordered=row.ordered) for row in result.daily],
        hours=result.hours,
        generated_at=result.generated_at,
    )


@router.get("/overview", response_model=TrafficOverviewResponse)
def get_overview(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_admin)],
) -> TrafficOverviewResponse:
    """Every restaurant's traffic at once. The platform admin only."""

    rows = traffic.overview(db)
    return TrafficOverviewResponse(
        generated_at=datetime.now(UTC),
        restaurants=[TrafficOverviewRow(**row.__dict__) for row in rows],
    )
