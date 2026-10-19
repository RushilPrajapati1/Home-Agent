# Home Fund architecture

This is the design in `docs/home-fund-design.pdf` written out in text, plus the decisions taken while setting up the foundation. The contracts in `packages/contracts` and the schema in `packages/db` are authoritative where this text and code disagree.

## What it does

A renter enters a target home: price or address, ZIP, down payment (3, 3.5, 10 or 20%), move-in date and savings already set aside. Their transactions come from Plaid or from uploaded CSV, OFX and PDF statements. Home Fund answers three questions:

1. How much cash does this home take? Down payment, closing costs and reserves, plus the monthly payment (PITI, plus PMI below 20% down).
2. When do I get there at my current pace? A month-by-month savings chart against the move-in date.
3. What would I cut to get there on time? The smallest ranked set of cuts, which the user approves, edits or rejects.

## Components

All components run inside one private network except the browser and the outside APIs.

| Component | Tech | Role |
|---|---|---|
| Web app | React + Recharts | Goal form, savings chart, cut approval |
| api | FastAPI | Auth, imports, plans, SSE stream |
| agent | LangChain + LangGraph | Plans, projects, cuts, checks; Postgres checkpointer |
| Model server | vLLM (Ollama in dev) | gpt-oss-20b, Qwen3.5-9B |
| embed | dedicated service | BGE-M3 dense + sparse, bge-reranker-v2-m3 |
| budget-mcp | FastMCP | Cash flow, projections, cut solver. Read-only SQL |
| housing-mcp | FastMCP | Home cost, mortgage rate, property tax. FRED and RentCast |
| guides-mcp | FastMCP | Hybrid search over guides and glossary, with citations |
| importer | parser + small LLM | Parse, dedupe, categorize statements; optional Plaid sync |
| ingest | scheduled job | Fetch, chunk and embed CFPB and HUD guides |
| Postgres + pgvector | Postgres 17 | App data (transactions, goals, plans, imports) and guide vectors |

Request path: browser → api → agent → MCP servers and model server, with events streaming back agent → api → browser. Data comes in through importer (transactions) and ingest (chunks and vectors).

## Data and chunking: numbers go in tables, words go in vectors

- **Transactions** are never chunked. There is one row per transaction. The small model fills in only the category, and SQL does all the math.
- **Monthly summaries** come from the `monthly_summaries` materialized view: one record per user, month and category. budget-mcp turns each into a short line ("Dining and delivery · Mar 2026 · $612 · 23 purchases") so the planner can explain patterns without reading 2,000 rows.
- **Statement PDFs** get table-aware parsing (pdfplumber or Docling), row by row, never splitting a row. The account summary block stays whole.
- **CFPB and HUD guides** get a heading-aware, parent-child split: roughly 500-token children with 50 tokens of overlap. "document › section" is prepended before embedding, and the model is handed the parent section.
- **Glossary**: one term per chunk.
- **Retrieval**: question → BGE-M3 dense + sparse search → filter by source and tax year → top 20 → bge-reranker-v2-m3 → top 5, with their parent sections passed into the prompt.

Public data: FRED `MORTGAGE30US` (weekly 30-year fixed, cached weekly); RentCast value estimate and property records (property tax). Insurance and PMI are estimated as percentages unless the user enters a quote.

## Agent graph

The nodes, in order:

- `parse_goal` (LLM). Then `goal complete?`: if no, go to `ask_user` (pause) and back to `parse_goal`.
- `estimate_home_cost` (housing-mcp), then `analyze_spending` (budget-mcp), then `project_savings` (budget-mcp). Then `on track?`.
  - **No**: `solve_cuts` (LLM + budget-mcp), then `review_cuts` (pause). Approved cuts go back to `project_savings`.
  - **Yes**: `explain_costs` (guides-mcp), then `write_plan` (LLM). Then `plan checks pass?`: if no, retry `write_plan` once. If yes, END.

State is `homefund_contracts.state.PlanState`. It has the design's fields (goal, home_cost, cashflow, projection, cuts, notes, plan, review_rounds) plus `on_track`, `pending_question` and `user_id`.

Guards:

