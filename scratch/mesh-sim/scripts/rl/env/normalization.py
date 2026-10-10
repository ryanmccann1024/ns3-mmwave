"""Resolved physical scales shared by observation and reward calculations."""

import math
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Normalization:
    sinr_min_db: float = -20.0
    sinr_max_db: float = 40.0
    sinr_invalid_db: float = -900.0
    capacity_log10_denominator: float = 4.0
    velocity_scale_mps: float = 40.0

    def __post_init__(self):
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
               for v in asdict(self).values()):
            raise ValueError("normalization scales must be finite numbers")
        if not self.sinr_invalid_db < self.sinr_min_db < self.sinr_max_db:
            raise ValueError("SINR scales require invalid < min < max")
        if self.capacity_log10_denominator <= 0 or self.velocity_scale_mps <= 0:
            raise ValueError("capacity and velocity scales must be positive")

    def sinr_valid(self, value):
        return math.isfinite(value) and value > self.sinr_invalid_db

    def sinr_quality(self, value):
        if not self.sinr_valid(value):
            return 0.0
        return min(1.0, max(0.0, (value - self.sinr_min_db) /
                           (self.sinr_max_db - self.sinr_min_db)))

    def capacity(self, value):
        return min(1.0, max(0.0, math.log10(max(1.0 + value, 1.0)) /
                           self.capacity_log10_denominator))

    @classmethod
    def resolve(cls, overrides, fields):
        if not isinstance(overrides, dict):
            raise ValueError("normalization parameters must be an object")
        unknown = set(overrides) - set(fields)
        if unknown:
            raise ValueError(f"unused normalization parameters: {sorted(unknown)}")
        resolved = cls(**overrides)
        return {key: value for key, value in asdict(resolved).items() if key in fields}


SINR_FIELDS = ("sinr_min_db", "sinr_max_db", "sinr_invalid_db")
LINK_FIELDS = SINR_FIELDS + ("capacity_log10_denominator",)
