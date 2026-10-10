"""Standalone baseline preparation and simulator process lifecycle."""

import os
import signal
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from scripts.baselines import artifacts, config, preparation
from scripts.sim_support import find_mesh_root, parse_seed_spec, simulator_env, tail_lines


@dataclass(frozen=True)
class RunSettings:
    """Standalone run options supplied by the CLI or another caller."""

    sim_binary: str
    run_config: str
    seeds: str | None = None
    algorithm: str | None = None
    output_dir: str | None = None
    band: str | None = None
    planner_source: str | None = None


OUTPUT_LABEL = "baseline"
# Mirrors the [scenario] seed default in src/config/config-loader.cc.
DEFAULT_SCENARIO_SEED = 42
TERMINATE_WAIT_S = 10.0
SIM_LOG_TAIL_LINES = 40
_SIGNALS = (signal.SIGINT, signal.SIGTERM)


class _Interrupted(BaseException):
    """SIGINT or SIGTERM arrived; unwinds to the runner's cleanup path."""

    def __init__(self, signum: int):
        super().__init__(signum)
        self.signum = signum


def _raise_interrupted(signum, frame):
    for selected in _SIGNALS:
        signal.signal(selected, signal.SIG_IGN)
    raise _Interrupted(signum)


def automatic_output_root(mesh_root: str | Path, now: datetime | None = None) -> Path:
    """Fresh outputs/YYYY-MM/DD/HH-MM-SS-baseline[-N] path, named like the RL tools' roots."""
    now = now or datetime.now()
    parent = Path(mesh_root) / "outputs" / now.strftime("%Y-%m") / now.strftime("%d")
    stem = f"{now:%H-%M-%S}-{OUTPUT_LABEL}"
    candidate = parent / stem
    suffix = 2
    while candidate.exists():
        candidate = parent / f"{stem}-{suffix}"
        suffix += 1
    return candidate


def resolve_seeds(raw: str | None, run_config: str | Path) -> list[int]:
    """--seeds when given, otherwise the INI's [scenario] seed (or the simulator default)."""
    if raw is not None:
        return parse_seed_spec(raw)
    value = config.ini_value(config.read_ini(run_config), "scenario", "seed")
    if value is None:
        return [DEFAULT_SCENARIO_SEED]
    if not value.isdigit():
        raise ValueError(f"[scenario] seed in {run_config} is not a non-negative integer: "
                         f"{value!r}")
    return [int(value)]


def _check_inputs(args) -> tuple[str, Path]:
    binary = Path(args.sim_binary)
    if not binary.is_file() or not os.access(binary, os.X_OK):
        raise ValueError(f"--sim-binary {binary} is not an executable file")
    if not Path(args.run_config).is_file():
        raise ValueError(f"--run-config {args.run_config} does not exist")
    run_dir = Path(args.output_dir) if args.output_dir else automatic_output_root(
        find_mesh_root())
    run_dir = run_dir.resolve()
    if run_dir.exists() and (not run_dir.is_dir() or any(run_dir.iterdir())):
        raise ValueError(f"Refusing to start: {run_dir} exists and is not empty")
    return str(binary.resolve()), run_dir


def sim_command(binary: str, run_config: Path, run_dir: Path, seeds: list[int] | None,
                band: str | None) -> list[str]:
    """Simulator argv; --seeds and --band appear only when the caller gave them."""
    command = [binary, f"--run-config={run_config}", f"--output-dir={run_dir}"]
    if seeds is not None:
        command.append("--seeds=" + ",".join(str(seed) for seed in seeds))
    if band is not None:
        command.append(f"--band={band}")
    return command


def seed_records(run_dir: Path, seeds: list[int], absent: str) -> list[dict]:
    """One record per seed; a seed without seed-N/summary.json gets status `absent`."""
    records = []
    for seed in seeds:
        summary = f"seed-{seed}/summary.json"
        if (run_dir / summary).is_file():
            records.append(artifacts.seed_record(seed, "complete", summary))
        else:
            records.append(artifacts.seed_record(seed, absent, None))
    return records


def stop_child(proc: subprocess.Popen, wait_s: float = TERMINATE_WAIT_S) -> None:
    """Terminate, kill after `wait_s`, and always reap."""
    if proc.poll() is not None:
        proc.wait()
        return
    try:
        proc.terminate()
    except ProcessLookupError:
        pass
    try:
        proc.wait(timeout=wait_s)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


def _exit_status(returncode: int) -> int:
    return returncode if returncode > 0 else 128 - returncode


