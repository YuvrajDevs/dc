"""Freshness: has each source delivered recently enough?"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from tally.warehouse import Warehouse

# source -> (table, date column, days it may lag behind "today" before it is stale)
SOURCES = {
    "ledger_entries": ("marts.fct_ledger_entry", "booked_date", 2),
    "processor_txns": ("marts.fct_processor_txn", "captured_date", 2),
    "processor_payouts": ("marts.fct_payout", "payout_date", 2),
    "bank_lines": ("marts.fct_bank_line", "value_date", 4),
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
