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

EVAL_MANIFEST_NAME = "eval_manifest.json"
EVAL_MANIFEST_VERSION = 1
HOLD_ACTION = 4
_RETURN_TOL = 1e-9
_DEMAND_EPS = 1e-9


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

    def __init__(self, model):
        self._model = model

    def act(self, obs, mask, contract) -> np.ndarray:
        action, _ = self._model.predict(obs, action_masks=np.asarray(mask, dtype=bool),
                                        deterministic=True)
        return np.asarray(action, dtype=np.int64).reshape(-1)


@dataclass(frozen=True)
class PolicySpec:
    """A named policy plus how to build it once its env exists."""

    name: str
    build: Callable


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
    episode_dir: str
    status: str
    exit_code: int | None
    decisions: int
    total_return: float
    reward_components_sum: dict
    revalidated_slots_total: int
    mask_violations: int
    actions_sha256: str
    metrics: dict

    def describe(self) -> dict:
        return {"seed": self.seed, "episode_dir": self.episode_dir,
                "status": self.status, "exit_code": self.exit_code,
                "decisions": self.decisions, "return": self.total_return,
                "reward_components_sum": dict(self.reward_components_sum),
                "revalidated_slots_total": self.revalidated_slots_total,
                "mask_violations": self.mask_violations,
                "actions_sha256": self.actions_sha256, "metrics": dict(self.metrics)}


def _episode_dir(env) -> Path:
    """The running episode's directory, taken from the simulator command line."""
    for token in env._cmd:
        if token.startswith("--output-dir="):
            return Path(token.split("=", 1)[1])
    raise RuntimeError("Environment has no running episode")


def _actions_sha256(actions: list[list[int]]) -> str:
    payload = json.dumps(actions, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _read_records(episode_dir: Path) -> list[dict]:
    path = episode_dir / TELEMETRY_FILE
    if not path.is_file():
        return []
    lines = [line for line in path.read_text().splitlines() if line.strip()]
    records = [json.loads(line) for line in lines[1:]]
    return [r for r in records if int(r.get("decision", 0)) >= 1]


def episode_metrics(episode_dir: Path, num_links: int) -> dict:
    """Delivery, connectivity, and LOS from the saved per-decision window sums."""
    records = _read_records(episode_dir)
    metrics = {"delivery_ratio": None, "connectivity": None, "los_fraction": None,
               "first_all_los_decision": None}
    if not records:
        return metrics

    ticks = demand = delivered = connected = los = 0.0
    for record in records:
        window = record["facts"]["window"]
        ticks += int(window["ticks"])
        demand += float(window["demand_mbps_sum"])
        delivered += float(window["delivered_mbps_sum"])
        connected += int(window["connected_pairs_sum"])
        los += int(window["los_pairs_sum"])
        if (metrics["first_all_los_decision"] is None
                and int(window["los_pairs_sum"]) == int(window["ticks"]) * num_links):
            metrics["first_all_los_decision"] = int(record["decision"])

    pairs = ticks * num_links
    if demand > _DEMAND_EPS:
        metrics["delivery_ratio"] = delivered / demand
    if pairs > 0:
        metrics["connectivity"] = connected / pairs
        metrics["los_fraction"] = los / pairs
    return metrics


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
    )


def summarize(results: list[EpisodeResult]) -> dict:
    """Per-policy aggregate over its episodes."""
    returns = [r.total_return for r in results]
    return {
        "mean_return": (sum(returns) / len(returns)) if returns else None,
        "min_return": min(returns) if returns else None,
        "max_return": max(returns) if returns else None,
        "revalidated_slots_total": sum(r.revalidated_slots_total for r in results),
        "mask_violations_total": sum(r.mask_violations for r in results),
        "completed_episodes": sum(1 for r in results if r.status == "completed"),
    }


def _initial_manifest(base: dict, seeds: list[int]) -> dict:
    return {
        "eval_manifest_version": EVAL_MANIFEST_VERSION,
        "status": "running",
        "started_at": now_iso(),
        "ended_at": None,
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


def evaluate(make_env, policies: list[PolicySpec], seeds: list[int], out_dir,
             base: dict) -> dict:
    """Run every policy over every seed and write eval_manifest.json."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = out_dir / EVAL_MANIFEST_NAME
    manifest = _initial_manifest(base, seeds)
    write_json(manifest_path, manifest)

    try:
        for spec in policies:
            env = make_env(spec.name)
            try:
                prepared = spec.build(env, int(seeds[0]))
                manifest.update(prepared.manifest_updates)
                results = [run_episode(env, prepared.policy, int(seed),
                                       initial=prepared.initial if index == 0 else None)
                           for index, seed in enumerate(seeds)]
                if manifest["contract"] is None:
                    manifest["contract"] = env.contract
                    manifest["selection"] = env.selection.describe()
                    manifest["observation_schema"] = env.observation_schema
                    manifest["reward_schema"] = env.reward_schema
                manifest["policies"][spec.name] = {
                    "episodes": [result.describe() for result in results],
                    "summary": summarize(results),
                }
                write_json(manifest_path, manifest)
            finally:
                env.close()
    except Exception as exc:
        manifest["status"] = "failed"
        manifest["ended_at"] = now_iso()
        manifest["error"] = f"{type(exc).__name__}: {exc}"
        write_json(manifest_path, manifest)
        raise

    manifest["status"] = "completed"
    manifest["ended_at"] = now_iso()
    write_json(manifest_path, manifest)
    return manifest
