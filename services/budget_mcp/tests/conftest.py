"""Fakes for budget-mcp tests: monthly_summaries built from the fixture CSV, no database."""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from homefund_budget_mcp.domain import SummaryRow

from homefund_contracts.clock import FixedClock
from homefund_contracts.enums import Category

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures"
DEDUPE_FIELDS = ("account", "posted_on", "amount", "raw_description", "reference")


class FakeRepository:
    def __init__(
        self, rows: dict[UUID, list[SummaryRow]], saved: dict[UUID, Decimal] | None = None
    ) -> None:
        self.rows = rows
        self.saved = saved or {}

    def monthly_summaries(self, user_id: UUID, start: date, end: date) -> list[SummaryRow]:
        return [r for r in self.rows.get(user_id, []) if start <= r.month <= end]

    def saved_so_far(self, user_id: UUID) -> Decimal | None:
        return self.saved.get(user_id)


def fixture_summaries() -> list[SummaryRow]:
    """What `make seed` puts in monthly_summaries: rows deduped like the seed's hash."""
    seen: set[tuple[str, ...]] = set()
    totals: dict[tuple[date, Category], Decimal] = defaultdict(Decimal)
    counts: dict[tuple[date, Category], int] = defaultdict(int)
    with (FIXTURES / "demo_user" / "transactions_labeled.csv").open(encoding="utf-8") as fh:
        for rec in csv.DictReader(fh):
            key = tuple(rec[k] for k in DEDUPE_FIELDS)
            if key in seen:
                continue
            seen.add(key)
            month = date.fromisoformat(rec["posted_on"]).replace(day=1)
            cat = Category(rec["category"])
            totals[month, cat] += Decimal(rec["amount"])
            counts[month, cat] += 1
    return [SummaryRow(m, c, totals[m, c], counts[m, c]) for m, c in totals]


@pytest.fixture(scope="session")
def golden() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(
        (FIXTURES / "golden_scenario.json").read_text(encoding="utf-8")
    )
    return data


@pytest.fixture
def clock(golden: dict[str, Any]) -> FixedClock:
    return FixedClock(date.fromisoformat(golden["clock"]["date"]))


@pytest.fixture
def user_id(golden: dict[str, Any]) -> UUID:
    return UUID(golden["user_id"])


@pytest.fixture
def summaries() -> list[SummaryRow]:
    return fixture_summaries()


@pytest.fixture
def fake_repo() -> type[FakeRepository]:
    return FakeRepository


@pytest.fixture
def repo(golden: dict[str, Any], user_id: UUID) -> FakeRepository:
    saved = Decimal(golden["request"]["goal"]["saved"])
    return FakeRepository({user_id: fixture_summaries()}, {user_id: saved})
