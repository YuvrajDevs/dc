"""The run ledger: what ran, when, on which inputs, with what outcome.

Every call opens its own short connection to the warehouse file, so a step that needs the file
exclusively (dbt) never fights a long-lived handle held by the orchestrator.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from trueup.warehouse import Warehouse

DDL = [
    "CREATE TABLE IF NOT EXISTS ops.runs (run_key VARCHAR, run_id VARCHAR, kind VARCHAR, "
    "partition_start DATE, partition_end DATE, status VARCHAR, started_at TIMESTAMP, "
    "finished_at TIMESTAMP, error VARCHAR)",
    "CREATE TABLE IF NOT EXISTS ops.run_steps (run_id VARCHAR, run_key VARCHAR, step VARCHAR, "
    "status VARCHAR, attempt INTEGER, input_hash VARCHAR, started_at TIMESTAMP, "
    "finished_at TIMESTAMP, seconds DOUBLE, detail VARCHAR)",
    "CREATE TABLE IF NOT EXISTS ops.run_inputs (run_id VARCHAR, batch_name VARCHAR, "
    "batch_id VARCHAR, status VARCHAR, rows_loaded BIGINT, rows_quarantined BIGINT)",
    "CREATE TABLE IF NOT EXISTS ops.alerts (alert_id VARCHAR, raised_at TIMESTAMP, "
    "severity VARCHAR, kind VARCHAR, run_id VARCHAR, message VARCHAR)",
]


class Ledger:
    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        with Warehouse(self.db_path) as wh:
            for stmt in DDL:
                wh.con.execute(stmt)

    def _run(self, sql: str, params: list | None = None):
        with Warehouse(self.db_path) as wh:
            return wh.con.execute(sql, params or []).fetchall()

    # -- runs --------------------------------------------------------------------------
    def next_run_id(self, run_key: str) -> str:
        (n,) = self._run("SELECT count(*) FROM ops.runs WHERE run_key = ?", [run_key])[0]
        return f"{run_key}#{n + 1}"

    def start_run(self, run_key: str, run_id: str, kind: str, start: date, end: date) -> None:
        self._run(
            "INSERT INTO ops.runs VALUES (?, ?, ?, ?, ?, 'running', now(), NULL, NULL)",
            [run_key, run_id, kind, start, end],
        )

    def open_run(self, run_key: str) -> str | None:
        """The id of a run for this key that is still in progress, if any (resumable)."""
        rows = self._run(
            "SELECT run_id FROM ops.runs "
            "WHERE run_key = ? AND status IN ('running', 'interrupted') "
            "ORDER BY started_at DESC, rowid DESC LIMIT 1",
            [run_key],
        )
        return rows[0][0] if rows else None

    def finish_run(self, run_id: str, status: str, error: str | None = None) -> None:
        self._run(
            "UPDATE ops.runs SET status = ?, finished_at = now(), error = ? WHERE run_id = ?",
            [status, error, run_id],
        )

    # -- steps -------------------------------------------------------------------------
    def last_success(self, run_key: str, step: str) -> str | None:
        rows = self._run(
            "SELECT input_hash FROM ops.run_steps WHERE run_key = ? AND step = ? "
            "AND status = 'succeeded' ORDER BY finished_at DESC, rowid DESC LIMIT 1",
            [run_key, step],
        )
        return rows[0][0] if rows else None

    def record_step(
        self, run_id, run_key, step, status, attempt, input_hash, seconds, detail: dict | None
    ) -> None:
        self._run(
            "INSERT INTO ops.run_steps VALUES (?, ?, ?, ?, ?, ?, now(), now(), ?, ?)",
            [run_id, run_key, step, status, attempt, input_hash, seconds,
             json.dumps(detail or {}, sort_keys=True, default=str)],
        )  # fmt: skip

    def record_input(self, run_id, name, batch_id, status, loaded, quarantined) -> None:
        self._run(
            "INSERT INTO ops.run_inputs VALUES (?, ?, ?, ?, ?, ?)",
            [run_id, name, batch_id, status, loaded, quarantined],
        )

    # -- reading -----------------------------------------------------------------------
    def runs(self, limit: int = 50) -> list[dict]:
        cols = ["run_key", "run_id", "kind", "partition_start", "partition_end", "status",
                "started_at", "finished_at", "error"]  # fmt: skip
        rows = self._run(
            f"SELECT {', '.join(cols)} FROM ops.runs ORDER BY started_at DESC, rowid DESC LIMIT ?",
            [limit],
        )
        return [dict(zip(cols, r, strict=True)) for r in rows]

    def steps(self, run_id: str) -> list[dict]:
        cols = ["step", "status", "attempt", "seconds", "detail"]
        rows = self._run(
            f"SELECT {', '.join(cols)} FROM ops.run_steps WHERE run_id = ? ORDER BY rowid", [run_id]
        )
        return [dict(zip(cols, r, strict=True)) for r in rows]

    def alerts(self, limit: int = 100) -> list[dict]:
        cols = ["raised_at", "severity", "kind", "run_id", "message"]
        rows = self._run(
            f"SELECT {', '.join(cols)} FROM ops.alerts ORDER BY raised_at DESC, rowid DESC LIMIT ?",
            [limit],
        )
        return [dict(zip(cols, r, strict=True)) for r in rows]
