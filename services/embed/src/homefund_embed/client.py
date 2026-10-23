"""Async client for the embed service, used by ingest (index time) and guides-mcp (query time)."""

from __future__ import annotations

import os
from collections.abc import Sequence
from dataclasses import dataclass
from types import TracebackType
from typing import Self

import httpx

from homefund_embed.schemas import (
    MAX_TEXTS,
    EmbedRequest,
    EmbedResponse,
    Health,
    RerankRequest,
    RerankResponse,
    SparseWeights,
)

DEFAULT_URL = "http://localhost:8200"


@dataclass(frozen=True)
class Embeddings:
    model: str
    dense: list[list[float]]
    sparse: list[SparseWeights] | None


class EmbedClient:
    """Thin wrapper over POST /embed and /rerank that splits big inputs into batches."""

    def __init__(
        self,
        base_url: str | None = None,
        *,
        batch_size: int = 64,
        timeout: float = 300.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not 1 <= batch_size <= MAX_TEXTS:
            raise ValueError(f"batch_size must be between 1 and {MAX_TEXTS}")
        url = base_url or os.environ.get("EMBED_URL", "").strip() or DEFAULT_URL
        self._batch_size = batch_size
        self._http = httpx.AsyncClient(base_url=url, timeout=timeout, transport=transport)

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._http.aclose()

    async def health(self) -> Health:
        resp = await self._http.get("/healthz")
        resp.raise_for_status()
        return Health.model_validate(resp.json())

    async def embed(self, texts: Sequence[str], *, sparse: bool = True) -> Embeddings:
        model = ""
        dense: list[list[float]] = []
        weights: list[SparseWeights] = []
        for start in range(0, len(texts), self._batch_size):
            batch = list(texts[start : start + self._batch_size])
            body = EmbedRequest(texts=batch, sparse=sparse)
            resp = await self._http.post("/embed", json=body.model_dump())
            resp.raise_for_status()
            out = EmbedResponse.model_validate(resp.json())
            if len(out.dense) != len(batch):
                raise RuntimeError("embed service returned the wrong number of vectors")
            model = out.model
            dense.extend(out.dense)
            if sparse:
                if out.sparse is None or len(out.sparse) != len(batch):
                    raise RuntimeError("embed service returned no sparse weights")
                weights.extend(out.sparse)
        return Embeddings(model=model, dense=dense, sparse=weights if sparse else None)

    async def rerank(self, query: str, passages: Sequence[str]) -> list[float]:
        scores: list[float] = []
        for start in range(0, len(passages), self._batch_size):
            batch = list(passages[start : start + self._batch_size])
            body = RerankRequest(query=query, passages=batch)
            resp = await self._http.post("/rerank", json=body.model_dump())
            resp.raise_for_status()
            out = RerankResponse.model_validate(resp.json())
            if len(out.scores) != len(batch):
                raise RuntimeError("rerank service returned the wrong number of scores")
            scores.extend(out.scores)
        return scores
