"""Geometry, safe routes, curriculum, seeded environments and saved-model compatibility."""

import copy
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import zipfile
from functools import partial
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from scripts.rl.env import curriculum as curriculum_module
from scripts.rl.env.curriculum import (CurriculumEnv, load_curriculum_schedule,
                                       starts_from_reference, validate_positions)
from scripts.rl.env.geometry import physical_audit, route, safe_segment, segment_hits, swept_distance
from scripts.rl.env.seeded_env import SeededEnv
from scripts.rl.policy.scripted import ReferencePolicy, ScriptedMissionPolicy
from scripts.rl.tests.conftest import MULTI_RUN_INI, NODES_JSON
from scripts.sim_support import find_mesh_root

MESH_ROOT = find_mesh_root()
BOX = {'x_min': 20, 'x_max': 40, 'y_min': -5, 'y_max': 30, 'z_min': 0, 'z_max': 10}


SEGMENTS = [
    ([5, 20, 1.5], [35, 20, 1.5], BOX, 2),
    ([5, 20, 20], [35, 20, 20], BOX, 2),
    ([5, 20, 9], [35, 20, 9], BOX, 2),
    ([5, 5, 1.5], [10, 35, 1.5], BOX, 0),
    ([30, 10, 5], [30, 10, 5], BOX, 0),
    ([0, 0, 0], [100, 100, 0], BOX, 0),
    ([19, -100, 5], [19, 100, 5], BOX, 0.5),
    ([19, -100, 5], [19, 100, 5], BOX, 1.5),
]


def test_segment_hits_fixed_values():
    assert [segment_hits(a, b, box, c) for a, b, box, c in SEGMENTS] == [
        True, False, True, False, True, True, False, True]
    assert safe_segment([0, 0, 1.5], [10, 0, 1.5], [BOX]) and not safe_segment([0, 20, 1.5], [50, 20, 1.5], [BOX])


def test_physical_audit_expected_values():
    contract = {'navigation': {'buildings': [BOX], 'building_clearance_m': 2}, 'unsafe_separation_m': 5}
    safe = [{'facts': {'nodes': [[0, 0, 20], [10, 50, 1.5]], 'node_available': [True, True]}},
            {'facts': {'nodes': [[3, 0, 20], [10, 45, 1.5]], 'node_available': [True, True]}}]
    assert physical_audit(safe, contract) == {'building_penetrations': 0, 'peer_collisions': 0,
                                               'min_swept_peer_distance_m': pytest.approx((45**2 + 7**2 + 18.5**2)**.5)}
    crossing = [{'facts': {'nodes': [[0, 60, 0], [10, 60, 0]], 'node_available': [True, True]}},
                {'facts': {'nodes': [[10, 60, 0], [0, 60, 0]], 'node_available': [True, True]}}]
    with pytest.raises(ValueError, match='peer collision'):
        physical_audit(crossing, contract)
    through = [{'facts': {'nodes': [[0, 10, 1.5]], 'node_available': [True]}},
               {'facts': {'nodes': [[60, 10, 1.5]], 'node_available': [True]}}]
    with pytest.raises(ValueError, match='crosses a building'):
        physical_audit(through, contract)


def test_route_and_swept_distance_fixed_values():
    # Expected values come from the scenario_check implementation moved verbatim.
    assert route((0, 0, 1.5), (60, 10, 1.5), [BOX]) == [
        [0, 10, 1.5], [15, 10, 1.5], [15, 35, 1.5], [45, 35, 1.5], [45, 10, 1.5], [60, 10, 1.5]]
    assert route((0, 0, 20), (60, 10, 20), [BOX]) == [[0, 10, 20], [60, 10, 20]]
    assert route((12, 12, 1.5), (12, 12, 1.5), []) == [[12, 12, 1.5]]
    with pytest.raises(ValueError, match='start cannot reach'):
        route((30, 10, 1.5), (60, 10, 1.5), [BOX])
    assert swept_distance((0, 0, 0), (10, 0, 0), (10, 0, 0), (0, 0, 0)) == 0
    assert swept_distance((0, 0, 20), (10, 0, 20), (10, 0, 1.5), (0, 0, 1.5)) == 18.5


