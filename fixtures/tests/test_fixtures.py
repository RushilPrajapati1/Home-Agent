from __future__ import annotations

import csv
import json
import re
import runpy
from collections import Counter
from decimal import Decimal
from pathlib import Path

FIXTURES = Path(__file__).resolve().parents[1]


def _rows() -> list[dict[str, str]]:
    path = FIXTURES / "demo_user" / "transactions_labeled.csv"
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def test_generated_files_are_current() -> None:
    render = runpy.run_path(str(FIXTURES / "generate.py"))["render"]
    for path, text in render().items():
        assert path.read_text(encoding="utf-8") == text, f"{path.name} is stale"


def test_six_month_averages_after_dedupe() -> None:
    kept = [r for r in _rows() if r["note"] != "duplicate"]
    months = {r["posted_on"][:7] for r in kept}
    assert months == {f"2026-{m:02d}" for m in range(4, 10)}
    income = sum(Decimal(r["amount"]) for r in kept if r["category"] == "Income")
    spend = -sum(Decimal(r["amount"]) for r in kept if r["category"] not in ("Income", "Transfer"))
    assert income / 6 == Decimal("6800")
    assert spend / 6 == Decimal("5600")


def test_walkthrough_categories_support_the_cuts() -> None:
    kept = [r for r in _rows() if r["note"] != "duplicate"]
    by_cat: Counter[str] = Counter()
    for r in kept:
        by_cat[r["category"]] += -Decimal(r["amount"])
    assert by_cat["Dining and delivery"] / 6 == Decimal("600")
    assert by_cat["Shopping"] / 6 == Decimal("360")
    assert by_cat["Rideshare"] / 6 == Decimal("240")
    assert by_cat["Travel fund"] / 6 == Decimal("280")
    subs = {r["merchant"] for r in kept if r["category"] == "Subscriptions"}
    assert len(subs) == 7


def test_duplicates_and_same_day_repeats() -> None:
    rows = _rows()
    dups = [r for r in rows if r["note"] == "duplicate"]
    assert len(dups) >= 3
    for d in dups:
        twins = [r for r in rows if r["reference"] == d["reference"]]
        assert len(twins) == 2
        assert {k: v for k, v in twins[0].items() if k != "note"} == {
            k: v for k, v in twins[1].items() if k != "note"
        }
    repeats = [r for r in rows if r["note"] == "same-day repeat"]
    assert len(repeats) >= 4
    assert len({r["reference"] for r in repeats}) == len(repeats)


def test_ofx_and_csv_carry_every_row() -> None:
    n = len(_rows())
    ofx = (FIXTURES / "demo_user" / "statement.ofx").read_text(encoding="utf-8")
    assert len(re.findall(r"<STMTTRN>", ofx)) == n
    with (FIXTURES / "demo_user" / "statement.csv").open(newline="", encoding="utf-8") as fh:
        assert len(list(csv.DictReader(fh))) == n


def test_golden_numbers() -> None:
    g = json.loads((FIXTURES / "golden_scenario.json").read_text(encoding="utf-8"))
    e = g["expected"]
    hc = e["home_cost"]
    assert (hc["down_payment"], hc["closing_costs"], hc["reserves"], hc["cash_needed"]) == (
        "42000.00",
        "12600.00",
        "6300.00",
        "60900.00",
    )
    assert Decimal("3125") <= Decimal(hc["piti_monthly"]) <= Decimal("3174.99")
    assert e["saved_so_far"] == "18000.00" and e["gap"] == "42900.00"
    assert e["current_pace"] | {} == {
        "monthly": "1200.00",
        "months_to_goal": 36,
        "reach_month": "2029-10-01",
        "months_late": 16,
        "on_track": False,
    }
    assert e["deadline"]["months_until_move_in"] == 20
    assert e["deadline"]["monthly_needed"] == "2145.00"
    assert Decimal(e["cuts"]["min_total_monthly"]) == Decimal("945.00")
    assert g["clock"]["date"] == "2026-10-01"
    fred = json.loads((FIXTURES / "mocks" / "fred_mortgage30us.json").read_text())
    assert fred["observations"][-1]["value"] == g["mock_inputs"]["rate_pct"]
