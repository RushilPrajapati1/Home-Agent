# infra

Shared infrastructure owned by the foundation prompt. The root `docker-compose.yml` defines postgres (pgvector) and ollama plus the `internal` (no internet) and `egress` networks. Planned here: per-service egress allowlist proxies (housing-mcp to FRED and RentCast, ingest to CFPB and HUD, importer to Plaid), a vLLM profile for production inference, and TLS for Postgres. Request changes in `docs/contract-requests/infra.md`.
