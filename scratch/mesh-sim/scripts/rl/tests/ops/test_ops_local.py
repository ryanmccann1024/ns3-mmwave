"""Plan v3 local scheduler: locks, worker and pool caps, DAG/failure policies and receipts.

Every child process here is INERT: the real worker (`task_execution.run_step`)
runs, but its child is the fake executor in this module (`child` entry point),
which writes plausible manifests, model ZIPs and check results without any
simulator, training or evaluation. Reporting/check-result owners are replaced
by in-process fakes. No ./ns3, simulator or training is executed.
"""

import copy
import fcntl
import json
import os
import signal
import subprocess
import sys
import threading
import time
import types
import zipfile
from pathlib import Path

import pytest

from scripts.rl.experiments.config import load_matrix_v2
from scripts.rl.experiments.plan import build_batch_plan, write_batch_plan
from scripts.rl.ops import batch_identity, local, recovery, run_task, tasks
from scripts.sim_support import find_mesh_root

MESH = find_mesh_root()
EXAMPLE = MESH / "inputs/experiments/examples/coordination-smoke/batch.json"
THIS = "scripts.rl.tests.ops.test_ops_local"
EXECUTION = {
    "workers": 2,
    "threads_per_worker": 1,
    "failure_policy": "continue",
    "nice": 0,
    "recovery": "checkpoint",
    "resource_pool": None,
    "source": {
        "workers": "cli",
        "threads_per_worker": "default",
        "failure_policy": "default",
        "nice": "default",
    },
}


def small_matrix(run_config: str, **changes) -> dict:
    """One row, one training seed on the 2-decision fake scenario: checkpoints 4 and 8."""
    data = {
        "matrix_version": 2,
        "name": "tiny",
        "description": "scheduler test",
        "kind": "train",
        "scenarios": {"scene": {"run_config": run_config}},
        "seeds": {"training": [1], "diagnostic": [21, 22]},
        "training": {
            "total_timesteps": 8,
            "n_steps": 2,
            "batch_size": 2,
            "n_epochs": 1,
            "checkpoint_every_steps": 4,
            "keep_checkpoints": 2,
            "checkpoint_timing": "after_update",
        },
        "evaluation": {
            "operations": [
                {
                    "id": "frozen",
                    "mode": "frozen_deterministic",
                    "seed_role": "diagnostic",
                    "at_steps": [4, "final"],
                }
            ]
        },
        "execution": {"recovery": "checkpoint"},
        "rows": [
            {
                "name": "row-a",
                "scenario": "scene",
                "profile": "standard",
                "observation_preset": "raw_links_v1",
                "action_profile": "move_2d",
                "reward_components": ["delivery_ratio"],
                "reward_weights": [1.0],
            }
        ],
    }
    data.update(copy.deepcopy(changes))
    return data


def make_root(tmp_path: Path, data, sim_binary: str, name: str = "root") -> Path:
    """Write a real plan v3 into a temporary root from a matrix dict or file."""
    if isinstance(data, dict):
        directory = tmp_path / f"m-{name}"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "batch.json"
        path.write_text(json.dumps(data))
    else:
        path = data
    root = tmp_path / name
    write_batch_plan(build_batch_plan(load_matrix_v2(path), root, sim_binary), root)
    return root.resolve()


def worker_command(root, task, attempt) -> list[str]:
    return [sys.executable, "-m", THIS, "worker", str(root), task["id"], str(attempt)]


def receipts(root: Path) -> dict:
    plan = json.loads((root / "experiment_plan.json").read_text())
    out = {}
    for task in plan["tasks"]:
        path = root / "state/steps" / f"{task['key']}.json"
        out[task["id"]] = json.loads(path.read_text()) if path.is_file() else None
    return out


def states(root: Path) -> dict:
    return {tid: (r or {}).get("state") for tid, r in receipts(root).items()}


def fake_report(task, plan, root, accepted):
    sources = {n: accepted[n]["state"] for n in task["needs"]}
    directory = Path(task["attempt_dir"])
    directory.mkdir(parents=True, exist_ok=True)
    (directory / task["expected_outputs"][0]).write_text(
        json.dumps({"sources": sources})
    )
    return {
        "sources": len(sources),
        "incomplete": any(s != "completed" for s in sources.values()),
    }


