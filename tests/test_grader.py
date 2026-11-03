"""The grader must itself be trustworthy: it is what we measure the engine with."""

import json
from pathlib import Path

import pytest

from tally.grade import check_floors, grade, load_key, load_links
from tally.synth.config import Config
from tally.synth.generate import generate
from tally.warehouse import Warehouse

FLOORS = {
    "min_support": 10, "micro_precision_min": 0.99, "micro_recall_min": 0.99,
    "class_precision_min": 0.98, "class_recall_min": 0.98,
    "link_ledger_txn_min": 0.999, "link_payout_bank_min": 0.99, "benign_false_alarm_max": 0.005,
}  # fmt: skip


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    root = tmp_path_factory.mktemp("grader") / "world"
    generate(Config(seed=5, days=30, merchants=10, txns_per_day=300), root)
    return root


def make_db(path: Path, findings: list[dict], links: list[tuple]) -> Warehouse:
    wh = Warehouse(path)
    wh.con.execute("CREATE SCHEMA IF NOT EXISTS recon")
    wh.con.execute(
        "CREATE OR REPLACE TABLE recon.findings (class VARCHAR, category VARCHAR, entities VARCHAR)"
    )
    wh.con.execute(
        "CREATE OR REPLACE TABLE recon.links (link_type VARCHAR, left_id VARCHAR, right_id VARCHAR)"
    )
    for f in findings:
        wh.con.execute(
            "INSERT INTO recon.findings VALUES (?, ?, ?)",
            [f["class"], f["category"], f["entities"]],
        )
    for link in links:
        wh.con.execute("INSERT INTO recon.links VALUES (?, ?, ?)", list(link))
    return wh


def perfect(world):
    findings = [
        {"class": d["class"], "category": d["category"], "entities": d["entities"]}
        for d in load_key(world)
    ]
    return findings, sorted(load_links(world))


def test_a_perfect_engine_scores_one_everywhere(tmp_path, world):
    findings, links = perfect(world)
    with make_db(tmp_path / "a.duckdb", findings, links) as wh:
        card = grade(wh, world)
    assert all(c.precision == 1.0 and c.recall == 1.0 for c in card.classes)
    assert card.links["all"]["precision"] == card.links["all"]["recall"] == 1.0
    assert card.benign_false_alarms == 0
    assert check_floors(card, FLOORS) == []


def test_missing_findings_lower_recall_and_break_the_floor(tmp_path, world):
    findings, links = perfect(world)
    dropped = [f for f in findings if f["class"] == "fee_variance"][:20]
    kept = [f for f in findings if f not in dropped]
    with make_db(tmp_path / "b.duckdb", kept, links) as wh:
        card = grade(wh, world)
    fee = next(c for c in card.classes if c.name == "fee_variance")
    assert fee.fn == 20 and fee.recall < 1.0 and fee.precision == 1.0
    assert any("fee_variance" in f for f in check_floors(card, FLOORS))


def test_invented_findings_lower_precision(tmp_path, world):
    findings, links = perfect(world)
    fake = [
        {"class": "fee_variance", "category": "error",
         "entities": json.dumps([{"source": "processor", "id": f"txn_{9000000 + i}"}])}
        for i in range(30)
    ]  # fmt: skip
    with make_db(tmp_path / "c.duckdb", findings + fake, links) as wh:
        card = grade(wh, world)
    fee = next(c for c in card.classes if c.name == "fee_variance")
    assert fee.fp == 30 and fee.precision < 1.0
    assert card.unexplained_error_findings == 30
    assert check_floors(card, FLOORS)


def test_alarming_on_a_benign_record_counts_as_a_false_alarm(tmp_path, world):
    findings, links = perfect(world)
    benign = next(d for d in load_key(world) if d["class"] == "fx_rounding")
    wrong = {"class": "amount_mismatch", "category": "error", "entities": benign["entities"]}
    with make_db(tmp_path / "d.duckdb", findings + [wrong], links) as wh:
        card = grade(wh, world)
    assert card.benign_false_alarms == 1


def test_a_correct_error_on_a_record_with_a_benign_quirk_is_not_a_false_alarm(tmp_path):
    """Compound defects: the error is real, so flagging it must not be punished."""
    from tally.synth.config import HARD

    root = tmp_path / "w"
    generate(Config(seed=3, days=30, merchants=10, txns_per_day=300, hardness=HARD), root)
    findings, links = perfect(root)
    with make_db(tmp_path / "e.duckdb", findings, links) as wh:
        card = grade(wh, root)
    assert card.benign_false_alarms == 0


def test_missing_links_lower_link_recall(tmp_path, world):
    findings, links = perfect(world)
    with make_db(tmp_path / "f.duckdb", findings, links[100:]) as wh:
        card = grade(wh, world)
    assert card.links["all"]["recall"] < 1.0 and card.links["all"]["precision"] == 1.0


def test_wrong_links_lower_link_precision(tmp_path, world):
    findings, links = perfect(world)
    wrong = [("ledger_txn", "led_9999999", "txn_9999999")] * 1 + [
        ("ledger_txn", "led_9999998", "txn_9999998")
    ]
    with make_db(tmp_path / "g.duckdb", findings, links + wrong) as wh:
        card = grade(wh, world)
    assert card.links["ledger_txn"]["precision"] < 1.0 and card.links["ledger_txn"]["recall"] == 1.0
