"""Tool outputs: the contract models plus the fields this lane has requested from foundation.

Each class is a strict superset of its contract model (docs/contract-requests/housing-mcp.md).
Once foundation adds ``assumptions``, ``warnings`` and ``source_url`` to the contracts, these
collapse back into plain aliases.
"""

from __future__ import annotations

from pydantic import Field

from homefund_contracts import CostBreakdown, Money, Percent, ZipCode
from homefund_contracts.mcp.housing import GetMortgageRateOutput, GetPropertyOutput
from homefund_contracts.types import ContractModel


class Assumption(ContractModel):
    item: str = Field(description="What was assumed, e.g. 'closing_cost_pct'")
    value: str = Field(description="The value used, as shown to the user")
    source: str
    url: str | None = None


class HomeCost(CostBreakdown):
    assumptions: list[Assumption]
    warnings: list[str] = Field(default_factory=list)


class MortgageRate(GetMortgageRateOutput):
    source_url: str
    warnings: list[str] = Field(default_factory=list)


class PropertyInfo(GetPropertyOutput):
    """Fail-soft property lookup: every data field may be empty, with the reason in warnings."""

    zip: ZipCode | None = None  # type: ignore[assignment]
    value_estimate: Money | None = None  # type: ignore[assignment]
    property_tax_rate_pct: Percent | None = None
    cached: bool = False
    warnings: list[str] = Field(default_factory=list)
