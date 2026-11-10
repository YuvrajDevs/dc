"""The exception queue: a status and an audit trail for every finding.

Findings are rebuilt on every run, but what people decided about them must survive. The queue
keeps one row per finding id (a stable hash of class and records) and appends an event for every
change, with who made it and why.
"""

from __future__ import annotations

from trueup.warehouse import Warehouse

STATUSES = ("open", "explained", "resolved", "auto_cleared")
HUMAN_STATUSES = ("open", "explained", "resolved")
NOTE_REQUIRED = ("explained", "resolved")


def ensure_tables(wh: Warehouse) -> None:
    wh.con.execute(
        "CREATE TABLE IF NOT EXISTS ops.exceptions (finding_id VARCHAR, class VARCHAR, "
        "category VARCHAR, level VARCHAR, entities VARCHAR, amount_at_stake_minor BIGINT, "
        "currency VARCHAR, reason VARCHAR, status VARCHAR, note VARCHAR, updated_by VARCHAR, "
        "first_seen TIMESTAMP, updated_at TIMESTAMP)"
    )
    wh.con.execute(
        "CREATE TABLE IF NOT EXISTS ops.exception_events (finding_id VARCHAR, "
        "occurred_at TIMESTAMP, "
        "actor VARCHAR, from_status VARCHAR, to_status VARCHAR, note VARCHAR)"
    )


def _event(
    wh: Warehouse, finding_id: str, actor: str, old: str | None, new: str, note: str
) -> None:
    wh.con.execute(
        "INSERT INTO ops.exception_events VALUES (?, now(), ?, ?, ?, ?)",
        [finding_id, actor, old, new, note],
    )


def sync(wh: Warehouse, actor: str = "engine") -> dict[str, int]:
    """Bring the queue in line with the latest findings, never overwriting a human decision."""
    ensure_tables(wh)
    con = wh.con
    new_rows = con.execute(
        "SELECT f.finding_id, f.status FROM recon.findings f "
        "WHERE f.finding_id NOT IN (SELECT finding_id FROM ops.exceptions)"
    ).fetchall()
    con.execute(
        "INSERT INTO ops.exceptions SELECT finding_id, class, category, level, entities, "
        "amount_at_stake_minor, currency, reason, status, NULL, ?, now(), now() "
        "FROM recon.findings WHERE finding_id NOT IN (SELECT finding_id FROM ops.exceptions)",
        [actor],
    )
    for finding_id, status in new_rows:
        _event(wh, finding_id, actor, None, status, "first reported")

    reopened = con.execute(
        "SELECT e.finding_id FROM ops.exceptions e JOIN recon.findings f USING (finding_id) "
        "WHERE e.status = 'auto_cleared'"
    ).fetchall()
    for (finding_id,) in reopened:
        con.execute(
            "UPDATE ops.exceptions SET status = 'open', updated_by = ?, updated_at = now() "
            "WHERE finding_id = ?",
            [actor, finding_id],
        )
        _event(wh, finding_id, actor, "auto_cleared", "open", "reported again")

    cleared = con.execute(
        "SELECT finding_id FROM ops.exceptions WHERE status = 'open' "
        "AND finding_id NOT IN (SELECT finding_id FROM recon.findings)"
    ).fetchall()
    for (finding_id,) in cleared:
        con.execute(
            "UPDATE ops.exceptions SET status = 'auto_cleared', updated_by = ?, updated_at = now() "
            "WHERE finding_id = ?",
            [actor, finding_id],
        )
        _event(wh, finding_id, actor, "open", "auto_cleared", "no longer reported by the engine")

    # keep the descriptive text current without touching status or notes
    con.execute(
        "UPDATE ops.exceptions SET reason = f.reason, "
        "amount_at_stake_minor = f.amount_at_stake_minor "
        "FROM recon.findings f WHERE ops.exceptions.finding_id = f.finding_id"
    )
    return {"new": len(new_rows), "reopened": len(reopened), "auto_cleared": len(cleared)}


def set_status(wh: Warehouse, finding_id: str, status: str, actor: str, note: str = "") -> None:
    ensure_tables(wh)
    if status not in HUMAN_STATUSES:
        raise ValueError(f"status must be one of {HUMAN_STATUSES}, got {status!r}")
    if not actor.strip():
        raise ValueError("an actor is required so the audit trail says who made the change")
    if status in NOTE_REQUIRED and not note.strip():
        raise ValueError(f"a note is required when marking a finding {status}")
    row = wh.con.execute(
        "SELECT status FROM ops.exceptions WHERE finding_id = ?", [finding_id]
    ).fetchone()
    if row is None:
        raise KeyError(f"unknown finding {finding_id}")
    old = row[0]
    if old == status:
        return
    wh.con.execute(
        "UPDATE ops.exceptions SET status = ?, note = ?, updated_by = ?, updated_at = now() "
        "WHERE finding_id = ?",
        [status, note, actor, finding_id],
    )
    _event(wh, finding_id, actor, old, status, note)


def history(wh: Warehouse, finding_id: str) -> list[dict]:
    rows = wh.con.execute(
        "SELECT occurred_at, actor, from_status, to_status, note FROM ops.exception_events "
        "WHERE finding_id = ? ORDER BY occurred_at, rowid",
        [finding_id],
    ).fetchall()
    return [{"at": r[0], "actor": r[1], "from": r[2], "to": r[3], "note": r[4]} for r in rows]
