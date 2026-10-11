"""Pinned Optuna ask/tell adapter and seeded study state."""

import pickle
from pathlib import Path
from scripts.rl.tuning.config import N_STARTUP_TRIALS
from scripts.sim_support import find_mesh_root

PIN_NAME = "requirements-tuning.txt"
_INSTALL_HINT = f"install with: .venv/bin/python -m pip install -r {PIN_NAME}"



def read_tuning_pin(path) -> str:
    """Read the single optuna pin; read_pins is not reused because it enforces DIRECT_DEPS."""
    for line in Path(path).read_text().splitlines():
        name, separator, version = line.split("#", 1)[0].strip().partition("==")
        if name == "optuna" and separator and version:
            return version
    raise ValueError(f"{path} must contain one exact pin: optuna==<version>")


def load_optuna(pin_file=None):
    """Import Optuna lazily and refuse any version other than the pinned one."""
    pin_file = Path(pin_file) if pin_file else find_mesh_root() / PIN_NAME
    pin = read_tuning_pin(pin_file)
    try:
        import optuna
    except ImportError as exc:
        raise ValueError(f"optuna is not installed ({exc}); {_INSTALL_HINT}") from exc
    if optuna.__version__ != pin:
        raise ValueError(f"optuna {optuna.__version__} is installed but {pin_file} "
                         f"pins optuna=={pin}; {_INSTALL_HINT}")
    return optuna


class _OptunaStudy:
    """ask/tell over an in-memory Optuna study; the only Optuna-aware object here."""

    def __init__(self, space: dict, settings: dict, direction="maximize", pin_file=None):
        self._optuna = load_optuna(pin_file)
        self.version = self._optuna.__version__
        self._optuna.logging.set_verbosity(self._optuna.logging.WARNING)
        self._distributions = _distributions(self._optuna, space)
        self._study = self._optuna.create_study(
            direction=direction,
            sampler=self._optuna.samplers.TPESampler(
                seed=settings["seed"], n_startup_trials=settings["n_startup_trials"],
                n_ei_candidates=settings["n_ei_candidates"],
                multivariate=settings["multivariate"]))

    def __getstate__(self):
        state = self.__dict__.copy()
        state.pop("_optuna")
        return state

    def __setstate__(self, state):
        self.__dict__.update(state)
        self._optuna = load_optuna()

    def ask(self) -> tuple:
        trial = self._study.ask(self._distributions)
        return trial.number, dict(trial.params)

    def tell(self, handle, objective: float | None) -> None:
        if objective is None:
            self._study.tell(handle, state=self._optuna.trial.TrialState.FAIL)
        else:
            self._study.tell(handle, objective)


class _CallableStudy:
    """Adapter so a plain `sampler(space, number) -> params` callable can drive trials."""

    def __init__(self, sampler, space: dict):
        self.version = None
        self._sampler = sampler
        self._space = space
        self._number = 0

    def ask(self) -> tuple:
        params = self._sampler(self._space, self._number)
        self._number += 1
        return None, dict(params)

    def tell(self, handle, objective: float | None) -> None:
        return None


def _distributions(optuna, space: dict) -> dict:
    built = {}
    for key, entry in space.items():
        if entry["type"] == "categorical":
            built[key] = optuna.distributions.CategoricalDistribution(entry["choices"])
        elif entry["type"] == "int":
            built[key] = optuna.distributions.IntDistribution(
                low=entry["low"], high=entry["high"], log=entry["log"])
        else:
            built[key] = optuna.distributions.FloatDistribution(
                low=entry["low"], high=entry["high"], log=entry["log"])
    return built


def open_study(spec, sampler=None):
    if sampler is not None:
        return _CallableStudy(sampler, spec["search_space"])
    from scripts.rl.tuning.trainer import get_trainer
    return _OptunaStudy(spec["search_space"], spec["sampler"],
                        direction=get_trainer(spec["trainer"]).direction)


def copy_study(study):
    """Isolate ask/tell mutations until their associated records can commit."""
    return pickle.loads(pickle.dumps(study, protocol=pickle.HIGHEST_PROTOCOL))
