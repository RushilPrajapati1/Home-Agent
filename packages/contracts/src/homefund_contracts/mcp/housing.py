"""housing-mcp tools. Names and parameters exactly as on the design's APIs page."""

from __future__ import annotations

from datetime import date

from pydantic import Field

from homefund_contracts.domain import CostBreakdown
from homefund_contracts.types import ContractModel, Money, Percent, ZipCode

SERVER = "housing-mcp"


# estimate_home_cost(price, zip, down_pct) -> down payment, closing, reserves, PITI, PMI
class EstimateHomeCostInput(ContractModel):
    price: Money = Field(gt=0)
    zip: ZipCode
    down_pct: Percent = Field(gt=0)


EstimateHomeCostOutput = CostBreakdown


# get_mortgage_rate() -> FRED MORTGAGE30US, cached weekly
class GetMortgageRateInput(ContractModel):
    pass


class GetMortgageRateOutput(ContractModel):
    series: str = "MORTGAGE30US"
    rate_pct: Percent
    as_of: date = Field(description="Observation date of the weekly average")
    cached: bool


# get_property(address) -> value estimate and property tax from RentCast
class GetPropertyInput(ContractModel):
    address: str = Field(min_length=5)


class GetPropertyOutput(ContractModel):
    address: str
    zip: ZipCode
    value_estimate: Money
    value_low: Money | None = None
    value_high: Money | None = None
    property_tax_annual: Money | None = None
    tax_year: int | None = None
    property_tax_rate_pct: Percent | None = Field(
        default=None, description="property_tax_annual / value_estimate"
    )
