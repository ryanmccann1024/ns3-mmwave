"""Read engine settings from INI and delegate meaning to planner owners."""

import json
from dataclasses import fields

from scripts.baselines.config import read_ini, ini_value
from scripts.baselines.planners.objective import ObjectiveSettings
from scripts.baselines.planners.optimization import OptimizerSettings
from scripts.baselines.planners.channel import QuerySettings


def _section(ini, section, owner, integer_keys=(), string_keys=(), json_keys=()):
    if not ini.has_section(section):
        return owner()
    allowed = {field.name for field in fields(owner)}
    unknown = set(ini.options(section)) - allowed
    if unknown:
        raise ValueError(f"[{section}] unknown settings: {sorted(unknown)}")
    values = {}
    for key in ini.options(section):
        raw = ini_value(ini, section, key)
        if raw is None:
            raise ValueError(f"[{section}] {key} cannot be blank")
        if key in json_keys:
            values[key] = json.loads(raw)
        elif key in string_keys:
            values[key] = raw
        elif key in integer_keys:
            values[key] = int(raw)
        else:
            values[key] = float(raw)
    return owner(**values)


def load_settings(path):
    ini = read_ini(path)
    return (
        _section(
            ini, "placement_objective", ObjectiveSettings, json_keys=("component_parameters",)
        ),
        _section(
            ini,
            "placement_optimizer",
            OptimizerSettings,
            string_keys=("warm_start",),
            json_keys=("move_weights",),
        ),
        _section(
            ini,
            "channel_query_client",
            QuerySettings,
            integer_keys=("max_layouts", "response_budget_bytes", "cache_bytes"),
        ),
    )
