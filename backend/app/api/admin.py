from __future__ import annotations

import uuid
import logging
import re
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.models.chat_history import ChatHistory
from app.models.menu_item import MenuItem
from app.config.database import get_db
from app.models.order import Order
from app.models.restaurant import Restaurant
from app.models.restaurant_location import RestaurantLocation
from app.models.user import User
from app.models.app_client import AppClient
from app.models.enums import OrderStatus, UserRole
from app.schemas.admin import (
    RestaurantDemoUpdate,
    PlatformCheck,
    PlatformIssue,
    PlatformRestaurantToday,
    PlatformWatchResponse,
    AdminCommissionReport,
    AdminCommissionRow,
    AdminUserResponse,
    AdminUserStats,
    AdminUserUpdate,
    AdminAILogResponse,
    AdminAIOfferGenerationRequest,
    AdminAIOfferGenerationStatusResponse,
    AdminAIOfferGenerationTriggerResponse,
    AdminDashboardStats,
    AdminMenuItemResponse,
    RestaurantApprovalUpdate,
    UserStatusUpdate,
)
from app.schemas.auth import UserResponse
from app.schemas.delivery_pricing import (
    DeliveryPricingResponse,
    DeliveryPricingUpdate,
    DeliverySlab,
)
from app.schemas.insights import InsightGenerationTriggerResponse
from app.schemas.restaurant import (
    AdminRestaurantUpdate,
    RestaurantDetailResponse,
    RestaurantResponse,
)
from app.services.app_clients import get_app_client_for_restaurant
from app.services.auth import (
    get_current_user,
    normalize_phone_number,
    require_admin,
    resolve_owner_restaurant_id,
)
from app.config import get_settings
from app.config.celery import celery_app
from app.services.realtime.outbox import queue_session_revoked
from app.services.bestsellers import (
    get_menu_item_featured_flag,
    get_menu_item_recent_valid_order_count,
    hydrate_dynamic_bestseller_flags,
    hydrate_recent_valid_order_counts,
    is_menu_item_bestseller,
)
from app.services.menu_item_metadata import is_menu_item_new, resolve_menu_item_launch_timestamp
from app.services.personalized_offers import invalidate_all_personalized_offer_caches
from app.tasks.ai_offers import generate_ai_offers_task
from app.tasks.insights import generate_owner_briefings_task

router = APIRouter(prefix="/admin", tags=["Admin"])
settings = get_settings()
logger = logging.getLogger(__name__)


def _slugify(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    return normalized or "restaurant"


def _generate_unique_slug(db: Session, restaurant_name: str, *, exclude_restaurant_id: uuid.UUID | None = None) -> str:
    base_slug = _slugify(restaurant_name)
    candidate = base_slug
    suffix = 2

    while True:
        query = select(Restaurant.id).where(Restaurant.slug == candidate)
        if exclude_restaurant_id is not None:
            query = query.where(Restaurant.id != exclude_restaurant_id)
        if db.scalar(query) is None:
            return candidate
        candidate = f"{base_slug}-{suffix}"
        suffix += 1


@router.get("/platform-watch", response_model=PlatformWatchResponse)
def get_platform_watch(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_admin)],
) -> PlatformWatchResponse:
    """System health, what needs attention, and today per restaurant.

    Admin only: it reads every restaurant at once. Read-only - nothing here
    changes anything.
    """

    from dataclasses import asdict

    from app.services import platform_watch

    watch = platform_watch.build(db)
    return PlatformWatchResponse(
        generated_at=watch.generated_at,
        checks=[PlatformCheck(**asdict(check)) for check in watch.checks],
        issues=[PlatformIssue(**asdict(issue)) for issue in watch.issues],
        restaurants=[PlatformRestaurantToday(**asdict(row)) for row in watch.restaurants],
    )


def _delivery_pricing_response(db: Session, pricing) -> DeliveryPricingResponse:
    updated_by_name = None
    if pricing.updated_by is not None:
        editor = db.get(User, pricing.updated_by)
        updated_by_name = (editor.full_name or editor.email) if editor is not None else None
    return DeliveryPricingResponse(
        slabs=[DeliverySlab(up_to_km=limit, fee=fee) for limit, fee in pricing.slabs],
        max_distance_km=pricing.max_distance_km,
        gst_percent=pricing.gst_percent,
        saved=pricing.saved,
        updated_at=pricing.updated_at,
        updated_by_user_id=pricing.updated_by,
        updated_by_name=updated_by_name,
    )