def _nodes(points, types=('drone', 'vehicle', 'pedestrian')):
    return [dict(id=f'n{i}', role='peer', node_type=t, position=dict(zip('xyz', p)))
            for i, (t, p) in enumerate(zip(types, points))]


def test_validate_positions_rejects_violations():
    buildings = [{'bounds': {'x_min': 100, 'x_max': 120, 'y_min': 100, 'y_max': 120, 'z_min': 0, 'z_max': 30}}]
    nodes = _nodes([(300, 280, 20.), (310, 290, 1.5), (330, 300, 1.5)])
    assert validate_positions(nodes, buildings)['minimum_separation_m'] >= 5
    for change, message in ((lambda n: n[0]['position'].update(z=1.5), 'altitude'),
                            (lambda n: n[1]['position'].update(x=401), 'bounds'),
                            (lambda n: n[1]['position'].update(x=99, y=110), 'building clearance'),
                            (lambda n: n[2]['position'].update(x=311, y=291), 'peer separation'),
                            (lambda n: n[0].update(role='relay'), 'peer types')):
        bad = copy.deepcopy(nodes)
        change(bad)
        with pytest.raises(ValueError, match=message):
            validate_positions(bad, buildings)


def test_starts_from_reference_expected_values():
    nodes = _nodes([(0, 0, 20.), (10, 0, 1.5), (20, 0, 1.5)])
    header = {'contract': {'node_ids': [n['id'] for n in nodes]}}
    rows = []
    for t, distance in enumerate((400, 250, 200, 150, 110, 80)):
        x = 345 - distance
        rows.append({'time_s': float(t), 'facts': {'node_available': [True, True, t != 1],
                     'nodes': [[x, 300, 20.], [x+6, 300, 1.5], [x+12, 300, 1.5]]}})
    result = starts_from_reference(header, rows, nodes, [])
    assert result['near']['evidence']['reference_time_s'] == 4.0
    assert result['intermediate']['evidence']['reference_time_s'] == 2.0
    with pytest.raises(ValueError, match='node order'):
        starts_from_reference({'contract': {'node_ids': ['x']}}, rows, nodes, [])


def test_pinned_curriculum_frames_validate_pinned_frames():
    cases = sorted((MESH_ROOT/'inputs/custom/10-23-6').glob('*/curriculum/evidence.json'))
    if not cases:
        pytest.skip('local 10-23-6 curriculum inputs unavailable')
    for evidence in cases:
        case = evidence.parent.parent
        buildings = json.loads((case/'buildings.json').read_text())
        for stage, limit in (('near', 120), ('intermediate', 210)):
            nodes = json.loads((evidence.parent/stage/'nodes.json').read_text())
            check = validate_positions(nodes, buildings)
            assert validate_positions(nodes, buildings)['minimum_separation_m'] >= 5
            assert check['minimum_separation_m'] >= 5 and check['furthest_target_distance_m'] <= limit


def _stub_curriculum(tmp_path, monkeypatch):
    from scripts.rl.env.mesh_env import MeshRlEnv
    env = object.__new__(CurriculumEnv)
    env.schedule = {s: tmp_path/s for s in ('near', 'intermediate', 'original')}
    env.completed_episodes = 0
    env.reset_records = []
    env._session = SimpleNamespace(_episode_dir=tmp_path)
    env._protocol = SimpleNamespace(facts={'nodes': [[0, 0, 1.5]]})
    env._output_dir = tmp_path
    monkeypatch.setattr(MeshRlEnv, 'reset', lambda *a, **k: ('observation', {}))
    monkeypatch.setattr(MeshRlEnv, 'step', lambda *a, **k: ('observation', 0, True, False, {}))
    monkeypatch.setattr(curriculum_module, 'read_scenario_identity', lambda p: {'config': p})
    return env


def test_curriculum_counts_completed_episodes_not_probe_resets(tmp_path, monkeypatch):
    env = _stub_curriculum(tmp_path, monkeypatch)
    monkeypatch.setattr(env, '_write_schedule', lambda: None)
    env.reset()
    env.reset()  # initial space probe and learner reset both stay near
    assert env.completed_episodes == 0
    for _ in range(25):
        env.step([4])
        env.reset()
    assert [r['stage'] for r in env.reset_records if r['completed']] == ['near']*5+['intermediate']*5+['original']*15
    assert env.stage() == 'original'
    assert env._run_config == str(tmp_path/'original') == env._session._run_config


