"""Home Fund ingest: fetch CFPB and HUD guides once, chunk them heading-aware into parent
sections and ~500-token children (one glossary term per chunk), embed through the embed
service and write guide_chunks idempotently."""
