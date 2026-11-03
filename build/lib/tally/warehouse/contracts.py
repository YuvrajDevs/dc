"""Schema contracts: what each source file must look like before it may enter the warehouse.

Files are read as text exactly as received. A contract says which columns are required,
what type each must convert to, and which simple business rules every row must satisfy.
"""

from __future__ import annotations

from dataclasses import dataclass

CURRENCIES = ("USD", "EUR", "GBP", "INR")


@dataclass(frozen=True)
class Column:
    name: str
    type: str = "VARCHAR"  # VARCHAR, BIGINT, DATE, TIMESTAMP
    nullable: bool = False
    minimum: int | None = None
    allowed: tuple[str, ...] | None = None


@dataclass(frozen=True)
class Contract:
    source: str
    columns: tuple[Column, ...]
    key: str
    allow_empty: bool = False
    # (message, SQL predicate that must hold). Evaluated on the typed values; unknown counts as ok.
    row_rules: tuple[tuple[str, str], ...] = ()

    @property
    def names(self) -> list[str]:
        return [c.name for c in self.columns]


def _c(name, type="VARCHAR", **kw) -> Column:
    return Column(name, type, **kw)


CONTRACTS: dict[str, Contract] = {
    "ledger_entries": Contract(
        "ledger_entries",
        (
            _c("ledger_id"),
            _c("order_ref", nullable=True),
            _c("merchant_id"),
            _c("currency", allowed=CURRENCIES),
            _c("amount_minor", "BIGINT", minimum=1),
            _c("amount_base_minor", "BIGINT", minimum=1),
            _c("booked_at", "TIMESTAMP"),
        ),
        key="ledger_id",
    ),
    "processor_txns": Contract(
        "processor_txns",
        (
            _c("txn_id"),
            _c("order_ref"),
            _c("merchant_id"),
            _c("currency", allowed=CURRENCIES),
            _c("gross_minor", "BIGINT", minimum=1),
            _c("fee_minor", "BIGINT", minimum=0),
            _c("net_minor", "BIGINT", minimum=1),
            _c("captured_at", "TIMESTAMP"),
            _c("payout_id"),
        ),
        key="txn_id",
        row_rules=(
            (
                "net_minor must equal gross_minor - fee_minor",
                "net_minor = gross_minor - fee_minor",
            ),
        ),
    ),
    "processor_payouts": Contract(
        "processor_payouts",
        (
            _c("payout_id"),
            _c("merchant_id"),
            _c("currency", allowed=CURRENCIES),
            _c("payout_date", "DATE"),
            _c("txn_count", "BIGINT", minimum=1),
            _c("net_minor_total", "BIGINT", minimum=1),
        ),
        key="payout_id",
    ),
    "bank_lines": Contract(
        "bank_lines",
        (
            _c("bank_line_id"),
            _c("reference", nullable=True),
            _c("currency", allowed=CURRENCIES),
            _c("amount_minor", "BIGINT", minimum=1),
            _c("value_date", "DATE"),
            _c("description", nullable=True),
        ),
        key="bank_line_id",
    ),
    "merchants": Contract(
        "merchants",
        (
            _c("merchant_id"),
            _c("name"),
            _c("currency", allowed=CURRENCIES),
            _c("fee_tier", allowed=("A", "B", "C")),
        ),
        key="merchant_id",
    ),
    "fee_schedule": Contract(
        "fee_schedule",
        (
            _c("fee_tier", allowed=("A", "B", "C")),
            _c("currency", allowed=CURRENCIES),
            _c("bps", "BIGINT", minimum=0),
            _c("fixed_minor", "BIGINT", minimum=0),
            _c("effective_from", "DATE"),
        ),
        key="fee_tier",
    ),
    "fx_rates": Contract(
        "fx_rates",
        (
            _c("rate_date", "DATE"),
            _c("currency", allowed=CURRENCIES),
            _c("usd_micro_per_unit", "BIGINT", minimum=1),
        ),
        key="rate_date",
    ),
}

# Files that must never enter the warehouse. The answer key belongs to the grader only.
FORBIDDEN_FILES = {"answer_key.csv", "expected_links.csv"}
