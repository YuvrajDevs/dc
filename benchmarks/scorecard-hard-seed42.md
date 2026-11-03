# Tally scorecard

seed: 42, days: 60, profile_hardness: {'bank_ref_missing': 0.06, 'compound_rate': 0.06, 'round_amount_share': 0.25, 'typo_share': 0.4}

## Summary

- Real errors: micro precision **0.999**, micro recall **0.994**
- Benign look-alikes wrongly raised as errors: **0 of 1654** (0.00%)
- Error findings that match no injected defect: 0
- Link accuracy: precision **0.9999**, recall **1.0000**

## By class

| Class | Kind | Cases | Found right | Missed | False alarms | Precision | Recall | F1 |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| `amount_mismatch` | error | 106 | 106 | 0 | 0 | 1.000 | 1.000 | 1.000 |
| `bank_orphan` | error | 22 | 21 | 1 | 0 | 1.000 | 0.955 | 0.977 |
| `bank_ref_missing` | benign | 36 | 36 | 0 | 1 | 0.973 | 1.000 | 0.986 |
| `cutoff_timing` | benign | 272 | 272 | 0 | 0 | 1.000 | 1.000 | 1.000 |
| `duplicate_ledger` | error | 108 | 108 | 0 | 0 | 1.000 | 1.000 | 1.000 |
| `fee_variance` | error | 289 | 289 | 0 | 0 | 1.000 | 1.000 | 1.000 |
| `fx_rounding` | benign | 516 | 516 | 0 | 0 | 1.000 | 1.000 | 1.000 |
| `missing_in_ledger` | error | 73 | 72 | 1 | 0 | 1.000 | 0.986 | 0.993 |
| `missing_in_processor` | error | 76 | 75 | 1 | 0 | 1.000 | 0.987 | 0.993 |
| `payout_late` | benign | 55 | 55 | 0 | 0 | 1.000 | 1.000 | 1.000 |
| `payout_missing` | error | 20 | 19 | 1 | 0 | 1.000 | 0.950 | 0.974 |
| `payout_short` | error | 23 | 23 | 0 | 1 | 0.958 | 1.000 | 0.979 |
| `payout_split` | benign | 51 | 51 | 0 | 0 | 1.000 | 1.000 | 1.000 |
| `ref_noise` | benign | 724 | 724 | 0 | 1 | 0.999 | 1.000 | 0.999 |

## Links

| Kind | Expected | Found | Precision | Recall |
|---|---:|---:|---:|---:|
| ledger_txn | 23851 | 23852 | 1.0000 | 1.0000 |
| payout_bank | 751 | 752 | 0.9987 | 1.0000 |
| all | 24602 | 24604 | 0.9999 | 1.0000 |
