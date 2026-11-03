# Roadmap: from empty repo to a released, user-accepted product

Working title: **Tally**. Reconciliation that is *graded* against a known answer key, so its quality is measured, not claimed.

Every phase ends with: tests passing in CI, docs updated, a demo you can run, and its **exit criteria** met. Nothing moves on until the exit criteria are true. Thresholds marked *(provisional)* are set from the first real measurement in Phase 4, then frozen.

| # | Phase | Status |
|---|---|---|
| 0 | Foundation | Done |
| 1 | Synthetic world and answer key | Done |
| 2 | Ingestion and warehouse | Done |
| 3 | Reconciliation engine | Next |
| 4 | Grader and benchmarks | |
| 5 | Orchestration and operations | |
| 6 | Product UI | |
| 7 | Natural-language questions (validated SQL) | |
| 8 | Hardening and polish | |
| 9 | User acceptance testing (UAT) | |
| 10 | Release | |

---

## Phase 0: Foundation
**Goal:** a repo anyone can clone, run and trust.
- Deliverables: package layout, `pyproject`, `Makefile`, lint and format (ruff), GitHub Actions CI, `.gitignore`, README.
- Exit: CI green on a clean clone; `make test` and `make generate` work.

## Phase 1: Synthetic world and answer key
**Goal:** invent realistic, messy payment data where we know the correct answer.
- Three sources: internal **ledger**, **processor** transactions and payouts, **bank** lines. Money is integer minor units, never floats.
- Thirteen defect classes (errors and benign look-alikes), injected at known rates, each recorded in `answer_key.csv`. True pairings recorded in `expected_links.csv`.
- Deterministic: same seed gives byte-identical files (hashes in `manifest.json`).
- Tests: clean world reconciles exactly; key references only real records; property-based tests over random worlds.
- Exit: every class has at least 10 cases in a 60-day world; determinism and key-integrity tests pass.

## Phase 2: Ingestion and warehouse
**Goal:** load the three sources safely, the way a real pipeline must.
- Raw layer (immutable, as received) to staging (typed, cleaned) to marts, in DuckDB with dbt models and dbt tests.
- Idempotent loads: loading the same file twice changes nothing. Late-arriving and duplicate records handled by design.
- Schema contracts and **data-quality gates**: a bad batch (wrong types, missing columns, impossible amounts) is quarantined and never reaches marts.
- Reference data: fee schedule and FX rates versioned by date.
- Exit: double-load produces identical table hashes; a deliberately corrupted batch is blocked with a clear reason; dbt tests green.
- **Result:** all three exit tests are automated (`tests/test_warehouse_pipeline.py`). Late and shuffled deliveries also produce identical marts, and a later delivery of the same id corrects an earlier one while raw keeps the history.

## Phase 3: Reconciliation engine
**Goal:** find every disagreement and explain it.
- Matching in tiers: exact reference, normalised reference, then attributes (merchant, amount, time window) for mangled or missing references.
- Payout level: many-to-one (sum of transactions to one payout), one-to-many (split bank lines), timing windows (late versus missing, with an as-of date).
- Fee and FX checks against reference data, with rounding tolerance.
- Every finding carries a class, the records involved, an amount at stake, a confidence and a plain-language reason.
- Exception queue with status (open, explained, resolved) and an audit trail of who changed what.
- Exit: engine runs end to end on the Phase 1 world and emits findings in the same format as the answer key.

## Phase 4: Grader and benchmarks
**Goal:** prove how good it is, with numbers.
- Grader compares findings to the answer key: precision, recall and F1 per class, link accuracy, and the false-alarm rate on benign look-alikes.
- CI regression gate: a change that drops any metric below its frozen floor fails the build.
- Performance benchmarks at 10k, 100k and 1M rows (throughput, p95, memory) with method documented; query plans inspected and tuned.
- Acceptance floors *(provisional)*: error-class recall at least 0.95 and precision at least 0.97; link accuracy at least 0.995; benign false alarms at most 2%.
- Exit: published scorecard, floors frozen, regression gate live.

## Phase 5: Orchestration and operations
**Goal:** run it daily, safely, and see what happened.
- Airflow DAG: ingest, validate, reconcile, grade, publish. Retries with backoff, SLAs, alerts.
- Idempotent re-runs and **backfills**: re-running a day, or a range, gives the same result as a clean run.
- Run ledger (what ran, when, inputs, outputs, row counts), freshness checks and lineage.
- Exit: a three-day backfill equals a clean three-day run (hash-identical); a killed run resumes without duplicating work; failures raise an alert.

## Phase 6: Product UI
**Goal:** a calm, minimal tool a finance analyst can use without training.
- Next.js dashboard in a clean card style, Poppins type, soft green palette.
- Screens: **Overview** (balance, expected versus received, trend), **Exceptions** (filter, sort, explain, resolve), **Payouts**, **Scorecard** (the grader results), **Runs** (health and freshness).
- Empty, loading and error states for every screen; CSV export; keyboard navigation.
- Exit: every UAT scenario in `docs/UAT.md` marked UI-covered is possible; accessibility checks pass (see Phase 8).

## Phase 7: Natural-language questions (validated SQL)
**Goal:** ask "which payouts are missing from the bank this week?" and get a trustworthy answer.
- Pluggable question-to-SQL layer: a deterministic planner for common questions, an optional LLM provider behind an interface (no keys in the repo).
- Every query validated before running: read-only, allow-listed tables and columns, row and time limits, cost estimate from the query plan, and an audit log.
- Evaluation set of at least 40 questions with expected results; the assistant is graded like the engine is.
- Exit: evaluation set at or above its floor; every unsafe query in the red-team set is refused.

## Phase 8: Hardening and polish
**Goal:** production-grade, not demo-grade.
- Accessibility audit (WCAG AA contrast, focus, labels, reduced motion), responsive layouts, performance budgets.
- Security review of the app itself, dependency audit in CI, secrets handling, input validation.
- Structured logging and metrics, clear error messages, docs (architecture, runbook, data dictionary, how to read the scorecard).
- Exit: audit checklist signed off; no known S1 or S2 defects; cold start to demo in one command.

## Phase 9: User acceptance testing (UAT)
**Goal:** a real person, doing real tasks, confirms it is fit for purpose. Full plan in `docs/UAT.md`.
- Personas: Finance Operations Analyst, Data Engineer, Reviewer (hiring manager or client).
- Around 25 scenarios with steps and expected results; entry and exit criteria; defect severity scale; sign-off table.
- Automated acceptance: end-to-end browser tests mapped to scenarios, plus golden-dataset acceptance on the scorecard.
- Manual UAT: you run the scenarios; defects are logged, fixed and retested.
- Exit: all S1 and S2 scenarios pass, no open S1 or S2 defects, sign-off recorded.

## Phase 10: Release
**Goal:** ship it and make it easy to understand.
- Version 1.0 tag and changelog; hosted demo of the dashboard on a frozen sample run.
- Walkthrough video or GIF, a one-page architecture diagram, and the portfolio case study in the same compact format as the other projects.
- Retrospective: what the benchmark taught us, what we would change.
- Exit: a stranger can go from the README to a running demo in under ten minutes.

---

## Rules for the whole project
- Only synthetic data. No real customer, employer or bank data, ever.
- Money is integers. Dates are UTC. Every test is deterministic (seeded).
- Scores are measured, then frozen, then protected by CI. We do not move a floor to make a build pass.
