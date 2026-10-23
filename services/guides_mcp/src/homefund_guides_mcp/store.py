"""Where chunks come from: pgvector as mcp_ro in the service, a JSON corpus in tests."""

from __future__ import annotations

import json
import math
import uuid
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any, Protocol

from pgvector import SparseVector, Vector
from sqlalchemy import Engine, create_engine, text

from homefund_db.config import MCP_URL_VAR, database_url
from homefund_db.models import SPARSE_DIM
from homefund_guides_mcp.chunks import Chunk, Filters

COLUMNS = "id, parent_id, content, metadata"
# The f-string SQL below only splices COLUMNS and fixed filter fragments from _where();
# every value is a bound parameter.


class GuideStore(Protocol):
    def dense_search(self, vector: Sequence[float], n: int, filters: Filters) -> list[Chunk]: ...

    def sparse_search(self, weights: dict[int, float], n: int, filters: Filters) -> list[Chunk]: ...

    def get(self, ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, Chunk]: ...

    def glossary(self) -> list[Chunk]: ...


def _chunk(row: Any) -> Chunk:
    return Chunk(id=row.id, parent_id=row.parent_id, content=row.content, metadata=row.metadata)


class PgGuideStore:
    """Read-only: the connection sets default_transaction_read_only on top of mcp_ro's
    SELECT-only grants."""

    def __init__(self, engine: Engine, *, ef_search: int = 200) -> None:
        self._engine = engine
        self._ef_search = ef_search

    @classmethod
    def from_env(cls) -> PgGuideStore:
        engine = create_engine(
            database_url(MCP_URL_VAR),
            pool_pre_ping=True,
            connect_args={"options": "-c default_transaction_read_only=on"},
        )
        return cls(engine)

    @staticmethod
    def _where(filters: Filters, params: dict[str, Any]) -> str:
        sql = ""
        if filters.sources is not None:
            sql += " AND metadata->>'source' = ANY(:sources)"
            params["sources"] = sorted(filters.sources)
        if filters.tax_year is not None:
            sql += " AND (metadata->>'tax_year' IS NULL OR (metadata->>'tax_year')::int = :ty)"
            params["ty"] = filters.tax_year
        return sql

    def dense_search(self, vector: Sequence[float], n: int, filters: Filters) -> list[Chunk]:
        params: dict[str, Any] = {"q": Vector(list(vector)).to_text(), "n": n}
        where = self._where(filters, params)
        with self._engine.begin() as conn:
            # HNSW with a filter: widen the candidate list and let pgvector 0.8 keep
            # scanning until n rows pass the filter.
            conn.execute(text(f"SET LOCAL hnsw.ef_search = {int(self._ef_search)}"))
            conn.execute(text("SET LOCAL hnsw.iterative_scan = relaxed_order"))
            rows = conn.execute(
                text(
                    f"SELECT {COLUMNS} FROM guide_chunks WHERE dense IS NOT NULL{where} "  # noqa: S608
                    "ORDER BY dense <=> CAST(:q AS vector) LIMIT :n"
                ),
                params,
            )
            return [_chunk(r) for r in rows]

    def sparse_search(self, weights: dict[int, float], n: int, filters: Filters) -> list[Chunk]:
        if not weights:
            return []
        params: dict[str, Any] = {"q": SparseVector(weights, SPARSE_DIM).to_text(), "n": n}
        where = self._where(filters, params)
        with self._engine.begin() as conn:
            # <#> is the negative inner product: ascending order is best match first.
            rows = conn.execute(
                text(
                    f"SELECT {COLUMNS} FROM guide_chunks WHERE sparse IS NOT NULL{where} "  # noqa: S608
                    "ORDER BY sparse <#> CAST(:q AS sparsevec) LIMIT :n"
                ),
                params,
            )
            return [_chunk(r) for r in rows]

    def get(self, ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, Chunk]:
        wanted = [str(i) for i in set(ids)]
        if not wanted:
            return {}
        with self._engine.begin() as conn:
            rows = conn.execute(
                text(f"SELECT {COLUMNS} FROM guide_chunks WHERE id = ANY(CAST(:ids AS uuid[]))"),  # noqa: S608
                {"ids": wanted},
            )
            return {r.id: _chunk(r) for r in rows}

    def glossary(self) -> list[Chunk]:
        with self._engine.begin() as conn:
            rows = conn.execute(
                text(
                    f"SELECT {COLUMNS} FROM guide_chunks "  # noqa: S608
                    'WHERE metadata @> \'{"role": "glossary"}\'::jsonb'
                )
            )
            return [_chunk(r) for r in rows]


class MemoryGuideStore:
    """Exact search over an in-memory corpus: the unit-test and offline-eval twin of
    PgGuideStore. Same ordering rules (cosine distance, negative inner product)."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._chunks: dict[uuid.UUID, Chunk] = {}
        self._dense: dict[uuid.UUID, list[float]] = {}
        self._sparse: dict[uuid.UUID, dict[int, float]] = {}
        for r in rows:
            cid = uuid.UUID(r["id"])
            parent = uuid.UUID(r["parent_id"]) if r.get("parent_id") else None
            self._chunks[cid] = Chunk(cid, parent, r["content"], r["metadata"])
            if r.get("dense") is not None:
                self._dense[cid] = r["dense"]
            if r.get("sparse") is not None:
                s = r["sparse"]
                self._sparse[cid] = dict(zip(s["indices"], s["values"], strict=True))

    @classmethod
    def from_json(cls, path: Path) -> MemoryGuideStore:
        return cls(json.loads(path.read_text(encoding="utf-8"))["chunks"])

    def _rank(self, scores: dict[uuid.UUID, float], n: int, filters: Filters) -> list[Chunk]:
        ok = [cid for cid in scores if filters.matches(self._chunks[cid].metadata)]
        ok.sort(key=lambda cid: (-scores[cid], str(cid)))
        return [self._chunks[cid] for cid in ok[:n]]

    def dense_search(self, vector: Sequence[float], n: int, filters: Filters) -> list[Chunk]:
        qn = math.sqrt(math.fsum(x * x for x in vector)) or 1.0
        scores = {}
        for cid, v in self._dense.items():
            vn = math.sqrt(math.fsum(x * x for x in v)) or 1.0
            scores[cid] = math.fsum(a * b for a, b in zip(vector, v, strict=True)) / (qn * vn)
        return self._rank(scores, n, filters)

    def sparse_search(self, weights: dict[int, float], n: int, filters: Filters) -> list[Chunk]:
        scores = {
            cid: math.fsum(w * s.get(i, 0.0) for i, w in weights.items())
            for cid, s in self._sparse.items()
        }
        return self._rank({c: v for c, v in scores.items() if v > 0}, n, filters)

    def get(self, ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, Chunk]:
        return {i: self._chunks[i] for i in ids if i in self._chunks}

    def glossary(self) -> list[Chunk]:
        return [c for c in self._chunks.values() if c.is_glossary]