def fake_view(task, plan, root, accepted):
    return [
        accepted[t]["attempt_dir"]
        for t in task["view"]["sources"] + task["view"]["baselines"]
        if accepted[t]["attempt_dir"]
    ]


def fake_check_passed(directory) -> bool:
    record = json.loads((Path(directory) / "check_result.json").read_text())
    return record.get("status") == "passed"


def install_fakes(monkeypatch=None) -> None:
    """Replace the reporting owner and the check-result reader with inert fakes."""
    from scripts.rl.policy import operation

    module = types.ModuleType("scripts.rl.experiments.reporting")
    module.run_report_task = fake_report
    module.build_comparison_view = fake_view
    if monkeypatch is None:
        sys.modules[module.__name__] = module
        operation.check_result_passed = fake_check_passed
    else:
        monkeypatch.setitem(sys.modules, module.__name__, module)
        monkeypatch.setattr(
            operation, "check_result_passed", fake_check_passed, raising=False
        )


@pytest.fixture(name="fakes")
def fakes(monkeypatch, tmp_path):
    """In-process fakes plus environment for the inert child executor."""
    import torch

    install_fakes(monkeypatch)
    state = tmp_path / "optimizer.pth"
    parameter = torch.nn.Parameter(torch.zeros(2))
    optimizer = torch.optim.Adam([parameter])
    parameter.grad = torch.ones(2)
    optimizer.step()
    torch.save(optimizer.state_dict(), state)
    monkeypatch.setenv("FAKE_OPT_STATE", str(state))
    monkeypatch.setenv("FAKE_BATCH_LOG", str(tmp_path / "children.jsonl"))
    monkeypatch.setenv("FAKE_BATCH_RULES", "[]")
    monkeypatch.setattr(local, "PROGRESS_INTERVAL_S", 0.0)
    # Pin source identity to a private tree: the shared checkout may be edited concurrently.
    sources = tmp_path / "source-root"
    (sources / "scripts").mkdir(parents=True)
    (sources / "scripts" / "pinned.py").write_text("VALUE = 1\n")
    monkeypatch.setenv("FAKE_SOURCE_ROOT", str(sources))
    monkeypatch.setattr(batch_identity, "_source_root", lambda: sources)
    return tmp_path


def set_rules(monkeypatch, rules: list[dict]) -> None:
    monkeypatch.setenv("FAKE_BATCH_RULES", json.dumps(rules))


def run(root: Path, **execution) -> int:
    return local.run_batch(
        str(root), {**EXECUTION, **execution}, worker_command=worker_command
    )


def interrupt_when(
    path: Path, condition=None, timeout: float = 60.0
) -> threading.Thread:
    """SIGINT this (supervisor) process once a hanging child wrote `path`."""

    def wait():
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if path.exists() and (condition is None or condition()):
                time.sleep(0.2)
                os.kill(os.getpid(), signal.SIGINT)
                return
            time.sleep(0.05)

    thread = threading.Thread(target=wait, daemon=True)
    thread.start()
    return thread


def children(tmp_path: Path) -> list[dict]:
    log = tmp_path / "children.jsonl"
    return (
        [json.loads(line) for line in log.read_text().splitlines()]
        if log.exists()
        else []
    )


def max_overlap(rows: list[dict]) -> int:
    events = sorted(
        [(r["start"], 1) for r in rows if "end" in r]
        + [(r["end"], -1) for r in rows if "end" in r],
        key=lambda e: (e[0], e[1]),
    )
    level = peak = 0
    for _, delta in events:
        level += delta
        peak = max(peak, level)
    return peak


def _arg(args, flag, default=None):
    return args[args.index(flag) + 1] if flag in args else default


def _sha(path) -> str:
    import hashlib

    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _zip(path: Path, steps: int, updates: int) -> None:
    tmp = path.with_suffix(".tmp")
    with zipfile.ZipFile(tmp, "w") as archive:
        archive.writestr(
            "data", json.dumps({"num_timesteps": steps, "_n_updates": updates})
        )
        archive.writestr("policy.pth", b"weights")
        archive.writestr(
            "policy.optimizer.pth", Path(os.environ["FAKE_OPT_STATE"]).read_bytes()
        )
    tmp.replace(path)