@router.get("/delivery-pricing", response_model=DeliveryPricingResponse)
def get_delivery_pricing(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_admin)],
) -> DeliveryPricingResponse:
    """The delivery slabs every restaurant charges, the limit, and the GST.

    Admin only. An owner is never shown it: beside what a courier charges it
    is the platform's delivery margin.
    """

    from app.services.delivery import slabs

    return _delivery_pricing_response(db, slabs.load_pricing(db))


@router.put("/delivery-pricing", response_model=DeliveryPricingResponse)
def put_delivery_pricing(
    payload: DeliveryPricingUpdate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_admin)],
) -> DeliveryPricingResponse:
    """Change the delivery pricing for every restaurant at once.

    Takes effect on the next quote: nothing is cached. A list with a gap, a
    backwards step or no open-ended last slab is refused with a 422 and the
    saved pricing is left as it was (`slabs.validate_update`).
    """

    from app.services.delivery import slabs

    return _delivery_pricing_response(db, slabs.save_pricing(db, current_user, payload))


@router.get("/commission", response_model=AdminCommissionReport)
def get_commission_report(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_admin)],
    days: int = Query(default=30, ge=1, le=366),
) -> AdminCommissionReport:
    """What the platform earned from each restaurant in the last `days`.

    Admin only. The commission is the platform's own figure - an owner is not
    told the rate (`menu_pricing.sees_commission_rate`), and a report of what
    it added up to would tell them by division.
    """

    from app.services import commission
    from app.services.orders import normalize_stored_currency

    since = datetime.now(UTC) - timedelta(days=days)
    rows = commission.summarise(db, since=since)
    currencies = {
        restaurant_id: normalize_stored_currency(code)
        for restaurant_id, code in db.execute(
            select(Restaurant.id, Restaurant.currency).where(
                Restaurant.id.in_([row.restaurant_id for row in rows])
            )
        )
    }
    return AdminCommissionReport(
        days=days,
        since=since,
        counted_from=commission.first_recorded_at(db),
        restaurants=[
            AdminCommissionRow(
                restaurant_id=row.restaurant_id,
                restaurant_name=row.restaurant_name,
                orders=row.orders,
                sales=row.sales,
                commission=row.commission,
                currency=currencies.get(row.restaurant_id, ""),
            )
            for row in rows
        ],
    )


@router.get("/dashboard", response_model=AdminDashboardStats)
def get_dashboard_stats(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_admin)],
) -> AdminDashboardStats:
    """The platform's headline numbers, over the real restaurants only.

    Revenue used to be the sum of every order ever created: abandoned
    checkouts, cancelled orders, and the demo kitchens' Canadian dollars added
    to Indian rupees. It is now what was sold - neither unpaid nor cancelled,
    the same rule Platform watch and the commission report use - and an
    abandoned checkout is not counted as an order at all.
    """

    real = Restaurant.is_demo.is_(False)
    total_orders = db.scalar(
        select(func.count(Order.id))
        .join(Restaurant, Restaurant.id == Order.restaurant_id)
        .where(real, Order.status != OrderStatus.PAYMENT_PENDING)
    ) or 0
    total_revenue = db.scalar(
        select(func.coalesce(func.sum(Order.total_amount), 0))
        .join(Restaurant, Restaurant.id == Order.restaurant_id)
        .where(real, Order.status.not_in((OrderStatus.PAYMENT_PENDING, OrderStatus.CANCELLED)))
    ) or 0
    total_restaurants = db.scalar(select(func.count(Restaurant.id)).where(real)) or 0
    total_users = db.scalar(select(func.count(User.id))) or 0
    currencies = set(db.scalars(select(Restaurant.currency).where(real).distinct()))
    return AdminDashboardStats(
        total_orders=int(total_orders),
        total_revenue=float(total_revenue),
        total_restaurants=int(total_restaurants),
        total_users=int(total_users),
        currency=next(iter(currencies)) if len(currencies) == 1 else None,
    )


