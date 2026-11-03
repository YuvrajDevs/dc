"""The reconciliation engine on small generated worlds, graded against the answer key."""

import json
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest

from tally.grade import check_floors, grade, load_key
from tally.pipeline import load_world
from tally.recon import ReconConfig, reconcile
from tally.recon import queue as xq
from tally.synth.config import HARD, Config
from tally.synth.generate import generate
from tally.warehouse import Warehouse

FLOORS = json.loads((Path(__file__).parents[1] / "benchmarks" / "floors.json").read_text())


def build(root: Path, cfg: Config):
    world, db = root / "world", root / "wh.duckdb"
    generate(cfg, world)
    load_world(world, db)
    return world, db, ReconConfig(as_of=cfg.start + timedelta(days=cfg.days + 5))


@pytest.fixture(scope="module")
def easy(tmp_path_factory):
    return build(
        tmp_path_factory.mktemp("easy"), Config(seed=21, days=30, merchants=10, txns_per_day=300)
    )


@pytest.fixture(scope="module")
def hard(tmp_path_factory):
    cfg = Config(seed=22, days=30, merchants=10, txns_per_day=300, hardness=HARD)
    return build(tmp_path_factory.mktemp("hard"), cfg)


def run(env, cfg=None):
    world, db, recon_cfg = env
    wh = Warehouse(db)
    reconcile(wh, cfg or recon_cfg)
    return wh, grade(wh, world)


def test_easy_world_meets_its_floors(easy):
    wh, card = run(easy)
    with wh:
        assert check_floors(card, FLOORS["easy"]) == []
        assert card.benign_false_alarms == 0


def test_hard_world_meets_its_floors(hard):
    wh, card = run(hard)
    with wh:
        assert check_floors(card, FLOORS["hard"]) == []


def test_mistyped_references_are_matched_to_the_right_payment(hard):
    """A digit swap often names a different real order. Matching must not be fooled."""
    world, _, _ = hard
    typos = [
        d
        for d in load_key(world)
        if d["class"] == "ref_noise" and json.loads(d["detail"]).get("mode") == "typo"
    ]
    assert len(typos) > 5
    wh, card = run(hard)
    with wh:
        ledger_ids = [json.loads(d["entities"])[0]["id"] for d in typos]
        right = {
            (r[0], r[1])
            for r in wh.con.execute(
                "SELECT left_id, right_id FROM recon.links WHERE link_type = 'ledger_txn'"
            ).fetchall()
        }
        expected = {
            (json.loads(d["entities"])[0]["id"], json.loads(d["entities"])[1]["id"]) for d in typos
        }
        assert len(expected & right) / len(expected) > 0.95, ledger_ids[:3]
        assert card.links["ledger_txn"]["recall"] >= 0.999


def test_engine_never_reads_the_answer_key():
    import tally.recon.engine as engine

    source = Path(engine.__file__).read_text()
    assert "answer_key" not in source and "expected_links" not in source


def test_running_twice_gives_identical_results(easy):
    wh, _ = run(easy)
    with wh:
        before = wh.fingerprints(("recon",))
    wh, _ = run(easy)
    with wh:
        assert wh.fingerprints(("recon",)) == before


def test_a_payout_is_only_missing_once_its_window_has_passed(easy):
    world, db, cfg = easy
    early = replace(cfg, as_of=cfg.as_of - timedelta(days=12))
    with Warehouse(db) as wh:
        late_summary = reconcile(wh, cfg)
        early_summary = reconcile(wh, early)
        assert early_summary.pending_payouts > 0
        assert (
            early_summary.findings.get("payout_missing", 0)
            < late_summary.findings["payout_missing"]
        )
        reconcile(wh, cfg)  # leave the shared warehouse in its normal state


def test_benign_look_alikes_are_explained_not_alarmed(easy):
    wh, _ = run(easy)
    with wh:
        rows = dict(
            wh.con.execute("SELECT category, count(*) FROM recon.findings GROUP BY 1").fetchall()
        )
        assert rows["benign"] > 0 and rows["error"] > 0
        statuses = wh.con.execute(
            "SELECT DISTINCT status FROM recon.findings WHERE category = 'benign'"
        ).fetchall()
        assert statuses == [("explained",)]


def test_every_finding_explains_itself(easy):
    wh, _ = run(easy)
    with wh:
        rows = wh.con.execute(
            "SELECT reason, confidence, entities FROM recon.findings "
            "WHERE reason IS NULL OR length(reason) < 15 "
            "OR confidence IS NULL OR confidence <= 0 OR confidence > 1"
        ).fetchall()
        assert rows == []


def test_a_broken_engine_fails_the_regression_gate(hard):
    """The gate only means something if it actually fails when matching gets worse."""
    broken = ReconConfig(
        as_of=hard[2].as_of,
        attr_before_minutes=0,
        attr_after_hours=0,
        fuzzy_amount_pct=0,
        bank_fuzzy_pct=0,
    )
    wh, card = run(hard, broken)
    with wh:
        failures = check_floors(card, FLOORS["hard"])
        assert failures, "a crippled engine must not pass"
        reconcile(wh, hard[2])


def test_exception_queue_keeps_human_decisions_across_runs(easy):
    world, db, cfg = easy
    with Warehouse(db) as wh:
        wh.con.execute("DROP TABLE IF EXISTS ops.exceptions")
        wh.con.execute("DROP TABLE IF EXISTS ops.exception_events")
        reconcile(wh, cfg)
        first = xq.sync(wh)
        assert first["new"] > 0
        errors, benign = (
            wh.con.execute(
                "SELECT count(*) FROM ops.exceptions WHERE category = ? AND status = ?", [c, s]
            ).fetchone()[0]
            for c, s in (("error", "open"), ("benign", "explained"))
        )
        assert errors > 0 and benign > 0

        fid = wh.con.execute(
            "SELECT finding_id FROM ops.exceptions WHERE status = 'open' LIMIT 1"
        ).fetchone()[0]
        with pytest.raises(ValueError, match="note is required"):
            xq.set_status(wh, fid, "explained", actor="amina", note="")
        with pytest.raises(ValueError, match="actor"):
            xq.set_status(wh, fid, "resolved", actor=" ", note="fixed")
        xq.set_status(wh, fid, "explained", actor="amina", note="Known fee dispute, ticket 4411")

        reconcile(wh, cfg)
        again = xq.sync(wh)
        assert again == {"new": 0, "reopened": 0, "auto_cleared": 0}
        row = wh.con.execute(
            "SELECT status, note, updated_by FROM ops.exceptions WHERE finding_id = ?", [fid]
        ).fetchone()
        assert row == ("explained", "Known fee dispute, ticket 4411", "amina")
        trail = xq.history(wh, fid)
        assert [t["to"] for t in trail] == ["open", "explained"]
        assert trail[1]["actor"] == "amina"


def test_findings_that_go_away_auto_clear_and_come_back(easy):
    world, db, cfg = easy
    with Warehouse(db) as wh:
        reconcile(wh, cfg)
        xq.sync(wh)
        reconcile(
            wh, replace(cfg, as_of=cfg.as_of - timedelta(days=12))
        )  # some payouts become pending
        gone = xq.sync(wh)
        assert gone["auto_cleared"] > 0
        reconcile(wh, cfg)
        back = xq.sync(wh)
        assert back["reopened"] == gone["auto_cleared"]
