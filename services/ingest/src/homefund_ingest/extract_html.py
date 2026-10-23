"""HTML pages (consumerfinance.gov, hud.gov) to blocks.

Walks the content root in document order. Headings become heading blocks; each CFPB
"expandable" panel becomes a heading one level below the heading it sits under; ``li`` and
table rows are kept whole; loose inline text is gathered into paragraphs.
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup, NavigableString, Tag

from homefund_ingest.model import Block, Extracted, GlossaryEntry
from homefund_ingest.sources import SourceDoc

HEADINGS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}
PARAGRAPHS = {"p", "blockquote", "dd", "dt", "figcaption", "address", "pre"}
LISTS = {"ul", "ol"}
BLOCKISH = (
    set(HEADINGS)
    | PARAGRAPHS
    | LISTS
    | {
        "div",
        "section",
        "article",
        "table",
        "li",
        "dl",
        "figure",
        "header",
        "footer",
        "aside",
        "details",
        "summary",
        "nav",
        "form",
        "main",
        "hr",
        "br",
    }
)
BLOCK_CHILDREN = ["div", "section", "ul", "ol", "table", "p", *HEADINGS]
ALWAYS_DROP = (
    "script, style, noscript, template, svg, img, picture, iframe, form, nav, input, select, "
    "textarea, link, meta, button:not(.o-expandable__header), .u-visually-hidden, .u-hide, "
    "[aria-hidden=true], .m-breadcrumbs, .breadcrumb, .o-expandable__cues, .u-hide-if-js, "
    ".u-screen-only, .m-social-media, .eyebrow, .answer-edited-date, .m-notification, "
    "p.text-align-center"
)
EXPANDABLE = "o-expandable"
EXPANDABLE_LABEL = ".o-expandable__label, .o-expandable__header"
EXPANDABLE_CONTENT = ".o-expandable__content"
WS = re.compile(r"\s+")
CTA = re.compile(
    r"(?:(?<=[.!?])\s+|^)(?:Learn|Read more|Find out|Understand more|See how|Get more)\b"
    r"[^.!?]*[.!?]?\s*\.?$"
)


SPACE_BEFORE_PUNCT = re.compile(r"\s+([.,;:!?])(?=\s|$)")


def clean(text: str) -> str:
    text = WS.sub(" ", text.replace("\xa0", " ")).strip()
    return SPACE_BEFORE_PUNCT.sub(r"\1", text)


def root_of(soup: BeautifulSoup, doc: SourceDoc) -> Tag:
    for sel in filter(None, [doc.selector, "main", "body"]):
        found = soup.select_one(sel)
        if isinstance(found, Tag):
            return found
    raise ValueError(f"{doc.id}: no content root")


class _Walker:
    def __init__(self) -> None:
        self.blocks: list[Block] = []
        self.inline: list[str] = []
        self.level = 1

    def flush(self) -> None:
        text = clean(" ".join(self.inline))
        self.inline = []
        if text:
            self.blocks.append(Block("paragraph", text))

    def heading(self, text: str, level: int, *, keep_level: bool = False) -> None:
        """``keep_level``: a pseudo-heading (a bold paragraph) sits under the current
        heading without becoming the parent of the next one."""
        self.flush()
        text = clean(text)
        if text:
            self.blocks.append(Block("heading", text, level=level))
            if not keep_level:
                self.level = level

    def walk(self, node: Tag) -> None:
        for child in node.children:
            if isinstance(child, NavigableString):
                if type(child) is NavigableString:  # skip comments, CDATA, doctype
                    self.inline.append(str(child))
                continue
            if not isinstance(child, Tag):
                continue
            name = child.name
            classes = child.get_attribute_list("class")
            if name in HEADINGS:
                self.heading(child.get_text(" "), HEADINGS[name])
            elif EXPANDABLE in classes:
                self.expandable(child)
            elif name == "table":
                self.flush()
                self.table(child)
            elif name == "li":
                self.flush()
                self.list_item(child)
            elif name in PARAGRAPHS and not child.find(BLOCK_CHILDREN):
                self.flush()
                text = clean(child.get_text(" "))
                if text and name == "p" and is_link_only(child, text):
                    pass  # "Learn more about escrow": navigation, not content
                elif text and name == "p" and is_bold_line(child, text):
                    self.heading(text, min(self.level + 1, 6), keep_level=True)
                elif text:
                    self.blocks.append(Block("paragraph", text))
            elif name in BLOCKISH:
                self.flush()
                self.walk(child)
                self.flush()
            else:  # inline: a, span, strong, em, ...
                self.inline.append(child.get_text(" "))

    def expandable(self, node: Tag) -> None:
        label = node.select_one(EXPANDABLE_LABEL)
        content = node.select_one(EXPANDABLE_CONTENT)
        outer = self.level
        if label is not None:
            self.heading(label.get_text(" "), min(outer + 1, 6))
        self.walk(content if content is not None else node)
        self.flush()
        self.level = outer

    def list_item(self, node: Tag) -> None:
        nested = [c for c in node.find_all(LISTS, recursive=False)]
        for n in nested:
            n.extract()
        text = clean(node.get_text(" "))
        if text:
            self.blocks.append(Block("list_item", text))
        for n in nested:
            self.walk(n)

    def table(self, node: Tag) -> None:
        rows: list[str] = []
        header_rows = 0
        for tr in node.find_all("tr"):
            tags = tr.find_all(["th", "td"])
            cells = [clean(c.get_text(" ")) for c in tags]
            if not any(cells):
                continue
            # Leading all-<th> rows are the header, repeated if the table has to be split.
            if header_rows == len(rows) and all(t.name == "th" for t in tags):
                header_rows += 1
            rows.append(" | ".join(cells))
        caption = node.find("caption")
        if caption is not None and clean(caption.get_text(" ")):
            self.blocks.append(Block("paragraph", clean(caption.get_text(" "))))
        if rows:
            self.blocks.append(Block.table(rows, header_rows=max(header_rows, 1)))


def is_link_only(p: Tag, text: str) -> bool:
    links = " ".join(a.get_text(" ") for a in p.find_all("a"))
    return len(text.split()) <= 15 and clean(links) == text


def strip_trailing_links(text: str, node: Tag) -> str:
    """Drop a closing call-to-action sentence ("Read more", "Learn how to calculate your
    debt-to-income ratio.") when it carries a link: navigation, not definition."""
    m = CTA.search(text)
    if m is None:
        return text
    sentence = m.group(0)
    if any(clean(a.get_text(" ")) in sentence for a in node.find_all("a")):
        return text[: m.start()].rstrip()
    return text


def is_bold_line(p: Tag, text: str) -> bool:
    """A short paragraph whose text is all inside <strong>/<b>/<u>: a heading in disguise
    (hud.gov writes its subheads this way)."""
    if len(text.split()) > 12 or text.endswith((".", ":", ";", ",")):
        return False
    bold = " ".join(e.get_text(" ") for e in p.find_all(["strong", "b", "u"]))
    return clean(bold) == text


def drop_sections(blocks: list[Block], titles: list[str]) -> list[Block]:
    """Remove each heading in ``titles`` and everything under it, up to the next heading at
    the same or a higher level."""
    wanted = {clean(t).casefold() for t in titles}
    out: list[Block] = []
    dropping_at: int | None = None
    for b in blocks:
        if b.kind == "heading":
            if dropping_at is not None and b.level <= dropping_at:
                dropping_at = None
            if dropping_at is None and b.text.casefold() in wanted:
                dropping_at = b.level
        if dropping_at is None:
            out.append(b)
    return out


def glossary_terms(root: Tag, doc: SourceDoc) -> list[GlossaryEntry]:
    """CFPB glossary markup: ``dl.terms > div.term`` with ``dt`` name and ``dd`` definition."""
    entries = []
    aliases = {k.casefold(): v for k, v in doc.aliases.items()}
    for term in root.select("div.term"):
        dt, dd = term.find("dt"), term.find("dd")
        if dt is None or dd is None:
            continue
        name = clean(dt.get_text(" "))
        for para in dd.find_all("p"):
            if is_link_only(para, clean(para.get_text(" "))):
                para.decompose()  # "Learn more about ..." links
        definition = strip_trailing_links(clean(dd.get_text(" ")), dd)
        anchor = term.get("id")
        url = f"{doc.url}#{anchor}" if isinstance(anchor, str) else doc.url
        entries.append(
            GlossaryEntry(
                term=name,
                definition=definition,
                aliases=tuple(aliases.get(name.casefold(), ())),
                url=url,
            )
        )
    return entries


def extract_html(raw: bytes, doc: SourceDoc, drop_titles: list[str]) -> Extracted:
    soup = BeautifulSoup(raw, "lxml")
    root = root_of(soup, doc)
    for sel in [ALWAYS_DROP, *doc.drop]:
        for el in root.select(sel):
            el.decompose()
    if doc.kind == "glossary":
        entries = glossary_terms(root, doc)
        if entries:
            return Extracted(glossary=entries)
    walker = _Walker()
    walker.walk(root)
    walker.flush()
    return Extracted(blocks=drop_sections(walker.blocks, drop_titles))
