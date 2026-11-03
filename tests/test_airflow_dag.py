"""The Airflow DAG: structure is always checked; it is parsed for real if Airflow is installed."""

import ast
import importlib.util
from pathlib import Path

import pytest

DAG = Path(__file__).parents[1] / "orchestration" / "airflow" / "dags" / "tally_daily.py"


def test_dag_declares_the_four_steps_in_order_with_safe_defaults():
    source = DAG.read_text()
    tree = ast.parse(source)
    funcs = [n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
    for step in ("ingest", "build", "reconcile", "publish"):
        assert step in funcs
    assert "ingest() >> build() >> reconcile() >> publish()" in source
    assert "max_active_runs=1" in source  # the warehouse file is single-writer
    assert '"retry_exponential_backoff": True' in source
    assert "AirflowFailException" in source  # bad data fails fast instead of retrying
    assert "TALLY_ALERT_WEBHOOK" in source


@pytest.mark.skipif(importlib.util.find_spec("airflow") is None, reason="Airflow is not installed")
def test_dag_parses_in_airflow():
    from airflow.models import DagBag

    bag = DagBag(dag_folder=str(DAG.parent), include_examples=False)
    assert not bag.import_errors
    dag = bag.get_dag("tally_daily")
    assert [t.task_id for t in dag.topological_sort()] == [
        "ingest",
        "build",
        "reconcile",
        "publish",
    ]
