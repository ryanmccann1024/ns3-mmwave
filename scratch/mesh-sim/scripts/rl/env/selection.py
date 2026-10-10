"""Resolve policy inputs, rewards, and telemetry: CLI > run.ini > default."""

from dataclasses import dataclass, field

from .config import read_rl_selection
from .observations import DEFAULT_PRESET, PRESETS
from .rewards import RewardComposer

TELEMETRY_MODES = ("none", "steps")
_DEFAULTS = {
    "observation_preset": DEFAULT_PRESET,
    "reward_components": (),
    "reward_weights": (),
    "telemetry": "none",
    "telemetry_every": 1,
}


@dataclass(frozen=True)
class RlSelection:
    """Validated policy selection with the source of every key."""

    observation_preset: str = DEFAULT_PRESET
    reward_components: tuple[str, ...] = ()
    reward_weights: tuple[float, ...] = ()
    telemetry: str = "none"
    telemetry_every: int = 1
    source: dict = field(default_factory=dict)

    def describe(self) -> dict:
        return {
            "observation_preset": self.observation_preset,
            "reward_components": list(self.reward_components),
            "reward_weights": [float(w) for w in self.reward_weights],
            "telemetry": self.telemetry,
            "telemetry_every": int(self.telemetry_every),
            "source": {key: self.source.get(key, "default")
                       for key in _DEFAULTS},
        }


def uses_custom_observation(selection: RlSelection) -> bool:
    """True when a non-default observation preset is selected."""
    return selection.observation_preset != DEFAULT_PRESET


def uses_composed_reward(selection: RlSelection) -> bool:
    """True when Python composes the reward."""
    return bool(selection.reward_components)


def _split_list(key: str, raw: str, source: str) -> list[str]:
    tokens = [token.strip() for token in raw.split(",") if token.strip()]
    if not tokens:
        raise ValueError(
            f"{key} was given as an empty list ({source}); omit it instead of "
            "passing an empty value"
        )
    return tokens


def _resolve_raw(cli: dict, ini: dict) -> tuple[dict, dict]:
    values, sources = {}, {}
    for key in _DEFAULTS:
        if cli.get(key) is not None:
            values[key], sources[key] = cli[key], "cli"
        elif key in ini:
            values[key], sources[key] = ini[key], "run.ini"
        else:
            sources[key] = "default"
    return values, sources


def resolve_selection(run_config: str, *, observation_preset=None,
                      reward_components=None, reward_weights=None, telemetry=None,
                      telemetry_every=None) -> RlSelection:
    """Validate the selection before any simulator process or output directory exists."""
    cli = {
        "observation_preset": observation_preset,
        "reward_components": reward_components,
        "reward_weights": reward_weights,
        "telemetry": telemetry,
        "telemetry_every": telemetry_every,
    }
    ini = read_rl_selection(run_config)
    raw, sources = _resolve_raw(cli, ini)

    preset = _DEFAULTS["observation_preset"]
    if "observation_preset" in raw:
        preset = str(raw["observation_preset"]).strip()
        if preset not in PRESETS:
            raise ValueError(
                f"observation_preset {preset!r} is not registered "
                f"({sources['observation_preset']}); valid choices: {sorted(PRESETS)}"
            )

    components: tuple[str, ...] = ()
    if "reward_components" in raw:
        names = _split_list("reward_components", str(raw["reward_components"]),
                            sources["reward_components"])
        components = tuple(names)

    if "reward_weights" in raw:
        if not components:
            raise ValueError(
                "reward_weights requires reward_components "
                f"({sources['reward_weights']})"
            )
        tokens = _split_list("reward_weights", str(raw["reward_weights"]),
                             sources["reward_weights"])
        try:
            parsed = [float(token) for token in tokens]
        except ValueError as exc:
            raise ValueError(
                f"reward_weights must be floats ({sources['reward_weights']}): {exc}"
            ) from exc
        weights = tuple(parsed)
    else:
        weights = tuple(1.0 for _ in components)

    try:
        RewardComposer(components, weights)
    except ValueError as exc:
        raise ValueError(f"{exc} ({sources['reward_components']}, "
                         f"{sources['reward_weights']})") from exc

    mode = _DEFAULTS["telemetry"]
    if "telemetry" in raw:
        mode = str(raw["telemetry"]).strip()
        if mode not in TELEMETRY_MODES:
            raise ValueError(
                f"telemetry {mode!r} is not valid ({sources['telemetry']}); valid "
                f"choices: {list(TELEMETRY_MODES)}"
            )

    every = _DEFAULTS["telemetry_every"]
    if "telemetry_every" in raw:
        token = str(raw["telemetry_every"]).strip()
        try:
            every = int(token)
        except ValueError as exc:
            raise ValueError(
                f"telemetry_every must be a positive integer, got {token!r} "
                f"({sources['telemetry_every']})"
            ) from exc
        if every < 1:
            raise ValueError(
                f"telemetry_every must be a positive integer, got {every} "
                f"({sources['telemetry_every']})"
            )
        if mode != "steps":
            raise ValueError(
                f"telemetry_every requires telemetry = steps, got {mode!r} "
                f"({sources['telemetry_every']})"
            )

    selection = RlSelection(preset, components, weights, mode, every, dict(sources))
    return selection
