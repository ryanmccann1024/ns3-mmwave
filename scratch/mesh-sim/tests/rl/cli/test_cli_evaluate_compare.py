"""Gap tests for the scripts/rl/evaluate.py and scripts/rl/compare.py CLIs.

Sources: scripts/rl/README.md (evaluate flag + exit tables: 0 clean, 2 counters,
1 error/incomplete; compare flags: exactly one of --eval-dirs/--plan, --output-dir
must not contain a training or evaluation manifest, --baselines default "every
non-model policy"), scripts/rl/CLAUDE.md (exit 2 = warning). Placement policies
(geometric/optimization) are out of scope here. Simulator = fake_sim.py.
"""

import json
from pathlib import Path

import pytest

from scripts.rl import compare as compare_cli
from scripts.rl import evaluate as evaluate_cli
from scripts.rl.tests.test_policy_comparison import SEEDS, write_eval


def _eval_argv(sim_binary, run_config, out_dir, *extra) -> list[str]:
    argv = ["--sim-binary", sim_binary, "--run-config", run_config,
            "--seeds", "1", "--policies", "hold"]
    if out_dir is not None:
        argv += ["--output-dir", str(out_dir)]
    return argv + list(extra)


# 1. evaluate argument errors --------------------------------------------------------

@pytest.mark.parametrize("flag,value", [
    ("--observation-preset", "local_links_v1"),
    ("--reward-components", "delivery_ratio"),
    ("--reward-weights", "1.0"),
    ("--telemetry", "steps"),
    ("--telemetry-every", "2"),
])
def test_selection_flags_are_refused_with_run_dir(sim_binary, multi_run_config, tmp_path,
                                                  capsys, flag, value):
    run_dir = tmp_path / "train"
    run_dir.mkdir()
    out_dir = tmp_path / "eval"
    argv = _eval_argv(sim_binary, multi_run_config, out_dir,
                      "--run-dir", str(run_dir), flag, value)
    assert evaluate_cli.main(argv) == 1
    assert "not allowed with --run-dir" in capsys.readouterr().err
    assert not out_dir.exists()


def test_run_config_is_required_without_run_dir(sim_binary, tmp_path, capsys):
    out_dir = tmp_path / "eval"
    argv = ["--sim-binary", sim_binary, "--seeds", "1", "--policies", "hold",
            "--output-dir", str(out_dir)]
    assert evaluate_cli.main(argv) == 1
    assert "--run-config is required without --run-dir" in capsys.readouterr().err
    assert not out_dir.exists()


@pytest.mark.parametrize("policies,message", [
    ("", "at least one policy"),
    (" , ", "at least one policy"),
    ("hold,hold", "distinct"),
    ("hold,Hold", "unknown entries"),
])
def test_policy_list_refusals(sim_binary, multi_run_config, tmp_path, capsys, policies,
                              message):
    argv = _eval_argv(sim_binary, multi_run_config, tmp_path / "eval")
    argv[argv.index("--policies") + 1] = policies
    assert evaluate_cli.main(argv) == 1
    assert message in capsys.readouterr().err


@pytest.mark.parametrize("seeds", ["-1", "1,,x", "2-1", "1,1-2"])
def test_seed_list_refusals_write_nothing(sim_binary, multi_run_config, tmp_path, seeds):
    out_dir = tmp_path / "eval"
    argv = _eval_argv(sim_binary, multi_run_config, out_dir)
    argv[argv.index("--seeds") + 1] = seeds
    assert evaluate_cli.main(argv) == 1
    assert not out_dir.exists()


def test_output_dir_equal_to_run_dir_is_refused(sim_binary, multi_run_config, tmp_path,
                                                capsys):
    run_dir = tmp_path / "train"
    run_dir.mkdir()
    argv = _eval_argv(sim_binary, multi_run_config, run_dir, "--run-dir", str(run_dir))
    assert evaluate_cli.main(argv) == 1
    assert "inside the training run" in capsys.readouterr().err
    assert list(run_dir.iterdir()) == []


def test_existing_eval_manifest_is_not_overwritten(sim_binary, multi_run_config,
                                                   tmp_path, capsys):
    out_dir = tmp_path / "eval"
    out_dir.mkdir()
    (out_dir / "eval_manifest.json").write_text('{"previous": true}')
    assert evaluate_cli.main(_eval_argv(sim_binary, multi_run_config, out_dir)) == 1
    assert "already contains eval_manifest.json" in capsys.readouterr().err
    assert json.loads((out_dir / "eval_manifest.json").read_text()) == {"previous": True}


