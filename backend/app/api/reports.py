from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.models.enums import OrderStatus
from app.models.user import User
from app.schemas.report import ReportsResponse
from app.services.auth import get_current_user
from app.services.reports import ReportsFilters, get_reports_snapshot

router = APIRouter(prefix="/reports", tags=["Reports"])


@router.get("", response_model=ReportsResponse)
def get_reports(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    restaurant_id: uuid.UUID | None = Query(default=None),
    cuisine_type: str | None = Query(default=None),
    category: str | None = Query(default=None),
    order_status: OrderStatus | None = Query(default=None),
) -> ReportsResponse:
    filters = ReportsFilters(
        date_from=date_from,
        date_to=date_to,
        restaurant_id=restaurant_id,
        cuisine_type=cuisine_type,
        category=category,
        order_status=order_status,
    )
    return get_reports_snapshot(
        db,
        current_user=current_user,
        filters=filters,
    )
