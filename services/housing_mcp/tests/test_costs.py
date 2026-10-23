from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from homefund_housing_mcp import config as cfg
from homefund_housing_mcp.costs import (
    RateInput,
    estimate,
    monthly_payment,
    national_default_tax_pct,
    round_to_hundred,
)
from homefund_housing_mcp.models import HomeCost, PropertyInfo
from homefund_housing_mcp.zip_states import state_for_zip

from homefund_contracts import CostBreakdown, CreditScoreRange

D = Decimal
RATE = RateInput(D("6.27"), date(2026, 9, 24), "FRED MORTGAGE30US", None)


def est(
    price: str = "420000",
    down: str = "10",
    *,
    credit_band: CreditScoreRange | None = None,
    prop: PropertyInfo | None = None,
    insurance_annual: Decimal | None = None,
) -> HomeCost:
    return estimate(
        price=D(price),
        zip_code="78704",
        down_pct=D(down),
        rate=RATE,
        credit_band=credit_band,
        prop=prop,
        insurance_annual=insurance_annual,
    )


# Standard 30-year fixed amortization table values (monthly P&I).
@pytest.mark.parametrize(
    ("principal", "rate", "expected"),
    [
        ("100000", "6", "599.55"),
        ("100000", "5", "536.82"),
        ("200000", "4.5", "1013.37"),
        ("300000", "7", "1995.91"),
        ("378000", "6.27", "2332.33"),  # golden walkthrough
    ],
)
def test_amortization_matches_published_table(principal: str, rate: str, expected: str) -> None:
    assert monthly_payment(D(principal), D(rate), 360) == D(expected)


def test_amortization_zero_rate_and_zero_principal() -> None:
    assert monthly_payment(D("360000"), D("0"), 360) == D("1000.00")
    assert monthly_payment(D("0"), D("6"), 360) == D("0.00")


def test_reserves_round_half_up_to_hundred() -> None:
    assert round_to_hundred(D("6274.66")) == D("6300.00")
    assert round_to_hundred(D("6250.00")) == D("6300.00")
    assert round_to_hundred(D("6249.99")) == D("6200.00")


def test_pmi_on_below_20_percent_down() -> None:
    c = est(down="10")
    assert c.pmi_rate_pct == D("0.5")
    assert c.pmi_monthly == D("157.50")  # 378,000 x 0.5% / 12
    assert c.monthly_payment == c.piti_monthly + c.pmi_monthly


@pytest.mark.parametrize("down", ["20", "25"])
def test_pmi_off_at_or_above_20_percent(down: str) -> None:
    c = est(down=down)
    assert c.pmi_rate_pct == 0
    assert c.pmi_monthly == D("0.00")
    assert c.monthly_payment == c.piti_monthly


def test_pmi_on_just_below_20() -> None:
    assert est(down="19.99").pmi_monthly > 0


def test_fha_path_at_3_5_percent_down() -> None:
    c = est(price="300000", down="3.5")
    base_loan = D("289500.00")  # 300,000 - 10,500
    ufmip = D("5066.25")  # 1.75% of base loan, financed
    assert c.down_payment == D("10500.00")
    assert c.loan_amount == base_loan + ufmip
    assert c.principal_interest_monthly == monthly_payment(base_loan + ufmip, D("6.27"), 360)
    # LTV 96.5% > 95% and base loan <= $726,200 -> 55 bps annual MIP on the base loan.
    assert c.pmi_rate_pct == D("0.55")
    assert c.pmi_monthly == D("132.69")  # 289,500 x 0.55% / 12
    # UFMIP is financed, so it is not cash needed.
    assert c.cash_needed == c.down_payment + c.closing_costs + c.reserves
    items = {a.item: a for a in c.assumptions}
    assert items["loan_type"].value.startswith("FHA")
    assert "2023-05" in items["fha_annual_mip_pct"].source
    assert items["fha_upfront_mip"].url == cfg.FHA_MIP_SOURCE.url


def test_fha_high_balance_tier() -> None:
    c = est(price="800000", down="3.5")  # base loan 772,000 > 726,200
    assert c.pmi_rate_pct == D("0.75")


def test_three_percent_down_is_conventional_pmi() -> None:
    c = est(down="3")
    assert c.pmi_rate_pct == cfg.PMI_PCT
    assert c.loan_amount == D("407400.00")


def test_credit_band_shifts_rate() -> None:
    assert est().rate_pct == D("6.27")
    assert est(credit_band=CreditScoreRange.AT_LEAST_740).rate_pct == D("6.27")
    low = est(credit_band=CreditScoreRange.FROM_620_TO_679)
    assert low.rate_pct == D("7.02")
    assert low.principal_interest_monthly == monthly_payment(D("378000"), D("7.02"), 360)


def test_state_default_tax_by_zip_prefix() -> None:
    assert state_for_zip("78704") == "TX"
    assert state_for_zip("10001") == "NY"
    assert state_for_zip("94110") == "CA"
    assert state_for_zip("73301") == "TX"  # IRS Austin, inside Oklahoma's range
    assert state_for_zip("00901") is None  # Puerto Rico
    c = est()
    assert c.property_tax_rate_pct == D("1.40")
    assert c.property_tax_monthly == D("490.00")
    tax = next(a for a in c.assumptions if a.item == "property_tax_pct")
    assert tax.url == cfg.STATE_TAX_SOURCE.url


def test_unknown_state_uses_national_average_with_warning() -> None:
    c = estimate(price=D("200000"), zip_code="00901", down_pct=D("20"), rate=RATE)
    assert c.property_tax_rate_pct == national_default_tax_pct()
    assert c.warnings


def test_rentcast_tax_rate_wins_when_known() -> None:
    prop = PropertyInfo(
        address="x",
        value_estimate=D("450000"),
        property_tax_annual=D("8100"),
        tax_year=2025,
        property_tax_rate_pct=D("1.8"),
    )
    c = est(prop=prop)
    assert c.property_tax_monthly == D("630.00")
    tax = next(a for a in c.assumptions if a.item == "property_tax_pct")
    assert "RentCast" in tax.source


def test_insurance_quote_overrides_default() -> None:
    assert est().insurance_monthly == D("175.00")
    c = est(insurance_annual=D("1800"))
    assert c.insurance_monthly == D("150.00")
    assert c.insurance_rate_pct == D("0.4286")


def test_every_assumption_has_a_source_and_output_fits_the_contract() -> None:
    c = est(down="3.5")
    assert all(a.source for a in c.assumptions)
    items = {a.item for a in c.assumptions}
    assert {"closing_cost_pct", "base_rate_pct", "property_tax_pct", "reserve_months"} <= items
    # The superset still validates as the contract model once the extra fields are dropped.
    contract = CostBreakdown.model_validate(c.model_dump(exclude={"assumptions", "warnings"}))
    assert contract.cash_needed == c.cash_needed
