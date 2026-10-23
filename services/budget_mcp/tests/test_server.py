"""Start budget-mcp in-process and call every tool through an MCP client.

The client speaks streamable HTTP to the server's ASGI app through httpx's ASGI
transport, so the user header is exercised end to end without opening a socket.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from decimal import Decimal
from typing import Any
from uuid import UUID

import httpx
import pytest
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from fastmcp.exceptions import ToolError
from homefund_budget_mcp.server import CashflowWithSavings, create_server

from homefund_contracts.clock import FixedClock
from homefund_contracts.mcp import TOOLS, USER_HEADER
from homefund_contracts.mcp.budget import (
    SERVER,
    GetFixedBillsOutput,
    GetSpendingByCategoryOutput,
    ProjectSavingsOutput,
    SolveCutsOutput,
)

D = Decimal
pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@asynccontextmanager
async def client_for(repo: Any, clock: FixedClock, user_id: UUID | None) -> AsyncIterator[Client]:
    app = create_server(repo, clock).http_app(path="/mcp", stateless_http=True, json_response=True)

    def factory(
        headers: dict[str, str] | None = None,
        timeout: httpx.Timeout | None = None,
        auth: httpx.Auth | None = None,
        **kwargs: Any,
    ) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            headers=headers,
            timeout=timeout,
            auth=auth,
            **kwargs,
        )

    headers = {USER_HEADER: str(user_id)} if user_id else {}
    transport = StreamableHttpTransport(
        "http://budget-mcp/mcp", headers=headers, httpx_client_factory=factory
    )
    async with app.router.lifespan_context(app), Client(transport) as client:
        yield client


async def test_every_tool_over_mcp(repo: Any, clock: FixedClock, user_id: UUID) -> None:
    async with client_for(repo, clock, user_id) as client:
        listed = {t.name for t in await client.list_tools()}
        assert listed == set(TOOLS[SERVER])

        flow = CashflowWithSavings.model_validate(
            (await client.call_tool("get_cashflow", {"months": 6})).structured_content
        )
        assert (flow.take_home_monthly, flow.spending_monthly, flow.saved_monthly) == (
            D("6800.00"),
            D("5600.00"),
            D("1200.00"),
        )
        assert flow.saved_so_far == D("18000.00")

        spending = GetSpendingByCategoryOutput.model_validate(
            (await client.call_tool("get_spending_by_category", {})).structured_content
        )
        assert spending.months == 6
        assert len({r.month for r in spending.records}) == 6
        assert any(
            r.text.startswith("Dining and delivery · Apr 2026 · $") for r in spending.records
        )

        bills = GetFixedBillsOutput.model_validate(
            (await client.call_tool("get_fixed_bills", {})).structured_content
        )
        assert bills.total_monthly == D("3090.00")

        proj = ProjectSavingsOutput.model_validate(
            (
                await client.call_tool(
                    "project_savings",
                    {"start": "18000.00", "monthly": "1200.00", "target": "60900.00"},
                )
            ).structured_content
        )
        assert proj.months_to_goal == 36
        assert proj.reach_month is not None and proj.reach_month.isoformat() == "2029-10-01"

        cuts = SolveCutsOutput.model_validate(
            (await client.call_tool("solve_cuts", {"gap_per_month": "945.00"})).structured_content
        )
        assert cuts.meets_gap and cuts.total_monthly >= D("945.00")
        assert {c.category.value for c in cuts.cuts}.isdisjoint(
            {"Rent", "Insurance", "Utilities", "Debt minimum"}
        )


async def test_tool_inputs_validated(repo: Any, clock: FixedClock, user_id: UUID) -> None:
    async with client_for(repo, clock, user_id) as client:
        with pytest.raises(ToolError):
            await client.call_tool("get_cashflow", {"months": 13})
        with pytest.raises(ToolError):
            await client.call_tool("solve_cuts", {"gap_per_month": "0"})
        with pytest.raises(ToolError):
            await client.call_tool(
                "solve_cuts", {"gap_per_month": "10", "protected": ["Rent", "Nope"]}
            )


async def test_user_header_required(repo: Any, clock: FixedClock) -> None:
    async with client_for(repo, clock, None) as client:
        with pytest.raises(ToolError, match=USER_HEADER):
            await client.call_tool("get_cashflow", {})


async def test_other_user_sees_nothing(repo: Any, clock: FixedClock) -> None:
    other = UUID("00000000-0000-4000-8000-000000000001")
    async with client_for(repo, clock, other) as client:
        flow = CashflowWithSavings.model_validate(
            (await client.call_tool("get_cashflow", {})).structured_content
        )
        assert flow.take_home_monthly == 0 and flow.by_category == []
        assert flow.saved_so_far is None