- **Math lives in tools.** Every dollar figure comes from budget-mcp or housing-mcp. The checks recompute each figure before the plan is shown.
- **Essentials are protected.** Rent, Insurance, Utilities and Debt minimum (`PROTECTED`) can't be cut unless the user unlocks them in a review (`ReviewRequest.unlock`).
- **The user approves first.** `interrupt()` pauses at `review_cuts` and `ask_user`, and the Postgres checkpointer resumes the graph. LangGraph adds its own checkpointer tables (app_rw has CREATE on `public` for this).
- **Loops are bounded.** At most 3 review rounds and 1 plan retry, with a recursion limit as a backstop.

## APIs, MCP servers and data model

The MCP tools are listed below, with names and parameters exactly as in the design. Their models are in `homefund_contracts.mcp`.

- budget-mcp: `get_cashflow(months=6)`, `get_spending_by_category(months=6)`, `get_fixed_bills()`, `project_savings(start, monthly, target)`, `solve_cuts(gap_per_month, protected)`
- housing-mcp: `estimate_home_cost(price, zip, down_pct)`, `get_mortgage_rate()`, `get_property(address)`
- guides-mcp: `search_guides(query, k=5)`, `define_term(term)`, `get_section(chunk_id)`

MCP calls are scoped to a user with the `X-HomeFund-User-Id` header on the MCP transport (`homefund_contracts.mcp.USER_HEADER`), not with a tool parameter, so the signatures stay exactly as designed. budget-mcp reads only the transactions the user has already synced or uploaded. Plaid's own MCP servers cover developer diagnostics, not user transactions.

App API: models are in `homefund_contracts.api`, and SSE events are in `homefund_contracts.events`.

| Method | Path | Body → Response |
|---|---|---|
| POST | `/api/imports` | multipart files (+ `CreateImportForm`) → `CreateImportResponse` |
| GET | `/api/imports/{id}` | → `ImportResponse` |
| POST | `/api/plans` | `CreatePlanRequest` → `CreatePlanResponse` (plan_id only) |
| GET | `/api/plans/{id}/events` | SSE stream of `PlanEvent` |
| POST | `/api/plans/{id}/review` | `ReviewRequest` → `ReviewResponse` |
| POST | `/api/plans/{id}/answer` | `AnswerRequest` → `AnswerResponse` (answers `ask_user`) |
| GET | `/api/plans/{id}` | → `PlanResponse` |

SSE event types: `node_started`, `node_finished`, `cost_ready`, `projection_ready`, `cuts_proposed` (graph paused), `question` (graph paused at ask_user), `plan_ready`, `error`.

### Tables (migration 0001)

- `transactions`: id, user_id, account, posted_on, amount numeric(12,2) (signed: income +, spending −), merchant and raw_description (encrypted), category (CHECK = `Category`), category_source (rule | llm | user), is_fixed, source (plaid | csv | ofx | pdf), dedupe_hash (unique, keyed HMAC), created_at.
- `goals`: id, user_id, price, zip, down_pct (percentage points), move_in, saved.
- `plans`: id, goal_id, user_id, status (running | awaiting_input | awaiting_review | done | failed), cash_needed, monthly_target, on_track, projection, cuts, citations (jsonb), plan_text, created_at, updated_at.
- `guide_chunks`: id, parent_id (self-reference: parent sections are rows), content, dense vector(1024) with an HNSW index (cosine), sparse sparsevec(250002), metadata jsonb (source, document, section, url, tax_year) with a GIN index.
- `imports`: status of each `POST /api/imports` job.
- `monthly_summaries`: materialized view (user_id, month, category, total, count), with a unique index for `REFRESH … CONCURRENTLY`. Owned by app_rw so the importer can refresh it.

Roles: `app_rw` (read/write app tables, owns the view, CREATE on public) and `mcp_ro` (SELECT only on transactions, monthly_summaries, goals, guide_chunks). Migrations run as the admin user. `homefund_db.roles` gives both roles LOGIN and their passwords from the environment.

Deviations from the design page, and why:

- `plans.user_id`, nullable `plans.goal_id`, `on_track`, `plan_text` and timestamps. A plan starts before `parse_goal` has a goal, and `GET /api/plans/{id}` must return the saved plan text.
- The `imports` table. `GET /api/imports/{id}` needs status that both importer and api can see.
- `transactions.raw_description` and `created_at`.
- There is no users table, so `user_id` is a plain indexed UUID. Auth lives in api.

