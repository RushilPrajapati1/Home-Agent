"""Live calls to FRED and RentCast. Skipped unless the key is set *and* HOUSING_LIVE_TESTS=1.

`make` exports .env into every recipe, so keys alone would turn `make test` into network
calls, and every RentCast call spends the free tier's ~50 requests a month (2 per run here).
Run with: HOUSING_LIVE_TESTS=1 uv run pytest services/housing_mcp/tests/test_live.py
"""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path

import pytest
from homefund_housing_mcp.cache import MemoryCache
from homefund_housing_mcp.fred import FredClient
from homefund_housing_mcp.http import SafeClient
from homefund_housing_mcp.rentcast import RentCastClient

from homefund_contracts import SystemClock

pytestmark = pytest.mark.anyio

LIVE = os.environ.get("HOUSING_LIVE_TESTS") == "1"
FRED_KEY = os.environ.get("FRED_API_KEY", "")
RENTCAST_KEY = os.environ.get("RENTCAST_API_KEY", "")
# RentCast's own documentation example address.
LIVE_ADDRESS = "5500 Grand Lake Dr, San Antonio, TX 78244"


@pytest.mark.skipif(not (LIVE and FRED_KEY), reason="needs FRED_API_KEY and HOUSING_LIVE_TESTS=1")
async def test_live_fred_latest_rate() -> None:
    clock = SystemClock()
    rate = await FredClient(SafeClient(), MemoryCache(clock), clock, FRED_KEY).get_rate()
    assert 0 < rate.rate_pct < 20
    assert (clock.today() - rate.as_of).days < 21
    assert isinstance(rate.as_of, date) and not rate.warnings


@pytest.mark.skipif(
    not (LIVE and RENTCAST_KEY), reason="needs RENTCAST_API_KEY and HOUSING_LIVE_TESTS=1"
)
async def test_live_rentcast_property(tmp_path: Path) -> None:
    clock = SystemClock()
    client = RentCastClient(SafeClient(), MemoryCache(clock), clock, RENTCAST_KEY, monthly_limit=2)
    prop = await client.get_property(LIVE_ADDRESS)
    assert prop.warnings == []
    assert prop.value_estimate is not None and prop.value_estimate > 0
    assert prop.zip == "78244"
