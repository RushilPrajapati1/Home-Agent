"""Alembic environment. Migrations run as the admin role from DATABASE_URL_ADMIN."""

from __future__ import annotations

from alembic import context
from sqlalchemy import engine_from_config, pool

from homefund_db.config import ADMIN_URL_VAR, database_url
from homefund_db.models import Base

config = context.config
target_metadata = Base.metadata


def _url() -> str:
    # Tests pass an explicit URL via config attributes; everything else uses the env.
    explicit = config.attributes.get("url")
    return str(explicit) if explicit else database_url(ADMIN_URL_VAR)


def run_migrations_offline() -> None:
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        {"sqlalchemy.url": _url()}, prefix="sqlalchemy.", poolclass=pool.NullPool
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
