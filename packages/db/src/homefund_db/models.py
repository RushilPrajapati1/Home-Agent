"""SQLAlchemy 2 models. Migration 0001 is the authority for DDL; these mirror it.

user_id columns are plain indexed UUIDs: the design has no users table (auth lives in
the API), so there is nothing to reference yet.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pgvector.sqlalchemy import SPARSEVEC, Vector
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Numeric,
    Table,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from homefund_contracts.enums import (
    Category,
    CategorySource,
    ImportStatus,
    PlanStatus,
    TransactionSource,
)
from homefund_db.crypto import EncryptedText

DENSE_DIM = 1024
SPARSE_DIM = 250_002  # BGE-M3 vocabulary size


def check_in(column: str, values: list[str]) -> str:
    quoted = ", ".join("'" + v.replace("'", "''") + "'" for v in values)
    return f"{column} IN ({quoted})"


CATEGORY_VALUES = [c.value for c in Category]
CATEGORY_SOURCE_VALUES = [c.value for c in CategorySource]
TRANSACTION_SOURCE_VALUES = [c.value for c in TransactionSource]
PLAN_STATUS_VALUES = [c.value for c in PlanStatus]
IMPORT_STATUS_VALUES = [c.value for c in ImportStatus]


class Base(DeclarativeBase):
    pass


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )


def _created_at() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Transaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (
        CheckConstraint(check_in("category", CATEGORY_VALUES), name="ck_transactions_category"),
        CheckConstraint(
            check_in("category_source", CATEGORY_SOURCE_VALUES),
            name="ck_transactions_category_source",
        ),
        CheckConstraint(
            check_in("source", TRANSACTION_SOURCE_VALUES), name="ck_transactions_source"
        ),
        UniqueConstraint("dedupe_hash", name="uq_transactions_dedupe_hash"),
        Index("ix_transactions_user_posted_on", "user_id", "posted_on"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    account: Mapped[str] = mapped_column(Text, nullable=False)
    posted_on: Mapped[date] = mapped_column(Date, nullable=False)
    amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, comment="Signed: income +, spending -"
    )
    merchant: Mapped[str | None] = mapped_column(EncryptedText, comment="Fernet ciphertext")
    raw_description: Mapped[str | None] = mapped_column(EncryptedText, comment="Fernet ciphertext")
    category: Mapped[str] = mapped_column(Text, nullable=False)
    category_source: Mapped[str] = mapped_column(Text, nullable=False)
    is_fixed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    source: Mapped[str] = mapped_column(Text, nullable=False)
    dedupe_hash: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = _created_at()


class Goal(Base):
    __tablename__ = "goals"
    __table_args__ = (Index("ix_goals_user_id", "user_id"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    zip: Mapped[str] = mapped_column(Text, nullable=False)
    down_pct: Mapped[Decimal] = mapped_column(
        Numeric(7, 4), nullable=False, comment="Percentage points: 10 means 10%"
    )
    move_in: Mapped[date] = mapped_column(Date, nullable=False)
    saved: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    created_at: Mapped[datetime] = _created_at()


class Plan(Base):
    __tablename__ = "plans"
    __table_args__ = (
        CheckConstraint(check_in("status", PLAN_STATUS_VALUES), name="ck_plans_status"),
        Index("ix_plans_goal_id", "goal_id"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    goal_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("goals.id", ondelete="CASCADE")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'running'"))
    cash_needed: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    monthly_target: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    on_track: Mapped[bool | None] = mapped_column(Boolean)
    projection: Mapped[Any] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    cuts: Mapped[Any] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    citations: Mapped[Any] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    plan_text: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class GuideChunk(Base):
    """Child chunks carry vectors; parent sections are rows too, referenced by parent_id."""

    __tablename__ = "guide_chunks"
    __table_args__ = (
        Index(
            "ix_guide_chunks_dense_hnsw",
            "dense",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"dense": "vector_cosine_ops"},
        ),
        Index("ix_guide_chunks_metadata", "metadata", postgresql_using="gin"),
        Index("ix_guide_chunks_parent_id", "parent_id"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("guide_chunks.id", ondelete="CASCADE")
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    dense: Mapped[Any] = mapped_column(Vector(DENSE_DIM), nullable=True)
    sparse: Mapped[Any] = mapped_column(SPARSEVEC(SPARSE_DIM), nullable=True)
    # "metadata" is reserved on declarative classes, hence the attribute name.
    meta: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
        comment="source (cfpb|hud|glossary), document, section, url, tax_year (int)",
    )
    created_at: Mapped[datetime] = _created_at()


class Import(Base):
    """Status of one POST /api/imports job, written by importer, read by api."""

    __tablename__ = "imports"
    __table_args__ = (
        CheckConstraint(check_in("status", IMPORT_STATUS_VALUES), name="ck_imports_status"),
        Index("ix_imports_user_id", "user_id"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'queued'"))
    filenames: Mapped[Any] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    account: Mapped[str | None] = mapped_column(Text)
    rows_parsed: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    rows_inserted: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    duplicates_skipped: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    categorized_by_rule: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    categorized_by_llm: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created_at()
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# The materialized view lives on its own MetaData so create_all and Alembic autogenerate
# never try to create it as a table. Migration 0001 defines it; importer refreshes it.
view_metadata = MetaData()

monthly_summaries = Table(
    "monthly_summaries",
    view_metadata,
    Column("user_id", UUID(as_uuid=True), nullable=False),
    Column("month", Date, nullable=False),
    Column("category", Text, nullable=False),
    Column("total", Numeric(12, 2), nullable=False),
    Column("count", Integer, nullable=False),
)