@router.post("/offers/generate-ai", response_model=AdminAIOfferGenerationTriggerResponse)
def trigger_ai_offer_generation(
    payload: AdminAIOfferGenerationRequest,
    current_user: Annotated[User, Depends(require_admin)],
) -> AdminAIOfferGenerationTriggerResponse:
    task_kwargs = {
        "user_limit": payload.user_limit,
        "batch_size": payload.batch_size,
        "force_refresh": payload.force_refresh,
        "allow_disabled": True,
    }
    if not payload.queue_only:
        try:
            result = generate_ai_offers_task.apply(kwargs=task_kwargs)
        except Exception as error:  # pragma: no cover - defensive execution failure path
            logger.exception("Admin AI offer generation inline run failed admin_user_id=%s", current_user.id)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Unable to run AI offer generation right now. The cause is in the server log.",
            ) from error
        logger.info(
            "Admin AI offer generation completed inline admin_user_id=%s task_id=%s user_limit=%s batch_size=%s force_refresh=%s successful=%s",
            current_user.id,
            result.id,
            payload.user_limit,
            payload.batch_size,
            payload.force_refresh,
            result.successful(),
        )
        if result.successful():
            return AdminAIOfferGenerationTriggerResponse(
                task_id=str(result.id),
                queued=False,
                status=str(result.state or "SUCCESS").upper(),
                message="AI offer generation completed.",
                ready=True,
                successful=True,
                summary=result.result if isinstance(result.result, dict) else None,
            )
        return AdminAIOfferGenerationTriggerResponse(
            task_id=str(result.id),
            queued=False,
            status=str(result.state or "FAILURE").upper(),
            message="AI offer generation failed.",
            ready=True,
            successful=False,
            error=str(result.result or "AI offer generation failed."),
        )

    try:
        task = generate_ai_offers_task.delay(**task_kwargs)
    except Exception as error:  # pragma: no cover - defensive queue failure path
        logger.exception("Admin AI offer generation queue failed admin_user_id=%s", current_user.id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to queue AI offer generation right now. The cause is in the server log.",
        ) from error

    logger.info(
        "Admin AI offer generation queued admin_user_id=%s task_id=%s user_limit=%s batch_size=%s force_refresh=%s",
        current_user.id,
        task.id,
        payload.user_limit,
        payload.batch_size,
        payload.force_refresh,
    )

    return AdminAIOfferGenerationTriggerResponse(
        task_id=str(task.id),
        queued=True,
        status="QUEUED",
        message="AI offer generation has been queued.",
        ready=False,
    )


@router.post("/insights/generate", response_model=InsightGenerationTriggerResponse)
def trigger_owner_insight_generation(
    current_user: Annotated[User, Depends(require_admin)],
    restaurant_limit: int | None = Query(default=None, ge=1),
    queue_only: bool = Query(default=True),
) -> InsightGenerationTriggerResponse:
    """Run owner briefing generation on demand.

    `allow_disabled` is always set, so a run can be exercised before the feature
    flag is switched on.
    """

    task_kwargs = {"restaurant_limit": restaurant_limit, "allow_disabled": True}

    if not queue_only:
        try:
            result = generate_owner_briefings_task.apply(kwargs=task_kwargs)
        except Exception as error:  # pragma: no cover - defensive execution failure path
            logger.exception(
                "Admin owner insight generation inline run failed admin_user_id=%s",
                current_user.id,
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Unable to run insight generation right now. The cause is in the server log.",
            ) from error
        return InsightGenerationTriggerResponse(
            task_id=str(result.id),
            queued=False,
            detail=(
                "Insight generation completed."
                if result.successful()
                else f"Insight generation failed: {result.result}"
            ),
        )

    try:
        task = generate_owner_briefings_task.delay(**task_kwargs)
    except Exception as error:  # pragma: no cover - defensive queue failure path
        logger.exception(
            "Admin owner insight generation queue failed admin_user_id=%s", current_user.id
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to queue insight generation right now. The cause is in the server log.",
        ) from error

    logger.info(
        "Admin owner insight generation queued admin_user_id=%s task_id=%s restaurant_limit=%s",
        current_user.id,
        task.id,
        restaurant_limit,
    )
    return InsightGenerationTriggerResponse(
        task_id=str(task.id),
        queued=True,
        detail="Insight generation has been queued.",
    )


