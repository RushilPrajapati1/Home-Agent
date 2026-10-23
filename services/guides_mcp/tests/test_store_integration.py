"""PgGuideStore against the local Postgres after `make ingest` (make test-integration)."""

from __future__ import annotations

import os

import pytest
from homefund_guides_mcp.chunks import Filters

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def pg():
    if not os.environ.get("DATABASE_URL_MCP"):
        pytest.skip("DATABASE_URL_MCP is not set")
    from homefund_guides_mcp.store import PgGuideStore

    store = PgGuideStore.from_env()
    if not store.glossary():
        pytest.skip("guide_chunks is empty; run `make ingest`")
    return store


def test_pg_store_searches_and_filters(pg, corpus) -> None:
    q = corpus["queries"]["What is PMI?"]
    dense = pg.dense_search(q["dense"], 10, Filters())
    assert len(dense) == 10
    sparse = pg.sparse_search(
        dict(zip(q["sparse"]["indices"], q["sparse"]["values"], strict=True)), 10, Filters()
    )
    assert sparse and any(c.metadata.get("term") == "PMI" for c in dense + sparse)
    hud = pg.dense_search(q["dense"], 5, Filters(sources=frozenset({"hud"})))
    assert hud and {c.metadata["source"] for c in hud} == {"hud"}
    old = pg.dense_search(q["dense"], 300, Filters(tax_year=2025))
    assert not any(c.metadata.get("tax_year") == 2026 for c in old)


def test_pg_store_get_and_glossary(pg) -> None:
    gl = pg.glossary()
    assert len(gl) >= 107
    pmi = next(c for c in gl if c.metadata["term"] == "PMI")
    assert pg.get([pmi.id])[pmi.id].content.startswith("PMI")


def test_mcp_role_is_read_only(pg) -> None:
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError

    with pytest.raises(DBAPIError), pg._engine.begin() as conn:
        conn.execute(text("DELETE FROM guide_chunks"))
