"""Read a saved training run as a verified model bundle."""

import dataclasses
import hashlib
import json
import zipfile
from dataclasses import dataclass
from pathlib import Path

from scripts.rl.cli_common import MANIFEST_NAME, package_versions, sha256_file
from scripts.rl.env.observations import PRESETS
from scripts.rl.env.rewards import COMPONENTS, RewardComposer
from scripts.rl.env.selection import TELEMETRY_MODES, RlSelection
from scripts.rl.policy.compat import BundleError
from scripts.rl.policy.training_artifacts import MANIFEST_VERSION, CHECKPOINT_DIR

_SELECTION_KEYS = (
    "observation_preset",
    "reward_components",
    "reward_weights",
    "telemetry",
    "telemetry_every",
    "observation_parameters",
    "reward_parameters",
)
_SCENARIO_SHA_KEYS = (
    "run_ini_sha256",
    "nodes_json_sha256",
    "buildings_json_sha256",
    "jammers_json_sha256",
)
_READABLE_MANIFEST_VERSIONS = (4, 5, 6, MANIFEST_VERSION)


@dataclass(frozen=True)
class ModelBundle:
    """One verified model file with the manifest it came from."""

    run_dir: Path
    manifest: dict
    selection: str
    model_path: Path
    model_sha256: str
    num_timesteps: int | None

    def describe(self) -> dict:
        return {
            "run_dir": str(self.run_dir),
            "model_selection": self.selection,
            "model_path": str(self.model_path),
            "model_sha256": self.model_sha256,
            "num_timesteps": self.num_timesteps,
            "train_manifest_sha256": sha256_file(self.run_dir / MANIFEST_NAME),
        }


def read_manifest(run_dir) -> dict:
    """Load train_manifest.json; every problem is a BundleError."""
    path = Path(run_dir) / MANIFEST_NAME
    if not path.is_file():
        raise BundleError(f"No {MANIFEST_NAME} in {run_dir}")
    try:
        manifest = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise BundleError(f"{path} is not readable JSON: {exc}") from exc
    if not isinstance(manifest, dict):
        raise BundleError(f"{path} does not contain a JSON object")
    return manifest


def _checkpoint_target(
    run_dir: Path, manifest: dict, model: str
) -> tuple[Path, str, int]:
    relative = Path(model)
    if (
        relative.is_absolute()
        or len(relative.parts) != 2
        or relative.parts[0] != CHECKPOINT_DIR
        or relative.suffix != ".zip"
    ):
        raise BundleError(
            f"--model {model!r} must be 'final', 'best', or "
            f"'{CHECKPOINT_DIR}/<name>.zip' relative to {run_dir}"
        )
    target = (run_dir / relative).resolve()
    if target.parent != (run_dir / CHECKPOINT_DIR).resolve():
        raise BundleError(
            "checkpoint must remain inside the training checkpoint directory"
        )
    for entry in manifest.get("checkpoints") or []:
        if Path(entry["path"]).resolve() == target:
            return target, entry["sha256"], int(entry["num_timesteps"])
    raise BundleError(f"{model} is not listed in the manifest's retained checkpoints")


def _model_target(
    run_dir: Path, manifest: dict, model: str
) -> tuple[Path, str, int | None]:
    if model == "final":
        path, digest = manifest.get("model_path"), manifest.get("model_sha256")
        if not path or not digest:
            raise BundleError(f"{run_dir} has no final model recorded")
        return Path(path), digest, None
    if model == "best":
        path, digest = (
            manifest.get("best_model_path"),
            manifest.get("best_model_sha256"),
        )
        if not path or not digest:
            raise BundleError(
                f"{run_dir} has no best model; train with --eval-every-steps > 0"
            )
        return Path(path), digest, None
    return _checkpoint_target(run_dir, manifest, model)


