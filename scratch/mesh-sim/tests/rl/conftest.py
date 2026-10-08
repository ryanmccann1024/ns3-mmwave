"""Shared setup for generated RL tests under tests/rl/.

Puts the mesh-sim root on sys.path so ``scripts...`` imports work, and re-exports
the shared fake-simulator fixtures (``sim_binary``, ``multi_run_config``) from
``scripts/rl/tests/conftest.py``. Fakes are importable as
``from scripts.rl.tests import fake_sim, fake_slurm``.
"""

import sys
from pathlib import Path

MESH_ROOT = Path(__file__).resolve().parents[2]
if str(MESH_ROOT) not in sys.path:
    sys.path.insert(0, str(MESH_ROOT))

from scripts.rl.tests import conftest as _rl_shared  # noqa: E402

FAKE_SIM = _rl_shared.FAKE_SIM
MULTI_RUN_INI = _rl_shared.MULTI_RUN_INI
NODES_JSON = _rl_shared.NODES_JSON
sim_binary = _rl_shared.sim_binary
multi_run_config = _rl_shared.multi_run_config
