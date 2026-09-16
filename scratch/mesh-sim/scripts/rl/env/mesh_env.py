"""Gymnasium environment wrapping the C++ mesh simulator via stdin/stdout JSON."""

import json
import math
import re
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import gymnasium
import numpy as np
from gymnasium import spaces

from scripts.sim_support import find_mesh_root, simulator_env, tail_lines
from .config import read_rl_bounds, read_scenario_seed

_EPISODE_RE = re.compile(r"^episode-(\d{4})$")

_STDERR_TAIL_LINES = 40
_BAD_LINE_CHARS = 200
_MAX_ERROR_CHARS = 1000

# Contract ids this env knows how to interpret (IPC schema §7.1).
_CONTRACTS = {
    "mesh_move_2d_v1": {
        "dimensions": 2,
        "action_meanings": ["west", "east", "south", "north", "hold"],
    },
}
_SLOT_ACTIONS = 5        # west, east, south, north, hold
_HOLD_ACTION = 4
_SLOT_STATE_VALUES = 4   # active, x, y, z
_MAX_SLOTS = 64
_PADDED_SLOT_MASK = [0, 0, 0, 0, 1]

# Bounded-cleanup budget (§7.6): one monotonic deadline covers every stage.
_CLEANUP_BUDGET_S = 10.0
_NATURAL_EXIT_S = 5.0
_ESCALATION_WAIT_S = 2.0
_DRAIN_CHUNK = 64 * 1024

_TIME_TOL = 1e-6


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_finite_number(value) -> bool:
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value))


