"""Generate a synthetic world, inject known defects and write the answer key."""

from __future__ import annotations

import csv
import hashlib
import json
import random
from collections import defaultdict
from dataclasses import asdict
from datetime import date, datetime, timedelta
from pathlib import Path

from trueup.synth import world
from trueup.synth.classes import DEFECT_CLASSES
from trueup.synth.config import Config

DAY = world.DAY


def _rng(seed: int, stage: str) -> random.Random:
    """An independent, reproducible random stream per stage."""
    digest = hashlib.sha256(f"{seed}:{stage}".encode()).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


def _pick(rng: random.Random, options: list[tuple[str, float]]) -> str | None:
    """Pick at most one class, with the given probabilities (sum must be <= 1)."""
    u = rng.random()
    acc = 0.0
    for name, p in options:
        acc += p
        if u < acc:
            return name
    return None


class Key:
    """Collects the answer key: every defect, and every true link between sources."""

    def __init__(self) -> None:
        self.defects: list[dict] = []
        self.links: list[dict] = []

    def defect(self, cls: str, entities: list[tuple[str, str]], **detail) -> None:
        category, level, _ = DEFECT_CLASSES[cls]
        self.defects.append(
            {
                "class": cls,
                "category": category,
                "level": level,
                "entities": json.dumps([{"source": s, "id": i} for s, i in entities]),
                "detail": json.dumps(detail, sort_keys=True),
            }
        )

    def link(self, link_type: str, left: str, right: str) -> None:
        self.links.append({"link_type": link_type, "left_id": left, "right_id": right})


def _mangle_ref(rng: random.Random, ref: str) -> tuple[str, str]:
    mode = rng.choice(["lower_pad", "strip_prefix", "blank", "trailing_space"])
    if mode == "lower_pad":
        return f" {ref.lower()} ", mode
    if mode == "strip_prefix":
        return ref.removeprefix("ord_"), mode
    if mode == "blank":
        return "", mode
    return ref + " ", mode


COMPOUND_ORDER = ["amount_mismatch", "fee_variance", "fx_rounding", "cutoff_timing", "ref_noise"]
COMPOUNDABLE = set(COMPOUND_ORDER)


def _typo_ref(rng: random.Random, ref: str) -> tuple[str, str]:
    """Swap two neighbouring digits. The result usually names a different, real order."""
    digits = ref.removeprefix("ord_")
    spots = [i for i in range(len(digits) - 1) if digits[i] != digits[i + 1]]
    if not spots:
        return "", "blank"
    i = rng.choice(spots)
    swapped = digits[:i] + digits[i + 1] + digits[i] + digits[i + 2 :]
    return "ord_" + swapped, "typo"


