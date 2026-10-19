# budget_mcp

budget-mcp is the FastMCP server for everything about the user's own money: six-month cash flow, per-category monthly summaries, fixed bills, the month-by-month savings projection and the cut solver. It reads Postgres only through the read-only mcp_ro role (transactions, monthly_summaries, goals), does every calculation in Decimal, takes a Clock for all date logic, and never calls out to the internet.
