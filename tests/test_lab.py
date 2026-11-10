from trueup.lab import LabSettings, run


def test_default_lab_finds_every_planted_incident():
    r = run(LabSettings())
    assert r["score"] == {"found": 4, "missed": 0, "false_alarms": 0, "planted": 4}


def test_nothing_planted_stays_quiet():
    r = run(
        LabSettings(
            outage_hours=0, card_testing_attempts=0, downgrade_share=0, dispute_multiplier=0
        )
    )
    assert r["score"]["planted"] == 0
    assert all(x["verdict"] == "quiet" for x in r["results"])


def test_settings_are_clamped_and_deterministic():
    a = run(LabSettings(seed=11, days=500, txns_per_day=5))
    b = run(LabSettings(seed=11, days=500, txns_per_day=5))
    assert a["settings"]["days"] == 120 and a["settings"]["txns_per_day"] == 100
    assert a["results"] == b["results"]
