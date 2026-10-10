"""Named observation presets built from the simulator's per-decision facts."""

import json
import math
from dataclasses import dataclass, field, replace
from typing import Callable

import numpy as np
from gymnasium import spaces

from scripts.artifact_io import canonical_sha256
from .normalization import LINK_FIELDS, Normalization
from .protocol import SLOT_ACTIONS

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


def _build_local_links_v1(facts: dict, contract: dict, scales: Normalization) -> np.ndarray:
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
            valid = scales.sinr_valid(sinr) and math.isfinite(capacity)
            sinr_n = scales.sinr_quality(sinr) if valid else 0.0
            cap_n = scales.capacity(capacity) if valid else 0.0
            values.extend([1.0, 1.0 if valid else 0.0, sinr_n, cap_n])
    return np.asarray(values, dtype=np.float32)


def _build_geometry_v1(facts: dict, contract: dict) -> np.ndarray:
    """Self xy and peer-relative xy only; no objective or future information."""
    nodes, bounds = facts["nodes"], contract["bounds"]
    sx = float(bounds["x_max"]) - float(bounds["x_min"])
    sy = float(bounds["y_max"]) - float(bounds["y_min"])
    values: list[float] = []
    for slot in range(_num_slots(contract)):
        index = _slot_node_index(contract, slot)
        if index is None:
            values.extend([0.0] * (3 + 3 * (_num_nodes(contract) - 1)))
            continue
        row = nodes[index]
        values.extend([1.0, _normalize_axis(float(row[0]), bounds["x_min"],
                                             bounds["x_max"]),
                       _normalize_axis(float(row[1]), bounds["y_min"],
                                       bounds["y_max"])])
        for peer in _peer_indices(contract, index):
            other = nodes[peer]
            values.extend([1.0,
                           _clip((float(other[0]) - float(row[0])) / sx, -1.0, 1.0),
                           _clip((float(other[1]) - float(row[1])) / sy, -1.0, 1.0)])
    return np.asarray(values, dtype=np.float32)


def _service_values(window: dict, contract: dict, scales: Normalization) -> list[float]:
    demand = float(window["demand_mbps_sum"])
    delivered = float(window["delivered_mbps_sum"])
    ticks = max(1, int(window["scored_ticks"]))
    pair_ticks = ticks * int(contract["num_links"])
    flow_ticks = int(window["flow_ticks_with_demand"])
    return [
        _clip(math.log10(1.0 + demand / ticks) / scales.capacity_log10_denominator, 0.0, 1.0),
        _clip(math.log10(1.0 + delivered / ticks) / scales.capacity_log10_denominator, 0.0, 1.0),
        _clip(delivered / demand, 0.0, 1.0) if demand > 1e-9 else 0.0,
        _clip(float(window["connected_pairs_sum"]) / pair_ticks, 0.0, 1.0)
        if pair_ticks else 0.0,
        _clip(float(window["unroutable_flow_ticks"]) / flow_ticks, 0.0, 1.0)
        if flow_ticks else 0.0,
    ]


def _build_service_v1(facts: dict, contract: dict, scales: Normalization) -> np.ndarray:
    local = _build_local_links_v1(facts, contract, scales)
    local_width = 4 + 4 * (_num_nodes(contract) - 1)
    service = _service_values(facts["window"], contract, scales)
    values: list[float] = []
    for slot in range(_num_slots(contract)):
        values.extend(local[slot * local_width:(slot + 1) * local_width])
        values.extend(service if _slot_node_index(contract, slot) is not None
                      else [0.0] * len(service))
    return np.asarray(values, dtype=np.float32)


