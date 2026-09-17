"""`/api/p/<token>` — the short payment link a phone was sent.

One job: send the phone on to Stripe. No page of ours is shown on the way,
because a page between the tap and the card is a page to distrust.
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, RedirectResponse

from app.config import get_settings
from app.services.short_links import resolve

settings = get_settings()
router = APIRouter(prefix="/p", tags=["Payments"])


@router.get("/{token}", include_in_schema=False)
def follow_short_link(token: str):
    url = resolve(token)
    if url:
        # 302, not 301: a browser must ask again next time, because next
        # time the session may be gone.
        return RedirectResponse(url, status_code=302)

    number = "".join(ch for ch in settings.whatsapp_business_number if ch.isdigit())
    back = f'<p><a class="back" href="https://wa.me/{number}">Back to WhatsApp</a></p>' if number else ""
    return HTMLResponse(
        status_code=404,
        content=f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>This link has expired</title>
<style>
  body {{ font-family: system-ui, -apple-system, sans-serif; margin: 0; padding: 48px 24px;
         background: #f7f5f0; color: #1b1b1b; text-align: center; }}
  h1 {{ font-size: 1.6rem; margin: 0 0 12px; }}
  p {{ font-size: 1.05rem; line-height: 1.5; margin: 0 0 20px; }}
  .back {{ display: inline-block; padding: 14px 22px; border-radius: 999px; background: #1f8f4e;
           color: #fff; text-decoration: none; font-weight: 600; }}
</style></head>
<body>
  <h1>This payment link has expired</h1>
  <p>Nothing has been charged. Go back to the chat and ask for a fresh link.</p>
  {back}
</body></html>""",
    )