@router.get("/offers/generate-ai/{task_id}", response_model=AdminAIOfferGenerationStatusResponse)
def get_ai_offer_generation_status(
    task_id: str,
    current_user: Annotated[User, Depends(require_admin)],
) -> AdminAIOfferGenerationStatusResponse:
    result = celery_app.AsyncResult(task_id)
    task_state = str(result.state or "PENDING").upper()
    logger.info(
        "Admin AI offer generation status requested admin_user_id=%s task_id=%s state=%s ready=%s successful=%s",
        current_user.id,
        task_id,
        task_state,
        result.ready(),
        result.successful() if result.ready() else None,
    )
    response = AdminAIOfferGenerationStatusResponse(
        task_id=task_id,
        status=task_state,
        ready=result.ready(),
        successful=result.successful() if result.ready() else None,
    )
    if not result.ready():
        return response
    if result.successful():
        response.summary = result.result if isinstance(result.result, dict) else None
        return response
    response.error = str(result.result or "AI offer generation failed.")
    return response


@router.get("/restaurants", response_model=list[RestaurantResponse])
def list_all_restaurants(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_admin)],
    include_demo: bool = Query(default=False),
) -> list[RestaurantResponse]:
    query = select(Restaurant).order_by(Restaurant.created_at.desc())
    if not include_demo:
        query = query.where(Restaurant.is_demo.is_(False))
    restaurants = db.scalars(query).all()
    return [RestaurantResponse.model_validate(restaurant) for restaurant in restaurants]


@router.patch("/restaurants/{restaurant_id}/demo", response_model=RestaurantResponse)
def update_restaurant_demo(
    restaurant_id: uuid.UUID,
    payload: RestaurantDemoUpdate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_admin)],
) -> RestaurantResponse:
    """Mark a restaurant as seeded demo data, or as real again."""

    restaurant = db.get(Restaurant, restaurant_id)
    if restaurant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Restaurant not found")
    restaurant.is_demo = payload.is_demo
    db.commit()
    db.refresh(restaurant)
    return RestaurantResponse.model_validate(restaurant)


@router.patch("/restaurants/{restaurant_id}/approval", response_model=RestaurantResponse)
def update_restaurant_approval(
    restaurant_id: uuid.UUID,
    payload: RestaurantApprovalUpdate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_admin)],
) -> RestaurantResponse:
    restaurant = db.get(Restaurant, restaurant_id)
    if restaurant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Restaurant not found")

    restaurant.is_approved = payload.is_approved
    db.add(restaurant)
    db.commit()
    db.refresh(restaurant)
    invalidate_all_personalized_offer_caches()
    return RestaurantResponse.model_validate(restaurant)


@router.get("/restaurants/{restaurant_id}", response_model=RestaurantDetailResponse)
def get_restaurant(
    restaurant_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_admin)],
) -> RestaurantDetailResponse:
    restaurant = db.get(Restaurant, restaurant_id)
    if restaurant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Restaurant not found")
    return RestaurantDetailResponse.model_validate(restaurant)


@router.patch("/restaurants/{restaurant_id}", response_model=RestaurantResponse)
def update_restaurant(
    restaurant_id: uuid.UUID,
    payload: AdminRestaurantUpdate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_admin)],
) -> RestaurantResponse:
    restaurant = db.get(Restaurant, restaurant_id)
    if restaurant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Restaurant not found")

    restaurant.name = payload.name
    restaurant.slug = _generate_unique_slug(db, payload.name, exclude_restaurant_id=restaurant.id)
    restaurant.description = payload.description
    restaurant.cuisine_type = payload.cuisine_type
    restaurant.address_line_1 = payload.address_line_1
    restaurant.address_line_2 = payload.address_line_2
    restaurant.city = payload.city
    restaurant.state = payload.state
    restaurant.country = payload.country
    restaurant.postal_code = payload.postal_code
    restaurant.phone_number = payload.phone_number
    restaurant.minimum_order_amount = payload.minimum_order_amount
    restaurant.delivery_fee = payload.delivery_fee
    restaurant.logo_image_url = payload.logo_image_url
    restaurant.cover_image_url = payload.cover_image_url
    restaurant.is_open = payload.is_open

    db.add(restaurant)
    db.commit()
    db.refresh(restaurant)
    invalidate_all_personalized_offer_caches()
    return RestaurantResponse.model_validate(restaurant)


