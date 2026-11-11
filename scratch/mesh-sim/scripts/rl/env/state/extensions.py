"""Opt-in Python facts derived from completed decisions; native facts stay intact."""


def make_extensions(preset, composer):
    """Instantiate descriptor-declared state once per episode, never by preset name."""
    from scripts.rl.env.state.coordination import CoordinationState

    factories = {"coordination_v1": CoordinationState}
    names = set(preset.fact_extensions)
    options = {}
    if composer is not None:
        for component in composer.components:
            for name in component.fact_extensions:
                names.add(name)
                for key, value in composer.parameters[component.name].items():
                    if key in options.setdefault(name, {}) and options[name][key] != value:
                        raise ValueError(f"conflicting {name} parameter {key}")
                    options[name][key] = value
    return [factories[name](options.get(name, {})) for name in sorted(names)]
