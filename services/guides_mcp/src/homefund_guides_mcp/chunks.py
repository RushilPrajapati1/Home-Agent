"""A guide_chunks row as the retriever sees it, and how it becomes a Citation."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from homefund_contracts.domain import Citation
from homefund_contracts.enums import GuideSource

PATH_SEP = " > "
QUOTE_CHARS = 280


@dataclass(frozen=True)
class Filters:
    """Optional source and tax-year filters. A chunk with no tax_year is not year-specific
    and always passes the tax-year filter."""

    sources: frozenset[str] | None = None
    tax_year: int | None = None

    def matches(self, metadata: dict[str, Any]) -> bool:
        if self.sources is not None and metadata.get("source") not in self.sources:
            return False
        year = metadata.get("tax_year")
        return self.tax_year is None or year is None or int(year) == self.tax_year


@dataclass(frozen=True)
class Chunk:
    id: uuid.UUID
    parent_id: uuid.UUID | None
    content: str
    metadata: dict[str, Any]

    @property
    def path(self) -> tuple[str, ...]:
        return tuple(self.metadata.get("section_path") or ())

    @property
    def doc_title(self) -> str:
        return str(self.metadata.get("doc_title", ""))

    @property
    def is_glossary(self) -> bool:
        return self.metadata.get("role") == "glossary"

    @property
    def section(self) -> str:
        return PATH_SEP.join(self.path) or "Overview"

    @property
    def title(self) -> str:
        return self.path[-1] if self.path else self.doc_title

    @property
    def rerank_text(self) -> str:
        """The text the chunk was embedded as: 'document > section' first when ingest had
        CONTEXT_HEADER on (homefund_ingest.chunker.embed_text)."""
        if self.metadata.get("context_header"):
            return f"{PATH_SEP.join((self.doc_title, *self.path))}\n\n{self.content}"
        return self.content

    def citation(self, *, quote: bool = True) -> Citation:
        tax_year = self.metadata.get("tax_year")
        return Citation(
            chunk_id=self.id,
            source=GuideSource(self.metadata["source"]),
            document=self.doc_title,
            section=self.section,
            url=self.metadata.get("url"),
            tax_year=int(tax_year) if tax_year is not None else None,
            quote=excerpt(self.content) if quote else None,
        )


def excerpt(text: str, limit: int = QUOTE_CHARS) -> str:
    flat = " ".join(text.split())
    if len(flat) <= limit:
        return flat
    cut = flat[:limit].rsplit(" ", 1)[0]
    return f"{cut}…"