def _build_full_facts_v1(facts: dict, contract: dict, scales: Normalization) -> np.ndarray:
    service = _build_service_v1(facts, contract, scales)
    service_width = 9 + 4 * (_num_nodes(contract) - 1)
    nodes, bounds = facts["nodes"], contract["bounds"]
    spans = [float(bounds[f"{axis}_max"]) - float(bounds[f"{axis}_min"])
             for axis in "xyz"]
    values: list[float] = []
    for slot in range(_num_slots(contract)):
        values.extend(service[slot * service_width:(slot + 1) * service_width])
        index = _slot_node_index(contract, slot)
        if index is None:
            values.extend([0.0] * (7 * (_num_nodes(contract) - 1) + 1))
            continue
        row = nodes[index]
        for peer in _peer_indices(contract, index):
            other = nodes[peer]
            values.extend(_clip((float(other[axis]) - float(row[axis])) / spans[axis],
                                -1.0, 1.0) for axis in range(3))
            values.extend(_clip((float(other[axis]) - float(row[axis])) /
                                scales.velocity_scale_mps, -1.0, 1.0)
                          for axis in range(3, 6))
            values.append(float(facts["links"][_link_index(_num_nodes(contract),
                                                          index, peer)][2]))
        window = facts["window"]
        gap = max(0.0, float(window["demand_mbps_sum"]) -
                  float(window["delivered_mbps_sum"])) / max(1, int(window["scored_ticks"]))
        values.append(_clip(math.log10(1.0 + gap) / scales.capacity_log10_denominator, 0.0, 1.0))
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


def _geometry_features(contract: dict) -> list[str]:
    names = []
    for slot in range(_num_slots(contract)):
        names.extend((f"slot{slot}.active", f"slot{slot}.x_n", f"slot{slot}.y_n"))
        for peer in range(_num_nodes(contract) - 1):
            names.extend((f"slot{slot}.peer_index{peer}.present",
                          f"slot{slot}.peer_index{peer}.relative_x_n",
                          f"slot{slot}.peer_index{peer}.relative_y_n"))
    return names


_SERVICE_NAMES = ("demand_log_n", "delivered_log_n", "delivery_ratio", "connected_fraction",
                  "unroutable_fraction")


def _service_features(contract: dict) -> list[str]:
    base = _local_links_features(contract)
    width = 4 + 4 * (_num_nodes(contract) - 1)
    names = []
    for slot in range(_num_slots(contract)):
        names.extend(base[slot * width:(slot + 1) * width])
        names.extend(f"slot{slot}.{name}" for name in _SERVICE_NAMES)
    return names


def _full_facts_features(contract: dict) -> list[str]:
    base = _service_features(contract)
    width = 9 + 4 * (_num_nodes(contract) - 1)
    names = []
    for slot in range(_num_slots(contract)):
        names.extend(base[slot * width:(slot + 1) * width])
        for peer in range(_num_nodes(contract) - 1):
            names.extend(f"slot{slot}.peer_index{peer}.relative_{name}_n"
                         for name in ("x", "y", "z", "vx", "vy", "vz"))
            names.append(f"slot{slot}.peer_index{peer}.is_los")
        names.append(f"slot{slot}.service_gap_log_n")
    return names


def _bounded_space(contract, slot_low):
    low = slot_low * _num_slots(contract)
    return spaces.Box(low=np.asarray(low, dtype=np.float32),
                      high=np.ones(len(low), dtype=np.float32), dtype=np.float32)


def _geometry_space(contract):
    return _bounded_space(contract, [0, -1, -1] + [0, -1, -1] * (_num_nodes(contract) - 1))


def _service_slot_low(contract):
    return [0, -1, -1, -1] + [0] * (4 * (_num_nodes(contract) - 1) + 5)


def _service_space(contract):
    return _bounded_space(contract, _service_slot_low(contract))


def _full_facts_space(contract):
    return _bounded_space(contract, _service_slot_low(contract) +
                          ([-1] * 6 + [0]) * (_num_nodes(contract) - 1) + [0])


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
    normalization: dict | Callable
    normalization_fields: tuple[str, ...] = ()
    parameters: dict = field(default_factory=dict)
    required_facts: tuple[str, ...] = ("nodes", "links")
    compatibility_fields: tuple[str, ...] = ()

    def build(self, facts: dict, contract: dict) -> np.ndarray:
        if self.normalization_fields:
            return self._build(facts, contract, Normalization(**self.parameters))
        return self._build(facts, contract)

    def space(self, contract: dict) -> spaces.Box:
        return self._space(contract)

    def feature_names(self, contract: dict) -> list[str]:
        return self._features(contract)

    def schema(self, contract: dict) -> dict:
        return _preset_schema(self, contract)


def _link_normalization(parameters):
    return {**parameters, "position": "rl_bounds",
            "sinr_clip_db": [parameters["sinr_min_db"], parameters["sinr_max_db"]],
            "capacity": f"log10(1+x)/{parameters['capacity_log10_denominator']:g}"}


