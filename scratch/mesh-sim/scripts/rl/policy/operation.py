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
import json
from pathlib import Path
from types import SimpleNamespace

from sb3_contrib import MaskablePPO
from sb3_contrib.common.wrappers import ActionMasker
from stable_baselines3.common.callbacks import BaseCallback
from stable_baselines3.common.logger import configure

from scripts.artifact_io import now_iso, sha256_file, write_json
from scripts.rl.env.seeded_env import SeededEnv
from scripts.rl.policy import bundle as _bundle
from scripts.rl.policy.evaluate import ModelPolicy, episode_metrics, run_episode

ONLINE_MANIFEST_NAME = "online_manifest.json"
ONLINE_MANIFEST_VERSION = 5
WEIGHT_AUDIT_NAME = "weight_audit.json"
FROZEN_MODES = ("frozen_deterministic", "frozen_sampled")
ONLINE_PROTOCOLS = ("online_gated_v1", "online_sb3_v1")
OPERATION_MODES = FROZEN_MODES + ONLINE_PROTOCOLS
DEFAULT_MODES = ("fixed_sampled", "online")
SB3_DEFAULTS = {"ent_coef": .001, "target_kl": .02}
SB3_LEARNING_RATE_CAP = .0001
SB3_PARENT_LEARNING_RATE_FALLBACK = .0003
_PPO_SCOPES = (("actor", ("mlp_extractor.policy_net", "action_net")),
               ("critic", ("mlp_extractor.value_net", "value_net")))


def native_gate_s(config):
    """The deployment gate the simulator will use; an absent key is the native default 0."""
    from scripts.sim_support import parse_ini
    value = parse_ini(config).get("rl", {}).get("control_start_s")
    return 0.0 if value is None else float(value)


def resolve_gates(configs, case):
    """Per-seed gates from the native INIs; a declared case gate must agree, a missing one is not invented."""
    declared = (case or {}).get("seeds") or {}
    seeds = {}
    for key, config in configs.items():
        native = native_gate_s(config)
        given = (declared.get(str(key)) or {}).get("gate_s")
        if given is not None and float(given) != native:
            raise ValueError(f"seed {key}: declared gate {given} s differs from native control_start_s {native} s")
        seeds[str(key)] = {**(declared.get(str(key)) or {}), "gate_s": native}
    return {**(case or {}), "seeds": seeds}


class DiagnosticEnv(SeededEnv):
    """Per-seed env that checks the bundle's schemas after each reset, before any model action."""

    def __init__(self, binary, configs, output, case, *, initial_seed, bundle=None, allow_different_scenario=True,
                 band=None, decision_records=None):
        self.bundle = bundle
        self.allow_different_scenario = allow_different_scenario
        self.compatibility = []
        super().__init__(binary, configs, Path(output), resolve_gates(configs, case), initial_seed=initial_seed,
                         band=band, decision_records=decision_records)

    def reset(self, *, seed, options=None):
        initial = super().reset(seed=seed, options=options)
        if self.case.get("mission") == "jamming":
            from scripts.rl.scenario_check.validation import jammer_timing
            verified = jammer_timing(self.configs[str(seed)], self.case, seed, self.inner._cmd)
            directory = next(Path(x.split("=", 1)[1]) for x in self.inner._cmd if x.startswith("--output-dir="))
            write_json(directory / "event_timing.json", verified)
        if self.bundle is not None:
            from scripts.rl.env.config import read_scenario_identity
            from scripts.rl.policy.compat import check_compatibility
            report = check_compatibility(self.bundle.manifest, self.inner,
                                         live_identity=read_scenario_identity(str(self.configs[str(seed)])),
                                         live_band=self.requested_band,
                                         allow_different_scenario=self.allow_different_scenario)
            self.compatibility.append(dict(seed=seed, **report.describe()))
            self.output.mkdir(parents=True, exist_ok=True)
            write_json(self.output / "compatibility.json", self.compatibility)
        return initial


class OperationEnv(DiagnosticEnv):
    """Diagnostic env that reports every transition and its native facts to ``observer``."""

    observer = None

    def step(self, action):
        result = self.inner.step(action)
        if self.observer is not None:
            obs, reward, terminated, truncated, info = result
            self.observer.observe(obs, reward, terminated, truncated, info, self.inner._protocol.facts)
        return result


