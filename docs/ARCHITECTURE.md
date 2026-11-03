# Architecture

```
 synthetic world ──► raw ──► staging ──► marts ──► reconciliation ──► findings
  (seeded, with       (as       (typed,    (joined,     (tiered          │
   answer key)       received)  cleaned)   reference     matching)       ▼
                                           data)                    grader ◄── answer key
                                                                       │
                                  orchestration (Airflow) ─────────────┤
                                                                       ▼
                                                      dashboard (Next.js) + validated Q&A
```

## Sources and keys
| Source | Table | Key facts |
|---|---|---|
| Internal ledger | `ledger_entries` | `order_ref` (can be mangled), amount, base-currency amount, booked time |
| Processor | `processor_txns`, `processor_payouts` | `order_ref`, gross, fee, net, `payout_id` |
| Bank | `bank_lines` | `reference` (a payout id, or empty), amount, value date |

Links: ledger to processor by `order_ref`; transaction to payout by `payout_id`; payout to bank by `reference`. A payout is a **sum** of many transactions, and a payout can arrive as **more than one** bank line.

## Defect classes
Errors the engine must raise: `duplicate_ledger`, `missing_in_ledger`, `missing_in_processor`, `amount_mismatch`, `fee_variance`, `payout_missing`, `payout_short`, `bank_orphan`.

Benign look-alikes it must leave alone (classify, do not alarm): `fx_rounding`, `cutoff_timing`, `ref_noise`, `payout_late`, `payout_split`.

## Conventions
- Amounts are integer minor units. Percentage fees and FX use integer arithmetic with round-half-up.
- All timestamps are UTC. Dates are ISO 8601.
- The generator is a pure function of its config: independent random streams per stage, sorted output, SHA-256 per file in `manifest.json`.
