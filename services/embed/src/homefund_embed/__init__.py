"""Home Fund embed service: BGE-M3 dense + sparse vectors and bge-reranker-v2-m3 scores.

The base package is the wire schema and an async HTTP client, so ingest and guides-mcp can
import it without torch. The FastAPI server and its model backends need the ``model`` extra.
"""

from homefund_embed.client import EmbedClient
from homefund_embed.schemas import (
    DENSE_DIM,
    EmbedRequest,
    EmbedResponse,
    RerankRequest,
    RerankResponse,
    SparseWeights,
)

__all__ = [
    "DENSE_DIM",
    "EmbedClient",
    "EmbedRequest",
    "EmbedResponse",
    "RerankRequest",
    "RerankResponse",
    "SparseWeights",
]
