"""What extraction produces and the chunker consumes: a flat run of typed blocks."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

BlockKind = Literal["heading", "paragraph", "list_item", "table"]


@dataclass(frozen=True)
class Block:
    kind: BlockKind
    text: str
    level: int = 0  # headings only: 1 (title) .. 6
    rows: tuple[str, ...] = ()  # tables only: rendered "a | b | c" rows
    header_rows: int = 0  # tables only: leading rows to repeat if a table must be split

    @staticmethod
    def table(rows: list[str], header_rows: int = 1) -> Block:
        return Block("table", "\n".join(rows), rows=tuple(rows), header_rows=header_rows)


@dataclass(frozen=True)
class GlossaryEntry:
    term: str
    definition: str
    aliases: tuple[str, ...] = ()
    url: str | None = None


@dataclass(frozen=True)
class Extracted:
    blocks: list[Block] = field(default_factory=list)
    glossary: list[GlossaryEntry] = field(default_factory=list)

    def plain_text(self) -> str:
        return "\n".join(b.text for b in self.blocks)
