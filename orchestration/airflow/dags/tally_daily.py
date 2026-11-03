"""Airflow DAG for the daily Tally pipeline.

Airflow owns scheduling, ordering and retries. Each task runs exactly one pipeline step through
``Pipeline.run_step``, which keeps the same run ledger, input-hash skipping and alerts as the
standalone runner. A re-run of a finished day does nothing; a backfill (``airflow backfill`` or
clearing tasks) re-processes the days asked for and gives the same result as a clean run.

Configuration (environment variables):
  TALLY_DB        path to the DuckDB warehouse file
  TALLY_BATCHES   folder holding one delivery folder per day (YYYY-MM-DD) and 0000-reference
  TALLY_ALERT_WEBHOOK   optional URL that receives alerts as JSON
"""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta
from pathlib import Path

try:  # Airflow 3
    from airflow.sdk import dag, task
except ImportError:  # Airflow 2
    from airflow.decorators import dag, task

DB = os.environ.get("TALLY_DB", "/opt/tally/data/warehouse.duckdb")
BATCHES = os.environ.get("TALLY_BATCHES", "/opt/tally/data/batches")


def _pipeline():
    from tally.ops import Pipeline, PipelineConfig  # imported lazily so the DAG parses fast

    return Pipeline(DB, PipelineConfig(batches_dir=Path(BATCHES)))


def _run_step(step: str, ds: str) -> dict:
    from tally.ops import PermanentError

    try:
        return _pipeline().run_step(step, [date.fromisoformat(ds)])
    except PermanentError as exc:
        # bad data will not fix itself: fail the task without burning retries
        try:
            from airflow.sdk.exceptions import AirflowFailException
        except ImportError:
            from airflow.exceptions import AirflowFailException
        raise AirflowFailException(str(exc)) from exc


def _alert_on_failure(context) -> None:
    from tally.ops import Alerter
    from tally.ops.ledger import Ledger

    ti = context.get("task_instance")
    Alerter(Ledger(DB)).raise_alert(
        "critical",
        "airflow_task_failed",
        f"{ti.dag_id}.{ti.task_id} failed for {context.get('ds')}",
    )


@dag(
    dag_id="tally_daily",
    schedule="0 6 * * *",
    start_date=datetime(2026, 1, 1),
    catchup=False,
    max_active_runs=1,  # the warehouse file is single-writer
    default_args={
        "retries": 3,
        "retry_delay": timedelta(minutes=2),
        "retry_exponential_backoff": True,
        "max_retry_delay": timedelta(minutes=30),
        "execution_timeout": timedelta(minutes=30),
        "on_failure_callback": _alert_on_failure,
    },
    tags=["tally", "reconciliation"],
)
def tally_daily():
    @task
    def ingest(ds=None):
        return _run_step("ingest", ds)

    @task
    def build(ds=None):
        return _run_step("build", ds)

    @task
    def reconcile(ds=None):
        return _run_step("reconcile", ds)

    @task
    def publish(ds=None):
        return _run_step("publish", ds)

    ingest() >> build() >> reconcile() >> publish()


tally_daily()
