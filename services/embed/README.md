# embed

The dedicated embedding and reranking service on the internal network. Ollama and vLLM serve dense vectors only and have no reranker, so BGE-M3 (dense 1024-d + sparse lexical weights) and bge-reranker-v2-m3 live here, loaded with FlagEmbedding. It has no database access and no egress once its weights are present.

| Method | Path | Body → Response |
|---|---|---|
| POST | `/embed` | `{texts: [...≤256], sparse: bool}` → `{model, dim: 1024, dense: [[...]], sparse: [{indices, values}] \| null}` |
| POST | `/rerank` | `{query, passages: [...≤256]}` → `{model, scores: [...]}` (sigmoid-normalised) |
| GET | `/healthz` | → `{status, device, fp16, embed_model, rerank_model}` |

- Device: `EMBED_DEVICE=auto` picks CUDA with fp16, else CPU without it (`mps` is opt-in). `EMBED_FP16`, `EMBED_BATCH_SIZE` (32) and `EMBED_MAX_LENGTH` (1024) override the defaults.
- The base package is the wire schema plus `EmbedClient` (async, batches big inputs), which is what ingest and guides-mcp import. torch and FlagEmbedding are the `model` extra, so a plain `uv sync` leaves them out.
- `make embed-run` serves on the host at `EMBED_URL`. `make embed-models` fills the compose volume. `make embed-test-slow` runs the one real-model test.
