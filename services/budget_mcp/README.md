# budget_mcp

budget-mcp is the FastMCP server for everything about the user's own money: six-month cash flow, per-category monthly summaries, fixed bills, the month-by-month savings projection and the cut solver. It reads Postgres only through the read-only mcp_ro role (monthly_summaries, goals), does every calculation in Decimal, takes a Clock for all date logic, and never calls out to the internet.

## Layout

- `domain.py`: all the logic, as pure functions over `SummaryRow`s. No MCP or database imports.
- `config.py`: `CutConfig`, the solver's cap shares and ease scores.
- `repository.py`: `PostgresRepository` (mcp_ro, every transaction `READ ONLY`). URL from `DATABASE_URL_RO`, falling back to `DATABASE_URL_MCP`.
- `server.py`: `create_server(repo, clock, config)` registers the five tools; `main()` serves streamable HTTP at `/mcp` (port 8101), plus `GET /healthz`.

Calls are scoped by the `X-HomeFund-User-Id` header. A call without it fails.

## Tools

| Tool | Returns |
|---|---|
| `get_cashflow(months=6)` | `Cashflow` over the last N full months before the clock, plus `saved_so_far` from the latest goal (see contract request) |
| `get_spending_by_category(months=6)` | one `MonthlySummary` per category per month (Transfer left out), e.g. `Dining and delivery · Apr 2026 · $587 · 23 purchases`, plus each category's average |
| `get_fixed_bills()` | 6-month averages for Rent, Insurance, Utilities and Debt minimum |
| `project_savings(start, monthly, target)` | `points[0]` is the clock's month at `start`, one point per month until balance >= target; `months_to_goal`, `reach_month`. The chart stops at 600 months; the answer stays exact |
| `solve_cuts(gap_per_month, protected)` | ranked `Cut`s, total, `meets_gap`, `shortfall_monthly` |

## Cut solver

1. Candidates: categories with spending in the last 6 months that are not protected and not Income/Transfer.
2. Cap: `cap_share` × average, rounded down to cents (default 50%, Travel fund 100%). Subscriptions are cut whole: count = transactions ÷ months, at most 60% of them (7 → 4), each worth the average price.
3. Choose the fewest categories whose caps cover the gap. Ties go to the lowest total ease score, then to the most combined room.
4. Rank easiest first. Every cut but the last is at its cap, and the last covers only what's left (rounded up to whole subscriptions). If no set covers the gap, every candidate is returned at its cap, with the shortfall.

Ease scores (lower is easier; 1–2 easy, 3 medium, 4+ hard): Travel fund 1, Subscriptions 1, Entertainment 2, Dining, Shopping and Rideshare 3, Other 4, Groceries 5, unlocked essentials 5.

On the golden fixtures, a $945 gap gives Travel fund $280, Dining $300, Shopping $180 and Groceries $185: four cuts, $945. The walkthrough's illustrative cuts ($952, no Groceries) use five categories. Setting `cap_shares[Groceries]` to 30% (cap under $185) makes the solver pick those five: Travel fund $280, Subscriptions $71.36 (7 down to 3), Dining $300, Shopping $180, Rideshare $113.64.

## Make targets

`budget-mcp-run`, `budget-mcp-test`, `budget-mcp-test-integration`, `budget-mcp-up`, `budget-mcp-logs`.
