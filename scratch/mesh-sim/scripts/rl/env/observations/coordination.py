"""Compact inputs with explicit target closeness and completed-action feedback."""
import math
import numpy as np
from gymnasium import spaces
from scripts.rl.env.observations.compact import build as compact
from scripts.rl.env.observations.compact import features as compact_features
from scripts.rl.env.observations.compact import space as compact_space
from scripts.rl.env.normalization import LINK_FIELDS


EXTRA=('target_distance','target_excess','target_closeness','inside_target','achieved_move','peer_blocked','wall_contact',
       'last_west','last_east','last_south','last_north','last_hold')
GLOBAL=('phase.approach_restore_expand','phase.assemble_dwell','phase.settle','phase.good_dwell','mission.relevant_delivery','team.lower_tail_service','team.path_support','coverage.target','target.team_closeness')


def features(c):
    return compact_features(c)+[f'node.{node}.{name}'for node in c['node_ids']for name in EXTRA]+list(GLOBAL)


def build(f,c,scales):
    state=f['coordination_v1']; values=list(compact(f,c,scales)); m=c['mission']; radius=m.get('team_radius_m',50.)
    for i,node in enumerate(c['node_ids']):
        slot=c['slot_node_ids'].index(node);d=math.dist(f['nodes'][i][:2],[m['goal_x'],m['goal_y']]);e=max(0.,d-radius)
        values += [d/(100+d),e/(100+e),math.exp(-e/100.),float(d<=radius),state['moved_fraction'][i],
                   float(slot in f['safety']['peer_rejected_slots']),float(slot in f['safety'].get('boundary_contacted_slots',[])),
                   *[float(state['previous_action'][i]==a)for a in range(5)]]
    t=state['terms'];values += [float(state['stage']==i)for i in range(3)]+[min(1.,state['good_s']/30),t['D'],t['F'],t['L'],state['coverage_goal'],t['Q']]
    return np.asarray(values,dtype=np.float32)


def space(c):
    base=compact_space(c);extra=12*len(c['node_ids'])+9
    return spaces.Box(low=np.concatenate((base.low,np.zeros(extra,dtype=np.float32))),high=np.concatenate((base.high,np.ones(extra,dtype=np.float32))),dtype=np.float32)


def register(T,registry):
    registry['mission_coordination_v1']=T('mission_coordination_v1','float32',build,space,features,
        lambda p:{**p,'base':'mission_compact_v1','target_distance':'d/(100+d)','target_closeness':'exp(-max(d-target_radius,0)/100 m)',
                  'completed_action':'one-hot last requested cardinal action; actual/permitted movement; native rejection/contact flags',
                  'phase':'measured 30 s success dwell; 5 s relapse hysteresis, immediate severe fallback; no future events'},
        normalization_fields=LINK_FIELDS,required_facts=('nodes','links','window','node_service','mission','mission_state','coordination_v1'),
        compatibility_fields=('bounds','mission','navigation','node_types'),fact_extensions=('coordination_v1',))
