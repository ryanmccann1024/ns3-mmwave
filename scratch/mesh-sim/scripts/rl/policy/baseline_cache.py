"""Reuse immutable baseline trajectories and rescore their recorded decision facts."""

from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import shutil

from scripts.rl.cli_common import sha256_file, write_json
from scripts.rl.env.rewards import RewardComposer, position_context, reward_schema
from scripts.rl.policy.evaluate import EpisodeResult, summarize
from scripts.rl.policy.reward_matrix import write_reward_matrix


@contextmanager
def baseline_lock(root):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    with (root / "cache.lock").open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def ensure_baselines(root, signature, run):
    """Create once under a process lock; refuse different or incomplete cached runs."""
    root = Path(root)
    with baseline_lock(root):
        identity = root / "cache_identity.json"
        output = root / "trajectories"
        if identity.is_file():
            if json.loads(identity.read_text()) != signature:
                raise ValueError("baseline cache identity changed; use a new output root")
        else:
            if output.exists():
                raise ValueError("baseline cache is incomplete; move its directory before retrying")
            write_json(identity, signature)
        manifest_path = output / "eval_manifest.json"
        if not manifest_path.is_file():
            if output.exists():
                raise ValueError("baseline cache is incomplete; move its directory before retrying")
            if run(output) not in (0, 2):
                raise RuntimeError("shared baseline evaluation failed")
        manifest = json.loads(manifest_path.read_text())
        if manifest["status"] != "completed":
            raise RuntimeError("shared baseline evaluation is incomplete")
        return manifest


def cache_signature(binary, identity, band, seeds, policies, preset, *,
                    observation_parameters=None, planning_seeds=()):
    from scripts.baselines.runtime_identity import planner_code_identity
    return {"baseline_cache_version": 2, "binary_sha256": sha256_file(binary),
            "scenario_identity": identity, "band": band, "seeds": list(seeds),
            "policies": list(policies), "observation_preset": preset,
            "observation_parameters": observation_parameters or {},
            "planning_seeds": list(planning_seeds),
            "planner_code": planner_code_identity()}


def _link_or_copy(source, destination):
    try:
        os.link(source, destination)
    except OSError:
        shutil.copy2(source, destination)
    return destination


def rescore_episode(source, destination, result, selection):
    """Keep actions and physics fixed while replacing only composed reward fields."""
    source, destination = Path(source), Path(destination)
    path = destination / "steps.jsonl"
    records = [json.loads(line) for line in (source / "steps.jsonl").read_text().splitlines()]
    header, steps = records[0], records[1:]
    contract = header["contract"]
    schema = reward_schema(selection.reward_components, selection.reward_weights,
                           contract=contract, parameters=selection.reward_parameters)
    header["selection"], header["reward_schema"] = selection.describe(), schema
    composer = RewardComposer(selection.reward_components, selection.reward_weights, selection.reward_parameters)
    sums = {name: 0.0 for name in selection.reward_components}
    initial = steps[0]["facts"]["nodes"]
    previous, total, decisions = initial, 0.0, 0
    for record in steps:
        if record["decision"] == 0:
            continue
        facts = record["facts"]
        context = composer.context(facts, contract, {"previous_nodes": previous, "initial_nodes": initial, "elapsed_ticks": record["ticks_in_step"]})
        breakdown = composer.compose(facts["window"], record["legacy_reward"], contract, context)
        record["reward_context"] = context
        record["reward"] = {"total": breakdown.total, "components": breakdown.components,
                            "valid": breakdown.valid}
        previous = facts["nodes"]
        total += breakdown.total
        decisions += 1
        for name, value in breakdown.components.items(): sums[name] += value
    if decisions != result["decisions"]:
        raise ValueError("baseline rescore requires complete decision records")
    path.unlink()
    path.write_text("".join(json.dumps(record, sort_keys=True, allow_nan=False)+"\n" for record in records))
    episode_path = destination / "rl_episode.json"
    episode = json.loads(episode_path.read_text())
    episode.update(cumulative_reward=total, selection=selection.describe(),
                   reward_schema_sha256=schema["sha256"], reward_components_sum=sums)
    episode_path.unlink()
    write_json(episode_path, episode)
    output = dict(result)
    output.update(episode_dir=str(destination), **{"return": total, "reward_components_sum": sums})
    if output.get("summary_json"):
        relative = Path(result["summary_json"]).relative_to(source)
        output["summary_json"] = str(destination / relative)
    return output


def merge_baselines(manifest, cached, output, selection, cache_root):
    """Materialize replay links under each variant so the GUI retains its usual layout."""
    output = Path(output)
    for policy, block in cached["policies"].items():
        source = Path(cache_root) / "trajectories" / policy
        destination = output / policy
        shutil.copytree(source, destination, copy_function=_link_or_copy)
        episodes = []
        results = []
        for result in block["episodes"]:
            old = Path(result["episode_dir"])
            new = destination / old.relative_to(source)
            rescored = rescore_episode(old, new, result, selection)
            episodes.append(rescored)
            results.append(EpisodeResult(seed=rescored["seed"], episode_dir=rescored["episode_dir"],
                status=rescored["status"], exit_code=rescored["exit_code"], decisions=rescored["decisions"],
                total_return=rescored["return"], reward_components_sum=rescored["reward_components_sum"],
                revalidated_slots_total=rescored["revalidated_slots_total"],
                mask_violations=rescored["mask_violations"], actions_sha256=rescored["actions_sha256"],
                metrics=rescored["metrics"], summary_json=rescored.get("summary_json")))
        manifest["policies"][policy] = {**block, "episodes": episodes,
                                         "summary": summarize(results, len(results))}
        for filename in ("reward_matrix.json", "reward_matrix.csv"):
            (destination / filename).unlink(missing_ok=True)
        write_reward_matrix(results, destination)
    manifest["episodes_expected"] = len(manifest["policies"]) * len(manifest["seeds"])
    manifest["episodes_completed"] += cached["episodes_completed"]
    manifest["baseline_cache"] = str(Path(cache_root).resolve())
    manifest["status"] = "completed" if manifest["episodes_completed"] == manifest["episodes_expected"] else "partial"
    write_json(output / "eval_manifest.json", manifest)
    return manifest
