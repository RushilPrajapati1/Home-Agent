"""Load the fixture user and refresh monthly_summaries. Run by `make seed` as app_rw.

Idempotent: transactions conflict on dedupe_hash (which also drops the fixture's exact
duplicates) and the goal has a fixed id.
"""

from __future__ import annotations

import argparse
import csv
import json
import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import Connection, text
from sqlalchemy.dialects.postgresql import insert

from homefund_contracts.enums import CategorySource, TransactionSource
from homefund_db.config import APP_URL_VAR, make_engine
from homefund_db.crypto import dedupe_hash
from homefund_db.models import Goal, Transaction

DEMO_GOAL_ID = uuid.UUID("b3f1c2d4-5e6f-4a7b-8c9d-0e1f2a3b4c5d")


def transaction_rows(fixtures: Path, user_id: uuid.UUID) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    path = fixtures / "demo_user" / "transactions_labeled.csv"
    with path.open(newline="", encoding="utf-8") as fh:
        for rec in csv.DictReader(fh):
            posted_on = date.fromisoformat(rec["posted_on"])
            amount = Decimal(rec["amount"])
            rows.append(
                {
                    "user_id": user_id,
                    "account": rec["account"],
                    "posted_on": posted_on,
                    "amount": amount,
                    "merchant": rec["merchant"],
                    "raw_description": rec["raw_description"],
                    "category": rec["category"],
                    "category_source": CategorySource.RULE.value,
                    "is_fixed": rec["is_fixed"] == "true",
                    "source": TransactionSource.CSV.value,
                    "dedupe_hash": dedupe_hash(
                        user_id=user_id,
                        account=rec["account"],
                        posted_on=posted_on,
                        amount=amount,
                        raw_description=rec["raw_description"],
                        reference=rec["reference"],
                    ),
                }
            )
    return rows


def seed(conn: Connection, fixtures: Path) -> tuple[int, int]:
    scenario = json.loads((fixtures / "golden_scenario.json").read_text(encoding="utf-8"))
    user_id = uuid.UUID(scenario["user_id"])
    rows = transaction_rows(fixtures, user_id)

    # The ORM table applies EncryptedText to merchant and raw_description on bind.
    stmt = (
        insert(Transaction)
        .values(rows)
        .on_conflict_do_nothing(index_elements=["dedupe_hash"])
        .returning(Transaction.id)
    )
    inserted = len(conn.execute(stmt).all())

    goal = scenario["request"]["goal"]
    conn.execute(
        insert(Goal)
        .values(
            id=DEMO_GOAL_ID,
            user_id=user_id,
            price=Decimal(goal["price"]),
            zip=goal["zip"],
            down_pct=Decimal(goal["down_pct"]),
            move_in=date.fromisoformat(goal["move_in"]),
            saved=Decimal(goal["saved"]),
        )
        .on_conflict_do_nothing(index_elements=["id"])
    )
    conn.execute(text("REFRESH MATERIALIZED VIEW monthly_summaries"))
    return len(rows), inserted


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixtures", type=Path, default=Path("fixtures"))
    args = parser.parse_args()
    with make_engine(APP_URL_VAR).begin() as conn:
        total, inserted = seed(conn, args.fixtures)
    print(f"seed: {inserted} of {total} fixture rows inserted (duplicates skipped by hash)")
    print("seed: monthly_summaries refreshed")


if __name__ == "__main__":
    main()