## Decisions

- **SSE comes from a GET endpoint.** `POST /api/plans` starts the run and returns only `plan_id`. The browser then opens `EventSource('/api/plans/{id}/events')`, because EventSource can only GET. Each event carries a per-plan `seq`, sent as the SSE `id:`, so a reconnect resumes from `Last-Event-ID`. A paused graph (`cuts_proposed`, `question`) resumes via `POST …/review` or `POST …/answer`, and events continue on the same stream.
- **Postgres is encrypted at the volume and connection level.** Production runs on an encrypted volume and requires TLS (`sslmode=verify-full`). The dev compose stack uses plain connections, but only over the private network and 127.0.0.1. Only `merchant` and `raw_description` are column-encrypted (Fernet, app-side, `homefund_db.crypto.EncryptedText`). Amounts, dates and categories stay in plaintext columns so SQL can sum them and budget-mcp never needs the key. The dedupe hash is a keyed HMAC, so it doesn't leak the description either.
- **Egress is allowlisted per service.** housing-mcp (api.stlouisfed.org, api.rentcast.io), ingest (consumerfinance.gov, hud.gov) and importer (Plaid, only when `PLAID_ENABLED=true`) each get their own allowlisted egress. Every other service, and every model, is only on the `internal` network (`internal: true`, no route out). Allowlists are enforced by a per-service egress proxy on the `egress` network (infra lane).
- **Embeddings and reranking run in a dedicated embed service.** Ollama/vLLM serve only the chat models. The embed service serves BGE-M3 dense + sparse and bge-reranker-v2-m3 at `EMBED_URL`, used by guides-mcp at query time and by ingest at index time.
- **Bounded review.** After 3 review rounds, or a full rejection, the graph stops proposing cuts and continues to `explain_costs` and `write_plan` with `on_track = false`. The plan then says plainly that the date isn't reachable with accepted cuts, and when the current pace gets there.
- **Shared conventions** (pinned in `fixtures/golden_scenario.json`):
  - Projection `points[0]` is the clock's current month at `start`, and each later point adds `monthly`.
  - Reserves are 2 × PITI, rounded to the nearest $100. PMI is reported separately and isn't in PITI or reserves.
  - The cash-flow window is the last N full months before the clock.
  - Spending excludes Income and Transfer (`NON_SPENDING`).

## Models and security

(The PDF's Models & security page is missing. This section stands in for it.)

| Where | Model | Why |
|---|---|---|
| `parse_goal` | Qwen3.5-9B (`qwen3.5:9b`), structured output into `HomeGoal` | Small, fast, reliable JSON |
| importer categorization | Qwen3.5-9B, after deterministic rules | Only fills in the category; output limited to `Category` |
| `solve_cuts` | gpt-oss-20b ranks and explains the candidate cuts that budget-mcp computes | Judgment on ease; amounts come from the solver |
| `write_plan` | gpt-oss-20b, from tool numbers only; the checks recompute every figure | Best prose of the open models |
| guides-mcp / ingest | BGE-M3 (dense 1024 + sparse) and bge-reranker-v2-m3 in the embed service | Hybrid retrieval + rerank |
| `estimate_home_cost`, `analyze_spending`, `project_savings`, `explain_costs` | no LLM | Tool calls only |

All of these models are open-weight and served from hardware we control (Ollama in dev, vLLM in prod). No hosted LLM API is ever called.

**What never leaves the private network:**

- Transactions, merchants, descriptions, amounts, account labels.
- Goals and saved amounts.
- Plans, cuts and projections.
- Prompts and completions, embeddings and LangGraph checkpoints.

Models have no network route out at all.

**What does leave, and only through the allowlisted egress:**

- housing-mcp sends the FRED series id, and the target home's address or ZIP to RentCast. That address is the only user-derived data that leaves.
- ingest sends plain GETs for public CFPB and HUD documents.
- importer sends Plaid API calls with the user's Plaid access token, only when enabled.

Other controls:

- **Least privilege.** MCP servers use `mcp_ro`, so they can read but never write. housing-mcp has no database credentials.
- **Model weights.** Pulled once (`make models`). In production they're mounted read-only, and the model server has no egress.
- **Secrets.** Kept in `.env` (never committed). `.env.example` holds only dev placeholders.
