"""Behavior checks preserved from the experiment pilots; no native simulation."""

import json
from pathlib import Path

import pytest

from scripts.rl.env.rewards import RewardComposer
from scripts.rl.env.selection import resolve_selection
from scripts.rl.env.mesh_env import MeshRlEnv
from scripts.rl.env.recording.telemetry import replay_file
from scripts.rl.policy.mission_metrics import compute_mission_metrics
from scripts.rl.policy.reward_audit import reconstruct_coordinated
from scripts.rl.tests.env.test_observation_boundaries import make_contract, make_facts
from scripts.sim_support import find_mesh_root


@pytest.mark.parametrize("mission", ["coverage", "investigation"])
def test_mission_metrics_keep_zero_demand_score_undefined(mission):
    contract = make_contract(slot_nodes=("node-a", "node-b", "node-c"))
    contract["mission"]["kind"] = mission
    facts = make_facts(contract)
    facts["window"].update(demand_mbps_sum=0.0, delivered_mbps_sum=0.0)
    facts["safety"]["unsafe_ticks"] = 0
    facts["node_service"] = [[0.0, 0.0] for _ in contract["node_ids"]]
    facts["mission"].update(
        survivor_demand_mbps_sum=0.0,
        survivor_delivered_mbps_sum=0.0,
        survivor_node_service=facts["node_service"],
    )
    steps = [
        {"decision": decision, "time_s": decision * 0.5, "scored_ticks": 5, "facts": facts}
        for decision in range(contract["num_decisions"] + 1)
    ]

    metrics = compute_mission_metrics(steps, contract)

    assert metrics["mission_score"] is None
    assert metrics["original_demand_delivery"] is None
    assert metrics["coverage_mean"] == facts["coverage"]["fraction"]


def test_coordinated_audit_replays_weighted_component_after_delivery():
    contract = make_contract(slot_nodes=("node-a", "node-b", "node-c"))
    contract["mission"]["kind"] = "coverage"
    contract.update(num_decisions=600, num_ticks=3000, reward_warmup="exclude")
    facts = make_facts(contract)
    rows = [
        {
            "decision": decision,
            "time_s": decision * 0.5,
            "action_sent": [4, 4, 4] if decision else None,
            "legacy_reward": 0.0,
            "ticks_in_step": 5,
            "facts": facts,
        }
        for decision in range(contract["num_decisions"] + 1)
    ]
    component = "coordinated_coverage_fixed_v1"
    selection = {
        "observation_preset": "raw_links_v1",
        "reward_components": ["delivery_ratio", component],
        "reward_weights": [0.25, 2.0],
    }

    result = reconstruct_coordinated({"contract": contract, "selection": selection}, rows)

    assert result["reward_components_sum"] == pytest.approx(
        {"delivery_ratio": 480.0, component: 300.0}
    )
    assert result["return_"] == pytest.approx(720.0)


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
