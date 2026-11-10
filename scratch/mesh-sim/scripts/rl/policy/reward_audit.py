"""Reward reconstruction audits over saved 600-decision telemetry.

Each method replays an episode's saved facts through the reward composer (and,
where the reward needs it, the derived-state extensions) and returns the
reconstructed return, component sums and reward-schema SHA-256. The original
per-campaign differences are kept as separately named methods:

- ``position_replay_v1`` -- composer only, previous/initial positions as context (Phase 3).
- ``coordinated_v1`` -- adds mission/coordination history, observation bounds/hash
  and coordinated term decomposition (Phase 6).
- ``team_radio_v1`` -- as ``coordinated_v1`` with the team-radio decomposition for
  the bridge/coverage-sufficient components and final-minute physical team
  metrics (Phase 7).

:func:`audit_episode` recomputes only when the recorded reward schema,
observation schema and seed identities match what the caller expects.
"""
import copy
import json
import statistics
from pathlib import Path

from scripts.rl.policy.mission_metrics import read_episode

REWARD_AUDIT_VERSION = 1
COMPLETE_DECISIONS = 600
_TOLERANCE = 1e-9
_TEAM_RADIO_COMPONENTS = ("coordinated_service_bridge_v1", "coordinated_coverage_sufficient_v1")


def _composer(selection):
    from scripts.rl.env.rewards import RewardComposer
    return RewardComposer(selection["reward_components"], selection["reward_weights"],
                          selection.get("reward_parameters", {}))


def _schema_sha256(selection, contract):
    from scripts.rl.env.rewards import reward_schema
    return reward_schema(selection["reward_components"], selection["reward_weights"], contract=contract,
                         parameters=selection.get("reward_parameters", {}))["sha256"]


def reconstruct_position_replay(header, rows, selection=None, verify=False):
    s = selection or header["selection"]
    c = header["contract"]
    composer = _composer(s)
    initial = rows[0]["facts"]["nodes"]
    previous = initial
    total = 0.
    sums = dict.fromkeys(s["reward_components"], 0.)
    n = 0
    for row in rows:
        if row["decision"] <= 0:
            continue
        f = row["facts"]
        context = composer.context(f, c, dict(previous_nodes=previous, initial_nodes=initial,
                                              elapsed_ticks=row["ticks_in_step"]))
        v = composer.compose(f["window"], row["legacy_reward"], c, context)
        if verify and abs(v.total - row["reward"]["total"]) > _TOLERANCE:
            raise ValueError("saved reward failed replay")
        total += v.total
        n += 1
        for k, value in v.components.items():
            sums[k] += value
        previous = f["nodes"]
    if n != COMPLETE_DECISIONS:
        raise ValueError(f"expected 600 complete decisions, got {n}")
    return dict(return_=total, reward_components_sum=sums, reward_schema_sha256=_schema_sha256(s, c))


def _reconstruct_history(header, rows, selection, verify, decompose, tail_metrics):
    from scripts.rl.env.state.extensions import make_extensions
    from scripts.rl.env.state.mission import MissionState
    from scripts.rl.env.observations import get_preset
    from scripts.rl.env.recording.telemetry import obs_sha256
    s = selection or header["selection"]
    contract = header["contract"]
    q = _composer(s)
    preset = get_preset(s["observation_preset"], s.get("observation_parameters", {}))
    extensions = make_extensions(preset, q)
    mission = MissionState()
    total = 0.
    components = {k: 0. for k in s["reward_components"]}
    stages = {0: 0, 1: 0, 2: 0}
    changed = 0
    previous = None
    tail = []
    for row in rows:
        f = copy.deepcopy(row["facts"])
        recorded = f.pop("coordination_v1", None)
        recorded_mission = f.get("mission_state")
        mission.advance(f, contract, row["time_s"], row["decision"] == contract["num_decisions"])
        if verify and f["mission_state"] != recorded_mission:
            raise ValueError("mission history mismatch")
        for extension in extensions:
            extension.advance(f, contract, row["time_s"], row["action_sent"])
        if verify and f.get("coordination_v1") != recorded:
            raise ValueError(f"coordination history mismatch at decision {row['decision']}")
        obs = preset.build(f, contract)
        if not preset.space(contract).contains(obs):
            raise ValueError("derived observation outside declared bounds")
        if verify and obs_sha256(obs) != row["obs_sha256"]:
            raise ValueError("derived observation hash mismatch")
        if previous is None:
            initial = f["nodes"]
        if row["decision"] > 0:
            context = q.context(f, contract, dict(previous_nodes=previous, initial_nodes=initial,
                                                  elapsed_ticks=row["ticks_in_step"]))
            score = q.compose(f["window"], row["legacy_reward"], contract, context)
            total += score.total
            if verify and abs(score.total - row["reward"]["total"]) > _TOLERANCE:
                raise ValueError("coordinated reward replay mismatch")
            for k, v in score.components.items():
                components[k] += v
            if "coordination_v1" in f and f["coordination_v1"]["eligible"]:
                stages[f["coordination_v1"]["stage"]] += 1
                for component in q.components:
                    name = component.name
                    if "coordination_v1" not in component.fact_extensions or not score.valid[name]:
                        continue
                    terms, weights = decompose(f, contract, q.parameters[name], name)
                    expected = sum(terms[key] * weight for key, weight in weights.items())
                    if abs(expected - score.components[name]) > _TOLERANCE:
                        raise ValueError(f"term decomposition mismatch for {name}")
            changed += 1
            if tail_metrics and row["time_s"] > 540 and f.get("coordination_v1", {}).get("eligible"):
                from scripts.rl.env.rewards.radio import global_bridge_support
                tail.append((global_bridge_support(f, contract), float(f["mission_state"]["team_connected"]),
                             min(1., f["coverage"]["fraction"] / f["coordination_v1"]["coverage_goal"])))
        previous = f["nodes"]
    if changed != COMPLETE_DECISIONS:
        raise ValueError("complete 600-decision episode required")
    result = dict(return_=total, reward_components_sum=components, stage_decisions=stages,
                  reward_schema_sha256=_schema_sha256(s, contract))
    if tail_metrics:
        mean = (lambda i: statistics.mean(t[i] for t in tail) if tail else None)
        result = dict(physical_team_metrics=dict(final_minute_global_bridge_support=mean(0),
                                                 final_minute_team_connected_fraction=mean(1),
                                                 final_minute_coverage_target_retention=mean(2)), **result)
    return result


