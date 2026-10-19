# Home Fund

An agent that works out how much cash a specific home takes, projects when you'll get there at your current pace, and shows which spending cuts close the gap. Every model runs on hardware you control. Design: [`docs/home-fund-design.pdf`](docs/home-fund-design.pdf) · Architecture: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) · Working rules: [`CLAUDE.md`](CLAUDE.md).

## Quick start

Needs Docker (Compose v2.20+), GNU make, [uv](https://docs.astral.sh/uv/), Node 20 + pnpm (web only). On Windows, run make from Git Bash or WSL.

```bash
make up        # postgres (pgvector) + ollama
make migrate   # alembic upgrade head + role logins
make seed      # demo user: 6 months of transactions, goal, monthly_summaries
make test      # unit tests (no network)
make models    # pull gpt-oss:20b and qwen3.5:9b into ollama (large download)
```

`make help` lists everything; `make test-integration` runs migration, role and seed tests against the local Postgres.
