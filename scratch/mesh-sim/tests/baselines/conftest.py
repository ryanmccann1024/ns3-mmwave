"""Shared setup for generated baseline-planner tests under tests/baselines/.

Puts the mesh-sim root on sys.path so ``scripts...`` imports work, and re-exports
the fixtures of ``scripts/baselines/tests/conftest.py`` (``scenario``,
``stub_planner``, ``fake_child``, ``fake_query``). Helpers such as
``write_scenario``, ``fake_query_binary`` and ``install_stub_strategy`` are
importable from ``scripts.baselines.tests.conftest``.
"""

import sys
from pathlib import Path

MESH_ROOT = Path(__file__).resolve().parents[2]
if str(MESH_ROOT) not in sys.path:
    sys.path.insert(0, str(MESH_ROOT))

from scripts.baselines.tests import conftest as _bl_shared  # noqa: E402

scenario = _bl_shared.scenario
stub_planner = _bl_shared.stub_planner
fake_child = _bl_shared.fake_child
fake_query = _bl_shared.fake_query
