"""Schema contracts: what each source file must look like before it may enter the warehouse.

Files are read as text exactly as received. A contract says which columns are required,
what type each must convert to, and which simple business rules every row must satisfy.
"""

from __future__ import annotations

from dataclasses import dataclass

CURRENCIES = ("USD", "EUR", "GBP", "INR")
REGIONS = ("NA", "EU", "AP", "LA")
NETWORKS = ("visa", "mastercard")
PRODUCTS = ("debit", "credit_classic", "credit_premium", "commercial")
DISPUTE_CATEGORIES = (
    "fraud_cnp",
    "not_received",
    "not_as_described",
    "credit_not_processed",
    "duplicate",
    "cancelled_recurring",
)


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
    # ---- card network --------------------------------------------------------------------
    "merchant_profiles": Contract(
        "merchant_profiles",
        (
            _c("merchant_id"),
            _c("mcc"),
            _c("mcc_description"),
            _c("mcc_group", allowed=("everyday", "retail", "travel", "digital", "high_risk")),
            _c("country"),
            _c("region", allowed=REGIONS),
            _c("cnp_share_bps", "BIGINT", minimum=0),
        ),
        key="merchant_id",
        row_rules=(("mcc must be four digits", "regexp_full_match(mcc, '[0-9]{4}')"),),
    ),
    "card_bins": Contract(
        "card_bins",
        (
            _c("bin"),
            _c("network", allowed=NETWORKS),
            _c("product", allowed=PRODUCTS),
            _c("issuer_id"),
            _c("issuer_name"),
            _c("issuer_country"),
            _c("issuer_region", allowed=REGIONS),
        ),
        key="bin",
        row_rules=(("bin must be six digits", "regexp_full_match(bin, '[0-9]{6}')"),),
    ),
    "authorizations": Contract(
        "authorizations",
        (
            _c("auth_id"),
            _c("order_ref", nullable=True),
            _c("merchant_id"),
            _c("card_token"),
            _c("bin"),
            _c("currency", allowed=CURRENCIES),
            _c("amount_minor", "BIGINT", minimum=1),
            _c("entry_mode", allowed=("chip", "contactless", "magstripe", "ecommerce")),
            _c("card_present", allowed=("true", "false")),
            _c("three_ds", allowed=("authenticated", "none", "n/a")),
            _c("response_code"),
            _c("approved", allowed=("true", "false")),
            _c("requested_at", "TIMESTAMP"),
            _c("retry_of", nullable=True),
        ),
        key="auth_id",
        row_rules=(
            (
                "approved must agree with response code 00",
                "(approved = 'true') = (response_code = '00')",
            ),
            (
                "card-present payments cannot be e-commerce",
                "NOT (card_present = 'true' AND entry_mode = 'ecommerce')",
            ),
        ),
    ),
    "clearing_records": Contract(
        "clearing_records",
        (
            _c("clearing_id"),
            _c("auth_id"),
            _c("order_ref"),
            _c("txn_id"),
            _c("merchant_id"),
            _c("network", allowed=NETWORKS),
            _c("currency", allowed=CURRENCIES),
            _c("amount_minor", "BIGINT", minimum=1),
            _c("interchange_bps", "BIGINT", minimum=0),
            _c("interchange_minor", "BIGINT", minimum=0),
            _c("scheme_fee_minor", "BIGINT", minimum=0),
            _c("qualification", allowed=("standard", "downgraded")),
            _c("cleared_at", "TIMESTAMP"),
        ),
        key="clearing_id",
        row_rules=(
            (
                "fees cannot exceed the amount",
                "interchange_minor + scheme_fee_minor < amount_minor",
            ),
        ),
    ),
    "refunds": Contract(
        "refunds",
        (
            _c("refund_id"),
            _c("order_ref"),
            _c("merchant_id"),
            _c("currency", allowed=CURRENCIES),
            _c("amount_minor", "BIGINT", minimum=1),
            _c("refunded_at", "TIMESTAMP"),
        ),
        key="refund_id",
        allow_empty=True,
    ),
    "disputes": Contract(
        "disputes",
        (
            _c("dispute_id"),
            _c("order_ref"),
            _c("merchant_id"),
            _c("network", allowed=NETWORKS),
            _c("reason_category", allowed=DISPUTE_CATEGORIES),
            _c("reason_code"),
            _c("reason_label"),
            _c("currency", allowed=CURRENCIES),
            _c("amount_minor", "BIGINT", minimum=1),
            _c("fee_minor", "BIGINT", minimum=0),
            _c("opened_at", "TIMESTAMP"),
            _c("response_due", "DATE"),
            _c("responded_on", "DATE", nullable=True),
            _c("status", allowed=("open", "closed")),
            _c(
                "outcome",
                allowed=("pending", "won", "lost", "accepted", "reversed_liability_shift"),
            ),
        ),
        key="dispute_id",
        allow_empty=True,
        row_rules=(
            ("an open dispute must be pending", "status = 'closed' OR outcome = 'pending'"),
            (
                "a won or lost dispute needs a response date",
                "outcome NOT IN ('won', 'lost') OR responded_on IS NOT NULL",
            ),
        ),
    ),
    "interchange_schedule": Contract(
        "interchange_schedule",
        (
            _c("product", allowed=PRODUCTS),
            _c("channel", allowed=("cp", "cnp")),
            _c("base_bps", "BIGINT", minimum=0),
            _c("fixed_minor", "BIGINT", minimum=0),
            _c("eu_cap_bps", "BIGINT", minimum=0),
            _c("cross_border_add_bps", "BIGINT", minimum=0),
            _c("everyday_discount_bps", "BIGINT", minimum=0),
            _c("effective_from", "DATE"),
        ),
        key="product",
    ),
}

# Files that must never enter the warehouse. The answer key belongs to the grader only.
FORBIDDEN_FILES = {"answer_key.csv", "expected_links.csv"}
