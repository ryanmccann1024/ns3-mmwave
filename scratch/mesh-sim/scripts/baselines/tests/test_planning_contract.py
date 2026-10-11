"""Planning identity, ownership and resolved settings through a fake query worker."""

import json
from pathlib import Path

import pytest

from scripts.baselines import artifacts, preparation
from scripts.baselines.tests.conftest import install_stub_strategy, write_scenario


def test_evaluation_order_does_not_change_the_frozen_plan(tmp_path, fake_query, monkeypatch):
    install_stub_strategy(monkeypatch)
    ini = write_scenario(tmp_path / "scenario")
    outputs = []
    for index, seeds in enumerate(([9, 3], [3, 9])):
        prepared = preparation.prepare(
            ini,
            "geometric",
            tmp_path / str(index),
            mode="standalone",
            sim_binary=fake_query,
            simulation_seeds=seeds,
        )
        outputs.append(artifacts.read_json(prepared.manifest_path))
    assert outputs[0]["fingerprint"] == outputs[1]["fingerprint"]
    assert outputs[0]["planner_settings"] == outputs[1]["planner_settings"]
    assert outputs[0]["channel_scoring"]["planning_seed"] == 101
    assert outputs[0]["seed_roles"]["evaluation_seeds"] == [9, 3]
    assert outputs[1]["seed_roles"]["evaluation_seeds"] == [3, 9]


def test_planning_overlap_is_explicit(tmp_path, fake_query, monkeypatch):
    install_stub_strategy(monkeypatch)
    ini = write_scenario(tmp_path / "scenario")
    with pytest.raises(preparation.BaselinePreparationError, match="overlaps evaluation"):
        preparation.prepare(
            ini,
            "geometric",
            tmp_path / "refused",
            mode="standalone",
            sim_binary=fake_query,
            simulation_seeds=[101, 2],
        )
    assert not (tmp_path / "refused/effective-inputs.partial").exists()
    prepared = preparation.prepare(
        ini,
        "geometric",
        tmp_path / "diagnostic",
        mode="standalone",
        sim_binary=fake_query,
        simulation_seeds=[101, 2],
        allow_seed_overlap=True,
    )
    roles = prepared.metadata["seed_roles"]
    assert roles["planning_overlap"] == [101]
    assert roles["held_out_from_planning"] is False
    assert roles["overlap_allowed"] is True


def test_settings_and_diagnostics_survive_preparation(tmp_path, fake_query, monkeypatch):
    monkeypatch.setenv("FAKE_QUERY_DIAGNOSTICS", '["coverage heights extrapolated"]')
    ini = write_scenario(
        tmp_path / "scenario", overrides={"candidate_grid_cells": "4", "coverage_grid_cells": "4"}
    )
    with ini.open("a") as handle:
        handle.write(
            "\n[placement_objective]\ncoverage_weight = 2\n"
            "\n[channel_query_client]\ncache_bytes = 0\nmax_layouts = 1\n"
        )
    prepared = preparation.prepare(
        ini,
        "geometric",
        tmp_path / "plan",
        mode="standalone",
        sim_binary=fake_query,
        planning_seed=707,
    )
    manifest = artifacts.read_json(prepared.manifest_path)
    assert manifest["seed_roles"]["planning_seed_source"] == "cli"
    assert manifest["channel_scoring"]["planning_seed"] == 707
    assert manifest["planner_settings"]["query_client"]["cache_bytes"] == 0
    assert manifest["planner_settings"]["worker_limits"]["child_deadline_s"] == 60
    assert manifest["planner_settings"]["objective_settings"]["coverage_weight"] == 2
    plan = artifacts.read_json(prepared.plan_path)
    assert plan["planner_predictions"]["channel_diagnostics"] == ["coverage heights extrapolated"]
    assert manifest["planner_settings"]["sha256"]
    assert manifest["channel_scoring"]["resolved_channel"]


def test_active_gateway_cannot_be_selected_even_with_all(tmp_path, fake_query, monkeypatch):
    def forbidden(*args):
        raise AssertionError("worker must not be started")

    monkeypatch.setattr("scripts.baselines.solver.solve", forbidden)
    ini = write_scenario(
        tmp_path / "scenario", overrides={"movable_nodes": "all", "waypoint_policy": "translate"}
    )
    with ini.open("a") as handle:
        handle.write("\n[traffic]\nflow_topology = gateway\ngateway_node_id = gw\n")
    with pytest.raises(preparation.BaselinePreparationError, match="active traffic gateway"):
        preparation.prepare(
            ini, "geometric", tmp_path / "refused", mode="standalone", sim_binary=fake_query
        )


def test_missing_planning_seed_fails_before_a_worker(tmp_path, fake_query):
    ini = write_scenario(tmp_path / "scenario", drop=("planning_seed",))
    with pytest.raises(preparation.BaselinePreparationError, match="requires.*planning_seed"):
        preparation.prepare(
            ini, "geometric", tmp_path / "refused", mode="standalone", sim_binary=fake_query
        )