def _write(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload))


def _hang(rule) -> None:
    Path(rule["marker"]).write_text(str(os.getpid()))
    time.sleep(600)


def _fake_train(args, out: Path, rule) -> int:
    from scripts.rl.policy.training_artifacts import MANIFEST_VERSION

    total = int(_arg(args, "--total-timesteps"))
    every = int(_arg(args, "--checkpoint-every-steps"))
    keep = int(_arg(args, "--keep-checkpoints", 3))
    n_steps = int(_arg(args, "--n-steps"))
    decisions = int(_arg(args, "--decisions-per-episode", 2))
    seed = int(_arg(args, "--seed"))
    start, resume = 0, None
    if "--resume-run-dir" in args:
        parent = Path(_arg(args, "--resume-run-dir"))
        with zipfile.ZipFile(parent / _arg(args, "--resume-checkpoint")) as archive:
            start = json.loads(archive.read("data"))["num_timesteps"]
        resume = {"parent": {"run_dir": str(parent)}, "restored_timesteps": start}
    stop = (
        total if rule.get("action") not in ("train_interrupt",) else int(rule["value"])
    )
    manifest = {
        "manifest_version": MANIFEST_VERSION,
        "status": "running",
        "control_mode": "centralized",
        "seed": seed,
        "num_timesteps": start,
        "run_config": _arg(args, "--run-config"),
        "hyperparameters": {"total_timesteps": total, "n_steps": n_steps},
        "scenario_identity": {"run_ini_sha256": _sha(_arg(args, "--run-config"))},
        "observation_schema": {"sha256": "obs"},
        "reward_schema": {"sha256": "rew"},
        "checkpoints": [],
        "model_path": None,
        "model_sha256": None,
        "resume": resume,
    }
    events = []
    (out / "checkpoints").mkdir(parents=True, exist_ok=True)
    for steps in range(start + every, stop + 1, every):
        path = out / "checkpoints" / f"checkpoint_{steps}_steps.zip"
        _zip(path, steps, steps // n_steps)
        entries = manifest["checkpoints"] + [
            {"path": str(path), "sha256": _sha(path), "num_timesteps": steps}
        ]
        for old in entries[:-keep]:
            Path(old["path"]).unlink()
        manifest["checkpoints"] = entries[-keep:]
        manifest["num_timesteps"] = steps
        events.append(
            {
                "steps": steps,
                "total_episodes": steps // decisions,
                "optimizer_epoch_counter": steps // n_steps,
                "timing": "after optimizer update",
            }
        )
        _write(
            out / "post_update_checkpoints.json",
            {
                "post_update_checkpoints_version": 1,
                "restored_steps": start,
                "events": events,
            },
        )
    last_episode = stop // decisions + (
        1 if rule.get("action") == "train_interrupt" else 0
    )
    for episode in range(start // decisions + 1, last_episode + 1):
        _write(
            out / f"episode-{episode:05d}" / "rl_episode.json",
            {"status": "completed", "steps": decisions, "seed": seed},
        )
    if rule.get("action") == "train_interrupt":
        manifest["num_timesteps"] = last_episode * decisions
        _write(out / "train_manifest.json", manifest)
        _hang(rule)
    model = out / "maskable_ppo_mesh.zip"
    _zip(model, total, total // n_steps)
    manifest.update(num_timesteps=total)
    if rule.get("action") == "train_terminal":
        _write(out / "train_manifest.json", manifest)
        _hang(rule)
    manifest.update(status="completed", model_path=str(model), model_sha256=_sha(model))
    _write(out / "train_manifest.json", manifest)
    return 0


def _fake_operate(args, out: Path, rule) -> int:
    command = args[0]
    seed = int(_arg(args, "--seed", 0))
    status = "partial" if rule.get("action") == "partial" else "completed"
    if command in ("preflight", "replay-gate", "reward-audit"):
        _write(
            out / "check_result.json",
            {"status": "passed" if rule.get("action") != "check_fail" else "failed"},
        )
        return 0
    mode = _arg(args, "--mode", "baseline")
    if command == "model":
        _write(
            out / "model_used.json",
            {
                "run_dir": _arg(args, "--run-dir"),
                "model": _arg(args, "--model"),
                "binding": _arg(args, "--binding"),
            },
        )
    (out / f"episode-{seed}").mkdir(parents=True, exist_ok=True)
    episodes = [{"episode_dir": f"episode-{seed}"}]
    if mode in ("baseline", "frozen_deterministic", "frozen_sampled"):
        _write(
            out / "eval_manifest.json",
            {
                "status": status,
                "seeds": [seed],
                "episodes_expected": 1,
                "episodes_completed": 1 if status == "completed" else 0,
                "policies": {"model": {"episodes": episodes}},
            },
        )
    if mode != "baseline" and mode != "frozen_deterministic":
        _write(
            out / "online_manifest.json",
            {
                "online_experiment_version": 5,
                "protocol": mode,
                "status": status,
                "seed": seed,
                "episodes": episodes,
            },
        )
    return 0


def fake_child(argv: list[str]) -> int:
    module, args = argv[0], argv[1:]
    out = Path(_arg(args, "--output-dir"))
    joined = " ".join(argv)
    rules = json.loads(os.environ.get("FAKE_BATCH_RULES", "[]"))
    rule = next((r for r in rules if all(m in joined for m in r["match"])), {})
    log = os.environ.get("FAKE_BATCH_LOG")
    start = time.time()
    if rule.get("action") == "touch":
        Path(rule["value"]).write_text("# added during a batch\n")
    if rule.get("action") == "sleep" or "sleep" in rule:
        time.sleep(float(rule.get("sleep", rule.get("value", 0))))
    if rule.get("action") == "hang":
        _hang(rule)
    if rule.get("action") == "fail":
        code = 1
    elif module == "scripts.rl.train":
        code = _fake_train(args, out, rule)
    elif module == "scripts.rl.operate":
        code = _fake_operate(args, out, rule)
    else:
        _write(out / "comparison.json", {"status": "complete"})
        code = 0
    if rule.get("action") == "exit2":
        code = 2
    if log:
        with open(log, "a") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            handle.write(
                json.dumps(
                    {
                        "start": start,
                        "end": time.time(),
                        "out": str(out),
                        "pid": os.getpid(),
                    }
                )
                + "\n"
            )
    return code


def fake_worker(root: str, task_id: str, attempt: str) -> int:
    from scripts.rl.ops.process import ProcessInterrupted
    from scripts.rl.ops.task_execution import run_step

    try:
        return run_step(
            root,
            task_id,
            int(attempt),
            child_argv=lambda s: [
                sys.executable,
                "-m",
                THIS,
                "child",
                s["module"],
                *s["args"],
            ],
        )
    except ProcessInterrupted as exc:
        return 128 + exc.signum


def supervise(root: str, execution: str) -> int:
    install_fakes()
    batch_identity._source_root = lambda: Path(os.environ["FAKE_SOURCE_ROOT"])
    return local.run_batch(root, json.loads(execution), worker_command=worker_command)


def test_dag_completes_with_receipts_status_bindings_and_logs(
    fakes, multi_run_config, sim_binary
):
    root = make_root(fakes, small_matrix(multi_run_config), sim_binary)
    assert run(root) == 0
    plan = json.loads((root / "experiment_plan.json").read_text())
    got = receipts(root)
    assert set(r["state"] for r in got.values()) == {"completed"}
    for task in plan["tasks"]:
        receipt = got[task["id"]]
        assert receipt["batch_step_version"] == recovery.BATCH_STEP_VERSION
        assert receipt["accepted_attempt"] == 1 and receipt["outputs"]
        assert all(o["sha256"] for o in receipt["outputs"])
        if task.get("attempts") != "projection":
            assert receipt["attempts"][0]["attempt_dir"] == str(
                Path(task["output_dir"]) / "attempt-1"
            )
        assert (root / "local" / task["key"] / "attempt-1.log").is_file()
    train = next(t for t in plan["tasks"] if t["kind"] == "train")
    for checkpoint in ("4", "final"):
        binding = json.loads(
            (root / f"state/bindings/{train['key']}-{checkpoint}.json").read_text()
        )
        assert binding["model_binding_version"] == 1 and binding["optimizer_sha256"]
    operate = next(
        t
        for t in plan["tasks"]
        if t["kind"] == "operate" and t["identity"]["checkpoint"] == "4"
    )
    used = json.loads(
        (
            Path(got[operate["id"]]["attempts"][0]["attempt_dir"]) / "model_used.json"
        ).read_text()
    )
    assert used["model"] == "checkpoints/checkpoint_4_steps.zip"
    pinned = got[operate["id"]]["inputs"]["binding"]["path"]
    assert pinned == str(root / operate["binding"]["path"])
    assert "{binding_path}" in operate["args"] and used["binding"] == pinned
    assert got[operate["id"]]["inputs"]["binding"]["sha256"]
    status = json.loads((root / "campaign_status.json").read_text())
    assert status["campaign_version"] == 2 and status["state"] == "completed"
    assert status["counts"]["completed"] == len(plan["tasks"]) and set(
        status["counts"]
    ) == set(recovery.STATES)
    assert status["execution"]["source"]["workers"] == "cli"
    assert status["receipts"][train["id"]] == f"state/steps/{train['key']}.json"
    identity = json.loads((root / "runtime_identity.json").read_text())
    assert identity["runtime_identity_version"] == 1 and identity["python_sources"]
    assert (root / "resources.jsonl").is_file()
    view = local.batch_status(str(root))
    assert (
        view["state"] == "completed"
        and view["tasks"][train["id"]]["accepted_attempt"] == 1
    )
    assert run(root) == 0
    assert all(len(r["attempts"]) == 1 for r in receipts(root).values())


def test_root_lock_refuses_a_second_supervisor(
    fakes, multi_run_config, sim_binary, capsys
):
    root = make_root(fakes, small_matrix(multi_run_config), sim_binary)
    with local.root_lock(root):
        assert run(root) == 1
        assert local.lock_held(root)
    assert "another batch supervisor" in capsys.readouterr().err
    assert not (root / "state").exists() and not local.lock_held(root)


def test_per_root_worker_cap(fakes, multi_run_config, sim_binary, monkeypatch):
    set_rules(
        monkeypatch,
        [{"match": ["scripts.rl.operate"], "action": "sleep", "value": 0.6}],
    )
    root = make_root(fakes, small_matrix(multi_run_config), sim_binary)
    assert run(root, workers=2) == 0
    operates = [r for r in children(fakes) if "/operations/" in r["out"]]
    assert len(operates) == 4 and max_overlap(operates) == 2


def test_pool_capacity_mismatch_is_refused(fakes, multi_run_config, sim_binary, capsys):
    pool = {"path": str(fakes / "pool"), "reference": "pool", "capacity": 2}
    local.register_pool(pool)
    root = make_root(fakes, small_matrix(multi_run_config), sim_binary)
    assert run(root, resource_pool={**pool, "capacity": 3}) == 1
    assert "capacity 2" in capsys.readouterr().err
    assert all(not r["attempts"] for r in receipts(root).values() if r)


def test_shared_pool_caps_two_supervisors(
    fakes, multi_run_config, sim_binary, monkeypatch
):
    set_rules(
        monkeypatch, [{"match": ["scripts.rl."], "action": "sleep", "value": 0.3}]
    )
    pool = {"path": str(fakes / "pool"), "reference": "pool", "capacity": 1}
    roots = [
        make_root(fakes, small_matrix(multi_run_config), sim_binary, name)
        for name in ("a", "b")
    ]
    execution = json.dumps({**EXECUTION, "workers": 2, "resource_pool": pool})
    procs = [
        subprocess.Popen(
            [sys.executable, "-m", THIS, "supervise", str(r), execution],
            cwd=str(MESH),
            env=dict(os.environ),
        )
        for r in roots
    ]
    assert [p.wait(timeout=240) for p in procs] == [0, 0]
    rows = children(fakes)
    assert len(rows) == 10 and max_overlap(rows) == 1
    assert json.loads((fakes / "pool" / "pool.json").read_text())["capacity"] == 1
    assert not list((fakes / "pool").glob("slot-*.json"))


def test_worker_crash_keeps_slot_until_owned_child_is_reaped(fakes):
    pool = {"path": str(fakes / "pool"), "reference": "pool", "capacity": 1}
    marker = str(fakes / "attempt-marker")
    holder = f"""
import subprocess, sys, time
from scripts.rl.ops import local
with local.pool_slot({pool!r}, {{"task_id": "t"}}) as slot:
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)", {marker!r}],
                             start_new_session=True, pass_fds=(slot.fileno(),))
    local.record_slot_child({pool!r}, slot, child.pid, {marker!r})
    print(child.pid, flush=True)
    time.sleep(60)
"""
    worker = subprocess.Popen(
        [sys.executable, "-c", holder], cwd=str(MESH), stdout=subprocess.PIPE, text=True
    )
    child = int(worker.stdout.readline())
    worker.kill()
    worker.wait()
    with open(fakes / "pool" / "slot-0.lock", "a+") as handle:
        with pytest.raises(BlockingIOError):
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    assert local.owned_group_alive(child, marker)
    assert not local.reap_group(child, "not-this-attempt")
    assert local.reap_group(child, marker)
    with open(fakes / "pool" / "slot-0.lock", "a+") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)


def test_sigint_stops_reaps_records_interrupted_and_releases_slots(
    fakes, multi_run_config, sim_binary, monkeypatch
):
    marker = fakes / "hung"
    set_rules(
        monkeypatch,
        [{"match": ["scripts.rl.train"], "action": "hang", "marker": str(marker)}],
    )
    pool = {"path": str(fakes / "pool"), "reference": "pool", "capacity": 1}
    root = make_root(fakes, small_matrix(multi_run_config), sim_binary)
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            THIS,
            "supervise",
            str(root),
            json.dumps({**EXECUTION, "resource_pool": pool}),
        ],
        cwd=str(MESH),
    )
    deadline = time.monotonic() + 60
    while not marker.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    child = int(marker.read_text())
    proc.send_signal(signal.SIGINT)
    assert proc.wait(timeout=60) == 130
    got = states(root)
    train = next(t for t in got if t.startswith("train/"))
    assert got[train] == "interrupted"
    with pytest.raises(ProcessLookupError):
        os.kill(child, 0)
    with open(fakes / "pool" / "slot-0.lock", "a+") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    status = json.loads((root / "campaign_status.json").read_text())
    assert status["state"] == "interrupted" and status["counts"]["interrupted"] == 1
    assert local.batch_status(str(root))["state"] == "interrupted"


