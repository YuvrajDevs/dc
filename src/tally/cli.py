from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from tally import bench
from tally.grade import check_floors, grade, render_markdown
from tally.recon import ReconConfig, reconcile
from tally.recon import queue as exception_queue
from tally.synth.config import PROFILES, Config
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
    gen.add_argument("--profile", choices=sorted(PROFILES), default="easy")
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

    rec = sub.add_parser("reconcile", help="Run the reconciliation engine on the marts")
    rec.add_argument("--db", type=Path, required=True)
    rec.add_argument("--as-of", type=date.fromisoformat, default=None)

    grd = sub.add_parser("grade", help="Grade findings against a generated world's answer key")
    grd.add_argument("--db", type=Path, required=True)
    grd.add_argument("--world", type=Path, required=True)
    grd.add_argument("--json", type=Path, default=None)
    grd.add_argument("--markdown", type=Path, default=None)
    grd.add_argument("--floors", type=Path, default=None)
    grd.add_argument("--profile", choices=sorted(PROFILES), default="hard")

    chk = sub.add_parser(
        "check", help="Regression gate: run easy and hard profiles against the floors"
    )
    chk.add_argument("--floors", type=Path, default=Path("benchmarks/floors.json"))
    chk.add_argument("--days", type=int, default=60)

    stab = sub.add_parser("stability", help="Accuracy across several seeds")
    stab.add_argument("--profile", choices=sorted(PROFILES), default="hard")
    stab.add_argument("--seeds", type=int, nargs="+", default=[1, 2, 3, 4, 5])
    stab.add_argument("--days", type=int, default=40)

    scl = sub.add_parser("scale", help="Speed and memory at 10k, 100k, 1M ledger rows")
    scl.add_argument("--profile", choices=sorted(PROFILES), default="hard")
    scl.add_argument("--sizes", type=int, nargs="+", default=[10_000, 100_000, 1_000_000])
    scl.add_argument("--out", type=Path, default=None)

    one = sub.add_parser("bench-run", help=argparse.SUPPRESS)
    one.add_argument("--profile", choices=sorted(PROFILES), required=True)
    one.add_argument("--rows", type=int, required=True)

    args = parser.parse_args(argv)
    if args.command == "generate":
        cfg = Config(
            seed=args.seed,
            start=args.start,
            days=args.days,
            merchants=args.merchants,
            txns_per_day=args.txns_per_day,
            hardness=PROFILES[args.profile],
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
    if args.command == "reconcile":
        with Warehouse(args.db) as wh:
            summary = reconcile(wh, ReconConfig(as_of=args.as_of))
            counts = exception_queue.sync(wh)
        print(f"Reconciled as of {summary.as_of} in {summary.total_seconds:.2f}s")
        print(f"  links: {summary.links}   pending payouts: {summary.pending_payouts}")
        for name, n in summary.findings.items():
            print(f"    {name:<30}{n:>6}")
        print(f"  exception queue: {counts}")
        return 0
    if args.command == "grade":
        manifest = json.loads((args.world / "manifest.json").read_text())
        with Warehouse(args.db) as wh:
            card = grade(wh, args.world)
        card.meta = {
            "seed": manifest["seed"],
            "days": manifest["days"],
            "profile_hardness": manifest["hardness"],
        }
        if args.json:
            args.json.write_text(json.dumps(card.to_dict(), indent=2, sort_keys=True) + "\n")
        text = render_markdown(card)
        if args.markdown:
            args.markdown.write_text(text)
        print(text)
        if args.floors:
            failures = check_floors(card, json.loads(args.floors.read_text())[args.profile])
            for f in failures:
                print(f"FLOOR BROKEN: {f}")
            return 1 if failures else 0
        return 0
    if args.command == "check":
        floors = json.loads(args.floors.read_text())
        results = bench.check(floors, days=args.days)
        bad = 0
        for profile, failures in results.items():
            print(f"{profile}: {'OK' if not failures else 'FAILED'}")
            for f in failures:
                print(f"    FLOOR BROKEN: {f}")
            bad += len(failures)
        return 1 if bad else 0
    if args.command == "stability":
        out = bench.stability(args.profile, args.seeds, args.days, 12, 400)
        print(json.dumps(out, indent=2))
        return 0
    if args.command == "scale":
        results = bench.scale(args.profile, args.sizes)
        text = json.dumps(results, indent=2)
        if args.out:
            args.out.write_text(text + "\n")
        print(text)
        return 0
    if args.command == "bench-run":
        print(json.dumps(bench.scale_one(args.profile, args.rows)))
        return 0
    return 2
