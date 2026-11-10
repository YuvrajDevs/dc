"""The card-network world and the analytics built on it.

The generator plants four incidents and records them in the manifest. These tests check the
marts find each one, in the right place, and raise nothing where nothing was planted: the
analytics equivalent of grading reconciliation against its answer key.
"""

from __future__ import annotations

import csv
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

import duckdb
import pytest

from trueup.synth import network
from trueup.synth.config import Config
from trueup.synth.generate import build, generate

RECON_TABLES = ["ledger_entries", "processor_txns", "processor_payouts", "bank_lines"]


@pytest.fixture(scope="module")
def built(tmp_path_factory) -> tuple[Path, dict]:
    """A 120-day world (long enough for steady-state dispute ratios), loaded and modelled.

    The warehouse is built in a subprocess so this process can open it read-only afterwards.
    """
    root = tmp_path_factory.mktemp("network")
    manifest = generate(Config(days=120), root / "world")
    code = (
        "from pathlib import Path; from trueup.pipeline import load_world; "
        f"load_world(Path({str(root / 'world')!r}), Path({str(root / 'w.duckdb')!r}))"
    )
    subprocess.run([sys.executable, "-c", code], check=True, capture_output=True)
    return root, manifest


def _q(root: Path, sql: str) -> list[tuple]:
    with duckdb.connect(str(root / "w.duckdb"), read_only=True) as con:
        return con.execute(sql).fetchall()


def _incident(manifest: dict, kind: str) -> dict:
    return next(i for i in manifest["network"]["incidents"] if i["kind"] == kind)


# ---- the generator ----------------------------------------------------------------------
def test_every_captured_payment_has_one_approved_authorization():
    t = build(Config(seed=3, days=10, merchants=6, txns_per_day=120))
    approved = Counter(a["order_ref"] for a in t["authorizations"] if a["approved"] == "true")
    refs = {f"ord_{n:07d}" for n in range(1, len(t["clearing_records"]) + 1)}
    assert {r for r in approved if r} == refs
    assert all(approved[r] == 1 for r in refs)


def test_reconciliation_tables_do_not_depend_on_the_network_streams():
    """The network draws from its own random streams: changing its config leaves the
    reconciliation world byte-identical (so the frozen benchmark floors still hold)."""
    cfg = Config(seed=5, days=8, merchants=6, txns_per_day=100)
    a = build(cfg)
    default = network.NetworkConfig
    try:
        network.NetworkConfig = lambda: default(cards=500, refund_rate=0.2)  # type: ignore[misc]
        b = build(cfg)
    finally:
        network.NetworkConfig = default
    for name in RECON_TABLES:
        assert a[name] == b[name], name
    assert a["refunds"] != b["refunds"]


def test_small_worlds_keep_incidents_inside_the_window():
    cfg = Config(seed=1, days=6, merchants=4, txns_per_day=60)
    t = build(cfg)
    merchants = {m["merchant_id"] for m in t["merchants"]}
    for inc in t["_network"]["incidents"]:
        if "merchant_id" in inc:
            assert inc["merchant_id"] in merchants
        if "date" in inc:
            assert inc["date"] < (cfg.start.replace(day=cfg.start.day + cfg.days)).isoformat()


def test_network_files_are_deterministic(tmp_path):
    cfg = Config(seed=9, days=6, merchants=6, txns_per_day=80)
    m1 = generate(cfg, tmp_path / "a")
    m2 = generate(cfg, tmp_path / "b")
    for name in ("authorizations.csv", "clearing_records.csv", "disputes.csv", "refunds.csv"):
        assert m1["sha256"][name] == m2["sha256"][name]


# ---- the quality gate ---------------------------------------------------------------------
def test_network_files_load_cleanly(built):
    root, _ = built
    assert _q(root, "select count(*) from quarantine.rejected_rows") == [(0,)]
    assert _q(root, "select count(*) > 0 from raw.authorizations") == [(True,)]


