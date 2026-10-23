from __future__ import annotations

import pytest
from homefund_ingest.chunker import ChunkSettings
from homefund_ingest.model import Block, Extracted
from homefund_ingest.pipeline import build_rows, term_spans
from homefund_ingest.sources import SourceDoc, TermSpan


def test_glossary_is_one_term_per_chunk(rows) -> None:
    gl = rows("cfpb-key-terms")
    assert len(gl) == 106
    assert {r.metadata["role"] for r in gl} == {"glossary"}
    assert all(r.parent_id is None and r.embed_text for r in gl)
    pmi = next(r for r in gl if r.metadata["term"] == "PMI")
    assert pmi.content.startswith("PMI (private mortgage insurance): Private Mortgage Insurance")
    assert pmi.metadata["source"] == "glossary"
    assert pmi.metadata["kind"] == "glossary"
    assert pmi.metadata["url"].endswith("/key-terms/#pmi")
    assert "Understand more" not in pmi.content  # trailing link text dropped


def test_metadata_has_the_citation_fields(rows) -> None:
    for r in rows("hud-2026-loan-limits"):
        m = r.metadata
        assert {"source", "doc_title", "section_path", "url", "tax_year", "kind"} <= m.keys()
        assert m["source"] == "hud" and m["kind"] == "guide" and m["tax_year"] == 2026


def test_context_header_is_prepended_only_when_on(docs, rows) -> None:
    on = [r for r in rows("cfpb-pmi") if r.metadata["role"] == "child"]
    off = [r for r in rows("cfpb-pmi", context_header=False) if r.metadata["role"] == "child"]
    title = docs["cfpb-pmi"].title
    pay = next(r for r in on if r.metadata["section_path"] == ["How do I pay for PMI?"])
    assert pay.embed_text == f"{title} > How do I pay for PMI?\n\n{pay.content}"
    assert all(r.embed_text == r.content for r in off)
    assert [r.content for r in on] == [r.content for r in off]


def test_ids_are_stable_and_follow_the_content_hash(rows) -> None:
    a, b = rows("cfpb-pmi"), rows("cfpb-pmi")
    assert [r.id for r in a] == [r.id for r in b]
    off = rows("cfpb-pmi", context_header=False)
    parents = lambda rs: [r.id for r in rs if r.metadata["role"] == "parent"]  # noqa: E731
    kids = lambda rs: {r.id for r in rs if r.metadata["role"] == "child"}  # noqa: E731
    assert parents(a) == parents(off)  # parents are not embedded
    assert not kids(a) & kids(off)  # different embedding text, so re-embedded
    assert all(r.parent_id in set(parents(a)) for r in a if r.metadata["role"] == "child")


def test_model_change_changes_child_ids(docs, extracted) -> None:
    one = build_rows(docs["cfpb-pmi"], extracted("cfpb-pmi"), ChunkSettings(), "model-a")
    two = build_rows(docs["cfpb-pmi"], extracted("cfpb-pmi"), ChunkSettings(), "model-b")
    assert {r.id for r in one if r.embed_text} != {r.id for r in two if r.embed_text}


def test_metadata_change_changes_every_id(docs, extracted) -> None:
    doc = docs["hud-2026-loan-limits"]
    before = build_rows(doc, extracted(doc.id), ChunkSettings(), "m")
    for change in ({"title": "Renamed"}, {"tax_year": 2027}, {"url": "https://www.hud.gov/moved"}):
        after = build_rows(doc.model_copy(update=change), extracted(doc.id), ChunkSettings(), "m")
        assert not {r.id for r in before} & {r.id for r in after}, change


def test_duplicate_content_gets_distinct_ids() -> None:
    doc = SourceDoc(
        id="d", source="cfpb", kind="guide", publisher="cfpb", title="D", url="https://x"
    )
    blocks = [
        Block("heading", "A", level=2),
        Block("paragraph", "Same words here."),
        Block("heading", "A", level=2),
        Block("paragraph", "Same words here."),
    ]
    rows = build_rows(doc, Extracted(blocks=blocks), ChunkSettings(parent_max=5), "m")
    ids = [r.id for r in rows]
    assert len(ids) == len(set(ids)) == 4


def test_term_spans_cut_a_definition_out_of_the_text() -> None:
    doc = SourceDoc(
        id="hud",
        source="glossary",
        kind="glossary",
        publisher="hud",
        title="HUD",
        url="https://h",
        terms=[
            TermSpan(
                term="Reserves",
                aliases=["cash reserves"],
                start="Reserves refer to",
                end="any source.",
            )
        ],
    )
    ex = Extracted(
        blocks=[
            Block("paragraph", "Intro."),
            Block("paragraph", "Reserves refer to liquid assets minus funds due at closing."),
            Block("paragraph", "Reserves do not include:"),
            Block("list_item", "borrowed funds from any source."),
            Block("paragraph", "Next topic."),
        ]
    )
    (entry,) = term_spans(doc, ex)
    assert entry.definition == (
        "Reserves refer to liquid assets minus funds due at closing. "
        "Reserves do not include: - borrowed funds from any source."
    )
    bad = doc.model_copy(update={"terms": [TermSpan(term="X", start="nope", end="never")]})
    with pytest.raises(ValueError, match="could not find"):
        term_spans(bad, ex)


def test_eval_questions_point_at_real_sections(sources) -> None:
    """evals/retrieval/questions.jsonl (Prompt 4B's retrieval set): 30 questions whose
    expected and also-relevant sections all exist in the chunked corpus."""
    import json

    from homefund_ingest.pipeline import extract
    from homefund_ingest.sources import DEFAULT_DATA_DIR

    from .conftest import REPO

    sections = set()
    for doc in sources.documents:
        for r in build_rows(
            doc, extract(doc, DEFAULT_DATA_DIR, sources.drop_sections), ChunkSettings(), "m"
        ):
            if r.embed_text is not None:
                sections.add((doc.id, tuple(r.metadata["section_path"])))
    lines = (
        (REPO / "evals" / "retrieval" / "questions.jsonl").read_text(encoding="utf-8").splitlines()
    )
    questions = [json.loads(line) for line in lines]
    assert len(questions) == 30
    assert len({q["id"] for q in questions}) == len({q["question"] for q in questions}) == 30
    for q in questions:
        assert q["kind"] in {"definition", "guide"} and q["source"] in {"cfpb", "hud", "glossary"}
        for s in [q["expected"], *q["also_relevant"]]:
            assert (s["doc_id"], tuple(s["section_path"])) in sections, (q["id"], s)
