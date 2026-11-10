"""Phase 5 exit criteria: idempotent backfills, resumable runs, alerts on failure."""

import csv
import shutil
from datetime import date, timedelta
from pathlib import Path

import pytest

from trueup.ops import Alerter, PermanentError, Pipeline, PipelineConfig, SimulatedKill
from trueup.ops.pipeline import Hooks
from trueup.recon import ReconConfig
from trueup.synth.config import Config
from trueup.synth.generate import generate
from trueup.warehouse import Warehouse
from trueup.warehouse.split import split_world

START = date(2026, 1, 1)
DAYS = [START + timedelta(days=i) for i in range(3)]
NOISE = ("_batch_id", "_batch_seq", "_row_number", "_loaded_at", "_source_file")


@pytest.fixture(scope="module")
def batches(tmp_path_factory):
    root = tmp_path_factory.mktemp("ops")
    generate(Config(seed=31, days=3, merchants=8, txns_per_day=400), root / "world")
    split_world(root / "world", root / "batches")
    return root / "batches"


def make(tmp_path: Path, batches: Path, name="w", **kw) -> Pipeline:
    cfg = PipelineConfig(
        batches_dir=batches, recon=ReconConfig(as_of=DAYS[-1]), backoff_seconds=2.0, **kw
    )
    return Pipeline(tmp_path / f"{name}.duckdb", cfg, sleep=lambda s: None)


def state(db: Path):
    with Warehouse(db) as wh:
        return wh.fingerprints(("raw", "staging", "marts", "recon"), exclude=NOISE)


def alert_kinds(p: Pipeline) -> list[str]:
    return [a["kind"] for a in p.ledger.alerts()]


def test_three_day_backfill_equals_the_clean_run(tmp_path, batches):
    clean = make(tmp_path, batches, "clean")
    assert clean.run(DAYS, kind="backfill").status == "succeeded"

    by_day = make(tmp_path, batches, "by_day")
    results = by_day.backfill(DAYS[0], DAYS[-1], per_day=True)
    assert [r.status for r in results] == ["succeeded"] * 3

    assert state(tmp_path / "by_day.duckdb") == state(tmp_path / "clean.duckdb")

    # the findings that matter to a person end up the same
    def open_set(db):
        with Warehouse(db) as wh:
            return wh.con.execute(
                "SELECT finding_id, status FROM ops.exceptions "
                "WHERE finding_id IN (SELECT finding_id FROM recon.findings) ORDER BY 1"
            ).fetchall()

    assert open_set(tmp_path / "by_day.duckdb") == open_set(tmp_path / "clean.duckdb")


def test_a_killed_run_resumes_without_repeating_work(tmp_path, batches):
    clean = make(tmp_path, batches, "clean")
    clean.run(DAYS, kind="backfill")

    def kill_after_ingest(step):
        if step == "ingest":
            raise SimulatedKill()

    p = make(tmp_path, batches, "killed")
    p.hooks = Hooks(after_step=kill_after_ingest)
    with pytest.raises(SimulatedKill):
        p.run(DAYS, kind="backfill")
    assert p.ledger.runs()[0]["status"] == "interrupted"
    with Warehouse(tmp_path / "killed.duckdb") as wh:
        rows_after_kill = wh.con.execute("SELECT count(*) FROM raw.ledger_entries").fetchone()[0]
    assert rows_after_kill > 0

    resumed = make(tmp_path, batches, "killed")  # a fresh process, same warehouse
    result = resumed.run(DAYS, kind="backfill")
    assert result.status == "succeeded"
    assert result.skipped == ["ingest"], "ingest already done; it must not run again"
    assert result.executed == ["build", "reconcile", "publish"]
    with Warehouse(tmp_path / "killed.duckdb") as wh:
        assert (
            wh.con.execute("SELECT count(*) FROM raw.ledger_entries").fetchone()[0]
            == rows_after_kill
        )
    assert state(tmp_path / "killed.duckdb") == state(tmp_path / "clean.duckdb")


def test_running_a_finished_day_again_does_nothing(tmp_path, batches):
    p = make(tmp_path, batches)
    p.run(DAYS, kind="backfill")
    before = state(tmp_path / "w.duckdb")
    again = p.run(DAYS, kind="backfill")
    assert again.status == "succeeded"
    assert again.executed == [] and len(again.skipped) == 4
    assert state(tmp_path / "w.duckdb") == before


def test_transient_failures_retry_with_backoff(tmp_path, batches):
    delays: list[float] = []
    p = make(tmp_path, batches)
    p.sleep = delays.append

    def flaky(step, attempt):
        if step == "reconcile" and attempt < 3:
            raise RuntimeError("connection reset")

    p.hooks = Hooks(before_step=flaky)
    result = p.run(DAYS, kind="backfill")
    assert result.status == "succeeded"
    assert next(s for s in result.steps if s["step"] == "reconcile")["attempt"] == 3
    assert delays == [2.0, 4.0]
    assert alert_kinds(p).count("step_retry") == 2


