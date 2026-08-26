"""Per-restaurant theme.

The brand colour previously lived only on `app_clients.branding`, which ties it
to whoever configured the mobile build. It belongs to the restaurant: an owner
should be able to change their own app's look, and a marketplace build needs
somewhere to read a restaurant's colour from that is not its own app client.

Additive and empty by default, so every existing restaurant keeps the platform
default until somebody chooses otherwise.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0048_restaurant_theme"
down_revision = "0047_insight_provenance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "restaurants",
        sa.Column(
            "theme",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
    )


def downgrade() -> None:
    op.drop_column("restaurants", "theme")
