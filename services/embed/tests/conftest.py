from __future__ import annotations

import hashlib
from collections.abc import Sequence

import pytest
from homefund_embed.backends import Encoded
from homefund_embed.schemas import DENSE_DIM


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "slow: loads the real models; runs only with HOMEFUND_SLOW=1 (make embed-test-slow)",
    )


class FakeBackend:
    """Deterministic stand-in for FlagBackend: a vector and weights derived from the text."""

    embed_model = "fake/bge-m3"
    rerank_model = "fake/reranker"
    device = "cpu"
    fp16 = False

    def __init__(self) -> None:
        self.encode_calls: list[tuple[list[str], bool]] = []

    def encode(self, texts: Sequence[str], *, sparse: bool) -> Encoded:
        self.encode_calls.append((list(texts), sparse))
        dense = []
        weights = []
        for t in texts:
            h = hashlib.sha256(t.encode()).digest()
            v = [0.0] * DENSE_DIM
            v[h[0] % DENSE_DIM] = 1.0
            dense.append(v)
            weights.append({len(w): 0.1 * len(w) for w in t.split()})
        return Encoded(dense=dense, sparse=weights if sparse else None)

    def rerank(self, query: str, passages: Sequence[str]) -> list[float]:
        q = set(query.lower().split())
        return [len(q & set(p.lower().split())) / (len(q) or 1) for p in passages]


@pytest.fixture
def backend() -> FakeBackend:
    return FakeBackend()
