"""Validate cluster settings and resolve role resources."""

import json
import re
from pathlib import Path

CLUSTER_CONFIG_VERSION = 1
JOB_ROLES = ("tasks", "compare")

_TOP_KEYS = ("cluster_config_version", "name", "venv", "setup_lines", "task",
             "compare", "max_array_size", "max_concurrent_tasks")
_TASK_KEYS = ("partition", "account", "qos", "constraint", "time", "mem",
              "cpus_per_task")
_COMPARE_KEYS = ("time", "mem", "cpus_per_task")
PLACEMENT_KEYS = ("partition", "account", "qos", "constraint")
_TIME_RE = re.compile(r"^(\d+-)?\d{1,2}:[0-5]\d:[0-5]\d$")
_MEM_RE = re.compile(r"^\d+[KMGT]?$")


def _check_keys(mapping, allowed: tuple[str, ...], where: str) -> None:
    if not isinstance(mapping, dict):
        raise ValueError(f"{where} must be a JSON object")
    unknown = sorted(key for key in mapping if key not in allowed)
    if unknown:
        raise ValueError(f"{where} has unknown keys {unknown}; valid keys: "
                         f"{list(allowed)}. There is no free-form sbatch option")
    missing = [key for key in allowed if key not in mapping]
    if missing:
        raise ValueError(f"{where} is missing required keys {missing}; every key "
                         "must be present, with no default supplied by this tool")


def _no_placeholder(value, where: str) -> None:
    if isinstance(value, str) and value.startswith("<"):
        raise ValueError(f"{where} is still the example placeholder {value!r}")


def _text(mapping: dict, key: str, where: str, pattern=None, shape="") -> str:
    value, field = mapping[key], f"{where}.{key}"
    _no_placeholder(value, field)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} must be a non-empty string, got {value!r}")
    if pattern is not None and not pattern.match(value):
        raise ValueError(f"{field} must look like {shape}, got {value!r}")
    return value


def _positive_int(mapping: dict, key: str, where: str) -> int:
    value, field = mapping[key], f"{where}.{key}"
    _no_placeholder(value, field)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{field} must be an integer >= 1, got {value!r}")
    return value


def _nullable_text(mapping: dict, key: str, where: str) -> str | None:
    if mapping[key] is None:
        return None
    return _text(mapping, key, where)


def _resource_block(raw, keys: tuple[str, ...], where: str) -> dict:
    _check_keys(raw, keys, where)
    block = {"time": _text(raw, "time", where, _TIME_RE, "HH:MM:SS"),
             "mem": _text(raw, "mem", where, _MEM_RE, "4G or 4000M"),
             "cpus_per_task": _positive_int(raw, "cpus_per_task", where)}
    for key in keys:
        if key in PLACEMENT_KEYS:
            block[key] = _nullable_text(raw, key, where)
    return block


def load_cluster_config(path) -> dict:
    """Read and fully validate the cluster config; every key is required."""
    data = json.loads(Path(path).read_text())
    _check_keys(data, _TOP_KEYS, "cluster config")
    if data["cluster_config_version"] != CLUSTER_CONFIG_VERSION:
        raise ValueError(f"cluster_config_version must be {CLUSTER_CONFIG_VERSION}, "
                         f"got {data['cluster_config_version']!r}")
    setup = data["setup_lines"]
    if not isinstance(setup, list) or not all(isinstance(l, str) for l in setup):
        raise ValueError("setup_lines must be an array of shell command strings")
    for index, line in enumerate(setup):
        _no_placeholder(line, f"setup_lines[{index}]")

    config = {"cluster_config_version": CLUSTER_CONFIG_VERSION,
              "name": _text(data, "name", "cluster config"),
              "venv": _text(data, "venv", "cluster config"),
              "setup_lines": list(setup),
              "task": _resource_block(data["task"], _TASK_KEYS, "task"),
              "compare": _resource_block(data["compare"], _COMPARE_KEYS, "compare"),
              "max_array_size": _positive_int(data, "max_array_size", "cluster config"),
              "max_concurrent_tasks": None}
    if data["max_concurrent_tasks"] is not None:
        config["max_concurrent_tasks"] = _positive_int(data, "max_concurrent_tasks",
                                                       "cluster config")
    if not Path(config["venv"]).is_absolute():
        raise ValueError(f"venv must be an absolute path, got {config['venv']!r}")
    if not (Path(config["venv"]) / "bin" / "python").exists():
        raise ValueError(f"{config['venv']}/bin/python does not exist; prepare the "
                         "venv with scripts/rl/bootstrap_venv.py --venv <path>")
    return config


def resources(config: dict, role: str) -> dict:
    """Resource flags for one job role; compare inherits placement from task."""
    if role not in JOB_ROLES:
        raise ValueError(f"unknown job role {role!r}; valid: {list(JOB_ROLES)}")
    block = config["task"] if role == "tasks" else config["compare"]
    values = {key: config["task"][key] for key in PLACEMENT_KEYS}
    values.update({key: block[key] for key in ("time", "mem", "cpus_per_task")})
    return values
