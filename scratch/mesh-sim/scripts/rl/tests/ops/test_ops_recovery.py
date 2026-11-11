"""Plan v3 identity refusals, receipts and checkpoint recovery proposals.

Children are INERT (see `test_ops_local.py`): the fake executor writes plausible
train manifests, post-update checkpoint events and ZIPs, operation manifests
and check results. No simulator, training or evaluation runs. Interruptions are
real SIGINTs to the in-process supervisor while an inert child hangs.
"""

import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from scripts.rl.ops import batch_identity, batch_receipts, local, recovery
from scripts.rl.tests.ops.test_ops_local import (
    EXAMPLE,
    EXECUTION,
    fakes as ops_fakes,  # noqa: F401 (registered by pytest)
    interrupt_when,
    make_root,
    receipts,
    run,
    set_rules,
    small_matrix,
    states,
    worker_command,
)

TRAIN = "train/scene/row-a/train-seed-1"
EXAMPLE_TRAIN = "train/rural-coverage-3-peers/raw-delivery/train-seed-101"


def tree_hashes(directory: Path) -> dict:
    return {
        str(p.relative_to(directory)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(directory.rglob("*"))
        if p.is_file()
    }


def resume(root: Path, prepare_only: bool = False, sim_binary=None, **execution) -> int:
    return recovery.prepare_resume(
        str(root),
        sim_binary,
        {**EXECUTION, **execution},
        prepare_only,
        worker_command=worker_command,
    )


def proposals(root: Path) -> list[dict]:
    return [
        json.loads(p.read_text())
        for p in sorted((root / "state/recovery").glob("*.json"))
    ]


def interrupted_run(
    root: Path, marker: Path, monkeypatch, rules, condition=None
) -> None:
    set_rules(monkeypatch, rules)
    interrupt_when(marker, condition)
    assert run(root) == 130
    set_rules(monkeypatch, [])


def test_identity_is_pinned_once_and_changes_are_refused_before_dispatch(
    fakes, multi_run_config, sim_binary, monkeypatch, capsys
):
    root = make_root(fakes, small_matrix(multi_run_config), sim_binary)
    plan = json.loads((root / "experiment_plan.json").read_text())
    identity = recovery.ensure_identity(root, plan)
    raw = (root / "runtime_identity.json").read_bytes()
    assert (
        identity["sim_binary"]["sha256"] and identity["registry"]["reward_components"]
    )
    assert (
        set(identity["inputs"]) == set(plan["inputs"]) and identity["package_versions"]
    )
    sources = fakes / "source-root" / "scripts"

    (sources / "added.py").write_text("x = 1\n")
    with pytest.raises(recovery.IdentityChanged, match="source added scripts/added.py"):
        recovery.check_identity(root)
    assert run(root) == 1
    assert "source added" in capsys.readouterr().err
    assert not (root / "state/steps").exists()
    (sources / "added.py").unlink()
    (sources / "pinned.py").unlink()
    with pytest.raises(
        recovery.IdentityChanged, match="source removed scripts/pinned.py"
    ):
        recovery.check_identity(root)
    assert resume(root, prepare_only=True) == 1
    assert not (root / "state/recovery").exists()
    (sources / "pinned.py").write_text("VALUE = 1\n")
    recovery.check_identity(root)

    nodes = Path(multi_run_config).parent / "nodes.json"
    original = nodes.read_text()
    nodes.write_text(original + " ")
    with pytest.raises(recovery.IdentityChanged, match="input .*nodes.json"):
        recovery.check_identity(root)
    nodes.write_text(original)

    real_versions = batch_identity.package_versions
    monkeypatch.setattr(
        batch_identity, "package_versions", lambda: {**real_versions(), "torch": "0.0"}
    )
    with pytest.raises(recovery.IdentityChanged, match="dependency torch"):
        recovery.check_identity(root)
    monkeypatch.setattr(batch_identity, "package_versions", real_versions)

    binary = Path(sim_binary)
    copy = fakes / "moved" / "fake-sim"
    copy.parent.mkdir()
    copy.write_bytes(binary.read_bytes())
    recovery.check_identity(root, str(copy))
    copy.write_bytes(binary.read_bytes() + b"\n")
    with pytest.raises(recovery.IdentityChanged, match="simulator binary"):
        recovery.check_identity(root, str(copy))
    assert (root / "runtime_identity.json").read_bytes() == raw


def test_parent_model_zip_change_is_refused(fakes, multi_run_config, sim_binary):
    from scripts.artifact_io import sha256_file

    parent = fakes / "parent"
    parent.mkdir()
    model = parent / "maskable_ppo_mesh.zip"
    with zipfile.ZipFile(model, "w") as archive:
        archive.writestr("data", json.dumps({"num_timesteps": 4, "_n_updates": 2}))
    (parent / "train_manifest.json").write_text(
        json.dumps(
            {
                "status": "completed",
                "seed": 1,
                "num_timesteps": 4,
                "model_path": str(model),
                "model_sha256": sha256_file(model),
                "hyperparameters": {"n_steps": 2, "batch_size": 2, "n_epochs": 1},
                "scenario_identity": {"run_ini_sha256": sha256_file(multi_run_config)},
                "selection": {
                    "observation_preset": "raw_links_v1",
                    "reward_components": ["delivery_ratio"],
                    "reward_weights": [1.0],
                },
                "checkpoints": [],
            }
        )
    )
    data = small_matrix(
        multi_run_config,
        training={
            "total_timesteps": 12,
            "n_steps": 2,
            "batch_size": 2,
            "n_epochs": 1,
            "checkpoint_every_steps": 4,
            "keep_checkpoints": 2,
            "checkpoint_timing": "after_update",
        },
    )
    data["rows"][0]["continue_from"] = {"run_dir": str(parent)}
    data["evaluation"]["operations"][0]["at_steps"] = ["final"]
    root = make_root(fakes, data, sim_binary)
    identity = recovery.ensure_identity(
        root, json.loads((root / "experiment_plan.json").read_text())
    )
    assert str(model) in identity["parent_models"]
    with zipfile.ZipFile(model, "a") as archive:
        archive.writestr("extra", "changed")
    with pytest.raises(recovery.IdentityChanged, match="maskable_ppo_mesh.zip"):
        recovery.check_identity(root)


def test_source_change_during_a_batch_stops_dispatch(
    fakes, multi_run_config, sim_binary, monkeypatch
):
    added = fakes / "source-root" / "scripts" / "late.py"
    set_rules(
        monkeypatch,
        [{"match": ["scripts.rl.train"], "action": "touch", "value": str(added)}],
    )
    root = make_root(fakes, small_matrix(multi_run_config), sim_binary)
    assert run(root) == 1
    got = states(root)
    assert got[TRAIN] == "completed"
    assert {s for t, s in got.items() if t.startswith("operate/")} == {"pending"}
    status = json.loads((root / "campaign_status.json").read_text())
    assert (
        status["state"] == "failed"
        and "source added scripts/late.py" in status["refusal"]
    )


def test_interrupt_before_first_checkpoint_is_blocked(
    fakes, multi_run_config, sim_binary, monkeypatch
):
    marker = fakes / "hung"
    root = make_root(fakes, small_matrix(multi_run_config), sim_binary)
    interrupted_run(
        root,
        marker,
        monkeypatch,
        [
            {
                "match": ["scripts.rl.train"],
                "action": "train_interrupt",
                "value": 0,
                "marker": str(marker),
            }
        ],
    )
    assert states(root)[TRAIN] == "interrupted"
    assert resume(root, prepare_only=True) == 0
    entry = proposals(root)[0]["tasks"][TRAIN]
    assert (
        entry["action"] == "blocked"
        and "no verified post-update checkpoint" in entry["detail"]
    )
    assert resume(root) == 1
    got = states(root)
    assert got[TRAIN] == "blocked"
    assert {s for t, s in got.items() if t.startswith("operate/")} == {
        "skipped_dependency"
    }
    assert len(receipts(root)[TRAIN]["attempts"]) == 1


def test_terminal_zip_without_final_manifest_is_blocked(
    fakes, multi_run_config, sim_binary, monkeypatch
):
    marker = fakes / "hung"
    root = make_root(fakes, small_matrix(multi_run_config), sim_binary)
    interrupted_run(
        root,
        marker,
        monkeypatch,
        [
            {
                "match": ["scripts.rl.train"],
                "action": "train_terminal",
                "marker": str(marker),
            }
        ],
    )
    assert resume(root, prepare_only=True) == 0
    entry = proposals(root)[0]["tasks"][TRAIN]
    assert entry["action"] == "blocked" and "terminal budget" in entry["detail"]


def test_checkpoint_recovery_128_to_256_and_ancestor_milestone(
    fakes, sim_binary, monkeypatch
):
    marker = fakes / "hung"
    root = make_root(fakes, EXAMPLE, sim_binary)
    plan_bytes = (root / "experiment_plan.json").read_bytes()
    interrupted_run(
        root,
        marker,
        monkeypatch,
        [
            {
                "match": ["scripts.rl.train"],
                "action": "train_interrupt",
                "value": 128,
                "marker": str(marker),
            }
        ],
    )
    got = states(root)
    assert got[EXAMPLE_TRAIN] == "interrupted"
    completed_before = {t for t, s in got.items() if s == "completed"}
    assert completed_before and all(
        not t.startswith("operate/") for t in completed_before
    )
    attempt_one = Path(receipts(root)[EXAMPLE_TRAIN]["attempts"][0]["attempt_dir"])
    before = tree_hashes(attempt_one)

    assert resume(root, prepare_only=True) == 0
    first = sorted((root / "state/recovery").glob("*.json"))
    raw = first[0].read_bytes()
    entry = proposals(root)[0]["tasks"][EXAMPLE_TRAIN]
    assert entry["action"] == "resume_checkpoint"
    assert entry["restored_decisions"] == 128 and entry["remaining_decisions"] == 128
    assert entry["checkpoint"]["relative"] == "checkpoints/checkpoint_128_steps.zip"
    assert entry["checkpoint"]["event"]["timing"] == "after optimizer update"
    assert entry["accepted_episode_ranges"] == [
        {"attempt": 1, "first_episode": 1, "last_episode": 2}
    ]
    assert entry["excluded_tail"]["complete_episodes_excluded"] == 1
    assert entry["excluded_tail"]["last_recorded_steps"] == 192
    assert (
        "--resume-run-dir" in entry["args"]
        and "--observation-preset" not in entry["args"]
    )
    assert all(
        proposals(root)[0]["tasks"][t]["action"] == "keep" for t in completed_before
    )
    assert resume(root, prepare_only=True) == 0
    assert (
        sorted((root / "state/recovery").glob("*.json")) == first
        and first[0].read_bytes() == raw
    )
    assert tree_hashes(attempt_one) == before

    assert resume(root) == 0
    got = receipts(root)
    train = got[EXAMPLE_TRAIN]
    assert train["state"] == "completed" and train["accepted_attempt"] == 2
    assert train["attempts"][1]["resume"]["parent_attempt"] == 1
    assert all(len(got[t]["attempts"]) == 1 for t in completed_before)
    assert tree_hashes(attempt_one) == before
    assert (root / "experiment_plan.json").read_bytes() == plan_bytes

    plan = json.loads(plan_bytes)
    producer = next(t for t in plan["tasks"] if t["id"] == EXAMPLE_TRAIN)
    binding = json.loads(
        (root / f"state/bindings/{producer['key']}-128.json").read_text()
    )
    assert (
        binding["run_dir"] == str(attempt_one)
        and binding["model_selection"] == "checkpoint"
    )
    assert binding["num_timesteps"] == 128
    ancestor = [
        t
        for t in plan["tasks"]
        if t["kind"] == "operate" and t["identity"]["checkpoint"] == "128"
    ]
    assert len(ancestor) == 8
    for task in ancestor:
        receipt = got[task["id"]]
        assert receipt["state"] == "completed"
        used = json.loads(
            (
                Path(receipt["attempts"][0]["attempt_dir"]) / "model_used.json"
            ).read_text()
        )
        binding_file = str(root / f"state/bindings/{producer['key']}-128.json")
        assert receipt["inputs"]["binding"]["path"] == binding_file
        assert used["run_dir"] == str(attempt_one)
        assert used["model"] == "checkpoints/checkpoint_128_steps.zip"
        assert "{binding_path}" in task["args"] and used["binding"] == binding_file
    final = json.loads(
        (root / f"state/bindings/{producer['key']}-final.json").read_text()
    )
    assert (
        final["run_dir"] == train["attempts"][1]["attempt_dir"]
        and final["num_timesteps"] == 256
    )

    counts = {t: len(r["attempts"]) for t, r in receipts(root).items()}
    assert resume(root) == 0
    assert {t: len(r["attempts"]) for t, r in receipts(root).items()} == counts
    assert local.batch_status(str(root))["state"] == "completed"


def test_one_interrupted_seed_retries_alone(
    fakes, multi_run_config, sim_binary, monkeypatch
):
    marker = fakes / "hung"
    hung = "operate/scene/row-a/train-seed-1/checkpoint-final/frozen/diagnostic/seed-22"
    root = make_root(fakes, small_matrix(multi_run_config), sim_binary)

    def siblings_done():
        got = states(root)
        return (
            sum(
                1
                for t, s in got.items()
                if t.startswith("operate/") and s == "completed"
            )
            == 3
        )

    interrupted_run(
        root,
        marker,
        monkeypatch,
        [
            {
                "match": ["checkpoint-final/", "/seed-22/"],
                "action": "hang",
                "marker": str(marker),
            }
        ],
        siblings_done,
    )
    got = states(root)
    assert got[hung] == "interrupted"
    assert resume(root, prepare_only=True) == 0
    tasks = proposals(root)[0]["tasks"]
    assert tasks[hung]["action"] == "retry"
    assert all(tasks[t]["action"] == "keep" for t, s in got.items() if s == "completed")
    assert resume(root) == 0
    after = receipts(root)
    assert (
        after[hung]["accepted_attempt"] == 2
        and after[hung]["attempts"][0]["state"] == "interrupted"
    )
    assert all(
        len(after[t]["attempts"]) == 1 for t, s in got.items() if s == "completed"
    )


def test_malformed_receipt_and_changed_output_are_listed_in_the_proposal(
    fakes, multi_run_config, sim_binary
):
    root = make_root(fakes, small_matrix(multi_run_config), sim_binary)
    assert run(root) == 0
    plan = json.loads((root / "experiment_plan.json").read_text())
    ops = [t for t in plan["tasks"] if t["kind"] == "operate"]
    recovery.receipt_path(root, ops[0]).write_text('{"batch_step_version": 1}')
    changed = (
        Path(receipts(root)[ops[1]["id"]]["attempts"][0]["attempt_dir"])
        / "eval_manifest.json"
    )
    changed.write_text(changed.read_text() + "\n")
    assert resume(root, prepare_only=True) == 0
    proposal = proposals(root)[0]
    assert proposal["batch_recovery_version"] == 1
    assert proposal["tasks"][ops[0]["id"]]["action"] == "blocked"
    assert any(ops[0]["id"] in b for b in proposal["blockers"])
    assert proposal["tasks"][ops[1]["id"]]["action"] == "blocked"
    assert "accepted output changed" in proposal["tasks"][ops[1]["id"]]["detail"]
    assert proposal["tasks"][ops[2]["id"]]["action"] == "keep"


def test_replaced_bound_zip_blocks_the_consumer(
    fakes, multi_run_config, sim_binary, monkeypatch
):
    marker = fakes / "hung"
    root = make_root(fakes, small_matrix(multi_run_config), sim_binary)
    interrupted_run(
        root,
        marker,
        monkeypatch,
        [{"match": ["scripts.rl.operate"], "action": "hang", "marker": str(marker)}],
    )
    train_dir = Path(receipts(root)[TRAIN]["attempts"][0]["attempt_dir"])
    model = train_dir / "maskable_ppo_mesh.zip"
    with zipfile.ZipFile(model, "a") as archive:
        archive.writestr("extra", "replaced")
    assert resume(root) == 1
    got = states(root)
    assert got[TRAIN] == "blocked"
    assert {s for t, s in got.items() if t.startswith("operate/")} == {
        "skipped_dependency"
    }
    assert "accepted output changed" in receipts(root)[TRAIN]["detail"]


@pytest.mark.parametrize("completed_receipt", [False, True])
def test_resume_completes_missing_bindings_after_an_interrupted_acceptance(
    fakes,
    sim_binary,
    monkeypatch,
    completed_receipt,
):
    from scripts.rl.experiments.plan import load_batch_plan
    from scripts.rl.tests.ops.test_ops_local import _fake_train

    root = make_root(fakes, EXAMPLE, sim_binary)
    plan = load_batch_plan(root)
    task = next(task for task in plan["tasks"] if task["id"] == EXAMPLE_TRAIN)
    attempt_dir = Path(task["output_dir"]) / "attempt-1"
    assert _fake_train(task["args"], attempt_dir, {}) == 0
    receipt = recovery.new_receipt(task, plan)
    receipt.update(
        state="interrupted", attempts=[{"attempt": 1, "attempt_dir": str(attempt_dir)}]
    )
    recovery.write_receipt(root, receipt)
    recovery.ensure_identity(root, plan)

    if completed_receipt:
        # An older supervisor may already have published the receipt without bindings.
        outputs = recovery.validate_attempt(task, attempt_dir)["outputs"]
        receipt.update(state="completed", accepted_attempt=1, outputs=outputs)
        recovery.write_receipt(root, receipt)
    else:
        proposal = recovery.build_proposal(root, plan, EXECUTION, None)
        assert proposal["tasks"][task["id"]]["action"] == "accept"

        write_json = batch_receipts.write_json

        def interrupt_after_first_binding(path, payload):
            write_json(path, payload)
            if Path(path).parent.name == "bindings":
                raise KeyboardInterrupt

        with monkeypatch.context() as patch:
            patch.setattr(batch_receipts, "write_json", interrupt_after_first_binding)
            with pytest.raises(KeyboardInterrupt):
                recovery.apply_proposal(root, plan, proposal)
        assert len(list((root / "state/bindings").glob("*.json"))) == 1
        assert recovery.read_receipt(root, task)["state"] == "interrupted"

    # Test recovery without launching workers. A completed training receipt must
    # expose its checkpoint bindings before the scheduler can dispatch a consumer.
    def verify_bindings(root, plan, execution, **kwargs):
        batch = local._Batch(Path(root), plan, execution, "resume", None, None, None)
        batch.load()
        assert batch.states[task["id"]] == "completed"
        for spec in recovery.binding_specs(plan, task["id"]).values():
            assert recovery.load_binding(root, spec)["record"]["model_sha256"]
        return 0

    monkeypatch.setattr(local, "run_locked", verify_bindings)
    assert resume(root) == 0
