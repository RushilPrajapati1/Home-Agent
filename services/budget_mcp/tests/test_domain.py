from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from homefund_budget_mcp import domain
from homefund_budget_mcp.config import CutConfig
from homefund_budget_mcp.domain import SummaryRow

from homefund_contracts.clock import FixedClock
from homefund_contracts.domain import CategorySpend
from homefund_contracts.enums import PROTECTED, Category, Ease

D = Decimal
C = Category
CLOCK = FixedClock(date(2026, 10, 15))


def rows() -> list[SummaryRow]:
    """Three months: Jul-Sep 2026, plus a June row outside a 3-month window."""
    out = [SummaryRow(date(2026, 6, 1), C.DINING_AND_DELIVERY, D("-9999.00"), 99)]
    for m in (7, 8, 9):
        month = date(2026, m, 1)
        out += [
            SummaryRow(month, C.INCOME, D("5000.00"), 2),
            SummaryRow(month, C.TRANSFER, D("-1000.00"), 1),
            SummaryRow(month, C.RENT, D("-2000.00"), 1),
            SummaryRow(month, C.DINING_AND_DELIVERY, D(f"-{300 + m}.00"), 10 + m),
            SummaryRow(month, C.SUBSCRIPTIONS, D("-50.00"), 5),
        ]
    out.append(SummaryRow(date(2026, 9, 1), C.UTILITIES, D("-100.00"), 1))
    return out


def test_window_is_last_full_months_before_clock() -> None:
    win = domain.window(CLOCK, 6)
    assert (win.start, win.end) == (date(2026, 4, 1), date(2026, 9, 1))
    jan = domain.window(FixedClock(date(2026, 1, 1)), 3)
    assert (jan.start, jan.end) == (date(2025, 10, 1), date(2025, 12, 1))


def test_cashflow_averages_and_excludes_transfer() -> None:
    flow = domain.cashflow(rows(), domain.window(CLOCK, 3))
    assert flow.period_start == date(2026, 7, 1)
    assert flow.period_end == date(2026, 9, 1)
    assert flow.take_home_monthly == D("5000.00")
    # Rent 2000 + Dining (307+308+309)/3 = 308 + Subscriptions 50 + Utilities 100/3 = 33.33
    assert flow.spending_monthly == D("2391.33")
    assert flow.saved_monthly == D("2608.67")
    assert [c.category for c in flow.by_category] == [
        C.RENT,
        C.DINING_AND_DELIVERY,
        C.SUBSCRIPTIONS,
        C.UTILITIES,
    ]
    dining = flow.by_category[1]
    assert dining.monthly_avg == D("308.00")
    assert dining.transactions == 17 + 18 + 19
    assert {b.category for b in flow.fixed_bills} == {C.RENT, C.UTILITIES}
    assert flow.fixed_bills_monthly == D("2033.33")


def test_cashflow_divides_by_window_even_with_missing_months() -> None:
    only_sept = [SummaryRow(date(2026, 9, 1), C.INCOME, D("600.00"), 1)]
    flow = domain.cashflow(only_sept, domain.window(CLOCK, 6))
    assert flow.take_home_monthly == D("100.00")
    assert flow.by_category == []


def test_spending_by_category_records_and_text() -> None:
    out = domain.spending_by_category(rows(), domain.window(CLOCK, 3))
    assert out.months == 3
    assert all(r.category != C.TRANSFER for r in out.records)
    assert len(out.records) == 3 * 4 + 1
    assert [r.month for r in out.records] == sorted(r.month for r in out.records)
    dining = next(
        r for r in out.records if r.category == C.DINING_AND_DELIVERY and r.month.month == 9
    )
    assert dining.total == D("309.00")
    assert dining.text == "Dining and delivery · Sep 2026 · $309 · 19 purchases"
    income = next(r for r in out.records if r.category == C.INCOME)
    assert income.total == D("5000.00")
    assert income.text == "Income · Jul 2026 · $5,000 · 2 deposits"
    assert out.averages == domain.category_averages(rows(), domain.window(CLOCK, 3))


def test_summary_text_singular_and_rounding() -> None:
    text = domain.summary_text(date(2026, 3, 1), C.RENT, D("612.50"), 1)
    assert text == "Rent · Mar 2026 · $613 · 1 purchase"


def test_fixed_bills_only_protected_categories() -> None:
    averages = domain.category_averages(rows(), domain.window(CLOCK, 3))
    bills = domain.fixed_bills(averages)
    assert [(b.name, b.monthly_amount) for b in bills.bills] == [
        ("Rent", D("2000.00")),
        ("Utilities", D("33.33")),
    ]
    assert bills.total_monthly == D("2033.33")
    assert all(b.category in PROTECTED for b in bills.bills)


def test_project_savings_reaches_target() -> None:
    out = domain.project_savings(D("100"), D("30"), D("200"), date(2026, 10, 1))
    assert out.months_to_goal == 4
    assert out.reach_month == date(2027, 2, 1)
    assert [p.balance for p in out.points] == [D(100), D(130), D(160), D(190), D(220)]
    assert out.points[0].month == date(2026, 10, 1)
    assert all(p.target == D("200") for p in out.points)


