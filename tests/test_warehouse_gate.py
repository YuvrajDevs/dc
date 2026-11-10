"""The quality gate: what may enter the warehouse, and what is stopped (and why)."""

import csv
import shutil
from pathlib import Path

import pytest

from trueup.synth.generate import generate
from trueup.warehouse import Warehouse
from trueup.warehouse.split import split_world

FIELDS_TXN = (
    "txn_id,order_ref,merchant_id,currency,gross_minor,fee_minor,net_minor,captured_at,payout_id"
)


@pytest.fixture(scope="module")
def batches(tmp_path_factory, small_cfg):
    root = tmp_path_factory.mktemp("gate")
    generate(small_cfg, root / "world")
    split_world(root / "world", root / "batches")
    return root / "batches"


@pytest.fixture(scope="module")
def big_batches(tmp_path_factory):
    from trueup.synth.config import Config

    root = tmp_path_factory.mktemp("gate_big")
    generate(Config(seed=9, days=4, merchants=8, txns_per_day=700), root / "world")
    split_world(root / "world", root / "batches")
    return root / "batches"


def day_batch(batches: Path, tmp_path: Path) -> Path:
    """A private copy of one busy day, so tests can corrupt it freely."""
    src = sorted(p for p in batches.iterdir() if p.name[0] == "2")[2]
    dst = tmp_path / "batch"
    shutil.copytree(src, dst)
    return dst


def edit_csv(path: Path, change):
    with path.open(newline="") as f:
        rows = list(csv.DictReader(f))
        fields = list(rows[0])
    change(rows)
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    return len(rows)


def raw_count(wh, table):
    return wh.con.execute(f"SELECT count(*) FROM raw.{table}").fetchone()[0]


def test_clean_batch_loads(tmp_path, batches):
    with Warehouse(tmp_path / "w.duckdb") as wh:
        res = wh.load_batch(day_batch(batches, tmp_path))
        assert res.status == "loaded" and not res.rows_quarantined
        assert raw_count(wh, "ledger_entries") == res.rows_loaded["ledger_entries"] > 0


def test_missing_column_rejects_whole_batch(tmp_path, batches):
    b = day_batch(batches, tmp_path)
    text = (b / "processor_txns.csv").read_text().replace("fee_minor", "fee")
    (b / "processor_txns.csv").write_text(text)
    with Warehouse(tmp_path / "w.duckdb") as wh:
        res = wh.load_batch(b)
        assert res.status == "rejected"
        assert any("missing required column" in r and "fee_minor" in r for r in res.reasons)
        # nothing at all got in, not even the healthy files in the same batch
        assert raw_count(wh, "ledger_entries") == 0 and raw_count(wh, "processor_txns") == 0


def test_empty_file_rejects(tmp_path, batches):
    b = day_batch(batches, tmp_path)
    (b / "ledger_entries.csv").write_text(
        (b / "ledger_entries.csv").read_text().splitlines()[0] + "\n"
    )
    with Warehouse(tmp_path / "w.duckdb") as wh:
        res = wh.load_batch(b)
        assert res.status == "rejected" and any("no data rows" in r for r in res.reasons)


def test_few_bad_rows_are_quarantined_with_reasons(tmp_path, big_batches):
    b = day_batch(big_batches, tmp_path)

    def corrupt(rows):
        rows[0]["currency"] = "XXX"
        rows[1]["amount_minor"] = "12.5x"
        rows[2]["amount_minor"] = "-5"
        rows[3]["ledger_id"] = ""

    n = edit_csv(b / "ledger_entries.csv", corrupt)
    assert n > 400  # four bad rows stays under the 1% limit
    with Warehouse(tmp_path / "w.duckdb") as wh:
        res = wh.load_batch(b)
        assert res.status == "loaded_with_quarantine", res.reasons
        assert res.rows_quarantined["ledger_entries"] == 4
        assert raw_count(wh, "ledger_entries") == n - 4
        reasons = " | ".join(
            r[0] for r in wh.con.execute("SELECT reason FROM quarantine.rejected_rows").fetchall()
        )
        assert "currency: 'XXX' is not allowed" in reasons
        assert "amount_minor: bigint expected, got '12.5x'" in reasons
        assert "amount_minor: must be at least 1" in reasons
        assert "ledger_id: missing" in reasons
        # the original row is preserved for investigation
        sample = wh.con.execute("SELECT row_json FROM quarantine.rejected_rows LIMIT 1").fetchone()[
            0
        ]
        assert "ledger_id" in sample


def test_too_many_bad_rows_rejects_the_batch(tmp_path, batches):
    b = day_batch(batches, tmp_path)

    def corrupt(rows):
        for r in rows[::10]:  # 10% bad
            r["currency"] = "???"

    edit_csv(b / "ledger_entries.csv", corrupt)
    with Warehouse(tmp_path / "w.duckdb") as wh:
        res = wh.load_batch(b)
        assert res.status == "rejected"
        assert any("over the 1% limit" in r for r in res.reasons)
        assert raw_count(wh, "ledger_entries") == 0
        assert wh.con.execute("SELECT count(*) FROM quarantine.rejected_rows").fetchone()[0] == 0


def test_cross_field_rule(tmp_path, batches):
    b = day_batch(batches, tmp_path)

    def corrupt(rows):
        rows[0]["net_minor"] = str(int(rows[0]["net_minor"]) + 1)

    edit_csv(b / "processor_txns.csv", corrupt)
    with Warehouse(tmp_path / "w.duckdb") as wh:
        wh.load_batch(b)
        (reason,) = wh.con.execute("SELECT reason FROM quarantine.rejected_rows").fetchone()
        assert "net_minor must equal gross_minor - fee_minor" in reason


def test_answer_key_is_never_loaded(tmp_path, batches, small_cfg):
    b = day_batch(batches, tmp_path)
    world = tmp_path / "w"
    generate(small_cfg, world)
    shutil.copy(world / "answer_key.csv", b / "answer_key.csv")
    shutil.copy(world / "expected_links.csv", b / "expected_links.csv")
    with Warehouse(tmp_path / "w.duckdb") as wh:
        res = wh.load_batch(b)
        assert res.ok
        assert "answer_key.csv" in res.ignored_files
        assert any("grader-only" in r for r in res.reasons)
        names = [
            r[0]
            for r in wh.con.execute("SELECT table_name FROM information_schema.tables").fetchall()
        ]
        assert not any("answer" in n or "expected" in n for n in names)


def test_failure_midway_rolls_everything_back(tmp_path, batches):
    b = day_batch(batches, tmp_path)
    with Warehouse(tmp_path / "w.duckdb") as wh:
        # sabotage one raw table so the second insert fails after the first succeeded
        wh.con.execute("ALTER TABLE raw.processor_txns DROP COLUMN _source_file")
        with pytest.raises(Exception, match="(?i)column|table"):
            wh.load_batch(b)
        for table in ("ledger_entries", "bank_lines", "processor_payouts"):
            assert raw_count(wh, table) == 0, table
