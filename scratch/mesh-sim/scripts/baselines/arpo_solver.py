"""Load the unmodified ARPO planner through a scoped path shim and run one placement."""

import contextlib
import dataclasses
import hashlib
import importlib
import importlib.util
import logging
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import TextIO

from scripts.baselines.adapter import PlanRequest, PlanResult
from scripts.sim_support import find_mesh_root

SOURCE_ENV = "MESH_SIM_ARPO_PATH"
REQUIREMENTS_FILE = "requirements-baselines.txt"
ALLOWLIST = (
    "models.py",
    "core/__init__.py",
    "core/geometry.py",
    "core/rf.py",
    "core/context.py",
    "planners/__init__.py",
    "planners/base.py",
    "planners/geometric.py",
    "planners/optimization.py",
)
_MODULES = ("models", "core.geometry", "core.rf", "core.context", "planners.base",
            "planners.geometric", "planners.optimization")
_ROOT_NAMES = ("models", "core", "planners")
# import name -> distribution named in requirements-baselines.txt
_DEPENDENCIES = (("numpy", "numpy"), ("pydantic", "pydantic"), ("shapely", "shapely"),
                 ("pyproj", "pyproj"), ("yaml", "PyYAML"))
_ROLE_TYPES = {"gateway": "c2", "movable": "controlled", "fixed": "relay"}


class PlannerError(RuntimeError):
    """The planner source, its dependencies, or a planner run failed."""


def default_source_dir() -> Path:
    return find_mesh_root() / "third_party" / "arpo_placement"


def resolve_source_dir(override: str | Path | None = None) -> tuple[Path, str]:
    """Pick the planner directory: explicit override, then $MESH_SIM_ARPO_PATH, then default."""
    if override:
        return Path(override).resolve(), "planner_source"
    env = os.environ.get(SOURCE_ENV)
    if env:
        return Path(env).resolve(), SOURCE_ENV
    default = default_source_dir()
    if not default.is_dir():
        raise PlannerError(f"no planner source: {default} does not exist and {SOURCE_ENV} "
                           "is not set")
    return default, "default"


def source_hashes(source_dir: str | Path, origin: str = "default") -> dict:
    """Per-file SHA-256 of the nine allowlisted files plus one aggregate hash."""
    source_dir = Path(source_dir)
    missing = [name for name in ALLOWLIST if not (source_dir / name).is_file()]
    if missing:
        raise PlannerError(f"planner source {source_dir} (from {origin}) is missing "
                           f"{', '.join(missing)}")
    files = {name: hashlib.sha256((source_dir / name).read_bytes()).hexdigest()
             for name in ALLOWLIST}
    listing = "".join(f"{files[name]}  {name}\n" for name in ALLOWLIST)
    return {"origin": origin, "files": files,
            "aggregate_sha256": hashlib.sha256(listing.encode("utf-8")).hexdigest()}


def check_dependencies() -> None:
    """Fail once, naming every missing package; nothing is installed here."""
    missing = [dist for module, dist in _DEPENDENCIES
               if importlib.util.find_spec(module) is None]
    if missing:
        raise PlannerError(f"planner dependencies not installed: {', '.join(missing)}; "
                           f"install them with '.venv/bin/python -m pip install -r "
                           f"{REQUIREMENTS_FILE}'")


def _loaded_from(name: str) -> Path | None:
    module = sys.modules.get(name)
    if module is None:
        return None
    paths = list(getattr(module, "__path__", []) or [])
    location = paths[0] if paths else getattr(module, "__file__", None)
    return Path(location).resolve() if location else Path("<unknown>")


def load_planner(source_dir: str | Path) -> SimpleNamespace:
    """Import the planner modules from `source_dir`, refusing a same-name module elsewhere."""
    source_dir = Path(source_dir).resolve()
    source_hashes(source_dir)
    check_dependencies()
    for name in _ROOT_NAMES:
        location = _loaded_from(name)
        if location is None:
            continue
        expected = source_dir / ("models.py" if name == "models" else name)
        if location != expected.resolve():
            raise PlannerError(f"module '{name}' is already imported from {location}, not "
                               f"from the planner source {source_dir}; refusing to mix them")
    entry = str(source_dir)
    sys.path.insert(0, entry)
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        importlib.invalidate_caches()
        modules = {name: importlib.import_module(name) for name in _MODULES}
    except ImportError as exc:
        raise PlannerError(f"cannot import the planner from {source_dir}: {exc}") from exc
    finally:
        sys.dont_write_bytecode = previous
        with contextlib.suppress(ValueError):
            sys.path.remove(entry)
    return SimpleNamespace(**{name.rsplit(".", 1)[-1]: module
                              for name, module in modules.items()})


