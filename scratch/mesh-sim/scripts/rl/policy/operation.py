"""Operate one saved policy on one evaluation seed: frozen or online, with its record.

Modes (protocols) are separately named and never merged:

- ``frozen_deterministic`` / ``frozen_sampled`` -- no optimizer; the parameter
  **and** optimizer digests must be unchanged after the episode. An optional
  frozen schedule (``schedules.py``) switches sampling; it is not learning.
- ``online_gated_v1`` -- manual eligible-window PPO updates (``online_adaptation.py``).
- ``online_sb3_v1`` -- the SB3 ``learn()`` protocol: defaults
  ``learning_rate = min(parent, 1e-4)``, ``ent_coef = .001``,
  ``target_kl = .02``; budget = the native episode's decisions; untrained tail
  = ``budget % n_steps`` (``MissionBudgetCallback`` stops at the exact budget).

Each online operation reloads its parent model and optimizer for its own seed;
no learning is carried between evaluation seeds.

Records. :func:`run_operation` writes ``online_manifest.json`` with
``online_experiment_version`` 5 and an explicit ``protocol``. The standalone
CLI keeps its legacy envelope through :func:`run_online`: version 3 for the
default ``('fixed_sampled', 'online')`` tuple and version 4 for any other
subset/order. Version 4 alone never identifies a protocol -- gated campaign
writers also wrote version 4 -- so only version 5's ``protocol`` field does.
"""

from pathlib import Path
from types import SimpleNamespace

from scripts.artifact_io import now_iso, sha256_file, write_json
from scripts.rl.policy import bundle as _bundle
from scripts.rl.policy.evaluate import ModelPolicy, episode_metrics
from scripts.rl.policy.baseline_execution import import_baseline as import_baseline
from scripts.rl.policy.baseline_execution import run_baseline as run_baseline
from scripts.rl.policy.operation_checks import (
    check_result_passed as check_result_passed,
)
from scripts.rl.policy.operation_checks import write_check_result as write_check_result
from scripts.rl.policy.operation_inputs import DiagnosticEnv as DiagnosticEnv
from scripts.rl.policy.operation_inputs import OperationEnv
from scripts.rl.policy.operation_inputs import bound_bundle as bound_bundle
from scripts.rl.policy.operation_inputs import decision_recording as decision_recording
from scripts.rl.policy.operation_inputs import native_gate_s as native_gate_s
from scripts.rl.policy.operation_inputs import (
    prevalidated_scenario_difference as prevalidated_scenario_difference,
)
from scripts.rl.policy.operation_inputs import resolve_gates as resolve_gates
from scripts.rl.policy.sb3_operation import DEFAULT_MODES as DEFAULT_MODES
from scripts.rl.policy.sb3_operation import ONLINE_MANIFEST_NAME
from scripts.rl.policy.sb3_operation import UpdateRecorder as UpdateRecorder
from scripts.rl.policy.sb3_operation import operation_modes as operation_modes
from scripts.rl.policy.sb3_operation import run_online as run_online
from scripts.rl.policy.sb3_operation import sb3_collaborators as sb3_collaborators
from scripts.rl.policy.sb3_operation import sb3_operate as sb3_operate
from scripts.rl.policy.sb3_operation import sb3_settings as sb3_settings

ONLINE_MANIFEST_VERSION = 5
WEIGHT_AUDIT_NAME = "weight_audit.json"
FROZEN_MODES = ("frozen_deterministic", "frozen_sampled")
ONLINE_PROTOCOLS = ("online_gated_v1", "online_sb3_v1")
OPERATION_MODES = FROZEN_MODES + ONLINE_PROTOCOLS
SAMPLING_SCHEDULES = ("initial-sampling", "stall-burst")


def resolved_band(bundle, band):
    """``(band, source)`` a model operation requests: the CLI value, else the parent's band, as ``evaluate`` does."""
    return (band, "cli") if band else (bundle.manifest.get("band"), "parent")


def _relative(path, root):
    return Path(path).resolve().relative_to(Path(root).resolve()).as_posix()


