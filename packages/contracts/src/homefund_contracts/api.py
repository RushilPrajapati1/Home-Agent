"""Request and response bodies for the FastAPI app. The user comes from auth, never the body."""

from __future__ import annotations

from datetime import date, datetime
from typing import Self
from uuid import UUID

from pydantic import Field, model_validator

from homefund_contracts.domain import (
    Cashflow,
    Citation,
    CostBreakdown,
    Cut,
    HomeGoal,
    HomeGoalDraft,
    Point,
)
from homefund_contracts.enums import Category, ImportStatus, PlanStatus, ReviewAction
from homefund_contracts.types import ContractModel, Money

# POST /api/imports -------------------------------------------------------------
# Request: multipart/form-data with one or more `files` (CSV, OFX, PDF) and an
# optional `account` form field. Multipart cannot be a JSON model, so only the
# form fields are described here.


class CreateImportForm(ContractModel):
    account: str | None = Field(default=None, description="Account label applied to every row")


class CreateImportResponse(ContractModel):
    import_id: UUID
    status: ImportStatus


# GET /api/imports/{id} ---------------------------------------------------------


class ImportResponse(ContractModel):
    import_id: UUID
    status: ImportStatus
    filenames: list[str]
    rows_parsed: int = 0
    rows_inserted: int = 0
    duplicates_skipped: int = 0
    categorized_by_rule: int = 0
    categorized_by_llm: int = 0
    error: str | None = None
    created_at: datetime
    finished_at: datetime | None = None


# POST /api/plans ---------------------------------------------------------------


class CreatePlanRequest(ContractModel):
    """Free text ("I want a $420,000 home with 10% down by June 2028"), form fields, or both."""

    text: str | None = Field(default=None, max_length=2000)
    goal: HomeGoalDraft | None = None

    @model_validator(mode="after")
    def _something_given(self) -> Self:
        if not (self.text and self.text.strip()) and self.goal is None:
            raise ValueError("provide text, goal, or both")
        return self


class CreatePlanResponse(ContractModel):
    """Open GET /api/plans/{plan_id}/events next to follow progress."""

    plan_id: UUID


# POST /api/plans/{id}/review ---------------------------------------------------


class CutEdit(ContractModel):
    category: Category
    amount: Money = Field(ge=0, description="New monthly reduction; 0 drops the cut")


class ReviewRequest(ContractModel):
    action: ReviewAction
    edits: list[CutEdit] = Field(default_factory=list, description="Required when action=edit")
    unlock: list[Category] = Field(
        default_factory=list, description="Protected categories the user allows the solver to cut"
    )

    @model_validator(mode="after")
    def _edits_match_action(self) -> Self:
        if self.action == ReviewAction.EDIT and not self.edits:
            raise ValueError("action=edit needs at least one edit")
        if self.action != ReviewAction.EDIT and self.edits:
            raise ValueError("edits are only allowed with action=edit")
        return self


class ReviewResponse(ContractModel):
    plan_id: UUID
    status: PlanStatus
    review_rounds: int


# POST /api/plans/{id}/answer ---------------------------------------------------


class AnswerRequest(ContractModel):
    """Answers the question the graph asked at ask_user."""

    answer: str = Field(min_length=1, max_length=2000)


class AnswerResponse(ContractModel):
    plan_id: UUID
    status: PlanStatus


# GET /api/plans/{id} -----------------------------------------------------------


class PlanResponse(ContractModel):
    plan_id: UUID
    status: PlanStatus
    goal: HomeGoal | None = None
    home_cost: CostBreakdown | None = None
    cashflow: Cashflow | None = None
    cash_needed: Money | None = None
    monthly_target: Money | None = Field(
        default=None, description="Monthly saving needed to reach cash_needed by move_in"
    )
    reach_month: date | None = None
    on_track: bool | None = None
    projection: list[Point] = Field(default_factory=list)
    cuts: list[Cut] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    plan: str | None = None
    review_rounds: int = 0
    pending_question: str | None = None
    created_at: datetime
    updated_at: datetime


class ErrorResponse(ContractModel):
    code: str
    message: str
