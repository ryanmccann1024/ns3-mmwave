"""Study-spec validation, trial construction, and the tuning driver with stubs."""

import ast
import json
import sys
from pathlib import Path

import pytest

from scripts.rl.cli_common import write_json
from scripts.rl.ops import tune
from scripts.sim_support import find_mesh_root

MATRIX = find_mesh_root() / "inputs/experiments/bypass-smoke-matrix.json"
STUDY = find_mesh_root() / "inputs/experiments/bypass-smoke-study.json"
HELD_OUT = ("301", "302", "303")


def _matrix_file(tmp_path: Path, **training) -> Path:
    body = json.loads(MATRIX.read_text())
    body["training"].update(training)
    if body["training"]["eval_every_steps"] == 0:
        body["seeds"].pop("model_selection")
        body["evaluation"]["model"] = "final"
    path = tmp_path / "matrix.json"
    write_json(path, body)
    return path


def _spec_file(tmp_path: Path, matrix: Path | None = None, **overrides) -> Path:
    body = json.loads(STUDY.read_text())
    body["matrix"] = str(matrix or MATRIX)
    body.update(overrides)
    path = tmp_path / "study.json"
    write_json(path, body)
    return path


@pytest.fixture
def stub_binary(tmp_path: Path) -> str:
    """Executable file so validation passes; the stub trainer never runs it."""
    binary = tmp_path / "mesh-sim"
    binary.write_text("#!/bin/sh\nexit 1\n")
    binary.chmod(0o755)
    return str(binary)


def _sampler(space: dict, number: int) -> dict:
    """Deterministic stand-in for the TPE sampler; no Optuna needed."""
    return {"n_steps": 32 if number % 2 else 64,
            "gamma": 0.90 + 0.01 * number,
            "ent_coef": 0.001 * (number + 1)}


class _StubTrainer:
    """Writes the train manifest a trial's objective is read from; starts no process."""

    def __init__(self, rewards=None, codes=None):
        self.rewards = rewards or {}
        self.codes = codes or {}
        self.calls: list[dict] = []

    def __call__(self, trial: dict) -> int:
        number = len(self.calls)
        self.calls.append(trial)
        code = self.codes.get(number, 0)
        out_dir = Path(trial["train_dir"])
        out_dir.mkdir(parents=True, exist_ok=True)
        if code == 0:
            write_json(out_dir / "train_manifest.json",
                       {"status": "completed",
                        "best_mean_reward": self.rewards.get(number, 1.0 + number)})
        return code


def _run(spec: Path, out: Path, binary: str, execute, sampler=_sampler,
         extra=()) -> int:
    argv = ["--study", str(spec), "--output-root", str(out),
            "--sim-binary", binary, *extra]
    return tune.main(argv, sampler=sampler, execute=execute)


REFUSALS = [
    ("unknown key", {"overrides": {"nonsense": 1}}, "unknown keys"),
    ("total_timesteps", {"overrides": {"search_space": {
        "total_timesteps": {"type": "categorical", "choices": [128, 256]}}}},
     "budget is fixed per study"),
    ("weight_decay", {"overrides": {"search_space": {
        "weight_decay": {"type": "float", "low": 1e-5, "high": 1e-3}}}},
     "not wired to MaskablePPO"),
    ("inverted range", {"overrides": {"search_space": {
        "gamma": {"type": "float", "low": 0.99, "high": 0.90}}}}, "low < high"),
    ("gamma outside the unit interval", {"overrides": {"search_space": {
        "gamma": {"type": "float", "low": 0.9, "high": 1.5}}}}, r"inside \(0, 1\]"),
    ("log needs a positive low", {"overrides": {"search_space": {
        "ent_coef": {"type": "float", "low": 0.0, "high": 0.05, "log": True}}}},
     "log requires low > 0"),
    ("tiny n_steps choice", {"overrides": {"search_space": {
        "n_steps": {"type": "categorical", "choices": [1, 64]}}}}, "integer >= 2"),
    ("seed outside seeds.training", {"overrides": {"training_seed": 999}},
     "not in seeds.training"),
    ("empty search space", {"overrides": {"search_space": {}}}, "non-empty"),
    ("no selection cadence", {"training": {"eval_every_steps": 0}},
     "seeds.model_selection"),
    ("cadence above the budget", {"training": {"eval_every_steps": 512}},
     "eval_every_steps must satisfy"),
]


