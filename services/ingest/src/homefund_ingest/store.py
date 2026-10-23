"""Write guide_chunks as app_rw, idempotently per document.

For each document: read the ids it already has, embed and insert only the new rows
(parents before children, for the foreign key), then delete the document's rows that are
no longer produced. Unchanged content keeps its id and is never re-embedded.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from homefund_embed.schemas import SparseWeights
from pgvector import SparseVector, Vector
from sqlalchemy import Connection, text

from homefund_db.models import SPARSE_DIM
from homefund_ingest.pipeline import Row


@dataclass(frozen=True)
class Embedded:
    dense: list[float]
    sparse: SparseWeights


@dataclass(frozen=True)
class WriteStats:
    inserted: int
    unchanged: int
    deleted: int


def existing_ids(conn: Connection, doc_id: str) -> set[uuid.UUID]:
    rows = conn.execute(
        text("SELECT id FROM guide_chunks WHERE metadata->>'doc_id' = :d"), {"d": doc_id}
    )
    return {r[0] for r in rows}


def insert_rows(conn: Connection, rows: Sequence[Row], vectors: dict[uuid.UUID, Embedded]) -> None:
    ordered = sorted(rows, key=lambda r: r.parent_id is not None)
    params = []
    for r in ordered:
        v = vectors.get(r.id)
        params.append(
            {
                "id": r.id,
                "parent_id": r.parent_id,
                "content": r.content,
                "dense": Vector(v.dense).to_text() if v else None,
                "sparse": SparseVector(v.sparse.as_dict(), SPARSE_DIM).to_text() if v else None,
                "metadata": json.dumps(r.metadata),
            }
        )
    if params:
        conn.execute(
            text(
                "INSERT INTO guide_chunks (id, parent_id, content, dense, sparse, metadata) "
                "VALUES (:id, :parent_id, :content, CAST(:dense AS vector), "
                "CAST(:sparse AS sparsevec), CAST(:metadata AS jsonb)) "
                "ON CONFLICT (id) DO NOTHING"
            ),
            params,
        )


def delete_stale(conn: Connection, doc_id: str, keep: set[uuid.UUID]) -> int:
    result = conn.execute(
        text(
            "DELETE FROM guide_chunks WHERE metadata->>'doc_id' = :d "
            "AND NOT (id = ANY(CAST(:keep AS uuid[])))"
        ),
        {"d": doc_id, "keep": [str(k) for k in keep]},
    )
    return result.rowcount or 0


def delete_documents_except(conn: Connection, doc_ids: set[str]) -> int:
    """Remove documents that are no longer in sources.yaml."""
    result = conn.execute(
        text(
            "DELETE FROM guide_chunks WHERE NOT (metadata->>'doc_id' = ANY(CAST(:ids AS text[])))"
        ),
        {"ids": sorted(doc_ids)},
    )
    return result.rowcount or 0
