"""Generate every Home Fund fixture deterministically.

    uv run python fixtures/generate.py          # rewrite fixtures
    uv run python fixtures/generate.py --check  # exit 1 if committed fixtures are stale

Writes:
  fixtures/demo_user/transactions_labeled.csv  ground truth: category, is_fixed, notes
  fixtures/demo_user/statement.csv             what a bank export looks like (no labels)
  fixtures/demo_user/statement.ofx             same rows as OFX 1.02 (checking + card)
  fixtures/mocks/fred_mortgage30us.json        FRED series/observations response
  fixtures/mocks/rentcast_property.json        RentCast /v1/properties response
  fixtures/mocks/rentcast_value.json           RentCast /v1/avm/value response
  fixtures/golden_scenario.json                the walkthrough with every expected number

All arithmetic is Decimal. Six full months (Apr-Sep 2026) average exactly $6,800 take-home
and $5,600 spend, after removing exact duplicates and excluding Transfer rows.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import random
import sys
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
D = Decimal
CENT = D("0.01")
SEED = 20261001

USER_ID = "7c9e6679-7425-40de-944b-e07fc1f90ae7"
CHECKING = "checking-4417"
CARD = "card-8023"
MONTHS = [date(2026, m, 1) for m in range(4, 10)]  # Apr..Sep 2026


def q(x: Decimal) -> Decimal:
    return x.quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass
class Row:
    account: str
    posted_on: date
    amount: Decimal  # signed: income +, spending -
    raw_description: str
    merchant: str
    category: str
    is_fixed: bool = False
    note: str = ""
    scalable: bool = True
    reference: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


def month_end(m: date) -> date:
    nxt = date(m.year + (m.month == 12), m.month % 12 + 1, 1)
    return nxt - timedelta(days=1)


def business_day(d: date, *, backward: bool = False) -> date:
    step = timedelta(days=-1 if backward else 1)
    while d.weekday() >= 5:
        d += step
    return d


def spread(total: Decimal, n: int, rng: random.Random, wobble: float = 0.08) -> list[Decimal]:
    """Split `total` into n positive monthly targets that vary a little and sum exactly."""
    weights = [D(str(round(1 + rng.uniform(-wobble, wobble), 4))) for _ in range(n)]
    scale = total / sum(weights)
    parts = [q(w * scale) for w in weights[:-1]]
    parts.append(total - sum(parts))
    return parts


def rand_day(rng: random.Random, m: date) -> date:
    return m + timedelta(days=rng.randrange(month_end(m).day))


# --- merchant catalog: (raw description, merchant, low, high) -------------------------
DINING = [
    ("DOORDASH*TORCHYS TACOS DOORDASH.COM CA", "DoorDash", 24, 42, 4),
    ("DOORDASH*PHO THAILAND DOORDASH.COM CA", "DoorDash", 26, 44, 2),
    ("UBER *EATS 8005928996 CA", "Uber Eats", 22, 40, 4),
    ("STARBUCKS STORE 11457 AUSTIN TX", "Starbucks", 5, 9, 5),
    ("CHIPOTLE 2241 AUSTIN TX", "Chipotle", 12, 17, 3),
    ("TORCHYS TACOS - S 1ST AUSTIN TX", "Torchy's Tacos", 14, 24, 2),
    ("TST* ODD DUCK AUSTIN TX", "Odd Duck", 55, 85, 1),
    ("SQ *VERACRUZ ALL NATURAL AUSTIN TX", "Veracruz All Natural", 11, 19, 2),
]
GROCERIES = [
    ("H-E-B #424 AUSTIN TX", "H-E-B", 38, 96, 6),
    ("TRADER JOE S #752 AUSTIN TX", "Trader Joe's", 28, 64, 2),
    ("COSTCO WHSE #1159 AUSTIN TX", "Costco", 90, 160, 1),
]
SHOPPING = [
    ("AMZN Mktp US*{code} Amzn.com/bill WA", "Amazon", 14, 72, 4),
    ("TARGET 00027813 AUSTIN TX", "Target", 22, 85, 1),
    ("UNIQLO AUSTIN DOMAIN AUSTIN TX", "Uniqlo", 30, 80, 1),
]
RIDESHARE = [
    ("UBER *TRIP HELP.UBER.COM CA", "Uber", 9, 28, 7),
    ("LYFT *RIDE LYFT.COM CA", "Lyft", 9, 24, 3),
]
ENTERTAINMENT = [
    ("ALAMO DRAFTHOUSE S LAMAR AUSTIN TX", "Alamo Drafthouse", 18, 42, 1),
    ("AMC ONLINE #2120 KANSAS CITY MO", "AMC Theatres", 16, 34, 1),
    ("TICKETMASTER 800-653-8000 CA", "Ticketmaster", 45, 110, 1),
]
OTHER = [
    ("CVS/PHARMACY #07211 AUSTIN TX", "CVS Pharmacy", 9, 38, 2),
    ("SHELL OIL 57444123 AUSTIN TX", "Shell", 28, 52, 2),
    ("GREAT CLIPS #4021 AUSTIN TX", "Great Clips", 22, 30, 1),
    ("USPS PO 4816500123 AUSTIN TX", "USPS", 6, 18, 1),
]
SUBSCRIPTIONS = [  # 7 subscriptions, about $18 each
    ("NETFLIX.COM LOS GATOS CA", "Netflix", D("17.99"), 5),
    ("HLU*HULU 877-8244858 CA", "Hulu", D("18.99"), 9),
    ("MAX.COM HBOMAX.COM NY", "Max", D("16.99"), 12),
    ("SPOTIFY USA NEW YORK NY", "Spotify", D("16.99"), 14),
    ("GOOGLE *YOUTUBEPREMIUM G.CO/HELPPAY# CA", "YouTube Premium", D("13.99"), 18),
    ("ADOBE *PHOTOGRPHY PLAN 408-536-6000 CA", "Adobe", D("19.99"), 21),
    ("APPLE.COM/BILL 866-712-7753 CA", "Apple One", D("19.95"), 26),
]

# Six-month totals that make the walkthrough's averages exact.
TARGETS = {
    "Dining and delivery": D("3600.00"),  # $600/mo
    "Groceries": D("3300.00"),  # $550/mo
    "Shopping": D("2160.00"),  # $360/mo
    "Rideshare": D("1440.00"),  # $240/mo
    "Entertainment": D("900.00"),  # $150/mo
}
INCOME_PER_CHECK = D("3400.00")  # semi-monthly -> $6,800/mo
RENT = D("2400.00")
SPECTRUM = D("65.00")
ELECTRIC_TOTAL = D("690.00")  # with Spectrum -> Utilities $180/mo
LEMONADE = D("15.00")
PROGRESSIVE = D("145.00")  # Insurance $160/mo
NELNET = D("350.00")  # Debt minimum
TRAVEL_FUND = D("280.00")
HOME_FUND_SWEEP = D("1200.00")  # Transfer: excluded from spend
TOTAL_SPEND = D("33600.00")  # $5,600/mo over six months


def build_rows(rng: random.Random) -> list[Row]:
    rows: list[Row] = []

    def add(r: Row) -> Row:
        rows.append(r)
        return r

    electric = spread(ELECTRIC_TOTAL, 6, rng, wobble=0.2)
    for i, m in enumerate(MONTHS):
        # Checking: payroll, rent, bills, transfers.
        for d in (
            business_day(m.replace(day=15), backward=True),
            business_day(month_end(m), backward=True),
        ):
            add(
                Row(
                    CHECKING,
                    d,
                    INCOME_PER_CHECK,
                    "ACME ANALYTICS DES:PAYROLL ID:XXXXX4417 PPD",
                    "Acme Analytics",
                    "Income",
                )
            )
        add(
            Row(
                CHECKING,
                business_day(m),
                -RENT,
                "AVALON SOUTH LAMAR DES:WEB PMTS",
                "Avalon South Lamar",
                "Rent",
                is_fixed=True,
            )
        )
        add(
            Row(
                CHECKING,
                business_day(m.replace(day=8)),
                -electric[i],
                "CITY OF AUSTIN UTIL DES:UTIL PYMT",
                "Austin Energy",
                "Utilities",
                is_fixed=True,
            )
        )
        add(
            Row(
                CHECKING,
                business_day(m.replace(day=11)),
                -SPECTRUM,
                "SPECTRUM DES:SPECTRUM ID:8260161",
                "Spectrum",
                "Utilities",
                is_fixed=True,
            )
        )
        add(
            Row(
                CHECKING,
                business_day(m.replace(day=20)),
                -PROGRESSIVE,
                "PROGRESSIVE INS DES:INS PREM",
                "Progressive",
                "Insurance",
                is_fixed=True,
            )
        )
        add(
            Row(
                CHECKING,
                business_day(m.replace(day=25)),
                -NELNET,
                "NELNET DES:LOAN PYMT",
                "Nelnet",
                "Debt minimum",
                is_fixed=True,
            )
        )
        add(
            Row(
                CHECKING,
                business_day(m.replace(day=2)),
                -TRAVEL_FUND,
                "ONLINE TRANSFER TO SAV ...9031 TRAVEL FUND",
                "Travel fund savings",
                "Travel fund",
            )
        )
        add(
            Row(
                CHECKING,
                business_day(m.replace(day=16)),
                -HOME_FUND_SWEEP,
                "ONLINE TRANSFER TO SAV ...7702 HOME FUND",
                "Home fund savings",
                "Transfer",
            )
        )

        # Card: insurance and subscriptions at fixed prices.
        add(
            Row(
                CARD,
                m.replace(day=3),
                -LEMONADE,
                "LEMONADE INSURANCE NEW YORK NY",
                "Lemonade",
                "Insurance",
                is_fixed=True,
            )
        )
        for raw, merchant, price, day in SUBSCRIPTIONS:
            add(Row(CARD, m.replace(day=day), -price, raw, merchant, "Subscriptions"))

    # Card: variable categories, scaled so each (month, category) hits its target.
    catalogs = {
        "Dining and delivery": DINING,
        "Groceries": GROCERIES,
        "Shopping": SHOPPING,
        "Rideshare": RIDESHARE,
        "Entertainment": ENTERTAINMENT,
    }
    fixed_spend = -sum((r.amount for r in rows if r.category not in ("Income", "Transfer")), D(0))
    other_total = TOTAL_SPEND - fixed_spend - sum(TARGETS.values())
    targets = {**TARGETS, "Other": other_total}
    catalogs["Other"] = OTHER

    for category, catalog in catalogs.items():
        monthly = spread(targets[category], 6, rng)
        for i, m in enumerate(MONTHS):
            batch: list[Row] = []
            for raw, merchant, lo, hi, per_month in catalog:
                n = max(1, per_month + rng.choice([-1, 0, 0, 1]))
                for _ in range(n):
                    code = "".join(rng.choices("0123456789ABCDEFGHJKLMNPQRSTUVWXYZ", k=9))
                    amount = q(D(str(rng.uniform(lo, hi))))
                    batch.append(
                        Row(
                            CARD,
                            rand_day(rng, m),
                            -amount,
                            raw.replace("{code}", code),
                            merchant,
                            category,
                        )
                    )
            # Legitimate same-day repeats: never deduped.
            if category == "Dining and delivery" and m.month == 5:
                for _ in range(2):
                    batch.append(
                        Row(
                            CARD,
                            date(2026, 5, 14),
                            D("-5.45"),
                            "STARBUCKS STORE 11457 AUSTIN TX",
                            "Starbucks",
                            category,
                            note="same-day repeat",
                            scalable=False,
                        )
                    )
            if category == "Rideshare" and m.month == 8:
                for _ in range(2):
                    batch.append(
                        Row(
                            CARD,
                            date(2026, 8, 21),
                            D("-14.20"),
                            "UBER *TRIP HELP.UBER.COM CA",
                            "Uber",
                            category,
                            note="same-day repeat",
                            scalable=False,
                        )
                    )
            fixed = sum((-r.amount for r in batch if not r.scalable), D(0))
            flex = [r for r in batch if r.scalable]
            flex_sum = sum((-r.amount for r in flex), D(0))
            factor = (monthly[i] - fixed) / flex_sum
            for r in flex:
                r.amount = -q(-r.amount * factor)
            flex[-1].amount -= monthly[i] - (fixed + sum((-r.amount for r in flex), D(0)))
            assert all(r.amount < 0 for r in batch)
            rows.extend(batch)

    # Card autopay: checking pays last month's card charges; both sides are Transfer.
    card_by_month = {m: D(0) for m in MONTHS}
    for r in rows:
        if r.account == CARD:
            card_by_month[r.posted_on.replace(day=1)] -= r.amount
    previous = D("1912.37")  # March 2026 statement, before the fixture window
    for m in MONTHS:
        d = business_day(m.replace(day=22))
        add(
            Row(
                CHECKING,
                d,
                -previous,
                "CARD SERVICES DES:AUTOPAY ...8023",
                "Card payment",
                "Transfer",
            )
        )
        add(Row(CARD, d, previous, "AUTOMATIC PAYMENT - THANK YOU", "Card payment", "Transfer"))
        previous = card_by_month[m]

    rows.sort(key=lambda r: (r.posted_on, r.account, r.raw_description, r.amount))
    counters: dict[tuple[str, date], int] = {}
    for r in rows:
        key = (r.account, r.posted_on)
        counters[key] = counters.get(key, 0) + 1
        prefix = "C" if r.account == CARD else "K"
        r.reference = f"{prefix}{r.posted_on:%Y%m%d}{counters[key]:03d}"

    # Exact duplicates: the same row exported twice (overlapping statements).
    picks = [
        next(r for r in rows if r.merchant == "DoorDash" and r.posted_on.month == 4),
        next(r for r in rows if r.merchant == "Amazon" and r.posted_on.month == 6),
        next(r for r in rows if r.merchant == "H-E-B" and r.posted_on.month == 9),
    ]
    for p in picks:
        dup = Row(
            p.account,
            p.posted_on,
            p.amount,
            p.raw_description,
            p.merchant,
            p.category,
            p.is_fixed,
            note="duplicate",
            reference=p.reference,
        )
        rows.insert(rows.index(p) + 1, dup)
    return rows


# --- writers -----------------------------------------------------------------------
def labeled_csv(rows: list[Row]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(
        [
            "reference",
            "account",
            "posted_on",
            "amount",
            "raw_description",
            "merchant",
            "category",
            "is_fixed",
            "note",
        ]
    )
    for r in rows:
        w.writerow(
            [
                r.reference,
                r.account,
                r.posted_on.isoformat(),
                f"{r.amount:.2f}",
                r.raw_description,
                r.merchant,
                r.category,
                str(r.is_fixed).lower(),
                r.note,
            ]
        )
    return buf.getvalue()


def bank_csv(rows: list[Row]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["Date", "Description", "Amount", "Account", "Reference"])
    for r in rows:
        w.writerow(
            [
                f"{r.posted_on:%m/%d/%Y}",
                r.raw_description,
                f"{r.amount:.2f}",
                r.account,
                r.reference,
            ]
        )
    return buf.getvalue()


def ofx(rows: list[Row]) -> str:
    def stmttrn(r: Row) -> str:
        kind = "CREDIT" if r.amount > 0 else "DEBIT"
        name = r.raw_description.replace("&", "&amp;")[:32]
        return (
            f"<STMTTRN><TRNTYPE>{kind}<DTPOSTED>{r.posted_on:%Y%m%d}120000"
            f"<TRNAMT>{r.amount:.2f}<FITID>{r.reference}<NAME>{name}"
            f"<MEMO>{r.raw_description.replace('&', '&amp;')}</STMTTRN>"
        )

    start, end = "20260401", "20260930"
    checking = "\n".join(stmttrn(r) for r in rows if r.account == CHECKING)
    card = "\n".join(stmttrn(r) for r in rows if r.account == CARD)
    header = (
        "OFXHEADER:100\nDATA:OFXSGML\nVERSION:102\nSECURITY:NONE\nENCODING:USASCII\n"
        "CHARSET:1252\nCOMPRESSION:NONE\nOLDFILEUID:NONE\nNEWFILEUID:NONE\n\n"
    )
    signon = (
        "<SIGNONMSGSRSV1><SONRS><STATUS><CODE>0<SEVERITY>INFO</STATUS>"
        "<DTSERVER>20261001120000<LANGUAGE>ENG<FI><ORG>HOMEFUND DEMO BANK<FID>99999</FI>"
        "</SONRS></SIGNONMSGSRSV1>"
    )
    bank = (
        "<BANKMSGSRSV1><STMTTRNRS><TRNUID>1<STATUS><CODE>0<SEVERITY>INFO</STATUS><STMTRS>"
        "<CURDEF>USD<BANKACCTFROM><BANKID>111000025<ACCTID>4417<ACCTTYPE>CHECKING"
        f"</BANKACCTFROM><BANKTRANLIST><DTSTART>{start}<DTEND>{end}\n{checking}\n"
        "</BANKTRANLIST><LEDGERBAL><BALAMT>4210.55<DTASOF>20260930</LEDGERBAL>"
        "</STMTRS></STMTTRNRS></BANKMSGSRSV1>"
    )
    cc = (
        "<CREDITCARDMSGSRSV1><CCSTMTTRNRS><TRNUID>2<STATUS><CODE>0<SEVERITY>INFO</STATUS>"
        "<CCSTMTRS><CURDEF>USD<CCACCTFROM><ACCTID>8023</CCACCTFROM>"
        f"<BANKTRANLIST><DTSTART>{start}<DTEND>{end}\n{card}\n</BANKTRANLIST>"
        "<LEDGERBAL><BALAMT>-1874.20<DTASOF>20260930</LEDGERBAL>"
        "</CCSTMTRS></CCSTMTTRNRS></CREDITCARDMSGSRSV1>"
    )
    return f"{header}<OFX>\n{signon}\n{bank}\n{cc}\n</OFX>\n"


# --- golden scenario ---------------------------------------------------------------
RATE_PCT = D("6.27")
RATE_AS_OF = date(2026, 9, 24)
PROPERTY = {"value": D("450000"), "tax_2025": D("8100.00")}  # 1.8% effective
INSURANCE_PCT = D("0.5")  # annual, of price
PMI_PCT = D("0.5")  # annual, of loan, when down < 20%
CLOSING_PCT = D("3")
RESERVE_MONTHS = 2


def add_months(m: date, n: int) -> date:
    y, mo = divmod(m.month - 1 + n, 12)
    return date(m.year + y, mo + 1, 1)


def months_between(a: date, b: date) -> int:
    return (b.year - a.year) * 12 + (b.month - a.month)


def golden(rows: list[Row]) -> dict[str, Any]:
    price, down_pct, saved = D("420000.00"), D("10"), D("18000.00")
    clock = date(2026, 10, 1)
    move_in = date(2028, 6, 1)

    down = q(price * down_pct / 100)
    loan = price - down
    closing = q(price * CLOSING_PCT / 100)
    r = RATE_PCT / 100 / 12
    pi = q(loan * r / (1 - (1 + r) ** -360))
    tax_rate = PROPERTY["tax_2025"] / PROPERTY["value"] * 100
    tax = q(price * tax_rate / 100 / 12)
    ins = q(price * INSURANCE_PCT / 100 / 12)
    piti = pi + tax + ins
    pmi = q(loan * PMI_PCT / 100 / 12)
    reserves = (RESERVE_MONTHS * piti / 100).quantize(D(1), rounding=ROUND_HALF_UP) * 100
    cash_needed = down + closing + reserves
    gap = cash_needed - saved

    assert down == D("42000.00") and closing == D("12600.00"), (down, closing)
    assert D("3125") <= piti < D("3175"), piti
    assert reserves == D("6300") and cash_needed == D("60900.00") and gap == D("42900.00")

    kept = [x for x in rows if x.note != "duplicate"]
    income = sum((x.amount for x in kept if x.category == "Income"), D(0))
    spend = -sum((x.amount for x in kept if x.category not in ("Income", "Transfer")), D(0))
    take_home, spending = q(income / 6), q(spend / 6)
    saved_monthly = take_home - spending
    assert (take_home, spending, saved_monthly) == (D("6800.00"), D("5600.00"), D("1200.00"))

    by_cat: dict[str, Decimal] = {}
    counts: dict[str, int] = {}
    for x in kept:
        if x.category in ("Income", "Transfer"):
            continue
        by_cat[x.category] = by_cat.get(x.category, D(0)) - x.amount
        counts[x.category] = counts.get(x.category, 0) + 1
    categories = [
        {"category": c, "monthly_avg": f"{q(v / 6):.2f}", "transactions": counts[c]}
        for c, v in sorted(by_cat.items(), key=lambda kv: -kv[1])
    ]
    fixed = {c: q(by_cat[c] / 6) for c in ("Rent", "Utilities", "Insurance", "Debt minimum")}

    months_at_pace = (gap / saved_monthly).to_integral_value(rounding=ROUND_CEILING)
    reach = add_months(clock, int(months_at_pace))
    months_to_move_in = months_between(clock, move_in)
    needed = q(gap / months_to_move_in)
    assert months_at_pace == 36 and reach == date(2029, 10, 1)
    assert months_to_move_in == 20 and needed == D("2145.00")

    illustrative = {
        "Dining and delivery": D("300"),
        "Travel fund": D("280"),
        "Shopping": D("180"),
        "Rideshare": D("120"),
        "Subscriptions": D("72"),
    }
    with_cuts = saved_monthly + sum(illustrative.values(), D(0))
    assert with_cuts == D("2152") and saved + with_cuts * 20 >= cash_needed

    def money(x: Decimal) -> str:
        return f"{q(x):.2f}"

    return {
        "name": "walkthrough_420k_10pct_jun2028",
        "description": "The design's request walkthrough: $420,000 home, 10% down, June 2028 "
        "move-in. Every expected number is computed with Decimal by fixtures/generate.py.",
        "user_id": USER_ID,
        "clock": {"type": "FixedClock", "date": clock.isoformat()},
        "request": {
            "text": "I want a $420,000 home with 10% down by June 2028.",
            "goal": {
                "price": money(price),
                "zip": "78704",
                "down_pct": "10",
                "move_in": move_in.isoformat(),
                "saved": money(saved),
            },
        },
        "conventions": {
            "projection": "points[0] is the clock's month (2026-10) with balance=start; each "
            "later point adds `monthly`; reach_month is the first point with balance >= target",
            "months_until_move_in": "calendar months from the clock's month to the move-in month",
            "monthly_needed": "gap / months_until_move_in, rounded half-up to cents",
            "reserves": "reserve_months x PITI, rounded half-up to the nearest $100",
            "piti": "principal+interest (30-year fixed, rounded to cents) + property tax + "
            "insurance; PMI is reported separately and not part of PITI or reserves",
            "cashflow_window": "the last 6 full months before the clock: Apr-Sep 2026",
            "spending": "outflows in every category except Income and Transfer, after dedupe",
        },
        "mock_inputs": {
            "fred_fixture": "fixtures/mocks/fred_mortgage30us.json",
            "rentcast_property_fixture": "fixtures/mocks/rentcast_property.json",
            "rentcast_value_fixture": "fixtures/mocks/rentcast_value.json",
            "rate_pct": str(RATE_PCT),
            "rate_as_of": RATE_AS_OF.isoformat(),
            "property_tax_rate_pct": format(tax_rate.normalize(), "f"),
            "property_tax_source": "RentCast record in ZIP 78704: 2025 tax $8,100 on a "
            "$450,000 value",
            "insurance_rate_pct": str(INSURANCE_PCT),
            "pmi_rate_pct": str(PMI_PCT),
            "closing_cost_pct": str(CLOSING_PCT),
            "reserve_months": RESERVE_MONTHS,
        },
        "expected": {
            "home_cost": {
                "price": money(price),
                "down_pct": "10",
                "down_payment": money(down),
                "loan_amount": money(loan),
                "closing_cost_pct": str(CLOSING_PCT),
                "closing_costs": money(closing),
                "reserve_months": RESERVE_MONTHS,
                "reserves": money(reserves),
                "cash_needed": money(cash_needed),
                "rate_pct": str(RATE_PCT),
                "rate_as_of": RATE_AS_OF.isoformat(),
                "principal_interest_monthly": money(pi),
                "property_tax_rate_pct": format(tax_rate.normalize(), "f"),
                "property_tax_monthly": money(tax),
                "insurance_rate_pct": str(INSURANCE_PCT),
                "insurance_monthly": money(ins),
                "piti_monthly": money(piti),
                "pmi_rate_pct": str(PMI_PCT),
                "pmi_monthly": money(pmi),
                "monthly_payment": money(piti + pmi),
            },
            "piti_range": ["3125.00", "3174.99"],
            "cashflow": {
                "months": 6,
                "period_start": "2026-04-01",
                "period_end": "2026-09-01",
                "take_home_monthly": money(take_home),
                "spending_monthly": money(spending),
                "saved_monthly": money(saved_monthly),
                "by_category": categories,
                "fixed_bills_monthly": money(sum(fixed.values(), D(0))),
                "fixed_by_category": {c: money(v) for c, v in fixed.items()},
                "subscriptions_count": len(SUBSCRIPTIONS),
            },
            "saved_so_far": money(saved),
            "gap": money(gap),
            "current_pace": {
                "monthly": money(saved_monthly),
                "months_to_goal": int(months_at_pace),
                "reach_month": reach.isoformat(),
                "months_late": months_between(move_in, reach),
                "on_track": False,
            },
            "deadline": {
                "move_in_month": move_in.isoformat(),
                "months_until_move_in": months_to_move_in,
                "monthly_needed": money(needed),
                "gap_per_month": money(needed - saved_monthly),
            },
            "cuts": {
                "min_total_monthly": money(needed - saved_monthly),
                "protected_untouched": ["Debt minimum", "Insurance", "Rent", "Utilities"],
                "walkthrough_illustrative": [
                    {"category": c, "amount": money(a)} for c, a in illustrative.items()
                ],
                "walkthrough_total": money(sum(illustrative.values(), D(0))),
                "note": "The solver may choose differently; it must reach min_total_monthly "
                "without touching protected categories or cutting more than a category spends.",
            },
            "with_walkthrough_cuts": {
                "monthly": money(with_cuts),
                "months_to_goal": 20,
                "reach_month": move_in.isoformat(),
                "on_track": True,
            },
        },
        "dataset": {
            "files": [
                "fixtures/demo_user/transactions_labeled.csv",
                "fixtures/demo_user/statement.csv",
                "fixtures/demo_user/statement.ofx",
            ],
            "rows_total": len(rows),
            "rows_after_dedupe": len(kept),
            "exact_duplicates": sum(1 for x in rows if x.note == "duplicate"),
            "same_day_repeats": sum(1 for x in rows if x.note == "same-day repeat"),
        },
    }


def fred_mock() -> dict[str, Any]:
    weeks = [RATE_AS_OF - timedelta(weeks=i) for i in range(11, -1, -1)]
    values = [
        "6.41",
        "6.38",
        "6.35",
        "6.39",
        "6.36",
        "6.33",
        "6.34",
        "6.30",
        "6.31",
        "6.29",
        "6.28",
        "6.27",
    ]
    return {
        "realtime_start": "2026-10-01",
        "realtime_end": "2026-10-01",
        "observation_start": weeks[0].isoformat(),
        "observation_end": RATE_AS_OF.isoformat(),
        "units": "lin",
        "output_type": 1,
        "file_type": "json",
        "order_by": "observation_date",
        "sort_order": "asc",
        "count": len(weeks),
        "offset": 0,
        "limit": 100000,
        "observations": [
            {
                "realtime_start": "2026-10-01",
                "realtime_end": "2026-10-01",
                "date": w.isoformat(),
                "value": v,
            }
            for w, v in zip(weeks, values, strict=True)
        ],
    }


ADDRESS = "4512 Larkspur Bend, Austin, TX 78704"


def rentcast_property() -> list[dict[str, Any]]:
    return [
        {
            "id": "4512-Larkspur-Bend,-Austin,-TX-78704",
            "formattedAddress": ADDRESS,
            "addressLine1": "4512 Larkspur Bend",
            "addressLine2": None,
            "city": "Austin",
            "state": "TX",
            "zipCode": "78704",
            "county": "Travis",
            "latitude": 30.2401,
            "longitude": -97.7712,
            "propertyType": "Single Family",
            "bedrooms": 3,
            "bathrooms": 2,
            "squareFootage": 1540,
            "lotSize": 6970,
            "yearBuilt": 1984,
            "taxAssessments": {
                "2025": {"year": 2025, "value": 450000, "land": 210000, "improvements": 240000}
            },
            "propertyTaxes": {"2025": {"year": 2025, "total": 8100}},
            "_synthetic": "Fictional address for Home Fund fixtures",
        }
    ]


def rentcast_value() -> dict[str, Any]:
    return {
        "price": 450000,
        "priceRangeLow": 427000,
        "priceRangeHigh": 473000,
        "latitude": 30.2401,
        "longitude": -97.7712,
        "subjectProperty": {
            "formattedAddress": ADDRESS,
            "zipCode": "78704",
            "propertyType": "Single Family",
        },
        "comparables": [],
    }


def render() -> dict[Path, str]:
    rows = build_rows(random.Random(SEED))

    def js(obj: Any) -> str:
        return json.dumps(obj, indent=2) + "\n"

    return {
        ROOT / "demo_user" / "transactions_labeled.csv": labeled_csv(rows),
        ROOT / "demo_user" / "statement.csv": bank_csv(rows),
        ROOT / "demo_user" / "statement.ofx": ofx(rows),
        ROOT / "mocks" / "fred_mortgage30us.json": js(fred_mock()),
        ROOT / "mocks" / "rentcast_property.json": js(rentcast_property()),
        ROOT / "mocks" / "rentcast_value.json": js(rentcast_value()),
        ROOT / "golden_scenario.json": js(golden(rows)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    stale = []
    for path, text in render().items():
        if args.check:
            if not path.exists() or path.read_text(encoding="utf-8") != text:
                stale.append(str(path.relative_to(ROOT.parent)))
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
        print(f"wrote {path.relative_to(ROOT.parent)}")
    if stale:
        print(
            "stale fixtures, run `uv run python fixtures/generate.py`: " + ", ".join(stale),
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
