"""Independent placement score terms, owned parameters, and reproducibility metadata."""

import math
from dataclasses import dataclass, field


@dataclass(frozen=True)
class ScoreComponent:
    value: object
    parameter: str | None = None
    version: int = 1
    unit: str = "m2"
    defaults: dict = field(default_factory=dict)

    def resolve(self, overrides, initial=None):
        if not isinstance(overrides, dict) or set(overrides) - set(self.defaults):
            raise ValueError(f"component parameters must be an object using {tuple(self.defaults)}")
        values = {**self.defaults, **(initial or {}), **overrides}
        for name, value in values.items():
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value < 0
            ):
                raise ValueError(f"component {name} must be finite and >= 0")
        return values


SCORE_COMPONENTS = {
    "coverage": ScoreComponent(
        lambda ctx, facts, p: facts["coverage"] * p["coverage_weight"],
        "coverage_weight",
        defaults={"coverage_weight": 1.0},
    ),
    "separation": ScoreComponent(
        lambda ctx, facts, p: facts["separation"],
        "separation_frac",
        defaults={"separation_frac": 0.4},
    ),
    "movement": ScoreComponent(lambda ctx, facts, p: -facts["movement"]),
    "connectivity": ScoreComponent(
        lambda ctx, facts, p: -ctx.big * facts["disconnected"],
        "disconnected_aoi_factor",
        defaults={"disconnected_aoi_factor": 2.0},
    ),
    "vulnerability": ScoreComponent(
        lambda ctx, facts, p: -ctx.w_vuln * facts["vulnerability"],
        "vulnerability_aoi_factor",
        defaults={"vulnerability_aoi_factor": 0.0},
    ),
}
