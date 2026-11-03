"""The defect classes the engine must find (or correctly leave alone)."""

from __future__ import annotations

# name -> (category, level, description)
DEFECT_CLASSES: dict[str, tuple[str, str, str]] = {
    "duplicate_ledger": ("error", "txn", "The same payment is booked twice in the ledger"),
    "missing_in_ledger": ("error", "txn", "Processor captured a payment the ledger never booked"),
    "missing_in_processor": (
        "error",
        "txn",
        "Ledger booked a payment the processor never captured",
    ),
    "amount_mismatch": ("error", "txn", "Ledger and processor disagree on the amount"),
    "fee_variance": ("error", "txn", "Processor fee differs from the agreed fee schedule"),
    "fx_rounding": ("benign", "txn", "Base-currency amount differs by a rounding error"),
    "cutoff_timing": ("benign", "txn", "Booked just after midnight, so on a different date"),
    "ref_noise": ("benign", "txn", "Ledger order reference is mangled but the payment matches"),
    "payout_late": ("benign", "payout", "Payout reaches the bank days later than expected"),
    "payout_missing": ("error", "payout", "Payout never reaches the bank"),
    "payout_short": ("error", "payout", "Bank received less than the payout total"),
    "payout_split": ("benign", "payout", "Payout arrives as two bank lines that sum correctly"),
    "bank_ref_missing": ("benign", "payout", "Bank line arrives without its payout reference"),
    "bank_orphan": ("error", "bank", "Bank line that belongs to no payout"),
}

TXN_CLASSES = [k for k, v in DEFECT_CLASSES.items() if v[1] == "txn"]
PAYOUT_CLASSES = [k for k, v in DEFECT_CLASSES.items() if v[1] == "payout"]
