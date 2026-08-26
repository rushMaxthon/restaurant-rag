from __future__ import annotations

import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import AppScopeDep, ensure_restaurant_readable, ensure_restaurant_writable
from app.config.database import get_db
from app.models.enums import UserRole
from app.models.menu_item import MenuItem
from app.models.personalized_offer import PersonalizedOffer
from app.models.restaurant import Restaurant
from app.models.user import User
from app.schemas.personalized_offer import (
    GeneratedOfferUpdateRequest,
    GeneratedOfferUserMatchResponse,
    PersonalizedOfferCardResponse,
    PersonalizedOfferContextRequest,
    PersonalizedOfferEventBatchRequest,
    PersonalizedOfferEventBatchResponse,
    PersonalizedOfferItemAvailabilityRequest,
    PersonalizedOfferItemAvailabilityResponse,
    PersonalizedOfferManagementResponse,
    PersonalizedOfferPreviewRequest,
    PersonalizedOfferPreviewResponse,
    PersonalizedOfferUpsertRequest,
)
from app.schemas.admin import (
    AdminAIOfferGenerationStatusResponse,
    AdminAIOfferGenerationTriggerResponse,
    OwnerAIOfferGenerationRequest,
)
from app.config.celery import celery_app
from app.tasks.ai_offers import generate_ai_offers_task
from app.services.auth import (
    get_current_user,
    require_customer,
    resolve_owner_restaurant_id,
)
from app.services.personalized_offers import (
    create_restaurant_offer,
    delete_generated_offer,
    delete_restaurant_offer,
    get_personalized_offer_item_availability,
    get_personalized_offers_for_context,
    get_generated_offer_for_restaurant,
    get_personalized_offers_for_user,
    list_generated_offer_user_matches,
    list_restaurant_offers,
    preview_personalized_offer_for_user,
    record_personalized_offer_events,
    update_generated_offer,
    update_restaurant_offer,
)
from app.services.restaurant_locations import require_location_for_restaurant

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Personalized Offers"])


def _get_accessible_restaurant(
    db: Session,
    restaurant_id: uuid.UUID,
    current_user: User,
) -> Restaurant:
    restaurant = db.scalar(select(Restaurant).where(Restaurant.id == restaurant_id))
    if restaurant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Restaurant not found")
    if current_user.role == UserRole.ADMIN:
        return restaurant
    if current_user.role == UserRole.OWNER and restaurant.owner_id == current_user.id:
        return restaurant
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="You do not have permission to manage offers for this restaurant",
    )


def _validate_offer_scope(
    db: Session,
    *,
    restaurant_id: uuid.UUID,
    payload: PersonalizedOfferUpsertRequest,
) -> None:
    if payload.starts_at and payload.expires_at and payload.starts_at >= payload.expires_at:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Offer start time must be earlier than the expiry time",
        )

    if payload.restaurant_location_id is not None:
        require_location_for_restaurant(
            db,
            restaurant_id=restaurant_id,
            location_id=payload.restaurant_location_id,
            include_inactive=True,
        )

    if payload.applicable_item_id is not None:
        menu_item = db.scalar(select(MenuItem).where(MenuItem.id == payload.applicable_item_id))
        if menu_item is None or menu_item.restaurant_id != restaurant_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Applicable menu item was not found in this restaurant",
            )
        if (
            payload.restaurant_location_id is not None
            and menu_item.restaurant_location_id != payload.restaurant_location_id
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Applicable menu item must belong to the selected branch",
            )


def _serialize_restaurant_offer(
    db: Session,
    *,
    restaurant_id: uuid.UUID,
    offer_id: uuid.UUID,
) -> PersonalizedOfferManagementResponse:
    offers = list_restaurant_offers(db, restaurant_id=restaurant_id)
    for offer in offers:
        if offer.id == offer_id:
            return offer
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Offer not found")


@router.get("/offers/personalized", response_model=list[PersonalizedOfferCardResponse])
def get_personalized_offers(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_customer)],
    app_scope: AppScopeDep,
    limit: int = Query(default=4, ge=1, le=8),
) -> list[PersonalizedOfferCardResponse]:
    return get_personalized_offers_for_user(
        db,
        current_user,
        limit=limit,
        restaurant_id=app_scope.restaurant_filter_id,
    )


@router.post("/offers/personalized/events", response_model=PersonalizedOfferEventBatchResponse)
def post_personalized_offer_events(
    payload: PersonalizedOfferEventBatchRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_customer)],
    app_scope: AppScopeDep,
) -> PersonalizedOfferEventBatchResponse:
    return record_personalized_offer_events(
        db,
        user=current_user,
        payload=payload,
        restaurant_id=app_scope.restaurant_filter_id,
    )


