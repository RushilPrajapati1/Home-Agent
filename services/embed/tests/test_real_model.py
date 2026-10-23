"""One end-to-end check against the real BGE-M3 and reranker weights.

Skipped unless HOMEFUND_SLOW=1 (``make embed-test-slow``): it needs the ``model`` extra and
the weights in the Hugging Face cache (``make embed-models`` or a first run with egress).
"""

from __future__ import annotations

import math
import os

import pytest

pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(os.environ.get("HOMEFUND_SLOW") != "1", reason="set HOMEFUND_SLOW=1"),
]


@pytest.fixture(scope="module")
def client():
    pytest.importorskip("FlagEmbedding")
    from fastapi.testclient import TestClient
    from homefund_embed.app import create_app
    from homefund_embed.backends import backend_from_env

    with TestClient(create_app(backend_from_env)) as c:
        yield c


def test_real_embed_and_rerank(client) -> None:
    texts = [
        "PMI: Private mortgage insurance protects the lender on a conventional loan.",
        "Escrow: an account your lender uses to pay property taxes and insurance.",
    ]
    out = client.post("/embed", json={"texts": texts, "sparse": True}).json()
    assert len(out["dense"]) == 2 and len(out["dense"][0]) == 1024
    assert math.isclose(math.fsum(x * x for x in out["dense"][0]), 1.0, rel_tol=1e-3)
    assert all(0 <= i < 250_002 for w in out["sparse"] for i in w["indices"])

    q = client.post("/embed", json={"texts": ["What is PMI?"]}).json()["dense"][0]
    sims = [math.fsum(a * b for a, b in zip(q, d, strict=True)) for d in out["dense"]]
    assert sims[0] > sims[1]

    scores = client.post("/rerank", json={"query": "What is PMI?", "passages": texts}).json()
    assert scores["scores"][0] > 0.5 > scores["scores"][1]
