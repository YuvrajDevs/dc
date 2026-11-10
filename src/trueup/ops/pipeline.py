"""The daily pipeline: ingest, build, reconcile, publish.

Design rules
  * Every step records an *input hash*. A step is skipped when it already succeeded for the same
    run key with the same inputs, so re-running a finished day does nothing and a run killed
    half-way resumes where it stopped.
  * A new delivery changes the inputs, which invalidates the steps that depend on it.
  * Transient failures are retried with exponential backoff. Data problems (a rejected batch,
    failing dbt tests) are permanent: no retry, a critical alert, and the run stops.
  * Alerting never breaks the run.
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from trueup.ops import freshness, lineage
from trueup.ops.alerts import Alerter
from trueup.ops.ledger import Ledger
from trueup.recon import ReconConfig, reconcile
from trueup.recon import queue as exception_queue
from trueup.warehouse import Warehouse, dbt_runner

STEPS = ("ingest", "build", "reconcile", "publish")


class PermanentError(Exception):
    """A problem retrying cannot fix (bad data, failing tests)."""


class SimulatedKill(BaseException):  # noqa: N818  (BaseException on purpose: bypasses retries)
    """Used by tests to model the process being killed between steps."""


@dataclass
class PipelineConfig:
    batches_dir: Path
    reference_batch: str = "0000-reference"
    recon: ReconConfig = field(default_factory=ReconConfig)
    retries: int = 3
    backoff_seconds: float = 2.0
    step_sla_seconds: dict[str, float] = field(
        default_factory=lambda: {"ingest": 120, "build": 300, "reconcile": 120, "publish": 60}
    )
    freshness_days: dict[str, int] | None = None
    quarantine_alert_rate: float = 0.005


@dataclass
class Hooks:
    """Test seams: called around each attempt of each step."""

    before_step: Callable[[str, int], None] = lambda step, attempt: None
    after_step: Callable[[str], None] = lambda step: None


@dataclass
class RunResult:
    run_key: str
    run_id: str
    status: str  # succeeded | failed | interrupted
    steps: list[dict] = field(default_factory=list)
    error: str | None = None

    @property
    def executed(self) -> list[str]:
        return [s["step"] for s in self.steps if s["status"] == "succeeded"]

    @property
    def skipped(self) -> list[str]:
        return [s["step"] for s in self.steps if s["status"] == "skipped"]


def _h(*parts: object) -> str:
    return hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()[:16]


class Pipeline:
    def __init__(
        self,
        db_path: str | Path,
        cfg: PipelineConfig,
        alerter: Alerter | None = None,
        hooks: Hooks | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.db = Path(db_path)
        self.cfg = cfg
        self.ledger = Ledger(self.db)
        self.alerter = alerter or Alerter(self.ledger, webhook="")
        self.hooks = hooks or Hooks()
        self.sleep = sleep

    # -- public ------------------------------------------------------------------------
    def run(self, days: list[date], kind: str = "daily", force: bool = False) -> RunResult:
        days = sorted(days)
        run_key = f"{kind}:{days[0]}:{days[-1]}"
        run_id = self.ledger.next_run_id(run_key)
        self.ledger.start_run(run_key, run_id, kind, days[0], days[-1])
        result = RunResult(run_key, run_id, "running")
        try:
            for step in STEPS:
                outcome = self._step(step, run_key, run_id, days, force)
                result.steps.append(outcome)
                self.hooks.after_step(step)
        except PermanentError as exc:
            return self._fail(result, str(exc))
        except Exception as exc:  # retries exhausted on a transient error
            return self._fail(result, f"{type(exc).__name__}: {exc}")
        except BaseException:  # killed or interrupted: leave a trail, then let it propagate
            self.ledger.finish_run(run_id, "interrupted", "process interrupted")
            raise
        result.status = "succeeded"
        self.ledger.finish_run(run_id, "succeeded")
        return result

    def backfill(self, start: date, end: date, per_day: bool = False) -> list[RunResult]:
        days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
        if not per_day:
            return [self.run(days, kind="backfill")]
        return [self.run([d]) for d in days]

    # -- internals ---------------------------------------------------------------------
    def _fail(self, result: RunResult, error: str) -> RunResult:
        result.status, result.error = "failed", error
        self.ledger.finish_run(result.run_id, "failed", error)
        self.alerter.raise_alert(
            "critical", "run_failed", f"{result.run_key}: {error}", result.run_id
        )
        return result

    def run_step(
        self, step: str, days: list[date], kind: str = "airflow", force: bool = False
    ) -> dict:
        """Run exactly one step (for an external scheduler that owns retries and ordering)."""
        days = sorted(days)
        run_key = f"{kind}:{days[0]}:{days[-1]}"
        run_id = self.ledger.open_run(run_key)
        if run_id is None:
            run_id = self.ledger.next_run_id(run_key)
            self.ledger.start_run(run_key, run_id, kind, days[0], days[-1])
        try:
            outcome = self._step(step, run_key, run_id, days, force, retries=0)
        except BaseException as exc:
            self.ledger.finish_run(run_id, "failed", f"{step}: {exc}")
            raise
        if step == STEPS[-1]:
            self.ledger.finish_run(run_id, "succeeded")
        return outcome

    def _step(
        self,
        step: str,
        run_key: str,
        run_id: str,
        days: list[date],
        force: bool,
        retries: int | None = None,
    ) -> dict:
        max_retries = self.cfg.retries if retries is None else retries
        input_hash = self._input_hash(step, days)
        if not force and self.ledger.last_success(run_key, step) == input_hash:
            self.ledger.record_step(
                run_id, run_key, step, "skipped", 0, input_hash, 0.0, {"why": "same inputs"}
            )
            return {"step": step, "status": "skipped", "attempt": 0}

        attempt = 0
        while True:
            attempt += 1
            t0 = time.perf_counter()
            try:
                self.hooks.before_step(step, attempt)
                detail = getattr(self, f"_do_{step}")(run_id, days)
                seconds = time.perf_counter() - t0
                self.ledger.record_step(
                    run_id, run_key, step, "succeeded", attempt, input_hash, seconds, detail
                )
                self._check_sla(step, seconds, run_id)
                return {"step": step, "status": "succeeded", "attempt": attempt, "detail": detail}
            except PermanentError as exc:
                self.ledger.record_step(
                    run_id, run_key, step, "failed", attempt, input_hash,
                    time.perf_counter() - t0, {"error": str(exc), "permanent": True},
                )  # fmt: skip
                self.alerter.raise_alert("critical", "step_failed", f"{step}: {exc}", run_id)
                raise
            except Exception as exc:
                self.ledger.record_step(
                    run_id, run_key, step, "failed", attempt, input_hash,
                    time.perf_counter() - t0, {"error": str(exc)},
                )  # fmt: skip
                if attempt > max_retries:
                    self.alerter.raise_alert(
                        "critical",
                        "step_failed",
                        f"{step} failed after {attempt} attempts: {exc}",
                        run_id,
                    )
                    raise
                self.alerter.raise_alert(
                    "warning",
                    "step_retry",
                    f"{step} attempt {attempt} failed ({exc}); retrying",
                    run_id,
                )
                self.sleep(self.cfg.backoff_seconds * 2 ** (attempt - 1))

    def _check_sla(self, step: str, seconds: float, run_id: str) -> None:
        limit = self.cfg.step_sla_seconds.get(step)
        if limit is not None and seconds > limit:
            self.alerter.raise_alert(
                "warning",
                "sla_missed",
                f"{step} took {seconds:.1f}s, over its {limit:.0f}s SLA",
                run_id,
            )

    # -- input hashes ------------------------------------------------------------------
    def _batch_dirs(self, days: list[date]) -> tuple[list[Path], list[date]]:
        root = self.cfg.batches_dir
        dirs, missing = [], []
        ref = root / self.cfg.reference_batch
        if ref.exists():
            dirs.append(ref)
        for d in days:
            p = root / d.isoformat()
            (dirs if p.exists() else missing).append(p if p.exists() else d)  # type: ignore[arg-type]
        return dirs, missing

    def _input_hash(self, step: str, days: list[date]) -> str:
        if step == "ingest":
            dirs, missing = self._batch_dirs(days)
            parts: list[object] = [d.name for d in dirs] + [str(m) for m in missing]
            for d in dirs:
                for f in sorted(d.glob("*.csv")):
                    parts += [f.name, hashlib.sha256(f.read_bytes()).hexdigest()]
            return _h(*parts)
        with Warehouse(self.db) as wh:
            loaded = wh.con.execute(
                "SELECT string_agg(batch_id, ',' ORDER BY batch_id) FROM ops.load_log "
                "WHERE status IN ('loaded', 'loaded_with_quarantine')"
            ).fetchone()[0]
            if step == "build":
                return _h("build", loaded)
            if step == "reconcile":
                marts = wh.fingerprints(("marts",)) if _built(wh) else {}
                return _h("reconcile", sorted(marts.items()), self._as_of(days), self.cfg.recon)
            recon = wh.fingerprints(("recon",)) if _has_recon(wh) else {}
            return _h("publish", sorted(recon.items()), self._as_of(days))

    def _as_of(self, days: list[date]) -> date:
        return self.cfg.recon.as_of or days[-1]

    # -- the steps ---------------------------------------------------------------------
    def _do_ingest(self, run_id: str, days: list[date]) -> dict:
        dirs, missing = self._batch_dirs(days)
        for d in missing:
            self.alerter.raise_alert(
                "warning", "missing_delivery", f"no delivery found for {d}", run_id
            )
        loaded = quarantined = 0
        names = []
        with Warehouse(self.db) as wh:
            for d in dirs:
                res = wh.load_batch(d)
                names.append(f"{d.name}:{res.status}")
                n_loaded, n_bad = sum(res.rows_loaded.values()), sum(res.rows_quarantined.values())
                loaded, quarantined = loaded + n_loaded, quarantined + n_bad
                self._record_input(run_id, d.name, res, n_loaded, n_bad, wh)
                if res.status == "rejected":
                    self.alerter.raise_alert(
                        "critical", "batch_rejected", f"{d.name}: {'; '.join(res.reasons)}", run_id
                    )
                    raise PermanentError(f"batch {d.name} rejected: {'; '.join(res.reasons)}")
        total = loaded + quarantined
        if total and quarantined / total > self.cfg.quarantine_alert_rate:
            self.alerter.raise_alert(
                "warning", "quarantine_spike",
                f"{quarantined} of {total} rows quarantined ({quarantined / total:.2%})", run_id,
            )  # fmt: skip
        return {"batches": names, "rows_loaded": loaded, "rows_quarantined": quarantined,
                "missing_deliveries": len(missing)}  # fmt: skip

    def _record_input(self, run_id, name, res, loaded, bad, wh) -> None:
        wh.con.execute(
            "INSERT INTO ops.run_inputs VALUES (?, ?, ?, ?, ?, ?)",
            [run_id, name, res.batch_id, res.status, loaded, bad],
        )

    def _do_build(self, run_id: str, days: list[date]) -> dict:
        summary = dbt_runner.build(self.db)
        if not summary.success:
            raise PermanentError("dbt build failed: " + "; ".join(summary.failures[:5]))
        return {"dbt": summary.counts}

    def _do_reconcile(self, run_id: str, days: list[date]) -> dict:
        cfg = ReconConfig(**{**self.cfg.recon.__dict__, "as_of": self._as_of(days)})
        with Warehouse(self.db) as wh:
            summary = reconcile(wh, cfg)
        return {
            "as_of": str(summary.as_of),
            "findings": sum(summary.findings.values()),
            "pending_payouts": summary.pending_payouts,
            "seconds": round(summary.total_seconds, 3),
        }

    def _do_publish(self, run_id: str, days: list[date]) -> dict:
        as_of = self._as_of(days)
        with Warehouse(self.db) as wh:
            queue = exception_queue.sync(wh)
            lineage.publish(wh)
            fresh = freshness.check(wh, as_of, self.cfg.freshness_days)
        stale = [f for f in fresh if f.status != "ok"]
        for f in stale:
            self.alerter.raise_alert(
                "warning",
                "freshness_stale",
                f"{f.source}: latest {f.latest}, {f.lag_days} day(s) behind "
                f"(allowed {f.allowed_days})",
                run_id,
            )
        return {"queue": queue, "stale_sources": [f.source for f in stale]}


def _built(wh: Warehouse) -> bool:
    return bool(wh.con.execute(
        "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'marts'"
    ).fetchone()[0])  # fmt: skip


def _has_recon(wh: Warehouse) -> bool:
    return bool(wh.con.execute(
        "SELECT count(*) FROM information_schema.tables "
        "WHERE table_schema = 'recon' AND table_name = 'findings'"
    ).fetchone()[0])  # fmt: skip