def test_missing_run_dir_is_an_error(sim_binary, tmp_path, capsys):
    out_dir = tmp_path / "eval"
    argv = ["--sim-binary", sim_binary, "--run-dir", str(tmp_path / "no-such-run"),
            "--seeds", "1", "--policies", "model,hold", "--output-dir", str(out_dir)]
    assert evaluate_cli.main(argv) == 1
    assert capsys.readouterr().err.strip()
    assert not (out_dir / "eval_manifest.json").exists()


def test_seeds_are_required(sim_binary, multi_run_config, tmp_path):
    with pytest.raises(SystemExit):
        evaluate_cli.main(["--sim-binary", sim_binary, "--run-config", multi_run_config,
                           "--output-dir", str(tmp_path / "eval")])


# 2. evaluate automatic output root and policy whitespace --------------------------

def test_automatic_output_root_is_announced_and_used(sim_binary, multi_run_config,
                                                     tmp_path, monkeypatch, capsys):
    auto = tmp_path / "auto-root"
    calls = []

    def fake_root(name):
        calls.append(name)
        return auto

    monkeypatch.setattr(evaluate_cli, "automatic_output_root", fake_root)
    argv = _eval_argv(sim_binary, multi_run_config, None)
    argv[argv.index("--policies") + 1] = " hold , random_valid "
    assert evaluate_cli.main(argv) == 0
    out = capsys.readouterr().out
    assert calls == ["rl-evaluation"]
    assert f"Evaluation output: {auto.resolve()}" in out
    manifest = json.loads((auto / "eval_manifest.json").read_text())
    assert set(manifest["policies"]) == {"hold", "random_valid"}
    assert manifest["status"] == "completed"


def test_automatic_output_root_is_not_announced_on_bad_input(sim_binary, multi_run_config,
                                                             tmp_path, monkeypatch,
                                                             capsys):
    auto = tmp_path / "auto-root"
    monkeypatch.setattr(evaluate_cli, "automatic_output_root", lambda name: auto)
    argv = _eval_argv(sim_binary, multi_run_config, None)
    argv[argv.index("--seeds") + 1] = "x"
    assert evaluate_cli.main(argv) == 1
    assert "Evaluation output" not in capsys.readouterr().out
    assert not auto.exists()


# 3. evaluate exit-code helper ------------------------------------------------------

def _episode(status="completed", revalidated=0, violations=0):
    return {"status": status, "revalidated_slots_total": revalidated,
            "mask_violations": violations}


@pytest.mark.parametrize("episodes,expected,code", [
    ([_episode(), _episode()], 2, 0),
    ([_episode(revalidated=None, violations=None), _episode()], 2, 0),
    ([_episode(revalidated=1), _episode()], 2, 2),
    ([_episode(violations=3), _episode()], 2, 2),
    ([_episode(), _episode(status="failed")], 2, 1),
    ([_episode(status="not_run", revalidated=4)], 1, 1),     # failure beats warning
    ([_episode()], 2, 1),                                    # a missing record
    ([_episode(), _episode(), _episode()], 2, 1),            # an unexpected record
])
def test_exit_code_rules(episodes, expected, code, capsys):
    manifest = {"policies": {"hold": {"episodes": episodes}}}
    assert evaluate_cli._exit_code(manifest, expected) == code
    if code == 1:
        assert "Not every evaluation episode completed" in capsys.readouterr().err


# 4. compare argument and input errors ----------------------------------------------

def test_compare_requires_exactly_one_source(tmp_path):
    eval_dir = write_eval(tmp_path / "eval", {s: 0.8 for s in SEEDS})
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps({"evaluations": [{"eval_dir": eval_dir}]}))
    with pytest.raises(SystemExit):
        compare_cli.main(["--output-dir", str(tmp_path / "cmp")])
    with pytest.raises(SystemExit):
        compare_cli.main(["--eval-dirs", eval_dir, "--plan", str(plan),
                          "--output-dir", str(tmp_path / "cmp")])
    with pytest.raises(SystemExit):
        compare_cli.main(["--eval-dirs", eval_dir])
    assert not (tmp_path / "cmp").exists()