@router.delete(
    "/restaurants/{restaurant_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def delete_restaurant(
    restaurant_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_admin)],
) -> Response:
    restaurant = db.get(Restaurant, restaurant_id)
    if restaurant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Restaurant not found")

    restaurant.is_active = False
    restaurant.is_open = False
    db.add(restaurant)
    db.commit()
    invalidate_all_personalized_offer_caches()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _serialize_admin_user(user: User) -> AdminUserResponse:
    """Adds the owning app to a user row. Read-only: nothing here scopes access."""

    app_client = user.app_client
    if app_client is None:
        return AdminUserResponse.model_validate(user)

    restaurant = app_client.restaurant
    return AdminUserResponse(
        **UserResponse.model_validate(user).model_dump(),
        app_client_id=app_client.id,
        app_key=app_client.key,
        app_mode=app_client.app_mode,
        app_label=app_client.display_name,
        restaurant_id=restaurant.id if restaurant is not None else None,
        restaurant_name=restaurant.name if restaurant is not None else None,
    )


def _admin_user_query():
    return select(User).options(
        selectinload(User.app_client).selectinload(AppClient.restaurant)
    )


#: A page of the Users list when the caller does not say (2026-10-07
#: security review: the list used to be every account in one response).
USERS_DEFAULT_LIMIT = 50


def _scoped_users_query(db: Session, current_user: User):
    """The accounts this caller may list, or None when there are none.

    Admins see every account; owners only their own app's customers - never
    marketplace customers, other restaurants' customers, or platform staff.
    Read-only: this narrows the listing, it does not change how anyone is
    authenticated or scoped.
    """

    if current_user.role == UserRole.ADMIN:
        return select(User)
    if current_user.role == UserRole.OWNER:
        owner_restaurant_id = resolve_owner_restaurant_id(db, current_user)
        app_client = get_app_client_for_restaurant(db, restaurant_id=owner_restaurant_id)
        if app_client is None:
            # No branded app yet, so no customers of its own to show.
            return None
        return select(User).where(User.role == UserRole.CUSTOMER, User.app_client_id == app_client.id)
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="You do not have permission to access this resource",
    )


def _escape_like(value: str) -> str:
    """Make `%` and `_` match themselves in an ILIKE (escape character: backslash)."""

    return value.replace("\\", r"\\").replace("%", r"\%").replace("_", r"\_")


