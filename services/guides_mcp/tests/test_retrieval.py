"""Retrieval on the 20-chunk fixture corpus, replaying real BGE-M3 and reranker outputs."""

from __future__ import annotations

import asyncio

import pytest
from homefund_guides_mcp.chunks import Filters
from homefund_guides_mcp.service import GuidesService

from .conftest import by_term


def search(service: GuidesService, query: str, k: int = 5, filters: Filters | None = None):
    return asyncio.run(service.retrieve(query, k, filters))


def test_corpus_has_twenty_searchable_chunks(corpus) -> None:
    searchable = [c for c in corpus["chunks"] if c.get("dense") is not None]
    assert len(searchable) == 20
    assert all(len(c["dense"]) == 1024 for c in searchable)


def test_what_is_pmi_returns_the_pmi_glossary_entry_first(service, store) -> None:
    hits = search(service, "What is PMI?")
    first = hits[0]
    assert first.child.id == by_term(store, "PMI").id
    assert first.child.citation().source == "glossary"
    # The CFPB PMI answer follows right behind it.
    assert hits[1].child.metadata["doc_id"] == "cfpb-pmi"


def test_closing_costs_question_returns_a_cfpb_closing_cost_section(service) -> None:
    hits = search(service, "What closing costs will I pay when I buy a house?")
    top = hits[0].child
    assert top.metadata["source"] == "cfpb"
    assert top.metadata["kind"] == "guide"
    assert top.metadata["doc_id"] == "cfpb-closing-fees"
    cfpb_closing = {"cfpb-closing-fees", "cfpb-loan-estimate", "cfpb-closing-disclosure"}
    assert cfpb_closing <= {h.child.metadata["doc_id"] for h in hits}


@pytest.mark.parametrize(
    ("query", "doc_id"),
    [
        ("How much is the FHA annual mortgage insurance premium?", "hud-ml-2023-05"),
        ("What is the FHA loan limit for a one-unit home in 2026?", "hud-2026-loan-limits"),
        ("How much cash reserves do I need after closing?", "hud-ml-2023-17"),
        ("Do I get my earnest money back?", "cfpb-key-terms"),
    ],
)
def test_other_questions_hit_the_right_document(service, query, doc_id) -> None:
    assert search(service, query)[0].child.metadata["doc_id"] == doc_id


def test_definition_question_on_an_alias_leads_with_the_glossary(service, store) -> None:
    hits = search(service, "What is a debt-to-income ratio?")
    assert hits[0].child.id == by_term(store, "Debt ratio").id  # DTI is its alias
    assert hits[1].child.metadata["doc_id"] == "cfpb-dti"


def test_hits_carry_parent_sections_one_per_parent(service, store) -> None:
    hits = search(service, "What is PMI?", k=8)
    keys = [h.child.parent_id or h.child.id for h in hits]
    assert len(keys) == len(set(keys))
    for h in hits:
        if h.child.parent_id is not None:
            assert h.parent.id == h.child.parent_id
            assert h.child.content.split("\n")[0] in h.parent.content
        else:
            assert h.parent is h.child  # glossary entries are their own section
    # Below the definition-first slot, hits are in reranker order.
    rest = [h.score for h in hits[1:]]
    assert rest == sorted(rest, reverse=True)


def test_k_limits_the_hits(service) -> None:
    assert len(search(service, "What closing costs will I pay when I buy a house?", k=2)) == 2


def test_rerank_sees_at_most_twenty_candidates(service, embedder) -> None:
    search(service, "What closing costs will I pay when I buy a house?")
    assert embedder.reranked == [("What closing costs will I pay when I buy a house?", 20)]


def test_tax_year_filter_drops_other_years_but_keeps_undated_guides(service) -> None:
    q = "What is the FHA loan limit for a one-unit home in 2026?"
    docs_2026 = {
        h.child.metadata["doc_id"] for h in search(service, q, filters=Filters(tax_year=2026))
    }
    docs_2025 = {
        h.child.metadata["doc_id"] for h in search(service, q, filters=Filters(tax_year=2025))
    }
    assert "hud-2026-loan-limits" in docs_2026
    assert "hud-2026-loan-limits" not in docs_2025
    assert docs_2025  # undated guides still pass


def test_source_filter(service) -> None:
    hits = search(service, "What is PMI?", filters=Filters(sources=frozenset({"hud"})))
    assert hits and {h.child.metadata["source"] for h in hits} == {"hud"}


def test_contract_output(service) -> None:
    out = asyncio.run(service.search_guides("What is PMI?", 3))
    assert len(out.hits) == 3
    hit = out.hits[0]
    assert hit.citation.chunk_id == hit.chunk_id
    assert hit.citation.document == "CFPB: Mortgage key terms"
    assert hit.citation.section == "PMI"
    assert hit.citation.url.endswith("#pmi")
    assert hit.citation.quote and hit.citation.quote.startswith("PMI (private mortgage insurance)")
    guide = next(h for h in out.hits if h.parent_id is not None)
    assert guide.citation.source == "cfpb" and guide.citation.url.startswith(
        "https://www.consumerfinance.gov/"
    )
