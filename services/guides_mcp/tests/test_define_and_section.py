from __future__ import annotations

import asyncio
import uuid

import pytest
from homefund_guides_mcp.glossary import Glossary, normalize
from homefund_guides_mcp.service import SectionNotFound

from .conftest import by_term


@pytest.mark.parametrize(
    ("text", "key"),
    [
        ("What is PMI?", "pmi"),
        ("what's an escrow account", "escrow account"),
        ("Define the loan-to-value ratio.", "loan to value ratio"),
        ("What does DTI mean?", "dti"),
        ("  Earnest   money ", "earnest money"),
    ],
)
def test_normalize(text, key) -> None:
    assert normalize(text) == key


@pytest.mark.parametrize(
    ("asked", "term", "how"),
    [
        ("PMI", "PMI", "exact"),
        ("private mortgage insurance", "PMI", "exact"),
        ("What is DTI?", "Debt ratio", "exact"),
        ("LTV", "Loan-to-value ratio", "exact"),
        ("closing costs", "Mortgage closing costs", "exact"),
        ("MIP", "FHA funding fee", "exact"),
        ("cash reserves", "Reserves", "exact"),
        ("down payments", "Down payment", "exact"),  # plural
        ("morgage insurance", "Mortgage insurance", "fuzzy"),
        ("earnest mony", "Earnest money", "fuzzy"),
    ],
)
def test_glossary_lookup(store, asked, term, how) -> None:
    match = Glossary(store.glossary()).lookup(asked)
    assert match is not None
    assert (match.chunk.metadata["term"], match.how) == (term, how)


def test_short_terms_never_fuzzy_match(store) -> None:
    assert Glossary(store.glossary()).lookup("PTI") is None  # not PITI, not PMI


def test_define_term_from_the_glossary(service, store) -> None:
    out = asyncio.run(service.define_term("pmi"))
    assert out.found and out.term == "PMI"
    assert out.definition.startswith(
        "Private Mortgage Insurance (PMI) is a type of mortgage insurance"
    )
    assert out.citation.chunk_id == by_term(store, "PMI").id
    assert out.citation.source == "glossary"


def test_define_term_falls_back_to_search(service) -> None:
    # Not a glossary term; the recorded query falls through to hybrid search.
    out = asyncio.run(
        service.define_term("What is the FHA loan limit for a one-unit home in 2026?")
    )
    assert out.found
    assert out.citation.source == "hud"
    assert "$541,287" in out.definition


def test_get_section_returns_the_parent(service, store, corpus) -> None:
    child = next(
        c for c in corpus["chunks"] if c["parent_id"] and c["metadata"]["doc_id"] == "cfpb-pmi"
    )
    out = asyncio.run(service.get_section(uuid.UUID(child["id"])))
    assert str(out.section_id) == child["parent_id"]
    assert out.title == child["metadata"]["doc_title"]  # the page-level section: its title
    assert child["content"].split("\n")[0] in out.content
    assert out.citation.chunk_id == out.section_id


def test_get_section_of_a_glossary_entry_is_itself(service, store) -> None:
    pmi = by_term(store, "PMI")
    out = asyncio.run(service.get_section(pmi.id))
    assert out.section_id == pmi.id and out.title == "PMI"


def test_get_section_unknown_id(service) -> None:
    with pytest.raises(SectionNotFound):
        asyncio.run(service.get_section(uuid.uuid4()))
