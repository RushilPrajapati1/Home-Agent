"""FastAPI app: POST /embed, POST /rerank, GET /healthz.

It exists because Ollama and vLLM serve dense vectors only and have no reranker. It runs on
the internal network only; weights come from a volume filled once by ``make embed-models``.
"""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request

from homefund_embed.backends import Backend
from homefund_embed.schemas import (
    DENSE_DIM,
    EmbedRequest,
    EmbedResponse,
    Health,
    RerankRequest,
    RerankResponse,
    SparseWeights,
)

log = logging.getLogger(__name__)


def create_app(backend_factory: Callable[[], Backend]) -> FastAPI:
    """Build the app. The backend loads in the lifespan, so the models load once per process."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.backend = backend_factory()
        yield

    app = FastAPI(title="homefund-embed", version="0.1.0", lifespan=lifespan)

    def backend(request: Request) -> Backend:
        b: Backend = request.app.state.backend
        return b

    # Sync handlers: FastAPI runs them in its threadpool, so model calls never block the loop.
    @app.post("/embed", response_model=EmbedResponse)
    def embed(body: EmbedRequest, request: Request) -> EmbedResponse:
        b = backend(request)
        out = b.encode(body.texts, sparse=body.sparse)
        if any(len(v) != DENSE_DIM for v in out.dense):
            raise RuntimeError(f"{b.embed_model} returned vectors that are not {DENSE_DIM}-d")
        sparse = None
        if body.sparse:
            if out.sparse is None:
                raise RuntimeError("backend returned no sparse weights")
            sparse = [SparseWeights.from_mapping(w) for w in out.sparse]
        return EmbedResponse(model=b.embed_model, dense=out.dense, sparse=sparse)

    @app.post("/rerank", response_model=RerankResponse)
    def rerank(body: RerankRequest, request: Request) -> RerankResponse:
        b = backend(request)
        return RerankResponse(model=b.rerank_model, scores=b.rerank(body.query, body.passages))

    @app.get("/healthz", response_model=Health)
    def healthz(request: Request) -> Health:
        b = backend(request)
        return Health(
            status="ok",
            device=b.device,
            fp16=b.fp16,
            embed_model=b.embed_model,
            rerank_model=b.rerank_model,
        )

    return app


def main() -> None:
    import uvicorn

    from homefund_embed.backends import backend_from_env

    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
    uvicorn.run(
        create_app(backend_from_env),
        host=os.environ.get("EMBED_HOST", "127.0.0.1"),
        port=int(os.environ.get("EMBED_PORT", "8200")),
    )


if __name__ == "__main__":
    main()
