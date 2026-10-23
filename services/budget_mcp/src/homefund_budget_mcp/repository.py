"""Read-only data access for budget-mcp. Postgres via the mcp_ro role, or any fake."""

from __future__ import annotations

import os
from datetime import date
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from sqlalchemy import Engine, create_engine, text

from homefund_budget_mcp.domain import SummaryRow
from homefund_contracts.enums import Category
from homefund_db.config import MCP_URL_VAR

RO_URL_VAR = "DATABASE_URL_RO"
"""budget-mcp's read-only URL. Falls back to the foundation's DATABASE_URL_MCP (same role)."""


class BudgetRepository(Protocol):
    def monthly_summaries(self, user_id: UUID, start: date, end: date) -> list[SummaryRow]:
        """Rows of monthly_summaries for months in [start, end]."""
        ...

    def saved_so_far(self, user_id: UUID) -> Decimal | None:
        """The saved amount on the user's latest goal, or None without a goal."""
        ...


def read_only_url(env: dict[str, str] | None = None) -> str:
    source = os.environ if env is None else env
    for var in (RO_URL_VAR, MCP_URL_VAR):
        url = source.get(var, "").strip()
        if url:
            return url
    raise RuntimeError(f"{RO_URL_VAR} (or {MCP_URL_VAR}) is not set; copy .env.example to .env")


class PostgresRepository:
    """Reads monthly_summaries and goals. Every transaction is opened READ ONLY as well."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine.execution_options(postgresql_readonly=True)

    @classmethod
    def from_env(cls) -> PostgresRepository:
        return cls(create_engine(read_only_url(), pool_pre_ping=True))

    def monthly_summaries(self, user_id: UUID, start: date, end: date) -> list[SummaryRow]:
        query = text(
            "SELECT month, category, total, count FROM monthly_summaries "
            "WHERE user_id = :user_id AND month BETWEEN :start AND :end"
        )
        with self._engine.connect() as conn:
            rows = conn.execute(query, {"user_id": user_id, "start": start, "end": end}).all()
        return [SummaryRow(r.month, Category(r.category), r.total, r.count) for r in rows]

    def saved_so_far(self, user_id: UUID) -> Decimal | None:
        query = text(
            "SELECT saved FROM goals WHERE user_id = :user_id "
            "ORDER BY created_at DESC, id DESC LIMIT 1"
        )
        with self._engine.connect() as conn:
            saved: Decimal | None = conn.execute(query, {"user_id": user_id}).scalar()
        return saved
