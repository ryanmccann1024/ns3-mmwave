"""Evaluate one prepared case and record its outcome."""

import json
from pathlib import Path
import time
import traceback

from scripts.artifact_io import write_json
from scripts.rl.env.seeded_env import SeededEnv as BaseSeededEnv
from scripts.rl.scenario_check.assessment import acceptance
from scripts.rl.scenario_check.defaults import (
    BAND,
    CHANNEL_PLANNING_SEED,
    EVALUATION_SEEDS,
    OPTIMIZER_SEED,
)
from scripts.rl.scenario_check.reports import inspect
from scripts.rl.scenario_check.validation import jammer_timing, placement_methods


class SeededEnv(BaseSeededEnv):
    """Per-seed env tracked by this queue's interrupt handling; jamming resets record event timing."""

    def __init__(self, binary, configs, output, case, environments=None):
        self.environments = environments
        super().__init__(
            binary, configs, output, case, initial_seed=EVALUATION_SEEDS[0], band=BAND
        )
        if environments is not None:
            with environments.lock:
                if environments.cancelled.is_set():
                    super().close()
                    raise RuntimeError("scenario check interrupted")
                environments.active.add(self)

    def reset(self, *, seed, options=None):
        if self.environments is not None and self.environments.cancelled.is_set():
            raise RuntimeError("scenario check interrupted")
        initial = super().reset(seed=seed, options=options)
        if self.case.get("mission") == "jamming":
            verified = jammer_timing(
                self.configs[str(seed)], self.case, seed, self.inner._cmd
            )
            directory = next(
                Path(x.split("=", 1)[1])
                for x in self.inner._cmd
                if x.startswith("--output-dir=")
            )
            write_json(directory / "event_timing.json", verified)
        return initial

    def close(self):
        super().close()
        if self.environments is not None:
            with self.environments.lock:
                self.environments.active.discard(self)


def run_case(case, source, output, binary, environments=None):
    from scripts.rl.policy.evaluate import evaluate, PolicySpec, Prepared, HoldPolicy
    from scripts.rl.policy.scripted import ReferencePolicy
    from scripts.rl.scenario_check.placement import prepare

    started = time.monotonic()
    folder = source / case["name"]
    destination = output / "Main" / case["name"]
    destination.mkdir(parents=True)
    reference = json.loads((folder / "reference.json").read_text())
    (destination / "README.md").write_text(
        f'# {case["name"]}\n\n'
        'Standalone baseline-only GUI evaluation: select this folder.\n'
        'Policies and episode directories are indexed by eval_manifest.json.\n'
        'Scenario checks and thresholds are in scenario_check.json.\n'
        'Per-episode scenario_timeline.csv and link_timeline.csv contain mission and LOS/SINR histories.\n'
    )
    configs = {s: folder / v["run_config"] for s, v in case["seeds"].items()}
    specs = [
        PolicySpec("hold", lambda env, seed: Prepared(HoldPolicy())),
        PolicySpec(
            "random_valid",
            lambda env, seed: Prepared(
                ReferencePolicy(env, reference, random_valid=True)
            ),
            {
                "description": "Uniform native-valid actions, frozen before scenario event."
            },
        ),
        PolicySpec(
            "scripted",
            lambda env, seed: Prepared(ReferencePolicy(env, reference)),
            {"description": reference["description"]},
        ),
    ]
    prepared = {}
    for method in placement_methods(case):
        # Preparation runs in make_env, after the three shared-start controls.
        specs.append(
            PolicySpec(
                method,
                lambda env, seed: Prepared(HoldPolicy()),
                {
                    "description": "Initial-placement benchmark; no route from common start."
                },
            )
        )

    def make_env(policy):
        chosen = configs
        if policy in ("geometric", "optimization"):
            chosen, meta = prepare(
                policy, folder, output / "planning" / case["name"] / policy, binary
            )
            prepared[policy] = meta
            specs_by_name[policy].metadata.update(meta)
        return SeededEnv(binary, chosen, destination / policy, case, environments)

    specs_by_name = {spec.name: spec for spec in specs}
    from scripts.rl.env.config import read_scenario_identity

    base = dict(
        label=f'10-23 scenario check {case["name"]}',
        sim_binary=str(binary),
        run_config=str(folder / "run.ini"),
        band=BAND,
        training=None,
        seed_roles=dict(
            training_seed=None,
            diagnostic_evaluation=list(EVALUATION_SEEDS),
            channel_planning=[CHANNEL_PLANNING_SEED],
            optimizer=[OPTIMIZER_SEED],
        ),
        scenario_identity=read_scenario_identity(str(folder / "run.ini")),
    )
    errors = []
    try:
        manifest = evaluate(make_env, specs, list(EVALUATION_SEEDS), destination, base)
    except Exception as exc:
        errors.append(f"{type(exc).__name__}: {exc}")
        (destination / "execution_error.log").write_text(traceback.format_exc())
        manifest = json.loads((destination / "eval_manifest.json").read_text())
    if manifest["status"] != "completed":
        errors.append(f'evaluation {manifest["status"]}; inspect eval_manifest.json')
    buildings = json.loads((folder / "buildings.json").read_text())
    results, episodes = {}, []
    for policy, block in manifest["policies"].items():
        for episode in block["episodes"]:
            if episode["status"] != "completed":
                continue
            try:
                metrics = inspect(
                    episode["episode_dir"], case, episode["seed"], buildings
                )
            except Exception as exc:
                errors.append(f'{policy} seed {episode["seed"]} audit failed: {exc}')
                continue
            results[(policy, episode["seed"])] = metrics
            episodes.append(
                dict(
                    policy=policy,
                    seed=episode["seed"],
                    episode_dir=episode["episode_dir"],
                    **metrics,
                )
            )
    if all((p, s) in results for p in ("hold", "scripted") for s in EVALUATION_SEEDS):
        gate = acceptance(case, results)
    else:
        gate = dict(
            accepted=False,
            reasons=["hold/scripted reference evidence incomplete"],
            coverage_threshold=None,
        )
    outcome = {
        **case,
        "status": "failed"
        if errors
        else "accepted"
        if gate["accepted"]
        else "needs_review",
        "error": "; ".join(errors) if errors else None,
        "acceptance": gate,
        "episodes": episodes,
        "wall_s": time.monotonic() - started,
    }
    write_json(destination / "scenario_check.json", outcome)
    return outcome