def _read_bundle(run_dir, model: str, recovering=False) -> ModelBundle:
    """Verify the manifest and the requested model file; no flag bypasses a digest."""
    run_dir = Path(run_dir).resolve()
    manifest = read_manifest(run_dir)

    version = manifest.get("manifest_version")
    if version not in _READABLE_MANIFEST_VERSIONS:
        raise BundleError(
            f"train manifest version {version!r} is not {MANIFEST_VERSION}; "
            "retrain with current tooling"
        )
    status = manifest.get("status")
    allowed = (
        ("completed", "failed", "running", "interrupted")
        if recovering
        else ("completed",)
    )
    if status not in allowed:
        raise BundleError(
            f"training run {run_dir} has status {status!r}, not 'completed'"
        )
    control_mode = manifest.get("control_mode")
    if control_mode == "legacy":
        raise BundleError("legacy control mode is not supported by this loader")
    if control_mode != "centralized":
        raise BundleError(
            f"control mode {control_mode!r} is not supported by this loader"
        )

    path, digest, num_timesteps = _model_target(run_dir, manifest, model)
    if not path.is_file():
        raise BundleError(f"model file is missing: {path}")
    actual = sha256_file(path)
    if actual != digest:
        raise BundleError(
            f"model file digest mismatch for {path}: recorded {digest}, found {actual}"
        )
    selection = model if model in ("final", "best") else "checkpoint"
    return ModelBundle(run_dir, manifest, selection, path, digest, num_timesteps)


def policy_weights_sha256(model_path) -> str | None:
    """SHA-256 of the zip's policy.pth entry, stable across re-saves of identical weights."""
    with zipfile.ZipFile(model_path) as archive:
        if "policy.pth" not in archive.namelist():
            return None
        return hashlib.sha256(archive.read("policy.pth")).hexdigest()


def training_provenance(manifest: dict) -> dict:
    """Portable training facts an evaluation records: seeds, budgets, scenario digests."""
    evaluation = manifest.get("evaluation") or {}
    identity = manifest.get("scenario_identity") or {}
    return {
        "algorithm": manifest.get("algorithm"),
        "seed": manifest.get("seed"),
        "seed_source": manifest.get("seed_source"),
        "evaluation_seed": evaluation.get("seed"),
        "evaluation_seeds": list(
            evaluation.get("seeds")
            or ([] if evaluation.get("seed") is None else [evaluation["seed"]])
        ),
        "evaluation_episodes": evaluation.get("episodes"),
        "scenario_identity": {key: identity.get(key) for key in _SCENARIO_SHA_KEYS},
        "hyperparameters": dict(manifest.get("hyperparameters") or {}),
    }


def seed_roles(
    manifest: dict | None, model_selection: str | None, seeds, *, planning_seeds=()
) -> dict:
    """Which evaluation seeds collide with training, selection or channel planning."""
    held_out_seeds = [int(seed) for seed in seeds]
    roles = {
        "training_seed": None,
        "model_selection_seed": None,
        "selection_seed_used_for_model": model_selection == "best",
        "held_out_seeds": held_out_seeds,
        "overlap": [],
        "overlap_allowed": False,
        "held_out": None,
        "planning_seeds": sorted(set(int(seed) for seed in planning_seeds)),
        "planning_overlap": [],
    }
    training_seed = (manifest or {}).get("seed")
    evaluation = (manifest or {}).get("evaluation")
    selection_seed = (evaluation or {}).get("seed") if evaluation else None
    roles["training_seed"] = None if training_seed is None else int(training_seed)
    roles["model_selection_seed"] = (
        None if selection_seed is None else int(selection_seed)
    )
    reserved = {
        seed
        for seed in (roles["training_seed"], roles["model_selection_seed"])
        if seed is not None
    }
    roles["model_selection_seeds"] = list(
        (evaluation or {}).get("seeds")
        or ([] if selection_seed is None else [selection_seed])
    )
    reserved.update(roles["model_selection_seeds"])
    roles["planning_overlap"] = [
        seed for seed in held_out_seeds if seed in roles["planning_seeds"]
    ]
    reserved.update(roles["planning_seeds"])
    roles["overlap"] = [seed for seed in held_out_seeds if seed in reserved]
    roles["held_out"] = (
        not roles["overlap"]
        if manifest is not None or roles["planning_seeds"]
        else None
    )
    return roles


def read_bundle(run_dir, model: str = "final") -> ModelBundle:
    """Verify a completed training bundle for evaluation."""
    return _read_bundle(run_dir, model)


