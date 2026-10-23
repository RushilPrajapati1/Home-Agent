# guides-rag (embed, ingest, guides-mcp)

## 2026-10-21 · Embed service, guides ingest, guides-mcp

Done:
- **embed**: FastAPI `/embed` (BGE-M3 dense 1024 + sparse) and `/rerank` (bge-reranker-v2-m3) via FlagEmbedding. Batching, CUDA+fp16 or CPU fallback, `/healthz`. The base package is the wire schema + async `EmbedClient`; torch is the `model` extra.
- **ingest**: 21 official sources in `sources.yaml` (CFPB Buying a House steps, Loan Estimate and Closing Disclosure explainers, Ask CFPB on closing fees/PMI/MIP/escrow/DTI/LTV/total payment, FHA loans; HUD FHA loans, 2026 loan limits (tax_year 2026), ML 2023-05 MIP rates PDF; glossary from CFPB key terms (106 terms) + "Reserves" from HUD ML 2023-17). Raw files are committed in `services/ingest/data/guides/` (3.6 MB). HTML and HUD side-head PDF extractors; heading-aware parent/child chunker (500/50, parents ≤1500 tokens, list items and table rows never split, tables whole when they fit); `CONTEXT_HEADER`; idempotent writes keyed by a content+metadata hash.
- **guides-mcp**: FastMCP over streamable HTTP with `search_guides` (the recipe: dense+sparse top-50 → RRF → filters → top 20 → rerank → top k parent sections with Citations), `define_term` (exact → fuzzy → search fallback), `get_section`. Reads as mcp_ro on read-only transactions.
- `evals/retrieval/questions.jsonl`: 30 questions, each with `expected` {doc_id, section_path} and `also_relevant`; a test checks every section exists.
- Fixtures: `fixtures/guides-rag/pages/` (5 frozen pages for chunker tests), `fixtures/guides-rag/corpus.json` (20 chunks with real vectors and recorded query embeddings and reranker scores).

Verified (macOS, Apple M2, CPU; Postgres 17.x + pgvector 0.8.7 from Homebrew on port 5433, since Docker isn't installed here):
- `make ingest`: 304 rows (35 parents, 162 children, 107 glossary), all searchable rows with dense + sparse, no orphans; a full embed takes ~2 min on CPU. A re-run gives 0 inserted / 304 unchanged / 0 deleted.
- `make test`: 126 passed, 1 skipped (slow). `make embed-test-slow`: 1 passed (real models). `make test-integration`: 8 passed. `make lint`: clean.
- guides-mcp called over HTTP with a fastmcp client: all three tools work.
- 30 eval questions on the live index: the expected section is the top hit for 23/30, in the top 5 for 26/30, and in the 20-candidate rerank pool for 29/30. Most misses are a sibling section of the same parent page, which is returned anyway.

Decisions:
- The `define_term` and search behaviour for "What is <term>?": the reranker alone puts the longer Ask CFPB PMI page (logit 7.2) above the PMI glossary entry (6.5). When the whole question normalizes to a glossary term or alias, that entry now leads. This is the only addition to the design's recipe.
- The MCP tool can't take filters (fixed signature), so it applies the clock's tax year. See the contract request.
- Tokens are counted as words + punctuation, not with the XLM-R tokenizer, so chunking stays offline and deterministic.
- Skipped the CFPB "Your home loan toolkit" PDF: it's a 2015 multi-column InDesign workbook that extracts badly, and the HTML pages cover the same ground.

Not verified: Dockerfiles and compose files (no Docker here); GPU/fp16 path; the egress allowlist proxy (infra lane).

Next: Prompt 4B retrieval eval (recall@20, nDCG@5) on `questions.jsonl`; a CONTEXT_HEADER on/off comparison; contract requests in `docs/contract-requests/guides-rag.md`.
