# Benchmarks

Everything here is produced by commands in this repo and saved under `benchmarks/`. Numbers below are copied from those files.

## How accuracy is measured
- A world is generated with hidden, recorded defects (`answer_key.csv`) and true pairings (`expected_links.csv`). The engine never sees them.
- A finding counts as **right** only if its class *and* the exact set of records involved match a key entry.
- **Precision** = right findings / all findings. **Recall** = right findings / defects in the key.
- **Benign false alarm**: a benign look-alike (late payout, rounding, mangled reference) that the engine raised as an *error*. A correct error on a record that also carries a benign quirk is not counted.
- **Links** are the pairings the engine made, graded the same way.
- The payout date is judged *as of* a fixed date (world end plus 5 days), so a late payout is not called missing too early.

Two profiles: **easy** (isolated, clean defects) and **hard** (25% round amounts so many payments look alike, typo'd references that land on other real payments, 6% of defective payments carrying a second defect, and 6% of bank lines arriving without a reference).

## Phase 3 result: the first engine failed the hard world, and the fix is measured
The first engine matched strictly in tiers and accepted the first reference match. It scored 1.000 on the easy world, which proves little because the easy world matches its own assumptions. On the hard world (seed 42, 60 days) it did not hold up:

| | First engine | Current engine |
|---|---:|---:|
| Error precision | 0.561 | **0.999** |
| Error recall | 0.981 | **0.994** |
| Ledger to transaction link precision | 0.9961 | **1.0000** |
| Ledger to transaction link recall | 0.9878 | **1.0000** |

False alarms and misses per class (seed 42, hard):

| Class | Kind | Cases | First: false alarms | First: missed | Now: false alarms | Now: missed |
|---|---|---:|---:|---:|---:|---:|
| `amount_mismatch` | error | 106 | 90 | 12 | 0 | 0 |
| `bank_orphan` | error | 22 | 0 | 0 | 0 | 1 |
| `bank_ref_missing` | benign | 36 | 0 | 36 | 1 | 0 |
| `cutoff_timing` | benign | 272 | 59 | 2 | 0 | 0 |
| `duplicate_ledger` | error | 108 | 190 | 0 | 0 | 0 |
| `fee_variance` | error | 289 | 0 | 0 | 0 | 0 |
| `fx_mismatch` | error | 0 | 63 | 0 | 0 | 0 |
| `fx_rounding` | benign | 516 | 1 | 8 | 0 | 0 |
| `missing_in_ledger` | error | 73 | 199 | 1 | 0 | 1 |
| `missing_in_processor` | error | 76 | 9 | 1 | 0 | 1 |
| `payout_late` | benign | 55 | 0 | 0 | 0 | 0 |
| `payout_missing` | error | 20 | 0 | 0 | 0 | 1 |
| `payout_short` | error | 23 | 0 | 0 | 1 | 0 |
| `payout_split` | benign | 51 | 0 | 0 | 0 | 0 |
| `ref_noise` | benign | 724 | 1 | 201 | 1 | 0 |

**Why it failed:** a mistyped reference usually names another real order. The first engine linked the payment to that other order, which made a false duplicate, a false "missing in ledger" for the order it should have matched, and a wrong amount mismatch.

**What fixed it** (all in `src/tally/recon/engine.py`):
1. A reference match must also agree on merchant, currency and time to be believed.
2. Strong evidence (reference *and* amount agree) is accepted first; an extra strong entry is a duplicate, a weak one is not.
3. Records still unmatched get attribute matching (merchant, currency, amount, time window), then a low-confidence fuzzy tier (amount within 12%, tight window, unique from both sides).
4. A reference-only match between two otherwise unclaimed records is the last resort and becomes an amount mismatch.
5. Bank lines without a reference are matched by amount and date, with a fuzzy tier for short payouts.

The benign false-alarm metric was also corrected along the way: it first counted correct errors on records with a benign quirk, which overstated the first engine's false alarms, so that figure is left out of the table.

## Stability across seeds (60 days, 8 seeds per profile)
| Profile | Error precision | Error recall | Benign false alarm | Ledger link precision | Payout link precision | Per-class precision / recall (min, classes with 30+ cases) |
|---|---|---|---|---|---|---|
| easy | 0.9983 to 1.0000 | 0.9966 to 1.0000 | 0.0000 to 0.0000 | 1.0000 to 1.0000 | 0.9987 to 1.0000 | 1.000 / 1.000 |
| hard | 0.9969 to 1.0000 | 0.9941 to 1.0000 | 0.0000 to 0.0006 | 1.0000 to 1.0000 | 0.9974 to 1.0000 | 1.000 / 1.000 |

The frozen floors in `benchmarks/floors.json` come from this evidence, each set a little below the worst value seen. They are enforced by `python -m tally check` in CI and by `tests/test_engine.py`. A test confirms a deliberately crippled engine fails them. **Floors are not moved to make a build pass.**

## Speed and memory (hard profile, one machine, 4 cores)
Per size, reconcile time before and after the one tuning change below:

| Ledger rows | Reconcile before | Reconcile after | `resolve_links` before | after | Rows per second (after) | Peak memory | Error precision / recall |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 10,011 | 0.352s | 0.275s | 0.0218s | 0.0196s | 36,403 | 234 MB | 1.0000 / 1.0000 |
| 100,150 | 1.618s | 1.314s | 0.5547s | 0.3053s | 76,211 | 388 MB | 0.9981 / 0.9966 |
| 1,000,917 | 14.294s | 7.21s | 6.2954s | 0.4818s | 138,827 | 1644 MB | 0.9953 / 0.9901 |

Whole-pipeline timings (after tuning):

| Ledger rows | Generate | Load | dbt build | Reconcile |
|---:|---:|---:|---:|---:|
| 10,011 | 0.32s | 0.458s | 6.026s | 0.275s |
| 100,150 | 3.0s | 1.615s | 7.594s | 1.314s |
| 1,000,917 | 39.51s | 4.763s | 9.107s | 7.21s |

**The tuning:** the slowest step at scale was `resolve_links` (6.3s at one million rows). `EXPLAIN ANALYZE` showed DuckDB using a MARK join for an `OR` inside an anti-join, scanning every candidate before filtering to the few weak ones. Rewriting it as separate anti-joins over a small materialised set cut that step to 0.48s and halved the total. Results were identical (same precision and recall before and after).

Peak memory is the whole run, including the Python generator, not the engine alone.

## What this does not show
- **It is synthetic.** I wrote the generator and the engine, so the hard profile is only as hard as I made it. A real ledger has surprises this does not model.
- **Density matters.** At one million rows over 100 days (about 10,000 payments a day across 12 merchants), precision and recall drop to about 0.995 and 0.990 because more look-alike payments share a time window. Real volumes need their own measurement.
- **A few errors remain on purpose.** Fuzzy matching can pair two unrelated unmatched records by coincidence (for example an orphan bank line landing near a missing payout's amount). The engine reports confidence so these can be reviewed.
- **No learning.** Rules and tolerances are set by hand and frozen; nothing is trained on the answer key.
