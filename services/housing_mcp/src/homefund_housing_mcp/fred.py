"""Latest weekly 30-year fixed rate from FRED (Freddie Mac PMMS, series MORTGAGE30US)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from homefund_contracts import Clock
from homefund_housing_mcp.cache import Cache
from homefund_housing_mcp.config import FRED_TTL
from homefund_housing_mcp.http import SafeClient, UpstreamError
from homefund_housing_mcp.models import MortgageRate

SERIES = "MORTGAGE30US"
OBSERVATIONS_URL = "https://api.stlouisfed.org/fred/series/observations"
SOURCE_URL = f"https://fred.stlouisfed.org/series/{SERIES}"
CACHE_KEY = f"fred:{SERIES}:latest"


class RateUnavailable(RuntimeError):
    """FRED failed and nothing usable is cached. There is no made-up fallback rate."""


def latest_observation(payload: Any) -> tuple[Decimal, date]:
    """The most recent observation with a numeric value. FRED marks missing values '.'."""
    best: tuple[Decimal, date] | None = None
    for obs in payload.get("observations", []):
        try:
            value, day = Decimal(obs["value"]), date.fromisoformat(obs["date"])
        except (KeyError, TypeError, ValueError, InvalidOperation):
            continue
        if value.is_finite() and (best is None or day > best[1]):
            best = (value, day)
    if best is None:
        raise ValueError("no numeric MORTGAGE30US observations in the response")
    return best


class FredClient:
    def __init__(self, http: SafeClient, cache: Cache, clock: Clock, api_key: str) -> None:
        self._http = http
        self._cache = cache
        self._clock = clock
        self._api_key = api_key

    async def get_rate(self) -> MortgageRate:
        entry = self._cache.get(CACHE_KEY)
        if entry is not None and entry.fresh(self._clock, FRED_TTL):
            return self._result(entry.value, cached=True)
        try:
            payload = await self._fetch()
            rate, as_of = latest_observation(payload)
        except (UpstreamError, ValueError) as exc:
            if entry is None:
                raise RateUnavailable(f"FRED {SERIES} unavailable: {exc}") from None
            stale = self._result(entry.value, cached=True)
            stale.warnings.append(
                f"FRED unavailable ({exc}); using a cached rate older than 7 days"
            )
            return stale
        value = {"rate_pct": str(rate), "as_of": as_of.isoformat()}
        self._cache.set(CACHE_KEY, value)
        return self._result(value, cached=False)

    async def _fetch(self) -> Any:
        if not self._api_key:
            raise UpstreamError(OBSERVATIONS_URL, None, "FRED_API_KEY is not set")
        return await self._http.get_json(
            OBSERVATIONS_URL,
            params={
                "series_id": SERIES,
                "api_key": self._api_key,
                "file_type": "json",
                "sort_order": "desc",
                "limit": "10",
            },
        )

    @staticmethod
    def _result(value: dict[str, str], *, cached: bool) -> MortgageRate:
        return MortgageRate(
            series=SERIES,
            rate_pct=Decimal(value["rate_pct"]),
            as_of=date.fromisoformat(value["as_of"]),
            cached=cached,
            source_url=SOURCE_URL,
        )
