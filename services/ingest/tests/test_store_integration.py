"""store.py against the local Postgres as app_rw (make test-integration). Uses its own
document id and removes it afterwards."""

from __future__ import annotations

import os

import pytest
from homefund_embed.schemas import SparseWeights
from homefund_ingest import store
from homefund_ingest.chunker import ChunkSettings
from homefund_ingest.model import Block, Extracted
from homefund_ingest.pipeline import build_rows
from homefund_ingest.sources import SourceDoc

pytestmark = pytest.mark.integration
DOC = SourceDoc(
    id="zz-integration-test", source="cfpb", kind="guide", publisher="cfpb",
    title="Integration test", url="https://www.consumerfinance.gov/x",
)  # fmt: skip


@pytest.fixture
def engine():
    if not os.environ.get("DATABASE_URL_APP"):
        pytest.skip("DATABASE_URL_APP is not set")
    from homefund_db.config import APP_URL_VAR, make_engine

    eng = make_engine(APP_URL_VAR)
    yield eng
    with eng.begin() as conn:
        store.delete_stale(conn, DOC.id, set())


def write(engine, text: str) -> tuple[int, int]:
    blocks = [Block("heading", "Section", level=2), Block("paragraph", text)]
    rows = build_rows(DOC, Extracted(blocks=blocks), ChunkSettings(), "test-model")
    with engine.begin() as conn:
        have = store.existing_ids(conn, DOC.id)
        new = [r for r in rows if r.id not in have]
        vectors = {
            r.id: store.Embedded([0.0] * 1023 + [1.0], SparseWeights(indices=[5], values=[0.5]))
            for r in new
            if r.embed_text
        }
        store.insert_rows(conn, new, vectors)
        deleted = store.delete_stale(conn, DOC.id, {r.id for r in rows})
    return len(new), deleted


def test_write_is_idempotent_and_prunes(engine) -> None:
    assert write(engine, "First version of the section.") == (2, 0)
    assert write(engine, "First version of the section.") == (0, 0)
    assert write(engine, "Second version of the section.") == (2, 2)
    with engine.begin() as conn:
        assert len(store.existing_ids(conn, DOC.id)) == 2
