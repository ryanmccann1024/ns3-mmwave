"""Run one planned operation, baseline or check; every result is written under --output-dir.

Subcommands: ``model`` (frozen or online operation of a saved policy on one
seed), ``baseline`` (hold / random_valid / scripted, or a verified import),
``preflight``, ``replay-gate`` and ``reward-audit`` (each writes
``check_result.json``). Exit 0 on success, 2 for evaluation health warnings
(revalidated slots or mask violations), 1 for any error, including usage errors.
"""

import argparse
import json
import sys

from scripts.rl.cli_common import add_decision_record_arguments, decision_records_from_args

MODES = ("frozen_deterministic", "frozen_sampled", "online_gated_v1", "online_sb3_v1")
OPERATION_SEED_ROLES = ("model_selection", "diagnostic", "held_out")
SEED_ROLES = ("training",) + OPERATION_SEED_ROLES
BASELINE_POLICIES = ("hold", "random_valid", "scripted")
PLACEMENT_POLICIES = ("geometric", "optimization")
REFERENCE_KINDS = ("scenario_routes_v1", "mission_waypoints_v1")
BANDS = ("mmwave", "sub-6")


class _Parser(argparse.ArgumentParser):
    """Usage errors exit 1: the scheduler accepts 2 as an evaluation warning."""

    def error(self, message):
        self.print_usage(sys.stderr)
        self.exit(1, f"{self.prog}: error: {message}\n")


def _json(text):
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise argparse.ArgumentTypeError(f"not valid JSON: {exc}") from exc


def _add_case_arguments(parser):
    parser.add_argument("--mission", help="Scenario case mission; required by gated and sampling-schedule "
                                          "operations, never inferred from run.ini")
    parser.add_argument("--coverage-target", type=float, help="Scenario case coverage target")


def _case(args):
    case = {}
    if args.mission is not None:
        case["mission"] = args.mission
    if args.coverage_target is not None:
        case["coverage_target"] = args.coverage_target
    if args.gate_s is not None:
        case["seeds"] = {str(args.seed): {"gate_s": args.gate_s}}
    return case


def _build_parser():
    parser = _Parser(prog="operate", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True, parser_class=_Parser)

    model = commands.add_parser("model", help="Operate a saved policy on one evaluation seed")
    model.add_argument("--sim-binary", required=True)
    model.add_argument("--run-dir", required=True)
    model.add_argument("--model", required=True, help="final, best or checkpoints/<name>.zip")
    model.add_argument("--mode", required=True, choices=MODES)
    model.add_argument("--operation-id", required=True)
    model.add_argument("--seed", required=True, type=int)
    model.add_argument("--seed-role", required=True, choices=OPERATION_SEED_ROLES)
    model.add_argument("--run-config", required=True)
    model.add_argument("--band", choices=BANDS)
    model.add_argument("--output-dir", required=True)
    model.add_argument("--protocol-settings-json", required=True, type=_json)
    model.add_argument("--schedule-json", type=_json)
    model.add_argument("--gate-s", type=float)
    model.add_argument("--binding", help="Scheduler model-binding JSON; required to operate a bound checkpoint "
                                         "whose training manifest is unfinished")
    _add_case_arguments(model)
    add_decision_record_arguments(model)

    baseline = commands.add_parser("baseline", help="Run or import one baseline policy on one seed")
    baseline.add_argument("--sim-binary", required=True)
    baseline.add_argument("--policy", required=True, choices=BASELINE_POLICIES + PLACEMENT_POLICIES)
    baseline.add_argument("--seed", required=True, type=int)
    baseline.add_argument("--seed-role", required=True, choices=SEED_ROLES)
    baseline.add_argument("--run-config", required=True)
    baseline.add_argument("--band", choices=BANDS)
    baseline.add_argument("--output-dir", required=True)
    baseline.add_argument("--reference-kind", choices=REFERENCE_KINDS)
    baseline.add_argument("--reference")
    baseline.add_argument("--gate-s", type=float)
    _add_case_arguments(baseline)
    add_decision_record_arguments(baseline)
    baseline.add_argument("--import-from")
    baseline.add_argument("--planning-seed", type=int,
                          help="Placement channel-planning seed; overrides [baseline] planning_seed (as evaluate)")
    baseline.add_argument("--allow-seed-overlap", action="store_true",
                          help="Placement only: allow the planning seed to equal the evaluation seed (as evaluate)")

    preflight = commands.add_parser("preflight", help="Scenario feature/difficulty check")
    preflight.add_argument("--check-id", required=True)
    preflight.add_argument("--sim-binary", required=True)
    preflight.add_argument("--seed-configs-json", required=True, type=_json)
    preflight.add_argument("--band", choices=BANDS)
    preflight.add_argument("--requirements", default="")
    preflight.add_argument("--reference-kind", choices=REFERENCE_KINDS)
    preflight.add_argument("--reference")
    preflight.add_argument("--output-dir", required=True)

    gate = commands.add_parser("replay-gate", help="Native saved-action replay gate")
    gate.add_argument("--check-id", required=True)
    gate.add_argument("--sim-binary", required=True)
    gate.add_argument("--seed-configs-json", required=True, type=_json)
    gate.add_argument("--band", choices=BANDS)
    gate.add_argument("--source", required=True, help="Source episode directory")
    gate.add_argument("--comparison", choices=("strict_v1", "pre_contact_source_v1"), default="strict_v1")
    gate.add_argument("--parent-run-dir", help="Completed parent training run for schema compatibility")
    gate.add_argument("--parent-model", default="final", help="Parent model selector (default final)")
    gate.add_argument("--case-json", type=_json, default={}, help="Scenario case, including verified event timing")
    gate.add_argument("--contact-audit", action="store_true", help="Verify native boundary-contact telemetry")
    gate.add_argument("--output-dir", required=True)

    audit = commands.add_parser("reward-audit", help="Reward reconstruction audit")
    audit.add_argument("--check-id", required=True)
    audit.add_argument("--source", required=True, help="Evaluation directory or episode directory")
    audit.add_argument("--method", required=True)
    audit.add_argument("--run-config", required=True)
    audit.add_argument("--observation-preset", required=True)
    audit.add_argument("--reward-components", required=True)
    audit.add_argument("--reward-weights", required=True)
    audit.add_argument("--observation-parameters", required=True, type=_json)
    audit.add_argument("--reward-parameters", required=True, type=_json)
    audit.add_argument("--output-dir", required=True)
    return parser


