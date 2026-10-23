"""Cash needed and monthly payment for one home. Pure Decimal math, no I/O.

Conventions (fixtures/golden_scenario.json): every money figure rounds half-up to cents;
reserves are reserve_months x PITI rounded half-up to the nearest $100; PMI (or FHA annual
MIP) is reported separately and is not part of PITI or reserves.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, localcontext

from homefund_contracts import CreditScoreRange
from homefund_housing_mcp import config as cfg
from homefund_housing_mcp.models import Assumption, HomeCost, PropertyInfo
from homefund_housing_mcp.rentcast import SOURCE as RENTCAST_SOURCE
from homefund_housing_mcp.zip_states import ZIP_PREFIX_SOURCE, state_for_zip

CENT = Decimal("0.01")
HUNDRED = Decimal("100")
TWELVE = Decimal("12")
RATE_PLACES = Decimal("0.0001")


def cents(x: Decimal) -> Decimal:
    return x.quantize(CENT, ROUND_HALF_UP)


def pct_of(amount: Decimal, pct: Decimal) -> Decimal:
    return amount * pct / HUNDRED


def monthly_payment(principal: Decimal, annual_rate_pct: Decimal, months: int) -> Decimal:
    """Level payment by the standard amortization formula, M = P r / (1 - (1 + r)^-n)."""
    if principal <= 0:
        return Decimal("0.00")
    if annual_rate_pct == 0:
        return cents(principal / months)
    with localcontext() as ctx:
        ctx.prec = 40
        r = annual_rate_pct / HUNDRED / TWELVE
        growth = (1 + r) ** months
        return cents(principal * r * growth / (growth - 1))


def round_to_hundred(x: Decimal) -> Decimal:
    return ((x / HUNDRED).quantize(Decimal("1"), ROUND_HALF_UP) * HUNDRED).quantize(CENT)


def national_default_tax_pct() -> Decimal:
    rates = cfg.STATE_PROPERTY_TAX_PCT.values()
    return (sum(rates, Decimal(0)) / len(rates)).quantize(Decimal("0.01"), ROUND_HALF_UP)


@dataclass(frozen=True)
class RateInput:
    rate_pct: Decimal
    as_of: date | None
    source: str
    url: str | None


def _a(item: str, value: object, source: cfg.Source | str, url: str | None = None) -> Assumption:
    if isinstance(source, cfg.Source):
        return Assumption(item=item, value=str(value), source=source.name, url=source.url)
    return Assumption(item=item, value=str(value), source=source, url=url)


def estimate(
    *,
    price: Decimal,
    zip_code: str,
    down_pct: Decimal,
    rate: RateInput,
    credit_band: CreditScoreRange | None = None,
    prop: PropertyInfo | None = None,
    insurance_annual: Decimal | None = None,
    warnings: list[str] | None = None,
) -> HomeCost:
    notes: list[Assumption] = []
    warnings = list(warnings or [])

    # Down payment and closing.
    down_payment = cents(pct_of(price, down_pct))
    base_loan = price - down_payment
    closing_costs = cents(pct_of(price, cfg.CLOSING_COST_PCT))
    notes.append(
        _a("closing_cost_pct", f"{cfg.CLOSING_COST_PCT}% of price", cfg.CLOSING_COST_SOURCE)
    )

    # Rate: FRED weekly average, shifted by credit band.
    notes.append(_a("base_rate_pct", f"{rate.rate_pct}% as of {rate.as_of}", rate.source, rate.url))
    adjust = cfg.CREDIT_BAND_ADJUST_PCT[credit_band] if credit_band else Decimal(0)
    band = credit_band.value if credit_band else "not given (treated as 740+)"
    notes.append(
        _a("credit_band_adjust_pct", f"+{adjust} for credit {band}", cfg.CREDIT_BAND_SOURCE)
    )
    rate_pct = rate.rate_pct + adjust

    # Mortgage insurance: FHA at exactly 3.5% down, conventional PMI below 20%.
    is_fha = down_pct == cfg.FHA_DOWN_PCT
    if is_fha:
        ltv = base_loan / price * HUNDRED
        small = base_loan <= cfg.FHA_BASE_LOAN_THRESHOLD
        mi_pct = cfg.FHA_ANNUAL_MIP_PCT[(small, ltv > cfg.FHA_LTV_BREAK_PCT)]
        ufmip = cents(pct_of(base_loan, cfg.FHA_UFMIP_PCT))
        loan_amount = base_loan + ufmip
        # Annual MIP is charged on the base loan; first-year balance approximates it.
        mi_monthly = cents(pct_of(base_loan, mi_pct) / TWELVE)
        notes.append(_a("loan_type", "FHA (3.5% down)", cfg.FHA_MIP_SOURCE))
        notes.append(
            _a(
                "fha_upfront_mip",
                f"{cfg.FHA_UFMIP_PCT}% of base loan = ${ufmip}, financed into the loan",
                cfg.FHA_MIP_SOURCE,
            )
        )
        notes.append(
            _a(
                "fha_annual_mip_pct",
                f"{mi_pct}% of base loan (LTV {ltv.quantize(Decimal('0.01'))}%, "
                f"base loan {'<=' if small else '>'} ${cfg.FHA_BASE_LOAN_THRESHOLD:,})",
                cfg.FHA_MIP_SOURCE,
            )
        )
    else:
        loan_amount = base_loan
        mi_pct = cfg.PMI_PCT if down_pct < cfg.PMI_DOWN_THRESHOLD_PCT else Decimal(0)
        mi_monthly = cents(pct_of(loan_amount, mi_pct) / TWELVE)
        notes.append(_a("loan_type", "conventional", cfg.TERM_SOURCE))
        if mi_pct:
            notes.append(_a("pmi_pct", f"{mi_pct}% of loan a year (down < 20%)", cfg.PMI_SOURCE))
        else:
            notes.append(_a("pmi_pct", "0 (down >= 20%)", cfg.PMI_SOURCE))

    principal_interest = monthly_payment(loan_amount, rate_pct, cfg.TERM_MONTHS)
    notes.append(_a("term", f"{cfg.TERM_MONTHS} months, fixed", cfg.TERM_SOURCE))

    # Property tax: the RentCast record when an address was looked up, else a state default.
    if prop is not None and prop.property_tax_rate_pct is not None:
        tax_pct = prop.property_tax_rate_pct
        notes.append(
            _a(
                "property_tax_pct",
                f"{tax_pct}% (${prop.property_tax_annual} {prop.tax_year} tax on "
                f"${prop.value_estimate} value)",
                f"{RENTCAST_SOURCE} for {prop.address}",
                "https://developers.rentcast.io/reference",
            )
        )
    else:
        state = state_for_zip(zip_code)
        if state is not None:
            tax_pct = cfg.STATE_PROPERTY_TAX_PCT[state]
            notes.append(
                _a(
                    "property_tax_pct",
                    f"{tax_pct}% ({state} average, ZIP {zip_code[:3]}xx via {ZIP_PREFIX_SOURCE})",
                    cfg.STATE_TAX_SOURCE,
                )
            )
        else:
            tax_pct = national_default_tax_pct()
            warnings.append(f"No state found for ZIP {zip_code}; used the national average")
            notes.append(
                _a(
                    "property_tax_pct",
                    f"{tax_pct}% (unweighted average of state rates)",
                    cfg.STATE_TAX_SOURCE,
                )
            )
    property_tax_monthly = cents(pct_of(price, tax_pct) / TWELVE)

    # Insurance: the user's quote, else a percent of price.
    if insurance_annual is not None:
        insurance_monthly = cents(insurance_annual / TWELVE)
        insurance_pct = (insurance_annual / price * HUNDRED).quantize(RATE_PLACES, ROUND_HALF_UP)
        notes.append(_a("insurance", f"quote of ${cents(insurance_annual)} a year", "user quote"))
    else:
        insurance_pct = cfg.INSURANCE_PCT
        insurance_monthly = cents(pct_of(price, insurance_pct) / TWELVE)
        notes.append(_a("insurance_pct", f"{insurance_pct}% of price a year", cfg.INSURANCE_SOURCE))

    piti = principal_interest + property_tax_monthly + insurance_monthly
    reserves = round_to_hundred(piti * cfg.RESERVE_MONTHS)
    notes.append(_a("reserve_months", cfg.RESERVE_MONTHS, cfg.RESERVES_SOURCE))

    return HomeCost(
        price=cents(price),
        down_pct=down_pct,
        down_payment=down_payment,
        loan_amount=cents(loan_amount),
        closing_cost_pct=cfg.CLOSING_COST_PCT,
        closing_costs=closing_costs,
        reserve_months=cfg.RESERVE_MONTHS,
        reserves=reserves,
        cash_needed=down_payment + closing_costs + reserves,
        rate_pct=rate_pct,
        rate_as_of=rate.as_of,
        principal_interest_monthly=principal_interest,
        property_tax_rate_pct=tax_pct,
        property_tax_monthly=property_tax_monthly,
        insurance_rate_pct=insurance_pct,
        insurance_monthly=insurance_monthly,
        piti_monthly=piti,
        pmi_rate_pct=mi_pct,
        pmi_monthly=mi_monthly,
        monthly_payment=piti + mi_monthly,
        assumptions=notes,
        warnings=warnings,
    )
