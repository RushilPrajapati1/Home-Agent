"""Model backends. The server talks to these protocols; tests swap in fakes.

``FlagBackend`` is the real one: BGE-M3 through ``BGEM3FlagModel`` and bge-reranker-v2-m3
through ``FlagReranker``. FlagEmbedding and torch are imported lazily so the module (and
the server with fake backends) imports without the ``model`` extra.
"""

from __future__ import annotations

import logging
import os
import threading
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Encoded:
    dense: list[list[float]]
    sparse: list[dict[int, float]] | None


class Backend(Protocol):
    embed_model: str
    rerank_model: str
    device: str
    fp16: bool

    def encode(self, texts: Sequence[str], *, sparse: bool) -> Encoded: ...

    def rerank(self, query: str, passages: Sequence[str]) -> list[float]: ...


@dataclass(frozen=True)
class DeviceChoice:
    device: str
    fp16: bool


def choose_device(requested: str = "auto", fp16: str = "auto") -> DeviceChoice:
    """``auto`` picks CUDA when present, else CPU. fp16 defaults to on for CUDA only.

    MPS is opt-in (``EMBED_DEVICE=mps``): it works for BGE-M3 but is slower than CUDA and
    some torch builds still miss ops, so CPU is the safe fallback.
    """
    device = requested.strip().lower() or "auto"
    if device == "auto":
        try:
            import torch

            device = "cuda:0" if torch.cuda.is_available() else "cpu"
        except ImportError:
            device = "cpu"
    if device == "cuda":
        device = "cuda:0"
    flag = fp16.strip().lower() or "auto"
    use_fp16 = device.startswith("cuda") if flag == "auto" else flag in {"1", "true", "on", "yes"}
    return DeviceChoice(device=device, fp16=use_fp16)


class FlagBackend:
    """BGE-M3 + bge-reranker-v2-m3 via FlagEmbedding. One lock per model: torch modules
    are not safe to call from several threads at once, and FastAPI runs sync endpoints in
    a threadpool."""

    def __init__(
        self,
        embed_model: str,
        rerank_model: str,
        *,
        device: DeviceChoice,
        batch_size: int = 32,
        max_length: int = 1024,
        cache_dir: str | None = None,
    ) -> None:
        from FlagEmbedding import BGEM3FlagModel, FlagReranker

        self.embed_model = embed_model
        self.rerank_model = rerank_model
        self.device = device.device
        self.fp16 = device.fp16
        self._batch_size = batch_size
        self._max_length = max_length
        log.info(
            "loading %s and %s on %s (fp16=%s)",
            embed_model,
            rerank_model,
            device.device,
            device.fp16,
        )
        self._embedder: Any = BGEM3FlagModel(
            embed_model, use_fp16=device.fp16, devices=device.device, cache_dir=cache_dir
        )
        self._reranker: Any = FlagReranker(
            rerank_model, use_fp16=device.fp16, devices=device.device, cache_dir=cache_dir
        )
        self._embed_lock = threading.Lock()
        self._rerank_lock = threading.Lock()

    def encode(self, texts: Sequence[str], *, sparse: bool) -> Encoded:
        with self._embed_lock:
            out = self._embedder.encode(
                list(texts),
                batch_size=self._batch_size,
                max_length=self._max_length,
                return_dense=True,
                return_sparse=sparse,
                return_colbert_vecs=False,
            )
        dense = [[float(x) for x in row] for row in out["dense_vecs"]]
        lexical = None
        if sparse:
            # FlagEmbedding keys lexical weights by token id as a string.
            lexical = [{int(k): float(v) for k, v in w.items()} for w in out["lexical_weights"]]
        return Encoded(dense=dense, sparse=lexical)

    def rerank(self, query: str, passages: Sequence[str]) -> list[float]:
        pairs = [(query, p) for p in passages]
        with self._rerank_lock:
            scores = self._reranker.compute_score(
                pairs, normalize=True, batch_size=self._batch_size, max_length=self._max_length
            )
        # compute_score returns a bare float for a single pair.
        if isinstance(scores, int | float):
            return [float(scores)]
        return [float(s) for s in scores]


def backend_from_env() -> FlagBackend:
    return FlagBackend(
        os.environ.get("EMBED_MODEL", "BAAI/bge-m3"),
        os.environ.get("RERANK_MODEL", "BAAI/bge-reranker-v2-m3"),
        device=choose_device(
            os.environ.get("EMBED_DEVICE", "auto"), os.environ.get("EMBED_FP16", "auto")
        ),
        batch_size=int(os.environ.get("EMBED_BATCH_SIZE", "32")),
        max_length=int(os.environ.get("EMBED_MAX_LENGTH", "1024")),
        cache_dir=os.environ.get("EMBED_CACHE_DIR") or None,
    )
