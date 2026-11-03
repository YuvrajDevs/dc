# Changelog

## 1.0.0-rc1
First release candidate. Manual UAT and sign-off are still pending (see docs/UAT.md).

- Synthetic payments world with 13 injected defect classes and an answer key.
- Gated ingestion, dbt staging and marts, idempotent loads.
- Five-tier reconciliation engine, 14 finding classes, exception queue with audit trail.
- Grader with per-class precision and recall; floors frozen from 8 seeds per profile and enforced in CI.
- Operations: run ledger, resumable runs, backfills, retries, alerts, freshness, lineage, Airflow DAG.
- Dashboard: Overview, Exceptions, Payouts, Scorecard, Runs, Ask.
- Question assistant with three-layer SQL validation; 45 evaluation questions, 68 red-team cases.
- Hardening: dependency audits in CI, security headers, request logging, automated accessibility checks.
