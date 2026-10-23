"""End to end through FastMCP's in-memory client, with respx serving the fixture mocks."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest
import respx
from fastmcp import Client
from homefund_housing_mcp.config import Settings
from homefund_housing_mcp.server import HousingService, build_server

from homefund_contracts import FixedClock
from homefund_contracts.mcp import TOOLS
from homefund_contracts.mcp.housing import SERVER

pytestmark = pytest.mark.anyio

REPO = Path(__file__).resolve().parents[3]
GOLDEN = json.loads((REPO / "fixtures" / "golden_scenario.json").read_text())
GOAL = GOLDEN["request"]["goal"]
EXPECTED = GOLDEN["expected"]["home_cost"]
FIXTURE_ADDRESS = "4512 Larkspur Bend, Austin, TX 78704"


async def call(service: HousingService, tool: str, args: dict[str, Any]) -> dict[str, Any]:
    async with Client(build_server(service)) as client:
        result = await client.call_tool(tool, args)
        assert result.structured_content is not None
        return result.structured_content


def walkthrough_args(**extra: str) -> dict[str, str]:
    return {"price": GOAL["price"], "zip": GOAL["zip"], "down_pct": GOAL["down_pct"], **extra}


async def test_tools_match_the_contract_registry(service: HousingService) -> None:
    async with Client(build_server(service)) as client:
        tools = {t.name: t for t in await client.list_tools()}
    assert set(tools) == set(TOOLS[SERVER])
    params = set(tools["estimate_home_cost"].input_schema["properties"])
    # Design's parameters first; the rest are optional extras (contract request filed).
    assert {"price", "zip", "down_pct"} <= params
    assert set(tools["estimate_home_cost"].input_schema["required"]) == {"price", "zip", "down_pct"}


# --- golden walkthrough ------------------------------------------------------------------


async def test_golden_down_payment_and_closing(
    service: HousingService, router: respx.MockRouter
) -> None:
    got = await call(service, "estimate_home_cost", walkthrough_args())
    assert got["down_payment"] == "42000.00" == EXPECTED["down_payment"]
    assert got["closing_costs"] == "12600.00" == EXPECTED["closing_costs"]
    for field in ("loan_amount", "rate_pct", "rate_as_of", "principal_interest_monthly"):
        assert got[field] == EXPECTED[field], field
    for field in ("insurance_monthly", "pmi_rate_pct", "pmi_monthly"):
        assert got[field] == EXPECTED[field], field
    assert router.routes["properties"].call_count == 0  # no address, no RentCast spend


@pytest.mark.xfail(
    strict=True,
    reason=(
        "golden_scenario.json prices tax at 1.8% from a RentCast record, but the walkthrough "
        "request has no address, so tax falls back to the TX state default (1.40%): reserves "
        "$6,000, cash needed $60,600. Regeneration requested in "
        "docs/contract-requests/housing-mcp.md."
    ),
)
async def test_golden_reserves_and_cash_needed(
    service: HousingService, router: respx.MockRouter
) -> None:
    got = await call(service, "estimate_home_cost", walkthrough_args())
    assert got["reserves"] == "6300.00" == EXPECTED["reserves"]
    assert got["cash_needed"] == "60900.00" == EXPECTED["cash_needed"]


async def test_walkthrough_without_address_uses_state_default(
    service: HousingService, router: respx.MockRouter
) -> None:
    got = await call(service, "estimate_home_cost", walkthrough_args())
    assert got["property_tax_rate_pct"] == "1.4"
    assert got["piti_monthly"] == "2997.33"
    assert got["reserves"] == "6000.00"
    assert got["cash_needed"] == "60600.00"


async def test_walkthrough_with_fixture_address_reproduces_golden(
    service: HousingService, router: respx.MockRouter
) -> None:
    got = await call(service, "estimate_home_cost", walkthrough_args(address=FIXTURE_ADDRESS))
    for field in ("property_tax_rate_pct", "property_tax_monthly", "piti_monthly", "reserves"):
        assert got[field] == EXPECTED[field], field
    assert got["cash_needed"] == "60900.00" == EXPECTED["cash_needed"]
    assert got["monthly_payment"] == EXPECTED["monthly_payment"]
    tax = next(a for a in got["assumptions"] if a["item"] == "property_tax_pct")
    assert "RentCast" in tax["source"]
    assert got["warnings"] == []


async def test_estimate_falls_back_when_rentcast_is_down(
    service: HousingService, router: respx.MockRouter
) -> None:
    router.routes["properties"].respond(429)
    router.routes["avm"].respond(429)
    got = await call(service, "estimate_home_cost", walkthrough_args(address=FIXTURE_ADDRESS))
    assert got["property_tax_rate_pct"] == "1.4"
    assert got["cash_needed"] == "60600.00"
    assert any("state default" in w for w in got["warnings"])


# --- tool surface ------------------------------------------------------------------------


async def test_get_mortgage_rate_tool(service: HousingService, router: respx.MockRouter) -> None:
    got = await call(service, "get_mortgage_rate", {})
    assert got["rate_pct"] == "6.27" and got["as_of"] == "2026-09-24"
    assert got["source_url"] == "https://fred.stlouisfed.org/series/MORTGAGE30US"
    assert got["cached"] is False
    assert (await call(service, "get_mortgage_rate", {}))["cached"] is True


async def test_get_property_tool(service: HousingService, router: respx.MockRouter) -> None:
    got = await call(service, "get_property", {"address": FIXTURE_ADDRESS})
    assert got["value_estimate"] == "450000.00"
    assert got["property_tax_annual"] == "8100.00"
    assert got["property_tax_rate_pct"] == "1.8"


@pytest.mark.parametrize(
    "bad",
    [
        {"price": 420000.5, "zip": "78704", "down_pct": "10"},  # float money
        {"price": "420000", "zip": "7870", "down_pct": "10"},
        {"price": "0", "zip": "78704", "down_pct": "10"},
        {"price": "420000", "zip": "78704", "down_pct": "100"},
    ],
)
async def test_estimate_rejects_bad_input(
    bad: dict[str, Any], service: HousingService, router: respx.MockRouter
) -> None:
    async with Client(build_server(service)) as client:
        result = await client.call_tool("estimate_home_cost", bad, raise_on_error=False)
    assert result.is_error


async def test_credit_band_and_insurance_quote(
    service: HousingService, router: respx.MockRouter
) -> None:
    got = await call(
        service,
        "estimate_home_cost",
        walkthrough_args(credit_band="620-679", insurance_annual="1800.00"),
    )
    assert got["rate_pct"] == "7.02"
    assert got["insurance_monthly"] == "150.00"


async def test_mock_mode_serves_fixtures_without_keys(tmp_path: Path) -> None:
    settings = Settings.from_env({"HOUSING_USE_MOCKS": "true", "HOUSING_CACHE_DIR": str(tmp_path)})
    assert not settings.fred_api_key
    service = HousingService.build(settings, clock=FixedClock(date(2026, 10, 1)))
    # respx raises on any request that reaches httpx's real transport.
    with respx.mock(assert_all_mocked=True):
        got = await call(service, "estimate_home_cost", walkthrough_args())
    assert got["cash_needed"] == "60600.00"


def test_settings_repr_hides_keys(settings: Settings) -> None:
    assert settings.fred_api_key not in repr(settings)
    assert settings.rentcast_api_key not in repr(settings)