class UpdateRecorder(BaseCallback):
    """Record actual parameter changes after each optimizer update cycle."""

    def __init__(self, path):
        super().__init__()
        self.path = Path(path)
        self.events = []

    def _on_training_start(self):
        self.start = self.model.num_timesteps
        self.last_updates = self.model._n_updates
        self.initial = {k: v.detach().cpu().clone() for k, v in self.model.policy.state_dict().items()}
        self.initial_digest = _bundle.parameter_digest(self.model)

    def record_update(self):
        if self.model._n_updates == self.last_updates:
            return
        state = self.model.policy.state_dict()
        delta = sum(float(((value.detach().cpu() - self.initial[key]) ** 2).sum()) for key, value in state.items()) ** .5
        changes = {scope + "_change_l2_from_start": sum(
                       float(((value.detach().cpu() - self.initial[key]) ** 2).sum())
                       for key, value in state.items() if key.startswith(prefixes)) ** .5
                   for scope, prefixes in _PPO_SCOPES}
        self.events.append({"decision": self.model.num_timesteps - self.start, **changes,
                            "optimizer_epochs": self.model._n_updates - self.last_updates,
                            "parameter_change_l2_from_start": delta,
                            "parameter_sha256": _bundle.parameter_digest(self.model)})
        self.last_updates = self.model._n_updates
        write_json(self.path, {"initial_parameter_sha256": self.initial_digest, "updates": self.events})

    def _on_rollout_start(self):
        self.record_update()

    def _on_step(self):
        return True

    def _on_training_end(self):
        self.record_update()


def operation_modes(values):
    """Validate the standalone CLI's legacy mode tuple."""
    modes = tuple(values)
    if not modes or len(set(modes)) != len(modes) or any(m not in DEFAULT_MODES for m in modes):
        raise ValueError("operation modes must be distinct fixed_sampled/online names")
    return modes


def sb3_settings(hyperparameters, n_steps, batch_size, learning_rate=None, ent_coef=None, target_kl=None):
    """Resolve ``online_sb3_v1`` settings; omitted values take the protocol defaults."""
    from scripts.rl.agents.config import validate_training_settings
    settings = {"n_steps": n_steps, "batch_size": batch_size,
                "learning_rate": (min(hyperparameters.get("learning_rate", SB3_PARENT_LEARNING_RATE_FALLBACK),
                                      SB3_LEARNING_RATE_CAP) if learning_rate is None else learning_rate),
                "target_kl": SB3_DEFAULTS["target_kl"] if target_kl is None else target_kl,
                "ent_coef": SB3_DEFAULTS["ent_coef"] if ent_coef is None else ent_coef}
    validate_training_settings(settings)
    if batch_size > n_steps or n_steps % batch_size:
        raise ValueError("online batch size must divide its rollout")
    return settings


def sb3_collaborators(**overrides):
    """The callables the SB3 protocol uses; the standalone CLI passes its own module names through."""
    from scripts.rl.env.config import read_scenario_identity
    from scripts.rl.env.mesh_env import MeshRlEnv
    from scripts.rl.policy.compat import check_compatibility
    from scripts.rl.policy.episode_review import endpoint_metrics
    from scripts.rl.policy.reward_matrix import write_reward_matrix
    names = dict(read_bundle=_bundle.read_bundle, selection_from_manifest=_bundle.selection_from_manifest,
                 eval_selection=_bundle.eval_selection, parameter_digest=_bundle.parameter_digest,
                 read_scenario_identity=read_scenario_identity, check_compatibility=check_compatibility,
                 MeshRlEnv=MeshRlEnv, MaskablePPO=MaskablePPO, ActionMasker=ActionMasker, configure=configure,
                 ModelPolicy=ModelPolicy, run_episode=run_episode, episode_metrics=episode_metrics,
                 endpoint_metrics=endpoint_metrics, write_reward_matrix=write_reward_matrix,
                 UpdateRecorder=UpdateRecorder, now_iso=now_iso, sha256_file=sha256_file, write_json=write_json)
    names.update(overrides)
    return SimpleNamespace(**names)


