"""Mission-first diagnostics and explicit rejection reasons for scenario checks."""

import csv
import json
import math
from pathlib import Path
import statistics

from scripts.artifact_io import write_json


def ratio(rows, survivor=False):
    kind = "mission" if survivor else "window"
    prefix = "survivor_" if survivor else ""
    demand = sum(r["facts"][kind][prefix + "demand_mbps_sum"] for r in rows)
    delivered = sum(r["facts"][kind][prefix + "delivered_mbps_sum"] for r in rows)
    return delivered / demand if demand > 1e-9 else None


def reduce_records(records, contract, mission, gate):
    """Keep boundary windows out of event comparisons; do not drop failures."""
    rows = [r for r in records if r.get("decision", 0) > 0]
    if not rows or rows[-1]["decision"] != contract["num_decisions"]:
        raise ValueError("complete decision telemetry required")
    dt = contract["decision_interval_s"]
    tail = [r for r in rows if r["time_s"] > rows[-1]["time_s"] - 60]
    # Strict inequality avoids a mixed pre/post window at the event boundary.
    before = [r for r in rows if r["time_s"] < gate]
    after = [r for r in rows if r["time_s"] - dt >= gate]
    survivor = mission == "recovery"

    def delivered(r):
        return ratio([r], survivor)

    def worst(r):
        return r["facts"]["mission_state"]["survivor_worst_service"]

    streak = 0.0
    first_completion = None
    goal_streak = 0.0
    goal_first = None
    timeline = []
    travel = dict.fromkeys(contract["node_ids"], 0.0)
    previous = records[0]
    for r in rows:
        f = r["facts"]
        for i, node in enumerate(contract["node_ids"]):
            travel[node] += math.dist(
                previous["facts"]["nodes"][i][:3], f["nodes"][i][:3]
            )
        distances = [math.hypot(p[0] - 345, p[1] - 300) for p in f["nodes"]]
        goal_ok = all(d <= 50 + 1e-6 for d in distances)
        goal_streak = goal_streak + dt if goal_ok else 0
        if goal_streak >= 30 and goal_first is None:
            goal_first = r["time_s"]
        post = r["time_s"] - dt >= gate
        ok = post and (delivered(r) or 0) >= 0.9 and worst(r) >= 0.8
        streak = streak + dt if ok else 0
        if streak >= 30 and first_completion is None:
            first_completion = r["time_s"]
        links = [
            link
            for link, (i, j) in zip(
                f["links"],
                (
                    (i, j)
                    for i in range(len(f["nodes"]))
                    for j in range(i + 1, len(f["nodes"]))
                ),
            )
            if f["node_available"][i] and f["node_available"][j]
        ]
        timeline.append(
            dict(
                time_s=r["time_s"],
                delivery=ratio([r]),
                survivor_delivery=ratio([r], True),
                worst_survivor_service=worst(r),
                coverage_fraction=f["coverage"]["fraction"],
                team_arrival_fraction=sum(d <= 50 for d in distances) / len(distances),
                team_max_target_distance_m=max(distances),
                mean_active_link_sinr_db=statistics.mean(link[0] for link in links)
                if links
                else None,
                active_los_fraction=statistics.mean(link[2] for link in links)
                if links
                else None,
                event_active=post,
                event_service_streak_s=streak,
                target_streak_s=goal_streak,
                cumulative_travel_m=sum(travel.values()),
            )
        )
        previous = r
    final = timeline[-1]
    active_tail = [r for r in tail if r["time_s"] - dt >= gate]
    outage = sum(dt for r in after if (delivered(r) or 0) < 0.9)
    result = dict(
        check_metrics_version=1,
        final_minute_coverage=statistics.mean(
            r["facts"]["coverage"]["fraction"] for r in tail
        ),
        final_minute_delivery=ratio(tail),
        pre_event_delivery=ratio(before, survivor),
        post_event_delivery=ratio(after, survivor),
        final_minute_event_delivery=ratio(active_tail, survivor),
        final_minute_worst_service=statistics.mean(worst(r) for r in tail),
        final_sinr_db=final["mean_active_link_sinr_db"],
        final_los_fraction=final["active_los_fraction"],
        final_minute_sinr_db=statistics.mean(
            r["mean_active_link_sinr_db"] for r in timeline[-60:]
        ),
        final_team_arrival_fraction=final["team_arrival_fraction"],
        final_team_max_distance_m=final["team_max_target_distance_m"],
        team_completed_ever=goal_first is not None,
        team_completion_s=goal_first,
        team_sustained_through_end=goal_streak >= 30,
        event_completed_ever=first_completion is not None,
        event_completion_s=first_completion,
        event_delay_s=first_completion - gate if first_completion is not None else None,
        event_sustained_through_end=streak >= 30,
        event_outage_s=outage,
        per_node_travel_m=travel,
        travel_m_total=sum(travel.values()),
    )
    return result, timeline