@pytest.mark.parametrize("policy", ["continue", "stop"])
def test_continue_and_stop_failure_policies(
    fakes, multi_run_config, sim_binary, monkeypatch, policy
):
    set_rules(monkeypatch, [{"match": ["train-seed-1/attempt-1"], "action": "fail"}])
    root = make_root(
        fakes,
        small_matrix(
            multi_run_config, seeds={"training": [1, 2], "diagnostic": [21, 22]}
        ),
        sim_binary,
    )
    assert run(root, workers=1, failure_policy=policy) == 1
    got = states(root)
    assert got["train/scene/row-a/train-seed-1"] == "failed"
    seed_one = [
        s for t, s in got.items() if t.startswith("operate/") and "/train-seed-1/" in t
    ]
    if policy == "continue":
        assert got["train/scene/row-a/train-seed-2"] == "completed"
        assert set(seed_one) == {"skipped_dependency"}
        assert all(s == "completed" for t, s in got.items() if "/train-seed-2/" in t)
        assert got["curves/scene"] == "completed"
    else:
        assert got["train/scene/row-a/train-seed-2"] == "pending"
        assert set(seed_one) == {"skipped_dependency"}
        assert {s for t, s in got.items() if "/train-seed-2/" in t} == {"pending"}
    assert json.loads((root / "campaign_status.json").read_text())["state"] == "failed"