def sb3_operate(bundle, env, initial, seed, destination, settings, learn, collaborators=None, track_optimizer=True):
    """One SB3 episode on a reset, compatibility-checked env; ``learn`` selects online vs frozen sampled."""
    c = collaborators or sb3_collaborators()
    destination = Path(destination)
    budget = env.contract["num_decisions"]
    n_steps, batch_size = settings["n_steps"], settings["batch_size"]
    if n_steps > budget or n_steps < 2 or batch_size < 2:
        raise ValueError("online rollout must fit within the episode")
    model = c.MaskablePPO.load(bundle.model_path, env=c.ActionMasker(env, lambda e: e.unwrapped.action_masks()),
                               device="cpu", n_steps=n_steps, batch_size=batch_size,
                               learning_rate=settings["learning_rate"], ent_coef=settings["ent_coef"],
                               target_kl=settings["target_kl"])
    model.set_random_seed(seed)
    before = c.parameter_digest(model)
    optimizer_before = _bundle.optimizer_digest(model) if track_optimizer else None
    updates_before = int(model._n_updates) if track_optimizer else None
    events = []
    if not learn:
        result = c.run_episode(env, c.ModelPolicy(model, deterministic=False), seed, initial=initial)
        episode_dir = Path(result.episode_dir)
    else:
        model.set_logger(c.configure(str(destination / "ppo"), ["csv"]))
        callback = c.UpdateRecorder(destination / "weight_updates.json")
        callbacks = [callback]
        if budget % n_steps:
            from scripts.rl.agents.callbacks import MissionBudgetCallback
            callbacks.append(MissionBudgetCallback(model.num_timesteps + budget))
        model.learn(total_timesteps=budget, reset_num_timesteps=False, callback=callbacks)
        events = callback.events
        completed = [p.parent for p in destination.glob("episode-*/rl_episode.json")
                     if json.loads(p.read_text())["status"] == "completed"]
        if len(completed) != 1:
            raise RuntimeError("online operation must complete exactly one episode per seed")
        episode_dir = completed[0]
        if not events or c.parameter_digest(model) == before:
            raise RuntimeError("online PPO completed without changing neural parameters")
        model.save(str(destination / "adapted_model"))
    if not learn and c.parameter_digest(model) != before:
        raise RuntimeError("frozen sampled control changed neural parameters")
    metadata = json.loads((episode_dir / "rl_episode.json").read_text())
    if metadata["status"] != "completed" or metadata["steps"] != budget:
        raise RuntimeError("incomplete operation episode")
    return SimpleNamespace(model=model, episode_dir=episode_dir, metadata=metadata, budget=budget, events=events,
                           initial_parameter_sha256=before, final_parameter_sha256=c.parameter_digest(model),
                           initial_optimizer_sha256=optimizer_before,
                           final_optimizer_sha256=_bundle.optimizer_digest(model) if track_optimizer else None,
                           optimizer_epochs=int(model._n_updates) - updates_before if track_optimizer else None,
                           untrained_tail_decisions=budget % n_steps if learn else 0)


