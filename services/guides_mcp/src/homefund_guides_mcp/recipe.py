"""The retrieval recipe's pure steps (design, Data & chunking page):

question → BGE-M3 dense + sparse top-N → reciprocal rank fusion → source / tax-year filter
→ top 20 → bge-reranker-v2-m3 → top k, one hit per parent section.

One addition: when the whole question is "what is <glossary term>", that glossary entry is
put first (see GuidesService.retrieve).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from homefund_guides_mcp.chunks import Chunk, Filters

RRF_K = 60


def rrf(rankings: Sequence[Sequence[Chunk]], k: int = RRF_K) -> list[Chunk]:
    """Reciprocal rank fusion: score(d) = Σ 1 / (k + rank), rank from 1. Ties keep the
    order of first appearance, so the result is deterministic."""
    scores: dict[uuid.UUID, float] = {}
    first: dict[uuid.UUID, int] = {}
    chunks: dict[uuid.UUID, Chunk] = {}
    order = 0
    for ranking in rankings:
        for rank, chunk in enumerate(ranking, start=1):
            scores[chunk.id] = scores.get(chunk.id, 0.0) + 1.0 / (k + rank)
            if chunk.id not in first:
                first[chunk.id] = order
                chunks[chunk.id] = chunk
                order += 1
    ids = sorted(scores, key=lambda i: (-scores[i], first[i]))
    return [chunks[i] for i in ids]


def apply_filters(chunks: Sequence[Chunk], filters: Filters) -> list[Chunk]:
    return [c for c in chunks if filters.matches(c.metadata)]


def best_per_parent(
    ranked: Sequence[tuple[Chunk, float]], k: int, *, first: Chunk | None = None
) -> list[tuple[Chunk, float]]:
    """Top ``k`` by reranker score, keeping only the best child of each parent section
    (a glossary entry is its own parent), since the parent is what the model receives.
    ``first``, if given and present, leads regardless of its score."""
    out: list[tuple[Chunk, float]] = []
    seen: set[uuid.UUID] = set()
    order = sorted(ranked, key=lambda cs: -cs[1])
    if first is not None:
        order.sort(key=lambda cs: cs[0].id != first.id)  # stable: the rest keep their order
    for chunk, score in order:
        key = chunk.parent_id or chunk.id
        if key in seen:
            continue
        seen.add(key)
        out.append((chunk, score))
        if len(out) == k:
            break
    return out