def test_selection_branches_skip_unselected_rows(fakes, multi_run_config, sim_binary):
    data = small_matrix(multi_run_config)
    data["evaluation"]["operations"][0]["at_steps"] = ["final"]
    base = data["rows"][0]
    data["rows"] = [
        {**base, "name": n, "profile": p}
        for n, p in (
            ("screen-a", "a"),
            ("screen-b", "b"),
            ("main-a", "a"),
            ("main-b", "b"),
        )
    ]
    data["stages"] = [
        {
            "name": "screen",
            "rows": ["screen-a", "screen-b"],
            "selection": {
                "rule": "replay",
                "candidates": {"a": ["screen-a"], "b": ["screen-b"]},
                "branches": {"a": ["main-a"], "b": ["main-b"]},
                "winners": ["a"],
                "provenance": "test replay",
            },
        },
        {"name": "main", "rows": ["main-a", "main-b"], "needs": ["screen"]},
    ]
    root = make_root(fakes, data, sim_binary)
    assert run(root) == 0
    got = states(root)
    assert got["select/screen"] == "completed"
    assert {s for t, s in got.items() if "/main-b/" in t} == {"skipped_selection"}
    assert {s for t, s in got.items() if "/main-a/" in t} == {"completed"}
    select = receipts(root)["select/screen"]
    receipt = json.loads(
        (
            Path(select["attempts"][0]["attempt_dir"]) / "selection_receipt.json"
        ).read_text()
    )
    assert receipt["selected"] == ["a"] and receipt["replay"] is True
    assert (
        json.loads((root / "campaign_status.json").read_text())["counts"][
            "skipped_selection"
        ]
        == 3
    )


