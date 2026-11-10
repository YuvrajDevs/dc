"""The lab: plant incidents with your own settings, generate a fresh card-network world, and
see whether the detectors find them.

Each run is a pure function of the settings (same settings, same world). The detectors are
the same rules the dbt marts use (issuer health, hourly anomaly scoring, rate-card rebuild,
dispute monitoring), run here in DuckDB on the freshly generated rows. Every detection is
then graded against what was planted: found, missed, or a false alarm.
"""

from __future__ import annotations

import csv
import math
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
    dispute_multiplier: float = 3.0  # one merchant's disputes vs its category norm; 1 = off

    LIMITS = {
        "seed": (1, 99999),
        "days": (35, 120),
        "txns_per_day": (100, 400),
        "outage_hours": (0, 12),
        "card_testing_attempts": (0, 800),
        "downgrade_share": (0.0, 0.8),
        "dispute_multiplier": (1.0, 4.0),
    }

    def clamped(self) -> LabSettings:
        vals = {}
        for k, (lo, hi) in self.LIMITS.items():
            v = getattr(self, k)
            vals[k] = type(lo)(min(max(v, lo), hi))
        return replace(self, **vals)


# Category dispute benchmarks per sale, card-present and online, by MCC.
_NC = network.NetworkConfig()
BENCHMARK = {
    (mcc, ch): (_NC.dispute_base_cnp if ch == "cnp" else _NC.dispute_base_cp) * risk
    for mcc, _d, _g, _c, risk in network.MCCS
    for ch in ("cp", "cnp")
}


def _poisson_sf(k: int, mu: float) -> float:
    """P(X >= k) for X ~ Poisson(mu)."""
    term = cdf = math.exp(-mu)
    for i in range(1, k):
        term *= mu / i
        cdf += term
    return max(0.0, 1.0 - cdf)


def _write(rows: list[dict], path: Path) -> None:
    cols = [k for k in rows[0] if not k.startswith("_")]
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


