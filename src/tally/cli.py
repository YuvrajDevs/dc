from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from tally.synth.config import Config
from tally.synth.generate import generate
from tally.warehouse import Warehouse, dbt_runner
from tally.warehouse.split import split_world


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tally", description="Tally reconciliation toolkit")
    sub = parser.add_subparsers(dest="command", required=True)

    gen = sub.add_parser("generate", help="Generate a synthetic world with an answer key")
    gen.add_argument("--seed", type=int, default=42)
    gen.add_argument("--days", type=int, default=30)
    gen.add_argument("--merchants", type=int, default=12)
    gen.add_argument("--txns-per-day", type=int, default=400)
    gen.add_argument("--start", type=date.fromisoformat, default=date(2026, 1, 1))
    gen.add_argument("--out", type=Path, required=True)

    spl = sub.add_parser("split", help="Split a generated world into daily deliveries")
    spl.add_argument("--world", type=Path, required=True)
    spl.add_argument("--out", type=Path, required=True)
    spl.add_argument("--late-rate", type=float, default=0.0)
    spl.add_argument("--seed", type=int, default=0)

    ing = sub.add_parser("ingest", help="Load delivery batches into the warehouse (quality-gated)")
    ing.add_argument("--db", type=Path, required=True)
    ing.add_argument("batches", type=Path, nargs="+")

    bld = sub.add_parser("build", help="Build staging and marts with dbt, including tests")
    bld.add_argument("--db", type=Path, required=True)

    st = sub.add_parser("status", help="Show the load log and table fingerprints")
    st.add_argument("--db", type=Path, required=True)

    args = parser.parse_args(argv)
    if args.command == "generate":
        cfg = Config(
            seed=args.seed,
            start=args.start,
            days=args.days,
            merchants=args.merchants,
            txns_per_day=args.txns_per_day,
        )
        manifest = generate(cfg, args.out)
        counts = manifest["defect_counts"]
        total = sum(counts.values())
        print(f"Wrote synthetic world to {args.out}")
        print(f"  rows: {manifest['row_counts']}")
        print(f"  injected defects: {total}")
        for name in sorted(counts):
            print(f"    {name:<22}{counts[name]:>5}")
        return 0
    if args.command == "split":
        written = split_world(args.world, args.out, args.late_rate, args.seed)
        print(f"Wrote {len(written)} deliveries to {args.out}")
        return 0
    if args.command == "ingest":
        exit_code = 0
        with Warehouse(args.db) as wh:
            for batch in args.batches:
                res = wh.load_batch(batch)
                loaded = sum(res.rows_loaded.values())
                quarantined = sum(res.rows_quarantined.values())
                print(
                    f"{batch.name:<16} {res.status:<24} loaded={loaded} quarantined={quarantined}"
                )
                for reason in res.reasons:
                    print(f"    - {reason}")
                if not res.ok:
                    exit_code = 1
        return exit_code
    if args.command == "build":
        summary = dbt_runner.build(args.db)
        print(f"dbt build: {'OK' if summary.success else 'FAILED'}  {summary.counts}")
        for failure in summary.failures:
            print(f"    - {failure}")
        return 0 if summary.success else 1
    if args.command == "status":
        with Warehouse(args.db) as wh:
            print("Load log:")
            for row in wh.con.execute(
                "SELECT batch_id, status, rows_loaded, reasons FROM ops.load_log ORDER BY logged_at"
            ).fetchall():
                print("  ", *row)
            print("Tables:")
            for name, (n, digest) in wh.fingerprints(exclude=("_loaded_at",)).items():
                print(f"  {name:<34}{n:>8}  {digest[:12]}")
        return 0
    return 2
