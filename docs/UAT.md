# User Acceptance Test (UAT) plan

UAT answers one question: **can a real user do their job with this, and would they sign off?** It is separate from unit and integration tests, which answer whether the code is correct.

## Personas
| Persona | Goal |
|---|---|
| **Finance Operations Analyst** | Start the day, see what needs attention, explain or resolve each exception. |
| **Data Engineer** | Trust the pipeline: runs, backfills, freshness, failures. |
| **Reviewer** (hiring manager or client) | Understand in minutes what it does and how good it is. |

## Entry criteria
- Phase 8 exit criteria met; CI green on the release candidate.
- A seeded demo world (default seed 42, 90 days) loaded.
- UAT environment reset with one command.

## Scenarios
Priority: **P1** must pass to ship, **P2** should pass, **P3** nice to have.

| ID | Persona | Scenario | Expected result | P |
|---|---|---|---|---|
| A1 | Analyst | Open Overview | Expected, received and difference shown; matches the scorecard totals | P1 |
| A2 | Analyst | Filter exceptions by class and amount | List narrows correctly; count updates | P1 |
| A3 | Analyst | Open a `fee_variance` exception | Shows expected versus actual fee and the reason in plain language | P1 |
| A4 | Analyst | Open a `payout_split` item | Shown as explained, not as an error; both bank lines listed | P1 |
| A5 | Analyst | Mark an exception explained, add a note | Status and note persist; audit entry written | P1 |
| A6 | Analyst | Find a duplicate booking | Both ledger entries shown; amount at stake correct | P1 |
| A7 | Analyst | Check a late payout before and after its bank line arrives | Pending, then matched; never raised as missing early | P1 |
| A8 | Analyst | Export current view to CSV | File matches the screen, correct columns, UTF-8 | P2 |
| A9 | Analyst | Use only the keyboard | Every action reachable, visible focus | P2 |
| A10 | Analyst | Ask "which payouts are missing from the bank?" | Correct list; the SQL shown; read-only | P1 |
| A11 | Analyst | Ask a question that tries to change data | Refused with a clear reason | P1 |
| D1 | Data Engineer | Run the daily pipeline | All steps succeed; run ledger records counts | P1 |
| D2 | Data Engineer | Load the same day twice | No change in any table hash | P1 |
| D3 | Data Engineer | Backfill three days | Identical to a clean three-day run | P1 |
| D4 | Data Engineer | Kill a run mid-way, restart | Resumes; no duplicates | P1 |
| D5 | Data Engineer | Feed a corrupted batch | Quarantined with the reason; marts untouched | P1 |
| D6 | Data Engineer | Check freshness | Stale source flagged | P2 |
| D7 | Data Engineer | Trigger a failure | Alert raised with the failing step | P2 |
| R1 | Reviewer | Read the README, run the demo | Running in under ten minutes | P1 |
| R2 | Reviewer | Open the Scorecard | Per-class precision and recall visible, with method explained | P1 |
| R3 | Reviewer | Rerun with a different seed | Scores stay within a stated band | P2 |
| R4 | Reviewer | View on a phone | Layout usable, nothing clipped | P2 |
| R5 | Reviewer | Screen reader pass on Overview | Landmarks, labels and values announced | P3 |
| X1 | All | Empty state (no data loaded) | Helpful message, not a blank page | P2 |
| X2 | All | Error state (service down) | Clear message and a way to retry | P2 |

## Automated acceptance (run `make uat`)
Browser tests drive the real dashboard against a throwaway copy of the demo database; engine tests cover the data scenarios.

| Scenario | Covered by | Result |
|---|---|---|
| A1, A2, A3, A5, A8, A9, A10, A11 | `dashboard/e2e/uat.mjs` | Pass |
| R2, R4, D1, X2 | `dashboard/e2e/uat.mjs` | Pass |
| R5 (automated part only) | `dashboard/e2e/uat.mjs` (axe-core, WCAG 2.1 AA, all pages) | Pass; manual screen-reader pass still due |
| A4, A6, A7 | `tests/test_engine.py` (benign look-alikes explained; payout missing only after its window) | Pass |
| D2, D5 | `tests/test_warehouse_pipeline.py`, `tests/test_warehouse_gate.py` | Pass |
| D3, D4, D6, D7 | `tests/test_ops.py` (also run for real under Airflow) | Pass |
| R3 | `benchmarks/` stability over 8 seeds per profile, enforced by `python -m trueup check` | Pass |
| A7 (UI), X1, R1 | Manual only | **Not yet run** |

## Defect severity
| Level | Meaning | Rule |
|---|---|---|
| S1 | Wrong money result, data loss, security issue, or cannot complete a P1 scenario | Blocks release |
| S2 | Feature works but misleading, or workaround is awkward | Blocks release |
| S3 | Cosmetic or minor usability | Fix if cheap, else log |
| S4 | Suggestion | Backlog |

## Exit criteria
- Every P1 scenario passes; at least 90% of P2 pass.
- No open S1 or S2 defects; every fix retested.
- Scorecard meets the frozen floors on the golden dataset.
- Sign-off recorded below.

## How UAT runs
1. **Automated acceptance** runs first: browser tests mapped to scenario IDs, and the golden-dataset scorecard check.
2. **Manual UAT** walks the scenarios as each persona, recording pass or fail with a screenshot for any failure.
3. Defects go in the log, get fixed, and the affected scenarios are retested.
4. A fresh full pass on the final candidate before sign-off.

## Defect log
| ID | Scenario | Severity | Description | Status |
|---|---|---|---|---|
| UAT-1 | R5 / A1 | S2 | Muted and warning text under 4.5:1 contrast; meters unnamed (found by axe) | Fixed, retested |
| UAT-2 | A1 | S2 | Overview had no expected/received/difference figures as the scenario requires | Fixed, retested |
| UAT-3 | A9 | S3 | Esc did not close the exception drawer when focus was outside it | Fixed, retested |

## Sign-off
| Role | Name | Date | Decision |
|---|---|---|---|
| Product owner | Yuvraj Singh Shekhawat | | **Pending** manual pass |
| Tester | | | **Pending** |
