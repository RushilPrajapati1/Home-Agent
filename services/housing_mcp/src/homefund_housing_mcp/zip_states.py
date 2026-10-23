"""ZIP code (3-digit prefix) to state, from the USPS prefix ranges.

Territories and military prefixes (PR, VI, GU, AA/AE/AP) map to nothing, so callers fall
back to a national figure.
"""

from __future__ import annotations

ZIP_PREFIX_SOURCE = "USPS 3-digit ZIP prefix ranges"

# (first prefix, last prefix, state), inclusive. Order doesn't matter; ranges don't overlap.
_RANGES: tuple[tuple[int, int, str], ...] = (
    (5, 5, "NY"), (10, 27, "MA"), (28, 29, "RI"), (30, 38, "NH"), (39, 49, "ME"),
    (50, 54, "VT"), (55, 55, "MA"), (56, 59, "VT"), (60, 69, "CT"), (70, 89, "NJ"),
    (100, 149, "NY"), (150, 196, "PA"), (197, 199, "DE"), (200, 200, "DC"), (201, 201, "VA"),
    (202, 205, "DC"), (206, 219, "MD"), (220, 246, "VA"), (247, 268, "WV"), (270, 289, "NC"),
    (290, 299, "SC"), (300, 319, "GA"), (320, 339, "FL"), (341, 349, "FL"), (350, 369, "AL"),
    (370, 385, "TN"), (386, 397, "MS"), (398, 399, "GA"), (400, 427, "KY"), (430, 459, "OH"),
    (460, 479, "IN"), (480, 499, "MI"), (500, 528, "IA"), (530, 549, "WI"), (550, 567, "MN"),
    (569, 569, "DC"), (570, 577, "SD"), (580, 588, "ND"), (590, 599, "MT"), (600, 629, "IL"),
    (630, 658, "MO"), (660, 679, "KS"), (680, 693, "NE"), (700, 714, "LA"), (716, 729, "AR"),
    (730, 732, "OK"), (733, 733, "TX"), (734, 749, "OK"), (750, 799, "TX"), (800, 816, "CO"),
    (820, 831, "WY"), (832, 838, "ID"), (840, 847, "UT"), (850, 865, "AZ"), (870, 884, "NM"),
    (885, 885, "TX"), (889, 898, "NV"), (900, 961, "CA"), (967, 968, "HI"), (970, 979, "OR"),
    (980, 994, "WA"), (995, 999, "AK"),
)  # fmt: skip


def state_for_zip(zip_code: str) -> str | None:
    """The state a 5-digit ZIP belongs to, or None for territories, military and unknowns."""
    prefix = int(zip_code[:3])
    for first, last, state in _RANGES:
        if first <= prefix <= last:
            return state
    return None
