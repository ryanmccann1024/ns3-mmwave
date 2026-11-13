"""Mission-first diagnostics and explicit rejection reasons for scenario checks."""

import csv
import json
import math
from pathlib import Path

from scripts.artifact_io import write_json
from scripts.rl.scenario_check.assessment import acceptance as acceptance
from scripts.rl.scenario_check.assessment import reduce_records as reduce_records


def inspect(directory, case, seed, buildings):
    from scripts.rl.policy.episode_review import inspect_episode, write_motion_review
    from scripts.rl.policy.mission_metrics import mission_episode_metrics, read_episode

    directory = Path(directory)
    trace = read_episode(directory)
    header, steps = trace
    mission_metrics = mission_episode_metrics(directory, trace=trace)
    inherited = inspect_episode(
        directory, buildings, trace=trace, metrics=mission_metrics
    )
    write_motion_review(directory, trace=trace, metrics=mission_metrics)
    timing = None
    if case["mission"] == "jamming":
        from scripts.rl.scenario_check.validation import jammer_timing

        episode = json.loads((directory / "rl_episode.json").read_text())
        command = episode["command"]
        config = next(
            x.split("=", 1)[1] for x in command if x.startswith("--run-config=")
        )
        timing = jammer_timing(config, case, seed, command)
    metrics, timeline = reduce_records(
        steps,
        header["contract"],
        case["mission"],
        case["seeds"][str(seed)]["gate_s"],
    )
    if timing is not None:
        metrics["event_timing_verified"] = timing["command_checked"]
        metrics["jammer_emission_end_s"] = timing["end_s"]
    with (directory / "scenario_timeline.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(timeline[0]))
        writer.writeheader()
        writer.writerows(timeline)
    # Pair-level LOS/SINR is useful when average delivery hides topology changes.
    with (directory / "link_timeline.csv").open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "time_s",
                "source",
                "destination",
                "both_available",
                "sinr_db",
                "capacity_mbps",
                "is_los",
            ]
        )
        ids = header["contract"]["node_ids"]
        for row in steps:
            facts = row["facts"]
            for link, (i, j) in zip(
                facts["links"],
                ((i, j) for i in range(len(ids)) for j in range(i + 1, len(ids))),
            ):
                writer.writerow(
                    [
                        row["time_s"],
                        ids[i],
                        ids[j],
                        facts["node_available"][i] and facts["node_available"][j],
                        *link,
                    ]
                )
    if case["mission"] == "jamming":
        onset = timing["onset_s"]
        center = tuple(timing["stationary_position"])
        contract = header["contract"]
        exposure = dict.fromkeys(contract["node_ids"], 0.0)
        for row in steps:
            if (
                row.get("decision", 0) > 0
                and row["time_s"] - contract["decision_interval_s"] >= onset
            ):
                for node, position in zip(contract["node_ids"], row["facts"]["nodes"]):
                    if math.dist(position[:3], center) <= timing["max_range_m"]:
                        exposure[node] += contract["decision_interval_s"]
        metrics["active_in_jammer_range_s_per_node"] = exposure
        metrics["jammer_emission_onset_s"] = onset
        metrics["jammer_range_m"] = timing["max_range_m"]
        metrics["jammer_range_exposure_definition"] = (
            "Decision samples within 140 m 3D cutoff while emitting; this is geometric exposure, not measured interference severity."
        )
    merged = {**inherited, **metrics}
    write_json(directory / "scenario_check_metrics.json", merged)
    return merged


def write_campaign_report(root, outcomes):
    rows = []
    for outcome in outcomes:
        for row in outcome.get("episodes", []):
            rows.append(
                {
                    **{
                        k: outcome[k]
                        for k in ("name", "mission", "environment", "peers")
                    },
                    **row,
                }
            )
    columns = sorted(
        {k for row in rows for k, v in row.items() if not isinstance(v, (dict, list))}
    )
    with (Path(root) / "scenario_episodes.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    write_json(
        Path(root) / "scenario_check_report.json",
        dict(
            scenario_check_report_version=1,
            training_launched=False,
            case_count=len(outcomes),
            episodes=len(rows),
            cases=outcomes,
            interpretation="Two diagnostic seeds test scenario headroom; no learned-policy ranking or statistical generalization claim.",
        ),
    )
    text = [
        "# Scenario check results",
        "",
        "Training was not launched. Open Main for scenario folders; each contains eval_manifest.json and policy episodes.",
        "Exit 0: all scenario gates passed. Exit 2: checks finished, revisions need review. Exit 1: execution or audit errors.",
        "",
        "| Scenario | Status | Review |",
        "| --- | --- | --- |",
    ]
    for o in outcomes:
        reasons = list(o.get("acceptance", {}).get("reasons", []))
        if o.get("error"):
            reasons.insert(0, o["error"])
        if not reasons:
            reasons = ["All gates passed"]
        text.append(f'| {o["name"]} | {o["status"]} | {"; ".join(reasons)} |')
    (Path(root) / "RESULTS.md").write_text("\n".join(text) + "\n")