def _health_exit(manifest):
    episodes = [e for block in manifest["policies"].values() for e in block["episodes"]]
    if not episodes or any(e["status"] != "completed" for e in episodes):
        print("Not every evaluation episode completed", file=sys.stderr)
        return 1
    return 2 if sum((e["revalidated_slots_total"] or 0) + (e["mask_violations"] or 0) for e in episodes) else 0


def _model(args):
    from pathlib import Path
    from scripts.rl.policy import operation
    from scripts.rl.policy.bundle import read_bundle
    records = decision_records_from_args(args)
    if args.binding:
        bundle, binding = operation.bound_bundle(args.binding, args.run_dir, args.model)
    else:
        bundle, binding = read_bundle(args.run_dir, args.model), None
    operation.run_operation(
        bundle, {str(args.seed): args.run_config}, _case(args), args.mode, args.seed, args.seed_role, args.output_dir,
        args.sim_binary, protocol_settings=args.protocol_settings_json, schedule=args.schedule_json,
        evaluation_seeds=[args.seed], label=args.operation_id, band=args.band, decision_records=records,
        binding=binding,
        allow_different_scenario=operation.prevalidated_scenario_difference(bundle, args.run_config, args.gate_s))
    manifest = Path(args.output_dir) / "eval_manifest.json"
    return _health_exit(json.loads(manifest.read_text())) if manifest.is_file() else 0


def _placement_baseline(args):
    """Placement baselines run the existing evaluate placement path unchanged; it owns planning seeds."""
    from scripts.rl import evaluate
    from scripts.rl.policy import operation
    if args.import_from or args.reference or args.reference_kind:
        raise ValueError(f"{args.policy} plans its own layout; --import-from/--reference do not apply")
    if args.gate_s is not None:
        operation.resolve_gates({str(args.seed): args.run_config}, {"seeds": {str(args.seed): {"gate_s": args.gate_s}}})
    argv = ["--sim-binary", args.sim_binary, "--run-config", args.run_config, "--output-dir", args.output_dir,
            "--seeds", str(args.seed), "--policies", args.policy,
            "--label", f"baseline {args.policy} {args.seed_role} seed {args.seed}"]
    if args.band is not None:
        argv += ["--band", args.band]
    if args.planning_seed is not None:
        argv += ["--planning-seed", str(args.planning_seed)]
    if args.allow_seed_overlap:
        argv.append("--allow-seed-overlap")
    if args.decision_records:
        argv.append("--decision-records")
    for flag in ("every", "max_bytes", "obs_vector", "preferences"):
        value = getattr(args, "decision_records_" + flag)
        if value is not None:
            argv += ["--decision-records-" + flag.replace("_", "-"), str(value)]
    return evaluate.main(argv)


def _baseline(args):
    from scripts.rl.policy import operation
    if args.policy in PLACEMENT_POLICIES:
        return _placement_baseline(args)
    if args.planning_seed is not None or args.allow_seed_overlap:
        raise ValueError("--planning-seed and --allow-seed-overlap apply only to placement baselines")
    records = decision_records_from_args(args)
    if (args.reference is None) != (args.reference_kind is None):
        raise ValueError("--reference and --reference-kind go together")
    if args.import_from:
        manifest = operation.import_baseline(args.import_from, args.policy, args.seed, args.run_config,
                                             args.output_dir, band=args.band)
    else:
        manifest = operation.run_baseline(args.policy, args.seed, args.seed_role, args.run_config, args.output_dir,
                                          args.sim_binary, gate_s=args.gate_s, reference_kind=args.reference_kind,
                                          reference_path=args.reference, band=args.band, case=_case(args),
                                          decision_records=records)
    return _health_exit(manifest)