def _resolve_protocol(mode, bundle, protocol_settings, schedule):
    from scripts.rl.policy.online_adaptation import gated_settings
    from scripts.rl.policy.schedules import validate_schedule

    if mode not in OPERATION_MODES:
        raise ValueError(
            f"unknown operation mode {mode!r}; expected one of {OPERATION_MODES}"
        )
    schedule = validate_schedule(schedule)
    if schedule is not None and mode not in FROZEN_MODES:
        raise ValueError("a frozen schedule cannot be combined with an online protocol")
    given = dict(protocol_settings or {})
    hyperparameters = bundle.manifest.get("hyperparameters") or {}
    if mode in FROZEN_MODES:
        if given:
            raise ValueError(f"{mode} takes no protocol settings, got {sorted(given)}")
        return {}, schedule
    for key in ("n_steps", "batch_size"):
        if key not in given:
            raise ValueError(f"{mode} requires explicit {key}")
    if mode == "online_gated_v1":
        unknown = set(given) - {"n_steps", "batch_size", "target_kl"}
        if unknown:
            raise ValueError(
                f"online_gated_v1 settings are inherited; cannot override {sorted(unknown)}"
            )
        if given.get("target_kl") is not None:
            raise ValueError("online_gated_v1 requires target_kl = null")
        return gated_settings(
            hyperparameters, given["n_steps"], given["batch_size"]
        ), schedule
    unknown = set(given) - {
        "n_steps",
        "batch_size",
        "learning_rate",
        "ent_coef",
        "target_kl",
    }
    if unknown:
        raise ValueError(f"unknown online_sb3_v1 settings {sorted(unknown)}")
    return sb3_settings(
        hyperparameters,
        given["n_steps"],
        given["batch_size"],
        given.get("learning_rate"),
        given.get("ent_coef"),
        given.get("target_kl"),
    ), schedule


