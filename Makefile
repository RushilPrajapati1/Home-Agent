# Home Fund. Needs GNU make, Docker (Compose v2.20+ for `include:`), uv and pnpm.
# Each service adds its own targets in services/<name>/Makefile.inc; never edit them here.

SHELL := bash
.DEFAULT_GOAL := help

# Create .env from the template on a clean clone, then export it to every recipe.
.env:
	cp .env.example .env
-include .env
export

COMPOSE := docker compose
UV := uv run
LLM_MODELS := gpt-oss:20b qwen3.5:9b

.PHONY: help up down migrate seed test test-integration lint fmt schema fixtures models

help: ## List targets
	@grep -hE '^[a-zA-Z0-9_-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-20s %s\n", $$1, $$2}'

up: ## Start postgres and ollama and wait until healthy
	$(COMPOSE) up -d --wait postgres ollama

down: ## Stop the stack (data volumes are kept)
	$(COMPOSE) down

migrate: ## Apply Alembic migrations, then enable role logins
	uv sync --quiet
	$(UV) alembic -c packages/db/alembic.ini upgrade head
	$(UV) python -m homefund_db.roles

seed: ## Load the fixture user and refresh monthly_summaries
	$(UV) python -m homefund_db.seed --fixtures fixtures

test: ## Unit tests: no network, no database
	$(UV) pytest -m "not integration"

test-integration: ## Migration, role and seed tests against the local Postgres
	$(UV) pytest -m integration

lint: ## ruff, format check, mypy (strict for contracts and db)
	$(UV) ruff check .
	$(UV) ruff format --check .
	$(UV) mypy --strict packages/contracts/src packages/db/src
	$(UV) mypy services fixtures/generate.py

fmt: ## Auto-fix lint and format
	$(UV) ruff check --fix .
	$(UV) ruff format .

schema: ## Export JSON Schema for API and SSE models to web/src/api/schema/
	$(UV) homefund-export-schema --out web/src/api/schema

fixtures: ## Regenerate fixtures and the golden scenario
	$(UV) python fixtures/generate.py

models: ## Pull the LLMs into the ollama container
	@for m in $(LLM_MODELS); do $(COMPOSE) exec ollama ollama pull $$m || exit 1; done

-include services/*/Makefile.inc
