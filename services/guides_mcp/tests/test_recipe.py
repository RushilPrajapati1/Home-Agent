from __future__ import annotations

import uuid

from homefund_guides_mcp.chunks import Chunk, Filters, excerpt
from homefund_guides_mcp.recipe import apply_filters, best_per_parent, rrf


def chunk(name: str, parent: str | None = None, **meta) -> Chunk:
    ns = uuid.NAMESPACE_URL
    return Chunk(
        uuid.uuid5(ns, name),
        uuid.uuid5(ns, parent) if parent else None,
        name,
        {"source": "cfpb", **meta},
    )


def test_rrf_sums_reciprocal_ranks() -> None:
    a, b, c = chunk("a"), chunk("b"), chunk("c")
    fused = rrf([[a, b, c], [c, a]], k=60)
    # a: 1/61 + 1/62, c: 1/63 + 1/61, b: 1/62
    assert [x.content for x in fused] == ["a", "c", "b"]


def test_rrf_ties_keep_first_appearance() -> None:
    a, b = chunk("a"), chunk("b")
    assert [x.content for x in rrf([[a], [b]])] == ["a", "b"]
    assert [x.content for x in rrf([[b], [a]])] == ["b", "a"]


def test_filters() -> None:
    dated = chunk("dated", tax_year=2026, source="hud")
    undated = chunk("undated", tax_year=None)
    assert apply_filters([dated, undated], Filters(tax_year=2025)) == [undated]
    assert apply_filters([dated, undated], Filters(tax_year=2026)) == [dated, undated]
    assert apply_filters([dated, undated], Filters(sources=frozenset({"hud"}))) == [dated]


def test_best_per_parent() -> None:
    p1a, p1b, p2, g = chunk("p1a", "P1"), chunk("p1b", "P1"), chunk("p2", "P2"), chunk("g")
    ranked = [(p1a, 0.5), (p1b, 0.9), (p2, 0.7), (g, 0.6)]
    assert [c.content for c, _ in best_per_parent(ranked, 5)] == ["p1b", "p2", "g"]
    assert [c.content for c, _ in best_per_parent(ranked, 2)] == ["p1b", "p2"]
    assert [c.content for c, _ in best_per_parent(ranked, 3, first=g)] == ["g", "p1b", "p2"]


def test_excerpt() -> None:
    assert excerpt("short  text") == "short text"
    long = " ".join(["word"] * 200)
    out = excerpt(long, 50)
    assert len(out) <= 51 and out.endswith("…")