DETECT = {
    # Issuer health: "issuer unavailable" (91) answers never happen in normal traffic, so a
    # cluster of them at one issuer is the signal: two inside an hour, or three in a day.
    "issuer_outage": """
        WITH t AS (
          SELECT b.issuer_id, a.requested_at
          FROM auth a JOIN bins b USING (bin) WHERE a.response_code = '91'),
        hourly AS (
          SELECT issuer_id, requested_at::date AS day, max(n) AS peak_hour
          FROM (SELECT issuer_id, requested_at,
                       count(*) OVER (PARTITION BY issuer_id ORDER BY requested_at
                                      RANGE BETWEEN INTERVAL 1 HOUR PRECEDING AND CURRENT ROW) n
                FROM t)
          GROUP BY ALL)
        SELECT t.issuer_id AS entity, t.requested_at::date AS day, count(*) AS unavailable,
               any_value(h.peak_hour) AS peak_hour,
               min(t.requested_at) AS first_at, max(t.requested_at) AS last_at
        FROM t JOIN hourly h ON h.issuer_id = t.issuer_id AND h.day = t.requested_at::date
        GROUP BY ALL
        HAVING count(*) >= 3 OR any_value(h.peak_hour) >= 2
        ORDER BY unavailable DESC""",
    # Card testing: an hour far above the merchant's own baseline, nearly every attempt on a
    # different card, with collapsing approvals.
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
          AND attempts >= 8 AND 10 * cards >= 9 * attempts
        ORDER BY zscore DESC""",
    # Interchange: the rate card is rebuilt exactly for each transaction, so any charge above
    # it is an overcharge. Three or more at one merchant is a pattern, not a one-off.
    "interchange_downgrade": """
        SELECT merchant_id AS entity, count(*) AS transactions,
               count(*) FILTER (WHERE interchange_bps > expected_bps) AS over_rate_card,
               sum(greatest(interchange_minor - expected_minor, 0)) AS overpaid_minor,
               any_value(currency) AS currency
        FROM clearing GROUP BY 1
        HAVING count(*) FILTER (WHERE interchange_bps > expected_bps) >= 3
        ORDER BY over_rate_card DESC""",
    # Disputes, early warning: each sale carries its category's benchmark dispute rate (card-
    # present or online, by MCC, as networks publish industry benchmarks). A merchant whose
    # disputes far exceed the sum of those expectations (a z >= 3.5 shortlist, then an exact
    # Poisson tail p < 0.0002, at least 6 disputes) is flagged before it reaches the
    # monitoring programme's threshold.
    "excessive_disputes": """
        WITH s AS (SELECT merchant_id, count(*) AS sales, sum(expected_dispute) AS expected
                   FROM clearing GROUP BY 1),
        d AS (SELECT merchant_id, count(*) AS disputes FROM disputes GROUP BY 1)
        SELECT s.merchant_id AS entity, sales, coalesce(disputes, 0) AS disputes,
               round(expected, 1) AS expected,
               round(10000.0 * coalesce(disputes, 0) / sales)::int AS ratio_bps,
               round((coalesce(disputes, 0) - expected) / sqrt(expected), 1) AS zscore
        FROM s LEFT JOIN d USING (merchant_id)
        WHERE coalesce(disputes, 0) >= 6
          AND (coalesce(disputes, 0) - expected) / sqrt(expected) >= 3.5
        ORDER BY zscore DESC""",
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
        "excessive_disputes": s.dispute_multiplier > 1,
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
        benchmark = BENCHMARK[(p["mcc"], channel)]
        clearing.append(
            {**c, "expected_bps": bps, "expected_minor": fee, "expected_dispute": benchmark}
        )

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
    # Exact Poisson tail for the dispute screen: the z-score shortlist is loose on small
    # samples, so keep only merchants whose dispute count chance alone explains < 1 in 5,000.
    found["excessive_disputes"] = [
        {**h, "p_value": float(f"{_poisson_sf(h['disputes'], h['expected']):.2g}")}
        for h in found["excessive_disputes"]
        if _poisson_sf(h["disputes"], h["expected"]) < 2e-4
    ]
    detect_s = time.perf_counter() - t1

    # How much of each planted incident actually reached the data. An outage at a quiet hour
    # can produce no timeouts at all; there is nothing for any detector to see.
    issuer_of = {b["bin"]: b["issuer_id"] for b in world["card_bins"]}
    target_m = planted.get("excessive_disputes", {}).get("merchant_id")
    norm_disputes = sum(c["expected_dispute"] for c in clearing if c["merchant_id"] == target_m)
    trace = {
        "issuer_outage": sum(
            1
            for a in world["authorizations"]
            if a["response_code"] == "91"
            and issuer_of[a["bin"]] == planted.get("issuer_outage", {}).get("issuer_id")
        ),
        "card_testing": s.card_testing_attempts,
        "interchange_downgrade": sum(
            1 for c in world["clearing_records"] if c["qualification"] == "downgraded"
        ),
        # Expected signal strength: the planted excess over the merchant's category norm, in
        # standard deviations of chance variation at this volume.
        "excessive_disputes": round(
            (s.dispute_multiplier - 1) * math.sqrt(max(norm_disputes, 1e-9)), 1
        ),
    }
    faint = {
        "issuer_outage": trace["issuer_outage"] < 2,
        "card_testing": trace["card_testing"] < 8,
        "interchange_downgrade": trace["interchange_downgrade"] < 3,
        "excessive_disputes": trace["excessive_disputes"] < 5,
    }

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
        if p:
            verdict = "found" if correct else ("too_faint" if faint[kind] else "missed")
        else:
            verdict = "false_alarm" if hits else "quiet"
        results.append(
            {
                "kind": kind,
                "planted": p,
                "verdict": verdict,
                "detected_entities": entities,
                "evidence": (correct or hits)[:3],
                "false_alarms": len(false_alarms),
                "trace": trace[kind] if p else 0,
            }
        )

    tp = sum(r["verdict"] == "found" for r in results)
    fn = sum(r["verdict"] == "missed" for r in results)
    fp = sum(r["false_alarms"] for r in results)
    faint_n = sum(r["verdict"] == "too_faint" for r in results)
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
        "score": {
            "found": tp,
            "missed": fn,
            "false_alarms": fp,
            "planted": len(planted),
            "too_faint": faint_n,
        },
        "seconds": {"generate": round(gen_s, 2), "detect": round(detect_s, 2)},
    }
