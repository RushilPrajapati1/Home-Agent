# guides_mcp targets. Owned by the guides_mcp lane; prefix every target with guides-mcp-.
.PHONY: guides-mcp-run guides-mcp-fixtures

guides-mcp-run: ## Serve guides-mcp on the host at GUIDES_MCP_URL (streamable HTTP, mcp_ro)
	$(UV) homefund-guides-mcp

guides-mcp-fixtures: ## Rebuild fixtures/guides-rag/corpus.json from guide_chunks + the embed service
	$(UV) python services/guides_mcp/scripts/build_fixture_corpus.py
