"""Compact centralized mission features without altering historical presets."""
import numpy as np
from gymnasium import spaces
from scripts.rl.env.normalization import Normalization
from scripts.rl.env.normalization import LINK_FIELDS
from scripts.rl.env.state.mission import navigation_features


def features(c):
    names=[]
    for node in c['node_ids']:
        names += [f'node.{node}.{f}' for f in ('available','x_n','y_n','z_n','pedestrian','drone','vehicle','goal_dx','goal_dy','obstacle_west','obstacle_east','obstacle_south','obstacle_north','delivery')]
    for i,a in enumerate(c['node_ids']):
        for b in c['node_ids'][i+1:]:names += [f'link.{a}.{b}.{f}' for f in ('sinr_n','capacity_n','los')]
    return names+['team.arrivals','team.connected','team.delivery','team.coverage','team.dwell','control.active']


def build(f,c,scales):
    values=[];navigation=navigation_features(f,c);bounds=c['bounds']
    for i,node in enumerate(c['node_ids']):
        row=f['nodes'][i];slot=c['slot_node_ids'].index(node);nav=navigation[6*slot:6*slot+6]
        pos=[max(-1.,min(1.,2*(row[a]-bounds[f'{axis}_min'])/(bounds[f'{axis}_max']-bounds[f'{axis}_min'])-1)) for a,axis in enumerate('xyz')]
        demand,delivered=f['node_service'][i]
        values += [float(f['node_available'][i]),*pos,*[float(c['node_types'][i]==kind) for kind in ('pedestrian','drone','vehicle')],*nav[4:6],*nav[:4],min(1.,max(0.,delivered/demand)) if demand>1e-9 else 0.]
    for link in f['links']:values += [scales.sinr_quality(link[0]),scales.capacity(link[1]),float(link[2])]
    s=f['mission_state'];w=f['window'];gate=f.get('deployment')
    values += [s['team_arrival_fraction'],float(s['team_connected']),min(1.,max(0.,w['delivered_mbps_sum']/w['demand_mbps_sum'])) if w['demand_mbps_sum']>1e-9 else 0.,f['coverage']['fraction'],min(1.,s['arrival_streak_s']/c['mission']['dwell_s']),float(gate is None or gate['active'])]
    return np.asarray(values,dtype=np.float32)


def space(c):
    low=([0.,-1.,-1.,-1.]+[0.]*10)*len(c['node_ids'])+[0.]*(3*c['num_links']+6)
    return spaces.Box(low=np.asarray(low,dtype=np.float32),high=np.ones(len(low),dtype=np.float32),dtype=np.float32)


def register(T,registry):
    registry['mission_compact_v1']=T('mission_compact_v1','float32',build,space,features,
        lambda p:{**p,'positions':'2*(value-min)/(max-min)-1','target_offsets':'0.5+0.5*(target-self)/field span','layout':'one node block, one unordered link block, six global measurements; no repeated pair geometry'},
        normalization_fields=LINK_FIELDS,
        required_facts=('nodes','links','node_service','node_available','mission_state','window','coverage'),
        compatibility_fields=('bounds','mission','navigation','node_types'))
