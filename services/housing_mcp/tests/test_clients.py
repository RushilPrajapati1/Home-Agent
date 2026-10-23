from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
import respx
from homefund_housing_mcp.cache import FileCache
from homefund_housing_mcp.fred import FredClient, RateUnavailable, latest_observation
from homefund_housing_mcp.http import ALLOWED_HOSTS, EgressDenied, SafeClient, UpstreamError
from homefund_housing_mcp.rentcast import RentCastClient, normalize_address

from homefund_contracts import FixedClock

pytestmark = pytest.mark.anyio

ADDRESS = "4512 Larkspur Bend, Austin, TX 78704"
FRED_KEY = "fred-test-key-SECRET"  # same values as conftest
RENTCAST_KEY = "rentcast-test-key-SECRET"
MakeFred = Callable[..., FredClient]
MakeRentCast = Callable[..., RentCastClient]


# --- allowlist and secrets -------------------------------------------------------------


def test_allowlist_is_exactly_fred_and_rentcast() -> None:
    assert frozenset({"api.stlouisfed.org", "api.rentcast.io"}) == ALLOWED_HOSTS


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/x",
        "http://api.stlouisfed.org/fred/series/observations",  # plain HTTP
        "https://api.stlouisfed.org.evil.com/x",
        "https://169.254.169.254/latest/meta-data",
    ],
)
async def test_refuses_hosts_outside_allowlist(url: str, router: respx.MockRouter) -> None:
    catch_all = router.route().respond(200, json={})
    with pytest.raises(EgressDenied):
        await SafeClient().get_json(url)
    assert not catch_all.called


async def test_redirects_are_not_followed(
    router: respx.MockRouter, no_sleep_client: SafeClient
) -> None:
    router.get("https://api.rentcast.io/v1/redirect").respond(
        302, headers={"Location": "https://example.com/"}
    )
    with pytest.raises(UpstreamError) as err:
        await no_sleep_client.get_json("https://api.rentcast.io/v1/redirect")
    assert err.value.status == 302


async def test_retries_5xx_then_succeeds(
    router: respx.MockRouter, no_sleep_client: SafeClient
) -> None:
    route = router.get("https://api.rentcast.io/v1/flaky")
    route.side_effect = [
        httpx.Response(503),
        httpx.ConnectError("boom"),
        httpx.Response(200, json={"ok": 1}),
    ]
    got = await no_sleep_client.get_json("https://api.rentcast.io/v1/flaky")
    assert got == {"ok": 1}
    assert route.call_count == 3


async def test_api_key_never_in_errors_or_logs(
    router: respx.MockRouter, make_fred: MakeFred, caplog: pytest.LogCaptureFixture
) -> None:
    router.routes["fred"].respond(500)
    caplog.set_level(logging.DEBUG)
    with pytest.raises(RateUnavailable) as err:
        await make_fred().get_rate()
    assert FRED_KEY not in str(err.value)
    assert err.value.__cause__ is None
    assert FRED_KEY not in caplog.text
    assert router.routes["fred"].calls.last.request.url.params["api_key"] == FRED_KEY


# --- FRED --------------------------------------------------------------------------------


def test_latest_observation_skips_missing_values() -> None:
    payload = {
        "observations": [
            {"date": "2026-10-01", "value": "."},
            {"date": "2026-09-24", "value": "6.27"},
            {"date": "2026-09-17", "value": "6.28"},
        ]
    }
    assert latest_observation(payload) == (Decimal("6.27"), date(2026, 9, 24))
    fixture = Path(__file__).resolve().parents[3] / "fixtures/mocks/fred_mortgage30us.json"
    assert latest_observation(json.loads(fixture.read_text()))[1] == date(2026, 9, 24)


async def test_fred_cache_miss_then_hit_then_expiry(
    router: respx.MockRouter, make_fred: MakeFred, clock: FixedClock
) -> None:
    client = make_fred()
    first = await client.get_rate()
    assert (first.rate_pct, first.as_of, first.cached) == (
        Decimal("6.27"),
        date(2026, 9, 24),
        False,
    )
    assert first.source_url == "https://fred.stlouisfed.org/series/MORTGAGE30US"

    clock.advance(timedelta(days=6, hours=23))
    assert (await client.get_rate()).cached is True
    assert router.routes["fred"].call_count == 1

    clock.advance(timedelta(hours=2))  # past 7 days
    assert (await client.get_rate()).cached is False
    assert router.routes["fred"].call_count == 2


