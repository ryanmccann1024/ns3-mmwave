"""Gymnasium environment wrapping the C++ mesh simulator via stdin/stdout JSON."""

import json
import re
import subprocess
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


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class MeshRlEnv(gymnasium.Env):
    ## Mesh simulator RL environment.

    # Spawns the C++ mesh-sim binary as a subprocess.  Each tick the sim writes
    # an observation+reward JSON line to stdout; this env reads it, returns it to
    # the agent, then writes the agent's action back to the sim's stdin.
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

        # Spaces are set dynamically on first reset once we know N and action_type.
        self.action_space: spaces.Space | None = None
        self.observation_space: spaces.Space | None = None
        self._action_type: str | None = None

        # Boundary info for action masking (read from [rl] on first reset).
        self._x_range: tuple[float, float] | None = None
        self._y_range: tuple[float, float] | None = None
        self._z_range: tuple[float, float] | None = None
        self._ctrl_pos: np.ndarray | None = None           # latest controlled-node position

        # Rendering (deferred to a later day).
        self.window_size = 512
        self.render_mode = render_mode

    # ------------------------------------------------------------------
    # Gymnasium API
    # ------------------------------------------------------------------

    def reset(self, *, seed=None, options=None):
        # A reset(seed=<already-resolved seed>) (SB3's DummyVecEnv does this) is not
        # a new provenance, so only a genuinely different seed relabels the source.
        if seed is not None and int(seed) != self.seed_value:
            self.seed_value = int(seed)
            self.seed_source = "gym"

        self._stop_proc("interrupted")

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

        msg = self._read_message()
        self._action_type = msg.get("action_type", "discrete")

        obs = self._parse_obs(msg)
        self._ctrl_pos = np.asarray(msg["obs"]["controlled_pos"], dtype=float)
        info = {"time_s": msg["time_s"], "tick": msg["tick"]}

        if self._x_range is None:
            self._read_rl_bounds()

        if self.observation_space is None:
            n = len(obs)
            self.observation_space = spaces.Box(
                low=-np.inf, high=np.inf, shape=(n,), dtype=np.float64
            )

        if self.action_space is None:
            if self._action_type == "continuous":
                # 2-D continuous target; 3-D continuous control is unverified (P1).
                self.action_space = spaces.Box(
                    low=-np.inf, high=np.inf, shape=(2,), dtype=np.float64
                )
            else:
                self.action_space = spaces.Discrete(7) # 3D Positioning(-X,+X,-Y,+Y,-Z,+Z,Stay)

        return obs, info

    def step(self, action):
        self._send_action(action)
        msg = self._read_message()

        obs = self._parse_obs(msg)
        self._ctrl_pos = np.asarray(msg["obs"]["controlled_pos"], dtype=float)
        reward = float(msg["reward"])
        terminated = bool(msg["done"])
        truncated = False
        info = {"time_s": msg["time_s"], "tick": msg["tick"]}

        if self._manifest is not None:
            self._manifest["steps"] += 1
            self._manifest["cumulative_reward"] += reward
            self._write_manifest()

        if terminated:
            self._wait_proc()

        return obs, reward, terminated, truncated, info

    #NOTE: Use Claude for Rendering code
    def render(self):
        #TODO: Create modes for rendering environment
        pass

    def _render_frame(self):
        #TODO: Produce Graph that shows nodes current position with link information
        #TODO: Produce Line Graph for nodes radio quality update, trying to match line similar to PID
        pass

    ## @brief Boolean mask of legal discrete actions from the current 3-D position.
    #
    # A move is masked out (False) only when the node is already at the arena
    # boundary in that direction, so the move would be a wasted no-op the sim
    # clamps. "Stay" is always legal.
    #
    # Action index -> direction. MUST match rl-bridge.cc ApplyAction:
    #   0:-X  1:+X  2:-Y  3:+Y  4:-Z  5:+Z  6:Stay
    # (MaskablePPO/ActionMasker look for this exact method name.)
    def action_masks(self) -> np.ndarray:
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
        self._stop_proc("interrupted")

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

    def _finalize_manifest(self, status: str, exit_code: int | None) -> None:
        if self._manifest is None:
            return
        self._manifest["status"] = status
        self._manifest["exit_code"] = exit_code
        self._manifest["ended_at"] = _now_iso()
        self._write_manifest()
        self._manifest = None

    ## @brief Last lines of the episode stderr log, after flushing the handle.
    def _stderr_tail(self) -> str:
        if self._stderr_file is not None:
            try:
                self._stderr_file.flush()
                self._stderr_file.close()
            except Exception:
                pass
            self._stderr_file = None
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
            self._proc.wait()
            rc = self._proc.returncode
            tail = self._stderr_tail()
            self._finalize_manifest("failed", rc)
            raise RuntimeError(
                f"Sim process ended unexpectedly (exit code {rc})\n"
                f"command: {self._cmd}\n"
                f"last {_STDERR_TAIL_LINES} stderr lines:\n{tail}"
            )
        try:
            return json.loads(line)
        except json.JSONDecodeError as exc:
            bad = line.rstrip("\n")[:_BAD_LINE_CHARS]
            tail = self._stderr_tail()
            self._finalize_manifest("failed", self._proc.poll())
            raise RuntimeError(
                f"Invalid JSON from sim on message line {self._msg_count}: {exc}\n"
                f"offending line: {bad!r}\n"
                f"command: {self._cmd}\n"
                f"last {_STDERR_TAIL_LINES} stderr lines:\n{tail}"
            ) from exc

    ## Action Function
    # @brief Produces action message for sim to make changes
    def _send_action(self, action) -> None:
        assert self._proc is not None and self._proc.stdin is not None
        if self._action_type == "continuous":
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

    def _wait_proc(self) -> None:
        """Wait for the sim to exit naturally after sending done=true."""
        if self._proc is None:
            return
        try:
            self._proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self._proc.kill()
            self._proc.wait(timeout=5)
        rc = self._proc.returncode
        self._proc = None
        self._close_stderr()
        self._finalize_manifest("completed" if rc == 0 else "failed", rc)

    def _close_stderr(self) -> None:
        if self._stderr_file is not None:
            try:
                self._stderr_file.close()
            except Exception:
                pass
            self._stderr_file = None

    ## @brief Stop any running sim: close stdin, then terminate, then kill.
    def _stop_proc(self, status: str) -> None:
        if self._proc is not None:
            try:
                if self._proc.stdin is not None and not self._proc.stdin.closed:
                    self._proc.stdin.close()
            except Exception:
                pass
            rc = self._reap(2)
            if rc is None:
                self._proc.terminate()
                rc = self._reap(2)
            if rc is None:
                self._proc.kill()
                rc = self._reap(5)
            self._proc = None
            self._close_stderr()
            self._finalize_manifest(status, rc)
        else:
            self._close_stderr()
            if self._manifest is not None:
                self._finalize_manifest(status, None)

    def _reap(self, timeout: float) -> int | None:
        try:
            return self._proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            return None

    ## @brief Read arena bounds from [rl]; defaults mirror RlConfig in C++.
    def _read_rl_bounds(self) -> None:
        self._x_range, self._y_range, self._z_range = read_rl_bounds(self._run_config)