@pytest.mark.parametrize("case,message", [entry[1:] for entry in REFUSALS],
                         ids=[entry[0] for entry in REFUSALS])
def test_bad_specs_are_refused_before_anything_runs(tmp_path, stub_binary, case,
                                                    message, capsys):
    matrix = _matrix_file(tmp_path, **case["training"]) if "training" in case else None
    spec = _spec_file(tmp_path, matrix, **case.get("overrides", {}))
    trainer = _StubTrainer()
    out = tmp_path / "out"

    assert _run(spec, out, stub_binary, trainer) == 1
    assert trainer.calls == []
    assert not out.exists()
    assert capsys.readouterr().err.startswith("ValueError: ")


@pytest.mark.parametrize("case,message", [entry[1:] for entry in REFUSALS],
                         ids=[entry[0] for entry in REFUSALS])
def test_refusal_messages_name_the_offending_setting(tmp_path, case, message):
    matrix = _matrix_file(tmp_path, **case["training"]) if "training" in case else None
    spec = _spec_file(tmp_path, matrix, **case.get("overrides", {}))

    with pytest.raises(ValueError, match=message):
        tune.load_study(spec)


def test_an_existing_study_directory_is_refused(tmp_path, stub_binary, capsys):
    out = tmp_path / "out"
    out.mkdir()
    write_json(out / "study_manifest.json", {"status": "completed"})
    trainer = _StubTrainer()

    assert _run(_spec_file(tmp_path), out, stub_binary, trainer) == 1
    assert trainer.calls == []
    assert "study_manifest.json" in capsys.readouterr().err


def test_a_missing_binary_is_refused_unless_the_run_is_dry(tmp_path, capsys):
    spec = _spec_file(tmp_path)
    out = tmp_path / "out"

    assert _run(spec, out, str(tmp_path / "absent"), _StubTrainer()) == 1
    assert "not an executable file" in capsys.readouterr().err
    assert _run(spec, out, str(tmp_path / "absent"), _StubTrainer(),
                extra=["--dry-run"]) == 0


def test_trial_arguments_carry_the_sampled_values_and_the_right_seeds(tmp_path):
    spec = tune.load_study(_spec_file(tmp_path))
    params = {"n_steps": 32, "gamma": 0.93, "ent_coef": 0.004}

    trial = tune.build_trial(spec, params, tmp_path / "trial-0000", "/bin/echo")
    args = trial["args"]

    assert trial["module"] == "scripts.rl.train"
    for flag, value in (("--n-steps", "32"), ("--gamma", "0.93"),
                        ("--ent-coef", "0.004"), ("--total-timesteps", "256"),
                        ("--seed", "101"), ("--eval-seed", "201")):
        assert args[args.index(flag) + 1] == value
    assert not set(HELD_OUT) & set(args)
    assert trial["train_dir"].endswith("trial-0000/train/local-delivery/train-seed-101")
    assert trial["training"]["total_timesteps"] == 256


def test_a_sampled_value_equal_to_a_held_out_seed_is_not_refused(tmp_path):
    body = json.loads(MATRIX.read_text())
    body["seeds"]["held_out"] = [64, 302, 303]
    matrix = tmp_path / "collision-matrix.json"
    write_json(matrix, body)
    spec = tune.load_study(_spec_file(tmp_path, matrix=matrix))

    trial = tune.build_trial(spec, {"n_steps": 64, "gamma": 0.93, "ent_coef": 0.004},
                             tmp_path / "trial-0000", "/bin/echo")

    args = trial["args"]
    assert args[args.index("--n-steps") + 1] == "64"
    assert args[args.index("--seed") + 1] == "101"


def test_a_held_out_seed_in_a_seed_flag_is_refused(tmp_path):
    spec = tune.load_study(_spec_file(tmp_path))
    spec["matrix"]["seeds"]["held_out"] = [101]

    with pytest.raises(ValueError, match="held-out seed"):
        tune.build_trial(spec, {"n_steps": 32, "gamma": 0.93, "ent_coef": 0.004},
                         tmp_path / "trial-0000", "/bin/echo")