@router.get("/users/stats", response_model=AdminUserStats)
def user_stats(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> AdminUserStats:
    """How many accounts per role, and how many of them are active.

    For the tiles above the Users list, which describe everybody the caller
    may see rather than the page on screen. Declared before
    `/users/{user_id}`, or "stats" would be read as an id.
    """

    query = _scoped_users_query(db, current_user)
    counts: dict[str, dict[str, int]] = {}
    if query is not None:
        scoped = query.subquery()
        rows = db.execute(
            select(scoped.c.role, func.count(), func.count().filter(scoped.c.is_active.is_(True))).group_by(
                scoped.c.role
            )
        ).all()
        for role, total, active in rows:
            counts[role.value if hasattr(role, "value") else str(role)] = {"total": int(total), "active": int(active)}
    empty = {"total": 0, "active": 0}
    return AdminUserStats(
        all={
            "total": sum(c["total"] for c in counts.values()),
            "active": sum(c["active"] for c in counts.values()),
        },
        ADMIN=counts.get("ADMIN", empty),
        OWNER=counts.get("OWNER", empty),
        KITCHEN=counts.get("KITCHEN", empty),
        CUSTOMER=counts.get("CUSTOMER", empty),
    )


@router.get("/users", response_model=list[AdminUserResponse])
def list_users(
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    search: str | None = Query(default=None, max_length=120),
    role: UserRole | None = Query(default=None),
    status_filter: Literal["ACTIVE", "INACTIVE"] | None = Query(default=None, alias="status"),
    limit: int = Query(default=USERS_DEFAULT_LIMIT, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[AdminUserResponse]:
    """One page of the accounts the caller may see, newest first.

    Filtered and paged here, with the full count in `X-Total-Count` - the
    contract `GET /orders` already has. It used to return every account at
    once for the page to filter (2026-10-07 security review): one stolen
    owner token, one request, every customer's name, email and phone.
    """

    query = _scoped_users_query(db, current_user)
    if query is None:
        response.headers["X-Total-Count"] = "0"
        return []
    if search and search.strip():
        pattern = f"%{_escape_like(search.strip())}%"
        query = query.where(
            or_(
                User.full_name.ilike(pattern, escape="\\"),
                User.email.ilike(pattern, escape="\\"),
                User.phone_number.ilike(pattern, escape="\\"),
            )
        )
    if role is not None:
        query = query.where(User.role == role)
    if status_filter is not None:
        query = query.where(User.is_active.is_(status_filter == "ACTIVE"))

    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    response.headers["X-Total-Count"] = str(total)
    page = query.options(selectinload(User.app_client).selectinload(AppClient.restaurant))
    users = db.scalars(page.order_by(User.created_at.desc(), User.id).limit(limit).offset(offset)).all()
    return [_serialize_admin_user(user) for user in users]


def _get_manageable_user(db: Session, user_id: uuid.UUID, current_user: User) -> User:
    """Load a user the caller is allowed to view or edit.

    Admins reach any account. Owners reach only customers of their own app
    client, so a customer from Marketplace or another restaurant is invisible
    to them - reported as 404 rather than 403 so the endpoint cannot be used
    to discover which user ids exist.
    """

    user = db.scalar(_admin_user_query().where(User.id == user_id))
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if current_user.role == UserRole.ADMIN:
        return user

    if current_user.role != UserRole.OWNER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to access this resource",
        )

    owner_restaurant_id = resolve_owner_restaurant_id(db, current_user)
    app_client = get_app_client_for_restaurant(db, restaurant_id=owner_restaurant_id)
    if (
        app_client is None
        or user.role != UserRole.CUSTOMER
        or user.app_client_id != app_client.id
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    return user


@router.get("/users/{user_id}", response_model=AdminUserResponse)
def get_user(
    user_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> AdminUserResponse:
    return _serialize_admin_user(_get_manageable_user(db, user_id, current_user))


@router.patch("/users/{user_id}/details", response_model=AdminUserResponse)
def update_user_details(
    user_id: uuid.UUID,
    payload: AdminUserUpdate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> AdminUserResponse:
    """Update a customer's profile details.

    Scoped identically to the listing: an owner can only edit customers of
    their own app. Account status lives on the sibling endpoint and stays
    admin-only.
    """

    user = _get_manageable_user(db, user_id, current_user)

    # The phone is a login - password sign-in accepts it and phone sign-in
    # matches on it - so an owner who could rewrite it could make a customer's
    # account answer to their own number (2026-10-07 security review). Owners
    # may correct a name or an address; the number is the customer's, or the
    # platform admin's, to change.
    new_phone = normalize_phone_number(payload.phone_number)
    if current_user.role != UserRole.ADMIN and new_phone != normalize_phone_number(user.phone_number):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the customer, or the platform admin, can change a phone number: it is how they sign in.",
        )

    user.full_name = payload.full_name
    user.phone_number = new_phone
    user.default_address = payload.default_address
    db.add(user)

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        constraint = getattr(getattr(exc.orig, "diag", None), "constraint_name", "") or ""
        if constraint in {
            "uq_users_app_client_id_phone_number_customer",
            "uq_users_phone_number_platform",
        }:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="That phone number is already in use",
            ) from exc
        logger.exception("User detail update failed constraint=%s", constraint)
        raise

    refreshed = db.scalar(_admin_user_query().where(User.id == user_id))
    return _serialize_admin_user(refreshed if refreshed is not None else user)


@router.patch("/users/{user_id}", response_model=AdminUserResponse)
def update_user_status(
    user_id: uuid.UUID,
    payload: UserStatusUpdate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_admin)],
) -> AdminUserResponse:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if user.id == current_user.id and not payload.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Admin cannot deactivate themselves")

    user.is_active = payload.is_active
    if not payload.is_active:
        # Deactivating has to END the sessions already issued, not just stop
        # new ones. Without this the account keeps working until its token
        # expires on its own — which for a KITCHEN account means the tablet on
        # the kitchen wall carries on taking orders after it was switched off.
        # `POST /kitchen-staff`'s own deactivate path has always done this;
        # this route is the other way to reach the same row.
        user.token_version += 1
        # And the sockets it has open, once this commits.
        queue_session_revoked(db, user_id=user.id)
    db.add(user)
    db.commit()

    # Re-read with the app client loaded so the row keeps its app label after
    # a status toggle.
    refreshed = db.scalar(_admin_user_query().where(User.id == user_id))
    return _serialize_admin_user(refreshed if refreshed is not None else user)


@router.get("/menu-items", response_model=list[AdminMenuItemResponse])
def list_admin_menu_items(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_admin)],
) -> list[AdminMenuItemResponse]:
    rows = db.execute(
        select(MenuItem, Restaurant, RestaurantLocation)
        .join(Restaurant, MenuItem.restaurant_id == Restaurant.id)
        .join(RestaurantLocation, MenuItem.restaurant_location_id == RestaurantLocation.id)
        .order_by(MenuItem.created_at.desc())
    ).all()
    hydrate_dynamic_bestseller_flags(db, [menu_item for menu_item, _, _ in rows])
    hydrate_recent_valid_order_counts(db, [menu_item for menu_item, _, _ in rows])

    return [
        AdminMenuItemResponse(
            id=menu_item.id,
            restaurant_id=restaurant.id,
            restaurant_location_id=location.id,
            restaurant_name=restaurant.name,
            restaurant_location_name=location.branch_name,
            restaurant_city=restaurant.city,
            name=menu_item.name,
            category=menu_item.category,
            cuisine_type=menu_item.cuisine_type,
            description=menu_item.description,
            price=menu_item.price,
            is_veg=menu_item.is_veg,
            is_available=menu_item.is_available,
            stock_quantity=menu_item.stock_quantity,
            out_of_stock=menu_item.out_of_stock,
            is_bestseller=is_menu_item_bestseller(menu_item),
            is_featured=get_menu_item_featured_flag(menu_item),
            image_url=menu_item.image_url,
            recent_valid_order_count=get_menu_item_recent_valid_order_count(menu_item),
            recent_valid_order_window_days=settings.bestseller_window_days,
            popularity_score=menu_item.popularity_score,
            rating=menu_item.rating,
            rating_count=menu_item.rating_count,
            launched_at=resolve_menu_item_launch_timestamp(menu_item),
            created_at=menu_item.created_at,
            updated_at=menu_item.updated_at,
            is_new_launch=menu_item.is_new_launch,
            is_new=is_menu_item_new(menu_item),
        )
        for menu_item, restaurant, location in rows
    ]


