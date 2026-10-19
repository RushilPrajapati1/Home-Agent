from __future__ import annotations

import json
import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from homefund_contracts.enums import Category, ImportStatus, PlanStatus
from homefund_db import Base
from homefund_db.crypto import decrypt, dedupe_hash, encrypt
from homefund_db.models import CATEGORY_VALUES, IMPORT_STATUS_VALUES, PLAN_STATUS_VALUES
from homefund_db.seed import transaction_rows

REPO = Path(__file__).resolve().parents[3]
USER = uuid.UUID("7c9e6679-7425-40de-944b-e07fc1f90ae7")


@pytest.fixture(autouse=True)
def _keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COLUMN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("DEDUPE_HMAC_KEY", "test-only-key")


def test_tables_and_columns() -> None:
    tables = Base.metadata.tables
    assert set(tables) == {"transactions", "goals", "plans", "guide_chunks", "imports"}
    tx = tables["transactions"].c
    for col in ("account", "dedupe_hash", "category_source", "raw_description"):
        assert col in tx
    assert "status" in tables["plans"].c
    assert tables["guide_chunks"].c["dense"].type.dim == 1024  # type: ignore[attr-defined]
    assert "metadata" in tables["guide_chunks"].c


def test_check_constraints_follow_contract_enums() -> None:
    assert [c.value for c in Category] == CATEGORY_VALUES
    assert [s.value for s in PlanStatus] == PLAN_STATUS_VALUES
    assert [s.value for s in ImportStatus] == IMPORT_STATUS_VALUES


def test_encryption_round_trip_is_not_plaintext() -> None:
    token = encrypt("DOORDASH*TORCHYS TACOS")
    assert "TORCHYS" not in token
    assert decrypt(token) == "DOORDASH*TORCHYS TACOS"


def test_dedupe_hash_separates_references_not_reexports() -> None:
    args = dict(
        user_id=USER,
        account="card-8023",
        posted_on=date(2026, 5, 14),
        amount=Decimal("-5.45"),
        raw_description="STARBUCKS STORE 11457 AUSTIN TX",
    )
    a = dedupe_hash(**args, reference="C20260514004")  # type: ignore[arg-type]
    b = dedupe_hash(**args, reference="C20260514005")  # type: ignore[arg-type]
    again = dedupe_hash(**args, reference="C20260514004")  # type: ignore[arg-type]
    assert a != b and a == again


def test_seed_rows_dedupe_to_expected_count() -> None:
    dataset = json.loads((REPO / "fixtures" / "golden_scenario.json").read_text())["dataset"]
    rows = transaction_rows(REPO / "fixtures", USER)
    assert len(rows) == dataset["rows_total"]
    assert len({r["dedupe_hash"] for r in rows}) == dataset["rows_after_dedupe"]
