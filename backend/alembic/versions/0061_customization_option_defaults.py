"""Mark the option a customer gets without touching anything, per group.

The chat ordering flow the customer specified is: pick a size, then the agent
states what the dish comes with and its price ("that's chicken tikka, comes
with garlic naan, $14"), then asks whether to change anything. Answering that
truthfully needs a stored fact — which option is "what you get by default" —
that this schema did not have: `menu_item_customization_options` carried
`extra_price`/`is_active`/`sort_order` but nothing marking one option as the
one already included, and `menu_item_customization_groups` only says how many
picks a group needs (`is_required`, `min_selection`, `max_selection`), not
which pick is the default. Without this column the agent could describe a
CHOICE ("pick a spice level") but never a DEFAULT ("comes with medium"), so it
could never truthfully say "comes with X" about anything.

Backfill rule: a group only gets a default when it is both `is_required` AND
`selection_type = 'SINGLE'`. That combination means the customer's cart
*cannot* leave this group empty — one option WILL be on the order — so there
is an honest default to name: the option already priced into
`menu_items.price`/`menu_item_sizes.price` is the cheapest active one in the
group, because the base price was set assuming the cheapest option, not a
paid upgrade. Naming any pricier option as the default would quietly promise
the customer a price the base menu price does not include, and they would
find the gap only at checkout. Ties broken by the owner's own `sort_order`,
the same tiebreak they already use to order options for display, rather than
an arbitrary one this migration invents.

Optional groups (`is_required = false`) and multi-select groups get no
default: the customer is genuinely free to end up with nothing chosen there
("no extra toppings" is a real, valid answer), and picking one option to
pre-select would misrepresent a free choice as something already decided.

Set-based, not a Python loop: "Spice level" alone spans 224 options across its
groups, "Choose your protein" 57, "Crust" 27 — a per-row Python loop over
every option in every restaurant's menu does not scale the way one indexed
`UPDATE ... FROM` does.

Revision ID: 0061_customization_option_defaults
Revises: 0060_customization_group_halves
"""

from alembic import op
import sqlalchemy as sa

revision = "0061_customization_option_defaults"
down_revision = "0060_customization_group_halves"
branch_labels = None
depends_on = None


# `DISTINCT ON` per group, ordered cheapest-first then by the owner's own
# display order, is Postgres's set-based way of picking "the one row I'd have
# picked first if I read the group top to bottom" — no per-row Python loop
# needed even at 224 options in one group.
_BACKFILL_SQL = """
UPDATE menu_item_customization_options AS opt
SET is_default = true
FROM (
    SELECT DISTINCT ON (o.group_id) o.id
    FROM menu_item_customization_options AS o
    JOIN menu_item_customization_groups AS g ON g.id = o.group_id
    WHERE o.is_active = true
      AND g.is_required = true
      AND g.selection_type = 'SINGLE'
    ORDER BY o.group_id, o.extra_price ASC, o.sort_order ASC, o.id ASC
) AS cheapest
WHERE opt.id = cheapest.id
"""


def upgrade() -> None:
    op.add_column(
        "menu_item_customization_options",
        sa.Column(
            "is_default",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.execute(_BACKFILL_SQL)


def downgrade() -> None:
    op.drop_column("menu_item_customization_options", "is_default")
