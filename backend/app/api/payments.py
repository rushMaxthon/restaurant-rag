from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.models.user import User
from app.schemas.payment import PaymentConfigResponse
from app.services.auth import get_current_user
from app.services.payments import handle_stripe_webhook, payment_config

router = APIRouter(prefix="/payments", tags=["Payments"])


@router.get("/config", response_model=PaymentConfigResponse)
def get_payment_config(
    # Authenticated so the publishable key is not handed to anonymous callers,
    # even though it is not secret.
    current_user: Annotated[User, Depends(get_current_user)],
) -> PaymentConfigResponse:
    return PaymentConfigResponse(**payment_config())


@router.post("/stripe/webhook", include_in_schema=False)
async def stripe_webhook(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    stripe_signature: Annotated[str | None, Header(alias="Stripe-Signature")] = None,
) -> dict[str, str]:
    """Stripe event sink.

    Deliberately unauthenticated: the signature *is* the authentication. The
    raw body is required — re-serialised JSON would not match the signature.
    """

    payload = await request.body()
    return handle_stripe_webhook(db, payload=payload, signature=stripe_signature)
