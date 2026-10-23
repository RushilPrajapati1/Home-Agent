"""PostgresRepository against the seeded local database (`make up migrate seed`)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from homefund_budget_mcp import domain
from homefund_budget_mcp.config import CutConfig
from homefund_budget_mcp.repository import PostgresRepository, read_only_url
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from homefund_contracts.clock import FixedClock
from homefund_contracts.enums import PROTECTED

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def pg() -> PostgresRepository:
    return PostgresRepository(create_engine(read_only_url()))


def test_golden_numbers_from_postgres(
    pg: PostgresRepository, golden: dict[str, Any], clock: FixedClock, user_id: UUID
) -> None:
    win = domain.window(clock, 6)
    rows = pg.monthly_summaries(user_id, win.start, win.end)
    flow = domain.cashflow(rows, win)
    assert flow.saved_monthly == Decimal("1200.00")
    assert [c.model_dump(mode="json") for c in flow.by_category] == golden["expected"]["cashflow"][
        "by_category"
    ]
    assert pg.saved_so_far(user_id) == Decimal("18000.00")
    cuts = domain.solve_cuts(Decimal("945"), set(PROTECTED), flow.by_category, 6, CutConfig())
    assert cuts.meets_gap


def test_window_bounds_are_inclusive(pg: PostgresRepository, user_id: UUID) -> None:
    rows = pg.monthly_summaries(user_id, date(2026, 9, 1), date(2026, 9, 1))
    assert rows and {r.month for r in rows} == {date(2026, 9, 1)}


def test_connection_cannot_write() -> None:
    engine = PostgresRepository(create_engine(read_only_url()))._engine
    with engine.connect() as conn, pytest.raises(DBAPIError):
        conn.execute(text("DELETE FROM goals"))
