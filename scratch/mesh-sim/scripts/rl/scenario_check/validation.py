"""Fail before reference movement when a configured event and actual command differ."""

import json
from pathlib import Path

from scripts.artifact_io import sha256_file
from scripts.rl.env.config import read_jammer_onsets
from scripts.rl.scenario_check.defaults import EVALUATION_SEEDS
from scripts.rl.scenario_check.archive import read_ini


def jammer_timing(config, case, seed, command=None):
    """Verify fixed intervals, no inherited override, and emission through last tick."""
    config = Path(config)
    ini = read_ini(config)
    if any(read_jammer_onsets(str(config))):
        raise ValueError(
            "fixed jammer intervals conflict with inherited training/evaluation onset schedules"
        )
    if command is not None and any(x.startswith("--jammer-onset-s") for x in command):
        raise ValueError(
            "unexpected jammer onset override; fixed intervals must remain authoritative"
        )
    path = Path(ini["scenario"]["jammers_file"])
    if not path.is_absolute():
        path = config.parent / path
    jammers = json.loads(path.read_text())
    active = [j for j in jammers if j.get("enabled")]
    if len(active) != 1:
        raise ValueError("scenario check requires exactly one enabled scheduled jammer")
    jammer = active[0]
    intervals = jammer.get("intervals", [])
    onset = case["seeds"][str(seed)]["gate_s"]
    duration = ini.getfloat("scenario", "duration_s")
    if (
        len(intervals) != 1
        or intervals[0]["start"] != onset
        or intervals[0]["end"] <= duration
    ):
        raise ValueError(
            "jammer interval must match controller gate and extend beyond final sample"
        )
    points = jammer.get("waypoints", [])
    if len(points) != 4 or points[2]["t"] != onset or points[1]["t"] != onset - 60:
        raise ValueError(
            "jammer must approach silently for 60 seconds and stop at emission"
        )
    if (
        any(points[2][axis] != points[3][axis] for axis in "xyz")
        or points[3]["t"] < duration
    ):
        raise ValueError(
            "jammer must remain at its destination through the final sample"
        )
    return dict(
        event_timing_version=1,
        onset_s=onset,
        end_s=intervals[0]["end"],
        command_checked=command is not None,
        authoritative_source="fixed_input_intervals",
        stationary_position=[points[2][axis] for axis in "xyz"],
        max_range_m=jammer["max_range_m"],
    )


def placement_methods(case):
    methods = case.get(
        "placement_benchmarks",
        ["geometric", "optimization"] if case["mission"] == "coverage" else [],
    )
    if len(set(methods)) != len(methods) or any(
        m not in ("geometric", "optimization") for m in methods
    ):
        raise ValueError("unknown or repeated placement benchmark")
    if methods and case["mission"] != "coverage":
        raise ValueError("placement benchmarks apply only to coverage")
    return methods


def validate_inputs(source):
    source = Path(source)
    campaign = json.loads((source / "scenario-check.json").read_text())
    if (
        campaign["scenario_check_version"] not in (1, 2)
        or campaign["training_enabled"] is not False
    ):
        raise ValueError("expected a version 1 or 2 checks-only campaign")
    for relative, digest in campaign["input_hashes"].items():
        if sha256_file(source / relative) != digest:
            raise ValueError(
                f"input changed after preparation: {relative}; review before replacing its fingerprint"
            )
    cases = campaign["cases"]
    count = sum((3 + len(placement_methods(c))) * len(c["seeds"]) for c in cases)
    if (
        not cases
        or len({c["name"] for c in cases}) != len(cases)
        or count != campaign["episodes_expected"]
    ):
        raise ValueError("case inventory and expected episode count disagree")
    if campaign["scenario_check_version"] == 1 and (len(cases) != 24 or count != 168):
        raise ValueError("expected original 24 scenarios / 168 episodes")
    if campaign["scenario_check_version"] == 2:
        for case in cases:
            if set(case["seeds"]) != {str(seed) for seed in EVALUATION_SEEDS}:
                raise ValueError(
                    "correction checks require paired diagnostic seeds 201/202"
                )
            for seed, settings in case["seeds"].items():
                config = source / case["name"] / settings["run_config"]
                if case["mission"] == "jamming":
                    jammer_timing(config, case, int(seed))
    return campaign