def read_recovery_bundle(run_dir, checkpoint: str | None = None) -> ModelBundle:
    """Verify a retained checkpoint, including one from a failed or interrupted run."""
    if checkpoint is None:
        entries = read_manifest(run_dir).get("checkpoints") or []
        if not entries:
            raise BundleError("run has no retained checkpoints to resume")
        entry = max(entries, key=lambda e: int(e["num_timesteps"]))
        checkpoint = f"{CHECKPOINT_DIR}/{Path(entry['path']).name}"
    if checkpoint in ("final", "best"):
        raise BundleError("recovery requires a retained checkpoint")
    bundle = _read_bundle(run_dir, checkpoint, recovering=True)
    if bundle.num_timesteps is None or bundle.num_timesteps < 0:
        raise BundleError("checkpoint has no valid restored timestep count")
    return bundle


def check_run_overlap(output_dir, run_dir):
    """Refuse equal, child, or ancestor output roots before any run artifacts are written."""
    out, run = Path(output_dir).resolve(), Path(run_dir).resolve()
    if out == run or run in out.parents or out in run.parents:
        raise ValueError(
            f"--output-dir {out} overlaps the training run {run}; choose a separate root"
        )


def selection_from_manifest(manifest: dict) -> RlSelection:
    """Rebuild the recorded policy selection, revalidating it against the registries."""
    saved = manifest.get("selection")
    if not isinstance(saved, dict):
        raise BundleError("train manifest has no recorded selection")

    preset = str(saved.get("observation_preset", ""))
    if preset not in PRESETS:
        raise BundleError(f"recorded observation_preset {preset!r} is not registered")
    components = tuple(str(name) for name in saved.get("reward_components") or ())
    unknown = [name for name in components if name not in COMPONENTS]
    if unknown:
        raise BundleError(f"recorded reward_components has unknown entries {unknown}")
    weights = tuple(float(w) for w in saved.get("reward_weights") or ())
    if len(weights) != len(components):
        raise BundleError(
            f"recorded reward_weights has {len(weights)} entries but reward_components "
            f"has {len(components)}"
        )
    try:
        RewardComposer(components, weights)
    except ValueError as exc:
        raise BundleError(str(exc)) from exc
    telemetry = str(saved.get("telemetry", "none"))
    if telemetry not in TELEMETRY_MODES:
        raise BundleError(f"recorded telemetry {telemetry!r} is not valid")
    every = int(saved.get("telemetry_every", 1))
    if every < 1:
        raise BundleError(f"recorded telemetry_every must be >= 1, got {every}")
    try:
        return RlSelection(
            preset,
            components,
            weights,
            telemetry,
            every,
            {key: "manifest" for key in _SELECTION_KEYS},
            observation_parameters=saved.get("observation_parameters", {}),
            reward_parameters=saved.get("reward_parameters", {}),
        )
    except ValueError as exc:
        raise BundleError(str(exc)) from exc


def eval_selection(selection: RlSelection) -> RlSelection:
    """Force per-decision telemetry so evaluation can derive its own domain metrics."""
    source = dict(selection.source)
    source.update({"telemetry": "eval", "telemetry_every": "eval"})
    return dataclasses.replace(
        selection, telemetry="steps", telemetry_every=1, source=source
    )


def load_model(bundle: ModelBundle, env, mask_fn):
    """Reload the verified model onto a masked env; only after check_compatibility."""
    from scripts.rl.agents.mask_ppo import MaskablePpoTrainer

    return MaskablePpoTrainer.load(str(bundle.model_path), env, mask_fn)


def model_identity(bundle, deterministic=True) -> dict:
    """Decision-record identity of the evaluated model file."""
    path = Path(bundle.model_path)
    run_dir = Path(bundle.run_dir)
    try:
        recorded = str(path.resolve().relative_to(run_dir.resolve()))
    except ValueError:
        recorded = str(path.resolve())
    versions = package_versions()
    return {
        "model_sha256": bundle.model_sha256,
        "policy_weights_sha256": policy_weights_sha256(path),
        "model_selection": bundle.selection,
        "model_path_recorded": recorded,
        "num_timesteps": bundle.num_timesteps,
        "train_manifest_sha256": sha256_file(run_dir / MANIFEST_NAME),
        "inference": {
            "deterministic": bool(deterministic),
            "device": "cpu",
            "stable_baselines3": versions["stable_baselines3"],
            "sb3_contrib": versions["sb3_contrib"],
            "torch": versions["torch"],
        },
    }


MODEL_BINDING_VERSION = 1
_BINDING_FIELDS = (
    "model_binding_version",
    "run_dir",
    "model_selection",
    "model_path",
    "model_sha256",
    "optimizer_sha256",
    "num_timesteps",
    "n_updates",
    "train_manifest_path",
    "train_manifest_sha256",
)


