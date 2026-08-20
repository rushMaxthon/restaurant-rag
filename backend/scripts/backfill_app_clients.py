"""Give every existing restaurant a complete app client configuration.

Restaurants created before app clients existed get one; app clients that are
missing a brand colour, minimum supported version, platform identifier, or order
sequence get the missing pieces filled in. Values that are already set are never
overwritten, so the script is idempotent and safe to re-run.

Usage, from `backend/`:

    python -m scripts.backfill_app_clients --dry-run
    python -m scripts.backfill_app_clients
"""

from __future__ import annotations

import argparse
import sys

from sqlalchemy.orm import Session

from app.config.database import SessionLocal
from app.services.app_clients import backfill_app_clients


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill app clients for existing restaurants")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would change without committing anything",
    )
    args = parser.parse_args()

    session: Session = SessionLocal()
    try:
        summary = backfill_app_clients(session)

        for entry in summary.created:
            print(f"created   {entry}")
        for entry in summary.completed:
            print(f"completed {entry}")
        for entry in summary.unchanged:
            print(f"ok        {entry}")

        if args.dry_run:
            session.rollback()
            print(f"\nDry run: {summary.changed_count} app client(s) would change. Nothing was written.")
            return 0

        session.commit()
        print(f"\nDone: {summary.changed_count} app client(s) changed.")
        return 0
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    sys.exit(main())
