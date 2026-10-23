"""search_guides, define_term and get_section over a GuideStore, an embedder and a reranker.

The store is synchronous (SQLAlchemy); its calls run in a worker thread so the MCP event
loop stays free. The embedder and reranker are the embed service (EmbedClient).
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from homefund_contracts.mcp.guides import (
    DefineTermOutput,
    GetSectionOutput,
    GuideHit,
    SearchGuidesOutput,
)
from homefund_guides_mcp.chunks import Chunk, Filters
from homefund_guides_mcp.glossary import Glossary, definition_of
from homefund_guides_mcp.recipe import apply_filters, best_per_parent, rrf
from homefund_guides_mcp.store import GuideStore

TOP_N = 50  # per retriever, before fusion
RERANK_POOL = 20  # "Top 20" in the recipe
GLOSSARY_TTL = 300.0  # seconds; ingest may add terms while the server runs
MIN_DEFINITION_SCORE = 0.3  # define_term's search fallback: below this, report not found


class SparseLike(Protocol):
    def as_dict(self) -> dict[int, float]: ...


class EmbeddingsLike(Protocol):
    dense: list[list[float]]

    @property
    def sparse(self) -> Sequence[SparseLike] | None: ...


class Embedder(Protocol):
    async def embed(self, texts: Sequence[str], *, sparse: bool = True) -> EmbeddingsLike: ...

    async def rerank(self, query: str, passages: Sequence[str]) -> list[float]: ...


class SectionNotFound(LookupError):
    pass


@dataclass(frozen=True)
class Hit:
    child: Chunk
    parent: Chunk
    score: float

    def to_contract(self) -> GuideHit:
        return GuideHit(
            chunk_id=self.child.id,
            parent_id=self.child.parent_id,
            content=self.parent.content,
            score=self.score,
            citation=self.child.citation(),
        )


class GuidesService:
    def __init__(
        self,
        store: GuideStore,
        embedder: Embedder,
        *,
        default_filters: Filters | None = None,
        top_n: int = TOP_N,
        rerank_pool: int = RERANK_POOL,
    ) -> None:
        self._store = store
        self._embed = embedder
        self._filters = default_filters or Filters()
        self._top_n = top_n
        self._pool = rerank_pool
        self._glossary: Glossary | None = None
        self._glossary_at = 0.0

    async def retrieve(self, query: str, k: int = 5, filters: Filters | None = None) -> list[Hit]:
        f = filters or self._filters
        q = await self._embed.embed([query], sparse=True)
        if q.sparse is None:
            raise RuntimeError("embed service returned no sparse weights")
        dense_hits, sparse_hits = await asyncio.gather(
            asyncio.to_thread(self._store.dense_search, q.dense[0], self._top_n, f),
            asyncio.to_thread(self._store.sparse_search, q.sparse[0].as_dict(), self._top_n, f),
        )
        pool = apply_filters(rrf([dense_hits, sparse_hits]), f)[: self._pool]
        # A definition question ("What is PMI?") whose whole subject is a glossary term gets
        # that entry first, as the design intends ("answered in a single hit"); the
        # reranker alone may prefer a longer guide page that also defines it.
        term = (await self.glossary()).lookup(query, fuzzy=False)
        definition = term.chunk if term and f.matches(term.chunk.metadata) else None
        if definition is not None and definition.id not in {c.id for c in pool}:
            pool.append(definition)
        if not pool:
            return []
        scores = await self._embed.rerank(query, [c.rerank_text for c in pool])
        top = best_per_parent(list(zip(pool, scores, strict=True)), k, first=definition)
        parent_ids = {c.parent_id for c, _ in top if c.parent_id is not None}
        parents = await asyncio.to_thread(self._store.get, parent_ids)
        return [Hit(c, parents.get(c.parent_id, c) if c.parent_id else c, s) for c, s in top]

    async def search_guides(self, query: str, k: int = 5) -> SearchGuidesOutput:
        hits = await self.retrieve(query, k)
        return SearchGuidesOutput(hits=[h.to_contract() for h in hits])

    async def glossary(self) -> Glossary:
        now = time.monotonic()
        if self._glossary is None or now - self._glossary_at > GLOSSARY_TTL:
            self._glossary = Glossary(await asyncio.to_thread(self._store.glossary))
            self._glossary_at = now
        return self._glossary

    async def define_term(self, term: str) -> DefineTermOutput:
        """Glossary first (exact, then fuzzy). Otherwise the best search hit's chunk, cited
        from its guide, if the reranker finds it relevant enough; else ``found`` is false."""
        match = (await self.glossary()).lookup(term)
        if match is not None:
            chunk = match.chunk
            return DefineTermOutput(
                term=str(chunk.metadata.get("term", term)),
                found=True,
                definition=definition_of(chunk),
                citation=chunk.citation(quote=False),
            )
        hits = await self.retrieve(term, k=1)
        if not hits or hits[0].score < MIN_DEFINITION_SCORE:
            return DefineTermOutput(term=term, found=False)
        child = hits[0].child
        return DefineTermOutput(
            term=term, found=True, definition=child.content, citation=child.citation()
        )

    async def get_section(self, chunk_id: uuid.UUID) -> GetSectionOutput:
        found = await asyncio.to_thread(self._store.get, [chunk_id])
        chunk = found.get(chunk_id)
        if chunk is None:
            raise SectionNotFound(f"no guide chunk {chunk_id}")
        section = chunk
        if chunk.parent_id is not None:
            parents = await asyncio.to_thread(self._store.get, [chunk.parent_id])
            section = parents.get(chunk.parent_id, chunk)
        return GetSectionOutput(
            section_id=section.id,
            title=section.title,
            content=section.content,
            citation=section.citation(quote=False),
        )
