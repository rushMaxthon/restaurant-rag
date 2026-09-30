"""Find the coordinates of every branch, and say plainly which ones failed.

A branch address is written once and then used by every order that branch ever
takes, so it is worth locating properly, once, rather than on a customer's
critical path. Run this after onboarding a restaurant.

It asks progressively less specific questions until one is answered — the full
address, then the neighbourhood, then the branch name, then the postcode — and
stores whatever comes back TOGETHER WITH how precise it is. See
`services/geocoding/branches.py` for why: a branch address here names a building
no map has heard of, with a real neighbourhood on the end of it.

What it does NOT do is pretend. A geocoder always answers something, so a
locality-level hit is stored as a locality-level hit and nothing later mistakes
it for the door. That is still worth having: a neighbourhood point is right to
within a kilometre or two, where an unlocated branch is priced from a stand-in
in another city, or not priced at all.

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
from app.services.geocoding.branches import locate_branch
from app.services.geocoding.registry import geocoder

logging.disable(logging.INFO)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write", action="store_true", help="store the coordinates that resolved precisely"
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="re-look-up branches that already have coordinates from a lookup",
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
            located_already = branch.latitude is not None and branch.longitude is not None
            # A pair with no confidence was typed in by a person, who pointed at
            # their own front door. `--all` re-runs LOOKUPS; it must never
            # overwrite that, or one bulk run silently undoes every correction
            # anybody has made.
            by_hand = located_already and not (branch.geocode_confidence or "").strip()
            if located_already and (by_hand or not args.all):
                print(f"  [{'hand' if by_hand else 'have'}]  {label}")
                continue

            found = locate_branch(db, branch)
            if found is None:
                print(f"  [MISS]  {label}")
                print(f"          {branch.address_line_1}, {branch.city}")
                missing.append(label)
                continue

            point = found.point
            mark = "ok" if point.is_precise else "vague"
            print(
                f"  [{mark:<5}] {label}  {point.latitude:.5f},{point.longitude:.5f}"
                f"  {point.confidence.value} via {found.matched_on}"
            )
            print(f"          matched: {point.matched[:76]}")
            (located if point.is_precise else imprecise).append(
                label if point.is_precise else (label, f"{point.confidence.value} via {found.matched_on}")
            )
            # Stored either way, with the confidence that came back.
            #
            # A neighbourhood-level point is worth keeping: it puts the branch
            # within a kilometre or two, which is the difference between a
            # delivery quote that is roughly right and one computed from a
            # stand-in in another city. What it is NOT is the door, and the
            # confidence beside it is what stops anything treating it as one.
            if args.write:
                branch.latitude = point.latitude
                branch.longitude = point.longitude
                branch.geocode_confidence = point.confidence.value

        if args.write:
            db.commit()

    print(
        f"\n{len(located)} precise, {len(imprecise)} only roughly placed, "
        f"{len(missing)} not found."
    )
    if args.write:
        print(f"Stored {len(located) + len(imprecise)}, each with its own confidence.")
    elif located or imprecise:
        print("Nothing was stored. Re-run with --write.")

    if imprecise:
        print(
            "\nThe roughly-placed ones ARE stored and usable: a neighbourhood point\n"
            "gives a distance right to within a kilometre or two, which is the\n"
            "difference between a quote that is roughly right and one computed\n"
            "from a stand-in in another city. They are not the door, so they are\n"
            "never treated as exact. To make one exact, open the branch in the\n"
            "admin and paste the pair from a map — right-click the door in Google\n"
            "Maps and the first item on the menu is the coordinates. A pasted pair\n"
            "is stored with NO confidence, which means \"a person put this here\"\n"
            "and is trusted above any geocoder."
        )
    if missing:
        print(
            "\nThe not-found ones have no point at all. Their deliveries fall back\n"
            "to the branch's flat fee until somebody pastes a pair in."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
