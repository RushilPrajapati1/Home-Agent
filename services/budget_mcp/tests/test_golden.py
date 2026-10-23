"""The design walkthrough on the seeded fixtures (fixtures/golden_scenario.json)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from homefund_budget_mcp import domain
from homefund_budget_mcp.config import CutConfig
from homefund_budget_mcp.domain import SummaryRow

from homefund_contracts.clock import FixedClock
from homefund_contracts.enums import PROTECTED, Category

D = Decimal


def test_golden_cashflow(
    golden: dict[str, Any], clock: FixedClock, summaries: list[SummaryRow]
) -> None:
    expected = golden["expected"]["cashflow"]
    flow = domain.cashflow(summaries, domain.window(clock, 6))
    assert flow.model_dump(mode="json", include={"months", "period_start", "period_end"}) == {
        "months": 6,
        "period_start": expected["period_start"],
        "period_end": expected["period_end"],
    }
    assert flow.take_home_monthly == D("6800.00")
    assert flow.spending_monthly == D("5600.00")
    assert flow.saved_monthly == D("1200.00")
    assert [c.model_dump(mode="json") for c in flow.by_category] == expected["by_category"]
    assert {b.category.value: str(b.monthly_amount) for b in flow.fixed_bills} == expected[
        "fixed_by_category"
    ]
    assert flow.fixed_bills_monthly == D(expected["fixed_bills_monthly"])


def test_golden_projection(golden: dict[str, Any], clock: FixedClock) -> None:
    exp = golden["expected"]
    start, target = D(exp["saved_so_far"]), D(exp["home_cost"]["cash_needed"])
    this_month = domain.current_month(clock)

    pace = domain.project_savings(start, D("1200"), target, this_month)
    assert pace.months_to_goal == 36
    assert pace.reach_month == date(2029, 10, 1)
    assert pace.points[0].month == date(2026, 10, 1)
    assert pace.points[0].balance == start
    assert len(pace.points) == 37

    needed = D(exp["deadline"]["monthly_needed"])
    assert needed == D("2145.00")
    deadline = domain.project_savings(start, needed, target, this_month)
    assert deadline.months_to_goal == 20
    assert deadline.reach_month == date.fromisoformat(exp["deadline"]["move_in_month"])


def test_golden_cuts(
    golden: dict[str, Any], clock: FixedClock, summaries: list[SummaryRow]
) -> None:
    exp = golden["expected"]
    gap = D(exp["deadline"]["gap_per_month"])
    assert gap == D("945.00")
    win = domain.window(clock, 6)
    averages = domain.category_averages(summaries, win)
    out = domain.solve_cuts(gap, set(PROTECTED), averages, win.months, CutConfig())

    assert out.meets_gap
    assert out.total_monthly >= D(exp["cuts"]["min_total_monthly"])
    assert not {c.category for c in out.cuts} & PROTECTED
    assert {c.value for c in PROTECTED} == set(exp["cuts"]["protected_untouched"])
    spent = {a.category: a.monthly_avg for a in averages}
    assert all(c.amount <= spent[c.category] for c in out.cuts)

    # With the cuts, $1,200 + cuts a month reaches the goal by the move-in month.
    monthly = D(exp["cashflow"]["saved_monthly"]) + out.total_monthly
    proj = domain.project_savings(
        D(exp["saved_so_far"]),
        monthly,
        D(exp["home_cost"]["cash_needed"]),
        domain.current_month(clock),
    )
    assert proj.reach_month is not None
    assert proj.reach_month <= date.fromisoformat(exp["deadline"]["move_in_month"])


def test_golden_subscriptions_cap_matches_walkthrough(
    clock: FixedClock, summaries: list[SummaryRow]
) -> None:
    win = domain.window(clock, 6)
    averages = domain.category_averages(summaries, win)
    cands = {c.category: c for c in domain.candidates(averages, 6, set(PROTECTED), CutConfig())}
    subs = cands[Category.SUBSCRIPTIONS]
    assert subs.subscriptions == 7
    assert subs.detail(subs.cap) == "Subscriptions, 7 down to 3"  # the walkthrough's "7 down to 3"
    assert cands[Category.TRAVEL_FUND].cap == D("280.00")
    assert cands[Category.DINING_AND_DELIVERY].cap == D("300.00")