def build(cfg: Config) -> dict:
    """Return all tables plus the answer key. Pure function of the config."""
    r = cfg.rates
    merchants = world.build_merchants(_rng(cfg.seed, "merchants"), cfg.merchants)
    fx = world.build_fx(_rng(cfg.seed, "fx"), cfg.start, cfg.days)
    payments = world.build_payments(_rng(cfg.seed, "payments"), cfg, merchants)

    # ---- clean ledger and processor, one row each per payment --------------------------
    ledger: list[dict] = []
    processor: list[dict] = []
    lag_rng = _rng(cfg.seed, "lag")
    for n, p in enumerate(payments, start=1):
        order_ref = f"ord_{n:07d}"
        captured = p["captured_at"]
        lag = lag_rng.randint(1, 45)
        booked = captured + timedelta(seconds=lag)
        if booked.date() != captured.date():  # keep clean rows on the same date
            booked = captured.replace(hour=23, minute=59, second=59)
        rate = fx[(captured.date(), p["currency"])]
        fee = world.fee_for(p["amount_minor"], p["fee_tier"], p["currency"])
        ledger.append(
            {
                "ledger_id": f"led_{n:07d}",
                "order_ref": order_ref,
                "merchant_id": p["merchant_id"],
                "currency": p["currency"],
                "amount_minor": p["amount_minor"],
                "amount_base_minor": world.to_base_minor(p["amount_minor"], rate),
                "booked_at": booked,
                "_near_midnight": p["near_midnight"],
            }
        )
        processor.append(
            {
                "txn_id": f"txn_{n:07d}",
                "order_ref": order_ref,
                "merchant_id": p["merchant_id"],
                "currency": p["currency"],
                "gross_minor": p["amount_minor"],
                "fee_minor": fee,
                "net_minor": p["amount_minor"] - fee,
                "captured_at": captured,
                "payout_id": "",
                "_fee_tier": p["fee_tier"],
            }
        )

    key = Key()
    h = cfg.hardness
    inj = _rng(cfg.seed, "inject_txn")
    next_ledger = len(ledger) + 1
    drop_ledger: set[str] = set()
    drop_proc: set[str] = set()
    extra_ledger: list[dict] = []

    for led, txn in zip(ledger, processor, strict=True):
        options: list[tuple[str, float]] = [
            ("duplicate_ledger", r.duplicate_ledger),
            ("missing_in_ledger", r.missing_in_ledger),
            ("missing_in_processor", r.missing_in_processor),
            ("amount_mismatch", r.amount_mismatch),
            ("fee_variance", r.fee_variance),
            ("ref_noise", r.ref_noise),
        ]
        if led["currency"] != "USD":
            options.append(("fx_rounding", r.fx_rounding))
        if led["_near_midnight"]:
            options.append(("cutoff_timing", r.cutoff_timing))
        cls = _pick(inj, options)
        classes = [cls] if cls else []
        if cls in COMPOUNDABLE and h.compound_rate and inj.random() < h.compound_rate:
            others = [
                c
                for c in COMPOUND_ORDER
                if c != cls
                and not (c == "fx_rounding" and led["currency"] == "USD")
                and not (c == "cutoff_timing" and not led["_near_midnight"])
            ]
            classes.append(inj.choice(others))
        classes.sort(key=lambda c: COMPOUND_ORDER.index(c) if c in COMPOUND_ORDER else -1)

        pair = [("ledger", led["ledger_id"]), ("processor", txn["txn_id"])]
        linked = True
        for cls in classes:
            if cls == "duplicate_ledger":
                dup = dict(led)
                dup["ledger_id"] = f"led_{next_ledger:07d}"
                next_ledger += 1
                dup["booked_at"] = led["booked_at"] + timedelta(seconds=inj.randint(1, 5))
                extra_ledger.append(dup)
                key.defect(
                    cls,
                    [("ledger", led["ledger_id"]), ("ledger", dup["ledger_id"])],
                    order_ref=led["order_ref"],
                )
            elif cls == "missing_in_ledger":
                drop_ledger.add(led["ledger_id"])
                linked = False
                key.defect(cls, [("processor", txn["txn_id"])])
            elif cls == "missing_in_processor":
                drop_proc.add(txn["txn_id"])
                linked = False
                key.defect(cls, [("ledger", led["ledger_id"])])
            elif cls == "amount_mismatch":
                amount = led["amount_minor"]
                delta = inj.choice([-1, 1]) * max(1, amount * inj.randint(1, 10) // 100)
                led["amount_minor"] = amount + delta
                rate = fx[(txn["captured_at"].date(), led["currency"])]
                led["amount_base_minor"] = world.to_base_minor(led["amount_minor"], rate)
                key.defect(cls, pair, delta_minor=delta)
            elif cls == "fee_variance":
                expected = txn["fee_minor"]
                actual = expected + max(5, expected * inj.randint(20, 150) // 100)
                txn["fee_minor"] = actual
                txn["net_minor"] = txn["gross_minor"] - actual
                key.defect(
                    cls,
                    [("processor", txn["txn_id"])],
                    expected_fee_minor=expected,
                    actual_fee_minor=actual,
                )
            elif cls == "fx_rounding":
                delta = inj.choice([-2, -1, 1, 2])
                led["amount_base_minor"] += delta
                key.defect(cls, pair, delta_base_minor=delta)
            elif cls == "cutoff_timing":
                next_day = datetime.combine(
                    led["booked_at"].date() + timedelta(days=1), datetime.min.time()
                )
                led["booked_at"] = next_day + timedelta(seconds=inj.randint(1, 40))
                key.defect(cls, pair)
            elif cls == "ref_noise":
                original = led["order_ref"]
                if h.typo_share and inj.random() < h.typo_share:
                    led["order_ref"], mode = _typo_ref(inj, original)
                else:
                    led["order_ref"], mode = _mangle_ref(inj, original)
                key.defect(cls, pair, mode=mode, original=original)
        if linked:
            key.link("ledger_txn", led["ledger_id"], txn["txn_id"])

    ledger = [e for e in ledger if e["ledger_id"] not in drop_ledger] + extra_ledger
    ledger.sort(key=lambda e: (e["booked_at"], e["ledger_id"]))
    processor = [t for t in processor if t["txn_id"] not in drop_proc]

    # ---- payouts: one per merchant, currency and payout date -----------------------------
    groups: dict[tuple[date, str, str], list[dict]] = defaultdict(list)
    for t in processor:
        groups[
            (t["captured_at"].date() + timedelta(days=1), t["merchant_id"], t["currency"])
        ].append(t)
    payouts: list[dict] = []
    bank: list[dict] = []
    for n, gkey in enumerate(sorted(groups), start=1):
        payout_date, merchant_id, currency = gkey
        po_id = f"po_{n:06d}"
        txns = groups[gkey]
        for t in txns:
            t["payout_id"] = po_id
        total = sum(t["net_minor"] for t in txns)
        payouts.append(
            {
                "payout_id": po_id,
                "merchant_id": merchant_id,
                "currency": currency,
                "payout_date": payout_date,
                "txn_count": len(txns),
                "net_minor_total": total,
            }
        )

    # ---- bank: one line per payout, then payout-level defects ---------------------------
    pinj = _rng(cfg.seed, "inject_payout")
    n_bank = 0

    def new_line(ref: str, ccy: str, amount: int, value: date, desc: str) -> dict:
        nonlocal n_bank
        n_bank += 1
        return {
            "bank_line_id": f"bk_{n_bank:06d}",
            "reference": ref,
            "currency": ccy,
            "amount_minor": amount,
            "value_date": value,
            "description": desc,
        }

    for po in payouts:
        value = po["payout_date"] + timedelta(days=1)
        cls = _pick(pinj, [
            ("payout_late", r.payout_late),
            ("payout_missing", r.payout_missing),
            ("payout_short", r.payout_short),
            ("payout_split", r.payout_split),
        ])  # fmt: skip
        total = po["net_minor_total"]
        desc = f"PSP PAYOUT {po['payout_id']}"
        pid = po["payout_id"]
        if cls == "payout_missing":
            key.defect(cls, [("processor_payout", pid)])
            continue
        if cls == "payout_split" and total < 200:
            cls = None
        if cls == "payout_split":
            first = max(1, total * pinj.randint(30, 70) // 100)
            a = new_line(pid, po["currency"], first, value, desc)
            b = new_line(
                pid, po["currency"], total - first, value + timedelta(days=pinj.randint(0, 1)), desc
            )
            bank += [a, b]
            key.link("payout_bank", pid, a["bank_line_id"])
            key.link("payout_bank", pid, b["bank_line_id"])
            key.defect(
                cls,
                [
                    ("processor_payout", pid),
                    ("bank", a["bank_line_id"]),
                    ("bank", b["bank_line_id"]),
                ],
            )
            continue
        if cls == "payout_late":
            value += timedelta(days=pinj.randint(1, 3))
        amount = total
        delta = 0
        if cls == "payout_short":
            delta = max(1, total * pinj.randint(1, 20) // 100)
            amount = total - delta
        line = new_line(pid, po["currency"], amount, value, desc)
        bank.append(line)
        key.link("payout_bank", pid, line["bank_line_id"])
        if (
            cls in (None, "payout_late", "payout_short")
            and cfg.hardness.bank_ref_missing
            and pinj.random() < cfg.hardness.bank_ref_missing
        ):
            line["reference"] = ""
            key.defect(
                "bank_ref_missing", [("processor_payout", pid), ("bank", line["bank_line_id"])]
            )
        if cls == "payout_late":
            key.defect(cls, [("processor_payout", pid), ("bank", line["bank_line_id"])],
                       days_late=(value - po["payout_date"]).days - 1)  # fmt: skip
        elif cls == "payout_short":
            key.defect(
                cls,
                [("processor_payout", pid), ("bank", line["bank_line_id"])],
                short_by_minor=delta,
            )

    first_day = min(po["payout_date"] for po in payouts) if payouts else cfg.start
    last_day = max(po["payout_date"] for po in payouts) if payouts else cfg.start
    span = max(1, (last_day - first_day).days)
    for _ in range(int(round(len(payouts) * r.bank_orphan))):
        ccy = pinj.choice(world.CURRENCIES)
        line = new_line("", ccy, pinj.randint(5_000, 400_000),
                        first_day + timedelta(days=pinj.randint(0, span)),
                        f"INCOMING TRANSFER {pinj.randint(100000, 999999)}")  # fmt: skip
        bank.append(line)
        key.defect("bank_orphan", [("bank", line["bank_line_id"])])
    bank.sort(key=lambda b: (b["value_date"], b["bank_line_id"]))

    fx_rows = [
        {"rate_date": d.isoformat(), "currency": c, "usd_micro_per_unit": v}
        for (d, c), v in sorted(fx.items())
    ]
    fee_rows = [
        {
            "fee_tier": t,
            "currency": c,
            "bps": bps,
            "fixed_minor": fixed,
            "effective_from": cfg.start.isoformat(),
        }
        for (t, c), (bps, fixed) in sorted(world.FEE_TABLE.items())
    ]
    return {
        "merchants": merchants,
        "ledger_entries": ledger,
        "processor_txns": processor,
        "processor_payouts": payouts,
        "bank_lines": bank,
        "fx_rates": fx_rows,
        "fee_schedule": fee_rows,
        "answer_key": _number_defects(key.defects),
        "expected_links": key.links,
    }


def _number_defects(defects: list[dict]) -> list[dict]:
    return [{"defect_id": f"d_{i:05d}", **d} for i, d in enumerate(defects, start=1)]


# ---- writing ------------------------------------------------------------------------------
def _cell(v):
    if isinstance(v, datetime):
        return world.iso(v)
    if isinstance(v, date):
        return v.isoformat()
    return v


def _write_csv(path: Path, rows: list[dict]) -> None:
    fields = [k for k in rows[0] if not k.startswith("_")] if rows else []
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
        w.writeheader()
        for row in rows:
            w.writerow({k: _cell(row[k]) for k in fields})


def generate(cfg: Config, out: Path) -> dict:
    tables = build(cfg)
    out.mkdir(parents=True, exist_ok=True)
    hashes: dict[str, str] = {}
    for name, rows in tables.items():
        path = out / f"{name}.csv"
        _write_csv(path, rows)
        hashes[f"{name}.csv"] = hashlib.sha256(path.read_bytes()).hexdigest()
    counts: dict[str, int] = defaultdict(int)
    for d in tables["answer_key"]:
        counts[d["class"]] += 1
    manifest = {
        "trueup_version": "0.1.0",
        "seed": cfg.seed,
        "start": cfg.start.isoformat(),
        "days": cfg.days,
        "merchants": cfg.merchants,
        "txns_per_day": cfg.txns_per_day,
        "hardness": asdict(cfg.hardness),
        "row_counts": {k: len(v) for k, v in tables.items()},
        "defect_counts": dict(sorted(counts.items())),
        "sha256": dict(sorted(hashes.items())),
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest
