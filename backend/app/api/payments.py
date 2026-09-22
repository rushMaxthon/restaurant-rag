from __future__ import annotations

import uuid
from typing import Annotated

from fastapi.responses import HTMLResponse
from fastapi import APIRouter, Depends, Header, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import get_settings
from app.config.database import get_db
from app.models.restaurant import Restaurant
from app.models.user import User
from app.schemas.payment import PaymentConfigResponse
from app.services.auth import get_current_user
from app.dependencies import AppScopeDep
from app.models.enums import PaymentGateway
from app.models.order import Order
from app.services.payments import handle_stripe_webhook, payment_config
from app.services.payments.service import (
    confirm_razorpay_checkout,
    handle_gateway_webhook,
)

settings = get_settings()

class RazorpayCheckoutConfirm(BaseModel):
    """The three values Razorpay Checkout hands the browser on success.

    Worth nothing until verified: the signature is an HMAC of the other two
    with the restaurant's API secret, which is what makes them believable.
    """

    razorpay_order_id: str = Field(min_length=4, max_length=255)
    razorpay_payment_id: str = Field(min_length=4, max_length=255)
    razorpay_signature: str = Field(min_length=16, max_length=255)


router = APIRouter(prefix="/payments", tags=["Payments"])


@router.get("/config", response_model=PaymentConfigResponse)
def get_payment_config(
    db: Annotated[Session, Depends(get_db)],
    # Authenticated so the publishable key is not handed to anonymous callers,
    # even though it is not secret.
    current_user: Annotated[User, Depends(get_current_user)],
    app_scope: AppScopeDep,
) -> PaymentConfigResponse:
    """The publishable key, the methods on offer, and the currency of THIS app.

    The currency used to come from one global setting, which was right while
    the platform served one restaurant. A branded app resolves to its own
    restaurant, so it is told what that restaurant charges in; a caller with
    no app scope — the marketplace, the admin panel — gets the platform
    default, because there is no single right answer for "every restaurant".

    `supported_methods` is the same story: it names what THIS restaurant can
    actually settle, so a storefront shows a card button only where a gateway
    exists behind it. The branch is not narrowed here — a customer has not
    chosen one yet at bootstrap — so this is the restaurant's ceiling, and
    checkout re-checks against the branch they end up ordering from.
    """

    restaurant_id = app_scope.restaurant_filter_id
    restaurant = db.get(Restaurant, restaurant_id) if restaurant_id else None
    return PaymentConfigResponse(
        **payment_config(
            db,
            currency=restaurant.currency if restaurant else None,
            restaurant_id=restaurant_id,
        )
    )


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


@router.post("/webhook/{gateway}/{restaurant_id}", include_in_schema=False)
async def gateway_webhook(
    gateway: PaymentGateway,
    restaurant_id: uuid.UUID,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    stripe_signature: Annotated[str | None, Header(alias="Stripe-Signature")] = None,
    razorpay_signature: Annotated[str | None, Header(alias="X-Razorpay-Signature")] = None,
) -> dict[str, str]:
    """Event sink for a restaurant that holds its own gateway account.

    **The restaurant is in the URL on purpose.** Each restaurant has its own
    webhook secret, so the secret to verify with must be known before anything
    in the body is believed — and before verification the only trustworthy
    thing about the request is where it arrived. Every gateway lets an account
    configure its own webhook URL, so each restaurant's dashboard points here,
    at its own path.

    Reading the order id out of the body to find the restaurant would also
    work, and is the shape to avoid: it makes a database lookup driven by
    attacker-controlled input the step *before* the check that decides whether
    that input can be trusted at all.

    Unauthenticated, like the platform sink above: the signature is the
    authentication. Posting to another restaurant's path fails, because the
    signature will not match that restaurant's secret. The raw body is
    required — re-serialised JSON would not match either gateway's HMAC.

    The URL for a restaurant is:
        POST /api/payments/webhook/RAZORPAY/<restaurant id>
    """

    payload = await request.body()
    signature = (
        razorpay_signature if gateway == PaymentGateway.RAZORPAY else stripe_signature
    )
    return handle_gateway_webhook(
        db,
        gateway=gateway,
        restaurant_id=restaurant_id,
        payload=payload,
        signature=signature,
    )


@router.post("/razorpay/confirm/{order_id}", response_model=dict)
def razorpay_confirm(
    order_id: uuid.UUID,
    payload: RazorpayCheckoutConfirm,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> dict[str, str]:
    """What the browser posts back when Razorpay Checkout succeeds.

    The fast path: it marks the order paid while the customer is still looking
    at the screen, rather than making them wait on a webhook. The webhook is
    still what settles an order whose customer closed the tab, and both routes
    end at the same idempotent `_mark_paid`.

    The three values are verified as a signature against this restaurant's own
    API secret before anything moves. Without that check a customer could post
    a made-up payment id and have their order marked paid — which is the whole
    reason Razorpay signs them.
    """

    order = db.get(Order, order_id)
    if order is None or order.customer_id != current_user.id:
        # Same answer for "no such order" and "not yours", so this cannot be
        # used to find out which order ids exist.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")

    return confirm_razorpay_checkout(
        db,
        order=order,
        razorpay_order_id=payload.razorpay_order_id,
        razorpay_payment_id=payload.razorpay_payment_id,
        razorpay_signature=payload.razorpay_signature,
    )


@router.get("/return/{order_id}", include_in_schema=False, response_class=HTMLResponse)
def payment_return(order_id: uuid.UUID, outcome: str = "paid") -> HTMLResponse:
    """The page a phone lands on after a hosted checkout.

    Deliberately says almost nothing: it is reachable by anyone holding the
    order id, so it carries no name, no amount and no address — the short
    reference and a way back to the chat. What actually happened is not
    read off the query string either; the webhook is the authority on that
    and the confirmation it sends to the chat is the record. This page only
    tells the customer where to look for it.
    """

    paid = outcome == "paid"
    reference = str(order_id)[:8]
    number = "".join(ch for ch in settings.whatsapp_business_number if ch.isdigit())
    back = f"https://wa.me/{number}" if number else None
    headline = "Payment received" if paid else "Payment not completed"
    detail = (
        "Thank you. Your confirmation is on its way to you in WhatsApp."
        if paid
        else "Nothing has been charged. Go back to WhatsApp to try again or change your order."
    )
    link = (
        f'<p><a class="back" href="{back}">Back to WhatsApp</a></p>' if back
        else "<p>You can close this page and go back to WhatsApp.</p>"
    )
    html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{headline}</title>
<style>
  body {{ font-family: system-ui, -apple-system, sans-serif; margin: 0; padding: 48px 24px;
         background: #f7f5f0; color: #1b1b1b; text-align: center; }}
  h1 {{ font-size: 1.6rem; margin: 0 0 12px; }}
  p {{ font-size: 1.05rem; line-height: 1.5; margin: 0 0 20px; }}
  .ref {{ color: #666; font-size: 0.95rem; }}
  .back {{ display: inline-block; padding: 14px 22px; border-radius: 999px; background: #1f8f4e;
           color: #fff; text-decoration: none; font-weight: 600; }}
</style></head>
<body>
  <h1>{headline}</h1>
  <p>{detail}</p>
  {link}
  <p class="ref">Order reference {reference}</p>
</body></html>"""
    return HTMLResponse(html)
