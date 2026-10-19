"""Migration and role tests against a real pgvector Postgres.

Run with `make test-integration` (local stack) or in CI. Each run creates and drops its
own scratch database, so the dev database is never touched.
"""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from cryptography.fernet import Fernet
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from homefund_db.models import Base
from homefund_db.seed import seed

pytestmark = pytest.mark.integration

REPO = Path(__file__).resolve().parents[3]
ADMIN_URL = os.environ.get("DATABASE_URL_ADMIN", "")


@pytest.fixture(scope="module")
def scratch_url() -> Iterator[str]:
    if not ADMIN_URL:
        pytest.skip("DATABASE_URL_ADMIN not set")
    name = f"homefund_test_{uuid.uuid4().hex[:8]}"
    admin = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    url = make_url(ADMIN_URL).set(database=name).render_as_string(hide_password=False)
    command.upgrade(_alembic(url), "head")
    try:
        yield url
    finally:
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


def _alembic(url: str) -> Config:
    cfg = Config(str(REPO / "packages" / "db" / "alembic.ini"))
    cfg.attributes["url"] = url
    return cfg


def test_upgrade_downgrade_upgrade(scratch_url: str) -> None:
    cfg = _alembic(scratch_url)
    command.downgrade(cfg, "base")
    engine = create_engine(scratch_url)
    with engine.connect() as conn:
        left = conn.execute(
            text(
                "SELECT count(*) FROM pg_tables WHERE schemaname = 'public' "
                "AND tablename <> 'alembic_version'"
            )
        ).scalar_one()
        assert left == 0
    command.upgrade(cfg, "head")
    engine.dispose()


def test_schema_matches_models(scratch_url: str) -> None:
    engine = create_engine(scratch_url)
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn, opts={"compare_type": False})
        diffs = [d for d in compare_metadata(ctx, Base.metadata) if d[0] != "remove_table"]
        assert diffs == []
        kinds = dict(
            conn.execute(
                text(
                    "SELECT relname, relkind FROM pg_class WHERE relname IN "
                    "('monthly_summaries', 'ix_guide_chunks_dense_hnsw')"
                )
            ).all()
        )
        assert kinds == {"monthly_summaries": "m", "ix_guide_chunks_dense_hnsw": "i"}
    engine.dispose()


def test_roles(scratch_url: str) -> None:
    engine = create_engine(scratch_url)
    with engine.connect() as conn:

        def can(role: str, table: str, priv: str) -> bool:
            return bool(
                conn.execute(
                    text("SELECT has_table_privilege(:r, :t, :p)"),
                    {"r": role, "t": table, "p": priv},
                ).scalar_one()
            )

        for t in ("transactions", "monthly_summaries", "goals", "guide_chunks"):
            assert can("mcp_ro", t, "SELECT")
            assert not can("mcp_ro", t, "INSERT")
        for t in ("plans", "imports"):
            assert not can("mcp_ro", t, "SELECT")
        for t in ("transactions", "goals", "plans", "guide_chunks", "imports"):
            assert can("app_rw", t, "INSERT")
    engine.dispose()


def test_seed_and_monthly_summaries(scratch_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COLUMN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("DEDUPE_HMAC_KEY", "test-only-key")
    golden = json.loads((REPO / "fixtures" / "golden_scenario.json").read_text())
    engine = create_engine(scratch_url)
    with engine.begin() as conn:
        conn.execute(text("SET ROLE app_rw"))  # seed runs as app_rw in `make seed`
        total, inserted = seed(conn, REPO / "fixtures")
        assert total == golden["dataset"]["rows_total"]
        assert inserted == golden["dataset"]["rows_after_dedupe"]
        _, again = seed(conn, REPO / "fixtures")
        assert again == 0
    with engine.connect() as conn:
        conn.execute(text("SET ROLE mcp_ro"))
        dining = conn.execute(
            text("SELECT sum(total) FROM monthly_summaries WHERE category = 'Dining and delivery'")
        ).scalar_one()
        assert dining == Decimal("-3600.00")
        merchant = conn.execute(text("SELECT merchant FROM transactions LIMIT 1")).scalar_one()
        assert merchant.startswith("gAAAA")  # Fernet ciphertext, not plaintext
    engine.dispose()
