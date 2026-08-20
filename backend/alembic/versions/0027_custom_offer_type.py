"""compatibility shim for missing custom offer type revision

This revision restores a migration ID that some local databases were stamped
with during development, but which is no longer present in the repository.

It intentionally performs no schema changes because the current codebase does
not require any additional database updates for this revision.

Revision ID: 0027_custom_offer_type
Revises: 0025_add_is_countable_to_options
Create Date: 2026-06-16 12:30:00.000000
"""

from __future__ import annotations


revision = "0027_custom_offer_type"
down_revision = "0025_add_is_countable_to_options"
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
