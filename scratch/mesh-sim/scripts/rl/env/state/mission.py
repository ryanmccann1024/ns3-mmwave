"""Measured mission state, reconstructed from current and previous decision facts."""

import math


def service(rows):
    ratios = [min(1.0, max(0.0, delivered/demand)) for demand, delivered in rows if demand > 1e-9]
    return (sum(math.sqrt(r) for r in ratios)/len(ratios), min(ratios)) if ratios else (0.0, 0.0)


def connected_core(facts):
    active = facts['node_available']
    neighbors = {i: set() for i, available in enumerate(active) if available}
    link = 0
    for i in range(len(active)):
        for j in range(i+1, len(active)):
            if active[i] and active[j] and facts['links'][link][0] >= -6.7:
                neighbors[i].add(j)
                neighbors[j].add(i)
            link += 1
    seen, core = set(), set()
    for root in neighbors:
        if root in seen:
            continue
        part, todo = set(), [root]
        while todo:
            node = todo.pop()
            if node in part:
                continue
            part.add(node)
            todo.extend(neighbors[node]-part)
        seen.update(part)
        if len(part) > len(core):
            core = part
    return core


class MissionState:
    """Track dwell, permanent failures and pre-failure coverage without future event data."""

    def __init__(self):
        self.previous_distance = None
        self.previous_time = 0.0
        self.previous_health = 0.0
        self.arrival_streak = self.recovery_streak = 0.0
        self.arrival_at = self.investigation_at = self.failure_at = self.recovery_at = None
        self.pre_coverage = []
        self.coverage_reference = 0.0
        self.previous_available = None

    def advance(self, facts, contract, time_s, done=False):
        if self.previous_available is not None and any(not old and new for old,new in zip(self.previous_available,facts['node_available'])):
            raise ValueError('permanently dropped peers cannot become available again')
        self.previous_available = list(facts['node_available'])
        spec = contract['mission']
        interval = max(0.0, time_s-self.previous_time)
        raw = facts['mission']
        demand, delivered = raw['survivor_demand_mbps_sum'], raw['survivor_delivered_mbps_sum']
        delivery = min(1.0, delivered/demand) if demand > 1e-9 else 0.0
        fair, worst = service(raw['survivor_node_service'])
        coverage = facts['coverage']['fraction']
        failure = not all(facts['node_available'])
        if failure and self.failure_at is None:
            self.failure_at = time_s
            self.coverage_reference = sum(v for _, v in self.pre_coverage)/len(self.pre_coverage) if self.pre_coverage else coverage
        if not failure:
            self.pre_coverage.append((time_s, coverage))
            self.pre_coverage = [(t, c) for t, c in self.pre_coverage if t > time_s-60.0]
        distance, connected, arrived = 0.0, False, False
        team_fraction, team_connected = 0.0, False
        if spec['kind'] == 'investigation':
            index = contract['node_ids'].index(spec['investigator_id'])
            node = facts['nodes'][index]
            distance = math.hypot(node[0]-spec['goal_x'], node[1]-spec['goal_y'])
            core = connected_core(facts)
            connected = facts['node_available'][index] and index in core and len(core) >= 2
            arrived = connected and distance <= spec['arrival_radius_m']
            if arrived and self.arrival_at is None and not spec.get('team_investigation',False):
                self.arrival_at = time_s
            if spec.get('team_investigation',False):
                distances = [math.hypot(n[0]-spec['goal_x'],n[1]-spec['goal_y'])
                             for i,n in enumerate(facts['nodes']) if facts['node_available'][i]]
                active = {i for i,v in enumerate(facts['node_available']) if v}
                team_connected = bool(active) and active <= core and len(active)>=2
                team_fraction = sum(d<=spec['team_radius_m'] for d in distances)/len(distances)
                distance = (sum(max(0,d-spec['team_radius_m']) for d in distances)/len(distances)
                            + max(0,min(distances)-spec['arrival_radius_m']))
                connected = team_connected
                arrived = (team_connected and team_fraction == 1 and
                           min(distances)<=spec['arrival_radius_m'] and
                           delivery>=spec['team_delivery_target'])
                if arrived and self.arrival_at is None: self.arrival_at = time_s
            success = arrived and raw['goal_coverage_fraction'] >= spec['goal_coverage_target']
            self.arrival_streak = self.arrival_streak+interval if success else 0.0
            if self.arrival_streak >= spec['dwell_s'] and self.investigation_at is None:
                self.investigation_at = time_s
        target_coverage = self.coverage_reference*spec['recovery_coverage_ratio']
        recovery_ok = (failure and delivery >= spec['recovery_delivery_target'] and
                       coverage >= target_coverage and worst >= spec['recovery_worst_target'])
        # The boundary window contains pre-failure ticks; start the recovery dwell afterwards.
        self.recovery_streak = self.recovery_streak+interval if recovery_ok and time_s > self.failure_at else 0.0
        if self.recovery_streak >= spec['dwell_s'] and self.recovery_at is None:
            self.recovery_at = time_s
        state = {
            'time_s': time_s, 'done': done, 'distance_m': distance,
            'team_arrival_fraction':team_fraction, 'team_connected':team_connected,
            'previous_distance_m': distance if self.previous_distance is None else self.previous_distance,
            'investigator_connected': connected, 'connected_arrival': arrived,
            'arrival_streak_s': self.arrival_streak, 'arrival_at_s': self.arrival_at,
            'investigation_completed_at_s': self.investigation_at,
            'failure_at_s': self.failure_at, 'recovery_completed_at_s': self.recovery_at,
            'recovery_streak_s': self.recovery_streak, 'coverage_reference': self.coverage_reference,
            'coverage_target': target_coverage, 'survivor_delivery': delivery,
            'survivor_fair_service': fair, 'survivor_worst_service': worst,
            'previous_survivor_health': self.previous_health,
            'survivor_demand_mbps_sum': demand, 'survivor_delivered_mbps_sum': delivered,
        }
        self.previous_distance = distance
        self.previous_time = time_s
        self.previous_health = min(delivery, fair, coverage)
        facts['mission_state'] = state
        return state