def parameter_digest(model) -> str:
    """SHA-256 over policy parameters: sorted state_dict names, then raw CPU tensor bytes."""
    digest = hashlib.sha256()
    for name, tensor in sorted(model.policy.state_dict().items()):
        digest.update(name.encode())
        digest.update(tensor.detach().cpu().numpy().tobytes())
    return digest.hexdigest()


def _optimizer_state_digest(state: dict) -> str:
    """Hash an optimizer state_dict deterministically.

    For each per-parameter entry in ascending integer parameter index, and each
    of its keys in sorted order: the key name, then for a tensor its dtype,
    shape and raw contiguous CPU bytes, or for any other value its canonical
    JSON text. Then each param group, in order, as canonical JSON (sorted keys,
    tuples as lists, non-JSON values by ``str``). Every item is length-prefixed
    so adjacent fields cannot run together.
    """
    import torch

    digest = hashlib.sha256()

    def put(data: bytes):
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)

    for index in sorted(state.get("state", {}), key=int):
        put(f"state:{int(index)}".encode())
        for key, value in sorted(state["state"][index].items()):
            put(str(key).encode())
            if isinstance(value, torch.Tensor):
                value = value.detach().cpu().contiguous()
                put(f"{value.dtype}:{tuple(value.shape)}".encode())
                put(value.numpy().tobytes())
            else:
                put(json.dumps(value, sort_keys=True, default=str).encode())
    for group in state.get("param_groups", []):
        put(json.dumps(group, sort_keys=True, default=str).encode())
    return digest.hexdigest()


def optimizer_digest(model) -> str:
    """SHA-256 of the live policy optimizer state; see ``_optimizer_state_digest``."""
    return _optimizer_state_digest(model.policy.optimizer.state_dict())


def checkpoint_optimizer_digest(zip_path) -> str:
    """Optimizer digest read from a saved ZIP without loading the policy or an env."""
    import io
    import torch

    with zipfile.ZipFile(zip_path) as archive:
        if "policy.optimizer.pth" not in archive.namelist():
            raise BundleError(f"{zip_path} has no optimizer state")
        raw = archive.read("policy.optimizer.pth")
    state = torch.load(io.BytesIO(raw), map_location="cpu", weights_only=True)
    return _optimizer_state_digest(state)


def checkpoint_counters(zip_path) -> dict:
    """Read the saved SB3 counters and state presence from a model ZIP (read-only)."""
    try:
        with zipfile.ZipFile(zip_path) as archive:
            names = set(archive.namelist())
            data = json.loads(archive.read("data")) if "data" in names else None
    except (OSError, zipfile.BadZipFile, json.JSONDecodeError) as exc:
        raise BundleError(f"{zip_path} is not a readable model ZIP: {exc}") from exc
    if not isinstance(data, dict):
        raise BundleError(f"{zip_path} has no SB3 data record")
    counters = {}
    for key in ("num_timesteps", "_n_updates"):
        value = data.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise BundleError(
                f"{zip_path} data.{key} is not a non-negative integer: {value!r}"
            )
        counters[key] = value
    return {
        "num_timesteps": counters["num_timesteps"],
        "n_updates": counters["_n_updates"],
        "policy_state_present": "policy.pth" in names,
        "optimizer_state_present": "policy.optimizer.pth" in names,
    }


def _manifest_model_selection(
    manifest: dict, model_path: Path, model_sha256: str
) -> str:
    """Which recorded model of the manifest this file is; refuse an unrecorded file."""
    resolved = model_path.resolve()
    for selection, path_key, sha_key in (
        ("final", "model_path", "model_sha256"),
        ("best", "best_model_path", "best_model_sha256"),
    ):
        if manifest.get(path_key) and Path(manifest[path_key]).resolve() == resolved:
            if manifest.get(sha_key) != model_sha256:
                raise BundleError(
                    f"bound {selection} model digest differs from its manifest"
                )
            return selection
    for entry in manifest.get("checkpoints") or []:
        if Path(entry["path"]).resolve() == resolved:
            if entry.get("sha256") != model_sha256:
                raise BundleError(
                    "bound checkpoint digest differs from its manifest entry"
                )
            return "checkpoint"
    raise BundleError(f"{model_path} is not recorded by its training manifest")


