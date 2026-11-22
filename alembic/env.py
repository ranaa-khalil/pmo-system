"""Alembic environment — wired to the app's Base.metadata and PMO_DATABASE_URL.

URL resolution order: a Config override (tests/CI set sqlalchemy.url directly)
wins, then the PMO_DATABASE_URL env var, then the app's settings (PostgreSQL
in prod, SQLite for local dev without Docker).
"""
import os
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

import app.models  # noqa: F401 — register all models with Base.metadata
from alembic import context
from app.database import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _database_url() -> str:
    """Config override > PMO_DATABASE_URL > the app's settings."""
    url = config.get_main_option("sqlalchemy.url")
    if url:
        return url
    env_url = os.getenv("PMO_DATABASE_URL")
    if env_url:
        return env_url
    from app.config import settings

    return settings.database_url


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (emit SQL to stdout, no DB connection)."""
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode (sync engine, real connection)."""
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = _database_url()
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