def run_online(run_dir, sim_binary, output, seeds, n_steps=120, batch_size=60,
               learning_rate=None, ent_coef=.001, target_kl=.02, model_selection="best", modes=DEFAULT_MODES,
               collaborators=None):
    """Standalone SB3 operation over several seeds, writing the legacy v3/v4 envelope unchanged.

    ``collaborators`` (see :func:`sb3_collaborators`) lets the standalone CLI keep its
    historical module-level names effective, including test substitutions.
    """
    c = collaborators or sb3_collaborators()
    modes = operation_modes(modes)
    bundle = c.read_bundle(run_dir, model_selection)
    manifest = bundle.manifest
    config = manifest["run_config"]
    selection = c.eval_selection(c.selection_from_manifest(manifest))
    settings = sb3_settings(manifest["hyperparameters"], n_steps, batch_size, learning_rate, ent_coef, target_kl)
    if set(seeds) & {manifest["seed"]}:
        raise ValueError("online operation cannot reuse the training seed")
    binary_digest = c.sha256_file(sim_binary)
    live_identity = c.read_scenario_identity(config)
    output = Path(output)
    record_path = output / ONLINE_MANIFEST_NAME
    if record_path.exists():
        previous = json.loads(record_path.read_text())
        if (previous["status"] == "completed" and previous["bundle"] == bundle.describe() and previous["seeds"] == seeds
                and previous.get("settings") == settings and previous.get("binary_sha256") == binary_digest
                and previous.get("scenario_identity") == live_identity
                and tuple(previous.get("modes", DEFAULT_MODES)) == modes):
            return previous
        raise ValueError(f"incomplete or changed online run at {output}; move it aside to retry")
    if output.exists() and any(output.iterdir()):
        raise ValueError(f"refusing to overwrite {output}")
    record = {"online_experiment_version": 3 if modes == DEFAULT_MODES else 4, "status": "running",
              "started_at": c.now_iso(), "bundle": bundle.describe(), "seeds": seeds, "episodes": [],
              "seed_roles": {"fixed_control": ("model-selection diagnostics; not held out"
                                               if set(seeds) & set((manifest.get("evaluation") or {}).get("seeds", []))
                                               else "held-out evaluation"),
                             "online": "adaptation experience; not learning-disabled evaluation"},
              "settings": settings, "binary_sha256": binary_digest, "scenario_identity": live_identity}
    if modes != DEFAULT_MODES:
        record["modes"] = list(modes)
    output.mkdir(parents=True, exist_ok=True)
    c.write_json(record_path, record)
    try:
        for mode in modes:
            results = []
            for seed in seeds:
                destination = output / mode / f"seed-{seed}"
                env = c.MeshRlEnv(sim_binary, config, seed=seed, output_dir=str(destination),
                                  band=manifest["band"], selection=selection)
                try:
                    initial = env.reset(seed=seed, options={"seed_source": "eval"})
                    c.check_compatibility(manifest, env, live_identity=c.read_scenario_identity(config),
                                          live_band=manifest["band"], allow_different_scenario=False)
                    run = sb3_operate(bundle, env, initial, seed, destination, settings, learn=mode == "online",
                                      collaborators=c, track_optimizer=False)
                    metrics = {**c.episode_metrics(run.episode_dir, env.contract["num_links"]),
                               **c.endpoint_metrics(run.episode_dir)}
                    record["episodes"].append({"mode": mode, "seed": seed, "episode_dir": str(run.episode_dir),
                                               "return": run.metadata["cumulative_reward"], "metrics": metrics,
                                               "initial_parameter_sha256": run.initial_parameter_sha256,
                                               "final_parameter_sha256": run.final_parameter_sha256,
                                               "update_cycles": len(run.events),
                                               "untrained_tail_decisions": run.untrained_tail_decisions})
                    results.append(SimpleNamespace(status="completed", seed=seed, decisions=run.budget,
                                                   episode_dir=str(run.episode_dir)))
                    c.write_json(record_path, record)
                finally:
                    env.close()
            c.write_reward_matrix(results, output / mode)
        record.update(status="completed", ended_at=c.now_iso())
        c.write_json(record_path, record)
        return record
    except BaseException as exc:
        record.update(status="failed", ended_at=c.now_iso(), error=f"{type(exc).__name__}: {exc}")
        c.write_json(record_path, record)
        raise


SAMPLING_SCHEDULES = ("initial-sampling", "stall-burst")
CHECK_RESULT_NAME = "check_result.json"
CHECK_RESULT_VERSION = 1
CHECK_KINDS = ("preflight", "replay_gate", "reward_audit")
SCENARIO_DIFFERENCE_ALLOWED = ("run_ini_sha256", "jammers_json_sha256")


def resolved_band(bundle, band):
    """``(band, source)`` a model operation requests: the CLI value, else the parent's band, as ``evaluate`` does."""
    return (band, "cli") if band else (bundle.manifest.get("band"), "parent")