def test_warning_exit_partial_and_train_exit_two(
    fakes, multi_run_config, sim_binary, monkeypatch
):
    set_rules(
        monkeypatch,
        [
            {"match": ["/seed-21/"], "action": "exit2"},
            {"match": ["checkpoint-final/", "/seed-22/"], "action": "partial"},
        ],
    )
    root = make_root(fakes, small_matrix(multi_run_config), sim_binary)
    assert run(root) == 1
    got = receipts(root)
    warned = [r for t, r in got.items() if "/seed-21/" in t]
    assert all(
        r["state"] == "completed" and r["warnings"] and r["exit_code"] == 2
        for r in warned
    )
    partial = got[
        "operate/scene/row-a/train-seed-1/checkpoint-final/frozen/diagnostic/seed-22"
    ]
    assert partial["state"] == "partial"
    assert json.loads((root / "campaign_status.json").read_text())["state"] == "failed"

    set_rules(monkeypatch, [{"match": ["/seed-21/"], "action": "exit2"}])
    root = make_root(fakes, small_matrix(multi_run_config), sim_binary, "warn")
    assert run(root) == 0
    assert (
        json.loads((root / "campaign_status.json").read_text())["state"]
        == "completed_with_warnings"
    )

    set_rules(monkeypatch, [{"match": ["scripts.rl.train"], "action": "exit2"}])
    root = make_root(fakes, small_matrix(multi_run_config), sim_binary, "train2")
    assert run(root) == 1
    assert states(root)["train/scene/row-a/train-seed-1"] == "failed"


