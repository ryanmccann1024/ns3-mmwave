"""Training-only starts from an archived safe reference path; no action guidance.

A curriculum schedule maps the stages `near`, `intermediate` and `original` to
`run.ini` files that differ only in node start positions. `CurriculumEnv` is an
`env_factory` hook: `partial(CurriculumEnv, schedule=...)` receives the usual
`MeshRlEnv` arguments, and switches only the reset input by completed episodes.
"""

import copy
import json
import math
from pathlib import Path

from scripts.artifact_io import write_json, sha256_file
from scripts.rl.env.config import read_scenario_identity
from scripts.rl.env.geometry import segment_hits
from scripts.rl.env.mesh_env import MeshRlEnv

CURRICULUM_STAGES = ("near", "intermediate", "original")
# Completed episodes per stage; the last stage continues for the remaining budget.
STAGE_EPISODES = (("near", 5), ("intermediate", 5), ("original", 15))


def validate_positions(nodes, buildings):
    points = [[n["position"][a] for a in "xyz"] for n in nodes]
    for n, p in zip(nodes, points):
        if n["role"] != "peer" or n["node_type"] not in ("pedestrian", "drone", "vehicle"):
            raise ValueError("curriculum must preserve peer types")
        if not all(0 <= p[a] <= 400 for a in (0, 1)) or p[2] != (
            20.0 if n["node_type"] == "drone" else 1.5
        ):
            raise ValueError("curriculum bounds or fixed altitude changed")
        if any(segment_hits(p, p, b["bounds"], 2.0) for b in buildings):
            raise ValueError("curriculum starts violate building clearance")
    minimum = min(math.dist(a, b) for i, a in enumerate(points) for b in points[i + 1 :])
    if minimum < 5.0 - 1e-6:
        raise ValueError("curriculum starts violate peer separation")
    distances = [math.dist(p[:2], [345.0, 300.0]) for p in points]
    return dict(
        minimum_separation_m=minimum,
        furthest_target_distance_m=max(distances),
        nearest_target_distance_m=min(distances),
        positions=points,
    )


def starts_from_reference(header, rows, nodes, buildings):
    """Select the first legal joint frame below 120/210 m, independent of learned scores."""
    result = {}
    if header["contract"]["node_ids"] != [n["id"] for n in nodes]:
        raise ValueError("reference node order changed")
    for stage, limit in (("near", 120.0), ("intermediate", 210.0)):
        for row in rows:
            if not all(row["facts"]["node_available"]):
                continue
            candidate = copy.deepcopy(nodes)
            for node, point in zip(candidate, row["facts"]["nodes"]):
                node["position"] = dict(zip("xyz", point[:3]))
            try:
                check = validate_positions(candidate, buildings)
            except ValueError:
                continue
            if 50.0 < check["furthest_target_distance_m"] <= limit:
                result[stage] = dict(
                    nodes=candidate, evidence=dict(reference_time_s=row["time_s"], **check)
                )
                break
        if stage not in result:
            raise ValueError(f"no legal {stage} curriculum frame")
    if (
        result["near"]["evidence"]["furthest_target_distance_m"]
        >= result["intermediate"]["evidence"]["furthest_target_distance_m"]
    ):
        raise ValueError("curriculum distances are not ordered")
    return result


def load_curriculum_schedule(path) -> dict:
    """Read a stage -> run.ini mapping, as stored in a variant's `curriculum_configs`.

    The file is either that mapping or an object holding it under
    `curriculum_configs`. Relative INI paths resolve against the file's folder.
    Returns `path`, the file's `sha256`, the resolved `schedule` (stage -> Path,
    the `CurriculumEnv` argument) and each INI's `config_sha256`.
    """
    path = Path(path).resolve()
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and "curriculum_configs" in data:
        data = data["curriculum_configs"]
    if not isinstance(data, dict) or set(data) != set(CURRICULUM_STAGES):
        raise ValueError(
            f"{path}: curriculum schedule must map exactly {list(CURRICULUM_STAGES)} to run.ini files"
        )
    schedule = {}
    for stage in CURRICULUM_STAGES:
        value = data[stage]
        if not isinstance(value, str) or not value:
            raise ValueError(f"{path}: curriculum stage {stage!r} must name a run.ini file")
        config = Path(value)
        if not config.is_absolute():
            config = path.parent / config
        if not config.is_file():
            raise ValueError(f"{path}: curriculum stage {stage!r} run.ini not found: {config}")
        schedule[stage] = config
    return dict(
        path=str(path),
        sha256=sha256_file(path),
        schedule=schedule,
        config_sha256={stage: sha256_file(config) for stage, config in schedule.items()},
    )


class CurriculumEnv(MeshRlEnv):
    """Switch only reset inputs; count completed episodes, not space-probe resets."""

    def __init__(self, *args, schedule, **kwargs):
        self.schedule = schedule
        self.completed_episodes = 0
        self.reset_records = []
        super().__init__(*args, **kwargs)

    def stage(self):
        return (
            "near"
            if self.completed_episodes < 5
            else "intermediate"
            if self.completed_episodes < 10
            else "original"
        )

    def reset(self, *, seed=None, options=None):
        stage = self.stage()
        config = self.schedule[stage]
        # One persistent session keeps output numbering unique across starts.
        # All non-start settings (including no jammer in investigation) are pinned.
        self._run_config = str(config)
        self._session._run_config = str(config)
        initial = super().reset(seed=seed, options=options)
        self.reset_records.append(
            dict(
                episode_dir=str(self._session._episode_dir),
                stage=stage,
                completed_before_reset=self.completed_episodes,
                config=str(config),
                scenario_identity=read_scenario_identity(str(config)),
                initial_positions=copy.deepcopy(self._protocol.facts["nodes"]),
                completed=False,
            )
        )
        self._write_schedule()
        return initial

    def step(self, action):
        result = super().step(action)
        if result[2] or result[3]:
            self.completed_episodes += 1
            self.reset_records[-1]["completed"] = True
            self._write_schedule()
        return result

    def _write_schedule(self):
        write_json(
            self._output_dir / "curriculum.json",
            dict(
                curriculum_version=1,
                nominal_train_manifest_identity="original evaluation scenario; actual training identities are recorded per reset here and in each simulator command",
                schedule=[
                    dict(
                        stage=s,
                        completed_episodes=n,
                        run_config=str(self.schedule[s]),
                        config_sha256=sha256_file(self.schedule[s]),
                    )
                    for s, n in STAGE_EPISODES
                ],
                resets=self.reset_records,
            ),
        )
