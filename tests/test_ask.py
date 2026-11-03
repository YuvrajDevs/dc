"""Phase 7: every question is validated; unsafe ones are refused; answers are graded."""

import shutil
from datetime import timedelta
from pathlib import Path

import duckdb
import pytest

from tally.ask import ask
from tally.ask.evalset import run_eval
from tally.ask.execute import lock_down
from tally.ask.provider import extract_sql
from tally.ask.redteam import UNSAFE_QUESTIONS, UNSAFE_SQL
from tally.ask.validate import MAX_ESTIMATED_ROWS, Refused, check_plan, validate
from tally.pipeline import load_world
from tally.recon import ReconConfig, reconcile
from tally.recon import queue as xq
from tally.synth.config import HARD, Config
from tally.synth.generate import generate
from tally.warehouse import Warehouse

PASS_FLOOR = 0.95


@pytest.fixture(scope="module")
def con(tmp_path_factory):
    root = tmp_path_factory.mktemp("ask")
    cfg = Config(seed=41, days=30, merchants=12, txns_per_day=300, hardness=HARD)
    generate(cfg, root / "world")
    load_world(root / "world", root / "wh.duckdb")
    with Warehouse(root / "wh.duckdb") as wh:
        reconcile(wh, ReconConfig(as_of=cfg.start + timedelta(days=cfg.days + 5)))
        xq.sync(wh)
        wh.con.execute("CHECKPOINT")  # fold the write-ahead log into the file before copying it
    shutil.copy(root / "wh.duckdb", root / "serve.duckdb")  # the service gets its own file
    c = duckdb.connect(str(root / "serve.duckdb"))
    lock_down(c)
    yield c
    c.close()


class Fake:
    name = "fake"

    def __init__(self, sql=None, boom=False):
        self.sql, self.boom = sql, boom

    def generate(self, question, schema_prompt):
        if self.boom:
            raise TimeoutError("network down")
        return self.sql


# ---- the grade ---------------------------------------------------------------------------
def test_the_assistant_meets_its_accuracy_floor(con):
    report = run_eval(con)
    failures = [r for r in report["results"] if not r["ok"]]
    assert report["total"] >= 40
    assert report["rate"] >= PASS_FLOOR, failures
    assert not failures, failures  # today it is perfect; a regression should be noticed


# ---- red team: every hostile input is refused ------------------------------------------------
@pytest.mark.parametrize("sql", UNSAFE_SQL, ids=lambda s: s[:50] or "<empty>")
def test_unsafe_sql_is_refused_by_the_validator(sql):
    with pytest.raises(Refused):
        validate(sql)


@pytest.mark.parametrize("sql", [s for s in UNSAFE_SQL if s.strip()], ids=lambda s: s[:40])
def test_unsafe_sql_from_a_language_model_never_runs(con, sql):
    before = con.execute("SELECT count(*) FROM ops.exceptions").fetchone()[0]
    result = ask(
        con, "A question the planner cannot answer, so the model is asked xyzzy", Fake(sql)
    )
    assert result.status == "refused", (sql, result.status, result.reason)
    assert con.execute("SELECT count(*) FROM ops.exceptions").fetchone()[0] == before


@pytest.mark.parametrize("question", UNSAFE_QUESTIONS)
def test_unsafe_questions_are_declined_and_change_nothing(con, question):
    before = con.execute("SELECT count(*) FROM ops.exceptions").fetchone()[0]
    result = ask(con, question, Fake("SELECT 1"))  # even a model must not be consulted
    assert result.status in ("refused", "no_answer"), result
    assert result.source != "llm"
    assert con.execute("SELECT count(*) FROM ops.exceptions").fetchone()[0] == before
    con.execute("SELECT count(*) FROM recon.findings").fetchone()  # still there


