# embed

embed is the dedicated embedding and reranking service inside the private network. It serves BGE-M3 dense (1024-d) and sparse vectors and bge-reranker-v2-m3 scores over HTTP at EMBED_URL, for guides-mcp at query time and for ingest at index time. It has no database access and no egress once its weights are present.
