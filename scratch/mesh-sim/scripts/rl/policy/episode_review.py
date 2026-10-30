"""Endpoint, physical and motion reviews from saved decision traces.

Formulas are unchanged from their original writers. ``mission_review.json``
payloads stay version 1 with no completion-status field; the reporting owner
decides where they are written. Building/peer path checks
(``physical_audit``) belong to ``scripts.rl.env.geometry``.

- :func:`endpoint_metrics` -- final-window service and post-motion recovery.
- :func:`inspect_episode` -- mission metrics, geometry safety audit and telemetry replay.
- :func:`write_motion_review` -- ``mission_trace.csv`` + ``mission_end_state.json`` (review 1).
- :func:`objective_diagnostics`, :func:`review_metrics`, :func:`objective_key`,
  :func:`mean_metrics`, :func:`scene_review` -- mission review payload builders.
"""

import csv
import json
import math
import statistics
from pathlib import Path

MISSION_REVIEW_VERSION = 1
MOTION_REVIEW_VERSION = 1


def delivery(rows):
    demand = sum(r["facts"]["window"]["demand_mbps_sum"] for r in rows)
    received = sum(r["facts"]["window"]["delivered_mbps_sum"] for r in rows)
    return received/demand if demand > 1e-9 else None


def endpoint_metrics(episode_dir, seconds=60):
    path = Path(episode_dir)
    records = [json.loads(line) for line in (path/"steps.jsonl").open()]
    rows = [r for r in records if r.get("decision", 0) > 0 and r["facts"]["window"]["scored_ticks"] > 0]
    if not rows:
        raise ValueError("endpoint metrics require recorded decisions")
    tail = [r for r in rows if r["time_s"] > rows[-1]["time_s"]-seconds]
    count = len(tail[0]["facts"]["node_service"])
    service = []
    for i in range(count):
        demand = sum(r["facts"]["node_service"][i][0] for r in tail)
        received = sum(r["facts"]["node_service"][i][1] for r in tail)
        if demand > 1e-9:
            service.append(received/demand)
    coverage = [r["facts"]["coverage"]["fraction"] for r in tail]
    episode = json.loads((path/"rl_episode.json").read_text())
    start = (episode.get("jammer_motion") or {}).get("motion_start_s")
    degraded = recovered = None
    streak = 0
    for row in rows:
        if start is None or row["time_s"] <= start:
            continue
        share = delivery([row])
        if share is not None and share < .9:
            if degraded is None:
                degraded = row["time_s"]
            streak = 0
        elif degraded is not None and recovered is None:
            streak += 1
            if streak == 30:
                recovered = row["time_s"]-29*records[0]["contract"]["decision_interval_s"]
    return {"endpoint_window_s": seconds, "endpoint_delivery_ratio": delivery(tail),
            "endpoint_worst_node_delivery": min(service) if service else None,
            "endpoint_coverage_fraction": sum(coverage)/len(coverage),
            "motion_start_s": start, "first_degradation_s": degraded,
            "first_recovery_s": recovered,
            "recovery_after_degradation_s": recovered-degraded if recovered is not None else None}


def inspect_episode(directory, expected_buildings=None):
    from scripts.rl.env.geometry import physical_audit
    from scripts.rl.env.recording.telemetry import replay_file
    from scripts.rl.policy.mission_metrics import mission_episode_metrics
    records = [json.loads(line) for line in (Path(directory)/'steps.jsonl').read_text().splitlines()]
    contract = records[0]['contract']; steps = records[1:]
    if expected_buildings is not None:
        expected = [{'id': b['id'], **b['bounds']} for b in expected_buildings]
        if contract.get('navigation', {}).get('buildings') != expected:
            raise ValueError('simulator and input building geometry differ; rebuild mesh-sim')
    audit = physical_audit(steps, contract)
    replay = replay_file(Path(directory)/'steps.jsonl')
    if replay.obs_mismatches or replay.reward_mismatches:
        raise ValueError('telemetry reconstruction mismatch')
    return {**mission_episode_metrics(directory), **audit}


