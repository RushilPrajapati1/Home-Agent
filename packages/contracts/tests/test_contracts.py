from __future__ import annotations

import inspect
import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from homefund_contracts import (
    PROTECTED,
    Category,
    Clock,
    CostBreakdown,
    Cut,
    FixedClock,
    HomeGoal,
    PlanStatus,
    Point,
    SystemClock,
    clock_from_env,
)
from homefund_contracts.api import CreatePlanRequest, ReviewRequest
from homefund_contracts.events import EVENT_TYPES, PlanEventAdapter
from homefund_contracts.export_schema import render
from homefund_contracts.mcp import TOOLS
from homefund_contracts.state import PlanStateAdapter

REPO = Path(__file__).resolve().parents[3]


def test_money_is_decimal_and_serializes_as_string() -> None:
    p = Point(month=date(2026, 10, 1), balance="18000", target=Decimal("60900.00"))
    assert isinstance(p.balance, Decimal)
    assert json.loads(p.model_dump_json()) == {
        "month": "2026-10-01",
        "balance": "18000.00",
        "target": "60900.00",
    }


@pytest.mark.parametrize("bad", [18000.0, "18000.001", "NaN", True])
def test_money_rejects_floats_and_sub_cent_values(bad: object) -> None:
    with pytest.raises(ValidationError):
        Point(month=date(2026, 10, 1), balance=bad, target="1")  # type: ignore[arg-type]


def test_month_must_be_first_of_month() -> None:
    with pytest.raises(ValidationError):
        Point(month=date(2026, 10, 2), balance="1", target="1")


def test_categories_and_protected_set() -> None:
    assert [c.value for c in Category] == [
        "Dining and delivery",
        "Groceries",
        "Travel fund",
        "Shopping",
        "Rideshare",
        "Subscriptions",
        "Entertainment",
        "Rent",
        "Insurance",
        "Utilities",
        "Debt minimum",
        "Income",
        "Transfer",
        "Other",
    ]
    assert {c.value for c in PROTECTED} == {"Rent", "Insurance", "Utilities", "Debt minimum"}


def test_plan_status_values() -> None:
    assert {s.value for s in PlanStatus} == {
        "running",
        "awaiting_input",
        "awaiting_review",
        "done",
        "failed",
    }


def test_fixed_clock() -> None:
    clock = FixedClock(date(2026, 10, 1))
    assert isinstance(clock, Clock)
    assert clock.today() == date(2026, 10, 1)
    assert clock.now().tzinfo is not None
    clock.advance(timedelta(days=31))
    assert clock.today() == date(2026, 11, 1)


def test_system_clock_is_aware() -> None:
    clock = SystemClock()
    assert isinstance(clock, Clock)
    assert clock.now().tzinfo is not None


def test_clock_from_env() -> None:
    assert clock_from_env({"CLOCK_FIXED_DATE": "2026-10-01"}).today() == date(2026, 10, 1)
    assert isinstance(clock_from_env({}), SystemClock)


def test_cut_must_be_consistent() -> None:
    ok = Cut(
        category=Category.SHOPPING,
        current_monthly="360",
        amount="180",
        new_monthly="180",
        ease="easy",
    )
    assert ok.approved is False
    with pytest.raises(ValidationError):
        Cut(
            category=Category.SHOPPING,
            current_monthly="360",
            amount="400",
            new_monthly="0",
            ease="easy",
        )
    with pytest.raises(ValidationError):
        Cut(
            category=Category.SHOPPING,
            current_monthly="360",
            amount="100",
            new_monthly="200",
            ease="easy",
        )
    with pytest.raises(ValidationError):
        Cut(
            category=Category.INCOME, current_monthly="10", amount="5", new_monthly="5", ease="easy"
        )


# Tool names and parameters exactly as on the design's "APIs, MCP servers & data model" page.
DESIGN_TOOLS = {
    "budget-mcp": {
        "get_cashflow": ["months"],
        "get_spending_by_category": ["months"],
        "get_fixed_bills": [],
        "project_savings": ["start", "monthly", "target"],
        "solve_cuts": ["gap_per_month", "protected"],
    },
    "housing-mcp": {
        "estimate_home_cost": ["price", "zip", "down_pct"],
        "get_mortgage_rate": [],
        "get_property": ["address"],
    },
    "guides-mcp": {
        "search_guides": ["query", "k"],
        "define_term": ["term"],
        "get_section": ["chunk_id"],
    },
}