def test_curriculum_schedule_file_records_stage_hashes(tmp_path, monkeypatch):
    for stage in ('near', 'intermediate', 'original'):
        (tmp_path/stage).write_text(stage)
    env = _stub_curriculum(tmp_path, monkeypatch)
    env.reset()
    env.step([4])
    written = json.loads((tmp_path/'curriculum.json').read_text())
    assert written['curriculum_version'] == 1
    assert [(s['stage'], s['completed_episodes']) for s in written['schedule']] == [
        ('near', 5), ('intermediate', 5), ('original', 15)]
    assert written['schedule'][0]['config_sha256'] == hashlib.sha256(b'near').hexdigest()
    assert written['resets'][0]['completed'] is True and written['resets'][0]['stage'] == 'near'


def test_load_curriculum_schedule_hashes_and_validates(tmp_path):
    for stage in ('near', 'intermediate'):
        (tmp_path/stage).mkdir()
        (tmp_path/stage/'run.ini').write_text(f'[scenario]\nname = {stage}\n')
    (tmp_path/'run.ini').write_text('[scenario]\nname = original\n')
    mapping = {'near': 'near/run.ini', 'intermediate': 'intermediate/run.ini', 'original': str(tmp_path/'run.ini')}
    path = tmp_path/'schedule.json'
    path.write_text(json.dumps(mapping))
    loaded = load_curriculum_schedule(path)
    assert loaded['sha256'] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert loaded['schedule'] == {'near': tmp_path/'near/run.ini', 'intermediate': tmp_path/'intermediate/run.ini',
                                  'original': tmp_path/'run.ini'}
    assert loaded['config_sha256']['near'] == hashlib.sha256(b'[scenario]\nname = near\n').hexdigest()
    wrapped = tmp_path/'variant.json'
    wrapped.write_text(json.dumps({'curriculum_configs': mapping, 'key': 'x'}))
    assert load_curriculum_schedule(wrapped)['schedule'] == loaded['schedule']
    for bad, message in (({k: v for k, v in mapping.items() if k != 'near'}, 'exactly'),
                         ({**mapping, 'far': 'run.ini'}, 'exactly'),
                         ({**mapping, 'near': 'missing.ini'}, 'not found'),
                         ({**mapping, 'near': 3}, 'must name')):
        path.write_text(json.dumps(bad))
        with pytest.raises(ValueError, match=message):
            load_curriculum_schedule(path)


def _stub_seeded(monkeypatch):
    from scripts.rl.env import mesh_env, selection
    created = []

    class StubEnv:
        def __init__(self, binary, config, **kwargs):
            self.config, self.kwargs, self.closed = config, kwargs, False
            created.append(self)

        def close(self):
            self.closed = True

        def reset(self, **kwargs):
            return self.config, kwargs

    monkeypatch.setattr(mesh_env, 'MeshRlEnv', StubEnv)
    monkeypatch.setattr(selection, 'resolve_selection', lambda config, **k: ('selection', config, k))
    return created


def test_seeded_env_selects_per_seed_config_and_passes_seed_source(monkeypatch, tmp_path):
    created = _stub_seeded(monkeypatch)
    case = dict(seeds={'101': dict(gate_s=5), '201': dict(gate_s=160), '202': dict(gate_s=180)})
    env = SeededEnv('bin', {'101': 'a.ini', '201': 'one.ini', '202': 'two.ini'}, tmp_path, case, initial_seed=101)
    try:
        assert created[0].config == 'a.ini' and env.gate_s == 5 and created[0].kwargs['seed'] == 101
        config, kwargs = env.reset(seed=202, options={'seed_source': 'eval'})
        assert config == 'two.ini' and env.gate_s == 180
        assert kwargs == {'seed': 202, 'options': {'seed_source': 'eval'}}
        assert created[0].closed and env.inner is created[1]
        assert created[1].kwargs['selection'] == ('selection', 'two.ini', {'telemetry': 'steps'})
        assert all(e.kwargs['output_dir'] == str(tmp_path) for e in created)
        assert all(e.kwargs['band'] is None and e.kwargs['decision_records'] is None for e in created)
        assert env.config == 'two.ini'  # attribute delegation to the live env
    finally:
        env.close()
    with pytest.raises(TypeError):
        SeededEnv('bin', {'201': 'one.ini'}, tmp_path, case)


