"""Resolve reproducible moving-jammer routes into archived episode inputs."""

import configparser
import json
from pathlib import Path


def motion_enabled(run_config):
    ini = configparser.ConfigParser(inline_comment_prefixes=(";", "#"))
    ini.read(run_config)
    profile = ini.get("rl", "jammer_motion_profile", fallback="")
    if profile not in ("", "sweep_v1"):
        raise ValueError("jammer_motion_profile must be empty or sweep_v1")
    return bool(profile)


def prepare_motion_config(run_config, episode_dir, seed, reset_index, evaluation):
    if not motion_enabled(run_config):
        return str(run_config), None
    source = Path(run_config).resolve()
    ini = configparser.ConfigParser(inline_comment_prefixes=(";", "#"))
    ini.read(source)
    for key in ("nodes_file", "buildings_file", "jammers_file"):
        value = ini.get("scenario", key, fallback="").strip()
        if value:
            ini.set("scenario", key, str((source.parent/value).resolve()))
    jammers = json.loads(Path(ini.get("scenario", "jammers_file")).read_text())
    if len(jammers) != 1:
        raise ValueError("sweep_v1 requires exactly one jammer")
    index = seed if evaluation else reset_index
    reverse = bool(index % 2)
    start = (80 + 20*(seed % 3)) if evaluation else (100 + 20*(reset_index % 3))
    cross = start + 300
    axis = "y" if evaluation else "x"
    first, last = (400, 0) if reverse else (0, 400)
    points = [(start+100, first), (cross, last), (600, 320 if reverse else 80)]
    waypoints = [{"t": 0, "x": 0, "y": 0, "z": 1.5},
                 {"t": start, "x": 0, "y": 0, "z": 1.5}]
    waypoints += [{"t": t, "x": v if axis == "x" else 200,
                   "y": v if axis == "y" else 200, "z": 1.5} for t, v in points]
    jammer = jammers[0]
    jammer.update(waypoints=waypoints, position={k: waypoints[0][k] for k in ("x", "y", "z")},
                  intervals=[], velocity={"vx": 0, "vy": 0, "vz": 0})
    destination = Path(episode_dir)/"motion-inputs"
    destination.mkdir()
    path = destination/"jammers.json"
    path.write_text(json.dumps(jammers, indent=2)+"\n")
    ini.set("scenario", "jammers_file", str(path))
    if not ini.has_section("output"):
        ini.add_section("output")
    ini.set("output", "dir", str(Path(episode_dir).resolve()))
    resolved = destination/"run.ini"
    with resolved.open("w") as handle:
        ini.write(handle)
    return str(resolved), {"profile": "sweep_v1", "axis": axis, "reverse": reverse,
                           "motion_start_s": start, "waypoints": waypoints,
                           "base_run_config": str(source)}
