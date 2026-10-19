"""Domain models carried in the agent's PlanState and returned by MCP tools.

Sign convention: Postgres stores transaction amounts signed (income +, spending -).
Every model here reports spending as a positive magnitude.
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Self
from uuid import UUID

from pydantic import Field, model_validator

from homefund_contracts.enums import NON_SPENDING, Category, Ease, GuideSource
from homefund_contracts.types import ContractModel, Money, Month, Percent, ZipCode


class CreditScoreRange(StrEnum):
    BELOW_620 = "<620"
    FROM_620_TO_679 = "620-679"
    FROM_680_TO_739 = "680-739"
    AT_LEAST_740 = "740+"


class HomeGoal(ContractModel):
    """A complete goal. parse_goal produces it; ask_user fills whatever is missing."""

    price: Money = Field(gt=0, description="Target home price")
    zip: ZipCode
    move_in: date = Field(description="Target move-in date")
    down_pct: Percent = Field(gt=0, description="Down payment, percentage points (3, 3.5, 10, 20)")
    saved: Money = Field(ge=0, description="Cash already set aside for the home")
    address: str | None = None
    credit_score_range: CreditScoreRange | None = None


class HomeGoalDraft(ContractModel):
    """Whatever the user supplied so far; any field may be missing."""

    price: Money | None = Field(default=None, gt=0)
    zip: ZipCode | None = None
    move_in: date | None = None
    down_pct: Percent | None = Field(default=None, gt=0)
    saved: Money | None = Field(default=None, ge=0)
    address: str | None = None
    credit_score_range: CreditScoreRange | None = None


class CostBreakdown(ContractModel):
    """Cash needed and monthly payment for one home. Produced only by housing-mcp."""

    price: Money
    down_pct: Percent
    down_payment: Money
    loan_amount: Money
    closing_cost_pct: Percent
    closing_costs: Money
    reserve_months: int = Field(ge=0, description="Months of PITI held as reserves")
    reserves: Money = Field(description="reserve_months x PITI, rounded to the nearest $100")
    cash_needed: Money = Field(description="down_payment + closing_costs + reserves")
    rate_pct: Percent = Field(description="30-year fixed rate used")
    rate_as_of: date | None = None
    principal_interest_monthly: Money
    property_tax_rate_pct: Percent
    property_tax_monthly: Money
    insurance_rate_pct: Percent
    insurance_monthly: Money
    piti_monthly: Money = Field(description="Principal + interest + property tax + insurance")
    pmi_rate_pct: Percent
    pmi_monthly: Money = Field(description="Zero when down_pct >= 20")
    monthly_payment: Money = Field(description="piti_monthly + pmi_monthly")


class CategorySpend(ContractModel):
    category: Category
    monthly_avg: Money = Field(description="Average monthly outflow, positive")
    transactions: int = Field(ge=0, description="Transaction count over the whole period")


class FixedBill(ContractModel):
    name: str = Field(description="Display name, e.g. 'Rent' or 'Student loan minimum'")
    category: Category
    monthly_amount: Money


class Cashflow(ContractModel):
    """Income, spending by category and fixed bills over the last N full months."""

    months: int = Field(ge=1, le=12)
    period_start: Month
    period_end: Month = Field(description="Last full month included")
    take_home_monthly: Money
    spending_monthly: Money = Field(description="Average spend, excluding Income and Transfer")
    saved_monthly: Money = Field(description="take_home_monthly - spending_monthly")
    by_category: list[CategorySpend]
    fixed_bills: list[FixedBill]
    fixed_bills_monthly: Money


class Point(ContractModel):
    """One month on the savings chart. points[0] is the clock's current month at `start`."""

    month: Month
    balance: Money
    target: Money


class Cut(ContractModel):
    category: Category
    current_monthly: Money = Field(ge=0)
    amount: Money = Field(gt=0, description="Monthly reduction, positive")
    new_monthly: Money = Field(ge=0)
    ease: Ease
    approved: bool = False
    detail: str | None = Field(default=None, description="e.g. 'Subscriptions, 7 down to 3'")

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.category in NON_SPENDING:
            raise ValueError(f"{self.category} is not a spending category")
        if self.amount > self.current_monthly:
            raise ValueError("a cut cannot exceed current monthly spend")
        if self.new_monthly != self.current_monthly - self.amount:
            raise ValueError("new_monthly must equal current_monthly - amount")
        return self


class Citation(ContractModel):
    chunk_id: UUID
    source: GuideSource
    document: str = Field(description="Document title, e.g. 'CFPB: Your home loan toolkit'")
    section: str
    url: str | None = None
    tax_year: int | None = None
    quote: str | None = Field(default=None, description="Short supporting excerpt")
