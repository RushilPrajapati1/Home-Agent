# guides_mcp

FastMCP server (streamable HTTP at `GUIDES_MCP_URL`, path `/mcp`) over the guides corpus. It reads pgvector as `mcp_ro` on a read-only transaction, and embeds and reranks through the embed service. It has no egress.

- `search_guides(query, k=5)`:
  1. Embed the query dense + sparse.
  2. Take the dense (HNSW, cosine) and sparse (inner product) top 50 from pgvector.
  3. Fuse them with reciprocal rank fusion (k=60).
  4. Apply the source and tax-year filters.
  5. Keep the top 20 and rerank them with bge-reranker-v2-m3.
  6. Return the top k as **parent sections**, with one hit per parent. Each hit has a `Citation` whose `quote` is the matched child.
  - The server applies the clock's year as the tax-year filter. Undated guides always pass it.
  - One addition to the recipe: when the whole question is "what is <glossary term>" (exact term or alias), that glossary entry leads.
- `define_term(term)`: glossary lookup (exact on term and aliases, then fuzzy for terms of four or more characters), falling back to `search_guides`. Below a reranker score of 0.3 it reports `found: false`.
- `get_section(chunk_id)`: the chunk's parent section (a glossary entry is its own section).

`make guides-mcp-run` serves it on the host. `make guides-mcp-fixtures` rebuilds `fixtures/guides-rag/corpus.json`: 20 chunks with their real vectors, plus recorded query embeddings and reranker scores. The unit tests replay that file, so they need no model server.