@router.post("/offers/personalized/preview", response_model=PersonalizedOfferPreviewResponse)
def post_personalized_offer_preview(
    payload: PersonalizedOfferPreviewRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_customer)],
    app_scope: AppScopeDep,
) -> PersonalizedOfferPreviewResponse:
    ensure_restaurant_writable(app_scope, payload.restaurant_id)
    return preview_personalized_offer_for_user(db, user=current_user, payload=payload)


@router.post(
    "/offers/personalized/context",
    response_model=list[PersonalizedOfferCardResponse],
)
def post_personalized_offer_context(
    payload: PersonalizedOfferContextRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_customer)],
    app_scope: AppScopeDep,
) -> list[PersonalizedOfferCardResponse]:
    ensure_restaurant_readable(app_scope, payload.restaurant_id)
    return get_personalized_offers_for_context(
        db,
        user=current_user,
        payload=payload,
    )


@router.post(
    "/offers/personalized/context/items",
    response_model=list[PersonalizedOfferItemAvailabilityResponse],
)
def post_personalized_offer_item_availability(
    payload: PersonalizedOfferItemAvailabilityRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_customer)],
    app_scope: AppScopeDep,
) -> list[PersonalizedOfferItemAvailabilityResponse]:
    ensure_restaurant_readable(app_scope, payload.restaurant_id)
    return get_personalized_offer_item_availability(
        db,
        user=current_user,
        payload=payload,
    )


