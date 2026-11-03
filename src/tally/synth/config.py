from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass(frozen=True)
class Rates:
    """How often each defect is injected. Rates apply to the eligible population."""

    # Transaction level, per eligible transaction
    duplicate_ledger: float = 0.004
    missing_in_ledger: float = 0.003
    missing_in_processor: float = 0.003
    amount_mismatch: float = 0.003
    fee_variance: float = 0.010
    fx_rounding: float = 0.030  # of non-USD transactions
    cutoff_timing: float = 0.50  # of near-midnight transactions
    ref_noise: float = 0.030
    # Payout level, per payout
    payout_late: float = 0.080
    payout_missing: float = 0.030
    payout_short: float = 0.030
    payout_split: float = 0.080
    bank_orphan: float = 0.030  # extra unmatched bank lines, as a fraction of payouts


@dataclass(frozen=True)
class Hardness:
    """Knobs that make the world adversarial. All zero means the easy world."""

    round_amount_share: float = 0.0  # payments with round amounts, so many look alike
    compound_rate: float = 0.0  # chance a defective payment gets a second, different defect
    typo_share: float = 0.0  # share of reference noise that is a digit swap onto another real ref
    bank_ref_missing: float = 0.0  # bank lines that arrive without their payout reference


EASY = Hardness()
HARD = Hardness(round_amount_share=0.25, compound_rate=0.06, typo_share=0.40, bank_ref_missing=0.06)
PROFILES = {"easy": EASY, "hard": HARD}


@dataclass(frozen=True)
class Config:
    seed: int = 42
    start: date = date(2026, 1, 1)
    days: int = 30
    merchants: int = 12
    txns_per_day: int = 400
    near_midnight_share: float = 0.02
    rates: Rates = field(default_factory=Rates)
    hardness: Hardness = field(default_factory=Hardness)
