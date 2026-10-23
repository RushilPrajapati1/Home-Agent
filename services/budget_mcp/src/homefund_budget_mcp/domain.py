"""budget-mcp logic as pure functions over monthly summary rows. No MCP, no database.

Money is Decimal throughout. Averages round half-up to cents; caps round down so a cut
never exceeds its cap.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_CEILING, ROUND_DOWN, ROUND_FLOOR, ROUND_HALF_UP, Decimal
from itertools import combinations

from homefund_budget_mcp.config import CutConfig
from homefund_contracts.clock import Clock
from homefund_contracts.domain import Cashflow, CategorySpend, Cut, FixedBill, Point
from homefund_contracts.enums import NON_SPENDING, PROTECTED, Category
from homefund_contracts.mcp.budget import (
    GetFixedBillsOutput,
    GetSpendingByCategoryOutput,
    MonthlySummary,
    ProjectSavingsOutput,
    SolveCutsOutput,
)
from homefund_contracts.types import CENT

MAX_PROJECTION_POINTS = 601
"""points[0] plus 50 years. Beyond that the chart is truncated; months_to_goal stays exact."""

ZERO = Decimal("0")
MONTH_ABBR = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
FIXED_BILL_NAMES = {
    Category.RENT: "Rent",
    Category.INSURANCE: "Insurance",
    Category.UTILITIES: "Utilities",
    Category.DEBT_MINIMUM: "Minimum debt payments",
}
CATEGORY_ORDER = {c: i for i, c in enumerate(Category)}


@dataclass(frozen=True)
class SummaryRow:
    """One monthly_summaries row. total is signed as stored: income +, spending -."""

    month: date
    category: Category
    total: Decimal
    count: int


@dataclass(frozen=True)
class Window:
    months: int
    start: date  # first full month included
    end: date  # last full month included


def add_months(month: date, n: int) -> date:
    index = month.year * 12 + month.month - 1 + n
    return date(index // 12, index % 12 + 1, 1)


def current_month(clock: Clock) -> date:
    return clock.today().replace(day=1)


def window(clock: Clock, months: int) -> Window:
    """The last ``months`` full months before the clock's current month."""
    this_month = current_month(clock)
    return Window(months, add_months(this_month, -months), add_months(this_month, -1))


