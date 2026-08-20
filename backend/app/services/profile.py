from __future__ import annotations

import logging
import uuid

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.enums import OrderStatus
from app.models.order import Order
from app.models.user import User
from app.models.user_saved_address import UserSavedAddress
from app.schemas.auth import UserResponse
from app.schemas.profile import (
    SavedAddressCreateRequest,
    SavedAddressResponse,
    SavedAddressUpdateRequest,
    UserProfileStatsResponse,
    UserProfileSummaryResponse,
    UserProfileUpdateRequest,
)
from app.services.favorites import get_user_favorite_ids
from app.services.orders import _order_base_query, _serialize_order
from app.services.recommendations import get_user_preferences_response

logger = logging.getLogger(__name__)


def _normalize_address_label(value: str) -> str:
    normalized = (value or "OTHER").strip().upper()
    return normalized if normalized in {"HOME", "WORK", "OTHER"} else "OTHER"


def _format_address(address: UserSavedAddress) -> str:
    parts = [
        (address.address_line_1 or "").strip(),
        (address.address_line_2 or "").strip(),
        (address.landmark or "").strip(),
        (address.city or "").strip(),
        (address.state or "").strip(),
        (address.postal_code or "").strip(),
    ]
    return ", ".join(part for part in parts if part)


def _is_saved_address_storage_error(exc: SQLAlchemyError) -> bool:
    message = str(getattr(exc, "orig", exc)).lower()
    return any(
        marker in message
        for marker in (
            "user_saved_addresses",
            "saved_addresses",
            "undefinedtable",
            "undefined column",
            "does not exist",
            "no such table",
        )
    )


def _raise_saved_address_unavailable(exc: SQLAlchemyError) -> None:
    logger.exception("Saved address storage failure", exc_info=exc)
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Saved addresses are temporarily unavailable. Please update the backend schema and try again.",
    ) from exc


def _load_saved_addresses(
    db: Session,
    user: User,
    *,
    fail_open: bool = False,
) -> list[UserSavedAddress]:
    try:
        return list(
            db.scalars(
                select(UserSavedAddress)
                .where(UserSavedAddress.user_id == user.id)
                .order_by(
                    UserSavedAddress.is_default.desc(),
                    UserSavedAddress.updated_at.desc(),
                )
            ).all()
        )
    except SQLAlchemyError as exc:
        db.rollback()
        if fail_open and _is_saved_address_storage_error(exc):
            logger.exception(
                "Saved addresses unavailable for user %s; returning empty list",
                user.id,
            )
            return []
        raise


def _serialize_saved_address(address: UserSavedAddress) -> SavedAddressResponse:
    return SavedAddressResponse(
        id=address.id,
        label=_normalize_address_label(address.label),
        address_line_1=address.address_line_1,
        address_line_2=address.address_line_2,
        landmark=address.landmark,
        city=address.city,
        state=address.state,
        postal_code=address.postal_code,
        phone_number=address.phone_number,
        is_default=address.is_default,
        formatted_address=_format_address(address),
        created_at=address.created_at,
        updated_at=address.updated_at,
    )


def _sync_user_default_address(db: Session, user: User) -> None:
    saved_addresses = _load_saved_addresses(db, user, fail_open=True)
    default_address = next((address for address in saved_addresses if address.is_default), None)
    user.default_address = _format_address(default_address) if default_address else None
    db.add(user)


def _get_saved_address_or_404(
    db: Session,
    user: User,
    address_id: uuid.UUID,
) -> UserSavedAddress:
    try:
        address = db.scalar(
            select(UserSavedAddress).where(
                UserSavedAddress.id == address_id,
                UserSavedAddress.user_id == user.id,
            )
        )
    except SQLAlchemyError as exc:
        db.rollback()
        if _is_saved_address_storage_error(exc):
            _raise_saved_address_unavailable(exc)
        raise
    if not address:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Saved address not found",
        )
    return address


def _set_default_address(
    db: Session,
    user: User,
    target_address: UserSavedAddress | None,
) -> None:
    for address in _load_saved_addresses(db, user):
        address.is_default = target_address is not None and address.id == target_address.id
        db.add(address)

    _sync_user_default_address(db, user)


def list_user_saved_addresses(db: Session, user: User) -> list[SavedAddressResponse]:
    return [
        _serialize_saved_address(address)
        for address in _load_saved_addresses(db, user, fail_open=True)
    ]


def create_user_saved_address(
    db: Session,
    user: User,
    payload: SavedAddressCreateRequest,
) -> SavedAddressResponse:
    existing_addresses = _load_saved_addresses(db, user, fail_open=True)
    next_address = UserSavedAddress(
        user_id=user.id,
        label=_normalize_address_label(payload.label),
        address_line_1=payload.address_line_1.strip(),
        address_line_2=payload.address_line_2.strip() or None if payload.address_line_2 else None,
        landmark=payload.landmark.strip() or None if payload.landmark else None,
        city=payload.city.strip(),
        state=payload.state.strip(),
        postal_code=payload.postal_code.strip(),
        phone_number=payload.phone_number.strip() or None if payload.phone_number else None,
        is_default=payload.is_default or not existing_addresses,
    )
    db.add(next_address)
    try:
        db.flush()
    except SQLAlchemyError as exc:
        db.rollback()
        if _is_saved_address_storage_error(exc):
            _raise_saved_address_unavailable(exc)
        raise

    if next_address.is_default:
        _set_default_address(db, user, next_address)

    try:
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        if _is_saved_address_storage_error(exc):
            _raise_saved_address_unavailable(exc)
        raise
    db.refresh(next_address)
    return _serialize_saved_address(next_address)


