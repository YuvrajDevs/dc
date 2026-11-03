"""Turn one generated world into daily deliveries, optionally with late-arriving rows.

Real data does not arrive in one file. Each day brings new rows, and some arrive days after
the event they describe. The answer key is never copied: it belongs to the grader only.
"""

from __future__ import annotations

import csv
import json
import random
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

DATE_COLUMN = {
    "ledger_entries": "booked_at",
    "processor_txns": "captured_at",
    "processor_payouts": "payout_date",
    "bank_lines": "value_date",
}
REFERENCE = ("merchants", "fee_schedule", "fx_rates")


def split_world(
    world_dir: Path, out_dir: Path, late_rate: float = 0.0, seed: int = 0
) -> list[Path]:
    rng = random.Random(f"split:{seed}")
    out_dir.mkdir(parents=True, exist_ok=True)
    batches: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    headers: dict[str, list[str]] = {}
    late_counts: dict[str, int] = defaultdict(int)

    ref_key = "0000-reference"
    for name in REFERENCE:
        with (world_dir / f"{name}.csv").open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            headers[name] = list(reader.fieldnames or [])
            batches[ref_key][name] = list(reader)

    all_days: list[date] = []
    for name, col in DATE_COLUMN.items():
        with (world_dir / f"{name}.csv").open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            headers[name] = list(reader.fieldnames or [])
            for row in reader:
                day = date.fromisoformat(row[col][:10])
                all_days.append(day)
                delivered = day
                if late_rate and rng.random() < late_rate:
                    delivered = day + timedelta(days=rng.randint(1, 3))
                    late_counts[delivered.isoformat()] += 1
                batches[delivered.isoformat()][name].append(row)

    written: list[Path] = []
    for key in sorted(batches):
        d = out_dir / key
        d.mkdir(exist_ok=True)
        for name, rows in batches[key].items():
            with (d / f"{name}.csv").open("w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=headers[name], lineterminator="\n")
                w.writeheader()
                w.writerows(rows)
        (d / "batch.json").write_text(
            json.dumps({"delivered": key, "late_rows": late_counts.get(key, 0)}, sort_keys=True)
            + "\n"
        )
        written.append(d)
    return written
