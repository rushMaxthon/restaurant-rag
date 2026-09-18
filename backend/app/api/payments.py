from __future__ import annotations

import uuid
from typing import Annotated

from fastapi.responses import HTMLResponse
from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy.orm import Session

from app.config import get_settings
from app.config.database import get_db
from app.models.restaurant import Restaurant
from app.models.user import User
from app.schemas.payment import PaymentConfigResponse
from app.services.auth import get_current_user
from app.dependencies import AppScopeDep
from app.services.payments import handle_stripe_webhook, payment_config

settings = get_settings()

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