def test_no_plan_file_is_written_for_a_trial(tmp_path):
    spec = tune.load_study(_spec_file(tmp_path))
    trial_dir = tmp_path / "trial-0000"

    tune.build_trial(spec, {"n_steps": 64, "gamma": 0.95, "ent_coef": 0.01},
                     trial_dir, "/bin/echo")

    assert not trial_dir.exists()


def test_a_completed_study_records_objectives_and_the_best_training_block(
        tmp_path, stub_binary):
    out = tmp_path / "out"
    trainer = _StubTrainer(rewards={0: 1.0, 1: 7.5, 2: 3.0})

    assert _run(_spec_file(tmp_path), out, stub_binary, trainer) == 0
    manifest = json.loads((out / "study_manifest.json").read_text())

    assert manifest["status"] == "completed"
    assert manifest["study_manifest_version"] == 2
    assert manifest["seed_roles"] == {"training": 101, "model_selection": 201,
                                      "held_out_used": False}
    assert manifest["sampler"]["n_startup_trials"] == tune.N_STARTUP_TRIALS
    assert [trial["objective"] for trial in manifest["trials"]] == [1.0, 7.5, 3.0]
    assert manifest["best"]["number"] == 1
    assert manifest["best"]["training"] == {
        "total_timesteps": 256, "n_steps": 32, "eval_every_steps": 128,
        "gamma": 0.91, "ent_coef": 0.002}

    trial = json.loads((out / "trials/trial-0001/trial.json").read_text())
    assert trial["trial_version"] == 2 and trial["state"] == "complete"
    assert trial["objective"] == 7.5 and trial["failure"] is None
    assert trial["params"] == {"n_steps": 32, "gamma": 0.91, "ent_coef": 0.002}


FAILURES = [("null objective", {"rewards": {1: None}}, "best_mean_reward is None"),
            ("non-zero exit", {"codes": {1: 1}}, "training exited 1")]


@pytest.mark.parametrize("kwargs,failure", [entry[1:] for entry in FAILURES],
                         ids=[entry[0] for entry in FAILURES])
def test_a_failed_trial_is_recorded_and_the_study_continues(tmp_path, stub_binary,
                                                            kwargs, failure):
    out = tmp_path / "out"
    trainer = _StubTrainer(**kwargs)

    assert _run(_spec_file(tmp_path), out, stub_binary, trainer) == 1
    assert len(trainer.calls) == 3
    manifest = json.loads((out / "study_manifest.json").read_text())

    assert manifest["status"] == "failed"
    assert [trial["state"] for trial in manifest["trials"]] == [
        "complete", "failed", "complete"]
    assert manifest["best"]["number"] == 2
    trial = json.loads((out / "trials/trial-0001/trial.json").read_text())
    assert trial["state"] == "failed" and trial["objective"] is None
    assert failure in trial["failure"]


def test_a_dry_run_prints_commands_without_creating_anything(tmp_path, capsys):
    out = tmp_path / "out"
    trainer = _StubTrainer()

    assert _run(_spec_file(tmp_path), out, "/nonexistent/mesh-sim", trainer,
                extra=["--dry-run"]) == 0
    printed = capsys.readouterr().out

    assert trainer.calls == []
    assert not out.exists()
    assert printed.count("params: ") == 3
    assert f"{sys.executable}" in printed and "scripts.rl.train" in printed
    assert not any(seed in printed for seed in HELD_OUT)


def _printed_params(printed: str) -> list[dict]:
    sets = []
    for line in printed.splitlines():
        if " params: " not in line:
            continue
        pairs = line.split(" params: ", 1)[1].split()
        sets.append({key: ast.literal_eval(value)
                     for key, value in (pair.split("=", 1) for pair in pairs)})
    return sets


def test_the_install_hint_names_the_pin_file(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "optuna", None)

    with pytest.raises(ValueError, match="requirements-tuning.txt"):
        tune.load_optuna()


