"""Run an already-validated query with a timeout and a row cap."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

import duckdb

from tally.ask.validate import ROW_CAP, Refused, Validated, check_plan

TIMEOUT_SECONDS = 10.0


def lock_down(con: duckdb.DuckDBPyConnection) -> None:
    """Process-wide, one-way: no file access, and the setting cannot be changed back."""
    con.execute("SET enable_external_access = false")
    con.execute("SET lock_configuration = true")


@dataclass
class Rows:
    columns: list[str]
    rows: list[list]
    truncated: bool
    estimated_rows: int
    milliseconds: int


def _jsonable(v):
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    if isinstance(v, Decimal):
        return float(v)
    return v


def run(con: duckdb.DuckDBPyConnection, q: Validated, row_cap: int = ROW_CAP) -> Rows:
    cur = con.cursor()
    try:
        runnable = q.run_sql or q.sql
        plan = cur.execute(f"EXPLAIN {runnable}").fetchall()[0][1]
    except duckdb.Error as exc:
        raise Refused(
            "invalid_query", f"The query is not valid: {str(exc).splitlines()[0][:160]}"
        ) from exc
    estimated = check_plan(plan)

    timer = threading.Timer(TIMEOUT_SECONDS, cur.interrupt)
    timer.start()
    t0 = time.perf_counter()
    try:
        cur.execute(runnable)
        columns = [d[0] for d in cur.description]
        fetched = cur.fetchmany(row_cap + 1)
    except duckdb.InterruptException as exc:
        raise Refused(
            "timeout", f"The query took longer than {TIMEOUT_SECONDS:.0f} seconds."
        ) from exc
    except duckdb.Error as exc:
        raise Refused(
            "invalid_query", f"The query failed: {str(exc).splitlines()[0][:160]}"
        ) from exc
    finally:
        timer.cancel()
    truncated = len(fetched) > row_cap
    rows = [[_jsonable(v) for v in r] for r in fetched[:row_cap]]
    return Rows(columns, rows, truncated, estimated, int((time.perf_counter() - t0) * 1000))