def _coordinated_decomposition(f, contract, parameters, name):
    from scripts.rl.env.rewards.coordination import decomposition
    return decomposition(f, contract, parameters, "adaptive" in name)


def _team_radio_decomposition(f, contract, parameters, name):
    if name in _TEAM_RADIO_COMPONENTS:
        from scripts.rl.env.rewards.radio import decomposition
        return decomposition(f, contract, parameters)
    return _coordinated_decomposition(f, contract, parameters, name)


def reconstruct_coordinated(header, rows, selection=None, verify=False):
    return _reconstruct_history(header, rows, selection, verify, _coordinated_decomposition, False)


def reconstruct_team_radio(header, rows, selection=None, verify=False):
    return _reconstruct_history(header, rows, selection, verify, _team_radio_decomposition, True)


# The flag keeps each original writer's key order: Phase 3 put "return" before its other fields.
AUDIT_METHODS = {
    "position_replay_v1": (reconstruct_position_replay, True),
    "coordinated_v1": (reconstruct_coordinated, False),
    "team_radio_v1": (reconstruct_team_radio, False),
}


def _method(name):
    if name not in AUDIT_METHODS:
        raise ValueError(f"unknown reward audit method {name!r}; expected one of {sorted(AUDIT_METHODS)}")
    return AUDIT_METHODS[name]


def reconstruct(method, header, rows, selection=None, verify=False):
    return _method(method)[0](header, rows, selection, verify)


def _entry(seed, episode_dir, record, return_first):
    value = record.pop("return_")
    if return_first:
        return dict(seed=seed, episode_dir=episode_dir, **{"return": value}, **record)
    return dict(seed=seed, episode_dir=episode_dir, **record, **{"return": value})


def _recorded_seed(directory):
    return json.loads((Path(directory) / "rl_episode.json").read_text()).get("seed")


def audit_episode(episode_dir, method, *, reward_schema_sha256, seed, observation_schema_sha256=None):
    """Verify-replay one episode after checking its reward, schema and seed identities."""
    function, _ = _method(method)
    header, rows = read_episode(episode_dir)
    recorded_reward = (header.get("reward_schema") or {}).get("sha256")
    if recorded_reward != reward_schema_sha256:
        raise ValueError(f"{episode_dir}: reward schema {recorded_reward} is not the audited {reward_schema_sha256}")
    recorded_observation = (header.get("observation_schema") or {}).get("sha256")
    if observation_schema_sha256 is not None and recorded_observation != observation_schema_sha256:
        raise ValueError(f"{episode_dir}: observation schema {recorded_observation} is not {observation_schema_sha256}")
    recorded_seed = _recorded_seed(episode_dir)
    if recorded_seed is None or int(recorded_seed) != int(seed):
        raise ValueError(f"{episode_dir}: recorded seed {recorded_seed} is not the audited seed {seed}")
    record = function(header, rows, None, True)
    if record["reward_schema_sha256"] != reward_schema_sha256:
        raise ValueError(f"{episode_dir}: reconstructed reward schema differs from the recorded one")
    return record


def baseline_audit(manifest, selection, method, expected_reward_schema_sha256=None):
    """Rescore every saved baseline episode under ``selection``; seeds must match their telemetry."""
    function, return_first = _method(method)
    result = {}
    for policy, block in manifest["policies"].items():
        entries = []
        for e in block["episodes"]:
            recorded_seed = _recorded_seed(e["episode_dir"])
            if recorded_seed is None or int(recorded_seed) != int(e["seed"]):
                raise ValueError(f"{e['episode_dir']}: telemetry seed {recorded_seed} is not {e['seed']}")
            header, rows = read_episode(e["episode_dir"])
            record = function(header, rows, selection)
            if (expected_reward_schema_sha256 is not None
                    and record["reward_schema_sha256"] != expected_reward_schema_sha256):
                raise ValueError(f"{e['episode_dir']}: rescored reward schema differs from the audited reward")
            entries.append(_entry(e["seed"], e["episode_dir"], record, return_first))
        result[policy] = dict(episodes=entries)
    return result
