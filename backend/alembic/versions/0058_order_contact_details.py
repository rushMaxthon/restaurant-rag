"""Keep the name and phone the customer types at checkout.

The checkout form has always demanded a full name and a phone number, marked
both required, and told the customer "we use this to reach you if the rider
needs directions". Neither reached the server: `OrderCreateRequest` carried
`delivery_address` and `special_instructions` and nothing else, so both fields
were collected, validated in the browser, and dropped on submit.

That is worse than not asking. The rider has no number, the customer believes
they gave one, and nobody finds out until a delivery goes wrong.

Nullable on purpose. Every existing order predates the columns and there is
nothing truthful to backfill them with — the data was never stored — and the
mobile client can go on sending neither until it is updated.

The account's own phone is NOT the same thing: someone ordering for a parent or
to an office gives the number that should ring for THAT delivery, which is why
this belongs on the order rather than being read off the user row.

Revision ID: 0058_order_contact_details
Revises: 0057_seed_dish_images
"""

from alembic import op
import sqlalchemy as sa

revision = "0058_order_contact_details"
down_revision = "0057_seed_dish_images"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("contact_name", sa.String(length=255), nullable=True))
    op.add_column("orders", sa.Column("contact_phone", sa.String(length=32), nullable=True))


def downgrade() -> None:
    op.drop_column("orders", "contact_phone")
    op.drop_column("orders", "contact_name")
