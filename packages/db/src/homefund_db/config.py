"""Database URLs by role. Every value comes from the environment (see .env.example)."""

from __future__ import annotations

import os

from sqlalchemy import Engine, create_engine

ADMIN_URL_VAR = "DATABASE_URL_ADMIN"  # migrations and role setup only
APP_URL_VAR = "DATABASE_URL_APP"  # app_rw: api, agent checkpointer, importer, ingest, seed
MCP_URL_VAR = "DATABASE_URL_MCP"  # mcp_ro: budget-mcp, guides-mcp


def database_url(var: str) -> str:
    url = os.environ.get(var, "").strip()
    if not url:
        raise RuntimeError(f"{var} is not set; copy .env.example to .env")
    return url


def make_engine(var: str, **kwargs: object) -> Engine:
    return create_engine(database_url(var), pool_pre_ping=True, **kwargs)