def _single_seed_config(configs):
    if not isinstance(configs, dict) or len(configs) != 1:
        raise ValueError("--seed-configs-json must map exactly one seed to its run.ini")
    (seed, ini), = configs.items()
    return int(seed), {str(seed): ini}


def _source_episode(source, seed):
    """An episode directory as given, or the one completed episode for ``seed`` in an evaluation directory."""
    from pathlib import Path
    manifest = Path(source) / "eval_manifest.json"
    if not manifest.is_file():
        return source
    episodes = [e for block in json.loads(manifest.read_text())["policies"].values() for e in block["episodes"]
                if int(e["seed"]) == seed and e["status"] == "completed"]
    if len(episodes) != 1:
        raise ValueError(f"{source} must hold exactly one completed episode for seed {seed}, found {len(episodes)}")
    return episodes[0]["episode_dir"]


def _preflight(args):
    raise ValueError("no single-case preflight adapter exists: preflight_campaign.py performs its feature "
                     "and stationary-difficulty checks inline in main() over a campaign.json, and requirement "
                     f"names {args.requirements.split(',') if args.requirements else []} have no defined checks")


def _replay_gate(args):
    from scripts.rl.policy.replay_gate import gate_passed, run_replay_gate
    from scripts.rl.policy.bundle import read_bundle
    seed, configs = _single_seed_config(args.seed_configs_json)
    if not isinstance(args.case_json, dict):
        raise ValueError("--case-json must be a JSON object")
    if args.parent_model != "final" and not args.parent_run_dir:
        raise ValueError("--parent-model requires --parent-run-dir")
    parent = read_bundle(args.parent_run_dir, args.parent_model) if args.parent_run_dir else None
    record = run_replay_gate(_source_episode(args.source, seed), configs, args.case_json, seed,
                             args.output_dir, args.sim_binary, bundle=parent, comparison=args.comparison,
                             contact_audit=args.contact_audit, label=f"replay gate {args.check_id}", band=args.band)
    return gate_passed(args.output_dir), dict(replay_gate="replay_gate.json", **{
        k: record.get(k) for k in ("seed", "comparison", "decisions", "source_steps_sha256",
                                   "replay_steps_sha256", "episode_dir", "parent", "case", "compatibility",
                                   "boundary", "event_timing")})


def _reward_audit(args):
    from pathlib import Path
    from scripts.artifact_io import sha256_file
    from scripts.rl.env.config import read_scenario_identity
    from scripts.rl.policy.reward_audit import AUDIT_METHODS, baseline_audit
    if args.method not in AUDIT_METHODS:
        raise ValueError(f"unknown reward audit method {args.method!r}; expected one of {sorted(AUDIT_METHODS)}")
    selection = dict(observation_preset=args.observation_preset,
                     reward_components=args.reward_components.split(","),
                     reward_weights=[float(w) for w in args.reward_weights.split(",")],
                     observation_parameters=args.observation_parameters, reward_parameters=args.reward_parameters)
    source = Path(args.source)
    if (source / "eval_manifest.json").is_file():
        manifest = json.loads((source / "eval_manifest.json").read_text())
        if manifest.get("status") != "completed":
            raise ValueError(f"{source} is not a completed evaluation")
        live = read_scenario_identity(args.run_config)
        recorded = manifest.get("scenario_identity") or {}
        geometry = [k for k in ("nodes_json_sha256", "buildings_json_sha256") if recorded.get(k) != live.get(k)]
        if geometry:
            raise ValueError(f"{source} geometry {geometry} differs from {args.run_config}")
    else:
        metadata = json.loads((source / "rl_episode.json").read_text())
        manifest = {"policies": {"episode": {"episodes": [{"seed": metadata["seed"], "episode_dir": str(source)}]}}}
    results = baseline_audit(manifest, selection, args.method)
    return True, dict(method=args.method, selection=selection, results=results,
                      source=str(source), run_config_sha256=sha256_file(args.run_config))


CHECKS = {"preflight": ("preflight", _preflight), "replay-gate": ("replay_gate", _replay_gate),
          "reward-audit": ("reward_audit", _reward_audit)}


def main(argv=None):
    args = _build_parser().parse_args(argv)
    try:
        if args.command == "model":
            return _model(args)
        if args.command == "baseline":
            return _baseline(args)
        from scripts.rl.policy.operation import write_check_result
        kind, run = CHECKS[args.command]
        try:
            passed, evidence = run(args)
        except Exception as exc:
            write_check_result(args.output_dir, check_id=args.check_id, kind=kind, passed=False,
                               evidence={"error": f"{type(exc).__name__}: {exc}"}, warnings=[])
            raise
        write_check_result(args.output_dir, check_id=args.check_id, kind=kind, passed=passed,
                           evidence=evidence, warnings=[])
        return 0 if passed else 1
    except Exception as exc:
        print(f"operate {args.command}: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