def _service_normalization(parameters):
    return {**_link_normalization(parameters),
            "demand": f"log10(1+Mbps)/{parameters['capacity_log10_denominator']:g}",
            "window": "sums_over_scored_ticks", "service_ratios": "unit ratios"}


def _full_normalization(parameters):
    return {**_service_normalization(parameters),
            "peer_relative_xyz": "(peer-self)/(max-min), clipped [-1,1]",
            "peer_relative_velocity": f"(peer-self)/{parameters['velocity_scale_mps']:g} mps, clipped [-1,1]"}


PRESETS = {
    "raw_links_v1": ObservationPreset(
        "raw_links_v1", "float64", _build_raw_links, _raw_links_space, _raw_links_features,
        {"position": "raw", "sinr_clip_db": None, "capacity": "raw"}),
    "local_links_v1": ObservationPreset(
        "local_links_v1", "float32", _build_local_links_v1, _local_links_space,
        _local_links_features, _link_normalization, normalization_fields=LINK_FIELDS,
        compatibility_fields=("bounds",)),
    "geometry_v1": ObservationPreset(
        "geometry_v1", "float32", _build_geometry_v1, _geometry_space, _geometry_features,
        {"self_xy": "2*(value-min)/(max-min)-1",
         "peer_relative_xy": "(peer-self)/(max-min), clipped [-1,1]"},
        required_facts=("nodes",), compatibility_fields=("bounds",)),
    "service_v1": ObservationPreset(
        "service_v1", "float32", _build_service_v1, _service_space, _service_features,
        _service_normalization, normalization_fields=LINK_FIELDS,
        required_facts=("nodes", "links", "window"), compatibility_fields=("bounds",)),
    "full_facts_v1": ObservationPreset(
        "full_facts_v1", "float32", _build_full_facts_v1, _full_facts_space,
        _full_facts_features, _full_normalization,
        normalization_fields=LINK_FIELDS + ("velocity_scale_mps",),
        required_facts=("nodes", "links", "window"), compatibility_fields=("bounds",)),
}

DEFAULT_PRESET = "raw_links_v1"


def get_preset(name: str, parameters=None) -> ObservationPreset:
    preset = PRESETS.get(name)
    if preset is None:
        raise ValueError(f"Unknown observation_preset {name!r}; valid choices: {sorted(PRESETS)}")
    resolved = Normalization.resolve({} if parameters is None else parameters,
                                     preset.normalization_fields)
    return replace(preset, parameters=resolved)


def canonical_json(payload: dict) -> str:
    """Strict canonical JSON used for every schema hash."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)


def schema_sha256(payload: dict) -> str:
    return canonical_sha256({key: value for key, value in payload.items() if key != "sha256"})


def _jsonable_bound(value: float) -> float | None:
    return None if not math.isfinite(value) else float(value)


def observation_schema(preset_name: str, contract: dict, parameters=None) -> dict:
    """Structural + scenario identity of one preset against one init contract."""
    return get_preset(preset_name, parameters).schema(contract)


def _preset_schema(preset: ObservationPreset, contract: dict) -> dict:
    slots = _num_slots(contract)
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
        "normalization": (preset.normalization(preset.parameters) if callable(preset.normalization)
                          else dict(preset.normalization)),
        "parameters": dict(preset.parameters),
        "required_facts": list(preset.required_facts),
        "compatibility_fields": list(preset.compatibility_fields),
        "bounds": dict(contract["bounds"]),
        "node_ids": _node_ids(contract),
        "slot_node_ids": list(contract["slot_node_ids"]),
    }
    schema["sha256"] = schema_sha256(schema)
    return schema


_STRUCTURAL_FIELDS = ("schema_id", "dtype", "obs_dim", "num_mesh_nodes",
                      "max_controlled_nodes", "feature_names", "contract_id",
                      "dimensions", "action_meanings", "nvec", "normalization",
                      "required_facts", "compatibility_fields", "parameters", "low", "high")
_SCENARIO_FIELDS = ("node_ids", "slot_node_ids")


def check_schema(saved: dict, live: dict) -> list[str]:
    """Raise on structural differences; return warnings for scenario identity."""
    fields = [f for f in _STRUCTURAL_FIELDS if saved.get(f) != live.get(f)]
    semantic_fields = set(saved.get("compatibility_fields", [])) | set(
        live.get("compatibility_fields", []))
    fields.extend(field for field in sorted(semantic_fields)
                  if saved.get(field) != live.get(field))
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