def _finish(manifest: Path, run_dir: Path, seeds: list[int], returncode: int) -> int:
    log = run_dir / artifacts.SIM_LOG_NAME
    if returncode != 0:
        artifacts.set_seed_records(manifest, seed_records(run_dir, seeds, "failed"))
        artifacts.set_status(manifest, "failed", error=(
            f"simulator exited with code {returncode}; last lines of "
            f"{artifacts.SIM_LOG_NAME}:\n{tail_lines(log, SIM_LOG_TAIL_LINES)}"))
        return _exit_status(returncode)
    records = seed_records(run_dir, seeds, "missing")
    artifacts.set_seed_records(manifest, records)
    missing = [str(record["seed"]) for record in records if record["status"] != "complete"]
    if missing:
        artifacts.set_status(manifest, "failed", error=(
            f"simulator exited 0 but seed(s) {', '.join(missing)} have no "
            "seed-N/summary.json"))
        return 1
    artifacts.set_status(manifest, "complete")
    return 0


def _mark_interrupted(manifest: Path, run_dir: Path, seeds: list[int], signum: int,
                      started: bool) -> None:
    if not manifest.is_file():
        return
    if artifacts.read_json(manifest).get("status") in artifacts.TERMINAL_STATUSES:
        return
    if started:
        artifacts.set_seed_records(manifest, seed_records(run_dir, seeds, "missing"))
    artifacts.set_status(manifest, "interrupted",
                         error=f"interrupted by {signal.Signals(signum).name}")


def run(args, binary: str, seeds: list[int], run_dir: Path) -> int:
    """Lifecycle after argument checks: prepare, launch, wait, record the outcome."""
    manifest = run_dir / artifacts.MANIFEST_NAME
    proc = None
    try:
        try:
            prepared = preparation.prepare(args.run_config, args.algorithm, run_dir,
                                           mode="standalone", planner_source=args.planner_source,
                                           band=args.band, simulation_seeds=seeds,
                                           sim_binary=binary)
        except preparation.BaselinePreparationError as exc:
            print(f"Baseline preparation failed: {exc}", file=sys.stderr)
            return 1
        command = sim_command(binary, prepared.effective_run_config, run_dir,
                              seeds if args.seeds is not None else None, args.band)
        with open(run_dir / artifacts.SIM_LOG_NAME, "w", encoding="utf-8") as log:
            try:
                proc = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=log,
                                        stderr=subprocess.STDOUT,
                                        env=simulator_env(find_mesh_root()))
            except OSError as exc:
                artifacts.set_status(manifest, "failed",
                                     error=f"cannot start the simulator: {exc}")
                print(f"Cannot start the simulator: {exc}", file=sys.stderr)
                return 1
            try:
                artifacts.set_status(manifest, "running")
                returncode = proc.wait()
            finally:
                stop_child(proc)
        code = _finish(manifest, run_dir, seeds, returncode)
    except _Interrupted as stop:
        for signum in _SIGNALS:
            signal.signal(signum, signal.SIG_IGN)
        if proc is not None:
            stop_child(proc)
        _mark_interrupted(manifest, run_dir, seeds, stop.signum, proc is not None)
        print(f"Interrupted by {signal.Signals(stop.signum).name}: {run_dir}", file=sys.stderr)
        return 128 + stop.signum
    except Exception as exc:
        message = f"{type(exc).__name__}: {exc}"
        print(f"Baseline run failed: {message}", file=sys.stderr)
        try:
            status = artifacts.read_json(manifest).get("status") if manifest.is_file() else None
            if status is not None and status not in artifacts.TERMINAL_STATUSES:
                artifacts.set_seed_records(manifest, seed_records(run_dir, seeds, "failed"))
                artifacts.set_status(manifest, "failed", error=message)
        except Exception as record_error:
            print(f"Could not record baseline failure: {record_error}", file=sys.stderr)
        return 1
    status = artifacts.read_json(manifest)["status"]
    print(f"Baseline run {status}: {run_dir}", file=sys.stderr if code else sys.stdout)
    return code


def execute(args: RunSettings) -> int:
    try:
        binary, run_dir = _check_inputs(args)
        seeds = resolve_seeds(args.seeds, args.run_config)
    except ValueError as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    if args.output_dir is None:
        print(f"Baseline output: {run_dir}", flush=True)
    previous = {signum: signal.signal(signum, _raise_interrupted) for signum in _SIGNALS}
    try:
        return run(args, binary, seeds, run_dir)
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)
