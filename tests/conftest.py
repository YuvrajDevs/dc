from dataclasses import fields

import pytest

from tally.synth.config import Config, Rates


def zero_rates() -> Rates:
    return Rates(**{f.name: 0.0 for f in fields(Rates)})


@pytest.fixture(scope="session")
def small_cfg() -> Config:
    return Config(seed=7, days=20, merchants=8, txns_per_day=150)
