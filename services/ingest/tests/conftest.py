from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from homefund_ingest.chunker import ChunkSettings
from homefund_ingest.model import Extracted
from homefund_ingest.pipeline import Row, build_rows, extract
from homefund_ingest.sources import DEFAULT_SOURCES, SourceDoc, load_sources

REPO = Path(__file__).resolve().parents[3]
PAGES = REPO / "fixtures" / "guides-rag" / "pages"


@pytest.fixture(scope="session")
def sources():
    return load_sources(DEFAULT_SOURCES)


@pytest.fixture(scope="session")
def docs(sources) -> dict[str, SourceDoc]:
    # The saved pages are frozen copies; skip the sha256 check against sources.yaml.
    return {d.id: d.model_copy(update={"sha256": None}) for d in sources.documents}


@pytest.fixture(scope="session")
def extracted(sources, docs):
    cache: dict[str, Extracted] = {}

    def get(doc_id: str) -> Extracted:
        if doc_id not in cache:
            cache[doc_id] = extract(docs[doc_id], PAGES, sources.drop_sections)
        return cache[doc_id]

    return get


@pytest.fixture(scope="session")
def rows(docs, extracted):
    def get(doc_id: str, **settings: Any) -> list[Row]:
        return build_rows(docs[doc_id], extracted(doc_id), ChunkSettings(**settings), "m")

    return get
