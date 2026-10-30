"""Binary mission success and continuous area, target and event-service objectives."""
import math
FAILURE_REWARD = -0.001

def _binary(success):
    return (1.0 if success else FAILURE_REWARD), True

def _eligible(window, context):
    gate = context['deployment']
    return gate['active'] and gate['eligible_ticks'] == window['scored_ticks']

def binary_coverage(window, reward, contract, parameters, context):
    return _binary(context['coverage']['fraction'] >= parameters['target'])

def binary_investigation(window, reward, contract, parameters, context):
    mission = contract['mission']
    distances = [math.hypot(node[0]-mission['goal_x'], node[1]-mission['goal_y'])
                 for node, active in zip(context['nodes'], context['node_available']) if active]
    return _binary(bool(distances) and max(distances) <= mission['team_radius_m'])

def binary_recovery(window, reward, contract, parameters, context):
    if not _eligible(window, context):
        return 0.0, False
    facts = context['mission']
    demand = facts['survivor_demand_mbps_sum']
    return _binary(demand > 1e-9 and facts['survivor_delivered_mbps_sum']/demand >= .9)

def binary_jamming(window, reward, contract, parameters, context):
    if not _eligible(window, context):
        return 0.0, False
    demand = window['demand_mbps_sum']
    return _binary(demand > 1e-9 and window['delivered_mbps_sum']/demand >= .9)

def register_binary(component_type, registry):
    common = dict(range=(FAILURE_REWARD, 1.0), parameters={'failure_reward': FAILURE_REWARD},
                  zero_demand_rule='no free success; zero reward during forced waiting or mixed event window')
    for mission, function, fields, dependencies, formula, tunable in (
        ('coverage', binary_coverage, ('coverage',), ('coverage',),
         '+1 if connected outdoor coverage >= {target:g}; otherwise -0.001', {'target':(.5,0,1)}),
        ('investigation', binary_investigation, ('nodes','node_available'), ('mission',),
         '+1 if every available peer is within team_radius_m of goal; otherwise -0.001', {}),
        ('recovery', binary_recovery, ('mission','deployment'), ('deployment_gate',),
         'zero until fully eligible; then +1 if survivor delivered/offered >= 0.9; otherwise -0.001', {}),
        ('jamming', binary_jamming, ('deployment',), ('deployment_gate',),
         'zero until fully eligible; then +1 if aggregate delivered/offered >= 0.9; otherwise -0.001', {}),
    ):
        name = f'level0_{mission}_v1'
        registry[name] = component_type(name, function, required_facts=fields,
            context_fields=fields, contract_fields=dependencies, formula=formula,
            tunable=tunable, **common)

COMPONENT_NAMES = {
    'coverage': 'connected_outdoor_area_fraction_v1',
    'investigation': 'team_target_distance_score_v1',
    'recovery': 'survivor_critical_delivery_fraction_v1',
    'jamming': 'jammed_traffic_delivery_fraction_v1',
}

LABELS = {
    'coverage': 'Connected outdoor area fraction (0–1)',
    'investigation': 'Team target proximity from mean excess distance (0–1)',
    'recovery': 'Survivor critical traffic delivery fraction after failure (0–1)',
    'jamming': 'Traffic delivery fraction during jamming (0–1)',
}

def coverage(window, reward, contract, parameters, context):
    return float(context['coverage']['fraction']), True

def investigation(window, reward, contract, parameters, context):
    mission, bounds = contract['mission'], contract['bounds']
    excess = [max(0., math.hypot(n[0]-mission['goal_x'], n[1]-mission['goal_y'])
                  - mission['team_radius_m'])
              for n, active in zip(context['nodes'], context['node_available']) if active]
    if not excess:
        return 0., False
    diagonal = math.hypot(bounds['x_max']-bounds['x_min'], bounds['y_max']-bounds['y_min'])
    if diagonal <= 0:
        raise ValueError('investigation needs positive planar field dimensions')
    return max(0., min(1., 1.-sum(excess)/len(excess)/diagonal)), True

def recovery(window, reward, contract, parameters, context):
    if not _eligible(window, context):
        return 0., False
    facts = context['mission']
    demand = facts['survivor_demand_mbps_sum']
    return (min(1., max(0., facts['survivor_delivered_mbps_sum']/demand)), True) if demand > 1e-9 else (0., False)

def jamming(window, reward, contract, parameters, context):
    if not _eligible(window, context):
        return 0., False
    demand = window['demand_mbps_sum']
    return (min(1., max(0., window['delivered_mbps_sum']/demand)), True) if demand > 1e-9 else (0., False)

def register_continuous(component_type, registry):
    for mission, function, fields, dependencies, formula in (
        ('coverage', coverage, ('coverage',), ('coverage',), 'current connected outdoor coverage fraction'),
        ('investigation', investigation, ('nodes', 'node_available'), ('mission', 'bounds'),
         'clamp(1 - mean(max(planar target distance - team_radius_m, 0))/planar field diagonal, 0, 1)'),
        ('recovery', recovery, ('mission', 'deployment'), ('deployment_gate',),
         'zero until fully eligible; then survivor delivered/offered fraction'),
        ('jamming', jamming, ('deployment',), ('deployment_gate',),
         'zero until fully eligible; then aggregate delivered/offered fraction'),
    ):
        name = COMPONENT_NAMES[mission]
        zero_rule=('not applicable; fraction over outdoor coverage probes' if mission=='coverage' else
                   'zero and invalid with no available peers' if mission=='investigation' else
                   'zero and invalid with no offered demand, forced waiting or a mixed event window')
        registry[name] = component_type(name, function, range=(0., 1.), required_facts=fields,
            context_fields=fields, contract_fields=dependencies, formula=formula,
            zero_demand_rule=zero_rule)

def register(component_type, registry):
    register_binary(component_type, registry)
    register_continuous(component_type, registry)
