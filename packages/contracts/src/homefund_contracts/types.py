"""Primitive annotated types shared by every contract.

Money and percentages are ``Decimal`` in Python and strings on the wire. Floats are
rejected at validation time so a binary-float value can never slip into money math.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Annotated, Any

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    PlainSerializer,
    StringConstraints,
    WithJsonSchema,
)

MONEY_PATTERN = r"^-?\d{1,12}(\.\d{1,2})?$"
PERCENT_PATTERN = r"^\d{1,3}(\.\d{1,4})?$"
CENT = Decimal("0.01")


def _reject_float(value: Any) -> Any:
    if isinstance(value, bool | float):
        raise ValueError("use Decimal, int or a decimal string; floats are not allowed for money")
    return value


def _money_to_str(value: Decimal) -> str:
    return str(value.quantize(CENT))


def _percent_to_str(value: Decimal) -> str:
    return format(value.normalize(), "f")


def _first_of_month(value: date) -> date:
    if value.day != 1:
        raise ValueError("a month is represented by its first day, e.g. 2026-10-01")
    return value


Money = Annotated[
    Decimal,
    BeforeValidator(_reject_float),
    Field(max_digits=14, decimal_places=2, allow_inf_nan=False),
    PlainSerializer(_money_to_str, return_type=str, when_used="json"),
    WithJsonSchema(
        {"type": "string", "pattern": MONEY_PATTERN, "description": 'US dollars, e.g. "1200.00"'}
    ),
]
"""US dollars as Decimal with at most 2 places; serialized as a string like ``"1200.00"``."""

Percent = Annotated[
    Decimal,
    BeforeValidator(_reject_float),
    Field(ge=0, le=100, decimal_places=4, allow_inf_nan=False),
    PlainSerializer(_percent_to_str, return_type=str, when_used="json"),
    WithJsonSchema(
        {
            "type": "string",
            "pattern": PERCENT_PATTERN,
            "description": 'Percentage points: "10" means 10%, "6.27" means 6.27%',
        }
    ),
]
"""Percentage points as Decimal: ``Decimal("10")`` is 10%. Serialized as a string."""

Month = Annotated[date, AfterValidator(_first_of_month)]
"""A calendar month, represented by its first day."""

ZipCode = Annotated[str, StringConstraints(pattern=r"^\d{5}$")]


class ContractModel(BaseModel):
    """Base for every contract model: unknown fields are an error, not silently dropped."""

    model_config = ConfigDict(extra="forbid", use_enum_values=False)