def test_an_inconsistent_authorization_is_quarantined(tmp_path):
    from trueup.warehouse import Warehouse

    generate(Config(seed=2, days=4, merchants=4, txns_per_day=200), tmp_path / "w")
    path = tmp_path / "w" / "authorizations.csv"
    rows = list(csv.DictReader(path.open()))
    victim = next(r for r in rows if r["approved"] == "true")
    victim["response_code"] = "05"  # declined code, but flagged approved
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    with Warehouse(tmp_path / "db.duckdb") as wh:
        result = wh.load_batch(tmp_path / "w")
        reasons = wh.con.execute(
            "select reason from quarantine.rejected_rows where source = 'authorizations'"
        ).fetchall()
    assert result.status == "loaded_with_quarantine"
    assert any("response code 00" in r[0] for r in reasons)


# ---- the analytics find what was planted, and only that ---------------------------------------
def test_issuer_outage_is_found_on_the_right_day(built):
    root, manifest = built
    inc = _incident(manifest, "issuer_outage")
    flagged = _q(
        root,
        "select issuer_id, requested_date::varchar from marts.mart_issuer_health "
        "where outage_suspected",
    )
    assert flagged == [(inc["issuer_id"], inc["date"])]


def test_card_testing_is_flagged_only_at_the_attacked_merchant(built):
    root, manifest = built
    inc = _incident(manifest, "card_testing")
    flagged = _q(
        root, "select merchant_id, hour::date::varchar from marts.mart_auth_anomalies where flagged"
    )
    assert flagged == [(inc["merchant_id"], inc["date"])]


def test_interchange_leakage_is_only_at_the_downgraded_merchant(built):
    root, manifest = built
    inc = _incident(manifest, "interchange_downgrade")
    leaking = _q(
        root,
        "select merchant_id from marts.mart_fee_economics group by 1 "
        "having sum(interchange_leakage_minor) > 0",
    )
    assert leaking == [(inc["merchant_id"],)]


def test_high_risk_merchant_breaches_the_dispute_threshold_in_steady_state(built):
    root, manifest = built
    inc = _incident(manifest, "excessive_disputes")
    rows = _q(
        root,
        f"select month, programme_status from marts.mart_dispute_monitoring "
        f"where merchant_id = '{inc['merchant_id']}' order by month",
    )
    steady = rows[1:]  # the first month starts cold: disputes arrive weeks after sales
    assert steady and all(status == "excessive" for _, status in steady)


def test_everyday_merchants_never_breach(built):
    root, _ = built
    rows = _q(
        root,
        "select distinct m.programme_status from marts.mart_dispute_monitoring m "
        "join staging.stg_merchant_profiles p using (merchant_id) where p.mcc_group = 'everyday'",
    )
    assert rows == [("ok",)]


def test_approval_rate_is_realistic_and_cross_border_cnp_is_worst(built):
    root, _ = built
    overall = _q(root, "select sum(approvals) * 1.0 / sum(attempts) from marts.mart_auth_daily")[0][
        0
    ]
    assert 0.80 < overall < 0.95
    by_segment = dict(
        (f"{ch}-{xb}", rate)
        for ch, xb, rate in _q(
            root,
            "select channel, cross_border, sum(approvals) * 1.0 / sum(attempts) "
            "from marts.mart_auth_daily group by 1, 2",
        )
    )
    assert min(by_segment, key=by_segment.get) == "cnp-True"


def test_manifest_records_the_incidents_but_they_never_reach_the_warehouse(built):
    root, manifest = built
    assert {i["kind"] for i in manifest["network"]["incidents"]} == {
        "issuer_outage",
        "card_testing",
        "interchange_downgrade",
        "excessive_disputes",
    }
    tables = _q(
        root, "select table_name from information_schema.tables where table_name ilike '%incident%'"
    )
    assert tables == []
    assert "incidents.csv" not in json.dumps(manifest["sha256"])
