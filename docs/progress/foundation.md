# foundation

## 2026-10-18 · Monorepo skeleton and contracts

Done:
- uv workspace (Python 3.12): `packages/contracts`, `packages/db`, eight empty services with pyproject, src package, tests/, README, compose.yaml (`services: {}`), Makefile.inc. Root compose `include:`s every service file; root Makefile `-include`s every Makefile.inc.
- `homefund_contracts`: Money/Percent as Decimal (strings on the wire, floats rejected), Category + PROTECTED + NON_SPENDING, Clock/SystemClock/FixedClock/clock_from_env, domain models, PlanState (design fields + on_track, pending_question, user_id), every MCP tool's input/output (names and params verified against the design in a test), API models, SSE event union, JSON Schema export to `web/src/api/schema/`.
- `homefund_db`: SQLAlchemy models, Alembic 0001 (transactions, goals, plans, guide_chunks, imports, monthly_summaries materialized view, HNSW index, app_rw/mcp_ro grants), Fernet column encryption for merchant/raw_description, keyed dedupe hash, `roles` (LOGIN + passwords), `seed`.
- Fixtures: deterministic generator; demo user Apr–Sep 2026 (CSV labeled + bank CSV + OFX), FRED/RentCast mocks, `golden_scenario.json` (PITI $3,137.33 → reserves $6,300; all walkthrough numbers asserted at generation time).
- Docs: CLAUDE.md, ARCHITECTURE.md (decisions + Models and security). CI: ruff, mypy (strict for contracts/db), pytest, alembic up/down/up + integration tests on a pgvector service container.

Verified:
- `uv run pytest -m "not integration"`: 31 passed. `ruff check`, `ruff format --check`, `mypy --strict packages/*/src`, `mypy services`: clean. Fixture and schema drift checks: clean.
- Migration, roles, seed and the 4 integration tests passed against embedded Postgres 16.2 (pgserver). That build ships pgvector 0.6.2, which has no `sparsevec`, so the column was swapped to `text` for that run only. The committed migration is unchanged.

Not verified here (no Docker or make on this machine): `make up`, `make migrate`/`seed` through make against the compose stack, `docker compose` include of `services: {}` files, `make models`, and `sparsevec` DDL on pgvector 0.8.7. CI's `migrations` job covers the last one.

Deviations from the design page (see ARCHITECTURE.md): `imports` table; plans gain user_id, nullable goal_id, on_track, plan_text, timestamps; transactions gain raw_description, created_at; no users table, so user_id has no FK.

Next: open contract requests from lanes; infra lane items (egress allowlist proxies, Postgres TLS, vLLM profile).
