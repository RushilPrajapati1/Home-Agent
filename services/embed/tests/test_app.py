from __future__ import annotations

from fastapi.testclient import TestClient
from homefund_embed.app import create_app
from homefund_embed.schemas import DENSE_DIM, MAX_TEXTS


def make_client(backend: object) -> TestClient:
    return TestClient(create_app(lambda: backend))  # type: ignore[arg-type, return-value]


def test_embed_dense_only(backend) -> None:
    with make_client(backend) as client:
        resp = client.post("/embed", json={"texts": ["what is pmi", "escrow"]})
    assert resp.status_code == 200
    body = resp.json()
    assert body["model"] == "fake/bge-m3"
    assert body["dim"] == DENSE_DIM
    assert len(body["dense"]) == 2
    assert all(len(v) == DENSE_DIM for v in body["dense"])
    assert body["sparse"] is None
    assert backend.encode_calls == [(["what is pmi", "escrow"], False)]


def test_embed_with_sparse_returns_sorted_token_weights(backend) -> None:
    with make_client(backend) as client:
        resp = client.post("/embed", json={"texts": ["closing costs explained"], "sparse": True})
    assert resp.status_code == 200
    (weights,) = resp.json()["sparse"]
    assert weights["indices"] == sorted(weights["indices"])
    assert len(weights["indices"]) == len(weights["values"])
    assert dict(zip(weights["indices"], weights["values"], strict=True))[5] == 0.5


def test_embed_rejects_empty_and_oversized_requests(backend) -> None:
    with make_client(backend) as client:
        assert client.post("/embed", json={"texts": []}).status_code == 422
        too_many = {"texts": ["x"] * (MAX_TEXTS + 1)}
        assert client.post("/embed", json=too_many).status_code == 422
        assert client.post("/embed", json={"texts": ["x"], "extra": 1}).status_code == 422


def test_rerank_returns_one_score_per_passage(backend) -> None:
    with make_client(backend) as client:
        resp = client.post(
            "/rerank",
            json={"query": "what is pmi", "passages": ["pmi is insurance", "escrow account"]},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["model"] == "fake/reranker"
    scores = body["scores"]
    assert len(scores) == 2
    assert scores[0] > scores[1]


def test_healthz_reports_device(backend) -> None:
    with make_client(backend) as client:
        body = client.get("/healthz").json()
    assert body == {
        "status": "ok",
        "device": "cpu",
        "fp16": False,
        "embed_model": "fake/bge-m3",
        "rerank_model": "fake/reranker",
    }


def test_backend_with_wrong_dimension_is_an_error(backend) -> None:
    from homefund_embed.backends import Encoded

    backend.encode = lambda texts, sparse: Encoded(dense=[[0.0] * 3], sparse=None)
    with TestClient(create_app(lambda: backend), raise_server_exceptions=False) as client:
        assert client.post("/embed", json={"texts": ["x"]}).status_code == 500