def test_sixteen_leaves_get_distinct_receipts_and_attempts(fakes, sim_binary):
    root = make_root(fakes, EXAMPLE, sim_binary)
    assert run(root, workers=4) == 0
    plan = json.loads((root / "experiment_plan.json").read_text())
    got = receipts(root)
    leaves = [t for t in plan["tasks"] if t["kind"] == "operate"]
    assert len(leaves) == 16
    paths = {str(recovery.receipt_path(root, t)) for t in leaves}
    dirs = {got[t["id"]]["attempts"][0]["attempt_dir"] for t in leaves}
    assert len(paths) == len(dirs) == 16
    assert all(got[t["id"]]["state"] == "completed" for t in plan["tasks"])


def test_malformed_receipt_and_unknown_directory_are_blocked(
    fakes, multi_run_config, sim_binary
):
    root = make_root(fakes, small_matrix(multi_run_config), sim_binary)
    plan = json.loads((root / "experiment_plan.json").read_text())
    ops = [t for t in plan["tasks"] if t["kind"] == "operate"]
    bad = recovery.receipt_path(root, ops[0])
    bad.parent.mkdir(parents=True)
    bad.write_text("{not json")
    Path(ops[1]["output_dir"], "attempt-1").mkdir(parents=True)
    assert run(root) == 1
    view = local.batch_status(str(root))
    assert view["tasks"][ops[0]["id"]]["state"] == "blocked"
    assert "unreadable" in view["tasks"][ops[0]["id"]]["detail"]
    assert view["tasks"][ops[1]["id"]]["state"] == "blocked"
    assert bad.read_text() == "{not json"
    assert view["tasks"][ops[2]["id"]]["state"] == "completed"


