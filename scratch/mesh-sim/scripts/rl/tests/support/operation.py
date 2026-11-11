"""Shared setup for policy operation tests."""

import pytest
from scripts.rl.policy import bundle as bundles
from scripts.rl.tests.policy.test_online_protocols import (
    three_decision_config,
    train_run,
)


pytest.importorskip("sb3_contrib")

# The 10-23-2 escape settings, split by kind.
INITIAL = {"initial_sample_decisions": 60}
STALL = {
    "burst_decisions": 20,
    "cooldown_decisions": 40,
    "max_bursts": 3,
    "rejected_window": 20,
    "rejected_threshold": 10,
    "movement_threshold_m": 1.0,
    "progress_window": 60,
    "progress_threshold": 0.01,
}
CASE = {"mission": "coverage", "coverage_target": 0.5}


@pytest.fixture(name="trained")
def trained_policy(sim_binary, multi_run_config, tmp_path, monkeypatch):
    config = three_decision_config(multi_run_config)
    run = train_run(sim_binary, config, tmp_path / "train", monkeypatch)
    return bundles.read_bundle(run, "final"), config


def operate(*argv):
    from scripts.rl import operate as cli

    return cli.main([str(a) for a in argv])