def test_seeded_env_band_resolution_from_ini_or_explicit(monkeypatch, tmp_path):
    created = _stub_seeded(monkeypatch)
    (tmp_path/'sub6.ini').write_text('[channel]\nband = sub-6   # inline comment\n')
    (tmp_path/'plain.ini').write_text('[scenario]\nname = plain\n')
    configs = {'201': str(tmp_path/'sub6.ini'), '202': str(tmp_path/'plain.ini')}
    case = dict(seeds={'201': dict(gate_s=0), '202': dict(gate_s=0)})
    env = SeededEnv('bin', configs, tmp_path/'out', case, initial_seed=201)
    try:
        assert (env.band, env.band_source) == ('sub-6', 'run.ini') and created[-1].kwargs['band'] is None
        env.reset(seed=202)
        assert (env.band, env.band_source) == ('mmwave', 'default') and created[-1].kwargs['band'] is None
    finally:
        env.close()
    env = SeededEnv('bin', configs, tmp_path/'out', case, initial_seed=202, band='sub-6')
    try:
        assert (env.band, env.band_source) == ('sub-6', 'cli') and created[-1].kwargs['band'] == 'sub-6'
        env.reset(seed=201)
        assert (env.band, env.band_source) == ('sub-6', 'cli') and created[-1].kwargs['band'] == 'sub-6'
    finally:
        env.close()


def test_seeded_env_forwards_decision_records_to_every_seed(monkeypatch, tmp_path):
    from scripts.rl.env.recording.decisions import DecisionRecording
    created = _stub_seeded(monkeypatch)
    records = object.__new__(DecisionRecording)
    case = dict(seeds={'201': dict(gate_s=0), '202': dict(gate_s=0)})
    env = SeededEnv('bin', {'201': 'one.ini', '202': 'two.ini'}, tmp_path, case, initial_seed=201,
                    decision_records=records)
    try:
        env.reset(seed=202)
        env.reset(seed=201)
        assert len(created) == 3 and all(e.kwargs['decision_records'] is records for e in created)
    finally:
        env.close()


def test_scenario_check_seeded_env_keeps_legacy_initial_seed_and_cancel(monkeypatch, tmp_path):
    created = _stub_seeded(monkeypatch)
    from scripts.rl.scenario_check import execution
    env = execution.SeededEnv('bin', {'201': 'one.ini', '202': 'two.ini'}, tmp_path,
                              dict(seeds={'201': dict(gate_s=160), '202': dict(gate_s=180)}))
    try:
        assert created[0].config == 'one.ini' and env in execution._ACTIVE
        assert created[0].kwargs['band'] == 'sub-6' and env.band == 'sub-6'
        assert created[0].kwargs['decision_records'] is None
        execution._CANCEL.set()
        with pytest.raises(RuntimeError, match='interrupted'):
            env.reset(seed=202)
    finally:
        execution._CANCEL.clear()
        env.close()
    assert env not in execution._ACTIVE


def _facts_env(facts, gate_s=None):
    env = SimpleNamespace(_protocol=SimpleNamespace(facts=facts))
    if gate_s is not None:
        env.gate_s = gate_s
    return env


WAYPOINT_CONTRACT = {'max_controlled_nodes': 2, 'node_ids': ['a', 'b'], 'slot_node_ids': ['a', 'b'],
                     'slot_speed_mps': [2, 2], 'decision_interval_s': 1}


