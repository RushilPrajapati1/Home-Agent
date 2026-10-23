# Build from the repo root (compose sets context: ../..). Installs only this service and
# its workspace dependencies from the shared uv.lock.
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.11.28 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY packages packages
COPY services services
RUN uv sync --frozen --no-dev --package homefund-guides-mcp 
ENV PATH=/app/.venv/bin:$PATH
USER nobody
CMD ["homefund-guides-mcp"]
