"""Behavior checks preserved from the experiment pilots; no native simulation."""

import json
from pathlib import Path

import pytest

from scripts.rl.env.rewards import RewardComposer
from scripts.rl.env.selection import resolve_selection
from scripts.rl.env.mesh_env import MeshRlEnv
from scripts.rl.env.recording.telemetry import replay_file
from scripts.sim_support import find_mesh_root


def test_maintenance_reward_is_current_not_latched():
    composer=RewardComposer(['survivor_service_maintained_v1'],[1])
    contract={'mission':{'recovery_delivery_target':.9,'recovery_worst_target':.8}}
    state={'failure_at_s':300,'survivor_delivery':1,'survivor_worst_service':1,'recovery_completed_at_s':330}
    assert composer.compose({'scored_ticks':2},0,contract,{'mission_state':state}).total==1
    state['survivor_delivery']=.2
    assert composer.compose({'scored_ticks':2},0,contract,{'mission_state':state}).total==0
    state.update(failure_at_s=None,survivor_delivery=1)
    assert composer.compose({'scored_ticks':2},0,contract,{'mission_state':state}).total==0


def test_goal_closeness_and_explicit_zero_movement_ablation():
    composer=RewardComposer(['team_goal_proximity_v1','decision_travel_v1'],[4,-.05])
    c={'mission':{}}
    far=composer.compose({'scored_ticks':2},0,c,{'mission_state':{'distance_m':300},'travel_fraction':1}).total
    near=composer.compose({'scored_ticks':2},0,c,{'mission_state':{'distance_m':40},'travel_fraction':1}).total
    assert near>far
    zero=RewardComposer(['team_goal_proximity_v1','decision_travel_v1'],[4,0])
    assert zero.compose({'scored_ticks':2},0,c,{'mission_state':{'distance_m':40},'travel_fraction':1}).total==pytest.approx(near+.05)


def test_survivor_sinr_excludes_failed_links_but_scores_invalid_active_links_zero():
    composer=RewardComposer(['active_sinr_quality_v1'],[1])
    context={'links':[[40,0,0],[-20,0,0],[40,0,0]],'node_available':[True,False,True]}
    assert composer.compose({'scored_ticks':2},0,{},context).total==0
    context['links'][1][0]=40
    assert composer.compose({'scored_ticks':2},0,{},context).total==1
    context['links'][1][0]=-1000
    assert composer.compose({'scored_ticks':2},0,{},context).total==0


def test_compact_training_keeps_validation_telemetry_when_requested(sim_binary,multi_run_config,tmp_path,monkeypatch):
    import sys
    from scripts.rl import train
    ini=Path(multi_run_config)
    ini.write_text(ini.read_text()+'\ncompact_training=true\nrecord_validation_telemetry=true\ntelemetry=none\n')
    out=tmp_path/'train'
    monkeypatch.setattr(sys,'argv',['train','--sim-binary',sim_binary,'--run-config',str(ini),
        '--output-dir',str(out),'--verbose','0','m-ppo','--seed','101','--total-timesteps','16',
        '--n-steps','8','--batch-size','8','--eval-every-steps','8','--eval-episodes','2','--eval-seeds','201,202'])
    assert train.main()==0
    assert not list(out.glob('episode-*/steps.jsonl'))
    for step in (8,16):
        record=json.loads((out/'eval'/f'checkpoint-{step}'/'reward_matrix.json').read_text())
        assert {e['seed'] for e in record['episodes']}=={201,202}
        assert not record['excluded']


@pytest.mark.parametrize('mission',['coverage','investigation','recovery'])
def test_new_reward_reconstructs_from_saved_facts(sim_binary,tmp_path,mission):
    import configparser
    root=find_mesh_root()/'inputs/custom/10-16-3'
    if not root.is_dir():pytest.skip('local follow-up inputs absent')
    config=json.loads((root/'campaign.json').read_text());selection=config['rewards'][mission+'-simple']
    source=root/('rural-'+mission+'-small');ini=configparser.ConfigParser(interpolation=None);ini.read(source/'run.ini')
    ini['scenario']['duration_s']='4';ini['scenario']['nodes_file']=str(source/'nodes.json');ini['scenario']['buildings_file']=str(source/'buildings.json')
    path=tmp_path/'run.ini'
    with path.open('w') as f:ini.write(f)
    resolved=resolve_selection(str(path),reward_components=','.join(selection['reward_components']),
        reward_weights=','.join(map(str,selection['reward_weights'])),telemetry='steps')
    env=MeshRlEnv(sim_binary,str(path),seed=101,output_dir=str(tmp_path/'episodes'),selection=resolved)
    try:
        env.reset()
        for _ in range(4):env.step([4,4,4])
    finally:env.close()
    result=replay_file(next((tmp_path/'episodes').glob('episode-*/steps.jsonl')))
    assert result.obs_mismatches==result.reward_mismatches==0