def to_cents(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def _in_window(rows: list[SummaryRow], win: Window) -> list[SummaryRow]:
    return [r for r in rows if win.start <= r.month <= win.end]


def category_averages(rows: list[SummaryRow], win: Window) -> list[CategorySpend]:
    """Average monthly outflow per spending category, largest first."""
    totals: dict[Category, Decimal] = defaultdict(lambda: ZERO)
    counts: dict[Category, int] = defaultdict(int)
    for r in _in_window(rows, win):
        if r.category in NON_SPENDING:
            continue
        totals[r.category] -= r.total
        counts[r.category] += r.count
    averages = [
        CategorySpend(category=c, monthly_avg=to_cents(t / win.months), transactions=counts[c])
        for c, t in totals.items()
    ]
    return sorted(averages, key=lambda a: (-a.monthly_avg, CATEGORY_ORDER[a.category]))


def fixed_bills(averages: list[CategorySpend]) -> GetFixedBillsOutput:
    bills = [
        FixedBill(
            name=FIXED_BILL_NAMES[a.category], category=a.category, monthly_amount=a.monthly_avg
        )
        for a in averages
        if a.category in PROTECTED
    ]
    return GetFixedBillsOutput(
        bills=bills, total_monthly=sum((b.monthly_amount for b in bills), ZERO)
    )


def cashflow(rows: list[SummaryRow], win: Window) -> Cashflow:
    income = sum((r.total for r in _in_window(rows, win) if r.category == Category.INCOME), ZERO)
    averages = category_averages(rows, win)
    take_home = to_cents(income / win.months)
    spending = sum((a.monthly_avg for a in averages), ZERO)
    bills = fixed_bills(averages)
    return Cashflow(
        months=win.months,
        period_start=win.start,
        period_end=win.end,
        take_home_monthly=take_home,
        spending_monthly=spending,
        saved_monthly=take_home - spending,
        by_category=averages,
        fixed_bills=bills.bills,
        fixed_bills_monthly=bills.total_monthly,
    )


def summary_text(month: date, category: Category, total: Decimal, count: int) -> str:
    dollars = int(total.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    noun = "deposit" if category == Category.INCOME else "purchase"
    plural = "" if count == 1 else "s"
    return (
        f"{category.value} · {MONTH_ABBR[month.month - 1]} {month.year} · "
        f"${dollars:,} · {count} {noun}{plural}"
    )


def spending_by_category(rows: list[SummaryRow], win: Window) -> GetSpendingByCategoryOutput:
    """One record per category per month (Income included, Transfer left out)."""
    records = []
    for r in _in_window(rows, win):
        if r.category == Category.TRANSFER:
            continue
        total = r.total if r.category == Category.INCOME else -r.total
        records.append(
            MonthlySummary(
                month=r.month,
                category=r.category,
                total=total,
                count=r.count,
                text=summary_text(r.month, r.category, total, r.count),
            )
        )
    records.sort(key=lambda m: (m.month, -m.total, CATEGORY_ORDER[m.category]))
    return GetSpendingByCategoryOutput(
        months=win.months, records=records, averages=category_averages(rows, win)
    )


def project_savings(
    start: Decimal, monthly: Decimal, target: Decimal, from_month: date
) -> ProjectSavingsOutput:
    """Balance by month from ``from_month`` (at ``start``) until it first reaches ``target``."""
    if start >= target:
        months_to_goal: int | None = 0
    elif monthly <= 0:
        months_to_goal = None
    else:
        months_to_goal = int(((target - start) / monthly).to_integral_value(ROUND_CEILING))
    last = 0 if months_to_goal is None else min(months_to_goal, MAX_PROJECTION_POINTS - 1)
    points = [
        Point(month=add_months(from_month, i), balance=start + monthly * i, target=target)
        for i in range(last + 1)
    ]
    return ProjectSavingsOutput(
        points=points,
        months_to_goal=months_to_goal,
        reach_month=None if months_to_goal is None else add_months(from_month, months_to_goal),
    )


@dataclass(frozen=True)
class Candidate:
    category: Category
    current: Decimal
    cap: Decimal
    ease_score: int
    subscriptions: int = 0  # how many subscriptions there are; 0 for other categories

    def amount_for(self, needed: Decimal) -> Decimal:
        """The smallest allowed cut that is >= needed, never above the cap."""
        if needed >= self.cap:
            return self.cap
        if not self.subscriptions:
            return needed
        k = 1
        while subscription_cut(self.current, self.subscriptions, k) < needed:
            k += 1
        return subscription_cut(self.current, self.subscriptions, k)

    def detail(self, amount: Decimal) -> str | None:
        if not self.subscriptions:
            return None
        k = next(
            k
            for k in range(1, self.subscriptions + 1)
            if subscription_cut(self.current, self.subscriptions, k) == amount
        )
        return f"Subscriptions, {self.subscriptions} down to {self.subscriptions - k}"


def subscription_cut(monthly_avg: Decimal, count: int, k: int) -> Decimal:
    """Monthly saving from cancelling k of count subscriptions, at their average price."""
    return (monthly_avg * k / count).quantize(CENT, rounding=ROUND_DOWN)


def candidates(
    averages: list[CategorySpend], months: int, protected: set[Category], config: CutConfig
) -> list[Candidate]:
    """Every category that may be cut, with its cap. Protected and non-spending never are."""
    out = []
    for a in averages:
        if a.category in protected or a.category in NON_SPENDING or a.monthly_avg <= 0:
            continue
        score = config.ease_score(a.category)
        if a.category == Category.SUBSCRIPTIONS:
            count = int((Decimal(a.transactions) / months).to_integral_value(ROUND_HALF_UP))
            max_k = int((count * config.subscription_max_share).to_integral_value(ROUND_FLOOR))
            if count == 0 or max_k == 0:
                continue
            cap = subscription_cut(a.monthly_avg, count, max_k)
            if cap > 0:
                out.append(Candidate(a.category, a.monthly_avg, cap, score, count))
            continue
        cap = (a.monthly_avg * config.cap_share(a.category)).quantize(CENT, rounding=ROUND_DOWN)
        cap = min(cap, a.monthly_avg)
        if cap > 0:
            out.append(Candidate(a.category, a.monthly_avg, cap, score))
    return out


def _rank_key(c: Candidate) -> tuple[int, Decimal, int]:
    return (c.ease_score, -c.cap, CATEGORY_ORDER[c.category])


def _choose(cands: list[Candidate], gap: Decimal) -> list[Candidate]:
    """Fewest categories whose caps cover the gap; ties go to the easier, then roomier set."""
    for size in range(1, len(cands) + 1):
        covering = [s for s in combinations(cands, size) if sum((c.cap for c in s), ZERO) >= gap]
        if covering:
            best = min(
                covering,
                key=lambda s: (
                    sum(c.ease_score for c in s),
                    -sum((c.cap for c in s), ZERO),
                    sorted(CATEGORY_ORDER[c.category] for c in s),
                ),
            )
            return sorted(best, key=_rank_key)
    return sorted(cands, key=_rank_key)


def solve_cuts(
    gap_per_month: Decimal,
    protected: set[Category],
    averages: list[CategorySpend],
    months: int,
    config: CutConfig,
) -> SolveCutsOutput:
    """The fewest ranked cuts that cover the gap, easiest first; all of them if none do.

    Every chosen category but the last (hardest) is cut to its cap, and the last only by
    what is still needed (rounded up to whole subscriptions). Minimality means no chosen
    cut is ever zero.
    """
    chosen = _choose(candidates(averages, months, protected, config), gap_per_month)
    cuts = []
    remaining = gap_per_month
    for c in chosen:
        amount = c.amount_for(remaining)
        remaining -= amount
        cuts.append(
            Cut(
                category=c.category,
                current_monthly=c.current,
                amount=amount,
                new_monthly=c.current - amount,
                ease=config.ease(c.category),
                detail=c.detail(amount),
            )
        )
    total = sum((cut.amount for cut in cuts), ZERO)
    return SolveCutsOutput(
        cuts=cuts,
        total_monthly=total,
        meets_gap=total >= gap_per_month,
        shortfall_monthly=max(gap_per_month - total, ZERO),
    )
