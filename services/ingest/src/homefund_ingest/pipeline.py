"""Raw file -> blocks -> chunks -> rows. Pure: no network, no database."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from homefund_ingest.chunker import (
    ChunkSettings,
    chunk_blocks,
    embed_text,
    glossary_content,
)
from homefund_ingest.extract_html import extract_html
from homefund_ingest.extract_pdf import extract_pdf
from homefund_ingest.fetch import verify
from homefund_ingest.model import Extracted, GlossaryEntry
from homefund_ingest.sources import SourceDoc

# Fixed namespace: the same content always gets the same row id, so re-runs are no-ops.
NAMESPACE = uuid.UUID("5d0c2a4e-3c1b-4f7e-9a51-6b8e2f0c7d13")
WS = re.compile(r"\s+")


@dataclass(frozen=True)
class Row:
    id: uuid.UUID
    parent_id: uuid.UUID | None
    content: str
    embed_text: str | None  # None for parents: they are not searched, only handed over
    metadata: dict[str, Any]


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def row_hash(*parts: object) -> str:
    """Hash of everything a row stores, so a changed title, url or tax year gets a new id
    (and a fresh row) instead of leaving stale metadata behind."""
    return sha256(json.dumps(parts, sort_keys=True, ensure_ascii=False))


def extract(doc: SourceDoc, data_dir: Path, drop_titles: list[str]) -> Extracted:
    raw = verify(doc, data_dir).read_bytes()
    extracted = extract_html(raw, doc, drop_titles) if doc.format == "html" else extract_pdf(raw)
    if doc.terms:
        return Extracted(blocks=[], glossary=extracted.glossary + term_spans(doc, extracted))
    return extracted


def term_spans(doc: SourceDoc, extracted: Extracted) -> list[GlossaryEntry]:
    """Cut each ``terms`` entry out of the document text, ``start`` through ``end``."""
    text = WS.sub(" ", "\n".join(_line(b.kind, b.text) for b in extracted.blocks))
    entries = []
    for t in doc.terms:
        i = text.find(t.start)
        j = text.find(t.end, i) if i >= 0 else -1
        if i < 0 or j < 0:
            raise ValueError(f"{doc.id}: could not find the span for glossary term {t.term!r}")
        entries.append(
            GlossaryEntry(
                term=t.term,
                definition=text[i : j + len(t.end)].strip(),
                aliases=tuple(t.aliases),
                url=doc.url,
            )
        )
    return entries


def _line(kind: str, text: str) -> str:
    return f"- {text}" if kind == "list_item" else text


class _Ids:
    """uuid5 over (doc, role, content hash); a repeat of identical content gets a suffix."""

    def __init__(self, doc_id: str) -> None:
        self.doc_id = doc_id
        self.seen: dict[str, int] = {}

    def __call__(self, role: str, digest: str) -> uuid.UUID:
        key = f"{self.doc_id}|{role}|{digest}"
        n = self.seen.get(key, 0)
        self.seen[key] = n + 1
        return uuid.uuid5(NAMESPACE, key if n == 0 else f"{key}|{n}")


def build_rows(
    doc: SourceDoc, extracted: Extracted, settings: ChunkSettings, embed_model: str
) -> list[Row]:
    """Parents first, then their children, then glossary entries. Each content hash covers
    the row's content, metadata, embedding text and the embedding model: toggling
    CONTEXT_HEADER, changing the model or editing a source's metadata re-embeds; re-running
    on unchanged sources does nothing."""
    ids = _Ids(doc.id)
    base = {
        "source": doc.source.value,
        "kind": doc.kind,
        "publisher": doc.publisher,
        "doc_id": doc.id,
        "doc_title": doc.title,
        "url": doc.url,
        "tax_year": doc.tax_year,
    }
    rows: list[Row] = []
    for parent in chunk_blocks(extracted.blocks, doc.title, settings):
        p_meta = {**base, "role": "parent", "section_path": list(parent.path)}
        p_hash = row_hash(parent.content, p_meta)
        p_id = ids("parent", p_hash)
        rows.append(
            Row(
                id=p_id,
                parent_id=None,
                content=parent.content,
                embed_text=None,
                metadata={**p_meta, "content_hash": p_hash},
            )
        )
        for n, child in enumerate(parent.children):
            text = embed_text(child.content, doc.title, child.path, header=settings.context_header)
            c_meta = {
                **base,
                "role": "child",
                "section_path": list(child.path),
                "chunk_index": n,
                "tokens": child.tokens,
                "overlap_tokens": child.overlap_tokens,
                "context_header": settings.context_header,
            }
            c_hash = row_hash(embed_model, text, child.content, c_meta)
            rows.append(
                Row(
                    id=ids("child", f"{p_id}|{c_hash}"),
                    parent_id=p_id,
                    content=child.content,
                    embed_text=text,
                    metadata={**c_meta, "content_hash": c_hash},
                )
            )
    for entry in extracted.glossary:
        content = glossary_content(entry)
        text = embed_text(content, doc.title, (entry.term,), header=settings.context_header)
        g_meta = {
            **base,
            "kind": "glossary",
            "source": "glossary",
            "role": "glossary",
            "section_path": [entry.term],
            "term": entry.term,
            "aliases": list(entry.aliases),
            "url": entry.url or doc.url,
            "context_header": settings.context_header,
        }
        g_hash = row_hash(embed_model, text, content, g_meta)
        rows.append(
            Row(
                id=ids("glossary", g_hash),
                parent_id=None,
                content=content,
                embed_text=text,
                metadata={**g_meta, "content_hash": g_hash},
            )
        )
    return rows