def bound_bundle(binding_path, run_dir, model):
    """The bundle of a scheduler-verified binding, re-verified against its original bytes.

    ``run_dir``/``model`` must name exactly the bound run and model (``final``,
    ``best`` or ``checkpoints/<file>.zip``); the training manifest may be unfinished
    only because the binding pins its bytes. Returns ``(bundle, {path, sha256})``.
    """
    binding_path = Path(binding_path).resolve()
    if binding_path.parent.name != "bindings" or binding_path.parent.parent.name != "state":
        raise ValueError("--binding is scheduler-only and must be under a batch state/bindings directory")
    record = json.loads(binding_path.read_text())
    bundle = _bundle.read_bound_checkpoint(record)
    if Path(run_dir).resolve() != Path(record["run_dir"]).resolve():
        raise ValueError(f"--run-dir {run_dir} is not the bound run {record['run_dir']}")
    selection = record["model_selection"]
    named = model if model in ("final", "best") else "checkpoint"
    if named != selection or (selection == "checkpoint" and
                              (Path(run_dir) / model).resolve() != Path(record["model_path"]).resolve()):
        raise ValueError(f"--model {model} is not the bound {selection} model {record['model_path']}")
    return bundle, {"path": str(binding_path.resolve()), "sha256": sha256_file(binding_path)}


def decision_recording(settings, policy, model=None, preference_source=None):
    """The ``decision_records=`` value for an operation env, or None when records are off."""
    if settings is None or not settings.enabled:
        return None
    from scripts.rl.env.recording.decisions import DecisionContext
    from scripts.rl.env.recording.decisions import DecisionRecording
    return DecisionRecording(settings, DecisionContext(mode="evaluation", source="evaluate", policy=policy,
                                                       model=model, preference_source=preference_source))


def prevalidated_scenario_difference(bundle, config, gate_s=None):
    """Whether ``config`` may differ from the training scenario on the explicit per-seed path.

    Identical identities need no allowance. A per-seed INI may differ only in its
    run.ini and jammer schedule (event timing); nodes and buildings must be the
    training ones, and a declared gate must equal the native ``control_start_s``.
    Anything else is refused rather than bypassed.
    """
    from scripts.rl.env.config import read_scenario_identity
    trained = (bundle.manifest.get("scenario_identity") or {})
    live = read_scenario_identity(str(config))
    keys = ("run_ini_sha256", "nodes_json_sha256", "buildings_json_sha256", "jammers_json_sha256")
    changed = [key for key in keys if trained.get(key) != live.get(key)]
    if not changed:
        return False
    fixed = [key for key in changed if key not in SCENARIO_DIFFERENCE_ALLOWED]
    if fixed:
        raise ValueError(f"{config} differs from the training scenario in {fixed}; only run.ini/jammer timing "
                         "may differ on the per-seed path")
    if gate_s is not None and float(gate_s) != native_gate_s(config):
        raise ValueError(f"{config}: declared gate {gate_s} s differs from native control_start_s")
    return True


def write_check_result(output_dir, *, check_id, kind, passed, evidence, warnings):
    """Write the versioned ``check_result.json`` that a check task's receipt validates."""
    if kind not in CHECK_KINDS:
        raise ValueError(f"unknown check kind {kind!r}")
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    record = dict(check_result_version=CHECK_RESULT_VERSION, check_id=check_id, kind=kind,
                  status="passed" if passed else "failed", passed=bool(passed), evidence=evidence,
                  warnings=list(warnings), written_at=now_iso())
    write_json(output / CHECK_RESULT_NAME, record)
    return record


def check_result_passed(attempt_dir):
    """The success test for a check attempt; False for a missing, malformed or unpassed result."""
    path = Path(attempt_dir) / CHECK_RESULT_NAME
    try:
        record = json.loads(path.read_text())
    except (OSError, ValueError):
        return False
    if not (isinstance(record, dict) and record.get("check_result_version") == CHECK_RESULT_VERSION
            and record.get("kind") in CHECK_KINDS and isinstance(record.get("check_id"), str)
            and record.get("passed") is True and record.get("status") == "passed"
            and isinstance(record.get("evidence"), dict)):
        return False
    if record["kind"] == "replay_gate":
        from scripts.rl.policy.replay_gate import gate_passed
        return gate_passed(attempt_dir)
    return True


# Compatibility names for existing library callers; execution belongs to scripted.
from scripts.rl.policy.scripted import run_baseline, import_baseline


def _relative(path, root):
    return Path(path).resolve().relative_to(Path(root).resolve()).as_posix()


