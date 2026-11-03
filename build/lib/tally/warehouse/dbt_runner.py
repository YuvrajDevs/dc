"""Run the dbt project (staging and marts) against a warehouse file."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

DBT_DIR = Path(__file__).resolve().parents[3] / "dbt"


@dataclass
class DbtSummary:
    success: bool
    counts: dict[str, int] = field(default_factory=dict)
    failures: list[str] = field(default_factory=list)


def build(db_path: str | Path, select: list[str] | None = None) -> DbtSummary:
    from dbt.cli.main import dbtRunner

    os.environ["TALLY_DB"] = str(Path(db_path).resolve())
    args = [
        "build",
        "--project-dir", str(DBT_DIR),
        "--profiles-dir", str(DBT_DIR),
        "--quiet",
    ]  # fmt: skip
    if select:
        args += ["--select", *select]
    res = dbtRunner().invoke(args)
    summary = DbtSummary(success=bool(res.success))
    results = getattr(res.result, "results", None) or []
    for r in results:
        status = str(r.status.value if hasattr(r.status, "value") else r.status)
        summary.counts[status] = summary.counts.get(status, 0) + 1
        if status in ("error", "fail"):
            summary.failures.append(f"{r.node.name}: {r.message}")
    if res.exception is not None:
        summary.failures.append(str(res.exception))
    return summary
