"""End to end: load, build with dbt, and prove the Phase 2 exit criteria."""

import csv
import random
import shutil
from pathlib import Path

import pytest

from tally.synth.config import Config
from tally.synth.generate import generate
from tally.warehouse import Warehouse, dbt_runner
from tally.warehouse.split import split_world

CFG = Config(seed=11, days=6, merchants=8, txns_per_day=120)
NOISE = ("_batch_id", "_batch_seq", "_row_number", "_loaded_at", "_source_file")


@pytest.fixture(scope="module")
def deliveries(tmp_path_factory):
    root = tmp_path_factory.mktemp("pipe")
    generate(CFG, root / "world")
    return {
        "ordered": split_world(root / "world", root / "ordered"),
        "late": split_world(root / "world", root / "late", late_rate=0.15, seed=5),
        "root": root,
    }


def load(db: Path, batches) -> None:
    with Warehouse(db) as wh:
        for b in batches:
            assert wh.load_batch(b).ok


def marts(db: Path):
    with Warehouse(db) as wh:
        return wh.fingerprints(("marts",))


def test_loading_everything_twice_changes_nothing(tmp_path, deliveries):
    db = tmp_path / "w.duckdb"
    load(db, deliveries["ordered"])
    assert dbt_runner.build(db).success
    with Warehouse(db) as wh:
        before = wh.fingerprints()

    with Warehouse(db) as wh:  # deliver every batch a second time
        results = [wh.load_batch(b) for b in deliveries["ordered"]]
        assert {r.status for r in results} == {"skipped_duplicate"}
    assert dbt_runner.build(db).success
    with Warehouse(db) as wh:
        assert wh.fingerprints() == before


def test_redelivered_rows_in_a_new_batch_do_not_change_the_marts(tmp_path, deliveries):
    db = tmp_path / "w.duckdb"
    load(db, deliveries["ordered"])
    assert dbt_runner.build(db).success
    expected = marts(db)

    # the same rows again, but a different file (reversed), so it counts as a new batch
    src = deliveries["ordered"][3]
    dup = tmp_path / "redelivery"
    shutil.copytree(src, dup)
    for f in dup.glob("*.csv"):
        lines = f.read_text().splitlines()
        f.write_text("\n".join([lines[0], *reversed(lines[1:])]) + "\n")
    with Warehouse(db) as wh:
        res = wh.load_batch(dup)
        assert res.status == "loaded"
        raw_rows = wh.con.execute("SELECT count(*) FROM raw.ledger_entries").fetchone()[0]
    assert dbt_runner.build(db).success
    assert marts(db) == expected
    with Warehouse(db) as wh:
        # raw keeps the audit trail of everything received
        assert wh.con.execute("SELECT count(*) FROM raw.ledger_entries").fetchone()[0] == raw_rows


def test_late_and_shuffled_deliveries_give_the_same_marts(tmp_path, deliveries):
    one_shot = tmp_path / "a.duckdb"
    load(one_shot, deliveries["ordered"])
    assert dbt_runner.build(one_shot).success

    shuffled = list(deliveries["late"])
    random.Random(3).shuffle(shuffled)
    other = tmp_path / "b.duckdb"
    load(other, shuffled)
    assert dbt_runner.build(other).success

    assert marts(other) == marts(one_shot)


def test_a_later_delivery_corrects_an_earlier_one(tmp_path, deliveries):
    db = tmp_path / "w.duckdb"
    load(db, deliveries["ordered"])
    with Warehouse(db) as wh:
        ledger_id, old = wh.con.execute(
            "SELECT ledger_id, amount_minor FROM raw.ledger_entries ORDER BY ledger_id LIMIT 1"
        ).fetchone()
    fix = tmp_path / "fix"
    fix.mkdir()
    src = next(b for b in deliveries["ordered"] if (b / "ledger_entries.csv").exists())
    with (src / "ledger_entries.csv").open(newline="") as f:
        rows = [r for r in csv.DictReader(f) if r["ledger_id"] == ledger_id]
    assert rows, "the chosen row must come from the first ledger delivery"
    rows[0]["amount_minor"] = str(int(old) + 100)
    with (fix / "ledger_entries.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    load(db, [fix])
    assert dbt_runner.build(db).success
    with Warehouse(db) as wh:
        assert (
            wh.con.execute(
                "SELECT amount_minor FROM staging.stg_ledger_entries WHERE ledger_id = ?",
                [ledger_id],
            ).fetchone()[0]
            == int(old) + 100
        )
        # the original is still in raw
        assert (
            wh.con.execute(
                "SELECT count(*) FROM raw.ledger_entries WHERE ledger_id = ?", [ledger_id]
            ).fetchone()[0]
            == 2
        )


def test_corrupted_batch_is_blocked_and_the_marts_stay_untouched(tmp_path, deliveries):
    db = tmp_path / "w.duckdb"
    good = deliveries["ordered"][:-1]
    load(db, good)
    assert dbt_runner.build(db).success
    before = marts(db)

    bad = tmp_path / "bad"
    shutil.copytree(deliveries["ordered"][-1], bad)
    path = bad / "bank_lines.csv"
    if not path.exists():
        path = next(bad.glob("ledger_entries.csv"))
    rows = list(csv.DictReader(path.open()))
    fields = list(rows[0])
    for r in rows:
        r["currency"] = "ZZZ"
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    with Warehouse(db) as wh:
        res = wh.load_batch(bad)
        assert res.status == "rejected"
        assert any("ZZZ" not in r and "failed the contract" in r for r in res.reasons)
    assert dbt_runner.build(db).success
    assert marts(db) == before


def test_dropping_a_transaction_is_caught_by_the_payout_total_check(tmp_path, deliveries):
    """Quarantining a transaction leaves its payout total too high; the build must fail loudly."""
    db = tmp_path / "w.duckdb"
    src = next(
        b for b in deliveries["ordered"] if (b / "processor_txns.csv").exists() and b.name[0] == "2"
    )
    bad = tmp_path / "bad"
    shutil.copytree(src, bad)
    rows = list(csv.DictReader((bad / "processor_txns.csv").open()))
    fields = list(rows[0])
    rows[0]["gross_minor"] = "oops"
    with (bad / "processor_txns.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    load(db, [d for d in deliveries["ordered"] if d != src and d.name[0] == "0"])  # reference data
    with Warehouse(db) as wh:
        res = wh.load_batch(bad)
        assert res.status == "loaded_with_quarantine"
        assert res.rows_quarantined["processor_txns"] == 1
    summary = dbt_runner.build(db)
    # either the payout files are absent (nothing to compare) or the check fails; with payouts
    # present in the batch the totals no longer add up
    if (bad / "processor_payouts.csv").exists():
        assert not summary.success
        assert any("assert_payout_totals_equal_transactions" in f for f in summary.failures)