def _resolve_protocol(mode, bundle, protocol_settings, schedule):
    from scripts.rl.policy.online_adaptation import gated_settings
    from scripts.rl.policy.schedules import validate_schedule
    if mode not in OPERATION_MODES:
        raise ValueError(f"unknown operation mode {mode!r}; expected one of {OPERATION_MODES}")
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
            raise ValueError(f"online_gated_v1 settings are inherited; cannot override {sorted(unknown)}")
        if given.get("target_kl") is not None:
            raise ValueError("online_gated_v1 requires target_kl = null")
        return gated_settings(hyperparameters, given["n_steps"], given["batch_size"]), schedule
    unknown = set(given) - {"n_steps", "batch_size", "learning_rate", "ent_coef", "target_kl"}
    if unknown:
        raise ValueError(f"unknown online_sb3_v1 settings {sorted(unknown)}")
    return sb3_settings(hyperparameters, given["n_steps"], given["batch_size"], given.get("learning_rate"),
                        given.get("ent_coef"), given.get("target_kl")), schedule


def run_operation(bundle, configs, case, mode, seed, seed_role, output_dir, sim_binary, *,
                  protocol_settings=None, schedule=None, evaluation_seeds=None,
                  allow_different_scenario=False, label=None, band=None, decision_records=None, binding=None):
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
        raise ValueError(f"refusing to overwrite operation output {output}; use a new attempt directory")
    seed = int(seed)
    seeds = [int(s) for s in (evaluation_seeds or [seed])]
    if seed not in seeds:
        raise ValueError(f"seed {seed} is not one of the declared evaluation seeds {seeds}")
    if str(seed) not in {str(k) for k in configs}:
        raise ValueError(f"no run.ini declared for seed {seed}")
    settings, schedule = _resolve_protocol(mode, bundle, protocol_settings, schedule)
    needs_mission = mode == "online_gated_v1" or (schedule is not None and schedule["kind"] in SAMPLING_SCHEDULES)
    if needs_mission and not (case or {}).get("mission"):
        raise ValueError(f"{mode}{' with ' + schedule['kind'] if schedule else ''} needs the scenario case mission; "
                         "eligibility and strict success depend on it and it is never inferred")
    if mode == "online_sb3_v1" and seed == bundle.manifest.get("seed"):
        raise ValueError("online operation cannot reuse the training seed")
    output.mkdir(parents=True, exist_ok=True)
    config = str(configs[str(seed)])
    settings = dict(settings)
    settings["band"], settings["band_source"] = resolved_band(bundle, band)
    settings["decision_records"] = decision_records.describe() if decision_records is not None else None
    record = dict(online_experiment_version=ONLINE_MANIFEST_VERSION, protocol=mode, status="running",
                  started_at=now_iso(), ended_at=None, error=None, label=label, seed=seed, seed_role=seed_role,
                  evaluation_seeds=seeds, settings=settings, schedule=schedule_metadata(schedule),
                  allow_different_scenario=allow_different_scenario,
                  parent={**bundle.describe(), "binding": binding},
                  run_config=config, scenario_identity=read_scenario_identity(config),
                  binary_sha256=sha256_file(sim_binary), model=None, optimizer=None, accounting=None,
                  evaluation=None, episodes=[])
    writes_record = mode != "frozen_deterministic" or schedule is not None
    record_path = output / ONLINE_MANIFEST_NAME

    def save():
        if writes_record:
            write_json(record_path, record)
    save()
    try:
        if mode == "online_sb3_v1":
            run = _sb3_operation(bundle, sim_binary, config, seed, output, settings, allow_different_scenario,
                                 settings["band"], decision_records)
        else:
            run = _evaluated_operation(bundle, sim_binary, configs, case, mode, seed, seeds, output, settings,
                                       schedule, allow_different_scenario, label, seed_role, config,
                                       settings["band"], decision_records, binding)
        audit = dict(initial_parameter_sha256=run["initial_parameter_sha256"],
                     final_parameter_sha256=run["final_parameter_sha256"],
                     initial_optimizer_sha256=run["initial_optimizer_sha256"],
                     final_optimizer_sha256=run["final_optimizer_sha256"], **run["accounting"])
        write_json(output / WEIGHT_AUDIT_NAME, audit)
        episode_dir = _relative(run["episode_dir"], output)
        record.update(
            model=dict(initial_parameter_sha256=run["initial_parameter_sha256"],
                       final_parameter_sha256=run["final_parameter_sha256"],
                       adapted_model=run.get("adapted_model"), adapted_model_sha256=run.get("adapted_model_sha256")),
            optimizer=dict(initial_optimizer_sha256=run["initial_optimizer_sha256"],
                           final_optimizer_sha256=run["final_optimizer_sha256"]),
            accounting=run["accounting"],
            evaluation=dict(eval_manifest=run.get("eval_manifest"), episode_dir=episode_dir,
                            decisions=run["decisions"], weight_audit=WEIGHT_AUDIT_NAME,
                            steps_sha256=sha256_file(Path(run["episode_dir"]) / "steps.jsonl")),
            episodes=[dict(mode=mode, seed=seed, episode_dir=episode_dir, decisions=run["decisions"],
                           metrics=run["metrics"], **{"return": run["return"]}, **audit)],
            status="completed", ended_at=now_iso())
        save()
        return record
    except BaseException as exc:
        record.update(status="interrupted" if isinstance(exc, KeyboardInterrupt) else "failed",
                      ended_at=now_iso(), error=f"{type(exc).__name__}: {exc}")
        save()
        raise


