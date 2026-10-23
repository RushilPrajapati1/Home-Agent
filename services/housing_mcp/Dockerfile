# housing-mcp image. Build context is the repo root (uv workspace + shared lockfile).
FROM ghcr.io/astral-sh/uv:0.11.28-python3.12-bookworm-slim

ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_NO_DEV=1 \
    FASTMCP_CHECK_FOR_UPDATES=off FASTMCP_SHOW_SERVER_BANNER=false
WORKDIR /app

# Workspace metadata first so dependency layers cache across source edits.
COPY pyproject.toml uv.lock ./
COPY packages ./packages
COPY services ./services
RUN uv sync --frozen --no-dev --package homefund-housing-mcp

COPY fixtures/mocks ./fixtures/mocks

RUN useradd --system --uid 10102 housing && mkdir -p /var/cache/housing-mcp \
    && chown housing /var/cache/housing-mcp
USER housing

EXPOSE 8102
CMD ["/app/.venv/bin/homefund-housing-mcp"]