@router.get(
    "/restaurants/{restaurant_id}/offers",
    response_model=list[PersonalizedOfferManagementResponse],
)
def get_restaurant_offers(
    restaurant_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> list[PersonalizedOfferManagementResponse]:
    if current_user.role not in {UserRole.ADMIN, UserRole.OWNER}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You do not have permission to manage offers")
    _get_accessible_restaurant(db, restaurant_id, current_user)
    return list_restaurant_offers(db, restaurant_id=restaurant_id)


@router.post(
    "/restaurants/{restaurant_id}/offers",
    response_model=PersonalizedOfferManagementResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_offer(
    restaurant_id: uuid.UUID,
    payload: PersonalizedOfferUpsertRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> PersonalizedOfferManagementResponse:
    if current_user.role not in {UserRole.ADMIN, UserRole.OWNER}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You do not have permission to manage offers")
    _get_accessible_restaurant(db, restaurant_id, current_user)
    _validate_offer_scope(db, restaurant_id=restaurant_id, payload=payload)
    offer = create_restaurant_offer(db, restaurant_id=restaurant_id, payload=payload)
    return _serialize_restaurant_offer(db, restaurant_id=restaurant_id, offer_id=offer.id)


@router.patch(
    "/restaurants/{restaurant_id}/offers/{offer_id}",
    response_model=PersonalizedOfferManagementResponse,
)
def patch_offer(
    restaurant_id: uuid.UUID,
    offer_id: uuid.UUID,
    payload: PersonalizedOfferUpsertRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> PersonalizedOfferManagementResponse:
    if current_user.role not in {UserRole.ADMIN, UserRole.OWNER}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You do not have permission to manage offers")
    _get_accessible_restaurant(db, restaurant_id, current_user)
    offer = db.scalar(
        select(PersonalizedOffer).where(
            PersonalizedOffer.id == offer_id,
            PersonalizedOffer.restaurant_id == restaurant_id,
        )
    )
    if offer is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Offer not found")
    _validate_offer_scope(db, restaurant_id=restaurant_id, payload=payload)
    updated = update_restaurant_offer(db, offer=offer, payload=payload)
    return _serialize_restaurant_offer(db, restaurant_id=restaurant_id, offer_id=updated.id)


@router.delete(
    "/restaurants/{restaurant_id}/offers/{offer_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def remove_offer(
    restaurant_id: uuid.UUID,
    offer_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> Response:
    if current_user.role not in {UserRole.ADMIN, UserRole.OWNER}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You do not have permission to manage offers")
    _get_accessible_restaurant(db, restaurant_id, current_user)
    offer = db.scalar(
        select(PersonalizedOffer).where(
            PersonalizedOffer.id == offer_id,
            PersonalizedOffer.restaurant_id == restaurant_id,
        )
    )
    if offer is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Offer not found")
    delete_restaurant_offer(db, offer=offer)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/restaurants/{restaurant_id}/generated-offers/{generated_offer_id}/matches",
    response_model=list[GeneratedOfferUserMatchResponse],
)
def get_generated_offer_matches(
    restaurant_id: uuid.UUID,
    generated_offer_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> list[GeneratedOfferUserMatchResponse]:
    if current_user.role not in {UserRole.ADMIN, UserRole.OWNER}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You do not have permission to manage offers")
    _get_accessible_restaurant(db, restaurant_id, current_user)
    return list_generated_offer_user_matches(
        db,
        restaurant_id=restaurant_id,
        generated_offer_id=generated_offer_id,
    )


@router.patch(
    "/restaurants/{restaurant_id}/generated-offers/{generated_offer_id}",
    response_model=PersonalizedOfferManagementResponse,
)
def patch_generated_offer(
    restaurant_id: uuid.UUID,
    generated_offer_id: uuid.UUID,
    payload: GeneratedOfferUpdateRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> PersonalizedOfferManagementResponse:
    if current_user.role not in {UserRole.ADMIN, UserRole.OWNER}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You do not have permission to manage offers")
    _get_accessible_restaurant(db, restaurant_id, current_user)
    generated_offer = get_generated_offer_for_restaurant(
        db,
        restaurant_id=restaurant_id,
        generated_offer_id=generated_offer_id,
    )
    if generated_offer is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Generated offer not found")
    update_generated_offer(
        db,
        generated_offer=generated_offer,
        payload=payload,
        edited_by_user=current_user,
    )
    offers = list_restaurant_offers(db, restaurant_id=restaurant_id)
    for offer in offers:
        if offer.id == generated_offer_id and offer.record_kind == "GENERATED":
            return offer
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Generated offer not found")


@router.delete(
    "/restaurants/{restaurant_id}/generated-offers/{generated_offer_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def remove_generated_offer(
    restaurant_id: uuid.UUID,
    generated_offer_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> Response:
    if current_user.role not in {UserRole.ADMIN, UserRole.OWNER}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You do not have permission to manage offers")
    _get_accessible_restaurant(db, restaurant_id, current_user)
    generated_offer = get_generated_offer_for_restaurant(
        db,
        restaurant_id=restaurant_id,
        generated_offer_id=generated_offer_id,
    )
    if generated_offer is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Generated offer not found")
    delete_generated_offer(db, generated_offer=generated_offer)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/owner/offers/generate-ai",
    response_model=AdminAIOfferGenerationTriggerResponse,
)
def trigger_owner_ai_offer_generation(
    payload: OwnerAIOfferGenerationRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> AdminAIOfferGenerationTriggerResponse:
    """Generate personalized offers for the caller's own restaurant.

    The owner-facing counterpart of the platform-wide admin run. The difference
    that matters is the scope: `restaurant_id` is resolved from the signed-in
    owner and passed to the task, so the run scans only the customers who have
    paid this restaurant and can only produce offers for it. Nothing in the
    request body can widen that - there is no restaurant field to send.

    Runs inline rather than queued, so the screen can report the result without
    a worker being attached.
    """

    restaurant_id = resolve_owner_restaurant_id(db, current_user)

    task_kwargs = {
        "user_limit": payload.user_limit,
        "batch_size": payload.batch_size,
        "force_refresh": payload.force_refresh,
        "allow_disabled": True,
        "restaurant_id": str(restaurant_id),
    }

    try:
        result = generate_ai_offers_task.apply(kwargs=task_kwargs)
    except Exception as error:  # pragma: no cover - defensive execution failure path
        logger.exception(
            "Owner AI offer generation failed owner_user_id=%s restaurant_id=%s",
            current_user.id,
            restaurant_id,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unable to run AI offer generation right now: {error}",
        ) from error

    logger.info(
        "Owner AI offer generation completed owner_user_id=%s restaurant_id=%s "
        "task_id=%s force_refresh=%s successful=%s",
        current_user.id,
        restaurant_id,
        result.id,
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


@router.get(
    "/owner/offers/generate-ai/{task_id}",
    response_model=AdminAIOfferGenerationStatusResponse,
)
def get_owner_ai_offer_generation_status(
    task_id: str,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> AdminAIOfferGenerationStatusResponse:
    """Progress of a run this owner started.

    Resolving the owner's restaurant first is not decoration: it is what stops a
    signed-in customer, or an owner with no restaurant, from reading task
    results at all.
    """

    resolve_owner_restaurant_id(db, current_user)

    result = celery_app.AsyncResult(task_id)
    task_state = str(result.state or "PENDING").upper()
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