def _sb3_operation(bundle, sim_binary, config, seed, output, settings, allow_different_scenario, band,
                   decision_records):
    from scripts.rl.env.config import read_scenario_identity
    from scripts.rl.env.mesh_env import MeshRlEnv
    from scripts.rl.policy.compat import check_compatibility
    from scripts.rl.policy.episode_review import endpoint_metrics
    from scripts.rl.policy.reward_matrix import write_reward_matrix
    manifest = bundle.manifest
    selection = _bundle.eval_selection(_bundle.selection_from_manifest(manifest))
    live_band = band
    recording = decision_recording(decision_records, "model", _bundle.model_identity(bundle, False))
    env = MeshRlEnv(sim_binary, config, seed=seed, output_dir=str(output), band=live_band, selection=selection,
                    decision_records=recording)
    try:
        initial = env.reset(seed=seed, options={"seed_source": "eval"})
        check_compatibility(manifest, env, live_identity=read_scenario_identity(config), live_band=live_band,
                            allow_different_scenario=allow_different_scenario)
        run = sb3_operate(bundle, env, initial, seed, output, settings, learn=True)
        metrics = {**episode_metrics(run.episode_dir, env.contract["num_links"]), **endpoint_metrics(run.episode_dir)}
    finally:
        env.close()
    write_reward_matrix([SimpleNamespace(status="completed", seed=seed, decisions=run.budget,
                                         episode_dir=str(run.episode_dir))], output)
    adapted = output / "adapted_model.zip"
    return dict(episode_dir=run.episode_dir, decisions=run.budget, metrics=metrics,
                **{"return": run.metadata["cumulative_reward"]},
                initial_parameter_sha256=run.initial_parameter_sha256, final_parameter_sha256=run.final_parameter_sha256,
                initial_optimizer_sha256=run.initial_optimizer_sha256, final_optimizer_sha256=run.final_optimizer_sha256,
                adapted_model=_relative(adapted, output), adapted_model_sha256=sha256_file(adapted),
                accounting=dict(update_cycles=len(run.events), optimizer_epochs=run.optimizer_epochs,
                                episode_budget=run.budget, actual_decisions=run.metadata["steps"],
                                untrained_tail_decisions=run.untrained_tail_decisions,
                                tail_policy="budget % n_steps decisions after the last full rollout are not trained",
                                weight_updates="weight_updates.json"))


