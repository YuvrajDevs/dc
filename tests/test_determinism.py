import hashlib
import json
from dataclasses import replace

from tally.synth.generate import generate


def test_same_seed_gives_identical_files(tmp_path, small_cfg):
    a = generate(small_cfg, tmp_path / "a")
    b = generate(small_cfg, tmp_path / "b")
    assert a == b


def test_different_seed_changes_data(tmp_path, small_cfg):
    a = generate(small_cfg, tmp_path / "a")
    b = generate(replace(small_cfg, seed=small_cfg.seed + 1), tmp_path / "b")
    assert a["sha256"]["ledger_entries.csv"] != b["sha256"]["ledger_entries.csv"]


def test_manifest_hashes_match_files(tmp_path, small_cfg):
    generate(small_cfg, tmp_path)
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    for name, digest in manifest["sha256"].items():
        assert hashlib.sha256((tmp_path / name).read_bytes()).hexdigest() == digest
