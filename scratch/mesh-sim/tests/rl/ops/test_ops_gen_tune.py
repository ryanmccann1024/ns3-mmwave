"""Tuning smoke paths that need no Optuna: pin checks, spec validation, seed roles.

Optuna is not installed here and must not be; a plain callable sampler is
injected through tune.main(sampler=...). Expectations come from
scripts/rl/ops/README.md "Tuning smoke".
"""

import json
import shlex
import sys
import types
from pathlib import Path

import pytest

from scripts.rl.cli_common import write_json
from scripts.rl.ops import tune
from scripts.sim_support import find_mesh_root

MATRIX = find_mesh_root() / "inputs/experiments/bypass-smoke-matrix.json"
STUDY = find_mesh_root() / "inputs/experiments/bypass-smoke-study.json"
HELD_OUT = {"301", "302", "303"}


def _spec(tmp_path: Path, matrix=None, **overrides) -> Path:
    body = json.loads(STUDY.read_text())
    body["matrix"] = str(matrix or MATRIX)
    body.update(overrides)
    path = tmp_path / "study.json"
    write_json(path, body)
    return path


def _space(**entries) -> dict:
    space = json.loads(STUDY.read_text())["search_space"]
    space.update(entries)
    return space


def _sampler(space, number):
    return {"n_steps": 64, "gamma": 0.95, "ent_coef": 0.01}


@pytest.fixture
def binary(tmp_path):
    path = tmp_path / "mesh-sim"
    path.write_text("#!/bin/sh\nexit 1\n")
    path.chmod(0o755)
    return str(path)


# --- Optuna pin ----------------------------------------------------------------


def test_gen_the_default_sampler_without_optuna_refuses_and_creates_nothing(
        tmp_path, binary, monkeypatch, capsys):
    monkeypatch.setitem(sys.modules, "optuna", None)
    out = tmp_path / "out"
    for extra in ([], ["--dry-run"]):
        assert tune.main(["--study", str(_spec(tmp_path)), "--output-root", str(out),
                          "--sim-binary", binary, *extra]) == 1
        err = capsys.readouterr().err
        assert "optuna is not installed" in err and tune.PIN_NAME in err
    assert not out.exists()


def test_gen_a_version_other_than_the_pin_names_both_versions(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "optuna",
                        types.SimpleNamespace(__version__="0.0.1"))
    pin = tmp_path / tune.PIN_NAME
    pin.write_text("optuna==9.9.9\n")
    with pytest.raises(ValueError) as caught:
        tune.load_optuna(pin)
    message = str(caught.value)
    assert "0.0.1" in message and "optuna==9.9.9" in message
    assert "pip install -r" in message


def test_gen_the_pinned_version_is_accepted_and_returned(tmp_path, monkeypatch):
    fake = types.SimpleNamespace(__version__="9.9.9")
    monkeypatch.setitem(sys.modules, "optuna", fake)
    pin = tmp_path / tune.PIN_NAME
    pin.write_text("# tuning only\noptuna==9.9.9  # tested\n")
    assert tune.load_optuna(pin) is fake


@pytest.mark.parametrize("text", ["optuna>=5.0\n", "optuna==\n", "optuna\n",
                                  "optuna-dashboard==1.0\n", "# optuna==5.0.0\n", ""])
def test_gen_only_an_exact_optuna_pin_is_accepted(tmp_path, text):
    pin = tmp_path / "pins.txt"
    pin.write_text(text)
    with pytest.raises(ValueError, match="optuna=="):
        tune.read_tuning_pin(pin)


def test_gen_the_tracked_pin_file_is_exact():
    version = tune.read_tuning_pin(find_mesh_root() / tune.PIN_NAME)
    assert version and all(part.isdigit() for part in version.split("."))


# --- study spec validation -----------------------------------------------------


