# housing-mcp contract requests

## 2026-10-21 · CostBreakdown.assumptions and warnings
Need: on `homefund_contracts.domain.CostBreakdown`, add
`assumptions: list[Assumption]` and `warnings: list[str] = []`, with
`Assumption(item: str, value: str, source: str, url: str | None = None)`.
Why: every cost assumption (closing %, base rate, credit-band adjustment, PMI/FHA MIP, tax rate, insurance, reserves) must carry its source so explain_costs and the plan checks can cite it, and fallbacks (RentCast down, stale FRED rate) must be visible.
Workaround: `homefund_housing_mcp.models.HomeCost(CostBreakdown)` adds both fields. The output is a strict superset, but `CostBreakdown.model_validate` on it fails (`extra="forbid"`). Consumers should drop the two keys or wait for this change.

## 2026-10-21 · Optional inputs on EstimateHomeCostInput
Need: `credit_band: CreditScoreRange | None = None`, `address: str | None = None`, `insurance_annual: Money | None = None` (all optional, so the design's `estimate_home_cost(price, zip, down_pct)` still works).
Why: credit score shifts the rate (design, Data & chunking page). The RentCast property tax needs an address, and "insurance … unless you enter a quote" needs the quote. `HomeGoal` already has `address` and `credit_score_range`.
Workaround: the tool accepts them as optional parameters. `EstimateHomeCostInput` validates only the three design fields.

## 2026-10-21 · source_url / warnings on GetMortgageRateOutput, fail-soft GetPropertyOutput
Need: `GetMortgageRateOutput.source_url: str` and `warnings: list[str] = []`. On `GetPropertyOutput`, make `zip` and `value_estimate` optional, and add `cached: bool = False` and `warnings: list[str] = []`.
Why: the rate must cite its source. get_property must fail soft (empty fields plus a warning) when RentCast or its quota is unavailable, and today `value_estimate` and `zip` are required.
Workaround: `models.MortgageRate` and `models.PropertyInfo` (subclasses that override the two fields with `type: ignore[assignment]`).

## 2026-10-21 · Golden scenario: property tax with no address
Need: regenerate `fixtures/golden_scenario.json` (and the walkthrough copy) for a request that has only a ZIP. Either:
- (a) keep the goal and use the TX state default, 1.40% (Tax Foundation, 2024 rates, published 2026-03). Then property_tax_monthly 490.00, piti 2997.33, reserves **6000.00**, cash_needed **60600.00** and monthly_payment 3154.83. Downstream: gap 42600.00, monthly_needed 2130.00, gap_per_month 930.00. Current pace still reaches 2029-10 (36 months), and the $952 illustrative cuts still clear the gap. Or:
- (b) add `"address": "4512 Larkspur Bend, Austin, TX 78704"` to the goal, so tax comes from the RentCast fixture (1.8%) and every current number stays.
Why: mock_inputs price tax at 1.8% from "a RentCast record in ZIP 78704", but this lane's rule (agreed with the user) is: RentCast for a known address, else the state default by ZIP prefix. With no address in the request, $6,300 / $60,900 isn't reachable honestly.
Workaround: `test_golden_reserves_and_cash_needed` is `xfail(strict=True)`, so it will XPASS (and fail) once the golden changes, and the marker should then be removed. The down payment, closing, P&I, insurance and PMI golden figures pass today. The address path reproduces every golden figure (`test_walkthrough_with_fixture_address_reproduces_golden`).

## 2026-10-21 · respx in the root dev group
Need: `respx>=0.22` in the root `[dependency-groups] dev`.
Why: a root `uv sync` (CI, `make test`) doesn't install members' dependency-groups, so a lane-level dev group never reaches the test run.
Workaround: respx is a runtime dependency of homefund-housing-mcp, and moves out when the root group has it.

## 2026-10-21 · Infra and foundation notes (no contract change)
- Egress proxy for housing-mcp: allow only `api.stlouisfed.org` and `api.rentcast.io` (HTTPS). The app already refuses anything else.
- uv 0.11.28 warns that `build-system.requires = ["uv_build>=0.9,<0.10"]` doesn't include the current uv. All workspace members share this.
- `HOUSING_MCP_URL` in `.env.example` already matches (`:8102/mcp`). Consider adding `RENTCAST_MONTHLY_LIMIT=50` and `HOUSING_LIVE_TESTS=` to `.env.example`.
