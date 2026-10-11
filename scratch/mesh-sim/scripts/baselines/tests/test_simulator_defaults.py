"""Compare Python planning fallbacks with the actual ns-3-free C++ input loader."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from scripts.baselines import adapter, config, preparation

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module")
def config_reader(tmp_path_factory):
    compiler = shutil.which("c++")
    if compiler is None:
        pytest.skip("C++ compiler unavailable for cross-language loader parity")
    directory = tmp_path_factory.mktemp("config-reader")
    source = directory / "reader.cc"
    source.write_text(
        """#include "src/config/config-loader.h"
#include "third_party/json.hpp"
#include <iostream>
int main(int argc, char** argv) {
    auto cfg = mesh_sim::ConfigLoader::Load(argv[1]);
    auto rw = cfg.nodes.front().random_walk;
    nlohmann::json out = {
        {"seed", cfg.seed}, {"run_id", cfg.run_id}, {"band", cfg.band},
        {"rl", {{"x_min", cfg.rl.x_min}, {"x_max", cfg.rl.x_max},
                {"y_min", cfg.rl.y_min}, {"y_max", cfg.rl.y_max}}},
        {"random_walk", {{"x_min", rw.x_min}, {"x_max", rw.x_max},
                         {"y_min", rw.y_min}, {"y_max", rw.y_max}}}
    };
    std::cout << out.dump();
}
"""
    )
    binary = directory / "reader"
    sources = ["config-loader.cc", "rl-control.cc", "layout-override.cc", "query-config.cc"]
    subprocess.run(
        [
            compiler,
            "-std=c++17",
            "-I",
            str(ROOT),
            str(source),
            *(str(ROOT / "src/config" / name) for name in sources),
            str(ROOT / "src/util/string-utils.cc"),
            str(ROOT / "src/util/ini-parser.cc"),
            "-o",
            str(binary),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return binary


@pytest.mark.parametrize("overrides", [False, True])
def test_loader_defaults_and_partial_overrides_agree(config_reader, tmp_path, overrides):
    node = {"id": "n", "mobility": "random_walk"}
    ini = "[output]\ndir = outputs\n"
    if overrides:
        node["random_walk"] = {"bounds": {"x_min": -23.5, "y_max": 87}}
        ini += "[scenario]\nseed = 9\nrun_id = 3\n[channel]\nband = sub-6\n[rl]\nx_max = 345\n"
    (tmp_path / "nodes.json").write_text(json.dumps([node]))
    path = tmp_path / "run.ini"
    path.write_text(ini)
    actual = json.loads(subprocess.check_output([str(config_reader), str(path)], text=True))
    parsed = config.read_ini(path)
    assert actual["seed"] == config.scenario_int(parsed, "seed", config.DEFAULT_SCENARIO_SEED)
    assert actual["run_id"] == config.scenario_int(parsed, "run_id", config.DEFAULT_RUN_ID)
    assert actual["band"] == preparation.resolve_band(parsed, None)[0]
    assert actual["rl"] == config.effective_rl_bounds(parsed)
    assert actual["random_walk"] == adapter._random_walk_bounds(node)


@pytest.mark.parametrize("name", ["run.ini", "run-zero-cost.ini"])
def test_committed_workflow_inputs_match_loader(config_reader, name):
    path = ROOT / "inputs/baselines/channel-scored-example" / name
    actual = json.loads(subprocess.check_output([str(config_reader), str(path)], text=True))
    cfg = config.load_baseline(path)
    ini = config.read_ini(path)
    config.require_method(cfg, "optimization")
    assert config.resolve_planning_seed(cfg) == (701, "run.ini")
    assert actual["seed"] == 801
    assert actual["run_id"] == 1
    assert actual["rl"] == config.effective_rl_bounds(ini)
    zero = name == "run-zero-cost.ini"
    assert (cfg.aerial_fixed_cost_m2 == 0) == zero
    assert (cfg.ground_fixed_cost_m2 == 0) == zero
    assert (cfg.aerial_cost_m2_per_m == 0) == zero
    assert (cfg.ground_cost_m2_per_m == 0) == zero