def update_user_saved_address(
    db: Session,
    user: User,
    address_id: uuid.UUID,
    payload: SavedAddressUpdateRequest,
) -> SavedAddressResponse:
    _load_saved_addresses(db, user, fail_open=True)
    address = _get_saved_address_or_404(db, user, address_id)

    if payload.label is not None:
        address.label = _normalize_address_label(payload.label)
    if payload.address_line_1 is not None:
        address.address_line_1 = payload.address_line_1.strip()
    if payload.address_line_2 is not None:
        address.address_line_2 = payload.address_line_2.strip() or None
    if payload.landmark is not None:
        address.landmark = payload.landmark.strip() or None
    if payload.city is not None:
        address.city = payload.city.strip()
    if payload.state is not None:
        address.state = payload.state.strip()
    if payload.postal_code is not None:
        address.postal_code = payload.postal_code.strip()
    if payload.phone_number is not None:
        address.phone_number = payload.phone_number.strip() or None

    db.add(address)
    db.flush()

    if payload.is_default is True:
        _set_default_address(db, user, address)
    elif address.is_default:
        _sync_user_default_address(db, user)

    try:
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        if _is_saved_address_storage_error(exc):
            _raise_saved_address_unavailable(exc)
        raise
    db.refresh(address)
    return _serialize_saved_address(address)


def delete_user_saved_address(
    db: Session,
    user: User,
    address_id: uuid.UUID,
) -> None:
    _load_saved_addresses(db, user, fail_open=True)
    address = _get_saved_address_or_404(db, user, address_id)
    was_default = address.is_default

    db.delete(address)
    db.flush()
    remaining_addresses = _load_saved_addresses(db, user, fail_open=True)

    if was_default:
        next_default = remaining_addresses[0] if remaining_addresses else None
        if next_default is not None:
            _set_default_address(db, user, next_default)
        else:
            _sync_user_default_address(db, user)

    try:
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        if _is_saved_address_storage_error(exc):
            _raise_saved_address_unavailable(exc)
        raise


def set_default_user_saved_address(
    db: Session,
    user: User,
    address_id: uuid.UUID,
) -> SavedAddressResponse:
    _load_saved_addresses(db, user, fail_open=True)
    address = _get_saved_address_or_404(db, user, address_id)
    _set_default_address(db, user, address)
    try:
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        if _is_saved_address_storage_error(exc):
            _raise_saved_address_unavailable(exc)
        raise
    db.refresh(address)
    return _serialize_saved_address(address)


def get_user_profile_summary(
    db: Session,
    user: User,
    *,
    recent_order_limit: int = 4,
) -> UserProfileSummaryResponse:
    total_orders = db.scalar(
        select(func.count(Order.id)).where(Order.customer_id == user.id)
    ) or 0
    delivered_orders = db.scalar(
        select(func.count(Order.id)).where(
            Order.customer_id == user.id,
            Order.status == OrderStatus.DELIVERED,
        )
    ) or 0
    saved_address_rows = _load_saved_addresses(db, user, fail_open=True)
    saved_places = len(saved_address_rows)
    favorites_count = len(get_user_favorite_ids(db, user, fail_open=True))
    recent_orders = db.scalars(
        _order_base_query().where(Order.customer_id == user.id).limit(recent_order_limit)
    ).all()

    return UserProfileSummaryResponse(
        user=UserResponse.model_validate(user),
        stats=UserProfileStatsResponse(
            total_orders=int(total_orders),
            delivered_orders=int(delivered_orders),
            saved_places=int(saved_places),
            favorites_count=favorites_count,
        ),
        preferences=get_user_preferences_response(db, user),
        recent_orders=[_serialize_order(order) for order in recent_orders],
        saved_addresses=[_serialize_saved_address(address) for address in saved_address_rows],
    )


def update_user_profile(
    db: Session,
    user: User,
    payload: UserProfileUpdateRequest,
) -> UserResponse:
    full_name = payload.full_name.strip()
    if len(full_name) < 2:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Full name must be at least 2 characters long",
        )

    user.full_name = full_name
    user.phone_number = (
        payload.phone_number.strip() or None
        if payload.phone_number
        else None
    )
    user.default_address = (
        payload.default_address.strip() or None
        if payload.default_address
        else None
    )

    try:
        db.add(user)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        message = str(getattr(exc, "orig", exc)).lower()
        if "phone" in message and ("unique" in message or "duplicate" in message):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="That phone number is already in use",
            ) from exc
        raise

    db.refresh(user)
    return UserResponse.model_validate(user)
