"""The lab: plant incidents with your own settings, generate a fresh card-network world, and
see whether the detectors find them.

Each run is a pure function of the settings (same settings, same world). The detectors are
the same rules the dbt marts use (issuer health, hourly anomaly scoring, rate-card rebuild,
dispute monitoring), run here in DuckDB on the freshly generated rows. Every detection is
then graded against what was planted: found, missed, or a false alarm.
"""

from __future__ import annotations

import csv
import tempfile
import time
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path

import duckdb

from trueup.synth import network
from trueup.synth.config import Config
from trueup.synth.generate import build


@dataclass(frozen=True)
class LabSettings:
    seed: int = 7
    days: int = 60
    txns_per_day: int = 300
    outage_hours: int = 6  # 0 = no outage
    card_testing_attempts: int = 420  # 0 = no attack
    downgrade_share: float = 0.35  # 0 = no downgrades
    dispute_multiplier: float = 1.0  # dispute risk at the high-risk merchant; 0 = off

    LIMITS = {
        "seed": (1, 99999),
        "days": (35, 120),
        "txns_per_day": (100, 400),
        "outage_hours": (0, 12),
        "card_testing_attempts": (0, 800),
        "downgrade_share": (0.0, 0.8),
        "dispute_multiplier": (0.0, 4.0),
    }

    def clamped(self) -> LabSettings:
        vals = {}
        for k, (lo, hi) in self.LIMITS.items():
            v = getattr(self, k)
            vals[k] = type(lo)(min(max(v, lo), hi))
        return replace(self, **vals)


def _write(rows: list[dict], path: Path) -> None:
    cols = [k for k in rows[0] if not k.startswith("_")]
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


DETECT = {
    # Issuer health: "issuer unavailable" (91) answers normally never happen.
    "issuer_outage": """
        SELECT b.issuer_id AS entity, a.requested_at::date AS day,
               count(*) FILTER (WHERE response_code = '91') AS unavailable, count(*) AS attempts,
               min(requested_at) FILTER (WHERE response_code = '91') AS first_at,
               max(requested_at) FILTER (WHERE response_code = '91') AS last_at
        FROM auth a JOIN bins b USING (bin)
        GROUP BY ALL
        HAVING count(*) FILTER (WHERE response_code = '91') >= 3
           AND 10 * count(*) FILTER (WHERE response_code = '91') >= count(*)
        ORDER BY unavailable DESC""",
    # Card testing: an hour far above the merchant's own baseline with collapsing approvals.
    "card_testing": """
        WITH h AS (
          SELECT merchant_id, date_trunc('hour', requested_at) AS hour, count(*) AS attempts,
                 count(*) FILTER (WHERE approved) AS approvals,
                 count(DISTINCT card_token) AS cards, median(amount_minor) AS median_amount
          FROM auth GROUP BY ALL),
        b AS (SELECT merchant_id, avg(attempts) m, stddev_pop(attempts) sd FROM h GROUP BY 1)
        SELECT h.merchant_id AS entity, h.hour::date AS day, h.hour, attempts, approvals, cards,
               median_amount, round((attempts - m) / nullif(sd, 0), 1) AS zscore
        FROM h JOIN b USING (merchant_id)
        WHERE (attempts - m) / nullif(sd, 0) >= 4 AND approvals * 2 < attempts
        ORDER BY zscore DESC""",
    # Interchange: the charged rate against the rate card rebuilt for each transaction.
    "interchange_downgrade": """
        SELECT merchant_id AS entity, count(*) AS transactions,
               count(*) FILTER (WHERE interchange_bps > expected_bps) AS over_rate_card,
               sum(greatest(interchange_minor - expected_minor, 0)) AS overpaid_minor,
               any_value(currency) AS currency
        FROM clearing GROUP BY 1
        HAVING 20 * count(*) FILTER (WHERE interchange_bps > expected_bps) >= count(*)
        ORDER BY over_rate_card DESC""",
    # Dispute monitoring: complete months only, programme thresholds.
    "excessive_disputes": """
        WITH s AS (
          SELECT merchant_id, date_trunc('month', cleared_at)::date AS month, count(*) AS sales,
                 count(DISTINCT cleared_at::date) AS days FROM clearing GROUP BY ALL),
        full_months AS (SELECT month FROM s GROUP BY month
                        HAVING max(days) >= date_part('day', last_day(month)) - 1),
        d AS (SELECT merchant_id, date_trunc('month', opened_at)::date AS month,
                     count(*) AS disputes
              FROM disputes GROUP BY ALL)
        SELECT s.merchant_id AS entity, s.month, s.sales, coalesce(d.disputes, 0) AS disputes,
               round(10000.0 * coalesce(d.disputes, 0) / s.sales)::int AS ratio_bps
        FROM s JOIN full_months USING (month) LEFT JOIN d USING (merchant_id, month)
        WHERE coalesce(d.disputes, 0) >= 10 AND 10000.0 * coalesce(d.disputes, 0) / s.sales >= 90
        ORDER BY ratio_bps DESC""",
}