def test_changed_output_hash_invalidates_the_accepted_attempt(
    fakes, multi_run_config, sim_binary
):
    root = make_root(fakes, small_matrix(multi_run_config), sim_binary)
    assert run(root) == 0
    task_id = (
        "operate/scene/row-a/train-seed-1/checkpoint-final/frozen/diagnostic/seed-21"
    )
    manifest = (
        Path(receipts(root)[task_id]["attempts"][0]["attempt_dir"])
        / "eval_manifest.json"
    )
    manifest.write_text(manifest.read_text() + " ")
    assert run(root) == 1
    receipt = receipts(root)[task_id]
    assert receipt["state"] == "blocked" and receipt["accepted_attempt"] is None
    assert receipt["invalidated"][0]["attempt"] == 1 and len(receipt["attempts"]) == 1


def test_step_dispatch_is_allowlisted_and_placeholders_must_resolve(tmp_path, capsys):
    assert run_task.main(["--output-root", str(tmp_path), "--step", "x"]) == 1
    assert (
        run_task.main(
            [
                "--output-root",
                str(tmp_path),
                "--step",
                "x",
                "--attempt",
                "1",
                "--compare",
            ]
        )
        == 1
    )
    assert "--step needs --attempt" in capsys.readouterr().err
    with pytest.raises(ValueError, match="allowlisted"):
        tasks.step_module({"id": "x", "module": "os", "handler": None})
    with pytest.raises(ValueError, match="allowlisted"):
        tasks.step_module(
            {"id": "x", "module": "scripts.rl.train", "handler": "select"}
        )
    task = {
        "id": "t",
        "args": [
            "--run-dir",
            "{binding_run_dir}",
            "--src",
            "{accepted_dir:a/b}",
            "--out",
            "{attempt_dir}",
            "--json",
            '{"attempt_dir": 1}',
        ],
    }
    with pytest.raises(ValueError, match="model binding"):
        tasks.substitute_args(task, "/x")
    binding = {
        "run_dir": "/r",
        "model_selection": "checkpoint",
        "model_path": "/r/checkpoints/c.zip",
    }
    assert tasks.substitute_args(task, "/x", binding, {"a/b": "/acc"}) == [
        "--run-dir",
        "/r",
        "--src",
        "/acc",
        "--out",
        "/x",
        "--json",
        '{"attempt_dir": 1}',
    ]
    bound = {
        "id": "m",
        "args": ["model", "--binding", "{binding_path}", "--model", "{binding_model}"],
    }
    with pytest.raises(ValueError, match="binding file"):
        tasks.substitute_args(bound, "/x", binding)
    assert tasks.substitute_args(
        bound, "/x", binding, binding_path="/root/state/bindings/k-4.json"
    ) == [
        "model",
        "--binding",
        "/root/state/bindings/k-4.json",
        "--model",
        "checkpoints/c.zip",
    ]
    assert tasks.substitute_args(
        {"id": "c", "args": ["--eval-dirs", "{accepted_dirs}", "--o", "x"]},
        "/x",
        accepted_dirs=["/a", "/b"],
    ) == ["--eval-dirs", "/a", "/b", "--o", "x"]
    args = [
        "--sim-binary",
        "b",
        "--observation-preset",
        "p",
        "--reward-weights=-1",
        "m-ppo",
        "--continue-from-run-dir",
        "d",
        "--continue-model",
        "final",
        "--seed",
        "1",
    ]
    assert tasks.resume_train_args(args, "/p", "checkpoints/c.zip") == [
        "--sim-binary",
        "b",
        "m-ppo",
        "--seed",
        "1",
        "--resume-run-dir",
        "/p",
        "--resume-checkpoint",
        "checkpoints/c.zip",
    ]


if __name__ == "__main__":
    entry, rest = sys.argv[1], sys.argv[2:]
    if entry == "child":
        sys.exit(fake_child(rest))
    if entry == "worker":
        sys.exit(fake_worker(*rest))
    if entry == "supervise":
        sys.exit(supervise(*rest))
    sys.exit(f"unknown entry {entry}")
