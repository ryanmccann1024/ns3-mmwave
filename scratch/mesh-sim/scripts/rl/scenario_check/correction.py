"""Prepare the approved correction batch using archived inputs and existing evidence."""

import json
import math
from pathlib import Path
import shutil

from scripts.artifact_io import write_json, sha256_file
from scripts.rl.scenario_check.inputs import read_ini
from scripts.rl.scenario_check.inputs import write_ini
from scripts.rl.scenario_check.inputs import reference_routes
from scripts.rl.scenario_check.geometry import safe_segment
from scripts.rl.scenario_check.validation import jammer_timing


def affected(case):
    return (case['mission'] in ('investigation','jamming') or
            (case['mission']=='recovery' and case['environment']=='urban') or
            (case['mission']=='coverage' and case['peers']==3))


def prepare(previous_output, destination):
    """Author files only; no placement, simulator, build, or training call exists here."""
    previous_output, destination = Path(previous_output).resolve(),Path(destination).resolve()
    if destination.exists():
        raise FileExistsError(f'will not overwrite correction inputs: {destination}')
    source = previous_output/'inputs'
    original = json.loads((source/'scenario-check.json').read_text())
    report_path = previous_output/'scenario_check_report.json'
    report = json.loads(report_path.read_text())
    cases,checks = [],[]
    destination.mkdir(parents=True)
    for original_case in original['cases']:
        if not affected(original_case):
            continue
        case = json.loads(json.dumps(original_case))
        case['placement_benchmarks'] = []
        case['correction_revision'] = 2
        folder = destination/case['name']
        shutil.copytree(source/case['name'],folder)
        nodes = json.loads((folder/'nodes.json').read_text())
        buildings = json.loads((folder/'buildings.json').read_text())
        boxes = [b['bounds'] for b in buildings]
        targets = None
        reason = 'Original reference routes retained.'
        if case['mission']=='coverage':
            if case['environment']=='urban':
                targets = dict(zip(('ground-1','drone-1','vehicle-1'),((195,100),(195,200),(195,300))))
                reason = 'All three peers spread along the clear central avenue, replacing the weak horizontal reference; RF feasibility unverified.'
            else:
                planned = json.loads((previous_output/'planning'/case['name']/'optimization/nodes.json').read_text())
                targets = {n['id']:tuple(5*round(n['position'][axis]/5) for axis in 'xy') for n in planned}
                reason = 'Use rounded endpoints from the archived seed-311 optimized layout, now reached from the shared start rather than teleported.'
        elif case['mission']=='recovery':
            targets = {}
            for node in nodes:
                kind,number = node['id'].rsplit('-',1)
                if kind=='drone':
                    targets[node['id']] = (node['position']['x'],node['position']['y'])
                else:
                    targets[node['id']] = (180 if kind=='ground' else 220,(200,190,220)[int(number)-1])
            reason = 'Survivor endpoint gap reduced from 60 to 40 m; initial deployment, failures, traffic and radio retained.'
        if targets is not None:
            routes = reference_routes(nodes,boxes,targets)
            write_json(folder/'reference.json',dict(reference_version=2,routes=routes,
                targets={k:list(v) for k,v in targets.items()},description=reason,
                reference_only=True,radio_feasibility='unverified_pending_user_run'))
        for config in folder.rglob('*.ini'):
            ini = read_ini(config)
            for key in ('nodes_file','buildings_file','jammers_file'):
                value = ini['scenario'].get(key,'')
                if value:
                    ini['scenario'][key] = str(destination/Path(value).resolve().relative_to(source))
            ini['scenario']['name'] = f'10-23-check-02-{case["name"]}'
            for key in list(ini['rl']):
                if key.startswith('jammer_') or key in ('training_jammer_onsets_s','evaluation_jammer_onsets_s'):
                    del ini['rl'][key]
            write_ini(config,ini)
        for seed,settings in case['seeds'].items():
            if case['mission']=='jamming':
                jammer_timing(folder/settings['run_config'],case,int(seed))
        reference = json.loads((folder/'reference.json').read_text())
        lengths = {}
        for node in nodes:
            start = tuple(node['position'][axis] for axis in 'xyz')
            points = [start]+reference['routes'][node['id']]
            if not safe_segment(start,start,boxes,2) or not all(safe_segment(a,b,boxes,3) for a,b in zip(points,points[1:])):
                raise ValueError(f'illegal start or route: {case["name"]}/{node["id"]}')
            lengths[node['id']] = sum(math.dist(a,b) for a,b in zip(points,points[1:]))
        write_json(folder/'case.json',case)
        checks.append(dict(case=case['name'],initial_nodes_unchanged=sha256_file(folder/'nodes.json')==sha256_file(source/case['name']/'nodes.json'),
            reference_route_length_m=lengths,change=reason))
        cases.append(case)
    assert len(cases)==17
    record = dict(correction_record_version=1,source_output=str(previous_output),
        source_campaign_sha256=sha256_file(source/'scenario-check.json'),source_report_sha256=sha256_file(report_path),
        original_completed_episodes=report['episodes'],original_elapsed_s=json.loads((previous_output/'scenario_check_status.json').read_text())['wall_s'],
        original_results_unchanged=True,stage='reference_checks_only',
        notes=['Investigation secondary targets explicitly support zero in C++ and Python.',
               'Remove inherited onset schedules; audit actual commands and final active interval.',
               'Keep nine-peer jammer power and all acceptance thresholds unchanged.',
               'Do not repeat placement planning or start training.'])
    write_json(destination/'preparation.json',record)
    campaign = dict(scenario_check_version=2,stage='scenario_checks_only',training_enabled=False,
        evaluation_seeds=[201,202],planning_seed=311,optimizer_seed=7,workers=4,
        episodes_expected=102,cases=cases,static_validation=checks,
        source_specification='Approved correction after record 002; append-only record 003',
        previous_output=str(previous_output),placement_searches_expected=0)
    campaign['input_hashes'] = {str(p.relative_to(destination)):sha256_file(p) for p in sorted(destination.rglob('*')) if p.is_file()}
    write_json(destination/'scenario-check.json',campaign)
    return campaign
