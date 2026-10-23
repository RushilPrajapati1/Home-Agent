from __future__ import annotations

import asyncio

import httpx
import pytest
from homefund_embed.app import create_app
from homefund_embed.client import EmbedClient


def make_client(backend: object, batch_size: int = 64) -> EmbedClient:
    app = create_app(lambda: backend)  # type: ignore[arg-type, return-value]
    app.state.backend = backend  # ASGITransport does not run the lifespan
    return EmbedClient(
        "http://embed", batch_size=batch_size, transport=httpx.ASGITransport(app=app)
    )


def test_embed_splits_into_batches_and_keeps_order(backend) -> None:
    texts = [f"text number {i}" for i in range(7)]

    async def run() -> None:
        async with make_client(backend, batch_size=3) as client:
            out = await client.embed(texts, sparse=True)
        assert out.model == "fake/bge-m3"
        assert len(out.dense) == 7
        assert out.sparse is not None and len(out.sparse) == 7

    asyncio.run(run())
    assert [len(batch) for batch, _ in backend.encode_calls] == [3, 3, 1]
    assert [t for batch, _ in backend.encode_calls for t in batch] == texts


def test_embed_dense_only(backend) -> None:
    async def run() -> None:
        async with make_client(backend) as client:
            out = await client.embed(["a"], sparse=False)
        assert out.sparse is None

    asyncio.run(run())


def test_rerank(backend) -> None:
    async def run() -> list[float]:
        async with make_client(backend, batch_size=2) as client:
            return await client.rerank("what is pmi", ["pmi", "escrow", "what is it"])

    scores = asyncio.run(run())
    assert len(scores) == 3
    assert scores[1] == 0.0


def test_http_errors_raise() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(503))

    async def run() -> None:
        async with EmbedClient("http://embed", transport=transport) as client:
            await client.embed(["x"])

    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(run())


def test_batch_size_is_bounded() -> None:
    with pytest.raises(ValueError):
        EmbedClient("http://embed", batch_size=0)


def test_health(backend) -> None:
    async def run():
        async with make_client(backend) as client:
            return await client.health()

    assert asyncio.run(run()).embed_model == "fake/bge-m3"