def bind_model(run_dir, model_path) -> dict:
    """Write-once binding record for a model file recorded by a training manifest.

    Fields (``MODEL_BINDING_VERSION`` 1): ``model_binding_version``; ``run_dir``
    and ``train_manifest_path`` (absolute original paths); ``train_manifest_sha256``
    (the manifest bytes at binding time); ``model_selection`` (``final``, ``best``
    or ``checkpoint``); ``model_path`` (absolute original path); ``model_sha256``;
    ``optimizer_sha256`` (``checkpoint_optimizer_digest``); ``num_timesteps`` and
    ``n_updates`` (the ZIP's ``data.num_timesteps`` / ``data._n_updates``).
    """
    run_dir = Path(run_dir).resolve()
    model_path = Path(model_path).resolve()
    manifest_path = run_dir / MANIFEST_NAME
    manifest = read_manifest(run_dir)
    model_sha256 = sha256_file(model_path)
    counters = checkpoint_counters(model_path)
    return {
        "model_binding_version": MODEL_BINDING_VERSION,
        "run_dir": str(run_dir),
        "model_selection": _manifest_model_selection(
            manifest, model_path, model_sha256
        ),
        "model_path": str(model_path),
        "model_sha256": model_sha256,
        "optimizer_sha256": checkpoint_optimizer_digest(model_path),
        "num_timesteps": counters["num_timesteps"],
        "n_updates": counters["n_updates"],
        "train_manifest_path": str(manifest_path),
        "train_manifest_sha256": sha256_file(manifest_path),
    }


def read_bound_checkpoint(binding: dict) -> ModelBundle:
    """Verify a write-once model binding against the original bytes; never rewrites them.

    The manifest may record any status (an interrupted parent attempt); the
    binding's pinned manifest/model/optimizer digests and counters are the
    evidence. Any missing field, changed byte or counter mismatch raises
    ``BundleError``. ``num_timesteps`` of the result comes from the ZIP.
    """
    if not isinstance(binding, dict):
        raise BundleError("model binding must be a JSON object")
    missing = [key for key in _BINDING_FIELDS if key not in binding]
    if missing:
        raise BundleError(f"model binding lacks {missing}")
    if binding["model_binding_version"] != MODEL_BINDING_VERSION:
        raise BundleError(
            f"model binding version {binding['model_binding_version']!r} "
            f"is not {MODEL_BINDING_VERSION}"
        )
    run_dir = Path(binding["run_dir"])
    manifest_path = Path(binding["train_manifest_path"])
    model_path = Path(binding["model_path"])
    if manifest_path != run_dir / MANIFEST_NAME:
        raise BundleError(
            "binding manifest is not the run directory's training manifest"
        )
    for path, key in (
        (manifest_path, "train_manifest_sha256"),
        (model_path, "model_sha256"),
    ):
        if not path.is_file():
            raise BundleError(f"bound file is missing: {path}")
        actual = sha256_file(path)
        if actual != binding[key]:
            raise BundleError(
                f"bound file digest mismatch for {path}: "
                f"recorded {binding[key]}, found {actual}"
            )
    manifest = read_manifest(run_dir)
    if manifest.get("manifest_version") not in _READABLE_MANIFEST_VERSIONS:
        raise BundleError(
            f"bound manifest version {manifest.get('manifest_version')!r} "
            "is not readable"
        )
    if manifest.get("control_mode") != "centralized":
        raise BundleError("bound model is not from a centralized training run")
    selection = _manifest_model_selection(manifest, model_path, binding["model_sha256"])
    if selection != binding["model_selection"]:
        raise BundleError(
            f"binding says {binding['model_selection']!r}, manifest records {selection!r}"
        )
    counters = checkpoint_counters(model_path)
    if not (counters["policy_state_present"] and counters["optimizer_state_present"]):
        raise BundleError("bound model lacks policy or optimizer state")
    if (counters["num_timesteps"], counters["n_updates"]) != (
        binding["num_timesteps"],
        binding["n_updates"],
    ):
        raise BundleError("bound model counters differ from the binding")
    if checkpoint_optimizer_digest(model_path) != binding["optimizer_sha256"]:
        raise BundleError("bound model optimizer state differs from the binding")
    return ModelBundle(
        run_dir.resolve(),
        manifest,
        selection,
        model_path.resolve(),
        binding["model_sha256"],
        counters["num_timesteps"],
    )
