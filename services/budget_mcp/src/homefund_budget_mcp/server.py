"""budget-mcp: FastMCP over streamable HTTP. Thin wrappers around ``domain``.

Calls are scoped to a user by the ``X-HomeFund-User-Id`` header, never by a parameter.
"""

from __future__ import annotations

import os
from typing import Annotated
from uuid import UUID

import anyio
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_http_headers
from pydantic import Field
from starlette.requests import Request
from starlette.responses import JSONResponse

from homefund_budget_mcp import domain
from homefund_budget_mcp.config import CutConfig
from homefund_budget_mcp.repository import BudgetRepository, PostgresRepository
from homefund_contracts.clock import Clock, clock_from_env
from homefund_contracts.domain import Cashflow
from homefund_contracts.enums import PROTECTED, Category
from homefund_contracts.mcp import USER_HEADER
from homefund_contracts.mcp.budget import (
    SERVER,
    GetCashflowInput,
    GetFixedBillsOutput,
    GetSpendingByCategoryInput,
    GetSpendingByCategoryOutput,
    ProjectSavingsInput,
    ProjectSavingsOutput,
    SolveCutsInput,
    SolveCutsOutput,
)
from homefund_contracts.types import Money

CUT_WINDOW_MONTHS = 6
DEFAULT_PROTECTED: list[Category] = sorted(PROTECTED)
DEFAULT_PORT = 8101


class CashflowWithSavings(Cashflow):
    """``Cashflow`` plus the goal's saved amount.

    Local stand-in until the contract gains the field (docs/contract-requests/budget-mcp.md).
    """

    saved_so_far: Money | None = Field(
        description="Saved amount on the user's latest goal; None when there is no goal"
    )


def current_user() -> UUID:
    headers = get_http_headers(include_all=True)
    raw = headers.get(USER_HEADER.lower(), "").strip()
    if not raw:
        raise ToolError(f"missing {USER_HEADER} header")
    try:
        return UUID(raw)
    except ValueError as exc:
        raise ToolError(f"{USER_HEADER} is not a UUID") from exc


def create_server(repo: BudgetRepository, clock: Clock, config: CutConfig | None = None) -> FastMCP:
    cut_config = config or CutConfig()
    mcp: FastMCP = FastMCP(SERVER)

    async def summaries(user_id: UUID, win: domain.Window) -> list[domain.SummaryRow]:
        return await anyio.to_thread.run_sync(repo.monthly_summaries, user_id, win.start, win.end)

    @mcp.tool
    async def get_cashflow(
        months: Annotated[int, Field(ge=1, le=12)] = 6,
    ) -> CashflowWithSavings:
        """Average monthly take-home, spend and amount saved over the last N full months."""
        args = GetCashflowInput(months=months)
        user_id = current_user()
        win = domain.window(clock, args.months)
        flow = domain.cashflow(await summaries(user_id, win), win)
        saved = await anyio.to_thread.run_sync(repo.saved_so_far, user_id)
        return CashflowWithSavings(**flow.model_dump(), saved_so_far=saved)

    @mcp.tool
    async def get_spending_by_category(
        months: Annotated[int, Field(ge=1, le=12)] = 6,
    ) -> GetSpendingByCategoryOutput:
        """One summary record per category per month, plus each category's monthly average."""
        args = GetSpendingByCategoryInput(months=months)
        win = domain.window(clock, args.months)
        return domain.spending_by_category(await summaries(current_user(), win), win)

    @mcp.tool
    async def get_fixed_bills() -> GetFixedBillsOutput:
        """Average monthly rent, insurance, utilities and minimum debt payments (last 6 months)."""
        win = domain.window(clock, CUT_WINDOW_MONTHS)
        rows = await summaries(current_user(), win)
        return domain.fixed_bills(domain.category_averages(rows, win))

    @mcp.tool
    def project_savings(start: Money, monthly: Money, target: Money) -> ProjectSavingsOutput:
        """Balance by month from today at `start`, adding `monthly`, until it reaches `target`."""
        args = ProjectSavingsInput(start=start, monthly=monthly, target=target)
        return domain.project_savings(
            args.start, args.monthly, args.target, domain.current_month(clock)
        )

    @mcp.tool
    async def solve_cuts(
        gap_per_month: Money,
        protected: list[Category] = DEFAULT_PROTECTED,
    ) -> SolveCutsOutput:
        """Fewest ranked cuts (easiest first) that close the monthly gap, capped per category."""
        args = SolveCutsInput(gap_per_month=gap_per_month, protected=protected)
        win = domain.window(clock, CUT_WINDOW_MONTHS)
        averages = domain.category_averages(await summaries(current_user(), win), win)
        return domain.solve_cuts(
            args.gap_per_month, set(args.protected), averages, win.months, cut_config
        )

    @mcp.custom_route("/healthz", methods=["GET"])
    async def healthz(_: Request) -> JSONResponse:
        return JSONResponse({"status": "ok"})

    return mcp


def main() -> None:
    server = create_server(PostgresRepository.from_env(), clock_from_env())
    server.run(
        transport="http",
        host=os.environ.get("BUDGET_MCP_HOST", "127.0.0.1"),
        port=int(os.environ.get("BUDGET_MCP_PORT", DEFAULT_PORT)),
        path="/mcp",
        stateless_http=True,
    )


__all__ = ["CashflowWithSavings", "create_server", "main"]
