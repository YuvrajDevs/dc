"""Quality-gated, idempotent loading into DuckDB.

Layers
  raw         rows exactly as received (all text) plus load metadata; append-only
  quarantine  rows that failed their contract, with the reason
  ops         a log of every batch: loaded, skipped as a repeat, or rejected

A batch is a directory of CSV files. Its identity is a hash of its contents, so loading the
same batch twice is a no-op. The gate rejects a whole batch for structural problems and
quarantines individual bad rows only while the bad-row rate stays under a limit.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import duckdb

from trueup.warehouse.contracts import CONTRACTS, FORBIDDEN_FILES, Contract

MAX_BAD_ROW_RATE = 0.01
META = ("_batch_id", "_batch_seq", "_row_number", "_loaded_at", "_source_file")


@dataclass
class LoadResult:
    batch_id: str
    status: str  # loaded | loaded_with_quarantine | skipped_duplicate | rejected
    reasons: list[str] = field(default_factory=list)
    rows_loaded: dict[str, int] = field(default_factory=dict)
    rows_quarantined: dict[str, int] = field(default_factory=dict)
    ignored_files: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.status != "rejected"


def batch_fingerprint(files: dict[str, Path]) -> str:
    h = hashlib.sha256()
    for name in sorted(files):
        h.update(name.encode())
        h.update(hashlib.sha256(files[name].read_bytes()).digest())
    return h.hexdigest()


def _cast(col, alias: str = "r") -> str:
    return f"try_cast({alias}.{col.name} AS {col.type})"


def _reason_sql(contract: Contract) -> str:
    """One SQL expression listing every rule a row breaks, or NULL if it is fine."""
    parts: list[str] = []
    for c in contract.columns:
        ref = f"r.{c.name}"
        if not c.nullable:
            parts.append(
                f"CASE WHEN {ref} IS NULL OR trim({ref}) = '' THEN '{c.name}: missing' END"
            )
        if c.type != "VARCHAR":
            parts.append(
                f"CASE WHEN {ref} IS NOT NULL AND trim({ref}) <> '' AND {_cast(c)} IS NULL "
                f"THEN '{c.name}: {c.type.lower()} expected, got ''' || {ref} || '''' END"
            )
        if c.minimum is not None:
            parts.append(
                f"CASE WHEN {_cast(c)} < {c.minimum} "
                f"THEN '{c.name}: must be at least {c.minimum}' END"
            )
        if c.allowed:
            allowed = ", ".join(f"'{a}'" for a in c.allowed)
            parts.append(
                f"CASE WHEN {ref} IS NOT NULL AND trim({ref}) <> '' AND {ref} NOT IN ({allowed}) "
                f"THEN '{c.name}: ''' || {ref} || ''' is not allowed' END"
            )
    by_name = {c.name: c for c in contract.columns}
    name_pattern = re.compile(r"\b(" + "|".join(by_name) + r")\b")

    def typed_name(m: re.Match) -> str:
        return _cast(by_name[m.group(1)])

    for message, predicate in contract.row_rules:
        typed = name_pattern.sub(typed_name, predicate)
        parts.append(f"CASE WHEN NOT coalesce({typed}, true) THEN '{message}' END")
    joined = ",\n    ".join(parts)
    return f"nullif(array_to_string(list_filter([{joined}], lambda x: x IS NOT NULL), '; '), '')"


class Warehouse:
    def __init__(self, path: str | Path):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.con = duckdb.connect(self.path)
        self._init_schema()

    def close(self) -> None:
        self.con.close()

    def __enter__(self) -> Warehouse:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- schema ------------------------------------------------------------------------
    def _init_schema(self) -> None:
        c = self.con
        for schema in ("raw", "quarantine", "ops", "staging", "marts"):
            c.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
        for contract in CONTRACTS.values():
            cols = ", ".join(f"{n} VARCHAR" for n in contract.names)
            c.execute(
                f"CREATE TABLE IF NOT EXISTS raw.{contract.source} ({cols}, "
                "_batch_id VARCHAR, _batch_seq INTEGER, _row_number INTEGER, "
                "_loaded_at TIMESTAMP, _source_file VARCHAR)"
            )
        c.execute(
            "CREATE TABLE IF NOT EXISTS quarantine.rejected_rows (batch_id VARCHAR, "
            "source VARCHAR, row_number INTEGER, reason VARCHAR, row_json VARCHAR, "
            "quarantined_at TIMESTAMP)"
        )
        c.execute(
            "CREATE TABLE IF NOT EXISTS ops.load_log (batch_id VARCHAR, batch_seq INTEGER, "
            "status VARCHAR, reasons VARCHAR, rows_loaded VARCHAR, rows_quarantined VARCHAR, "
            "logged_at TIMESTAMP)"
        )

    # -- loading -----------------------------------------------------------------------
    def load_batch(self, batch_dir: str | Path) -> LoadResult:
        batch_dir = Path(batch_dir)
        present = {p.stem: p for p in sorted(batch_dir.glob("*.csv"))}
        files = {k: v for k, v in present.items() if k in CONTRACTS}
        ignored = sorted(
            p.name for p in batch_dir.iterdir() if p.is_file() and p.stem not in CONTRACTS
        )
        forbidden = [n for n in ignored if n in FORBIDDEN_FILES]
        batch_id = batch_fingerprint(files)[:16]
        result = LoadResult(batch_id=batch_id, status="rejected", ignored_files=ignored)

        if not files:
            result.reasons.append("batch contains no recognised source files")
            return self._log(result)

        done = self.con.execute(
            "SELECT 1 FROM ops.load_log WHERE batch_id = ? "
            "AND status IN ('loaded', 'loaded_with_quarantine')",
            [batch_id],
        ).fetchone()
        if done:
            result.status = "skipped_duplicate"
            result.reasons.append("identical batch already loaded")
            return self._log(result)

        # Phase 1: validate everything without touching any data table.
        staged: dict[str, tuple[str, int, int]] = {}  # source -> (temp table, good, bad)
        for source, path in files.items():
            problem, info = self._validate_file(source, path)
            if problem:
                result.reasons.append(f"{source}: {problem}")
            else:
                staged[source] = info
        for source, (_, good, bad) in staged.items():
            total = good + bad
            if total and bad / total > MAX_BAD_ROW_RATE:
                result.reasons.append(
                    f"{source}: {bad} of {total} rows ({bad / total:.1%}) failed the contract, "
                    f"over the {MAX_BAD_ROW_RATE:.0%} limit"
                )
        if result.reasons:
            return self._log(result)

        # Phase 2: apply atomically.
        seq = self.con.execute(
            "SELECT coalesce(max(batch_seq), 0) + 1 FROM ops.load_log "
            "WHERE status IN ('loaded', 'loaded_with_quarantine')"
        ).fetchone()[0]
        self.con.execute("BEGIN")
        try:
            for source, (tmp, good, bad) in staged.items():
                contract = CONTRACTS[source]
                names = ", ".join(contract.names)
                self.con.execute(
                    f"INSERT INTO raw.{source} SELECT {names}, ?, ?, _row_number, now(), ? "
                    f"FROM {tmp} WHERE _reason IS NULL ORDER BY _row_number",
                    [batch_id, seq, files[source].name],
                )
                self.con.execute(
                    "INSERT INTO quarantine.rejected_rows "
                    "SELECT ?, ?, _row_number, _reason, "
                    f"to_json(struct_pack({_pack(contract)})), now() "
                    f"FROM {tmp} WHERE _reason IS NOT NULL ORDER BY _row_number",
                    [batch_id, source],
                )
                result.rows_loaded[source] = good
                if bad:
                    result.rows_quarantined[source] = bad
            self.con.execute("COMMIT")
        except Exception:
            self.con.execute("ROLLBACK")
            raise
        result.status = "loaded_with_quarantine" if result.rows_quarantined else "loaded"
        if forbidden:
            result.reasons.append(f"ignored grader-only files: {', '.join(forbidden)}")
        return self._log(result, seq)

    def _validate_file(self, source: str, path: Path):
        """Return (problem, None) for a structural failure, else (None, (temp table, good, bad))."""
        contract = CONTRACTS[source]
        tmp = f"_in_{source}"
        self.con.execute(
            f"CREATE OR REPLACE TEMP TABLE {tmp}_raw AS "
            "SELECT row_number() OVER () AS _row_number, * "
            "FROM read_csv(?, header = true, all_varchar = true, parallel = false)",
            [str(path)],
        )
        header = {r[0] for r in self.con.execute(f"DESCRIBE {tmp}_raw").fetchall()}
        missing = [n for n in contract.names if n not in header]
        if missing:
            return f"missing required column(s): {', '.join(missing)}", None
        rows = self.con.execute(f"SELECT count(*) FROM {tmp}_raw").fetchone()[0]
        if rows == 0 and not contract.allow_empty:
            return "file has no data rows", None
        self.con.execute(
            f"CREATE OR REPLACE TEMP TABLE {tmp} AS SELECT r.*, {_reason_sql(contract)} AS _reason "
            f"FROM {tmp}_raw r"
        )
        bad = self.con.execute(f"SELECT count(*) FROM {tmp} WHERE _reason IS NOT NULL").fetchone()[
            0
        ]
        return None, (tmp, rows - bad, bad)

    def _log(self, result: LoadResult, seq: int | None = None) -> LoadResult:
        self.con.execute(
            "INSERT INTO ops.load_log VALUES (?, ?, ?, ?, ?, ?, now())",
            [
                result.batch_id,
                seq,
                result.status,
                json.dumps(result.reasons),
                json.dumps(result.rows_loaded, sort_keys=True),
                json.dumps(result.rows_quarantined, sort_keys=True),
            ],
        )
        return result

    # -- inspection --------------------------------------------------------------------
    def fingerprints(
        self, schemas: tuple[str, ...] = ("raw", "staging", "marts"), exclude: tuple[str, ...] = ()
    ) -> dict[str, tuple[int, str]]:
        """A (row count, content hash) per table. Order of rows never matters."""
        out: dict[str, tuple[int, str]] = {}
        tables = self.con.execute(
            "SELECT table_schema, table_name FROM information_schema.tables "
            "WHERE table_schema IN (SELECT unnest(?)) AND table_type = 'BASE TABLE' "
            "ORDER BY 1, 2",
            [list(schemas)],
        ).fetchall()
        for schema, table in tables:
            cols = [
                r[0]
                for r in self.con.execute(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = ? AND table_name = ? ORDER BY ordinal_position",
                    [schema, table],
                ).fetchall()
                if r[0] not in exclude
            ]
            if not cols:
                continue
            row = ", ".join(f'"{c}"' for c in cols)
            n, digest = self.con.execute(
                "SELECT count(*), "
                "md5(coalesce(string_agg(md5(t::varchar), '' ORDER BY t::varchar), '')) "
                f"FROM (SELECT {row} FROM {schema}.{table}) t"
            ).fetchone()
            out[f"{schema}.{table}"] = (n, digest)
        return out


def _pack(contract: Contract) -> str:
    return ", ".join(f"{n} := {n}" for n in contract.names)
