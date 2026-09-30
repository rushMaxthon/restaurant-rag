"""Find the coordinates of every branch, and say plainly which ones failed.

A branch address is written once and then used by every order that branch ever
takes, so it is worth locating properly, once, rather than on a customer's
critical path. Run this after onboarding a restaurant.

What it does NOT do is pretend. A geocoder always answers something — ask it for
a street that does not exist and it hands back a city centroid with no
complaint — so this only stores a point precise enough to price a delivery from,
and it lists the rest for a person to fix by hand. That list is the useful
output: a branch nobody can locate is a branch whose deliveries are being priced
from a stand-in, and the only thing worse than knowing that is not knowing it.

    ./.venv/Scripts/python.exe scripts/locate_branches.py           # report only
    ./.venv/Scripts/python.exe scripts/locate_branches.py --write   # store them

Nothing is written without `--write`. Coordinates decide what customers are
charged for delivery, so storing them is an explicit act.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from app.config.database import SessionLocal
from app.models.restaurant_location import RestaurantLocation
from app.services.geocoding.base import AddressQuery
from app.services.geocoding.registry import geocoder
from app.services.geocoding.service import locate

logging.disable(logging.INFO)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write", action="store_true", help="store the coordinates that resolved precisely"
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="re-look-up branches that already have coordinates",
    )
    args = parser.parse_args()

    print(f"Geocoder: {geocoder().name}\n")
    located: list[str] = []
    imprecise: list[tuple[str, str]] = []
    missing: list[str] = []

    with SessionLocal() as db:
        branches = db.scalars(
            select(RestaurantLocation).order_by(RestaurantLocation.branch_name)
        ).all()
        for branch in branches:
            label = f"{branch.restaurant.name} · {branch.branch_name}"
            if not args.all and branch.latitude is not None and branch.longitude is not None:
                print(f"  [have]  {label}")
                continue

            point = locate(
                db,
                AddressQuery(
                    line1=branch.address_line_1 or "",
                    line2=branch.address_line_2 or "",
                    city=branch.city or "",
                    state=branch.state or "",
                    postal_code=branch.postal_code or "",
                ),
            )
            if point is None:
                print(f"  [MISS]  {label}")
                print(f"          {branch.address_line_1}, {branch.city}")
                missing.append(label)
                continue
            if not point.is_precise:
                print(f"  [vague] {label}  ({point.confidence.value})")
                print(f"          matched: {point.matched[:76]}")
                imprecise.append((label, point.confidence.value))
                continue

            print(f"  [ok]    {label}  {point.latitude:.5f},{point.longitude:.5f}")
            located.append(label)
            if args.write:
                branch.latitude = point.latitude
                branch.longitude = point.longitude

        if args.write:
            db.commit()

    print(
        f"\n{len(located)} located, {len(imprecise)} too vague to trust, "
        f"{len(missing)} not found."
    )
    if args.write and located:
        print(f"Stored {len(located)}.")
    elif located:
        print("Nothing was stored. Re-run with --write.")

    if imprecise or missing:
        print(
            "\nFix these by hand: open the branch in the admin and paste the\n"
            "latitude and longitude from a map. Right-click the exact spot in\n"
            "Google Maps and the first item on the menu is the pair, ready to\n"
            "copy. Until then their deliveries are priced from a stand-in point."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
