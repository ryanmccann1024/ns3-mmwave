"""Validate native scenario timing before building batch tasks."""

import math

from scripts.rl.policy.operation_inputs import resolve_gates
from scripts.sim_support import parse_ini

# Native tick limits and tolerances in rl-control.cc and config-validator.cc.
_MAX_TICKS = (1 << 32) - 2
_TICK_TOLERANCE = 1e-6
_GATE_TOLERANCE = 1e-8


def _timing(run_config: str) -> tuple[float, float, int, int]:
    ini = parse_ini(run_config)
    scenario, rl = ini.get("scenario", {}), ini.get("rl", {})
    try:
        duration = float(scenario.get("duration_s", "10"))
        tick = float(scenario.get("tick_s", "0.1"))
        interval = float(rl.get("decision_interval_s", "0"))
    except ValueError as exc:
        raise ValueError(f"{run_config}: unreadable timing: {exc}") from exc
    if (
        not (math.isfinite(duration) and math.isfinite(tick))
        or duration <= 0
        or tick <= 0
    ):
        raise ValueError(
            f"{run_config}: duration_s and tick_s must be finite and positive"
        )
    tick_ratio = duration / tick
    if not 1 <= tick_ratio <= _MAX_TICKS:
        raise ValueError(
            f"{run_config}: duration_s must span between 1 and {_MAX_TICKS} ticks"
        )
    nearest = round(tick_ratio)
    ticks = (
        nearest
        if abs(tick_ratio - nearest) <= _TICK_TOLERANCE
        else math.floor(tick_ratio)
    )

    if not math.isfinite(interval) or interval < 0:
        raise ValueError(
            f"{run_config}: decision_interval_s must be finite and nonnegative"
        )
    interval = interval or tick
    decision_ratio = interval / tick
    if decision_ratio > _MAX_TICKS:
        raise ValueError(f"{run_config}: decision_interval_s exceeds duration_s")
    decision_ticks = round(decision_ratio)
    if decision_ticks < 1 or abs(decision_ratio - decision_ticks) > _TICK_TOLERANCE:
        raise ValueError(
            f"{run_config}: decision_interval_s must be an integer multiple of tick_s"
        )
    if decision_ticks > ticks:
        raise ValueError(f"{run_config}: decision_interval_s exceeds duration_s")
    return duration, interval, ticks, decision_ticks


def native_decisions(run_config: str) -> int:
    """Return the bridge's decision count for a valid native cadence."""
    _, _, ticks, decision_ticks = _timing(run_config)
    return -(-ticks // decision_ticks)


def case_gate_s(case: dict | None, seed: int) -> float | None:
    return ((case or {}).get("seeds") or {}).get(str(seed), {}).get("gate_s")


def validate_deployment_gate(run_config: str, case: dict | None, seed: int) -> None:
    """Check a baseline or operation's gate against the INI it will actually use."""
    gate = case_gate_s(case, seed)
    if gate is None:
        return
    try:
        resolve_gates({str(seed): run_config}, case)
    except ValueError as exc:
        raise ValueError(f"{run_config}: {exc}") from exc
    duration, interval, _, _ = _timing(run_config)
    if not 0 <= gate < duration:
        raise ValueError(
            f"{run_config}: seed {seed} gate_s {gate} is outside [0,{duration})"
        )
    ratio = gate / interval
    if abs(ratio - round(ratio)) > _GATE_TOLERANCE:
        raise ValueError(
            f"{run_config}: seed {seed} gate_s {gate} is not on a decision boundary"
        )
