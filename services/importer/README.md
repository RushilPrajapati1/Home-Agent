# importer

importer turns statements into transaction rows: it parses CSV, OFX and PDF (table-aware, never splitting a row) and optionally syncs Plaid /transactions/sync, dedupes on dedupe_hash, categorizes with rules first and the small LLM second (category_source rule | llm | user), encrypts merchant and raw description, writes as app_rw, updates the imports row, and refreshes the monthly_summaries materialized view. Its only egress is Plaid, and only when PLAID_ENABLED is true.
