"""Root-cause explanations on insights, and resolved params on chat turns

Revision ID: 0044_insight_root_cause_chat_params
Revises: 0043_action_outcomes
Create Date: 2026-08-14 19:00:00.000000

Two small additive columns, both needed by Phase 6B:

* ``owner_insights.root_cause`` — why a finding happened, where the operational
  history added in 0042 supports an explanation. Null is the common and honest
  case: most declines have no recorded cause.
* ``owner_chat_messages.skill_params`` — the parameters the router resolved for
  a turn. Chat already stored *which* analysis answered a question but not the
  window or subject it used, so a follow-up like "and last month?" had nothing
  to inherit.

Two new ``owner_insight_type`` labels are added for root-cause findings. They
are added with ``ADD VALUE IF NOT EXISTS`` and are deliberately not *used*
anywhere in this migration: Postgres forbids using a label in the same
transaction that created it.

Every step is guarded so re-running is a no-op.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0044_insight_root_cause_chat_params"
down_revision = "0043_action_outcomes"
branch_labels = None
depends_on = None

NEW_INSIGHT_TYPES = ("STOCKOUT_IMPACT", "SLOW_ACCEPTANCE")


def _columns(bind, table_name: str) -> set[str]:
    return {column["name"] for column in sa.inspect(bind).get_columns(table_name)}


def upgrade() -> None:
    bind = op.get_bind()

    # Enum labels are added outside a transaction block; each is guarded so a
    # partial previous run cannot break this one.
    for label in NEW_INSIGHT_TYPES:
        op.execute(
            sa.text(
                f"ALTER TYPE owner_insight_type ADD VALUE IF NOT EXISTS '{label}'"
            ).execution_options(autocommit=True)
        )

    if "root_cause" not in _columns(bind, "owner_insights"):
        op.add_column("owner_insights", sa.Column("root_cause", sa.Text(), nullable=True))

    if "skill_params" not in _columns(bind, "owner_chat_messages"):
        op.add_column(
            "owner_chat_messages",
            sa.Column(
                "skill_params",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default="{}",
            ),
        )


def downgrade() -> None:
    bind = op.get_bind()

    if "skill_params" in _columns(bind, "owner_chat_messages"):
        op.drop_column("owner_chat_messages", "skill_params")
    if "root_cause" in _columns(bind, "owner_insights"):
        op.drop_column("owner_insights", "root_cause")

    # The enum labels are deliberately left in place. Postgres cannot drop a
    # value from an enum type, and recreating the type would require rewriting
    # every row that references it.