def _evaluated_operation(bundle, sim_binary, configs, case, mode, seed, seeds, output, settings, schedule,
                         allow_different_scenario, label, seed_role, config, band, decision_records, binding):
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
    capture = (PreferenceCapture() if decision_records is not None and decision_records.enabled
               and decision_records.preferences != "off" and not online and schedule is None else None)
    recording = decision_recording(decision_records, "model", _bundle.model_identity(bundle, deterministic),
                                   capture.take if capture is not None else None)

    def build(env, seed):
        initial = env.reset(seed=seed, options={"seed_source": "eval"})
        model = _bundle.load_model(bundle, env.inner, mask_fn)
        if online:
            from scripts.rl.policy.online_adaptation import verify_inherited_settings
            verify_inherited_settings(model, settings)
        model.set_random_seed(seed)
        before = (_bundle.parameter_digest(model), _bundle.optimizer_digest(model), int(model._n_updates))
        if schedule is not None:
            policy = schedule_policy(model, schedule, case, Path(env.inner._session._episode_dir),
                                     env.inner.contract, env.inner._protocol.facts)
            env.observer = policy
        elif online:
            policy = OnlinePolicy(model, case["mission"], settings, output)
            env.observer = policy
        else:
            policy = ModelPolicy(model, capture=capture, deterministic=mode == "frozen_deterministic")
        tracked.append((model, policy, before))
        return Prepared(policy, initial, dict(deterministic=deterministic, held_out=seed_role == "held_out",
                                              bundle={**bundle.describe(), "binding": binding},
                                              execution_schedule=schedule and schedule["kind"]))
    env_type = OperationEnv if online or schedule is not None else DiagnosticEnv
    base = dict(label=label or f"{mode} seed {seed}", training=bundle.describe(),
                bundle={**bundle.describe(), "binding": binding}, sim_binary=str(sim_binary),
                run_config=config, band=settings["band"], scenario_identity=read_scenario_identity(config),
                seed_roles=dict(role=seed_role, training_seed=bundle.manifest.get("seed"), evaluation_seeds=seeds,
                                held_out=seed_role == "held_out"),
                deterministic=deterministic)
    spec = PolicySpec("model", build, dict(weights_frozen=not online, protocol=mode, model_selection=bundle.selection,
                                           execution_schedule=schedule and schedule["kind"]))
    manifest = evaluate(lambda policy: env_type(sim_binary, configs, output, case, initial_seed=seeds[0],
                                                bundle=bundle, allow_different_scenario=allow_different_scenario,
                                                band=band, decision_records=recording),
                        [spec], [seed], output, base)
    if manifest["status"] != "completed":
        raise RuntimeError(f"{mode} seed {seed}: evaluation did not complete")
    model, policy, (before, optimizer_before, updates_before) = tracked[0]
    after, optimizer_after = _bundle.parameter_digest(model), _bundle.optimizer_digest(model)
    episode = manifest["policies"]["model"]["episodes"][0]
    result = dict(episode_dir=Path(episode["episode_dir"]), decisions=episode["decisions"],
                  metrics=episode["metrics"], eval_manifest="eval_manifest.json", **{"return": episode["return"]},
                  initial_parameter_sha256=before, final_parameter_sha256=after,
                  initial_optimizer_sha256=optimizer_before, final_optimizer_sha256=optimizer_after)
    if online:
        verified = policy.verify()
        model.save(str(output / "adapted_model.zip"))
        adapted = output / "adapted_model.zip"
        result.update(adapted_model=_relative(adapted, output), adapted_model_sha256=sha256_file(adapted),
                      accounting=dict(
                          update_cycles=verified["update_cycles"], optimizer_steps=verified["optimizer_steps"],
                          optimizer_epochs=int(model._n_updates) - updates_before,
                          episode_decisions=policy.decisions, eligible_decisions=verified["eligible_decisions"],
                          trained_decisions=verified["trained_decisions"],
                          excluded_prefix_decisions=verified["excluded_prefix_decisions"],
                          untrained_tail_decisions=verified["untrained_tail_decisions"],
                          actor_change_l2=policy.events[-1]["actor_change_l2_from_start"],
                          policy_parameters_changed=before != after,
                          optimizer_state_changed=optimizer_before != optimizer_after,
                          tail_policy="final partial rollout flushed; a singleton tail is skipped",
                          weight_updates="weight_updates.json"))
    else:
        if before != after or optimizer_before != optimizer_after:
            raise RuntimeError(f"{mode} execution changed policy or optimizer state")
        result["accounting"] = dict(update_cycles=0, optimizer_steps=0, untrained_tail_decisions=0)
        if schedule is not None:
            result["accounting"]["schedule_events"] = list(policy.schedule.events)
    return result
