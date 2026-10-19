# guides_mcp

guides-mcp is the FastMCP server for the home-buying RAG corpus: search_guides runs BGE-M3 dense plus sparse hybrid search over guide_chunks, filters by source and tax year, reranks the top 20 with bge-reranker-v2-m3 through the embed service and returns the top 5 with citations; define_term returns one glossary chunk; get_section returns a chunk's parent section. It reads pgvector through mcp_ro and has no egress.
