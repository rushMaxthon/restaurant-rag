"""Where browsers report what the strict script policy would have blocked.

The three web apps send `Content-Security-Policy-Report-Only` (2026-10-07
security review): nothing is blocked, each would-be block is reported here.
A few days of real traffic with no reports from legitimate pages is the
evidence for switching it to enforcing, which done blind could break
checkout - Stripe and Razorpay load from several hosts.

Public by necessity: browsers send these without a login. So it is rate
limited per IP, refuses a body over `MAX_REPORT_BYTES`, never echoes
anything back, and only logs - with query strings stripped from the URLs,
which can carry tokens.
"""

from __future__ import annotations

import json
import logging
from typing import Annotated, Any
from urllib.parse import urlsplit, urlunsplit

from fastapi import APIRouter, Depends, Request, Response, status

from app.services.rate_limit import per_ip

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/security", tags=["Security"])

MAX_REPORT_BYTES = 16_384


def _without_query(url: Any) -> str:
    text = str(url or "")
    try:
        parts = urlsplit(text)
    except ValueError:
        return text[:200]
    if not parts.scheme:
        return text[:200]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))[:300]


def _violations(payload: Any) -> list[dict[str, str]]:
    """Both report formats: the older `csp-report` object, and the Reporting
    API's list of `{type, body}`."""

    found = []
    if isinstance(payload, dict) and isinstance(payload.get("csp-report"), dict):
        report = payload["csp-report"]
        found.append(
            {
                "page": report.get("document-uri"),
                "directive": report.get("effective-directive") or report.get("violated-directive"),
                "blocked": report.get("blocked-uri"),
            }
        )
    elif isinstance(payload, list):
        for item in payload[:20]:
            body = item.get("body") if isinstance(item, dict) else None
            if isinstance(body, dict):
                found.append(
                    {
                        "page": body.get("documentURL"),
                        "directive": body.get("effectiveDirective"),
                        "blocked": body.get("blockedURL"),
                    }
                )
    return found


@router.post("/csp-report", status_code=status.HTTP_204_NO_CONTENT, include_in_schema=False)
async def csp_report(
    _rate_limited: Annotated[None, Depends(per_ip("csp-report", limit=60, window_seconds=60))],
    request: Request,
) -> Response:
    body = await request.body()
    if len(body) > MAX_REPORT_BYTES:
        return Response(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)
    try:
        payload = json.loads(body or b"null")
    except ValueError:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    for violation in _violations(payload):
        logger.warning(
            "CSP would block directive=%s blocked=%s page=%s",
            str(violation["directive"] or "")[:80],
            _without_query(violation["blocked"]),
            _without_query(violation["page"]),
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
