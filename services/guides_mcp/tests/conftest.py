from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
from homefund_embed.client import Embeddings
from homefund_embed.schemas import SparseWeights
from homefund_guides_mcp.chunks import Chunk
from homefund_guides_mcp.service import GuidesService
from homefund_guides_mcp.store import MemoryGuideStore

CORPUS = Path(__file__).resolve().parents[3] / "fixtures" / "guides-rag" / "corpus.json"


@pytest.fixture(scope="session")
def corpus() -> dict[str, Any]:
    return json.loads(CORPUS.read_text(encoding="utf-8"))


class ReplayEmbedder:
    """Replays the real BGE-M3 query vectors and reranker scores recorded in corpus.json.
    An unrecorded query or passage is an error, so tests can't silently use made-up numbers."""

    def __init__(self, corpus: dict[str, Any], store: MemoryGuideStore) -> None:
        self._queries = corpus["queries"]
        searchable = [c for c in corpus["chunks"] if c.get("dense") is not None]
        chunks = store.get(Chunk_ids(searchable))
        self._passage_ids = {c.rerank_text: str(c.id) for c in chunks.values()}
        self.reranked: list[tuple[str, int]] = []

    async def embed(self, texts: Sequence[str], *, sparse: bool = True) -> Embeddings:
        rows = [self._queries[t] for t in texts]
        return Embeddings(
            model="BAAI/bge-m3",
            dense=[r["dense"] for r in rows],
            sparse=[SparseWeights(**r["sparse"]) for r in rows] if sparse else None,
        )

    async def rerank(self, query: str, passages: Sequence[str]) -> list[float]:
        self.reranked.append((query, len(passages)))
        scores = self._queries[query]["rerank"]
        return [scores[self._passage_ids[p]] for p in passages]


def Chunk_ids(rows: list[dict[str, Any]]):
    import uuid

    return [uuid.UUID(r["id"]) for r in rows]


@pytest.fixture
def store(corpus) -> MemoryGuideStore:
    return MemoryGuideStore(corpus["chunks"])


@pytest.fixture
def embedder(corpus, store) -> ReplayEmbedder:
    return ReplayEmbedder(corpus, store)


@pytest.fixture
def service(store, embedder) -> GuidesService:
    return GuidesService(store, embedder)


def by_term(store: MemoryGuideStore, term: str) -> Chunk:
    return next(c for c in store.glossary() if c.metadata["term"] == term)
