# budget-mcp

## 2026-10-21 · budget-mcp server, solver and tests

Done:
- `homefund_budget_mcp`: `domain` (pure Decimal logic, no MCP or DB imports), `config.CutConfig`, `repository.PostgresRepository` (mcp_ro, READ ONLY transactions, `DATABASE_URL_RO` with a `DATABASE_URL_MCP` fallback), `server.create_server` with exactly the five design tools over streamable HTTP at `/mcp`, `/healthz`. The user comes from the `X-HomeFund-User-Id` header.
- Solver: picks the fewest categories whose caps cover the gap, breaking ties by ease score, and ranks the cuts easiest first. The last cut is trimmed to the remainder. Subscriptions are cut in whole-subscription steps, up to 60% of them. If nothing covers the gap, every candidate comes back at its cap with the shortfall.
- Tests: unit tests for every domain function (FixedClock); Hypothesis properties (protected categories untouched, caps respected, gap covered whenever possible, fewest cuts, ranking); a golden test on the fixtures ($1,200/mo, 36 months to 2029-10, $2,145/mo for 2028-06, cuts ≥ $945 with protected categories untouched, by_category exactly as in the golden file); an in-process MCP client test that calls all five tools over streamable HTTP via httpx's ASGI transport; and integration tests for the repository.
- `Dockerfile`, `compose.yaml` (internal network only, no published ports, read-only rootfs, healthcheck), `Makefile.inc` (`budget-mcp-*`).

Verified:
- `uv run pytest -m "not integration"`: 63 passed (32 of them budget-mcp). `ruff check .`, `ruff format --check .`, `mypy --strict packages/*/src`, `mypy services fixtures/generate.py`: clean.
- Integration: 3 passed as mcp_ro against a scratch Postgres 14 holding only transactions, goals and the monthly_summaries view, built from the homefund_db models, seeded with `homefund_db.seed`. Not run against the real migration (no Docker or pgvector here).
- Ran `python -m homefund_budget_mcp` against that DB and called tools over real HTTP with a FastMCP client.

Not verified: `docker compose build`/`up` for budget-mcp (no Docker here). The base image tag `ghcr.io/astral-sh/uv:0.11.28-python3.12-bookworm-slim` hasn't been pulled.

Notes for other lanes:
- get_cashflow returns `saved_so_far` as an extra key until the contract has it. Strict `Cashflow.model_validate` rejects it (see contract requests).
- On the golden data, a $945 gap gives Travel $280, Dining $300, Shopping $180, Groceries $185 (four cuts). The walkthrough's five-cut set needs a lower Groceries cap (see README).

Open contract requests: saved_so_far on GetCashflowOutput; DATABASE_URL_RO naming; hypothesis in the root dev group; `.hypothesis/` in .gitignore.

Next: get the contract requests resolved, then drop the local subclass. Build and run the compose service once Docker is available.