def test_the_engine_itself_blocks_file_access_and_config_changes(con):
    for sql in (
        "SELECT * FROM read_csv('/etc/hostname')",
        "COPY (SELECT 1) TO '/tmp/claude-0/leak.csv'",
        "SET enable_external_access = true",
    ):
        with pytest.raises(duckdb.Error):
            con.execute(sql)
    assert not Path("/tmp/claude-0/leak.csv").exists()


def test_the_plan_check_catches_what_the_parser_might_miss():
    with pytest.raises(Refused, match="reads files"):
        check_plan("│ Function: READ_CSV │")
    with pytest.raises(Refused, match="touches"):
        check_plan("│ Table: warehouse.raw.ledger_entries │")
    with pytest.raises(Refused, match="over the limit"):
        check_plan(f"│ Table: warehouse.recon.findings │ ~{MAX_ESTIMATED_ROWS + 1:,} rows")
    assert check_plan("│ Table: warehouse.recon.findings │ ~1,138 rows") == 1138


# ---- what is allowed ---------------------------------------------------------------------
def test_a_plain_select_runs_and_is_row_capped(con):
    r = ask(con, "x", Fake("SELECT * FROM marts.fct_ledger_entry"))
    assert r.status == "ok" and len(r.rows) == 1000 and r.truncated
    assert "LIMIT 1000" in r.sql.upper()


def test_a_larger_limit_is_lowered_and_a_smaller_one_kept(con):
    assert "1000" in validate("SELECT * FROM recon.findings LIMIT 99999").sql
    assert "LIMIT 5" in validate("SELECT * FROM recon.findings LIMIT 5").sql.upper()


def test_ctes_joins_and_unions_over_allowed_tables_work(con):
    r = ask(
        con,
        "x",
        Fake(
            "WITH a AS (SELECT class, count(*) n FROM recon.findings GROUP BY 1) "
            "SELECT a.class, a.n, f.category FROM a JOIN recon.findings f ON f.class = a.class "
            "GROUP BY 1, 2, 3 ORDER BY 2 DESC"
        ),
    )
    assert r.status == "ok" and r.rows
    u = ask(
        con, "x", Fake("SELECT class FROM recon.findings UNION SELECT class FROM recon.findings")
    )
    assert u.status == "ok"


def test_a_slow_query_is_stopped(con, monkeypatch):
    from tally.ask import execute

    monkeypatch.setattr(execute, "TIMEOUT_SECONDS", 0.001)
    r = ask(
        con,
        "x",
        Fake(
            "SELECT count(*) FROM marts.fct_ledger_entry a JOIN marts.fct_ledger_entry b "
            "ON a.merchant_id = b.merchant_id"
        ),
    )
    assert r.status == "refused" and r.code in ("timeout", "too_expensive")


# ---- behaviour around the model and the audit log ----------------------------------------------
def test_the_planner_answers_known_questions_without_a_model(con):
    r = ask(con, "How many open exceptions are there?", Fake("SELECT 1"))
    assert r.source == "planner" and r.status == "ok"


def test_unknown_questions_without_a_model_get_helpful_examples(con):
    r = ask(con, "What colour is the sky over the warehouse?")
    assert r.status == "no_answer" and r.examples


def test_a_model_outage_is_reported_not_raised(con):
    r = ask(con, "A question only a model could answer qwerty", Fake(boom=True))
    assert r.status == "error" and r.code == "provider_error"


def test_model_sql_is_extracted_from_a_fenced_block():
    assert extract_sql("Sure!\n```sql\nSELECT 1\n```\nHope that helps") == "SELECT 1"


def test_every_question_is_logged_with_its_outcome(con):
    ask(con, "How many fee variances are there?", actor="amina")
    ask(con, "Drop table recon.findings", actor="amina")
    rows = con.execute(
        "SELECT status, code FROM ops.ask_log WHERE actor = 'amina' ORDER BY asked_at DESC LIMIT 2"
    ).fetchall()
    assert ("refused", "unsafe_request") in rows and ("ok", "") in rows
