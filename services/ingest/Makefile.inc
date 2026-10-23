# ingest targets. Owned by the ingest lane; prefix every target with ingest-.
# `make ingest` is the job itself: fetch whatever is missing, then chunk, embed and write.
.PHONY: ingest ingest-fetch ingest-refresh ingest-chunk ingest-run

ingest: ingest-fetch ingest-run ## Fill guide_chunks (needs `make up`, `make migrate`, embed at EMBED_URL)

ingest-fetch: ## Download missing CFPB/HUD files into services/ingest/data/guides (network only if missing)
	$(UV) homefund-ingest fetch

ingest-refresh: ## Re-download every source file and update fetched/sha256 in sources.yaml
	$(UV) homefund-ingest fetch --refresh

ingest-chunk: ## Offline dry run: chunk every source and print counts (no embed, no database)
	$(UV) homefund-ingest chunk

ingest-run: ## Chunk, embed and write guide_chunks as app_rw; idempotent by content hash
	$(UV) homefund-ingest run
