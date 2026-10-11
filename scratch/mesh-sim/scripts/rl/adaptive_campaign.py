"""Screen bounded PPO profiles, extend one winner, and measure online operation."""

import argparse
import csv
import json
from pathlib import Path
import signal
import statistics
import sys

import numpy as np

from scripts.rl import campaign, experiment
from scripts.rl.cli_common import now_iso, write_json, sha256_file
from scripts.rl.env.jammer_motion import motion_enabled
from scripts.rl.ops.tasks import build_tasks
from scripts.rl.policy.episode_review import endpoint_metrics
from scripts.sim_support import find_mesh_root


def immutable_json(path, data):
    path = Path(path)
    if path.exists():
        if json.loads(path.read_text()) != data:
            raise ValueError(f"configuration changed at {path}; use a new output root")
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        write_json(path, data)


def load_config(path, output_root=None):
    config = campaign.load_config(path)
    if config["execution"]["stages"] != ["main"]:
        raise ValueError("adaptive campaign has only a main stage")
    if len(config["screen_scenarios"]) != 4 or len(config["profiles"]) != 6:
        raise ValueError("screen requires four scenarios and six bounded profiles")
    scenes = config["screen_scenarios"] + config["extend_scenarios"]
    if len(scenes) != len(set(scenes)):
        raise ValueError("screen and extension scenarios must be distinct")
    if len(set(config["profiles"])) != len(config["profiles"]):
        raise ValueError("profile names must be unique")
    if output_root:
        config["execution"]["output_root"] = str(Path(output_root).resolve())
    for scene in scenes:
        path = Path(config["inputs"])/scene/"run.ini"
        if not path.is_file():
            raise ValueError(f"missing scenario {path}")
        motion_enabled(path)
    if config["seeds"]["training"] != [101]:
        raise ValueError("bounded campaign currently requires training seed 101")
    for scene in config["screen_scenarios"] + config["extend_scenarios"]:
        if scene in config["moving_scenarios"]:
            continue
        models = list((find_mesh_root()/config["reference_root"]/"main"/scene/"train").glob("*/train-seed-101/best_model.zip"))
        if len(models) != 4:
            raise ValueError(f"four saved 10-09-2 reference models are required for {scene}")
    return config


def campaign_identity(config):
    mesh = find_mesh_root()
    inputs = Path(config["inputs"])
    sources = list((mesh/"scripts/rl").glob("*.py"))
    for folder in ("agents", "env", "policy"):
        sources.extend((mesh/"scripts/rl"/folder).glob("*.py"))
    return {"binary_sha256": sha256_file(config["execution"]["sim_binary"]),
            "inputs": {str(p.relative_to(inputs)): sha256_file(p) for p in sorted(inputs.rglob("*")) if p.is_file()},
            "python_sources": {str(p.relative_to(mesh)): sha256_file(p) for p in sorted(sources)}}


def prepare(config, scene, profile):
    root = Path(config["execution"]["output_root"])/"main"
    destination = root/scene/profile
    matrix = {"matrix_version": 1, "name": f"rl-10-09-3-{scene}-{profile}",
              "description": "Dynamic service coverage and movement reward with a bounded PPO profile",
              "run_config": str(Path(config["inputs"])/scene/"run.ini"), "band": "sub-6",
              "seeds": config["seeds"],
              "training": {**config["training"], **config["profiles"][profile]},
              "evaluation": {"model": "best", "policies": ["model", "hold", "random_valid", "geometric", "optimization"],
                             "decision_records": True, "decision_record_seeds": [config["seeds"]["held_out"][0]],
                             "reuse_baselines": True, "baseline_cache_dir": str(root/scene/"baseline-cache")},
              "rows": [config["reward"]]}
    path = root/"matrices"/f"{scene}-{profile}.json"
    immutable_json(path, matrix)
    args = ["plan", "--matrix", str(path), "--output-root", str(destination),
            "--sim-binary", config["execution"]["sim_binary"]]
    if experiment.main(args):
        raise ValueError(f"failed to prepare {scene}/{profile}")
    plan = experiment.load_plan(destination)
    jobs = [{"id": f"main/{scene}/{profile}/{task['id']}", "root": str(destination), "index": task["index"]}
            for task in build_tasks(plan)]
    return destination, jobs