def run_operation(
    bundle,
    configs,
    case,
    mode,
    seed,
    seed_role,
    output_dir,
    sim_binary,
    *,
    protocol_settings=None,
    schedule=None,
    evaluation_seeds=None,
    allow_different_scenario=False,
    label=None,
    band=None,
    decision_records=None,
    binding=None,
):
    """Operate ``bundle`` for one seed in ``mode`` and return its record.

    ``configs`` maps seed keys to native ``run.ini`` files; ``case`` carries the
    mission (and ``coverage_target`` for coverage). ``output_dir`` is a fresh
    attempt directory. Online and scheduled operations, and ``frozen_sampled``,
    write ``online_manifest.json`` v5; every mode writes ``weight_audit.json``.
    ``band`` is forwarded as the simulator's ``--band`` (None: the parent's band,
    as ``evaluate`` does); ``decision_records`` is a ``DecisionRecordSettings``.
    Both are recorded in ``settings``. ``binding`` (``{path, sha256}`` from
    :func:`bound_bundle`) is recorded with the parent.
    """
    from scripts.rl.env.config import read_scenario_identity
    from scripts.rl.policy.schedules import schedule_metadata

    output = Path(output_dir)
    if output.exists() and any(output.iterdir()):
        raise ValueError(
            f"refusing to overwrite operation output {output}; use a new attempt directory"
        )
    seed = int(seed)
    seeds = [int(s) for s in (evaluation_seeds or [seed])]
    if seed not in seeds:
        raise ValueError(
            f"seed {seed} is not one of the declared evaluation seeds {seeds}"
        )
    if str(seed) not in {str(k) for k in configs}:
        raise ValueError(f"no run.ini declared for seed {seed}")
    settings, schedule = _resolve_protocol(mode, bundle, protocol_settings, schedule)
    needs_mission = mode == "online_gated_v1" or (
        schedule is not None and schedule["kind"] in SAMPLING_SCHEDULES
    )
    if needs_mission and not (case or {}).get("mission"):
        raise ValueError(
            f"{mode}{' with ' + schedule['kind'] if schedule else ''} needs the scenario case mission; "
            "eligibility and strict success depend on it and it is never inferred"
        )
    if mode == "online_sb3_v1" and seed == bundle.manifest.get("seed"):
        raise ValueError("online operation cannot reuse the training seed")
    output.mkdir(parents=True, exist_ok=True)
    config = str(configs[str(seed)])
    settings = dict(settings)
    settings["band"], settings["band_source"] = resolved_band(bundle, band)
    settings["decision_records"] = (
        decision_records.describe() if decision_records is not None else None
    )
    record = dict(
        online_experiment_version=ONLINE_MANIFEST_VERSION,
        protocol=mode,
        status="running",
        started_at=now_iso(),
        ended_at=None,
        error=None,
        label=label,
        seed=seed,
        seed_role=seed_role,
        evaluation_seeds=seeds,
        settings=settings,
        schedule=schedule_metadata(schedule),
        allow_different_scenario=allow_different_scenario,
        parent={**bundle.describe(), "binding": binding},
        run_config=config,
        scenario_identity=read_scenario_identity(config),
        binary_sha256=sha256_file(sim_binary),
        model=None,
        optimizer=None,
        accounting=None,
        evaluation=None,
        episodes=[],
    )
    writes_record = mode != "frozen_deterministic" or schedule is not None
    record_path = output / ONLINE_MANIFEST_NAME

    def save():
        if writes_record:
            write_json(record_path, record)

    save()
    try:
        if mode == "online_sb3_v1":
            run = _sb3_operation(
                bundle,
                sim_binary,
                config,
                seed,
                output,
                settings,
                allow_different_scenario,
                settings["band"],
                decision_records,
            )
        else:
            run = _evaluated_operation(
                bundle,
                sim_binary,
                configs,
                case,
                mode,
                seed,
                seeds,
                output,
                settings,
                schedule,
                allow_different_scenario,
                label,
                seed_role,
                config,
                settings["band"],
                decision_records,
                binding,
            )
        audit = dict(
            initial_parameter_sha256=run["initial_parameter_sha256"],
            final_parameter_sha256=run["final_parameter_sha256"],
            initial_optimizer_sha256=run["initial_optimizer_sha256"],
            final_optimizer_sha256=run["final_optimizer_sha256"],
            **run["accounting"],
        )
        write_json(output / WEIGHT_AUDIT_NAME, audit)
        episode_dir = _relative(run["episode_dir"], output)
        record.update(
            model=dict(
                initial_parameter_sha256=run["initial_parameter_sha256"],
                final_parameter_sha256=run["final_parameter_sha256"],
                adapted_model=run.get("adapted_model"),
                adapted_model_sha256=run.get("adapted_model_sha256"),
            ),
            optimizer=dict(
                initial_optimizer_sha256=run["initial_optimizer_sha256"],
                final_optimizer_sha256=run["final_optimizer_sha256"],
            ),
            accounting=run["accounting"],
            evaluation=dict(
                eval_manifest=run.get("eval_manifest"),
                episode_dir=episode_dir,
                decisions=run["decisions"],
                weight_audit=WEIGHT_AUDIT_NAME,
                steps_sha256=sha256_file(Path(run["episode_dir"]) / "steps.jsonl"),
            ),
            episodes=[
                dict(
                    mode=mode,
                    seed=seed,
                    episode_dir=episode_dir,
                    decisions=run["decisions"],
                    metrics=run["metrics"],
                    **{"return": run["return"]},
                    **audit,
                )
            ],
            status="completed",
            ended_at=now_iso(),
        )
        save()
        return record
    except BaseException as exc:
        record.update(
            status="interrupted" if isinstance(exc, KeyboardInterrupt) else "failed",
            ended_at=now_iso(),
            error=f"{type(exc).__name__}: {exc}",
        )
        save()
        raise