def validate_mission_facts(facts, contract, mask):
    """Validate availability, survivor accounting and the failed slots' hold-only masks."""
    active = facts.get('node_available')
    if not isinstance(active, list) or len(active) != contract['num_mesh_nodes'] or any(type(v) is not bool for v in active):
        raise ValueError('mission facts require a boolean availability flag per peer')
    raw = facts.get('mission')
    if not isinstance(raw, dict):
        raise ValueError('mission facts missing; rebuild mesh-sim')
    for key in ('goal_coverage_fraction', 'survivor_demand_mbps_sum', 'survivor_delivered_mbps_sum'):
        value = raw.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise ValueError(f'invalid mission fact {key}')
    if raw['goal_coverage_fraction'] > 1 or raw['survivor_delivered_mbps_sum'] > raw['survivor_demand_mbps_sum']+1e-6:
        raise ValueError('mission fractions or survivor delivery out of range')
    rows = raw.get('survivor_node_service')
    if not isinstance(rows, list) or len(rows) != len(active):
        raise ValueError('mission survivor service requires one row per peer')
    for row in rows:
        if not isinstance(row, list) or len(row) != 2 or any(not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v) or v < 0 for v in row) or row[1] > row[0]+1e-6:
            raise ValueError('invalid survivor node service')
    for column, key in enumerate(('survivor_demand_mbps_sum', 'survivor_delivered_mbps_sum')):
        if not math.isclose(sum(row[column] for row in rows), 2*raw[key], abs_tol=1e-6, rel_tol=1e-6):
            raise ValueError('survivor endpoint accounting must equal twice the flow sums')
    for slot, node in enumerate(contract['slot_node_ids']):
        if node is not None and not active[contract['node_ids'].index(node)] and list(mask[5*slot:5*slot+5]) != [0,0,0,0,1]:
            raise ValueError('offline peer must have a hold-only action mask')


def validate_mission_contract(contract):
    spec=contract['mission']
    if not isinstance(spec,dict) or type(spec.get('version')) is not int or spec['version'] not in (1,2):
        raise ValueError('unsupported mission extension; expected version 1 or 2')
    if spec.get('kind') not in ('coverage','investigation','recovery'):
        raise ValueError('invalid mission kind')
    for key in ('goal_x','goal_y','arrival_radius_m','coverage_radius_m','dwell_s',
                'goal_coverage_target','recovery_delivery_target','recovery_coverage_ratio',
                'recovery_worst_target','progress_distance_scale_m'):
        value=spec.get(key)
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value):
            raise ValueError(f'mission.{key} must be finite')
        zero_allowed = key=='recovery_coverage_ratio' or (spec['kind']=='investigation' and key=='goal_coverage_target')
        if key not in ('goal_x','goal_y') and (value<0 or (value==0 and not zero_allowed)):
            raise ValueError(f'mission.{key} must be positive')
        if key in ('goal_coverage_target','recovery_delivery_target','recovery_coverage_ratio','recovery_worst_target') and value>1:
            raise ValueError(f'mission.{key} must be at most one')
    if spec['version']==2:
        if spec.get('team_investigation') is not True or spec['kind']!='investigation':
            raise ValueError('mission version 2 requires team investigation')
        for key in ('team_radius_m','team_delivery_target'):
            value=spec.get(key)
            if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value<0 or (value==0 and key!='team_delivery_target'):
                raise ValueError(f'invalid mission.{key}')
        if spec['team_delivery_target']>1:raise ValueError('team delivery target must be at most one')
    if spec.get('coverage_domain')!='outdoor_probe_cells':raise ValueError('unsupported mission coverage domain')
    if spec['kind']=='investigation' and spec.get('investigator_id') not in contract['slot_node_ids']:
        raise ValueError('investigator must be a controlled peer')


