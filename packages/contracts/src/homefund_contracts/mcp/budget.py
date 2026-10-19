"""budget-mcp tools. Names and parameters exactly as on the design's APIs page."""

from __future__ import annotations

from datetime import date

from pydantic import Field

from homefund_contracts.domain import Cashflow, CategorySpend, Cut, FixedBill, Point
from homefund_contracts.enums import PROTECTED, Category
from homefund_contracts.types import ContractModel, Money, Month

SERVER = "budget-mcp"


# get_cashflow(months=6) -> take-home, spending and amount saved
class GetCashflowInput(ContractModel):
    months: int = Field(default=6, ge=1, le=12)


GetCashflowOutput = Cashflow


# get_spending_by_category(months=6) -> monthly summary records per category
class GetSpendingByCategoryInput(ContractModel):
    months: int = Field(default=6, ge=1, le=12)


class MonthlySummary(ContractModel):
    """One row of the monthly_summaries view, ready to hand to the planner."""

    month: Month
    category: Category
    total: Money = Field(description="Outflow for spending categories, inflow for Income; positive")
    count: int = Field(ge=0)
    text: str = Field(description="e.g. 'Dining and delivery · Mar 2026 · $612 · 23 purchases'")


class GetSpendingByCategoryOutput(ContractModel):
    months: int
    records: list[MonthlySummary]
    averages: list[CategorySpend]


# get_fixed_bills() -> rent, insurance, minimum payments
class GetFixedBillsInput(ContractModel):
    pass


class GetFixedBillsOutput(ContractModel):
    bills: list[FixedBill]
    total_monthly: Money


# project_savings(start, monthly, target) -> balance by month for the chart
class ProjectSavingsInput(ContractModel):
    start: Money = Field(ge=0, description="Balance today (the goal's saved amount)")
    monthly: Money = Field(ge=0, description="Amount added at the end of each month")
    target: Money = Field(gt=0, description="Cash needed")


class ProjectSavingsOutput(ContractModel):
    points: list[Point] = Field(
        description="points[0] is the clock's current month with balance=start; one point per "
        "month until the first month whose balance >= target"
    )
    months_to_goal: int | None = Field(description="None when monthly is 0 and start < target")
    reach_month: date | None


# solve_cuts(gap_per_month, protected) -> smallest set of cuts, capped per category
class SolveCutsInput(ContractModel):
    gap_per_month: Money = Field(gt=0, description="Extra monthly saving needed")
    protected: list[Category] = Field(
        default_factory=lambda: sorted(PROTECTED),
        description="Categories that may not be cut; the user can unlock some at review",
    )


class SolveCutsOutput(ContractModel):
    cuts: list[Cut] = Field(description="Ranked, easiest first")
    total_monthly: Money
    meets_gap: bool
    shortfall_monthly: Money = Field(ge=0, description="0 when meets_gap")
