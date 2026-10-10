"""Masked deterministic evaluation of saved and baseline policies, one env per policy."""

import hashlib
import json
import platform
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Protocol

import numpy as np

from scripts.rl.cli_common import now_iso, package_versions, write_json
from scripts.rl.env.protocol import SLOT_ACTIONS
from scripts.rl.env.telemetry import TELEMETRY_FILE
from scripts.rl.policy.metrics import (CSV_METRICS, METRIC_SOURCE,
                                       episode_metrics as reduce_episode_metrics)

EVAL_MANIFEST_NAME = "eval_manifest.json"
EVAL_MANIFEST_VERSION = 4
DEFAULT_POLICIES = ("model", "hold", "random_valid")
PLACEMENT_POLICIES = ("geometric", "optimization")
POLICY_NAMES = DEFAULT_POLICIES + PLACEMENT_POLICIES
HOLD_ACTION = 4
_RETURN_TOL = 1e-9
_MAX_ERROR_CHARS = 1000



class Policy(Protocol):
    """One joint action per decision from the observation and the live mask."""

    name: str

    def act(self, obs, mask, contract) -> np.ndarray:
        ...


class HoldPolicy:
    """Every slot holds; hold is never masked."""

    name = "hold"

    def act(self, obs, mask, contract) -> np.ndarray:
        return np.full(len(mask) // SLOT_ACTIONS, HOLD_ACTION, dtype=np.int64)


class RandomValidPolicy:
    """Uniform choice among the valid actions of each slot, reseeded per episode."""

    name = "random_valid"

    def __init__(self):
        self._rng = np.random.default_rng(0)

    def start_episode(self, seed: int) -> None:
        self._rng = np.random.default_rng(int(seed))

    def act(self, obs, mask, contract) -> np.ndarray:
        flat = np.asarray(mask, dtype=bool)
        slots = len(flat) // SLOT_ACTIONS
        return np.asarray(
            [self._rng.choice(np.flatnonzero(flat[s * SLOT_ACTIONS:(s + 1) * SLOT_ACTIONS]))
             for s in range(slots)], dtype=np.int64)


class ModelPolicy:
    """Deterministic MaskablePPO prediction under the live mask."""

    name = "model"

    def __init__(self, model, capture=None):
        self._model = model
        if capture is not None:
            capture.attach(model)

    def act(self, obs, mask, contract) -> np.ndarray:
        action, _ = self._model.predict(obs, action_masks=np.asarray(mask, dtype=bool),
                                        deterministic=True)
        return np.asarray(action, dtype=np.int64).reshape(-1)


@dataclass(frozen=True)
class PolicySpec:
    """A named policy, how to build it once its env exists, and its manifest metadata."""

    name: str
    build: Callable
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Prepared:
    """What a spec's build returned: the policy, an optional reused reset, manifest keys."""

    policy: Policy
    initial: tuple | None = None
    manifest_updates: dict = field(default_factory=dict)


@dataclass(frozen=True)
class EpisodeResult:
    """One evaluated episode and the domain metrics derived from its telemetry."""

    seed: int
    episode_dir: str | None
    status: str
    exit_code: int | None
    decisions: int
    total_return: float | None
    reward_components_sum: dict
    revalidated_slots_total: int | None
    mask_violations: int | None
    actions_sha256: str | None
    metrics: dict
    summary_json: str | None = None
    error: str | None = None

    def describe(self) -> dict:
        return {"seed": self.seed, "episode_dir": self.episode_dir,
                "status": self.status, "error": self.error,
                "exit_code": self.exit_code,
                "decisions": self.decisions, "return": self.total_return,
                "reward_components_sum": dict(self.reward_components_sum),
                "revalidated_slots_total": self.revalidated_slots_total,
                "mask_violations": self.mask_violations,
                "actions_sha256": self.actions_sha256, "metrics": dict(self.metrics),
                "summary_json": self.summary_json}


def _episode_dir(env) -> Path:
    """The running episode's directory, taken from the simulator command line."""
    for token in env._cmd:
        if token.startswith("--output-dir="):
            return Path(token.split("=", 1)[1])
    raise RuntimeError("Environment has no running episode")


def _actions_sha256(actions: list[list[int]]) -> str:
    payload = json.dumps(actions, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _read_records(episode_dir: Path):
    path = episode_dir / TELEMETRY_FILE
    if not path.is_file():
        return
    with path.open() as handle:
        next(handle, None)
        for line in handle:
            if line.strip():
                record = json.loads(line)
                if int(record.get("decision", 0)) >= 1:
                    yield record


def episode_metrics(episode_dir: Path, num_links: int) -> dict:
    path = episode_dir / TELEMETRY_FILE
    if not path.is_file():
        return reduce_episode_metrics((), num_links)
    with path.open() as handle:
        header = json.loads(next(handle, "{}"))
        records = (json.loads(line) for line in handle if line.strip())
        return reduce_episode_metrics(records, num_links, header.get("contract"))


def run_episode(env, policy: Policy, seed: int, initial=None) -> EpisodeResult:
    """One simulator episode under `policy`; the return is self-checked against the manifest."""
    start = getattr(policy, "start_episode", None)
    if start is not None:
        start(seed)
    obs, _ = (env.reset(seed=seed, options={"seed_source": "eval"})
              if initial is None else initial)
    episode_dir = _episode_dir(env)
    contract = env.contract or {}

    actions: list[list[int]] = []
    total = 0.0
    violations = revalidated = 0
    done = False
    while not done:
        mask = np.asarray(env.action_masks(), dtype=bool)
        action = np.asarray(policy.act(obs, mask, contract), dtype=np.int64).reshape(-1)
        violations += sum(1 for slot, choice in enumerate(action)
                          if not mask[slot * SLOT_ACTIONS + int(choice)])
        actions.append([int(a) for a in action])
        obs, reward, terminated, truncated, info = env.step(action)
        total += float(reward)
        revalidated += len(info.get("revalidated_slots", []))
        done = bool(terminated or truncated)

    manifest = json.loads((episode_dir / "rl_episode.json").read_text())
    recorded = float(manifest.get("cumulative_reward", 0.0))
    if abs(total - recorded) > _RETURN_TOL:
        raise RuntimeError(
            f"Episode return {total!r} does not match {episode_dir}/rl_episode.json "
            f"cumulative_reward {recorded!r}")
    summary = episode_dir / f"seed-{int(seed)}" / "summary.json"
    return EpisodeResult(
        seed=int(seed),
        episode_dir=str(episode_dir),
        status=manifest.get("status"),
        exit_code=manifest.get("exit_code"),
        decisions=int(manifest.get("decisions", len(actions))),
        total_return=total,
        reward_components_sum=dict(manifest.get("reward_components_sum") or {}),
        revalidated_slots_total=revalidated,
        mask_violations=violations,
        actions_sha256=_actions_sha256(actions),
        metrics=episode_metrics(episode_dir, int(contract.get("num_links", 0))),
        summary_json=str(summary) if summary.is_file() else None,
    )


def _not_run(seed: int) -> EpisodeResult:
    """A seed the evaluation never attempted because it aborted earlier."""
    return EpisodeResult(seed=int(seed), episode_dir=None, status="not_run",
                         exit_code=None, decisions=0, total_return=None,
                         reward_components_sum={}, revalidated_slots_total=None,
                         mask_violations=None, actions_sha256=None,
                         metrics={name: None for name in CSV_METRICS})


def _partial_episode(env, seed: int, recorded: set[str]) -> tuple[Path | None, dict]:
    """The failing episode's directory and manifest, only if they belong to this seed."""
    try:
        path = _episode_dir(env)
        manifest = json.loads((path / "rl_episode.json").read_text())
    except (OSError, ValueError, RuntimeError, KeyError):
        return None, {}
    if str(path) in recorded or int(manifest.get("seed", -1)) != int(seed):
        return None, {}
    return path, manifest


def _failed_result(env, seed: int, exc: BaseException,
                   recorded: set[str]) -> EpisodeResult:
    """The record for an episode that raised: partial totals, an error, no metrics."""
    episode_dir, partial = _partial_episode(env, seed, recorded)
    reported = partial.get("status") if isinstance(partial.get("status"), str) else ""
    # A partial window spans less time than a full episode, so it is never averaged.
    return EpisodeResult(
        seed=int(seed), episode_dir=None if episode_dir is None else str(episode_dir),
        status=reported if reported and reported != "completed" else "failed",
        exit_code=partial.get("exit_code"),
        decisions=int(partial.get("decisions") or 0),
        total_return=partial.get("cumulative_reward"),
        reward_components_sum=dict(partial.get("reward_components_sum") or {}),
        revalidated_slots_total=None, mask_violations=None, actions_sha256=None,
        metrics={name: None for name in CSV_METRICS},
        error=f"{type(exc).__name__}: {exc}"[:_MAX_ERROR_CHARS],
    )


def summarize(results: list[EpisodeResult], expected: int | None = None) -> dict:
    """Per-policy aggregate; returns and counters cover completed episodes only."""
    done = [r for r in results if r.status == "completed"]
    returns = [r.total_return for r in done]
    return {
        "expected_episodes": len(results) if expected is None else int(expected),
        "mean_return": (sum(returns) / len(returns)) if returns else None,
        "min_return": min(returns) if returns else None,
        "max_return": max(returns) if returns else None,
        "revalidated_slots_total": sum(r.revalidated_slots_total or 0 for r in done),
        "mask_violations_total": sum(r.mask_violations or 0 for r in done),
        "completed_episodes": len(done),
    }


def _initial_manifest(base: dict, seeds: list[int]) -> dict:
    return {
        "eval_manifest_version": EVAL_MANIFEST_VERSION,
        "status": "running",
        "error": None,
        "label": base.get("label"),
        "started_at": now_iso(),
        "ended_at": None,
        "metric_source": dict(METRIC_SOURCE),
        "seed_roles": base.get("seed_roles"),
        "training": base.get("training"),
        "episodes_expected": None,
        "episodes_completed": 0,
        "sim_binary": base.get("sim_binary"),
        "run_config": base.get("run_config"),
        "band": base.get("band"),
        "scenario_identity": base.get("scenario_identity"),
        "contract": None,
        "bundle": base.get("bundle"),
        "compatibility": None,
        "selection": None,
        "observation_schema": None,
        "reward_schema": None,
        "deterministic": True,
        "seeds": [int(s) for s in seeds],
        "seed_source": "eval",
        "policies": {},
        "python_version": platform.python_version(),
        "platform": {"system": platform.system(), "machine": platform.machine()},
        "package_versions": package_versions(),
    }


def _store(manifest: dict, name: str, results: list[EpisodeResult],
           expected: int, metadata: dict) -> None:
    manifest["policies"][name] = {
        "episodes": [result.describe() for result in results],
        "summary": summarize(results, expected),
    }
    if metadata.get(name):
        manifest["policies"][name]["baseline"] = metadata[name]
    manifest["episodes_completed"] = sum(
        block["summary"]["completed_episodes"] for block in manifest["policies"].values())


def evaluate(make_env, policies: list[PolicySpec], seeds: list[int], out_dir,
             base: dict) -> dict:
    """Run every policy over every seed and write eval_manifest.json after each episode."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    seeds = [int(seed) for seed in seeds]
    manifest_path = out_dir / EVAL_MANIFEST_NAME
    manifest = _initial_manifest(base, seeds)
    manifest["episodes_expected"] = len(policies) * len(seeds)
    write_json(manifest_path, manifest)
    collected: dict[str, list[EpisodeResult]] = {spec.name: [] for spec in policies}
    metadata = {spec.name: spec.metadata for spec in policies}

    try:
        for spec in policies:
            results = collected[spec.name]
            env = make_env(spec.name)
            try:
                prepared = spec.build(env, seeds[0])
                manifest.update(prepared.manifest_updates)
                recorded: set[str] = set()
                for index, seed in enumerate(seeds):
                    try:
                        result = run_episode(
                            env, prepared.policy, seed,
                            initial=prepared.initial if index == 0 else None)
                    except Exception as exc:
                        result = _failed_result(env, seed, exc, recorded)
                    if result.episode_dir is not None:
                        recorded.add(result.episode_dir)
                    if manifest["contract"] is None and env.contract is not None:
                        manifest["contract"] = env.contract
                        manifest["selection"] = env.selection.describe()
                        manifest["observation_schema"] = env.observation_schema
                        manifest["reward_schema"] = env.reward_schema
                    results.append(result)
                    _store(manifest, spec.name, results, len(seeds), metadata)
                    write_json(manifest_path, manifest)
            finally:
                env.close()
    except BaseException as exc:
        for name, results in collected.items():
            results.extend(_not_run(seed) for seed in seeds[len(results):])
            _store(manifest, name, results, len(seeds), metadata)
        manifest["status"] = "failed"
        manifest["ended_at"] = now_iso()
        manifest["error"] = f"{type(exc).__name__}: {exc}"[:_MAX_ERROR_CHARS]
        write_json(manifest_path, manifest)
        raise

    completed = manifest["episodes_completed"]
    manifest["status"] = ("completed" if completed == manifest["episodes_expected"]
                          else "partial" if completed else "failed")
    manifest["ended_at"] = now_iso()
    write_json(manifest_path, manifest)
    return manifest


def placement_spec(prepared) -> PolicySpec:
    """Hold a layout applied through the prepared effective run.ini."""
    policy = HoldPolicy()
    return PolicySpec(prepared.method, lambda env, seed: Prepared(policy),
                      metadata=prepared.metadata)


def prepare_placements(policies: list[str], run_config: str, output_dir: str,
                       sim_binary: str, band: str | None, seeds: list[int]) -> dict:
    """Prepare every requested placement before starting any evaluation episode."""
    methods = [name for name in policies if name in PLACEMENT_POLICIES]
    if not methods:
        return {}
    from scripts.baselines.preparation import prepare

    return {method: prepare(run_config, method, Path(output_dir) / method / "baseline",
                            mode="evaluation", eval_root=output_dir, band=band,
                            simulation_seeds=seeds, sim_binary=sim_binary)
            for method in methods}
