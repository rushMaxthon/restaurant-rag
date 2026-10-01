"""Does this Pidge account work, and what kind of account is it?

Read-only. It logs in, asks whether a real address is serviceable, and asks
what that trip would cost. **It never creates an order**, so it cannot book a
rider, cannot be charged for one, and is safe to run against a live account
from a laptop — which is the whole point of it existing.

That matters because the alternative way to find out whether credentials work
is to accept an order and watch, and on a live account that sends a human to
somebody's door.

What it answers, in the order the answers are needed:

1. **Do the credentials authenticate at all?** Pidge's dashboard login and its
   channel API credentials are not always the same thing, and a dashboard
   password refused here is the usual first surprise.
2. **Is the account a vendor or an aggregator?** It matters: a vendor account
   (type 4) refuses an order carrying a brand block with "Brand is allowed
   only for aggregator(6)", so `PIDGE_BRAND_CODE` and its two companions must
   be EMPTY on a vendor account and set on an aggregator one. Guessing wrong
   fails at the first real dispatch, not here.
3. **Will they drive to a real customer?** Serviceability for one branch's own
   coordinates against a real drop.
4. **What do they charge?** The live quote, which is what a checkout prints.

Run it from `backend/`:

    ./.venv/Scripts/python.exe scripts/pidge_healthcheck.py
    ./.venv/Scripts/python.exe scripts/pidge_healthcheck.py --drop 21.2050,72.8300

Nothing is written anywhere, including the log.
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.config import get_settings  # noqa: E402
from app.services.delivery.base import DeliveryProviderError  # noqa: E402
from app.services.delivery.pidge_provider import PidgeProvider  # noqa: E402
from app.services.delivery.service import (  # noqa: E402
    _is_sandbox_host,
    live_dispatch_blocked_reason,
)

OK = "  ok   "
BAD = " FAIL  "
NOTE = "  --   "


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--drop",
        default="21.2050,72.8300",
        help="lat,lng of a customer to test against (default: a point in Surat)",
    )
    parser.add_argument(
        "--pickup",
        default="",
        help="lat,lng of the branch (default: read from the first located branch)",
    )
    args = parser.parse_args()

    settings = get_settings()
    sandbox = _is_sandbox_host(settings.pidge_base_url)

    print()
    print("Pidge account check — READ ONLY, no order is created")
    print("=" * 60)
    print(f"  host         {settings.pidge_base_url}")
    print(f"  kind         {'SANDBOX' if sandbox else 'LIVE — real riders, real money'}")
    print(f"  environment  {settings.environment}")
    print(f"  username     {'(set)' if settings.pidge_username else '(EMPTY)'}")
    print(f"  password     {'(set)' if settings.pidge_password else '(EMPTY)'}")
    print()

    if not settings.pidge_username or not settings.pidge_password:
        print(f"{BAD} No credentials. Set PIDGE_USERNAME and PIDGE_PASSWORD in .env")
        return 1

    provider = PidgeProvider(
        base_url=settings.pidge_base_url,
        username=settings.pidge_username,
        password=settings.pidge_password,
        brand_code=settings.pidge_brand_code,
        brand_location_code=settings.pidge_brand_location_code,
        brand_name=settings.pidge_brand_name,
    )

    # --- 1. authentication ------------------------------------------------
    try:
        token = provider._login()  # noqa: SLF001 - the point of this script
    except DeliveryProviderError as error:
        print(f"{BAD} Login refused: {error}")
        print()
        print("       Pidge's dashboard login and its channel API credentials are")
        print("       not always the same. If your dashboard password is being")
        print("       refused here, ask Pidge for API access for this account.")
        return 1
    print(f"{OK} Logged in ({len(token)}-character token)")

    # --- 2. account type ---------------------------------------------------
    #
    # Read from the token's own claims rather than from a separate call: Pidge
    # puts the account type in the JWT, and there is no public endpoint that
    # states it plainly.
    kind = _account_kind(token)
    if kind is None:
        print(f"{NOTE} Could not read the account type from the token")
        print("       Ask Pidge whether this is a vendor (4) or aggregator (6)")
    else:
        label = {4: "vendor", 6: "aggregator"}.get(kind, f"type {kind}")
        print(f"{OK} Account is a {label}")
        brand_set = bool(settings.pidge_brand_code)
        if kind == 6 and not brand_set:
            print(f"{BAD} An aggregator account NEEDS PIDGE_BRAND_CODE,")
            print("       PIDGE_BRAND_LOCATION_CODE and PIDGE_BRAND_NAME set")
        elif kind != 6 and brand_set:
            print(f"{BAD} PIDGE_BRAND_CODE is set but this is not an aggregator.")
            print('       Every order will be refused with "Brand is allowed')
            print('       only for aggregator(6)". Clear all three BRAND values.')
        else:
            print(f"{OK} Brand settings match the account type")

    # --- 3 & 4. serviceability and price ----------------------------------
    pickup = _coords(args.pickup) or _first_located_branch()
    drop = _coords(args.drop)
    if pickup is None:
        print(f"{NOTE} No branch has coordinates yet, so no trip could be priced")
        print("       Set one in the admin, or pass --pickup lat,lng")
        return 0
    if drop is None:
        print(f"{BAD} --drop must be lat,lng")
        return 1

    print()
    print(f"  pricing {pickup[0]:.5f},{pickup[1]:.5f} -> {drop[0]:.5f},{drop[1]:.5f}")
    try:
        quote = provider.quote(
            pickup_lat=pickup[0],
            pickup_lng=pickup[1],
            drop_lat=drop[0],
            drop_lng=drop[1],
            timeout=20.0,
        )
    except DeliveryProviderError as error:
        print(f"{BAD} Could not get a quote: {error}")
        return 1

    if not quote.serviceable:
        print(f"{BAD} They will not drive this trip")
        print("       On a live account this usually means the pickup is outside")
        print("       their coverage, or the branch is not registered with them.")
        return 1

    print(f"{OK} Serviceable")
    print(f"       cost      {quote.min_cost} - {quote.max_cost} {quote.currency}")
    if quote.distance_metres is not None:
        print(f"       distance  {quote.distance_metres / 1000:.2f} km")
    if quote.assign_seconds is not None:
        print(f"       to assign {quote.assign_seconds // 60} min")
    if quote.travel_seconds is not None:
        print(f"       to drive  {quote.travel_seconds // 60} min")

    # --- what would happen if an order were accepted right now -------------
    print()
    blocked = live_dispatch_blocked_reason()
    if settings.enable_delivery_rehearsal:
        print(f"{OK} No rider can be booked: the REHEARSAL courier is on, so")
        print("       Pidge is not called for dispatch at all. Deliveries are")
        print("       simulated. Set ENABLE_DELIVERY_REHEARSAL=false for real ones.")
    elif not settings.enable_delivery_dispatch:
        print(f"{OK} No rider can be booked: enable_delivery_dispatch is off")
    elif blocked:
        print(f"{OK} No REAL rider can be booked: {blocked}")
    elif sandbox:
        # Worth stating rather than passing over: dispatch IS on and orders
        # will be sent — just to a sandbox that never assigns anyone, which is
        # exactly what makes the sandbox safe and also useless for a demo.
        print(f"{OK} Dispatch is on, but this is the SANDBOX — orders are sent")
        print("       and no real rider is ever assigned.")
    else:
        print(f"{NOTE} DISPATCH IS LIVE ON A LIVE ACCOUNT.")
        print("       Accepting an order WILL send a real person to a real address.")
    print()
    return 0


def _account_kind(token: str) -> int | None:
    """The `type` claim out of Pidge's JWT, if it is there.

    The signature is not checked and must not be — this is their token, read
    for a label, and nothing is authorised on the strength of it.
    """

    import base64
    import json

    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload))
    except Exception:  # noqa: BLE001 - any malformed token means "unknown"
        return None
    for key in ("type", "account_type", "user_type"):
        value = claims.get(key)
        if isinstance(value, int):
            return value
    return None


def _coords(raw: str) -> tuple[float, float] | None:
    if not raw:
        return None
    try:
        lat, _, lng = raw.partition(",")
        return float(lat), float(lng)
    except ValueError:
        return None


def _first_located_branch() -> tuple[float, float] | None:
    """Any branch with real coordinates, so the check uses a real trip."""

    from sqlalchemy import select

    from app.config.database import SessionLocal
    from app.models.restaurant_location import RestaurantLocation

    with SessionLocal() as db:
        row = db.scalar(
            select(RestaurantLocation)
            .where(RestaurantLocation.latitude.is_not(None))
            .where(RestaurantLocation.longitude.is_not(None))
            .limit(1)
        )
        if row is None:
            return None
        print(f"  branch  {row.branch_name}")
        return float(row.latitude), float(row.longitude)


if __name__ == "__main__":
    raise SystemExit(main())
