"""who a campaign actually went to, which is what attribution needs

Revision ID: 0069_campaign_recipients
Revises: 0064_marketing_campaign_fields
Create Date: 2026-09-19 00:00:00.000000

Numbered 0069, and renumbered once. It was 0068, chosen to leave 0065-0067
alone because those belonged to a lineage that existed nowhere in this
repository and could not be read. On 2026-09-21 that lineage was introspected
off the shared database and rebuilt as 0065-0068, which took the number this
revision was using — the database turned out to be stamped at its own 0068,
not the 0067 we had recorded. Renumbering was safe precisely because nothing
was ever stamped with the old id: this migration reached the shared database
by having its `upgrade()` run by hand, out of band.

A recipient row is the record of one customer being sent one campaign. It is
what makes three otherwise impossible things possible:

* **Attribution.** "Did this campaign cause an order?" is answerable only
  against the list of who received it, inside the window that followed. A
  count cannot answer it, and the segment cannot either — segment membership
  is recomputed continuously and by the time the report is read it no longer
  describes who was messaged.
* **Frequency capping that is true.** `recently_messaged_user_ids` currently
  infers recent contact from campaign rows. Recipients make it a fact.
* **Honest failure reporting.** Which customers a send failed for, and why,
  rather than one aggregate counter.

`user_id` is ON DELETE CASCADE: a customer who is deleted takes their delivery
record with them, because the row names a person. That loses a little history
on the campaign report, which is the correct trade — the report is about
aggregate performance and the person had a right to be forgotten.

The unique constraint on (campaign_id, user_id) is what makes a retried send
idempotent per recipient: a dispatch that failed halfway and is run again
re-sends to the people it did not reach without messaging the others twice.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0069_campaign_recipients"
down_revision = "0064_marketing_campaign_fields"
branch_labels = None
depends_on = None


TABLE = "push_notification_campaign_recipients"

delivery_state = postgresql.ENUM(
    "PENDING",
    "SENT",
    "FAILED",
    "SKIPPED",
    name="campaign_recipient_state",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    delivery_state.create(bind, checkfirst=True)

    if TABLE not in inspector.get_table_names():
        op.create_table(
            TABLE,
            sa.Column(
                "id",
                postgresql.UUID(as_uuid=True),
                primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column(
                "campaign_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("push_notification_campaigns.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "user_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("state", delivery_state, nullable=False, server_default="PENDING"),
            # Null until the send is attempted. The attribution window opens
            # from this instant, per recipient, not from the campaign's own
            # `sent_at`: a large send spans minutes and the last customer's
            # window must not be shortened by the first customer's timestamp.
            sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
            # The reason this particular recipient did not get it. Kept per row
            # rather than aggregated so the report can say "812 delivered, 3
            # uninstalled" instead of "some failures".
            sa.Column("failure_reason", sa.String(255), nullable=True),
            sa.Column("device_token_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
        )
        op.create_unique_constraint(
            f"uq_{TABLE}_campaign_user", TABLE, ["campaign_id", "user_id"]
        )
        # The attribution query is "orders by these users, after these instants",
        # which reads the table campaign-first and then by recipient.
        op.create_index(f"ix_{TABLE}_campaign", TABLE, ["campaign_id"])
        op.create_index(f"ix_{TABLE}_user_sent", TABLE, ["user_id", "sent_at"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if TABLE in inspector.get_table_names():
        op.drop_table(TABLE)
    delivery_state.drop(bind, checkfirst=True)
