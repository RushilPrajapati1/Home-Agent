"""Input and output models for every MCP tool, plus a registry the servers and tests share.

MCP tool calls are scoped to a user by the ``USER_HEADER`` HTTP header on the MCP
transport, never by a tool parameter: tool signatures match the design exactly.
"""

from __future__ import annotations

from typing import NamedTuple

from pydantic import BaseModel

from homefund_contracts.mcp import budget, guides, housing

USER_HEADER = "X-HomeFund-User-Id"


class ToolSpec(NamedTuple):
    input: type[BaseModel]
    output: type[BaseModel]


TOOLS: dict[str, dict[str, ToolSpec]] = {
    budget.SERVER: {
        "get_cashflow": ToolSpec(budget.GetCashflowInput, budget.GetCashflowOutput),
        "get_spending_by_category": ToolSpec(
            budget.GetSpendingByCategoryInput, budget.GetSpendingByCategoryOutput
        ),
        "get_fixed_bills": ToolSpec(budget.GetFixedBillsInput, budget.GetFixedBillsOutput),
        "project_savings": ToolSpec(budget.ProjectSavingsInput, budget.ProjectSavingsOutput),
        "solve_cuts": ToolSpec(budget.SolveCutsInput, budget.SolveCutsOutput),
    },
    housing.SERVER: {
        "estimate_home_cost": ToolSpec(
            housing.EstimateHomeCostInput, housing.EstimateHomeCostOutput
        ),
        "get_mortgage_rate": ToolSpec(housing.GetMortgageRateInput, housing.GetMortgageRateOutput),
        "get_property": ToolSpec(housing.GetPropertyInput, housing.GetPropertyOutput),
    },
    guides.SERVER: {
        "search_guides": ToolSpec(guides.SearchGuidesInput, guides.SearchGuidesOutput),
        "define_term": ToolSpec(guides.DefineTermInput, guides.DefineTermOutput),
        "get_section": ToolSpec(guides.GetSectionInput, guides.GetSectionOutput),
    },
}

__all__ = ["TOOLS", "USER_HEADER", "ToolSpec", "budget", "guides", "housing"]
