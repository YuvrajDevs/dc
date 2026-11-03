"""Vercel entry point: serves the TrueUp API from the bundled demo database.

Vercel's filesystem is read-only except /tmp, so the database is copied there on a cold start.
Decisions made in the demo live in that copy and reset when the instance is recycled.
"""

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tally.api import create_app  # noqa: E402

DB = Path("/tmp/tally_demo.duckdb")
if not DB.exists():
    shutil.copyfile(ROOT / "demo" / "serve.duckdb", DB)

app = create_app(DB, bench_dir=ROOT / "benchmarks", allow_origins=["*"])
