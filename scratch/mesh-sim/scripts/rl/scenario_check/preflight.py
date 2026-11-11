"""Check simulator features and stationary scenario difficulty before a campaign."""

import argparse
import json
import math
from pathlib import Path

from scripts.rl.policy.evaluate import evaluate, PolicySpec, Prepared, HoldPolicy
from scripts.artifact_io import sha256_file, write_json
from scripts.rl.env.config import read_scenario_identity
from scripts.rl.env.mesh_env import MeshRlEnv
from scripts.rl.env.selection import resolve_selection
from scripts.rl.scenario_check.defaults import EVALUATION_SEEDS


def criteria(base):
    """Read optional challenge checks, preserving the original campaign defaults."""
    return _criteria(json.loads((base / "campaign.json").read_text()))


def _criteria(campaign):
    raw = campaign.get("preflight", {})
    if not isinstance(raw, dict) or set(raw) - {"seeds", "challenge_delivery_max"}:
        raise ValueError("preflight supports seeds and challenge_delivery_max only")
    seeds = raw.get("seeds", [EVALUATION_SEEDS[0]])
    if (
        not isinstance(seeds, list)
        or not seeds
        or any(
            isinstance(seed, bool) or not isinstance(seed, int) or seed < 1
            for seed in seeds
        )
        or len(set(seeds)) != len(seeds)
    ):
        raise ValueError("preflight.seeds must be distinct positive integers")
    maximum = raw.get("challenge_delivery_max")
    if maximum is not None and (
        isinstance(maximum, bool)
        or not isinstance(maximum, (int, float))
        or not math.isfinite(maximum)
        or not 0 <= maximum < 0.999
    ):
        raise ValueError("preflight.challenge_delivery_max must be finite in [0, .999)")
    return {"seeds": seeds, "challenge_delivery_max": maximum}


def signature(base, binary):
    campaign = json.loads((base / "campaign.json").read_text())
    return _signature(base, binary, campaign, _criteria(campaign))


def _signature(base, binary, campaign, rules):
    result = {
        "binary_sha256": sha256_file(binary),
        "scenarios": {
            name: read_scenario_identity(str(base / name / "run.ini"))
            for name in campaign["scenarios"]
        },
    }
    if "preflight" in campaign:
        result["criteria"] = rules
    return result


def check_difficulty(name, episodes, maximum):
    """Require saturated hold fixtures and, when configured, degraded challenge service."""
    for episode in episodes:
        metrics = episode["metrics"]
        if name.endswith("-hold"):
            if (
                metrics["delivery_ratio"] < 0.999
                or metrics["coverage_fraction_mean"] < 0.999
            ):
                raise RuntimeError(
                    f"{name}: hold fixture is not saturated in service and coverage; calibrate before training"
                )
        elif maximum is not None and metrics["delivery_ratio"] > maximum:
            raise RuntimeError(
                f"{name}: stationary delivery {metrics['delivery_ratio']:.3f} exceeds {maximum}; calibrate before training"
            )


def _probe_features(name, ini, binary, output, selection, seed, maximum):
    env = MeshRlEnv(
        str(binary),
        str(ini),
        seed=seed,
        output_dir=output,
        selection=selection,
    )
    try:
        env.reset()
        if (
            env.contract.get("unsafe_separation_m") != 1.0
            or "coverage" not in env.contract
            or not env.contract.get("avoid_buildings")
        ):
            raise RuntimeError(
                "binary lacks coverage, 1m separation, or building-mask support; rebuild the simulator"
            )
        if "coverage" not in env._protocol.facts:
            raise RuntimeError("binary did not emit measured coverage facts")
        if maximum is not None and "jammer" in name:
            if not any(link[0] < -6.7 for link in env._protocol.facts["links"]):
                raise RuntimeError(
                    f"{name}: jammer does not create failed links; rebuild with negative-SINR fix and calibrate"
                )
    finally:
        env.close()


def _evaluate_hold(name, ini, binary, target, selection, seeds):
    def make_env(_policy):
        return MeshRlEnv(
            str(binary),
            str(ini),
            seed=seeds[0],
            output_dir=target / "episodes",
            selection=selection,
        )

    manifest = evaluate(
        make_env,
        [PolicySpec("hold", lambda env, seed: Prepared(HoldPolicy()))],
        seeds,
        target,
        {
            "run_config": str(ini),
            "sim_binary": str(binary),
            "scenario_identity": read_scenario_identity(str(ini)),
        },
    )
    if manifest["status"] != "completed":
        raise RuntimeError(f"{name}: hold preflight failed ({manifest['status']})")
    return manifest["policies"]["hold"]["episodes"]


def run_preflight(base, root, binary, expected, rules, evaluate_hold):
    report = root / "preflight.json"
    root.mkdir(parents=True, exist_ok=True)
    result = {"status": "running", "signature": expected, "checks": {}}
    write_json(report, result)
    try:
        for name in expected["scenarios"]:
            ini = base / name / "run.ini"
            selection = resolve_selection(str(ini))
            _probe_features(
                name,
                ini,
                binary,
                root / "features" / name,
                selection,
                rules["seeds"][0],
                rules["challenge_delivery_max"],
            )
            episodes = evaluate_hold(
                name, ini, binary, root / name, selection, rules["seeds"]
            )
            result["checks"][name] = episodes[0]["metrics"]
            if len(episodes) > 1:
                result["checks"][name] = {
                    **episodes[0]["metrics"],
                    "episodes": episodes,
                }
            check_difficulty(name, episodes, rules["challenge_delivery_max"])
            write_json(report, result)
        result["status"] = "passed"
    except Exception as exc:
        result.update(status="failed", error=f"{type(exc).__name__}: {exc}")
        write_json(report, result)
        print(result["error"], flush=True)
        return 1
    write_json(report, result)
    print(
        "Preflight passed: hold fixtures healthy and configured challenge checks satisfied.",
        flush=True,
    )
    return 0


def main(argv=None, *, evaluate_hold=_evaluate_hold):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", required=True, type=Path)
    parser.add_argument("--sim-binary", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify a completed matching preflight without simulating",
    )
    args = parser.parse_args(argv)
    base, root = args.inputs.resolve(), args.output_root.resolve()
    try:
        campaign = json.loads((base / "campaign.json").read_text())
        rules = _criteria(campaign)
        expected = _signature(base, args.sim_binary.resolve(), campaign, rules)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    report = root / "preflight.json"
    if args.check:
        saved = json.loads(report.read_text()) if report.is_file() else {}
        if saved.get("signature") != expected or saved.get("status") != "passed":
            parser.error(
                "run preflight with this binary and unchanged scenario inputs before training"
            )
        return 0
    if report.exists():
        parser.error("preflight already exists; use a fresh output root to rerun")
    return run_preflight(
        base, root, args.sim_binary.resolve(), expected, rules, evaluate_hold
    )


if __name__ == "__main__":
    raise SystemExit(main())
