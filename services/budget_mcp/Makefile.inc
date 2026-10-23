# budget_mcp targets. Owned by the budget_mcp lane; prefix every target with budget-mcp-.

.PHONY: budget-mcp-run budget-mcp-test budget-mcp-test-integration budget-mcp-up budget-mcp-logs

budget-mcp-run: ## Run budget-mcp on the host (127.0.0.1:8101/mcp) against `make up`
	$(UV) python -m homefund_budget_mcp

budget-mcp-test: ## budget-mcp unit, property, golden and MCP client tests
	$(UV) pytest services/budget_mcp -m "not integration"

budget-mcp-test-integration: ## budget-mcp repository tests against the seeded Postgres
	$(UV) pytest services/budget_mcp -m integration

budget-mcp-up: ## Build and start budget-mcp in compose (internal network only)
	$(COMPOSE) up -d --build --wait budget-mcp

budget-mcp-logs: ## Follow budget-mcp logs
	$(COMPOSE) logs -f budget-mcp