@pytest.mark.parametrize('reference,expected', [
    ({'node_order': ['a', 'b'], 'waypoints': {'a': [[10, 0]], 'b': [[10, 20]]}, 'start_after_failure': False}, [1, 4]),
    ({'node_order': ['a', 'b'], 'waypoints': {'a': [[10, 0]], 'b': [[10, 20]]}, 'start_after_failure': False,
      'parallel': True}, [1, 1]),
    ({'node_order': ['a', 'b'], 'waypoints': {'a': [[0, -9]], 'b': [[0, 30]]}, 'start_after_failure': False,
      'parallel': True}, [2, 3]),
    ({'node_order': ['a', 'b'], 'waypoints': {'a': [[10, 0]], 'b': [[10, 20]]}, 'start_after_failure': True}, [4, 4]),
    ({'node_order': ['a', 'b'], 'waypoints': {'a': [[10, 0]], 'b': [[10, 20]]}, 'start_after_failure': False,
      'start_after_s': 5}, [4, 4]),
    ({'node_order': ['b', 'a'], 'waypoints': {'a': [[0.5, 0], [10, 0]], 'b': [[0, 20]]}, 'start_after_failure': False},
     [1, 4]),
])
def test_scripted_mission_policy_waypoint_format_expected_values(reference, expected):
    facts = {'nodes': [[0, 0, 0], [0, 20, 0]], 'node_available': [True, True], 'mission_state': {'time_s': 1}}
    mask = np.ones(10, dtype=bool)
    actions = []
    for policy_type in (ScriptedMissionPolicy,):
        policy = policy_type(_facts_env(facts), reference)
        policy.start_episode(201)
        actions.append(policy.act(None, mask, WAYPOINT_CONTRACT).tolist())
    assert actions == [expected]


def test_scripted_mission_policy_waits_for_delivery_trigger_and_mask():
    reference = {'node_order': ['a'], 'waypoints': {'a': [[10, 0]], 'b': []}, 'start_after_failure': False,
                 'start_below_delivery': .5}
    facts = {'nodes': [[0, 0, 0], [0, 20, 0]], 'node_available': [True, True],
             'mission_state': {'time_s': 1, 'survivor_delivery': .9}}
    policy = ScriptedMissionPolicy(_facts_env(facts), reference)
    policy.start_episode(1)
    mask = np.ones(10, dtype=bool)
    assert policy.act(None, mask, WAYPOINT_CONTRACT).tolist() == [4, 4]
    facts['mission_state']['survivor_delivery'] = .2
    mask[1] = False
    assert policy.act(None, mask, WAYPOINT_CONTRACT).tolist() == [4, 4]
    facts['mission_state']['survivor_delivery'] = .9  # stays triggered once started
    assert policy.act(None, np.ones(10, dtype=bool), WAYPOINT_CONTRACT).tolist() == [1, 4]


ROUTE_CONTRACT = {'max_controlled_nodes': 3, 'num_controlled': 2, 'node_ids': ['a', 'b'], 'slot_node_ids': ['a', 'b', None],
                  'slot_speed_mps': [2, 2, None], 'decision_interval_s': 1, 'unsafe_separation_m': 1}


def test_reference_policy_routes_format_gate_and_swept_reservation():
    facts = {'nodes': [[0, 0, 1.5], [3, 5, 1.5]], 'node_available': [True, True], 'mission_state': {'time_s': 10}}
    reference = {'routes': {'a': [[10, 0, 1.5]], 'b': [[3, 15, 1.5]]}}
    mask = np.ones(15, dtype=bool)
    policy = ReferencePolicy(_facts_env(facts, gate_s=20), reference)
    policy.start_episode(201)
    assert policy.act(None, mask, ROUTE_CONTRACT).tolist() == [4, 4, 4]
    policy.env.gate_s = 0
    assert policy.act(None, mask, ROUTE_CONTRACT).tolist() == [1, 3, 4]
    # Moving toward a peer that holds inside the separation margin is not proposed.
    facts['nodes'][1] = [2.5, 0, 1.5]
    reference['routes']['b'] = [[2.5, 0, 1.5]]
    policy = ReferencePolicy(_facts_env(facts, gate_s=0), reference)
    policy.start_episode(201)
    assert policy.act(None, mask, ROUTE_CONTRACT).tolist() == [4, 4, 4]


def test_reference_policy_random_valid_uses_only_masked_actions():
    facts = {'nodes': [[0, 0, 1.5], [3, 0, 1.5]], 'node_available': [True, True], 'mission_state': {'time_s': 10}}
    mask = np.zeros(15, dtype=bool)
    mask[[2, 4, 5+0, 10+4]] = True
    policy = ReferencePolicy(_facts_env(facts, gate_s=0), {'routes': {'a': [], 'b': []}}, random_valid=True)
    policy.start_episode(7)
    for _ in range(10):
        a, b, c = policy.act(None, mask, ROUTE_CONTRACT).tolist()
        assert a in (2, 4) and b == 0 and c == 4


