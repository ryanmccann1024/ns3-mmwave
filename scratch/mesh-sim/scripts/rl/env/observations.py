"""Named observation presets built from the simulator's per-decision facts."""

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Callable

import numpy as np
from gymnasium import spaces

from .protocol import SLOT_ACTIONS

SINR_CLIP_DB = (-20.0, 40.0)
SINR_INVALID_DB = -900.0
_SINR_SPAN = SINR_CLIP_DB[1] - SINR_CLIP_DB[0]
_CAP_LOG_SCALE = 4.0


class SchemaMismatchError(ValueError):
    """A saved observation schema is structurally incompatible with a live one."""

    def __init__(self, fields: list[str], detail: str):
        super().__init__(detail)
        self.fields = list(fields)


def _num_nodes(contract: dict) -> int:
    return int(contract["num_mesh_nodes"])


def _num_slots(contract: dict) -> int:
    return int(contract["max_controlled_nodes"])


def _node_ids(contract: dict) -> list[str]:
    return list(contract["node_ids"])


def _slot_node_index(contract: dict, slot: int) -> int | None:
    """Mesh node index driven by a slot, or None for a padded slot."""
    node_id = contract["slot_node_ids"][slot]
    if node_id is None:
        return None
    return _node_ids(contract).index(node_id)


def _link_index(n: int, i: int, j: int) -> int:
    """Row of pair (i, j) in the i<j table with i outer."""
    lo, hi = (i, j) if i < j else (j, i)
    return lo * n - lo * (lo + 1) // 2 + (hi - lo - 1)


def _clip(value: float, low: float, high: float) -> float:
    return low if value < low else high if value > high else value


def _normalize_axis(value: float, low: float, high: float) -> float:
    if not math.isfinite(value) or high <= low:
        return 0.0
    return _clip(2.0 * (value - low) / (high - low) - 1.0, -1.0, 1.0)


def _sinr_valid(sinr: float) -> bool:
    return math.isfinite(sinr) and sinr > SINR_INVALID_DB


def _peer_indices(contract: dict, index: int) -> list[int]:
    return [p for p in range(_num_nodes(contract)) if p != index]


def _build_raw_links(facts: dict, contract: dict) -> np.ndarray:
    n = _num_nodes(contract)
    nodes, links = facts["nodes"], facts["links"]
    values: list[float] = []
    for slot in range(_num_slots(contract)):
        index = _slot_node_index(contract, slot)
        if index is None:
            values.extend([0.0] * (4 + 2 * (n - 1)))
            continue
        row = nodes[index]
        values.extend([1.0, float(row[0]), float(row[1]), float(row[2])])
        for peer in _peer_indices(contract, index):
            link = links[_link_index(n, index, peer)]
            values.extend([float(link[0]), float(link[1])])
    return np.asarray(values, dtype=np.float64)


def _build_local_links_v1(facts: dict, contract: dict) -> np.ndarray:
    n = _num_nodes(contract)
    bounds = contract["bounds"]
    nodes, links = facts["nodes"], facts["links"]
    values: list[float] = []
    for slot in range(_num_slots(contract)):
        index = _slot_node_index(contract, slot)
        if index is None:
            values.extend([0.0] * (4 + 4 * (n - 1)))
            continue
        row = nodes[index]
        values.append(1.0)
        for axis, value in zip("xyz", row[:3]):
            values.append(_normalize_axis(
                float(value), float(bounds[f"{axis}_min"]), float(bounds[f"{axis}_max"])))
        for peer in _peer_indices(contract, index):
            link = links[_link_index(n, index, peer)]
            sinr, capacity = float(link[0]), float(link[1])
            valid = _sinr_valid(sinr) and math.isfinite(capacity)
            sinr_n = _clip((sinr - SINR_CLIP_DB[0]) / _SINR_SPAN, 0.0, 1.0) if valid else 0.0
            cap_n = _clip(
                math.log10(max(1.0 + capacity, 1.0)) / _CAP_LOG_SCALE, 0.0, 1.0
            ) if valid else 0.0
            values.extend([1.0, 1.0 if valid else 0.0, sinr_n, cap_n])
    return np.asarray(values, dtype=np.float32)


def _raw_links_features(contract: dict) -> list[str]:
    names = []
    for slot in range(_num_slots(contract)):
        names.append(f"slot{slot}.active")
        names.extend(f"slot{slot}.{axis}" for axis in "xyz")
        for peer in range(_num_nodes(contract) - 1):
            names.append(f"slot{slot}.peer_index{peer}.sinr_db")
            names.append(f"slot{slot}.peer_index{peer}.capacity_mbps")
    return names


def _local_links_features(contract: dict) -> list[str]:
    names = []
    for slot in range(_num_slots(contract)):
        names.append(f"slot{slot}.active")
        names.extend(f"slot{slot}.{axis}_n" for axis in "xyz")
        for peer in range(_num_nodes(contract) - 1):
            names.extend(
                f"slot{slot}.peer_index{peer}.{feature}"
                for feature in ("present", "sinr_valid", "sinr_n", "cap_n")
            )
    return names


def _raw_links_space(contract: dict) -> spaces.Box:
    width = _num_slots(contract) * (4 + 2 * (_num_nodes(contract) - 1))
    return spaces.Box(low=-np.inf, high=np.inf, shape=(width,), dtype=np.float64)


