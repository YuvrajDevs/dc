"""Lineage: which tables feed which, from the dbt manifest plus the engine's known reads."""

from __future__ import annotations

import json
from pathlib import Path

from trueup.warehouse import Warehouse
from trueup.warehouse.dbt_runner import DBT_DIR

MANIFEST = DBT_DIR.parent / "target" / "dbt" / "manifest.json"

# what each recon table reads, kept next to the engine's design (see recon/engine.py)
RECON_EDGES = [
    ("marts.fct_ledger_entry", "recon.ref_candidates"),
    ("marts.fct_processor_txn", "recon.ref_candidates"),
    ("recon.ref_candidates", "recon.strong_links"),
    ("recon.strong_links", "recon.txn_links"),
    ("marts.fct_ledger_entry", "recon.attr_links"),
    ("marts.fct_processor_txn", "recon.attr_links"),
    ("recon.attr_links", "recon.txn_links"),
    ("recon.fuzzy_links", "recon.txn_links"),
    ("recon.txn_links", "recon.findings"),
    ("recon.duplicate_entries", "recon.findings"),
    ("marts.fct_bank_line", "recon.payout_links"),
    ("marts.fct_payout", "recon.payout_links"),
    ("recon.payout_links", "recon.payout_summary"),
    ("recon.payout_summary", "recon.findings"),
    ("marts.dim_fx_rate", "recon.findings"),
    ("recon.findings", "ops.exceptions"),
]


def _name(node_id: str) -> str:
    parts = node_id.split(".")
    if parts[0] == "source":
        return f"raw.{parts[-1]}"
    name = parts[-1]
    return f"staging.{name}" if name.startswith("stg_") else f"marts.{name}"


def edges(manifest_path: Path = MANIFEST) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        for child, parents in manifest.get("parent_map", {}).items():
            if child.startswith(("model.", "source.")):
                for parent in parents:
                    if parent.startswith(("model.", "source.")):
                        found.append((_name(parent), _name(child)))
    return sorted(set(found)) + RECON_EDGES


def publish(wh: Warehouse) -> int:
    wh.con.execute("CREATE TABLE IF NOT EXISTS ops.lineage (parent VARCHAR, child VARCHAR)")
    wh.con.execute("DELETE FROM ops.lineage")
    rows = edges()
    wh.con.executemany("INSERT INTO ops.lineage VALUES (?, ?)", [list(e) for e in rows])
    return len(rows)


def mermaid(rows: list[tuple[str, str]] | None = None) -> str:
    rows = rows if rows is not None else edges()
    ident = lambda t: t.replace(".", "_")  # noqa: E731
    lines = ["graph LR"]
    for parent, child in rows:
        lines.append(f"  {ident(parent)}[{parent}] --> {ident(child)}[{child}]")
    return "\n".join(lines) + "\n"
