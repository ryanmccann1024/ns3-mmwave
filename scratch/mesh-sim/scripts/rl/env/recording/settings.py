"""Decision-record configuration, defaults, and validation; no record I/O."""

from dataclasses import dataclass, field

OBS_VECTOR_MODES = ("auto", "always")
PREFERENCE_MODES = ("auto", "off")
DEFAULT_MAX_BYTES = 64 * 1024 * 1024
_FLAGS = {
    "enabled": "--decision-records",
    "obs_vector": "--decision-records-obs-vector",
    "preferences": "--decision-records-preferences",
    "record_every": "--decision-records-every",
    "max_bytes_per_episode": "--decision-records-max-bytes",
}
_DEFAULTS = {
    "enabled": False,
    "obs_vector": "auto",
    "preferences": "auto",
    "record_every": 1,
    "max_bytes_per_episode": DEFAULT_MAX_BYTES,
}


@dataclass(frozen=True)
class DecisionRecordSettings:
    """Validated decision-record settings with the source of every key."""

    enabled: bool = False
    obs_vector: str = "auto"
    preferences: str = "auto"
    record_every: int = 1
    max_bytes_per_episode: int = DEFAULT_MAX_BYTES
    source: dict = field(default_factory=dict)

    def describe(self) -> dict:
        return {
            "enabled": bool(self.enabled),
            "obs_vector": self.obs_vector,
            "preferences": self.preferences,
            "record_every": int(self.record_every),
            "max_bytes_per_episode": int(self.max_bytes_per_episode),
            "source": {key: self.source.get(key, "default") for key in _DEFAULTS},
        }


def _int_setting(key: str, value, minimum: int, source: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{key} must be an integer >= {minimum}, got {value!r} ({source})")
    try:
        number = int(str(value).strip())
    except ValueError as exc:
        raise ValueError(
            f"{key} must be an integer >= {minimum}, got {value!r} ({source})") from exc
    if number < minimum:
        raise ValueError(f"{key} must be an integer >= {minimum}, got {number} ({source})")
    return number


def resolve_decision_records(*, enabled=None, obs_vector=None, preferences=None,
                             record_every=None,
                             max_bytes_per_episode=None) -> DecisionRecordSettings:
    """Validate decision-record settings before any simulator process exists."""
    given = {
        "enabled": enabled,
        "obs_vector": obs_vector,
        "preferences": preferences,
        "record_every": record_every,
        "max_bytes_per_episode": max_bytes_per_episode,
    }
    sources = {key: ("cli" if value is not None else "default")
               for key, value in given.items()}
    values = {key: (value if value is not None else _DEFAULTS[key])
              for key, value in given.items()}

    if not isinstance(values["enabled"], bool):
        raise ValueError(
            f"enabled must be a boolean, got {values['enabled']!r} ({sources['enabled']})")
    if not values["enabled"]:
        dependent = [key for key in _DEFAULTS
                     if key != "enabled" and given[key] is not None]
        if dependent:
            flags = ", ".join(f"{_FLAGS[key]} ({key})" for key in dependent)
            raise ValueError(
                f"{flags} requires {_FLAGS['enabled']} ({sources[dependent[0]]})")

    for key, modes in (("obs_vector", OBS_VECTOR_MODES),
                       ("preferences", PREFERENCE_MODES)):
        values[key] = str(values[key]).strip()
        if values[key] not in modes:
            raise ValueError(
                f"{key} {values[key]!r} is not valid ({sources[key]}); valid choices: "
                f"{list(modes)}")
    values["record_every"] = _int_setting(
        "record_every", values["record_every"], 1, sources["record_every"])
    values["max_bytes_per_episode"] = _int_setting(
        "max_bytes_per_episode", values["max_bytes_per_episode"], 0,
        sources["max_bytes_per_episode"])
    return DecisionRecordSettings(source=sources, **values)
