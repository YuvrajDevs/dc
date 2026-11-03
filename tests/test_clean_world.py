"""With no defects injected, all three sources must agree exactly."""

from collections import defaultdict
from dataclasses import replace

from conftest import zero_rates

from tally.synth import world
from tally.synth.generate import build


def test_clean_world_reconciles_perfectly(small_cfg):
    t = build(replace(small_cfg, rates=zero_rates()))
    ledger = {e["order_ref"]: e for e in t["ledger_entries"]}
    txns = t["processor_txns"]

    assert len(t["ledger_entries"]) == len(txns) == len(ledger)
    assert t["answer_key"] == []

    tier = {m["merchant_id"]: m["fee_tier"] for m in t["merchants"]}
    for tx in txns:
        led = ledger[tx["order_ref"]]
        assert led["amount_minor"] == tx["gross_minor"]
        assert tx["fee_minor"] == world.fee_for(
            tx["gross_minor"], tier[tx["merchant_id"]], tx["currency"]
        )
        assert tx["net_minor"] == tx["gross_minor"] - tx["fee_minor"] > 0
        assert led["booked_at"].date() == tx["captured_at"].date()


def test_clean_payouts_and_bank_agree(small_cfg):
    t = build(replace(small_cfg, rates=zero_rates()))
    by_payout = defaultdict(int)
    for tx in t["processor_txns"]:
        by_payout[tx["payout_id"]] += tx["net_minor"]
    assert all(po["net_minor_total"] == by_payout[po["payout_id"]] for po in t["processor_payouts"])

    bank = {b["reference"]: b for b in t["bank_lines"]}
    assert len(bank) == len(t["bank_lines"]) == len(t["processor_payouts"])
    for po in t["processor_payouts"]:
        assert bank[po["payout_id"]]["amount_minor"] == po["net_minor_total"]
        assert bank[po["payout_id"]]["currency"] == po["currency"]


def test_every_clean_record_has_exactly_one_link(small_cfg):
    t = build(replace(small_cfg, rates=zero_rates()))
    links = defaultdict(list)
    for link in t["expected_links"]:
        links[link["link_type"]].append(link)
    assert len(links["ledger_txn"]) == len(t["processor_txns"])
    assert len(links["payout_bank"]) == len(t["processor_payouts"])
