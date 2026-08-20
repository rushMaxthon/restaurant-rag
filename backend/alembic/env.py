from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool, text

from app.config import get_settings
from app.config.database import initialize_pg_extensions
from app.models import Base

config = context.config
settings = get_settings()

config.set_main_option("sqlalchemy.url", settings.sqlalchemy_database_uri)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# Alembic defaults the version column to VARCHAR(32), but this project has a
# revision id longer than that ("0031_personalized_recommendation_snapshots",
# 42 chars), so a fresh database fails partway through the upgrade. Existing
# databases already carry a widened column; this brings new ones in line.
VERSION_TABLE_COLUMN_WIDTH = 255


def widen_alembic_version_column(connection) -> None:
    connection.execute(
        text(
            "CREATE TABLE IF NOT EXISTS alembic_version ("
            f"version_num VARCHAR({VERSION_TABLE_COLUMN_WIDTH}) NOT NULL, "
            "CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num))"
        )
    )
    connection.execute(
        text(
            "ALTER TABLE alembic_version ALTER COLUMN version_num "
            f"TYPE VARCHAR({VERSION_TABLE_COLUMN_WIDTH})"
        )
    )
    # Must commit, like initialize_pg_extensions does: leaving this transaction
    # open would swallow Alembic's own commit and silently roll back the
    # entire upgrade while still exiting successfully.
    connection.commit()


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
        compare_server_default=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        initialize_pg_extensions(connection)
        widen_alembic_version_column(connection)
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