def _sb3_operation(
    bundle,
    sim_binary,
    config,
    seed,
    output,
    settings,
    allow_different_scenario,
    band,
    decision_records,
):
    from scripts.rl.env.config import read_scenario_identity
    from scripts.rl.env.mesh_env import MeshRlEnv
    from scripts.rl.policy.compat import check_compatibility
    from scripts.rl.policy.episode_review import endpoint_metrics
    from scripts.rl.policy.reward_matrix import write_reward_matrix

    manifest = bundle.manifest
    selection = _bundle.eval_selection(_bundle.selection_from_manifest(manifest))
    live_band = band
    recording = decision_recording(
        decision_records, "model", _bundle.model_identity(bundle, False)
    )
    env = MeshRlEnv(
        sim_binary,
        config,
        seed=seed,
        output_dir=str(output),
        band=live_band,
        selection=selection,
        decision_records=recording,
    )
    try:
        initial = env.reset(seed=seed, options={"seed_source": "eval"})
        check_compatibility(
            manifest,
            env,
            live_identity=read_scenario_identity(config),
            live_band=live_band,
            allow_different_scenario=allow_different_scenario,
        )
        run = sb3_operate(bundle, env, initial, seed, output, settings, learn=True)
        metrics = {
            **episode_metrics(run.episode_dir, env.contract["num_links"]),
            **endpoint_metrics(run.episode_dir),
        }
    finally:
        env.close()
    write_reward_matrix(
        [
            SimpleNamespace(
                status="completed",
                seed=seed,
                decisions=run.budget,
                episode_dir=str(run.episode_dir),
            )
        ],
        output,
    )
    adapted = output / "adapted_model.zip"
    return dict(
        episode_dir=run.episode_dir,
        decisions=run.budget,
        metrics=metrics,
        **{"return": run.metadata["cumulative_reward"]},
        initial_parameter_sha256=run.initial_parameter_sha256,
        final_parameter_sha256=run.final_parameter_sha256,
        initial_optimizer_sha256=run.initial_optimizer_sha256,
        final_optimizer_sha256=run.final_optimizer_sha256,
        adapted_model=_relative(adapted, output),
        adapted_model_sha256=sha256_file(adapted),
        accounting=dict(
            update_cycles=len(run.events),
            optimizer_epochs=run.optimizer_epochs,
            episode_budget=run.budget,
            actual_decisions=run.metadata["steps"],
            untrained_tail_decisions=run.untrained_tail_decisions,
            tail_policy="budget % n_steps decisions after the last full rollout are not trained",
            weight_updates="weight_updates.json",
        ),
    )