async def test_fred_down_serves_stale_cache_with_warning(
    router: respx.MockRouter, make_fred: MakeFred, clock: FixedClock
) -> None:
    client = make_fred()
    await client.get_rate()
    clock.advance(timedelta(days=8))
    router.routes["fred"].respond(503)
    stale = await client.get_rate()
    assert stale.rate_pct == Decimal("6.27") and stale.cached
    assert stale.warnings and FRED_KEY not in stale.warnings[0]


async def test_fred_without_key_or_cache_raises(make_fred: MakeFred) -> None:
    with respx.mock(assert_all_mocked=True), pytest.raises(RateUnavailable, match="FRED_API_KEY"):
        await make_fred(key="").get_rate()


# --- RentCast ----------------------------------------------------------------------------


def test_normalize_address() -> None:
    assert normalize_address("4512 Larkspur Bend, Austin, TX 78704") == normalize_address(
        "  4512  LARKSPUR bend austin tx, 78704 "
    )
    assert normalize_address("12 Main Street, Apt. 4") == "12 main st apt 4"


async def test_rentcast_cache_miss_then_hit_by_normalized_address(
    router: respx.MockRouter, make_rentcast: MakeRentCast, clock: FixedClock
) -> None:
    client = make_rentcast()
    first = await client.get_property(ADDRESS)
    assert first.cached is False
    assert first.value_estimate == Decimal("450000.00")
    assert first.property_tax_annual == Decimal("8100.00") and first.tax_year == 2025
    assert first.property_tax_rate_pct == Decimal("1.8")
    assert first.zip == "78704" and not first.warnings
    req = router.routes["avm"].calls.last.request
    assert req.headers["X-Api-Key"] == RENTCAST_KEY
    assert "api_key" not in str(req.url)

    again = await client.get_property("4512 LARKSPUR BEND austin tx 78704")
    assert again.cached is True
    assert router.routes["properties"].call_count == 1 and router.routes["avm"].call_count == 1
    assert client.requests_this_month() == 2

    clock.advance(timedelta(days=31))
    assert (await client.get_property(ADDRESS)).cached is False
    assert router.routes["avm"].call_count == 2


async def test_rentcast_404_is_cached_and_soft(
    router: respx.MockRouter, make_rentcast: MakeRentCast
) -> None:
    router.routes["properties"].respond(404, json={"message": "No data"})
    router.routes["avm"].respond(404, json={"message": "No data"})
    client = make_rentcast()
    prop = await client.get_property("1 Nowhere Rd, Austin, TX 78704")
    assert prop.value_estimate is None and prop.property_tax_rate_pct is None
    assert prop.zip == "78704"  # parsed from the address
    assert len(prop.warnings) == 2
    await client.get_property("1 Nowhere Road, Austin TX 78704")
    assert router.routes["properties"].call_count == 1  # the empty answer was cached


async def test_rentcast_local_quota_exceeded_falls_back(
    router: respx.MockRouter, make_rentcast: MakeRentCast, clock: FixedClock
) -> None:
    client = make_rentcast(limit=3)
    await client.get_property(ADDRESS)  # 2 requests
    prop = await client.get_property("9 Other St, Austin, TX 78704")  # 1 left: record yes, AVM no
    assert prop.value_estimate is None
    assert any("budget" in w for w in prop.warnings)
    assert router.routes["avm"].call_count == 1
    assert client.requests_this_month() == 3
    # Cached addresses still answer with the budget spent.
    assert (await client.get_property(ADDRESS)).value_estimate == Decimal("450000.00")
    # The budget resets with the calendar month.
    clock.advance(timedelta(days=31))
    assert client.requests_this_month() == 0


@pytest.mark.parametrize("status", [429, 401, 503])
async def test_rentcast_api_unavailable_fails_soft(
    status: int, router: respx.MockRouter, make_rentcast: MakeRentCast
) -> None:
    router.routes["properties"].respond(status)
    router.routes["avm"].respond(status)
    prop = await make_rentcast().get_property(ADDRESS)
    assert prop.value_estimate is None and prop.property_tax_annual is None
    assert prop.cached is False
    assert len(prop.warnings) == 2 and all(str(status) in w for w in prop.warnings)
    assert all(RENTCAST_KEY not in w for w in prop.warnings)


async def test_file_cache_survives_restart(tmp_path: Path, clock: FixedClock) -> None:
    a = FileCache(tmp_path, clock)
    a.set("rentcast:/avm/value:1 main st", {"price": 1})
    entry = FileCache(tmp_path, clock).get("rentcast:/avm/value:1 main st")
    assert entry is not None and entry.value == {"price": 1}
    assert entry.stored_at == clock.now()
    assert all("main" not in p.name for p in tmp_path.iterdir())
