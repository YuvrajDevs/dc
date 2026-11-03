"""Ask a question: plan, validate, run, and keep an audit trail."""

from __future__ import annotations

import contextlib
import re
import time
from dataclasses import dataclass, field

import duckdb

from tally.ask import execute, planner
from tally.ask.provider import SQLProvider
from tally.ask.schema import ALLOWED, DESCRIPTIONS
from tally.ask.validate import Refused, Validated, validate

EXAMPLES = [
    "Which payouts are missing from the bank?",
    "How many open exceptions are there?",
    "Show the 10 largest fee variances",
    "Which merchants have the most exceptions?",
    "How much money is at stake by class?",
    "List late payouts in the last 14 days",
    "How many duplicate ledger bookings are there?",
]


@dataclass
class AskResult:
    question: str
    status: str  # ok | refused | no_answer | error
    source: str = ""  # planner | llm
    sql: str = ""
    explanation: str = ""
    columns: list[str] = field(default_factory=list)
    rows: list[list] = field(default_factory=list)
    truncated: bool = False
    notes: list[str] = field(default_factory=list)
    reason: str = ""
    code: str = ""
    milliseconds: int = 0
    examples: list[str] = field(default_factory=list)


WRITE_INTENT = re.compile(
    r"^\s*(please\s+|can you\s+|could you\s+|kindly\s+)?"
    r"(delete|remove|erase|wipe|insert|update|modify|overwrite|change|alter|create|add|copy|export|"
    r"dump|download|mark|set|resolve|close|reopen|run|execute)\b",
    re.I,
)
UNSAFE = re.compile(
    r"\b(drop|truncate|alter|attach|detach|pragma|install)\b"
    r"|delete\s+from|insert\s+into|update\s+\w+\s+set|create\s+(table|view|schema)|copy\s+\S+\s+to"
    r"|read_(csv|parquet|json|text)|/etc/|passwd|\.csv\b|\.parquet\b|\bselect\s+.+\s+from\b|;\s*\w"
    r"|ignore\s+(all\s+|the\s+|your\s+|previous\s+)*(rules|instructions|guardrails)"
    r"|system\s+prompt|api[_ ]?key|environment\s+variable",
    re.I,
)


def unsafe_question(question: str) -> bool:
    """Questions that try to change data, read files or talk the assistant out of its rules."""
    return bool(UNSAFE.search(question) or WRITE_INTENT.search(question))


def schema_prompt(con: duckdb.DuckDBPyConnection) -> str:
    lines = []
    for schema, tables in ALLOWED.items():
        for t in tables:
            cols = con.execute(
                "SELECT column_name, data_type FROM information_schema.columns "
                "WHERE table_schema = ? AND table_name = ? ORDER BY ordinal_position",
                [schema, t],
            ).fetchall()
            if cols:
                body = ", ".join(f"{c} {d}" for c, d in cols)
                lines.append(f"{schema}.{t} ({body})  -- {DESCRIPTIONS[f'{schema}.{t}']}")
    return "\n".join(lines)


def ensure_log(con: duckdb.DuckDBPyConnection) -> None:
    con.execute("CREATE SCHEMA IF NOT EXISTS ops")
    con.execute(
        "CREATE TABLE IF NOT EXISTS ops.ask_log (asked_at TIMESTAMP, actor VARCHAR, question VARCHAR, "
        "source VARCHAR, sql VARCHAR, status VARCHAR, code VARCHAR, reason VARCHAR, row_count INTEGER, "
        "milliseconds INTEGER)"
    )


def _log(con, actor: str, r: AskResult) -> None:
    with contextlib.suppress(duckdb.Error):  # the audit log must never break an answer
        con.execute(
            "INSERT INTO ops.ask_log VALUES (now(), ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [actor, r.question[:500], r.source, r.sql[:4000], r.status, r.code, r.reason[:500],
             len(r.rows), r.milliseconds],
        )  # fmt: skip


def ask(
    con: duckdb.DuckDBPyConnection,
    question: str,
    provider: SQLProvider | None = None,
    actor: str = "analyst",
) -> AskResult:
    t0 = time.perf_counter()
    ensure_log(con)
    result = AskResult(question=question, status="no_answer")
    source, sql, explanation = "", "", ""

    unsafe = unsafe_question(question)
    if unsafe:
        result.status, result.code = "refused", "unsafe_request"
        result.reason = (
            "I only answer read-only questions about the reconciliation data. "
            "To change an exception's status, use the Exceptions page."
        )
        result.milliseconds = int((time.perf_counter() - t0) * 1000)
        _log(con, actor, result)
        return result

    plan = planner.plan(question)
    if plan:
        source, sql, explanation = "planner", plan.sql, plan.explanation
    elif provider is not None:
        try:
            sql = provider.generate(question, schema_prompt(con))
            source, explanation = (
                "llm",
                "SQL proposed by a language model and checked before running.",
            )
        except Exception as exc:  # network, quota, bad response
            result.status, result.reason, result.code = (
                "error",
                f"The assistant is unavailable: {type(exc).__name__}.",
                "provider_error",
            )
    if not sql:
        if result.status != "error":
            result.reason = "I don't know how to answer that yet."
            result.examples = EXAMPLES
        result.milliseconds = int((time.perf_counter() - t0) * 1000)
        _log(con, actor, result)
        return result

    result.source, result.sql, result.explanation = source, sql, explanation
    try:
        checked: Validated = validate(sql)
        result.sql, result.notes = checked.sql, checked.notes
        out = execute.run(con, checked)
        result.status = "ok"
        result.columns, result.rows, result.truncated = out.columns, out.rows, out.truncated
        if out.truncated:
            result.notes.append(f"Showing the first {len(out.rows)} rows.")
    except Refused as r:
        result.status, result.reason, result.code = "refused", r.reason, r.code
    result.milliseconds = int((time.perf_counter() - t0) * 1000)
    _log(con, actor, result)
    return result
