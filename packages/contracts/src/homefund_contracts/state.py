"""LangGraph state, exactly as on the design's Agent graph page plus three additions.

``total=False`` because nodes fill keys in as the graph runs: a fresh thread has only
``user_id`` (and later ``goal``).
"""

from __future__ import annotations

from typing import TypedDict
from uuid import UUID

from pydantic import TypeAdapter

from homefund_contracts.domain import Cashflow, Citation, CostBreakdown, Cut, HomeGoal, Point

MAX_REVIEW_ROUNDS = 3
"""After this many review rounds, or a full rejection, the graph continues with on_track=False."""

MAX_PLAN_RETRIES = 1


class PlanState(TypedDict, total=False):
    goal: HomeGoal  # price, zip, move_in, down_pct
    home_cost: CostBreakdown  # down payment, closing, reserves, PITI
    cashflow: Cashflow  # income, spend by category, fixed bills
    projection: list[Point]  # month, balance, target
    cuts: list[Cut]  # category, amount, ease, approved
    notes: list[Citation]  # cited explanations of each cost
    plan: str
    review_rounds: int  # max 3
    # Additions to the design page:
    on_track: bool | None  # set by project_savings / review_cuts; None until projected
    pending_question: str | None  # the question ask_user is waiting on, if paused there
    user_id: UUID  # owner; MCP calls are scoped to this user


PlanStateAdapter: TypeAdapter[PlanState] = TypeAdapter(PlanState)
"""Validate or JSON-dump a PlanState: ``PlanStateAdapter.validate_python(state)``."""
