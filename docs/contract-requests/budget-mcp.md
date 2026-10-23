# budget-mcp contract requests

## 2026-10-21 · saved_so_far on get_cashflow's output
Need: `saved_so_far: Money | None` on `GetCashflowOutput` (today an alias of `Cashflow`, which is `extra="forbid"`). Either add it to `Cashflow` or make `GetCashflowOutput` its own model `Cashflow + saved_so_far`.
Why: the budget-mcp brief has get_cashflow return the saved amount from `goals` alongside the averages, so analyze_spending gets income, spend and savings in one call.
Workaround: budget-mcp returns `homefund_budget_mcp.server.CashflowWithSavings` (a `Cashflow` subclass with the field). **Until this lands, a consumer that validates get_cashflow's result with the strict `Cashflow` model fails on the extra key**; drop `saved_so_far` first, or validate with the subclass.

## 2026-10-21 · DATABASE_URL_RO in .env.example
Need: a `DATABASE_URL_RO` entry (the mcp_ro URL), or confirmation that `DATABASE_URL_MCP` is the name to use.
Why: the budget-mcp brief names `DATABASE_URL_RO`; `.env.example` and `homefund_db.config` only define `DATABASE_URL_MCP`.
Workaround: budget-mcp reads `DATABASE_URL_RO` and falls back to `DATABASE_URL_MCP` (same role). Its compose service sets `DATABASE_URL_RO`.

## 2026-10-21 · hypothesis in the root dev group
Need: `hypothesis>=6.100` in the root `[dependency-groups] dev`.
Why: budget-mcp's property tests. Root `uv sync` drops packages that only a member's optional extra or group asks for.
Workaround: hypothesis is a regular dependency of homefund-budget-mcp for now, so it also lands in the image. Move it once the root dev group has it.

## 2026-10-21 · ignore .hypothesis/
Need: `.hypothesis/` in the root `.gitignore`.
Why: Hypothesis writes a constants cache to `.hypothesis/` at the repo root on every property-test run.
Workaround: the property tests set `database=None`, but the cache is still written. Don't commit it.
