#!/usr/bin/env python
"""Generate embeddings for menu items that do not have them.

Menu items are only embedded when someone creates or edits one through the admin
API, so every item that predates the feature has no vector and is invisible to
semantic search. This is how you fix that, and how you rebuild the table after
changing embedding provider.

Runs in-process rather than queueing Celery work, so it can be used on a machine
with no worker running and reports its result on the spot.

    # embed everything still missing a vector, with the configured provider
    python scripts/backfill_embeddings.py

    # one restaurant only
    python scripts/backfill_embeddings.py --restaurant-id <uuid>

    # after switching EMBEDDING_PROVIDER: rebuild the whole table
    python scripts/backfill_embeddings.py --all --force

    # see what would happen
    python scripts/backfill_embeddings.py --dry-run
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

# Same import-root convention the test suite uses, so this runs from anywhere.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import func, select  # noqa: E402

from app.config.database import SessionLocal  # noqa: E402
from app.models.menu_embedding import MenuEmbedding  # noqa: E402
from app.models.menu_item import MenuItem  # noqa: E402
from app.services.embeddings import embedding_signature  # noqa: E402
from app.tasks.embed import backfill_menu_embeddings  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--restaurant-id", default=None, help="Limit to one restaurant")
    parser.add_argument(
        "--all",
        action="store_true",
        help="Re-embed every item, not only those missing a vector. Required "
        "after a provider change, because vectors from different models are "
        "not comparable.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Proceed even when the stored vectors came from a different "
        "provider. Pair with --all so the table ends in one vector space.",
    )
    parser.add_argument("--limit", type=int, default=None, help="Cap items processed")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would be embedded and exit without calling a provider.",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
    )

    print(f"Embedding provider : {embedding_signature()}")

    with SessionLocal() as db:
        total = db.scalar(select(func.count()).select_from(MenuItem)) or 0
        embedded = db.scalar(select(func.count()).select_from(MenuEmbedding)) or 0
    print(f"Menu items         : {total}")
    print(f"Already embedded   : {embedded}")
    print(f"Missing            : {max(total - embedded, 0)}")

    if args.dry_run:
        scope = "every item" if args.all else "items with no vector"
        print(f"\nDry run — would embed {scope}. Nothing called, nothing written.")
        return 0

    result = backfill_menu_embeddings(
        restaurant_id=args.restaurant_id,
        only_missing=not args.all,
        force=args.force,
        limit=args.limit,
    )

    print()
    for key, value in result.items():
        print(f"  {key}: {value}")

    if result.get("status") == "refused":
        print(
            "\nRefused: the stored vectors were produced by a different provider.\n"
            "Re-run with --all --force to rebuild the table in one vector space."
        )
        return 2
    return 0 if not result.get("failed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