def mission_features(facts, contract, base):
    """Append target and measured mission state; never expose future failure schedules."""
    import numpy as np
    m, s = contract['mission'], facts['mission_state']
    bounds = contract['bounds']
    values = [float(v) for v in facts['node_available']]
    values.extend([float(m['kind'] == kind) for kind in ('coverage','investigation','recovery')])
    values.extend([(m['goal_x']-bounds['x_min'])/(bounds['x_max']-bounds['x_min']),
                   (m['goal_y']-bounds['y_min'])/(bounds['y_max']-bounds['y_min']),
                   min(1.0, s['distance_m']/math.hypot(bounds['x_max']-bounds['x_min'],bounds['y_max']-bounds['y_min'])),
                   float(s['investigator_connected']), float(s['connected_arrival']),
                   facts['mission']['goal_coverage_fraction'], min(1.0,s['arrival_streak_s']/m['dwell_s']),
                   float(s['investigation_completed_at_s'] is not None), float(s['failure_at_s'] is not None),
                   s['survivor_delivery'], s['survivor_fair_service'], s['survivor_worst_service'],
                   s['coverage_target'], min(1.0,s['recovery_streak_s']/m['dwell_s']),
                   float(s['recovery_completed_at_s'] is not None)])
    return np.concatenate((base, np.asarray(values,dtype=np.float32)))


def mission_feature_names(contract):
    return [f'node.{node}.available' for node in contract['node_ids']] + [
        'mission.coverage','mission.investigation','mission.recovery','mission.goal_x','mission.goal_y',
        'mission.distance','mission.connected','mission.arrived','mission.goal_coverage','mission.dwell',
        'mission.completed','mission.failure','mission.survivor_delivery','mission.survivor_fair',
        'mission.survivor_worst','mission.coverage_target','mission.recovery_dwell','mission.recovered']


def navigation_features(facts,contract):
    """Four local obstacle ranges and target offsets per controlled peer."""
    values=[];nav=contract['navigation'];range_m=nav['obstacle_sensing_range_m'];clearance=nav['building_clearance_m']
    m=contract['mission'];bounds=contract['bounds'];width=bounds['x_max']-bounds['x_min'];height=bounds['y_max']-bounds['y_min']
    for node_id in contract['slot_node_ids']:
        if node_id is None: values.extend([0.0]*6);continue
        x,y,z=facts['nodes'][contract['node_ids'].index(node_id)][:3]
        distances=[range_m]*4
        for b in nav['buildings']:
            if not b['z_min']-clearance<=z<=b['z_max']+clearance:continue
            xmin,xmax=b['x_min']-clearance,b['x_max']+clearance
            ymin,ymax=b['y_min']-clearance,b['y_max']+clearance
            if ymin<=y<=ymax:
                if x>=xmax:distances[0]=min(distances[0],x-xmax)
                if x<=xmin:distances[1]=min(distances[1],xmin-x)
            if xmin<=x<=xmax:
                if y>=ymax:distances[2]=min(distances[2],y-ymax)
                if y<=ymin:distances[3]=min(distances[3],ymin-y)
        values.extend(d/range_m for d in distances)
        values.extend([.5+.5*(m['goal_x']-x)/width,.5+.5*(m['goal_y']-y)/height])
    values.extend([facts['mission_state']['team_arrival_fraction'],float(facts['mission_state']['team_connected'])])
    return values


def navigation_feature_names(contract):
    return [f'node.{node}.{name}' for node in contract['slot_node_ids']
            for name in ('obstacle_west','obstacle_east','obstacle_south','obstacle_north','goal_dx','goal_dy')] + ['mission.team_arrivals','mission.team_connected']
