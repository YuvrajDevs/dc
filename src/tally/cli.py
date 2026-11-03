from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from tally.synth.config import Config
from tally.synth.generate import generate


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
    return 2
