# Tally

Payments reconciliation that is **graded against a known answer key**.

Most reconciliation demos show a dashboard and ask you to trust it. Tally invents its own messy payment data, hides a known set of mistakes in it, and then scores the reconciliation engine like a test: how many real mistakes did it find, how many false alarms did it raise, and how accurate were its matches, class by class.

All data is synthetic. No real customer, bank or employer data is used anywhere.

## The idea in one paragraph
Three records of the same money never agree: the internal **ledger**, the **payment processor**, and the **bank**. Payments are booked twice, arrive late, settle in batches, get split, carry fees and rounding differences, and lose their references. Reconciliation finds where the three disagree and why. Tally measures how well it does that.

## Quick start
```bash
python -m venv .venv && . .venv/bin/activate
make install
make test
make demo          # writes a synthetic world to data/world-42
```

## Status
Delivery is planned in phases through to user acceptance testing and release. See [docs/ROADMAP.md](docs/ROADMAP.md).

| Phase | | |
|---|---|---|
| 0 Foundation | Done | repo, CI, tooling |
| 1 Synthetic world and answer key | Done | 13 defect classes, deterministic, property-tested |
| 2 to 10 | Planned | warehouse, engine, grader, orchestration, UI, validated Q&A, hardening, UAT, release |

## Documents
- [Roadmap](docs/ROADMAP.md): every phase with deliverables and exit criteria
- [Architecture](docs/ARCHITECTURE.md): sources, keys and defect classes
- [UAT plan](docs/UAT.md): personas, 25 scenarios, severity scale, sign-off