def _evaluated_operation(
    bundle,
    sim_binary,
    configs,
    case,
    mode,
    seed,
    seeds,
    output,
    settings,
    schedule,
    allow_different_scenario,
    label,
    seed_role,
    config,
    band,
    decision_records,
    binding,
):
    from scripts.rl.env.config import read_scenario_identity
    from scripts.rl.policy.evaluate import PolicySpec, Prepared, evaluate
    from scripts.rl.policy.online_adaptation import OnlinePolicy
    from scripts.rl.policy.schedules import schedule_policy
    from scripts.rl.policy.training import mask_fn
    from scripts.rl.policy.preferences import PreferenceCapture

    online = mode == "online_gated_v1"
    deterministic = mode == "frozen_deterministic" and schedule is None
    tracked = []
    # Preferences are captured only from the plain frozen model; schedule/online policies act differently.
    capture = (
        PreferenceCapture()
        if decision_records is not None
        and decision_records.enabled
        and decision_records.preferences != "off"
        and not online
        and schedule is None
        else None
    )
    recording = decision_recording(
        decision_records,
        "model",
        _bundle.model_identity(bundle, deterministic),
        capture.take if capture is not None else None,
    )

    def build(env, seed):
        initial = env.reset(seed=seed, options={"seed_source": "eval"})
        model = _bundle.load_model(bundle, env.inner, mask_fn)
        if online:
            from scripts.rl.policy.online_adaptation import verify_inherited_settings

            verify_inherited_settings(model, settings)
        model.set_random_seed(seed)
        before = (
            _bundle.parameter_digest(model),
            _bundle.optimizer_digest(model),
            int(model._n_updates),
        )
        if schedule is not None:
            policy = schedule_policy(
                model,
                schedule,
                case,
                Path(env.inner._session._episode_dir),
                env.inner.contract,
                env.inner._protocol.facts,
            )
            env.observer = policy
        elif online:
            policy = OnlinePolicy(model, case["mission"], settings, output)
            env.observer = policy
        else:
            policy = ModelPolicy(
                model, capture=capture, deterministic=mode == "frozen_deterministic"
            )
        tracked.append((model, policy, before))
        return Prepared(
            policy,
            initial,
            dict(
                deterministic=deterministic,
                held_out=seed_role == "held_out",
                bundle={**bundle.describe(), "binding": binding},
                execution_schedule=schedule and schedule["kind"],
            ),
        )

    env_type = OperationEnv if online or schedule is not None else DiagnosticEnv
    base = dict(
        label=label or f"{mode} seed {seed}",
        training=bundle.describe(),
        bundle={**bundle.describe(), "binding": binding},
        sim_binary=str(sim_binary),
        run_config=config,
        band=settings["band"],
        scenario_identity=read_scenario_identity(config),
        seed_roles=dict(
            role=seed_role,
            training_seed=bundle.manifest.get("seed"),
            evaluation_seeds=seeds,
            held_out=seed_role == "held_out",
        ),
        deterministic=deterministic,
    )
    spec = PolicySpec(
        "model",
        build,
        dict(
            weights_frozen=not online,
            protocol=mode,
            model_selection=bundle.selection,
            execution_schedule=schedule and schedule["kind"],
        ),
    )
    manifest = evaluate(
        lambda policy: env_type(
            sim_binary,
            configs,
            output,
            case,
            initial_seed=seeds[0],
            bundle=bundle,
            allow_different_scenario=allow_different_scenario,
            band=band,
            decision_records=recording,
        ),
        [spec],
        [seed],
        output,
        base,
    )
    if manifest["status"] != "completed":
        raise RuntimeError(f"{mode} seed {seed}: evaluation did not complete")
    model, policy, (before, optimizer_before, updates_before) = tracked[0]
    after, optimizer_after = (
        _bundle.parameter_digest(model),
        _bundle.optimizer_digest(model),
    )
    episode = manifest["policies"]["model"]["episodes"][0]
    result = dict(
        episode_dir=Path(episode["episode_dir"]),
        decisions=episode["decisions"],
        metrics=episode["metrics"],
        eval_manifest="eval_manifest.json",
        **{"return": episode["return"]},
        initial_parameter_sha256=before,
        final_parameter_sha256=after,
        initial_optimizer_sha256=optimizer_before,
        final_optimizer_sha256=optimizer_after,
    )
    if online:
        verified = policy.verify()
        model.save(str(output / "adapted_model.zip"))
        adapted = output / "adapted_model.zip"
        result.update(
            adapted_model=_relative(adapted, output),
            adapted_model_sha256=sha256_file(adapted),
            accounting=dict(
                update_cycles=verified["update_cycles"],
                optimizer_steps=verified["optimizer_steps"],
                optimizer_epochs=int(model._n_updates) - updates_before,
                episode_decisions=policy.decisions,
                eligible_decisions=verified["eligible_decisions"],
                trained_decisions=verified["trained_decisions"],
                excluded_prefix_decisions=verified["excluded_prefix_decisions"],
                untrained_tail_decisions=verified["untrained_tail_decisions"],
                actor_change_l2=policy.events[-1]["actor_change_l2_from_start"],
                policy_parameters_changed=before != after,
                optimizer_state_changed=optimizer_before != optimizer_after,
                tail_policy="final partial rollout flushed; a singleton tail is skipped",
                weight_updates="weight_updates.json",
            ),
        )
    else:
        if before != after or optimizer_before != optimizer_after:
            raise RuntimeError(f"{mode} execution changed policy or optimizer state")
        result["accounting"] = dict(
            update_cycles=0, optimizer_steps=0, untrained_tail_decisions=0
        )
        if schedule is not None:
            result["accounting"]["schedule_events"] = list(policy.schedule.events)
    return result
