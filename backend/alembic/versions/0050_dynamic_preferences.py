"""Preference questions, options and answers as data.

The onboarding wizard was five steps hardcoded twice - once in the mobile app
and once in the customer website - answering into eleven typed columns on
`user_preferences`. Adding a question meant a migration, a schema change and a
release of both clients, so in practice nobody ever added one.

This moves the *structure* of the questionnaire into the database while leaving
its *meaning* declared on each question. `signal_role` is what tells the
recommender how to read an answer: a question tagged `DIET` still drives the
veg matching it drives today, and a question tagged `NONE` is stored and
queryable but does not touch scoring. That is deliberately the slot a future
taste vector consumes - new questions become useful without anyone having to
re-tune the ranking.

Additive and non-destructive. `user_preferences` is untouched here and keeps
working exactly as it does today; the follow-up seed backfills these tables from
it, and the projection keeps it in sync afterwards. Nothing reads these tables
until the API lands, so this migration changes no behaviour on its own.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0050_dynamic_preferences"
down_revision = "0049_menu_item_rating"
branch_labels = None
depends_on = None


preference_input_type = postgresql.ENUM(
    "SINGLE_SELECT",
    "MULTI_SELECT",
    name="preference_input_type",
    create_type=False,
)

# How the recommender is allowed to read a question's answers. Everything the
# scoring engine understands today has a value here; `NONE` is the escape hatch
# for a question that is collected but not scored.
preference_signal_role = postgresql.ENUM(
    "CUISINE",
    "DISLIKED_CUISINE",
    "DIET",
    "SPICE",
    "BUDGET",
    "FAVORITE_ITEM",
    "NONE",
    name="preference_signal_role",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    preference_input_type.create(bind, checkfirst=True)
    preference_signal_role.create(bind, checkfirst=True)

    op.create_table(
        "preference_questions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        # NULL means the question belongs to the platform and every restaurant
        # inherits it. A non-null value is a question that restaurant authored.
        sa.Column(
            "restaurant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("restaurants.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("key", sa.String(64), nullable=False),
        sa.Column("prompt", sa.String(255), nullable=False),
        sa.Column("help_text", sa.Text(), nullable=True),
        sa.Column("input_type", preference_input_type, nullable=False),
        sa.Column("is_required", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("min_selections", sa.Integer(), nullable=False, server_default="0"),
        # NULL means unlimited, which is what a multi-select without a cap wants.
        sa.Column("max_selections", sa.Integer(), nullable=True),
        sa.Column(
            "allows_free_text",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "signal_role",
            preference_signal_role,
            nullable=False,
            server_default="NONE",
        ),
        sa.Column("display_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        # Soft delete. A hard delete would strand every answer that points here,
        # and the answer FK below refuses it anyway.
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    # Scoped uniqueness, and only among the living: a restaurant may reuse a key
    # the platform also uses (that is how an override-by-key works), and a
    # deleted question must not block a new one taking its name back.
    op.create_index(
        "uq_preference_questions_scope_key",
        "preference_questions",
        ["restaurant_id", "key"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_preference_questions_lookup",
        "preference_questions",
        ["restaurant_id", "is_active", "display_order"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.create_table(
        "preference_options",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "question_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("preference_questions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("value", sa.String(64), nullable=False),
        sa.Column("label", sa.String(120), nullable=False),
        sa.Column("help_text", sa.Text(), nullable=True),
        # Everything the scoring engine needs to interpret this option without a
        # Python constant: `{"is_veg": true}` on a diet option, `{"amount": 420}`
        # on a budget tier. This is what lets an owner add an option that
        # actually affects ranking.
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("display_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "uq_preference_options_question_value",
        "preference_options",
        ["question_id", "value"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_preference_options_lookup",
        "preference_options",
        ["question_id", "is_active", "display_order"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    # How a restaurant hides a platform question without touching it. Deleting
    # or deactivating the global row would remove it for every other tenant, so
    # the opt-out is recorded per restaurant instead.
    op.create_table(
        "preference_question_overrides",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "restaurant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("restaurants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "question_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("preference_questions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("is_hidden", sa.Boolean(), nullable=False, server_default=sa.true()),
        # Lets a restaurant move an inherited question without copying it.
        sa.Column("display_order", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "restaurant_id",
            "question_id",
            name="uq_preference_question_overrides_scope",
        ),
    )

    op.create_table(
        "user_preference_answers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # RESTRICT, not CASCADE: a question being retired must never silently
        # take a customer's answers with it. Retiring is a soft delete, and this
        # constraint is what makes that the only option.
        sa.Column(
            "question_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("preference_questions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        # Null for a free-text answer, which is how "favourite items" keeps
        # accepting a dish that is not on the list.
        sa.Column(
            "option_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("preference_options.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("free_text", sa.String(120), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "option_id IS NOT NULL OR free_text IS NOT NULL",
            name="ck_user_preference_answers_has_value",
        ),
    )
    op.create_index(
        "ix_user_preference_answers_user",
        "user_preference_answers",
        ["user_id"],
    )
    # One row per chosen option. Two partial indexes rather than one constraint,
    # because Postgres treats NULLs as distinct - without the second, a customer
    # could store "Pasta" as a favourite five times.
    op.create_index(
        "uq_user_preference_answers_option",
        "user_preference_answers",
        ["user_id", "question_id", "option_id"],
        unique=True,
        postgresql_where=sa.text("option_id IS NOT NULL"),
    )
    op.create_index(
        "uq_user_preference_answers_free_text",
        "user_preference_answers",
        ["user_id", "question_id", sa.text("lower(free_text)")],
        unique=True,
        postgresql_where=sa.text("option_id IS NULL"),
    )


def downgrade() -> None:
    op.drop_table("user_preference_answers")
    op.drop_table("preference_question_overrides")
    op.drop_table("preference_options")
    op.drop_index("ix_preference_questions_lookup", table_name="preference_questions")
    op.drop_index("uq_preference_questions_scope_key", table_name="preference_questions")
    op.drop_table("preference_questions")

    bind = op.get_bind()
    preference_signal_role.drop(bind, checkfirst=True)
    preference_input_type.drop(bind, checkfirst=True)
