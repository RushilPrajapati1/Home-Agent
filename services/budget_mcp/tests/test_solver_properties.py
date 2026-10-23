"""Property tests for solve_cuts: protected untouched, caps respected, gap covered if possible."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from itertools import combinations

from homefund_budget_mcp import domain
from homefund_budget_mcp.config import CutConfig
from hypothesis import given, settings
from hypothesis import strategies as st

from homefund_contracts.domain import CategorySpend
from homefund_contracts.enums import NON_SPENDING, PROTECTED, Category

SPENDING = [c for c in Category if c not in NON_SPENDING]
CONFIG = CutConfig()
MONTHS = 6

cents = st.integers(min_value=0, max_value=500_000).map(lambda n: Decimal(n) / 100)


@st.composite
def averages(draw: st.DrawFn) -> list[CategorySpend]:
    categories = draw(st.lists(st.sampled_from(SPENDING), unique=True, max_size=len(SPENDING)))
    return [
        CategorySpend(
            category=c,
            monthly_avg=draw(cents),
            transactions=draw(st.integers(min_value=0, max_value=200)),
        )
        for c in categories
    ]


gaps = st.integers(min_value=1, max_value=800_000).map(lambda n: Decimal(n) / 100)
protected_sets = st.sets(st.sampled_from(SPENDING)) | st.just(set(PROTECTED))

PROPERTY_SETTINGS = settings(max_examples=300, deadline=None, database=None)


@PROPERTY_SETTINGS
@given(averages(), gaps, protected_sets)
def test_never_touches_protected(
    avgs: list[CategorySpend], gap: Decimal, protected: set[Category]
) -> None:
    out = domain.solve_cuts(gap, protected, avgs, MONTHS, CONFIG)
    assert not {c.category for c in out.cuts} & protected


@PROPERTY_SETTINGS
@given(averages(), gaps, protected_sets)
def test_never_exceeds_cap(
    avgs: list[CategorySpend], gap: Decimal, protected: set[Category]
) -> None:
    out = domain.solve_cuts(gap, protected, avgs, MONTHS, CONFIG)
    current = {a.category: a.monthly_avg for a in avgs}
    counts = {a.category: a.transactions for a in avgs}
    for cut in out.cuts:
        assert cut.current_monthly == current[cut.category]
        if cut.category == Category.SUBSCRIPTIONS:
            assert cut.amount <= cut.current_monthly * CONFIG.subscription_max_share
            n = int((Decimal(counts[cut.category]) / MONTHS).to_integral_value(ROUND_HALF_UP))
            assert any(
                domain.subscription_cut(cut.current_monthly, n, k) == cut.amount
                for k in range(1, n + 1)
            )
        else:
            assert cut.amount <= cut.current_monthly * CONFIG.cap_share(cut.category)
        assert 0 < cut.amount <= cut.current_monthly


@PROPERTY_SETTINGS
@given(averages(), gaps, protected_sets)
def test_covers_gap_whenever_possible_with_fewest_cuts(
    avgs: list[CategorySpend], gap: Decimal, protected: set[Category]
) -> None:
    out = domain.solve_cuts(gap, protected, avgs, MONTHS, CONFIG)
    cands = domain.candidates(avgs, MONTHS, protected, CONFIG)
    possible = sum((c.cap for c in cands), Decimal(0))
    assert out.meets_gap == (possible >= gap)
    assert out.total_monthly == sum((c.amount for c in out.cuts), Decimal(0))
    if out.meets_gap:
        assert out.total_monthly >= gap
        assert out.shortfall_monthly == 0
        fewer = len(out.cuts) - 1
        assert not any(
            sum((c.cap for c in s), Decimal(0)) >= gap for s in combinations(cands, fewer)
        )
    else:
        assert out.total_monthly == possible
        assert out.shortfall_monthly == gap - possible
        assert len(out.cuts) == len(cands)


@PROPERTY_SETTINGS
@given(averages(), gaps, protected_sets)
def test_ranked_easiest_first(
    avgs: list[CategorySpend], gap: Decimal, protected: set[Category]
) -> None:
    out = domain.solve_cuts(gap, protected, avgs, MONTHS, CONFIG)
    scores = [CONFIG.ease_score(c.category) for c in out.cuts]
    assert scores == sorted(scores)
