"""define_term lookup: exact on the normalised term and its aliases, then fuzzy."""

from __future__ import annotations

import difflib
import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from homefund_guides_mcp.chunks import Chunk

QUESTION = re.compile(r"^(?:what(?:'s| is| are| does)?|define|definition of|meaning of|explain)\s+")
ARTICLE = re.compile(r"^(?:an?|the)\s+")
TRAILER = re.compile(r"\s+(?:mean|means|stand for)$")
NON_WORD = re.compile(r"[^\w%$]+")
PAREN = re.compile(r"^(.*?)\s*\(([^)]+)\)\s*$")
FUZZY_CUTOFF = 0.85
FUZZY_MIN_LEN = 4  # "pmi" vs "mip" must never fuzzy-match


def normalize(term: str) -> str:
    t = term.casefold().strip().rstrip("?.!").strip()
    t = QUESTION.sub("", t)
    t = ARTICLE.sub("", t)
    t = TRAILER.sub("", t)
    return " ".join(NON_WORD.sub(" ", t).split())


def names(chunk: Chunk) -> list[str]:
    """The term, its aliases, and both halves of 'Long name (ABBR)'."""
    term = str(chunk.metadata.get("term", ""))
    out = [term, *chunk.metadata.get("aliases", [])]
    m = PAREN.match(term)
    if m:
        out += [m.group(1), m.group(2)]
    return out


@dataclass(frozen=True)
class Match:
    chunk: Chunk
    how: Literal["exact", "fuzzy"]


class Glossary:
    def __init__(self, entries: Iterable[Chunk]) -> None:
        self._index: dict[str, Chunk] = {}
        for chunk in sorted(entries, key=lambda c: str(c.metadata.get("term", ""))):
            for name in names(chunk):
                key = normalize(name)
                # The entry's own term wins over another entry's alias.
                if key and (key not in self._index or name == chunk.metadata.get("term")):
                    self._index[key] = chunk

    def __len__(self) -> int:
        return len({c.id for c in self._index.values()})

    def lookup(self, term: str, *, fuzzy: bool = True) -> Match | None:
        key = normalize(term)
        if not key:
            return None
        if key in self._index:
            return Match(self._index[key], "exact")
        if key.endswith("s") and key[:-1] in self._index:
            return Match(self._index[key[:-1]], "exact")
        if fuzzy and len(key) >= FUZZY_MIN_LEN:
            keys = [k for k in self._index if len(k) >= FUZZY_MIN_LEN]
            close = difflib.get_close_matches(key, keys, n=1, cutoff=FUZZY_CUTOFF)
            if close:
                return Match(self._index[close[0]], "fuzzy")
        return None


def definition_of(chunk: Chunk) -> str:
    """Glossary content is 'Term (aliases): definition'; return the definition."""
    term = str(chunk.metadata.get("term", ""))
    aliases = chunk.metadata.get("aliases") or []
    prefix = f"{term} ({', '.join(aliases)}): " if aliases else f"{term}: "
    return chunk.content.removeprefix(prefix)
