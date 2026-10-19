"""Server-Sent Events for GET /api/plans/{id}/events.

Wire format, one event per frame::

    id: <seq>
    event: <type>
    data: <PlanEvent JSON>

``seq`` increases by one per plan, so a reconnecting EventSource resumes with
Last-Event-ID. ``cuts_proposed`` and ``question`` mean the graph is paused.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, TypeAdapter

from homefund_contracts.api import PlanResponse
from homefund_contracts.domain import CostBreakdown, Cut, Point
from homefund_contracts.enums import NodeName
from homefund_contracts.types import ContractModel, Money


class _EventBase(ContractModel):
    plan_id: UUID
    seq: int = Field(ge=0)
    at: datetime


class NodeStarted(_EventBase):
    type: Literal["node_started"] = "node_started"
    node: NodeName


class NodeFinished(_EventBase):
    type: Literal["node_finished"] = "node_finished"
    node: NodeName
    duration_ms: int = Field(ge=0)


class CostReady(_EventBase):
    type: Literal["cost_ready"] = "cost_ready"
    home_cost: CostBreakdown


class ProjectionReady(_EventBase):
    type: Literal["projection_ready"] = "projection_ready"
    monthly: Money = Field(description="Monthly saving this projection assumes")
    projection: list[Point]
    months_to_goal: int | None
    reach_month: date | None
    on_track: bool


class CutsProposed(_EventBase):
    """The graph is paused at review_cuts; answer with POST /api/plans/{id}/review."""

    type: Literal["cuts_proposed"] = "cuts_proposed"
    cuts: list[Cut]
    gap_monthly: Money
    total_monthly: Money
    review_round: int = Field(ge=1)


class Question(_EventBase):
    """The graph is paused at ask_user; answer with POST /api/plans/{id}/answer."""

    type: Literal["question"] = "question"
    question: str
    missing: list[str] = Field(default_factory=list, description="HomeGoal fields still unknown")


class PlanReady(_EventBase):
    type: Literal["plan_ready"] = "plan_ready"
    plan: PlanResponse


class Error(_EventBase):
    type: Literal["error"] = "error"
    code: str
    message: str
    retryable: bool = False


PlanEvent = Annotated[
    NodeStarted
    | NodeFinished
    | CostReady
    | ProjectionReady
    | CutsProposed
    | Question
    | PlanReady
    | Error,
    Field(discriminator="type"),
]

PlanEventAdapter: TypeAdapter[PlanEvent] = TypeAdapter(PlanEvent)

EVENT_TYPES: tuple[str, ...] = (
    "node_started",
    "node_finished",
    "cost_ready",
    "projection_ready",
    "cuts_proposed",
    "question",
    "plan_ready",
    "error",
)
PAUSING_EVENT_TYPES: frozenset[str] = frozenset({"cuts_proposed", "question"})
