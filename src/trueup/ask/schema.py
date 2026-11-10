"""What a question may touch. Everything else (raw rows, quarantine, run ledger, answer key) is out."""

from __future__ import annotations

ALLOWED: dict[str, tuple[str, ...]] = {
    "marts": (
        "dim_merchant", "dim_fee_schedule", "dim_fx_rate",
        "fct_ledger_entry", "fct_processor_txn", "fct_payout", "fct_bank_line",
    ),
    "recon": ("findings", "links", "pending_items"),
    "ops": ("exceptions",),
}  # fmt: skip
ALLOWED_QUALIFIED = {f"{s}.{t}" for s, ts in ALLOWED.items() for t in ts}
ALLOWED_PLAN_NAMES = {f"{s}.{t}" for s, ts in ALLOWED.items() for t in ts}

DENIED_FUNCTIONS = {
    "glob", "getenv", "current_setting", "query", "query_table", "sniff_csv", "which_secret",
    "load_extension", "install_extension", "system", "shell", "os", "pg_read_file",
    "read_text", "read_blob", "list_directory", "unnest_file",
}  # fmt: skip
DENIED_FUNCTION_PREFIXES = ("read_", "duckdb_", "pragma_", "parquet_", "iceberg_", "delta_", "csv_",
                            "json_each_file", "glob_", "http_", "s3_", "gcs_")  # fmt: skip

DESCRIPTIONS = {
    "marts.dim_merchant": "merchants and their fee tier",
    "marts.dim_fee_schedule": "versioned fee schedule (bps and fixed fee per tier and currency)",
    "marts.dim_fx_rate": "daily USD conversion rates (usd_micro_per_unit = USD per unit, in millionths)",
    "marts.fct_ledger_entry": "internal ledger entries",
    "marts.fct_processor_txn": "processor transactions with expected_fee_minor and fee_delta_minor",
    "marts.fct_payout": "processor payouts beside what their transactions add up to",
    "marts.fct_bank_line": "bank lines (reference is a payout id, or empty)",
    "recon.findings": "every disagreement found, with class, category, entities (JSON), "
                      "amount_at_stake_minor, currency, confidence, reason, status",
    "recon.links": "which records were matched to which",
    "recon.pending_items": "payouts not yet due, so not yet missing",
    "ops.exceptions": "the exception queue: finding_id, status, note, updated_by",
}  # fmt: skip
