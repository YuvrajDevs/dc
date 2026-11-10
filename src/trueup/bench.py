"""Benchmarks: accuracy across seeds, and speed and memory at scale."""

from __future__ import annotations

import json
import resource
import statistics
import subprocess
import sys
import tempfile
import time
from datetime import timedelta
from pathlib import Path

from trueup.grade import check_floors
from trueup.pipeline import load_world, reconcile_and_grade
from trueup.recon import ReconConfig
from trueup.synth.config import PROFILES, Config
from trueup.synth.generate import generate


def run_once(
    profile: str, seed: int, days: int, merchants: int, per_day: int, workdir: Path
) -> dict:
    cfg = Config(
        seed=seed, days=days, merchants=merchants, txns_per_day=per_day, hardness=PROFILES[profile]
    )
    world, db = workdir / "world", workdir / "wh.duckdb"
    t0 = time.perf_counter()
    manifest = generate(cfg, world)
    gen_s = time.perf_counter() - t0
    timings = load_world(world, db)
    summary, card = reconcile_and_grade(
        db, world, ReconConfig(as_of=cfg.start + timedelta(days=days + 5))
    )
    t1 = time.perf_counter()
    rows = manifest["row_counts"]
    return {
        "profile": profile, "seed": seed, "days": days, "merchants": merchants,
        "txns_per_day": per_day,
        "rows": {
            k: rows[k]
            for k in ("ledger_entries", "processor_txns", "processor_payouts", "bank_lines")
        },
        "defects_injected": sum(manifest["defect_counts"].values()),
        "seconds": {
            "generate": round(gen_s, 2),
            **timings,
            "reconcile": round(summary.total_seconds, 3),
        },
        "reconcile_steps": summary.step_seconds,
        "ledger_rows_per_second": int(rows["ledger_entries"] / max(summary.total_seconds, 1e-6)),
        "peak_memory_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024),
        "scorecard": card.to_dict(),
        "_card": card,
        "_graded_at": t1,
    }  # fmt: skip


def public(result: dict) -> dict:
    return {k: v for k, v in result.items() if not k.startswith("_")}


def stability(profile: str, seeds: list[int], days: int, merchants: int, per_day: int) -> dict:
    runs = []
    for seed in seeds:
        with tempfile.TemporaryDirectory() as tmp:
            r = run_once(profile, seed, days, merchants, per_day, Path(tmp))
        s = r["scorecard"]["summary"]
        runs.append(
            {
                "seed": seed,
                "precision": s["error_micro_precision"],
                "recall": s["error_micro_recall"],
                "benign_false_alarm_rate": s["benign_false_alarm_rate"],
                "link_precision": r["scorecard"]["links"]["all"]["precision"],
                "link_recall": r["scorecard"]["links"]["all"]["recall"],
            }
        )
    band = {}
    for key in ("precision", "recall", "benign_false_alarm_rate", "link_precision", "link_recall"):
        vals = [x[key] for x in runs]
        band[key] = {"min": min(vals), "max": max(vals), "mean": round(statistics.mean(vals), 4)}
    return {"profile": profile, "days": days, "runs": runs, "band": band}


def check(floors: dict, days: int = 60, per_day: int = 400, seed: int = 42) -> dict[str, list[str]]:
    """Run each profile and compare to its floors. Empty lists mean everything holds."""
    out: dict[str, list[str]] = {}
    for profile in ("easy", "hard"):
        with tempfile.TemporaryDirectory() as tmp:
            r = run_once(profile, seed, days, 12, per_day, Path(tmp))
        out[profile] = check_floors(r["_card"], floors[profile])
    return out


def scale_one(profile: str, rows: int, seed: int = 1) -> dict:
    """Run one size in this process (the caller starts a fresh process per size)."""
    days = 25 if rows <= 10_000 else 100
    per_day = max(1, rows // days)
    with tempfile.TemporaryDirectory() as tmp:
        return public(run_once(profile, seed, days, 12, per_day, Path(tmp)))


def scale(profile: str, sizes: list[int]) -> list[dict]:
    results = []
    for n in sizes:
        proc = subprocess.run(
            [sys.executable, "-m", "trueup", "bench-run", "--profile", profile, "--rows", str(n)],
            capture_output=True, text=True, check=True,
        )  # fmt: skip
        results.append(json.loads(proc.stdout))
    return results
