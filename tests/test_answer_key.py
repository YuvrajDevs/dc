"""The answer key must be complete, consistent and refer only to real records."""

import json
from collections import Counter, defaultdict
from dataclasses import replace

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from trueup.synth.classes import DEFECT_CLASSES
from trueup.synth.config import Config
from trueup.synth.generate import build

ID_COLUMN = {
    "ledger": ("ledger_entries", "ledger_id"),
    "processor": ("processor_txns", "txn_id"),
    "processor_payout": ("processor_payouts", "payout_id"),
    "bank": ("bank_lines", "bank_line_id"),
}


def ids(tables, source):
    table, col = ID_COLUMN[source]
    return {row[col] for row in tables[table]}


def check_key_integrity(t):
    known = {s: ids(t, s) for s in ID_COLUMN}
    defect_ids = [d["defect_id"] for d in t["answer_key"]]
    assert len(defect_ids) == len(set(defect_ids))
    for d in t["answer_key"]:
        assert d["class"] in DEFECT_CLASSES
        assert d["category"] == DEFECT_CLASSES[d["class"]][0]
        entities = json.loads(d["entities"])
        assert entities
        for e in entities:
            assert e["id"] in known[e["source"]], (d, e)
    for link in t["expected_links"]:
        left, right = (("ledger", "processor") if link["link_type"] == "ledger_txn"
                       else ("processor_payout", "bank"))  # fmt: skip
        assert link["left_id"] in known[left]
        assert link["right_id"] in known[right]


def test_default_world_key_is_consistent(small_cfg):
    check_key_integrity(build(small_cfg))


def test_every_defect_class_appears_in_a_larger_world():
    t = build(Config(seed=3, days=60, merchants=12, txns_per_day=300))
    seen = Counter(d["class"] for d in t["answer_key"])
    assert set(seen) == set(DEFECT_CLASSES) - {"bank_ref_missing"}  # hard profile only
    # enough cases per class to grade meaningfully
    assert min(seen.values()) >= 10, seen


def test_each_payout_total_still_reconciles_unless_defective(small_cfg):
    t = build(small_cfg)
    defective = defaultdict(set)
    for d in t["answer_key"]:
        for e in json.loads(d["entities"]):
            if e["source"] == "processor_payout":
                defective[e["id"]].add(d["class"])
    by_payout = defaultdict(int)
    for tx in t["processor_txns"]:
        by_payout[tx["payout_id"]] += tx["net_minor"]
    bank = defaultdict(int)
    for b in t["bank_lines"]:
        bank[b["reference"]] += b["amount_minor"]
    for po in t["processor_payouts"]:
        assert po["net_minor_total"] == by_payout[po["payout_id"]]
        flagged = defective.get(po["payout_id"], set())
        if flagged & {"payout_missing", "payout_short"}:
            continue
        assert bank[po["payout_id"]] == po["net_minor_total"], po["payout_id"]


def test_missing_records_have_no_link(small_cfg):
    t = build(small_cfg)
    linked_txns = {
        link["right_id"] for link in t["expected_links"] if link["link_type"] == "ledger_txn"
    }
    for d in t["answer_key"]:
        if d["class"] == "missing_in_ledger":
            (e,) = json.loads(d["entities"])
            assert e["id"] not in linked_txns


@pytest.mark.parametrize("cls", ["fee_variance", "amount_mismatch"])
def test_error_details_are_real_differences(small_cfg, cls):
    t = build(replace(small_cfg, days=40))
    rows = [d for d in t["answer_key"] if d["class"] == cls]
    assert rows
    for d in rows:
        detail = json.loads(d["detail"])
        if cls == "fee_variance":
            assert detail["actual_fee_minor"] > detail["expected_fee_minor"]
        else:
            assert detail["delta_minor"] != 0


@settings(max_examples=15, deadline=None)
@given(
    seed=st.integers(min_value=0, max_value=10_000),
    days=st.integers(min_value=2, max_value=12),
    merchants=st.integers(min_value=1, max_value=10),
    per_day=st.integers(min_value=5, max_value=80),
)
def test_key_integrity_holds_for_random_worlds(seed, days, merchants, per_day):
    t = build(Config(seed=seed, days=days, merchants=merchants, txns_per_day=per_day))
    check_key_integrity(t)
    assert all(tx["net_minor"] > 0 for tx in t["processor_txns"])
    assert all(isinstance(e["amount_minor"], int) for e in t["ledger_entries"])


def test_hard_profile_adds_the_adversarial_cases():
    from trueup.synth.config import HARD

    t = build(Config(seed=3, days=60, merchants=12, txns_per_day=300, hardness=HARD))
    seen = Counter(d["class"] for d in t["answer_key"])
    assert set(seen) == set(DEFECT_CLASSES)
    modes = Counter(
        json.loads(d["detail"]).get("mode") for d in t["answer_key"] if d["class"] == "ref_noise"
    )
    assert modes["typo"] > 10
    check_key_integrity(t)
    # compound defects: some payments carry two defects at once
    by_entity = Counter()
    for d in t["answer_key"]:
        if d["level"] == "txn":
            for e in json.loads(d["entities"]):
                by_entity[(e["source"], e["id"])] += 1
    assert any(n > 1 for n in by_entity.values())
