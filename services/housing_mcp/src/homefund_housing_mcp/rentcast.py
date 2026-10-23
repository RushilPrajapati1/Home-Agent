"""Value estimate and property tax from RentCast, cached 30 days per normalized address.

The free tier is about 50 requests a month and overages are billed, so every response
(404s included) is cached, and a local monthly budget stops requests before RentCast would
charge. When the budget, the key or the API is unavailable, results come back empty with
a warning instead of an error.
"""

from __future__ import annotations

import asyncio
import re
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from homefund_contracts import Clock
from homefund_housing_mcp.cache import Cache
from homefund_housing_mcp.config import RENTCAST_TTL
from homefund_housing_mcp.http import SafeClient, UpstreamError
from homefund_housing_mcp.models import PropertyInfo

BASE_URL = "https://api.rentcast.io/v1"
PROPERTIES_URL = f"{BASE_URL}/properties"
AVM_URL = f"{BASE_URL}/avm/value"
SOURCE = "RentCast property records and AVM value estimate"

_SUFFIXES = {
    "street": "st", "avenue": "ave", "road": "rd", "drive": "dr", "lane": "ln",
    "boulevard": "blvd", "court": "ct", "place": "pl", "terrace": "ter", "circle": "cir",
    "parkway": "pkwy", "highway": "hwy", "north": "n", "south": "s", "east": "e", "west": "w",
    "apartment": "apt", "suite": "ste",
}  # fmt: skip
_ZIP_RE = re.compile(r"\b(\d{5})(?:-\d{4})?\b")
_RATE_PLACES = Decimal("0.0001")


class QuotaExceeded(RuntimeError):
    pass


def normalize_address(address: str) -> str:
    """Cache key for an address: case, punctuation and common suffix spellings folded."""
    words = re.sub(r"[^\w#]+", " ", address.lower()).split()
    return " ".join(_SUFFIXES.get(w, w) for w in words)


def _money(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        # RentCast sends JSON numbers; go through str so a float never becomes the Decimal.
        return Decimal(str(value)).quantize(Decimal("0.01"), ROUND_HALF_UP)
    except ArithmeticError:
        return None


def _latest_tax(record: dict[str, Any]) -> tuple[Decimal | None, int | None]:
    taxes = record.get("propertyTaxes") or {}
    years = sorted((y for y in taxes if str(y).isdigit()), key=int, reverse=True)
    for year in years:
        total = _money((taxes[year] or {}).get("total"))
        if total is not None and total > 0:
            return total, int(year)
    return None, None


class RentCastClient:
    def __init__(
        self,
        http: SafeClient,
        cache: Cache,
        clock: Clock,
        api_key: str,
        monthly_limit: int,
    ) -> None:
        self._http = http
        self._cache = cache
        self._clock = clock
        self._api_key = api_key
        self._limit = monthly_limit
        self._quota_lock = asyncio.Lock()

    def _quota_key(self) -> str:
        return f"rentcast:quota:{self._clock.today():%Y-%m}"

    def requests_this_month(self) -> int:
        entry = self._cache.get(self._quota_key())
        return int(entry.value) if entry is not None else 0

    async def _spend_one(self) -> None:
        async with self._quota_lock:
            used = self.requests_this_month()
            if used >= self._limit:
                raise QuotaExceeded(f"RentCast monthly budget of {self._limit} requests is used up")
            self._cache.set(self._quota_key(), used + 1)

    async def _cached_get(self, url: str, address: str) -> tuple[Any, bool]:
        """(payload or None for 'no record', served_from_cache)."""
        key = f"rentcast:{url.removeprefix(BASE_URL)}:{normalize_address(address)}"
        entry = self._cache.get(key)
        if entry is not None and entry.fresh(self._clock, RENTCAST_TTL):
            return entry.value, True
        if not self._api_key:
            raise UpstreamError(url, None, "RENTCAST_API_KEY is not set")
        try:
            payload = await self._http.get_json(
                url,
                params={"address": address},
                headers={"X-Api-Key": self._api_key, "Accept": "application/json"},
                before_attempt=self._spend_one,
            )
        except UpstreamError as exc:
            if exc.status != 404:
                raise
            payload = None
        self._cache.set(key, payload)
        return payload, False

    async def get_property(self, address: str) -> PropertyInfo:
        address = " ".join(address.split())
        warnings: list[str] = []
        record: dict[str, Any] | None = None
        avm: dict[str, Any] | None = None
        cached = True
        try:
            records, hit = await self._cached_get(PROPERTIES_URL, address)
            cached &= hit
            if isinstance(records, list) and records:
                record = records[0]
            elif records is None or records == []:
                warnings.append("RentCast has no property record for this address")
        except (UpstreamError, QuotaExceeded) as exc:
            cached = False
            warnings.append(f"RentCast property record unavailable: {exc}")
        try:
            avm, hit = await self._cached_get(AVM_URL, address)
            cached &= hit
            if avm is None:
                warnings.append("RentCast has no value estimate for this address")
        except (UpstreamError, QuotaExceeded) as exc:
            cached = False
            warnings.append(f"RentCast value estimate unavailable: {exc}")

        zip_code = (record or {}).get("zipCode") or ((avm or {}).get("subjectProperty") or {}).get(
            "zipCode"
        )
        if not zip_code and (m := _ZIP_RE.search(address)):
            zip_code = m.group(1)
        value = _money((avm or {}).get("price"))
        tax, tax_year = _latest_tax(record or {})
        rate = None
        if tax is not None and value:
            rate = (tax / value * 100).quantize(_RATE_PLACES, ROUND_HALF_UP)
        elif tax is not None:
            warnings.append("Property tax found but no value estimate, so no tax rate")
        return PropertyInfo(
            address=(record or {}).get("formattedAddress") or address,
            zip=zip_code,
            value_estimate=value,
            value_low=_money((avm or {}).get("priceRangeLow")),
            value_high=_money((avm or {}).get("priceRangeHigh")),
            property_tax_annual=tax,
            tax_year=tax_year,
            property_tax_rate_pct=rate,
            cached=cached,
            warnings=warnings,
        )
