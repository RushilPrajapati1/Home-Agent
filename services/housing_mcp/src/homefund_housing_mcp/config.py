"""Runtime settings and every cost assumption housing-mcp uses, each with its source.

Rates are percentage points as Decimal (``Decimal("0.5")`` is 0.5%). Anything a user can
override (insurance quote, address for property tax) is a tool parameter, not config.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from homefund_contracts import CreditScoreRange

# --- Runtime ------------------------------------------------------------------------------

FRED_TTL = timedelta(days=7)
RENTCAST_TTL = timedelta(days=30)
# RentCast's free tier is 50 requests a month and bills overages instead of rejecting them,
# so we stop ourselves. https://developers.rentcast.io/reference/billing-and-pricing
RENTCAST_MONTHLY_LIMIT = 50


@dataclass(frozen=True)
class Settings:
    fred_api_key: str
    rentcast_api_key: str
    use_mocks: bool
    mocks_dir: Path
    cache_dir: Path
    rentcast_monthly_limit: int = RENTCAST_MONTHLY_LIMIT
    timeout_s: float = 10.0
    retries: int = 2
    host: str = "0.0.0.0"  # noqa: S104 - inside the private compose network only
    port: int = 8102

    def __repr__(self) -> str:
        # Keys must never reach a log line, including via repr().
        return (
            f"Settings(use_mocks={self.use_mocks}, cache_dir={self.cache_dir}, "
            f"fred_api_key={'set' if self.fred_api_key else 'unset'}, "
            f"rentcast_api_key={'set' if self.rentcast_api_key else 'unset'})"
        )

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        e = os.environ if env is None else env
        repo_mocks = Path(__file__).resolve().parents[4] / "fixtures" / "mocks"
        return cls(
            fred_api_key=e.get("FRED_API_KEY", "").strip(),
            rentcast_api_key=e.get("RENTCAST_API_KEY", "").strip(),
            use_mocks=e.get("HOUSING_USE_MOCKS", "false").strip().lower() in {"1", "true", "yes"},
            mocks_dir=Path(e.get("HOUSING_MOCKS_DIR", str(repo_mocks))),
            cache_dir=Path(e.get("HOUSING_CACHE_DIR", ".cache/housing_mcp")),
            rentcast_monthly_limit=int(
                e.get("RENTCAST_MONTHLY_LIMIT", str(RENTCAST_MONTHLY_LIMIT))
            ),
            host=e.get("HOUSING_MCP_HOST", "0.0.0.0"),  # noqa: S104
            port=int(e.get("HOUSING_MCP_PORT", "8102")),
        )


# --- Cost assumptions ---------------------------------------------------------------------


@dataclass(frozen=True)
class Source:
    name: str
    url: str | None = None


HOME_FUND_DEFAULT = Source("Home Fund planning default; replace with a lender estimate or quote")

TERM_MONTHS = 360
TERM_SOURCE = Source(
    "Freddie Mac PMMS 30-year fixed (FRED MORTGAGE30US)",
    "https://fred.stlouisfed.org/series/MORTGAGE30US",
)

CLOSING_COST_PCT = Decimal("3")
CLOSING_COST_SOURCE = HOME_FUND_DEFAULT

RESERVE_MONTHS = 2
RESERVES_SOURCE = Source("Home Fund convention: 2 x PITI, rounded to the nearest $100")

INSURANCE_PCT = Decimal("0.5")
INSURANCE_SOURCE = HOME_FUND_DEFAULT

# Conventional PMI below 20% down, annual percent of the loan.
PMI_PCT = Decimal("0.5")
PMI_DOWN_THRESHOLD_PCT = Decimal("20")
PMI_SOURCE = Source(
    "Home Fund planning default; CFPB: PMI may be required below 20% down",
    "https://www.consumerfinance.gov/ask-cfpb/what-is-private-mortgage-insurance-en-122/",
)

# FHA: 3.5% down is treated as an FHA loan. Mortgagee Letter 2023-05 (effective for case
# numbers endorsed on or after 2023-03-20) is still current as of 2026-10-21: later letters
# (e.g. ML 2026-11, credit score methodology) point to Handbook 4000.1 Appendix 1.0
# without changing the forward-mortgage premiums.
FHA_DOWN_PCT = Decimal("3.5")
FHA_UFMIP_PCT = Decimal("1.75")
FHA_BASE_LOAN_THRESHOLD = Decimal("726200")
FHA_LTV_BREAK_PCT = Decimal("95")
# Annual MIP for terms over 15 years: (base loan <= threshold, LTV > 95%) -> bps.
FHA_ANNUAL_MIP_PCT: dict[tuple[bool, bool], Decimal] = {
    (True, True): Decimal("0.55"),
    (True, False): Decimal("0.50"),
    (False, True): Decimal("0.75"),
    (False, False): Decimal("0.70"),
}
FHA_MIP_SOURCE = Source(
    "HUD Mortgagee Letter 2023-05 (Handbook 4000.1 Appendix 1.0)",
    "https://archives.hud.gov/news/2024/2023-05hsgml.pdf",
)

# PMMS describes borrowers with good/excellent credit and 20% down, so 740+ (and an
# unknown score) gets no adjustment. The spreads for lower bands are our own estimate.
CREDIT_BAND_ADJUST_PCT: dict[CreditScoreRange, Decimal] = {
    CreditScoreRange.AT_LEAST_740: Decimal("0"),
    CreditScoreRange.FROM_680_TO_739: Decimal("0.25"),
    CreditScoreRange.FROM_620_TO_679: Decimal("0.75"),
    CreditScoreRange.BELOW_620: Decimal("1.5"),
}
CREDIT_BAND_SOURCE = Source(
    "Home Fund estimate over Freddie Mac PMMS (good/excellent credit, 20% down)",
    "https://www.freddiemac.com/pmms/about-pmms",
)

# Effective property tax rate on owner-occupied housing, 2024 (Census ACS B25082/B25090,
# Tax Foundation calculations), published 2026-03-16.
STATE_TAX_SOURCE = Source(
    "Tax Foundation, Property Taxes by State and County, 2026 (2024 effective rates)",
    "https://taxfoundation.org/data/all/state/property-taxes-by-state-county/",
)
STATE_PROPERTY_TAX_PCT: dict[str, Decimal] = {
    k: Decimal(v)
    for k, v in {
        "AL": "0.37", "AK": "0.94", "AZ": "0.48", "AR": "0.56", "CA": "0.70", "CO": "0.50",
        "CT": "1.54", "DE": "0.54", "DC": "0.60", "FL": "0.78", "GA": "0.79", "HI": "0.29",
        "ID": "0.50", "IL": "1.88", "IN": "0.76", "IA": "1.33", "KS": "1.21", "KY": "0.74",
        "LA": "0.55", "ME": "0.98", "MD": "0.92", "MA": "1.00", "MI": "1.19", "MN": "1.00",
        "MS": "0.58", "MO": "0.89", "MT": "0.61", "NE": "1.44", "NV": "0.50", "NH": "1.50",
        "NJ": "1.88", "NM": "0.63", "NY": "1.30", "NC": "0.66", "ND": "0.92", "OH": "1.36",
        "OK": "0.79", "OR": "0.81", "PA": "1.26", "RI": "1.12", "SC": "0.49", "SD": "1.00",
        "TN": "0.52", "TX": "1.40", "UT": "0.48", "VT": "1.51", "VA": "0.78", "WA": "0.75",
        "WV": "0.51", "WI": "1.32", "WY": "0.53",
    }.items()
}  # fmt: skip
