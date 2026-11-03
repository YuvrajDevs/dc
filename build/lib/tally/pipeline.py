"""One-call helpers that run the pipeline end to end on a generated world."""

from __future__ import annotations

import time
from pathlib import Path

from tally.grade import Scorecard, grade
from tally.recon import ReconConfig, ReconSummary, reconcile
from tally.warehouse import Warehouse, dbt_runner


def load_world(world: Path, db: Path) -> dict[str, float]:
    """Load a whole generated world as a single delivery, then build staging and marts."""
    if db.exists():
        db.unlink()
    t0 = time.perf_counter()
    with Warehouse(db) as wh:
        result = wh.load_batch(world)
        if not result.ok:
            raise RuntimeError(f"world rejected by the gate: {result.reasons}")
    t1 = time.perf_counter()
    summary = dbt_runner.build(db)
    if not summary.success:
        raise RuntimeError(f"dbt build failed: {summary.failures}")
    return {"load_s": round(t1 - t0, 3), "dbt_s": round(time.perf_counter() - t1, 3)}


def reconcile_and_grade(db: Path, world: Path, cfg: ReconConfig) -> tuple[ReconSummary, Scorecard]:
    with Warehouse(db) as wh:
        summary = reconcile(wh, cfg)
        card = grade(wh, world)
    return summary, card
