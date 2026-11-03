# Data dictionary (marts)

All amounts are integer minor units (cents, pence, paise). All times are UTC.

| Table | Grain | Key columns |
|---|---|---|
| `marts.dim_merchant` | one row per merchant | `merchant_id`, `currency`, `fee_tier` |
| `marts.dim_fee_schedule` | one row per tier, currency and version | `fee_tier`, `currency`, `bps`, `fixed_minor`, `valid_from`, `valid_to` (exclusive) |
| `marts.dim_fx_rate` | one row per date and currency | `usd_micro_per_unit` (USD per one unit, in millionths) |
| `marts.fct_ledger_entry` | one row per ledger entry | `ledger_id`, `order_ref_raw`, `order_ref_norm`, `amount_minor`, `amount_base_minor`, `booked_at` |
| `marts.fct_processor_txn` | one row per processor transaction | `txn_id`, `order_ref_norm`, `gross_minor`, `fee_minor`, `net_minor`, `payout_id`, `expected_fee_minor`, `fee_delta_minor` |
| `marts.fct_payout` | one row per payout | `payout_id`, `net_minor_total`, `net_minor_actual`, `net_minor_delta` |
| `marts.fct_bank_line` | one row per bank line | `bank_line_id`, `reference` (a payout id, or empty), `amount_minor`, `value_date` |

`order_ref_norm` is the reference upper-cased and trimmed, empty becomes null. Further matching (mangled and missing references) belongs to the engine in Phase 3.
