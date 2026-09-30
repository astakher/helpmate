# Stand-in for Workstream B - not part of the Part C deliverable
"""Alembic environment: async (asyncpg), raw-SQL migrations, URL from settings."""

from __future__ import annotations

import asyncio

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

from helpmate.settings import Settings

config = context.config


def _url() -> str:
    # programmatic runs pass the URL in attributes (no ConfigParser % interpolation issues)
    url = config.attributes.get("url") or Settings().database_url
    if not url:
        raise SystemExit("HELPMATE_DATABASE_URL isn't set (see .env.example).")
    return url.replace("postgresql://", "postgresql+asyncpg://", 1)


def _run(connection) -> None:
    context.configure(connection=connection, target_metadata=None)
    with context.begin_transaction():
        context.run_migrations()


async def _run_online() -> None:
    engine = create_async_engine(_url())
    async with engine.connect() as connection:
        await connection.run_sync(_run)
    await engine.dispose()


if context.is_offline_mode():
    context.configure(url=_url(), literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    asyncio.run(_run_online())
