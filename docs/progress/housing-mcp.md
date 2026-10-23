# housing-mcp

## 2026-10-21 · FastMCP server with the three tools

Done:
- FastMCP 4.1 server, streamable HTTP on `:8102/mcp` (+ `/healthz`): `estimate_home_cost(price, zip, down_pct, credit_band=None, address=None, insurance_annual=None)`, `get_mortgage_rate()`, `get_property(address)`. No LLM, no DB; all money math is Decimal in `costs.py`.
- FRED MORTGAGE30US: latest numeric observation, cached 7 days (file cache on a volume); serves a stale cache with a warning if FRED is down; no invented fallback rate.
- RentCast: `/v1/properties` + `/v1/avm/value`, each response (404s too) cached 30 days by normalized address. Local monthly budget (`RENTCAST_MONTHLY_LIMIT=50`, counted per attempt) because RentCast bills overages rather than rejecting. Quota, 4xx/5xx and transport failures fail soft with warnings.
- Costs: 3% closing; P&I by amortization at FRED rate + credit-band spread; PMI 0.5%/yr below 20% down; FHA at exactly 3.5% down: 1.75% UFMIP financed, annual MIP 0.55/0.50/0.75/0.70% by base loan ($726,200) and LTV (95%) per HUD ML 2023-05 (checked 2026-10-21: ML 2026-11 doesn't change premiums); tax from RentCast when an address is given, else Tax Foundation 2024 state rate via USPS ZIP prefix; insurance 0.5% unless quoted; reserves 2 × PITI to the nearest $100. Every assumption + source in `assumptions`.
- `SafeClient`: HTTPS + `ALLOWED_HOSTS` only (checked before send and in an httpx request hook), no redirects, timeouts, retries on transport/5xx; errors never include query strings or headers; httpx INFO logging (which prints URLs) muted; `Settings.__repr__` hides keys.
- `HOUSING_USE_MOCKS=true` serves `fixtures/mocks` through an httpx MockTransport behind the same allowlist.
- compose: `housing-mcp` on `internal` + `egress`, cache volume, read-only rootfs, healthcheck. Dockerfile. Make: `housing-mcp-run`, `-test`, `-test-live`, `-up`.

Verified:
- `make test`: 85 passed, 2 skipped (live), 1 xfailed (golden reserves/cash, see below). `make lint`: clean.
- Golden walkthrough: $42,000 down, $12,600 closing, P&I $2,332.33, PMI $157.50 match. Without an address, tax uses TX 1.40% → reserves **$6,000**, cash **$60,600** (golden says $6,300 / $60,900, which need the RentCast 1.8% record; with the fixture address all golden numbers match). Decision taken with the user: keep "address → RentCast, else state default"; regeneration requested.
- Ran the real server (`HOUSING_USE_MOCKS=true uv run homefund-housing-mcp`) and called it over streamable HTTP with `fastmcp.Client`.

Not verified: Docker build / `docker compose config` (no Docker on this machine); live FRED and RentCast tests (no keys; run `make housing-mcp-test-live`, which spends 2 RentCast requests). Live tests need `HOUSING_LIVE_TESTS=1` as well as keys, since `make` exports `.env`.

Open contract requests (docs/contract-requests/housing-mcp.md): `CostBreakdown.assumptions/warnings`; optional `credit_band/address/insurance_annual` on `EstimateHomeCostInput`; `source_url` on the rate output; fail-soft `GetPropertyOutput`; golden regeneration; respx in the root dev group.

Next: drop the superset models once contracts land; remove the xfail after golden is regenerated; credit-band spreads are a Home Fund estimate and could be replaced with a sourced table.