def _local_links_space(contract: dict) -> spaces.Box:
    low, high = _local_links_bounds(contract)
    return spaces.Box(low=np.asarray(low, dtype=np.float32),
                      high=np.asarray(high, dtype=np.float32), dtype=np.float32)


def _local_links_bounds(contract: dict) -> tuple[list[float], list[float]]:
    low: list[float] = []
    high: list[float] = []
    for _ in range(_num_slots(contract)):
        low.extend([0.0, -1.0, -1.0, -1.0])
        high.extend([1.0, 1.0, 1.0, 1.0])
        for _ in range(_num_nodes(contract) - 1):
            low.extend([0.0] * 4)
            high.extend([1.0] * 4)
    return low, high


@dataclass(frozen=True)
class ObservationPreset:
    """One named policy input layout with its space and schema."""

    name: str
    dtype: str
    _build: Callable[[dict, dict], np.ndarray]
    _space: Callable[[dict], spaces.Box]
    _features: Callable[[dict], list[str]]
    normalization: dict

    def build(self, facts: dict, contract: dict) -> np.ndarray:
        return self._build(facts, contract)

    def space(self, contract: dict) -> spaces.Box:
        return self._space(contract)

    def feature_names(self, contract: dict) -> list[str]:
        return self._features(contract)

    def schema(self, contract: dict) -> dict:
        return observation_schema(self.name, contract)


PRESETS = {
    "raw_links_v1": ObservationPreset(
        name="raw_links_v1",
        dtype="float64",
        _build=_build_raw_links,
        _space=_raw_links_space,
        _features=_raw_links_features,
        normalization={"position": "raw", "sinr_clip_db": None, "capacity": "raw"},
    ),
    "local_links_v1": ObservationPreset(
        name="local_links_v1",
        dtype="float32",
        _build=_build_local_links_v1,
        _space=_local_links_space,
        _features=_local_links_features,
        normalization={"position": "rl_bounds", "sinr_clip_db": list(SINR_CLIP_DB),
                       "capacity": "log10(1+x)/4"},
    ),
}

DEFAULT_PRESET = "raw_links_v1"


def get_preset(name: str) -> ObservationPreset:
    """Look up a registered preset by name."""
    preset = PRESETS.get(name)
    if preset is None:
        raise ValueError(
            f"Unknown observation_preset {name!r}; valid choices: {sorted(PRESETS)}"
        )
    return preset


def canonical_json(payload: dict) -> str:
    """Strict canonical JSON used for every schema hash."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)


def schema_sha256(payload: dict) -> str:
    """SHA-256 over the canonical JSON of a schema without its own hash field."""
    body = {key: value for key, value in payload.items() if key != "sha256"}
    return hashlib.sha256(canonical_json(body).encode("utf-8")).hexdigest()


def _jsonable_bound(value: float) -> float | None:
    return None if not math.isfinite(value) else float(value)


def observation_schema(preset_name: str, contract: dict) -> dict:
    """Structural + scenario identity of one preset against one init contract."""
    preset = get_preset(preset_name)
    slots = _num_slots(contract)
    if preset_name == "local_links_v1":
        low, high = _local_links_bounds(contract)
    else:
        space = preset.space(contract)
        low = [_jsonable_bound(v) for v in np.atleast_1d(space.low).tolist()]
        high = [_jsonable_bound(v) for v in np.atleast_1d(space.high).tolist()]
    features = preset.feature_names(contract)
    schema = {
        "schema_id": preset.name,
        "dtype": preset.dtype,
        "obs_dim": len(features),
        "num_mesh_nodes": _num_nodes(contract),
        "max_controlled_nodes": slots,
        "contract_id": contract["contract"],
        "dimensions": contract["dimensions"],
        "action_meanings": list(contract["action_meanings"]),
        "nvec": [SLOT_ACTIONS] * slots,
        "feature_names": features,
        "low": low,
        "high": high,
        "normalization": preset.normalization,
        "bounds": dict(contract["bounds"]),
        "node_ids": _node_ids(contract),
        "slot_node_ids": list(contract["slot_node_ids"]),
    }
    schema["sha256"] = schema_sha256(schema)
    return schema


_STRUCTURAL_FIELDS = ("schema_id", "dtype", "obs_dim", "num_mesh_nodes",
                      "max_controlled_nodes", "feature_names", "contract_id",
                      "dimensions", "action_meanings", "nvec", "normalization")
_SCENARIO_FIELDS = ("node_ids", "slot_node_ids")


def check_schema(saved: dict, live: dict) -> list[str]:
    """Raise on structural differences; return warnings for scenario identity."""
    fields = [f for f in _STRUCTURAL_FIELDS if saved.get(f) != live.get(f)]
    # Bounds affect local_links_v1's coordinates, not raw_links_v1's raw values.
    if "local_links_v1" in (saved.get("schema_id"), live.get("schema_id")):
        if saved.get("bounds") != live.get("bounds"):
            fields.append("bounds")
    if fields:
        detail = "; ".join(
            f"{field}: saved={saved.get(field)!r} live={live.get(field)!r}"
            for field in fields
        )
        raise SchemaMismatchError(
            fields,
            f"Saved observation schema is incompatible with this run ({detail})",
        )
    return [
        f"{field} changed: saved={saved.get(field)!r} live={live.get(field)!r}"
        for field in _SCENARIO_FIELDS if saved.get(field) != live.get(field)
    ]
