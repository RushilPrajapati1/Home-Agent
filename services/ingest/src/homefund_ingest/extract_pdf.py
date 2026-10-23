"""HUD Mortgagee Letter PDFs to blocks.

Mortgagee Letters use a side-head layout: bold section names in a left column
("Purpose", "Effective Date", "Summary of Changes"), body text in a right column, running
headers and footers, and ruled tables (the MIP rate tables). This extractor:

- keeps only tables with at least two multi-cell rows (pdfplumber also reports boxed
  paragraphs as one-column "tables"; those are read as text),
- reads the left column as level-2 headings and short standalone bold body lines as
  level-3 headings,
- turns "•" and "o" bullets into list items and the rest into paragraphs,
- drops the memo header (date, To:) before the first side-head, and the running
  header/footer lines.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass
from typing import Any

import pdfplumber

from homefund_ingest.model import Block, Extracted

SIDE_X = 160.0  # side-heads start at x≈72; the body column at x≈170
LINE_TOL = 3.0
CHROME = re.compile(
    r"^(Mortgagee Letter \d{4}-\d+, Continued|www\.hud\.gov( +espanol\.hud\.gov)?|\d{1,3})$"
)
BULLET = re.compile(r"^(?:[•▪●◦]|o(?=\s))\s*")


@dataclass
class _Line:
    page: int
    top: float
    bottom: float
    x0: float
    text: str
    bold: bool
    size: float


@dataclass
class _Item:
    page: int
    top: float
    block: Block


def _is_bold(fontname: str) -> bool:
    return "Bold" in fontname or "Black" in fontname


def _real_table(rows: list[list[str | None]]) -> bool:
    multi = [r for r in rows if sum(1 for c in r if c and c.strip()) >= 2]
    return len(multi) >= 2


def _looks_like_heading(text: str) -> bool:
    return len(text.split()) <= 12 and not text.endswith((".", ":", ";"))


def _cell(c: str | None) -> str:
    return re.sub(r"\s+", " ", c or "").strip()


def _table_blocks(rows: list[list[str | None]]) -> list[Block]:
    """Leading one-cell rows are captions: the first, if short, becomes a level-3 heading,
    the rest paragraphs. The remainder is one table. Merged cells come back as None; they
    label cells are filled down so each row reads on its own."""
    out: list[Block] = []
    i = 0
    while i < len(rows) and sum(1 for c in rows[i] if _cell(c)) < 2:
        text = _cell(" ".join(c or "" for c in rows[i]))
        if text and i == 0 and _looks_like_heading(text):
            out.append(Block("heading", text, level=3))
        elif text:
            out.append(Block("paragraph", text))
        i += 1
    body = rows[i:]
    rendered: list[str] = []
    previous: list[str] = []
    for r in body:
        cells = [_cell(c) for c in r]
        if sum(1 for c in cells if c) >= 2 and previous and len(previous) == len(cells):
            # Row spans only cover the leading label columns ("Less than or equal to
            # $726,200" over three LTV rows); fill those, never a gap mid-row.
            lead = next((j for j, c in enumerate(r) if c is not None), len(r))
            cells = [previous[j] if j < lead else c for j, c in enumerate(cells)]
        if any(cells):
            # A cell drawn across two grid columns comes back twice ("40 | 40").
            shown = [c for k, c in enumerate(cells) if c and (k == 0 or c != cells[k - 1])]
            rendered.append(" | ".join(shown))
            previous = cells
    if rendered:
        out.append(Block.table(rendered, header_rows=1))
    return out


def _lines(words: list[dict[str, Any]], page: int) -> list[_Line]:
    words = sorted(words, key=lambda w: (round(w["top"] / LINE_TOL), w["x0"]))
    groups: list[list[dict[str, Any]]] = []
    for w in words:
        if groups and abs(groups[-1][0]["top"] - w["top"]) <= LINE_TOL:
            groups[-1].append(w)
        else:
            groups.append([w])
    out = []
    for g in groups:
        g.sort(key=lambda w: w["x0"])
        text = " ".join(w["text"] for w in g)
        out.append(
            _Line(
                page=page,
                top=min(w["top"] for w in g),
                bottom=max(w["bottom"] for w in g),
                x0=g[0]["x0"],
                text=text,
                bold=all(_is_bold(w["fontname"]) for w in g),
                size=max(w["size"] for w in g),
            )
        )
    return out


def _inside(word: dict[str, Any], bbox: tuple[float, float, float, float]) -> bool:
    x0, top, x1, bottom = bbox
    cx = (word["x0"] + word["x1"]) / 2
    cy = (word["top"] + word["bottom"]) / 2
    return x0 <= cx <= x1 and top <= cy <= bottom


def _body_blocks(lines: list[_Line]) -> list[_Item]:
    """Group body-column lines into paragraphs, list items and level-3 headings."""
    items: list[_Item] = []
    buf: list[_Line] = []
    kind = "paragraph"

    def flush() -> None:
        nonlocal buf
        if buf:
            text = " ".join(line.text for line in buf)
            text = BULLET.sub("", text) if kind == "list_item" else text
            items.append(_Item(buf[0].page, buf[0].top, Block(kind, text)))  # type: ignore[arg-type]
        buf = []

    prev: _Line | None = None
    for line in lines:
        gap = line.top - prev.bottom if prev and prev.page == line.page else 99.0
        bullet = bool(BULLET.match(line.text))
        standalone_bold = line.bold and _looks_like_heading(line.text)
        if standalone_bold and gap > line.size * 0.6:
            flush()
            items.append(_Item(line.page, line.top, Block("heading", line.text, level=3)))
            kind = "paragraph"
            prev = line
            continue
        new_block = bullet or gap > line.size * 0.6 or prev is None
        if new_block:
            flush()
            kind = "list_item" if bullet else "paragraph"
        buf.append(line)
        prev = line
    flush()
    return items


def extract_pdf(raw: bytes) -> Extracted:
    items: list[_Item] = []
    left: list[_Line] = []
    body: list[_Line] = []
    with pdfplumber.open(io.BytesIO(raw)) as pdf:
        for pno, page in enumerate(pdf.pages):
            tables = []
            for t in page.find_tables():
                rows = t.extract()
                if _real_table(rows):
                    tables.append(t)
                    for i, b in enumerate(_table_blocks(rows)):
                        items.append(_Item(pno, t.bbox[1] + i * 0.01, b))
            words = page.extract_words(extra_attrs=["fontname", "size"])
            words = [w for w in words if not any(_inside(w, t.bbox) for t in tables)]
            # Running headers and footers, matched on full-width lines.
            chrome = [ln for ln in _lines(words, pno) if CHROME.match(ln.text)]
            words = [
                w for w in words if not any(abs(w["top"] - ln.top) <= LINE_TOL for ln in chrome)
            ]
            # Split the columns before grouping lines: a side-head shares its baseline with
            # the first body line next to it.
            for column, target in (
                ([w for w in words if w["x0"] < SIDE_X], left),
                ([w for w in words if w["x0"] >= SIDE_X], body),
            ):
                target.extend(_lines(column, pno))

    # Side-heads: consecutive bold left-column lines ("Summary of" / "Changes") join up.
    heads: list[_Line] = []
    for line in left:
        if not line.bold:
            body.append(line)
            continue
        last = heads[-1] if heads else None
        if last and last.page == line.page and line.top - last.bottom < line.size * 0.6:
            last.text = f"{last.text} {line.text}"
            last.bottom = line.bottom
        else:
            heads.append(_Line(**vars(line)))
    for h in heads:
        items.append(_Item(h.page, h.top - 0.5, Block("heading", h.text, level=2)))
    body.sort(key=lambda line: (line.page, line.top))
    items.extend(_body_blocks(body))
    items.sort(key=lambda it: (it.page, it.top))

    blocks = [it.block for it in items]
    # The memo header (Date, letter number, To: list) runs until the "Subject" side-head.
    heads_at = [i for i, b in enumerate(blocks) if b.kind == "heading" and b.level == 2]
    start = next(
        (i for i in heads_at if blocks[i].text == "Subject"), heads_at[0] if heads_at else 0
    )
    return Extracted(blocks=blocks[start:])
