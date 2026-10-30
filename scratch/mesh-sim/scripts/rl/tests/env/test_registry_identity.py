"""Frozen identities of the reward-component and observation-preset registries.

Saved models are checked against reward and observation schema hashes, and
those hashes include descriptor text and context field lists. This test pins,
for every registered reward component and observation preset: its id, its
registration-order index, its descriptor (formula, zero-demand rule, context
fields, parameters, normalization, ...) and the schema SHA-256 that production
code computes with default parameters against one fixed synthetic contract.
Adding, removing, reordering or changing any registered item fails the test.

The fixture also records each item's defining module so source renames are
visible in diffs. That module name is informational only and is deliberately
NOT asserted: renaming source files must not change scientific identities.

The fixed contract is stored in the fixture itself, so the test does not depend
on other test modules or on simulator output.

Regenerate the fixture only when an identity change is intended and approved::

    .venv/bin/python -m scripts.rl.tests.env.test_registry_identity --write
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.artifact_io import canonical_sha256, now_iso
from scripts.rl.env import observations, rewards

REGISTRY_IDENTITY_VERSION = 1
MESH_ROOT = Path(__file__).resolve().parents[4]
FIXTURE = MESH_ROOT / "tests" / "fixtures" / "registry_identity.json"

# Synthetic init contract carrying every field any registered component or
# preset reads; values are arbitrary but frozen in the fixture once written.
SYNTHETIC_CONTRACT = {
    "type": "init",
    "contract": "mesh_move_2d_v2",
    "dimensions": 2,
    "action_meanings": ["west", "east", "south", "north", "hold"],
    "max_controlled_nodes": 3,
    "num_controlled": 2,
    "slot_node_ids": ["node-b", "node-c", None],
    "slot_speed_mps": [10.0, 10.0, None],
    "num_mesh_nodes": 3,
    "obs_dim": 24,
    "mask_dim": 15,
    "tick_s": 0.1,
    "decision_interval_s": 0.5,
    "decision_interval_ticks": 5,
    "num_ticks": 10,
    "num_decisions": 2,
    "reward_type": "all_links_los",
    "reward_window": "mean",
    "wall_policy": "clip",
    "facts_schema": "mesh_facts_v2",
    "facts_columns": {"nodes": ["x", "y", "z", "vx", "vy", "vz", "slot"],
                      "links": ["sinr_db", "capacity_mbps", "is_los"]},
    "node_ids": ["node-a", "node-b", "node-c"],
    "node_types": ["vehicle", "drone", "pedestrian"],
    "num_links": 3,
    "bounds": {"x_min": 0.0, "x_max": 100.0, "y_min": -50.0, "y_max": 100.0,
               "z_min": 0.0, "z_max": 50.0},
    "band": "mmwave",
    "jammer_path_enabled": False,
    "warmup_s": 0.0,
    "reward_warmup": "exclude",
    "node_service_columns": ["demand_mbps_sum", "delivered_mbps_sum"],
    "mission": {"version": 2, "kind": "investigation", "investigator_id": "node-b",
                "coverage_domain": "outdoor_probe_cells", "progress_distance_scale_m": 100.0,
                "goal_x": 80.0, "goal_y": 60.0, "arrival_radius_m": 15.0,
                "coverage_radius_m": 50.0, "dwell_s": 30.0, "goal_coverage_target": 0.8,
                "recovery_delivery_target": 0.9, "recovery_coverage_ratio": 0.9,
                "recovery_worst_target": 0.8, "team_investigation": True,
                "team_radius_m": 50.0, "team_delivery_target": 0.8},
    "avoid_buildings": False,
    "avoid_node_collisions": False,
    "navigation": {"version": 1, "building_clearance_m": 0.0, "mask_building_moves": True,
                   "obstacle_sensing_range_m": 20.0, "buildings": []},
    "unsafe_separation_m": 1.0,
    "coverage": {"grid_cells": 100, "min_resolution_m": 5.0, "probe_height_m": 1.5,
                 "probe_rx_gain_dbi": 0.0, "sinr_db": -6.7,
                 "measurement": "decision_endpoint_connected_core"},
    "deployment_gate": {"version": 1, "source": "control_start_s"},
    "control_start_s": 0.0,
}


def _jsonable(value):
    return json.loads(json.dumps(value, allow_nan=False))


def _module_of(func) -> str:
    return getattr(func, "__module__", None) or type(func).__module__


def reward_identity(name: str, index: int, contract: dict) -> dict:
    component = rewards.get_component(name)
    defaults = component.resolve({})
    detail = component.schema(contract, defaults)
    return _jsonable({
        "id": name,
        "index": index,
        "module": _module_of(component._value),
        "descriptor": {
            "range": list(component.range),
            "required_facts": list(component.required_facts),
            "contract_fields": list(component.contract_fields),
            "tunable": {key: list(spec) for key, spec in component.tunable.items()},
            "default_parameters": defaults,
            "formula_template": component.formula,
            "formula": detail["formula"],
            "zero_demand_rule": component.zero_demand_rule,
            "fact_extensions": list(component.fact_extensions),
            "has_context_builder": component.context_builder is not None,
        },
        "context_fields": list(component.context_fields),
        "component_schema_sha256": canonical_sha256(detail),
        "schema_sha256": rewards.reward_schema([name], [1.0], contract=contract)["sha256"],
    })


def preset_identity(name: str, index: int, contract: dict) -> dict:
    preset = observations.get_preset(name)
    schema = observations.observation_schema(name, contract)
    return _jsonable({
        "id": name,
        "index": index,
        "module": _module_of(preset._build),
        "descriptor": {
            "dtype": preset.dtype,
            "normalization": schema["normalization"],
            "normalization_fields": list(preset.normalization_fields),
            "default_parameters": dict(preset.parameters),
            "required_facts": list(preset.required_facts),
            "compatibility_fields": list(preset.compatibility_fields),
            "fact_extensions": list(preset.fact_extensions),
            "feature_names": schema["feature_names"],
            "obs_dim": schema["obs_dim"],
        },
        "context_fields": [],
        "schema_sha256": schema["sha256"],
    })


def compute_identity(contract: dict) -> dict:
    reward_order = list(rewards.COMPONENTS)
    preset_order = list(observations.PRESETS)
    return {
        "reward_components": {
            "registration_order": reward_order,
            "items": [reward_identity(name, i, contract) for i, name in enumerate(reward_order)],
        },
        "observation_presets": {
            "registration_order": preset_order,
            "default_preset": observations.DEFAULT_PRESET,
            "items": [preset_identity(name, i, contract) for i, name in enumerate(preset_order)],
        },
    }


def _git_head() -> str | None:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=MESH_ROOT, check=True,
                              capture_output=True, text=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def write_fixture(path: Path = FIXTURE) -> dict:
    payload = {
        "registry_identity_version": REGISTRY_IDENTITY_VERSION,
        "created_utc": now_iso(),
        "git_head": _git_head(),
        "generator": "python -m scripts.rl.tests.env.test_registry_identity --write",
        "contract": SYNTHETIC_CONTRACT,
        **compute_identity(SYNTHETIC_CONTRACT),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
                    encoding="utf-8")
    return payload


@pytest.fixture(scope="module")
def frozen():
    if not FIXTURE.exists():
        pytest.fail(f"missing {FIXTURE}; generate it with --write before moving sources")
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def live(frozen):
    return compute_identity(frozen["contract"])


REGISTRIES = ("reward_components", "observation_presets")
COMPARED = ("id", "index", "descriptor", "context_fields", "schema_sha256",
            "component_schema_sha256")


def test_fixture_version(frozen):
    assert frozen["registry_identity_version"] == REGISTRY_IDENTITY_VERSION


@pytest.mark.parametrize("registry", REGISTRIES)
def test_registration_order_is_frozen(frozen, live, registry):
    assert live[registry]["registration_order"] == frozen[registry]["registration_order"]


@pytest.mark.parametrize("registry", REGISTRIES)
def test_every_item_identity_is_frozen(frozen, live, registry):
    """Module names are recorded but intentionally excluded from comparison."""
    expected = {item["id"]: item for item in frozen[registry]["items"]}
    actual = {item["id"]: item for item in live[registry]["items"]}
    assert sorted(actual) == sorted(expected)
    mismatches = {
        name: [key for key in COMPARED if actual[name].get(key) != expected[name].get(key)]
        for name in expected
    }
    assert {name: keys for name, keys in mismatches.items() if keys} == {}


def test_default_preset_is_frozen(frozen, live):
    assert (live["observation_presets"]["default_preset"]
            == frozen["observation_presets"]["default_preset"])


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--write", action="store_true",
                        help=f"regenerate {FIXTURE.relative_to(MESH_ROOT)}")
    args = parser.parse_args(argv)
    if not args.write:
        parser.error("pass --write to regenerate the fixture; run pytest to check it")
    payload = write_fixture()
    print(f"wrote {FIXTURE}: {len(payload['reward_components']['items'])} reward components, "
          f"{len(payload['observation_presets']['items'])} observation presets")
    return 0


if __name__ == "__main__":
    sys.exit(main())
