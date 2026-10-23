"""Heading-aware parent/child chunking, as on the design's Data & chunking page.

- Sections follow the headings. A *parent* is the largest enclosing section of at most
  ``parent_max`` tokens (a leaf section is a parent even when longer); its full text is what
  the model is handed.
- *Children* are about ``child_tokens`` tokens with ``overlap`` tokens carried over from the
  previous child. They never cross a heading, so every child has one section path.
- The packing units are sentences, list items and tables. A list item or a table row is
  never split. A table that fits in one child stays whole; a longer one is cut between
  rows, with its header row repeated. Only prose sentences may be cut, and only when a
  single sentence is longer than a child or is the overlap tail.
- Glossary entries are one chunk each.

Tokens are counted as words plus punctuation marks (``count_tokens``). That tracks the
BGE-M3 (XLM-R) tokenizer closely for English prose without loading it, so chunking stays
offline and deterministic.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass, field

from homefund_ingest.model import Block, GlossaryEntry

TOKEN = re.compile(r"\w+|[^\w\s]")
SENTENCE_END = re.compile(r"(?<=[.!?])[\"\u201d\u2019)]?\s+(?=[\"\u201c(]?[A-Z0-9$])")
PATH_SEP = " > "


def count_tokens(text: str) -> int:
    return len(TOKEN.findall(text))


def tail_tokens(text: str, n: int) -> str:
    """The last ``n`` tokens of ``text``, sliced from the original string."""
    spans = [m.start() for m in TOKEN.finditer(text)]
    if n <= 0:
        return ""
    if n >= len(spans):
        return text
    return text[spans[-n] :]


@dataclass(frozen=True)
class ChunkSettings:
    child_tokens: int = 500
    overlap: int = 50
    parent_max: int = 1500
    min_child_tokens: int = 3
    context_header: bool = True

    def __post_init__(self) -> None:
        if not 0 <= self.overlap < self.child_tokens:
            raise ValueError("overlap must be smaller than child_tokens")


@dataclass
class Section:
    path: tuple[str, ...]
    level: int
    blocks: list[Block] = field(default_factory=list)
    children: list[Section] = field(default_factory=list)

    def walk(self) -> Iterator[Section]:
        yield self
        for c in self.children:
            yield from c.walk()

    def tokens(self) -> int:
        own = sum(count_tokens(b.text) for b in self.blocks)
        heading = count_tokens(self.path[-1]) if self.path else 0
        return heading + own + sum(c.tokens() for c in self.children)


@dataclass(frozen=True)
class Unit:
    text: str
    tokens: int
    block: int  # index of the source block, to join sentences of one paragraph with spaces
    atomic: bool  # list items and tables are never cut
    table: bool = False


@dataclass(frozen=True)
class Child:
    path: tuple[str, ...]
    content: str
    tokens: int
    overlap_tokens: int  # how many leading tokens repeat the previous child's tail


@dataclass(frozen=True)
class Parent:
    path: tuple[str, ...]
    content: str
    children: list[Child]


# --- sections -------------------------------------------------------------------------


def build_sections(blocks: list[Block], doc_title: str) -> Section:
    """Nest blocks under their headings. An h1 that just repeats the document title is
    dropped from paths (its body stays at the root)."""
    root = Section(path=(), level=0)
    stack = [root]
    title = _fold(doc_title)
    for b in blocks:
        if b.kind == "heading":
            if b.level == 1 and (_fold(b.text) in title or title in _fold(b.text)):
                del stack[1:]
                continue
            while len(stack) > 1 and stack[-1].level >= b.level:
                stack.pop()
            sec = Section(path=(*stack[-1].path, b.text), level=b.level)
            stack[-1].children.append(sec)
            stack.append(sec)
        else:
            stack[-1].blocks.append(b)
    return root


def _fold(text: str) -> str:
    return text.casefold().replace("\u2019", "'").replace("\u2018", "'")


def choose_parents(sec: Section, parent_max: int) -> Iterator[Section]:
    """The largest sections of at most ``parent_max`` tokens. A section that is too big
    yields its own lead-in text as a parent and recurses into its subsections."""
    if sec.tokens() <= parent_max or not sec.children:
        yield sec
        return
    if sec.blocks:
        yield Section(path=sec.path, level=sec.level, blocks=sec.blocks)
    for c in sec.children:
        yield from choose_parents(c, parent_max)


def render_block(b: Block) -> str:
    return f"- {b.text}" if b.kind == "list_item" else b.text


def render_section(sec: Section) -> str:
    """Full parent text, headings as markdown, for the model."""
    out: list[str] = []
    top = len(sec.path)
    for s in sec.walk():
        if s.path:
            depth = max(len(s.path) - top + 2, 2)
            out.append(f"{'#' * min(depth, 6)} {s.path[-1]}")
        out.extend(render_block(b) for b in s.blocks)
    return "\n\n".join(out)


# --- units and packing --------------------------------------------------------------------


def split_sentences(text: str) -> list[str]:
    return [s.strip() for s in SENTENCE_END.split(text) if s.strip()]


def table_units(b: Block, index: int, limit: int) -> list[Unit]:
    whole = render_block(b)
    if count_tokens(whole) <= limit:
        return [Unit(whole, count_tokens(whole), index, atomic=True, table=True)]
    header = list(b.rows[: b.header_rows])
    budget = limit - count_tokens("\n".join(header))
    units: list[Unit] = []
    group: list[str] = []
    for row in b.rows[b.header_rows :]:
        if group and count_tokens("\n".join([*group, row])) > budget:
            text = "\n".join(header + group)
            units.append(Unit(text, count_tokens(text), index, atomic=True, table=True))
            group = []
        group.append(row)
    if group:
        text = "\n".join(header + group)
        units.append(Unit(text, count_tokens(text), index, atomic=True, table=True))
    return units


def to_units(blocks: list[Block], limit: int) -> list[Unit]:
    units: list[Unit] = []
    for i, b in enumerate(blocks):
        if b.kind == "table":
            units.extend(table_units(b, i, limit))
        elif b.kind == "list_item":
            text = render_block(b)
            units.append(Unit(text, count_tokens(text), i, atomic=True))
        else:
            for sentence in split_sentences(b.text):
                units.extend(_prose_units(sentence, i, limit))
    return units


def _prose_units(sentence: str, block: int, limit: int) -> list[Unit]:
    """A sentence longer than a whole child is cut into ``limit``-token windows."""
    starts = [m.start() for m in TOKEN.finditer(sentence)]
    if len(starts) <= limit:
        return [Unit(sentence, len(starts), block, atomic=False)]
    pieces = []
    for k in range(0, len(starts), limit):
        end = starts[k + limit] if k + limit < len(starts) else len(sentence)
        piece = sentence[starts[k] : end].strip()
        pieces.append(Unit(piece, count_tokens(piece), block, atomic=False))
    return pieces


def join_units(units: list[Unit]) -> str:
    out = ""
    for k, u in enumerate(units):
        if k == 0:
            out = u.text
        elif u.block == units[k - 1].block and not u.atomic:
            out += " " + u.text
        else:
            out += "\n" + u.text
    return out


def overlap_tail(units: list[Unit], overlap: int) -> list[Unit]:
    """Whole trailing units worth at most ``overlap`` tokens. When the last unit alone is
    longer, a prose sentence contributes its last ``overlap`` tokens; a list item or table
    is never cut, so it contributes nothing."""
    tail: list[Unit] = []
    total = 0
    for u in reversed(units):
        if u.table or total + u.tokens > overlap:
            break
        tail.insert(0, u)
        total += u.tokens
    if not tail and units and not units[-1].atomic and overlap > 0:
        last = units[-1]
        text = tail_tokens(last.text, overlap)
        tail = [Unit(text, count_tokens(text), last.block, atomic=False)]
    return tail


def pack(units: list[Unit], settings: ChunkSettings) -> list[tuple[list[Unit], int]]:
    """Greedy packing into children of at most ``child_tokens`` tokens. Returns each child's
    units and how many of its leading tokens are overlap."""
    children: list[tuple[list[Unit], int]] = []
    cur: list[Unit] = []
    cur_tokens = 0
    carried = 0
    for u in units:
        if cur and cur_tokens + u.tokens > settings.child_tokens:
            children.append((cur, carried))
            cur = overlap_tail(cur, settings.overlap)
            cur_tokens = sum(x.tokens for x in cur)
            if cur_tokens + u.tokens > settings.child_tokens:
                cur, cur_tokens = [], 0
            carried = cur_tokens
        cur.append(u)
        cur_tokens += u.tokens
    if cur:
        children.append((cur, carried))
    return children


def chunk_section(parent: Section, settings: ChunkSettings) -> Parent:
    children: list[Child] = []
    for sec in parent.walk():
        if not sec.blocks:
            continue
        for units, carried in pack(to_units(sec.blocks, settings.child_tokens), settings):
            content = join_units(units)
            tokens = count_tokens(content)
            if tokens - carried < settings.min_child_tokens:
                continue
            children.append(Child(sec.path, content, tokens, carried))
    return Parent(parent.path, render_section(parent), children)


def chunk_blocks(blocks: list[Block], doc_title: str, settings: ChunkSettings) -> list[Parent]:
    root = build_sections(blocks, doc_title)
    parents = [chunk_section(p, settings) for p in choose_parents(root, settings.parent_max)]
    return [p for p in parents if p.children]


# --- glossary and embedding text ------------------------------------------------------------


def glossary_content(entry: GlossaryEntry) -> str:
    name = f"{entry.term} ({', '.join(entry.aliases)})" if entry.aliases else entry.term
    return f"{name}: {entry.definition}"


def context_header(doc_title: str, path: tuple[str, ...]) -> str:
    return PATH_SEP.join((doc_title, *path))


def embed_text(content: str, doc_title: str, path: tuple[str, ...], *, header: bool) -> str:
    """What gets embedded (and reranked): 'document > section' then the chunk, when on."""
    return f"{context_header(doc_title, path)}\n\n{content}" if header else content