@pytest.mark.parametrize("content", [
    None,                                         # file missing
    "{not json",
    "[1, 2]",
    '{"evaluations": []}',
    '{"evaluations": "x"}',
    '{"steps": []}',
    '{"evaluations": [{"label": "a"}]}',          # entry without eval_dir
])
def test_compare_refuses_a_bad_plan_and_writes_nothing(tmp_path, capsys, content):
    plan = tmp_path / "experiment_plan.json"
    if content is not None:
        plan.write_text(content)
    out = tmp_path / "cmp"
    assert compare_cli.main(["--plan", str(plan), "--output-dir", str(out)]) == 1
    assert capsys.readouterr().err.strip()
    assert not out.exists()


@pytest.mark.parametrize("baselines,message", [
    (",,", "at least one policy"),
    ("hold,hold", "distinct"),
])
def test_compare_refuses_bad_baselines(tmp_path, capsys, baselines, message):
    eval_dir = write_eval(tmp_path / "eval", {s: 0.8 for s in SEEDS})
    out = tmp_path / "cmp"
    assert compare_cli.main(["--eval-dirs", eval_dir, "--output-dir", str(out),
                             "--baselines", baselines]) == 1
    assert message in capsys.readouterr().err
    assert not out.exists()


def test_compare_refuses_an_output_dir_holding_a_training_manifest(tmp_path, capsys):
    eval_dir = write_eval(tmp_path / "eval", {s: 0.8 for s in SEEDS})
    out = tmp_path / "train-run"
    out.mkdir()
    (out / "train_manifest.json").write_text("{}")
    assert compare_cli.main(["--eval-dirs", eval_dir, "--output-dir", str(out)]) == 1
    assert "train_manifest.json" in capsys.readouterr().err
    assert sorted(p.name for p in out.iterdir()) == ["train_manifest.json"]


def test_compare_absent_baseline_is_incomplete_not_zero(tmp_path, capsys):
    eval_dir = write_eval(tmp_path / "eval", {s: 0.8 for s in SEEDS})
    out = tmp_path / "cmp"
    assert compare_cli.main(["--eval-dirs", eval_dir, "--output-dir", str(out),
                             "--baselines", "random_valid"]) == 1
    payload = json.loads((out / "comparison.json").read_text())
    assert payload["status"] == "incomplete"
    primary = [c for c in payload["evaluations"][0]["comparisons"]
               if c["metric"] == payload["primary_metric"]]
    assert primary and all(c["mean_difference"] is None for c in primary)
    assert "no usable evaluation seeds" in capsys.readouterr().out


def test_compare_seed_overlap_exits_two(tmp_path):
    eval_dir = write_eval(tmp_path / "eval", {s: 0.8 for s in SEEDS}, held_out=False)
    out = tmp_path / "cmp"
    assert compare_cli.main(["--eval-dirs", eval_dir, "--output-dir", str(out)]) == 2
    assert (out / "comparison.json").is_file()


def test_compare_writes_no_tmp_files(tmp_path):
    eval_dir = write_eval(tmp_path / "eval", {s: 0.8 for s in SEEDS})
    out = tmp_path / "cmp"
    assert compare_cli.main(["--eval-dirs", eval_dir, "--output-dir", str(out)]) == 0
    assert sorted(p.name for p in out.iterdir()) == ["comparison.json", "episodes.csv"]
    header = (out / "episodes.csv").read_text().splitlines()[0]
    assert header.split(",")[0]


# QUESTION: compare.py:59-67 (_parse_baselines) accepts "model" as a baseline, so
# `--baselines model` compares the model against itself (difference 0, status
# "complete", exit 0). README: "default is every non-model policy present";
# a model-vs-model comparison is meaningless and probably should be refused.
def test_compare_refuses_model_as_a_baseline(tmp_path):
    eval_dir = write_eval(tmp_path / "eval", {s: 0.8 for s in SEEDS})
    out = tmp_path / "cmp"
    assert compare_cli.main(["--eval-dirs", eval_dir, "--output-dir", str(out),
                             "--baselines", "model"]) == 1


def test_cell_and_prefix_formatting():
    assert compare_cli._cell(None) == ""
    assert compare_cli._cell(True) == "true" and compare_cli._cell(False) == "false"
    assert compare_cli._cell(0) == "0" and compare_cli._cell(0.5) == "0.5"
    assert compare_cli._prefix(None, None, "/x/eval-a") == "(unlabeled) eval-a"
    assert compare_cli._prefix("row", 7, "/x/eval-a") == "row train-seed-7"
    assert compare_cli._prefix("row", 0, "/x/eval-a") == "row train-seed-0"
