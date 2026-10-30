"""One explicit feature substitution; vector width and all other features are unchanged."""
from scripts.rl.env.observations.coordination import build as previous_build
from scripts.rl.env.observations.coordination import features as previous_features
from scripts.rl.env.observations.coordination import space
from scripts.rl.env.state.measurements import global_bridge_support
from scripts.rl.env.normalization import LINK_FIELDS


def features(c):
    return ['team.global_bridge_support' if name == 'team.path_support' else name
            for name in previous_features(c)]


def build(f, c, scales):
    values = previous_build(f, c, scales)
    values[previous_features(c).index('team.path_support')] = global_bridge_support(f, c)
    return values


def register(T, registry):
    registry['mission_bridge_v1'] = T('mission_bridge_v1', 'float32', build, space, features,
        lambda p:{**p, 'base':'mission_coordination_v1',
                  'substitution':'team.path_support replaced by weakest all-active-pair widest-path sigmoid SINR; same vector width; other features unchanged'},
        normalization_fields=LINK_FIELDS,
        required_facts=('nodes','links','node_available','window','node_service','mission','mission_state','coordination_v1'),
        compatibility_fields=('bounds','mission','navigation','node_types'), fact_extensions=('coordination_v1',))