def test_scenario_check_geometry_reexports_owners():
    from scripts.rl.scenario_check import geometry
    assert geometry.ReferencePolicy is ReferencePolicy
    assert geometry.route is route and geometry.safe_segment is safe_segment
    assert geometry.swept_distance is swept_distance


MISSION_INI = MULTI_RUN_INI.replace(
    'controlled_nodes = node-b, node-c', 'controlled_nodes = node-a, node-b, node-c'
).replace('reward_type = all_links_los', 'reward_type = all_links_los\ncoverage_enabled = true\n'
          'observation_preset = mission_compact_v1\nreward_components = available_target_arrival_fraction_v1\n'
          'reward_weights = 1') + (
    '\n[mission]\nkind = investigation\ninvestigator_id = node-b\ngoal_x = 80\ngoal_y = 40\n'
    'team_investigation = true\nteam_radius_m = 50\n')

# Run in a fresh interpreter that refuses any phase-numbered env module, so the
# load proves the ZIP and live registries need only the functional names.
LOAD_SCRIPT = r'''
import hashlib, importlib.abc, json, re, sys
LEGACY = re.compile(r"scripts\.rl\.(env\.phase\d_|phase_|pilot_reference)")
class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path, target=None):
        if LEGACY.match(name):
            raise ImportError("blocked legacy module " + name)
sys.meta_path.insert(0, Block())
mode, target = sys.argv[1], sys.argv[2]
if mode == "bundle":
    from scripts.rl.env.config import read_scenario_identity
    from scripts.rl.env.mesh_env import MeshRlEnv
    from scripts.rl.policy.bundle import load_model, read_bundle, selection_from_manifest
    from scripts.rl.policy.compat import check_compatibility
    from scripts.rl.policy.training import mask_fn
    bundle = read_bundle(target, "final")
    manifest = bundle.manifest
    run_config = sys.argv[4]
    env = MeshRlEnv(sys.argv[3], run_config, seed=1, output_dir=sys.argv[5],
                    selection=selection_from_manifest(manifest))
    try:
        env.reset()
        check_compatibility(manifest, env, live_identity=read_scenario_identity(run_config), live_band=None)
        model = load_model(bundle, env, mask_fn)
    finally:
        env.close()
else:
    from sb3_contrib import MaskablePPO
    import scripts.rl.env.observations, scripts.rl.env.rewards
    model = MaskablePPO.load(target, device="cpu")
state = model.policy.state_dict()
digest = hashlib.sha256()
for key in sorted(state):
    digest.update(key.encode()); digest.update(state[key].detach().cpu().numpy().tobytes())
print(json.dumps({"digest": digest.hexdigest(), "type": type(model).__name__,
                  "legacy_loaded": sorted(m for m in sys.modules if LEGACY.match(m))}))
'''


def _zip_digest(path):
    import torch
    with zipfile.ZipFile(path) as archive:
        state = torch.load(io.BytesIO(archive.read('policy.pth')), map_location='cpu', weights_only=True)
    digest = hashlib.sha256()
    for key in sorted(state):
        digest.update(key.encode())
        digest.update(state[key].detach().cpu().numpy().tobytes())
    return digest.hexdigest()


def _serialized_module_refs(path):
    with zipfile.ZipFile(path) as archive:
        text = b''.join(archive.read(name) for name in archive.namelist())
    return text.count(b'scripts.rl'), text.count(b'env.phase')


def _load_in_subprocess(*args):
    result = subprocess.run([sys.executable, '-c', LOAD_SCRIPT, *map(str, args)], cwd=MESH_ROOT,
                            capture_output=True, text=True, timeout=300)
    assert result.returncode == 0, result.stderr[-3000:]
    return json.loads(result.stdout.strip().splitlines()[-1])




def test_historical_zip_deserializes_without_legacy_modules():
    """Read-only check of one real saved model; set MESH_HISTORICAL_ZIP to run it."""
    target = os.environ.get('MESH_HISTORICAL_ZIP')
    if not target:
        pytest.skip('MESH_HISTORICAL_ZIP not set')
    pytest.importorskip('sb3_contrib')
    path = Path(target)
    assert path.is_file(), path
    _, legacy_references = _serialized_module_refs(path)
    assert legacy_references == 0
    loaded = _load_in_subprocess('zip', path)
    assert loaded['digest'] == _zip_digest(path) and loaded['legacy_loaded'] == []
