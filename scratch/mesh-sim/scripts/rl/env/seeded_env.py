"""Per-seed scenario selection: a fresh `MeshRlEnv` for each reset seed.

`configs` maps a seed (string key) to its `run.ini`; `case['seeds'][seed]['gate_s']`
is that seed's controller gate. All seeds share one output root, so episode
numbering and layout match a single standard environment. Reset options (such
as `seed_source`) reach `MeshRlEnv.reset` unchanged and are recorded there.
"""

from scripts.rl.env.config import _get, _read_ini

# Simulator default when neither --band nor [channel] band is given.
_DEFAULT_BAND = "mmwave"


def resolve_band(run_config, band=None):
    """Effective band and its source, in the simulator's order: CLI, run.ini, default."""
    if band:
        return band, "cli"
    ini_band = _get(_read_ini(str(run_config)), "channel", "band")
    if ini_band:
        return ini_band, "run.ini"
    return _DEFAULT_BAND, "default"


class SeededEnv:
    """A fresh environment per seed, preserving standard episode allocation/layout.

    `band` is forwarded as the simulator's `--band` (None leaves the per-seed INI
    in charge); `self.band` / `self.band_source` hold the band resolved for the
    current seed. `decision_records` is forwarded to every per-seed `MeshRlEnv`.
    """

    def __init__(
        self, binary, configs, output, case, *, initial_seed, band=None, decision_records=None
    ):
        # Resolved at construction, not import, so callers and tests can substitute them.
        from scripts.rl.env.mesh_env import MeshRlEnv
        from scripts.rl.env.selection import resolve_selection

        self._type, self._resolve = MeshRlEnv, resolve_selection
        self.binary, self.configs, self.output, self.case = binary, configs, output, case
        self.requested_band, self.decision_records = band, decision_records
        self.inner = None
        self.gate_s = 0
        self._create(initial_seed)

    def _create(self, seed):
        config = self.configs[str(seed)]
        self.gate_s = self.case["seeds"][str(seed)]["gate_s"]
        self.band, self.band_source = resolve_band(config, self.requested_band)
        self.inner = self._type(
            str(self.binary),
            str(config),
            seed=seed,
            output_dir=str(self.output),
            selection=self._resolve(str(config), telemetry="steps"),
            band=self.requested_band,
            decision_records=self.decision_records,
        )

    def reset(self, *, seed, options=None):
        self.inner.close()
        self._create(seed)
        return self.inner.reset(seed=seed, options=options)

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def close(self):
        if self.inner is not None:
            self.inner.close()
