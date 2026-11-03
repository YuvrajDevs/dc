"""Build the clean synthetic world: three sources that agree perfectly.

All money is integer minor units (cents, pence, paise). No floats touch an amount.
"""

from __future__ import annotations

import math
import random
from datetime import date, datetime, timedelta

CURRENCIES = ["USD", "EUR", "GBP", "INR"]
# USD per 1 unit of local currency, in millionths (integer maths only)
FX_START_MICRO = {"USD": 1_000_000, "EUR": 1_080_000, "GBP": 1_270_000, "INR": 12_000}
TIERS = ["A", "B", "C"]
# (tier, currency) -> (percentage in basis points, fixed fee in minor units)
FEE_TABLE = {
    ("A", "USD"): (290, 30), ("B", "USD"): (250, 25), ("C", "USD"): (220, 20),
    ("A", "EUR"): (140, 25), ("B", "EUR"): (120, 20), ("C", "EUR"): (100, 15),
    ("A", "GBP"): (150, 20), ("B", "GBP"): (130, 18), ("C", "GBP"): (110, 15),
    ("A", "INR"): (200, 300), ("B", "INR"): (180, 250), ("C", "INR"): (160, 200),
}  # fmt: skip
DAY = 86400


def fee_for(amount_minor: int, tier: str, currency: str) -> int:
    bps, fixed = FEE_TABLE[(tier, currency)]
    return (amount_minor * bps + 5000) // 10000 + fixed  # round half up


def to_base_minor(amount_minor: int, rate_micro: int) -> int:
    return (amount_minor * rate_micro + 500_000) // 1_000_000  # round half up


def iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def build_merchants(rng: random.Random, n: int) -> list[dict]:
    merchants = []
    for i in range(n):
        merchants.append(
            {
                "merchant_id": f"m{i + 1:02d}",
                "name": f"Merchant {i + 1:02d}",
                "currency": CURRENCIES[i % len(CURRENCIES)],
                "fee_tier": rng.choice(TIERS),
            }
        )
    return merchants


def build_fx(rng: random.Random, start: date, days: int) -> dict[tuple[date, str], int]:
    """A gentle daily random walk per currency, covering the data window plus settlement."""
    rates: dict[tuple[date, str], int] = {}
    for ccy in CURRENCIES:
        rate = FX_START_MICRO[ccy]
        for d in range(days + 6):
            step = rng.randint(-30, 30)  # up to +/-0.3% a day
            rate = max(1, rate + rate * step // 10_000)
            rates[(start + timedelta(days=d), ccy)] = rate
    return rates


def build_payments(rng: random.Random, cfg, merchants: list[dict]) -> list[dict]:
    payments: list[dict] = []
    for d in range(cfg.days):
        day = datetime.combine(cfg.start + timedelta(days=d), datetime.min.time())
        for _ in range(cfg.txns_per_day):
            m = rng.choice(merchants)
            major = math.exp(rng.gauss(3.4, 1.0))  # median about 30
            minor = max(100, min(500_000, int(round(major * 100))))
            if m["currency"] == "INR":
                minor *= 80
            if rng.random() < cfg.near_midnight_share:
                second = DAY - rng.randint(5, 240)
                near_midnight = True
            else:
                second = rng.randint(0, DAY - 301)
                near_midnight = False
            payments.append(
                {
                    "merchant_id": m["merchant_id"],
                    "currency": m["currency"],
                    "fee_tier": m["fee_tier"],
                    "amount_minor": minor,
                    "captured_at": day + timedelta(seconds=second),
                    "near_midnight": near_midnight,
                }
            )
    payments.sort(key=lambda p: (p["captured_at"], p["merchant_id"], p["amount_minor"]))
    return payments