def run(settings: LabSettings) -> dict:
    s = settings.clamped()
    t0 = time.perf_counter()
    cfg = Config(seed=s.seed, start=date(2026, 1, 1), days=s.days, txns_per_day=s.txns_per_day)
    ncfg = network.NetworkConfig(
        outage_hours=(9, 9 + s.outage_hours),
        card_testing_attempts=s.card_testing_attempts,
        downgrade_share=s.downgrade_share,
        excessive_dispute_multiplier=s.dispute_multiplier,
    )
    world = build(cfg, ncfg)
    gen_s = time.perf_counter() - t0

    planted_all = world["_network"]["incidents"]
    active = {
        "issuer_outage": s.outage_hours > 0,
        "card_testing": s.card_testing_attempts > 0,
        "interchange_downgrade": s.downgrade_share > 0,
        "excessive_disputes": s.dispute_multiplier > 0,
    }
    planted = {i["kind"]: i for i in planted_all if active[i["kind"]]}

    # Rebuild the rate card for every cleared transaction, from the auth and BIN it came from.
    bins = {b["bin"]: b for b in world["card_bins"]}
    prof = {p["merchant_id"]: p for p in world["merchant_profiles"]}
    auth = {a["auth_id"]: a for a in world["authorizations"]}
    clearing = []
    for c in world["clearing_records"]:
        a = auth[c["auth_id"]]
        b, p = bins[a["bin"]], prof[c["merchant_id"]]
        channel = "cp" if a["card_present"] == "true" else "cnp"
        bps, fee = network.interchange_for(
            c["amount_minor"],
            b["product"],
            channel,
            p["region"],
            b["issuer_region"],
            p["mcc_group"],
        )
        clearing.append({**c, "expected_bps": bps, "expected_minor": fee})

    t1 = time.perf_counter()
    found: dict[str, list[dict]] = {}
    with tempfile.TemporaryDirectory() as d:
        tables = {
            "auth": world["authorizations"],
            "bins": world["card_bins"],
            "clearing": clearing,
            "disputes": world["disputes"],
        }
        con = duckdb.connect()
        for name, rows in tables.items():
            path = Path(d) / f"{name}.csv"
            _write(rows, path)
            con.execute(
                f"CREATE TABLE {name} AS SELECT * FROM read_csv_auto('{path}', all_varchar=false)"
            )
        for kind, sql in DETECT.items():
            cur = con.execute(sql)
            cols = [c[0] for c in cur.description]
            found[kind] = [
                {
                    k: (v.isoformat() if hasattr(v, "isoformat") else v)
                    for k, v in zip(cols, r, strict=True)
                }
                for r in cur.fetchall()
            ]
        con.close()
    detect_s = time.perf_counter() - t1

    results = []
    for kind in DETECT:
        p = planted.get(kind)
        target = (p or {}).get("issuer_id") or (p or {}).get("merchant_id")
        hits = found[kind]
        entities = sorted({h["entity"] for h in hits})
        correct = [h for h in hits if h["entity"] == target]
        if kind in ("issuer_outage", "card_testing") and p:
            correct = [h for h in correct if h["day"] == p["date"]]
        false_alarms = [h for h in hits if h not in correct]
        verdict = ("found" if correct else "missed") if p else ("false_alarm" if hits else "quiet")
        results.append(
            {
                "kind": kind,
                "planted": p,
                "verdict": verdict,
                "detected_entities": entities,
                "evidence": (correct or hits)[:3],
                "false_alarms": len(false_alarms),
            }
        )

    tp = sum(r["verdict"] == "found" for r in results)
    fn = sum(r["verdict"] == "missed" for r in results)
    fp = sum(r["false_alarms"] for r in results)
    return {
        "settings": {k: getattr(s, k) for k in LabSettings.LIMITS},
        "world": {
            "start": cfg.start.isoformat(),
            "days": s.days,
            "authorizations": len(world["authorizations"]),
            "cleared": len(clearing),
            "disputes": len(world["disputes"]),
            "issuers": len({b["issuer_id"] for b in world["card_bins"]}),
            "merchants": len(prof),
        },
        "results": results,
        "score": {"found": tp, "missed": fn, "false_alarms": fp, "planted": len(planted)},
        "seconds": {"generate": round(gen_s, 2), "detect": round(detect_s, 2)},
    }