class MeshRlEnv(gymnasium.Env):
    ## Mesh simulator RL environment.

    # Spawns the C++ mesh-sim binary as a subprocess.  Each decision the sim writes
    # an observation+reward JSON line to stdout; this env reads it, returns it to
    # the agent, then writes the agent's action back to the sim's stdin.
    #
    # Two modes, selected by the simulator's first message: legacy single-node
    # control (Discrete(7)/continuous, no init line) and centralized multi-node
    # control (an init line, then MultiDiscrete([5]*M) with C++-owned masks).
    #
    # Every reset() starts a fresh simulator process in its own episode-NNNN
    # directory under output_dir. The seed is fixed for the whole training run;
    # the episode index never feeds into it.

    metadata = {"render_modes": ["human", "rgb_array"], "render_fps": 4}

    def __init__(self, sim_binary: str, run_config: str, seed: int | None = None,
                 output_dir: str = "", band: str | None = None,
                 render_mode: str | None = None):
        super().__init__()
        if not output_dir:
            raise ValueError("MeshRlEnv requires output_dir (the training output root)")

        self._sim_binary = sim_binary
        self._run_config = run_config
        self._output_dir = Path(output_dir)
        self._band = band

        if seed is not None:
            self.seed_value = int(seed)
            self.seed_source = "cli"
        else:
            ini_seed = read_scenario_seed(run_config)
            if ini_seed is None:
                raise ValueError(
                    "No seed available: pass seed=<int> to MeshRlEnv or set "
                    f"[scenario] seed in {run_config}"
                )
            self.seed_value = ini_seed
            self.seed_source = "run.ini"

        self._proc: subprocess.Popen | None = None
        self._stderr_file = None
        self._stderr_path: Path | None = None
        self._episode_dir: Path | None = None
        self._episode_index: int | None = None
        self._manifest: dict | None = None
        self._cmd: list[str] = []
        self._msg_count = 0
        self._last_tail = "(no stderr captured)"

        # Spaces are set dynamically on first reset once the mode is known.
        self.action_space: spaces.Space | None = None
        self.observation_space: spaces.Space | None = None
        self._action_type: str | None = None

        # Structural signature frozen by the first reset (§7.5).
        self._signature: dict | None = None
        self._control_mode: str | None = None
        self._contract: dict | None = None

        # Centralized per-episode state.
        self._num_slots = 0
        self._num_controlled = 0
        self._obs_dim = 0
        self._mask_dim = 0
        self._tick_s = 0.0
        self._interval_ticks = 1
        self._num_ticks = 0
        self._num_decisions = 0
        self._mask: np.ndarray | None = None
        self._last_tick: int | None = None
        self._last_time: float | None = None
        self._last_decision: int | None = None

        # Boundary info for legacy action masking (read from [rl] on first reset).
        self._x_range: tuple[float, float] | None = None
        self._y_range: tuple[float, float] | None = None
        self._z_range: tuple[float, float] | None = None
        self._ctrl_pos: np.ndarray | None = None           # latest controlled-node position

        # Rendering (deferred to a later day).
        self.window_size = 512
        self.render_mode = render_mode

    ## @brief "legacy" or "centralized" once the first reset has run.
    @property
    def control_mode(self) -> str | None:
        return self._control_mode

    ## @brief The live init object in centralized mode, None in legacy mode.
    @property
    def contract(self) -> dict | None:
        return dict(self._contract) if self._contract is not None else None

    # ------------------------------------------------------------------
    # Gymnasium API
    # ------------------------------------------------------------------

    def reset(self, *, seed=None, options=None):
        # A reset(seed=<already-resolved seed>) (SB3's DummyVecEnv does this) is not
        # a new provenance, so only a genuinely different seed relabels the source.
        if seed is not None and int(seed) != self.seed_value:
            self.seed_value = int(seed)
            self.seed_source = "gym"

        self._stop_proc("interrupted", "reset")

        self._episode_dir, self._episode_index = self._allocate_episode_dir()
        self._cmd = [
            self._sim_binary,
            f"--run-config={self._run_config}",
            "--rl-mode",
            f"--seed={self.seed_value}",
            f"--output-dir={self._episode_dir}",
        ]
        if self._band is not None:
            self._cmd.append(f"--band={self._band}")

        self._manifest = {
            "manifest_version": 1,
            "episode": self._episode_index,
            "seed": self.seed_value,
            "seed_source": self.seed_source,
            "command": list(self._cmd),
            "started_at": _now_iso(),
            "ended_at": None,
            "status": "running",
            "exit_code": None,
            "steps": 0,
            "cumulative_reward": 0.0,
        }
        self._write_manifest()

        self._stderr_path = self._episode_dir / "sim_stderr.log"
        self._stderr_file = open(self._stderr_path, "w")
        self._msg_count = 0
        self._mask = None
        self._last_tick = None
        self._last_time = None
        self._last_decision = None
        try:
            self._proc = subprocess.Popen(
                self._cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=self._stderr_file,
                text=True,
                bufsize=1,  # line-buffered
                env=self._child_env(),
            )
        except OSError as exc:
            self._finalize_manifest("failed", None)
            raise RuntimeError(f"Failed to launch simulator {self._cmd}: {exc}") from exc

        first = self._read_message()
        kind = first.get("type")
        if kind == "init":
            return self._reset_centralized(first)
        if kind == "step":
            return self._reset_legacy(first)
        self._protocol_error(
            f"Unexpected first message type {kind!r}; expected 'init' (centralized) "
            "or 'step' (legacy)"
        )

    def step(self, action):
        self._send_action(action)
        msg = self._read_message()

        if self._control_mode == "centralized":
            obs = self._validate_step(msg)
            reward = float(msg["reward"])
            terminated = bool(msg["done"])
            info = {
                "tick": msg["tick"],
                "time_s": msg["time_s"],
                "decision": msg["decision"],
                "ticks_in_step": msg["ticks_in_step"],
                "revalidated_slots": list(msg["revalidated_slots"]),
            }
        else:
            self._validate_legacy_step(msg)
            obs = self._parse_obs(msg)
            self._ctrl_pos = np.asarray(msg["obs"]["controlled_pos"], dtype=float)
            reward = float(msg["reward"])
            terminated = bool(msg["done"])
            info = {"time_s": msg["time_s"], "tick": msg["tick"]}
        truncated = False

        if self._manifest is not None:
            self._manifest["steps"] += 1
            self._manifest["cumulative_reward"] += reward
            if self._manifest["manifest_version"] == 2:
                self._manifest["decisions"] = msg["decision"]
                self._manifest["last_tick"] = msg["tick"]
            self._write_manifest()

        if terminated:
            self._stop_proc("completed", "done")

        return obs, reward, terminated, truncated, info

    #NOTE: Use Claude for Rendering code
    def render(self):
        #TODO: Create modes for rendering environment
        pass

    def _render_frame(self):
        #TODO: Produce Graph that shows nodes current position with link information
        #TODO: Produce Line Graph for nodes radio quality update, trying to match line similar to PID
        pass

    ## @brief Boolean mask of legal actions.
    #
    # Centralized mode returns the authoritative flat mask C++ sent with the last
    # message; Python never re-derives it. Legacy mode masks a move out only when
    # the node is already at the arena boundary in that direction, so the move
    # would be a wasted no-op the sim clamps. "Stay" is always legal.
    #
    # Legacy action index -> direction. MUST match rl-bridge.cc ApplyAction:
    #   0:-X  1:+X  2:-Y  3:+Y  4:-Z  5:+Z  6:Stay
    # (MaskablePPO/ActionMasker look for this exact method name.)
    def action_masks(self) -> np.ndarray:
        if self._control_mode == "centralized":
            if self._mask is None:
                return np.ones(self._mask_dim, dtype=bool)
            return self._mask.astype(bool)

        n = self.action_space.n if isinstance(self.action_space, spaces.Discrete) else 7
        mask = np.ones(n, dtype=bool)
        if self._ctrl_pos is None or self._x_range is None:
            return mask  # called before first reset -> allow everything

        pos = self._ctrl_pos
        x, y = float(pos[0]), float(pos[1])
        xmin, xmax = self._x_range
        ymin, ymax = self._y_range

        if n > 0: mask[0] = x > xmin       # -X
        if n > 1: mask[1] = x < xmax       # +X
        if n > 2: mask[2] = y > ymin       # -Y
        if n > 3: mask[3] = y < ymax       # +Y
        if n > 5 and self._z_range is not None and pos.shape[0] >= 3:
            z = float(pos[2]); zmin, zmax = self._z_range
            mask[4] = z > zmin             # -Z
            mask[5] = z < zmax             # +Z
        # index 6 (Stay) always True
        return mask

    ## @brief Alias some ActionMasker setups expect.
    def valid_action_mask(self) -> np.ndarray:
        return self.action_masks()

    def close(self):
        self._stop_proc("interrupted", "close")

    # ------------------------------------------------------------------
    # Mode-specific reset
    # ------------------------------------------------------------------

    def _reset_legacy(self, msg: dict):
        self._validate_legacy_step(msg, first=True)
        action_type = msg.get("action_type", "discrete")
        if action_type not in ("discrete", "continuous"):
            self._protocol_error(f"Unknown legacy action_type {action_type!r}")

        obs = self._parse_obs(msg)
        signature = {
            "control_mode": "legacy",
            "action_type": action_type,
            "obs_dim": int(obs.shape[0]),
        }
        self._check_signature(signature)

        self._control_mode = "legacy"
        self._contract = None
        self._action_type = action_type
        self._ctrl_pos = np.asarray(msg["obs"]["controlled_pos"], dtype=float)
        info = {"time_s": msg["time_s"], "tick": msg["tick"]}

        if self._x_range is None:
            self._read_rl_bounds()

        if self.observation_space is None:
            self.observation_space = spaces.Box(
                low=-np.inf, high=np.inf, shape=(obs.shape[0],), dtype=np.float64
            )
        if self.action_space is None:
            if action_type == "continuous":
                # 2-D continuous target; 3-D continuous control is unverified (P1).
                self.action_space = spaces.Box(
                    low=-np.inf, high=np.inf, shape=(2,), dtype=np.float64
                )
            else:
                self.action_space = spaces.Discrete(7) # 3D Positioning(-X,+X,-Y,+Y,-Z,+Z,Stay)

        return obs, info

    def _reset_centralized(self, init: dict):
        self._validate_init(init)
        slots = int(init["max_controlled_nodes"])

        signature = {
            "control_mode": "centralized",
            "contract": init["contract"],
            "dimensions": init["dimensions"],
            "action_meanings": tuple(init["action_meanings"]),
            "num_mesh_nodes": init["num_mesh_nodes"],
            "max_controlled_nodes": slots,
            "obs_dim": init["obs_dim"],
            "mask_dim": init["mask_dim"],
            "nvec": (_SLOT_ACTIONS,) * slots,
            # Frozen for the lifetime of this environment (one scenario per env).
            "slot_node_ids": tuple(init["slot_node_ids"]),
            "slot_speed_mps": tuple(init["slot_speed_mps"]),
            "tick_s": init["tick_s"],
            "decision_interval_s": init["decision_interval_s"],
            "decision_interval_ticks": init["decision_interval_ticks"],
            "num_ticks": init["num_ticks"],
            "num_decisions": init["num_decisions"],
            "reward_type": init["reward_type"],
            "reward_window": init["reward_window"],
            "wall_policy": init["wall_policy"],
        }
        self._check_signature(signature)

        self._control_mode = "centralized"
        self._contract = dict(init)
        self._action_type = "discrete"
        self._num_slots = slots
        self._num_controlled = int(init["num_controlled"])
        self._obs_dim = int(init["obs_dim"])
        self._mask_dim = int(init["mask_dim"])
        self._tick_s = float(init["tick_s"])
        self._interval_ticks = int(init["decision_interval_ticks"])
        self._num_ticks = int(init["num_ticks"])
        self._num_decisions = int(init["num_decisions"])

        self.observation_space = spaces.Box(
            low=-np.inf, high=np.inf, shape=(self._obs_dim,), dtype=np.float64
        )
        self.action_space = spaces.MultiDiscrete([_SLOT_ACTIONS] * slots)

        if self._manifest is not None:
            self._manifest["manifest_version"] = 2
            self._manifest["control_mode"] = "centralized"
            self._manifest["contract"] = dict(init)
            self._manifest["decisions"] = 0
            self._manifest["last_tick"] = None
            self._manifest["stop_reason"] = None
            self._write_manifest()

        msg = self._read_message()
        obs = self._validate_step(msg, first=True)
        info = {
            "tick": msg["tick"],
            "time_s": msg["time_s"],
            "decision": msg["decision"],
            "ticks_in_step": msg["ticks_in_step"],
            "revalidated_slots": list(msg["revalidated_slots"]),
        }
        return obs, info

    # ------------------------------------------------------------------
    # Message validation (§7.5)
    # ------------------------------------------------------------------

    def _validate_init(self, init: dict) -> None:
        contract = init.get("contract")
        spec = _CONTRACTS.get(contract) if isinstance(contract, str) else None
        if spec is None:
            self._protocol_error(
                f"Unknown init contract {contract!r}; supported: {sorted(_CONTRACTS)}"
            )
        if init.get("dimensions") != spec["dimensions"]:
            self._protocol_error(
                f"init dimensions {init.get('dimensions')!r} != "
                f"{spec['dimensions']} for contract {contract}"
            )
        if init.get("action_meanings") != spec["action_meanings"]:
            self._protocol_error(
                f"init action_meanings {init.get('action_meanings')!r} != "
                f"{spec['action_meanings']} for contract {contract}"
            )

        for field in ("max_controlled_nodes", "num_controlled", "num_mesh_nodes",
                      "obs_dim", "mask_dim", "decision_interval_ticks",
                      "num_ticks", "num_decisions"):
            if not _is_int(init.get(field)):
                self._protocol_error(
                    f"init {field} must be an integer, got {init.get(field)!r}"
                )
        for field in ("tick_s", "decision_interval_s"):
            value = init.get(field)
            if not _is_finite_number(value) or value <= 0:
                self._protocol_error(
                    f"init {field} must be finite and > 0, got {value!r}"
                )
        for field in ("reward_type", "reward_window", "wall_policy"):
            if not isinstance(init.get(field), str) or not init[field]:
                self._protocol_error(
                    f"init {field} must be a non-empty string, got {init.get(field)!r}"
                )

        slots = init["max_controlled_nodes"]
        count = init["num_controlled"]
        nodes = init["num_mesh_nodes"]
        if not 1 <= count <= slots <= _MAX_SLOTS:
            self._protocol_error(
                f"init requires 1 <= num_controlled ({count}) <= max_controlled_nodes "
                f"({slots}) <= {_MAX_SLOTS}"
            )
        if nodes < 2:
            self._protocol_error(f"init num_mesh_nodes must be >= 2, got {nodes}")
        for field in ("decision_interval_ticks", "num_ticks", "num_decisions"):
            if init[field] < 1:
                self._protocol_error(f"init {field} must be >= 1, got {init[field]}")

        expected_obs = slots * (_SLOT_STATE_VALUES + 2 * (nodes - 1))
        if init["obs_dim"] != expected_obs:
            self._protocol_error(
                f"init obs_dim {init['obs_dim']} != max_controlled_nodes*(4+2*(N-1)) "
                f"= {expected_obs}"
            )
        if init["mask_dim"] != _SLOT_ACTIONS * slots:
            self._protocol_error(
                f"init mask_dim {init['mask_dim']} != {_SLOT_ACTIONS}*"
                f"max_controlled_nodes = {_SLOT_ACTIONS * slots}"
            )
        ticks, k = init["num_ticks"], init["decision_interval_ticks"]
        if k > ticks:
            self._protocol_error(
                f"init decision_interval_ticks {k} exceeds num_ticks {ticks}"
            )
        expected_decisions = -(-ticks // k)
        if init["num_decisions"] != expected_decisions:
            self._protocol_error(
                f"init num_decisions {init['num_decisions']} != "
                f"ceil(num_ticks/decision_interval_ticks) = {expected_decisions}"
            )

        ids = init.get("slot_node_ids")
        speeds = init.get("slot_speed_mps")
        for field, value in (("slot_node_ids", ids), ("slot_speed_mps", speeds)):
            if not isinstance(value, list) or len(value) != slots:
                self._protocol_error(
                    f"init {field} must be a list of {slots} entries, got {value!r}"
                )
        active_ids = ids[:count]
        if not all(isinstance(i, str) and i for i in active_ids):
            self._protocol_error(
                f"init slot_node_ids has a non-string active entry: {active_ids!r}"
            )
        if len(set(active_ids)) != count:
            self._protocol_error(
                f"init slot_node_ids has duplicate active entries: {active_ids!r}"
            )
        if any(i is not None for i in ids[count:]):
            self._protocol_error(
                f"init slot_node_ids padding must be null, got {ids[count:]!r}"
            )
        if not all(_is_finite_number(s) and s > 0 for s in speeds[:count]):
            self._protocol_error(
                f"init slot_speed_mps active entries must be finite and > 0, "
                f"got {speeds[:count]!r}"
            )
        if any(s is not None for s in speeds[count:]):
            self._protocol_error(
                f"init slot_speed_mps padding must be null, got {speeds[count:]!r}"
            )

    def _validate_step(self, msg: dict, first: bool = False) -> np.ndarray:
        if msg.get("type") != "step":
            self._protocol_error(
                f"Expected a 'step' message, got type {msg.get('type')!r}"
            )

        obs = msg.get("obs")
        if not isinstance(obs, list) or len(obs) != self._obs_dim:
            length = len(obs) if isinstance(obs, list) else None
            self._protocol_error(f"obs length {length} != obs_dim {self._obs_dim}")
        bad = next((i for i, v in enumerate(obs) if not _is_finite_number(v)), None)
        if bad is not None:
            self._protocol_error(f"obs[{bad}] is not a finite number: {obs[bad]!r}")

        mask = msg.get("mask")
        if not isinstance(mask, list) or len(mask) != self._mask_dim:
            length = len(mask) if isinstance(mask, list) else None
            self._protocol_error(f"mask length {length} != mask_dim {self._mask_dim}")
        bad = next((i for i, v in enumerate(mask) if not _is_int(v) or v not in (0, 1)),
                   None)
        if bad is not None:
            self._protocol_error(f"mask[{bad}] is not 0 or 1: {mask[bad]!r}")

        if not _is_finite_number(msg.get("reward")):
            self._protocol_error(f"reward is not a finite number: {msg.get('reward')!r}")
        if not isinstance(msg.get("done"), bool):
            self._protocol_error(f"done must be a boolean, got {msg.get('done')!r}")

        slot_obs = self._obs_dim // self._num_slots if self._num_slots else 0
        for slot in range(self._num_controlled, self._num_slots):
            window = obs[slot * slot_obs:(slot + 1) * slot_obs]
            if any(v != 0 for v in window):
                self._protocol_error(
                    f"padded slot {slot} observation must be all zero, got {window!r}"
                )
        for slot in range(self._num_slots):
            window = mask[slot * _SLOT_ACTIONS:(slot + 1) * _SLOT_ACTIONS]
            if window[_HOLD_ACTION] != 1:
                self._protocol_error(f"hold is masked out in slot {slot}: {window!r}")
            if slot >= self._num_controlled and window != _PADDED_SLOT_MASK:
                self._protocol_error(
                    f"padded slot {slot} mask must be {_PADDED_SLOT_MASK}, got {window!r}"
                )

        for field in ("tick", "decision", "ticks_in_step"):
            if not _is_int(msg.get(field)) or msg[field] < 0:
                self._protocol_error(
                    f"{field} must be a non-negative integer, got {msg.get(field)!r}"
                )
        if not _is_finite_number(msg.get("time_s")):
            self._protocol_error(f"time_s is not a finite number: {msg.get('time_s')!r}")
        revalidated = msg.get("revalidated_slots")
        if not isinstance(revalidated, list) or not all(
                _is_int(s) and 0 <= s < self._num_slots for s in revalidated):
            self._protocol_error(
                f"revalidated_slots must be slot indices in [0,{self._num_slots}), "
                f"got {revalidated!r}"
            )

        tick, decision, window_ticks = msg["tick"], msg["decision"], msg["ticks_in_step"]
        if first:
            if tick != 0 or decision != 0 or window_ticks != 1:
                self._protocol_error(
                    f"reset message must be tick 0, decision 0, ticks_in_step 1; got "
                    f"tick {tick}, decision {decision}, ticks_in_step {window_ticks}"
                )
        else:
            if tick <= self._last_tick:
                self._protocol_error(
                    f"tick {tick} does not advance past {self._last_tick}"
                )
            if decision != self._last_decision + 1:
                self._protocol_error(
                    f"decision {decision} does not follow {self._last_decision}"
                )
            if msg["time_s"] <= self._last_time:
                self._protocol_error(
                    f"time_s {msg['time_s']} does not advance past {self._last_time}"
                )
            expected = min(self._interval_ticks, self._num_ticks - self._last_tick)
            if window_ticks != expected or tick - self._last_tick != window_ticks:
                self._protocol_error(
                    f"ticks_in_step {window_ticks} is not the expected window "
                    f"{expected} for ticks ({self._last_tick},{tick}]"
                )
        if decision > self._num_decisions:
            self._protocol_error(
                f"decision {decision} exceeds num_decisions {self._num_decisions}"
            )
        if tick > self._num_ticks:
            self._protocol_error(f"tick {tick} exceeds num_ticks {self._num_ticks}")
        if abs(msg["time_s"] - tick * self._tick_s) > _TIME_TOL:
            self._protocol_error(
                f"time_s {msg['time_s']} != tick*tick_s = {tick * self._tick_s}"
            )
        if msg["done"] != (tick == self._num_ticks):
            self._protocol_error(
                f"done {msg['done']} disagrees with tick {tick} of {self._num_ticks}"
            )

        self._last_tick, self._last_decision = tick, decision
        self._last_time = msg["time_s"]
        self._mask = np.asarray(mask, dtype=np.int8)
        return np.asarray(obs, dtype=np.float64)

    def _validate_legacy_step(self, msg: dict, first: bool = False) -> None:
        if msg.get("type") != "step":
            self._protocol_error(
                f"Expected a 'step' message, got type {msg.get('type')!r}"
            )
        obs = msg.get("obs")
        if not isinstance(obs, dict):
            self._protocol_error(f"legacy obs must be an object, got {obs!r}")
        pos = obs.get("controlled_pos")
        if not isinstance(pos, list) or not all(_is_finite_number(v) for v in pos):
            self._protocol_error(f"legacy controlled_pos is not finite: {pos!r}")
        sinrs, caps = obs.get("link_sinrs"), obs.get("link_capacities")
        if not isinstance(sinrs, list) or not isinstance(caps, list):
            self._protocol_error("legacy obs needs link_sinrs and link_capacities lists")
        if len(sinrs) != len(caps):
            self._protocol_error(
                f"legacy link_sinrs ({len(sinrs)}) and link_capacities ({len(caps)}) "
                "differ in length"
            )
        if not all(_is_finite_number(v) for v in (*sinrs, *caps)):
            self._protocol_error("legacy link values are not all finite numbers")
        if not _is_finite_number(msg.get("reward")):
            self._protocol_error(f"reward is not a finite number: {msg.get('reward')!r}")
        if not isinstance(msg.get("done"), bool):
            self._protocol_error(f"done must be a boolean, got {msg.get('done')!r}")
        if not _is_int(msg.get("tick")) or not _is_finite_number(msg.get("time_s")):
            self._protocol_error(
                f"legacy tick/time_s invalid: {msg.get('tick')!r}, {msg.get('time_s')!r}"
            )
        if not first and self._last_tick is not None and msg["tick"] <= self._last_tick:
            self._protocol_error(
                f"tick {msg['tick']} does not advance past {self._last_tick}"
            )
        if not first and self.observation_space is not None:
            width = len(pos) + 2 * len(sinrs)
            if width != self.observation_space.shape[0]:
                self._protocol_error(
                    f"legacy observation width {width} != "
                    f"{self.observation_space.shape[0]}"
                )
        self._last_tick = msg["tick"]

    ## @brief Reject any structural drift before spaces are replaced under the policy.
    def _check_signature(self, signature: dict) -> None:
        if self._signature is None:
            self._signature = signature
            return
        if signature == self._signature:
            return
        keys = sorted(set(self._signature) | set(signature))
        diffs = "; ".join(
            f"{key}: first={self._signature.get(key)!r} now={signature.get(key)!r}"
            for key in keys if self._signature.get(key) != signature.get(key)
        )
        self._protocol_error(f"Simulator contract changed between resets ({diffs})")

    ## @brief Stop the process, record the failure, and raise with full diagnostics.
    def _protocol_error(self, detail: str):
        message = f"{detail} on message line {self._msg_count}"
        if self._manifest is not None:
            self._manifest["error"] = message[:_MAX_ERROR_CHARS]
        rc = self._stop_proc("failed", "error")
        raise RuntimeError(
            f"{message}\n"
            f"command: {self._cmd}\n"
            f"exit code: {rc}\n"
            f"last {_STDERR_TAIL_LINES} stderr lines:\n{self._last_tail}"
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    ## @brief Next unused episode-NNNN directory under the output root.
    def _allocate_episode_dir(self) -> tuple[Path, int]:
        self._output_dir.mkdir(parents=True, exist_ok=True)
        while True:
            used = [int(m.group(1)) for m in
                    (_EPISODE_RE.match(p.name) for p in self._output_dir.iterdir())
                    if m]
            index = max(used) + 1 if used else 0
            path = self._output_dir / f"episode-{index:04d}"
            try:
                path.mkdir(exist_ok=False)
            except FileExistsError:
                continue
            return path, index

    ## @brief Child environment with the ns-3 shared libraries on the loader path.
    def _child_env(self) -> dict:
        return simulator_env(find_mesh_root(__file__))

    def _write_manifest(self) -> None:
        if self._manifest is None or self._episode_dir is None:
            return
        with open(self._episode_dir / "rl_episode.json", "w") as fh:
            json.dump(self._manifest, fh, indent=2)
            fh.write("\n")

    def _finalize_manifest(self, status: str, exit_code: int | None,
                           stop_reason: str | None = None,
                           escalation: str | None = None) -> None:
        if self._manifest is None:
            return
        self._manifest["status"] = status
        self._manifest["exit_code"] = exit_code
        self._manifest["ended_at"] = _now_iso()
        if self._manifest["manifest_version"] == 2:
            self._manifest["stop_reason"] = stop_reason
            self._manifest["escalation"] = escalation
        self._write_manifest()
        self._manifest = None

    ## @brief Last lines of the episode stderr log, after flushing the handle.
    def _stderr_tail(self) -> str:
        self._close_stderr()
        if self._stderr_path is None or not self._stderr_path.is_file():
            return "(no stderr captured)"
        return tail_lines(self._stderr_path, _STDERR_TAIL_LINES) or "(stderr empty)"

    ## Observation Function
    # @brief Grabs output message from sim
    def _read_message(self) -> dict:
        assert self._proc is not None and self._proc.stdout is not None
        line = self._proc.stdout.readline()
        self._msg_count += 1
        if not line:
            if self._manifest is not None:
                self._manifest["error"] = "sim process ended unexpectedly"
            rc = self._stop_proc("failed", "error")
            raise RuntimeError(
                f"Sim process ended unexpectedly (exit code {rc})\n"
                f"command: {self._cmd}\n"
                f"last {_STDERR_TAIL_LINES} stderr lines:\n{self._last_tail}"
            )
        try:
            return json.loads(line)
        except json.JSONDecodeError as exc:
            bad = line.rstrip("\n")[:_BAD_LINE_CHARS]
            message = f"Invalid JSON from sim on message line {self._msg_count}: {exc}"
            if self._manifest is not None:
                self._manifest["error"] = message[:_MAX_ERROR_CHARS]
            rc = self._stop_proc("failed", "error")
            raise RuntimeError(
                f"{message}\n"
                f"offending line: {bad!r}\n"
                f"command: {self._cmd}\n"
                f"exit code: {rc}\n"
                f"last {_STDERR_TAIL_LINES} stderr lines:\n{self._last_tail}"
            ) from exc

    ## @brief Normalize an agent action into exactly num_slots integers in [0,4].
    def _joint_action(self, action) -> list[int]:
        array = np.asarray(action)
        if array.ndim == 0:
            raise ValueError(
                f"centralized mode needs {self._num_slots} slot actions, got a scalar"
            )
        values = array.reshape(-1).tolist()
        if len(values) != self._num_slots:
            raise ValueError(
                f"centralized action must have {self._num_slots} entries, "
                f"got {len(values)}"
            )
        joint = []
        for slot, value in enumerate(values):
            if isinstance(value, bool) or int(value) != value:
                raise ValueError(f"slot {slot} action must be an integer, got {value!r}")
            index = int(value)
            if not 0 <= index < _SLOT_ACTIONS:
                raise ValueError(
                    f"slot {slot} action {index} is outside [0,{_SLOT_ACTIONS - 1}]"
                )
            joint.append(index)
        return joint

    ## Action Function
    # @brief Produces action message for sim to make changes
    def _send_action(self, action) -> None:
        assert self._proc is not None and self._proc.stdin is not None
        if self._control_mode == "centralized":
            action_val = self._joint_action(action)
        elif self._action_type == "continuous":
            action_val = [float(action[0]), float(action[1])]
        else:
            action_val = int(action)
        msg = json.dumps({"action": action_val})
        try:
            self._proc.stdin.write(msg + "\n")
            self._proc.stdin.flush()
        except (BrokenPipeError, ValueError, OSError):
            pass  # the sim already died; _read_message reports it with diagnostics

    ## Message Parser
    # @brief Parses through output message from env and collects radio quality value
    @staticmethod
    def _parse_obs(msg: dict) -> np.ndarray:
        """Flatten the observation dict into [x, y, z, sinr_0, cap_0, sinr_1, cap_1, ...]."""
        obs_dict = msg["obs"]
        parts = list(obs_dict["controlled_pos"])
        sinrs = obs_dict["link_sinrs"]
        caps = obs_dict["link_capacities"]
        for s, c in zip(sinrs, caps):
            parts.append(s)
            parts.append(c)
        return np.array(parts, dtype=np.float64)

    def _close_stderr(self) -> None:
        if self._stderr_file is not None:
            try:
                self._stderr_file.flush()
                self._stderr_file.close()
            except Exception:
                pass
            self._stderr_file = None

    ## @brief Drain and discard stdout in bounded chunks so the child never blocks.
    @staticmethod
    def _start_drain(proc: subprocess.Popen) -> threading.Thread:
        stream = proc.stdout

        def drain() -> None:
            if stream is None:
                return
            try:
                while stream.read(_DRAIN_CHUNK):
                    pass
            except (ValueError, OSError):
                pass

        thread = threading.Thread(target=drain, name="mesh-sim-drain", daemon=True)
        thread.start()
        return thread

    @staticmethod
    def _close_stream(stream) -> None:
        if stream is None or stream.closed:
            return
        try:
            stream.close()
        except Exception:
            pass

    ## @brief Stop any running sim within one bounded deadline (§7.6).
    #
    # Hands stdout to a single short-lived drain thread, closes stdin, then
    # escalates natural exit -> terminate -> kill and reaps the child.
    def _stop_proc(self, status: str, stop_reason: str | None = None) -> int | None:
        proc, self._proc = self._proc, None
        if proc is None:
            if status == "failed":
                self._last_tail = self._stderr_tail()
            self._close_stderr()
            if self._manifest is not None:
                self._finalize_manifest(status, None, stop_reason, None)
            return None

        deadline = time.monotonic() + _CLEANUP_BUDGET_S
        reader = self._start_drain(proc)
        self._close_stream(proc.stdin)

        escalation = "exited"
        rc = self._reap(proc, min(_NATURAL_EXIT_S, self._remaining(deadline)))
        if rc is None:
            proc.terminate()
            escalation = "terminated"
            rc = self._reap(proc, min(_ESCALATION_WAIT_S, self._remaining(deadline)))
        if rc is None:
            proc.kill()
            escalation = "killed"
            rc = self._reap(proc, min(_ESCALATION_WAIT_S, self._remaining(deadline)))

        reader.join(timeout=self._remaining(deadline))
        self._close_stream(proc.stdout)
        if status == "failed" or stop_reason == "done":
            self._last_tail = self._stderr_tail()
        self._close_stderr()

        if stop_reason == "done":
            status = "completed" if rc == 0 else "failed"
        self._finalize_manifest(status, rc, stop_reason, escalation)
        return rc

    @staticmethod
    def _remaining(deadline: float) -> float:
        return max(0.0, deadline - time.monotonic())

    @staticmethod
    def _reap(proc: subprocess.Popen, timeout: float) -> int | None:
        try:
            return proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            return None

    ## @brief Read arena bounds from [rl]; defaults mirror RlConfig in C++.
    def _read_rl_bounds(self) -> None:
        self._x_range, self._y_range, self._z_range = read_rl_bounds(self._run_config)
