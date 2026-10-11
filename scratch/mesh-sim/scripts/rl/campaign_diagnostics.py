"""Compare saved hold models under sampled and deterministic execution."""

from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
import json
from pathlib import Path
import sys

from scripts.rl.cli_common import write_json
from scripts.sim_support import find_mesh_root


def diagnostic_jobs(config):
    spec = config.get("diagnostics")
    if not spec: return []
    root = Path(config["execution"]["output_root"]) / "main" / "diagnostics"
    jobs = []
    for model in spec["models"]:
        run = Path(model["run_dir"])
        if not run.is_absolute(): run = find_mesh_root() / run
        for mode in model.get("modes", ("deterministic", "sampled")):
            output = root / model["name"] / mode
            command = [sys.executable, "-m", "scripts.rl.evaluate", "--sim-binary",
                       config["execution"]["sim_binary"], "--run-dir", str(run), "--model", "best",
                       "--policies", "model", "--seeds", ",".join(map(str, spec["seeds"])),
                       "--output-dir", str(output), "--label", model["name"]]
            if mode == "sampled": command.append("--stochastic-model")
            if model.get("run_config"):
                command += ["--run-config", str(find_mesh_root() / model["run_config"]),
                            "--allow-different-scenario"]
            jobs.append({"id": f"diagnostics/{model['name']}/{mode}", "output": output,
                         "command": command})
    return jobs


def run_diagnostics(config, runner, record, record_path):
    jobs = diagnostic_jobs(config)
    if not jobs: return
    print(f"Starting main/diagnostics: {len(jobs)} saved-model evaluations; no retraining", flush=True)
    pool = ThreadPoolExecutor(max_workers=config["execution"]["max_workers"])
    pending = {}
    try:
        for job in jobs:
            manifest = job["output"] / "eval_manifest.json"
            if manifest.is_file():
                if json.loads(manifest.read_text())["status"] != "completed":
                    raise RuntimeError(f"incomplete diagnostic: {job['output']}; move it before retrying")
                record["jobs"][job["id"]] = {"status": "completed", "exit_code": 0, "reused": True}
                continue
            pending[pool.submit(runner.execute, job["command"], job["output"].with_suffix(".log"))] = job
        for future in as_completed(pending):
            job, code = pending[future], future.result()
            record["jobs"][job["id"]] = {"status": "completed" if code in (0,2) else "failed", "exit_code": code}
            write_json(record_path, record)
            print(f"{job['id']}: {'completed' if code in (0,2) else 'failed'}", flush=True)
            if code not in (0,2):
                runner.stop()
                raise RuntimeError(f"diagnostic failed: {job['output']}")
    except BaseException:
        runner.stop()
        for future in pending: future.cancel()
        raise
    finally:
        pool.shutdown(wait=True, cancel_futures=True)
    rows = []
    for job in jobs:
        block = json.loads((job["output"] / "eval_manifest.json").read_text())["policies"]["model"]
        done = block["episodes"]
        row = {"model": job["output"].parent.name, "mode": job["output"].name, "episodes": len(done)}
        for metric in ("delivery_ratio", "travel_m_total", "unsafe_proximity_fraction"):
            values = [episode["metrics"][metric] for episode in done]
            row[metric] = sum(values)/len(values)
        rows.append(row)
    path = Path(config["execution"]["output_root"]) / "main/diagnostics/summary.csv"
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
