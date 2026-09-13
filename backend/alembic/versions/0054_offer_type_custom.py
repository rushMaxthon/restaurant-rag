"""Add CUSTOM to the personalized_offer_type enum.

`PersonalizedOfferType.CUSTOM` exists in Python and is written by the
owner-authored offer path, but the Postgres enum was never given the label — so
any query touching an offer of that type died with

    invalid input value for enum personalized_offer_type: "CUSTOM"

and, because the failure aborts the surrounding transaction, took the whole
request with it. That is what made "is there any offer today" return a 500 in
the customer chat rather than an answer.

ADD VALUE cannot run inside a transaction block on older servers, hence the
autocommit block. IF NOT EXISTS keeps this safe to re-run.

Revision ID: 0054_offer_type_custom
Revises: 0053_orders_currency_cad
"""

from alembic import op

revision = "0054_offer_type_custom"
down_revision = "0053_orders_currency_cad"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE personalized_offer_type ADD VALUE IF NOT EXISTS 'CUSTOM'")


def downgrade() -> None:
    # Postgres cannot drop a value from an enum. Removing it would mean
    # rebuilding the type and rewriting every dependent column, which is far
    # more destructive than leaving an unused label in place.
    pass
