# housing_mcp

housing-mcp is the FastMCP server that prices a specific home: down payment, closing costs, reserves, PITI and PMI (estimate_home_cost), the 30-year rate from FRED MORTGAGE30US cached weekly (get_mortgage_rate), and value and property tax from RentCast (get_property). It has no database access and is one of three services with allowlisted egress, limited to the FRED and RentCast APIs.

- Run: `make housing-mcp-run` (host) or `make housing-mcp-up` (compose). Endpoint `http://localhost:8102/mcp`, health `/healthz`.
- Env: `FRED_API_KEY`, `RENTCAST_API_KEY`, `HOUSING_USE_MOCKS` (serve `fixtures/mocks`), `RENTCAST_MONTHLY_LIMIT` (default 50), `HOUSING_CACHE_DIR`, `CLOCK_FIXED_DATE`.
- Tests: `make housing-mcp-test` (no network). Live: `make housing-mcp-test-live` (needs keys; spends 2 RentCast requests).

Layout: `costs.py` (Decimal math), `config.py` (every assumption and its source), `http.py` (allowlist, retries, redaction), `fred.py`, `rentcast.py`, `cache.py`, `server.py`.

Property tax comes from RentCast when `address` is given, otherwise from the state's average effective rate (Tax Foundation) by ZIP prefix. Outputs add `assumptions` and `warnings` to the contract models while those fields are pending in `docs/contract-requests/housing-mcp.md`.
