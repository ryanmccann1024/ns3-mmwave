"""Reward rows and aligned curves from complete, fully recorded episodes."""

import csv
import json
import math
from pathlib import Path

from scripts.rl.cli_common import write_json


def aggregate_rows(rows):
    """Average each available decision without padding missing observations with zero."""
    width = max((len(row) for row in rows), default=0)
    means, deviations, counts = [], [], []
    for index in range(width):
        values = [row[index] for row in rows if index < len(row)]
        mean = sum(values) / len(values)
        means.append(mean)
        counts.append(len(values))
        deviations.append(math.sqrt(sum((value-mean)**2 for value in values)/(len(values)-1))
                          if len(values) > 1 else None)
    return {"mean": means, "sample_std": deviations, "episodes_per_timestep": counts}


def write_reward_matrix(results, output):
    """Save episode-by-decision rewards, components, and cumulative curves beside evaluation."""
    episodes, rows, component_rows, times = [], [], {}, None
    excluded = []
    for result in results:
        if result.status != "completed" or not result.episode_dir:
            continue
        path = Path(result.episode_dir)/"steps.jsonl"
        if not path.is_file():
            excluded.append({"seed": result.seed, "reason": "missing telemetry"})
            continue
        records = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
        steps = [record for record in records if record.get("type") == "step"
                 and record.get("decision", 0) > 0]
        if [s["decision"] for s in steps] != list(range(1, result.decisions+1)):
            excluded.append({"seed": result.seed, "reason": "incomplete decision telemetry"})
            continue
        row_times = [step["time_s"] for step in steps]
        if times is None:
            times = row_times
        if row_times != times:
            raise ValueError("reward matrix requires equal decision times across episodes")
        episodes.append({"seed": result.seed, "episode_dir": result.episode_dir})
        rows.append([float(step["reward"]["total"]) for step in steps])
        for component in steps[0]["reward"].get("components", {}) if steps else ():
            component_rows.setdefault(component, []).append(
                [step["reward"]["components"][component] for step in steps])
    cumulative = []
    for row in rows:
        total, values = 0.0, []
        for value in row:
            total += value
            values.append(total)
        cumulative.append(values)
    payload = {"reward_matrix_version": 1, "episodes": episodes, "excluded": excluded,
               "time_s": times or [], "reward": rows, "reward_curve": aggregate_rows(rows),
               "cumulative_reward_curve": aggregate_rows(cumulative),
               "components": {name: {"rows": values, "curve": aggregate_rows(values)}
                              for name, values in component_rows.items()}}
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    write_json(output/"reward_matrix.json", payload)
    with (output/"reward_matrix.csv").open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["seed", *[f"decision_{i+1}" for i in range(len(times or []))]])
        for episode, row in zip(episodes, rows):
            writer.writerow([episode["seed"], *row])
    return payload
