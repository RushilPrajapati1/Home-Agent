# guides-rag contract requests

## 2026-10-21 · Optional filters on search_guides
Need: `SearchGuidesInput` gains `sources: list[GuideSource] | None = None` and `tax_year: int | None = None` (optional, so the design's `search_guides(query, k=5)` calls still validate).
Why: the retrieval recipe filters by source and tax year. The agent (`explain_costs`) can't ask for e.g. HUD-only or a specific tax year today.
Workaround: the filters exist in `GuidesService.retrieve(..., filters=Filters(...))`. The MCP tool applies the clock's current year as the tax-year filter (undated chunks always pass) and no source filter.

## 2026-10-21 · guide_chunks.metadata keys
Need: update the column comment (migration 0001) and ARCHITECTURE.md to the keys ingest writes: `source` (cfpb|hud|glossary), `kind` (guide|glossary), `doc_title`, `section_path` (list of headings), `url`, `tax_year`, plus `doc_id`, `role` (parent|child|glossary), `publisher`, `content_hash`, `term`/`aliases` (glossary), `chunk_index`/`tokens`/`overlap_tokens`/`context_header` (children). The comment currently says `document, section`.
Why: the prompt for this lane specified `doc_title` and `section_path`. Readers (evals) should filter on the real keys.
Workaround: none needed; `Citation.document`/`section` are built from `doc_title`/`section_path`.

## 2026-10-21 · Optional: expression index on metadata->>'doc_id'
Need: `CREATE INDEX ix_guide_chunks_doc_id ON guide_chunks ((metadata->>'doc_id'))`.
Why: ingest selects and prunes rows per document. It's fine at today's ~300 rows, but it's a sequential scan.
Workaround: none needed yet.

## 2026-10-21 · .env.example entries
Need: add `CONTEXT_HEADER=on`, `EMBED_DEVICE=auto` and `GUIDES_MCP_PORT=8103` (all documented in the service READMEs; defaults already match).
Why: discoverability; root files are foundation-owned.