def test_exhausted_retries_fail_the_run_and_alert(tmp_path, batches):
    p = make(tmp_path, batches, retries=2)

    def always(step, attempt):
        if step == "build":
            raise RuntimeError("disk full")

    p.hooks = Hooks(before_step=always)
    result = p.run(DAYS, kind="backfill")
    assert result.status == "failed" and "disk full" in result.error
    kinds = alert_kinds(p)
    assert "step_failed" in kinds and "run_failed" in kinds
    assert result.executed == ["ingest"], "nothing after the failing step may run"
    assert p.ledger.runs()[0]["status"] == "failed"
    assert (
        sum(1 for s in p.ledger.steps(result.run_id) if s["step"] == "build") == 3
    )  # 1 + 2 retries


def test_a_rejected_batch_alerts_critically_and_is_not_retried(tmp_path, batches):
    bad = tmp_path / "bad_batches"
    shutil.copytree(batches, bad)
    target = bad / DAYS[1].isoformat() / "ledger_entries.csv"
    rows = list(csv.DictReader(target.open()))
    for r in rows:
        r["currency"] = "ZZZ"
    with target.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)

    p = make(tmp_path, bad)
    result = p.run(DAYS, kind="backfill")
    assert result.status == "failed"
    alerts = p.ledger.alerts()
    assert any(a["kind"] == "batch_rejected" and a["severity"] == "critical" for a in alerts)
    assert sum(1 for s in p.ledger.steps(result.run_id) if s["step"] == "ingest") == 1  # no retry
    assert "build" not in result.executed


def test_a_few_bad_rows_raise_a_quarantine_alert_but_the_run_continues(tmp_path, batches):
    noisy = tmp_path / "noisy"
    shutil.copytree(batches, noisy)
    target = noisy / DAYS[0].isoformat() / "ledger_entries.csv"
    rows = list(csv.DictReader(target.open()))
    for r in rows[:2]:
        r["amount_minor"] = "-1"
    with target.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    p = make(tmp_path, noisy, quarantine_alert_rate=0.0005)
    result = p.run(DAYS, kind="backfill")
    assert result.status == "succeeded"
    ingest = next(s for s in result.steps if s["step"] == "ingest")
    assert ingest["detail"]["rows_quarantined"] == 2
    assert "quarantine_spike" in alert_kinds(p)
    with Warehouse(tmp_path / "w.duckdb") as wh:
        assert wh.con.execute("SELECT count(*) FROM quarantine.rejected_rows").fetchone()[0] == 2


def test_missing_delivery_and_stale_sources_are_flagged(tmp_path, batches):
    p = make(tmp_path, batches)
    future = DAYS + [DAYS[-1] + timedelta(days=30)]  # no batch exists for that day
    p.cfg.recon = ReconConfig(as_of=DAYS[-1] + timedelta(days=30))
    result = p.run(future, kind="backfill")
    assert result.status == "succeeded"
    kinds = alert_kinds(p)
    assert "missing_delivery" in kinds
    assert "freshness_stale" in kinds


def test_slow_steps_breach_their_sla(tmp_path, batches):
    p = make(
        tmp_path,
        batches,
        step_sla_seconds={s: 0.0 for s in ("ingest", "build", "reconcile", "publish")},
    )
    p.run(DAYS, kind="backfill")
    assert alert_kinds(p).count("sla_missed") == 4


def test_runs_record_their_inputs_and_lineage(tmp_path, batches):
    p = make(tmp_path, batches)
    result = p.run(DAYS, kind="backfill")
    with Warehouse(tmp_path / "w.duckdb") as wh:
        inputs = wh.con.execute(
            "SELECT batch_name, status FROM ops.run_inputs WHERE run_id = ? ORDER BY 1",
            [result.run_id],
        ).fetchall()
        assert ("0000-reference", "loaded") in inputs and len(inputs) == 4
        edges = set(wh.con.execute("SELECT parent, child FROM ops.lineage").fetchall())
    assert ("raw.ledger_entries", "staging.stg_ledger_entries") in edges
    assert ("staging.stg_ledger_entries", "marts.fct_ledger_entry") in edges
    assert ("marts.fct_ledger_entry", "recon.ref_candidates") in edges
    assert ("recon.findings", "ops.exceptions") in edges


def test_alerter_never_breaks_a_run_when_the_webhook_is_down(tmp_path, batches):
    p = make(tmp_path, batches)
    p.alerter = Alerter(p.ledger, webhook="http://127.0.0.1:9/nope")
    p.alerter.raise_alert("critical", "test", "the webhook is unreachable")  # must not raise
    assert "test" in alert_kinds(p)


def test_permanent_errors_are_a_distinct_type():
    assert issubclass(PermanentError, Exception) and not issubclass(SimulatedKill, Exception)