def select_profile(config):
    root = Path(config["execution"]["output_root"])/"main"
    rankings = []
    for profile in config["profiles"]:
        values, stability, evidence = [], [], []
        for scene in config["screen_scenarios"]:
            run = root/scene/profile/"train"/config["reward"]["name"]/"train-seed-101"
            manifest = json.loads((run/"train_manifest.json").read_text())
            if manifest["status"] != "completed":
                raise ValueError("profile selection requires completed training")
            with np.load(run/"evaluations.npz") as evaluations:
                means = evaluations["results"].mean(axis=1)
            value = manifest["best_mean_reward"]/600
            spread = float(np.std(means[-3:]))/600
            values.append(value)
            stability.append(spread)
            evidence.append({"scenario": scene, "best_validation_mean_reward": value,
                             "last_three_checkpoint_std": spread})
        rankings.append({"profile": profile, "validation_mean_reward": statistics.mean(values),
                         "checkpoint_std_mean": statistics.mean(stability), "scenarios": evidence})
    rankings.sort(key=lambda r: (-r["validation_mean_reward"], r["checkpoint_std_mean"], r["profile"]))
    return {"selection_version": 1, "winner": rankings[0]["profile"],
            "rule": "highest equally weighted mean best validation reward per decision across four cases; checkpoint variability breaks ties",
            "selection_seeds": config["seeds"]["model_selection"], "held_out_seeds_used": False,
            "rankings": rankings}


def references(config, runner):
    from concurrent.futures import ThreadPoolExecutor
    mesh = find_mesh_root()
    previous = mesh/config["reference_root"]
    root = Path(config["execution"]["output_root"])/"main/references"
    commands = []
    for scene in config["screen_scenarios"]+config["extend_scenarios"]:
        for run in sorted((previous/"main"/scene/"train").glob("*/train-seed-101")):
            output = root/scene/run.parent.name
            manifest = output/"eval_manifest.json"
            if manifest.exists() and json.loads(manifest.read_text())["status"] == "completed":
                continue
            command = [sys.executable, "-m", "scripts.rl.evaluate", "--sim-binary", config["execution"]["sim_binary"],
                       "--run-dir", str(run), "--model", "best", "--output-dir", str(output),
                       "--seeds", ",".join(map(str, config["seeds"]["held_out"])),
                       "--policies", "model,hold,random_valid,geometric,optimization",
                       "--baseline-cache-dir", str(root/scene/"baseline-cache"), "--label", run.parent.name]
            commands.append((command, output/"reference.log"))
    from concurrent.futures import wait, FIRST_COMPLETED
    pool = ThreadPoolExecutor(max_workers=config["execution"]["max_workers"])
    pending = {pool.submit(runner.execute, command, log): log for command, log in commands}
    completed = 0
    try:
        while pending:
            done, _ = wait(pending, timeout=30, return_when=FIRST_COMPLETED)
            if not done:
                print(f"Saved reference evaluations: {completed}/{len(commands)} completed; workers running", flush=True)
            for future in done:
                log = pending.pop(future)
                if future.result() not in (0, 2):
                    raise RuntimeError(f"archived reference evaluation failed; inspect {log}")
                completed += 1
                print(f"Saved reference evaluations: {completed}/{len(commands)} completed", flush=True)
    except BaseException:
        runner.stop()
        for future in pending:
            future.cancel()
        raise
    finally:
        pool.shutdown(wait=True, cancel_futures=True)


def write_reviews(root):
    root = Path(root)
    rows = []
    for manifest in sorted((root/"main").rglob("eval_manifest.json")):
        if "baseline-cache" in manifest.parts:
            continue
        data = json.loads(manifest.read_text())
        for policy, block in data["policies"].items():
            for episode in block["episodes"]:
                if episode["status"] != "completed":
                    continue
                extra = endpoint_metrics(episode["episode_dir"])
                rows.append({"source": str(manifest.relative_to(root)), "policy": policy, "seed": episode["seed"],
                             "return": episode["return"], **{k: v for k, v in episode["metrics"].items() if not isinstance(v, (dict, list))}, **extra})
    for manifest in sorted((root/"main").rglob("online_manifest.json")):
        data = json.loads(manifest.read_text())
        for episode in data["episodes"]:
            rows.append({"source": str(manifest.relative_to(root)), "policy": episode["mode"], "seed": episode["seed"],
                         "return": episode["return"], "update_cycles": episode["update_cycles"],
                         **{k: v for k, v in episode["metrics"].items() if not isinstance(v, (dict, list))}})
    if rows:
        columns = sorted(set().union(*(row.keys() for row in rows)))
        with (root/"episode_comparison.csv").open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()
            writer.writerows(rows)
        numeric = [key for key in columns if key not in ("source", "policy", "seed")]
        groups = {}
        for row in rows:
            groups.setdefault((row["source"], row["policy"]), []).append(row)
        summary = []
        for (source, policy), members in groups.items():
            result = {"source": source, "policy": policy, "episodes": len(members)}
            for key in numeric:
                values = [row[key] for row in members if isinstance(row.get(key), (int, float))]
                result[key] = statistics.mean(values) if values else None
                result[key+"_std"] = statistics.stdev(values) if len(values) > 1 else None
            summary.append(result)
        with (root/"policy_comparison.csv").open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(summary[0]))
            writer.writeheader()
            writer.writerows(summary)


