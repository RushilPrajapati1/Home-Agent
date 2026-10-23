from __future__ import annotations

import itertools
import re

import pytest
from homefund_ingest.chunker import (
    TOKEN,
    ChunkSettings,
    build_sections,
    chunk_blocks,
    count_tokens,
    render_block,
)
from homefund_ingest.model import Block

WS = re.compile(r"\s+")


def norm(text: str) -> str:
    return WS.sub(" ", text).strip()


def children(rows):
    return [r for r in rows if r.metadata["role"] == "child"]


def own_text_by_path(blocks, title):
    root = build_sections(blocks, title)
    return {s.path: norm(" ".join(render_block(b) for b in s.blocks)) for s in root.walk()}


def toks(text: str) -> list[str]:
    return TOKEN.findall(text)


# --- headings ------------------------------------------------------------------------------


def test_children_stay_inside_one_section(docs, extracted, rows) -> None:
    for doc_id in ("cfpb-pmi", "cfpb-loan-estimate", "hud-2026-loan-limits", "hud-ml-2023-05"):
        bodies = own_text_by_path(extracted(doc_id).blocks, docs[doc_id].title)
        kids = children(rows(doc_id))
        assert kids, doc_id
        for child in kids:
            path = tuple(child.metadata["section_path"])
            assert path in bodies, (doc_id, path)
            assert norm(child.content) in bodies[path], (doc_id, path)


def test_pmi_sections_follow_the_headings(rows) -> None:
    paths = {tuple(c.metadata["section_path"]) for c in children(rows("cfpb-pmi"))}
    assert () in paths  # the answer under the h1, which repeats the title and is not a path
    assert ("How do I pay for PMI?",) in paths
    assert ("How does PMI compare to other parts of my loan offer?", "Down payment") in paths
    # Site chrome sections are dropped.
    assert not any("Browse related questions" in p for path in paths for p in path)


def test_expandable_panels_are_sections(rows) -> None:
    paths = {tuple(c.metadata["section_path"]) for c in children(rows("cfpb-loan-estimate"))}
    assert ("Sample Loan Estimate", "Actions to take", "Check the spelling of your name") in paths
    assert ("Sample Loan Estimate", "Definitions to know", "Mortgage insurance") in paths


def test_pdf_side_heads_are_sections(extracted) -> None:
    blocks = extracted("hud-ml-2023-05").blocks
    heads = [b.text for b in blocks if b.kind == "heading" and b.level == 2]
    assert heads[:4] == ["Subject", "Purpose", "Effective Date", "Public Feedback"]
    assert "Summary of Changes" in heads
    text = " ".join(b.text for b in blocks)
    assert "All FHA Roster Appraisers" not in text  # memo header dropped
    assert "Continued" not in text  # running header dropped


def test_parent_holds_the_full_section(rows) -> None:
    all_rows = rows("cfpb-pmi")
    parents = {r.id: r for r in all_rows if r.metadata["role"] == "parent"}
    for child in children(all_rows):
        assert norm(child.content) in norm(parents[child.parent_id].content)


def test_big_sections_are_split_into_smaller_parents() -> None:
    blocks = [Block("heading", "Guide", level=1)]
    for s in range(3):
        blocks.append(Block("heading", f"Part {s}", level=2))
        blocks += [Block("paragraph", sentences(40, f"p{s}")), Block("paragraph", "End.")]
    small = chunk_blocks(blocks, "Guide", ChunkSettings(parent_max=600))
    assert [p.path for p in small] == [("Part 0",), ("Part 1",), ("Part 2",)]
    whole = chunk_blocks(blocks, "Guide", ChunkSettings(parent_max=10_000))
    assert [p.path for p in whole] == [()]


# --- overlap -------------------------------------------------------------------------------


def sentences(n: int, tag: str = "s", words: int = 9) -> str:
    return " ".join(
        f"Sentence {tag}{i} " + " ".join(f"w{tag}{i}x{j}" for j in range(words)) + "."
        for i in range(n)
    )


def check_overlaps(kids, settings: ChunkSettings) -> list[int]:
    overlaps = []
    for prev, nxt in itertools.pairwise(kids):
        k = nxt.overlap_tokens
        assert 0 < k <= settings.overlap
        assert toks(prev.content)[-k:] == toks(nxt.content)[:k]
        overlaps.append(k)
    return overlaps