REFUSALS = [
    ("zero trials", {"n_trials": 0}, "between 1 and 50"),
    ("51 trials", {"n_trials": 51}, "between 1 and 50"),
    ("boolean trials", {"n_trials": True}, "n_trials must be an integer"),
    ("random sampler", {"sampler": {"type": "random", "seed": 7}}, "must be 'tpe'"),
    ("string sampler seed", {"sampler": {"type": "tpe", "seed": "7"}},
     "sampler.seed must be an integer"),
    ("extra sampler key", {"sampler": {"type": "tpe", "seed": 7, "startup": 3}},
     "unknown keys"),
    ("extra entry key",
     {"search_space": _space(gamma={"type": "float", "low": 0.9, "high": 0.99,
                                    "step": 0.01})}, "unknown keys"),
    ("range keys on a categorical",
     {"search_space": _space(n_steps={"type": "categorical", "choices": [32],
                                      "low": 2})}, "unknown keys"),
    ("float n_steps", {"search_space": _space(n_steps={"type": "float", "low": 2.0,
                                                       "high": 8.0})},
     "type must be one of"),
    ("int n_steps below 2", {"search_space": _space(n_steps={"type": "int", "low": 1,
                                                             "high": 8})}, ">= 2"),
    ("non-integer choice", {"search_space": _space(n_steps={"type": "categorical",
                                                            "choices": [32.0, 64]})},
     "must be an integer"),
    ("duplicate choices", {"search_space": _space(n_steps={"type": "categorical",
                                                           "choices": [64, 64]})},
     "distinct"),
    ("empty choices", {"search_space": _space(n_steps={"type": "categorical",
                                                       "choices": []})}, "non-empty"),
    ("gamma low 0", {"search_space": _space(gamma={"type": "float", "low": 0.0,
                                                   "high": 0.5})}, r"inside \(0, 1\]"),
    ("negative ent_coef", {"search_space": _space(ent_coef={"type": "float",
                                                            "low": -0.1,
                                                            "high": 0.1})}, ">= 0"),
    ("non-boolean log", {"search_space": _space(gamma={"type": "float", "low": 0.9,
                                                       "high": 0.99, "log": "yes"})},
     "true or false"),
    ("equal bounds", {"search_space": _space(gamma={"type": "float", "low": 0.9,
                                                    "high": 0.9})}, "low < high"),
    ("study version 2", {"study_version": 2}, "study_version must be 1"),
    ("empty name", {"name": ""}, "non-empty string"),
    ("non-string description", {"description": 5}, "description must be a string"),
    ("unknown row", {"row": "nope"}, "is not in"),
    ("held-out seed as the training seed", {"training_seed": 301},
     "not in seeds.training"),
    ("model-selection seed as the training seed", {"training_seed": 201},
     "not in seeds.training"),
    ("boolean training seed", {"training_seed": True}, "must be an integer"),
    ("matrix not a path", {"matrix": 5}, "path to a matrix"),
]


@pytest.mark.parametrize("overrides,message", [case[1:] for case in REFUSALS],
                         ids=[case[0] for case in REFUSALS])
def test_gen_spec_refusals(tmp_path, overrides, message):
    path = _spec(tmp_path)
    body = json.loads(path.read_text())
    body.update(overrides)
    write_json(path, body)
    with pytest.raises(ValueError, match=message):
        tune.load_study(path)


ACCEPTED = [
    ("50 trials", {"n_trials": 50}),
    ("gamma up to exactly 1", {"search_space": _space(gamma={"type": "float",
                                                             "low": 0.9,
                                                             "high": 1.0})}),
    ("ent_coef from 0 without log", {"search_space": _space(ent_coef={
        "type": "float", "low": 0.0, "high": 0.05})}),
    ("int n_steps range", {"search_space": {"n_steps": {"type": "int", "low": 2,
                                                        "high": 128, "log": True}}}),
    ("only gamma", {"search_space": {"gamma": {"type": "float", "low": 0.9,
                                               "high": 0.99}}}),
    ("no description", {"description": ""}),
]


@pytest.mark.parametrize("overrides", [case[1] for case in ACCEPTED],
                         ids=[case[0] for case in ACCEPTED])
def test_gen_documented_edges_are_accepted(tmp_path, overrides):
    path = _spec(tmp_path)
    body = json.loads(path.read_text())
    body.update(overrides)
    write_json(path, body)
    spec = tune.load_study(path)
    assert spec["search_space"]


def test_gen_a_relative_matrix_resolves_against_the_mesh_root(tmp_path, monkeypatch):
    elsewhere = tmp_path / "deep" / "dir"
    elsewhere.mkdir(parents=True)
    monkeypatch.chdir(elsewhere)
    spec = tune.load_study(_spec(elsewhere,
                                 matrix="inputs/experiments/bypass-smoke-matrix.json"))
    assert Path(spec["matrix"]["path"]).resolve() == MATRIX.resolve()


def test_gen_a_cadence_equal_to_the_budget_is_allowed(tmp_path):
    body = json.loads(MATRIX.read_text())
    body["training"]["eval_every_steps"] = body["training"]["total_timesteps"]
    matrix = tmp_path / "matrix.json"
    write_json(matrix, body)
    assert tune.load_study(_spec(tmp_path, matrix=matrix))["n_trials"] == 3


# --- output root, binary, dry run --------------------------------------------


@pytest.mark.parametrize("existing", ["trials", tune.STUDY_MANIFEST_NAME])
def test_gen_an_earlier_study_in_the_root_is_refused(tmp_path, binary, existing,
                                                     capsys):
    out = tmp_path / "out"
    out.mkdir()
    (out / existing).mkdir() if existing == "trials" else (out / existing).write_text("{}")
    assert tune.main(["--study", str(_spec(tmp_path)), "--output-root", str(out),
                      "--sim-binary", binary], sampler=_sampler,
                     execute=lambda trial: 0) == 1
    assert "studies are not resumed" in capsys.readouterr().err