def write_motion_review(directory):
    from scripts.artifact_io import write_json
    from scripts.rl.policy.mission_metrics import mission_episode_metrics
    directory = Path(directory); data = [json.loads(line) for line in (directory/'steps.jsonl').read_text().splitlines()]
    contract = data[0]['contract']; steps = data[1:]; ids = contract['node_ids']; travel = dict.fromkeys(ids, 0.)
    fields = ['time_s', 'node', 'x', 'y', 'z', 'available', 'cumulative_travel_m', 'step_travel_m', 'delivery_ratio',
              'survivor_delivery', 'coverage', 'team_arrivals', 'building_attempts', 'peer_attempts']
    with (directory/'mission_trace.csv').open('w', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields); writer.writeheader()
        previous = steps[0]['facts']['nodes']
        for record in steps:
            facts = record['facts']; state = facts['mission_state']; window = facts['window']; safety = facts['safety']
            for i, node in enumerate(ids):
                p = facts['nodes'][i]; distance = math.hypot(p[0]-previous[i][0], p[1]-previous[i][1]); travel[node] += distance
                writer.writerow({'time_s': record['time_s'], 'node': node, 'x': p[0], 'y': p[1], 'z': p[2],
                    'available': facts['node_available'][i], 'cumulative_travel_m': travel[node], 'step_travel_m': distance,
                    'delivery_ratio': window['delivered_mbps_sum']/window['demand_mbps_sum'] if window['demand_mbps_sum'] else '',
                    'survivor_delivery': state['survivor_delivery'], 'coverage': facts['coverage']['fraction'],
                    'team_arrivals': state.get('team_arrival_fraction'), 'building_attempts': len(safety.get('building_rejected_slots', [])),
                    'peer_attempts': len(safety.get('peer_rejected_slots', []))})
            previous = facts['nodes']
    write_json(directory/'mission_end_state.json', {'review_version': MOTION_REVIEW_VERSION, 'per_node_travel_m': travel,
        'final_positions': dict(zip(ids, [p[:3] for p in steps[-1]['facts']['nodes']])),
        'metrics': mission_episode_metrics(directory)})


def objective_diagnostics(records, contract):
    rows = [r for r in records if r.get('decision', 0) > 0
            and r['facts']['window']['scored_ticks'] > 0]
    if not rows or rows[-1]['decision'] != contract['num_decisions']:
        raise ValueError('mission review requires a complete episode')
    end = rows[-1]['facts']['mission_state']
    onset = contract.get('jammer_onset_s')
    disrupted = 0.0
    los, sinr = [], []
    for row in rows:
        facts = row['facts']; active = facts['node_available']; index = 0
        values = []
        for i in range(len(active)):
            for j in range(i+1, len(active)):
                link = facts['links'][index]; index += 1
                if active[i] and active[j]:
                    values.append(link)
        if values:
            los.append(statistics.mean(v[2] for v in values))
            valid = [v[0] for v in values if v[0] > -900 and math.isfinite(v[0])]
            if valid:
                sinr.append(statistics.mean(valid))
        start = row['time_s']-row['ticks_in_step']*contract['tick_s']
        window = facts['window']
        if onset is not None and start >= onset and window['demand_mbps_sum'] > 0:
            if window['delivered_mbps_sum']/window['demand_mbps_sum'] < .9:
                disrupted += row['ticks_in_step']*contract['tick_s']
    return {
        'recovery_sustained_final': int(end['failure_at_s'] is not None and
                                        end['recovery_streak_s'] >= contract['mission']['dwell_s']),
        'team_distance_remaining_m': end['distance_m'] if contract['mission']['kind'] == 'investigation' else None,
        'team_arrival_peak_fraction': max(r['facts']['mission_state'].get('team_arrival_fraction', 0) for r in rows),
        'jammer_disruption_s': disrupted if onset is not None else None,
        'active_los_fraction': statistics.mean(los) if los else None,
        'active_mean_sinr_db': statistics.mean(sinr) if sinr else None,
    }


def review_metrics(directory):
    from scripts.rl.env.jammer_motion import emission_onset
    from scripts.rl.policy.metrics import episode_metrics
    directory = Path(directory)
    with (directory/'steps.jsonl').open() as handle:
        header = json.loads(next(handle)); records = [json.loads(line) for line in handle if line.strip()]
    contract = dict(header['contract'])
    episode = json.loads((directory/'rl_episode.json').read_text())
    contract['jammer_onset_s'] = emission_onset(episode)
    return {**episode_metrics(records, contract['num_links'], contract), **objective_diagnostics(records, contract)}


def objective_key(kind, metrics):
    """Lexicographic mission outcome; missing measurements never become healthy zeros."""
    def val(name, default=-1e12):
        v = metrics.get(name)
        return float(v) if isinstance(v, (int, float)) and math.isfinite(v) else default
    attempts = val('building_collision_attempts', 0)+val('peer_collision_attempts', 0)
    safety = -val('unsafe_fraction', 1)
    if kind == 'investigation':
        return (safety, val('investigation_success'), val('team_arrival_fraction_final'),
                -val('team_distance_remaining_m', 1e12), val('final_minute_survivor_delivery'),
                -attempts, -val('travel_m_total', 1e12))
    if kind == 'recovery':
        return (safety, val('recovery_sustained_final'), val('final_minute_survivor_delivery'),
                -val('survivor_outage_s', 1e12), val('post_failure_survivor_delivery'),
                -attempts, -val('travel_m_total', 1e12))
    if kind == 'jamming':
        return (safety, val('final_minute_survivor_delivery'), -val('jammer_disruption_s', 1e12),
                val('post_jammer_delivery_ratio'), -attempts, -val('travel_m_total', 1e12))
    return (safety, int(val('final_minute_survivor_delivery') >= .9),
            val('final_minute_coverage'), val('final_minute_survivor_delivery'),
            -attempts, -val('travel_m_total', 1e12))