def run(config, plan_only=False):
    root = Path(config["execution"]["output_root"])
    record = {"campaign_version": 1, "status": "running", "started_at": now_iso(), "jobs": {}}
    record_path = root/"campaign_status.json"
    runner = campaign.ProcessRunner(config["execution"]["threads_per_worker"])
    with campaign.campaign_lock(root):
        immutable_json(root/"campaign_resolved.json", config)
        immutable_json(root/"campaign_identity.json", campaign_identity(config))
        plans, jobs = [], []
        for scene in config["screen_scenarios"]:
            for profile in config["profiles"]:
                plan, batch = prepare(config, scene, profile)
                plans.append(plan)
                jobs.extend(batch)
        print("Main: 24 screening models, 8 winner extensions, 40 saved-model references; four workers", flush=True)
        print("Moving cases: online updates plus a fixed sampled control, five seeds each", flush=True)
        if plan_only:
            return 0
        write_json(record_path, record)
        try:
            if campaign.run_jobs(jobs, config["execution"]["max_workers"], runner, record, record_path):
                raise RuntimeError("screening failed; inspect main scenario local logs")
            selection = select_profile(config)
            immutable_json(root/"main/selected_profile.json", selection)
            print(f"Selected profile: {selection['winner']} from validation only", flush=True)
            extensions = []
            for scene in config["extend_scenarios"]:
                plan, batch = prepare(config, scene, selection["winner"])
                plans.append(plan)
                extensions.extend(batch)
            if campaign.run_jobs(extensions, config["execution"]["max_workers"], runner, record, record_path):
                raise RuntimeError("winner extension failed")
            for plan in plans:
                command = [sys.executable, "-m", "scripts.rl.ops.run_task", "--output-root", str(plan), "--compare"]
                if runner.execute(command, plan/"local/compare.log") not in (0, 2):
                    raise RuntimeError(f"comparison failed in {plan}")
            print("Evaluating the 40 saved reference models on the same fresh seeds; no retraining", flush=True)
            references(config, runner)
            for scene in config["moving_scenarios"]:
                destination = root/"main"/scene/selection["winner"]
                command = [sys.executable, "-m", "scripts.rl.online", "--run-dir",
                           str(destination/"train"/config["reward"]["name"]/"train-seed-101"),
                           "--sim-binary", config["execution"]["sim_binary"], "--output-dir", str(destination/"online"),
                           "--seeds", ",".join(map(str, config["seeds"]["held_out"]))]
                print(f"Continuing PPO operation: {scene}", flush=True)
                if runner.execute(command, destination/"online.log"):
                    raise RuntimeError(f"online operation failed in {scene}")
            campaign.write_reward_summary(plans, root)
            write_reviews(root)
            record.update(status="completed", winner=selection["winner"])
            return 0
        except KeyboardInterrupt:
            runner.stop()
            record["status"] = "interrupted"
            return 130
        except Exception as exc:
            runner.stop()
            record.update(status="failed", error=f"{type(exc).__name__}: {exc}")
            print(record["error"], file=sys.stderr, flush=True)
            return 1
        finally:
            record["ended_at"] = now_iso()
            write_json(record_path, record)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--output-root")
    parser.add_argument("--plan-only", action="store_true")
    args = parser.parse_args()
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    return run(load_config(args.config, args.output_root), args.plan_only)


if __name__ == "__main__":
    raise SystemExit(main())