def local_frame(planner: SimpleNamespace, origin_lat: float, origin_lon: float):
    """The adapter's projection: the supplied LocalFrame centred on the mapping origin."""
    return planner.geometry.LocalFrame(center_lat=origin_lat, center_lon=origin_lon)


def run_rf_config(loaded, seed: int | None, max_iterations: int | None):
    """Per-run copy with zero terrain and the requested optimizer seed and iteration cap."""
    optimizer = dataclasses.replace(loaded.optimizer, seed=seed, max_iters=max_iterations)
    return dataclasses.replace(loaded, terrain_elevation_m=0.0, optimizer=optimizer)


def inspect_rf(rf_path: str | Path, source_dir: str | Path) -> dict:
    """Radio specs and movement caps from the RF file, loaded by the supplied RFConfig."""
    planner = load_planner(source_dir)
    try:
        loaded = planner.rf.RFConfig.load(Path(rf_path))
    except Exception as exc:
        raise PlannerError(f"cannot load RF config {rf_path}: {exc}") from exc
    return {
        "radios": {name: dataclasses.asdict(spec) for name, spec in loaded.radios.items()},
        "movement_cost": {name: dataclasses.asdict(cost)
                          for name, cost in loaded.movement_cost.items()},
        "fade_margin_db": loaded.fade_margin_db,
        "range_safety_factor": loaded.range_safety_factor,
        "reference_receiver": dataclasses.asdict(loaded.reference_receiver),
    }


def build_input(planner: SimpleNamespace, frame, request: PlanRequest):
    """ARPOInput for the request: explicit roles, [z, z] altitude bands, projected rectangle."""
    rect = request.rectangle
    corners = [(rect["x_min"], rect["y_min"]), (rect["x_max"], rect["y_min"]),
               (rect["x_max"], rect["y_max"]), (rect["x_min"], rect["y_max"])]
    fence = []
    for x, y in corners:
        lat, lon = frame.to_latlon(x, y)
        fence.append({"lat": float(lat), "lon": float(lon)})
    nodes = []
    for record in request.nodes:
        lat, lon = frame.to_latlon(record.x, record.y)
        nodes.append({
            "node_id": record.id,
            "position": {"lat": float(lat), "lon": float(lon), "elevation_m": record.z,
                         "heading_deg": 0.0},
            "radios": [{"radio_id": f"{record.id}/{index}", "radio_type": radio}
                       for index, radio in enumerate(record.radios)],
            "type": _ROLE_TYPES[record.role],
            "mobility": record.platform if record.role == "movable" else "fixed",
            "altitude_band_m": {"min_agl_m": record.z, "max_agl_m": record.z},
        })
    return planner.models.ARPOInput(nodes=nodes, geofence={"points": fence},
                                    coas=[request.objective])


class _LogHandler(logging.Handler):
    def __init__(self, stream: TextIO):
        super().__init__()
        self.stream = stream

    def emit(self, record: logging.LogRecord) -> None:
        self.stream.write(f"{record.levelname} {record.name}: {record.getMessage()}\n")


def solve(request: PlanRequest, log: TextIO) -> PlanResult:
    """Run the requested planner once and return positions in scenario metres."""
    planner = load_planner(request.source_dir)
    frame = local_frame(planner, request.origin_lat, request.origin_lon)
    try:
        loaded = planner.rf.RFConfig.load(Path(request.rf_config))
        config = run_rf_config(loaded, request.planner_seed, request.max_iterations)
        arpo_input = build_input(planner, frame, request)
        context = planner.context.PlanningContext(arpo_input, config)
        model = (planner.geometric.GeometricModel() if request.method == "geometric"
                 else planner.optimization.OptimizationModel())
    except Exception as exc:
        raise PlannerError(f"planner setup failed: {exc}") from exc
    handler = _LogHandler(log)
    root = logging.getLogger()
    root.addHandler(handler)
    started = time.perf_counter()
    try:
        with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
            result = model.solve(context, request.objective)
            placements = model.to_placements(context, result)
    except Exception as exc:
        raise PlannerError(f"{request.method} planner failed: {exc}") from exc
    finally:
        root.removeHandler(handler)
    wall_s = time.perf_counter() - started
    positions = {}
    for node_id, placement in placements.items():
        x, y = frame.to_xy(placement.lat, placement.lon)
        positions[node_id] = (float(x), float(y), float(placement.elevation_m))
    return PlanResult(positions=positions,
                      predictions=result.diagnostics.model_dump(mode="json"),
                      planner_wall_s=wall_s)
