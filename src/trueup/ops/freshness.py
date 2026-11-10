"""Freshness: has each source delivered recently enough?"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from trueup.warehouse import Warehouse

# source -> (table, date column, days it may lag behind "today" before it is stale).
# Deliveries can arrive up to 3 days late by design, so 3 days is "on time" for daily feeds.
SOURCES = {
    "ledger_entries": ("marts.fct_ledger_entry", "booked_date", 3),
    "processor_txns": ("marts.fct_processor_txn", "captured_date", 3),
    "processor_payouts": ("marts.fct_payout", "payout_date", 3),
    "bank_lines": ("marts.fct_bank_line", "value_date", 4),
    "authorizations": ("marts.fct_authorization", "requested_date", 3),
}


@dataclass
class Freshness:
    source: str
    latest: date | None
    lag_days: int | None
    allowed_days: int
    status: str  # ok | stale | empty


def check(wh: Warehouse, as_of: date, allowed: dict[str, int] | None = None) -> list[Freshness]:
    out = []
    for source, (table, col, default_allowed) in SOURCES.items():
        if not _exists(wh, table):
            continue  # older warehouses have no card-network tables
        allowed_days = (allowed or {}).get(source, default_allowed)
        (latest,) = wh.con.execute(f"SELECT max({col}) FROM {table}").fetchone()
        if latest is None:
            out.append(Freshness(source, None, None, allowed_days, "empty"))
            continue
        lag = (as_of - latest).days
        out.append(
            Freshness(source, latest, lag, allowed_days, "ok" if lag <= allowed_days else "stale")
        )
    return out


def _exists(wh: Warehouse, table: str) -> bool:
    schema, name = table.split(".")
    return bool(
        wh.con.execute(
            "SELECT count(*) FROM information_schema.tables "
            "WHERE table_schema = ? AND table_name = ?",
            [schema, name],
        ).fetchone()[0]
    )
