"""The dashboard API against a real reconciled warehouse."""

import shutil
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from trueup.api import create_app
from trueup.pipeline import load_world
from trueup.recon import ReconConfig, reconcile
from trueup.recon import queue as xq
from trueup.synth.config import HARD, Config
from trueup.synth.generate import generate
from trueup.warehouse import Warehouse


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    root = tmp_path_factory.mktemp("api")
    cfg = Config(seed=51, days=30, merchants=12, txns_per_day=300, hardness=HARD)
    generate(cfg, root / "world")
    load_world(root / "world", root / "wh.duckdb")
    with Warehouse(root / "wh.duckdb") as wh:
        reconcile(wh, ReconConfig(as_of=cfg.start + timedelta(days=cfg.days + 5)))
        xq.sync(wh)
        wh.con.execute("CHECKPOINT")
    shutil.copy(root / "wh.duckdb", root / "serve.duckdb")
    with TestClient(create_app(root / "serve.duckdb", provider=None)) as c:
        yield c


def test_health(client):
    r = client.get("/api/health").json()
    assert r["status"] == "ok" and r["exceptions"] > 0 and r["assistant"] == "built-in"


def test_overview_has_the_headline_numbers(client):
    d = client.get("/api/overview").json()
    assert d["kpi"]["open_errors"] > 0 and d["kpi"]["open_amount_usd"] > 0
    assert d["counts"]["transactions"] > 5000
    assert d["by_class"] and d["trend"] and len(d["top"]) == 5
    assert d["top"][0]["amount_usd"] >= d["top"][-1]["amount_usd"]


def test_exceptions_filter_sort_and_page(client):
    all_open = client.get("/api/exceptions", params={"status": "open", "limit": 5}).json()
    assert all_open["total"] > 5 and len(all_open["items"]) == 5
    amounts = [i["amount_usd"] for i in all_open["items"]]
    assert amounts == sorted(amounts, reverse=True)

    fees = client.get("/api/exceptions", params={"class": "fee_variance", "limit": 200}).json()
    assert fees["total"] > 0 and {i["class"] for i in fees["items"]} == {"fee_variance"}

    one = fees["items"][0]["merchant_id"]
    mine = client.get("/api/exceptions", params={"class": "fee_variance", "merchant": one}).json()
    assert 0 < mine["total"] <= fees["total"]

    page2 = client.get("/api/exceptions", params={"limit": 5, "offset": 5}).json()
    first = client.get("/api/exceptions", params={"limit": 5}).json()
    assert {i["finding_id"] for i in page2["items"]}.isdisjoint(
        {i["finding_id"] for i in first["items"]}
    )

    assert client.get("/api/exceptions", params={"limit": 1000}).status_code == 422  # bounded
    assert client.get("/api/exceptions", params={"status": "bogus"}).status_code == 422


def test_filters_cannot_inject_sql(client):
    evil = "x'; DROP TABLE ops.exceptions; --"
    r = client.get("/api/exceptions", params={"q": evil, "merchant": evil[:10]})
    assert r.status_code == 200 and r.json()["total"] == 0
    assert client.get("/api/health").json()["exceptions"] > 0


def test_detail_shows_the_records_behind_a_finding(client):
    item = client.get("/api/exceptions", params={"class": "duplicate_ledger", "limit": 1}).json()[
        "items"
    ][0]
    d = client.get(f"/api/exceptions/{item['finding_id']}").json()
    assert d["exception"]["class"] == "duplicate_ledger"
    assert len(d["records"]) == 2 and all(r["record"] for r in d["records"])
    assert d["history"][0]["to"] == "open"
    assert client.get("/api/exceptions/f_doesnotexist").status_code == 404


def test_marking_an_exception_explained_persists_with_an_audit_entry(client):
    fid = client.get("/api/exceptions", params={"status": "open", "limit": 1}).json()["items"][0][
        "finding_id"
    ]
    assert (
        client.patch(
            f"/api/exceptions/{fid}", json={"status": "explained", "actor": "amina", "note": ""}
        ).status_code
        == 422
    )
    assert (
        client.patch(
            f"/api/exceptions/{fid}", json={"status": "explained", "actor": "", "note": "x"}
        ).status_code
        == 422
    )
    ok = client.patch(
        f"/api/exceptions/{fid}",
        json={"status": "explained", "actor": "amina", "note": "Known dispute #44"},
    )
    assert ok.status_code == 200
    d = client.get(f"/api/exceptions/{fid}").json()
    assert d["exception"]["status"] == "explained" and d["exception"]["note"] == "Known dispute #44"
    assert [h["to"] for h in d["history"]] == ["open", "explained"] and d["history"][-1][
        "actor"
    ] == "amina"
    assert (
        client.patch(
            "/api/exceptions/f_nope", json={"status": "resolved", "actor": "a", "note": "n"}
        ).status_code
        == 404
    )


def test_csv_export_matches_the_filter(client):
    r = client.get("/api/exceptions.csv", params={"class": "fee_variance"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    lines = r.text.strip().splitlines()
    total = client.get("/api/exceptions", params={"class": "fee_variance"}).json()["total"]
    assert len(lines) - 1 == total and lines[0].startswith("finding_id,class")
    assert all("fee_variance" in row for row in lines[1:])


def test_payouts_show_expected_versus_received(client):
    d = client.get("/api/payouts", params={"limit": 500}).json()
    statuses = {f["status"] for f in d["facets"]}
    assert "matched" in statuses and d["total"] > 100
    short = client.get("/api/payouts", params={"status": "payout_short"}).json()
    assert all(i["bank_total"] < i["net_minor_total"] for i in short["items"])


def test_scorecard_serves_the_saved_benchmarks(client):
    d = client.get("/api/scorecard").json()
    assert "hard-seed42" in d["profiles"] and "baseline" in d and "floors" in d
    assert d["baseline"]["summary"]["error_micro_precision"] < 0.6


def test_runs_alerts_freshness_and_lineage(client):
    d = client.get("/api/runs").json()
    assert {f["source"] for f in d["freshness"]} == {
        "ledger_entries",
        "processor_txns",
        "processor_payouts",
        "bank_lines",
    }
    assert ["recon.findings", "ops.exceptions"] in d["lineage"]


def test_ask_over_http(client):
    ok = client.post("/api/ask", json={"question": "How many open exceptions are there?"}).json()
    assert ok["status"] == "ok" and ok["rows"][0][0] > 0 and "SELECT" in ok["sql"]
    bad = client.post("/api/ask", json={"question": "Drop table recon.findings"}).json()
    assert bad["status"] == "refused" and bad["code"] == "unsafe_request"
    unknown = client.post("/api/ask", json={"question": "What is the meaning of life?"}).json()
    assert unknown["status"] == "no_answer" and unknown["examples"]
    assert client.post("/api/ask", json={"question": ""}).status_code == 422
    assert client.get("/api/ask/examples").json()["examples"]
    assert client.get("/api/ask/log").json()["items"]