def test_the_pin_file_holds_one_exact_optuna_pin(tmp_path):
    assert tune.read_tuning_pin(find_mesh_root() / tune.PIN_NAME)
    with pytest.raises(ValueError, match="optuna=="):
        tune.read_tuning_pin(_write_pin(tmp_path, "# no pin here\n"))


def _write_pin(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "requirements-tuning.txt"
    path.write_text(text)
    return path


def test_a_version_other_than_the_pin_is_refused(tmp_path):
    pytest.importorskip("optuna")
    pin = _write_pin(tmp_path, "optuna==0.0.0\n")

    with pytest.raises(ValueError, match="pins optuna==0.0.0"):
        tune.load_optuna(pin)


def test_the_seeded_sampler_matches_its_dry_run_preview(tmp_path, stub_binary, capsys):
    pytest.importorskip("optuna")
    spec = _spec_file(tmp_path)
    out = tmp_path / "out"

    assert _run(spec, out, stub_binary, _StubTrainer(), sampler=None,
                extra=["--dry-run"]) == 0
    previewed = _printed_params(capsys.readouterr().out)

    assert _run(spec, out, stub_binary, _StubTrainer(), sampler=None) == 0
    executed = [json.loads((out / f"trials/trial-000{number}/trial.json").read_text())
                ["params"] for number in range(3)]

    assert len(previewed) == 3
    assert previewed == executed


def test_two_runs_with_the_same_sampler_seed_agree(tmp_path, stub_binary):
    pytest.importorskip("optuna")
    spec = _spec_file(tmp_path)
    runs = []
    for name in ("first", "second"):
        out = tmp_path / name
        assert _run(spec, out, stub_binary, _StubTrainer(), sampler=None) == 0
        runs.append([trial["params"] for trial in
                     json.loads((out / "study_manifest.json").read_text())["trials"]])

    assert runs[0] == runs[1]
    assert json.loads((tmp_path / "first/study_manifest.json").read_text())[
        "optuna_version"] == tune.read_tuning_pin(find_mesh_root() / tune.PIN_NAME)


def test_configured_sampler_settings_and_trial_budget(tmp_path):
    spec = tune.load_study(_spec_file(tmp_path, n_trials=75, trainer="maskable_ppo",
                                    sampler={"type": "tpe", "seed": 7,
                                             "n_startup_trials": 3,
                                             "n_ei_candidates": 12, "multivariate": True}))
    assert spec["n_trials"] == 75
    assert spec["sampler"]["n_startup_trials"] == 3
    assert spec["sampler"]["n_ei_candidates"] == 12
    assert spec["sampler"]["multivariate"] is True


@pytest.mark.parametrize("overrides", [
    {"trainer": "unimplemented"},
    {"sampler": {"type": "tpe", "seed": -1}},
    {"sampler": {"type": "tpe", "seed": 7, "n_startup_trials": 0}},
    {"sampler": {"type": "tpe", "seed": 7, "n_ei_candidates": 0}},
    {"sampler": {"type": "tpe", "seed": 7, "multivariate": "true"}},

])
def test_invalid_adapter_or_sampler_settings_fail_before_outputs(tmp_path, stub_binary, overrides):
    out = tmp_path / "out"
    assert _run(_spec_file(tmp_path, **overrides), out, stub_binary, _StubTrainer()) == 1
    assert not out.exists()


def test_running_trial_is_recorded_before_execution_and_resume_retains_it(tmp_path, stub_binary):
    spec = _spec_file(tmp_path)
    out = tmp_path / "out"
    completed = _StubTrainer()
    calls = []

    def interrupt(trial):
        record = json.loads((out / f"trials/trial-{len(calls):04d}/trial.json").read_text())
        assert record["state"] == "running" and record["params"]
        calls.append(trial)
        if len(calls) == 2:
            raise KeyboardInterrupt("interrupted")
        return completed(trial)

    with pytest.raises(KeyboardInterrupt):
        _run(spec, out, stub_binary, interrupt)
    before = (out / "trials/trial-0000/trial.json").read_bytes()
    resumed = _StubTrainer()
    assert _run(spec, out, stub_binary, resumed, extra=["--resume"]) == 1
    manifest = json.loads((out / "study_manifest.json").read_text())
    assert len(resumed.calls) == 1
    assert (out / "trials/trial-0000/trial.json").read_bytes() == before
    assert [r["state"] for r in manifest["trials"]] == ["complete", "failed", "complete"]
    assert "not restarted" in manifest["trials"][1]["failure"]
    assert manifest["resume_events"]


def test_resume_recovers_finished_training_without_reexecuting_it(tmp_path, stub_binary):
    spec = _spec_file(tmp_path)
    out = tmp_path / "out"
    trainer = _StubTrainer()

    def completed_then_interrupted(trial):
        trainer(trial)
        raise KeyboardInterrupt("crash before recording objective")

    with pytest.raises(KeyboardInterrupt):
        _run(spec, out, stub_binary, completed_then_interrupted)
    resumed = _StubTrainer()
    assert _run(spec, out, stub_binary, resumed, extra=["--resume"]) == 0
    assert len(resumed.calls) == 2
    records = json.loads((out / "study_manifest.json").read_text())["trials"]
    assert records[0]["state"] == "complete"
    assert records[0]["objective"] == 1.0


def test_completed_resume_launches_nothing_and_changed_spec_is_refused(tmp_path, stub_binary):
    spec = _spec_file(tmp_path)
    out = tmp_path / "out"
    assert _run(spec, out, stub_binary, _StubTrainer()) == 0
    trainer = _StubTrainer()
    assert _run(spec, out, stub_binary, trainer, extra=["--resume"]) == 0
    assert trainer.calls == []
    body = json.loads(spec.read_text())
    body["sampler"]["seed"] = 8
    write_json(spec, body)
    assert _run(spec, out, stub_binary, trainer, extra=["--resume"]) == 1
    assert trainer.calls == []


def test_resume_refuses_a_corrupt_checkpoint(tmp_path, stub_binary):
    spec = _spec_file(tmp_path)
    out = tmp_path / "out"
    assert _run(spec, out, stub_binary, _StubTrainer()) == 0
    checkpoint = out / "study-checkpoint.bin"
    checkpoint.write_bytes(checkpoint.read_bytes()[:-5])
    trainer = _StubTrainer()
    assert _run(spec, out, stub_binary, trainer, extra=["--resume"]) == 1
    assert trainer.calls == []


def test_adaptive_search_and_resume_preserve_seeded_continuation(tmp_path, stub_binary, monkeypatch):
    optuna = pytest.importorskip("optuna")
    spec = _spec_file(tmp_path, n_trials=8,
                      sampler={"type": "tpe", "seed": 7, "n_startup_trials": 3})
    adaptive = []
    original = optuna.samplers.TPESampler._sample

    def sample(self, study, trial, *args, **kwargs):
        adaptive.append(trial.number)
        return original(self, study, trial, *args, **kwargs)

    monkeypatch.setattr(optuna.samplers.TPESampler, "_sample", sample)

    def objective(trial):
        gamma = trial["training"]["gamma"]
        Path(trial["train_dir"]).mkdir(parents=True, exist_ok=True)
        write_json(Path(trial["train_dir"]) / "train_manifest.json",
                   {"status": "completed", "best_mean_reward": -(gamma - 0.945)**2})
        return 0

    uninterrupted = tmp_path / "uninterrupted"
    assert _run(spec, uninterrupted, stub_binary, objective, sampler=None) == 0
    assert adaptive and min(adaptive) >= 3
    interrupted = tmp_path / "interrupted"
    calls = 0

    def crash(trial):
        nonlocal calls
        calls += 1
        code = objective(trial)
        if calls == 5:
            raise KeyboardInterrupt("after adaptive trial completed")
        return code

    with pytest.raises(KeyboardInterrupt):
        _run(spec, interrupted, stub_binary, crash, sampler=None)
    assert _run(spec, interrupted, stub_binary, objective, sampler=None, extra=["--resume"]) == 0
    first = json.loads((uninterrupted / "study_manifest.json").read_text())
    second = json.loads((interrupted / "study_manifest.json").read_text())
    assert [(r["params"], r["objective"]) for r in first["trials"]] == [
        (r["params"], r["objective"]) for r in second["trials"]]
    assert first["best"] == second["best"]


def test_checkpoint_survives_failure_to_refresh_json_mirror(tmp_path, stub_binary, monkeypatch):
    from scripts.rl.tuning import artifacts
    spec = _spec_file(tmp_path)
    out = tmp_path / "out"
    original = artifacts.write_json

    def fail(path, payload):
        if Path(path).name == "study_manifest.json":
            raise OSError("mirror storage failure")
        return original(path, payload)

    monkeypatch.setattr(artifacts, "write_json", fail)
    assert _run(spec, out, stub_binary, _StubTrainer()) == 1
    assert (out / "study-checkpoint.bin").is_file()
    monkeypatch.setattr(artifacts, "write_json", original)
    assert _run(spec, out, stub_binary, _StubTrainer(), extra=["--resume"]) == 0


def test_nonfinite_search_range_is_refused(tmp_path, stub_binary):
    spec = _spec_file(tmp_path)
    body = json.loads(spec.read_text())
    body["search_space"]["ent_coef"]["high"] = float("inf")
    spec.write_text(json.dumps(body))
    out = tmp_path / "out"
    assert _run(spec, out, stub_binary, _StubTrainer()) == 1
    assert not out.exists()


def test_concurrent_writer_is_refused(tmp_path, stub_binary):
    from scripts.rl.tuning.artifacts import study_lock
    out = tmp_path / "out"
    trainer = _StubTrainer()
    with study_lock(out):
        assert _run(_spec_file(tmp_path), out, stub_binary, trainer) == 1
    assert trainer.calls == []
    assert not (out / "study-checkpoint.bin").exists()


def test_build_failure_records_and_closes_the_asked_trial(tmp_path, stub_binary, monkeypatch):
    from scripts.rl.tuning import driver
    optuna = pytest.importorskip("optuna")
    spec = _spec_file(tmp_path)
    out = tmp_path / "out"
    original = driver.build_trial
    calls = 0

    def build(*args):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ValueError("trial command preparation failed")
        return original(*args)

    monkeypatch.setattr(driver, "build_trial", build)
    assert _run(spec, out, stub_binary, _StubTrainer(), sampler=None) == 1
    from scripts.rl.tuning.artifacts import identity, restore
    state = restore(out, identity(tune.load_study(spec), stub_binary), optuna.__version__)
    assert [r.number for r in state["study"]._study.trials] == [0, 1, 2]
    assert state["study"]._study.trials[0].state == optuna.trial.TrialState.FAIL
    assert state["manifest"]["trials"][0]["state"] == "failed"
    assert "preparation failed" in state["manifest"]["trials"][0]["failure"]


@pytest.mark.parametrize("operation", ["ask", "tell"])
def test_interrupted_sampler_mutation_is_not_committed_without_its_record(
        tmp_path, stub_binary, monkeypatch, operation):
    pytest.importorskip("optuna")
    from scripts.rl.tuning.study import _OptunaStudy
    spec = _spec_file(tmp_path)
    original = getattr(_OptunaStudy, operation)
    interrupted_once = False

    def interrupt(self, *args):
        nonlocal interrupted_once
        result = original(self, *args)
        if not interrupted_once:
            interrupted_once = True
            raise KeyboardInterrupt(f"inside {operation}")
        return result

    out = tmp_path / "interrupted"
    with monkeypatch.context() as patch:
        patch.setattr(_OptunaStudy, operation, interrupt)
        with pytest.raises(KeyboardInterrupt):
            _run(spec, out, stub_binary, _StubTrainer(), sampler=None)

    assert _run(spec, out, stub_binary, _StubTrainer(), sampler=None, extra=["--resume"]) == 0
    uninterrupted = tmp_path / "uninterrupted"
    assert _run(spec, uninterrupted, stub_binary, _StubTrainer(), sampler=None) == 0
    resumed = json.loads((out / "study_manifest.json").read_text())["trials"]
    reference = json.loads((uninterrupted / "study_manifest.json").read_text())["trials"]
    assert [r["params"] for r in resumed] == [r["params"] for r in reference]
    assert [r["number"] for r in resumed] == [0, 1, 2]
    assert all(r["state"] == "complete" for r in resumed)
