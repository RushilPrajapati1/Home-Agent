from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from datetime import date
from pathlib import Path
from typing import Any

import pytest
import respx
from homefund_housing_mcp.cache import MemoryCache
from homefund_housing_mcp.config import Settings
from homefund_housing_mcp.fred import OBSERVATIONS_URL, FredClient
from homefund_housing_mcp.http import SafeClient
from homefund_housing_mcp.rentcast import AVM_URL, PROPERTIES_URL, RentCastClient
from homefund_housing_mcp.server import HousingService

from homefund_contracts import FixedClock

REPO = Path(__file__).resolve().parents[3]
MOCKS = REPO / "fixtures" / "mocks"
GOLDEN = json.loads((REPO / "fixtures" / "golden_scenario.json").read_text())
FRED_KEY = "fred-test-key-SECRET"
RENTCAST_KEY = "rentcast-test-key-SECRET"
ADDRESS = "4512 Larkspur Bend, Austin, TX 78704"


def mock_json(name: str) -> Any:
    return json.loads((MOCKS / name).read_text())


async def _no_sleep(_: float) -> None:
    return None


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock(date.fromisoformat(GOLDEN["clock"]["date"]))


@pytest.fixture
def cache(clock: FixedClock) -> MemoryCache:
    return MemoryCache(clock)


@pytest.fixture
def router() -> Iterator[respx.MockRouter]:
    """respx with the fixture mocks; anything not routed fails the test."""
    with respx.mock(assert_all_called=False, assert_all_mocked=True) as r:
        r.get(OBSERVATIONS_URL, name="fred").respond(json=mock_json("fred_mortgage30us.json"))
        r.get(PROPERTIES_URL, name="properties").respond(json=mock_json("rentcast_property.json"))
        r.get(AVM_URL, name="avm").respond(json=mock_json("rentcast_value.json"))
        yield r


@pytest.fixture
def make_fred(cache: MemoryCache, clock: FixedClock) -> Callable[..., FredClient]:
    def make(key: str = FRED_KEY) -> FredClient:
        return FredClient(SafeClient(sleep=_no_sleep), cache, clock, key)

    return make


@pytest.fixture
def make_rentcast(cache: MemoryCache, clock: FixedClock) -> Callable[..., RentCastClient]:
    def make(limit: int = 50) -> RentCastClient:
        return RentCastClient(SafeClient(sleep=_no_sleep), cache, clock, RENTCAST_KEY, limit)

    return make


@pytest.fixture
def no_sleep_client() -> SafeClient:
    return SafeClient(retries=2, sleep=_no_sleep)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        fred_api_key=FRED_KEY,
        rentcast_api_key=RENTCAST_KEY,
        use_mocks=False,
        mocks_dir=MOCKS,
        cache_dir=tmp_path,
        rentcast_monthly_limit=50,
    )


@pytest.fixture
def service(settings: Settings, clock: FixedClock, cache: MemoryCache) -> HousingService:
    return HousingService.build(
        settings, clock=clock, cache=cache, http=SafeClient(retries=2, sleep=_no_sleep)
    )
