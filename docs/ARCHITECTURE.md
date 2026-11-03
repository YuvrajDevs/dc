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

## Warehouse (Phase 2)

DuckDB file with five schemas:

| Schema | Holds | Written by |
|---|---|---|
| `raw` | Rows exactly as received (all text) plus batch id, sequence, row number, load time | the loader, append-only |
| `quarantine` | Rows that failed their contract, with the reason and the original values | the loader |
| `ops` | `load_log`: every batch, with status and reasons | the loader |
| `staging` | Typed, de-duplicated rows (dbt) | dbt |
| `marts` | Dimensions and facts ready for reconciliation (dbt) | dbt |

### The quality gate
A **batch** is a folder of CSV files. Its identity is a hash of the file contents.

1. **Repeat batch:** same contents as one already loaded, so it is skipped. Loading twice changes nothing.
2. **Structure:** a missing required column or an empty file rejects the **whole batch**. Nothing is written.
3. **Rows:** each row is checked against its contract (required values, types, minimums, allowed values, simple cross-field rules). Bad rows are quarantined with a reason, **unless** more than 1% of a file's rows fail, in which case the whole batch is rejected.
4. **Atomic write:** accepted rows go in one transaction; a failure rolls everything back.
5. **Grader files** (`answer_key.csv`, `expected_links.csv`) are always ignored and never enter the warehouse. A dbt test enforces this.

### Staging and marts
- Staging keeps one row per id, the **latest delivery wins**, so a correction replaces an earlier value while `raw` keeps the history. Two different ledger ids with the same order reference are **both kept**: that is a real duplicate booking for the engine to find.
- `dim_fee_schedule` is versioned (`valid_from`, `valid_to`). `fct_processor_txn` carries the fee the schedule says the transaction should have paid on its capture date, and the difference.
- `fct_payout` sets each payout total beside what its transactions add up to. A second gate: if a transaction was quarantined, this check fails the build loudly.

### Tests that protect it
Loading twice, re-delivering the same rows in a new batch, late and shuffled arrival, corrections, a blocked corrupted batch and the payout-total check are all automated.

## Reconciliation engine (Phase 3)
`recon` schema, rebuilt on every run, written by SQL steps in `src/tally/recon/engine.py`.

**Ledger to transaction**, strongest evidence first, only unmatched records move down:
1. Reference match (exact, normalised, or prefix-stripped), accepted only if merchant, currency and time also agree.
2. Strong = reference **and** amount agree. The earliest booking is primary; further strong entries are duplicate bookings.
3. Attribute match: same merchant, currency and amount inside a time window.
4. Fuzzy: amount within 12%, tight window, unique from both sides (confidence 0.60).
5. Last resort: reference-only match between two unclaimed records, reported as an amount mismatch.

**Payout to bank:** payout reference on the bank line, then amount and date, then a fuzzy tier for short payouts. A payout may match several bank lines (a split).

**Findings:** each has a class, category (error or benign), the records involved, amount at stake, currency, confidence, a plain-language reason and a stable id. Benign look-alikes are `explained`; errors are `open`. A payout with no bank line is `pending` until its window has passed (as-of date), then `payout_missing`.

**Exception queue:** `ops.exceptions` holds one row per finding id with a status (open, explained, resolved, auto_cleared) and `ops.exception_events` appends every change with actor, time and note. Re-runs never overwrite a human decision; a finding that stops being reported auto-clears and reopens if it returns.

## Grader (Phase 4)
`src/tally/grade.py` is the only code that reads `answer_key.csv` and `expected_links.csv`, directly from the world folder. It scores per class, link accuracy and benign false alarms, writes JSON and Markdown scorecards, and checks them against the frozen floors in `benchmarks/floors.json`.

## Service, dashboard and assistant (Phases 6 and 7)
- `src/tally/api/` is a FastAPI app holding **one locked-down DuckDB connection** (external access off, configuration locked) and giving each request its own cursor. Endpoints: `/api/overview`, `/api/exceptions` (+ `.csv`, detail, decision), `/api/payouts`, `/api/scorecard`, `/api/runs`, `/api/ask`.
- `dashboard/` is a Next.js App Router app. Next proxies `/api/*` to the service, so the browser talks to a single origin.
- `src/tally/ask/` turns a question into SQL and validates it three ways before it runs; see [ASSISTANT.md](ASSISTANT.md).
