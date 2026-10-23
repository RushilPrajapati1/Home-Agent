# ingest

The job that builds the guides corpus in `guide_chunks`. Run it with `make ingest`. It needs `make up` and `make migrate`, and the embed service at `EMBED_URL` (`make embed-run`).

1. **Fetch** (`make ingest-fetch`) downloads each document in `sources.yaml` that is missing from `data/guides/`, and records `fetched` and `sha256`. The raw files are committed, so re-chunking never needs the network. Hosts are allowlisted (consumerfinance.gov, hud.gov), and redirects off the list are refused. `make ingest-refresh` re-downloads everything.
2. **Extract** HTML (CFPB, hud.gov) and HUD Mortgagee Letter PDFs into typed blocks: headings, paragraphs, list items and tables. CFPB "expandable" panels and hud.gov bold subheads become headings, and site chrome is dropped. In PDFs, left-column side-heads become sections and ruled tables are kept with filled-down row labels.
3. **Chunk** (`homefund_ingest.chunker`; `make ingest-chunk` is an offline dry run):
   - Parents follow the headings: each is the largest section of at most 1,500 tokens.
   - Children are about 500 tokens with a 50-token overlap and never cross a heading.
   - List items and table rows are never split. A table that fits in one child stays whole; a longer one is cut between rows with its header repeated.
   - The glossary is one term per chunk: the CFPB key-terms page, plus spans cut from other documents (`terms:`).
4. **Embed** `'document > section'` + the chunk text (when `CONTEXT_HEADER=on`, the default) as dense + sparse vectors, and **write** as app_rw. Row ids are uuid5 of a hash of the content, metadata, embedding text and model. A re-run inserts nothing, a changed document replaces only its own rows, and documents dropped from `sources.yaml` are pruned.

Metadata on every row: `source` (cfpb | hud | glossary), `kind` (guide | glossary), `doc_title`, `section_path`, `url`, `tax_year`, plus `doc_id`, `role` (parent | child | glossary), `publisher`, `content_hash`, and `term`/`aliases` for glossary entries.

Settings: `CONTEXT_HEADER` (on), `CHUNK_TOKENS` (500), `CHUNK_OVERLAP` (50), `PARENT_MAX_TOKENS` (1500).
