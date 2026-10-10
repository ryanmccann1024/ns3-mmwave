"""Run fixed-budget trials and resume their persisted sampler and outcomes."""

import json
import os
import shlex
import socket
import sys
from pathlib import Path

from scripts.artifact_io import now_iso
from scripts.rl.ops.process import execute_step
from scripts.rl.tuning import artifacts
from scripts.rl.tuning.study import copy_study, open_study
from scripts.rl.tuning.trainer import build_trial, get_trainer



def _params_text(params):
    return " ".join(f"{key}={value!r}" for key, value in params.items())



def dry_run(spec, root, binary, sampler=None):
    study = open_study(spec, sampler)
    count = min(spec["n_trials"], spec["sampler"]["n_startup_trials"])
    for number in range(count):
        _, params = study.ask()
        trial = build_trial(spec, params, Path(root) / "trials" / f"trial-{number:04d}", binary)
        command = [sys.executable, "-m", trial["module"], *trial["args"]]
        print(f"trial {number:04d} params: {_params_text(params)}")
        print(f"trial {number:04d} command: " + " ".join(shlex.quote(part) for part in command))
    if spec["n_trials"] > count:
        print(f"the remaining {spec['n_trials'] - count} trials depend on earlier objectives "
              "and cannot be previewed")
    print("dry run: no output directory, record, or process was created")
    return 0



def _check_previous_process(record):
    process = record.get("process")
    if process is None:
        return
    if process["host"] != socket.gethostname():
        raise ValueError("resume the interrupted study on its original host")
    try:
        os.killpg(process["pid"], 0)
    except ProcessLookupError:
        return
    raise ValueError("previous trial process group may still be active; stop it before resume")



def _finish(state, record, trainer, code, failure=None):
    objective = None
    if code == 0 and failure is None:
        objective, failure = trainer.objective(record["train_dir"])
    elif failure is None:
        failure = f"training exited {code}"
    proposed = copy_study(state["study"])
    proposed.tell(state["handle"], objective)
    completed = {**record, "state": "complete" if failure is None else "failed",
                 "objective": objective, "failure": failure, "exit_code": code,
                 "ended_at": now_iso()}
    records = [completed if row["number"] == record["number"] else row
               for row in state["manifest"]["trials"]]
    manifest = {**state["manifest"], "trials": records,
                "best": artifacts.best(records, trainer.direction)}
    state.update(study=proposed, handle=None, manifest=manifest)
    print(f"trial {completed['number']:04d} {completed['state']} objective={objective} "
          + _params_text(record["params"]) + (f" ({failure})" if failure else ""))


def _recover_pending(state, trainer):
    records = state["manifest"]["trials"]
    if not records or records[-1]["state"] != "running":
        return
    record = records[-1]
    _check_previous_process(record)
    path = (Path(record["train_dir"]) / "train_manifest.json"
            if record["train_dir"] is not None else None)
    try:
        completed = path is not None and json.loads(path.read_text()).get("status") == "completed"
    except (OSError, ValueError):
        completed = False
    if completed:
        _finish(state, record, trainer, 0)
    else:
        _finish(state, record, trainer, None,
                "interrupted trial has no completed training; retained as failed, not restarted")



def run(spec, output_root, binary, *, resume=False, sampler=None, execute=None):
    root = Path(output_root).resolve()
    if resume and not (root / artifacts.CHECKPOINT_NAME).is_file():
        raise ValueError("no recovery checkpoint; version 1 studies cannot be resumed")
    trainer = get_trainer(spec["trainer"])
    candidate = open_study(spec, sampler)
    expected = artifacts.identity(spec, binary)
    with artifacts.study_lock(root):
        if resume:
            state = artifacts.restore(root, expected, candidate.version)
            _recover_pending(state, trainer)
            state["manifest"]["resume_events"].append({"at": now_iso(),
                                                       "retained_trials": len(state["manifest"]["trials"])})
        else:
            if any((root / name).exists() for name in
                   (artifacts.CHECKPOINT_NAME, artifacts.STUDY_MANIFEST_NAME, "trials")):
                raise ValueError(f"{root}: study_manifest.json or checkpoint/trials already exists; use --resume")
            state = {"identity": expected, "study": candidate, "handle": None,
                     "manifest": artifacts.manifest(spec, candidate, binary)}
        manifest = state["manifest"]
        manifest.update(status="running", ended_at=None)
        artifacts.publish(root, state)
        try:
            for number in range(len(manifest["trials"]), spec["n_trials"]):
                proposed = copy_study(state["study"])
                handle, params = proposed.ask()
                trial_dir = root / "trials" / f"trial-{number:04d}"
                record = {"trial_version": artifacts.TRIAL_VERSION, "number": number,
                          "params": params, "training": {}, "module": None, "args": [],
                          "train_dir": None, "state": "running", "objective": None,
                          "failure": None, "exit_code": None,
                          "started_at": now_iso(), "ended_at": None, "process": None}
                manifest = {**state["manifest"],
                            "trials": [*state["manifest"]["trials"], record]}
                state.update(study=proposed, handle=handle, manifest=manifest)
                artifacts.publish(root, state)

                def launched(process):
                    record["process"] = {"pid": process.pid, "host": socket.gethostname()}
                    artifacts.publish(root, state)

                try:
                    trial = build_trial(spec, params, trial_dir, binary)
                    record.update(trial)
                    artifacts.publish(root, state)
                    code = execute(trial) if execute is not None else execute_step(trial, launched)
                except Exception as exc:
                    _finish(state, record, trainer, None, f"{type(exc).__name__}: {exc}")
                else:
                    _finish(state, record, trainer, code)
                manifest = state["manifest"]
                artifacts.publish(root, state)
        except BaseException as exc:
            manifest = state["manifest"]
            manifest.update(status="interrupted" if isinstance(exc, KeyboardInterrupt) else "failed",
                            ended_at=now_iso(), error=f"{type(exc).__name__}: {exc}")
            try:
                artifacts.publish(root, state)
            except Exception as recording_error:
                print(f"Could not record study failure: {recording_error}", file=sys.stderr)
            raise
        failed = [record["number"] for record in manifest["trials"] if record["state"] == "failed"]
        manifest.update(status="failed" if failed else "completed", ended_at=now_iso())
        manifest.pop("error", None)
        artifacts.publish(root, state)
        if failed:
            print(f"{len(failed)} of {spec['n_trials']} trials produced no objective: {failed}",
                  file=sys.stderr)
        return 1 if failed else 0
