# housing_mcp targets. Owned by the housing_mcp lane; prefix every target with housing-mcp-.
.PHONY: housing-mcp-run housing-mcp-test housing-mcp-test-live housing-mcp-up

housing-mcp-run: ## Run housing-mcp on the host (streamable HTTP on :8102/mcp)
	$(UV) homefund-housing-mcp

housing-mcp-test: ## housing-mcp unit tests (no network)
	$(UV) pytest services/housing_mcp -m "not integration"

housing-mcp-test-live: ## Live FRED + RentCast tests (needs keys; spends 2 RentCast requests)
	HOUSING_LIVE_TESTS=1 $(UV) pytest services/housing_mcp/tests/test_live.py -rs

housing-mcp-up: ## Build and start housing-mcp in compose
	$(COMPOSE) up -d --build --wait housing-mcp
