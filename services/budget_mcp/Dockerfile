# budget-mcp. Build context is the repo root (see compose.yaml). Copies only what the
# workspace needs to resolve, never .env or .venv.
FROM ghcr.io/astral-sh/uv:0.11.28-python3.12-bookworm-slim

ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_NO_DEV=1
WORKDIR /app

COPY pyproject.toml uv.lock ./
COPY packages ./packages
COPY services ./services
RUN uv sync --locked --no-dev --package homefund-budget-mcp

RUN useradd --system --uid 10001 app
USER app

ENV BUDGET_MCP_HOST=0.0.0.0 BUDGET_MCP_PORT=8101
EXPOSE 8101
CMD ["/app/.venv/bin/python", "-m", "homefund_budget_mcp"]
