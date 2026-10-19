# Home Fund

Home Fund is an agentic RAG portfolio project for renters saving for a first home.
Given a specific home (price, ZIP, down payment, move-in date), it works out the cash needed:
down payment, closing costs and reserves.
It projects when the user gets there at their current savings pace, from six months of their own transactions.
It proposes the smallest ranked spending cuts that hit the date, and pauses for the user to approve them.
A LangGraph agent plans, three FastMCP servers (budget, housing, guides) do every calculation and fetch,
and RAG over CFPB and HUD guides cites each cost.
Only open-weight models run (gpt-oss-20b, Qwen3.5-9B, BGE-M3, bge-reranker-v2-m3), all inside a private network.
The stack is Python 3.12 (uv workspace), FastAPI, Postgres 17 + pgvector, Ollama in dev and vLLM in prod,
and React + Recharts.
Design: `docs/home-fund-design.pdf`. In text, with decisions: `docs/ARCHITECTURE.md`.

## Layout and ownership

Each directory is owned by exactly one prompt (lane). Edit only your lane's directories.

| Path | Owner lane |
|---|---|
| `packages/contracts/` (`homefund_contracts`) | foundation |
| `packages/db/` (`homefund_db`: models, Alembic, roles, seed) | foundation |
| root files, `infra/`, `.github/`, `fixtures/` (except `fixtures/<lane>/`), `docs/ARCHITECTURE.md` | foundation |
| `services/budget_mcp/` | budget-mcp |
| `services/housing_mcp/` | housing-mcp |
| `services/guides_mcp/` | guides-mcp |
| `services/embed/` | embed |
| `services/ingest/` | ingest |
| `services/importer/` | importer |
| `services/agent/` | agent |
| `services/api/` | api |
| `web/` (except `web/src/api/schema/`, which is generated) | web |
| `evals/` | evals |
| `docs/progress/<lane>.md`, `docs/contract-requests/<lane>.md`, `fixtures/<lane>/` | that lane |

Each service has its own `pyproject.toml`, `compose.yaml` (joined to the root by `include:`) and `Makefile.inc` (joined by `-include`).
Add dependencies, containers and make targets there, never in root files.
Prefix your make targets with your lane name, e.g. `budget-mcp-run`.
In your `compose.yaml`, redeclare any root network you join (`internal: {internal: true}` or `egress: {}`).
`uv.lock` is shared: after adding a dependency, run `uv lock`. On merge conflicts, rerun `uv lock` rather than hand-merging.

## Rules

1. Never edit `packages/contracts` or `packages/db` outside the foundation prompt. Log what you need in `docs/contract-requests/<lane>.md`.
2. All money math is `Decimal`, inside MCP tools or domain modules. LLMs never produce numbers: they choose, rank, phrase and explain, and every figure they show comes from a tool result.
3. Every date goes through a `Clock` (`homefund_contracts.clock`). Never call `date.today()` or `datetime.now()` directly. Tests use `FixedClock`, and the golden scenario uses 2026-10-01.
4. Unit tests never touch the network (no HTTP, no Postgres, no model server). Use the files in `fixtures/` and fakes. DB tests are marked `@pytest.mark.integration`.
5. Run `make test` (and `make lint`) before finishing.
6. At the end of every session, write a short entry in `docs/progress/<lane>.md`.

Useful: `make up`, `make migrate`, `make seed`, `make test`, `make test-integration`, `make lint`, `make schema`, `make models`.
Expected numbers for the walkthrough are in `fixtures/golden_scenario.json`.
