"""Cut-solver settings: how much of each category may be cut, and how easy each cut is."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from homefund_contracts.enums import Category, Ease

DEFAULT_CAP_SHARE = Decimal("0.5")

# Lower is easier. Protected categories only become candidates when the user unlocks them.
DEFAULT_EASE_SCORES: dict[Category, int] = {
    Category.TRAVEL_FUND: 1,
    Category.SUBSCRIPTIONS: 1,
    Category.ENTERTAINMENT: 2,
    Category.DINING_AND_DELIVERY: 3,
    Category.SHOPPING: 3,
    Category.RIDESHARE: 3,
    Category.OTHER: 4,
    Category.GROCERIES: 5,
    Category.RENT: 5,
    Category.INSURANCE: 5,
    Category.UTILITIES: 5,
    Category.DEBT_MINIMUM: 5,
}


@dataclass(frozen=True)
class CutConfig:
    default_cap_share: Decimal = DEFAULT_CAP_SHARE
    cap_shares: dict[Category, Decimal] = field(
        default_factory=lambda: {Category.TRAVEL_FUND: Decimal("1")}
    )
    # Subscriptions are cut whole: at most this share of them, rounded down.
    subscription_max_share: Decimal = Decimal("0.6")
    ease_scores: dict[Category, int] = field(default_factory=lambda: dict(DEFAULT_EASE_SCORES))
    default_ease_score: int = 3

    def cap_share(self, category: Category) -> Decimal:
        return self.cap_shares.get(category, self.default_cap_share)

    def ease_score(self, category: Category) -> int:
        return self.ease_scores.get(category, self.default_ease_score)

    def ease(self, category: Category) -> Ease:
        score = self.ease_score(category)
        if score <= 2:
            return Ease.EASY
        if score == 3:
            return Ease.MEDIUM
        return Ease.HARD