def mean_metrics(episodes):
    keys = set().union(*(e.keys() for e in episodes))
    return {key: statistics.mean(values) for key in keys
            if (values := [e[key] for e in episodes if isinstance(e.get(key), (int, float))
                           and math.isfinite(e[key])])}


def _manifest(source):
    """``(record, base)``: a loaded manifest dict (base None) or a manifest file/directory path."""
    if isinstance(source, dict):
        return source, None
    path = Path(source)
    path = path/'eval_manifest.json' if path.is_dir() else path
    return json.loads(path.read_text()), path.parent


def _episode_dir(entry, base, root):
    # Batch (v5) records store leaf-relative episode paths; they belong to their manifest's directory.
    directory = Path(entry['episode_dir'])
    return (directory if directory.is_absolute() else Path(base or root)/directory).resolve()


def scene_review(root, scene, models, baselines=None):
    """The version 1 ``mission_review.json`` payload for one scene of ``final_models``.

    ``baselines`` lists eval-manifest paths (files or their directories) or loaded
    manifests; when None, the legacy ``root/baselines/<scene>/eval_manifest.json``
    is read if present. A scene with no models yields an empty ranking.
    """
    from scripts.artifact_io import sha256_file
    root = Path(root).resolve(); episodes = {}; ranking = []
    subset = [m for m in models if m['scene'] == scene]
    fallback = scene.split('-')[1] if '-' in scene else None
    kind = subset[0].get('mission', fallback) if subset else fallback

    def add(entry, base):
        directory = _episode_dir(entry, base, root)
        relative = directory.relative_to(root).as_posix()
        if relative not in episodes:
            episodes[relative] = {'metrics': review_metrics(directory),
                                  'telemetry_sha256': sha256_file(directory/'steps.jsonl')}
        return {**entry.get('metrics', {}), **episodes[relative]['metrics']}
    for model in subset:
        fixed = Path(model['fixed'])/'eval_manifest.json'
        if not fixed.is_file():
            continue
        record = json.loads(fixed.read_text())
        if record['status'] != 'completed':
            continue
        values = [add(e, fixed.parent) for e in record['policies'].get('model', {}).get('episodes', [])]
        if values:
            means = mean_metrics(values)
            ranking.append({'reward': model['reward'], 'profile': model['profile'],
                            'training_seed': model.get('training_seed', 101), 'stage': model.get('stage', 'pilot'),
                            'label': model.get('label'), 'metrics': means, 'rank_key': objective_key(kind, means)})
        operation = Path(model['operation'])/'online_manifest.json' if model.get('operation') else None
        if operation and operation.is_file():
            for entry in json.loads(operation.read_text()).get('episodes', []):
                if (_episode_dir(entry, operation.parent, root)/'rl_episode.json').is_file():
                    add(entry, operation.parent)
    if baselines is None:
        legacy = root/'baselines'/scene/'eval_manifest.json'
        baselines = [legacy] if legacy.is_file() else []
    for source in baselines:
        record, base = _manifest(source)
        for block in record.get('policies', {}).values():
            for entry in block['episodes']:
                add(entry, base)
    ranking.sort(key=lambda row: tuple(row['rank_key']), reverse=True)
    return {'mission_review_version': MISSION_REVIEW_VERSION, 'objective': kind,
            'ranking_basis': 'Frozen deterministic validation; separate variants and training seeds; not held-out confirmation',
            'ranking': ranking, 'episodes': episodes}


def contact_audit(header,rows,required=True):
    c=header['contract'];b=c['bounds'];previous=None;contacts=0;at_wall=0;active_samples=0
    for row in rows:
        f=row['facts'];seen=f['safety'].get('boundary_contacted_slots')
        if seen is None:
            if required:raise ValueError('rebuild required: simulator has no native boundary contact telemetry')
            return dict(available=False)
        expected=[]
        for slot,node in enumerate(c['slot_node_ids']):
            if node is None:continue
            i=c['node_ids'].index(node)
            if not f['node_available'][i]:continue
            p=f['nodes'][i]
            if row['decision']>0 and contact_eligible(row):
                active_samples+=1
                at_wall+=any(abs(p[a]-b[f'{axis}_{edge}'])<1e-7 for a,axis in enumerate(('x','y')) for edge in ('min','max'))
            if previous is not None:
                a=previous['nodes'][i]
                if any(abs(p[k]-a[k])>1e-8 and (abs(p[k]-b[f'{axis}_min'])<1e-7 or
                     abs(p[k]-b[f'{axis}_max'])<1e-7) for k,axis in enumerate(('x','y'))):expected.append(slot)
        if sorted(seen)!=expected:raise ValueError(f'boundary telemetry disagrees with actual motion at decision {row["decision"]}: {seen} vs {expected}')
        contacts+=len(seen);previous=f
    return dict(available=True,contacts=contacts,active_peer_samples=active_samples,
                boundary_occupancy_fraction=at_wall/active_samples if active_samples else None)


def contact_eligible(row):
    f=row['facts'];g=f.get('deployment');w=f['window']
    return bool(w['scored_ticks']) and (g is None or (g['active'] and g['eligible_ticks']==w['scored_ticks']))
