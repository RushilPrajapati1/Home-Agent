# ingest

ingest is the scheduled job that builds the guides corpus: it fetches CFPB and HUD home-buying guides and the glossary from an allowlisted set of public hosts, splits prose heading-aware into roughly 500-token children with 50-token overlap under parent sections, keeps one glossary term per chunk, prepends 'document > section', embeds through the embed service, and writes guide_chunks (with source, section and tax_year in metadata) as app_rw.
