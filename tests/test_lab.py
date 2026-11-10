import random

from trueup.lab import LabSettings, run

CLEAN = dict(outage_hours=0, card_testing_attempts=0, downgrade_share=0, dispute_multiplier=1)


def test_default_lab_finds_every_planted_incident():
    r = run(LabSettings())
    assert r["score"]["found"] == 4 and r["score"]["false_alarms"] == 0


def test_nothing_planted_stays_quiet_across_seeds():
    for seed in range(1, 16):
        r = run(LabSettings(seed=seed, **CLEAN))
        assert r["score"]["planted"] == 0
        assert all(x["verdict"] == "quiet" for x in r["results"]), seed


def test_random_settings_recall_and_no_false_alarms():
    """Random settings across the whole slider range: at least 90% of the incidents that
    left a detectable trace are found, and nothing is flagged that was not planted."""
    rng = random.Random(2026)
    found = missed = false_alarms = 0
    for _ in range(25):
        st = LabSettings(
            seed=rng.randint(1, 99999),
            days=rng.choice([35, 60, 90, 120]),
            txns_per_day=rng.choice([100, 200, 300, 400]),
            outage_hours=rng.randint(0, 12),
            card_testing_attempts=rng.choice([0, rng.randint(8, 800)]),
            downgrade_share=round(rng.uniform(0, 0.8), 2),
            dispute_multiplier=round(rng.uniform(1, 4), 1),
        )
        sc = run(st)["score"]
        found, missed, false_alarms = (
            found + sc["found"],
            missed + sc["missed"],
            false_alarms + sc["false_alarms"],
        )
    assert found / (found + missed) >= 0.9
    assert false_alarms == 0


def test_settings_are_clamped_and_deterministic():
    a = run(LabSettings(seed=11, days=500, txns_per_day=5))
    b = run(LabSettings(seed=11, days=500, txns_per_day=5))
    assert a["settings"]["days"] == 120 and a["settings"]["txns_per_day"] == 100
    assert a["results"] == b["results"]