def test_children_are_500_tokens_with_50_token_overlap() -> None:
    settings = ChunkSettings()
    text = sentences(150)  # 12 tokens per sentence: 1800 tokens
    (parent,) = chunk_blocks([Block("paragraph", text)], "Doc", settings)
    kids = parent.children
    assert len(kids) == 4  # 1800 tokens + 3 overlaps of ~48 fit in four 500-token children
    assert all(c.tokens <= settings.child_tokens for c in kids)
    assert all(c.tokens >= 450 for c in kids[:-1])
    overlaps = check_overlaps(kids, settings)
    assert all(k >= settings.overlap - 12 for k in overlaps)  # whole sentences, near 50
    # Nothing lost: dropping each overlap and concatenating gives the original tokens back.
    rebuilt = toks(kids[0].content)
    for c in kids[1:]:
        rebuilt += toks(c.content)[c.overlap_tokens :]
    assert rebuilt == toks(text)


def test_long_sentence_overlap_is_exactly_the_last_50_tokens() -> None:
    settings = ChunkSettings()
    text = sentences(12, words=60)  # 63 tokens each: longer than the overlap
    (parent,) = chunk_blocks([Block("paragraph", text)], "Doc", settings)
    overlaps = check_overlaps(parent.children, settings)
    assert overlaps and all(k == settings.overlap for k in overlaps)


def test_overlap_respects_custom_settings() -> None:
    settings = ChunkSettings(child_tokens=120, overlap=20)
    (parent,) = chunk_blocks([Block("paragraph", sentences(40))], "Doc", settings)
    assert all(c.tokens <= 120 for c in parent.children)
    check_overlaps(parent.children, settings)


def test_overlap_must_be_smaller_than_children() -> None:
    with pytest.raises(ValueError):
        ChunkSettings(child_tokens=50, overlap=50)


# --- lists and tables ------------------------------------------------------------------------


def test_list_items_are_never_split() -> None:
    items = [f"item{i} " + " ".join(f"word{i}x{j}" for j in range(70)) for i in range(12)]
    blocks = [Block("list_item", t) for t in items]
    (parent,) = chunk_blocks(blocks, "Doc", ChunkSettings())
    assert len(parent.children) > 1
    for child in parent.children:
        lines = child.content.split("\n")
        assert all(line.removeprefix("- ") in items for line in lines)
        assert child.overlap_tokens == 0  # a 72-token item is longer than the overlap


def test_html_table_stays_whole(extracted, rows) -> None:
    (table,) = [b for b in extracted("hud-2026-loan-limits").blocks if b.kind == "table"]
    assert table.rows[0].startswith("Property Size")
    holders = [c for c in children(rows("hud-2026-loan-limits")) if "One-Unit" in c.content]
    assert len(holders) == 1
    assert table.text in holders[0].content


def test_pdf_mip_table_stays_whole(extracted, rows) -> None:
    tables = [b for b in extracted("hud-ml-2023-05").blocks if b.kind == "table"]
    mip = next(t for t in tables if "MIP (bps)" in t.rows[0])
    assert "Less than or equal to $726,200 | > 95.00% | 55 | Mortgage term" in mip.rows
    holders = [c for c in children(rows("hud-ml-2023-05")) if mip.rows[1] in c.content]
    assert len(holders) == 1 and mip.text in holders[0].content


def test_long_table_is_cut_between_rows_with_the_header_repeated() -> None:
    header = "Year | Rate | Points | Note"
    data = [
        f"{2000 + i} | {i}.5% | {i} | " + " ".join(f"n{i}x{j}" for j in range(8)) for i in range(60)
    ]
    settings = ChunkSettings()
    (parent,) = chunk_blocks([Block.table([header, *data])], "Doc", settings)
    kids = parent.children
    assert len(kids) > 1
    seen = []
    for c in kids:
        lines = c.content.split("\n")
        assert lines[0] == header
        assert c.tokens <= settings.child_tokens
        assert c.overlap_tokens == 0  # table rows are never carried as overlap
        seen += lines[1:]
    assert seen == data  # every row once, whole, in order


def test_small_table_inside_prose_is_one_unit() -> None:
    blocks = [
        Block("paragraph", sentences(30)),
        Block.table(["A | B", "1 | 2", "3 | 4"]),
        Block("paragraph", sentences(30, "t")),
    ]
    (parent,) = chunk_blocks(blocks, "Doc", ChunkSettings(child_tokens=400, overlap=40))
    holders = [c for c in parent.children if "1 | 2" in c.content]
    assert holders and all("A | B\n1 | 2\n3 | 4" in c.content for c in holders)


def test_token_count() -> None:
    # PMI · costs · 0 · . · 5 · % · a · year · , · typically · .
    assert count_tokens("PMI costs 0.5% a year, typically.") == 11
