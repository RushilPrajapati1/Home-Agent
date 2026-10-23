"""housing-mcp: FastMCP server (streamable HTTP) with the three tools on the design's APIs page.

No LLM calls and no database. Every figure is computed in ``costs`` with Decimal.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from decimal import Decimal

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from pydantic import ValidationError
from starlette.requests import Request
from starlette.responses import JSONResponse

from homefund_contracts import Clock, CreditScoreRange, Money, Percent, ZipCode, clock_from_env
from homefund_contracts.mcp.housing import SERVER, EstimateHomeCostInput, GetPropertyInput
from homefund_housing_mcp import costs
from homefund_housing_mcp.cache import Cache, FileCache
from homefund_housing_mcp.config import Settings
from homefund_housing_mcp.fred import FredClient, RateUnavailable
from homefund_housing_mcp.http import SafeClient
from homefund_housing_mcp.mocks import fixture_transport
from homefund_housing_mcp.models import HomeCost, MortgageRate, PropertyInfo
from homefund_housing_mcp.rentcast import RentCastClient

log = logging.getLogger(__name__)

MOCK_KEY = "mock-key"


@dataclass
class HousingService:
    fred: FredClient
    rentcast: RentCastClient
    http: SafeClient

    @classmethod
    def build(
        cls,
        settings: Settings,
        *,
        clock: Clock,
        cache: Cache | None = None,
        http: SafeClient | None = None,
    ) -> HousingService:
        if http is None:
            transport = fixture_transport(settings.mocks_dir) if settings.use_mocks else None
            http = SafeClient(
                timeout_s=settings.timeout_s, retries=settings.retries, transport=transport
            )
        cache = cache if cache is not None else FileCache(settings.cache_dir, clock)
        fred_key = settings.fred_api_key or (MOCK_KEY if settings.use_mocks else "")
        rc_key = settings.rentcast_api_key or (MOCK_KEY if settings.use_mocks else "")
        return cls(
            fred=FredClient(http, cache, clock, fred_key),
            rentcast=RentCastClient(http, cache, clock, rc_key, settings.rentcast_monthly_limit),
            http=http,
        )

    async def get_mortgage_rate(self) -> MortgageRate:
        try:
            return await self.fred.get_rate()
        except RateUnavailable as exc:
            raise ToolError(str(exc)) from None

    async def get_property(self, address: str) -> PropertyInfo:
        try:
            GetPropertyInput(address=address)
        except ValidationError as exc:
            raise ToolError(f"invalid address: {exc.errors()[0]['msg']}") from None
        return await self.rentcast.get_property(address)

    async def estimate_home_cost(
        self,
        price: Decimal,
        zip: str,
        down_pct: Decimal,
        credit_band: CreditScoreRange | None = None,
        address: str | None = None,
        insurance_annual: Decimal | None = None,
    ) -> HomeCost:
        try:
            req = EstimateHomeCostInput(price=price, zip=zip, down_pct=down_pct)
        except ValidationError as exc:
            raise ToolError(f"invalid input: {exc.errors()[0]['msg']}") from None
        if req.down_pct >= 100:
            raise ToolError("down_pct must be below 100")
        if insurance_annual is not None and insurance_annual < 0:
            raise ToolError("insurance_annual must not be negative")
        rate = await self.get_mortgage_rate()
        warnings = [*rate.warnings]
        prop = None
        if address:
            prop = await self.get_property(address)
            warnings += prop.warnings
            if prop.property_tax_rate_pct is None:
                warnings.append("No RentCast tax rate for the address; used the state default")
        return costs.estimate(
            price=req.price,
            zip_code=req.zip,
            down_pct=req.down_pct,
            rate=costs.RateInput(
                rate.rate_pct,
                rate.as_of,
                f"FRED {rate.series} weekly average" + (" (cached)" if rate.cached else ""),
                rate.source_url,
            ),
            credit_band=credit_band,
            prop=prop,
            insurance_annual=insurance_annual,
            warnings=warnings,
        )


def build_server(service: HousingService) -> FastMCP:
    mcp = FastMCP(
        SERVER,
        instructions=(
            "Prices a specific home: cash needed (down payment, closing costs, reserves) and the "
            "monthly payment, from the FRED 30-year rate and RentCast property tax. Every "
            "figure is computed by the tool; quote them as returned."
        ),
    )

    @mcp.tool
    async def estimate_home_cost(
        price: Money,
        zip: ZipCode,
        down_pct: Percent,
        credit_band: CreditScoreRange | None = None,
        address: str | None = None,
        insurance_annual: Money | None = None,
    ) -> HomeCost:
        """Down payment, closing costs, reserves, PITI and PMI for one home.

        Money and percents are decimal strings ("420000.00", "10" for 10%). Pass `address`
        to use the property's RentCast tax record, and `insurance_annual` for a real quote.
        """
        return await service.estimate_home_cost(
            price, zip, down_pct, credit_band, address, insurance_annual
        )

    @mcp.tool
    async def get_mortgage_rate() -> MortgageRate:
        """Latest weekly 30-year fixed rate (FRED MORTGAGE30US), cached 7 days."""
        return await service.get_mortgage_rate()

    @mcp.tool
    async def get_property(address: str) -> PropertyInfo:
        """Value estimate and property tax from RentCast, cached 30 days per address.

        Fails soft: when RentCast or its monthly quota is unavailable, fields come back
        empty and `warnings` says why.
        """
        return await service.get_property(address)

    @mcp.custom_route("/healthz", methods=["GET"])
    async def healthz(_: Request) -> JSONResponse:
        return JSONResponse({"status": "ok"})

    return mcp


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    os.environ.setdefault("FASTMCP_CHECK_FOR_UPDATES", "off")
    settings = Settings.from_env()
    log.info("starting housing-mcp: %r", settings)
    service = HousingService.build(settings, clock=clock_from_env())
    build_server(service).run(
        transport="http", host=settings.host, port=settings.port, show_banner=False
    )


if __name__ == "__main__":
    main()