def test_gen_an_existing_empty_root_is_fine(tmp_path, binary):
    out = tmp_path / "out"
    out.mkdir()
    calls = []

    def execute(trial):
        calls.append(trial)
        Path(trial["train_dir"]).mkdir(parents=True)
        write_json(Path(trial["train_dir"]) / "train_manifest.json",
                   {"best_mean_reward": 1.0})
        return 0

    assert tune.main(["--study", str(_spec(tmp_path)), "--output-root", str(out),
                      "--sim-binary", binary], sampler=_sampler, execute=execute) == 0
    assert len(calls) == 3


def test_gen_a_non_executable_binary_is_refused(tmp_path, capsys):
    path = tmp_path / "mesh-sim"
    path.write_text("not executable")
    path.chmod(0o644)
    assert tune.main(["--study", str(_spec(tmp_path)), "--output-root",
                      str(tmp_path / "out"), "--sim-binary", str(path)],
                     sampler=_sampler, execute=lambda trial: 0) == 1
    assert "not an executable file" in capsys.readouterr().err
    assert not (tmp_path / "out").exists()


def _dry(tmp_path, capsys, n_trials, sampler=None):
    out = tmp_path / "out"
    sampled = []

    def recording(space, number):
        sampled.append(number)
        return {"n_steps": 32 + 32 * (number % 2), "gamma": 0.9 + number / 1000,
                "ent_coef": 0.001 * (number + 1)}

    assert tune.main(["--study", str(_spec(tmp_path, n_trials=n_trials)),
                      "--output-root", str(out), "--sim-binary", "/no/such/binary",
                      "--dry-run"], sampler=sampler or recording,
                     execute=lambda trial: pytest.fail("dry run executed a trial")) == 0
    assert not out.exists()
    return sampled, capsys.readouterr().out


def test_gen_a_large_dry_run_previews_only_the_startup_trials(tmp_path, capsys):
    sampled, out = _dry(tmp_path, capsys, 12)
    assert sampled == list(range(10))
    assert out.count(" params: ") == 10 and out.count(" command: ") == 10
    assert "the remaining 2 trials depend on earlier objectives" in out


def test_gen_a_small_dry_run_previews_every_trial(tmp_path, capsys):
    sampled, out = _dry(tmp_path, capsys, 3)
    assert sampled == [0, 1, 2] and "remaining" not in out


def test_gen_no_previewed_command_names_a_held_out_seed(tmp_path, capsys):
    _, out = _dry(tmp_path, capsys, 10)
    commands = [shlex.split(line.split(" command: ", 1)[1])
                for line in out.splitlines() if " command: " in line]
    assert len(commands) == 10
    for argv in commands:
        seeds = {argv[i + 1] for i, token in enumerate(argv)
                 if token in ("--seed", "--eval-seed")}
        assert seeds == {"101", "201"}
        assert not HELD_OUT & set(argv)


# --- objectives ----------------------------------------------------------------


@pytest.mark.parametrize("text,objective,failure", [
    ('{"best_mean_reward": 3}', 3.0, None),
    ('{"best_mean_reward": -1.5}', -1.5, None),
    ('{"best_mean_reward": NaN}', None, "nan"),
    ('{"best_mean_reward": Infinity}', None, "inf"),
    ('{"best_mean_reward": true}', None, "True"),
    ('{"best_mean_reward": "4.0"}', None, "'4.0'"),
    ('{}', None, "None"),
    ("{broken", None, "unreadable"),
    (None, None, "unreadable"),
])
def test_gen_the_objective_is_a_finite_number_or_a_recorded_failure(tmp_path, text,
                                                                    objective, failure):
    if text is not None:
        (tmp_path / "train_manifest.json").write_text(text)
    value, reason = tune._objective(tmp_path)
    assert value == objective
    if failure is None:
        assert reason is None and isinstance(value, float)
    else:
        assert failure in reason


def test_gen_a_nan_objective_fails_the_trial_but_not_the_study(tmp_path, binary):
    out = tmp_path / "out"
    rewards = iter(["NaN", "2.0", "2.0"])

    def execute(trial):
        Path(trial["train_dir"]).mkdir(parents=True)
        (Path(trial["train_dir"]) / "train_manifest.json").write_text(
            '{"best_mean_reward": %s}' % next(rewards))
        return 0

    assert tune.main(["--study", str(_spec(tmp_path)), "--output-root", str(out),
                      "--sim-binary", binary], sampler=_sampler, execute=execute) == 1
    manifest = json.loads((out / tune.STUDY_MANIFEST_NAME).read_text())
    assert manifest["status"] == "failed"
    assert [trial["state"] for trial in manifest["trials"]] \
        == ["failed", "complete", "complete"]
    assert manifest["best"]["number"] == 1
    assert manifest["fixed_training"] == {"total_timesteps": 256,
                                          "eval_every_steps": 128}
    assert manifest["optuna_version"] is None
    assert manifest["seed_roles"]["held_out_used"] is False