@router.get("/ai-logs", response_model=list[AdminAILogResponse])
def list_admin_ai_logs(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_admin)],
    # A window, not the whole table (2026-10-07 security review): this read
    # every chat message ever written into memory on each call - customers'
    # typed addresses and numbers included - which is a slow page today and
    # an outage as the table grows.
    days: int = Query(default=30, ge=1, le=365),
) -> list[AdminAILogResponse]:
    since = datetime.now(UTC) - timedelta(days=days)
    rows = db.execute(
        select(ChatHistory, User, Restaurant)
        .join(User, ChatHistory.user_id == User.id)
        .outerjoin(Restaurant, ChatHistory.restaurant_id == Restaurant.id)
        .where(ChatHistory.created_at >= since)
        .order_by(ChatHistory.session_id.asc(), ChatHistory.created_at.asc())
    ).all()

    session_last_user_message: dict[uuid.UUID, tuple[ChatHistory, User, Restaurant | None]] = {}
    logs: list[AdminAILogResponse] = []

    for entry, user, restaurant in rows:
        if entry.role.value == "USER":
            session_last_user_message[entry.session_id] = (entry, user, restaurant)
            continue

        paired = session_last_user_message.get(entry.session_id)
        if paired is None:
            continue

        user_message, actor, user_restaurant = paired
        user_context = user_message.context_payload or {}
        assistant_context = entry.context_payload or {}
        suggestions = assistant_context.get("suggestions")
        response_time_ms: int | None = None
        if entry.created_at and user_message.created_at:
            response_time_ms = max(
                int((entry.created_at - user_message.created_at).total_seconds() * 1000),
                0,
            )

        logs.append(
            AdminAILogResponse(
                session_id=entry.session_id,
                user_name=actor.full_name,
                user_email=actor.email,
                restaurant_name=(restaurant or user_restaurant).name if (restaurant or user_restaurant) else None,
                query_text=user_message.message,
                reply_text=entry.message,
                retrieved_count=int(user_context.get("retrieved_count", 0) or 0),
                filtered_count=int(user_context.get("filtered_count", 0) or 0),
                suggestions_count=len(suggestions) if isinstance(suggestions, list) else 0,
                success=bool(entry.message.strip()) and "don't have access" not in entry.message.lower(),
                response_time_ms=response_time_ms,
                created_at=entry.created_at,
            )
        )

    return list(reversed(logs[-200:]))
