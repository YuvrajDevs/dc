"""Validate a SQL string before it is allowed anywhere near the warehouse.

Three independent layers, so no single parser quirk is enough to get through:

  1. the syntax tree (this module): one read-only SELECT, allow-listed tables, no file or system
     functions, no table functions, no cartesian joins, no recursion, a row cap
  2. the query plan (``check_plan``): DuckDB's own plan must scan only allow-listed tables, read
     no files, and stay under an estimated-cost limit
  3. the engine (``execute``): external access disabled and configuration locked for the process
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import sqlglot
from sqlglot import exp

from tally.ask.schema import (
    ALLOWED_PLAN_NAMES,
    ALLOWED_QUALIFIED,
    DENIED_FUNCTION_PREFIXES,
    DENIED_FUNCTIONS,
)

MAX_SQL_CHARS = 4000
ROW_CAP = 1000
MAX_ESTIMATED_ROWS = 50_000_000


class Refused(Exception):
    def __init__(self, code: str, reason: str):
        super().__init__(reason)
        self.code, self.reason = code, reason


@dataclass
class Validated:
    sql: str  # what is shown to the user (limit = cap)
    run_sql: str = ""  # what runs (limit = cap + 1, so truncation can be detected)
    tables: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _func_name(node: exp.Expression) -> str:
    if isinstance(node, exp.Anonymous):
        return str(node.this).lower()
    return (node.sql_name() or type(node).__name__).lower()


def validate(sql: str, row_cap: int = ROW_CAP) -> Validated:
    if not sql or not sql.strip():
        raise Refused("empty", "The query is empty.")
    if len(sql) > MAX_SQL_CHARS:
        raise Refused("too_long", f"The query is longer than {MAX_SQL_CHARS} characters.")
    try:
        statements = sqlglot.parse(sql.strip().rstrip(";"), read="duckdb")
    except Exception as exc:
        raise Refused(
            "unparseable", f"The query could not be parsed: {type(exc).__name__}."
        ) from exc
    statements = [s for s in statements if s is not None]
    if len(statements) != 1:
        raise Refused("multiple_statements", "Only a single statement is allowed.")
    tree = statements[0]

    if not isinstance(tree, exp.Query):
        raise Refused("not_select", f"Only SELECT queries are allowed, not {type(tree).__name__}.")

    # anything that writes, defines or controls, even nested inside a SELECT
    forbidden = (exp.Insert, exp.Update, exp.Delete, exp.Create, exp.Drop, exp.Alter, exp.Copy,
                 exp.Command, exp.Pragma, exp.Set, exp.Attach, exp.Detach, exp.Install, exp.Use,
                 exp.Merge, exp.Transaction, exp.Commit, exp.Rollback, exp.Into)  # fmt: skip
    for node in tree.walk():
        if isinstance(node, forbidden):
            raise Refused("not_read_only", f"{type(node).__name__} is not allowed.")

    if tree.find(exp.With) and any(w.args.get("recursive") for w in tree.find_all(exp.With)):
        raise Refused("recursive", "Recursive queries are not allowed.")

    # functions: no file, system or table-reading functions
    for node in tree.walk():
        if isinstance(node, (exp.Func, exp.Anonymous)):
            name = _func_name(node)
            if name in DENIED_FUNCTIONS or name.startswith(DENIED_FUNCTION_PREFIXES):
                raise Refused("denied_function", f"The function {name}() is not allowed.")

    # tables: only qualified, allow-listed tables (or CTE names defined in this query)
    cte_names = {c.alias_or_name.lower() for c in tree.find_all(exp.CTE)}
    used: list[str] = []
    for table in tree.find_all(exp.Table):
        if not isinstance(table.this, exp.Identifier):
            raise Refused("table_function", "Reading from functions or files is not allowed.")
        name, schema = table.name.lower(), (table.db or "").lower()
        if table.catalog:
            raise Refused("table_not_allowed", "Cross-database references are not allowed.")
        if not schema and name in cte_names:
            continue
        qualified = f"{schema}.{name}" if schema else name
        if qualified not in ALLOWED_QUALIFIED:
            hint = "" if schema else " Use schema-qualified names such as recon.findings."
            raise Refused("table_not_allowed", f"The table {qualified} is not available.{hint}")
        used.append(qualified)

    # no cartesian products
    for join in tree.find_all(exp.Join):
        kind = (join.args.get("kind") or "").upper()
        has_condition = bool(join.args.get("on") or join.args.get("using"))
        if kind == "CROSS" or (not has_condition and not join.args.get("method")):
            raise Refused("cartesian_join", "Joins need a condition; cross joins are not allowed.")

    shown, run = _apply_row_cap(tree, row_cap)
    return Validated(sql=shown, run_sql=run, tables=sorted(set(used)), notes=[])


def _apply_row_cap(tree: exp.Query, cap: int) -> tuple[str, str]:
    """Return (sql to show, sql to run). The run version asks for one extra row."""
    limit = tree.args.get("limit")
    if isinstance(tree, exp.Select) and limit is not None:
        expr = limit.expression
        if isinstance(expr, exp.Literal) and expr.is_int and int(expr.name) <= cap:
            same = tree.sql(dialect="duckdb")
            return same, same  # the user asked for fewer rows than the cap: nothing is cut
    if isinstance(tree, exp.Select):
        return tree.limit(cap).sql(dialect="duckdb"), tree.limit(cap + 1).sql(dialect="duckdb")
    inner = tree.sql(dialect="duckdb")
    return (
        f"SELECT * FROM ({inner}) AS q LIMIT {cap}",
        f"SELECT * FROM ({inner}) AS q LIMIT {cap + 1}",
    )


# ---- layer 2: the plan ---------------------------------------------------------------------
_TABLE = re.compile(r"Table:\s+([\w\.\"]+)")
_ROWS = re.compile(r"~([\d,]+)\s+rows?", re.I)


def check_plan(plan_text: str, max_rows: int = MAX_ESTIMATED_ROWS) -> int:
    """Check DuckDB's own plan. Returns the largest estimated row count seen."""
    if re.search(r"Function:\s*(READ_|GLOB|PARQUET|JSON|SNIFF)", plan_text, re.I):
        raise Refused("plan_reads_files", "The query plan reads files, which is not allowed.")
    for found in _TABLE.findall(plan_text):
        parts = found.replace('"', "").split(".")
        name = ".".join(parts[-2:]) if len(parts) >= 2 else parts[0]
        if name not in ALLOWED_PLAN_NAMES:
            raise Refused(
                "plan_table_not_allowed", f"The query plan touches {found}, which is not available."
            )
    biggest = max((int(m.replace(",", "")) for m in _ROWS.findall(plan_text)), default=0)
    if biggest > max_rows:
        raise Refused(
            "too_expensive", f"The query is estimated at {biggest:,} rows, over the limit."
        )
    return biggest