def test_mcp_tools_match_design() -> None:
    actual = {
        server: {name: list(spec.input.model_fields) for name, spec in tools.items()}
        for server, tools in TOOLS.items()
    }
    assert actual == DESIGN_TOOLS


def test_mcp_defaults_match_design() -> None:
    budget = TOOLS["budget-mcp"]
    assert budget["get_cashflow"].input().model_dump() == {"months": 6}
    assert budget["get_spending_by_category"].input().model_dump() == {"months": 6}
    assert set(budget["solve_cuts"].input(gap_per_month="945").protected) == PROTECTED
    assert TOOLS["guides-mcp"]["search_guides"].input(query="PMI").k == 5


def test_every_tool_model_is_strict() -> None:
    for tools in TOOLS.values():
        for spec in tools.values():
            for model in (spec.input, spec.output):
                assert inspect.isclass(model)
                assert model.model_config.get("extra") == "forbid", model


def test_event_union_round_trips_every_type() -> None:
    base = {"plan_id": str(uuid4()), "seq": 0, "at": datetime.now(UTC).isoformat()}
    cut = {
        "category": "Shopping",
        "current_monthly": "360.00",
        "amount": "180.00",
        "new_monthly": "180.00",
        "ease": "easy",
    }
    now = datetime.now(UTC).isoformat()
    samples = {
        "node_started": {"node": "parse_goal"},
        "node_finished": {"node": "parse_goal", "duration_ms": 12},
        "cost_ready": {"home_cost": _golden()["expected"]["home_cost"]},
        "projection_ready": {
            "monthly": "1200.00",
            "months_to_goal": 36,
            "reach_month": "2029-10-01",
            "on_track": False,
            "projection": [{"month": "2026-10-01", "balance": "18000.00", "target": "60900.00"}],
        },
        "cuts_proposed": {
            "cuts": [cut],
            "gap_monthly": "945.00",
            "total_monthly": "180.00",
            "review_round": 1,
        },
        "question": {"question": "What ZIP code?", "missing": ["zip"]},
        "plan_ready": {
            "plan": {
                "plan_id": base["plan_id"],
                "status": "done",
                "created_at": now,
                "updated_at": now,
            }
        },
        "error": {"code": "mcp_unavailable", "message": "budget-mcp timed out"},
    }
    assert set(samples) == set(EVENT_TYPES)
    for kind, payload in samples.items():
        event = PlanEventAdapter.validate_python({**base, "type": kind, **payload})
        assert event.type == kind
        again = PlanEventAdapter.validate_json(PlanEventAdapter.dump_json(event))
        assert again == event


def test_create_plan_needs_text_or_goal() -> None:
    with pytest.raises(ValidationError):
        CreatePlanRequest()
    assert CreatePlanRequest(text="I want a $420,000 home").goal is None


def test_review_edits_require_edit_action() -> None:
    with pytest.raises(ValidationError):
        ReviewRequest(action="edit")
    with pytest.raises(ValidationError):
        ReviewRequest(action="approve", edits=[{"category": "Shopping", "amount": "100"}])
    assert ReviewRequest(action="reject").edits == []


def _golden() -> dict:  # type: ignore[type-arg]
    return json.loads((REPO / "fixtures" / "golden_scenario.json").read_text(encoding="utf-8"))


def test_golden_scenario_fits_contracts() -> None:
    golden = _golden()
    cost = CostBreakdown.model_validate(golden["expected"]["home_cost"])
    assert cost.cash_needed == cost.down_payment + cost.closing_costs + cost.reserves
    assert cost.piti_monthly == (
        cost.principal_interest_monthly + cost.property_tax_monthly + cost.insurance_monthly
    )
    goal = HomeGoal.model_validate(golden["request"]["goal"])
    state = PlanStateAdapter.validate_python(
        {"user_id": golden["user_id"], "goal": goal, "home_cost": cost, "review_rounds": 0}
    )
    assert state["home_cost"].reserves == Decimal("6300.00")


def test_exported_schema_is_current() -> None:
    schema_dir = REPO / "web" / "src" / "api" / "schema"
    for name, text in render().items():
        path = schema_dir / name
        assert path.exists(), f"missing {path}; run `make schema`"
        assert path.read_text(encoding="utf-8") == text, f"{name} is stale; run `make schema`"