def test_project_savings_exact_hit_and_already_there() -> None:
    exact = domain.project_savings(D("0"), D("50"), D("100"), date(2026, 11, 1))
    assert exact.months_to_goal == 2
    assert exact.points[-1].balance == D("100")
    done = domain.project_savings(D("500"), D("0"), D("100"), date(2026, 11, 1))
    assert done.months_to_goal == 0
    assert done.reach_month == date(2026, 11, 1)
    assert len(done.points) == 1


def test_project_savings_never_without_saving() -> None:
    out = domain.project_savings(D("10"), D("0"), D("100"), date(2026, 10, 1))
    assert out.months_to_goal is None
    assert out.reach_month is None
    assert [p.balance for p in out.points] == [D("10")]


def test_project_savings_truncates_chart_not_answer() -> None:
    out = domain.project_savings(D("0"), D("1"), D("10000"), date(2026, 10, 1))
    assert out.months_to_goal == 10000
    assert out.reach_month == date(2860, 2, 1)
    assert len(out.points) == domain.MAX_PROJECTION_POINTS


def spend(category: Category, avg: str, transactions: int = 6) -> CategorySpend:
    return CategorySpend(category=category, monthly_avg=D(avg), transactions=transactions)


AVERAGES = [
    spend(C.RENT, "2000.00"),
    spend(C.DINING_AND_DELIVERY, "400.00", 60),
    spend(C.TRAVEL_FUND, "200.00"),
    spend(C.SUBSCRIPTIONS, "100.00", 30),  # 5 subscriptions at $20
    spend(C.GROCERIES, "500.00", 40),
    spend(C.INCOME, "5000.00"),
]


def test_candidate_caps() -> None:
    caps = {c.category: c.cap for c in domain.candidates(AVERAGES, 6, set(PROTECTED), CutConfig())}
    assert caps == {
        C.DINING_AND_DELIVERY: D("200.00"),
        C.TRAVEL_FUND: D("200.00"),
        C.SUBSCRIPTIONS: D("60.00"),  # 3 of 5 (60%)
        C.GROCERIES: D("250.00"),
    }


def test_solve_cuts_single_easy_cut() -> None:
    out = domain.solve_cuts(D("150"), set(PROTECTED), AVERAGES, 6, CutConfig())
    assert [(c.category, c.amount) for c in out.cuts] == [(C.TRAVEL_FUND, D("150"))]
    assert out.meets_gap and out.shortfall_monthly == 0
    assert out.cuts[0].ease == Ease.EASY
    assert out.cuts[0].new_monthly == D("50.00")


def test_solve_cuts_fewest_then_easiest_and_trims_last() -> None:
    out = domain.solve_cuts(D("380"), set(PROTECTED), AVERAGES, 6, CutConfig())
    # Two cuts suffice; Travel+Dining (ease 1+3) beats Travel+Groceries (1+5).
    assert [(c.category, c.amount) for c in out.cuts] == [
        (C.TRAVEL_FUND, D("200.00")),
        (C.DINING_AND_DELIVERY, D("180.00")),
    ]
    assert out.total_monthly == D("380.00")


def test_solve_cuts_subscriptions_in_whole_steps() -> None:
    protected = set(PROTECTED) | {C.GROCERIES}
    out = domain.solve_cuts(D("230"), protected, AVERAGES, 6, CutConfig())
    assert [(c.category, c.amount) for c in out.cuts] == [
        (C.TRAVEL_FUND, D("200.00")),
        (C.SUBSCRIPTIONS, D("40.00")),
    ]
    assert out.cuts[1].detail == "Subscriptions, 5 down to 3"
    assert out.total_monthly == D("240.00")


def test_solve_cuts_shortfall_returns_everything_at_cap() -> None:
    out = domain.solve_cuts(D("1000"), set(PROTECTED), AVERAGES, 6, CutConfig())
    assert out.total_monthly == D("710.00")
    assert not out.meets_gap
    assert out.shortfall_monthly == D("290.00")
    assert [c.category for c in out.cuts] == [
        C.TRAVEL_FUND,
        C.SUBSCRIPTIONS,
        C.DINING_AND_DELIVERY,
        C.GROCERIES,
    ]


def test_solve_cuts_unlocked_rent_and_custom_config() -> None:
    config = CutConfig(cap_shares={C.RENT: D("0.2")})
    out = domain.solve_cuts(D("300"), set(PROTECTED) - {C.RENT}, AVERAGES, 6, config)
    assert [(c.category, c.amount) for c in out.cuts] == [(C.RENT, D("300"))]
    assert out.cuts[0].ease == Ease.HARD


@pytest.mark.parametrize(
    "score,ease", [(1, Ease.EASY), (2, Ease.EASY), (3, Ease.MEDIUM), (5, Ease.HARD)]
)
def test_ease_tiers(score: int, ease: Ease) -> None:
    assert CutConfig(ease_scores={C.OTHER: score}).ease(C.OTHER) == ease
