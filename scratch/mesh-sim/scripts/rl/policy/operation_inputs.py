"""Resolve operation inputs, environment compatibility, and checkpoint bindings."""

import json
from pathlib import Path

from scripts.artifact_io import sha256_file, write_json
from scripts.rl.env.config import read_scenario_identity
from scripts.rl.env.seeded_env import SeededEnv
from scripts.rl.policy import bundle as _bundle
from scripts.sim_support import parse_ini


def native_gate_s(config):
    """The deployment gate the simulator will use; an absent key is the native default 0."""
    value = parse_ini(config).get("rl", {}).get("control_start_s")
    return 0.0 if value is None else float(value)


def resolve_gates(configs, case, *, replay=False):
    """Verify operation gates against native INIs and preserve reference gates for replay."""
    declared = (case or {}).get("seeds") or {}
    seeds = {}
    for key, config in configs.items():
        native = native_gate_s(config)
        given = (declared.get(str(key)) or {}).get("gate_s")
        if not replay and given is not None and float(given) != native:
            raise ValueError(
                f"seed {key}: declared gate {given} s differs from native control_start_s {native} s"
            )
        seeds[str(key)] = {
            **(declared.get(str(key)) or {}),
            "gate_s": given if replay and given is not None else native,
        }
    return {**(case or {}), "seeds": seeds}


class DiagnosticEnv(SeededEnv):
    """Per-seed env that checks the bundle's schemas after each reset, before any model action."""

    def __init__(
        self,
        binary,
        configs,
        output,
        case,
        *,
        initial_seed,
        bundle=None,
        allow_different_scenario=True,
        band=None,
        decision_records=None,
        replay=False,
    ):
        self.bundle = bundle
        self.allow_different_scenario = allow_different_scenario
        self.compatibility = []
        gates = resolve_gates(configs, case, replay=replay)
        super().__init__(
            binary,
            configs,
            Path(output),
            gates,
            initial_seed=initial_seed,
            band=band,
            decision_records=decision_records,
        )

    def reset(self, *, seed, options=None):
        initial = super().reset(seed=seed, options=options)
        if self.case.get("mission") == "jamming":
            from scripts.rl.scenario_check.validation import jammer_timing

            verified = jammer_timing(
                self.configs[str(seed)], self.case, seed, self.inner._cmd
            )
            directory = next(
                Path(x.split("=", 1)[1])
                for x in self.inner._cmd
                if x.startswith("--output-dir=")
            )
            write_json(directory / "event_timing.json", verified)
        if self.bundle is not None:
            from scripts.rl.policy.compat import check_compatibility

            report = check_compatibility(
                self.bundle.manifest,
                self.inner,
                live_identity=read_scenario_identity(str(self.configs[str(seed)])),
                live_band=self.requested_band,
                allow_different_scenario=self.allow_different_scenario,
            )
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
            self.observer.observe(
                obs, reward, terminated, truncated, info, self.inner._protocol.facts
            )
        return result


def bound_bundle(binding_path, run_dir, model):
    """The bundle of a scheduler-verified binding, re-verified against its original bytes.

    ``run_dir``/``model`` must name exactly the bound run and model (``final``,
    ``best`` or ``checkpoints/<file>.zip``); the training manifest may be unfinished
    only because the binding pins its bytes. Returns ``(bundle, {path, sha256})``.
    """
    binding_path = Path(binding_path).resolve()
    if (
        binding_path.parent.name != "bindings"
        or binding_path.parent.parent.name != "state"
    ):
        raise ValueError(
            "--binding is scheduler-only and must be under a batch state/bindings directory"
        )
    record = json.loads(binding_path.read_text())
    bundle = _bundle.read_bound_checkpoint(record)
    if Path(run_dir).resolve() != Path(record["run_dir"]).resolve():
        raise ValueError(
            f"--run-dir {run_dir} is not the bound run {record['run_dir']}"
        )
    selection = record["model_selection"]
    named = model if model in ("final", "best") else "checkpoint"
    if named != selection or (
        selection == "checkpoint"
        and (Path(run_dir) / model).resolve() != Path(record["model_path"]).resolve()
    ):
        raise ValueError(
            f"--model {model} is not the bound {selection} model {record['model_path']}"
        )
    return bundle, {
        "path": str(binding_path.resolve()),
        "sha256": sha256_file(binding_path),
    }


def decision_recording(settings, policy, model=None, preference_source=None):
    """The ``decision_records=`` value for an operation env, or None when records are off."""
    if settings is None or not settings.enabled:
        return None
    from scripts.rl.env.recording.decisions import DecisionContext
    from scripts.rl.env.recording.decisions import DecisionRecording

    return DecisionRecording(
        settings,
        DecisionContext(
            mode="evaluation",
            source="evaluate",
            policy=policy,
            model=model,
            preference_source=preference_source,
        ),
    )


_TIMING_INI_FIELDS = {
    ("rl", "control_start_s"),
    ("scenario", "seed"),
    ("scenario", "nodes_file"),
    ("scenario", "buildings_file"),
    ("scenario", "jammers_file"),
}


def _physical_ini(config):
    return {
        (section, key): value
        for section, values in parse_ini(config).items()
        for key, value in values.items()
        if (section, key) not in _TIMING_INI_FIELDS
    }


def _jammer_configuration(config):
    value = parse_ini(config).get("scenario", {}).get("jammers_file")
    if not value:
        return None, None
    path = Path(config).parent / value
    jammers = json.loads(path.read_text())
    for jammer in jammers:
        for interval in jammer.get("intervals", []):
            interval.pop("start", None)
            interval.pop("end", None)
        for waypoint in jammer.get("waypoints", []):
            waypoint.pop("t", None)
    return sha256_file(path), jammers


def prevalidated_scenario_difference(bundle, config, gate_s=None):
    """Allow verified deployment and jammer timing changes in per-seed inputs."""
    trained = bundle.manifest.get("scenario_identity") or {}
    live = read_scenario_identity(str(config))
    if gate_s is not None and float(gate_s) != native_gate_s(config):
        raise ValueError(
            f"{config}: declared gate {gate_s} s differs from native control_start_s"
        )
    fixed = [
        key
        for key in ("nodes_json_sha256", "buildings_json_sha256")
        if trained.get(key) != live.get(key)
    ]
    if fixed:
        raise ValueError(f"{config} differs from the training scenario in {fixed}")
    ini_changed = trained.get("run_ini_sha256") != live["run_ini_sha256"]
    jammer_changed = trained.get("jammers_json_sha256") != live["jammers_json_sha256"]
    if not (ini_changed or jammer_changed):
        return False

    original = trained.get("run_config") or bundle.manifest.get("run_config")
    if (
        not original
        or not Path(original).is_file()
        or sha256_file(original) != trained.get("run_ini_sha256")
    ):
        raise ValueError(
            "cannot verify timing changes without the original training INI"
        )
    if ini_changed:
        before, after = _physical_ini(original), _physical_ini(config)
        changed = sorted(
            f"{section}.{key}"
            for section, key in before.keys() | after.keys()
            if before.get((section, key)) != after.get((section, key))
        )
        if changed:
            raise ValueError(
                f"{config}: non-timing settings differ from training: {', '.join(changed)}"
            )
    if jammer_changed:
        original_hash, before = _jammer_configuration(original)
        live_hash, after = _jammer_configuration(config)
        if original_hash != trained.get("jammers_json_sha256"):
            raise ValueError(
                "cannot verify timing changes without the original training jammer file"
            )
        if live_hash != live["jammers_json_sha256"] or before != after:
            raise ValueError(
                f"{config}: jammer changes must be limited to event timing"
            )
    return True