def inspect(directory, case, seed, buildings):
    from scripts.rl.policy.episode_review import inspect_episode, write_motion_review

    directory = Path(directory)
    inherited = inspect_episode(directory, buildings)
    write_motion_review(directory)
    data = [
        json.loads(line)
        for line in (directory / "steps.jsonl").read_text().splitlines()
    ]
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
        data[1:],
        data[0]["contract"],
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
        ids = data[0]["contract"]["node_ids"]
        for row in data[1:]:
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
        contract = data[0]["contract"]
        exposure = dict.fromkeys(contract["node_ids"], 0.0)
        for row in data[1:]:
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


def acceptance(case, results):
    """Require both diagnostic seeds to pass; placement episodes do not satisfy gates."""
    reasons = []
    thresholds = None
    for seed in (201, 202):
        hold, script = (results[(p, seed)] for p in ("hold", "scripted"))

        def require(condition, text):
            if not condition:
                reasons.append(f"seed {seed}: {text}")

        mission = case["mission"]
        if mission == "coverage":
            gain = script["final_minute_coverage"] - hold["final_minute_coverage"]
            require(gain >= 0.05, f"scripted coverage gain {gain:.4f} is below 0.05")
            require(
                (script["final_minute_delivery"] or 0) >= 0.9,
                "scripted coverage loses service below 90%",
            )
        elif mission == "investigation":
            require(
                not hold["team_completed_ever"], "hold already completes investigation"
            )
            require(
                script["team_sustained_through_end"],
                "scripted team does not sustain all-peer arrival for final 30 s",
            )
        else:
            require(
                (hold["pre_event_delivery"] or 0) >= 0.9,
                "held pre-event service is below 90%",
            )
            require(
                hold["final_minute_event_delivery"] is not None
                and hold["final_minute_event_delivery"] < 0.6,
                "held final event service is not below 60%",
            )
            require(
                (script["final_minute_event_delivery"] or 0) >= 0.9,
                "scripted final event delivery is below 90%",
            )
            require(
                script["final_minute_worst_service"] >= 0.8,
                "scripted worst final service is below 80%",
            )
            require(
                script["event_sustained_through_end"],
                "scripted service is not sustained for final 30 s",
            )
    if case["mission"] == "coverage":
        h = max(results[("hold", s)]["final_minute_coverage"] for s in (201, 202))
        s = min(results[("scripted", s)]["final_minute_coverage"] for s in (201, 202))
        if s - h >= 0.05:
            thresholds = dict(
                hold_upper=h,
                scripted_lower=s,
                proposed_target=(h + s) / 2,
                status="proposed_only_requires_review_before_training",
            )
        else:
            reasons.append("no common two-seed coverage threshold with 0.05 headroom")
    return dict(accepted=not reasons, reasons=reasons, coverage_threshold=thresholds)


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
        "# October 23 scenario check results",
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
