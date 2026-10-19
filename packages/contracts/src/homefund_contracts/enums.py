"""Enumerations shared across services. Values are the exact strings stored in Postgres."""

from __future__ import annotations

from enum import StrEnum


class Category(StrEnum):
    DINING_AND_DELIVERY = "Dining and delivery"
    GROCERIES = "Groceries"
    TRAVEL_FUND = "Travel fund"
    SHOPPING = "Shopping"
    RIDESHARE = "Rideshare"
    SUBSCRIPTIONS = "Subscriptions"
    ENTERTAINMENT = "Entertainment"
    RENT = "Rent"
    INSURANCE = "Insurance"
    UTILITIES = "Utilities"
    DEBT_MINIMUM = "Debt minimum"
    INCOME = "Income"
    TRANSFER = "Transfer"
    OTHER = "Other"


PROTECTED: frozenset[Category] = frozenset(
    {Category.RENT, Category.INSURANCE, Category.UTILITIES, Category.DEBT_MINIMUM}
)
"""Essentials that solve_cuts may never cut unless the user explicitly unlocks them."""

NON_SPENDING: frozenset[Category] = frozenset({Category.INCOME, Category.TRANSFER})
"""Categories excluded from spending totals. Income is take-home; Transfer moves money
between the user's own accounts (savings sweeps, card payments) and is neither."""


class CategorySource(StrEnum):
    RULE = "rule"
    LLM = "llm"
    USER = "user"


class TransactionSource(StrEnum):
    PLAID = "plaid"
    CSV = "csv"
    OFX = "ofx"
    PDF = "pdf"


class PlanStatus(StrEnum):
    RUNNING = "running"
    AWAITING_INPUT = "awaiting_input"
    AWAITING_REVIEW = "awaiting_review"
    DONE = "done"
    FAILED = "failed"


class ImportStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class Ease(StrEnum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


class GuideSource(StrEnum):
    CFPB = "cfpb"
    HUD = "hud"
    GLOSSARY = "glossary"


class NodeName(StrEnum):
    """Nodes of the LangGraph agent, as on the design's Agent graph page."""

    PARSE_GOAL = "parse_goal"
    ASK_USER = "ask_user"
    ESTIMATE_HOME_COST = "estimate_home_cost"
    ANALYZE_SPENDING = "analyze_spending"
    PROJECT_SAVINGS = "project_savings"
    SOLVE_CUTS = "solve_cuts"
    REVIEW_CUTS = "review_cuts"
    EXPLAIN_COSTS = "explain_costs"
    WRITE_PLAN = "write_plan"


class ReviewAction(StrEnum):
    APPROVE = "approve"
    EDIT = "edit"
    REJECT = "reject"
